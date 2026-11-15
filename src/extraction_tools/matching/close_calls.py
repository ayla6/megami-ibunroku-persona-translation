"""The close calls: shipped pages whose runner-up layout nearly won.

  python src/extraction_tools/matching/close_calls.py     write build/close_calls.tsv

The port's last step. Every shipped page (manual wins over generated, what a
builder reads) is weighed again with vwf_wrap.weigh - the flow's own ranking
of every layout it considered - and two kinds of page are listed:
- a close call: the best layout beat the runner-up on the last score (line
  ends and shape) by less than CLOSE rhythm points, and the best layout is
  the stored one;
- a stale page: a MANUAL row whose stored lines are not what the flow
  chooses now (the port reflows generated rows every run; a human's row
  keeps its breaks until the human looks again).
The page is weighed as one run of words, without the porter's structure
(instruction captions, a box joined to the one before, choice grids), so a
generated page the porter laid out differently is not listed: the porter
knew more than this weighing does.
The viewer (tools/textvis) reads the file; it never weighs the tables itself.

Columns: rel pos page close margin decided_by stored_differs chosen runner_up
(the line lists joined with ' / ').
"""
import concurrent.futures as futures
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import toolbelt  # noqa: E402
import vwf_wrap  # noqa: E402

OUT = os.path.join(ROOT, 'build', 'close_calls.tsv')
COLS = ('rel', 'pos', 'page', 'close', 'margin', 'decided_by',
        'stored_differs', 'chosen', 'runner_up')
# A runner-up that lost on line ends and shape by less than this many rhythm
# points is worth a human look.
CLOSE = 1.0


def measure_for(rel):
    """The measure a family's builder prices lines with: the battle talk
    lines price their insert codes with talktl, everything else vwf_wrap."""
    if rel.startswith('TALK/'):
        import talktl
        return talktl.width
    return vwf_wrap.text_width


def weigh_page(page, measure):
    """The flow's choice for one page's words, the layout it nearly chose,
    what decided between them and by how much - or None for a page of
    fewer than three words."""
    words = ' '.join(page).split(' ')
    if sum(1 for w in words if w.strip()) < 3:
        return None
    ranked = vwf_wrap.weigh(words, measure=measure)
    if not ranked:
        return None
    best = ranked[0]
    second = next((r for r in ranked[1:] if r[1] != best[1]), None)
    if second is None:
        return None
    # the first rank the two differ on; none at all is a dead heat, which
    # the search's order decided
    d = next((i for i, (a, b) in enumerate(zip(best[0], second[0])) if a != b),
             None)
    margin = 0 if d is None else round(second[0][d] - best[0][d], 3)
    return {'chosen': best[1], 'runner_up': second[1],
            'decided_by': 'a dead heat' if d is None else vwf_wrap.RANK_NAMES[d],
            'margin': margin,
            'close': d is None or (d == 6 and margin < CLOSE),
            'stored_differs': [' '.join(x.split()) for x in best[1]]
                              != [' '.join(x.split()) for x in page]}


def scan(rel):
    import textshape
    measure = measure_for(rel)
    out = []
    try:
        table = toolbelt.merged_rows(rel)
        manual = {r['pos'] for r in toolbelt.read_manual(rel, optional=True)
                  if (r.get('en') or '').strip()}
    except (OSError, ValueError, SystemExit):
        return out
    for row in table:
        en = row.get('en') or ''
        if not en.strip() or '<FF0E>' in en:
            continue
        for n, page in enumerate(textshape.pages(en), 1):
            w = weigh_page(page, measure)
            if not w:
                continue
            w['close'] = w['close'] and not w['stored_differs']
            w['stored_differs'] = w['stored_differs'] and row.get('pos') in manual
            if w['close'] or w['stored_differs']:
                out.append((rel, row.get('pos', ''), str(n), str(int(w['close'])),
                            str(w['margin']), w['decided_by'],
                            str(int(w['stored_differs'])),
                            ' / '.join(w['chosen']), ' / '.join(w['runner_up'])))
    return out


def main():
    rows = []
    with futures.ProcessPoolExecutor(max_workers=toolbelt.jobs()) as pool:
        for got in pool.map(scan, toolbelt.psx_rels()):
            rows += got
    rows.sort(key=lambda r: (r[3] != '1', float(r[4]), r[0], r[1]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\t'.join(COLS) + '\n')
        for r in rows:
            f.write('\t'.join(x.replace('\t', ' ') for x in r) + '\n')
    print(f'close_calls: {sum(r[3] == "1" for r in rows)} close calls, '
          f'{sum(r[6] == "1" for r in rows)} stale pages -> {OUT}')


if __name__ == '__main__':
    main()
