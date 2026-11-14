#!/usr/bin/env python3
"""List laid-out pages whose shape the flow's own rules call bad.

  python tools/textshape.py                     every table, worst first, TSV
  python tools/textshape.py --family ADV        one family (a rel prefix)
  python tools/textshape.py --rel ADV/E0        one file
  python tools/textshape.py --finding rise      one finding only
  python tools/textshape.py --limit 0           no row limit
  python tools/textshape.py --wide             count the label-only line too

Each row is one visible page as it would ship (manual wins over generated,
exactly what a builder reads). The findings are the flow's own thresholds
(`vwf_wrap.shape_report`), so a row names a cost the optimizer paid rather
than a matter of taste:

  label-fragment  a scrap of speech rides the speaker's name line
  tiny-tail       the last line is under half the line before it
  rise            a line is over 40% wider than the line above it
  hollow          a middle line is under half of BOTH its neighbours
  over            a line is wider than the box (tstatus' job, shown anyway)

A first line that is only the speaker's name is not part of the block's
shape (spec 2.4: a standalone label is not a speech line), so it never
causes a rise, a hollow or a tail by being short - unless --wide asks for
the reader's view instead of the flow's. Choice rows (<FF0E>) are skipped:
their grid has its own gate in choices.py. Nothing here writes anything.
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import toolbelt  # noqa: E402
import vwf_wrap  # noqa: E402

LINE = ('FF03', 'FFF6')                       # a line move
# a wait, a page, an end; in talk text FFFB/FFF7 turn the page and a voice
# code (FFEB-FFEE) opens the next speaker's box
PAGE = ('FF02', 'FF04', 'FF01', 'FFEF', 'FFF5', 'FFFB', 'FFF7',
        'FFEB', 'FFEC', 'FFED', 'FFEE')
CODE = re.compile(r'<([0-9A-Fa-f]+)>')


def pages(en):
    """The row's visible pages, each a list of line texts.

    A line move closes a line; a wait, a page move or an end closes the page
    as well (a scroll is <FF02><FF03>: the wait ends the page, the empty
    line it leaves is dropped). Any other code stays in its line, priced at
    its real width by the shared measure."""
    out, page, line, at = [], [], '', 0
    for m in CODE.finditer(en):
        line += en[at: m.start()]
        code = m.group(1).upper()
        if code in LINE:
            if line.strip():
                page.append(line)
            line = ''
        elif code in PAGE:
            if line.strip():
                page.append(line)
            line = ''
            if page:
                out.append(page)
                page = []
        else:
            line += m.group(0)
        at = m.end()
    line += en[at:]
    if line.strip():
        page.append(line)
    if page:
        out.append(page)
    return out


def findings_for(page, wide=False):
    lines = page
    if not wide and len(page) > 1:
        lines = [page[0]] + page[1:]      # label test still sees line 0
    widths, found, cost, clauses = vwf_wrap.shape_report(lines)
    for line in page:
        if vwf_wrap.text_width(line) > vwf_wrap.BOX_WIDTH:
            found.append('over')
            break
    return widths, found, cost, clauses


def rows(args):
    rels = [rel for rel in toolbelt.psx_rels()
            if (not args.family or rel == args.family
                or rel.startswith(args.family + '/'))
            and (not args.rel or rel == args.rel)]
    for rel in rels:
        try:
            table = toolbelt.merged_rows(rel)
        except (OSError, ValueError) as exc:      # a table with no port yet
            print('textshape: %s: %s' % (rel, exc), file=sys.stderr)
            continue
        for row in table:
            en = row.get('en') or ''
            if not en or '<FF0E>' in en:
                continue
            for n, page in enumerate(pages(en), 1):
                widths, found, cost, clauses = findings_for(page, args.wide)
                if len(widths) < 2 or not found:
                    continue
                if args.finding and args.finding not in found:
                    continue
                yield (rel, str(row.get('pos', '')), n, widths, found,
                       cost, clauses, page)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--family', default='', help='rel prefix (ADV, DNG, S2D)')
    ap.add_argument('--rel', default='', help='one table, e.g. ADV/E0')
    ap.add_argument('--finding', default='', help='only rows with this finding')
    ap.add_argument('--limit', type=int, default=200,
                    help='rows to print, worst first (0 = all)')
    ap.add_argument('--wide', action='store_true',
                    help='count the label-only first line as speech')
    args = ap.parse_args()

    found = list(rows(args))
    found.sort(key=lambda r: (-len(r[4]), -r[5], r[0], r[1]))
    if args.limit:
        found = found[:args.limit]
    print('rel\tpos\tpage\twidths\tfindings\tcost\tclauses\ttext')
    tally = {}
    for rel, pos, n, widths, names, cost, clauses, page in found:
        for name in names:
            tally[name] = tally.get(name, 0) + 1
        print('\t'.join((rel, pos, str(n), ','.join(map(str, widths)),
                         ','.join(names), str(cost), str(clauses),
                         ' | '.join(page))))
    print('textshape: %d rows, %d mid-clause ends; %s' % (
        len(found), sum(r[6] for r in found),
        ', '.join('%s %d' % kv for kv in sorted(tally.items()))),
        file=sys.stderr)


if __name__ == '__main__':
    main()
