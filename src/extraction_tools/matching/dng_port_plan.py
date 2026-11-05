"""Text-free, source-validated dungeon correspondence plan.

Capture with both PSP regions; replay computes English from PSP-US and PSX
without reading PSP-JP. The plan holds paths, offsets, modes and digests only.
"""
import hashlib
import inspect
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
import toolbelt
import source_plan

PLAN = Path(toolbelt.MAPPINGS) / 'dng_port_plan.tsv'
US_ROOT = ROOT / 'data/psp_us/PSP_GAME/USRDIR/pack/dng'
VERSION = '1'


def digest(data):
    return hashlib.sha1(data).hexdigest()


def file_digest(path):
    return digest(Path(path).read_bytes())


def rule_digest():
    import port_dng
    h = hashlib.sha1()
    for part in (inspect.getsource(port_dng.us_near), inspect.getsource(port_dng.paired_boxes),
                 inspect.getsource(port_dng.port)):
        h.update(part.encode('utf-8') + b'\0')
    for path in (Path(port_dng.MAP), Path(toolbelt.PSP_GLYPHS)):
        h.update(path.read_bytes())
    return h.hexdigest()


def inputs(surface):
    psx = {rel: file_digest(ROOT / 'data/psx' / (rel + '.BIN')) for rel in sorted(surface)}
    us = {p.parent.name: file_digest(p) for p in sorted(US_ROOT.glob('d*/d*.bin'))
          if p.stem == p.parent.name}
    if not psx or not us:
        raise ValueError('DNG plan needs PSX and PSP-US dungeon source files')
    return psx, us


def capture(path=PLAN):
    import port_dng
    gen, surface = port_dng.port(False, strict=True)
    psx, us = inputs(surface)
    texts = {}
    entries = []
    for rel in sorted(gen):
        for row in gen[rel]:
            sub, off = row['psp'].split(':', 1)
            pos = int(off, 16)
            if sub not in texts:
                texts[sub] = dict(port_dng.boxes('us', sub))
            if pos not in texts[sub]:
                raise ValueError(f'DNG {rel}:{row["pos"]}: missing US source {row["psp"]}')
            entries.append({'rel': rel, 'pos': row['pos'], 'us_sub': sub,
                            'us_pos': hex(pos), 'mode': row['_source_mode']})
    plan = {'version': VERSION, 'rule_sha1': rule_digest()}
    plan.update({f'psx:{rel}': value for rel, value in psx.items()})
    plan.update({f'us:{sub}': value for sub, value in us.items()})
    source_plan.write(path, plan, entries)
    print(f'DNG plan: {len(entries)} text-free correspondences -> {path}')
    return plan, entries


def replay(surface, path=PLAN):
    import port_dng
    plan, entries = source_plan.read(path)
    if plan.get('version') != VERSION or plan.get('rule_sha1') != rule_digest():
        raise ValueError('DNG correspondence plan does not match the matching rules')
    psx, us = inputs(surface)
    stored_psx = {k[4:]: v for k, v in plan.items() if k.startswith('psx:')}
    stored_us = {k[3:]: v for k, v in plan.items() if k.startswith('us:')}
    if stored_psx != psx or stored_us != us:
        raise ValueError('DNG correspondence plan does not match the PSX or PSP-US inputs')
    positions = {rel: dict(rows) for rel, rows in surface.items()}
    texts, result = {}, {}
    for entry in entries:
        rel, pos, sub = entry['rel'], entry['pos'], entry['us_sub']
        offset = int(entry['us_pos'], 16)
        if rel not in positions or pos not in positions[rel] or sub not in us:
            raise ValueError(f'DNG correspondence plan has stale position {rel}:{pos}')
        if sub not in texts:
            texts[sub] = dict(port_dng.boxes('us', sub))
        raw = texts[sub].get(offset)
        if raw is None:
            raise ValueError(f'DNG correspondence plan has stale US source {sub}:{offset:x}')
        ja, raw = positions[rel][pos], port_dng.clean_us(raw)
        if port_dng.HOLE.search(raw):
            raise ValueError(f'DNG {rel}:{pos}: US source contains undecoded glyphs')
        if entry['mode'] == 'anchored':
            en = port_dng.assemble(ja, raw)
            if en is None:
                raise ValueError(f'DNG {rel}:{pos}: cannot assemble matched source')
            en = port_dng.reflow_en(en)
            reason = port_dng.fit_report(ja, en, None)
            if 'encode-fail' in reason or 'codes differ' in reason:
                raise ValueError(f'DNG {rel}:{pos}: source fails QA: {reason}')
        elif entry['mode'] == 'similarity':
            en = port_dng.reflow_en(port_dng.psx_furniture(ja, raw))
        else:
            raise ValueError(f'DNG {rel}:{pos}: unknown correspondence mode')
        if not port_dng.etext.has_text(en):
            raise ValueError(f'DNG {rel}:{pos}: empty correspondence result')
        result.setdefault(rel, []).append({'pos': pos, 'psp': f'{sub}:{offset:x}',
                                           'en': en, '_source_mode': entry['mode']})
    return result


if __name__ == '__main__':
    capture()
