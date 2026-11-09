"""Derived test data: every negotiation choice row and where it can be shown.

The choice box is data-driven (BtlOpenChoice / BtlMenuOpenChoices in the
decomp): the <FFFD> parameter in a TALK dialogue unit is the row index; the
row is 12 bytes in header[3] as (count, id0, id1, id2); each id indexes the
u32[512] answer directory at header[1].  A third id >= 0x1F4 means "no third
entry": the box drops to two.  This tool dumps every row of every TALK file,
resolves both the retail JP and the shipped (build/) EN, and records every
dialogue unit that opens it, so a screenshot can be matched back to bytes.

  python tools/talk_choices.py [--out DIR] [--psx DIR] [--build DIR]

Writes:
  DIR/talk_choices.tsv           one line per (file, row), options as columns
  DIR/talk_choice_options.tsv    one line per visible option (the long view)
  DIR/talk_choice_questions.tsv  one line per <FFFD> site (question -> options)
  DIR/talk_choice_problems.tsv   referenced rows with duplicate/missing options

Untracked test data (data/derived/ by default); not part of the build.
"""
import argparse
import glob
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import talk  # noqa: E402
import etext  # noqa: E402

CHOICE_THIRD_NO = 0x1F4      # CHOICE_NO_THIRD in menuopen.c
CHOICE_MAX = 3
NL = chr(10)


def slot_id_text(t, slot):
    """(jp, present) for directory slot `slot` of a parsed Talk."""
    if not (0 <= slot < len(t.s1_tab)) or t.s1_tab[slot] == 0xFFFFFFFF:
        return None, False
    v = t.s1_tab[slot]
    spans = {o: sp for o, sp in t.s1}
    sp = spans.get(v)
    if sp is None:
        return None, False
    return etext.decode(sp[:t.s1_text_len(sp)]), True


def slot_pointer(t, slot, scratch=0x801C0000):
    """(directory value, absolute script address) for a slot, as the engine sees it."""
    entry = t.s1_tab[slot]
    return entry, scratch + t.hdr[1] + entry


def engine_text(t, slot, last):
    """Text the choice box draws for `slot` with `last` as its pointer bound.

    Mirrors BtlMenuOpenChoices: a script pointer above `last` is replaced by
    directory entry 0. Retail's bound is 0x801CFFFF; the translated build uses
    the loaded answer pool's end (btlp/choice_answer_bound.asm).
    """
    if not (0 <= slot < len(t.s1_tab)):
        return None
    entry, at = slot_pointer(t, slot)
    if at > last:
        entry = t.s1_tab[0]
    sp = {o: s for o, s in t.s1}.get(entry)
    if sp is None:
        return None
    return etext.decode(sp[:t.s1_text_len(sp)])


def fffd_sites(t):
    """{row: [(unit index, unit start offset)]} for every <FFFD> in the file."""
    out = {}
    for i, u in enumerate(t.units):
        j = 0
        while j + 1 < len(u):
            if u[j] == 0xFF:
                if u[j + 1] == 0xFD and j + 2 < len(u):
                    out.setdefault(u[j + 2], []).append((i, t.starts[i]))
                    j += 3
                    continue
                j += 2
            else:
                j += 1
    return out


def question_text(t, unit, limit=80):
    """The line up to its <FFFD>, with control codes left visible."""
    u = t.units[unit]
    s = etext.decode(u)
    cut = s.find('<FFFD>')
    if cut >= 0:
        s = s[:cut]
    for end in ('<FFF5>', '<FFEF>'):
        k = s.find(end)
        if k >= 0:
            s = s[:k]
    s = s.replace(chr(9), ' ')
    return s[:limit]


def resolve(t, ids, eff_count, built):
    """Per visible option: dict(jp, en, id, present, fallback, note).

    The shipped build is what the engine runs, so its directory offsets and
    answer-pool end (header word 2) decide what is drawn. A pointer past the
    pool end is replaced by directory entry 0, exactly like the ASM patch in
    btlp/choice_answer_bound.asm. Retail (t) supplies the JP wording.
    """
    eng = built or t
    pool_last = 0x801C0000 + eng.hdr[2]
    retail_last = 0x801CFFFF
    out = []
    for i in range(CHOICE_MAX):
        slot = ids[i]
        there = i < eff_count
        jp = engine_text(t, slot, retail_last) if there else None
        en = engine_text(eng, slot, pool_last) if there else None
        present = slot_id_text(eng, slot)[1] if there else False
        fallback = False
        note = ''
        if not there:
            note = 'not drawn'
        elif slot >= len(eng.s1_tab):
            note = 'id past 512-entry directory'
        else:
            entry, at = slot_pointer(eng, slot)
            if at > pool_last:
                fallback = True
                note = (f'dir=0x{entry:08x} -> past pool end 0x{eng.hdr[2]:x},'
                        ' fallback slot 0')
            elif not present:
                # menuopen still reads the directory entry when it is
                # 0xFFFFFFFF; the 32-bit wrap lands at hdr[1]-1, inside the
                # pack, so it does not hit the pool-end fallback.
                note = (f'dir=0x{entry:08x} -> reads pack offset'
                        f' 0x{at - 0x801C0000:x}')
        out.append(dict(id=slot, jp=jp, en=en, present=present,
                        fallback=fallback, note=note, drawn=there))
    return out


def clean(s):
    """TSV-safe; keep the end code visible because it is what ships."""
    return (s or '').replace(chr(9), ' ').replace(chr(10), ' ')


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


HEAD = ['file', 'row', 'referenced', 'raw_count', 'eff_count',
        'id0', 'id1', 'id2',
        'jp0', 'jp1', 'jp2', 'en0', 'en1', 'en2',
        'fallback', 'duplicate', 'same3', 'note',
        'contexts', 'question_en']
OPT_HEAD = ['file', 'row', 'referenced', 'option', 'id', 'jp', 'en',
            'fallback', 'note', 'contexts', 'question_en']
Q_HEAD = ['file', 'unit', 'pos', 'param', 'row', 'eff_count',
          'question_jp', 'question_en', 'opt0_en', 'opt1_en', 'opt2_en']


def scan(psx, build):
    """(rows, visible options, problem rows) for every TALK file under psx."""
    head, opt_head = HEAD, OPT_HEAD
    rows = []
    opts_out = []
    questions = []
    probs = []
    for path in sorted(glob.glob(os.path.join(psx, '*.BIN'))):
        name = os.path.basename(path)[:-4]
        t = talk.Talk(name, _read(path))
        if not t.ok or t.hdr[4] <= t.hdr[3]:
            continue
        bp = os.path.join(build, name + '.BIN')
        built = talk.Talk(name, _read(bp)) if os.path.exists(bp) else None
        refs = fffd_sites(t)
        nrows = (t.hdr[4] - t.hdr[3]) // 12
        for r in range(nrows):
            count, id0, id1, id2 = struct.unpack_from('<4H', t.data, t.hdr[3] + r * 12)
            ids = [id0, id1, id2]
            eff = CHOICE_MAX if count > CHOICE_MAX else count
            if id2 >= CHOICE_THIRD_NO:
                eff = 2
            opts = resolve(t, ids, eff, built)
            drawn = [o for o in opts if o['drawn']]
            fb = any(o['fallback'] for o in drawn)
            texts = [o['en'] or o['jp'] for o in drawn]
            dup = len(set(texts)) < len(texts) and all(texts)
            same3 = eff == 3 and all(texts) and texts[0] == texts[1] == texts[2]
            ctx = []
            row_q = ''
            for unit, start in refs.get(r, []):
                ctx.append(f'unit {unit} at 0x{start:x} param={r}')
                qja = question_text(t, unit)
                qen = question_text(built, unit) if built else qja
                if not row_q:
                    row_q = qen
                questions.append([name, unit, f'0x{start:x}', r, r, eff,
                                  clean(qja), clean(qen),
                                  clean(opts[0]['en']), clean(opts[1]['en']),
                                  clean(opts[2]['en'])])
            note = '; '.join(sorted({o['note'] for o in opts
                                     if o['note'] and o['note'] != 'not drawn'}))
            rec = [name, r, 'Y' if r in refs else 'N', count, eff,
                   id0, id1, id2,
                   clean(opts[0]['jp']), clean(opts[1]['jp']), clean(opts[2]['jp']),
                   clean(opts[0]['en']), clean(opts[1]['en']), clean(opts[2]['en']),
                   'Y' if fb else 'N', 'Y' if dup else 'N', 'Y' if same3 else 'N',
                   note, '; '.join(ctx), clean(row_q)]
            rows.append(rec)
            for i, o in enumerate(drawn):
                opts_out.append([name, r, 'Y' if r in refs else 'N', i, o['id'],
                                 clean(o['jp']), clean(o['en']),
                                 'Y' if o['fallback'] else 'N',
                                 clean(o['note']), '; '.join(ctx), clean(row_q)])
            if r in refs and (dup or same3 or fb or any(
                    o['drawn'] and not o['present'] for o in opts)):
                probs.append(rec)
    return head, opt_head, Q_HEAD, rows, opts_out, questions, probs


def _write(path, head, data):
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(chr(9).join(head) + NL)
        for rec in data:
            f.write(chr(9).join(str(x) for x in rec) + NL)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'derived'))
    ap.add_argument('--psx', default=os.path.join(ROOT, 'data', 'psx', 'TALK'))
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 'TALK'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    head, opt_head, q_head, rows, opts_out, questions, probs = scan(a.psx, a.build)
    p1 = _write(os.path.join(a.out, 'talk_choices.tsv'), head, rows)
    p2 = _write(os.path.join(a.out, 'talk_choice_options.tsv'), opt_head, opts_out)
    p3 = _write(os.path.join(a.out, 'talk_choice_questions.tsv'), q_head, questions)
    p4 = _write(os.path.join(a.out, 'talk_choice_problems.tsv'), head, probs)
    print(f'{len(rows)} rows from {len(set(x[0] for x in rows))} files -> {p1}')
    print(f'{len(opts_out)} visible options -> {p2}')
    print(f'{len(questions)} question sites -> {p3}')
    print(f'{len(probs)} referenced rows with a problem -> {p4}')


if __name__ == '__main__':
    main()
