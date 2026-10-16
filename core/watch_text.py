"""Conservative equivalence for watched dialogue with animated advance cursors."""

# Recognizers can read the same triangle as an arrow, angle bracket or triangle.
# Ignore only trailing cursor symbols after sentence punctuation. Actual letters,
# digits, kana, kanji and punctuation remain meaningful, even a one-character edit.
_CURSORS = frozenset("▷▶▸▹►▻△▲▽▼◁◀◂◃→⇒➜➤➔>＞")
_ENDINGS = frozenset("。！？.!?…」』）)\"”’")


def dialogue_key(text: str | None, ignored_suffixes=()) -> str | None:
    if text is None:
        return None
    original = text.strip()
    candidate = original
    for suffix in sorted(ignored_suffixes, key=len, reverse=True):
        if candidate.endswith(suffix):
            prefix = candidate[:-len(suffix)].rstrip()
            if prefix and prefix[-1] in _ENDINGS:
                candidate = prefix
                break
    original = candidate
    count = 0
    while candidate and candidate[-1] in _CURSORS and count < 3:
        candidate = candidate[:-1].rstrip()
        count += 1
    if count and candidate and candidate[-1] in _ENDINGS:
        return candidate
    return original
