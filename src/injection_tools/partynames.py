"""Party member full names (family / given) in SLPS_005.00: the STATUS screen header, name inserts of the script interpreters.

  python src/injection_tools/partynames.py     QA + generate build/partynames.asm (included by main.asm)

Origin: a table of 10-byte slots at 0x80049040 (index * 10), FF01-terminated glyph strings: 0 = "アトラス" (the
company), 1 = "主人公" (the protagonist's placeholder), then eight family / given pairs (園村 麻希, 上杉 秀彦,
南条 圭, 稲葉 正男, 桐島 英理子, 綾瀬 優香, 黛 ゆきの, 城戸 玲司). Read through the dialogue interpreters'
name inserts (cases 7 / 15 / 16 of the message machine: surname / given name), i.e. as text.

Wording is ported from the PSP US build's own party-name table (data/extracted_text/psp_us/EBOOT.tsv: one full name per
member - "Maki Sonomura" - immediately in front of that build's Japanese copy of this same table, so the
member order is the PSX pairs' order and nothing is typed in here). A full name is western order, the slots
are the PSX's family-then-given, so the given name is its first word and the family name the rest; every pair
that glossary.tsv also knows (its 'card' domain) is checked against it, and the two non-member slots take
their words from the glossary's 'party' domain. Builds read the generated
SLPS_005.00 rows, not the PSP extract.

Encoding: the dialogue's VWF letters (ASCII + 0x68), like every dialogue string and like retail, whose slots
hold dialogue-encoded Japanese (82 4b = 南条). THE CASE IS THE TRANSLATION'S, never this tool's: a byte
0x88..0xE6 is one VWF character (the interpreter classifies only 0x80..0x87 as a two-byte glyph), so 'A'
(0xA9) and 'a' (0xC9) are both single letters and a name is written exactly as the source spells it.

The message machine prints these slots through the dialogue engine's NAME stub
(message codes 7 / 15 / 16, base + 20 * (id - 1), the given name at + 10), where every byte is looked up in
vwf_small_map first - that map serves the small-font insert tables (Persona / demon / item / arcana names),
where 0xA9 is 'D' and 0xC9 is '9'. The engine's glyph-map entry, vwf_glyph_map_party, is therefore a wrapper
that tests the insert pointer against this table (src/asm/slps_005.00/party_name_vwf.asm): inside it the byte IS a VWF character
and passes through, everywhere else the small map applies. Without that test the capitals shifted (A -> D)
and 'a' came out as '9'.

Order: the PSP prints a western full name ("Kei Nanjo"), the PSX slots are
family-then-given, so the STATUS page's name row swaps the two opcodes and prints the given name first
(name_row_patches: the row is <FF0F> id 00 <FF07> id in retail, one template per overlay). The DATA is never
rearranged to fake an order: the family name stays in the family slot and the given name in the given one -
only the row that displays them reads them the other way round.

Capacity: the retail insert prints 5 characters (ori v1,zero,5 -> sb v1,0x35(s1)); the count glue below
raises it to 8 for the 1-byte English letters the slot holds. A part of a name longer than that is written
as its initial and a full stop (Kirishima -> "K."), the same rule for every name.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext      # noqa: E402
import strlib     # noqa: E402
import toolbelt   # noqa: E402

ROOT = etext.ROOT
REL = 'SLPS_005.00'
BASE = 0x80049040            # PARTY_NAMES_ADDR (addresses.inc; the VWF wrapper tests this range)
SLOT = 10                    # bytes per slot (9 letters + FF 01 would fit)
SLOTS = 18                   # company, protagonist, then 8 family / given pairs
FIRST_PAIR = 2
MAXCHARS = 8                 # characters the name inserts print (the count glue below)
SLPS_BASE = 0x8000F800       # file offset = VA - SLPS_BASE
OUT = os.path.join(ROOT, 'build', 'partynames.asm')
UA = chr(0x3000)             # the full-width space of a Japanese full name
WIDE_SPACE = chr(0xE000)     # the font's 8 px blank (make_vwf_font.WIDE_SPACE), the row's separator


def retail_slots():
    """[(index, the slot's Japanese text)] - the table as retail stores it."""
    d = open(os.path.join(ROOT, 'data', 'psx', REL), 'rb').read()
    out = []
    for i in range(SLOTS):
        off = BASE + SLOT * i - SLPS_BASE
        out.append((i, etext.decode(d[off:off + SLOT].split(b'\xff')[0])))
    return out


def psp_full_rows(n):
    """The n PSP-US full names and source offsets, in member order."""
    rows = sorted((int(r['pos'], 16), r['text'].strip())
                  for r in toolbelt.read_extracted('psp_us', 'EBOOT'))
    ja = dict(retail_slots())
    # The English table sits right in front of this build's Japanese copy of
    # the same table; that copy is what identifies it (company slot, then the
    # protagonist's within a slot count of it).
    anchor = [p for p, t in rows if t == ja[0] + '<FF01>'
              and any(0 < q - p < 0x200 and t2 == ja[1] + '<FF01>' for q, t2 in rows)]
    if len(anchor) != 1:
        toolbelt.fail(f'partynames: the PSP US party-name table is not unique: {anchor}')
    full = [(p, t) for p, t in rows if p < anchor[0]
            and re.fullmatch(r"[A-Z][\w.'-]*(?: [A-Z][\w.'-]*)+<FF01>", t)]
    names = [(p, re.sub(r'<FF01>$', '', t)) for p, t in full[-n:]]
    if len(names) != n:
        toolbelt.fail(f'partynames: {len(names)} full name(s) in front of the PSP table, want {n}: {names}')
    return names


def psp_full_names(n):
    return [text for _pos, text in psp_full_rows(n)]


def members():
    """[(slot of the family name, English family, English given)]"""
    ja = dict(retail_slots())
    pairs = [(i, ja[i], ja[i + 1]) for i in range(FIRST_PAIR, SLOTS, 2)]
    rows = {r['pos']: r for r in toolbelt.merged_rows(REL)}
    card = strlib.glossary('card')
    out = []
    for i, jf, jg in pairs:
        family = (rows.get(hex(BASE + i * SLOT - SLPS_BASE), {}).get('en') or '').strip()
        given = (rows.get(hex(BASE + (i + 1) * SLOT - SLPS_BASE), {}).get('en') or '').strip()
        if not family or not given:
            toolbelt.fail(f'partynames: missing generated or manual name at slot {i}')
        name = given + ' ' + family
        known = card.get(jf + UA + jg)
        if known is not None and known != name:
            toolbelt.fail(f'partynames: {jf + UA + jg} is {known!r} in glossary.tsv, {name!r} in the PSP table')
        out.append((i, family, given))
    return out


def fit(part, i):
    """The insert prints MAXCHARS characters; a longer part keeps its initial."""
    if len(part) <= MAXCHARS:
        return part
    print(f'partynames: slot {i} {part!r} is {len(part)} characters, the insert prints {MAXCHARS}: using {part[0] + "."!r}')
    return part[0] + '.'


def enc(t):
    out = etext.encode(t)          # dialogue encoding, ends FF 01
    if len(out) > SLOT:
        toolbelt.fail(f'partynames: {t!r} needs {len(out)} bytes (slot {SLOT})')
    return out + bytes(SLOT - len(out))


def table():
    """[(slot index, the text it holds)] - the 18 slots, derived."""
    ja = dict(retail_slots())
    party = strlib.glossary('party')
    words = {0: party[ja[0]], 1: party[ja[1]]}
    for i, family, given in members():
        words[i] = fit(family, i)
        words[i + 1] = fit(given, i + 1)
    missing = [i for i in range(SLOTS) if not words.get(i)]
    if missing:
        toolbelt.fail(f'partynames: no wording for slot(s) {missing}')
    return [(i, words[i]) for i in range(SLOTS)]


# The count-fix glue's home per overlay: the *_PARTY_COUNT_FIX_ADDR dead
# functions in addresses.inc. Read, never restated (toolbelt.asm_equ is the
# one place these live). Check other claimed spans before emitting the glue:
# armips silently overwrites overlapping .org claims.
DEAD = {nm: toolbelt.asm_equ(f'{nm}_PARTY_COUNT_FIX_ADDR') for nm in ('ADV', 'DNG', 'S2D')}
# Every other feature's claimed span in that overlay: a glue address inside one
# of them is the same silent .org overlap, whether or not the sizes match today.
# (*_SIZE is a size, the others are end addresses - both live in addresses.inc.)
for _nm, _addr in DEAD.items():
    _claims = ((f'{_nm}_SF_EXTENSION', f'{_nm}_SF_DATA_ADDR', f'{_nm}_SF_EXTENSION_END'),) if _nm == 'ADV' else (
        (f'{_nm}_SF_ROW', f'{_nm}_SF_ROW_ADDR', f'{_nm}_SF_ROW_SIZE'),
        (f'{_nm}_SF_HELP', f'{_nm}_SF_HELP_ADDR', f'{_nm}_SF_HELP_SIZE'),
        (f'{_nm}_ITEM_DATA', f'{_nm}_ITEM_DATA_ADDR', f'{_nm}_ITEM_DATA_END'))
    for _label, _a, _b in _claims:
        _start = toolbelt.asm_equ(_a)
        _b_val = toolbelt.asm_equ(_b)
        _end = _start + _b_val if _b.endswith('SIZE') else _b_val
        if _start <= _addr < _end:
            raise SystemExit(
                f'partynames: {_nm}_PARTY_COUNT_FIX_ADDR is {_addr:#x}, inside '
                f'{_label} ({_start:#x}..{_end:#x}) - give the count glue its own '
                f'dead function (addresses.inc) instead of overwriting another feature.')
    if _addr == toolbelt.asm_equ(f'{_nm}_ITEM_NAME_STUB'):
        raise SystemExit(
            f'partynames: {_nm}_PARTY_COUNT_FIX_ADDR is {_addr:#x}, the item-name '
            f'stub - give the count glue its own dead function (addresses.inc).')


# The status page's name row, as the engine spells it: <FF0F> id 00 <FF07> id
# (code 15 = the member's family name, code 7 = the given name - the engine's
# dispatch reads PARTY_NAMES_ADDR + 10 for code 7 and the base for code 15; see
# bgreset.c, "7, 15, 16  a member's surname, first name, or both"). Retail PSX
# writes it family-first, the PSP prints "Kei Nanjo": the ROW swaps the two
# opcodes, the DATA keeps family / given in their own slots (nothing is moved
# between them). The template is unique per overlay - both parameters are the
# same placeholder, and the game copies it into its RAM script buffer at
# 0x800B186C, filling the two id bytes (g_char_msg_key / g_char_msg_key2).
NAME_ROW_RE = re.compile(rb'\xff\x0f(.)\x00\xff\x07\1\xff\x01', re.S)


def name_row_patches():
    """Write each overlay's given-first name row -> build/partynames_row_<ovl>.asm."""
    nl = chr(10)
    for nm in ('ADV', 'DNG', 'S2D'):
        rel = nm + '.BIN'
        d = open(os.path.join(ROOT, 'data', 'psx', rel), 'rb').read()
        hits = list(NAME_ROW_RE.finditer(d))
        if len(hits) != 1:
            toolbelt.fail(f'partynames: the status name row is not unique in {rel} ({len(hits)} hits)')
        m = hits[0]
        # The separator is ONE byte: the row is a 9-byte script (code, id,
        # gap, code, id, FF 01), so a second space would push the end code out.
        # The retail byte is the engine's glyph 0, a FULL-WIDTH space (Japanese
        # layouts measure with it, and vwf_name_map keeps glyph 0 at 16 px);
        # the English row takes the font's 8 px blank instead - half that
        # width, one code, blank (make_vwf_font.WIDE_SPACE).
        body = (b'\xff\x07' + m.group(1) + etext.encode(WIDE_SPACE, end=None)
                + b'\xff\x0f' + m.group(1))
        with open(os.path.join(ROOT, 'build', f'partynames_row_{nm.lower()}.asm'), 'w', newline=nl) as o:
            o.write(f';; generated by tools/partynames.py - do not edit ({nm}: the status name row, given name first){nl}')
            o.write(f'.org {toolbelt.file_va(rel, m.start()):#x}{nl}')
            o.write('    .byte ' + ', '.join(f'0x{b:02X}' for b in body) + nl)


def overlay_patches():
    """name-insert opcodes: 5 -> 8 characters, except the hero (id 1): his typed name is 5 two-byte glyphs filling the whole
    10-byte slot without terminator. At the two `sb v1,0x35(s1)` that store the
    count (delay slot = the following addiu v0,v0,-1, so the glue sees v0 = id - 1) a jal to dead-function glue sets 5 for the hero."""
    import struct
    for nm in ('ADV', 'DNG', 'S2D'):
        d = open(os.path.join(ROOT, 'data', 'psx', nm + '.BIN'), 'rb').read()
        w = struct.unpack_from('<%dI' % (len(d) // 4), d, 0)
        nl = chr(10)
        lines = [';; generated by tools/partynames.py - do not edit']
        for i, x in enumerate(w):
            if x == 0x34030005 and any(w[j] == 0xA2230035 for j in range(i + 1, min(i + 12, len(w)))):
                lines.append('.org %#x%s    .byte %d' % (0x800643C4 + 4 * i, nl, MAXCHARS))
        sites = [0x800643C4 + 4 * i for i, x in enumerate(w) if x == 0xA2230035 and w[i + 1] == 0x2442FFFF and w[i - 1] == 0x24849040]
        assert len(lines) == 4 and len(sites) == 2, (nm, lines, sites)
        for a in sites:
            lines.append('.org %#x%s    jal     party_count_fix_%s' % (a, nl, nm.lower()))
        g = DEAD[nm]
        lines += ['.org %#x' % g, '.area 0x50',
                  'party_count_fix_%s:                ; v0 = id - 1 (hero = 0), v1 = 8' % nm.lower(),
                  '    li      t1, %d' % MAXCHARS,
                  '    bnez    v0, @@store',
                  '    nop',
                  '    li      t1, 5',
                  '@@store:',
                  '    jr      ra',
                  '    sb      t1, 0x35(s1)',
                  '.endarea']
        open(os.path.join(ROOT, 'build', 'partynames_%s.asm' % nm.lower()), 'w', newline=nl).write(nl.join(lines) + nl)


def main():
    overlay_patches()
    name_row_patches()
    rows = table()
    with open(OUT, 'w', newline=chr(10)) as o:
        o.write(';; generated by tools/partynames.py - do not edit' + chr(10))
        for i, t in rows:
            o.write(f'; {i} {t}{chr(10)}.org {BASE + SLOT * i:#x}{chr(10)}    .byte ' + ', '.join(f'0x{x:02X}' for x in enc(t)) + chr(10))
    print('partynames: %d slots -> %s' % (len(rows), OUT))
    print('partynames: ' + ', '.join(t for _i, t in rows if t))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
