"""PSX extraction: every text unit of every real PSX file, per-file TSVs.

  python src/extraction_tools/psx/extract_text_all.py

data/extracted_text/psx/<rel>.tsv (id | pos | text): the Japanese text of
data/psx/<rel>, keyed by file offset - the position source the porters
match against and the navigator shows. Same shape as the PSP extracts.
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'injection_tools'))
import toolbelt  # noqa: E402
import toolbelt   # noqa: E402
import etext      # noqa: E402

ROOT = toolbelt.ROOT
PSX = os.path.join(toolbelt.ROOT, 'data', 'psx')


def dng_rows(rel, path):
    import dngpacks   # noqa: E402
    d = open(path, 'rb').read()
    base = os.path.basename(rel)
    if len(base) == 3:                        # boxes file
        return [(off, ja) for off, _ln, ja in dngpacks.boxes(d)]
    if base.endswith('M'):                    # name fields file
        return [(off, ja) for off, ja in dngpacks.name_fields(d)]
    return []                                 # D0?S and friends: not text


def slps_rows(rel, path):
    import slps       # noqa: E402
    d = open(path, 'rb').read()
    return [(off, ja) for off, ja, _psp, _fam in slps.families(d)]


def s2d_rows(rel, path):
    import s2d        # noqa: E402
    d = open(path, 'rb').read()
    out = []
    for a, e in s2d.script_boxes(d):
        out.append((a - s2d.B, etext.decode(d[a - s2d.B:e - s2d.B - 2])))
    for a, e in s2d.name_slots(d):
        out.append((a - s2d.B, etext.decode(d[a - s2d.B:e - s2d.B - 2])))
    return out


def btlp_rows(rel, path):
    """BTLP.BIN: one row per slot of btlp.families (evt, neg, msg, banner, board),
    in that order - the same slots btlp.dump scaffolds, so the extract's
    ids line up with the generated ones. Scan the evt zone only once:
    btlevt.messages and btlp.evt_messages walk the same zone."""
    import btlp       # noqa: E402
    import battle_board_text
    d = open(path, 'rb').read()
    board = dict(battle_board_text.scan(d))
    spans = {a: e for a, e in (btlp.evt_messages(d) + btlp.neg_strings(d)
                               + btlp.msg_messages(d))}
    ban = {p: ja for _k, p, ja in btlp.ban_records(d)}
    out = []
    for off, fam in btlp.families(d):
        p = off + btlp.B
        text = board[off] if fam == 'board' else (ban[p] if fam == 'banner' else btlp.dec(d, p, spans[p]))
        out.append((off, text))
    return out


def adv_rows(rel, path):
    import sysmsg, giftmsg, scriptmsg   # noqa: E402
    d = open(path, 'rb').read()
    out = [(a - sysmsg.B, sysmsg.dec(d, a, e))
           for i, (a, e) in enumerate(sysmsg.messages(d)) if i not in sysmsg.DEAD]
    out.append((giftmsg.OLD_A - giftmsg.B,
                etext.decode(d[giftmsg.OLD_A - giftmsg.B:giftmsg.OLD_E - giftmsg.B])))
    out += [(off, ja) for off, ja in scriptmsg.messages(d)]
    return out


def dng_bin_rows(rel, path):
    """DNG.BIN itself (the pack scans cover D0?/D*M): its only text is the
    `FF 55` script messages. FF09/FF0A take an item / skill id, not text."""
    import scriptmsg   # noqa: E402
    d = open(path, 'rb').read()
    return [(off, ja) for off, ja in
            scriptmsg.messages(d, scriptmsg.NAME_PARAMS)]


def story_rows(rel, path):
    """ADV archives (efile): every box of every entry, pos = 'entry:off'."""
    import efile   # noqa: E402
    out = []
    try:
        entries = efile.load(path).entries
    except Exception as ex:
        print(f'extract_text_all: {rel}: not an efile archive ({ex}) - skipped')
        return out
    for e, ent in enumerate(entries):
        for b, (a, z) in enumerate(ent.boxes):
            out.append((((e + 1) << 24) | a, etext.decode(ent.body[a:z])))
    return out


def casino_rows(rel, path):
    import casinoprize   # noqa: E402
    return [(off, ja) for off, _raw, ja in casinoprize.records(open(path, 'rb').read())]


def talk_rows(rel, path):
    """TALK/<NAME>.BIN: dialogue units (entry 0) + the answer table
    (entry 1) - same sections as the PSP talk extracts."""
    import talk   # noqa: E402
    name = os.path.basename(path)[:-4]
    t = talk.Talk(name, open(path, 'rb').read())
    if not t.ok:
        return []
    # a dialogue unit that is its end code alone shows nothing: not a row
    # (port_talk carries the PSP bytes cut at its index into the stream)
    out = [(t.starts[i], etext.decode(u), '0') for i, u in enumerate(t.units)
           if not talk.dead_unit(u)]
    for v, sp in t.s1:
        out.append((t.hdr[1] + v, etext.decode(sp[:t.s1_text_len(sp)]), '1'))
    return out


SCANS = {'S2D': s2d_rows, 'BTLP': btlp_rows, 'ADV': adv_rows, 'CASINO': casino_rows}


def main(*, worklists=True):
    total = files = 0
    import dngpacks
    dng_set = {path for _rel, path in dngpacks.pack_files()}
    for fp in sorted(glob.glob(os.path.join(PSX, '**', '*.BIN'), recursive=True)
                     + glob.glob(os.path.join(PSX, 'SLPS_*'))):
        rel = os.path.relpath(fp, PSX)
        if rel.endswith('.BIN'):
            rel = rel[:-4]
        base = os.path.basename(rel)
        if rel == 'SLPS_005.00':
            rows = slps_rows(rel, fp)
        elif os.path.basename(fp) == 'ADV.BIN':
            rows = adv_rows(rel, fp)
        elif rel.startswith('ADV/') and rel.count('/') == 1:
            rows = story_rows(rel, fp)
        elif rel.startswith('TALK/'):
            rows = talk_rows(rel, fp)
        elif rel in SCANS:
            rows = SCANS[rel](rel, fp)
        elif rel == 'DNG':                  # the overlay's FF55 script messages
            rows = dng_bin_rows(rel, fp)
        elif fp in dng_set:                 # every dungeon pack (boxes+names)
            rows = dng_rows(rel, fp)
        else:
            continue
        if not rows:
            continue
        # rows = (off, text) or (off, text, entry); archive scans pack
        # entry+1 in the high byte so entry 0 survives into the pos cell
        items = []
        for r in rows:
            off, ja = r[0], r[1]
            ent = r[2] if len(r) > 2 else ''
            packed = off >> 24
            if packed:
                ent = str(packed - 1)
                cell = f'{ent}:{off & 0xFFFFFF:#x}'
            else:
                cell = hex(off)
            items.append({'entry': ent, 'pos': cell, 'text': ja})
        toolbelt.write_extracted('psx', rel, items)
        if worklists:
            toolbelt.route_gaps(rel, [it['pos'] for it in items], stale=True)
        total += len(rows)
        files += 1
    print(f'extract_text_all: {total} text units in {files} files -> '
          f'{os.path.join(toolbelt.EXTRACTED, "psx")}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-worklists', action='store_true',
                        help='extract caches without changing manual worklists')
    args = parser.parse_args()
    main(worklists=not args.no_worklists)
