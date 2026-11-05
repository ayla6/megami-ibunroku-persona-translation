"""Dungeon script boxes (story lines, locked doors, billboards ...) inside the dungeon data files D0x/D??.BIN.

  python tools/dngtext.py          patch build/<D0x>/D??.BIN (run after smallfont_pages.py; finds the boxes in the original, writes into the build copy if there is one)
  python tools/dngtext.py list     print every box found with its slot size and whether it is translated

Where the text comes from: the dungeon files are event records (fixed layout, sizes inside the records, no pointer table
for the text), the boxes are inline dialogue strings: ... FF21 00 00 <text> FF01 ... (also chained boxes without FF21,
speech between FF01 end codes). Boxes are found by scanning for FF01 and cutting the segment after the last FF21 0000 (or
after the previous FF01); a segment counts when it holds an FF02 wait code and >= 3 kana/kanji. Because the records cannot
grow, every English text is written IN PLACE into the Japanese slot (codes kept, rest zero-filled); the English must be
<= the slot including the FF01 end. English source: none right now (legacy dungeon translations removed); every box
is left in Japanese until PSP-sourced text lands. Dungeon speech engine: VWF ASCII, FF03 new line, FF04 new page, FF02 wait, FF0E choice, FF0F/FF07/FF08/FF10 name inserts + 1 param byte.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext  # noqa: E402
import strlib   # noqa: E402
import vwf_wrap   # noqa: E402

ROOT = etext.ROOT
TSV = os.path.join(ROOT, 'translation', 'manual', 'strings', 'DNGTEXT.tsv')


def load_all():
    """[(ja, en, note)] merging manual over generated, keyed by ja (this TSV
    has no numeric id column)."""
    def read(path):
        out = {}
        if not os.path.exists(path):
            return out
        for f in strlib.tsv_rows(path, required=('ja', 'en', 'note')):
            out[f['ja']] = (f['en'], f['note'])
        return out
    gen = read(os.path.join(ROOT, 'translation', 'generated', 'strings', 'DNGTEXT.tsv'))
    man = read(TSV)
    merged = dict(gen)
    for ja, (en, note) in man.items():
        if etext.has_text(en) or ja not in merged:
            merged[ja] = (en, note)
    return [(ja, en, note) for ja, (en, note) in merged.items()]


def load_rows():
    """[(ja, en)] dungeon translations; empty English keeps Japanese."""
    return [(ja, en) for ja, en, _note in load_all() if etext.has_text(en)]


def dump():
    """Recreate Japanese pointers for every unique dungeon-script box
    (keeps `en` and `note`: provenance survives regeneration)."""
    old = {ja: (en, note) for ja, en, note in load_all()}
    texts = {}
    for name, original, _ in files():
        for _, _, ja in boxes(open(original, 'rb').read()):
            en, note = old.get(ja, ('', ''))
            texts.setdefault(ja, (en if etext.has_text(en) else '', note))
    os.makedirs(os.path.join(ROOT, 'translation', 'manual', 'strings'), exist_ok=True)
    with open(TSV, 'w', encoding='utf-8', newline='\n') as out:
        out.write('ja\ten\tnote\n')
        for ja, (en, note) in texts.items():
            out.write(f'{ja}\t{en}\t{note}\n')
    print(f'wrote {TSV}: {len(texts)} unique Japanese boxes')


EN = dict(load_rows())
END = bytes((0xFF, 0x01))
# Fragments inside records without FF02 (menu prompts or posters).
SUBS = []
TOK = re.compile(r'<FF0[2-4]>')


def boxes(d):
    """[(offset, length, japanese text)] of every dialogue box in a dungeon file"""
    out, prev = [], 0
    for m in re.finditer(b'\xff\x01', d):
        seg = d[prev:m.start() + 2]
        start = prev
        prev = m.start() + 2
        k = seg.rfind(b'\xff\x21\x00\x00')
        if k >= 0:
            seg, start = seg[k + 4:], start + k + 4
        if b'\xff\x02' not in seg or len(seg) > 400:
            continue
        try:
            t = etext.decode(seg)
        except Exception:
            continue
        if sum(1 for c in t if ord(c) > 0x2000) < 3:
            continue
        out.append((start, len(seg), t))
    return out


def width_ok(en):
    t = en.replace('<FF0F>　', '<FF0F>あ').replace('<FF07>　', '<FF07>あ').replace('<FF08>　', '<FF08>あ')
    return all(vwf_wrap.text_width(l) <= vwf_wrap.BOX_WIDTH + 1 for l in TOK.sub('<FF03>', t).split('<FF03>'))


def files():
    for fp in sorted(glob.glob(os.path.join(ROOT, 'data', 'psx', 'D0*', 'D*.BIN'))):
        if len(os.path.basename(fp)) == 7:
            bp = os.path.join(ROOT, 'build', os.path.relpath(fp, os.path.join(ROOT, 'data', 'psx')))
            yield os.path.basename(fp), fp, bp


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) > 1 and sys.argv[1] == 'dump':
        dump()
        return
    lst = len(sys.argv) > 1 and sys.argv[1] == 'list'
    total = nfiles = 0
    skipped = []
    wide = []  # over-wide rows built as-is (warning only, never shortened)
    missing = set()
    for name, fp, bp in files():
        orig = open(fp, 'rb').read()
        d = bytearray(open(bp, 'rb').read() if os.path.exists(bp) else orig)
        n = 0
        restored = 0
        for off, ln, ja in boxes(orig):          # offsets from the ORIGINAL (the build copy may hold older patches)
            en = EN.get(ja)
            if lst:
                print(f'{name} {off:#x} {ln:3d} B {"OK " if en else "-- "}{ja}')
            if en is None:
                missing.add(ja)
                continue
            # writable extent: the slot plus its alignment padding (trailing
            # zeros to the next record; the reader consumes text to FF01, so
            # padding stays padding under every record-framing model).
            cap = ln
            while off + cap < len(orig) and orig[off + cap] == 0:
                cap += 1
            lead = len(ja) - len(ja.lstrip('　'))      # the game drops as many leading glyphs as the Japanese has indent cells
            eb = etext.encode(en, end=END)
            if lead and not en.startswith('　') and '<FF06>' not in en:
                eb2 = etext.encode('　' * lead + en, end=END)
                if len(eb2) <= cap:
                    en, eb = '　' * lead + en, eb2
            if len(eb) > cap:
                skipped.append(ja)
                # over-cap drafts never resurrect stale fills: the slot
                # goes back to Japanese until relocation lands them.
                if d[off:off + cap] != orig[off:off + cap]:
                    d[off:off + cap] = orig[off:off + cap]
                    restored += 1
                continue
            if '<FF06>' not in en and not width_ok(en.lstrip('　')):   # FF06 boxes are name-token puzzles
                # over-wide: builds as-is, wraps/scrolls in game (warning
                # only: textbox text is never shortened, never skipped).
                # (Byte-size overflow above still skips: fixed slots.)
                wide.append(ja)
            d[off:off + cap] = eb + bytes(cap - len(eb))
            n += 1
        for ja, en in SUBS:
            jb, eb = etext.encode(ja, end=None), etext.encode(en, end=None)
            if len(eb) > len(jb):
                raise SystemExit(f'dngtext: {en!r} needs {len(eb)} bytes, slot {len(jb)}')
            i = orig.find(jb)
            while i >= 0:
                d[i:i + len(jb)] = eb + bytes(len(jb) - len(eb))
                n += 1
                i = orig.find(jb, i + len(jb))
        if n and not lst:
            os.makedirs(os.path.dirname(bp), exist_ok=True)
            open(bp, 'wb').write(bytes(d))
            nfiles += 1
            total += n
        elif restored and not lst:
            # only restores (stale fills evicted): still write the file.
            os.makedirs(os.path.dirname(bp), exist_ok=True)
            open(bp, 'wb').write(bytes(d))
            nfiles += 1
    print(f'dngtext: {total} boxes in {nfiles} files, {len(missing)} Japanese boxes without English, {len(skipped)} over-cap draft(s) left as Japanese')
    for ja in sorted(set(skipped)):
        print(f'  over-cap anchor (JA kept for spill prefix match): {ja[:80]!r}')
    if wide:
        print(f'dngtext: {len(wide)} over-wide box(es) built as-is (warning only)')
    for ja in sorted(missing):
        print('  missing:', ja)


if __name__ == '__main__':
    main()
