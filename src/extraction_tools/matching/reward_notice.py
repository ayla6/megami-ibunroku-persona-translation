"""Corroborate PSX reward notices using independently paired PSP story frames.

No translation or name is authored here. A candidate must match a complete
highlighted-item story notice whose JP/US records share a proven coordinate,
then a unique canonical item and unique PSP-JP and PSP-US messages bounded by
independently proven, monotonic EBOOT anchors. Ambiguity is always a gap.
"""
import bisect
import collections
import hashlib
import os
import re
import unicodedata
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlmsg
import items
import match_jp
import toolbelt
import source_plan

PLAN = Path(toolbelt.MAPPINGS) / 'reward_notice_port_plan.tsv'
REPLAY_ENV = 'PERSONA_REWARD_NOTICE_PLAN'
VERSION = '1'


class PlanError(ValueError):
    """A replay needs a fresh capture; never silently drop a notice."""


_capture = None
_loaded = None
_loaded_path = None

# A complete, single highlighted source item with no other controls. The
# parameters are the PSP story script's item and highlight controls, not names.
HIGHLIGHT = re.compile(
    r'^([^<>]*)<FF19><[0-9A-F]{4}><FF18><0500>([^<>]+)'
    r'<FF18><0000>([^<>]*)<FF02><FF01>$')
CONTROL = re.compile(r'<([0-9A-F]{4})>')
TOKEN = re.compile(r'<[0-9A-F]{4}>|[^<]')
PUNCT = frozenset(' \t\r\n\u3000＞＜>"\'「」『』.,。．!！:：、，?？')


def frame(text, name, *, insensitive=False):
    """Normalize only presentation punctuation; retain all semantic ink."""
    match = re.search(re.escape(name), text, re.I if insensitive else 0)
    if not match or re.search(re.escape(name), text[match.end():], re.I if insensitive else 0):
        return None
    text = text[:match.start()] + '{item}' + text[match.end():]
    text = unicodedata.normalize('NFKC', text)
    if any(not (c.isalnum() or c in PUNCT or c in '{}') for c in text):
        return None
    return ''.join(c.casefold() for c in text if c.isalnum() or c in '{}')


def story_frames(pairs):
    """Frames learned exclusively from complete independently paired records."""
    out = set()
    for jp, us in pairs:
        a, b = HIGHLIGHT.fullmatch(jp), HIGHLIGHT.fullmatch(us)
        if not a or not b:
            continue
        af = frame(a.group(1) + a.group(2) + a.group(3), a.group(2))
        bf = frame(b.group(1) + b.group(2) + b.group(3), b.group(2))
        if af and bf:
            out.add((af, bf))
    return out


def complete(text):
    """Plain candidate: no parameters, embedded controls, pages, or waits."""
    if not text.endswith('<FF02><FF01>'):
        return None
    body = text[:-len('<FF02><FF01>')]
    return body if '<' not in body and '>' not in body else None


def overlaps(target, rows):
    """Reject nested scan records whose preceding complete text covers target."""
    for row in rows:
        start = int(row['pos'], 16)
        if start >= target:
            break
        text = row['text']
        # EBOOT uses two bytes per glyph/control. End at the first actual end;
        # ignore any continuation the extractor happened to attach after it.
        if '<FF01>' in text:
            text = text[:text.index('<FF01>') + len('<FF01>')]
        tokens = TOKEN.findall(text)
        # Malformed markup cannot be priced exactly. Its raw character length
        # is an upper bound on encoded units, so retain a conservative overlap.
        units = (sum(1 if t.startswith('<') else len(t.encode('utf-16-be')) // 2
                     for t in tokens)
                 if ''.join(tokens) == text else len(text.encode('utf-16-be')) // 2)
        if start + 2 * units > target:
            return True
    return False


def candidates(messages, names, jp_rows, us_rows, anchors, templates):
    """Yield (PSX position, Japanese, US record) after every proof gate."""
    if not templates:
        return []
    jp_by_text = collections.defaultdict(list)
    jp_rows = sorted(jp_rows, key=lambda r: int(r['pos'], 16))
    for row in jp_rows:
        # Count duplicates even when one carries a semantic control; excluding
        # it before the uniqueness test could make an ambiguous row look safe.
        key = _ink(CONTROL.sub('', row['text']))
        if key is not None:
            jp_by_text[key].append(row)
    us_rows = sorted(us_rows, key=lambda r: int(r['pos'], 16))
    anchors = sorted(anchors)
    jc = collections.Counter(a for a, _ in anchors)
    uc = collections.Counter(b for _, b in anchors)
    aj = [a for a, _ in anchors]
    by_ja = collections.defaultdict(list)
    by_en = collections.defaultdict(list)
    for japanese, english in names:
        if japanese and english:
            by_ja[japanese].append(english)
            by_en[english.casefold()].append(japanese)
    out = []
    for pos, japanese in messages:
        matching = [n for n in by_ja if japanese.startswith(n) and len(japanese) > len(n)]
        if len(matching) != 1:
            continue
        item = matching[0]
        if len(by_ja[item]) != 1:
            continue
        english = by_ja[item][0]
        if len(by_en[english.casefold()]) != 1:
            continue
        key = _ink(japanese)
        jp = jp_by_text.get(key, []) if key is not None else []
        if len(jp) != 1 or complete(jp[0]['text']) is None:
            continue
        point = int(jp[0]['pos'], 16)
        if overlaps(point, jp_rows):
            continue
        index = bisect.bisect_left(aj, point)
        if not 0 < index < len(anchors):
            continue
        (j0, u0), (j1, u1) = anchors[index - 1:index + 1]
        if not (j0 < point < j1 and u0 < u1 and jc[j0] == jc[j1] == uc[u0] == uc[u1] == 1):
            continue
        whole = re.compile(r'(?<!\w)' + re.escape(english) + r'(?!\w)', re.I)
        matching_us = []
        for row in us_rows:
            address = int(row['pos'], 16)
            if not u0 < address < u1:
                continue
            if whole.search(row['text']):
                matching_us.append(row)
        if len(matching_us) != 1:
            continue
        us = matching_us[0]
        body = complete(us['text'])
        if body is None or len(whole.findall(body)) != 1:
            continue
        if overlaps(int(us['pos'], 16), us_rows):
            continue
        pair = (frame(japanese, item), frame(body, english, insensitive=True))
        if None not in pair and pair in templates:
            out.append((pos, japanese, us, item, (j0, j1, u0, u1), pair))
    peers = collections.defaultdict(set)
    for _pos, _ja, _us, item, interval, pair in out:
        peers[(interval, pair)].add(item)
    return [(pos, japanese, us) for pos, japanese, us, item, interval, pair in out
            if len(peers[(interval, pair)]) >= 2]


def _ink(text):
    text = unicodedata.normalize('NFKC', text)
    if any(not (c.isalnum() or c in PUNCT) for c in text):
        return None
    return ''.join(c.casefold() for c in text if c.isalnum())


def source_pairs():
    """Story pack pairs whose shared entry/box coordinate is a bijection."""
    root = Path(toolbelt.ROOT) / 'data/extracted_text/psp_jp/pack'
    for path in sorted(root.glob('*.tsv')):
        rel = 'pack/' + path.stem
        if not match_jp.coordinate_join(rel):
            continue
        for row in toolbelt.read_extracted('psp_jp', rel):
            if not HIGHLIGHT.fullmatch(row['text']):
                continue
            us = match_jp.us_twin(rel, row)
            if us:
                yield row['text'], us['text']


def begin_capture():
    global _capture
    _capture = []


def capturing():
    return _capture is not None


def replaying():
    return bool(os.environ.get(REPLAY_ENV))


def _digest(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def _pack_digest(region):
    h = hashlib.sha1()
    for path in sorted((Path(toolbelt.ROOT) / 'data/extracted_text' / region / 'pack').glob('*.tsv')):
        h.update(path.name.encode('utf-8') + b'\0')
        h.update(path.read_bytes())
    return h.hexdigest()


def _name_digest():
    """Digest exactly the item-name evidence `_derive_live` reads.

    The rest of SLPS_005.00 (dialogue, descriptions, other surfaces) does not
    feed a notice decision, and generated/ is rebuilt before this plan runs.
    Hashing the whole generated table made an unrelated row change invalidate
    the plan even though every consumed name was identical."""
    gen = {r['pos']: r for r in toolbelt.read_generated('SLPS_005.00')}
    h = hashlib.sha1()
    for offset, _ja, _psp in items.records():
        row = gen.get(hex(offset), {})
        for field in ('en', 'psp'):
            h.update((row.get(field) or '').encode('utf-8') + b'\0')
    return h.hexdigest()


def inputs():
    root = Path(toolbelt.ROOT)
    return {
        'psx:BTLP': _digest(root / 'data/psx/BTLP.BIN'),
        'psx:SLPS': _digest(root / 'data/psx/SLPS_005.00'),
        'names:SLPS': _name_digest(),
        'us:EBOOT': _digest(root / 'data/extracted_text/psp_us/EBOOT.tsv'),
        'us:pack': _pack_digest('psp_us'),
    }


def rule_digest():
    h = hashlib.sha1()
    here = Path(__file__).resolve().parent
    for path in (here / 'reward_notice.py', here / 'match_jp.py',
                 ROOT / 'src/injection_tools/items.py',
                 Path(toolbelt.MAPPINGS) / 'psp_pairs.tsv',
                 here / 'psp_pairs_extra.tsv', here / 'psx_jp_extra.tsv'):
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
        raise PlanError('reward-notice plan version mismatch; recapture with PSP-JP')
    for name, value in inputs().items():
        if plan.get(name) != value:
            raise PlanError(f'reward-notice plan does not match {name}; recapture')
    if plan.get('rule_sha1') != rule_digest():
        raise PlanError('reward-notice plan does not match the matching rules; recapture')
    _loaded, _loaded_path = {'matches': matches}, path
    return _loaded


def _replay():
    plan = load()
    us = dict(toolbelt.read_eboot('psp_us'))
    data = btlmsg.data()
    ja_by_pos = {hex(start - btlmsg.B): btlmsg.dec(data, start, end)
                 for start, end in btlmsg.messages(data)}
    out = []
    for row in plan['matches']:
        pos = row['pos']
        if pos not in ja_by_pos:
            raise PlanError(f'reward-notice plan has a stale PSX position {pos}; recapture')
        offset = int(row['us_pos'], 16)
        if offset not in us:
            raise PlanError(f'reward-notice plan has a stale US source {offset:#x}; recapture')
        out.append((pos, ja_by_pos[pos], {'pos': hex(offset), 'text': us[offset]}))
    return out


def write(path=PLAN):
    global _capture, _loaded, _loaded_path
    if _capture is None:
        raise RuntimeError('write without begin_capture')
    matches = _capture
    metadata = {'version': VERSION, 'rule_sha1': rule_digest()}
    metadata.update(inputs())
    source_plan.write(path, metadata, matches)
    _capture, _loaded, _loaded_path = None, None, None
    print(f'reward-notice plan: {len(matches)} decisions -> {path}')


def derive():
    """Read source tables and return only structurally corroborated candidates.

    A captured plan replays the chosen PSP-US record for each PSX position;
    without one (or during capture) the Japanese PSP side is read."""
    if replaying():
        return _replay()
    rows = _derive_live()
    if _capture is not None:
        for pos, _ja, source in rows:
            _capture.append({'rel': 'BTLP', 'pos': pos, 'mode': 'reward',
                             'us_sub': 'boot',
                             'us_pos': format(int(source['pos'], 16), 'x')})
    return rows


def _derive_live():
    gen = {r['pos']: r for r in toolbelt.read_generated('SLPS_005.00')}
    names = []
    for offset, ja, _ in items.records():
        row = gen.get(hex(offset), {})
        english, locator = row.get('en', '').strip(), row.get('psp', '')
        if not english or not locator.startswith('EBOOT:'):
            continue
        source = match_jp._us_row_at('EBOOT', locator.split(':', 1)[1])
        if source and source['text'].casefold().endswith(english.casefold()):
            names.append((ja, english))
    data = btlmsg.data()
    messages = [(hex(start - btlmsg.B), btlmsg.dec(data, start, end))
                for start, end in btlmsg.messages(data)]
    anchors, _jp_order, _us_order = match_jp._between('EBOOT')
    return candidates(messages, names,
        toolbelt.read_extracted('psp_jp', 'EBOOT'),
        toolbelt.read_extracted('psp_us', 'EBOOT'), anchors,
        story_frames(source_pairs()))


def capture():
    """Capture the selected PSP-US record for every corroborated notice."""
    sys.modules.setdefault('reward_notice', sys.modules[__name__])
    import boot_btlmsg
    begin_capture()
    boot_btlmsg.main()
    write()


if __name__ == '__main__':
    if '--without-psp-jp' in sys.argv:
        os.environ[REPLAY_ENV] = str(PLAN)
    else:
        capture()
