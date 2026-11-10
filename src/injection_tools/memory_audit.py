"""Inventory assembled writes and indexed retail RAM-reference leads as TSV.

Usage: python src/injection_tools/memory_audit.py
The default audits BTLP using the most recent armips listing. Results live in
build/memory-audit/, never in the reviewed source map. Both the listing and the
chosen retail overlay must be from the intended variant/revision. A candidate
whose base is near an allocation is not proof of an overlap, and an allocation
without a candidate is not proof of safety; see docs/MEMORY_AUDIT.md.
"""
import argparse
import csv
from pathlib import Path

import runtime_map
import write_guard

ROOT = Path(__file__).resolve().parents[2]


def allocations(section, root=ROOT):
    """Merge overlapping/adjacent writes only within one source and padding kind."""
    groups = {}
    for write in section.writes:
        key = (write.path, write.zero)
        groups.setdefault(key, []).append(write)
    result = []
    for (path, padding), writes in groups.items():
        writes.sort(key=lambda w: (w.addr, w.end, w.line))
        current = None
        for write in writes:
            if current is None or write.addr > current['end']:
                current = {'start': write.addr, 'end': write.end, 'path': path,
                           'padding': padding, 'first_line': write.line,
                           'last_line': write.line, 'writes': 0}
                result.append(current)
            else:
                current['end'] = max(current['end'], write.end)
                current['first_line'] = min(current['first_line'], write.line)
                current['last_line'] = max(current['last_line'], write.line)
            current['writes'] += 1
    return sorted(result, key=lambda r: (r['start'], r['end'], r['path'], r['padding']))


def retail_content(start, end, base, retail):
    """Describe source bytes, not whether they are safe to reuse."""
    lo, hi = start - base, end - base
    if lo < 0 or hi > len(retail):
        return 'outside-retail-image'
    blob = retail[lo:hi]
    if not any(blob):
        return 'all-zero'
    return 'mixed-or-nonzero'


def indexed_hits(spans, candidates, lookahead=0x200):
    """Candidate bases at or before a write. No array extent is inferred."""
    if lookahead < 0:
        raise ValueError('lookahead must be nonnegative')
    hits = []
    for pc, address, access, index in candidates:
        for span in spans:
            # Exact intersection is meaningful even for a base inside the
            # allocation; nearby bases are only leads requiring further work.
            if span['start'] <= address < span['end']:
                relation = 'base-inside-write'
            elif 0 < span['start'] - address <= lookahead:
                relation = 'base-before-write'
            else:
                continue
            hits.append((pc, address, access, index, relation, span))
    return sorted(hits, key=lambda hit: (hit[1], hit[0], hit[5]['start'], hit[5]['path']))


def _relative(path, root):
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def report(listing, image, output_dir, lookahead=0x200):
    sections, problems = write_guard.parse_listing(str(listing))
    if problems:
        raise ValueError('listing cannot be audited: ' + '; '.join(problems))
    selected = [section for section in sections if Path(section.out).name == image]
    if len(selected) != 1:
        raise ValueError(f'expected exactly one {image} section, found {len(selected)}')
    section = selected[0]
    if not section.input:
        raise ValueError('an audit requires a retail input image')
    retail = Path(section.input).read_bytes()
    spans = allocations(section)
    candidates = list(runtime_map.candidates(retail, section.base))
    hits = indexed_hits(spans, candidates, lookahead)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / 'allocations.tsv').open('w', encoding='utf-8', newline='') as f:
        out = csv.writer(f, delimiter='\t', lineterminator='\n')
        out.writerow(('image', 'start', 'end', 'bytes', 'kind', 'retail_bytes',
                      'source', 'first_line', 'last_line', 'statements'))
        for span in spans:
            out.writerow((image, hex(span['start']), hex(span['end']), span['end'] - span['start'],
                          'padding' if span['padding'] else 'assembled-write',
                          retail_content(span['start'], span['end'], section.base, retail),
                          _relative(span['path'], ROOT), span['first_line'],
                          span['last_line'], span['writes']))
    with (output_dir / 'indexed-leads.tsv').open('w', encoding='utf-8', newline='') as f:
        out = csv.writer(f, delimiter='\t', lineterminator='\n')
        out.writerow(('instruction', 'indexed_base', 'access', 'index_register', 'relation',
                      'write_start', 'write_end', 'kind', 'retail_bytes', 'source', 'first_line'))
        for pc, address, access, index, relation, span in hits:
            out.writerow((hex(pc), hex(address), access, index, relation,
                          hex(span['start']), hex(span['end']),
                          'padding' if span['padding'] else 'assembled-write',
                          retail_content(span['start'], span['end'], section.base, retail),
                          _relative(span['path'], ROOT), span['first_line']))
    return len(spans), len(candidates), len(hits)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--listing', type=Path, default=ROOT / 'build/armips-main.lst')
    parser.add_argument('--image', default='BTLP.BIN', help='exact output image basename')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/memory-audit')
    parser.add_argument('--lookahead', type=lambda value: int(value, 0), default=0x200,
                        help='maximum distance after an indexed base to flag as a lead')
    args = parser.parse_args()
    try:
        spans, refs, hits = report(args.listing, args.image, args.output_dir, args.lookahead)
    except (OSError, ValueError) as error:
        parser.exit(1, f'memory audit: {error}\n')
    print(f'{args.image}: {spans} write ranges, {refs} indexed references, {hits} leads; '
          f'TSV reports in {args.output_dir} (leads are not proven overlaps)')


if __name__ == '__main__':
    main()
