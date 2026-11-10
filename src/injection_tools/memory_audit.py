"""Inventory assembled writes and indexed retail RAM-reference leads as TSV.

Usage: python src/injection_tools/memory_audit.py [--image NAME ... | --all]
The default audits BTLP using the most recent armips listing; --all audits
every overlay the listing writes. Each image gets its own directory under
build/memory-audit/ plus one summary.tsv for the run, never the reviewed
source map. Both the listing and the retail images must be from the intended
variant/revision. A candidate whose base is near an allocation is not proof
of an overlap, and an allocation without a candidate is not proof of safety;
see docs/MEMORY_AUDIT.md.
"""
import argparse
import csv
import struct
from pathlib import Path

import runtime_map
import write_guard

ROOT = Path(__file__).resolve().parents[2]
EXE_MAGIC = b'PS-X EXE'


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


def retail_image(section):
    """The bytes and load address the retail instructions live at.

    A PS-X EXE carries its load address in the header and its text starts
    after the 0x800-byte header, while an overlay is loaded whole."""
    if not section.input:
        raise ValueError('an audit requires a retail input image')
    data = Path(section.input).read_bytes()
    if data.startswith(EXE_MAGIC) and len(data) >= 0x800:
        base = struct.unpack_from('<I', data, 0x18)[0]
        return data[0x800:], base
    return data, section.base


def _relative(path, root):
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def _section_for(sections, image):
    selected = [section for section in sections if Path(section.out).name == image]
    if len(selected) != 1:
        raise ValueError(f'expected exactly one {image} section, found {len(selected)}')
    return selected[0]


def audit_section(section, output_dir, lookahead=0x200):
    """Write one image's two TSVs; return its summary row.

    An image with no assembled writes has nothing to collide with, so it gets
    a summary row and no report files.
    """
    image = Path(section.out).name
    summary = {'image': image, 'ranges': 0, 'padding': 0, 'references': 0,
               'exact': 0, 'near_stores': 0, 'near_loads': 0,
               'outside_retail': 0, 'note': ''}
    if not section.writes:
        summary['note'] = 'no assembled writes'
        return summary
    if section.create or not section.input:
        summary['note'] = 'no retail input to scan'
        return summary
    retail, base = retail_image(section)
    spans = allocations(section)
    candidates = list(runtime_map.candidates(retail, base))
    hits = indexed_hits(spans, candidates, lookahead)
    image_dir = Path(output_dir) / image
    image_dir.mkdir(parents=True, exist_ok=True)
    with (image_dir / 'allocations.tsv').open('w', encoding='utf-8', newline='') as f:
        out = csv.writer(f, delimiter='\t', lineterminator='\n')
        out.writerow(('image', 'start', 'end', 'bytes', 'kind', 'retail_bytes',
                      'source', 'first_line', 'last_line', 'statements'))
        for span in spans:
            out.writerow((image, hex(span['start']), hex(span['end']),
                          span['end'] - span['start'],
                          'padding' if span['padding'] else 'assembled-write',
                          retail_content(span['start'], span['end'], base, retail),
                          _relative(span['path'], ROOT), span['first_line'],
                          span['last_line'], span['writes']))
    with (image_dir / 'indexed-leads.tsv').open('w', encoding='utf-8', newline='') as f:
        out = csv.writer(f, delimiter='\t', lineterminator='\n')
        out.writerow(('instruction', 'indexed_base', 'access', 'index_register',
                      'relation', 'write_start', 'write_end', 'kind',
                      'retail_bytes', 'source', 'first_line'))
        for pc, address, access, index, relation, span in hits:
            out.writerow((hex(pc), hex(address), access, index, relation,
                          hex(span['start']), hex(span['end']),
                          'padding' if span['padding'] else 'assembled-write',
                          retail_content(span['start'], span['end'], base, retail),
                          _relative(span['path'], ROOT), span['first_line']))
    summary.update({
        'ranges': len(spans),
        'padding': sum(1 for span in spans if span['padding']),
        'references': len(candidates),
        'exact': sum(1 for hit in hits if hit[4] == 'base-inside-write'),
        'near_stores': sum(1 for hit in hits if hit[4] == 'base-before-write'
                           and hit[2].startswith('s')),
        'near_loads': sum(1 for hit in hits if hit[4] == 'base-before-write'
                          and not hit[2].startswith('s')),
        'outside_retail': sum(1 for span in spans
                              if retail_content(span['start'], span['end'],
                                                base, retail)
                              == 'outside-retail-image'),
    })
    return summary


SUMMARY_FIELDS = ('image', 'ranges', 'padding', 'references', 'exact',
                  'near_stores', 'near_loads', 'outside_retail', 'note')


def audit_images(listing, images, output_dir, lookahead=0x200):
    """Audit every named image in one listing and write a run summary.

    `images` of None means every section with assembled writes. Results are
    per-image directories under `output_dir`, so several overlays never
    overwrite each other's reports.
    """
    sections, problems = write_guard.parse_listing(str(listing))
    if problems:
        raise ValueError('listing cannot be audited: ' + '; '.join(problems))
    if images is None:
        selected = [section for section in sections if section.writes]
    else:
        names = list(dict.fromkeys(images))
        selected = [_section_for(sections, image) for image in names]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = [audit_section(section, output_dir, lookahead)
                 for section in selected]
    with (output_dir / 'summary.tsv').open('w', encoding='utf-8', newline='') as f:
        out = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, delimiter='\t',
                             lineterminator='\n')
        out.writeheader()
        out.writerows(summaries)
    return summaries


def report(listing, image, output_dir, lookahead=0x200):
    """Audit exactly one image; kept as the single-image entry point."""
    sections, problems = write_guard.parse_listing(str(listing))
    if problems:
        raise ValueError('listing cannot be audited: ' + '; '.join(problems))
    section = _section_for(sections, image)
    return audit_section(section, output_dir, lookahead)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--listing', type=Path, default=ROOT / 'build/armips-main.lst')
    parser.add_argument('--image', action='append', metavar='NAME',
                        help='exact output image basename; repeat for several'
                             ' (default: BTLP.BIN)')
    parser.add_argument('--all', action='store_true',
                        help='audit every image the listing writes')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/memory-audit')
    parser.add_argument('--lookahead', type=lambda value: int(value, 0), default=0x200,
                        help='maximum distance after an indexed base to flag as a lead')
    args = parser.parse_args()
    if args.all and args.image:
        parser.error('--all and --image select images differently; use one')
    images = None if args.all else (args.image or ['BTLP.BIN'])
    try:
        summaries = audit_images(args.listing, images, args.output_dir, args.lookahead)
    except (OSError, ValueError) as error:
        parser.exit(1, f'memory audit: {error}\n')
    for row in summaries:
        print(f'{row["image"]}: {row["ranges"]} write ranges, '
              f'{row["references"]} indexed references, {row["exact"]} exact, '
              f'{row["near_stores"]} near-store, {row["near_loads"]} near-load '
              f'leads{"; " + row["note"] if row["note"] else ""}')
    print(f'TSV reports in {args.output_dir} (leads are not proven overlaps)')


if __name__ == '__main__':
    main()
