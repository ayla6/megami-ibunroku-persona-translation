"""Compile additive subtitle lines without changing a single blend result.

Positive glyph contributions at a pixel are interned as an expression. The
console evaluates each distinct expression once at the line's current alpha,
then walks positioned spans. Saturating additions associate, so overlapping
glyphs can be summed before their one final saturated add to the background.
"""
import struct

MAX_RECIPES = 1024             # eight 4 KB lookups; zoom bank starts at 0x80130000


def line_pixels(text, x, y, cells, advances, first=0x20):
    pixels = {}
    for char in text:
        gi = ord(char) - first
        for gy, row in enumerate(cells[gi]):
            for gx, (gray, coverage) in enumerate(row):
                if gray and coverage:
                    pixels.setdefault((y + gy, x + gx), []).append((gray, coverage))
        x += advances[gi]
    return pixels


def compile_line(text, x, y, cells, advances, first=0x20):
    pixels = line_pixels(text, x, y, cells, advances, first)
    expressions = sorted({tuple(p) for p in pixels.values()})
    if len(expressions) > MAX_RECIPES:
        raise ValueError('FMV ink expressions exceed runtime lookup')
    ids = {p: i for i, p in enumerate(expressions)}
    out = bytearray(struct.pack('<H', len(expressions)))
    # A conservative exact upper bound for either rounding mode, including
    # overhanging glyphs. This proves when packed RGB addition cannot carry
    # between channels, instead of assuming that all text has single coverage.
    peaks = [min(255, max((sum((gray * (cov * alpha >> 8) + 128) >> 8
                               for gray, cov in expr) for expr in expressions), default=0))
             for alpha in range(256)]
    out.extend(struct.pack('<256H', *peaks))
    for expr in expressions:
        if len(expr) > 255:
            raise ValueError('too many overlapping glyph contributions')
        out.append(len(expr))
        for gray, coverage in expr:
            out.extend((gray, coverage))
    # All subsequent u16 IDs are aligned, including after odd-sized recipes.
    if len(out) & 1:
        out.append(0)
    for row in sorted({y for y, x in pixels}):
        xs = sorted(x for yy, x in pixels if yy == row)
        runs = []
        for x in xs:
            if not runs or x != runs[-1][-1] + 1:
                runs.append([])
            runs[-1].append(x)
        if not 0 <= row < 240 or len(runs) > 255:
            raise ValueError('invalid FMV ink span row')
        out.extend((row, len(runs)))
        for run in runs:
            out.extend(struct.pack('<HH', run[0], len(run)))
            for x in run:
                out.extend(struct.pack('<H', ids[tuple(pixels[row, x])]))
    out.append(255)
    return bytes(out)
