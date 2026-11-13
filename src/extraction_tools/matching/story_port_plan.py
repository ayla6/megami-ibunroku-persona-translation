"""Text-free decisions for the two story checks that consult PSP-JP.

Speaker arbitration compares PSX Japanese with its PSP-JP partner to tell a
refined translation from a misaligned scene; the slot join names a PSP-JP line
when align.tsv has no row for a PSX box. Both outcomes are frozen here as
hashes and booleans/pointers, never wording, so replay needs only PSX and
PSP-US data.

Capture (both regions available):

  python src/extraction_tools/matching/story_port_plan.py

Replay:

  python src/extraction_tools/matching/port_story.py --bulk --apply --without-psp-jp

A decision missing from the plan is an error, not a silent gap: recapture with
PSP-JP after changing the correspondence inputs.
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

PLAN = Path(toolbelt.MAPPINGS) / 'story_port_plan.tsv'
REPLAY_ENV = 'PERSONA_STORY_PLAN'
VERSION = '2'


class PlanError(ValueError):
    """A replay needs a fresh capture; never quietly file the box as a gap."""


def digest(raw):
    return hashlib.sha1(raw).hexdigest()


def matching_inputs_digest():
    """Invalidate frozen decisions when their correspondence inputs change."""
    paths = [HERE / 'match_jp.py', HERE / 'align.py', Path(toolbelt.MAPPINGS) / 'align.tsv',
             Path(toolbelt.SOURCE_MAPPINGS) / 'align_fix.tsv',
             Path(toolbelt.SOURCE_MAPPINGS) / 'accept.tsv']
    h = hashlib.sha1()
    for path in paths:
        h.update(path.name.encode('utf-8') + b'\0')
        h.update(Path(path).read_bytes())
    return h.hexdigest()


def inputs():
    """PSX and PSP-US script files the decisions are computed from."""
    psx = {name: digest((ROOT / 'data' / 'psx' / 'ADV' / (name + '.BIN')).read_bytes())
           for name in ('E0', 'E1', 'E2', 'E3')}
    us = {name: digest((ROOT / 'data' / 'psp_us' / 'PSP_GAME' / 'USRDIR' / 'pack'
                        / (name + '.BIN')).read_bytes())
          for name in ('E0', 'E1', 'E2', 'E3')}
    return psx, us


class _Capture:
    def __init__(self):
        self.arbitrations = {}
        self.slots = {}
        self.joins = {}


_capture = None
_plan = None


def begin_capture():
    global _capture
    _capture = _Capture()


def capturing():
    return _capture is not None


def _load():
    global _plan
    if _plan is not None:
        return _plan
    env = os.environ.get(REPLAY_ENV)
    if not env:
        _plan = {}
        return _plan
    plan, matches = source_plan.read(env)
    if plan.get('version') != VERSION:
        raise PlanError('story plan version mismatch; recapture with PSP-JP')
    psx, us = inputs()
    if {k[4:]: v for k, v in plan.items() if k.startswith('psx:')} != psx:
        raise PlanError('story plan does not match the PSX scripts; recapture')
    if {k[3:]: v for k, v in plan.items() if k.startswith('us:')} != us:
        raise PlanError('story plan does not match the PSP-US scripts; recapture')
    if plan.get('matching_inputs_sha1') != matching_inputs_digest():
        raise PlanError('story plan does not match the correspondence inputs; recapture')
    _plan = {(r['rel'], r['pos'], r['us_sub']): r for r in matches}
    return _plan


def _lookup(row_kind, f, ei, key):
    plan = _load()
    if not plan:
        return None
    row = plan.get((f, f'{ei}:{key}', row_kind))
    if row is None and row_kind == 'arbitrate':
        raise PlanError(f'story plan has no speaker decision for {f}/{ei}/{key}; '
                         'recapture with PSP-JP')
    return row


def decide(f, ei, k, jidx, live):
    """Speaker arbitration outcome; `live` returns (bool, PSP-JP bytes)."""
    global _capture
    if _capture is not None:
        result, _jp_raw = live()
        _capture.arbitrations[(f, ei, k)] = {'same': result}
        return result
    row = _lookup('arbitrate', f, ei, k)
    if row is None:
        return live()[0]
    return row['mode'] == 'same'


def slot(f, ei, psx_offset, live):
    """(us_file, us_entry, us_box) chosen by the slot join, or None."""
    global _capture
    if _capture is not None:
        result = live()
        _capture.slots[(f, ei, psx_offset)] = {'result': result}
        return result
    row = _lookup('slot', f, ei, f'{psx_offset:#x}')
    if row is None:
        if _load():
            raise PlanError(f'story plan has no slot join for {f}/{ei}/{psx_offset:#x}; '
                             'recapture with PSP-JP')
        return live()
    if row['mode'] == 'none':
        return None
    return row['us_sub'], int(row['mode']), int(row['us_pos'], 16)


def joins(f, ei, k, live):
    """Box-boundary joins (port_story.box_joins) for a PSX box, or None."""
    global _capture
    if _capture is not None:
        result = live()
        _capture.joins[(f, ei, k)] = result
        return result
    row = _lookup('joins', f, ei, k)
    if row is None:
        if _load():
            raise PlanError(f'story plan has no box joins for {f}/{ei}/{k}; '
                             'recapture with PSP-JP')
        return live()
    if row['mode'] == 'none':
        return None
    return [c == '1' for c in row['mode']]


def write_capture(path=PLAN):
    global _capture
    if _capture is None:
        raise RuntimeError('write_capture without begin_capture')
    psx, us = inputs()
    metadata = {'version': VERSION, 'matching_inputs_sha1': matching_inputs_digest()}
    metadata.update({f'psx:{k}': v for k, v in psx.items()})
    metadata.update({f'us:{k}': v for k, v in us.items()})
    matches = []
    for (f, ei, k), row in sorted(_capture.arbitrations.items()):
        matches.append({'rel': f, 'pos': f'{ei}:{k}', 'us_sub': 'arbitrate',
                        'mode': 'same' if row['same'] else 'different'})
    for (f, ei, off), row in sorted(_capture.slots.items()):
        found = row['result']
        if found is None:
            matches.append({'rel': f, 'pos': f'{ei}:{off:#x}', 'us_sub': 'slot',
                            'mode': 'none'})
        else:
            sfile, sei, sk = found
            matches.append({'rel': f, 'pos': f'{ei}:{off:#x}', 'us_sub': 'slot',
                            'mode': str(sei), 'us_pos': hex(sk)})
    for (f, ei, k), found in sorted(_capture.joins.items()):
        matches.append({'rel': f, 'pos': f'{ei}:{k}', 'us_sub': 'joins',
                        'mode': 'none' if found is None
                        else ''.join('1' if j else '0' for j in found)})
    source_plan.write(path, metadata, matches)
    print(f'story plan: {len(matches)} decisions -> {path}')
    return matches


if __name__ == '__main__':
    # Run through port_story's module instance: this file is `__main__` here,
    # and port_story imports it under its real name.
    import port_story
    port_story.story_port_plan.begin_capture()
    port_story.cmd_bulk(apply=False, jobs=1)
    port_story.story_port_plan.write_capture()
