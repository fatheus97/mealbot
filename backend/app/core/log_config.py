"""Structured logging: one JSON object per line, each tagged with its request.

Every record gets a ``request_id`` attribute, taken from ``request_id_var`` at
the moment the record is created. ``app.core.request_context`` sets that var
once per HTTP request, so every line a request causes (its handlers, the
services they call, background tasks after the response, the parse executor's
threads) can be found with one grep, including lines from concurrent requests
that would otherwise interleave beyond untangling. Outside a request (startup,
the lifespan, scripts) it is ``None``.

The id is stamped by a record factory rather than a handler filter, so every
handler sees it, pytest's ``caplog`` included. A consequence: passing
``extra={"request_id": ...}`` to a log call raises ``KeyError``, because the
record already has the attribute.

Stdlib only. Fields passed through ``extra=`` become top-level JSON keys.
"""

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord carries; anything else on a record came from
# `extra=` and is emitted as its own JSON key.
_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "request_id",
    # uvicorn's extra: its message again, wrapped in terminal colour codes.
    "color_message",
}

_installed = False


class JsonFormatter(logging.Formatter):
    """Render a record as one line of JSON."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = record.__dict__.get("request_id")
        if request_id is not None:
            entry["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _RECORD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        if record.stack_info:
            entry["stack"] = record.stack_info
        # default=str: a stray non-serialisable `extra` must never turn a log
        # call into an exception.
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging() -> None:
    """Send every log line, uvicorn's included, to stdout as JSON. Idempotent."""
    global _installed
    if not _installed:
        base_factory = logging.getLogRecordFactory()

        def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = base_factory(*args, **kwargs)
            record.__dict__["request_id"] = request_id_var.get()
            return record

        logging.setLogRecordFactory(factory)
        _installed = True

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for old in [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]:
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # uvicorn configures its loggers with their own text handlers before it
    # imports the app. Route them through the root handler instead.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # Its access log is replaced by the one request line request_context
    # writes: that one carries the request id, and no query string (an admin
    # user search puts e-mail addresses there, and the privacy policy promises
    # the logs never hold sign-in or reset links).
    logging.getLogger("uvicorn.access").disabled = True
