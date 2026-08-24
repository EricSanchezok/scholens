from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from app.tooling.bounded_singleflight_lru import BoundedSingleflightLru


def _cache() -> BoundedSingleflightLru[str]:
    return BoundedSingleflightLru(
        max_entries=2,
        max_total_size=10,
        max_entry_size=5,
        max_concurrent_builds=2,
        size_of=len,
        oversized=lambda actual, maximum: ValueError(f"{actual}>{maximum}"),
    )


def test_shared_lru_evicts_the_least_recently_used_value() -> None:
    cache = _cache()
    cache.get_or_create(key="first", value_factory=lambda: "1111")
    cache.get_or_create(key="second", value_factory=lambda: "2222")
    assert cache.get(key="first") == "1111"

    cache.get_or_create(key="third", value_factory=lambda: "3333")

    assert cache.get(key="first") == "1111"
    assert cache.get(key="second") is None
    assert cache.get(key="third") == "3333"
    assert cache.total_size == 8


def test_shared_singleflight_fans_one_factory_error_out_to_all_waiters() -> None:
    cache = _cache()
    started = Event()
    release = Event()
    calls_lock = Lock()
    factory_calls = 0

    def fail() -> str:
        nonlocal factory_calls
        with calls_lock:
            factory_calls += 1
        started.set()
        assert release.wait(timeout=5)
        raise LookupError("producer failed")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(cache.get_or_create, key="same", value_factory=fail)
            for _index in range(8)
        ]
        assert started.wait(timeout=5)
        release.set()
        for future in futures:
            with pytest.raises(LookupError, match="producer failed"):
                future.result(timeout=5)

    assert factory_calls == 1
    assert cache.active_builds == 0
    assert cache.inflight_reserved_size == 0


def test_shared_cache_treats_none_as_a_present_value() -> None:
    calls = 0
    cache = BoundedSingleflightLru[str | None](
        max_entries=1,
        max_total_size=1,
        max_entry_size=1,
        max_concurrent_builds=1,
        size_of=lambda _value: 0,
        oversized=lambda actual, maximum: ValueError(f"{actual}>{maximum}"),
    )

    def factory() -> None:
        nonlocal calls
        calls += 1

    assert cache.get_or_create(key="none", value_factory=factory) is None
    assert cache.get_or_create(key="none", value_factory=factory) is None
    assert calls == 1


def test_shared_cache_rejects_negative_sizes_without_corrupting_accounting() -> None:
    cache = BoundedSingleflightLru[str](
        max_entries=1,
        max_total_size=1,
        max_entry_size=1,
        max_concurrent_builds=1,
        size_of=lambda _value: -1,
        oversized=lambda actual, maximum: ValueError(f"{actual}>{maximum}"),
    )

    with pytest.raises(ValueError, match="negative"):
        cache.get_or_create(key="invalid", value_factory=lambda: "value")

    assert cache.total_size == 0
    assert cache.active_builds == 0
    assert cache.inflight_reserved_size == 0


def test_shared_cache_rejects_recursive_same_key_factory_calls() -> None:
    cache = _cache()

    def recursive_factory() -> str:
        return cache.get_or_create(key="recursive", value_factory=lambda: "nested")

    with pytest.raises(RuntimeError, match="recursively"):
        cache.get_or_create(key="recursive", value_factory=recursive_factory)

    assert cache.active_builds == 0
    assert cache.inflight_reserved_size == 0


def test_shared_cache_rejects_recursive_cross_key_factory_calls() -> None:
    cache = BoundedSingleflightLru[str](
        max_entries=2,
        max_total_size=10,
        max_entry_size=5,
        max_concurrent_builds=1,
        size_of=len,
        oversized=lambda actual, maximum: ValueError(f"{actual}>{maximum}"),
    )

    def recursive_factory() -> str:
        return cache.get_or_create(key="nested", value_factory=lambda: "nested")

    with pytest.raises(RuntimeError, match="recursively"):
        cache.get_or_create(key="outer", value_factory=recursive_factory)

    assert cache.active_builds == 0
    assert cache.inflight_reserved_size == 0


def test_shared_cache_breaks_two_thread_cross_key_cycles() -> None:
    cache = _cache()
    first_started = Event()
    second_started = Event()

    def build_first() -> str:
        first_started.set()
        assert second_started.wait(timeout=5)
        return cache.get_or_create(key="second", value_factory=lambda: "second")

    def build_second() -> str:
        second_started.set()
        assert first_started.wait(timeout=5)
        return cache.get_or_create(key="first", value_factory=lambda: "first")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(
                cache.get_or_create,
                key="first",
                value_factory=build_first,
            ),
            executor.submit(
                cache.get_or_create,
                key="second",
                value_factory=build_second,
            ),
        )
        for future in futures:
            with pytest.raises(RuntimeError, match="recursively"):
                future.result(timeout=5)

    assert cache.active_builds == 0
    assert cache.inflight_reserved_size == 0
