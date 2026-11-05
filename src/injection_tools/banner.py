"""Battle banner names (BTLP): the name shown in the banner at the top of the screen when a skill / attack / item is used.

  python tools/banner.py dump     write/refresh translation/manual/BTLP.BIN/BANNER.tsv (keeps the `en` and `note` columns)
  python tools/banner.py build    QA + generate build/banner_btlp.asm (BTLP section) and build/banner_slps.asm (SLPS)

Layout (BTLP.BIN, RAM = file offset + 0x800643C4): pointer table of 347 absolute words at 0x800D92F4; entry
0 and 112/113 = RESERVE, 1-162 = Persona spells (same id as the skill records, tools/skills.py), 163-242 = enemy /
physical attacks, 243-346 = items (a second reader uses 0x800D96BC = entry 242 as the item base, so positions are
fixed). Strings are in small-font single-byte codes like tools/items.py (the banner call passes a1 = 1, the
small-font-name path: VWF bytes draw wrong glyphs there, found 2026-10-13 with VWF 'l'/'b' showing as I/q in game).
Pool 0x800D835C-0x800D92F4.
English is longer than the kana: the pool is re-packed (identical strings and suffixes shared) and what does not
fit spills into unreferenced SLPS functions (SPILL; the pointers are absolute and the main EXE is resident).
`en`: any text etext.encode accepts (ASCII through the VWF); names from the 2009 PSP release (glossary.tsv).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext  # noqa: E402
import items  # noqa: E402
import smallfont_lc  # noqa: E402
import strlib  # noqa: E402

ROOT = etext.ROOT
B = 0x800643C4
TABLE = 0x800D92F4
COUNT = 347
POOL = (0x800D835C, 0x800D92F4)
# unreferenced SLPS functions (tools/deadfuncs.py) not used by anything else; see common/addresses.inc
SPILL = [(0x80026A10, 0x80026A54), (0x80018B50, 0x80018B88), (0x8002C374, 0x8002C3E0)]
TSV = os.path.join(ROOT, 'translation', 'manual', 'BTLP.BIN', 'BANNER.tsv')
OUT_BTLP = os.path.join(ROOT, 'build', 'banner_btlp.asm')
OUT_SLPS = os.path.join(ROOT, 'build', 'banner_slps.asm')
NL = chr(10)
END = b'\xff\xf5'


def data():
    return open(os.path.join(ROOT, 'data', 'psx', 'BTLP.BIN'), 'rb').read()


def decode(d, p):
    out, i = [], p - B
    while d[i] != 0xFF:
        c = d[i]
        if 0x80 <= c <= 0x87:
            g = ((c & 7) << 8) | d[i + 1]
            i += 2
        else:
            g = c
            i += 1
        out.append(etext.glyph.get(g, '<G%03X>' % g))
    return ''.join(out)


def records():
    d = data()
    out = []
    for k in range(COUNT):
        p = struct.unpack_from('<I', d, TABLE + 4 * k - B)[0]
        assert POOL[0] <= p < POOL[1], (k, hex(p))
        out.append((k, p, decode(d, p)))
    return out


def read_tsv(manual_only=False):
    return {k: (en, note) for k, (ja, en, note)
            in strlib.read(TSV, 'BANNER.tsv', manual_only).items()}


def generated_map():
    """{idx: (ja, en)} of the PSP/cross-generated table, for dump trimming."""
    return {k: (ja, en) for k, (ja, en, note)
            in strlib.generated('BANNER.tsv').items() if en.strip()}


def dump():
    old = read_tsv(manual_only=True)
    auto = generated_map()
    rows = []
    for k, p, ja in records():
        en, note = old.get(k, ('', ''))
        port = auto.get(k)
        if not en and port and port[0] == ja:
            continue
        rows.append(f'{k}\t{p:08X}\t{ja}\t{en}\t{note}')
    if not rows:
        if os.path.exists(TSV):
            os.remove(TSV)
    else:
        with open(TSV, 'w', encoding='utf-8', newline=NL) as o:
            o.write('idx\tptr\tja\ten\tnote' + NL)
            o.write(NL.join(rows) + NL)
    print('wrote', TSV)


def encode_small(t):
    """Small-font single-byte encoding (battle banners render through the
    small-font name path, not the dialogue VWF).
    Same charset as tools/items.py (A-Z 0-9 space / : - a-z . ')."""
    import items
    out = bytearray()
    for c in t:
        if 'A' <= c <= 'Z' or '0' <= c <= '9' or c in items.EXTRA:
            out.append(items.glyph(c))
        elif 'a' <= c <= 'z' or c in smallfont_lc.PUNCT:
            out.append(smallfont_lc.code(c))
        else:
            raise ValueError(f'no small-font glyph for {c!r}')
    return bytes(out)


def build():
    en = read_tsv()
    recs = records()
    d = data()
    want = {}                                   # idx -> encoded bytes (with END)
    for k, p, ja in recs:
        t = en.get(k, ('', ''))[0].strip()
        if t:
            try:
                want[k] = encode_small(t) + END
            except ValueError as ex:
                raise SystemExit(f'banner: {k} {t!r}: {ex}')
        else:                                   # untranslated: keep the original bytes
            i = p - B
            j = d.index(END, i)
            want[k] = bytes(d[i:j + 2])
    # place unique strings, longest first, sharing suffixes
    placed = {}                                 # bytes -> address
    zones = [list(POOL)] + [list(z) for z in SPILL]
    chunks = {i: [] for i in range(len(zones))}  # zone -> [(addr, bytes)]
    for s in sorted(set(want.values()), key=len, reverse=True):
        host = next((h for h in placed if h.endswith(s)), None)
        if host is not None:
            placed[s] = placed[host] + len(host) - len(s)
            continue
        for zi, z in enumerate(zones):
            if z[1] - z[0] >= len(s):
                placed[s] = z[0]
                chunks[zi].append((z[0], s))
                z[0] += len(s)
                break
        else:
            raise SystemExit(f'banner: out of space ({len(s)} bytes for {s.hex()})')
    with open(OUT_BTLP, 'w', newline=NL) as o:
        o.write(';; generated by tools/banner.py build - battle banner names (BTLP pool + pointer table)' + NL)
        a0 = POOL[0]
        o.write(f'.org {a0:#x}{NL}.area {POOL[1] - POOL[0]:#x}, 0{NL}')
        for a, s in chunks[0]:
            o.write('    .byte ' + ', '.join(f'0x{c:02X}' for c in s) + NL)
        o.write('.endarea' + NL)
        o.write(f'.org {TABLE:#x}{NL}')
        for k in range(COUNT):
            o.write(f'    .word {placed[want[k]]:#x}' + NL)
    spilled = 0
    with open(OUT_SLPS, 'w', newline=NL) as o:
        o.write(';; generated by tools/banner.py build - battle banner names that did not fit BTLP' + NL)
        for zi in range(1, len(zones)):
            for a, s in chunks[zi]:
                o.write(f'.org {a:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in s) + NL)
                spilled += len(s)
    used = zones[0][0] - POOL[0]
    print(f'banner: {sum(1 for k in want if en.get(k, ("", ""))[0].strip())}/{COUNT} translated, '
          f'pool {used}/{POOL[1] - POOL[0]} bytes, {spilled} spilled to SLPS -> {OUT_BTLP}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
