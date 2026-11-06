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
that tests the insert pointer against this table (src/asm/slps_005.00/party_name_vwf.asm): inside it the
bytes go through vwf_name_map (this build's ASCII + 0x68 pass unchanged, a legacy save's retail glyph codes
map exactly like typed names), everywhere else the small map applies. Without that test the capitals shifted
(A -> D) and 'a' came out as '9'.

Order: the PSP prints a western full name ("Kei Nanjo"), the PSX slots are
family-then-given, so the STATUS page's name row swaps the two opcodes and prints the given name first
(name_row_patches: the row is <FF0F> id 00 <FF07> id in retail, one template per overlay). The DATA is never
rearranged to fake an order: the family name stays in the family slot and the given name in the given one -
only the row that displays them reads them the other way round.

Capacity: the retail insert prints 5 characters. The hero's family / given slots now hold up to 8 compact
VWF bytes + FF 01 (name/long_names.asm), and every party slot is FF-terminated too, so the overlay stubs call
the resident name_count_store helper (slps_005.00/name_count.asm): a compact slot (first byte 0x88 or above)
stores its real glyph count - the FF position, never padded to eight - and a legacy all-glyph slot keeps
retail's five. Code 16's second half (MSG_SURNAME) calls name_count_surname, the same scan on the +10 slot
plus the blank separator that branch prints before it; the DNG field-script name print gets the same scan
through a proxy (it stops at FF itself, so the scan there only picks the wide bound). A name longer than
eight is written as its initial and a full stop (Kirishima -> "K."), the same rule for every name.
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
    """The two `sb v1,0x35(s1)` that store a name insert's glyph count, per
    overlay. Each is replaced by a `jal party_count_fix_<ovl>` whose delay
    slot is the retail `addiu v0,v0,-1`, so the resident name_count_store
    helper sees v0 = id - 1 exactly as the retail address math does. The two
    `ori v1,zero,5` in front are left as they are - the store they feed is
    gone, and v1 is recomputed by the following instruction.

    Code 16 prints the first half and then re-enters the message machine for
    the second (MSG_SURNAME), which stores its own hardcoded 5 with
    `ori v0,zero,5; sb v0,0x35(s1)`. That branch prints a blank separator
    first, so it calls the resident name_count_surname (+10 slot, count + 1).

    DNG's field-script interpreter calls FieldMsgPrint(0x80075428, a1 = 5)
    directly in three places. FieldMsgPrint stops at MSG_END (0xFF), so its
    count only has to cover a compact slot: a proxy in the rest of the count
    stub's dead function scans a0's 10-byte slot for FF, sets a1 = 8 / 5, and
    tail-jumps to FieldMsgPrint. It uses only t0-t2 and leaves a0 alone."""
    import struct
    base = 0x800643C4
    nl = chr(10)
    fmp = toolbelt.asm_equ('DNG_FIELD_MSG_PRINT_ADDR')
    fmp_jal = 0x0C000000 | ((fmp >> 2) & 0x03FFFFFF)
    for nm in ('ADV', 'DNG', 'S2D'):
        d = open(os.path.join(ROOT, 'data', 'psx', nm + '.BIN'), 'rb').read()
        w = struct.unpack_from('<%dI' % (len(d) // 4), d, 0)
        lines = [';; generated by tools/partynames.py - do not edit']
        sites = [base + 4 * i for i, x in enumerate(w)
                 if x == 0xA2230035 and w[i + 1] == 0x2442FFFF and w[i - 1] == 0x24849040]
        if len(sites) != 2:
            toolbelt.fail(f'partynames: {nm} has {len(sites)} name-count stores, want 2')
        for a in sites:
            lines.append('.org %#x%s    jal     party_count_fix_%s' % (a, nl, nm.lower()))
        # Code 16's MSG_SURNAME continuation: `lbu v1,(s2); ...; ori v0,zero,5;
        # sb v0,0x35(s1); addiu v1,v1,-1` (the id is already in v1).
        surname = [base + 4 * i for i, x in enumerate(w)
                   if x == 0x34020005 and w[i + 1] == 0xA2220035
                   and w[i + 2] == 0x2463FFFF and w[i - 1] == 0xAE220000
                   and w[i - 3] == 0x92430000]
        if len(surname) != 1:
            toolbelt.fail(f'partynames: {nm} has {len(surname)} MSG_SURNAME count stores, want 1')
        lines += ['.org %#x' % surname[0],
                  '    jal     name_count_surname',
                  '    addiu   v0, v1, -1']
        lines += ['.org %#x' % DEAD[nm],
                  'party_count_fix_%s:' % nm.lower(),
                  '    j       name_count_store',
                  '    nop']
        if nm == 'DNG':
            hits = [base + 4 * i for i, x in enumerate(w) if x == fmp_jal]
            if len(hits) != 3:
                toolbelt.fail(f'partynames: DNG has {len(hits)} FieldMsgPrint name calls, want 3')
            for a in hits:
                if w[(a - base) // 4 + 1] != 0x34050005:
                    toolbelt.fail(f'partynames: {a:#x} does not pass a1 = 5 to FieldMsgPrint')
                lines.append('.org %#x%s    jal     dng_name_print' % (a, nl))
            lines += ['.org %#x' % toolbelt.asm_equ('DNG_NAME_PRINT_ADDR'),
                      '.area %d' % (toolbelt.asm_equ('DNG_NAME_PRINT_END') - toolbelt.asm_equ('DNG_NAME_PRINT_ADDR')),
                      'dng_name_print:',
                      '    move    t0, a0',
                      '    li      t1, 10',
                      '    li      a1, 5',
                      '@@scan:',
                      '    lbu     t2, 0(t0)',
                      '    beq     t2, 0xFF, @@wide',
                      '    addiu   t0, t0, 1',
                      '    addiu   t1, t1, -1',
                      '    bnez    t1, @@scan',
                      '    nop',
                      '    b       @@go',
                      '    nop',
                      '@@wide:',
                      '    li      a1, 8',
                      '@@go:',
                      '    j       %#x' % fmp,
                      '    nop',
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
