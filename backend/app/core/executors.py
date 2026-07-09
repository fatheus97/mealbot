"""A dedicated, bounded thread pool for untrusted-input parsing.

Two request paths hand attacker-controlled bytes to blocking, CPU-bound C/native
code and offload it off the event loop:

  * ``receipt_scanner._extract_pdf_text`` — pypdf on an uploaded PDF (a crafted
    or decompression-bomb file can burn CPU for the full parse timeout).
  * ``recipe_retriever`` embedding — fastembed/ONNX on a user search query or a
    meal-entry text.

Both currently reach the thread pool via ``asyncio.to_thread``, which always
dispatches to the event loop's *default* ``ThreadPoolExecutor`` — the very same
pool that offloads bcrypt password hashing on login/register (see
``app.core.security`` + ``app.api.auth``). A burst of oversized PDFs or embedding
requests can occupy every worker in that shared pool, so a bcrypt login task
submitted afterwards has to *queue* behind untrusted parse work. That turns a
parse-cost problem into a login-availability problem.

This module owns a separate, small, bounded pool so parse load is capped and
isolated: excess parse work queues here instead of on the default pool, and
auth stays responsive. Per-operation *duration* is still bounded by the
``asyncio.wait_for`` wrappers at each call site — the pool bounds *concurrency*.

Note this isolates pool-queue starvation, not raw CPU contention (all threads
still share cores under the GIL for the native sections). Capping the worker
count also caps how much CPU untrusted parsing can claim at once, which is the
lever that matters on a small box.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-global singleton. Created by start_parse_executor() at app startup, or
# lazily on first use (tests exercise parsing without running the app lifespan).
_parse_executor: ThreadPoolExecutor | None = None

# Latch flipped by shutdown_parse_executor(). Once the app lifespan has torn the
# pool down, a late request racing the shutdown window must NOT lazily resurrect
# a fresh pool — nothing would ever join it, leaking non-daemon worker threads.
# start_parse_executor() clears it, so an explicit (re)start re-enables dispatch.
_shutting_down: bool = False

# Guards the (_parse_executor, _shutting_down) state transition against the
# shutdown/dispatch race. The lifespan offloads shutdown to a *separate thread*
# (so the blocking join can't stall the loop), which means shutdown_parse_executor
# and run_in_parse_executor can now run truly concurrently. Without this lock a
# request racing the drain window could read a non-None pool, skip the latch, and
# submit to an already-.shutdown() pool → a raw stdlib "cannot schedule new
# futures after shutdown" bubbling out of a parse call site. The lock is held
# only for the microsecond state-check + submit (never across the await or the
# blocking join), so it never serializes actual parse work.
_lock = threading.Lock()


def start_parse_executor() -> None:
    """Create the bounded parse pool. Idempotent — safe to call once at startup.

    Clears the shutdown latch. Lock-free by design: it's called either at
    lifespan startup (before any request is served, so no concurrency) or from
    inside run_in_parse_executor's locked section (taking _lock here would
    self-deadlock — threading.Lock is non-reentrant).
    """
    global _parse_executor, _shutting_down
    _shutting_down = False
    if _parse_executor is None:
        _parse_executor = ThreadPoolExecutor(
            max_workers=settings.parse_executor_workers,
            thread_name_prefix="parse",
        )
        logger.info(
            "Parse executor started (max_workers=%d)",
            settings.parse_executor_workers,
        )


def shutdown_parse_executor() -> None:
    """Tear the pool down at app shutdown: wait for RUNNING parses to finish,
    cancel still-QUEUED ones, and latch 'shut down' so run_in_parse_executor
    won't resurrect it. Idempotent.

    cancel_futures=True is deliberate and load-bearing: it bounds shutdown
    duration to the in-flight (running) items only — at most
    parse_executor_workers of them, ~one parse-timeout cycle — instead of the
    full queue depth. The queue is NOT bounded by worker count: any number of
    concurrent requests (across users) can have submitted before the latch flips,
    so draining the whole queue could stall shutdown for (queued / workers) ×
    timeout and blow past the container SIGTERM grace into a SIGKILL. A parse that
    was legitimately submitted but is still queued is cancelled; run_in_parse_
    executor turns that into a clean RuntimeError for the awaiting request rather
    than a bare asyncio.CancelledError.

    Blocking (joins running parse threads via shutdown(wait=True)); the lifespan
    offloads this to a thread so it can't stall the event loop / graceful drain.
    docker-compose.prod.yml sets stop_grace_period > the parse timeouts so those
    running items finish within the container's grace window. Under the lock we
    latch + detach the pool reference *before* the join, so a concurrent dispatch
    either submitted first (covered by wait / the cancel path) or sees None and
    raises the clean latch error — it can never submit to a pool mid-.shutdown().
    """
    global _parse_executor, _shutting_down
    with _lock:
        _shutting_down = True
        executor, _parse_executor = _parse_executor, None
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)
        logger.info("Parse executor shut down")


async def run_in_parse_executor[T](func: Callable[..., T], *args: object) -> T:
    """Run a blocking parse call on the dedicated bounded pool.

    Drop-in for ``asyncio.to_thread(func, *args)`` that targets the isolated
    parse executor instead of the loop's shared default executor. Lazily starts
    the pool if the app lifespan hasn't (keeps direct-call unit tests working) —
    but after an explicit shutdown it raises rather than resurrecting an
    un-owned pool that would leak threads on process exit.
    """
    loop = asyncio.get_running_loop()
    # Submit under the lock so the pool can't be shut down between the latch
    # check and the submit; await the returned future *outside* the lock.
    with _lock:
        if _parse_executor is None:
            if _shutting_down:
                raise RuntimeError(
                    "Parse executor has been shut down; refusing to resurrect it."
                )
            start_parse_executor()
        assert _parse_executor is not None  # start_parse_executor guarantees it
        future = loop.run_in_executor(_parse_executor, func, *args)
    try:
        return await future
    except asyncio.CancelledError:
        # Tell "shutdown cancelled our still-queued parse out from under us" apart
        # from "our own task was told to cancel". Both converge on the same
        # observable state — CancelledError raised, future.cancelled() True — so
        # neither of those alone is a valid discriminator:
        #   * shutdown path: executor.shutdown(cancel_futures=True) cancels the
        #     concurrent future directly; the chain propagates into our asyncio
        #     future WITHOUT ever calling task.cancel(), so cancelling() stays 0.
        #   * timeout / disconnect: the caller's wait_for (or the client drop)
        #     calls task.cancel(), which cancels the same future AND bumps
        #     cancelling() to >= 1.
        # Only the shutdown path becomes a clean, catchable RuntimeError (the
        # bare CancelledError is a BaseException the parse call sites don't catch
        # and an ASGI server conflates with request cancellation). A genuine
        # wait_for timeout MUST re-raise CancelledError so wait_for can convert it
        # to the documented TimeoutError (504) — even mid-shutdown, when
        # _shutting_down is True for the whole drain window.
        task = asyncio.current_task()
        if (
            _shutting_down
            and future.cancelled()
            and (task is None or task.cancelling() == 0)
        ):
            raise RuntimeError(
                "Parse executor is shutting down; parse aborted."
            ) from None
        raise
