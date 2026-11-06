"""Script-style messages embedded in the ADV / DNG overlays (outside the E files): `FF 55 00 00 <ptr>` text commands.

  python tools/scriptmsg.py     write build/scriptmsg_adv.asm, build/scriptmsg_dng.asm (included in the overlay sections of main.asm)

The command has 3 text targets in ADV.BIN and 2 in DNG.BIN. S2D's 61 script boxes
are handled by s2d.py.
The slots are tiny, and the pointer words sit inside the command stream; the
wording comes from the manual / generated rows at the message's file offset.
English that does not fit relocates to a cave and the FF55 pointer word is
repointed. ADV's cave is intra-file (CAVE); DNG's is in the overlay extension
(DNG_SCRIPTMSG_ADDR..DNG_SCRIPTMSG_LIMIT, between the dialogue glue and the
spill window), which the build loads like the glue itself.
The name-insert head (`<FF09><12><00>` - code + item id, `<FF0A><73>` - code +
skill id) is part of the row like any other control code: the en cell carries
the source's literal tokens wherever the PSP-US wording puts the name. QA
compares the encoded row against the binary's own head bytes, so a mistyped id
fails loud instead of shipping a different item.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext   # noqa: E402
import strlib   # noqa: E402

ROOT = etext.ROOT
B = 0x800643C4
NL = chr(10)
# Control codes whose next bytes are a name-insert id, not text. DNG's
# script dispatches FF09 to the item-name printer (2 id bytes) and FF0A to
# skill_name_copy (1 id byte) - see dng/vwf_script.asm.
NAME_PARAMS = {0x09: 2, 0x0A: 1}
# Verified intra-file zero caves (zeros + no refs + no other claimants).
# DNG.BIN's tail has pointers into it: no cave there until surveyed.
CAVE = {'ADV': (0x58270, 160)}
# Overlay extensions that are zero by construction: an .org past the image
# end is zero-filled by armips, and the generated asm asserts the range
# against the neighbouring blocks. DNG's relocated messages live here.
EXT_CAVE = {'DNG': ('DNG_SCRIPTMSG_ADDR', 'DNG_SCRIPTMSG_LIMIT', 'DNG_SPILL_ADDR')}
# (overlay, RAM address, number of original bytes kept before the text (name codes))
MSGS = [
    ('ADV', 0x800B6C58, 0),
    ('ADV', 0x800B6C7C, 0),
    ('ADV', 0x800B6CA4, 0),
    ('DNG', 0x8009A18C, 4),
    ('DNG', 0x8009A1B4, 3),
]


def _norm_key(t):
    t = re.sub(r'(<FF0[124]>)+$', '', t).strip('　 ')
    return t


def messages(d, params=None):
    """Every `FF 55 00 00 <ptr>` embedded-message command of an overlay as
    [(file offset, decoded text)] - the mechanical scan behind MSGS.
    The extraction authority scans the same spots: a row's position must
    exist in its rel's full scan or stale detection rejects the row.
    `params` is the overlay's name-insert argument table (NAME_PARAMS for
    DNG, whose FF09/FF0A ids are not text)."""
    out = []
    i = 0
    while True:
        i = d.find(b'\xff\x55\x00\x00', i)
        if i < 0:
            break
        off = int.from_bytes(d[i + 4:i + 8], 'little') - B
        if 0 <= off < len(d) - 2:
            e = d.find(b'\xff\x01', off)
            if 0 <= e < off + 0x200:
                out.append((off, etext.decode(d[off:e + 2], params)))
        i += 4
    return out


def _assemble(text):
    """The message bytes: the row encodes whole, inserts and all."""
    return etext.encode(text, end=b'\xff\x02\xff\x01')


def head_ids(text):
    """[(code, id)] of the row's name-insert heads (static script data:
    FF09 carries a 16-bit item id, FF0A an 8-bit skill id)."""
    out = []
    for m in re.finditer(r'<FF(09|0A)>((?:<[0-9A-Fa-f]{2}>)+)', text):
        code = int(m.group(1), 16)
        raw = bytes(int(x, 16) for x in re.findall(r'<([0-9A-Fa-f]{2})>', m.group(2)))
        want = {0x09: 2, 0x0A: 1}[code]
        if len(raw) != want:
            raise SystemExit(f'scriptmsg: FF{code:02X} takes {want} parameter '
                             f'byte(s), got {len(raw)}: {m.group(0)}')
        out.append((code, raw[0] | (raw[1] << 8 if code == 0x09 else 0)))
    return out


def _record_name(code, ident):
    """The name the insert prints: the id is static, so the line is measured
    with THIS name - there is no worst case to reserve (insert_widths.tsv is
    for inserts whose parameter is written at run time)."""
    import name_tails
    if code == 0x09:
        rows = name_tails.item_rows()
    else:
        import slps
        import toolbelt
        first = slps.SK_FIRST - slps.BASE
        rows = []
        for r in toolbelt.merged_rows(slps.REL):
            pos = int(r['pos'], 16)
            if (first <= pos < first + slps.SK_STRIDE * slps.SK_COUNT
                    and not (pos - first) % slps.SK_STRIDE):
                t = (r.get('en') or '').strip()
                if t:
                    rows.append(((pos - first) // slps.SK_STRIDE + 1, t))
    name = dict(rows).get(ident)
    if not name:
        raise SystemExit(f'scriptmsg: insert id {ident} has no English name')
    return name


def check_lines(text, where):
    """THE BOX RULE at the message's only write: every authored line holds
    the box, with each insert measured as the name its static id prints."""
    import vwf_wrap
    shown = text
    for code, ident in head_ids(text):
        shown = shown.replace(_insert_token(code, ident), _record_name(code, ident))
    for line in (l for l in shown.split('<FF03>') if l.strip()):
        px = vwf_wrap.text_width(line)
        if px > vwf_wrap.BOX_WIDTH:
            raise SystemExit(f'scriptmsg: {where} line {px}px > '
                             f'{vwf_wrap.BOX_WIDTH}px: {line!r}')


def _insert_token(code, ident):
    """The row spelling of one insert head."""
    if code == 0x09:
        return f'<FF09><{ident & 0xFF:02X}><{ident >> 8:02X}>'
    return f'<FF0A><{ident:02X}>'


def _cave(ovl, d):
    """(file offset, size) of the relocation cave for `ovl`; a cave in the
    file's extension has no retail bytes to check - the assembler fills
    .org holes with zeros and the generated asm asserts the range."""
    if ovl in CAVE:
        base, size = CAVE[ovl]
        assert d[base:base + size] == bytes(size), f'scriptmsg: {ovl} cave not zeroed'
        return base, size
    if ovl in EXT_CAVE:
        addr, limit, stop = (toolbelt.asm_equ(n) for n in EXT_CAVE[ovl])
        base, size = addr - B, limit - addr
        if base < len(d):
            raise SystemExit(f'scriptmsg: {ovl} extension cave starts inside the '
                             f'retail image ({base:#x} < {len(d):#x})')
        if limit > stop:
            raise SystemExit(f'scriptmsg: {ovl} cave {limit:#x} crosses {stop:#x}')
        return base, size
    return None


def port_embedded():
    """PORT side: overlay-embedded messages whose Japanese matches a story
    box take that box's ported English (this matching is porter logic -
    builders never match text). Writes rows at the MSGS spots."""
    import toolbelt

    def key(t):
        return _norm_key(t)

    story = {}                     # normalized ja -> (rel, pos)
    for f in ('E0', 'E1', 'E2', 'E3'):
        rel = f'ADV/{f}'
        for r in toolbelt.read_extracted('psx', rel, optional=True):
            story[key(r['text'])] = (rel, r['pos'])
    en_by = {}
    for f in ('E0', 'E1', 'E2', 'E3'):
        rel = f'ADV/{f}'
        for r in toolbelt.read_generated(rel, optional=True):
            en_by[(rel, r['pos'])] = (r['en'], r.get('psp', ''))
    auto = {}
    for ovl, ram, _keep in MSGS:
        d = open(toolbelt.bin_path(ovl), 'rb').read()
        s = ram - B
        e = d.index(b'\xff\x01', s) + 2
        hit = story.get(key(etext.decode(d[s:e])))
        if hit and en_by.get(hit, ('', ''))[0].strip():
            auto[(ovl, ram)] = en_by[hit]
    rows = {}
    for (ovl, ram), (en, psp) in auto.items():
        row = {'pos': hex(ram - B), 'en': en}
        if psp:                      # the derived row carries its source
            row['psp'] = psp
        rows.setdefault(ovl, []).append(row)
    for ovl, rs in rows.items():
        toolbelt.upsert_generated(toolbelt.rel_for(os.path.join(ROOT, 'data', 'psx', ovl + '.BIN')), rs)
    print(f'scriptmsg: {len(auto)} embedded ports written')
    return auto


def race_titles():
    """Patch race titles (the ANALYZE list) with the canonical race-name
    rows (demons.race_en - one source for the race wording, rendered here
    in the dialogue encoding; the 8-byte title slots are the same 26-name
    list the 6-byte race tables hold)."""
    import demons
    en = {k - 1: v for k, v in demons.race_en().items() if etext.has_text(v)}
    first = etext.encode('夜魔', end=bytes((0xFF, 0x01)))
    for ovl in ('ADV', 'DNG', 'S2D'):
        lines = [f';; generated by scriptmsg.py - do not edit ({ovl} race titles){NL}']
        if en:
            d = open(os.path.join(ROOT, 'data', 'psx', ovl + '.BIN'), 'rb').read()
            s = d.index(first)
            for k, text in sorted(en.items()):
                a = s + 8 * k
                b = etext.encode(text, end=bytes((0xFF, 0x01)))
                assert len(b) <= 8 and d[a + 4:a + 6] != b'', (k, text)
                lines.append(f'.org {B + a:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b + bytes(8 - len(b))) + NL)
        os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
        open(os.path.join(ROOT, 'build', f'racetitles_{ovl.lower()}.asm'), 'w', newline=NL).write(''.join(lines))


def dump():
    """Queue every overlay-embedded message spot and port the ones whose
    Japanese matches a story box (port_embedded)."""
    import toolbelt
    for ovl in ('ADV', 'DNG', 'S2D'):
        rel = toolbelt.rel_for(os.path.join(ROOT, 'data', 'psx', ovl + '.BIN'))
        toolbelt.route_gaps(rel, [hex(ram - B) for o, ram, _k in MSGS if o == ovl])
    port_embedded()
    print('scriptmsg: spots queued + embedded ports written')


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'dump':
        dump()
        return
    race_titles()
    import toolbelt
    merged = {}                            # (overlay, file offset) -> en
    for ovl in ('ADV', 'DNG', 'S2D'):
        rel = toolbelt.rel_for(os.path.join(ROOT, 'data', 'psx', ovl + '.BIN'))
        for r in toolbelt.merged_rows(rel):
            for _entry, off in toolbelt.pos_offsets(r['pos']):
                merged[(ovl, off)] = r['en']
    out = {'ADV': [], 'DNG': []}
    reloc = {}                                    # (ovl, bytes) -> ram (dedup identical strings)
    for ovl, ram, keep in MSGS:
        text = merged.get((ovl, ram - B)) or ''
        if not etext.has_text(text):
            continue
        d = open(os.path.join(ROOT, 'data', 'psx', ovl + '.BIN'), 'rb').read()
        s = ram - B
        e = d.index(b'\xff\x01', s) + 2
        if d[e - 4:e] != b'\xff\x02\xff\x01':
            raise SystemExit(f'scriptmsg: {ram:#x}: unexpected end {d[e - 4:e].hex()}')
        b = _assemble(text)
        head = d[s:s + keep]
        if keep and head not in b:
            raise SystemExit(f'scriptmsg: {ram:#x}: the row lost the source '
                             f'insert head {head.hex(" ")} - the ids are the '
                             'source script\'s, keep them verbatim')
        check_lines(text, f'{ovl} {ram:#x}')
        if len(b) > e - s:
            # Oversize: relocate into a verified cave and repoint the FF55
            # command words (old slot bytes stay). A cave in the file's own
            # extension is loaded with the overlay (DNG_GLUE/SPILL already
            # live there and the build updates FSIZE.DAT).
            import struct as _struct
            refs = []
            for h in range(len(d) - 3):
                if _struct.unpack_from('<I', d, h)[0] == ram and d[h - 4:h] == b'\xff\x55\x00\x00':
                    refs.append(B + h)
            if not refs:
                print(f'scriptmsg: {ram:#x}: oversize ({len(b)} bytes) but no FF55 reference found, keeping Japanese')
                continue
            key = (ovl, bytes(b))
            if key not in reloc:
                cave = _cave(ovl, d)
                if cave is None:
                    print(f'scriptmsg: {ram:#x}: oversize ({len(b)} bytes), no surveyed cave in {ovl}, keeping Japanese')
                    continue
                base, size = cave
                used = sum(len(x[1]) for o, x in reloc.items() if o[0] == ovl)
                if used + len(b) > size:
                    raise SystemExit(f'scriptmsg: {ovl} cave exhausted ({used} + {len(b)} > {size})')
                new_ram = B + base + used
                reloc[key] = (new_ram, bytes(b))
            else:
                new_ram = reloc[key][0]
            out[ovl].append(f'.org {new_ram:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL)
            for where in refs:
                out[ovl].append(f'.org {where:#x}{NL}    .word {new_ram:#x}{NL}')
            print(f'scriptmsg: {ram:#x}: relocated {len(b)} bytes to {new_ram:#x} ({len(refs)} ref(s) patched)')
            continue
        b += bytes(e - s - len(b))
        out[ovl].append(f'.org {ram:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL)
    for ovl, lines in out.items():
        head = f';; generated by scriptmsg.py - do not edit ({ovl}){NL}'
        if ovl in EXT_CAVE:
            addr, limit, stop = EXT_CAVE[ovl]
            head += (f'.if {addr} < dng_glue_end{NL}'
                     f'    .error "scriptmsg: {ovl} cave overlaps the dialogue glue"{NL}'
                     f'.endif{NL}'
                     f'.if {limit} > {stop}{NL}'
                     f'    .error "scriptmsg: {ovl} cave crosses {stop}"{NL}'
                     f'.endif{NL}')
        open(os.path.join(ROOT, 'build', f'scriptmsg_{ovl.lower()}.asm'), 'w', newline=NL).write(
        head + ''.join(lines))
    print(f'scriptmsg: {len(MSGS)} messages')


if __name__ == '__main__':
    main()
