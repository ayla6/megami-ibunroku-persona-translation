"""Port BTLNEG gaps from the PSP BOOT contact cluster.

Mapping lives in src/extraction_tools/matching/btlneg_map.tsv (PSX idx, BOOT addresses,
Japanese skeleton keys); English is read at runtime from
data/extracted_text/psp_us/boot_be.tsv. This file is logic only.

  python src/extraction_tools/matching/port_btlneg.py        # report only
  python src/extraction_tools/matching/port_btlneg.py --apply  # write generated

Human-only (PSX-only/rewrite/garbage/debug): 38, 40, 114, 118, 184, 188,
195, 210-212, 217, 234-236, 279, 287, 295-297, 299, 301, 302-352, 145, 167
(packed-blob rows, not dialogue).
"""
import csv
import os
import re
import sys

# Deterministic output: set/dict iteration order otherwise leaks the
# per-process hash seed into row content. Same seed as build.py.
# Seed re-exec ONLY as a script: an import must never hijack the host
# process.
if __name__ == '__main__' and os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'injection_tools'))
import toolbelt  # noqa: E402
import port_derive  # noqa: E402
import btlmsg      # noqa: E402
import etext      # noqa: E402
import strlib     # noqa: E402
import vwf_wrap   # noqa: E402
import notice_consumer  # noqa: E402
import control_consumer  # noqa: E402
import eboot_twin_plan  # noqa: E402
from btlneg import ZONE, strings, width, PACK_IDX, BUF  # noqa: E402

ROOT = etext.ROOT
BOOT = os.path.join(ROOT, 'data', 'cache', 'boot_be.tsv')
MAP = os.path.join(toolbelt.SOURCE_MAPPINGS, 'btlneg_map.tsv')
MAN = os.path.join(ROOT, 'translation', 'manual', 'strings', 'BTLNEG.tsv')
GEN = os.path.join(ROOT, 'translation', 'generated', 'BTLP.BIN', 'BTLNEG.tsv')
BOX_W = vwf_wrap.BOX_WIDTH


def load_boot():
    """(offset, kind, text) of every EBOOT text record: the be_runs view
    (toolbelt.read_be), whose offsets are the ones btlneg_map.tsv names."""
    import toolbelt
    return [(p, '', t) for p, t in toolbelt.read_be()]


def load_map():
    rows = list(csv.DictReader(open(MAP, encoding='utf-8'), delimiter='\t'))
    auto, blob, rev, ex = [], [], [], {}
    for r in rows:
        kind = r['kind']
        keys = [k for k in r['keys'].split(';') if k]
        if kind == 'auto':
            # A PREFIX THAT IS ONLY THE HEAD MARK IS NOT WORDING. The PSP opens
            # these lines with its '＞' head, which the unit itself already
            # carries, and port_derive.head_marks decides whether it survives (the
            # PSX row's own Japanese is the judge). Adding a second one from the
            # map made the row read '>＞ ...' - the map spells the mark ASCII,
            # which is the INJECTION's spelling, so it never matched the '＞'
            # the rule removes.
            pre = ('' if set(r['prefix'].strip()) <= {'>', '＞', '<', '＜'}
                   else r['prefix'])
            auto.append((int(r['idx']),
                         [int(x, 16) for x in r['src'].split(',')],
                         keys, pre, r['tone'] == '1'))
        elif kind == 'blob':
            addr, item = r['src'].split(':')
            blob.append((int(r['idx']), int(addr, 16), int(item), keys))
        elif kind == 'revrange':
            lo, hi = r['src'].split('-')
            rev.append((int(lo, 16), int(hi, 16), int(r['idx']), keys))
        elif kind == 'exseg':
            # The source span remains useful; legacy per-word segmentation
            # and injected control suffixes are not a source of script text.
            ex.setdefault(int(r['idx']), {'src': r['src'], 'keys': keys})
    for v in ex.values():
        v['src'] = [int(x, 16) for x in v['src'].split(',')]
    return auto, blob, rev, ex


def box_text(boot, addr, first=True):
    amap = {a: (k, t) for a, k, t in boot}
    if addr not in amap:
        return ''          # no text unit at this offset: row stays a gap
    k, t = amap[addr]
    t = t or k.strip()
    if first:
        t = re.sub(r'^[ \u2026]+', '', t)
    return t


def speaker_of(boot, addrs):
    """(speaker, [box texts]) - the PSP nameplate read as STRUCTURE, the
    same rule every dialogue family uses (port_derive.label_head): the
    first box's label is the row's speaker, and a repeat at a continuation
    box is that nameplate echoed (TEXT_LAYOUT_SPEC §4.4) and is dropped
    there. The label is never left in the body and never dropped either (§4.1)."""
    speaker = ''
    texts = []
    for i, a in enumerate(addrs):
        t = box_text(boot, a, first=(i == 0))
        lab, rest = port_derive.label_head(t, bare=True)
        if lab:
            if not speaker:
                speaker = lab
            if lab == speaker:
                t = rest
        texts.append(t)
    return speaker, texts


def source_message(boot, addrs, raw=None):
    speaker, texts = speaker_of(boot, addrs)
    if not texts or any(not text.strip() for text in texts):
        raise ValueError('missing or empty PSP source in negotiation span')
    # EBOOT spans can split a sentence around an independently stored word.
    # Their boundaries are not page turns: preserve the source bytes and
    # its authored controls rather than inserting a wait at every fragment.
    body = ''
    for i, text in enumerate(texts):
        if i and raw is not None:
            start, end = addrs[i - 1], addrs[i]
            if end <= start:
                raise ValueError('negotiation source span is not in source order')
            if any(raw[at:at + 2] == b'\xff\x01'
                   for at in range(start, end - 1, 2)) and not body.endswith('<FF01>'):
                body += '<FF01>'
        # A new line's head marker is not part of the preceding fragment's
        # word, even if the source stored neither surrounding space.
        if body and not body[-1].isspace() and text.startswith(('＞', '>')):
            body += ' '
        body += text
    body = re.sub(r'<FF01>\s*$', '', body)
    return speaker, body


def label_prefix(speaker):
    """The destination's label spelling: these boxes print the speaker
    INLINE (their PSX Japanese carries 'name：', no FF1B), so the English
    carries 'Name: ' - a code the row does not have would fail the
    builder's code check."""
    return speaker + ': ' if speaker else ''


# how many messages a row holds: port_derive's rule, its one home (the
# derivation refuses a composition whose count differs from the Japanese's)
_messages = port_derive.messages


def sequential_source(idx, ja, srcs, raw):
    """Align independently terminated source messages to sequential PSX text.

    Exact JP/US twins establish any known pairing; if precisely one target and
    one source remain, the one-to-one correspondence establishes the other.
    Ambiguous or missing sources remain a gap, never a merged message.
    """
    parts = re.split(r'<FFEF>', ja)
    starts = [srcs[0]] if srcs else []
    for left, right in zip(srcs, srcs[1:]):
        if any(raw[at:at + 2] == b'\xff\x01' for at in range(left, right - 1, 2)):
            starts.append(right)
    if len(parts) != len(starts) or len(parts) < 2 or any(not p.strip() for p in parts):
        raise ValueError('multiple PSP messages require destination alignment')
    units = dict(toolbelt.read_eboot('psp_us'))
    if len(set(starts)) != len(starts) or any(not units.get(pos, '').strip() for pos in starts):
        raise ValueError('multiple PSP messages lack complete extracted source units')
    keys = [(f'{idx}:{i}', part) for i, part in enumerate(parts)]
    proved = eboot_twin_plan.exact_us('btlneg-sequential', keys)
    selected = {}
    for i, (key, _) in enumerate(keys):
        offset = proved.get(key)
        if offset in starts:
            selected[i] = offset
    if len(set(selected.values())) != len(selected):
        raise ValueError('multiple PSP messages have conflicting source matches')
    missing = [i for i in range(len(parts)) if i not in selected]
    remaining = [offset for offset in starts if offset not in selected.values()]
    if len(missing) == len(remaining) == 1 and selected:
        selected[missing[0]] = remaining[0]
    if len(selected) != len(parts):
        raise ValueError('multiple PSP messages require destination alignment')
    output = []
    for i, part in enumerate(parts):
        text, why = port_derive.derive(units[selected[i]], part, 'BTLP', '')
        if why:
            raise ValueError(why)
        output.append(text)
    return '<FFEF>'.join(output)


def emit(idx, en, src, man, ok, fail, srcs=(), raw_boot=None):
    if not (en or '').strip():
        fail.append((idx, 'no boot text', '', tuple(srcs)))
        return
    # One packed string cannot contain two independently terminated PSP
    # messages. Never let layout silently drop the first terminator and
    # combine their wording; their destination order needs separate proof.
    ja = man[str(idx)][2]
    # THE derivation, on the first pass (port_derive): the codes in the
    # battle family's spelling, the box's own layout and label rule, the
    # destination's own cap (the neg buffer) and the approved name/choice
    # deviations. No special cases here - what cannot ship is a draft with
    # the reason, never a bespoke gate.
    if re.search(r'<FF01>\s*\S', en):
        try:
            if raw_boot is None:
                raise ValueError('multiple PSP messages require destination alignment')
            laid, why = sequential_source(idx, ja, srcs, raw_boot), ''
        except ValueError as error:
            fail.append((idx, str(error), en, tuple(srcs)))
            return
    else:
        laid, why = port_derive.derive(en, ja, 'BTLP', '')
    if why:
        fail.append((idx, why, laid, tuple(srcs)))
        return
    try:
        b = etext.encode(laid, end=None) + b'\xff\xf5'
    except ValueError:
        fail.append((idx, 'encode', laid, tuple(srcs)))
        return
    ok.append((idx, laid, src, tuple(srcs)))


def route_failures(fail, ok, msgs, manual_en):
    """Queue each unsuccessful candidate once with its full PSP draft."""
    succeeded = {i for i, _en, _note, _srcs in ok}
    routed = 0
    seen = set()
    for i, reason, draft, srcs in fail:
        pos = hex(msgs[i][0] - btlmsg.B)
        if i in succeeded or pos in manual_en or i in seen:
            continue
        seen.add(i)
        psp = ','.join(f'EBOOT:{a:x}' for a in srcs)
        toolbelt.route_over('BTLP', pos, psp, draft, reason)
        routed += 1
    return routed


def port(apply, force=False):
    # btlmsg.ZONE is a module global other readers share: swap it for this
    # porter's bank, then put it back even when a gate aborts the pass.
    previous = btlmsg.ZONE
    btlmsg.ZONE = ZONE
    try:
        return _port(apply, force)
    finally:
        btlmsg.ZONE = previous


def _port(apply, force=False):
    boot = load_boot()
    from tables import us_boot
    raw_boot = us_boot()
    auto, blob, rev, ex = load_map()
    import toolbelt
    d = btlmsg.data()
    rf = btlmsg.refs(d)
    msgs = strings(d, rf)
    ja = {i: btlmsg.dec(d, a, q) for i, (a, q) in enumerate(msgs)}
    merged = {r['pos']: r for r in toolbelt.merged_rows('BTLP')}
    man, gen = {}, {}
    for i, (a, q) in enumerate(msgs):
        r = merged.get(hex(a - btlmsg.B))
        en = (r['en'] if r else '').strip()
        man[str(i)] = [str(i), f'{a:08X}', ja[i], en, r.get('note', '') if r else '']
        if en:
            gen[str(i)] = man[str(i)]
    blobs = {}
    for _, ba, ii, _ in blob:
        if ba in blobs:
            continue
        for a, k, t in boot:
            if a == ba:
                blobs[ba] = [s.strip() for s in t.split('<FFF5>')
                             if s.strip()]
    amap = {a: (k, t) for a, k, t in boot}
    ok, fail, skip = [], [], []
    src_of = {}                    # idx -> its PSP source offsets (provenance)

    manual_en = {r['pos'] for r in toolbelt.read_manual('BTLP', optional=True)
                 if (r.get('en') or '').strip()}

    def filled(sidx):
        # Generated rows are derived data, not an obstacle to re-porting.
        # Only the user's manual wording takes precedence.
        return hex(msgs[int(sidx)][0] - btlmsg.B) in manual_en

    for idx, addrs, keys, pre, tone in auto:
        sidx = str(idx)
        src_of[idx] = tuple(addrs)
        if filled(sidx):
            skip.append(idx)
            continue
        if not all(k in man[sidx][2] for k in keys):
            fail.append((idx, 'source mapping does not match destination', '', tuple(addrs)))
            continue
        speaker, body = source_message(boot, addrs, raw_boot)
        # Keep source controls with their source words. The shared derivation
        # translates their interpreter spelling and owns width-based layout.
        src = 'psp-boot %s%s' % (
            ','.join('0x%x' % a for a in addrs), ' (tone-match)' if tone else '')
        emit(idx, label_prefix(speaker) + pre + body, src,
             man, ok, fail, srcs=addrs, raw_boot=raw_boot)

    for idx, ba, ii, keys in blob:
        sidx = str(idx)
        src_of[idx] = (ba,)
        if filled(sidx):
            skip.append(idx)
            continue
        if not all(k in man[sidx][2] for k in keys):
            fail.append((idx, 'source mapping does not match destination', '', (ba,)))
            continue
        emit(idx, blobs[ba][ii], 'psp-boot blob 0x%x item %d' % (ba, ii),
             man, ok, fail, srcs=(ba,))

    for lo, hi, first, keys in rev:
        rng = sorted(a for a, _, _ in boot if lo <= a <= hi)
        # boot's last row (Night) maps to EXTRA 359, handled below
        assert len(rng) == len(keys) + 1, (hex(lo), len(rng), len(keys))
        for k, a in enumerate(rng[:len(keys)]):
            idx = first + (len(keys) - 1 - k)
            sidx = str(idx)
            src_of[idx] = (a,)
            if filled(sidx):
                skip.append(idx)
                continue
            if keys[len(keys) - 1 - k] not in man[sidx][2]:
                fail.append((idx, 'source mapping does not match destination', '', (a,)))
                continue
            kk, t = amap[a]
            lab, body = port_derive.label_head((t or kk.strip()).strip(),
                                               bare=True)
            emit(idx, label_prefix(lab) + body.strip().replace('<FF01>', ''),
                 'psp-boot 0x%x' % a, man, ok, fail, srcs=(a,))
    if not filled('359') and '夜魔' in man['359'][2]:
        for a, k, t in boot:
            if a == 0x2a8fa2:
                emit(359, (t or k).strip().replace('<FF01>', ''),
                     'psp-boot 0x2a8fa2 (dup of 145)', man, ok, fail, srcs=(0x2a8fa2,))
                break
    ref198 = [(e, s) for i, e, n, s in ok if i == 198]
    if ref198 and not filled('298') and all(
            k in man['298'][2] for k in ['一目で分かっちゃった', '迫力が違う']):
        emit(298, ref198[0][0], 'psp-boot (same as 198)', man, ok, fail,
             srcs=ref198[0][1])

    for idx, spec in ex.items():
        sidx = str(idx)
        addrs = spec['src']
        src_of[idx] = tuple(addrs)
        pos = hex(msgs[idx][0] - btlmsg.B)
        # Mapped source spans are derived on every pass, not treated as
        # human-owned just because generated text already exists.
        if pos in manual_en:
            skip.append(idx)
            continue
        if not all(k in man[sidx][2] for k in spec['keys']):
            raise ValueError(f'BTLNEG {idx}: source mapping does not match destination')
        if any(addr not in amap or not (amap[addr][1] or '').strip() for addr in addrs):
            raise ValueError(f'BTLNEG {idx}: missing or ambiguous PSP source')
        speaker, body = source_message(boot, addrs, raw_boot)
        before = len(fail)
        emit(idx, label_prefix(speaker) + body,
             'psp-boot source-span', man, ok, fail, srcs=addrs, raw_boot=raw_boot)
        if len(fail) != before and fail[-1][1] != 'multiple PSP messages require destination alignment':
            raise ValueError(f'BTLNEG {idx}: mapped source cannot be ported: {fail[-1][1]}')

    # The source proof reads immutable PSP executables/canonical extracts and
    # shares this porter's existing emit/upsert; it never rewrites a row later.
    # Existing mapped slots and human wording retain their ownership, including
    # during a forced refresh.
    claimed = {i for i, _en, _src, _srcs in ok} | set(src_of)
    if eboot_twin_plan.replaying():
        consumer_proofs = (eboot_twin_plan.consumer_us('notice', list(ja.items()))
                           + eboot_twin_plan.consumer_us('control', list(ja.items())))
    else:
        notice_proofs = notice_consumer.derive(list(ja.items()))
        control_proofs = control_consumer.derive(list(ja.items()))
        eboot_twin_plan.record_consumer('notice', notice_proofs)
        eboot_twin_plan.record_consumer('control', control_proofs)
        consumer_proofs = notice_proofs + control_proofs
    for idx, source_row in consumer_proofs:
        pos = hex(msgs[idx][0] - btlmsg.B)
        if idx in claimed or filled(str(idx)) or pos in manual_en:
            continue
        source = int(source_row['pos'], 16)
        before = len(ok)
        emit(idx, source_row['text'], 'psp-boot executable consumer',
             man, ok, fail, srcs=(source,))
        if len(ok) != before:
            src_of[idx] = (source,)
            claimed.add(idx)

    # THE SAME LINE IN THE PSP: a zone string no pass above claims, whose
    # Japanese is exactly one PSP-JP row (match_jp.exact_twins - repeated
    # lines pair by occurrence when both builds hold the same number of
    # copies), takes that row's PROVEN US twin (match_jp.us_twin, never an
    # 'align' guess). Last, so every owner above keeps its slots.
    open_idx = [i for i in range(len(msgs))
                if i not in claimed and not filled(str(i))
                and hex(msgs[i][0] - btlmsg.B) not in manual_en]
    offsets = eboot_twin_plan.exact_us('btlneg', [(i, ja[i]) for i in open_idx])
    for idx in open_idx:
        source = offsets.get(idx)
        if source is None:
            continue
        before = len(ok)
        emit(idx, eboot_twin_plan.us_text(source),
             'psp twin (exact Japanese)', man, ok, fail, srcs=(source,))
        if len(ok) != before:
            src_of[idx] = (source,)
            claimed.add(idx)

    print('ported %d, failed %d, skipped-filled %d'
          % (len(ok), len(fail), len(skip)))
    for f in fail:
        print('FAIL', f[0], f[1], repr(f[2])[:110])
    stale = [idx for idx, reason, *_ in fail if str(idx) in gen
             and reason != 'multiple PSP messages require destination alignment']
    if stale:
        raise ValueError('BTLNEG: generated rows could not be rederived: '
                         + ', '.join(map(str, sorted(set(stale)))))
    if apply and (ok or src_of or fail):
        import toolbelt  # noqa: E402
        rows, over = [], 0
        for i, en, note, srcs in ok:
            pos = hex(msgs[i][0] - btlmsg.B)
            psp = ','.join(f'EBOOT:{a:x}' for a in srcs)   # the row's PSP source unit(s)
            if note.startswith('over limit'):
                toolbelt.route_over('BTLP', pos, psp, en, note)   # draft -> note
                over += 1
            else:
                row = {'pos': pos, 'en': en}
                if psp:
                    row['psp'] = psp
                rows.append(row)
        # Route failures with their complete draft and source. A later
        # successful source for the same position wins; human-owned wording
        # is never overwritten or withdrawn by a forced refresh.
        over += route_failures(fail, ok, msgs, manual_en)
        n = toolbelt.upsert_generated('BTLP', rows)
        # provenance-only refresh: an already-filled row that carries no psp
        # pointer yet gets its source (generated rows state where they
        # came from - docs/TEXT_ARCHITECTURE.md)
        have = {r['pos']: r for r in toolbelt.read_generated('BTLP', optional=True)}
        fix = []
        for idx, srcs in src_of.items():
            pos = hex(msgs[idx][0] - btlmsg.B)
            cur = have.get(pos)
            if (cur is not None and (cur.get('en') or '').strip()
                    and not (cur.get('psp') or '').strip()):
                fix.append({'pos': pos, 'en': cur['en'],
                            'psp': ','.join(f'EBOOT:{a:x}' for a in srcs)})
        if fix:
            toolbelt.upsert_generated('BTLP', fix)
        print(f'port_btlneg: wrote {n} rows, {over} over limit -> manual, '
              f'{len(fix)} provenance pointer(s) filled')


if __name__ == '__main__':
    if '--without-psp-jp' in sys.argv:
        os.environ[eboot_twin_plan.REPLAY_ENV] = str(eboot_twin_plan.PLAN)
    port('--apply' in sys.argv[1:], '--force' in sys.argv[1:])
