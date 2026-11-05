"""Skill names of SLPS_005.00 (battle skill menu, field Persona menus, battle messages ...).

  python tools/skills.py dump     write/refresh translation/manual/SLPS_005.00/SKILLS.tsv (keeps the `en` and `note` columns)
  python tools/skills.py build    QA + generate build/skills.asm (included by main.asm, SLPS section)

Layout: 242 records of 0x14 bytes from 0x80047D58 (ids 163-242 = demon/special attacks, e.g. Twinkle Punch) (id 1 = record 0; the game indexes them as 0x80047D44 + id*0x14).
The name is the first 10 bytes, single-byte glyph indices of the 8x12 small font (see tools/items.py), FF-terminated
unless it is exactly 10 glyphs; bytes +0x0A..+0x10 are data (element, power, cost ...), +0x11..+0x13 unused.

English names are the official PSP ones (glossary.tsv). The battle skill menu
draws them with the small-font VWF in a slot `SKILL_MENU_STRIDE` (24) bytes
wide, so the storage bound is 23 glyphs (`MAXLEN`). The real display bound is
the width both retail columns leave between them: the two list-A columns start
144 px apart and the patch has always drawn a 15-cell (120 px) name in each, so
`NAME_PX` is 120. A name is accepted by width, not by a character count. The
resident copy helper writes the name and an FF terminator, so the menu's
SKILL_MAXLEN-glyph descriptor count never draws blank padding. Names longer than 10
characters keep their first 10 characters in the record (so screens that are
not patched yet show a clean truncation); the rest (the "tail") goes to the
record's unused bytes +0x11..+0x13: up to 3 glyphs inline (FF-terminated when
shorter), longer tails as FE, offset into `skill_tails_x` (build/skill_tails.asm,
tail glyphs + FF). The resident helper `skill_name_copy`
(slps_005.00/skill_names.asm) assembles the full name. Screens patched to use the helper: see HANDOFF.md.
`en` characters: A-Z a-z 0-9 space - / : . '   (lowercase, . and ' are redrawn kana cells, tools/smallfont_lc.py)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext   # noqa: E402
import strlib  # noqa: E402
import items   # noqa: E402
import smallfont_lc  # noqa: E402
import toolbelt  # noqa: E402

ROOT = etext.ROOT
BASE = 0x80010000 - 0x800
FIRST = 0x80047D58
STRIDE = 0x14
COUNT = 242                        # 162 player skills + 80 enemy / special attacks (ids 163-242); 243+ is other data
FIELD = 10
MAXLEN = toolbelt.asm_equ('SKILL_MAXLEN')   # slot capacity from addresses.inc (23 glyphs + FF)
NAME_PX = 120                      # list-A columns are 144 px apart; both lists already draw 120 px
SPARE = 0x11                       # 3 unreferenced bytes per record (+0x11..+0x13)
TSV = os.path.join(ROOT, 'translation', 'manual', 'SLPS_005.00', 'SKILLS.tsv')
OUT = os.path.join(ROOT, 'build', 'skills.asm')
OUT_X = os.path.join(ROOT, 'build', 'skill_tails.asm')     # included by slps_005.00/skill_names.asm
NL = chr(10)


def records():
    d = open(os.path.join(ROOT, 'data', 'psx', 'SLPS_005.00'), 'rb').read()
    out = []
    for i in range(COUNT):
        a = FIRST + STRIDE * i
        f = d[a - BASE:a - BASE + FIELD]
        out.append((i, a, ''.join(etext.glyph.get(x, '<%02X>' % x) for x in f.split(b'\xff')[0])))
    return out


def read_tsv(manual_only=False):
    return {k: (en, note) for k, (ja, en, note)
            in strlib.read(TSV, 'SKILLS.tsv', manual_only).items()}


def generated_map():
    """{idx: (ja, en)} of the PSP-generated table, for dump trimming."""
    return {k: (ja, en) for k, (ja, en, note)
            in strlib.generated('SKILLS.tsv').items() if en.strip()}


def dump():
    old = read_tsv(manual_only=True)
    auto = generated_map()
    rows = []
    for i, a, ja in records():
        en, note = old.get(i, ('', ''))
        port = auto.get(i)
        if not en and port and port[0] == ja:
            continue
        rows.append(f'{i}\t{a:08X}\t{ja}\t{en}\t{note}')
    if not rows:
        if os.path.exists(TSV):
            os.remove(TSV)
    else:
        with open(TSV, 'w', encoding='utf-8', newline=NL) as o:
            o.write('idx\tram\tja\ten\tnote' + NL)
            o.write(NL.join(rows) + NL)
    print('wrote', TSV)


def glyph(c):
    if 'a' <= c <= 'z' or c in smallfont_lc.PUNCT_CODES:
        return smallfont_lc.code(c)
    return items.glyph(c)


def encode_glyphs(i, t):
    """Encode small-font glyphs without imposing another family's buffer size."""
    for c in t:
        if not ('A' <= c <= 'Z' or 'a' <= c <= 'z' or '0' <= c <= '9' or c in " .-/:'"):
            raise SystemExit(f'skills: {i} {t!r}: {c!r} is not in the small font')
    return bytes(glyph(c) for c in t)


def encode(i, t):
    """Encode one skill name within skill_name_copy's fixed output buffer."""
    if len(t) > MAXLEN:
        raise SystemExit(f'skills: {i} {t!r} is {len(t)} chars, max {MAXLEN}')
    return encode_glyphs(i, t)


def width_px(t):
    """Rendered width of a skill name in the small-font VWF, in pixels."""
    import smallfont_vwf
    return smallfont_vwf.line_px(t)


def check_width(i, t):
    """The screen's own limit: the columns are 144 px apart and both lists
    have always drawn a 120 px name. Storage (MAXLEN) is not the display cap."""
    px = width_px(t)
    if px > NAME_PX:
        raise SystemExit(f'skills: {i} {t!r} is {px}px, max {NAME_PX}px')
    return px


def append_tail(bank, tail):
    """Append a terminated tail without crossing the next resident owner."""
    room = toolbelt.asm_equ('SKILL_TAILS_SIZE')
    start = toolbelt.asm_equ('SKILL_TAILS_ADDR')
    next_owner = toolbelt.asm_equ('AFF_FREE2_ADDR')
    if start + room != next_owner or room > 0x100:
        raise SystemExit('skills: tail bank boundary/offset encoding is inconsistent')
    entry = tail + b'\xff'
    previous = bank.find(entry)
    if previous >= 0:
        return previous
    if len(bank) + len(entry) > room:
        raise SystemExit(f'skills: full skill tails need {len(bank) + len(entry)} bytes; '
                         f'{room} owned before the next resident code')
    offset = len(bank)
    bank.extend(entry)
    return offset


def vwf_ownership(ids):
    """Bit per 1-based skill ID whose English record was actually written."""
    if toolbelt.asm_equ('SKILL_COUNT') != COUNT:
        raise SystemExit('skills: assembly skill count does not match the record scanner')
    bits = bytearray((COUNT + 1 + 7) // 8)
    for ident in ids:
        if not 1 <= ident <= COUNT:
            raise ValueError(f'skill ID {ident} outside 1..{COUNT}')
        bits[ident >> 3] |= 1 << (ident & 7)
    return bytes(bits)


def pack_tails(tails):
    """Allocate complete tails longest first so terminated suffixes share bytes."""
    bank, offsets = bytearray(), {}
    for tail in sorted(set(tails), key=lambda value: (-len(value), value)):
        offsets[tail] = append_tail(bank, tail)
    return bank, offsets


def build():
    en = read_tsv()
    planned = [(i, a, en.get(i, ('', ''))[0].strip()) for i, a, _ja in records()]
    for i, _a, text in planned:
        if text:
            check_width(i, text)
    encoded = {i: encode(i, text) for i, _a, text in planned if text}
    x, offsets = pack_tails(b[FIELD:] for b in encoded.values() if len(b) > FIELD + 3)
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by tools/skills.py build - do not edit' + NL)
        n = nl = 0
        for i, a, t in planned:
            if not t:
                continue
            b = encoded[i]
            head = b[:FIELD]
            if len(b) < FIELD:
                head += b'\xff'
            head += bytes(FIELD - len(head))
            o.write(f'; {i + 1} {t}{NL}.org {a:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in head) + NL)
            tail = b[FIELD:]
            if tail:
                nl += 1
                if len(tail) <= 3:
                    spare = (tail + b'\xff\x00\x00')[:3]
                else:
                    spare = bytes([0xFE, offsets[tail], 0])
                o.write(f'.org {a + SPARE:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in spare) + NL)
            n += 1
    with open(OUT_X, 'w', newline=NL) as o:
        o.write(';; generated by tools/skills.py build - tails longer than the 3 spare bytes (offsets from skill_tails_x)' + NL)
        if x:
            o.write('    .byte ' + ', '.join(f'0x{c:02X}' for c in x) + NL)
    print(f'skills: {n}/{COUNT} translated, {nl} long names ({len(x)} bytes overflow) -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
