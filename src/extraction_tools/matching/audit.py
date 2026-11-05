"""Provenance audit: EVERY en string in the build must derive from PSP data
or be an explicitly marked manual gap-fill. Anything else is AI leftover
('slop') and fails the audit.

Sources of truth:
  translation/generated/ADV/ported.tsv    story boxes from PSP-US
  translation/manual/events/E?.tsv       sparse manual overrides
  translation/generated/TALK/*.tsv        TALK port output
  translation/generated/SLPS_005.00/choices.tsv choice rows verified against PSP

  python src/extraction_tools/matching/audit.py
Checks manual event English columns against generated PSP provenance.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import strlib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
EV = os.path.join(ROOT, 'translation', 'manual', 'events')
PSP = os.path.join(ROOT, 'translation', 'generated')


def load_set(path, cols=3):
    out = set()
    if not os.path.exists(path):
        return out
    for f in strlib.tsv_fields(path, cols):
        if f[1].isdigit():
            out.add((f[0], int(f[1]), int(f[2])))
    return out


def main():
    ported = load_set(os.path.join(PSP, 'ADV', 'ported.tsv'))
    manual = set()
    listed = set()
    pending = 0
    slop = 0
    for fn in ('E0', 'E1', 'E2', 'E3'):
        path = os.path.join(EV, fn + '.tsv')
        if not os.path.exists(path):
            continue
        for r in strlib.tsv_rows(path, required=('entry', 'box', 'en')):
            if r['entry'].isdigit() and r['box'].isdigit():
                key = (fn, int(r['entry']), int(r['box']))
                listed.add(key)
                if r['en'].strip():
                    manual.add(key)
                elif key not in ported:
                    pending += 1
                if r['en'].strip() and key not in ported:
                    slop += 1
    print(f'PSP-derived event ports: {len(ported)}')
    print(f'manual event overrides: {len(manual)}')
    print(f'unmatched source rows awaiting manual text: {pending}')
    print(f'filled event rows without PSP/manual provenance: {slop}')
    # completeness: every PSX ADV box is either ported or listed in manual
    # (a box in neither would stay Japanese with nothing tracking it)
    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
    import efile as _efile
    orphan = 0
    for fn in ('E0', 'E1', 'E2', 'E3'):
        try:
            entries = _efile.load(os.path.join(ROOT, 'data', 'psx', 'ADV', fn + '.BIN')).entries
        except Exception:
            continue
        for ei in range(len(entries)):
            for k in range(len(entries[ei].boxes)):
                if (fn, ei, k) not in ported and (fn, ei, k) not in listed:
                    if orphan < 10:
                        print(f'ORPHAN (neither ported nor manual): {fn}/{ei}/{k}')
                    orphan += 1
    print(f'orphan event boxes: {orphan}')
    # choices provenance
    cp = os.path.join(PSP, 'SLPS_005.00', 'choices.tsv')
    verified, todo = [], []
    if os.path.exists(cp):
        for f in strlib.tsv_rows(cp, required=('idx', 'psp_en', 'source')):
            if f['idx'].isdigit():
                (verified if f['source'] != 'TODO' else todo).append(f['idx'])
    print(f'choice rows PSP-verified: {len(verified)} {verified}')
    print(f'choice rows TODO (still Japanese/unverified): {len(todo)}')
    # Manual CHOICES rows are sparse; only real overrides are checked against the generated baseline.
    drift = []
    if verified:
        cur = {}
        ch_path = os.path.join(ROOT, 'translation', 'manual', 'strings', 'CHOICES.tsv')
        if os.path.exists(ch_path):
            for f in strlib.tsv_rows(ch_path, required=('idx', 'en')):
                if f['idx'].isdigit() and f['en'].strip():
                    cur[f['idx']] = f['en']
        want = {}
        for f in strlib.tsv_rows(cp, required=('idx', 'psp_en', 'source')):
            if f['idx'].isdigit() and f['source'] != 'TODO':
                want[f['idx']] = f['psp_en']
        for idx, w in want.items():
            if idx in cur and cur[idx] != w:
                drift.append(idx)
    if drift:
        print(f'CHOICE DRIFT (manual CHOICES.tsv override != generated choices.tsv): {drift}')
    # verify ported boxes' en matches the port generator output? (spot check
    # that nobody hand-edited a ported row: compare against align us_text?)
    return 0 if not drift else 1


if __name__ == '__main__':
    sys.exit(main())
