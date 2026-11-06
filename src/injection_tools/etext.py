"""Event script text: lossless box text codec, TSV dump and apply for ADV/E0..E3.BIN.

Text syntax (one line per box, no real newlines):
  any glyph character   one glyph of the game font (tools/font_map.tsv)
  ASCII 0x20-0x7E       VWF English byte (ord + 0x68) -- use for translations
  <FFxx>                control code (e.g. <FF03> newline, <FF02> wait, <FF01> end)
  <Gxxx>                glyph 0xxxx without a printable character
  <xx>                  raw byte
A box must end with <FF01>; the tool appends it when a translation omits it.

Control codes (PSX meanings; docs/TEXT_ARCHITECTURE.md):
  <FF01> end/dismiss
  <FF02> wait -- press to scroll; the box keeps its context
  <FF03> line break
  <FF04> page/clear -- fresh window; counts as a new box
  <FF05> + 2 bytes (e.g. <FF05><10><00>) timed pause
  <FF06> + 1 byte (e.g. <FF06><02>) style/colour; port: card/frame style
  <FF07>/<FF08> name inserts; <FF0F> + 1 byte name insert
  <FF0E> + 1 byte scroll-to-choice

The box is 15 cells by 4 rows, but a page is **three visible lines plus
the fourth scroll line**. `port_story.paginate` inserts <FF02> after line
3, so the fourth line is player-gated. <FF04> is not a scroll: it clears
to a new window. See docs/TEXT_ARCHITECTURE.md "Text boxes: three visible
lines + one scroll".

CLI (run from persona-tl/):
  python tools/etext.py check                 decode->encode identity over all boxes
  python tools/etext.py dump [outdir]         translation/events/E?.tsv  (entry box ja en)
  python tools/etext.py layout [--grow]       reserve fixed per-entry slots (translation/layout.json)
  python tools/etext.py build [outdir]        apply the `en` column -> build/ADV/E?.BIN + build/event_tables.asm
"""
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import efile  # noqa: E402
import strlib  # noqa: E402
import make_vwf_font  # noqa: E402  (the font's character map)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GENERATED_ADV = os.path.join(ROOT, 'translation', 'generated', 'ADV')
LAYOUT = os.path.join(GENERATED_ADV, 'layout.json')
VWF_BIAS = 0x68
# font slot -> the character it prints. ASCII is itself; the extra map
# entries (make_vwf_font.EXTRA, written after the '=' of its character
# map) take the free slots above 0x7E. The English font carries its own
# glyph for every character it prints - nothing falls through to the
# Japanese FONT.BIN, whose design and metrics are not ours.
_VWF_CHAR = {c: chr(c) for c in range(0x20, 0x7F)}
_VWF_CHAR.update({code: ch for ch, code in
                  make_vwf_font.EXTRA_CODE.items()})
NO_LITERAL = set('<\t\r\n')
# THE SOURCE'S SPELLING IN THE GLYPHS THIS FONT HAS (make_vwf_font.SPELL): a
# typographic apostrophe is the ASCII one, an en/em dash is '-'. It is a
# SPELLING fold, not an edit of the wording - the tables keep the PSP's own
# characters (a quote typed anywhere in the source still reads as a quote),
# and the fold happens here, once, where text becomes bytes. '’' has no cell
# of its own on the sheet, so without this it fell through to the Japanese
# FONT.BIN's 2-byte path and no VWF textbox could hold it.
spell = make_vwf_font.spell
# '>' and '<' print as text where the Japanese itself draws one
# (port_derive.head_marks spells the fullwidth pair ASCII). In the TABLES a
# literal '<' still opens a control-code token; only the injection emits it
# as a glyph.


def printable_byte(b):
    """True when an encoded byte is one of the VWF font's own printable
    glyphs - ASCII plus the extras the font carries above it (e7 = '...').
    THE authority for "is this text English text": anything else in a
    box's bytes is leftover Japanese (or a glyph code), never wording."""
    return (b - VWF_BIAS) in _VWF_CHAR


def vwf_byte(ch):
    """The one VWF byte a printable character prints (ASCII plus the
    font's extras). Characters with only a Japanese FONT.BIN glyph have
    no VWF byte and raise - the same reach encode() has, minus the
    two-byte glyph codes the one-byte-per-glyph rows cannot carry."""
    o = ord(ch)
    if 0x20 <= o <= 0x7E:
        return o + VWF_BIAS
    if ch in make_vwf_font.EXTRA_CODE:
        return make_vwf_font.EXTRA_CODE[ch] + VWF_BIAS
    raise ValueError(f'no VWF byte for {ch!r} (U+{o:04X})')


def is_todo(en):
    """True when an `en` cell is empty."""
    return not en.strip()


def has_text(en):
    """True when an `en` cell holds real translated text."""
    return bool(en.strip())


def pos_map(c):
    """{pos: (entry, box)} for every box of a container (pos = 'entry:0xoffset',
    the canonical locator the generated/manual rows use)."""
    return {f'{e.index}:{s:#x}': (e.index, k)
            for e in c.entries for k, (s, _x) in enumerate(e.boxes)}


def auto_event_text():
    """{(file, entry, box): (ja, en)} from the canonical generated rows
    (translation/generated/ADV/E?.tsv, pos-keyed)."""
    import toolbelt
    out = {}
    for file in FILES:
        rows = toolbelt.read_generated(f'ADV/{file}', optional=True)
        if not rows:
            continue
        c = efile.load(path(file))
        pmap = pos_map(c)
        for r in rows:
            key = pmap.get(r['pos'])
            if key is None or not has_text(r.get('en', '')):
                continue
            e = c.entries[key[0]]
            a, b = e.boxes[key[1]]
            out[(file, key[0], key[1])] = (decode(e.body[a:b]), r['en'])
    return out

glyph = {}       # index -> char
char2g = {}
for _f in strlib.tsv_fields(os.path.join(ROOT, 'src', 'injection_tools', 'font_map.tsv'), 2):
    _i, _c = _f
    glyph[int(_i, 16)] = _c
    char2g.setdefault(_c, int(_i, 16))


def _g(g):
    c = glyph.get(g)
    if c is None or c in NO_LITERAL or len(c) != 1 or (0x20 <= ord(c) <= 0x7E):
        return f'<G{g:03X}>'
    return c


# Control codes whose next N raw bytes are the code's own argument (not
# text). The table is the event codec's; a caller that knows a code takes
# an argument the event codec does not (the DNG script's FF09/FF0A name
# inserts take the item / skill id) passes `params` for that decode only.
# ENCODE prices FF09 (2 bytes) and FF0A (1 byte) as arguments as well, so a
# row carries the insert literally - `<FF09><12><00>` - wherever its wording
# puts the name.
DECODE_ARGS = {5: 2, 6: 1, 14: 1, 15: 1}


def decode(b, params=None):
    args = DECODE_ARGS if not params else {**DECODE_ARGS, **params}
    out, i = [], 0
    arguments = 0
    while i < len(b):
        c = b[i]
        if arguments:
            out.append(f'<{c:02X}>'); i += 1
            arguments -= 1
        elif c < 0x80:
            out.append(_g(c)); i += 1
        elif c <= 0x87 and i + 1 < len(b):
            out.append(_g(((c & 7) << 8) | b[i + 1])); i += 2
        elif c == 0xFF and i + 1 < len(b):
            arguments = args.get(b[i + 1], 0)
            out.append(f'<FF{b[i + 1]:02X}>'); i += 2
        elif 0x88 <= c <= 0xEF:
            ch = _VWF_CHAR.get(c - VWF_BIAS)
            if ch is None:
                out.append(f'<{c:02X}>')
            else:
                out.append(ch if ch not in NO_LITERAL else f'<{c:02X}>')
            i += 1
        else:
            out.append(f'<{c:02X}>'); i += 1
    return ''.join(out)


_TOKEN = re.compile(r'<(FF[0-9A-F]{2}|G[0-9A-F]{3}|[0-9A-F]{2})>')


def encode(s, end=bytes([0xFF, 0x01])):
    out = bytearray()
    pos = 0
    arguments = 0
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if arguments:
            if m and len(m.group(1)) == 2:
                value = int(m.group(1), 16)
                pos = m.end()
            elif s[pos] in (' ', '　'):
                # Legacy tables spell raw zero as a blank, not VWF text.
                value = 0
                pos += 1
            elif s[pos] in char2g and char2g[s[pos]] < 0x80:
                value = char2g[s[pos]]
                pos += 1
            else:
                raise ValueError('control argument requires a raw <xx> byte')
            out.append(value)
            arguments -= 1
            continue
        if m:
            t = m.group(1)
            if t.startswith('FF'):
                out += bytes([0xFF, int(t[2:], 16)])
                arguments = {5: 2, 6: 1, 9: 2, 10: 1,
                             14: 1, 15: 1}.get(int(t[2:], 16), 0)
            elif t.startswith('G'):
                g = int(t[1:], 16)
                out += bytes([g]) if g < 0x80 else bytes([0x80 | (g >> 8), g & 0xFF])
            else:
                out.append(int(t, 16))
            pos = m.end()
            continue
        ch = spell(s[pos])
        if ch in ('＞', '＜'):
            ch = '>' if ch == '＞' else '<'
                         # the table spelling of the head marks (one rule:
                         # port_derive.head_marks); the font's glyphs are
                         # the ASCII ones
        o = ord(ch)
        if 0x20 <= o <= 0x7E:
            out.append(o + VWF_BIAS)
        elif ch in make_vwf_font.EXTRA_CODE:
            out.append(make_vwf_font.EXTRA_CODE[ch] + VWF_BIAS)
        elif ch in char2g:
            g = char2g[ch]
            out += bytes([g]) if g < 0x80 else bytes([0x80 | (g >> 8), g & 0xFF])
        else:
            raise ValueError(f'no glyph for {ch!r} (U+{ord(ch):04X})')
        pos += 1
    if arguments:
        raise ValueError('missing control argument')
    if end and out[-len(end):] != end:
        out += end
    return bytes(out)


FILES = ['E0', 'E1', 'E2', 'E3']
# sector tables of the E files embedded in SLPS_005.00 (RAM addresses; the loader at
# 0x800159EC indexes them by script id; each equals the file's own sector 0 table)
SLPS_TABLES = {'E0': 0x8004DA70, 'E1': 0x8004DC34, 'E2': 0x8004DDF8, 'E3': 0x8004DFDC}


def path(n):
    return os.path.join(ROOT, 'data', 'psx', 'ADV', f'{n}.BIN')


def cmd_check():
    bad = total = 0
    for n in FILES:
        for e in efile.load(path(n)).entries:
            for k, (s, en) in enumerate(e.boxes):
                total += 1
                raw = e.body[s:en]
                if encode(decode(raw)) != raw:
                    bad += 1
                    if bad <= 5:
                        print('MISMATCH', n, e.index, k, raw[:24].hex(' '), decode(raw)[:40])
    print(f'{total} boxes, {bad} not identical after decode->encode')


def read_rows(tp):
    """{(entry, box): (ja, en)} from an existing TSV (empty if missing)."""
    rows = {}
    if os.path.exists(tp):
        for row in strlib.tsv_rows(tp, required=('entry', 'box', 'ja', 'en')):
            if row['entry'].isdigit() and row['box'].isdigit():
                rows[(int(row['entry']), int(row['box']))] = (row['ja'], row['en'])
    return rows


def cmd_dump(outdir=None):
    """The manual work list is toolbelt-managed: every box position without a
    translation gets a gap row (translation/manual/ADV/<n>.tsv), filled rows
    clean up automatically. port_story owns the same list on the port side;
    kept here so the build-time trim still works."""
    import toolbelt
    for n in FILES:
        c = efile.load(path(n))
        spots = [f'{e.index}:{s:#x}' for e in c.entries for s, _x in e.boxes]
        toolbelt.route_gaps(f'ADV/{n}', spots)
    print('ADV worklists trimmed (translation/manual/ADV)')


def load_edits(n, tsvdir=None):
    """edits[entry][box] = encoded en from the canonical rows (manual wins):
    generated/ADV/<n>.tsv (the PSP port) and manual/ADV/<n>.tsv (the human's),
    both pos-keyed. A filled manual pos the scan no longer carries is a stale
    row: fail loud for human re-homing - never guess by text content."""
    import toolbelt
    edits = {}
    c = efile.load(path(n))
    pmap = pos_map(c)
    rel = f'ADV/{n}'
    man = {r['pos']: r.get('en', '')
           for r in toolbelt.read_manual(rel, optional=True)}
    for pos, text in man.items():
        if has_text(text) and pos not in pmap:
            raise SystemExit(f'translation/manual/ADV/{n}.tsv: pos {pos} is '
                             f'stale (the scan has no such box) - re-home it')
    auto = {(e, b): en for (f, e, b), (_ja, en) in auto_event_text().items()
            if f == n}
    for pos, (entry, box) in pmap.items():
        text = man.get(pos, '')
        if not text:
            text = auto.get((entry, box), '')
        if not text:
            continue
        try:
            edits.setdefault(entry, {})[box] = encode(text)
        except ValueError as ex:
            raise SystemExit(f'{n}/{entry}/{box} ({pos}): {ex}')
    return edits


def cmd_layout(grow=False):
    """Reserve a fixed slot (sectors) per entry, once: translation/layout.json.
    slot = max(original sectors, ceil(1.5 * image / 2048) + 1), at most 31 sectors (the game
    loads an entry into a 0xFFF8-byte buffer). With --grow, existing slots are kept and only
    raised where the current translation needs more."""
    S = efile.SECTOR
    cur = json.load(open(LAYOUT, encoding='utf-8')) if (grow and os.path.exists(LAYOUT)) else {}
    tsvdir = os.path.join(ROOT, 'translation', 'manual', 'events')
    for n in FILES:
        c = efile.load(path(n))
        edits = load_edits(n, tsvdir) if grow else {}
        slots = list(cur.get(n, []))
        for e in c.entries:
            orig = c.t[e.index + 1] - c.t[e.index]
            if e.index < len(slots):
                want = slots[e.index]
            else:
                want = min(31, max(orig, -(-int((8 + e.size) * 1.5) // S) + 1))
            if grow and e.index in edits:
                need = -(-len(e.rebuild(edits[e.index])) // S)
                want = max(want, min(31, need))
            if e.index < len(slots):
                slots[e.index] = want
            else:
                slots.append(want)
        cur[n] = slots
    os.makedirs(os.path.dirname(LAYOUT), exist_ok=True)
    json.dump(cur, open(LAYOUT, 'w', encoding='utf-8', newline=chr(10)))
    print('layout written:', {n: f'{sum(v)} sectors' for n, v in cur.items()})


def cmd_build(tsvdir, outdir, asm=None):
    """Apply translated rows. Writes outdir/E?.BIN only for files that have edits (stale
    ones are removed) and `asm`: an armips include that patches the sector tables the
    game reads from SLPS_005.00 for those files."""
    os.makedirs(outdir, exist_ok=True)
    layout = {}
    if os.path.exists(LAYOUT):
        layout = json.load(open(LAYOUT, encoding='utf-8'))
    asm = asm or os.path.join(os.path.dirname(os.path.abspath(outdir)), 'event_tables.asm')
    lines = [';; generated by tools/etext.py build - do not edit',
             ';; sector tables of the edited ADV/E?.BIN files (the game reads these copies)']
    for n in FILES:
        c = efile.load(path(n))
        edits = load_edits(n, tsvdir)
        out = os.path.join(outdir, f'{n}.BIN')
        slots = layout.get(n)
        if not edits and not slots:
            if os.path.exists(out):
                os.remove(out)
            print(f'{n}: no edits')
            continue
        for idx in edits:
            if idx >= len(c.entries):
                raise SystemExit(f'{n}: no entry {idx}')
        raws = []
        for e in c.entries:
            try:
                raws.append(e.rebuild(edits.get(e.index)))
            except ValueError as ex:
                raise SystemExit(f'{n}/{e.index}: {ex}')
        for e, r in zip(c.entries, raws):
            if len(r) - 8 > 0xFFF8:
                raise SystemExit(f'{n}/{e.index}: image {len(r) - 8} bytes exceeds 0xFFF8')
            if slots and len(r) > slots[e.index] * efile.SECTOR:
                print(f'WARNING {n}/{e.index}: needs {-(-len(r) // efile.SECTOR)} sectors but its reserved slot is '
                      f'{slots[e.index]}: the sector table changes, save states made earlier go stale. '
                      f'Raise the slot in translation/layout.json (python tools/etext.py layout --grow).')
        data, table = c.build(raws, slots)
        with open(out, 'wb') as f:
            f.write(data)
        lines.append(f'.org 0x{SLPS_TABLES[n]:08X}   ; {n} ({len(table)} values)')
        for i in range(0, len(table), 16):
            lines.append('.halfword ' + ', '.join(str(v) for v in table[i:i + 16]))
        print(f'{n}: {sum(len(v) for v in edits.values())} boxes edited, '
              f'{len(c.data)} -> {len(data)} bytes')
    with open(asm, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a = sys.argv[1:] or ['check']
    if a[0] == 'check':
        cmd_check()
    elif a[0] == 'dump':
        cmd_dump(a[1] if len(a) > 1 else os.path.join(ROOT, 'translation', 'manual', 'events'))
    elif a[0] == 'layout':
        cmd_layout('--grow' in a)
    elif a[0] == 'build':
        cmd_build(os.path.join(ROOT, 'translation', 'manual', 'events'),
                  a[1] if len(a) > 1 else os.path.join(ROOT, 'build', 'ADV'))
    else:
        raise SystemExit(__doc__)
