"""Splitting a recognised line into words.

A direct port of the extension's src/lib/segment.js, constants included. Its reasoning, kept
because it is the whole justification for not writing the four-line version:

Chinese is written without spaces, so a line read off an image is one run of characters and
something has to decide where the words are. The obvious algorithm is forward maximum matching --
take the longest dictionary word from the left, advance, repeat -- and it is wrong often enough
to matter, because a greedy first choice can strand everything after it:

    研究生命起源   greedy -> 研究生 | 命 | 起源     ("graduate student", "life")
                   wanted -> 研究 | 生命 | 起源     ("research", "origin of life")

So every position is a node, every dictionary match is an edge, and the segmentation is the
cheapest path across. Same O(n · max_word_length) work as maximum matching, but nothing is
committed until the whole line has been considered.

The costs stand in for word frequencies, which CC-CEDICT does not carry. If a frequency table is
ever added this stays exactly as it is and TOKEN becomes -log P(word).
"""

from dataclasses import dataclass

# A dictionary word. Fewer, longer words is the right prior for Chinese.
TOKEN = 1.0

# Extra cost for a one-character word. This is the rule that earns its keep: in the example above
# both segmentations are three tokens, so counting alone ties, and the tie is broken by the greedy
# one having stranded 命 on its own. Without this the DP is barely better than maximum matching.
SINGLE = 0.5

# A character the dictionary does not know: punctuation, latin, or whatever OCR made up. Priced
# above a known single character so it is never preferred, but finite, so an unreadable glyph
# costs one token rather than dragging its neighbours into a worse split.
UNKNOWN = 2.0


@dataclass(frozen=True)
class Span:
    start: int
    length: int


def segment(length: int, word_lengths_at: list[list[int]]) -> list[Span]:
    """Choose where the words are.

    Pure, and deliberately ignorant of the dictionary: given only how long the text is and which
    lengths are words at each position, so it can be tested against a fake dictionary.

    `word_lengths_at` is indexed by character position and holds the lengths of dictionary words
    starting there. May be empty at any position. Order does not matter.
    """
    if length <= 0:
        return []

    # cost[i] is the cheapest way to cover everything from i onwards; take[i] is the token length
    # that achieves it. Solved back to front so each step only reads answers it already has.
    cost = [0.0] * (length + 1)
    take = [1] * (length + 1)

    for i in range(length - 1, -1, -1):
        # The fallback is always available: one unknown character, whatever the dictionary thinks.
        # Without it a position with no matches would have no finite cost and the DP would break.
        best = UNKNOWN + cost[i + 1]
        chosen = 1

        # Longest first, with a strict comparison below, so ties resolve to the longer word.
        for word_length in sorted(word_lengths_at[i] if i < len(word_lengths_at) else [], reverse=True):
            if word_length < 1 or i + word_length > length:
                continue
            candidate = TOKEN + (SINGLE if word_length == 1 else 0.0) + cost[i + word_length]
            if candidate < best:
                best = candidate
                chosen = word_length

        cost[i] = best
        take[i] = chosen

    spans = []
    i = 0
    while i < length:
        spans.append(Span(start=i, length=take[i]))
        i += take[i]
    return spans
