"""Ciphertext corpus + substitution solver for PSP Persona text (`text.py`).

Text units are u16BE glyph indices; FF xx (xx < 0x20) are control codes.
0x0000 is the word space (verified positionally). This tool:

  corpus REGION   dump every US/JP box's text-unit stream + word frequencies
  words REGION    rank unit-words (split on 0000) by frequency
  solve US        interactive-ish automatic monoalphabetic solve for the US
                  Latin map, checked against an English wordlist

The verified US glyph map lives in `codec.py` (unit -> character).
"""
import os
import re
import struct
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from text import load_psp  # noqa: E402

SPACE = 0x0000


def box_text_units(raw):
    """Text-unit sequence of one raw box: drop FF xx controls entirely.

    Returns (units, skeleton) where skeleton records control positions so the
    text can be re-wrapped later. Leading 0000 padding units are stripped.
    """
    units, skel = [], []
    i = 0
    while i + 1 <= len(raw):
        if raw[i] == 0xFF:
            skel.append((len(units), 'FF%02X' % raw[i + 1]))
            i += 2
        else:
            units.append(struct.unpack_from('>H', raw, i)[0])
            i += 2
    while units and units[0] == SPACE:
        units.pop(0)
        skel = [(p - 1, c) for p, c in skel if p > 0]
    return units, skel


def iter_boxes(region, files=('E0', 'E1', 'E2', 'E3', 'E4')):
    for which in files:
        c = load_psp(which, region)
        for i, e in enumerate(c.entries):
            for k in range(len(e.boxes)):
                yield which, i, k, e.box_bytes(k)


def cmd_words(region):
    words = Counter()
    nunits = nboxes = 0
    vocab = {}
    for which, i, k, raw in iter_boxes(region):
        units, _ = box_text_units(raw)
        nunits += len(units)
        nboxes += 1
        cur = []
        for u in units:
            if u == SPACE:
                if cur:
                    words[tuple(cur)] += 1
                    cur = []
            else:
                cur.append(u)
        if cur:
            words[tuple(cur)] += 1
    print(f'{region}: {nboxes} boxes, {nunits} text units, {len(words)} distinct words')
    for rank, (w, cnt) in enumerate(words.most_common(120)):
        print(f'{rank:>3} x{cnt:<7} len={len(w)} {" ".join("%04x" % u for u in w)}')
    return words


if __name__ == '__main__':
    if sys.argv[1] == 'words':
        cmd_words(sys.argv[2])
