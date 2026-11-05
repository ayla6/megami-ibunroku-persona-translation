"""Queue affinity descriptions for manual translation, with JP and US sources.

Usage: python src/extraction_tools/matching/port_affinity.py [--apply]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import affinity  # noqa: E402
import toolbelt  # noqa: E402

B = affinity.SLPS_BASE


def _be():
    sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
    from tables import be_runs
    with open(os.path.join(ROOT, 'build', 'us_boot_decrypted.bin'), 'rb') as source:
        return be_runs(source.read())


def purge():
    """Remove generated affinity wording without touching manual work."""
    positions = {hex(a - B) for _k, a, _ja in affinity.records()}
    generated = toolbelt.read_generated('SLPS_005.00', optional=True)
    keep = [row for row in generated if row['pos'] not in positions]
    if len(keep) != len(generated):
        toolbelt.write_generated('SLPS_005.00', keep)
    print(f'affinity: removed {len(generated) - len(keep)} generated affinity row(s)')


def queue_manual():
    """Queue each retail record with source texts, preserving human work."""
    source = [(o, t) for o, t, term in _be()
              if 0x27baa4 <= o < 0x28374c and term == 'FF01']
    if len(source) != affinity.COUNT:
        raise SystemExit(f'affinity: expected {affinity.COUNT} PSP records, got {len(source)}')
    records = affinity.records()
    manual = {r['pos']: r for r in toolbelt.read_manual('SLPS_005.00', optional=True)}
    nxt = max((int(r['id']) for r in manual.values() if str(r['id']).isdigit()), default=-1) + 1
    for k, address, ja in records:
        pos = hex(address - B)
        row = manual.get(pos)
        if row and (row.get('en') or '').strip():
            continue
        if row is None:
            row = {'id': str(nxt), 'pos': pos, 'psp': '', 'en': '', 'note': ''}
            nxt += 1
            manual[pos] = row
        off, us = source[k]
        row['psp'] = f'EBOOT:{off:x}'
        us = ' '.join(re.sub(r'<[0-9A-Fa-f]{4}>', ' ', us).split())
        row['note'] = f'JP: {ja} | US: {us}'
    toolbelt.write_manual('SLPS_005.00', list(manual.values()))
    print(f'affinity: queued {len(records)} records for manual translation')


def main():
    if '--apply' in sys.argv:
        purge()
        queue_manual()
    else:
        print(f'affinity: {len(affinity.records())} records; English descriptions are manual')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
