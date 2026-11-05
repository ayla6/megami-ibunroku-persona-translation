"""Automatic text extraction from PSP BOOT.BIN (both regions) - disc data only.

Outputs below are MACHINE-GENERATED (overwritten on every run - do not hand-edit;
manual overrides live in translation/manual/):

  data/cache/boot_choices_us.tsv  US choice-option table (idx, en)
  data/cache/boot_choices_jp.tsv  JP choice-option table (idx, ja)
  data/cache/boot_strings.tsv (us)  all decoded US BOOT C-strings (offset, text)
  data/cache/boot_strings.tsv (jp)  all decoded JP BOOT C-strings (offset, text)
  data/cache/boot_quote (via port_quote.py)     US opening-butterfly quote
  data/cache/boot_quote (via port_quote.py)     JP opening-butterfly quote
  translation/generated/fmv/opening.tsv        the opening-movie quote (port_quote.py)

Glyph codecs come from `codec.py` and the mapping in `src/extraction_tools/psp_glyphs.tsv`.
No web/FAQ input is read here.

Layout inside BOOT.BIN (verified by decoding):
  LE u16 C-strings (0000-terminated; 8140 = space in US) hold the opening
    quote + title/system menus. The JP quote sits just before the title menu
    ('物語の最初から'); the US quote just before 'Start from the beginning'.
    Both files store the quote last-sentence-first and doubled; the extractor
    dedupes and returns narrative order.
  One BE u16 option table (FF03-separated; 0000 and 8140 both space; options
    padded to 4-byte boundaries) holds the dialogue-choice options in an
    order mirroring the PS1 SLPS_005.00 table (PSP-only menus first, then
    PS1 idx31 down to idx0; some PSP wordings/positions differ - see
    tools/choices.py BOOT_MAP, verified against the JP table + JP box order).
    US table: file offset 0x2c06ec. JP table: file offset 0x2a57e8.

US BOOT.BIN on the disc is encrypted; it is decrypted from EBOOT.BIN with
`pip install pyeboot` (pyeboot.decrypt(src, dst), reproducible: re-decrypting
yields a byte-identical file). JP BOOT.BIN needs no decryption. The decrypted
image is cached at build/us_boot_decrypted.bin. --us-boot points at a
pre-decrypted image instead.

Usage:
  python src/extraction_tools/psp/boot.py extract [--us-boot PATH]
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from codec import US_MAP  # noqa: E402
from tables import (  # noqa: E402  shared BOOT readers/decoders
    JP_BOOT, US_CACHE, US_EBOOT, US_KNOWN, US_LE, US_SPACE,
    be_table, jp_boot, jp_map, le_strings, us_boot,
)
US_TEXT = os.path.join(ROOT, 'data', 'cache', 'boot_choices_us.tsv')
JP_TEXT = os.path.join(ROOT, 'data', 'cache', 'boot_choices_jp.tsv')
US_TABLE = 0x2c06ec       # BE option table ('Yes, it was.' ...)
US_TABLE_HEAD = 'Yes, it was.'
JP_TABLE = 0x2a57e8       # BE option table ('登録する' ...)
JP_TABLE_HEAD = '登録する'


def quote_us(data):
    """Narrative-order opening quote lines from the US BOOT LE strings."""
    strs = sorted(le_strings(data, US_LE, US_SPACE))
    anchor = next((o for o, s in strs if 'Start from the beginning' in s), None)
    if anchor is None:
        raise SystemExit('boot: US quote anchor (title menu) not found')
    below = [(o, s) for o, s in strs if o < anchor]
    chain = []
    prev = anchor
    for o, s in reversed(below):
        if prev - o > 0x100:
            break
        prev = o
        chain.append((o, s))
        if len(chain) > 40:
            break
    chain.reverse()
    # file stores the quote last-sentence-first and doubled: dedupe,
    # expect [-Zhuangzi, ..., Once, ...]
    uniq = []
    for o, s in chain:
        if all(s != u for _uo, u in uniq):
            uniq.append((o, s))
    # A chunk mixing kanji is data, never quote text (the US quote is
    # English). The author line also
    # carries the PSP's own decoration mark ('＾-Zhuangzi').
    uniq = [(o, s) for o, s in uniq
            if not any('\u3040' <= c <= '\u9fff' for c in s)]
    if not uniq or not uniq[0][1].endswith('-Zhuangzi') \
            or not uniq[-1][1].startswith('Once,'):
        raise SystemExit(f'boot: unexpected US quote layout: {[s[:30] for _o, s in uniq]}')
    lines = list(reversed(uniq[1:])) + [uniq[0]]
    if len(lines) != 10:
        raise SystemExit(f'boot: expected 10 US quote lines, got {len(lines)}: {[s for _o, s in lines]}')
    return lines


def cmd_extract(us_boot_path=None):
    us = us_boot(us_boot_path)
    jp = open(JP_BOOT, 'rb').read()
    us_opts, us_end = be_table(us, US_TABLE, US_MAP, strict=True)
    if not us_opts or us_opts[0] != US_TABLE_HEAD:
        raise SystemExit(f'boot: US table head mismatch at {US_TABLE:#x}: {us_opts[:1]}')
    jm = jp_map()
    jp_opts, _ = be_table(jp, JP_TABLE, jm, strict=False)
    if not jp_opts or JP_TABLE_HEAD not in jp_opts[0]:
        raise SystemExit(f'boot: JP table head mismatch at {JP_TABLE:#x}: {jp_opts[:1]}')
    print(f'boot: {len(us_opts)} US options (to {us_end:#x}), {len(jp_opts)} JP options; '
          f'text lives in extracted_text/psp_us/us/jp EBOOT.tsv, quote rows in port_quote.py')


if __name__ == '__main__':
    args = sys.argv[1:] or ['extract']
    ub = None
    if '--us-boot' in args:
        ub = args[args.index('--us-boot') + 1]
    if args[0] == 'extract':
        cmd_extract(ub)
    else:
        raise SystemExit(__doc__)
