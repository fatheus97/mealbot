"""Tests for the dedicated bounded parse executor.

The point of app.core.executors is isolation: untrusted-input parsing (PDF +
embedding) must run on a *separate*, *bounded* pool so it can't starve the
default thread pool that offloads bcrypt logins. These tests pin both
properties — the dedicated-thread routing and the concurrency cap — plus the
lazy-start / idempotent-lifecycle contract the app relies on.
"""
import asyncio
import threading
import time

import pytest

from app.core import executors
from app.core.config import settings
from app.core.executors import (
    run_in_parse_executor,
    shutdown_parse_executor,
    start_parse_executor,
)


def _add(a: int, b: int) -> int:
    return a + b


@pytest.fixture
def fresh_pool():
    """Each test starts from a pristine 'never started' pool and resets to it
    after, so worker-count monkeypatching takes effect and no threads leak
    between tests.

    Crucially, clear the _shutting_down latch on both ends: shutdown sets it, and
    leaving it set would make the next lazy caller (endpoint embed tests, which
    never run the app lifespan) raise instead of transparently starting."""
    shutdown_parse_executor()
    executors._shutting_down = False
    yield
    shutdown_parse_executor()
    executors._shutting_down = False


class TestParseExecutor:
    async def test_runs_func_and_returns_result(self, fresh_pool):
        assert await run_in_parse_executor(lambda: 6 * 7) == 42

    async def test_passes_positional_args(self, fresh_pool):
        # receipt_scanner relies on positional passthrough: run_in_parse_executor(
        # _extract_pdf_text, pdf_bytes).
        assert await run_in_parse_executor(_add, 2, 3) == 5

    async def test_runs_on_dedicated_pool_not_the_default(self, fresh_pool):
        """The core isolation guarantee: work lands on OUR pool (threads named
        'parse…'), never the event loop's shared default executor."""
        name = await run_in_parse_executor(
            lambda: threading.current_thread().name
        )
        assert name.startswith("parse")

    async def test_lazy_starts_without_explicit_start(self, fresh_pool):
        # fresh_pool tore the pool down; a bare call must transparently recreate
        # it (unit tests exercise parsing without running the app lifespan).
        assert executors._parse_executor is None
        await run_in_parse_executor(lambda: None)
        assert executors._parse_executor is not None

    async def test_concurrency_is_bounded_to_worker_count(
        self, fresh_pool, monkeypatch: pytest.MonkeyPatch
    ):
        """With 2 workers and 6 queued tasks, at most 2 run at once. If the pool
        were unbounded (or defaulted to asyncio.to_thread's large default pool),
        the peak would climb toward 6. peak == 2 proves BOTH real parallelism
        and the cap."""
        monkeypatch.setattr(settings, "parse_executor_workers", 2)
        start_parse_executor()

        lock = threading.Lock()
        state = {"current": 0, "peak": 0}

        def work() -> None:
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            time.sleep(0.1)  # hold the worker so overlap is observable
            with lock:
                state["current"] -= 1

        await asyncio.gather(
            *(run_in_parse_executor(work) for _ in range(6))
        )
        assert state["peak"] == 2

    async def test_refuses_to_resurrect_after_shutdown(self, fresh_pool):
        """A request racing the shutdown window must not silently spin up a new,
        un-owned pool (leaked threads). After an explicit shutdown, dispatch
        raises; only an explicit restart re-enables it."""
        start_parse_executor()
        shutdown_parse_executor()
        assert executors._parse_executor is None
        with pytest.raises(RuntimeError, match="shut down"):
            await run_in_parse_executor(lambda: 1)
        # An explicit (re)start clears the latch and re-enables dispatch.
        start_parse_executor()
        assert await run_in_parse_executor(lambda: 1) == 1

    async def test_inflight_task_drains_on_concurrent_shutdown(self, fresh_pool):
        """A parse submitted before shutdown finishes cleanly even though
        shutdown runs concurrently on another thread (as the lifespan does).
        The lock makes the submit atomic vs. the state swap, and
        shutdown(wait=True) drains the in-flight task — no raw stdlib
        'cannot schedule new futures' escaping a parse call site."""
        start_parse_executor()
        started = threading.Event()
        release = threading.Event()

        def slow() -> str:
            started.set()
            release.wait(timeout=2)
            return "done"

        task = asyncio.create_task(run_in_parse_executor(slow))
        # Ensure the parse is actually running on a pool thread before shutdown.
        assert await asyncio.to_thread(started.wait, 2) is True
        # Shutdown concurrently on a thread; shutdown(wait=True) blocks on `slow`.
        shutdown_task = asyncio.create_task(
            asyncio.to_thread(shutdown_parse_executor)
        )
        release.set()
        assert await task == "done"
        await shutdown_task
        assert executors._parse_executor is None

    async def test_start_is_idempotent(self, fresh_pool):
        start_parse_executor()
        first = executors._parse_executor
        start_parse_executor()
        assert executors._parse_executor is first  # not replaced

    async def test_shutdown_is_idempotent(self, fresh_pool):
        start_parse_executor()
        shutdown_parse_executor()
        assert executors._parse_executor is None
        shutdown_parse_executor()  # second call must not raise
        assert executors._parse_executor is None
