"""S2D.BIN: every text family, one table, one builder.

  python src/injection_tools/s2d.py dump     refresh generated/S2D.BIN.tsv (keeps en)
  python src/injection_tools/s2d.py build    QA + build/s2d.asm (+ _slps spill, map json)

Families (docs/TEXT_ARCHITECTURE.md: one TSV per real file, rows keyed by
pos = file offset of the row's original slot; relocation systems may place
bytes elsewhere - the builder owns final placement and pointer fixing):

  script  61 dialogue boxes in the FF55 block (0x800AB040-0x800AC400),
          event encoding (FF01 end, FF02/FF04 waits, FF05 pauses). Own
          slot first, then the block's free ranges, then the S2D
          extension spill; every pointer word / lui-addiu pair that
          targets a moved string is rewritten. Nothing ships to wrap in
          game: an over-wide box is refused loudly (text is never
          shortened - the row waits in manual).
  names   47 location names (0x800AAE0E-0x800AB034): arrival banner +
          map labels, byte-packed 1-row VWF entries (FF01-terminated),
          reached through pointer words and lui 0x800B/addiu pairs.
          One slot feeds two consumers: the slot keeps the banner name
          (BANNER_LIMIT 240 px), and the map-label placement entries get
          their own string (LABEL_LIMIT 128 px). A manual row keyed by a
          label placement's name word supplies the shorter map wording.

All table IO, merging and emission goes through toolbelt. Placement must
preserve the other S2D extension allocations and grid-full latch.
"""
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext      # noqa: E402
import tstatus    # noqa: E402
import toolbelt   # noqa: E402
import vwf_wrap   # noqa: E402

ROOT = toolbelt.ROOT
REL = 'S2D'
B = 0x800643C4                    # overlay slot
D_PATH = toolbelt.bin_path(REL)
OUT = os.path.join(ROOT, 'build', 's2d.asm')
OUT_SLPS = os.path.join(ROOT, 'build', 's2d_slps.asm')
OUT_MAP = os.path.join(ROOT, 'build', 's2d_map.json')

# script family
BLOCK = (0x800AB040, 0x800AC400)
# Overflow: S2D.BIN is loaded in whole sectors (352256 bytes = up to RAM
# 0x800BA3C4); the file is extended by the sectors that hold the English
# boxes that do not fit their Japanese slots. Nothing in the overlay or
# the main EXE refers to that RAM (static scan), it only held the tail of
# the ADV overlay that was resident before.
SCRIPT_SPILL = [(0x800BA3C4, 0x800BB200)]   # up to S2D_GLUE_ADDR (addresses.inc)
# names family
NZONE = (0x800AAE0E, 0x800AB034)
# The arrival / current-location banner reads its name from this pointer
# table (one word per name slot, in slot order). The map labels read the
# same slot through pointer words in the label-entry tables. One slot, two
# consumers; build() splits them.
NAME_TABLE_ADDR = 0x800A54DC
# The 8x1 map labels read their name from placement tables: one 8-byte
# entry per label (u16 x, u16 y, name pointer), terminated by two -1 words.
# The root array lists a table per map; its order is not the name slot order.
LABEL_TABLE_ROOT = 0x800A5764
BANNER_LIMIT = 240                # px: the 15x1 arrival banner's own strip
LABEL_LIMIT = 128                 # px: an 8x1 map label's own strip
# Spill space: the S2D extension past the VWF glue. Keep its existing
# conservative ceiling; the compositor ring lives in resident scratch.
NAME_SPILL = [(0x800BB8F0, 0x800BBB70)]


def data():
    return open(D_PATH, 'rb').read()


def script_boxes(d):
    starts = set()
    for i in range(len(d) - 8):
        if d[i:i + 4] == b'\xff\x55\x00\x00':
            v = struct.unpack_from('<I', d, i + 4)[0]
            if BLOCK[0] <= v < BLOCK[1]:
                starts.add(v)
    out = []
    for s in sorted(starts):
        e = d.index(b'\xff\x01', s - B) + 2 + B
        out.append((s, e))
    return out


def script_refs(d, bx):
    """pointer words (4-aligned) at a box start; error for mid-box pointers."""
    found = {i: [] for i in range(len(bx))}
    for k in range(0, len(d) - 3, 4):
        v = struct.unpack_from('<I', d, k)[0]
        for i, (a, e) in enumerate(bx):
            if a <= v < e:
                if v != a:
                    toolbelt.fail(f'{REL}: pointer {B + k:#x} into the middle of box {i} ({v:#x})')
                found[i].append(B + k)
    return found


def name_slots(d):
    out, p = [], NZONE[0]
    while p < NZONE[1]:
        e = d.index(b'\xff\x01', p - B) + 2 + B
        out.append((p, e))
        p = e
    return out


def label_table_refs(d):
    """The name-word addresses of the 8x1 map-label placement tables.

    LABEL_TABLE_ROOT lists a placement table per map. Each table is 8-byte
    entries (u16 x, u16 y, name pointer) ended by two -1 words; the name
    word is entry+4. These are the only refs the map labels read, so they
    are the only refs that may take the shorter label wording.
    """
    words = set()
    p = LABEL_TABLE_ROOT
    while True:
        base = struct.unpack_from('<I', d, p - B)[0]
        if not base:
            break
        p += 4
        q = base
        while True:
            coords, _name = struct.unpack_from('<II', d, q - B)
            if coords == 0xFFFFFFFF:
                break
            words.add(q + 4)
            q += 8
    return words


def label_refs(nrf, i, words):
    """slot i's map-label pointer words (the name words of the placement
    tables). Every other ref into the slot feeds the arrival banner, which
    keeps the slot's own wording."""
    return [w for kind, w, _old, _lui in nrf[i]
            if kind == 'ptr' and w in words]


def name_refs(d, msgs):
    found = {i: [] for i in range(len(msgs))}

    def which(v):
        for i, (a, e) in enumerate(msgs):
            if a <= v < e:
                return i

    for k in range(0, len(d) - 3, 4):
        v = struct.unpack_from('<I', d, k)[0]
        if NZONE[0] <= v < NZONE[1]:
            i = which(v)
            if i is not None:
                found[i].append(('ptr', B + k, v, 0))
    for k in range(0, len(d) - 36, 4):
        w = struct.unpack_from('<I', d, k)[0]
        hi = w & 0xFFFF
        if (w >> 26) == 0xF and hi in (0x800A, 0x800B):
            rt = (w >> 16) & 31
            for j in range(1, 8):
                x = struct.unpack_from('<I', d, k + 4 * j)[0]
                op, imm = x >> 26, x & 0xFFFF
                if ((x >> 21) & 31) != rt or op not in (9, 0xD):
                    continue
                v = (hi << 16) + (imm - 0x10000 if (imm & 0x8000 and op == 9) else imm)
                i = which(v)
                if i is not None:
                    found[i].append(('addiu' if op == 9 else 'ori', B + k + 4 * j, v, B + k))
    return found


def families(d):
    """[(pos, psp)] every row slot in file order (script boxes, then
    names). ja is deliberately not stored (docs: lookup via pos)."""
    out = []
    for a, _e in script_boxes(d):
        out.append((a - B, ''))
    for a, _e in name_slots(d):
        out.append((a - B, ''))
    return out


def route_label_drafts():
    """Queue a manual row for every map label wider than its 8x1 strip.

    A label's wording defaults to the location name. When that name does not
    fit the label's 128 px strip, the row lands in manual with empty `en` and
    the full name as the over-limit draft; a filled row at any of the slot's
    label references becomes the shorter map wording. The arrival banner
    keeps the full name, so this is the one place the two are split.
    """
    d = data()
    msgs = name_slots(d)
    nrf = name_refs(d, msgs)
    lwords = label_table_refs(d)
    gen = {int(r['pos'], 16): r for r in toolbelt.read_generated(REL, optional=True)}
    man = {int(r['pos'], 16): r for r in toolbelt.read_manual(REL, optional=True)}
    for i, (a, _e) in enumerate(msgs):
        refs = label_refs(nrf, i, lwords)
        if not refs:
            continue
        filled = [(w - B) for w in refs
                  if (man.get(w - B) or {}).get('en', '').strip()]
        text = (man[filled[0]]['en'].strip() if filled
                else (gen.get(a - B, {}).get('en') or '').strip())
        if not text:
            continue
        px = vwf_wrap.text_width(text)
        if px <= LABEL_LIMIT:
            continue
        key = filled[0] if filled else refs[0] - B
        toolbelt.route_over(REL, hex(key), gen.get(a - B, {}).get('psp', ''),
                            text, toolbelt.note_over(px, LABEL_LIMIT))


def dump():
    # S2D.tsv is shared: this scan owns the text boxes and location slots,
    # while boot_tables.py's race pass owns the 26-name race table that is
    # copied into the same overlay (demons.RACE_TABLES). Keep those filled
    # rows - the default position surface would drop them.
    rows, _man = toolbelt.dump_scaffold(
        REL, [(hex(off), psp) for off, psp in families(data())],
        keep_other=True)
    route_label_drafts()
    print(f's2d: {len(rows)} rows -> {toolbelt.gen_path(REL)}')


def _vwf_byte(t, c):
    try:
        return etext.vwf_byte(c)
    except ValueError:
        toolbelt.fail(f'{t!r}: {c!r} has no 1-row VWF byte')


def name_bytes(t):
    """ASCII -> one VWF byte per char + FF01 (retail entry shape; the S2D
    interpreter 0x8009B2F4 walks entries as BYTES - u16 packing desyncs it
    and over-grid walks deadlock in the grid-full latch)."""
    return bytes(_vwf_byte(t, c) for c in t) + b'\xff\x01'


def fill_pauses(ja, en):
    """`<FF05>` without parameter bytes in `en` -> the two parameter glyph
    bytes of the same FF05 in `ja`."""
    jb = etext.encode(ja)
    par = [jb[i + 2:i + 4] for i in range(len(jb) - 3) if jb[i] == 0xFF and jb[i + 1] == 5]
    k = iter(par)
    return re.sub(r'<FF05>(?!<[0-9A-F]{2}>)',
                  lambda m: '<FF05>' + ''.join(f'<{x:02X}>' for x in next(k)), en)


def build():
    d = data()
    rows = toolbelt.merged_rows(REL)
    body = []
    n_script = n_names = 0

    # --- script family: own slot first, then block free ranges, then spill
    bx = script_boxes(d)
    rf = script_refs(d, bx)
    tstatus.load_glossary()
    todo = {}
    box_at = {a - B: i for i, (a, _e) in enumerate(bx)}
    for r in rows:
        pos = int(r['pos'], 16)
        i = box_at.get(pos)
        if i is None:
            continue                # another family's row (e.g. a map label)
        t = r['en'].strip()
        if not t:
            continue
        ja = etext.decode(d[bx[i][0] - B:bx[i][1] - B - 2])
        t = fill_pauses(ja, t)
        bad = tstatus.ship_errors(ja, t)     # the QA's gate, exemptions and all
        if bad:
            toolbelt.fail(f'script box {i} id {r["id"]}: '
                          + '; '.join(f'[{k}] {m}' for k, m in bad))
        todo[i] = etext.encode(t)
    free = [bx[i] for i in todo]
    pools = [free, list(SCRIPT_SPILL)]
    placed, addr_of = {}, {}
    for i in sorted(todo, key=lambda i: -len(todo[i])):
        b = todo[i]
        if b in placed:
            addr_of[i] = placed[b]
            continue
        a, e = bx[i]
        if len(b) <= e - a and (a, e) in free:                # its own slot first
            placed[b] = a
            addr_of[i] = a
            free[free.index((a, e))] = (a + len(b), e)
            continue
        for pool in pools:
            for k, (pa, pe) in enumerate(pool):
                if pe - pa >= len(b):
                    placed[b] = pa
                    addr_of[i] = pa
                    pool[k] = (pa + len(b), pe)
                    break
            else:
                continue
            break
        else:
            toolbelt.fail(f'script box {i}: out of space ({len(b)} bytes); free '
                          f'{sum(e - a for p in pools for a, e in p)} bytes')
    for i in todo:
        a, e = bx[i]
        body.append(f'.org {a:#x}\n.fill {e - a}, 0')
    for b, a in placed.items():
        body.append(f'.org {a:#x}\n    .byte ' + ', '.join(f'0x{x:02X}' for x in b))
    for i in todo:
        for where in rf[i]:
            body.append(f'.org {where:#x}\n    .word {addr_of[i]:#x}')
    n_script = len(todo)

    # --- names family: one slot, two strings ---------------------
    # Every location slot feeds two consumers: the arrival / current-location
    # banner (the pointer table at NAME_TABLE_ADDR) and the 8x1 overworld map
    # labels (pointer words inside the label-entry tables). The slot keeps the
    # banner name. Each label reference gets its own string: the same name by
    # default, or the wording of a manual row keyed by any of that slot's
    # label-reference positions. The short map wording is therefore a normal
    # manual entry, never a name table inside this tool.
    msgs = name_slots(d)
    nrf = name_refs(d, msgs)
    lwords = label_table_refs(d)
    by_pos = {int(r['pos'], 16): r for r in rows}
    # Map-label wording is a human row keyed at a label pointer, never a
    # generated row (generated has no positions there).
    man_by_pos = {int(r['pos'], 16): r
                  for r in toolbelt.read_manual(REL, optional=True)}
    slot_pos = {i: a - B for i, (a, _e) in enumerate(msgs)}

    label_wording = {}
    for i in range(len(msgs)):
        found = []
        for w in label_refs(nrf, i, lwords):
            r = man_by_pos.get(w - B)
            if r is not None and r['en'].strip():
                found.append(r['en'].strip())
        if found:
            if len(set(found)) != 1:
                toolbelt.fail(f'name {i}: map-label rows disagree: '
                              f'{sorted(set(found))}')
            label_wording[i] = found[0]

    ntodo, ltodo = {}, {}
    for i in range(len(msgs)):
        r = by_pos.get(slot_pos[i])
        if r is None or not r['en'].strip():
            continue
        t = r['en'].strip()
        px = vwf_wrap.text_width(t)
        if px > BANNER_LIMIT:
            toolbelt.fail(f'name {i} id {r["id"]} {t!r}: {px}px > {BANNER_LIMIT}px')
        ntodo[i] = name_bytes(t)
        label = label_wording.get(i)
        if label is not None and label != t:
            ltodo[i] = name_bytes(label)
    free = sorted(msgs[i] for i in ntodo)
    merged = []
    for a, e in free:
        if merged and merged[-1][1] == a:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((a, e))
    placed, naddr, laddr = {}, {}, {}
    spill = list(NAME_SPILL)

    def put(i, b, pools, addr):
        if b in placed:
            addr[i] = placed[b]
            return True
        for pool in pools:
            for k, (a, e) in enumerate(pool):
                if e - a >= len(b):
                    placed[b] = a
                    addr[i] = a
                    pool[k] = (a + len(b), e)
                    return True
        return False

    order = sorted(ntodo, key=lambda i: (not any(r[0] in ('addiu', 'ori') for r in nrf[i]), -len(ntodo[i])))
    for i in order:
        has_code = any(r[0] in ('addiu', 'ori') for r in nrf[i])
        if not put(i, ntodo[i], [merged] if has_code else [merged, spill], naddr):
            toolbelt.fail(f'name {i}: out of space ({len(ntodo[i])} bytes, code refs: {has_code})')
    for i in sorted(ltodo):
        if ltodo[i] == ntodo[i]:
            laddr[i] = naddr[i]
        elif not put(i, ltodo[i], [merged, spill], laddr):
            toolbelt.fail(f'name {i}: map label out of space ({len(ltodo[i])} bytes)')
    for i in ntodo:
        a, e = msgs[i]
        body.append(f'.org {a:#x}\n.fill {e - a}, 0')
    for b, a in placed.items():
        if NZONE[0] <= a < NZONE[1]:
            body.append(f'.org {a:#x}\n    .byte ' + ', '.join(f'0x{x:02X}' for x in b))
    for i in ntodo:
        for kind, where, old, lui in nrf[i]:
            label = kind == 'ptr' and where in lwords and i in laddr
            new = laddr[i] if label else naddr[i]
            if kind == 'ptr':
                body.append(f'.org {where:#x}\n    .word {new:#x}')
            elif kind == 'addiu':
                body.append(f'.org {where:#x}\n    .halfword {(new - 0x800B0000) & 0xFFFF:#x}')
            else:                                              # ori with lui 0x800A
                body.append(f'.org {where:#x}\n    .halfword {new & 0xFFFF:#x}')
    n_names = len(ntodo)
    n_labels = sum(1 for i in ltodo if ltodo[i] != ntodo[i])

    toolbelt.write_asm(OUT, 's2d', '\n'.join(body) + '\n')
    ptrmap, content = {}, {}
    for i in ntodo:
        for kind, where, old, lui in nrf[i]:
            label = kind == 'ptr' and where in lwords and i in laddr
            new = laddr[i] if label else naddr[i]
            ptrmap[f'{old:#010x}'] = f'{new:#010x}'
        content[ntodo[i].hex()] = f'{naddr[i]:#010x}'
        if i in ltodo:
            content[ltodo[i].hex()] = f'{laddr[i]:#010x}'
    with open(OUT_MAP, 'w') as o:
        json.dump({'ptr': ptrmap, 'content': content}, o)
    spill_body = []
    for b, a in placed.items():
        if not (NZONE[0] <= a < NZONE[1]):
            spill_body.append(f'.org {a:#x}\n    .byte ' + ', '.join(f'0x{x:02X}' for x in b))
    toolbelt.write_asm(OUT_SLPS, 's2d',
                       ';; overworld names spilled into the S2D extension\n'
                       + '\n'.join(spill_body) + ('\n' if spill_body else ''))
    print(f's2d: {n_script} script boxes, {n_names} names, '
          f'{n_labels} map labels -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if sys.argv[1:] else 'build']()
