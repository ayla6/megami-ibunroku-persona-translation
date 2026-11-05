"""EBOOT.BIN extraction: ONE extracted file per real PSP file.

  python src/extraction_tools/psp/eboot.py [--us-only]

data/extracted_text/{psp_us,psp_jp}/EBOOT.tsv = every TEXT BOX of
EBOOT.BIN, keyed by its offset in the file (id = row order, pos = offset):

    id  pos       text
    0   0x1a08dc  ...

A row is one box (tables.be_boxes): split at every FF01 and at the record
padding, the record header around a name left out, and rows that carry no
language - the pointer and stat tables the BOOT also holds - are not text
units at all. That is what makes the extract readable and what makes a
`psp` pointer land on ONE unit instead of a merged record.

BE records (menus, tables, boxes) and LE C-strings interleave; consumers
filter by pos range.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'injection_tools'))
import toolbelt  # noqa: E402
import strlib  # noqa: E402
from tables import (be_boxes, be_runs, le_strings, le_string_at, us_boot,
                    US_LE, US_SPACE)  # noqa: E402


def mapped_units(boot_bytes, glyphs, space=None):
    """US units whose starts are proven by authored BOOT source mappings.

    The broad census may merge a record head with its text, and the opposite
    endian scan may also decode that same address. Source coordinates are
    stronger evidence than either scan: retain census rows outside proven
    source spans, making exact pointer units authoritative within them.
    """
    ranges = [(int(r['lo'], 16), int(r['hi'], 16)) for r in
              strlib.tsv_rows(os.path.join(toolbelt.SOURCE_MAPPINGS,
                                           's2d_map.tsv'), required=('lo', 'hi'))]
    units = {off: (text, end)
             for off, text, _term, end in be_runs(boot_bytes, with_spans=True)
             if any(lo <= off <= hi for lo, hi in ranges)}
    for lo, hi in ranges:
        if lo not in units or hi not in units:
            raise ValueError(f'BOOT source range {lo:#x}..{hi:#x} has no BE unit')
    for r in strlib.tsv_rows(os.path.join(toolbelt.SOURCE_MAPPINGS,
                                         'boot_s2dnames.tsv'),
                             required=('us_boot_offset',)):
        at = int(r['us_boot_offset'], 16)
        units[at] = le_string_at(boot_bytes, at, glyphs, space, with_end=True)
    return [(off, text, end) for off, (text, end) in units.items()]


def dump(region, boot_bytes, glyphs, space=None):
    mapped = mapped_units(boot_bytes, glyphs, space) if region == 'psp_us' else []
    rows = [(off, text) for off, text, _end in mapped]
    census = []
    if glyphs:
        for off, text in le_strings(boot_bytes, glyphs, space):
            census.append((off, text))
    for off, text, _term in be_boxes(boot_bytes, glyphs if region == 'psp_jp' else None):
        census.append((off, text))
    # Only proven source spans suppress opposite-endian/interior census rows.
    # Everything outside them keeps the broad extraction's original behavior.
    rows.extend((off, text) for off, text in census
                if not any(start <= off < end for start, _text, end in mapped))
    rows.sort(key=lambda row: row[0])
    out, seen = [], set()
    for off, text in rows:
        if off in seen or not text.strip():
            continue
        seen.add(off)
        out.append({'id': str(len(out)), 'pos': hex(off), 'text': text})
    toolbelt.write_extracted(region, 'EBOOT', out)
    print(f'eboot[{region}]: {len(out)} text boxes -> {toolbelt.ext_path(region, "EBOOT")}')


def ensure_us():
    """Refresh the canonical US extract when its source contract changes.

    Standalone porters need the same extraction as the full pipeline. A
    fresh extract is reused; source maps, glyphs, decoder code and BOOT
    changes invalidate it without requiring a manual cache deletion.
    """
    import codec
    import tables
    target = toolbelt.ext_path('psp_us', 'EBOOT')
    sources = [__file__, tables.__file__, codec.__file__, toolbelt.PSP_GLYPHS,
               tables.US_CACHE, tables.US_EBOOT]
    sources.extend(os.path.join(toolbelt.SOURCE_MAPPINGS, name)
                   for name in ('s2d_map.tsv', 'boot_s2dnames.tsv'))
    stamp = os.stat(target).st_mtime_ns if os.path.exists(target) else -1
    if stamp < 0 or any(os.path.exists(path) and os.stat(path).st_mtime_ns > stamp
                        for path in sources):
        dump('psp_us', us_boot(), US_LE, US_SPACE)
        return True
    return False


def main():
    from tables import jp_boot, jp_map, US_SPACE
    us = us_boot()
    dump('psp_us', us, US_LE, US_SPACE)
    if '--us-only' not in sys.argv[1:]:
        jm = jp_map()
        dump('psp_jp', jp_boot(), {k: v for k, v in jm.items() if k != 0}, US_SPACE)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
