"""Cached character-table and font generation owned by the alphabet component."""
from __future__ import annotations

from collections.abc import Callable
import os
import toolpath

def prepare_tables(py: str, incremental: bool = False, *,
                   run: Callable[..., None]) -> None:
    """Generate assembler character tables from their declared sources."""
    import build_step_cache
    src = os.path.join(toolpath.ROOT, 'src')
    build_step_cache.run(
        'character tables', [toolpath.script(name) for name in ('make_tbl.py', 'strlib.py')]
        + [os.path.join(src, 'injection', 'formats', 'font_map.tsv')],
        [os.path.join(src, 'mods', 'base', 'asm', 'common', name) for name in ('persona.tbl', 'persona_vwf.tbl')],
        lambda: run(py, 'make_tbl.py'),
        os.path.join(toolpath.ROOT, 'build', 'step_cache', 'character-tables.tsv'), reuse=incremental)


def prepare_vwf_font(py: str, incremental: bool = False, *,
                   run: Callable[..., None]) -> None:
    """Generate the dialogue font; cache only its explicitly owned outputs."""
    import build_step_cache
    src = os.path.join(toolpath.ROOT, 'src')
    font = toolpath.FONT_DIR
    build_step_cache.run(
        'dialogue font', [os.path.join(src, 'injection', 'fonts', 'make_vwf_font.py'),
                          os.path.join(src, 'injection', 'other', 'name_grid.py'),
                          os.path.join(src, 'injection', 'text', 'vwf_wrap.py'),
                          __file__,
                          os.path.join(src, 'pipeline', 'build_step_cache.py'),
                          os.path.join(font, 'sheet.png'),
                          os.path.join(font, 'sheet-characters.tsv'),
                          os.path.join(font, 'reclaimed-kanji.tsv'),
                          os.path.join(font, 'small_serif.png'),
                          os.path.join(src, 'mods', 'latin-alphabet', 'asm', 'vwf', 'vwf_dialog.asm'),
                          os.path.join(src, 'mods', 'base', 'asm', 'common', 'addresses.inc'),
                          os.path.join(toolpath.DEFAULT_TRANSLATION, 'generated'),
                          os.path.join(toolpath.DEFAULT_TRANSLATION, 'manual')],
        [toolpath.font_path(kind, edition) for edition in toolpath.FONT_EDITIONS
         for kind in ('font', 'width', 'index', 'glyphs')],
        lambda: run(py, 'make_vwf_font.py'),
        os.path.join(toolpath.ROOT, 'build', 'step_cache', 'dialogue-font.tsv'), reuse=incremental)

