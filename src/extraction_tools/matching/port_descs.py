"""Port PSX skill/item descriptions (DESCS.tsv) from the PSP-US BOOT bank.

Every English string here is READ from the boot description bank
(data/cache/boot_banks.tsv, the bank chain boot_tables.py parses) at
runtime via a psx-slot -> bank-offset map (src/extraction_tools/matching/descs_bank.tsv).
No English is typed into this file. The map carries verified bank offsets,
not wording.

Description-bank house style (user decision 2026-11-02): the one-line help
bank has 239 px, less than the PSP-US bank was written for. Three mechanical
abbreviations keep the wording intact where space allows and are applied here
so every re-port produces them:

  damage -> DMG     the damage amount, not the hazard in "damage floors"
  X status -> X     "status" is redundant after the status' own name
  Instant -> Insta  only ever the instant-kill lines in this bank

Nothing else is shortened; wording that still does not fit is routed to
manual as a draft for a human.

Routing (strlib doctrine):
* bank text fits the PSX slot -> translation/generated/strings/DESCS.tsv
  (auto, injectable);
* bank text wider than the slot -> translation/manual/strings/DESCS.tsv
  with the full source wording kept as a manual draft (toolbelt.route_over)
  until the destination can display it;
* no bank map entry -> manual gap (human text or deliberate skip).

Manual wins at build (descs.py reads via strlib.read).

Usage: python src/extraction_tools/matching/port_descs.py [--apply]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import strlib  # noqa: E402
import toolbelt  # noqa: E402
import vwf_wrap  # noqa: E402

BANK = os.path.join(ROOT, 'data', 'cache', 'boot_banks.tsv')
MAP = os.path.join(toolbelt.SOURCE_MAPPINGS, 'descs_bank.tsv')
NOTE = 'psp-boot-bank'
WIDTH = 239
HEAD = 'idx\tram\tja\ten\tnote\tused_by'


def bank_map():
    """{offset: text} of the boot description bank. The offsets are the BANK
    CHAIN's (src/extraction_tools/matching/descs_bank.tsv is keyed by them; boot_tables.py
    'banks' parses the chain and caches it) - not EBOOT.tsv's, whose rows
    anchor at the first glyph and so sit a space later."""
    import toolbelt
    if not os.path.exists(BANK):
        toolbelt.fail(f'{BANK} missing - run: python '
                      f'src/extraction_tools/psp/boot_tables.py banks')
    out = {}
    for r in strlib.tsv_rows(BANK, required=('offset', 'en')):
        out[int(r['offset'], 16)] = ' '.join(r['en'].split())
    return out


def bank_text(bank, off):
    """The bank line whose entry CONTAINS `off`: the map's offsets anchor at
    the first glyph, the bank's at its chain head, so exact equality is the
    wrong lookup (factcheck and this porter both use this)."""
    heads = sorted(bank)
    key = max((h for h in heads if h <= off), default=None)
    if key is None or off - key > 0x100:
        return ''
    return bank[key]


def slot_map():
    """{psx_idx: bank_offset} (derived, offset structure only)."""
    out = {}
    for r in strlib.tsv_rows(MAP, required=('psx_idx', 'bank_offset')):
        out[int(r['psx_idx'])] = int(r['bank_offset'], 16)
    return out


def house_style(text):
    """The description bank's three abbreviations (see the module docstring).

    They are token substitutions, not rewrites: the PSX help line is 239 px
    and the PSP-US bank was written for a wider box. Everything else stays
    the source's wording; text that still overruns is drafted for a human.
    """
    text = re.sub(r'\bdamage\b(?! floors)', 'DMG', text)
    text = re.sub(r'\s+status\b', '', text)
    return re.sub(r'\bInstant\b', 'Insta', text)


def main():
    apply = '--apply' in sys.argv
    bank, slots = bank_map(), slot_map()
    import toolbelt
    import descs
    # fact gate: a bank line may only be auto-added where it states the same
    # numbers as the PSX line (see factcheck.py). A dropped NAME is advisory
    # only: where the PSX and PSP-JP lines agree on the fact (both name the
    # gem), the PSP-US's shorter form is intentional localization and ships
    # as-is - the name is on screen in the same menu. Contradicting numbers
    # are blocked outright: no en, no note draft, because the wording IS the
    # inaccurate data.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import factcheck
    ok_map = factcheck.portable()
    d = descs.data()
    tab = descs.table(d)
    auto, over, n, blocked = [], [], 0, 0
    for i, (a, e) in enumerate(descs.strings(d)):
        pos = hex(a - descs.B)
        if i not in slots:
            continue
        en = vwf_wrap.one_line(house_style(bank_text(bank, slots[i])))
        if not ok_map.get(('descs', pos), True):
            blocked += 1
            continue
        px = vwf_wrap.text_width(en)
        if px <= WIDTH:
            auto.append({'pos': pos, 'en': en,
                         'psp': f'EBOOT:{slots[i]:x}'})
            n += 1
        else:
            # Over the display width: preserve the full draft in the note;
            # Japanese ships until the destination can display the full text.
            over.append((pos, f'EBOOT:{slots[i]:x}', en, px))
    if apply:
        if auto:
            toolbelt.upsert_generated('SLPS_005.00', auto)
        for pos, src, draft, px in over:
            toolbelt.route_over('SLPS_005.00', pos, src, draft,
                                toolbelt.note_over(px, WIDTH, 'px'))
    print(f'descs: {n} auto (bank text fits {WIDTH}px), '
          f'{len(over)} over limit -> manual, {blocked} blocked by the '
          f'fact check (see data/derived/factcheck.tsv)')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
