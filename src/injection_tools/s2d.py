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
          LABEL_LIMIT 224 px; longer is refused loudly.

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
LABEL_LIMIT = 224                 # px (14 cells; double the old fixed 7-cell cap)
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


def dump():
    rows, _man = toolbelt.dump_scaffold(REL, [(hex(off), psp) for off, psp in families(data())])
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
    for r in rows:
        pos = int(r['pos'], 16)
        if not (BLOCK[0] - B <= pos < BLOCK[1] - B):
            continue
        t = r['en'].strip()
        if not t:
            continue
        i = next(i for i, (a, _e) in enumerate(bx) if a - B == pos)
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

    # --- names family: merged zone first (code refs), then spill
    msgs = name_slots(d)
    nrf = name_refs(d, msgs)
    ntodo = {}
    for r in rows:
        pos = int(r['pos'], 16)
        if not (NZONE[0] - B <= pos < NZONE[1] - B):
            continue
        t = r['en'].strip()
        if not t:
            continue
        i = next(i for i, (a, _e) in enumerate(msgs) if a - B == pos)
        if not nrf[i]:
            toolbelt.fail(f'name {i} id {r["id"]}: no reference')
        px = vwf_wrap.text_width(t)
        if px > LABEL_LIMIT:
            toolbelt.fail(f'name {i} id {r["id"]} {t!r}: {px}px > {LABEL_LIMIT}px')
        ntodo[i] = name_bytes(t)
    free = sorted(msgs[i] for i in ntodo)
    merged = []
    for a, e in free:
        if merged and merged[-1][1] == a:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((a, e))
    nplaced, naddr = {}, {}
    spill = list(NAME_SPILL)

    def put(i, pools):
        b = ntodo[i]
        if b in nplaced:
            naddr[i] = nplaced[b]
            return True
        for pool in pools:
            for k, (a, e) in enumerate(pool):
                if e - a >= len(b):
                    nplaced[b] = a
                    naddr[i] = a
                    pool[k] = (a + len(b), e)
                    return True
        return False

    order = sorted(ntodo, key=lambda i: (not any(r[0] in ('addiu', 'ori') for r in nrf[i]), -len(ntodo[i])))
    for i in order:
        has_code = any(r[0] in ('addiu', 'ori') for r in nrf[i])
        if not put(i, [merged] if has_code else [merged, spill]):
            toolbelt.fail(f'name {i}: out of space ({len(ntodo[i])} bytes, code refs: {has_code})')
    for i in ntodo:
        a, e = msgs[i]
        body.append(f'.org {a:#x}\n.fill {e - a}, 0')
    for b, a in nplaced.items():
        if NZONE[0] <= a < NZONE[1]:
            body.append(f'.org {a:#x}\n    .byte ' + ', '.join(f'0x{x:02X}' for x in b))
    for i in ntodo:
        for kind, where, old, lui in nrf[i]:
            new = naddr[i]
            if kind == 'ptr':
                body.append(f'.org {where:#x}\n    .word {new:#x}')
            elif kind == 'addiu':
                body.append(f'.org {where:#x}\n    .halfword {(new - 0x800B0000) & 0xFFFF:#x}')
            else:                                              # ori with lui 0x800A
                body.append(f'.org {where:#x}\n    .halfword {new & 0xFFFF:#x}')
    n_names = len(ntodo)

    toolbelt.write_asm(OUT, 's2d', '\n'.join(body) + '\n')
    ptrmap, content = {}, {}
    for i in ntodo:
        for kind, where, old, lui in nrf[i]:
            ptrmap[f'{old:#010x}'] = f'{naddr[i]:#010x}'
        content[ntodo[i].hex()] = f'{naddr[i]:#010x}'
    with open(OUT_MAP, 'w') as o:
        json.dump({'ptr': ptrmap, 'content': content}, o)
    spill_body = []
    for b, a in nplaced.items():
        if not (NZONE[0] <= a < NZONE[1]):
            spill_body.append(f'.org {a:#x}\n    .byte ' + ', '.join(f'0x{x:02X}' for x in b))
    toolbelt.write_asm(OUT_SLPS, 's2d',
                       ';; overworld names spilled into the S2D extension\n'
                       + '\n'.join(spill_body) + ('\n' if spill_body else ''))
    print(f's2d: {n_script} script boxes, {n_names} names -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if sys.argv[1:] else 'build']()
