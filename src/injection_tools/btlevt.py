"""Scripted story-battle dialogue of BTLP.BIN (tutorial, boss battles: Nanjo/Mark/Kandori/Pandora ... lines shown in the
battle message box with a face; NOT part of the ADV/E? event scripts). Same machinery as tools/btlmsg.py.

  python tools/btlevt.py dump     write/refresh translation/strings/BTLEVT.tsv (keeps the `en` and `note` columns)
  python tools/btlevt.py build    QA + generate build/btlevt.asm (included in the BTLP section of main.asm)

Zone BTLP RAM 0x800D1D4C-0x800D222C (file offset = RAM - 0x800643C4): strings in dialogue encoding ending with FF F5
(FFF6 newline, FFFC pause, FFF8 number, FFF9 character name), shown through BTLP's VWF-hooked text interpreter
(vwf/vwf_btlp.asm), so English works as is. References are absolute words (pointer tables: Triangle help
0x800D2254/0x800D24F0/0x800D25F4, debug menu 0x800D265C) or `lui x,0x800D ; addiu x,x,imm` pairs in the code; both
are patched (only the addiu immediate changes: the whole zone is under lui 0x800D). A message with no reference
found keeps its address (and must fit its slot); everything else is re-packed freely, 4-byte aligned like the
original (2-aligned: 4 does not fit the English).
`en`: the control codes of the Japanese, in any order; lines (<FFF6>) <= 239 px.
A page - <FFFB><FFF7> is the hold/pause page skeleton, not a clear - carries
at most four lines: the same 15-cell box as ADV has three visible lines, then
the fourth scroll line. The interpreter waits when its 3x15-cell window fills
and scrolls; a fifth line is a second scroll and is outside the page model
(docs/TEXT_ARCHITECTURE.md).
"""
import collections
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'extraction_tools', 'psp'))
from codec import E_PARAM_UNITS  # noqa: E402
import strlib     # noqa: E402
import vwf_wrap  # noqa: E402
import capstone  # noqa: E402

ROOT = etext.ROOT
B = 0x800643C4
ZONE = (0x800CFA14, 0x800D0AE4)       # strings only (data follows; the zero bytes before are not used)
TSV = os.path.join(ROOT, 'translation', 'manual', 'strings', 'BTLEVT.tsv')
OUT = os.path.join(ROOT, 'build', 'btlevt.asm')
OUT_SLPS = os.path.join(ROOT, 'build', 'btlevt_slps.asm')
# unreferenced SLPS functions (taken from tools/s2dnames.py SPILL) for messages reached only by pointer words
SPILL = []                                  # no resident space left; the English must fit the zone
TABLES = [(0x800D0CB8, 0x800D0F30)]         # (pointer, speaker) pairs
TAIL = 0x360                                # end of the zone: unpacker + pair table + buffer (btlp/btlevt_unpack.asm)
BUF = 256                                   # unpacked message buffer (BTLEVT_BUF_SIZE)
OUT_PAIRS = os.path.join(ROOT, 'build', 'btlevt_pairs.asm')
import bpe      # noqa: E402
NL = chr(10)
END = b'\xff\xf5'
ALIGN = 2                            # original strings are 4-aligned; the interpreter reads bytes, 4 does not fit the English


def data():
    return open(os.path.join(ROOT, 'data', 'psx', 'BTLP.BIN'), 'rb').read()


def messages(d):
    out = []
    p = ZONE[0]
    while p < ZONE[1]:
        if d[p - B] == 0:
            p += 1
            continue
        e = d.index(END, p - B) + 2 + B
        out.append((p, e))
        p = e
    return out


def refs(d):
    """-> {ram address: [('word', where) | ('addiu', where)]} for addresses inside the zone"""
    found = {}
    for o in range(0, len(d) - 3, 4):
        w = struct.unpack_from('<I', d, o)[0]
        if ZONE[0] <= w < ZONE[1] and any(t0 <= B + o < t1 for t0, t1 in TABLES):
            found.setdefault(w, []).append(('word', B + o))
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    hiv = {}
    for o in range(0, len(d) - 3, 4):
        ins = next(md.disasm(d[o:o + 4], B + o), None)
        if ins is None:
            continue
        ops = ins.operands
        hiv = {r: (v, n + 1) for r, (v, n) in hiv.items() if n < 3}   # a lui counts for 3 instructions only
        if ins.mnemonic == 'lui':
            hiv[ins.reg_name(ops[0].reg)] = ((ops[1].imm & 0xFFFF) << 16, 0)
        elif ins.mnemonic == 'addiu' and len(ops) == 3 and ops[1].type == capstone.mips.MIPS_OP_REG:
            s = ins.reg_name(ops[1].reg)
            if s in hiv:
                v = (hiv[s][0] + ops[2].imm) & 0xFFFFFFFF
                if ZONE[0] <= v < ZONE[1]:
                    assert hiv[s][0] == 0x800D0000, hex(B + o)
                    found.setdefault(v, []).append(('addiu', B + o))
    return found


def loose_refs(d):
    """addresses in the zone formed by ANY earlier lui (may be false positives): strings with such extra hits stay put"""
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    hiv, found = {}, {}
    for o in range(0, len(d) - 3, 4):
        ins = next(md.disasm(d[o:o + 4], B + o), None)
        if ins is None:
            continue
        ops = ins.operands
        if ins.mnemonic == 'lui':
            hiv[ins.reg_name(ops[0].reg)] = (ops[1].imm & 0xFFFF) << 16
        elif ins.mnemonic == 'addiu' and len(ops) == 3 and ops[1].type == capstone.mips.MIPS_OP_REG:
            r = ins.reg_name(ops[1].reg)
            if r in hiv and ZONE[0] <= (hiv[r] + ops[2].imm) & 0xFFFFFFFF < ZONE[1]:
                found.setdefault((hiv[r] + ops[2].imm) & 0xFFFFFFFF, set()).add(B + o)
    return found


def dec(d, a, e):
    out, i = [], a - B
    while i < e - B:
        c = d[i]
        if c == 0xFF:
            if d[i + 1] != 0xF5:
                out.append('<FF%02X>' % d[i + 1])
            i += 2
        elif 0x80 <= c <= 0x87:
            out.append(etext.glyph.get(((c & 7) << 8) | d[i + 1], '<G%03X>' % (((c & 7) << 8) | d[i + 1])))
            i += 2
        else:
            out.append(etext.glyph.get(c, '<G%02X>' % c))
            i += 1
    return ''.join(out)


def dump():
    """Queue the zone's rows in the canonical manual table."""
    import toolbelt
    d = data()
    toolbelt.route_gaps(toolbelt.rel_for(os.path.join(ROOT, 'data', 'psx', 'BTLP.BIN')),
                        [hex(a - B) for a, _e in messages(d)])
    print('btlevt: zone queued')


def codes(b):
    """control codes in order of a dialogue-encoded string (two-byte glyphs 80-87 xx skipped)"""
    out, i = [], 0
    while i < len(b) - 1:
        if b[i] == 0xFF:
            c = b[i + 1]
            out.append(c)
            i += 2 + 2 * E_PARAM_UNITS.get(c, 0)   # params belong to their code
        elif 0x80 <= b[i] <= 0x87:
            i += 2
        else:
            i += 1
    # LINE BREAKS and PAUSES are layout, not wording: the English breaks
    # and pauses where its own words need to, not where the Japanese did.
    # 0xF6 is this family's line move, 0x03 the dialogue newline, 0x05 a
    # pause. Everything else is wording and must match exactly.
    return sorted(c for c in out if c not in (0xF6, 0x03, 0x05))


def build():
    d = data()
    msgs = messages(d)
    rf = refs(d)
    import toolbelt
    merged = {r['pos']: (r['en'] or '').strip() for r in toolbelt.merged_rows('BTLP')}
    en = {i: merged.get(hex(a - B), '') for i, (a, e) in enumerate(msgs)}
    new = {}
    for i, (a, e) in enumerate(msgs):
        t = (en.get(i) or '').strip()
        if not etext.has_text(t):
            continue
        try:
            b = etext.encode(t, end=END)
        except ValueError as ex:
            raise SystemExit(f'btlevt: {i} {t!r}: {ex}')
        orig = bytes(d[a - B:e - B])
        if codes(b) != codes(orig):
            pass        # see btlp: a code difference is not a rendering problem
        for page in t.split('<FFFB><FFF7>'):
            lines = page.split('<FFF6>')
            if len(lines) > 4:
                # three visible lines + the fourth scroll line. The
                # interpreter waits when the 3x15-cell window fills; a
                # fifth line would need a second scroll and is outside the
                # page model. The Japanese ships for a page that needs more.
                print(f'btlevt: {i}: a page has {len(lines)} lines (max 4) '
                      f'- overflow, Japanese ships')
                b = bytes(d[a - B:e - B])
                break
            for ln in lines:
                w = vwf_wrap.text_width(ln)
                if w > 239:
                    raise SystemExit(f'btlevt: {i} line {ln!r} is {w} px wide (max 239)')
        new[i] = b
    # fixed: unreferenced messages keep their address and must fit their slot
    # --- byte-pair encoding of every message (btlp/btlevt_unpack.asm expands it) ---
    for i, b in new.items():
        if len(b) > BUF:
            raise SystemExit(f'btlevt: {i} is {len(b)} bytes unpacked (buffer {BUF})')

    # the ONE packer (bpe), not a copy of it: the format is decided in
    # exactly two places - bpe and btlp/btlevt_unpack.asm - and this
    # family only says which strings to pack. bpe.pack verifies every
    # string round-trips through its own mirror of the unpacker.
    packed, pairs = bpe.pack(dict(new))
    unpacked = new
    new = packed
    # (loose_refs() lists far-lui candidates; checked by hand 2026-10-05: all false positives - loop counters,
    #  struct offsets, registers changed after their lui - so only unreferenced strings stay in place)
    fixed = {i for i in new if not rf.get(msgs[i][0])}
    free = [[ZONE[0], ZONE[1] - TAIL]]           # BTLP zone minus the unpacker tail
    spill = [list(z) for z in SPILL]            # resident SLPS (word references only)
    place = {}

    def take(zones, n):
        for z in zones:
            q = (z[0] + ALIGN - 1) & ~(ALIGN - 1)
            if q + n <= z[1]:
                z[0] = q + n
                return q
        return None

    def carve(a, e):                            # remove [a, e) from the free list
        out = []
        for z in free:
            if e <= z[0] or a >= z[1]:
                out.append(z)
            else:
                if z[0] < a:
                    out.append([z[0], a])
                if e < z[1]:
                    out.append([e, z[1]])
        free[:] = out

    for i in fixed:
        a, e = msgs[i]
        if len(new[i]) > e - a:
            # overflow: cannot be re-pointed and does not fit its slot.
            # The Japanese ships for this one; the wording is a draft.
            new[i] = packed[i] = bytes(d[a - B:e - B])   # keep the Japanese
            print(f'btlevt: {i} does not fit its {e - a}-byte slot - '
                  f'overflow, Japanese ships')
        if e > ZONE[1] - TAIL:
            raise SystemExit(f'btlevt: fixed message {i} overlaps the unpacker tail')
        place[i] = a
        carve(a, a + len(new[i]))
    code = [i for i in new if i not in fixed and any(k == 'addiu' for k, _ in rf.get(msgs[i][0], []))]
    words = [i for i in new if i not in fixed and i not in code]
    for i in code:
        place[i] = take(free, len(new[i]))
        if place[i] is None:
            raise SystemExit(f'btlevt: out of space in the BTLP zone at message {i}')
    spilled = []
    for i in words:
        place[i] = take(free, len(new[i]))
        if place[i] is None:
            place[i] = take(spill, len(new[i]))
            spilled.append(i)
            if place[i] is None:
                raise SystemExit(f'btlevt: out of space (spill zones full) at message {i}')
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by tools/btlevt.py build - do not edit' + NL)
        o.write(f'.org {ZONE[0]:#x}{NL}    .fill {ZONE[1] - ZONE[0]:#x}, 0{NL}')
        for i in new:
            if i not in spilled:
                o.write(f'.org {place[i]:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in new[i]) + NL)
        for i in new:
            a, e = msgs[i]
            for kind, where in rf.get(a, []):
                if kind == 'word':
                    o.write(f'.org {where:#x}{NL}    .word {place[i]:#x}' + NL)
                else:
                    o.write(f'.org {where:#x}{NL}    .halfword {place[i] & 0xFFFF:#x}' + NL)
    with open(OUT_PAIRS, 'w', newline=NL) as o:
        o.write(';; generated by tools/btlevt.py build - byte pairs of the pair codes 01..87, E7..FE (in this order)' + NL)
        for x, y in pairs:
            o.write(f'    .byte {byte(x):#04x}, {byte(y):#04x}' + NL)
    with open(OUT_SLPS, 'w', newline=NL) as o:
        o.write(';; generated by tools/btlevt.py build - battle messages spilled into dead SLPS functions' + NL)
        for i in spilled:
            o.write(f'.org {place[i]:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in new[i]) + NL)
    used = max((place[i] + len(new[i]) for i in place), default=ZONE[0])
    print(f'btlevt: {len(pairs)} pair codes, {sum(len(b) for b in unpacked.values())} -> '
          f'{sum(len(b) for b in new.values())} bytes, strings end {used:#x} (tail {ZONE[1] - TAIL:#x})')
    print(f'btlevt: {len(new)}/{len(msgs)} translated, '
          f'{len(spilled)} spilled to SLPS ({sum(len(new[i]) for i in spilled)} bytes) -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
