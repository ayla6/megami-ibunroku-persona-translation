"""Map a Japanese/US BOOT string pair to its matching PSX battle-message slot."""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import toolbelt  # noqa: E402
import btlmsg  # noqa: E402
import etext  # noqa: E402
import port_derive  # noqa: E402
import vwf_wrap  # noqa: E402
import reward_notice  # noqa: E402
import eboot_twin_plan  # noqa: E402

MAP = os.path.join(toolbelt.SOURCE_MAPPINGS, 'boot_btlmsg.tsv')
JP_CACHE = os.path.join(ROOT, 'data', 'cache', 'boot_strings_jp.tsv')
US_CACHE = os.path.join(ROOT, 'data', 'cache', 'boot_strings_us.tsv')
OUT = os.path.join(ROOT, 'translation', 'generated', 'BTLP.BIN', 'BTLMSG.tsv')


def rejection_reason(text, reason):
    """Use the canonical manual-queue reason for an over-wide message."""
    width = vwf_wrap.text_width(text)
    return toolbelt.note_over(width, 240, 'px') if width > 240 else reason


def text_by_offset(path):
    return {int(row['offset'], 16): row['text']
            for row in csv.DictReader(open(path, encoding='utf-8'), delimiter='\t')}


def main():
    import toolbelt
    replay = eboot_twin_plan.replaying()
    if not replay:
        jp = dict(toolbelt.read_eboot('psp_jp'))
    us = dict(toolbelt.read_eboot('psp_us'))
    source = btlmsg.data()
    messages = btlmsg.messages(source)
    rows = []
    rejected = []
    for item in csv.DictReader(open(MAP, encoding='utf-8'), delimiter='\t'):
        idx = int(item['psx_idx'])
        start, end = messages[idx]
        ja = btlmsg.dec(source, start, end)
        if not replay:
            jp_text = jp[int(item['jp_boot_offset'], 16)]
            if jp_text != ja:
                raise SystemExit(f'BOOT/BTLMSG mapping drift at {idx}: {jp_text!r} != {ja!r}')
        off = int(item['us_boot_offset'], 16)
        # every textbox goes through THE derivation on its first pass
        # (port_derive.derive: codes in the destination family's spelling,
        # the box's own layout, the destination's reason) - never a
        # verbatim copy and never a later sweep's repair
        ja = btlmsg.dec(source, start, end)
        en, why = port_derive.derive(us[off], ja, 'BTLP', hex(start - btlmsg.B))
        if why:
            rejected.append((hex(start - btlmsg.B), f'EBOOT:{off:x}', en, rejection_reason(en, why)))
            continue
        rows.append({'pos': hex(start - btlmsg.B), 'en': en,
                     'psp': f'EBOOT:{off:x}'})
    occupied = {r['pos'] for r in rows}
    manual = {r['pos']: r for r in toolbelt.read_manual('BTLP', optional=True)}
    for pos, ja, source_row in reward_notice.derive():
        if pos in occupied:
            raise SystemExit(f'boot_btlmsg: duplicate source ownership at {pos}')
        if (manual.get(pos, {}).get('en') or '').strip():
            continue                       # human wording always wins
        en, why = port_derive.derive(source_row['text'], ja, 'BTLP', pos)
        if why:
            rejected.append((pos, f"EBOOT:{int(source_row['pos'], 16):x}", en, rejection_reason(en, why)))
            continue
        rows.append({'pos': pos, 'en': en,
                     'psp': f"EBOOT:{int(source_row['pos'], 16):x}"})
        occupied.add(pos)
    # THE SAME LINE IN THE PSP, every message the map and the notices leave:
    # its Japanese is exactly one PSP-JP row (match_jp.exact_twins), and that
    # row's PROVEN US twin (match_jp.us_twin) is the wording - through the
    # same derivation; a row it cannot lay out stays a gap.
    left = []
    for start, end in messages:
        pos = hex(start - btlmsg.B)
        if pos in occupied or (manual.get(pos, {}).get('en') or '').strip():
            continue
        left.append((pos, btlmsg.dec(source, start, end)))
    offsets = eboot_twin_plan.exact_us('boot_btlmsg', left)
    for pos, ja in left:
        off = offsets.get(pos)
        if off is None:
            continue
        text = eboot_twin_plan.us_text(off)
        if not (text or '').strip():
            continue
        en, why = port_derive.derive(text, ja, 'BTLP', pos)
        if why:
            rejected.append((pos, f'EBOOT:{off:x}', en, rejection_reason(en, why)))
            continue
        rows.append({'pos': pos, 'en': en, 'psp': f'EBOOT:{off:x}'})
        occupied.add(pos)
    for pos, psp, draft, why in rejected:
        toolbelt.route_over('BTLP', pos, psp, draft, why)
    n = toolbelt.upsert_generated('BTLP', rows)
    print(f'BOOT -> BTLP: {n} verified string port(s) -> '
          f'{toolbelt.gen_path("BTLP")}')


if __name__ == '__main__':
    if '--without-psp-jp' in sys.argv:
        os.environ[eboot_twin_plan.REPLAY_ENV] = str(eboot_twin_plan.PLAN)
        os.environ[reward_notice.REPLAY_ENV] = str(reward_notice.PLAN)
    main()
