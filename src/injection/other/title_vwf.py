"""Original-face metrics for the title's bounded saved-name sprite writer."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import toolpath
import smallfont_variants
import smallfont_vwf

ROOT: Final = Path(toolpath.ROOT)


def build() -> None:
    page, _palette, _width = smallfont_vwf.disc_page()
    metrics = smallfont_variants.original_metrics(page, smallfont_vwf.glyph_rows)
    table = smallfont_vwf.btl_orig_widths(metrics, smallfont_vwf.text_bits())
    low, high, count = smallfont_vwf.btl_orig_runs(table)
    output = ROOT / 'build'
    output.mkdir(exist_ok=True)
    (output / 'title_original_metrics.bin').write_bytes(metrics)
    (output / 'title_name_metrics.bin').write_bytes(table[:low] + table[high:high + count])
    (output / 'title_name_metrics.asm').write_text(
        f'.definelabel TITLE_NAME_LOW, {low}\n'
        f'.definelabel TITLE_NAME_HIGH, {high}\n'
        f'.definelabel TITLE_NAME_COUNT, {count}\n')


if __name__ == '__main__':
    build()
