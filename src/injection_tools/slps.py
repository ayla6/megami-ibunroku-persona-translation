"""SLPS_005.00 (resident main EXE): every text family, one table, one builder.

  python src/injection_tools/slps.py dump     refresh generated/SLPS_005.00.tsv (keeps en)
  python src/injection_tools/slps.py build    QA + build/slps.asm (+ skill tails)

Families (docs/TEXT_ARCHITECTURE.md: one TSV per real file, rows keyed by
pos; builders never search):

  items      382 stride-0x20 records from 0x8004442C, name field +0x10,
             10 bytes, small-font glyphs, FF-terminated (10-glyph names
             have no terminator). Cut to 10 glyphs = user decision
             2026-10-06 (full wording stays in the TSV).
  nicknames  9 stride-0x28 records from 0x800442B2, 10-byte field after
             4F01 0000 6F01, FF-terminated, max 8 visible chars
             (2026-10-05). Copied into party/save data at join time.
  skills     242 stride-0x28(?) records, 10-byte field + 3 spare bytes at
             +0x11; long names spill tails into build/skill_tails.asm via
             the FE,len escape.
  descs      pointer-table strings in the bank zone (TABLE at 0x800458D4?):
             zero-separated FF01-terminated scripts; over 239px fails.

Schema: id | pos | psp | en. Rows carry pos = ROM offset within
data/psx/SLPS_005.00; psp points at the extracted PSP source
(data/extracted_text/psp_us/...). Human rows live in
translation/manual/SLPS_005.00.tsv (sacred en; note column).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext      # noqa: E402
import toolbelt   # noqa: E402
import items      # noqa: E402
import skills     # noqa: E402
from toolbelt import Patch, smallfont_char  # noqa: E402

ROOT = toolbelt.ROOT
REL = 'SLPS_005.00'
BASE = 0x80010000 - 0x800            # SLPS file offset = VA - BASE
D = os.path.join(ROOT, 'data', 'psx', REL)
OUT = os.path.join(ROOT, 'build', 'slps.asm')
OUT_TAILS = os.path.join(ROOT, 'build', 'skill_tails.asm')
G2C = {v: k for k, v in etext.char2g.items()}

# --- items ----------------------------------------------------------------
IT_FIRST = 0x8004442C
IT_STRIDE = 0x20
IT_COUNT = 382                       # 0-162 items, 163-381 equipment
IT_FIELD = 10

# --- nicknames ------------------------------------------------------------
NK_FIRST = 0x800442B2
NK_STRIDE = 0x28
NK_COUNT = 9
NK_FIELD = 10
NK_MAX = 8

# --- skills ---------------------------------------------------------------
SK_FIRST = 0x80047D58
SK_STRIDE = 0x14
SK_COUNT = 242                       # 162 player + 80 enemy/special
SK_FIELD = 10
SK_SPARE = 0x11                      # 3 unreferenced bytes per record (+0x11..+0x13)

# --- descs -----------------------------------------------------------------
DS_ZONE = (0x80049104, 0x8004AA78)   # string bank (zero-separated FF01 ends)
DS_TABLE = (0x8004AA7C, 0x8004B0CC)  # pointer table (u32/entry)


def data():
    return open(D, 'rb').read()


def families(d):
    """[(pos, ja, psp, family)] every text row of the file, in source
    order. The ONLY structural scan; builders pick rows by pos range."""
    out = []
    for i in range(IT_COUNT):
        off = IT_FIRST - BASE + IT_STRIDE * i
        if i < 163 and d[off - 4:off - 2] != b'\xff\x01':
            toolbelt.fail(f'{REL}:{off:#x}: item {i} record head mismatch')
        nm = d[off:off + IT_FIELD]
        end = nm.index(b'\xff') if b'\xff' in nm else IT_FIELD
        out.append((off, _small_ja(nm[:end]), '', 'items'))
    for i in range(NK_COUNT):
        off = NK_FIRST - BASE + NK_STRIDE * i
        if d[off - 2:off] != b'\x6f\x01':
            toolbelt.fail(f'{REL}:{off:#x}: nickname {i} head mismatch')
        f = d[off:off + NK_FIELD]
        out.append((off, _small_ja(f.split(b'\xff')[0]), '', 'nicknames'))
    for i in range(SK_COUNT):
        off = SK_FIRST - BASE + SK_STRIDE * i
        f = d[off:off + SK_FIELD]
        out.append((off, _small_ja(f.split(b'\xff')[0]), '', 'skills'))
    i = DS_TABLE[0] - BASE
    seen = set()
    ptrs = []
    while i < DS_TABLE[1] - BASE:
        p = struct.unpack_from('<I', d, i)[0]
        if DS_ZONE[0] <= p < DS_ZONE[1] and p not in seen:
            seen.add(p)
            ptrs.append(p - BASE)
        i += 4
    for off in sorted(ptrs):
        e = d.index(b'\xff\x01', off) + 2
        out.append((off, etext.decode(d[off:e]), '', 'descs'))
    import personas as _per, demons as _dem   # noqa: E402 (record scans)
    for _k, a, ja in _per.records():
        out.append((a - BASE, ja, '', 'personas'))
    for _k, a, ja in _dem.records():
        out.append((a - BASE, ja, '', 'demons'))
    import affinity as _aff                   # noqa: E402 (record scans)
    for _k, a, ja in _aff.records():
        out.append((a - BASE, ja, '', 'affinity'))
    return out


def _small_ja(b):
    return ''.join(G2C.get(x, '<%02X>' % x) for x in b)


def dump():
    # SLPS_005.00 is written by several owners (this scan, the choice
    # table, the descriptions, the affinity lines): a position this scan
    # does not name is not vanished, it is someone else's row.
    rows, _man = toolbelt.dump_scaffold(
        REL, [(hex(off), psp) for off, _ja, psp, _fam in families(data())],
        keep_other=True)
    print(f'slps: {len(rows)} rows -> {toolbelt.gen_path(REL)}')


def encode_items(t):
    b = items.encode(t)
    if len(b) > items.MAXLEN:
        toolbelt.fail(f'items {t!r} is {len(b)} glyphs, max {items.MAXLEN}')
    return b


def encode_nick(t):
    if len(t) > NK_MAX:
        toolbelt.fail(f'nickname {t!r} longer than {NK_MAX} (panel clips)')
    return bytes(toolbelt.smallfont_char(c) for c in t) + b'\xff'


def encode_skill(t):
    return skills.encode(0, t)


def build():
    p = Patch('slps', OUT)
    sk0 = SK_FIRST - BASE
    nk0 = NK_FIRST - BASE
    it0 = IT_FIRST - BASE
    rows = toolbelt.merged_rows(REL)
    requested = []
    translated_skill_ids = []
    for r in rows:
        pos = int(r['pos'], 16)
        t = r['en'].strip()
        if (t and sk0 <= pos < sk0 + SK_STRIDE * SK_COUNT
                and (pos - sk0) % SK_STRIDE == 0):
            translated_skill_ids.append((pos - sk0) // SK_STRIDE + 1)
            tail = encode_skill(t)[SK_FIELD:]
            if len(tail) > 3:
                requested.append(tail)
    tails, tail_offsets = skills.pack_tails(requested)
    for r in rows:
        t = r['en'].strip()
        if not t:
            continue
        pos = int(r['pos'], 16)
        if sk0 <= pos < sk0 + SK_STRIDE * SK_COUNT and (pos - sk0) % SK_STRIDE == 0:
            skills.check_width(r.get('id', '?'), t)
            b = encode_skill(t)
            head = b[:SK_FIELD]
            if len(b) < SK_FIELD:
                head += b'\xff'
            head += bytes(SK_FIELD - len(head))
            p.org(toolbelt.file_va(REL, pos), head, f'{r["id"]} {t}')
            tail = b[SK_FIELD:]
            if tail:
                if len(tail) <= 3:
                    spare = (tail + b'\xff\x00\x00')[:3]
                else:
                    spare = bytes([0xFE, tail_offsets[tail], 0])
                p.org(toolbelt.file_va(REL, pos + SK_SPARE), spare)
            continue
        if nk0 <= pos < nk0 + NK_STRIDE * NK_COUNT and (pos - nk0) % NK_STRIDE == 0:
            b = toolbelt.fit_field(encode_nick(t), NK_FIELD, pad=b'\x00',
                                   what=f'{REL} id {r["id"]} {t!r}')
            p.org(toolbelt.file_va(REL, pos), b, f'{r["id"]} {t}')
            continue
        if it0 <= pos < it0 + IT_STRIDE * IT_COUNT and (pos - it0) % IT_STRIDE == 0:
            b = encode_items(t)
            if len(b) > IT_FIELD:
                b = b[:IT_FIELD]          # physical head; name_tails owns the rest
            elif len(b) < IT_FIELD:
                b += b'\xff' + bytes(IT_FIELD - len(b) - 1)
            p.org(toolbelt.file_va(REL, pos), b, f'{r["id"]} {t}')
            continue
        # personas/demons/descs/affinity rows belong to their own builders
        # (personas.py, demons.py, descs.py, affinity.py) - never placed here
    flags = skills.vwf_ownership(translated_skill_ids)
    flags_addr = toolbelt.asm_equ('SKILL_VWF_FLAGS_ADDR')
    slots_addr = toolbelt.asm_equ('SKILL_VWF_SLOTS_ADDR')
    if (slots_addr & 1 or flags_addr + len(flags) > slots_addr
            or slots_addr + 2 > toolbelt.asm_equ('SKILL_CODE_END')):
        toolbelt.fail('skill VWF source bitmap and aligned name-slot flags exceed their resident allocation')
    p.org(flags_addr, flags, 'source-derived skill ownership')
    p.org(slots_addr, b'\x00\x00',
          'runtime semantic name-slot ownership (no bits set at boot)')
    n = p.write()
    with open(OUT_TAILS, 'w', encoding='utf-8', newline='\n') as o:
        o.write(';; generated by tools/slps.py build - do not edit\n')
        o.write(';; skill tails longer than the 3 spare bytes (offsets from skill_tails_x)\n')
        if tails:
            o.write('    .byte ' + ', '.join(f'0x{x:02X}' for x in tails) + '\n')
    print(f'slps: {n} rows, {len(tails)} skill tail bytes -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if sys.argv[1:] else 'build']()
