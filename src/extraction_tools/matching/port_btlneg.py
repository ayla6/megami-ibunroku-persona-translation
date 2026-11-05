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
BREAK_RX = r'(?:<FF02>|<FF03>|<FF04>)+'


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
            ex.setdefault(int(r['idx']), {'src': r['src'], 'keys': keys,
                                          'strip': r['strip'] == '1',
                                          'segs': []})
            parts, words = [], []
            for p, w in zip(r['parts'].split(','), r['words'].split(',')):
                parts.append(int(p))
                if w == '-':
                    words.append((None, None))
                else:
                    a, b = w.split('-')
                    words.append((int(a) if a else None,
                                  int(b) if b else None))
            ex[int(r['idx'])]['segs'].append(
                (parts, words, r['pre'], r['post']))
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


def split_parts(t):
    t = t.replace('<FF01>', '<FF03>')
    return [p for p in
            (x.strip().replace(' ,', ',').replace('  ', ' ')
             for x in re.split(BREAK_RX, t)) if p]


def concat_parts(boot, addrs):
    speaker, texts = speaker_of(boot, addrs)
    return speaker, split_parts(''.join(texts))


def label_prefix(speaker):
    """The destination's label spelling: these boxes print the speaker
    INLINE (their PSX Japanese carries 'name：', no FF1B), so the English
    carries 'Name: ' - a code the row does not have would fail the
    builder's code check."""
    return speaker + ': ' if speaker else ''


def ja_codes(ja):
    return sorted(re.findall(r'<FF[0-9A-F]{2}>', ja))


def en_codes(en):
    return sorted('<FF%02X>' % c for c in
                  btlmsg.codes(etext.encode(en, end=None)))


def assemble(parts, need_f6):
    """The PSP parts into the JA skeleton's need_f6+1 lines. The count is the
    skeleton's (its control codes must match it, so it is not ours to choose);
    the break points are the flow engine's - vwf_wrap.fill_lines, the same one
    every textbox uses, so a line comes out as square as the words allow and
    nothing anywhere else decides a break."""
    return vwf_wrap.fill_lines(' '.join(parts).split(' '), need_f6 + 1,
                               BOX_W, width)


def balance_marks(segs, want):
    """Append JA's FFFB/FFF7 expressive marks BOOT lacks (to the last
    segment; humans reposition while shortening the draft). `want` is the
    JA code list."""
    need_b = want.count('<FFFB>')
    need_7 = want.count('<FFF7>')
    have_b = sum(s.count('<FFFB>') for s in segs)
    have_7 = sum(s.count('<FFF7>') for s in segs)
    while have_b < need_b and have_7 < need_7:
        segs[-1] = segs[-1] + '<FFFB><FFF7>'
        have_b += 1
        have_7 += 1
    while have_b < need_b:
        segs[-1] = segs[-1] + '<FFFB>'
        have_b += 1
    while have_7 < need_7:
        segs[-1] = segs[-1] + '<FFF7>'
        have_7 += 1
    return segs


def balance_fffc(segs, need):
    have = sum(s.count('<FFFC>') for s in segs)
    for i in range(len(segs)):
        if have >= need:
            break
        segs[i] = segs[i] + '<FFFC>'
        have += 1
    if have > need:
        out = []
        for s in segs:
            while have > need and '<FFFC>' in s:
                s = s.replace('<FFFC>', '', 1)
                have -= 1
            out.append(s)
        segs = out
    return segs


# how many messages a row holds: port_derive's rule, its one home (the
# derivation refuses a composition whose count differs from the Japanese's)
_messages = port_derive.messages


def emit(idx, en, src, man, ok, fail, srcs=()):
    if not (en or '').strip():
        fail.append((idx, 'no boot text', ''))   # gap: manual queue holds it
        return
    ja = man[str(idx)][2]
    # THE derivation, on the first pass (port_derive): the codes in the
    # battle family's spelling, the box's own layout and label rule, the
    # destination's own cap (the neg buffer) and the approved name/choice
    # deviations. No special cases here - what cannot ship is a draft with
    # the reason, never a bespoke gate.
    laid, why = port_derive.derive(en, ja, 'BTLP', '')
    if why:
        fail.append((idx, why, laid[:100]))
        return
    try:
        b = etext.encode(laid, end=None) + b'\xff\xf5'
    except ValueError:
        fail.append((idx, 'encode', laid[:80]))
        return
    ok.append((idx, laid, src, tuple(srcs)))


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

    def filled(sidx):
        # --force re-derives even filled rows (generated is ephemeral; a
        # human's manual row is untouched and still wins at build time)
        return not force and sidx in gen and gen[sidx][3].strip()

    for idx, addrs, keys, pre, tone in auto:
        sidx = str(idx)
        src_of[idx] = tuple(addrs)
        if filled(sidx):
            skip.append(idx)
            continue
        if not all(k in man[sidx][2] for k in keys):
            fail.append((idx, 'ja-keys', man[sidx][2][:60]))
            continue
        speaker, parts = concat_parts(boot, addrs)
        segs = assemble(parts, ja_codes(man[sidx][2]).count('<FFF6>'))
        segs = balance_fffc(segs, ja_codes(man[sidx][2]).count('<FFFC>'))
        segs = balance_marks(segs, ja_codes(man[sidx][2]))
        src = 'psp-boot %s%s' % (
            ','.join('0x%x' % a for a in addrs), ' (tone-match)' if tone else '')
        emit(idx, label_prefix(speaker) + pre + '<FFF6>'.join(segs), src,
             man, ok, fail, srcs=addrs)

    for idx, ba, ii, keys in blob:
        sidx = str(idx)
        src_of[idx] = (ba,)
        if filled(sidx):
            skip.append(idx)
            continue
        if not all(k in man[sidx][2] for k in keys):
            fail.append((idx, 'ja-keys', man[sidx][2][:60]))
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
                fail.append((idx, 'ja-keys', man[sidx][2][:60]))
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
        src_of[idx] = tuple(spec['src'])
        if filled(sidx):
            skip.append(idx)
            continue
        if not all(k in man[sidx][2] for k in spec['keys']):
            fail.append((idx, 'ja-keys', man[sidx][2][:60]))
            continue
        speaker, texts = speaker_of(boot, spec['src'])
        text = ''.join(texts)
        if spec['strip']:
            text = text.replace('<FFFC>', '')
        parts = split_parts(text)
        segs = []
        for chunk_ps, chunk_ws, pre, post in spec['segs']:
            words = []
            for pi, (w0, w1) in zip(chunk_ps, chunk_ws):
                if pi >= len(parts):
                    words.append('PART-MISSING')
                else:
                    words.extend(parts[pi].split(' ')[w0:w1])
            seg = ' '.join(words)
            if pre and seg.startswith('…'):
                seg = pre + seg.lstrip('… ')
            elif pre:
                seg = pre + seg
            segs.append(seg + post)
        emit(idx, label_prefix(speaker) + '<FFF6>'.join(segs),
             'psp-boot explicit-reassembly', man, ok, fail, srcs=spec['src'])

    # The source proof reads immutable PSP executables/canonical extracts and
    # shares this porter's existing emit/upsert; it never rewrites a row later.
    # Existing mapped slots and human wording retain their ownership, including
    # during a forced refresh.
    manual_en = {r['pos'] for r in toolbelt.read_manual('BTLP', optional=True)
                 if (r.get('en') or '').strip()}
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
    if apply and (ok or src_of):
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
        # A STORED ROW THAT FAILS TODAY'S RULE IS WITHDRAWN, not left to
        # ship: generated is only as right as the last run that wrote it, and
        # a row whose line holds a different number of messages than its own
        # Japanese cannot be shown correctly (emit says why). It leaves
        # generated with the reason and its draft in the manual queue.
        for i in sorted(gen, key=int):
            cur = gen[i][3]
            if _messages(gen[i][2]) == _messages(cur):
                continue
            pos = hex(msgs[int(i)][0] - btlmsg.B)
            toolbelt.route_over('BTLP', pos, '',
                                cur, f'source mismatch: the row holds '
                                f'{_messages(gen[i][2])} message(s), the '
                                f'stored line {_messages(cur)}')
            toolbelt.unport('BTLP', pos)
            print(f'withdrawn {i}: {cur[:70]!r}')
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
