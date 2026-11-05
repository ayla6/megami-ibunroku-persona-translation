"""DNG spill-over texts: full English for dungeon boxes that exceed their
in-place slot (even with alignment padding).

  python tools/dngspill.py     write build/dng_spill.asm (table + spill bytes,
                               included in the DNG overlay extension by main.asm)

Mechanism (see src/asm/dng/spill.asm): the dungeon script interpreter reads
box text inline (s5 streams record bytes to FF01). For spilled boxes the
hook redirects s5 to spill bytes when the 24 bytes at s5 match the box's
Japanese prefix; the box-end FF01 pops the engine's own resume, so nothing
else changes (waits/pages/timing untouched). Boxes hold arbitrary text: a
row whose English cannot go in place (dngpacks.place) ships its full text
here instead - nothing is ever cut. Spilled slots stay Japanese, so the JA
prefix is always present to match.

The fingerprint is the RAW FILE BYTES at that occurrence's box head, so a
box shorter than 24 bytes carries one (the bytes after its FF01 are part of
the match). Two occurrences of the same wording can therefore differ past
the FF01 (adjacent file data); each distinct 24-byte prefix gets its own
table entry, sharing the encoded English when the wording is the same. A
prefix that maps to two different wordings refuses the build. Every raw
occurrence of every emitted prefix must be an own spilled box start or lie
inside an in-place slot (whose Japanese bytes are overwritten at runtime);
anything else refuses the build instead of letting the hook misfire.
"""
import glob
import os
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import dngpacks           # noqa: E402 (the box scan + placement rules)
import etext              # noqa: E402
import strlib              # noqa: E402

ROOT = etext.ROOT
OUT = os.path.join(ROOT, 'build', 'dng_spill.asm')
IMAGE = os.path.join(ROOT, 'build', 'dng_spill.bin')
NL = chr(10)
PREFIX_LEN = 24  # bytes of the box head the hook matches (words: the table
                 # entry is PREFIX_LEN + a pointer). 12 could not tell a short
                 # box from a longer box sharing its head
                 # ('扉は固く閉ざされている<FF02><FF01>' vs
                 # '...<FF02><FF04>外には出られそうにない...'); the fingerprint is
                 # the RAW FILE BYTES at the box start, so a box shorter than
                 # the fingerprint still carries one (the bytes past its FF01
                 # are part of the identity)
# Spill text shares the DNG.BIN extension (src/asm/dng/): the extension is
# appended to the overlay file and carried by the same mechanism as the VWF
# script code (~68KB today), so full text is never held back for space.
BUDGET = 16384


def occurrences(files, blobs, byfile):
    """[(fp, off, ln, ja, en, eb, cap)] every box carrying English.

    eb is None when the English fits in place (dngpacks.place); otherwise it
    is the encoded spill text and the box stays Japanese in the pack. Rows
    are pos-keyed; a stale pos refuses the build.
    """
    out = []
    for fp in files:
        rel = os.path.relpath(fp, os.path.join(ROOT, 'data', 'psx'))[:-4]
        posmap = {hex(off): ja for off, _ln, ja in byfile[fp]}
        rows = {}
        for r in toolbelt.merged_rows(rel):
            text = (r.get('en') or '').strip()
            if not etext.has_text(text):
                continue
            if r['pos'] not in posmap:
                raise SystemExit(f'dngspill: {rel} pos {r["pos"]} is stale - '
                                 f'build refused')
            rows[r['pos']] = text
        for off, ln, ja in byfile[fp]:
            en = rows.get(hex(off))
            if not en:
                continue
            placed, cap, _chosen = dngpacks.place(en, ja, blobs[fp], off, ln)
            if placed is not None:
                out.append((fp, off, ln, ja, en, None, cap))
                continue
            try:
                eb = etext.encode(dngpacks.indent_en(en, ja), end=dngpacks.END)
            except ValueError as ex:
                raise SystemExit(f'dngspill: {ja[:40]!r}: encode-fail {ex} - '
                                 f'build refused')
            out.append((fp, off, ln, ja, en, eb, cap))
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    files = [fp for fp in sorted(glob.glob(os.path.join(ROOT, 'data', 'psx', 'D0*', 'D*.BIN')))
             if len(os.path.basename(fp)) == 7]
    blobs = {fp: open(fp, 'rb').read() for fp in files}
    byfile = {fp: dngpacks.boxes(blobs[fp]) for fp in files}
    occs = occurrences(files, blobs, byfile)
    # One table entry per distinct spilled occurrence fingerprint. The same
    # wording can appear at several box starts with different bytes past its
    # FF01; each needs its own match, but only one encoded text is stored.
    texts = {}       # prefix -> encoded English
    own = {}         # prefix -> {(file, box start)}
    order = []       # prefixes in first-seen order (deterministic)
    inplace = {}     # file -> [(box start, overwritten slot length)]
    for fp, off, ln, ja, en, eb, cap in occs:
        if eb is None:
            inplace.setdefault(fp, []).append((off, cap))
            continue
        pre = blobs[fp][off:off + PREFIX_LEN]
        if len(pre) < PREFIX_LEN:
            raise SystemExit(f'dngspill: {ja[:40]!r}: box head shorter than '
                             f'the fingerprint - build refused')
        if not pre[:4].strip(b'\0'):
            raise SystemExit(f'dngspill: {ja[:40]!r}: fingerprint starts with '
                             f'a zero word, which the table sentinel reads as '
                             f'its end - build refused')
        if pre in texts and texts[pre] != eb:
            raise SystemExit(
                f'dngspill: {ja[:40]!r}: 24-byte prefix at '
                f'{os.path.basename(fp)}@{off:#x} maps to different English - '
                f'build refused')
        if pre not in texts:
            texts[pre] = eb
            order.append(pre)
        own.setdefault(pre, set()).add((fp, off))
    # Prefix uniqueness: an emitted fingerprint may occur only at its own
    # spilled box start or inside a slot that builds in place (those JA
    # bytes are English at runtime, so the hook cannot see them). Any other
    # occurrence would redirect the wrong text and refuses the build.
    counts = {}
    for pre in order:
        n = 0
        for fp in files:
            d = blobs[fp]
            i = 0
            while True:
                i = d.find(pre, i)
                if i < 0:
                    break
                n += 1
                if (fp, i) not in own.get(pre, ()) and not any(
                        o <= i < o + c for o, c in inplace.get(fp, ())):
                    other = next((bja for boff, _bl, bja in byfile[fp]
                                  if boff == i), None)
                    raise SystemExit(
                        f'dngspill: prefix at {os.path.basename(fp)}@{i:#x} '
                        f'({other[:20] if other else "not a box"}) is neither '
                        f'its spilled box nor an in-place slot - build refused')
                i += 1
        counts[pre] = n
    # Share encoded text blobs whose wording is identical.
    labels, blobs_out, text_ja = {}, [], {}
    for pre in order:
        eb = texts[pre]
        if eb not in labels:
            labels[eb] = len(blobs_out)
            blobs_out.append(eb)
            text_ja[eb] = next(ja for fp, off, ln, ja, en, oeb, cap in occs
                               if oeb == eb)
        print(f'dngspill: spill {text_ja[eb][:56]!r} '
              f'({counts[pre]} occurrence(s), {len(eb)} bytes)')
    total = sum(len(eb) for eb in blobs_out)
    if total > BUDGET:
        raise SystemExit(f'dngspill: {total} spill bytes exceed {BUDGET} budget')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by src/injection_tools/dngspill.py - do not edit' + NL)
        o.write('.org DNG_SPILL_ADDR' + NL)
        o.write('dng_spill_tab:' + NL)
        for pre in order:
            w = struct.unpack('<%dI' % (PREFIX_LEN // 4), pre)
            o.write('    .word ' + ', '.join(f'0x{x:08X}' for x in w)
                    + f', dng_spill_t{labels[texts[pre]]}'
                    f'  ; {counts[pre]} occurrence(s)' + NL)
        o.write('    .word ' + ', '.join(['0'] * (PREFIX_LEN // 4 + 1)) + '  ; sentinel' + NL)
        for idx, eb in enumerate(blobs_out):
            o.write(f'dng_spill_t{idx}:  ; {text_ja[eb][:56]!r}' + NL)
            o.write('    .byte ' + ', '.join(f'0x{x:02X}' for x in eb) + NL)
        # The generated block owns an explicit extension window. Its bounds
        # do not depend on the including file's current assembly cursor.
        o.write('dng_spill_end:' + NL)
        o.write('.if dng_spill_tab != DNG_SPILL_ADDR || dng_spill_end > DNG_SPILL_LIMIT' + NL)
        o.write('    .error "dngspill: spill data is outside its assigned extension"' + NL)
        o.write('.endif' + NL)
        o.write('    .align 4  ; hook code follows continuously' + NL)
    # Independent byte readback for the assembler output, including pointers.
    at = toolbelt.asm_equ('DNG_SPILL_ADDR')
    cursor = at + (len(order) + 1) * (PREFIX_LEN + 4)
    text_at = {}
    for eb in blobs_out:
        text_at[eb] = cursor
        cursor += len(eb)
    image = bytearray()
    for pre in order:
        image.extend(pre + struct.pack('<I', text_at[texts[pre]]))
    image.extend(bytes(PREFIX_LEN + 4))
    image.extend(b''.join(blobs_out))
    Path(IMAGE).write_bytes(image)
    print(f'dngspill: {len(order)} spilled occurrence prefix(es), '
          f'{len(blobs_out)} text(s), {total} bytes -> {os.path.relpath(OUT, ROOT)}')


def verify():
    """Read back the assigned spill window, entry hook, and sector-rounded load."""
    built = Path(ROOT, 'build', 'DNG.BIN').read_bytes()
    expected = Path(IMAGE).read_bytes()
    sym = {}
    for line in Path(ROOT, 'build', 'persona.sym').read_text().splitlines():
        match = re.match(r'^([0-9A-Fa-f]{8})\s+(\S+)', line)
        if match:
            sym[match[2]] = int(match[1], 16)
    base = toolbelt.asm_equ('OVERLAY_SLOT_ADDR')
    start = toolbelt.asm_equ('DNG_SPILL_ADDR')
    limit = toolbelt.asm_equ('DNG_SPILL_LIMIT')
    hook, end = sym['dng_spill_hook'], sym['dng_spill_hook_end']
    if not (sym['dng_glue_end'] <= start == sym['dng_spill_tab']
            and sym['dng_spill_end'] == start + len(expected)
            and start + len(expected) <= hook < end <= limit and hook % 4 == 0):
        raise SystemExit('dngspill: verify: spill data/code is outside its assigned extension')
    if built[start-base:start-base+len(expected)] != expected:
        raise SystemExit('dngspill: verify: assembled spill table/text differs from generated bytes')
    entry = struct.pack('<II', 0x08000000 | ((hook >> 2) & 0x3FFFFFF), 0)
    if built[0x80073F90-base:0x80073F90-base+8] != entry:
        raise SystemExit('dngspill: verify: interpreter entry does not jump to the spill hook')
    loaded_end = base + ((len(built) + 0x7FF) // 0x800) * 0x800
    if loaded_end > toolbelt.asm_equ('DNG_ITEM_DATA_END'):
        raise SystemExit('dngspill: verify: sector-rounded overlay load reaches the GPU work area')
    print(f'dngspill: verify: data {start:#x}..{start+len(expected):#x}, '
          f'hook {hook:#x}..{end:#x}, loaded through {loaded_end:#x}')


if __name__ == '__main__':
    verify() if sys.argv[1:] == ['verify'] else main()
