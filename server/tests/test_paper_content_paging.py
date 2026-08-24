from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from threading import Event, Lock
from uuid import uuid4

import pytest

from app.modules.papers.application.content import AccessiblePaperContent

from app.tooling.paper_content_paging import (
    PAPER_CONTENT_BUILD_WORKING_BYTES,
    PAPER_CONTENT_JSON_STRING_BYTES,
    PAPER_CONTENT_LINE_CHECKPOINT_INTERVAL,
    PaperContentPager,
    PaperContentSearchCapacityError,
    PaperContentSnapshot,
    PaperContentSnapshotCache,
    PaperContentSnapshotTooLargeError,
)


def _paper(*, revision: str, content: str) -> AccessiblePaperContent:
    return AccessiblePaperContent(
        document_id=uuid4(),
        original_filename="paper.pdf",
        title="Paper",
        abstract=None,
        raw_content=content,
        storage_key="private/source.pdf",
        parser_markdown_storage_key="private/content.md",
        content_revision=revision,
    )


def _snapshot(*, revision: str, content: str) -> PaperContentSnapshot:
    return PaperContentSnapshot.build(_paper(revision=revision, content=content))


def test_paper_content_page_respects_lines_and_exposes_line_continuation() -> None:
    pager = PaperContentPager.build("first\nsecond\nthird")

    page = pager.page(offset=0, max_lines=2, max_utf8_bytes=32_768)

    assert page.content == "first\nsecond\n"
    assert page.start_line == 1
    assert page.end_line == 2
    assert page.next_start_line == 3
    assert page.next_offset == len(page.content)
    assert page.ends_mid_line is False


def test_long_unicode_line_reassembles_losslessly_without_split_codepoints() -> None:
    raw_content = "开头🙂" + ("界🔬" * 40_000) + "结尾"
    pager = PaperContentPager.build(raw_content)
    offset = 0
    fragments: list[str] = []

    while True:
        page = pager.page(
            offset=offset,
            max_lines=500,
            max_utf8_bytes=32_768,
        )
        fragments.append(page.content)
        assert len(page.content.encode("utf-8")) <= 32_768
        assert (
            len(json.dumps(page.content, ensure_ascii=False).encode("utf-8"))
            <= PAPER_CONTENT_JSON_STRING_BYTES
        )
        if page.next_offset is None:
            assert page.ends_mid_line is False
            break
        assert page.next_start_line is None
        assert page.ends_mid_line is True
        offset = page.next_offset

    assert "".join(fragments) == raw_content
    assert "\ufffd" not in "".join(fragments)
    assert pager.content_sha256 == hashlib.sha256(raw_content.encode()).hexdigest()


def test_json_escape_heavy_text_is_bounded_before_transport_serialization() -> None:
    pager = PaperContentPager.build(('\\"\x00\n' * 20_000) + "tail")

    page = pager.page(offset=0, max_lines=500, max_utf8_bytes=32_768)

    assert (
        len(json.dumps(page.content, ensure_ascii=False).encode("utf-8"))
        <= PAPER_CONTENT_JSON_STRING_BYTES
    )
    assert page.next_offset is not None


def test_empty_content_has_one_stable_terminal_page() -> None:
    page = PaperContentPager.build("").page(
        offset=0,
        max_lines=200,
        max_utf8_bytes=32_768,
    )

    assert page.content == ""
    assert page.total_lines == 0
    assert page.end_line is None
    assert page.next_offset is None


def test_sparse_line_index_bounds_hostile_many_line_overhead() -> None:
    raw_content = "x\n" * 200_000

    pager = PaperContentPager.build(raw_content)

    assert pager.total_lines == 200_000
    assert len(pager.line_checkpoints) <= (
        pager.total_lines // PAPER_CONTENT_LINE_CHECKPOINT_INTERVAL + 1
    )
    assert pager.retained_size_bytes < len(raw_content.encode()) * 2
    assert pager.offset_for_line(199_999) == (199_999 - 1) * 2


def test_pager_preserves_crlf_line_identity_across_a_mid_separator_page() -> None:
    pager = PaperContentPager.build("first\r\nsecond")

    first = pager.page(offset=0, max_lines=10, max_utf8_bytes=6, start_line=1)
    second = pager.page(
        offset=first.end_offset,
        max_lines=10,
        max_utf8_bytes=32,
        start_line=first.next_start_line or first.end_line,
    )

    assert first.content == "first\r"
    assert first.ends_mid_line is True
    assert first.next_start_line is None
    assert second.start_line == 1
    assert second.content == "\nsecond"
    assert second.end_line == 2
    assert second.ends_mid_line is False


def test_snapshot_cache_is_lru_and_never_exceeds_total_retained_budget() -> None:
    first = _snapshot(revision="first", content="a" * 200)
    second = _snapshot(revision="second", content="b" * 200)
    third = _snapshot(revision="third", content="c" * 200)
    total_budget = first.retained_size_bytes + second.retained_size_bytes
    cache = PaperContentSnapshotCache(
        max_entries=2,
        max_total_retained_bytes=total_budget,
        max_entry_retained_bytes=max(
            first.retained_size_bytes,
            second.retained_size_bytes,
            third.retained_size_bytes,
        ),
    )
    cached_first = cache.get_or_create(
        key="first", value_factory=lambda: _paper(revision="first", content="a" * 200)
    )
    cache.get_or_create(
        key="second",
        value_factory=lambda: _paper(revision="second", content="b" * 200),
    )
    assert cache.get(key="first") is cached_first

    cached_third = cache.get_or_create(
        key="third", value_factory=lambda: _paper(revision="third", content="c" * 200)
    )

    assert cache.get(key="first") is cached_first
    assert cache.get(key="second") is None
    assert cache.get(key="third") is cached_third
    assert cache.total_retained_bytes <= total_budget


def test_snapshot_cache_rejects_an_entry_over_its_hard_memory_limit() -> None:
    snapshot = _snapshot(revision="oversized", content="x" * 1_000)
    cache = PaperContentSnapshotCache(
        max_entries=2,
        max_total_retained_bytes=snapshot.retained_size_bytes,
        max_entry_retained_bytes=snapshot.retained_size_bytes - 1,
    )

    with pytest.raises(PaperContentSnapshotTooLargeError) as raised:
        cache.get_or_create(
            key="oversized",
            value_factory=lambda: _paper(revision="oversized", content="x" * 1_000),
        )

    assert raised.value.actual_retained_bytes == snapshot.retained_size_bytes
    assert raised.value.maximum_retained_bytes == snapshot.retained_size_bytes - 1
    assert cache.total_retained_bytes == 0


def test_snapshot_cache_builds_one_revision_only_once() -> None:
    snapshot = _snapshot(revision="one", content="evidence")
    paper = AccessiblePaperContent(
        document_id=uuid4(),
        original_filename="paper.pdf",
        title="Paper",
        abstract=None,
        raw_content="evidence",
        storage_key="private/source.pdf",
        parser_markdown_storage_key=None,
        content_revision="one",
    )
    cache = PaperContentSnapshotCache(
        max_entries=2,
        max_total_retained_bytes=1_000_000,
        max_entry_retained_bytes=1_000_000,
    )
    factory_calls = 0

    def factory() -> AccessiblePaperContent:
        nonlocal factory_calls
        factory_calls += 1
        return paper

    created = cache.get_or_create(key="same", value_factory=factory)
    cached = cache.get_or_create(key="same", value_factory=factory)

    assert created.pager.raw_content == snapshot.pager.raw_content
    assert cached is created
    assert factory_calls == 1


def test_snapshot_cache_singleflights_concurrent_hydration_for_one_revision() -> None:
    paper = AccessiblePaperContent(
        document_id=uuid4(),
        original_filename="paper.pdf",
        title="Paper",
        abstract=None,
        raw_content="evidence",
        storage_key="private/source.pdf",
        parser_markdown_storage_key=None,
        content_revision="one",
    )
    cache = PaperContentSnapshotCache(
        max_entries=2,
        max_total_retained_bytes=2_000_000,
        max_entry_retained_bytes=1_000_000,
        max_concurrent_builds=2,
    )
    started = Event()
    release = Event()
    calls_lock = Lock()
    factory_calls = 0

    def factory() -> AccessiblePaperContent:
        nonlocal factory_calls
        with calls_lock:
            factory_calls += 1
        started.set()
        assert release.wait(timeout=2)
        return paper

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                cache.get_or_create,
                key="same-revision",
                value_factory=factory,
            )
            for _ in range(8)
        ]
        assert started.wait(timeout=2)
        assert cache.active_builds == 1
        assert cache.inflight_reserved_bytes == 1_000_000
        assert (
            cache.inflight_working_reserved_bytes == PAPER_CONTENT_BUILD_WORKING_BYTES
        )
        assert cache.inflight_working_reserved_bytes <= cache.max_inflight_working_bytes
        assert cache.total_retained_bytes + cache.inflight_reserved_bytes <= 2_000_000
        release.set()
        snapshots = [future.result(timeout=2) for future in futures]

    assert factory_calls == 1
    assert all(snapshot is snapshots[0] for snapshot in snapshots)
    assert cache.active_builds == 0
    assert cache.inflight_reserved_bytes == 0
    assert cache.inflight_working_reserved_bytes == 0


def test_snapshot_cache_reserves_global_budget_before_distinct_builds() -> None:
    papers = [
        AccessiblePaperContent(
            document_id=uuid4(),
            original_filename="paper.pdf",
            title="Paper",
            abstract=None,
            raw_content=f"evidence-{index}",
            storage_key="private/source.pdf",
            parser_markdown_storage_key=None,
            content_revision=str(index),
        )
        for index in range(3)
    ]
    cache = PaperContentSnapshotCache(
        max_entries=4,
        max_total_retained_bytes=2_000_000,
        max_entry_retained_bytes=1_000_000,
        max_concurrent_builds=8,
    )
    two_started = Event()
    release = Event()
    calls_lock = Lock()
    started_count = 0

    def factory(index: int) -> AccessiblePaperContent:
        nonlocal started_count
        with calls_lock:
            started_count += 1
            if started_count == 2:
                two_started.set()
        assert release.wait(timeout=2)
        return papers[index]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(
                cache.get_or_create,
                key=f"revision-{index}",
                value_factory=lambda index=index: factory(index),
            )
            for index in range(3)
        ]
        assert two_started.wait(timeout=2)
        assert started_count == 2
        assert cache.active_builds == 2
        assert cache.inflight_reserved_bytes == 2_000_000
        assert (
            cache.inflight_working_reserved_bytes
            == 2 * PAPER_CONTENT_BUILD_WORKING_BYTES
        )
        assert cache.inflight_working_reserved_bytes <= cache.max_inflight_working_bytes
        assert cache.total_retained_bytes + cache.inflight_reserved_bytes <= 2_000_000
        release.set()
        [future.result(timeout=2) for future in futures]

    assert started_count == 3
    assert cache.total_retained_bytes <= 2_000_000
    assert cache.inflight_reserved_bytes == 0
    assert cache.inflight_working_reserved_bytes == 0


def test_snapshot_cache_bounds_searches_even_when_content_is_already_cached() -> None:
    cache = PaperContentSnapshotCache(max_concurrent_searches=1)

    with cache.search_slot(timeout_seconds=0):
        with pytest.raises(PaperContentSearchCapacityError):
            with cache.search_slot(timeout_seconds=0):
                pytest.fail("a second regex scan acquired the only search slot")

    with cache.search_slot(timeout_seconds=0):
        pass
