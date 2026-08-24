"""Reusable size-bounded LRU with per-key singleflight construction."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from concurrent.futures import Future
from threading import Condition, RLock, get_ident
from typing import Generic, TypeVar

_Value = TypeVar("_Value")


class BoundedSingleflightLru(Generic[_Value]):
    """Bound retained values and distinct in-flight factories process-wide.

    Each distinct build reserves the maximum entry size before its factory runs.
    Same-key callers share one Future. A small, explicit working reservation may
    additionally describe bounded transient allocations controlled by the build
    concurrency limit; it is intentionally separate from retained cache bytes.
    """

    def __init__(
        self,
        *,
        max_entries: int,
        max_total_size: int,
        max_entry_size: int,
        max_concurrent_builds: int,
        size_of: Callable[[_Value], int],
        oversized: Callable[[int, int], BaseException],
        working_size_per_build: int = 0,
        max_total_working_size: int | None = None,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if max_total_size <= 0:
            raise ValueError("max_total_size must be positive")
        if not 0 < max_entry_size <= max_total_size:
            raise ValueError("max_entry_size must fit the cache budget")
        if max_concurrent_builds <= 0:
            raise ValueError("max_concurrent_builds must be positive")
        if working_size_per_build < 0:
            raise ValueError("working_size_per_build must not be negative")
        resolved_max_working_size = (
            max_concurrent_builds * working_size_per_build
            if max_total_working_size is None
            else max_total_working_size
        )
        if resolved_max_working_size < working_size_per_build:
            raise ValueError("one build must fit the working-size budget")
        self._max_entries = max_entries
        self._max_total_size = max_total_size
        self._max_entry_size = max_entry_size
        self._max_concurrent_builds = max_concurrent_builds
        self._size_of = size_of
        self._oversized = oversized
        self._working_size_per_build = working_size_per_build
        self._max_total_working_size = resolved_max_working_size
        self._entries: OrderedDict[Hashable, _Value] = OrderedDict()
        self._entry_sizes: dict[Hashable, int] = {}
        self._total_size = 0
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._inflight: dict[Hashable, Future[_Value]] = {}
        self._inflight_owners: dict[Hashable, int] = {}
        self._inflight_reserved_size = 0
        self._inflight_working_reserved_size = 0
        self._active_builds = 0

    @property
    def max_entry_size(self) -> int:
        return self._max_entry_size

    @property
    def total_size(self) -> int:
        with self._lock:
            return self._total_size

    @property
    def inflight_reserved_size(self) -> int:
        with self._lock:
            return self._inflight_reserved_size

    @property
    def inflight_working_reserved_size(self) -> int:
        with self._lock:
            return self._inflight_working_reserved_size

    @property
    def max_inflight_working_size(self) -> int:
        return self._max_total_working_size

    @property
    def active_builds(self) -> int:
        with self._lock:
            return self._active_builds

    def get(self, *, key: Hashable) -> _Value | None:
        with self._lock:
            if key not in self._entries:
                return None
            self._entries.move_to_end(key)
            return self._entries[key]

    def get_or_create(
        self,
        *,
        key: Hashable,
        value_factory: Callable[[], _Value],
    ) -> _Value:
        future, owner = self._claim(key)
        if not owner:
            return future.result()

        try:
            created = value_factory()
            actual_size = self._checked_size(created)
            if actual_size > self._max_entry_size:
                raise self._oversized(actual_size, self._max_entry_size)
            return self._publish(
                key=key,
                future=future,
                created=created,
                actual_size=actual_size,
            )
        except BaseException as exc:
            self._fail(key=key, future=future, exception=exc)
            raise

    def _claim(self, key: Hashable) -> tuple[Future[_Value], bool]:
        with self._condition:
            while True:
                if get_ident() in self._inflight_owners.values():
                    raise RuntimeError(
                        "bounded cache factory recursively requested the cache"
                    )
                if key in self._entries:
                    future: Future[_Value] = Future()
                    future.set_result(self._entries[key])
                    self._entries.move_to_end(key)
                    return future, False
                existing = self._inflight.get(key)
                if existing is not None:
                    return existing, False
                self._evict_for_reservation()
                if self._can_reserve():
                    future = Future()
                    self._inflight[key] = future
                    self._inflight_owners[key] = get_ident()
                    self._active_builds += 1
                    self._inflight_reserved_size += self._max_entry_size
                    self._inflight_working_reserved_size += self._working_size_per_build
                    return future, True
                self._condition.wait()

    def _can_reserve(self) -> bool:
        return (
            self._active_builds < self._max_concurrent_builds
            and self._inflight_working_reserved_size + self._working_size_per_build
            <= self._max_total_working_size
            and self._total_size + self._inflight_reserved_size + self._max_entry_size
            <= self._max_total_size
        )

    def _publish(
        self,
        *,
        key: Hashable,
        future: Future[_Value],
        created: _Value,
        actual_size: int,
    ) -> _Value:
        with self._condition:
            self._release_reservation(key=key, future=future)
            self._entries[key] = created
            self._entry_sizes[key] = actual_size
            self._total_size += actual_size
            self._evict_to_limits()
            future.set_result(created)
            return created

    def _fail(
        self,
        *,
        key: Hashable,
        future: Future[_Value],
        exception: BaseException,
    ) -> None:
        with self._condition:
            if self._inflight.get(key) is future:
                self._release_reservation(key=key, future=future)
            if not future.done():
                future.set_exception(exception)

    def _evict_for_reservation(self) -> None:
        while self._entries and (
            self._total_size + self._inflight_reserved_size + self._max_entry_size
            > self._max_total_size
        ):
            evicted_key, _ = self._entries.popitem(last=False)
            self._total_size -= self._entry_sizes.pop(evicted_key)

    def _evict_to_limits(self) -> None:
        while self._entries and (
            len(self._entries) > self._max_entries
            or self._total_size + self._inflight_reserved_size > self._max_total_size
        ):
            evicted_key, _ = self._entries.popitem(last=False)
            self._total_size -= self._entry_sizes.pop(evicted_key)

    def _checked_size(self, value: _Value) -> int:
        size = self._size_of(value)
        if size < 0:
            raise ValueError("size_of returned a negative size")
        return size

    def _release_reservation(
        self,
        *,
        key: Hashable,
        future: Future[_Value],
    ) -> None:
        if self._inflight.get(key) is not future:
            raise RuntimeError("bounded cache build ownership was lost")
        del self._inflight[key]
        del self._inflight_owners[key]
        self._active_builds -= 1
        self._inflight_reserved_size -= self._max_entry_size
        self._inflight_working_reserved_size -= self._working_size_per_build
        self._condition.notify_all()


__all__ = ["BoundedSingleflightLru"]
