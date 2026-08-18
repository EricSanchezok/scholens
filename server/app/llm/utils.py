def find_offsets(target: str, full_text: str) -> tuple[int, int]:
    """Locate the exact offsets of ``target`` inside ``full_text``.

    Returns ``(-1, -1)`` when the quote is not found verbatim. Callers must
    skip the annotation instead of persisting a partial window: the previous
    difflib longest-match fallback silently produced 3-6 character spans for
    paraphrased quotes, corrupting every highlight built from them.
    """
    start_offset = full_text.find(target)
    if start_offset < 0:
        return -1, -1
    return start_offset, start_offset + len(target)
