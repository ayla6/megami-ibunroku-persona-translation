"""The small-font page (the edited sheet) in every copy of it on the disc.

  python tools/smallfont_pages.py        write build/<dir>/<file> for each 2D/ and D0x/ file carrying the page

Every 2D-map (2D/2DLTS0x.BIN) and dungeon file (D0x/Dxx.BIN) loads its own copy of the page to VRAM (the battle panels
use the one at (960,256)), as do ADV/ADVCMD.BIN, ADV/ADVCMD0.BIN and OPEN.BIN (those three: tools/menu_gfx.py).
Copies are 256 px wide; they are found by their kana glyph rows (identical in all copies) and the whole glyph area
(codes 0..214, 84 pixel rows) is replaced with the page this build ships - the sheet, or the disc's own page
when `SF_VWF` is off - so the file keeps its size and every code the recorder draws is the sheet's art. The copy's
own art is whatever is neither the retail page nor the page the previous build left here (`page_prior`), so glyph art
an earlier build wrote is updated by the next one instead of sticking. The rows below the glyph area stay the copy's
own (the D0x copies are a differently tinted variant of the same page; their palettes tint the sheet's indices
exactly as they tint retail's). Needs files in `data/psx/`
(`python src/extraction_tools/psx/extract.py <image.bin> data/psx`).
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import menu_gfx      # noqa: E402
import smallfont_vwf  # noqa: E402
import tim           # noqa: E402

ROOT = tim.ROOT
DIRS = ['2D', 'D00', 'D01', 'D02', 'D03', 'D04']
ROWS = menu_gfx.GLYPH_ROWS          # the page's glyph area (codes 0..214)
PROBE = 3 * 12                      # the kana rows every copy stores identically: what identifies a copy


def reference():
    d = open(os.path.join(ROOT, 'data', 'psx', 'ADV', 'ADVCMD.BIN'), 'rb').read()
    t = tim.parse(d, menu_gfx.PAGE)
    return d[t['at']:t['at'] + 128 * 256]


def find_pages(b, page):
    """-> [(offset of pixel row 0, bytes per row)]"""
    out = []
    probe = page[13 * 128:13 * 128 + 120]
    i = b.find(probe)
    while i >= 0:
        for bpr in (128, 124):
            at = i - 13 * bpr
            if at >= 0 and all(b[at + y * bpr:at + y * bpr + bpr] == page[y * 128:y * 128 + bpr] for y in range(PROBE)):
                out.append((at, bpr))
                break
        i = b.find(probe, i + 1)
    return out


def main():
    page = reference()
    pix = smallfont_vwf.page_indices()[0]           # the page this build ships (the sheet, retail with SF_VWF off)
    prior = smallfont_vwf.page_prior()              # ... and the page the previous build left in these copies
    n = nl = 0
    for dname in DIRS:
        for path in sorted(glob.glob(os.path.join(ROOT, 'data', 'psx', dname, '*.BIN'))):
            orig = open(path, 'rb').read()
            pages = find_pages(orig, page)      # found in the original: a build copy may already carry another page
            if not pages:
                continue
            rel = os.path.relpath(path, os.path.join(ROOT, 'data', 'psx'))
            src = os.path.join(ROOT, 'build', rel)
            # Only edit a build copy that still has the original's length: this
            # step replaces page bytes in place and never resizes a file, so a
            # shorter copy is not ours to trust (it would truncate the disc
            # file). A tool that really rewrites a pack writes the same size.
            if not os.path.exists(src) or os.path.getsize(src) != len(orig):
                src = path                     # no builder touched this file
            b = bytearray(open(src, 'rb').read())
            ref = smallfont_vwf.unpack_page(page)
            for at, bpr in pages:
                # `old` is the packed block this copy holds (bpr bytes per
                # row); page_copy takes/returns packed bytes too. Slicing it
                # twice as long would shrink the file on assignment.
                old = bytes(b[at:at + bpr * ROWS])
                new = smallfont_vwf.page_copy(
                    smallfont_vwf.unpack_page(old), ref, pix, bpr * 2, ROWS, prior)
                assert len(new) == len(old), f'{rel}: page block changed size'
                b[at:at + len(old)] = new
                nl += menu_gfx.label_rows(b, at, bpr, page)     # MATK / MDEF where the kanji labels exist
            out = os.path.join(ROOT, 'build', rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            assert len(b) == len(orig), f'{rel}: page patch changed the file size'
            open(out, 'wb').write(bytes(b))
            n += 1
    smallfont_vwf.save_page_last(pix)
    print(f'small-font pages: {n} files patched ({smallfont_vwf.page_indices()[2]}), {nl} pages with MATK/MDEF labels')


if __name__ == '__main__':
    main()
