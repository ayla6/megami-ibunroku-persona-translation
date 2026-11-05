"""Dungeon in-room messages (locked doors, closed shops ...) inside the dungeon data files D0x/D??.BIN.

  python tools/dngmsg.py     patch build/<D0x>/D??.BIN (run after smallfont_pages.py; reads the original if there is no build copy)

The boxes are dialogue strings (FF02 wait + FF01 end) of the dungeon script data, shown by the DNG overlay dialogue engine
(VWF ASCII, 1 byte per letter; FF03 = new line, FF04 = new page). The slots are the Japanese lengths (mostly 1-byte kana), so the
English is abbreviated to fit and the rest of the slot is zero-filled. 15 distinct texts, 21 places in the 16 dungeon files
(D00 Mikage / D01 / D05 / D0A ...); every occurrence of a Japanese text is replaced.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext   # noqa: E402
import dngtext  # noqa: E402 (jurisdiction: dngtext owns FF21 boxes)

ROOT = etext.ROOT
END = bytes((0xFF, 0x01))
TSV = os.path.join(ROOT, 'translation', 'manual', 'strings', 'DNGMSG.tsv')


GEN = os.path.join(ROOT, 'translation', 'generated', 'strings', 'DNGMSG.tsv')


def messages():
    """[(ja, en)] merging manual over generated, keyed by ja."""
    merged = {}

    def read(path):
        if not os.path.exists(path):
            return
        for line in open(path, encoding='utf-8').read().split('\n')[1:]:
            if line.strip():
                ja, en = line.split('\t', 1)
                merged[ja] = en
    read(GEN)
    _man = {}
    if os.path.exists(TSV):
        for line in open(TSV, encoding='utf-8').read().split('\n')[1:]:
            if line.strip():
                ja, en = line.split('\t', 1)
                _man[ja] = en
    for ja, en in _man.items():
        if etext.has_text(en) or ja not in merged:
            merged[ja] = en
    return [(ja, en) for ja, en in merged.items() if etext.has_text(en)]


def main():
    total = files = 0
    inside = []
    for fp in sorted(glob.glob(os.path.join(ROOT, 'data', 'psx', 'D0*', 'D*.BIN'))):
        name = os.path.basename(fp)
        if len(name) != 7:
            continue
        rel = os.path.relpath(fp, os.path.join(ROOT, 'data', 'psx'))
        bp = os.path.join(ROOT, 'build', rel)
        orig = open(fp, 'rb').read()
        d = bytearray(open(bp, 'rb').read() if os.path.exists(bp) else orig)
        # dngtext owns every FF21 box: this tool never writes inside one
        # (a substring replace there duplicates/corrupts the box's own
        # English: D02 あかず box read 'ItIt seems...').
        boxranges = []
        for off, ln, _ja in dngtext.boxes(orig):
            boxranges.append((off, off + ln))
        n = 0
        for ja, en in messages():
            jb = etext.encode(ja, end=END)
            eb = etext.encode(en, end=END)
            # writable extent per occurrence: the JA bytes plus alignment
            # padding (trailing zeros); all occurrences must fit, else the
            # same door would read differently in different dungeons.
            spots = []
            i = orig.find(jb)
            while i >= 0:
                cap = len(jb)
                while i + cap < len(orig) and orig[i + cap] == 0:
                    cap += 1
                if not any(a <= i < b for a, b in boxranges):
                    spots.append((i, cap))
                i = orig.find(jb, i + len(jb))
            if not spots:
                inside.append(ja)
                continue
            if any(len(eb) > cap for _, cap in spots):
                raise SystemExit(
                    f'dngmsg: over-cap draft {ja[:80]!r} '
                    f'(EN {len(eb)} bytes > caps {[c for _, c in spots]}): '
                    f'relocation needed, build refused')
            for i, cap in spots:
                d[i:i + cap] = eb + bytes(cap - len(eb))
                n += 1
        os.makedirs(os.path.dirname(bp), exist_ok=True)
        open(bp, 'wb').write(bytes(d))
        if n:
            files += 1
            total += n
    print(f'dngmsg: {total} messages in {files} files')
    if inside:
        print(f'dngmsg: {len(set(inside))} inside-box row(s) owned by dngtext, never touched')


if __name__ == '__main__':
    main()
