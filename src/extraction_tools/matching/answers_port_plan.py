"""Text-free answer-source plan.

The answer porter matches PSX answer strings to PSP-JP talk slots and to the
executable's rows, then takes the PSP-US wording. Capture that source choice
once; replay reads the US text from the recorded locator and reruns the answer
QA with the PSX Japanese only.

  python src/extraction_tools/matching/answers_port_plan.py   capture
  python src/extraction_tools/matching/port_answers.py --apply --without-psp-jp

A locator is `talk:NAME:k` (the PSP-US answer slot) or `boot:HEX` (a PSP-US
EBOOT box). The plan says which US source answers which PSX row, never what
the Japanese or the English says.
"""
import glob
import hashlib
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
import toolbelt
import source_plan

PLAN = Path(toolbelt.MAPPINGS) / 'answers_port_plan.tsv'
REPLAY_ENV = 'PERSONA_ANSWERS_PLAN'
VERSION = '1'


class PlanError(ValueError):
    """A replay needs a fresh capture; never silently drop an answer."""


_capture = None
_loaded = None
_loaded_path = None


def capturing():
    return _capture is not None


def begin_capture():
    global _capture
    _capture = []


def replaying():
    return bool(os.environ.get(REPLAY_ENV))


def record(kind, rel, pos, us_kind='', us_pos='', split=''):
    """Note one source decision; a no-op outside capture mode.

    `mode` is the row category ('answer', 'slot', 'sim', 'anchor', 'fuzzy').
    `split` carries the answer outcome/tag ('psp-us', ..., 'miss', 'qa-fail')
    and the similarity score for fuzzy-candidate rows."""
    if _capture is None:
        return
    _capture.append({'rel': str(rel), 'pos': str(pos), 'mode': kind,
                     'us_sub': us_kind, 'us_pos': us_pos, 'split': split})


def _files_digest(paths):
    h = hashlib.sha1()
    for path in sorted(map(str, paths)):
        h.update(os.path.basename(path).encode('utf-8') + b'\0')
        h.update(open(path, 'rb').read())
    return h.hexdigest()


def inputs():
    psx = _files_digest(glob.glob(str(ROOT / 'data/psx/TALK/*.BIN')))
    us = _files_digest(glob.glob(str(ROOT / 'data/psp_us/PSP_GAME/USRDIR/pack/talk/*.BIN')))
    boot = hashlib.sha1((ROOT / 'data/extracted_text/psp_us/EBOOT.tsv').read_bytes()).hexdigest()
    return psx, us, boot


def rule_digest():
    h = hashlib.sha1()
    for path in (HERE / 'port_answers.py', HERE / 'match_jp.py',
                 HERE / 'port_derive.py', HERE / 'port_common.py',
                 HERE / 'answers_port_plan.py',
                 ROOT / 'src/injection_tools/talktl.py',
                 ROOT / 'src/injection_tools/talk.py',
                 Path(toolbelt.MAPPINGS) / 'psp_pairs.tsv'):
        h.update(path.name.encode('utf-8') + b'\0')
        h.update(Path(path).read_bytes())
    return h.hexdigest()


def load():
    """{key: row} for single decisions and the ordered fuzzy rows."""
    global _loaded, _loaded_path
    path = os.environ.get(REPLAY_ENV)
    if _loaded is not None and _loaded_path == path:
        return _loaded
    if not path:
        _loaded, _loaded_path = {}, path
        return _loaded
    plan, matches = source_plan.read(path)
    if plan.get('version') != VERSION:
        raise PlanError('answers plan version mismatch; recapture with PSP-JP')
    psx, us, boot = inputs()
    if plan.get('psx:TALK') != psx or plan.get('us:TALK') != us or plan.get('us:EBOOT') != boot:
        raise PlanError('answers plan does not match the PSX/PSP-US talk data; recapture')
    if plan.get('rule_sha1') != rule_digest():
        raise PlanError('answers plan does not match the matching rules; recapture')
    index, fuzzy = {}, []
    for row in matches:
        key = (row['mode'], row['rel'], row['pos'])
        if row['mode'] == 'fuzzy':
            fuzzy.append(row)
            continue
        if key in index:
            raise PlanError(f'answers plan repeats the {row["mode"]} decision {row["rel"]}/{row["pos"]}')
        index[key] = row
    _loaded, _loaded_path = {'index': index, 'fuzzy': fuzzy}, path
    return _loaded


def lookup(kind, rel, pos):
    plan = load()
    if not plan:
        return None
    hit = plan['index'].get((kind, str(rel), str(pos)))
    if hit is None:
        raise PlanError(f'answers plan has no {kind} source for {rel}/{pos}; recapture')
    return hit


def us_text(row):
    """Wording at a captured locator ('talk:NAME:k' or 'boot:HEX')."""
    kind, rest = row['us_sub'], row['us_pos']
    if kind == 'boot':
        return dict(toolbelt.read_eboot('psp_us'))[int(rest, 16)]
    if kind != 'talk':
        raise PlanError(f'answers plan has an unknown locator {kind!r}; recapture')
    from text import load_talk_slots
    from port_answers import cut_end
    name, box = rest.rsplit(':', 1)
    return cut_end(load_talk_slots(name, 'us')[int(box)])


def locator(row):
    """The human-readable source tag used in generated rows and notes."""
    if row['us_sub'] == 'boot':
        return 'EBOOT/' + row['us_pos']
    name, box = row['us_pos'].rsplit(':', 1)
    return f'{name}/{box}'


def write(path=PLAN):
    global _capture, _loaded, _loaded_path
    if _capture is None:
        raise RuntimeError('write without begin_capture')
    matches = []
    for row in _capture:
        if not row['mode']:
            raise PlanError('answers plan decision without a kind')
        if row['mode'] == 'answer' and row['split'] == 'miss':
            row = dict(row, us_sub='', us_pos='')
        elif not row['us_sub'] or not row['us_pos']:
            raise PlanError(f'answers plan has an unqualified locator for {row["rel"]}/{row["pos"]}')
        matches.append(row)
    psx, us, boot = inputs()
    metadata = {'version': VERSION, 'rule_sha1': rule_digest(),
                'psx:TALK': psx, 'us:TALK': us, 'us:EBOOT': boot}
    source_plan.write(path, metadata, matches)
    _capture, _loaded, _loaded_path = None, None, None
    print(f'answers plan: {len(matches)} source decisions -> {path}')
    return matches


if __name__ == '__main__':
    # port_answers imports this module by name; running it as __main__ must
    # share the same capture state, not a second module object.
    sys.modules.setdefault('answers_port_plan', sys.modules[__name__])
    import port_answers
    begin_capture()
    port_answers.collect(apply=False)
    write()
