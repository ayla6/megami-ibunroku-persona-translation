"""Text-free, source-validated S2D correspondence plan.

Capture with both PSP regions available; replay needs only PSX and PSP-US.
The plan stores source offsets and input digests, never Japanese text or
English wording. It freezes the proven matches, not the finished translations.
"""
import hashlib
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
import toolbelt
import tables
import source_plan

PLAN = Path(toolbelt.MAPPINGS) / 's2d_port_plan.tsv'
VERSION = '1'


def digest(data):
    return hashlib.sha1(data).hexdigest()


def matching_inputs_digest():
    """Invalidate the frozen matches if their correspondence inputs change."""
    paths = [HERE / 'match_jp.py', HERE / 'psx_jp_extra.tsv',
             HERE / 'psp_pairs_extra.tsv', Path(toolbelt.MAPPINGS) / 'psp_pairs.tsv',
             Path(toolbelt.PSP_GLYPHS)]
    h = hashlib.sha1()
    for path in paths:
        h.update(path.name.encode('utf-8') + b'\0')
        h.update(bytes.fromhex(digest(path.read_bytes())))
    return h.hexdigest()


def _us():
    return {hex(int(r['pos'], 16)): r['text']
            for r in toolbelt.read_extracted('psp_us', 'EBOOT')}


def capture(path=PLAN):
    """Re-derive matches with both regions, then atomically publish a plan."""
    import port_s2d
    import s2d
    # Report-only strict pass: no generated/manual translation is rewritten.
    rows = port_s2d.port(False, force=True, strict=True)
    data = s2d.data()
    boxes = s2d.script_boxes(data)
    script_positions = {hex(a - s2d.B) for a, _ in boxes}
    us = _us()
    entries = []
    # Legacy authored BOOT ranges are still evaluated by the normal owner;
    # only the whole-dialogue matches need this plan.
    legacy = {hex(boxes[int(r['idx'])][0] - s2d.B)
              for r in port_s2d.strlib.tsv_rows(port_s2d.MAP, required=('idx',))}
    for row in rows:
        if row['pos'] not in script_positions or row['pos'] in legacy:
            continue
        prefix, loc = row['psp'].split(':', 1)
        if prefix != 'EBOOT':
            raise ValueError(f"S2D {row['pos']}: unsupported source {row['psp']}")
        pos = hex(int(loc, 16))
        if pos not in us:
            raise ValueError(f'S2D {row["pos"]}: missing US source {pos}')
        entries.append({'pos': row['pos'], 'us_pos': pos})
    plan = {'version': VERSION, 'matching_inputs_sha1': matching_inputs_digest(),
            'psx_sha1': digest(data), 'us_boot_sha1': digest(tables.us_boot())}
    source_plan.write(path, plan, entries)
    print(f'S2D plan: {len(entries)} text-free correspondences -> {path}')
    return plan, entries


def replay(data, boxes, done, path=PLAN):
    """Re-port proven matches from the US source; fail on stale/missing data."""
    import port_s2d
    import s2d
    plan, matches = source_plan.read(path)
    if plan.get('version') != VERSION or plan.get('psx_sha1') != digest(data):
        raise ValueError('S2D correspondence plan does not match the PSX input')
    if plan.get('matching_inputs_sha1') != matching_inputs_digest():
        raise ValueError('S2D correspondence plan does not match the matching inputs')
    if plan.get('us_boot_sha1') != digest(tables.us_boot()):
        raise ValueError('S2D correspondence plan does not match the PSP-US BOOT')
    us = _us()
    positions = {hex(a - s2d.B): (a, e) for a, e in boxes}
    seen, result = set(), []
    for entry in matches:
        pos, source = entry['pos'], entry['us_pos']
        if pos in seen or pos not in positions:
            raise ValueError(f'S2D correspondence plan has duplicate or stale position {pos}')
        seen.add(pos)
        if source not in us:
            raise ValueError(f'S2D correspondence plan has stale US source {source}')
        if pos in done:
            continue
        a, e = positions[pos]
        ja = port_s2d.etext.decode(data[a - s2d.B:e - s2d.B - 2])
        try:
            en = port_s2d.script_text(ja, port_s2d.decoded_en(us[source], ja))
        except ValueError as exc:
            raise ValueError(f'S2D {pos}: cannot replay correspondence: {exc}') from exc
        bad = port_s2d.tstatus.ship_errors(ja, en)
        if bad:
            raise ValueError(f'S2D {pos}: correspondence fails QA: {bad}')
        result.append({'pos': pos, 'en': en, 'psp': f'EBOOT:{int(source, 16):x}'})
    return result


if __name__ == '__main__':
    capture()
