"""The base game's credits shortcut: its END.EXE script (build/end_credits.asm).

  python src/injection_tools/end_credits.py

The staff roll is the tail of retail ending 1's script: after the story pages
it loads the credits artwork, then walks the thirteen credits text pages
(0x38..0x44) and the closing logos. The shortcut plays that tail on its own
ending (5), so nothing is retyped and no page is invented:

  - the credits text pages are the 'n' rows of the page map, translated
    mechanically from the END.BIN page offsets through g_end_sectors;
  - the script starts at the artwork load that the first credits page sits
    on (the nearest kind-0 load before it), so the page keeps its backdrop;
  - the music opcode already before that point is kept (the roll's music);
  - the rest of the halfwords are copied verbatim from retail, except the
    bad endings' final 0xA (END.EXE's no-op "hold the last screen" opcode):
    ending 5 ends the roll with 0x9 instead, so END.EXE's done: returns the
    resident to the boot/title state.

The generated file moves the five-entry ending-script table into a dead
END.EXE function so it can hold the sixth (credits) entry, patches the
table pointer in END.EXE's ending selection, and writes the table and the
script at that home.
"""
import csv
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402

ROOT = toolbelt.ROOT
OUT = os.path.join(ROOT, 'build', 'end_credits.asm')
PAGE_MAP = os.path.join(toolbelt.SOURCE_MAPPINGS, 'endtext_map.tsv')

END_BASE = 0x80080000
END_T_SIZE = 0x2D800

# Retail END.EXE addresses (the project's pressing).
SCRIPT_TABLE = 0x80099FF4      # g_end_scripts, five words
SECTORS = 0x80099698           # g_end_sectors, u16 per END.BIN page
SECTOR_COUNT = 0xAC // 2
ENDING_1 = 1                   # the ending whose tail is the staff roll
TABLE_PTR_LUI = 0x80080D90     # lui at, 0x800a
TABLE_PTR_ADDIU = 0x80080D94   # addiu at, at, -0x600c
CREDITS_SCRIPTS = 0x80091818   # dead END.EXE function (0x3a4 bytes)
SCRIPT_COUNT = 5

# One argument for these opcodes, none for 6/9/0xA (end of script).
ONE_ARG = {0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x7, 0x8, 0xB}
NO_ARG = {0x6, 0x9, 0xA}


def rd(d, addr, size):
    """Bytes of the loaded END.EXE image at a RAM address."""
    off = 0x800 + (addr - END_BASE)
    if off < 0x800 or off + size > len(d):
        raise ValueError(f'{addr:#x} is outside END.EXE')
    return d[off:off + size]


def script_end(words):
    """Halfword index just past the script's terminator (9 = end, or the
    0xA hold that the bad endings leave on the last screen)."""
    i = 0
    while i < len(words):
        op = words[i]
        if op in ONE_ARG:
            i += 2
        elif op in NO_ARG:
            if op in (9, 0xA):
                return i + 1
            i += 1
        else:
            raise ValueError(f'unknown ending-script opcode {op:#x} at {i}')
    raise ValueError('ending script has no end opcode')


def credits_pages(sectors):
    """END.BIN page indices whose text is a staff-roll page ('n' layout)."""
    pages = []
    with open(PAGE_MAP, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            if row['layout'] != 'n':
                continue
            off = int(row['ps1_tim_offset'], 16)
            hit = [i for i, s in enumerate(sectors) if s * 2048 + 4 == off]
            if len(hit) != 1:
                raise ValueError(f'page map offset {off:#x} names {len(hit)} '
                                 'END.BIN pages')
            pages.append(hit[0])
    if not pages:
        raise ValueError('the page map has no staff-roll (n) pages')
    return pages


def plan(d):
    """Return (table_words, script_words) for the credits-only ending."""
    if len(d) < 0x800 + END_T_SIZE:
        raise ValueError('END.EXE is shorter than its t_size')
    table = list(struct.unpack('<%dI' % SCRIPT_COUNT,
                               rd(d, SCRIPT_TABLE, SCRIPT_COUNT * 4)))
    for p in table:
        if not (END_BASE <= p < END_BASE + END_T_SIZE):
            raise ValueError(f'ending script pointer {p:#x} is outside END.EXE')
    sectors = list(struct.unpack('<%dH' % SECTOR_COUNT,
                                 rd(d, SECTORS, SECTOR_COUNT * 2)))
    credits = set(credits_pages(sectors))

    # A script runs to the next script's home (they are laid out in order).
    nxt = min(p for p in table if p > table[ENDING_1])
    size = nxt - table[ENDING_1]
    script = list(struct.unpack('<%dH' % (size // 2),
                                rd(d, table[ENDING_1], size)))
    end = script_end(script)

    first = next((i for i in range(0, end, 1)
                  if script[i] in (0, 1, 2) and script[i + 1] in credits), None)
    if first is None:
        raise ValueError('ending 1 never loads a staff-roll page')
    if script[first] != 2:
        raise ValueError('the first staff-roll load is not a text page')

    # The artwork the roll is drawn on: the nearest kind-0 load above it.
    start = first
    while start >= 0 and script[start] != 0:
        start -= 1
    if start < 0:
        raise ValueError('the staff roll has no backdrop image before it')

    # Keep the score the ending already set before the roll.
    music = None
    i = 0
    while i < start:
        if script[i] in ONE_ARG:
            if script[i] == 0xB:
                music = script[i:i + 2]
            i += 2
        else:
            i += 1

    script = (music or []) + script[start:end]
    if not script or script[-1] not in (9, 0xA):
        raise ValueError('credits script does not end on an end opcode')
    # Retail endings 1 and 2 hold their last screen with the no-op 0xA.
    # Ending 5 is reached from the title and has to come back, so it ends
    # the script (0x9): done: leaves g_movie_next_state at the -1 the
    # dispatch wrote, and the resident boots the title again.
    if script[-1] == 0xA:
        script[-1] = 9
    return table, script


def emit(table, script):
    hi = ((CREDITS_SCRIPTS + 0x8000) >> 16) & 0xFFFF
    lo = CREDITS_SCRIPTS & 0xFFFF
    lines = [
        '; generated by src/injection_tools/end_credits.py - do not edit',
        '; base game credits: ending 5 holds the staff-roll tail of retail script 1.',
        f'.definelabel CREDITS_SCRIPTS, {CREDITS_SCRIPTS:#010x}',
        f'.org {TABLE_PTR_LUI:#010x}',
        f'    lui     at, {hi:#06x}',
        f'.org {TABLE_PTR_ADDIU:#010x}',
        f'    addiu   at, at, {lo:#06x}',
        f'.org CREDITS_SCRIPTS',
        'credits_script_table:',
    ]
    for p in table:
        lines.append(f'    .word   {p:#010x}')
    script_at = CREDITS_SCRIPTS + 4 * (len(table) + 1)
    lines.append(f'    .word   {script_at:#010x}')
    lines.append('credits_script:')
    for i in range(0, len(script), 8):
        lines.append('    .halfword ' + ', '.join(f'{x:#06x}'
                                                 for x in script[i:i + 8]))
    lines.append('')
    return '\n'.join(lines)


def main():
    d = open(os.path.join(ROOT, 'data', 'psx', 'EXE', 'END.EXE'), 'rb').read()
    try:
        table, script = plan(d)
    except ValueError as ex:
        toolbelt.fail(f'end_credits: {ex}')
    toolbelt.ensure_parent(OUT)
    open(OUT, 'w', encoding='utf-8', newline='\n').write(emit(table, script))
    print(f'end_credits: {len(script)} halfwords at '
          f'{CREDITS_SCRIPTS + 4 * (len(table) + 1):#x}')


if __name__ == '__main__':
    main()
