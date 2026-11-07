"""Text-free EBOOT twin plan for the boot-string porters.

The boot-string porters (boot_btlmsg, port_btlneg, port_btlbanner) take a PSX
line whose Japanese is exactly one PSP-JP EBOOT row and use that row's proven
PSP-US twin. Matching that pair needs the PSP-JP extract; capture the chosen
PSP-US offset once, then replay it with PSX + PSP-US only.

  python src/extraction_tools/matching/eboot_twin_plan.py   capture
  python src/extraction_tools/matching/boot_btlmsg.py --without-psp-jp
  python src/extraction_tools/matching/port_btlneg.py --without-psp-jp --apply
  python src/extraction_tools/matching/port_btlbanner.py --without-psp-jp --apply

A row is (consumer, PSX key) -> PSP-US EBOOT offset, or a 'none' decision when
no proven twin exists. Wording is never stored.
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

PLAN = Path(toolbelt.MAPPINGS) / 'eboot_twin_port_plan.tsv'
REPLAY_ENV = 'PERSONA_EBOOT_TWIN_PLAN'
VERSION = '1'


class PlanError(ValueError):
    """A replay needs a fresh capture; never silently drop a line."""


_capture = None
_loaded = None
_loaded_path = None
_us = None


def capturing():
    return _capture is not None


def begin_capture():
    global _capture
    _capture = []


def replaying():
    return bool(os.environ.get(REPLAY_ENV))


def record(consumer, key, mode, offset):
    if _capture is None:
        return
    _capture.append({'rel': consumer, 'pos': str(key), 'mode': mode,
                     'us_sub': 'boot' if offset is not None else '',
                     'us_pos': f'{offset:x}' if offset is not None else '',
                     'split': 'none' if offset is None else ''})


def _digest(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def inputs():
    return {
        'psx:BTLP': _digest(ROOT / 'data/psx/BTLP.BIN'),
        'us:EBOOT': _digest(ROOT / 'data/extracted_text/psp_us/EBOOT.tsv'),
        'us:boot-bin': _digest(ROOT / 'data/psp_us/PSP_GAME/SYSDIR/EBOOT.BIN'),
        'map:boot_btlmsg': _digest(Path(toolbelt.SOURCE_MAPPINGS) / 'boot_btlmsg.tsv'),
        'map:btlneg': _digest(Path(toolbelt.SOURCE_MAPPINGS) / 'btlneg_map.tsv'),
    }


def rule_digest():
    h = hashlib.sha1()
    for path in (HERE / 'eboot_twin_plan.py', HERE / 'match_jp.py', HERE / 'align.py',
                 HERE / 'notice_consumer.py', HERE / 'control_consumer.py',
                 HERE / 'boot_btlmsg.py', HERE / 'port_btlneg.py',
                 HERE / 'port_btlbanner.py', HERE / 'psp_pairs_extra.tsv',
                 HERE / 'psx_jp_extra.tsv',
                 Path(toolbelt.MAPPINGS) / 'psp_pairs.tsv'):
        h.update(path.name.encode('utf-8') + b'\0')
        h.update(Path(path).read_bytes())
    return h.hexdigest()


def load():
    global _loaded, _loaded_path
    path = os.environ.get(REPLAY_ENV)
    if _loaded is not None and _loaded_path == path:
        return _loaded
    if not path:
        _loaded, _loaded_path = {}, path
        return _loaded
    plan, matches = source_plan.read(path)
    if plan.get('version') != VERSION:
        raise PlanError('EBOOT twin plan version mismatch; recapture with PSP-JP')
    expected = inputs()
    for name, value in expected.items():
        if plan.get(name) != value:
            raise PlanError(f'EBOOT twin plan does not match {name}; recapture')
    if plan.get('rule_sha1') != rule_digest():
        raise PlanError('EBOOT twin plan does not match the matching rules; recapture')
    index = {}
    for row in matches:
        key = (row['rel'], row['pos'])
        if key in index:
            raise PlanError(f'EBOOT twin plan repeats {row["rel"]}/{row["pos"]}')
        index[key] = row
    _loaded, _loaded_path = {'index': index, 'rows': matches}, path
    return _loaded


def _record_offset(consumer, key, mode, offset, text):
    """Record the offset only when the twin actually carries wording."""
    if offset is not None and not (text or '').strip():
        offset = None
    record(consumer, key, mode, offset)
    return offset


def exact_us(consumer, texts):
    """{key: PSP-US EBOOT offset or None} for exact_twins + us_twin."""
    plan = load()
    if plan:
        out = {}
        for key, _ja in texts:
            row = plan['index'].get((consumer, str(key)))
            if row is None:
                raise PlanError(f'EBOOT twin plan has no decision for '
                                f'{consumer}/{key}; recapture')
            out[key] = int(row.get('us_pos', ''), 16) if row.get('us_pos') else None
        return out
    import match_jp
    twins = match_jp.exact_twins('EBOOT', texts)
    out = {}
    for key, _ja in texts:
        jp_row = twins.get(key)
        us = match_jp.us_twin('EBOOT', jp_row) if jp_row else None
        offset = int(us['pos'], 16) if us else None
        out[key] = _record_offset(consumer, key, 'exact', offset,
                                  us.get('text') if us else '')
    return out


def unanimous_us(consumer, items):
    """{key: PSP-US EBOOT offset or None} for unanimous_twin."""
    plan = load()
    if plan:
        out = {}
        for key, _ja in items:
            row = plan['index'].get((consumer, str(key)))
            if row is None:
                raise PlanError(f'EBOOT twin plan has no decision for '
                                f'{consumer}/{key}; recapture')
            out[key] = int(row.get('us_pos', ''), 16) if row.get('us_pos') else None
        return out
    import match_jp
    out = {}
    for key, ja in items:
        us = match_jp.unanimous_twin('EBOOT', ja)
        offset = int(us['pos'], 16) if us else None
        out[key] = _record_offset(consumer, key, 'unanimous', offset,
                                  us.get('text') if us else '')
    return out


def record_consumer(consumer, proofs):
    """Capture the consumer-proven rows of one porter pass.

    These proofs read the PSP-JP executable and extract, so replay records
    only the selected PSP-US EBOOT offset (a decision, never wording)."""
    if _capture is None:
        return
    for idx, source in proofs:
        record('consumer:' + consumer, idx, 'consumer', int(source['pos'], 16))


def consumer_us(consumer, messages):
    """[(idx, PSP-US row)] for one consumer's captured proofs.

    The plan is the decision list: only captured indexes return a row, in
    capture order. A captured index the porter no longer knows is stale."""
    plan = load()
    if not plan:
        raise RuntimeError('consumer proofs need a plan; recapture with PSP-JP')
    known = {idx for idx, _ja in messages}
    out = []
    for row in plan['rows']:
        if row['rel'] != 'consumer:' + consumer:
            continue
        idx = int(row['pos'])
        if idx not in known:
            raise PlanError(f'EBOOT twin plan has a stale {consumer} message '
                            f'{idx}; recapture')
        if not row.get('us_pos'):
            continue
        offset = int(row['us_pos'], 16)
        out.append((idx, {'pos': hex(offset), 'text': us_text(offset)}))
    return out


def us_text(offset):
    """The PSP-US wording at a captured EBOOT offset."""
    global _us
    if _us is None:
        _us = dict(toolbelt.read_eboot('psp_us'))
    if offset not in _us:
        raise PlanError(f'EBOOT twin plan has a stale US source {offset:#x}; recapture')
    return _us[offset]


def write(path=PLAN):
    global _capture, _loaded, _loaded_path
    if _capture is None:
        raise RuntimeError('write without begin_capture')
    matches = _capture
    metadata = {'version': VERSION, 'rule_sha1': rule_digest()}
    metadata.update(inputs())
    source_plan.write(path, metadata, matches)
    _capture, _loaded, _loaded_path = None, None, None
    print(f'EBOOT twin plan: {len(matches)} decisions -> {path}')


def capture():
    """Record the boot-string decisions from the two-region match."""
    # port_btlneg imports this module by name; share the capture state.
    sys.modules.setdefault('eboot_twin_plan', sys.modules[__name__])
    import boot_btlmsg
    import port_btlneg
    import port_btlbanner
    begin_capture()
    boot_btlmsg.main()
    # generated/ is ephemeral and port.py runs port_btlneg before boot_btlmsg:
    # a capture that honours rows already in generated/ would omit decisions
    # the from-zero replay still asks for. Capture the full domain instead;
    # replay applies the subset its current tables leave open.
    port_btlneg.port(apply=False, force=True)
    port_btlbanner.port(apply=False)
    write()


if __name__ == '__main__':
    capture()
