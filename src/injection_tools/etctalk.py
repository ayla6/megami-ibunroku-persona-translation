"""TALK/ETC.BIN (the "other layout" negotiation file): parse, dump, rebuild.

Layout:
  0x00  u32  = 4        base: table offsets are relative to it, so unit i starts at  table[i] + 4
  0x04  u32[199] table  ascending, FFFFFFFF padding up to 0x2000, text pool from 0x2000 (first 4 bytes FF FF FF FF)
  The last unit runs to the end of the file. Unlike the other TALK files a unit holds SEVERAL pages
  (<FFFB><FFF7> between them) with different speakers, and a 2-byte colour/portrait code (<FFEB>..<FFEE>) before a line.
  Units are the scripted Persona <-> demon conversations (see translation/HANDOFF.md), 199 of them, most are repeated variants.

   python src/injection_tools/etctalk.py check      parse + rebuild must be byte-identical, codec lossless
   python src/injection_tools/etctalk.py dump       write Japanese work rows for unique segments
   python src/injection_tools/etctalk.py assemble   combine filled TSV segments; empty segments remain untranslated
   python src/injection_tools/etctalk.py tsv        write translation/manual/talk/ETC.tsv
   python src/injection_tools/etctalk.py build [dir]  build/TALK/ETC.BIN (translated units only)
Workflow: etctalk.py dump; fill the segment TSV; assemble; tsv; talktl.py check/apply ETC; etctalk.py build.
Segments = the text between two control codes of a unit; units 0 and 198 (dead data / dummy) stay Japanese.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext  # noqa: E402
import vwf_wrap  # noqa: E402

ROOT = etext.ROOT
SRC = os.path.join(ROOT, 'data', 'psx', 'TALK', 'ETC.BIN')
POOL = 0x2000
BASE = 4


def parse(d):
    offs, i = [], BASE
    while i < POOL:
        v = struct.unpack_from('<I', d, i)[0]
        if v == 0xFFFFFFFF:
            break
        offs.append(v)
        i += 4
    starts = [o + BASE for o in offs]
    assert starts == sorted(starts) and starts[0] == POOL + BASE and starts[-1] < len(d)
    ends = starts[1:] + [len(d)]
    return [bytes(d[s:e]) for s, e in zip(starts, ends)]


def rebuild(d, units):
    head = bytearray(d[:POOL])
    pos = POOL + BASE
    for k, u in enumerate(units):
        struct.pack_into('<I', head, BASE + 4 * k, pos - BASE)
        pos += len(u)
    return bytes(head) + d[POOL:POOL + BASE] + b''.join(units)


SKIP = {0, 198}


def segments(path):
    """ordered {Japanese segment: index} over the unique-units work file (same numbering as translation/src/etc_en.py)"""
    segs = {}
    for line in open(path, encoding='utf-8').read().split(chr(10))[1:]:
        c = line.split(chr(9))
        if len(c) > 1 and c[0].isdigit():
            for t in re.split(r'<FF[0-9A-F]{2}>', c[1]):
                if t.strip():
                    segs.setdefault(t, len(segs))
    return segs


def wrap(en):
    """fit every page into 3 lines of <= 239 px: keep the line breaks and wrap too-wide lines at spaces; if that gives more than
    3 lines, reflow the whole page as one paragraph (control codes are atoms). Both passes lay the words out with the shared flow
    engine (vwf_wrap.flow_lines) at the TALK widths - there is no other wrapping anywhere."""
    import talktl

    def flow(text):
        return vwf_wrap.wrap_line(text, vwf_wrap.BOX_WIDTH, talktl.width,
                                  '<FFF6>')

    en = re.sub(r'(?<=[.!?,~*:)])<FFFC>(?=[A-Za-z])', '<FFFC> ', en)
    pages = []
    for pg in en.split('<FFFB><FFF7>'):
        end = ''
        for e in ('<FFF5>', '<FFEF>'):
            if pg.endswith(e):
                pg, end = pg[:-len(e)], e
        lines = []
        for ln in pg.split('<FFF6>'):
            lines += flow(ln)
        if len(lines) > 3:
            para = re.sub(r'(?<=[^ ])<FFFC>(?=[^ <])', '<FFFC> ', pg.replace('<FFF6>', ' '))
            lines = flow(re.sub(' +', ' ', para))
        pages.append('<FFF6>'.join(lines) + end)
    return '<FFFB><FFF7>'.join(pages)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = open(SRC, 'rb').read()
    units = parse(d)
    cmd = (sys.argv[1:] or ['check'])[0]
    if cmd == 'check':
        bad = sum(1 for u in units if etext.encode(etext.decode(u), end=None) != u)
        print(f'{len(units)} units, rebuild identical: {rebuild(d, units) == d}, codec mismatches: {bad}')
    elif cmd == 'dump':
        seen = {}
        for i, u in enumerate(units):
            seen.setdefault(etext.decode(u), i)
        p = os.path.join(ROOT, 'translation', 'manual', 'work', 'talk_ETC_ja.tsv')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='\n') as o:
            o.write('unit\tja\n')
            for ja, i in sorted(seen.items(), key=lambda x: x[1]):
                o.write(f'{i}\t{ja}\n')
        print(f'{len(units)} units, {len(seen)} unique -> {p}')
    elif cmd == 'assemble':
        seg_en = {}
        for line in open(os.path.join(ROOT, 'translation', 'manual', 'talk', 'ETC_segments_en.tsv'), encoding='utf-8').read().split(chr(10))[1:]:
            if not line.strip():
                continue
            k, v = line.split(chr(9))
            if k.isdigit() and etext.has_text(v):
                seg_en[int(k)] = v
        wj = os.path.join(ROOT, 'translation', 'manual', 'work', 'talk_ETC_ja.tsv')
        segs = segments(wj)
        miss = [i for i in range(len(segs)) if i not in seg_en]
        if miss:
            raise SystemExit(f'etctalk assemble: segments {miss[:10]} have empty English in translation/manual/talk/ETC_segments_en.tsv')
        by_ja = {t: seg_en[i] for t, i in segs.items()}
        out = ['unit	en	note']
        for line in open(wj, encoding='utf-8').read().split(chr(10))[1:]:
            c = line.split(chr(9))
            if len(c) > 1 and c[0].isdigit() and int(c[0]) not in SKIP:
                parts = re.split(r'(<FF[0-9A-F]{2}>)', c[1])
                en = ''.join(p if p.startswith('<FF') and p.endswith('>') and len(p) == 6 else (by_ja[p] if p.strip() else ('' if p else ''))
                             for p in parts)
                out.append(f'{c[0]}	{wrap(en)}	')
        open(os.path.join(ROOT, 'translation', 'manual', 'work', 'talk_ETC_en.tsv'), 'w', encoding='utf-8', newline=chr(10)).write(chr(10).join(out) + chr(10))
        print(f'{len(out) - 1} units assembled from {len(segs)} segments')
    elif cmd == 'tsv':
        p = os.path.join(ROOT, 'translation', 'manual', 'talk', 'ETC.tsv')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        old = {}
        if os.path.exists(p):
            for line in open(p, encoding='utf-8').read().split(chr(10))[1:]:
                c = line.split(chr(9))
                if len(c) >= 3 and c[0].isdigit():
                    old[int(c[0])] = (c[1], c[2], c[3] if len(c) > 3 else '')
        with open(p, 'w', encoding='utf-8', newline=chr(10)) as o:
            rows = []
            for i, u in enumerate(units):
                ja = etext.decode(u)
                en = old[i][1] if i in old and old[i][0] == ja and etext.has_text(old[i][1]) else ''
                note = old[i][2] if i in old and old[i][0] == ja else ''
                rows.append((i, ja, en, note))
            if any(r[3] for r in rows):
                o.write('unit\tja\ten\tnote' + chr(10))
                for i, ja, en, note in rows:
                    o.write(f'{i}\t{ja}\t{en}\t{note}' + chr(10))
            else:
                o.write('unit\tja\ten' + chr(10))
                for i, ja, en, note in rows:
                    o.write(f'{i}\t{ja}\t{en}' + chr(10))
        print('wrote', p)
    elif cmd == 'build':
        outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'build', 'TALK')
        # canonical rows (TALK/ETC, pos = the ORIGINAL unit offsets; manual
        # wins) - one read path with every other builder
        import toolbelt
        import talk as _t
        orig = _t.Talk('ETC', open(SRC, 'rb').read())
        rows = {}
        for r in (toolbelt.read_generated('TALK/ETC', optional=True)
                  + toolbelt.read_manual('TALK/ETC', optional=True)):
            rows[r['pos']] = r.get('en') or ''
        edits = {}
        for i, _u in enumerate(units):
            en = rows.get(hex(orig.starts[i]), '')
            if etext.has_text(en):
                try:
                    edits[i] = etext.encode(en, end=None)
                except ValueError as ex:
                    raise SystemExit(f'TALK/ETC unit {i}: {ex}')
        out = os.path.join(outdir, 'ETC.BIN')
        if not edits:
            if os.path.exists(out):
                os.remove(out)
            return
        new = rebuild(d, [edits.get(i, u) for i, u in enumerate(units)])
        os.makedirs(outdir, exist_ok=True)
        open(out, 'wb').write(new)
        print(f'ETC: {len(edits)} units edited, {len(d)} -> {len(new)} bytes')
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
