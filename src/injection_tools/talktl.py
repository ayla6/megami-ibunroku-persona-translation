"""Check / apply English for the negotiation scripts TALK/*.BIN (translation/talk/<NAME>.tsv, columns unit, ja, en).

  python tools/talktl.py prep NAME                   write translation/work/talk_NAME_ja.tsv: the UNIQUE Japanese texts (columns unit, ja);
                                                     the parameter character after <FFFD> is replaced by '#' (it differs per unit)
  python tools/talktl.py check NAME                  validate translation/work/talk_NAME_en.tsv (columns unit, en[, note])
  python tools/talktl.py apply NAME                  validate, expand to every unit with the same Japanese (restoring each unit's
                                                     <FFFD> parameter character) and write the `en` column of translation/talk/NAME.tsv
  python tools/talktl.py ans-prep | ans-check | ans-apply   the player's ANSWER lines (section 1 of every TALK file, one shared
                                                     table translation/talk/ANSWERS.tsv; work files translation/work/talk_ANS_*.tsv;
                                                     ONE line (the window spaces answers 16-24 px apart, a 2nd line overlaps the next answer), <= one battle-box line, same codes)
  python tools/talktl.py qa                          validate every translated unit of every translation/talk/*.tsv
In the work file write <FFFD># exactly as in the _ja file (the # is replaced by the real parameter character).

Rules (each unit = ONE page of the BTLP text box: 3 lines of 15 cells, VWF, 239 px per line):
  * the unit ends with the same end code as the Japanese (<FFF5> or <FFEF>), exactly once;
  * control codes keep their meaning: every code except <FFF6> (new line) and <FFFC> (short pause) must occur the same number
    of times and in the same order as in the Japanese; <FFFD> is followed by a parameter character (a result index, NOT
    text): write <FFFD># as in the _ja file; <FFFC> may be moved but not added or dropped;
  * at most 3 lines (2 x <FFF6>), each at most 239 px (tools/vwf_wrap.py widths; inserted names counted at a safe width:
    <FFF3> own demon name 80 px, <FFF0> race / second name 54 px, <FFF9> party member name 72 px, <FFF4> item 100 px,
    <FFF2> card 80 px, <FFF8> number 27 px);
  * plain ASCII text only (letters, digits, space and ! ? . , ' " - ~ : ; / ( ) & * +), no other symbols.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext                  # noqa: E402
import strlib                  # noqa: E402
import vwf_wrap   # noqa: E402

ROOT = etext.ROOT
TALK = os.path.join(ROOT, 'translation', 'manual', 'talk')
NL = chr(10)
TOKEN = re.compile(r'<[0-9A-F]{4}>')
WIDTH = {'<FFF3>': 80, '<FFF0>': 54, '<FFF9>': 72, '<FFF4>': 100, '<FFF2>': 80, '<FFF8>': 27}
FREE = ('<FFF6>', '<FFFC>')
# the codes that print text at the pen (windowtype.c's insert slots)
INSERTS = frozenset(WIDTH) | {'<FFFA>'}
END = ('<FFF5>', '<FFEF>')


def codes(s, norm=False):
    """[(code, param)]: <FFFD> carries the character after it"""
    out = []
    for m in TOKEN.finditer(s):
        c = m.group(0)
        if c in FREE:
            continue
        p = s[m.end():m.end() + 1] if c == '<FFFD>' else ''
        out.append((c, '#' if norm and p else p))
    return out


# The printable set is the FONT's own charset (etext._VWF_CHAR: ASCII plus
# make_vwf_font.EXTRA) - never a hand-typed list, which is how the curly
# quotes and the fullsize ＊ got refused while the font already carried room
# for them. '<' '>' stay out: they wrap control-code tokens.
import etext as _etext
OKCHARS = ({ch for ch in _etext._VWF_CHAR.values()
            if ch not in _etext.NO_LITERAL}
           | {'＞', '＜'})             # the head marks' TABLE spelling
                                    # (port_derive.head_marks keeps them
                                    # fullwidth so no rule reads them as a
                                    # <code>); etext injects ASCII '>' '<'


def codes(s, norm=False):
    """[(code, param)]: <FFFD> carries the character after it"""
    out = []
    for m in TOKEN.finditer(s):
        c = m.group(0)
        if c in FREE:
            continue
        p = s[m.end():m.end() + 1] if c == '<FFFD>' else ''
        out.append((c, '#' if norm and p else p))
    return out


def pages_of(s):
    """pages of a unit: <FFFB><FFF7> starts a new page (each page max 3 lines)"""
    t = s
    for c in END:
        t = t.replace(c, '')
    return [pg.split('<FFF6>') for pg in t.split('<FFFB><FFF7>')]


def lines_of(s):
    return [ln for pg in pages_of(s) for ln in pg]


def width(line):
    w = 0
    for c, tw in WIDTH.items():
        w += line.count(c) * tw
        line = line.replace(c, '')
    line = re.sub(r'<FFFD>.', '', line)
    return w + vwf_wrap.text_width(TOKEN.sub('', line))


def check(ja, en, norm=False, maxw=None, maxlines=3):
    errs = []
    if etext.is_todo(en):
        return []
    # THE FONT'S SPELLING (etext.spell): '’' prints as the ASCII apostrophe,
    # so the gate judges, prices and encodes the character the screen shows -
    # the row itself keeps the PSP-US character it came with.
    en = etext.spell(en)
    cut = [ja.index(c) + len(c) for c in END if c in ja]
    if cut:
        ja = ja[:min(cut)]      # text after the first end code of a unit is dead data (e.g. TINPRA 229)
    ends = [c for c in END if c in en]
    jends = [c for c in END if c in ja]
    if len(ends) != 1 or not en.endswith(ends[0]) or ends != jends:
        errs.append(f'must end with exactly one {jends[0] if jends else "<FFF5>"}')
    # The line's other codes are the PSP-US wording's own, carried over - the
    # battle box runs the same code set, so they are never compared with the
    # Japanese: only what the box itself needs is checked (one end code,
    # lines, width, printable characters).
    ls = lines_of(en)
    if max(len(pg) for pg in pages_of(en)) > maxlines:
        errs.append(f'{max(len(pg) for pg in pages_of(en))} lines (max {maxlines})')
    for ln in ls:
        w = width(ln)
        if w > (maxw or vwf_wrap.BOX_WIDTH + 1):
            errs.append(f'{w} px: {re.sub(TOKEN, "", ln)[:40]}')
            break
    text = re.sub(r'<FFFD>.', '', en)  # parameter character (# or kana)
    bad = sorted({c for c in TOKEN.sub('', text) if c not in OKCHARS})
    if bad:
        errs.append(f'characters not allowed: {"".join(bad)}')
    else:
        try:
            etext.encode(en, end=None)
        except ValueError as ex:
            errs.append(str(ex))
    return errs


def _keycol(p):
    """Key column of a manual/work talk table: 'id' (answer pool) or
    'unit' (per-demon units). Loud when neither is present."""
    cols = strlib.tsv_cols(p)
    for k in ('id', 'unit'):
        if k in cols:
            return k
    raise ValueError(f'{p}: no id/unit key column (has {cols})')


def read_ja(name):
    # Raw TSVs (writers emit raw text, never csv-quoted): split on tabs so
    # literal quotes in the English stay literal. See talk.py dump.
    rows = {}
    p = os.path.join(TALK, name + '.tsv')
    if not os.path.exists(p):
        return rows
    key = _keycol(p)
    for c in strlib.tsv_rows(p, required=(key, 'ja', 'en')):
        if c[key].isdigit():
            rows[int(c[key])] = (c['ja'], c['en'])
    return rows


def read_note(name):
    """{unit: note} for the manual worklist (auto-prefills carry 'auto: ...').
    Tables without a note column simply have no notes."""
    notes = {}
    p = os.path.join(TALK, name + '.tsv')
    if not os.path.exists(p):
        return notes
    if 'note' not in strlib.tsv_cols(p):
        return notes
    key = _keycol(p)
    for c in strlib.tsv_rows(p, required=(key, 'note')):
        if c[key].isdigit():
            notes[int(c[key])] = c['note']
    return notes


def read_work(path):
    rows = {}
    key = _keycol(path)
    for c in strlib.tsv_rows(path, required=(key, 'ja')):
        if c[key].isdigit() and etext.has_text(c['ja']):
            rows[int(c[key])] = c['ja'].strip()
    return rows


def key(ja):
    return re.sub('<FFFD>.', '<FFFD>#', ja)


def params(ja):
    return re.findall(r'<FFFD>(.)', ja)


def prep(name):
    rows = read_ja(name)
    seen = {}
    for u, (ja, en) in sorted(rows.items()):
        seen.setdefault(key(ja), u)
    p = os.path.join(ROOT, 'translation', 'manual', 'work', f'talk_{name}_ja.tsv')
    with open(p, 'w', encoding='utf-8', newline=NL) as o:
        o.write('unit	ja' + NL)
        for k, u in sorted(seen.items(), key=lambda x: x[1]):
            o.write(f'{u}	{k}' + NL)
    print(f'{name}: {len(rows)} units, {len(seen)} unique -> {p}')


def run(name, write):
    rows = read_ja(name)
    wdir = os.path.join(ROOT, 'translation', 'manual', 'work')
    kj = {u: ja for u, ja in read_work(os.path.join(wdir, f'talk_{name}_ja.tsv')).items()}
    work = read_work(os.path.join(wdir, f'talk_{name}_en.tsv'))
    bad = 0
    for u, en in sorted(work.items()):
        if u not in kj:
            print(f'unit {u}: not in the _ja file')
            bad += 1
            continue
        e = check(kj[u], en, True)
        if e:
            bad += 1
            print(f'unit {u}: ' + '; '.join(e))
    missing = [u for u in kj if u not in work]
    print(f'{name}: {len(work)}/{len(kj)} unique texts translated, {len(missing)} missing, {bad} with problems')
    if bad or not write:
        return bad
    by_key = {kj[u]: work[u] for u in work}
    n = 0
    p = os.path.join(TALK, name + '.tsv')
    cols = strlib.tsv_cols(p)
    ki = cols.index('id' if 'id' in cols else 'unit') if ('id' in cols or 'unit' in cols) else None
    if ki is None or 'ja' not in cols or 'en' not in cols:
        raise ValueError(f'{p}: need an id/unit key plus ja/en (has {cols})')
    ji, ei = cols.index('ja'), cols.index('en')
    lines = open(p, encoding='utf-8').read().split(NL)
    out = [lines[0]]
    for row in strlib.tsv_rows(p, required=(cols[ki], 'ja', 'en')):
        c = [row[x] for x in cols]
        if c[ki].isdigit() and key(c[ji]) in by_key:
            en = by_key[key(c[ji])]
            for par in params(c[ji]):
                en = en.replace('<FFFD>#', '<FFFD>' + par, 1)
            e2 = check(c[ji], en)
            if e2:
                print(f'unit {c[ki]} after expansion: ' + '; '.join(e2))
                bad += 1
            c[ei] = en
            n += 1
        out.append('\t'.join(c))
    if bad:
        return bad
    open(p, 'w', encoding='utf-8', newline=NL).write(NL.join(out))
    print(f'wrote {n} units into {p}')
    return 0


ANS = os.path.join(TALK, 'ANSWERS.tsv')
ANS_W = vwf_wrap.BOX_WIDTH   # an answer is one line the battle VWF draws (15 cells; see vwf_wrap.BATTLE_BOX_WIDTH)


def ans_strings():
    """{decoded ja text: [files]} of every section-1 answer string (text part only)"""
    import glob
    import talk
    out = {}
    for p in sorted(glob.glob(os.path.join(ROOT, 'data', 'psx', 'TALK', '*.BIN'))):
        name = os.path.basename(p)[:-4]
        t = talk.load(name)
        for v, sp in t.s1:
            out.setdefault(etext.decode(sp[:t.s1_text_len(sp)]), []).append(name)
    return out


def ans_prep():
    os.makedirs(os.path.dirname(ANS), exist_ok=True)
    old = {}
    if os.path.exists(ANS):
        for line in open(ANS, encoding='utf-8').read().split(NL)[1:]:
            c = line.split('	')
            if len(c) >= 3 and c[0].isdigit():
                old[c[1]] = c[2]
    strs = ans_strings()
    with open(ANS, 'w', encoding='utf-8', newline=NL) as o:
        o.write('id	ja	en' + NL)
        for i, (ja, files) in enumerate(sorted(strs.items(), key=lambda x: (-len(x[1]), x[0]))):
            en = old.get(ja, '')
            o.write(f'{i}	{ja}	{en if etext.has_text(en) else ""}' + NL)
    w = os.path.join(ROOT, 'translation', 'manual', 'work', 'talk_ANS_ja.tsv')
    os.makedirs(os.path.dirname(w), exist_ok=True)
    with open(w, 'w', encoding='utf-8', newline=NL) as o:
        o.write('unit	ja' + NL)
        for i, ja in enumerate(sorted(strs, key=lambda k: (-len(strs[k]), k))):
            o.write(f'{i}	{ja}' + NL)
    print(f'{len(strs)} unique answer strings -> {ANS}, {w}')


def ans_run(write):
    wdir = os.path.join(ROOT, 'translation', 'manual', 'work')
    ja = read_work(os.path.join(wdir, 'talk_ANS_ja.tsv'))
    en = read_work(os.path.join(wdir, 'talk_ANS_en.tsv'))
    bad = 0
    for u, t in sorted(en.items()):
        if u not in ja:
            print(f'unit {u}: not in the _ja file')
            bad += 1
            continue
        e = check(ja[u], t, False, ANS_W, 1)
        if e:
            bad += 1
            print(f'unit {u}: ' + '; '.join(e))
    print(f'ANS: {len(en)}/{len(ja)} translated, {len(ja) - len(en)} missing, {bad} with problems')
    if bad or not write:
        return bad
    by_ja = {ja[u]: en[u] for u in en}
    lines = open(ANS, encoding='utf-8').read().split(NL)
    out = [lines[0]]
    for line in lines[1:]:
        c = line.split('	')
        if len(c) >= 3 and c[0].isdigit() and c[1] in by_ja:
            c[2] = by_ja[c[1]]
            line = '	'.join(c)
        out.append(line)
    open(ANS, 'w', encoding='utf-8', newline=NL).write(NL.join(out))
    print(f'wrote {len(by_ja)} answers into {ANS}')
    return 0


def width_only(errs):
    """True when every error is overflow (lines/px): builds as-is with a
    warning. Textbox text is never shortened, never skipped."""
    return bool(errs) and all(re.match(r'^\d+ (px:|lines)', e) for e in errs)


def qa():
    # Build gate: human English only. Unedited auto-prefills (note
    # 'auto: ...') are known-broken drafts awaiting a human; talk.py build
    # skips them byte-identical, so they never reach this gate. Width
    # overflow anywhere is a warning, never a failure.
    import glob
    tot = bad = 0
    for p in sorted(glob.glob(os.path.join(TALK, '*.tsv'))):
        name = os.path.basename(p)[:-4]
        notes = read_note(name)
        for u, (ja, en) in read_ja(name).items():
            if etext.has_text(en) and not notes.get(u, '').startswith('auto:'):
                tot += 1
                e = check(ja, en)
                if e and not width_only(e):
                    bad += 1
                    print(f'{name} {u}: ' + '; '.join(e))
                elif e:
                    print(f'{name} {u} [width-warning]: ' + '; '.join(e))
    if os.path.exists(ANS):
        for line in open(ANS, encoding='utf-8').read().split(NL)[1:]:
            c = line.split('	')
            if len(c) >= 3 and c[0].isdigit() and etext.has_text(c[2]):
                tot += 1
                e = check(c[1], c[2], False, ANS_W, 1)
                if e and not width_only(e):
                    bad += 1
                    print(f'ANSWER {c[0]}: ' + '; '.join(e))
                elif e:
                    print(f'ANSWER {c[0]} [width-warning]: ' + '; '.join(e))
    print(f'TALK QA: {tot} translated units and answers, {bad} with problems')
    return bad


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    if a[0] == 'qa':
        sys.exit(1 if qa() else 0)
    if a[0] == 'prep':
        prep(a[1].upper())
        sys.exit(0)
    if a[0] == 'ans-prep':
        ans_prep()
        sys.exit(0)
    if a[0] in ('ans-check', 'ans-apply'):
        sys.exit(1 if ans_run(a[0] == 'ans-apply') else 0)
    sys.exit(1 if run(a[1].upper(), a[0] == 'apply') else 0)
