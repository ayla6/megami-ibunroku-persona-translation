"""Three-sided TSV dump: one whole file with PSX, PSP-JP and PSP-US text
next to each other, each column pair carrying its own row id.

  python tools/sidebyside.py D00/D00
  python tools/sidebyside.py D00/D00 --no-jp

Output: psx_id psx jp_id jp us_id us (--no-jp drops the jp pair), one
row per textview item, header first, tab-separated. Text keeps every
control code; a side with no row is an empty id and an empty text.

The correspondence is textview's, not this tool's: cmd_file() calls
textview.build_items(), so the rows and their ids are exactly what
`textview.py file` shows - (entry, box) joined, align.tsv where the boxes
do not line up, `psp` pointers for the units with no joined side.
"""
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import textview as tv  # noqa: E402

# (column prefix, Item attribute)
COLUMNS = (('psx', 'psx'), ('jp', 'jp'), ('us', 'us'))


def rows(items, with_jp=True):
    """Yield the TSV header and one line per item (no terminal needed)."""
    sides = [(label, attr) for label, attr in COLUMNS
             if with_jp or attr != 'jp']
    header = []
    for label, _attr in sides:
        header += [f'{label}_id', label]
    yield '\t'.join(header)
    for it in items:
        cells = []
        for _label, attr in sides:
            row = getattr(it, attr)
            cells += [row['id'], row['text']] if row is not None else ['', '']
        yield '\t'.join(cells)


def cmd_file(name, with_jp=True):
    _key, sd = tv.resolve(name)
    items = tv.build_items(sd.get('psx'), sd.get('psp_jp'), sd.get('psp_us'))
    for line in rows(items, with_jp):
        print(line)


def main():
    args = sys.argv[1:]
    name, with_jp = None, True
    for arg in args:
        if arg in ('-h', '--help', 'help'):
            print(__doc__)
            return
        if arg == '--no-jp':
            with_jp = False
        elif arg.startswith('-'):
            sys.exit(f'sidebyside: {arg}: unknown option\n\n{__doc__}')
        elif name is not None:
            sys.exit(f'sidebyside: {arg}: only one file at a time')
        else:
            name = arg
    if name is None:
        print(__doc__)
        return
    cmd_file(name, with_jp)


if __name__ == '__main__':
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # `| head` ends quietly
    main()
