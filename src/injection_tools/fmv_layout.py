"""Layout of the movies whose frames carry burned-in text.

The wording is never here: quote_lines()/poem_lines() read the translated text
(PSP-US port + the human-signed poem translation). What lives here is the
PS1-movie-specific layout the burn tools always carried: which frames are a
card, where the original text sits, and which English line replaces which
Japanese line ('>N' pins). The renderer/measurement read it from one place.

Frame numbers are 0-based stream frames (g_movie_frame's units).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import toolbelt  # noqa: E402

QUOTE_MOVIE = 0x1C            # opening movie MV1C: the Zhuangzi quote cards
ATTR_RIGHT = 286              # ink right edge of right-aligned lines

# movies whose frames carry burned-in text: the first frame with the scene
# clear of text and filter (the plate) and the span the burned-in text lives in
MOVIES = {
    'MV1C': (0x1C, 'STR1/MV1C.STR', 490, (20, 492)),
    'MV1E': (0x1E, 'STR1/MV1E.STR', 229, (40, 230)),
    'MV25': (0x25, 'STR2/MV25.STR', 188, (20, 190)),
}


# THE CARD FONT'S REPERTOIRE: the movie font's atlas is ASCII 0x20-0x7E
# (fmv_subgen.GLYPH_FIRST..GLYPH_LAST), and the compositor walks that atlas -
# a character outside it has no advance and no ink box, so it is skipped and
# the card shows a hole. The PSP title-quote table carries one such cell
# ('＾-Zhuangzi', U+FF3E - the JP build's table has the same mark before
# '~荘子~': a decorative cell, not a letter), so the card adapter drops what
# the card cannot draw and SAYS SO - a hole is not a translation.
CARD_LO, CARD_HI = 0x20, 0x7E


def card_text(line):
    """One card line in the characters the movie font can draw (see above)."""
    keep = ''.join(c for c in line if CARD_LO <= ord(c) <= CARD_HI or c == '\n')
    if keep != line:
        lost = sorted({f'{c!r} (U+{ord(c):04X})' for c in line if c not in keep})
        print(f'fmv_layout: card font cannot draw {", ".join(lost)} - dropped '
              f'from {line!r}')
    return keep


def quote_lines():
    """The opening-movie quote, line by line: the PSP-US BOOT.BIN title-quote
    wording (translation/generated/fmv/opening.tsv, port_quote.py), with any
    line filled in translation/manual/fmv/opening.tsv winning."""
    import strlib
    lines = {}
    for sub in ('generated', 'manual'):
        path = os.path.join(ROOT, 'translation', sub, 'fmv', 'opening.tsv')
        if not os.path.exists(path):
            continue
        for r in strlib.tsv_rows(path, required=('line', 'text')):
            if (r.get('text') or '').strip():
                lines[int(r['line'])] = r['text']
    out = [card_text(lines[k]) for k in sorted(lines)]
    if len(out) != 10:
        raise SystemExit(f'fmv_layout: expected 10 quote lines, got {len(out)}')
    return out


def poem_lines():
    """The ending poems, verbatim from the PSP-US transcription
    (translation/manual/fmv/poems.tsv)."""
    import strlib
    path = os.path.join(ROOT, 'translation', 'manual', 'fmv', 'poems.tsv')
    if not os.path.exists(path):
        raise SystemExit('fmv_layout: missing ' + path)
    out = {}
    for r in strlib.tsv_rows(path, required=('movie', 'seq', 'text')):
        out.setdefault(r['movie'], []).append(r['text'])
    return out


# (first, last, [(band y0, y1) of each Japanese line], [English line each])
# Band layout/pins are PS1-movie-specific (handmade): a trailing '>N' pins a
# line to band N (PSP sometimes uses fewer lines than the Japanese card);
# default is lines[k] on bands[k]. A leading '>' is the right-aligned
# attribution (attribution ink ends at ATTR_RIGHT).
def quote_cards():
    q = quote_lines()
    return [
        (20, 98, [(107, 120)], [q[0]]),
        (99, 230, [(79, 92), (99, 112), (119, 132), (139, 152)],
         [q[1] + '>0', q[2] + '>1', q[3] + '>2']),
        (231, 338, [(85, 98), (125, 138)], [q[4], q[5]]),
        (339, 492, [(83, 95), (102, 115), (122, 135), (165, 178)],
         [q[6], q[7], q[8], '>' + q[9] + '>3']),
    ]


# movie: (first, last, rect x0,y0,x1,y1, first line top y, English lines)
# The poem is one block: every line fades with the same curve.
def poem_cards():
    p = poem_lines()
    return {
        'MV1E': (40, 230, (20, 50, 300, 188), 57, p['MV1E']),
        'MV25': (20, 190, (40, 30, 290, 175), 57, p['MV25']),
    }
