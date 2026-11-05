"""Layout of centred, padded literal headings in retail battle text lists.

Discover BtlGfxTextList/BtlGfxText structures, not particular strings or row
addresses. Only the top row of a validated list, straddling the object's
origin and carrying equal nonempty space padding, is a centred heading.
Its text, count, palette and transform remain untouched.
"""
import struct

BASE = 0x800643C4


def centred_headings(data, widths, text_bits):
    """Yield (descriptor offset, x) using the renderer's packed advances.

    Restrict discovery to complete in-image 8x12 text lists, and require the
    heading's count to describe its entire FF-terminated, text-only literal.
    Mutable names, numerical fields and ordinary left-aligned rows are not
    layout candidates.
    """
    found = {}
    for at in range(0, len(data) - 7, 4):
        count, pointer = struct.unpack_from('<II', data, at)
        start = pointer - BASE
        if not 0 < count <= 255 or start < 0 or start % 4 or start + count * 12 > len(data):
            continue
        rows = [struct.unpack_from('<hhIBBBB', data, start + i * 12)
                for i in range(count)]
        if any(not n or not 0 < clut <= 0x7F or h != 12 or v != 0
               or not BASE <= p < BASE + len(data)
               for x, y, p, n, clut, h, v in rows):
            continue
        top = min(row[1] for row in rows)
        for i, (x, y, p, n, clut, h, v) in enumerate(rows):
            if y != top or not x < 0 < x + n * 8:
                continue
            off = p - BASE
            if off + n >= len(data) or data[off + n] != 0xFF:
                continue
            text = data[off:off + n]
            pad = len(text) - len(text.lstrip(b'\0'))
            if (not pad or pad != len(text) - len(text.rstrip(b'\0'))
                    or not text.strip(b'\0')):
                continue
            if not all(text_bits[c // 8] & (1 << (c % 8)) for c in text):
                continue
            width = len(text) * 8       # literal headings retain the original face/pitch
            found[start + i * 12] = -(width // 2)
    return sorted(found.items())


def assembly(rows):
    return (';; Generated padded battle heading layout; no text is changed.\n'
            + ''.join(f'.org {BASE + off:#x}\n    .halfword {x}\n'
                      for off, x in rows))


def verify(data, rows):
    for off, x in rows:
        if struct.unpack_from('<h', data, off)[0] != x:
            raise ValueError(f'battle heading at {BASE + off:#x} is not centred')
