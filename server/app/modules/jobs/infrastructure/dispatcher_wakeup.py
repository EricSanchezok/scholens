"""Process-local wake signal for the transactional outbox dispatcher."""

from __future__ import annotations

import asyncio


class JobDispatcherWakeup:
    """Wake an idle dispatcher while retaining its polling fallback."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def notify(self) -> None:
        self._event.set()

    async def wait(self, stop: asyncio.Event, *, timeout: float) -> None:
        if self._event.is_set():
            self._event.clear()
            return

        stop_waiter = asyncio.create_task(stop.wait())
        wake_waiter = asyncio.create_task(self._event.wait())
        try:
            done, _pending = await asyncio.wait(
                (stop_waiter, wake_waiter),
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if wake_waiter in done:
                self._event.clear()
        finally:
            for waiter in (stop_waiter, wake_waiter):
                if not waiter.done():
                    waiter.cancel()
            await asyncio.gather(stop_waiter, wake_waiter, return_exceptions=True)


__all__ = ["JobDispatcherWakeup"]
