from types import SimpleNamespace

import pytest

from scholens_ai.token_passages import (
    TOKEN_LOOKAHEAD_CHARACTERS,
    PassageLimitExceeded,
    iter_token_passages,
)


class CharacterTokenizer:
    def __init__(self):
        self.largest_input = 0

    def encode(self, sequence, *, add_special_tokens):
        assert not add_special_tokens
        self.largest_input = max(self.largest_input, len(sequence))
        return SimpleNamespace(
            offsets=[(i, i + 1) for i, c in enumerate(sequence) if not c.isspace()]
        )


class UnicodeExpansionTokenizer(CharacterTokenizer):
    """Byte fallback and normalization can share one character across tokens."""

    def encode(self, sequence, *, add_special_tokens):
        encoded = super().encode(sequence, add_special_tokens=add_special_tokens)
        return SimpleNamespace(
            offsets=[
                offset
                for offset in encoded.offsets
                for _ in range(3 if sequence[offset[0]] == "💠" else 1)
            ]
        )


def test_multilingual_windows_preserve_exact_offsets_lines_and_overlap():
    text = ("Evidence 中文证据 café ﬁ ﬂ\n" * 15 + "\n") * 20
    tokenizer = CharacterTokenizer()
    passages = list(iter_token_passages(text, tokenizer))
    assert len(passages) > 10
    for index, passage in enumerate(passages):
        assert passage.content == text[passage.start_offset : passage.end_offset]
        assert passage.start_line == text[: passage.start_offset].count("\n") + 1
        assert passage.end_line == text[: passage.end_offset].count("\n") + 1
        assert passage.token_count <= 256
        if index:
            assert (
                passages[index - 1].start_offset
                < passage.start_offset
                < passages[index - 1].end_offset
            )
    assert passages[-1].end_offset == len(text.rstrip())
    assert len({passage.identity for passage in passages}) == len(passages)
    assert passages == list(iter_token_passages(text, tokenizer))


def test_paragraph_boundary_is_preferred_after_half_a_window():
    text = "a" * 180 + "\n\n" + "b" * 180
    first = next(iter_token_passages(text, CharacterTokenizer()))
    assert first.content == "a" * 180
    assert first.token_count == 180


def test_large_input_never_tokenizes_the_entire_document_and_never_silently_truncates():
    tokenizer = CharacterTokenizer()
    text = "long input 中文\n" * 100_000
    with pytest.raises(PassageLimitExceeded):
        list(iter_token_passages(text, tokenizer, limit=3))
    assert tokenizer.largest_input <= TOKEN_LOOKAHEAD_CHARACTERS


def test_whitespace_has_no_fake_passages_and_trailing_space_does_not_loop():
    assert list(iter_token_passages("\n \t " * 10_000, CharacterTokenizer())) == []
    assert (
        len(list(iter_token_passages("text" + " " * 10_000, CharacterTokenizer()))) == 1
    )


@pytest.mark.parametrize(
    "text",
    ["a" * 255 + "💠" * 300, "💠" * 900],
    ids=["boundary-expansion", "repeated-expansion"],
)
def test_shared_unicode_offsets_never_split_a_character_across_token_budget(text):
    tokenizer = UnicodeExpansionTokenizer()
    passages = list(iter_token_passages(text, tokenizer))
    assert len(passages) > 1
    covered = 0
    for passage in passages:
        assert passage.start_offset <= covered < passage.end_offset
        assert passage.content == text[passage.start_offset : passage.end_offset]
        actual = tokenizer.encode(passage.content, add_special_tokens=False).offsets
        assert passage.token_count == len(actual) <= 256
        covered = passage.end_offset
    assert covered == len(text)
    assert passages == list(iter_token_passages(text, tokenizer))
