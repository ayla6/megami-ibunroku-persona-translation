"""Demon negotiation scripts: TALK/*.BIN (parse, dump, rebuild).

File layout (verified against BTLP.BIN 0x80074BAC, which returns base + table[i] + 0x14):
  0x00  u32[5]   header: [0]=0x14 (text offsets are relative to this), [1..4] = absolute file
                 offsets of four data sections that follow the text pool ([1] = pool end)
  0x14  u32[n]   text table, ascending; unit i starts at  table[i] + 0x14
  ...   FF       padding up to 0x2014, where the text pool starts
  0x2014         text pool: unit i = bytes [start_i, start_{i+1}); the last one runs to header[1].
                 Displayed text ends at the first FF F5 (page) / FF EF; a few units carry stray
                 bytes after it, which are kept as part of the span (lossless).
  [1]..          sections 1-4: u16 index/script tables (no file pointers seen)
Control codes: FFF5 end of page, FFEF end, FFF6 newline, FFFC/FFFD(+1 byte) pause/branch,
FFFB/FFF7, FFF1, FFEC ... Parameter bytes are kept as is. The renderer is BTLP's own
(16 px glyphs, 15 per line): English needs a VWF hook there before it can be shown.

CLI (run from persona-tl/):
  python tools/talk.py check            parse every file, rebuild unchanged, compare bytes
  python tools/talk.py dump             write translation/manual/talk/<NAME>.tsv (unit ja en)
  python tools/talk.py build [outdir]   apply `en` -> build/TALK/<NAME>.BIN (only edited files)
"""
import glob
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext  # noqa: E402
import strlib  # noqa: E402

ROOT = etext.ROOT
SRC = os.path.join(ROOT, 'data', 'psx', 'TALK')
TSV = os.path.join(ROOT, 'translation', 'manual', 'talk')
POOL = 0x2014
ENDS = {0xF5, 0xEF}


def end_codes(b):
    """positions just past every FF F5 / FF EF in an encoded unit (aligned parse)."""
    out, i = [], 0
    while i + 1 < len(b):
        c = b[i]
        if c == 0xFF:
            if b[i + 1] in ENDS:
                out.append(i + 2)
            i += 2
        elif 0x80 <= c <= 0x87:
            i += 2
        else:
            i += 1
    return out


class Talk:
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.hdr = list(struct.unpack_from('<5I', data, 0))
        base = self.base = self.hdr[0]
        offs, i = [], base
        while i + 4 <= len(data):
            v = struct.unpack_from('<I', data, i)[0]
            if v == 0xFFFFFFFF:
                break
            offs.append(v)
            i += 4
        self.starts = [o + base for o in offs]
        self.ok = (bool(self.starts) and self.starts == sorted(self.starts)
                   and self.starts[0] == POOL and self.starts[-1] < self.hdr[1] <= len(data))
        self.units = []
        if self.ok:
            ends = self.starts[1:] + [self.hdr[1]]
            self.units = [bytes(data[s:e]) for s, e in zip(self.starts, ends)]
        elif (self.starts and self.starts == sorted(self.starts)
                and all(0 <= s < len(data) for s in self.starts)
                and self.hdr[1] <= self.starts[0]):
            # flat string table (ETC.BIN): sorted offsets, no text pool;
            # hdr[1] sits at/below the first string, so the standard shape
            # above can never match — mutually exclusive with it.
            ends = self.starts[1:] + [len(data)]
            units = [bytes(data[s:e]) for s, e in zip(self.starts, ends)]
            if units and all(len(u) >= 2 for u in units):
                self.units = units
                self.ok = True
        # section 1 = the player's answer lines: u32[512] table (offset from the section start, 0xFFFFFFFF = none), then the
        # strings packed in table order (each ends with FF F5 / FF EF, a few carry stray bytes before the next one)
        self.s1_tab, self.s1 = [], []
        if self.ok and self.hdr[2] - self.hdr[1] >= 2048:
            a, b = self.hdr[1], self.hdr[2]
            self.s1_tab = list(struct.unpack_from('<512I', data, a))
            offs = sorted({v for v in self.s1_tab if v != 0xFFFFFFFF})
            if offs and offs[0] == 2048:
                ends = offs[1:] + [b - a]
                self.s1 = [(v, bytes(data[a + v:a + e])) for v, e in zip(offs, ends)]

    def s1_text_len(self, span):
        e = [x for x in (span.find(bytes((0xFF, 0xF5))), span.find(bytes((0xFF, 0xEF)))) if x >= 0]
        return min(e) + 2 if e else len(span)

    def rebuild(self, edits=None, s1_edits=None):
        """file bytes with units replaced ({index: bytes}) and answer strings replaced ({position in self.s1: text bytes},
        the stray bytes behind the original end code are kept)."""
        edits = edits or {}
        s1_edits = s1_edits or {}
        units = [edits.get(i, u) for i, u in enumerate(self.units)]
        starts, pos = [], POOL
        for u in units:
            starts.append(pos)
            pos += len(u)
        head = bytearray(self.data[:POOL])
        for k, s in enumerate(starts):
            struct.pack_into('<I', head, self.base + 4 * k, s - self.base)
        # section 1
        old1 = self.hdr[2] - self.hdr[1]
        if self.s1:
            spans, offs, p = [], {}, 2048
            for k, (v, sp) in enumerate(self.s1):
                if k in s1_edits:
                    sp = s1_edits[k] + sp[self.s1_text_len(sp):]
                offs[v] = p
                spans.append(sp)
                p += len(sp)
            tab = [offs.get(v, v) if v != 0xFFFFFFFF else v for v in self.s1_tab]
            sec1 = struct.pack('<512I', *tab) + b''.join(spans)
        else:
            sec1 = self.data[self.hdr[1]:self.hdr[2]]
        # sections keep their alignment modulo 4 (pad with FF)
        fill = (self.hdr[1] - pos) % 4
        delta = pos + fill - self.hdr[1]
        pad = (old1 - len(sec1)) % 4
        sec1 += bytes((0xFF,)) * pad
        delta1 = len(sec1) - old1
        for k in range(1, 5):
            v = self.hdr[k] + delta + (delta1 if k >= 2 else 0)
            struct.pack_into('<I', head, 4 * k, v)
        return bytes(head) + b''.join(units) + bytes((0xFF,)) * fill + sec1 + self.data[self.hdr[2]:]


def files():
    return sorted(glob.glob(os.path.join(SRC, '*.BIN')))


def load(name):
    return Talk(name, open(os.path.join(SRC, name + '.BIN'), 'rb').read())


def _refresh_corpus():
    """Regenerate the JP talk text cache when the glyph map is newer.

    Same rule as the event porter: extracts must reflect the map, or rg
    shows stale brackets for already-solved glyphs."""
    _map = toolbelt.PSP_GLYPHS
    _probe = os.path.join(ROOT, 'data', 'extracted_text', 'psp_jp', 'pack',
                           'talk', 'KYOUKI.tsv')
    if os.path.exists(_map) and (not os.path.exists(_probe)
                                 or os.path.getmtime(_map) > os.path.getmtime(_probe)):
        print('glyph map newer than talk cache: regenerating extracts')
        sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
        from text import cmd_talk_slots as _recache
        _recache('jp')


def cmd_check():
    _refresh_corpus()
    tot = good = nunits = 0
    for f in files():
        name = os.path.basename(f)[:-4]
        t = load(name)
        tot += 1
        if not t.ok:
            print(f'{name}: layout not recognised (header {[hex(x) for x in t.hdr]}) - needs its own handling')
            continue
        same = t.rebuild() == t.data
        good += same
        nunits += len(t.units)
        # text codec must be lossless on every unit
        bad = sum(1 for u in t.units if etext.encode(etext.decode(u), end=None) != u)
        multi = sum(1 for u in t.units if len(end_codes(u)) != 1)
        print(f'{name:10s} {len(t.units):4d} units  rebuild identical: {same}  codec mismatches: {bad}  units without exactly one end code: {multi}')
    print(f'{good}/{tot} files round-trip, {nunits} units')


def _serious(errs):
    """True when the row may not ship - anything its own box cannot show.
    Rows exceeding their box capacity stay in the manual queue rather than
    relying on in-game wrapping or scrolling. Wording is never shortened."""
    return bool(errs)


def _qa(ja, en):
    """talktl errors for a generated row. Single place deciding clean vs
    needs-human; generated files never store the verdict."""
    from talktl import check
    return check(ja, en)


def cmd_dump():
    """The canonical work list: every unit position without a translation
    gets a manual gap row (toolbelt route_gaps); filled rows (human or
    port) clean up automatically. A human's en is never touched.

    The s1 section - the answer-pool strings the <FFFD> parameter rows
    serve - is NOT worklisted here: those slots belong to the answers
    system (port_answers), which ports them by id; queueing them here
    made the TALK worklists fill with rows this pipeline can never ship.
"""
    _refresh_corpus()
    import toolbelt
    for f in files():
        name = os.path.basename(f)[:-4]
        t = load(name)
        if not t.ok:
            continue
        toolbelt.route_gaps(f'TALK/{name}', text_starts(t))
    print('wrote canonical TALK worklists (translation/manual/TALK)')


def dead_unit(unit):
    """A dialogue unit that is its end code alone: it shows nothing, so it
    is no row (port_talk carries the PSP bytes cut at its index into the
    stream before it)."""
    return not re.sub(r'<[^>]*>', '', etext.decode(unit)).strip()


def text_starts(t):
    """[pos] of the dialogue units that hold text - THE work surface."""
    return [hex(t.starts[k]) for k, u in enumerate(t.units) if not dead_unit(u)]


def canon_texts(name):
    """({pos: en} generated, {pos: en} manual) for TALK/<NAME> - THE read
    path (toolbelt rows; generated is the PSP port, manual is the human's,
    and the human wins at build). Rows are keyed by the file offset the
    extract uses: a unit's start or an answer string's offset."""
    import toolbelt
    rel = f'TALK/{name}'
    gen = {r['pos']: r.get('en', '')
           for r in toolbelt.read_generated(rel, optional=True)
           if etext.has_text(r.get('en', ''))}
    man = {r['pos']: r.get('en', '')
           for r in toolbelt.read_manual(rel, optional=True)
           if etext.has_text(r.get('en', ''))}
    return gen, man


def generated_answers():
    """PSP-derived answers: ({ja: en} by-text unanimous, {(file, offset): en}
    per-slot context map). Only QA-clean rows are stored upstream."""
    by_text, by_slot = {}, {}
    gp = os.path.join(ROOT, 'translation', 'generated', 'TALK', 'ANSWERS.tsv')
    if os.path.exists(gp):
        for x in strlib.tsv_rows(gp, required=('id', 'ja', 'en', 'source')):
            if etext.has_text(x['en']) and x['source'].startswith('psp-us'):
                by_text.setdefault(x['ja'], x['en'])
    sp = os.path.join(ROOT, 'translation', 'generated', 'TALK', 'ANSWERS_SLOT.tsv')
    if os.path.exists(sp):
        for x in strlib.tsv_rows(sp, required=('file', 'offset', 'ja', 'en')):
            if x['offset'].isdigit() and etext.has_text(x['en']):
                by_slot[(x['file'], int(x['offset']))] = (x['ja'], x['en'])
    return by_text, by_slot


def cmd_build(outdir):
    # Injection reads PSX units and canonical translation tables only. The
    # PSP-JP text cache is used by extraction/porting, not by this builder.
    os.makedirs(outdir, exist_ok=True)
    skipped = []        # rows the table HAS and this box cannot show
    for f in files():
        name = os.path.basename(f)[:-4]
        if name == 'ETC':
            continue        # the "other layout" file: etctalk.py owns it
        t = load(name)
        out = os.path.join(outdir, name + '.BIN')
        gen, man = canon_texts(name)
        edits = {}
        for i, original_unit in enumerate(t.units):
            ja = etext.decode(original_unit)
            pos = hex(t.starts[i])
            text = man.get(pos, '')          # the human's en is sacred
            human = bool(text)
            if not text:
                text = gen.get(pos, '')
            if not text:
                continue
            errs = _qa(ja, text)
            if errs:
                if human:
                    raise SystemExit(f'{name} unit {i} ({pos}): '
                                     + '; '.join(errs))
                # auto row its box cannot show: never builds - and never
                # silently. A row that is here and does not ship keeps the
                # unit Japanese in game, so it is named in the report.
                skipped.append((name, f'unit {i}', pos, ja, '; '.join(errs)))
                continue
            try:
                u = etext.encode(text, end=None)
            except ValueError as ex:
                raise SystemExit(f'{name} unit {i} ({pos}): {ex}')
            if len(end_codes(u)) != 1 or end_codes(u)[0] != len(u):
                raise SystemExit(f'{name} unit {i} ({pos}): a unit must end '
                                 f'with exactly one <FFF5> (or <FFEF>)')
            edits[i] = u
        s1e = {}
        for k, (v, sp) in enumerate(t.s1 if t.ok else []):
            ja = etext.decode(sp[:t.s1_text_len(sp)])
            pos = hex(t.hdr[1] + v)
            text = man.get(pos, '')
            human = bool(text)
            if not text:
                text = gen.get(pos, '')
            if not text:
                continue
            errs = _qa(ja, text)
            if errs:
                if human:
                    raise SystemExit(f'{name} answer {ja!r} ({pos}): '
                                     + '; '.join(errs))
                skipped.append((name, f'answer {ja[:20]!r}', pos, ja,
                                '; '.join(errs)))
                continue
            u = etext.encode(text, end=None)
            if len(end_codes(u)) != 1 or end_codes(u)[0] != len(u):
                raise SystemExit(f'{name} answer {ja!r} ({pos}): must end with '
                                 f'exactly one end code')
            s1e[k] = u
        if not edits and not s1e:
            if os.path.exists(out):
                os.remove(out)
            continue
        data = t.rebuild(edits, s1e)
        open(out, 'wb').write(data)
        print(f'{name}: {len(edits)} units + {len(s1e)} answers edited, {len(t.data)} -> {len(data)} bytes')
    if skipped:
        # LOUD: a translated row this box cannot show means the unit stays
        # Japanese in game. Never a silent hole - named here, listed in the
        # report, and verify_disc's back-check reads the same disc bytes.
        print(f'TALK: {len(skipped)} translated row(s) NOT shipped (their '
              f'box cannot show them; the unit stays Japanese in game):')
        for name, what, pos, ja, why in skipped[:12]:
            print(f'  {name} {what} {pos}: {why[:70]}')
        if len(skipped) > 12:
            print(f'  ... and {len(skipped) - 12} more')
        rep = os.path.join(ROOT, 'scratch', 'translation_reports',
                           'talk_not_shipped.tsv')
        os.makedirs(os.path.dirname(rep), exist_ok=True)
        with open(rep, 'w', encoding='utf-8') as fh:
            fh.write('file\twhat\tpos\tja\ten\twhy\n')
            for name, what, pos, ja, why in skipped:
                fh.write(f'{name}\t{what}\t{pos}\t{ja}\t'
                         f'\t{why}\n')
        print(f'TALK: not-shipped rows -> {os.path.relpath(rep, ROOT)}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a = sys.argv[1:] or ['check']
    if a[0] == 'check':
        cmd_check()
    elif a[0] == 'dump':
        cmd_dump()
    elif a[0] == 'build':
        cmd_build(a[1] if len(a) > 1 else os.path.join(ROOT, 'build', 'TALK'))
    else:
        raise SystemExit(__doc__)
