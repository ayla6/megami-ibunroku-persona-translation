"""Text-free battle-dialogue correspondence plan.

The PSX battle messages are matched to the PSP-JP cluster, bridged to PSP-US
and tiled into spans. Capture that per-message decision once (both regions
available); replay re-reads PSP-US wording and re-runs compose/rewrap/QA with
PSX and PSP-US only.

  python src/extraction_tools/matching/btlevt_port_plan.py   capture
  python src/extraction_tools/matching/port_btlevt.py --apply --without-psp-jp

Positions are file offsets into BTLP.BIN and start offsets of PSP-US EBOOT
records: the plan says which source line answers which message, never what it
says in Japanese.
"""
import hashlib
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
import toolbelt
import source_plan

PLAN = Path(toolbelt.MAPPINGS) / 'btlevt_port_plan.tsv'
REPLAY_ENV = 'PERSONA_BTLEVT_PLAN'
VERSION = '1'


class PlanError(ValueError):
    """A replay needs a fresh capture; never quietly file the message as a gap."""


def digest(data):
    return hashlib.sha1(data).hexdigest()


def matching_inputs_digest():
    paths = [HERE / 'port_btlevt.py', HERE / 'match_jp.py', HERE / 'align.py',
             HERE / 'port_derive.py', HERE / 'port_codes.py', Path(toolbelt.MAPPINGS) / 'psp_pairs.tsv',
             Path(toolbelt.SOURCE_MAPPINGS) / 'accept.tsv',
             ROOT / 'src/extraction_tools/psp/eboot.py',
             ROOT / 'src/extraction_tools/psp/text.py']
    h = hashlib.sha1()
    for path in paths:
        h.update(path.name.encode('utf-8') + b'\0')
        h.update(Path(path).read_bytes())
    return h.hexdigest()


def inputs():
    psx = digest((ROOT / 'data/psx/BTLP.BIN').read_bytes())
    us = digest((ROOT / 'data/extracted_text/psp_us/EBOOT.tsv').read_bytes())
    return psx, us


def load():
    env = os.environ.get(REPLAY_ENV)
    if not env:
        return None
    plan, matches = source_plan.read(env)
    if plan.get('version') != VERSION:
        raise PlanError('battle plan version mismatch; recapture with PSP-JP')
    psx, us = inputs()
    if plan.get('psx:BTLP') != psx:
        raise PlanError('battle plan does not match BTLP.BIN; recapture')
    if plan.get('us:EBOOT') != us:
        raise PlanError('battle plan does not match the PSP-US EBOOT extract; recapture')
    if plan.get('matching_inputs_sha1') != matching_inputs_digest():
        raise PlanError('battle plan does not match the matching inputs; recapture')
    return matches


def sources(psx, junits, uunits):
    """(per-message decisions, speaker map) from the plan or a live pass."""
    import port_btlevt
    matches = load()
    if matches is None:
        return port_btlevt.plan_sources(psx, junits, uunits)
    if len(matches) != len(psx):
        raise PlanError('battle plan does not cover every PSX message; recapture')
    us_index = {pos: i for i, (pos, _text) in enumerate(uunits)}
    out = []
    for (off, ja), row in zip(psx, matches):
        if row['rel'] != 'BTLP' or row['pos'] != hex(off):
            raise PlanError(f'battle plan order does not match BTLP at {off:#x}; recapture')
        if row['mode'] == 'gap':
            out.append({'kind': 'gap', 'off': off, 'ja': ja})
            continue
        lo = us_index.get(int(row['us_pos'], 16))
        hi = us_index.get(int(row['us_hi_pos'], 16))
        if lo is None or hi is None or hi < lo:
            raise PlanError(f'battle plan has a stale PSP-US span at {off:#x}; recapture')
        out.append({'kind': 'ok', 'off': off, 'ja': ja, 'lo': lo, 'hi': hi,
                    'speaker': row.get('speaker', ''), 'cut': row.get('split', '')})
    return out, {}


def write(psx, junits, uunits, path=PLAN):
    import port_btlevt
    decisions, _amap = port_btlevt.plan_sources(psx, junits, uunits)
    matches = []
    for src in decisions:
        row = {'rel': 'BTLP', 'pos': hex(src['off']), 'us_sub': 'btlevt',
               'mode': src['kind']}
        if src['kind'] == 'ok':
            row.update(us_pos=hex(uunits[src['lo']][0]),
                       us_hi_pos=hex(uunits[src['hi']][0]),
                       speaker=src['speaker'], split=src['cut'])
        matches.append(row)
    psx_digest, us_digest = inputs()
    metadata = {'version': VERSION, 'matching_inputs_sha1': matching_inputs_digest(),
                'psx:BTLP': psx_digest, 'us:EBOOT': us_digest}
    source_plan.write(path, metadata, matches)
    print(f'battle plan: {len(matches)} decisions -> {path}')
    return matches


if __name__ == '__main__':
    import port_btlevt
    data = port_btlevt.btlevt.data()
    psx = [(start - port_btlevt.btlevt.B,
            port_btlevt.etext.decode(data[start - port_btlevt.btlevt.B:
                                          end - port_btlevt.btlevt.B - 2]))
           for start, end in port_btlevt.btlevt.messages(data)]
    write(psx, port_btlevt.jp_units(), port_btlevt.us_units())
