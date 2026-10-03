"""A background asyncio loop that the Qt thread hands work to."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Awaitable, Callable, Optional, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")


class AsyncRunner:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="fizzy-async", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(
        self,
        coro: Awaitable[T],
        on_error: Optional[Callable[[BaseException], None]] = None,
    ) -> concurrent.futures.Future:
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def _done(f: concurrent.futures.Future) -> None:
            if f.cancelled():
                return
            exc = f.exception()
            if exc is not None:
                log.error("background task failed", exc_info=exc)
                if on_error is not None:
                    on_error(exc)

        fut.add_done_callback(_done)
        return fut

    def run(self, coro: Awaitable[T], timeout: float = 10.0) -> T:
        """Block the calling thread until coro finishes. Never call from the loop."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2)
