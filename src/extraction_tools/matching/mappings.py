"""Prepare disposable correspondence maps; authored inputs always live in src.

Both port.py and build.py call ensure() before readers start. Existing caches
are validated, never silently replaced. Missing outputs are generated in a
private directory and published only after validation. No worklist is edited.

    python src/extraction_tools/matching/mappings.py
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import toolbelt

HEADERS = {
    'align.tsv': ('file', 'entry', 'psx_box', 'jp_box', 'us_box', 'kind'),
    'map_jp_psx.tsv': ('file', 'entry', 'psx_box', 'jp_box', 'kind'),
    'map_us_jp.tsv': ('file', 'entry', 'jp_box', 'us_box', 'kind'),
    'psp_pairs.tsv': ('file', 'us_pos', 'jp_pos', 'how'),
    'labels.tsv': ('label',),
}
SOURCE_MAPS = (
    'accept.tsv', 'align_fix.tsv', 'boot_btlmsg.tsv', 'boot_s2dnames.tsv',
    'btlneg_map.tsv', 'descs_bank.tsv', 'dng_map.tsv', 'endtext_map.tsv',
    'psp_pairs_extra.tsv', 'psx_jp_extra.tsv', 's2d_map.tsv',
)


def validate(path, name):
    """An empty/truncated cache is an error, not a plausible empty mapping."""
    with Path(path).open(encoding='utf-8') as source:
        header = source.readline().rstrip('\r\n').split('\t')
        if tuple(header) != HEADERS[name]:
            raise ValueError(f'{path}: expected header {HEADERS[name]!r}; '
                             'remove this generated cache to regenerate it')
        count = 0
        seen = {}
        for number, line in enumerate(source, 2):
            fields = line.rstrip('\r\n').split('\t')
            if len(fields) != len(header) or not fields[0]:
                raise ValueError(f'{path}:{number}: malformed mapping row')
            row = dict(zip(header, fields))
            if name == 'psp_pairs.tsv':
                try:
                    for column in ('us_pos', 'jp_pos'):
                        if int(row[column], 16) < 0:
                            raise ValueError('negative offset')
                except ValueError as exc:
                    raise ValueError(f'{path}:{number}: invalid pair offset') from exc
                key = (row['file'], int(row['us_pos'], 16))
            elif name != 'labels.tsv':
                for column in header:
                    if column == 'entry' or column.endswith('_box'):
                        value = row[column]
                        # align.py spells an unmatched PSX side as None.
                        if value not in ('', 'None') and not value.isdecimal():
                            raise ValueError(f'{path}:{number}: invalid {column}')
                key = None  # split projections legitimately repeat gap rows
            else:
                key = fields[0]
            if key is not None:
                if key in seen:
                    raise ValueError(f'{path}:{number}: duplicate mapping key {key!r}')
                seen[key] = number
            count += 1
        if not count:
            raise ValueError(f'{path}: mapping contains no rows')


def _run(script, *args):
    command = [sys.executable, str(script), *map(str, args)]
    print('mappings: +', ' '.join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONHASHSEED': '0'},
                   check=True)


def _require(paths):
    missing = [str(p) for p in paths if not Path(p).is_file()]
    if missing:
        raise FileNotFoundError('mapping preparation needs extracted game/source '
                                'files (nothing was fabricated):\n  '
                                + '\n  '.join(missing))


def _prepare_pairs():
    # boot_pairs anchors on existing, independently ported provenance. It
    # never consumes last-resort matches as proof of their own correctness.
    _require([ROOT / 'data/psp_jp/PSP_GAME/SYSDIR/BOOT.BIN',
              ROOT / 'data/psp_us/PSP_GAME/SYSDIR/EBOOT.BIN',
              ROOT / 'data/psx/SLPS_005.00', ROOT / 'data/psx/S2D.BIN',
              ROOT / 'data/psx/BTLP.BIN'])
    # Pair inference uses prior family-port evidence, not only the discs.
    # Refuse a fresh/partial provenance tree rather than cache a deceptively
    # nonempty extras-only map forever. The checked-in family ports supply it.
    for rel in ('SLPS_005.00', 'S2D', 'BTLP'):
        rows = toolbelt.read_generated(rel, optional=True)
        if not any(r.get('en', '').strip() and
                   r.get('psp', '').startswith('EBOOT:') for r in rows):
            raise ValueError(f'psp_pairs.tsv: missing independently ported EBOOT '
                             f'provenance for {rel}; generate the independently verified family '
                             'port before preparing pair mappings')
    # Refresh the complete anchor corpus once on pair regeneration. A few
    # sentinel extracts cannot prove the other PSX files have been decoded.
    _run(HERE.parent / 'psp' / 'eboot.py')
    _run(HERE.parent / 'psx' / 'extract_text_all.py', '--no-worklists')


def ensure(names=None):
    """Fill missing generated maps only; fail before port/build on bad inputs.

    No import-time generation; authored inputs come from src.
    A second call on a populated checkout starts no extraction processes.
    """
    names = tuple(HEADERS if names is None else names)
    unknown = set(names) - HEADERS.keys()
    if unknown:
        raise ValueError(f'unknown generated mappings: {sorted(unknown)}')
    _require([toolbelt.PSP_GLYPHS, toolbelt.GLOSSARY,
              *(Path(toolbelt.SOURCE_MAPPINGS) / n for n in SOURCE_MAPS)])
    base = Path(toolbelt.MAPPINGS)
    base.mkdir(parents=True, exist_ok=True)
    # Stable topological order, even when callers ask for split maps first.
    wanted = set(names)
    if wanted & {'map_jp_psx.tsv', 'map_us_jp.tsv'}:
        wanted.add('align.tsv')
    missing = []
    for name in HEADERS:
        if name in wanted:
            path = base / name
            if path.exists():
                validate(path, name)
            else:
                missing.append(name)
    for name in missing:
        if name == 'psp_pairs.tsv':
            _prepare_pairs()
        with tempfile.TemporaryDirectory(prefix='.prepare-', dir=base) as tmp:
            _run(Path(__file__).resolve(), '--generate', name, tmp)
            staged = Path(tmp) / name
            validate(staged, name)
            # Only the requested output is published: split_maps also writes
            # its sibling, but an existing sibling is never overwritten.
            os.replace(staged, base / name)
        print(f'mappings: generated {name}', flush=True)
    return tuple(missing)


def _generate(name, directory):
    """Isolated worker: existing algorithms own correspondence decisions."""
    output = Path(directory) / name
    if name == 'align.tsv':
        import align
        align.OUT = str(output)
        align.main()
    elif name.startswith('map_'):
        import split_maps
        # Input remains the real align.tsv; only output paths are staged.
        split_maps.STRUCT_OUT = str(Path(directory) / 'map_jp_psx.tsv')
        split_maps.WORD_OUT = str(Path(directory) / 'map_us_jp.tsv')
        split_maps.cmd_split()
    elif name == 'psp_pairs.tsv':
        import boot_pairs
        boot_pairs.OUT = str(output)
        sys.argv = [boot_pairs.__file__, '--apply']
        boot_pairs.main()
    elif name == 'labels.tsv':
        from port_story import collect_labels
        labels = collect_labels()
        output.write_text('label\n' + ''.join(x + '\n' for x in sorted(labels)),
                          encoding='utf-8')
    else:
        raise ValueError(f'unknown generated mapping: {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', nargs=2, metavar=('NAME', 'DIRECTORY'),
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.generate:
            _generate(*args.generate)
        else:
            ensure()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'mappings: {exc}\n')


if __name__ == '__main__':
    main()
