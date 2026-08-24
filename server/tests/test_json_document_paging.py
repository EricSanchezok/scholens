from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from threading import Event, Lock

import pytest

from app.tooling.json_document_paging import (
    JSON_DOCUMENT_BUILD_WORKING_SIZE_FACTOR,
    JsonDocumentPager,
    JsonDocumentPagerCache,
    JsonDocumentTooLargeError,
)


def test_json_document_pages_are_lossless_utf8_and_canonical() -> None:
    value = {"emoji": "🔬" * 20, "multilingual": "论文 café", "z": [1, True]}
    pager = JsonDocumentPager(value)

    chunks: list[str] = []
    offset = 0
    while offset < pager.total_utf8_bytes:
        page = pager.page(start_utf8_byte=offset, max_utf8_bytes=17)
        assert len(page.content.encode("utf-8")) <= 17
        assert page.start_utf8_byte == offset
        assert page.end_utf8_byte > offset
        chunks.append(page.content)
        offset = page.end_utf8_byte

    reconstructed = "".join(chunks)
    assert json.loads(reconstructed) == value
    assert hashlib.sha256(reconstructed.encode()).hexdigest() == pager.content_sha256


def test_json_document_page_rejects_invalid_or_split_offsets() -> None:
    pager = JsonDocumentPager({"value": "界"})
    encoded = '{"value":"界"}'.encode()
    split_offset = encoded.index("界".encode()) + 1

    with pytest.raises(ValueError, match="splits"):
        pager.page(start_utf8_byte=split_offset, max_utf8_bytes=8)
    with pytest.raises(ValueError, match="outside"):
        pager.page(start_utf8_byte=pager.total_utf8_bytes + 1, max_utf8_bytes=8)
    with pytest.raises(ValueError, match="code point"):
        pager.page(start_utf8_byte=0, max_utf8_bytes=3)


def test_json_document_empty_terminal_page_is_well_defined() -> None:
    pager = JsonDocumentPager({})
    page = pager.page(
        start_utf8_byte=pager.total_utf8_bytes,
        max_utf8_bytes=16,
    )

    assert page.content == ""
    assert page.complete is True


def test_revision_cache_serializes_a_multi_page_document_once() -> None:
    cache = JsonDocumentPagerCache(
        max_entries=2,
        max_total_utf8_bytes=2_000_000,
        max_entry_utf8_bytes=1_000_000,
    )
    value = {"abstract": '\x00\\"界🙂' * 20_000}
    factory_calls = 0

    def value_factory() -> object:
        nonlocal factory_calls
        factory_calls += 1
        return value

    chunks: list[str] = []
    offset = 0
    for _ in range(1_000):
        pager = cache.get_or_create(
            key=(7, "paper", "revision-1"), value_factory=value_factory
        )
        page = pager.page(start_utf8_byte=offset, max_utf8_bytes=1_024)
        chunks.append(page.content)
        offset = page.end_utf8_byte
        if page.complete:
            break
    else:  # pragma: no cover - guards the deterministic complexity assertion
        pytest.fail("cached document did not terminate")

    assert json.loads("".join(chunks)) == value
    assert factory_calls == 1


def test_revision_cache_rejects_an_oversized_document_instead_of_reencoding() -> None:
    cache = JsonDocumentPagerCache(
        max_entries=2,
        max_total_utf8_bytes=128,
        max_entry_utf8_bytes=64,
    )
    factory_calls = 0

    def value_factory() -> object:
        nonlocal factory_calls
        factory_calls += 1
        return {"value": "x" * 128}

    with pytest.raises(JsonDocumentTooLargeError) as raised:
        cache.get_or_create(key="oversized", value_factory=value_factory)

    assert raised.value.maximum_utf8_bytes == 64
    assert raised.value.actual_utf8_bytes > 64
    assert factory_calls == 1


def test_revision_cache_singleflights_concurrent_reads_for_the_same_key() -> None:
    cache = JsonDocumentPagerCache(
        max_entries=2,
        max_total_utf8_bytes=2_000_000,
        max_entry_utf8_bytes=1_000_000,
        max_concurrent_builds=2,
    )
    started = Event()
    release = Event()
    calls_lock = Lock()
    factory_calls = 0

    def value_factory() -> object:
        nonlocal factory_calls
        with calls_lock:
            factory_calls += 1
        started.set()
        assert release.wait(timeout=2)
        return {"value": "bounded"}

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                cache.get_or_create,
                key="same-revision",
                value_factory=value_factory,
            )
            for _ in range(8)
        ]
        assert started.wait(timeout=2)
        assert cache.active_builds == 1
        assert cache.inflight_reserved_utf8_bytes == 1_000_000
        assert cache.inflight_working_bytes == (
            JSON_DOCUMENT_BUILD_WORKING_SIZE_FACTOR * 1_000_000
        )
        assert cache.inflight_working_bytes <= cache.max_inflight_working_bytes
        assert cache.total_utf8_bytes + cache.inflight_reserved_utf8_bytes <= 2_000_000
        release.set()
        pagers = [future.result(timeout=2) for future in futures]

    assert factory_calls == 1
    assert all(pager is pagers[0] for pager in pagers)
    assert cache.active_builds == 0
    assert cache.inflight_reserved_utf8_bytes == 0
    assert cache.inflight_working_bytes == 0


def test_revision_cache_reserves_global_budget_before_distinct_builds() -> None:
    cache = JsonDocumentPagerCache(
        max_entries=4,
        max_total_utf8_bytes=128,
        max_entry_utf8_bytes=64,
        max_concurrent_builds=8,
        max_total_build_working_bytes=(
            2 * JSON_DOCUMENT_BUILD_WORKING_SIZE_FACTOR * 64
        ),
    )
    two_started = Event()
    release = Event()
    calls_lock = Lock()
    started_count = 0

    def value_factory() -> object:
        nonlocal started_count
        with calls_lock:
            started_count += 1
            if started_count == 2:
                two_started.set()
        assert release.wait(timeout=2)
        return {"value": "x"}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(
                cache.get_or_create,
                key=f"revision-{index}",
                value_factory=value_factory,
            )
            for index in range(3)
        ]
        assert two_started.wait(timeout=2)
        assert started_count == 2
        assert cache.active_builds == 2
        assert cache.inflight_reserved_utf8_bytes == 128
        assert cache.inflight_working_bytes == (
            2 * JSON_DOCUMENT_BUILD_WORKING_SIZE_FACTOR * 64
        )
        assert cache.inflight_working_bytes <= cache.max_inflight_working_bytes
        assert cache.total_utf8_bytes + cache.inflight_reserved_utf8_bytes <= 128
        release.set()
        [future.result(timeout=2) for future in futures]

    assert started_count == 3
    assert cache.total_utf8_bytes <= 128
    assert cache.inflight_reserved_utf8_bytes == 0
    assert cache.inflight_working_bytes == 0
