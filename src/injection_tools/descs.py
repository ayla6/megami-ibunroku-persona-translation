"""Skill / item descriptions of SLPS_005.00 (Triangle help in the battle skill menu, item menus ...).

  python tools/descs.py dump     write/refresh translation/strings/DESCS.tsv (keeps the `en` and `note` columns)
  python tools/descs.py build    QA + generate build/descs.asm (included by main.asm, SLPS section)

Strings: 0x80049104-0x8004AA78, dialogue encoding ending with FF 01; pointer table 0x8004AA7C-0x8004B0CC (404 words;
entries share strings). No other reference into the zone was found (word scan of every code file), so the English
strings are re-packed freely inside it and the table rewritten. One `en` per unique string (TSV row = string).
`en`: one line, <= 239 px (tools/vwf_wrap.py), control codes as in the Japanese.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext     # noqa: E402
import vwf_wrap  # noqa: E402

ROOT = etext.ROOT
REL = 'SLPS_005.00'
B = 0x80010000 - 0x800
ZONE = (0x80049104, 0x8004AA78)
TABLE = (0x8004AA7C, 0x8004B0CC)
OUT = os.path.join(ROOT, 'build', 'descs.asm')
DRAFT_OUT = os.path.join(ROOT, 'build', 'descs_drafts.tsv')
NL = chr(10)
END = b'\xff\x01'


def data():
    return open(os.path.join(ROOT, 'data', 'psx', 'SLPS_005.00'), 'rb').read()


def strings(d):
    out, i = [], ZONE[0] - B
    while i < ZONE[1] - B:
        if d[i] == 0:
            i += 1
            continue
        e = d.index(END, i) + 2
        out.append((B + i, B + e))
        i = e
    return out


def table(d):
    return [struct.unpack_from('<I', d, a - B)[0] for a in range(TABLE[0], TABLE[1], 4)]


def read_rows():
    """Merged canonical rows keyed by pos (manual wins)."""
    import toolbelt  # noqa: E402
    return {r['pos']: r for r in toolbelt.merged_rows('SLPS_005.00')}


def dump():
    """Queue the string-bank positions in the canonical manual worklist
    (the rows themselves are scaffolded by slps.py dump; the port lives in
    port_descs.py)."""
    import toolbelt  # noqa: E402
    d = data()
    toolbelt.route_gaps(REL, [hex(a - B) for a, _e in strings(d)])
    print('descs: worklist queued in', toolbelt.man_path(REL))


def build():
    import toolbelt  # noqa: E402
    d = data()
    strs = strings(d)
    tab = table(d)
    starts = {a: i for i, (a, e) in enumerate(strs)}
    for p in tab:
        assert p in starts, hex(p)
    rows = read_rows()
    man = {r['pos']: r for r in toolbelt.read_manual('SLPS_005.00')}
    # a filled row in the string bank that the scan has no slot for is a
    # stale row (binary layout shifted): fail loud for human re-homing
    known = {hex(a - B) for a in starts}
    for pos, r in rows.items():
        for _entry, off in toolbelt.pos_offsets(pos):
            if (ZONE[0] - B <= off < ZONE[1] - B and hex(off) not in known
                    and (r.get('en') or '').strip()):
                toolbelt.fail(f'descs: row {r["id"]} pos {pos} is stale '
                              f'(the string scan has no such slot) - re-home it')
    routed = set()
    human_drafts = []
    new = []
    for i, (a, e) in enumerate(strs):
        pos = hex(a - B)
        r = rows.get(pos)
        t = (r['en'] if r else '').strip()
        if not t:
            new.append(bytes(d[a - B:e - B]))   # gap or un-adopted draft: JA ships
            continue
        if re.search(r'<FF(?:03|04|F6)>', t, re.IGNORECASE):
            toolbelt.fail(f'descs: {pos}: line/page move in a one-row description')
        try:
            b = etext.encode(t, end=END)
        except ValueError as ex:
            toolbelt.fail(f'descs: {i} {t!r}: not encodable in the text charset')
        w = vwf_wrap.text_width(t)
        if w > 239:
            if pos in man and man[pos].get('en', '').strip() == t:
                # The human's full wording stays untouched in manual. Until
                # every consumer can display more than one line, keep the
                # original Japanese bytes and explicitly report the draft.
                human_drafts.append((pos, w, t))
                new.append(bytes(d[a - B:e - B]))
                continue
            # porter wording over cap: route to manual (draft in the note),
            # generated stays empty (JA ships)
            toolbelt.route_over(
                REL, pos, r['psp'], t, toolbelt.note_over(w, 239, 'px'))
            routed.add(pos)
            new.append(bytes(d[a - B:e - B]))
            continue
        new.append(b)
    # identical strings and suffixes are shared (the table points into the middle of a longer string)
    at = {}
    p = ZONE[0]
    blobs = []
    for b in sorted(set(new), key=len, reverse=True):
        host = next((h for h in at if h.endswith(b)), None)
        if host is not None:
            at[b] = at[host] + len(host) - len(b)
            continue
        at[b] = p
        blobs.append((p, b))
        p += len(b)
    place = [at[b] for b in new]
    if p > ZONE[1]:
        raise SystemExit(f'descs: {p - ZONE[1]} bytes over the zone')
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by tools/descs.py build - do not edit' + NL)
        o.write(f'.org {ZONE[0]:#x}{NL}    .fill {ZONE[1] - ZONE[0]:#x}, 0{NL}')
        for a, b in blobs:
            o.write(f'.org {a:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in b) + NL)
        o.write(f'.org {TABLE[0]:#x}{NL}')
        for q in tab:
            o.write(f'    .word {place[starts[q]]:#x}' + NL)
    with open(DRAFT_OUT, 'w', encoding='utf-8', newline=NL) as o:
        o.write('pos\twidth_px\tdraft\n')
        for pos, width, draft in human_drafts:
            o.write(f'{pos}\t{width}\t{draft}\n')
    print(f'descs: {sum(1 for pos in known if rows.get(pos, {}).get("en", "").strip()) - len(human_drafts)}/{len(strs)} translated, '
          f'{len(routed)} routed to manual, {len(human_drafts)} human draft(s) retained unshipped, '
          f'{p - ZONE[0]} of {ZONE[1] - ZONE[0]} bytes -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
