"""Derive battle action banners from the PSP skill/item name tables."""
import collections
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
import btlp
import toolbelt
import vwf_wrap
import eboot_twin_plan


def frame_width():
    source = (ROOT / 'references/persona-decomp/src/btlp/openmessage.c').read_text()
    m = re.search(r'^#define\s+MSG_CENTRE_W\s+(0x[0-9a-fA-F]+|\d+)', source, re.M)
    if not m:
        raise SystemExit('battle banner: cannot derive narrow frame width')
    return int(m.group(1), 0)


def candidates(records, names):
    """Group pointer aliases and fail closed when their PSP names disagree."""
    grouped = collections.defaultdict(list)
    for index, pointer, _ja in records:
        if index in btlp.BAN_RESERVE or index not in names:
            continue
        text, source = names[index]
        text = (text or '').strip()
        if text:
            grouped[pointer].append((text, source))
    for pointer, values in sorted(grouped.items()):
        if len({text for text, _source in values}) != 1:
            raise ValueError(f'battle banner: conflicting PSP names share {pointer:#x}')
        text, source = values[0]
        yield {'pos': hex(pointer - btlp.B), 'psp': source, 'en': text}


def port(apply=False):
    generated = {r['pos']: r for r in toolbelt.read_generated('BTLP', optional=True)}
    manual = {r['pos']: r for r in toolbelt.read_manual('BTLP', optional=True)}
    cap = frame_width()
    changes, skipped = [], []
    rows = list(candidates(btlp.ban_records(btlp.data()), btlp.banner_wording()))
    # the RESERVE slots are no positional name (btlp.BAN_RESERVE): their own
    # Japanese takes the PSP line whose every copy says the same in English
    records = btlp.ban_records(btlp.data())
    reserve = [(hex(pointer), ja) for index, pointer, ja in records
               if index in btlp.BAN_RESERVE]
    offsets = eboot_twin_plan.unanimous_us('btlbanner', reserve)
    for index, pointer, ja in records:
        if index not in btlp.BAN_RESERVE:
            continue
        off = offsets.get(hex(pointer))
        if off is None:
            continue
        text = eboot_twin_plan.us_text(off).strip()
        if text:
            rows.append({'pos': hex(pointer - btlp.B),
                         'psp': f'EBOOT:{off:x}', 'en': text})
    for row in rows:
        old = generated.get(row['pos'], {})
        man = manual.get(row['pos'], {})
        if (man.get('en') or '').strip():
            continue
        try:
            btlp.ban_encode(row['en'])
        except ValueError as e:
            skipped.append((row['pos'], str(e)))
            continue
        width = vwf_wrap.text_width(row['en'])
        if width > cap:
            skipped.append((row['pos'], f'{width}px > {cap}px'))
            continue
        if old.get('en') != row['en'] or old.get('psp') != row['psp']:
            changes.append(row)
    if apply and changes:
        toolbelt.upsert_generated('BTLP', changes)
    print(f'btlbanner: {len(changes)} source-derived rows to write; {len(skipped)} kept as gaps/drafts')
    for pos, why in skipped:
        print(f'  {pos}: {why}')
    return changes, skipped


if __name__ == '__main__':
    if '--without-psp-jp' in sys.argv:
        os.environ[eboot_twin_plan.REPLAY_ENV] = str(eboot_twin_plan.PLAN)
    port('--apply' in sys.argv[1:])
