import pytest

from scholens_ai.evidence import evidence_segments, resolve_evidence


@pytest.mark.parametrize(
    ("source", "quote"),
    [
        ("The measured café response is stable.", "cafe\u0301 response is stable"),
        ("The efﬁcient method improves results.", "efficient method improves results"),
        ("实验结果\n\t表明准确率达到 95%。", "实验结果 表明准确率达到 95%"),
        ("We measured 12\u00a0ms of latency.", "measured 12 ms of latency"),
    ],
)
def test_reversible_normalization_keeps_original_quote_and_offsets(source, quote):
    segment = next(evidence_segments(source))
    result = resolve_evidence(source, quote, segment_id=segment.id)
    assert result.anchor is not None
    assert result.anchor.quote == source[result.anchor.start : result.anchor.end]
    assert result.reason is None


def test_segment_identity_disambiguates_repeated_quotes_and_rejects_stale_content():
    text = "Repeated exact evidence. " + "x" * 2600 + " Repeated exact evidence."
    segments = list(evidence_segments(text))
    assert resolve_evidence(text, "Repeated exact evidence.").reason == "ambiguous"
    result = resolve_evidence(
        text, "Repeated exact evidence.", segment_id=segments[-1].id
    )
    assert result.anchor is not None and result.anchor.start > 2000
    assert (
        resolve_evidence(
            text + "!", "Repeated exact evidence.", segment_id=segments[-1].id
        ).reason
        == "stale_segment"
    )


@pytest.mark.parametrize(
    "quote",
    ["", "results", "The new method is better.", "the method improved results."],
)
def test_no_paraphrase_casefold_or_short_partial_match(quote):
    assert resolve_evidence("The method improved results.", quote).anchor is None


def test_segment_boundaries_cover_text_and_are_bounded():
    text = "Paragraph evidence 中文.\n\n" * 800
    segments = list(evidence_segments(text))
    assert segments[0].start == 0 and segments[-1].end == len(text)
    for previous, following in zip(segments, segments[1:]):
        assert previous.start < following.start < previous.end
    assert all(
        len(s.text) <= 2400 and s.text == text[s.start : s.end] for s in segments
    )


def test_normalized_partial_character_is_rejected_and_legacy_unique_quote_works():
    assert resolve_evidence("abcdefgh\u00bc", "abcdefgh1").anchor is None
    assert (
        resolve_evidence(
            "The method improved results.", "method improved results"
        ).anchor
        is not None
    )


def test_exact_match_is_also_rejected_if_normalized_form_is_ambiguous():
    assert (
        resolve_evidence(
            "The cafe\u0301 result. The café result.", "The café result."
        ).reason
        == "ambiguous"
    )


def test_legacy_streaming_match_crosses_buffer_and_long_whitespace_boundaries():
    content = "x" * 4090 + "reliable " + " \n" * 20_000 + "source evidence" + "z" * 5000
    result = resolve_evidence(content, "reliable source evidence")
    assert result.anchor is not None
    assert result.anchor.start == 4090
    assert result.anchor.quote == content[result.anchor.start : result.anchor.end]
