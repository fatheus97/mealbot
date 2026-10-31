"""Request ids and JSON log lines (app.core.request_context, app.core.log_config)."""

import asyncio
import json
import logging
import re
import sys
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.executors import run_in_parse_executor
from app.core.log_config import JsonFormatter, configure_logging, request_id_var
from app.core.request_context import RequestContextMiddleware, unhandled_error_response

HEX32 = re.compile(r"^[0-9a-f]{32}$")
REQUEST_LOGGER = "app.core.request_context"


def _request_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == REQUEST_LOGGER]


def _mini_app() -> FastAPI:
    """The middleware around routes that log, raise and wait, as main.py wires it."""
    app = FastAPI()
    log = logging.getLogger("tests.mini")

    @app.get("/log")
    async def log_something() -> dict[str, str]:
        log.info("inside the request")
        return {"ok": "yes"}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    @app.get("/slow/{name}")
    async def slow(name: str) -> dict[str, str]:
        await asyncio.sleep(0.05)  # both requests are in flight at once here
        log.info("slow %s", name)
        return {"name": name}

    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(Exception, unhandled_error_response)
    return app


@pytest.fixture
async def mini() -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=_mini_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestTheRealApp:
    async def test_every_response_carries_a_fresh_id(self, unauthed_client: AsyncClient) -> None:
        first = await unauthed_client.get("/health")
        second = await unauthed_client.get("/health")
        ids = [first.headers["x-request-id"], second.headers["x-request-id"]]
        assert all(HEX32.match(i) for i in ids)
        assert ids[0] != ids[1]

    async def test_a_response_from_an_outer_layer_carries_one_too(self, unauthed_client: AsyncClient) -> None:
        # CORS answers a preflight itself, without reaching any route. The id
        # header proves the middleware sits outside it.
        resp = await unauthed_client.options(
            "/api/config",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert HEX32.match(resp.headers["x-request-id"])

    async def test_one_line_per_request_without_the_query_string(
        self, unauthed_client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        resp = await unauthed_client.get("/api/config?q=someone%40example.com")
        [line] = _request_lines(caplog)
        assert line.getMessage().startswith("GET /api/config 200 ")
        assert line.__dict__["path"] == "/api/config"
        assert line.__dict__["status"] == 200
        assert line.__dict__["request_id"] == resp.headers["x-request-id"]
        assert "example.com" not in JsonFormatter().format(line)


class TestTheMiddleware:
    async def test_lines_logged_during_a_request_carry_its_id(
        self, mini: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        resp = await mini.get("/log")
        [inside] = [r for r in caplog.records if r.getMessage() == "inside the request"]
        assert inside.__dict__["request_id"] == resp.headers["x-request-id"]

    async def test_concurrent_requests_keep_their_own_ids(
        self, mini: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        a, b = await asyncio.gather(mini.get("/slow/a"), mini.get("/slow/b"))
        by_name = {r.args[0]: r.__dict__["request_id"] for r in caplog.records if r.name == "tests.mini"}  # type: ignore[index]
        assert by_name == {"a": a.headers["x-request-id"], "b": b.headers["x-request-id"]}
        assert a.headers["x-request-id"] != b.headers["x-request-id"]

    async def test_an_unhandled_error_still_returns_the_id_and_logs_a_500(
        self, mini: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        resp = await mini.get("/boom")
        assert resp.status_code == 500
        assert resp.text == "Internal Server Error"
        [line] = _request_lines(caplog)
        assert line.__dict__["status"] == 500
        assert line.__dict__["request_id"] == resp.headers["x-request-id"]


    async def test_the_id_outlives_the_middleware_for_the_servers_traceback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # uvicorn logs "Exception in ASGI application" after the middleware has
        # unwound, in the request's own task. ASGITransport runs the app in this
        # task, so what this task sees afterwards is what uvicorn's line gets.
        caplog.set_level(logging.INFO)
        transport = ASGITransport(app=_mini_app(), raise_app_exceptions=True)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with pytest.raises(RuntimeError, match="kaboom"):
                await client.get("/boom")
        [line] = _request_lines(caplog)
        assert request_id_var.get() == line.__dict__["request_id"]


def test_main_wires_the_500_handler() -> None:
    from app.main import app

    assert app.exception_handlers[Exception] is unhandled_error_response


class TestJsonFormatter:
    def _record(self, msg: str = "hello %s", args: tuple[object, ...] = ("world",), **extra: object) -> logging.LogRecord:
        record = logging.getLogger("tests.fmt").makeRecord("tests.fmt", logging.WARNING, __file__, 1, msg, args, None, extra=extra)
        return record

    def test_one_json_object_with_the_core_fields(self) -> None:
        token = request_id_var.set("abc123")
        try:
            out = json.loads(JsonFormatter().format(self._record()))
        finally:
            request_id_var.reset(token)
        assert out["msg"] == "hello world"
        assert out["level"] == "WARNING"
        assert out["logger"] == "tests.fmt"
        assert out["request_id"] == "abc123"
        assert out["ts"].endswith("+00:00")

    def test_no_request_id_key_outside_a_request(self) -> None:
        assert "request_id" not in json.loads(JsonFormatter().format(self._record()))

    def test_extra_fields_become_keys_and_never_break_the_line(self) -> None:
        out = json.loads(JsonFormatter().format(self._record(status=201, obj=object())))
        assert out["status"] == 201
        assert out["obj"].startswith("<object object")

    def test_uvicorn_colour_codes_stay_out(self) -> None:
        out = json.loads(JsonFormatter().format(self._record(color_message="\x1b[36mhi\x1b[0m")))
        assert "color_message" not in out

    def test_an_exception_keeps_its_traceback_on_one_line(self) -> None:
        try:
            raise ValueError("bad")
        except ValueError:
            record = logging.getLogger("tests.fmt").makeRecord(
                "tests.fmt", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
            )
        text = JsonFormatter().format(record)
        assert "\n" not in text
        assert "ValueError: bad" in json.loads(text)["exc"]


class TestConfiguration:
    def test_idempotent_and_routes_uvicorn_through_it(self) -> None:
        configure_logging()
        configure_logging()
        root = logging.getLogger()
        assert sum(isinstance(h.formatter, JsonFormatter) for h in root.handlers) == 1
        assert logging.getLogger("uvicorn").propagate is True
        assert logging.getLogger("uvicorn.error").handlers == []
        # Replaced by the request line, which has the id and no query string.
        assert logging.getLogger("uvicorn.access").disabled is True

    def test_extra_request_id_is_refused_loudly(self) -> None:
        # The factory already set it; logging refuses to overwrite.
        with pytest.raises(KeyError):
            logging.getLogger("tests.cfg").info("x", extra={"request_id": "forged"})


async def test_the_parse_executor_keeps_the_request_id() -> None:
    token = request_id_var.set("from-the-request")
    try:
        seen = await run_in_parse_executor(request_id_var.get)
    finally:
        request_id_var.reset(token)
    assert seen == "from-the-request"
