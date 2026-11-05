"""System > Config screen texts (rows, options, button-function names, title) in the ADV / DNG / S2D overlays.

  python tools/cfgtext.py     write build/cfgtext_<ovl>.asm (included in each overlay section of main.asm)

The texts are tile strings of the 8x12 small font (1 byte per cell, same encoding as tools/items.py: A-Z are the
full-width glyph codes, space = 0 = blank cell) drawn by the overlay's 0x80067C00 with a cell count, ending at FF
(or at the count). They are patched IN PLACE, padded with blank cells, so every string must fit the Japanese slot
(`room`). The <TAB> token advances to the next 40-pixel option-marker position with SF_VWF enabled.
ADV is the reference (RAM addresses below); DNG / S2D hold byte-identical blocks at a fixed file-offset delta,
checked by content before writing.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext   # noqa: E402
import items   # noqa: E402
import strlib  # noqa: E402
import toolbelt  # noqa: E402

ROOT = etext.ROOT
B = 0x800643C4
NL = chr(10)
# file offset of the block in the other overlays = ADV offset - delta
DELTA = {'ADV': 0, 'DNG': 0x1CD24, 'S2D': 0x1A194}
DELTA_LOW = {'ADV': 0, 'DNG': 0x17510, 'S2D': 0x14980}       # the block below 0x800B3000 sits at other offsets

# (ADV RAM address, room = bytes available incl. FF, has_ff, English)
E_LAY = [
    (0x800b95cc, 12, True),
    (0x800b95d8, 12, True),
    (0x800b95e4, 12, True),
    (0x800b95f0, 8, True),
    (0x800b95f8, 8, True),
    (0x800b9600, 12, True),
    (0x800b9618, 8, True),
    (0x800b9620, 11, True),
    (0x800b962c, 16, False),
    (0x800b963c, 16, True),
    (0x800b964c, 16, True),
    (0x800b965c, 12, True),
    (0x800b9670, 12, True),
    (0x800b967c, 13, True),
    (0x800b9698, 12, True),
    (0x800b96a4, 10, True),
    (0x800b9714, 8, True),
    (0x800b971c, 8, True),
    (0x800b9724, 8, True),
    (0x800b972c, 16, True),
    (0x800b973c, 12, True),
    (0x800b9748, 12, True),
    (0x800b9754, 16, True),
    (0x800b9764, 16, True),
    (0x800b9774, 12, True),
    (0x800b9780, 12, True),
    (0x800b978c, 8, True),
    (0x800b9794, 12, True),
    (0x800b97a0, 12, True),
    (0x800b97ac, 12, True),
    (0x800b97b8, 12, True),
    (0x800b97c4, 12, True),
    (0x800b97d0, 8, True),
    (0x800b97d8, 8, True),
    (0x800b97e0, 13, True),
    (0x800b9cf8, 9, True),
    (0x800b2310, 12, True),
    (0x800b231c, 10, True),
    (0x800b2328, 14, True),
    (0x800b2338, 12, True),
    (0x800b2374, 12, False),
    (0x800b2384, 8, False),
    (0x800b238c, 4, False),
    (0x800b23a8, 8, False),
]
E = [(a, r, ff, strlib.glossary('cfgtext')[f'{a:#x}']) for a, r, ff in E_LAY]


# casino / coin-exchange labels (small font, ADV overlay only): count-limited, padded with blanks
E_ADV_LAY = [
    (0x800bb124, 4, False),
    (0x800bb128, 8, False),
    (0x800bb130, 8, False),
    (0x800bb138, 12, False),
    (0x800bb144, 8, False),
    (0x800bb14c, 4, False),
]
E_ADV = [(a, r, ff, strlib.glossary('cfgtext')[f'{a:#x}']) for a, r, ff in E_ADV_LAY]
# dialogue-format strings (VWF bytes, FF01 end): (ADV RAM address, room in bytes incl. FF01, English)
D_LAY = [
    (0x800b2360, 20),
]
D = [(a, r, strlib.glossary('cfgtext')[f'{a:#x}']) for a, r in D_LAY]


def enc(t):
    parts = t.split('<TAB>')
    if len(parts) > 1 and not parts[0]:
        raise ValueError('a tab must follow a glyph')
    tab = toolbelt.asm_equ('SF_TAB', os.path.join(ROOT, 'src/asm/vwf/smallfont_defs.asm'))
    return bytes([tab]).join(bytes(items.glyph(c) for c in part) for part in parts)


def centered_producers(data, ovl):
    """Find the retail controller title producers from their writer geometry.

    The two place labels share the same 11-cell, bank-2 writer; both branches
    of that producer are included. The top title is the 10-cell field on the
    top map row. Do not identify the English text or alter the source rows.
    """
    hook = toolbelt.asm_equ(f'{ovl}_SF_HOOK_ADDR')
    jal = 0x0C000000 | ((hook >> 2) & 0x3FFFFFF)
    words = struct.unpack(f'<{len(data) // 4}I', data[:len(data) & ~3])
    tilemap = 0x800EF580 + (0x20000 if ovl == 'S2D' else 0)
    dst = tilemap + 11 * 2
    dst_hi = 0x3C050000 | (dst >> 16)
    dst_lo = 0x34A50000 | (dst & 0xFFFF)
    title, labels = [], []
    for i, word in enumerate(words[:-1]):
        if word != jal:
            continue
        prev = words[max(0, i - 10):i]
        if words[i + 1] == 0x3407000A and dst_hi in prev and dst_lo in prev:
            title.append(i)
        if words[i + 1] == 0x3407000B and 0x340601AE in prev:
            labels.append(i)
    if len(title) != 1 or len(labels) != 3:
        raise SystemExit(f'cfgtext: {ovl} centered producer shape changed: {title}, {labels}')
    return [(B + 4 * (i + 1), words[i + 1] | 0x8000) for i in title + labels]


def main():
    adv = open(os.path.join(ROOT, 'data', 'psx', 'ADV.BIN'), 'rb').read()
    for ovl in DELTA:
        d = open(os.path.join(ROOT, 'data', 'psx', ovl + '.BIN'), 'rb').read()
        out = [f';; generated by tools/cfgtext.py - do not edit ({ovl})' + NL]
        for at, instruction in centered_producers(d, ovl):
            out.append(f'.if SF_VWF{NL}.org {at:#x}{NL}    .word {instruction:#010x}{NL}.endif{NL}')
        for addr, room, has_ff, t in E:
            delta = (DELTA_LOW if addr < 0x800b3000 else DELTA)[ovl]
            off = addr - B
            ja = adv[off:off + room]
            if d[off - delta:off - delta + room] != ja:
                raise SystemExit(f'cfgtext: {ovl} block differs at {addr:#x}')
            b = enc(t)
            # A full slot can use the existing terminator immediately after
            # it, provided only blank cells intervene. Never write the
            # neighbouring bytes: another string may own them.
            if has_ff and len(b) == room:
                tail = d[off - delta + room:off - delta + room + 8]
                end = tail.find(b'\xff')
                if end >= 0 and not any(tail[:end]):
                    out.append(f'; {t}{NL}.org {B + off - delta:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL)
                    continue
            if len(b) + (1 if has_ff else 0) > room:
                raise SystemExit(f'cfgtext: {t!r} is {len(b)} cells, room {room - (1 if has_ff else 0)}')
            b = b + (b'\xff' if has_ff else b'')
            b += bytes(room - len(b))                      # blank cells
            out.append(f'; {t}{NL}.org {B + off - delta:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL)
        if ovl == 'ADV':
            for addr, room, has_ff, t in E_ADV:
                off = addr - B
                if len(enc(t)) > room:
                    raise SystemExit(f'cfgtext: {t!r} too long for {room}')
                b = enc(t) + bytes(room - len(enc(t)))
                out.append(f'; {t}{NL}.org {addr:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL)
        for addr, room, t in D:
            delta = DELTA_LOW[ovl]
            off = addr - B
            ja = adv[off:off + room]
            if d[off - delta:off - delta + room] != ja or ja[-2:] != bytes((0xFF, 0x01)):
                raise SystemExit(f'cfgtext: {ovl} dialogue block differs at {addr:#x}')
            b = etext.encode(t)
            if len(b) > room:
                raise SystemExit(f'cfgtext: {t!r} is {len(b)} bytes, room {room}')
            b += bytes(room - len(b))
            out.append(f'; {t}{NL}.org {B + off - delta:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL)
        open(os.path.join(ROOT, 'build', f'cfgtext_{ovl.lower()}.asm'), 'w', newline=NL).write(''.join(out))
    print(f'cfgtext: {len(E)} strings x 3 overlays, {len(E_ADV)} ADV-only, {len(D)} dialogue-format')


if __name__ == '__main__':
    main()
