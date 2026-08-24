from __future__ import annotations

import pytest

from scholens_job_contracts import (
    MAX_STORAGE_DELETE_BATCH_JSON_BYTES,
    MAX_STORAGE_DELETE_KEY_UTF8_BYTES,
    MAX_STORAGE_DELETE_KEYS_PER_BATCH,
    chunk_storage_delete_keys,
    require_storage_delete_batch,
    require_storage_delete_key,
    storage_delete_batch_digest,
    storage_delete_batch_json_bytes,
)


def _document_key(index: int, *, suffix: str = "canonical.md") -> str:
    return f"documents/{index:064x}/{suffix}"


@pytest.mark.parametrize(
    "key",
    [
        f"documents/{'a' * 64}/source.pdf",
        (
            f"documents/{'b' * 64}/repairs/unicode-replacement-v1/"
            "00000000-0000-4000-8000-000000000001/canonical.md"
        ),
        "documents/00000000-0000-4000-8000-000000000001/reflow/assets/abc.png",
        "research/audio/00000000-0000-4000-8000-000000000002.mp3",
    ],
)
def test_storage_delete_contract_accepts_owned_generated_namespaces(key: str) -> None:
    assert require_storage_delete_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        "uploads/1/session/source.pdf",
        "avatars/user.png",
        "documents/../private.pdf",
        "documents//private.pdf",
        "documents/evil\\path.pdf",
        "documents/evil\x00path.pdf",
        "documents/论文.pdf",
        "documents/" + "a" * MAX_STORAGE_DELETE_KEY_UTF8_BYTES,
        "",
        None,
    ],
)
def test_storage_delete_contract_rejects_hostile_or_foreign_keys(key: object) -> None:
    with pytest.raises(ValueError, match="storage_delete"):
        require_storage_delete_key(key)


def test_storage_delete_chunks_preserve_producer_order_and_item_bound() -> None:
    keys = [
        _document_key(index) for index in range(MAX_STORAGE_DELETE_KEYS_PER_BATCH + 1)
    ]

    batches = tuple(chunk_storage_delete_keys(keys))

    assert tuple(key for batch in batches for key in batch) == tuple(keys)
    assert [len(batch) for batch in batches] == [MAX_STORAGE_DELETE_KEYS_PER_BATCH, 1]
    assert all(require_storage_delete_batch(batch) == batch for batch in batches)


def test_storage_delete_chunker_rejects_a_duplicate_in_current_batch() -> None:
    key = _document_key(1)

    with pytest.raises(ValueError, match="input_duplicate_key"):
        tuple(chunk_storage_delete_keys((key, key)))


def test_storage_delete_chunker_rejects_duplicate_across_batch_boundary() -> None:
    keys = [
        _document_key(index) for index in range(MAX_STORAGE_DELETE_KEYS_PER_BATCH + 1)
    ]

    with pytest.raises(ValueError, match="input_duplicate_key"):
        tuple(chunk_storage_delete_keys((*keys, keys[-1])))


def test_storage_delete_chunker_rejects_out_of_order_key_after_batch() -> None:
    keys = [
        _document_key(index) for index in range(MAX_STORAGE_DELETE_KEYS_PER_BATCH + 2)
    ]

    with pytest.raises(ValueError, match="input_order_invalid"):
        tuple(chunk_storage_delete_keys((*keys, keys[50])))


def test_storage_delete_chunker_does_not_preconsume_the_full_stream() -> None:
    consumed = 0

    def keys():
        nonlocal consumed
        for index in range(MAX_STORAGE_DELETE_KEYS_PER_BATCH * 3):
            consumed += 1
            yield _document_key(index)

    batches = chunk_storage_delete_keys(keys())

    assert len(next(batches)) == MAX_STORAGE_DELETE_KEYS_PER_BATCH
    assert consumed == MAX_STORAGE_DELETE_KEYS_PER_BATCH + 1


def test_storage_delete_chunks_by_exact_json_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scholens_job_contracts import storage_cleanup

    first = _document_key(1)
    second = _document_key(2)
    one_key_bytes = len(storage_delete_batch_json_bytes((first,)))
    monkeypatch.setattr(
        storage_cleanup, "MAX_STORAGE_DELETE_BATCH_JSON_BYTES", one_key_bytes
    )

    batches = tuple(storage_cleanup.chunk_storage_delete_keys((first, second)))

    assert batches == ((first,), (second,))
    assert all(
        len(storage_delete_batch_json_bytes(batch)) <= one_key_bytes
        for batch in batches
    )


def test_storage_delete_batch_rejects_duplicates_or_over_budget_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scholens_job_contracts import storage_cleanup

    first = _document_key(1)
    second = _document_key(2)
    with pytest.raises(ValueError, match="duplicate_key"):
        require_storage_delete_batch((first, first))
    with pytest.raises(ValueError, match="order_invalid"):
        require_storage_delete_batch((second, first))

    monkeypatch.setattr(
        storage_cleanup,
        "MAX_STORAGE_DELETE_BATCH_JSON_BYTES",
        len(storage_delete_batch_json_bytes((first,))) - 1,
    )
    with pytest.raises(ValueError, match="byte_limit"):
        storage_cleanup.require_storage_delete_batch((first,))


def test_maximum_batch_stays_within_declared_json_budget() -> None:
    batch = tuple(
        _document_key(index, suffix="x" * 900)
        for index in range(MAX_STORAGE_DELETE_KEYS_PER_BATCH)
    )

    chunks = tuple(chunk_storage_delete_keys(batch))

    assert all(len(chunk) <= MAX_STORAGE_DELETE_KEYS_PER_BATCH for chunk in chunks)
    assert all(
        len(storage_delete_batch_json_bytes(chunk))
        <= MAX_STORAGE_DELETE_BATCH_JSON_BYTES
        for chunk in chunks
    )
    assert len({storage_delete_batch_digest(chunk) for chunk in chunks}) == len(chunks)
