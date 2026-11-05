"""Parser for PSP Persona (ULJM05422 / ULUS10432) pack/E?.BIN event scripts.

Container: u32 offset-pair table (entry i = bytes t[2i]..t[2i+1]).
Entry:     raw image, no header (cf. PSX 8-byte load/end header in tools/efile.py).
Image:     same script VM as PSX: map header + command stream (FF op a b;
           `FF 55 00 00 <u32LE image-relative pointer>` says the box at ptr)
           + text pool + small tail.
Boxes:     text units are u16BE glyph indices; control codes are FF xx with
           xx < 0x20 (same split as PSX: 1B/18/03/02/04 seen, box ends in FF 01),
           then zero padding to a 4-byte boundary. Boxes after a said box that
           parse as text are reached sequentially (same chaining rule as efile).

TALK files (pack/talk/*.BIN): same family as tools/talk.py -- u32[5] header
with base 0x18 (PSX: 0x14), text-offset table from base until 0xFFFFFFFF,
unit i = [starts[i], starts[i+1]), text pool starts at 0x2014 (identical).

CLI (run from repo root):
  python src/extraction_tools/psp/text.py E0 [entry]     dump boxes of pack/E0.BIN (both regions)
  python src/extraction_tools/psp/text.py counts         per-entry box counts PSX vs PSPJP vs PSPUS
  python src/extraction_tools/psp/text.py talk SLIME     unit counts + first units of a TALK file
"""
import os
import struct
import sys
from functools import lru_cache

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PSX = os.path.join(ROOT, 'data', 'psx', 'ADV')
PJ = os.path.join(ROOT, 'data', 'psp_jp', 'PSP_GAME', 'USRDIR', 'pack')
PU = os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR', 'pack')

sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import strlib  # noqa: E402
import toolbelt  # noqa: E402
import efile  # noqa: E402  (PSX reference implementation)


def psp_scan_box(b, i, limit=40000):
    """Index just past the FF 01 ending the PSP text box starting at i, else None.

    Text units are 2 bytes (u16BE glyph index); FF xx with xx < 0x20 is a control
    code (mirrors efile.scan_box, which steps 1-2 bytes for the 1-byte PSX encoding).
    """
    n = len(b)
    s = i
    while i + 1 < n and i - s < limit:
        c = b[i]
        if c == 0xFF:
            op = b[i + 1]
            if op >= 0x20:
                return None  # command, not text
            i += 2
            if op == 1:
                return i
        else:
            i += 2
    return None


def orphan_runs(b, glyphs, himark=None):
    """FF01-terminated text runs anywhere in the entry image, independent of
    the offset table (mirrors the upstream PSP-script scanner's e_boxes).

    Catches live text the compact table omits and no FF55 pointer reaches
    (e.g. US E0/18's opening Maki line). A run must end at FF01 and carry a
    known glyph word so padding/command data is never invented as text.
    Returns [(start, end)] byte offsets.

    A glyph word is any word inside the glyph map's range - the JP map has
    955 kanji at >= 0x800. himark derives from the map unless a caller
    overrides it, so all mapped kanji remain within a text run.

    Head padding is zeros ONLY: an unknown head word may be a glyph-map
    hole and is kept in the box (visible [xxxx], reported by the decoder) -
    never silently trimmed away."""
    if himark is None:
        himark = max(glyphs) + 1 if glyphs else 0x800
    E_PARAM = {0xFF05, 0xFF06, 0xFF0E, 0xFF18, 0xFF19, 0xFF1A}
    # A dialogue box always carries a structural control (page/line/wait
    # breaks, choice, nameplate) or a pause; data that merely ends in FF01
    # is not text.
    STRUCT = {0xFF02, 0xFF03, 0xFF04, 0xFF05, 0xFF0E, 0xFF1B}
    n = len(b) // 2
    w = struct.unpack('>%dH' % n, b[:n * 2])
    res, start, i = [], None, 0
    while i < n:
        v = w[i]
        if v < himark or 0xFF01 <= v <= 0xFF1F:
            if start is None:
                start = i
            if v in E_PARAM:
                i += 1
            elif (v == 0xFF1B and i + 2 < n
                  and w[i + 1] in (0x0200, 0x0300) and w[i + 2] == 0x0044):
                i += 2  # intro-card parameter pair
            elif v == 0xFF01:
                k = start
                while k < i and w[k] == 0:
                    k += 1
                box = list(w[k:i + 1])
                if any(x in glyphs for x in box) and any(x in STRUCT for x in box):
                    res.append((k * 2, (i + 1) * 2))
                start = None
        else:
            start = None
        i += 1
    return res


class PspEntry:
    def __init__(self, index, body, region='jp'):
        self.index = index
        self.body = bytes(body)
        self.region = region
        self._parse()

    def pointers(self):
        """(offset, target) for every even-aligned u32 pointing into the image."""
        b = self.body
        out = []
        for off in range(0, len(b) - 3, 2):
            v = struct.unpack_from('<I', b, off)[0]
            if v < len(b):
                out.append((off, v))
        return out

    def _table(self):
        """Box-offset table: the LAST [N][off0..offN-1] run in the image with
        strictly ascending in-image offsets that all start valid boxes.
        (Can't anchor on trailing zeros: a table whose last offset has zero
        high bytes blends into the padding.)"""
        b = self.body
        n = len(b)
        if n < 12:
            return None
        for p in range(n - 8, -1, -2):
            count = struct.unpack_from('<I', b, p)[0]
            if count < 1 or count > 600 or p + 4 + 4 * count > n:
                continue
            prev = -1
            offs = []
            ok = True
            for k in range(count):
                v = struct.unpack_from('<I', b, p + 4 + 4 * k)[0]
                if v <= prev or v >= n:
                    ok = False
                    break
                prev = v
                offs.append(v)
            if not ok or not offs or offs[0] < 0x200:
                continue
            # every offset must start a box ending within bounds
            good = True
            for k, s in enumerate(offs):
                limit = offs[k + 1] if k + 1 < len(offs) else n
                e = psp_scan_box(b, s)
                if e is None or e > limit or e - s < 4:
                    good = False
                    break
            if good:
                return p, offs
        return None

    def _parse(self):
        b = self.body
        tab = self._table()
        if tab is not None:
            _, starts = tab
            # Some live dialogue boxes are reached by FF55 pointers but are
            # absent from the compact box-offset table. Include those roots
            # instead of silently dropping their text from the extraction.
            roots = {target for off, target in self.pointers()
                     if off >= 4 and b[off - 4] == 0xFF and b[off - 3] == 0x55}
            starts = sorted(set(starts) | roots)
            boxes = []
            covered = 0
            for k, s in enumerate(starts):
                if s < covered:
                    continue
                limit = starts[k + 1] if k + 1 < len(starts) else len(b)
                # The offset table can skip live boxes; chain sequential text
                # after each start (same rule as the table-less fallback) up
                # to the next known start. Chained boxes must carry a real
                # glyph word so pure control-code runs are not invented.
                i = s
                first = True
                while i < limit:
                    e = psp_scan_box(b, i)
                    if e is None or e > limit or (e - i) < 4:
                        break
                    if not first:
                        if not any(b[i:e - 2]):
                            break
                        words = struct.unpack('>%dH' % ((e - i) // 2), b[i:e])
                        if not any(w < 0xFF00 and w != 0 for w in words):
                            break
                    boxes.append((i, e))
                    covered = e
                    j = e
                    while j < len(b) and b[j] == 0 and j - e < 4:
                        j += 1
                    # Text units are 2 bytes: a chained box always starts on
                    # an even offset. Without this, an odd zero-run lands
                    # mid-word and the rest of the entry decodes as garbage.
                    i = j + (j % 2)
                    first = False
            self.boxes = sorted(set(boxes) | set(self._orphans(boxes)))
            self.from_table = True
            return
        self.from_table = False
        b = self.body
        ptrs = self.pointers()
        say = sorted({tg for off, tg in ptrs
                      if off >= 4 and b[off - 4] == 0xFF and b[off - 3] == 0x55})
        # NOTE: no `other`-pointer guard (unlike PSX efile): with relative
        # pointers every small data word looks like a pointer (false positives
        # kill chains). Say-roots + sequential FF01 scan are enough.
        boxes = []
        covered = 0
        for s0 in say:
            if s0 < covered:
                continue
            i = s0
            first = True
            while i < len(b):
                if not first and i < covered:
                    break
                e = psp_scan_box(b, i)
                if e is None or (e - i) < 4:
                    break
                if not first and not any(b[i:e - 2]):
                    break
                boxes.append((i, e))
                covered = e
                # PSP does NOT pad boxes to 4 (unlike PSX): chained boxes
                # follow back-to-back, or after up to 3 zero bytes. Text
                # units are 2 bytes, so chained boxes start on even offsets.
                j = e
                while j < len(b) and b[j] == 0 and j - e < 4:
                    j += 1
                i = j + (j % 2)
                first = False
        self.boxes = sorted(set(boxes) | set(self._orphans(boxes)))

    def _orphans(self, boxes):
        """Text runs the table/roots/chains missed (validated against the
        upstream FF01 scanner for US). Only runs outside already-covered
        spans are added, so referenced boxes keep their exact boundaries."""
        try:
            if self.region == 'us':
                from codec import US_MAP
                glyphs, himark = set(US_MAP), 0x0800
            else:
                glyphs, himark = set(jp_glyph_map()), 0x9000
        except Exception:
            return []
        taken = [(s, e) for s, e in boxes]
        out = []
        for s, e in orphan_runs(self.body, glyphs, himark):
            if any(s < te and e > ts for ts, te in taken):
                continue
            out.append((s, e))
        return out

    def box_bytes(self, k):
        s, e = self.boxes[k]
        return self.body[s:e]


class PspContainer:
    def __init__(self, data, region='jp'):
        offs = []
        j = 0
        while j + 4 <= len(data):
            v = struct.unpack_from('<I', data, j)[0]
            if j > 0 and v < offs[-1]:
                break
            offs.append(v)
            j += 4
            if len(offs) > 6000:
                break
        assert len(offs) % 2 == 0, f'odd pair table ({len(offs)})'
        self.entries = [PspEntry(i, data[offs[2 * i]:offs[2 * i + 1]], region)
                        for i in range(len(offs) // 2)]


def units_hex(b):
    """Debug rendering: u16BE units as hex, FF xx controls as <FFxx>."""
    out = []
    i = 0
    while i + 1 <= len(b):
        if b[i] == 0xFF:
            out.append('<FF%02X>' % b[i + 1])
            i += 2
        else:
            out.append('%04x' % struct.unpack_from('>H', b, i)[0])
            i += 2
    if i < len(b):
        out.append('<%02X>' % b[i])
    return ' '.join(out)


@lru_cache(maxsize=10)
def load_psp(which, region='jp'):
    base = PJ if region == 'jp' else PU
    with open(os.path.join(base, f'{which}.BIN'), 'rb') as f:
        return PspContainer(f.read(), region)


def jp_glyph_map():
    """The JP glyph map (codec owns the loading)."""
    from codec import jp_map
    return jp_map()


def cmd_cache(region=None, strict=True):
    """Decode PSP E0-E4 box text into local per-file TSV caches mirroring
    the pack layout (data/extracted_text/psp_<lang>/pack/E?.tsv)."""
    import csv
    from codec import decode_box

    regions = (region,) if region else ('jp', 'us')
    all_holes = []
    for lang in regions:
        if lang not in ('jp', 'us'):
            raise SystemExit('cache region must be jp or us')
        if lang == 'jp':
            glyph_map = jp_glyph_map()
        else:
            # ONE table (src/extraction_tools/psp_glyphs.tsv): the PSP has a single
            # charset and no US/JP split, so untranslated JP remnants decode
            # as Japanese with the same map and there is nothing to layer.
            glyph_map = jp_glyph_map()
        import toolbelt
        for file in ('E0', 'E1', 'E2', 'E3', 'E4'):
            container = load_psp(file, lang)
            rows = []
            for entry in container.entries:
                for box in range(len(entry.boxes)):
                    raw = entry.box_bytes(box)
                    text = decode_box(raw, glyph_map, holes=all_holes)
                    s = entry.boxes[box][0]
                    rows.append({'entry': str(entry.index), 'box': str(box),
                                 'pos': f'{entry.index}:{s:#x}', 'text': text})
            toolbelt.write_extracted(f'psp_{lang}', f'pack/{file}', rows)
        print(f'{lang}: decoded PSP box text -> extracted_text/psp_{lang}/pack')
    report_holes('psp pack/E?', all_holes, strict=strict)


def cmd_counts():
    files = ['E0', 'E1', 'E2', 'E3']
    psx_n, jp_n, us_n = {}, {}, {}
    for e in files:
        psx_n[e] = [len(x.boxes) for x in efile.load(os.path.join(PSX, f'{e}.BIN')).entries]
        jp_n[e] = [len(x.boxes) for x in load_psp(e, 'jp').entries]
        us_n[e] = [len(x.boxes) for x in load_psp(e, 'us').entries]
    print(f"{'entry':>12} {'PSX':>5} {'JP':>5} {'US':>5}  match")
    bad = 0
    for e in files:
        for i, (a, b, c) in enumerate(zip(psx_n[e], jp_n[e], us_n[e])):
            ok = 'OK' if a == b == c else 'DIFF'
            if ok == 'DIFF':
                bad += 1
                print(f'{e}/{i:>8} {a:>5} {b:>5} {c:>5}  {ok}')
    total_psx = sum(sum(v) for v in psx_n.values())
    total_jp = sum(sum(v) for v in jp_n.values())
    total_us = sum(sum(v) for v in us_n.values())
    n_entries = sum(len(v) for v in psx_n.values())
    print(f'{n_entries} entries; boxes PSX={total_psx} JP={total_jp} US={total_us}; '
          f'{bad} entries with box-count mismatch')


def cmd_dump(which, entry=None):
    for region in ('jp', 'us'):
        c = load_psp(which, region)
        idx = range(len(c.entries)) if entry is None else [int(entry)]
        for i in idx:
            e = c.entries[i]
            print(f'== {region} {which}/{i}: {len(e.boxes)} boxes')
            for k in range(min(len(e.boxes), 8 if entry is None else 10**9)):
                print(f'  [{k}] {e.boxes[k][0]:#x}-{e.boxes[k][1]:#x} '
                      f'{units_hex(e.box_bytes(k))[:160]}')


def decode_talk_box(raw, glyphs, holes=None):
    """TALK byte stream -> decoded string (FF codes kept, ends at end code).
    THE single TALK decoder: porters and caches all go through this.
    Thin wrapper over codec.decode_box (parameter units and glyph-map holes
    behave identically in every family)."""
    from codec import decode_box
    return decode_box(raw, glyphs, stop_at_end=True, holes=holes)


def report_holes(what, holes, strict=True):
    """Glyph-map holes met while decoding: always print the full worklist
    (nothing is ever dropped silently - a hole is a glyph map to fix).
    strict (the CLI gates) exits nonzero; library callers keep the visible
    cache and route hole-carrying rows to gaps."""
    if not holes:
        return
    from collections import Counter
    c = Counter(u for _, u in holes)
    lines = [f'{what}: {len(holes)} glyph-map holes ({len(c)} distinct words):']
    for u, n in c.most_common():
        off = next(o for o, x in holes if x == u)
        lines.append(f'  0x{u:04x} x{n} (first at +0x{off:x})')
    lines.append('fix src/extraction_tools/psp_glyphs.tsv (the one PSP table, '
                 'converted from references/persona1psptable.tbl)')
    if strict:
        raise SystemExit('\n'.join(lines))
    print('\n'.join(lines))


TALK_DIR = {r: os.path.join(ROOT, 'data', 'psp_%s' % r, 'PSP_GAME', 'USRDIR', 'pack', 'talk') for r in ('jp', 'us')}
TALK_CACHE = {r: os.path.join(ROOT, 'data', 'extracted_text', 'psp_%s' % r, 'pack', 'talk') for r in ('jp', 'us')}
DNG_DIR = {r: os.path.join(ROOT, 'data', 'psp_%s' % r, 'PSP_GAME', 'USRDIR', 'pack', 'dng') for r in ('jp', 'us')}
DNG_CACHE = {r: os.path.join(ROOT, 'data', 'extracted_text', 'psp_%s' % r, 'pack', 'dng') for r in ('jp', 'us')}
MAP_FILES = {'jp': toolbelt.PSP_GLYPHS,
             'us': toolbelt.PSP_GLYPHS}


def _stale(cache, *sources):
    if not os.path.exists(cache):
        return True
    mt = os.path.getmtime(cache)
    return any(os.path.exists(s) and os.path.getmtime(s) > mt for s in sources)


def talk_bins(name):
    """(jp_bytes, us_bytes) of a talk file, or (None, None)."""
    out = []
    for r in ('jp', 'us'):
        p = os.path.join(TALK_DIR[r], name + '.BIN')
        out.append(open(p, 'rb').read() if os.path.exists(p) else None)
    return out[0], out[1]


def slot_table(d):
    """Full section-1 offset table of a talk file (may exceed 512 entries;
    entries past the answer table address binary junk -- callers validate)."""
    h = struct.unpack_from('<6I', d, 0)
    n = (h[2] - h[1]) // 4 if h[2] > h[1] else 0
    return (h, struct.unpack('<%dI' % n, d[h[1]:h[2]])) if n else (h, ())


def refresh_talk_slots(name, region, holes=None):
    """Decode every answer-table slot of one talk file into its cache TSV.
    The cache keeps EVERYTHING (holes included): it is the visible original.
    Returns {slot: text}."""
    from codec import US_MAP
    d = open(os.path.join(TALK_DIR[region], name + '.BIN'), 'rb').read()
    h, tab = slot_table(d)
    gm = jp_glyph_map()          # ONE table: the PSP has a single charset
    local = [] if holes is None else holes
    import toolbelt
    out = {}
    rows = []
    sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'matching'))
    import port_talk as _pt
    for i, (st, seg) in enumerate(_pt.psp_unit_spans(os.path.join(TALK_DIR[region], name + '.BIN'))):
        rows.append({'entry': '0', 'box': str(i), 'pos': hex(st),
                     'text': decode_talk_box(seg, gm, holes=local)})
    for k in range(min(len(tab), 512)):
        v = tab[k]
        if v == 0xFFFFFFFF or v >= h[2]:
            continue
        out[k] = decode_talk_box(d[v:h[2]], gm, holes=local)
        rows.append({'entry': '1', 'box': str(k), 'pos': hex(v), 'text': out[k]})
    toolbelt.write_extracted(f'psp_{region}', f'pack/talk/{name}', rows)
    if holes is None:
        report_holes(f'psp_{region} pack/talk/{name}', local)
    return out


def load_talk_slots(name, region):
    """{slot: text} from the standard extract (answer section = entry 1),
    refreshing when the BIN or glyph map is newer. Glyph-map holes are
    LOUD but not fatal here: the cache stays the visible original with
    [xxxx] markers and every consumer treats marker-carrying slots as
    unsourced (they route to manual gaps, never as text). The CLI gates
    (text.py talk-slots/dng/cache) still exit nonzero on them."""
    import toolbelt
    p = toolbelt.ext_path(f'psp_{region}', f'pack/talk/{name}')
    src = os.path.join(TALK_DIR[region], name + '.BIN')
    if _stale(p, src, MAP_FILES[region], __file__):
        holes = []
        out = refresh_talk_slots(name, region, holes=holes)
        if holes:
            print(f'warning: psp_{region} pack/talk/{name}: {len(holes)} '
                  f'glyph-map holes (visible as [xxxx]; gates list them)',
                  file=sys.stderr)
        return out
    return {int(r['box']): r['text']
            for r in toolbelt.read_extracted(f'psp_{region}', f'pack/talk/{name}', optional=True)
            if r['entry'] == '1'}

def refresh_dng(sub, region, holes=None):
    """Decode every FF01 box of one dng file into its cache TSV (holes kept
    visible in the cache, then reported loud). The box scan is the shared
    structural one (dngpacks.boxes) - the same enumeration on every side,
    so PSX and PSP rows pair by scan index."""
    from codec import glyphs
    gm = glyphs(region)
    d = open(os.path.join(DNG_DIR[region], sub, sub + '.bin'), 'rb').read()
    local = [] if holes is None else holes
    import dngpacks
    out = [(s, decode_talk_box(d[s:s + ln], gm, holes=local))
           for s, ln, _ja in dngpacks.boxes(d)]
    import toolbelt
    toolbelt.write_extracted(f'psp_{region}', f'pack/dng/{sub}',
                             [{'entry': '', 'box': str(k), 'pos': hex(s), 'text': t}
                              for k, (s, t) in enumerate(out)])
    if holes is None:
        report_holes(f'psp_{region} pack/dng/{sub}', local)
    return out


def load_dng_boxes(region, sub):
    """[(off, text)] from cache, refreshing when the BIN or map is newer.
    Holes are loud but not fatal (see load_talk_slots: the cache stays the
    visible original; marker-carrying rows route to gaps, never as text)."""
    p = os.path.join(ROOT, 'data', 'extracted_text', f'psp_{region}', 'pack', 'dng', sub + '.tsv')
    src = os.path.join(DNG_DIR[region], sub, sub + '.bin')
    if _stale(p, src, MAP_FILES[region], __file__):
        holes = []
        out = refresh_dng(sub, region, holes=holes)
        if holes:
            print(f'warning: psp_{region} pack/dng/{sub}: {len(holes)} '
                  f'glyph-map holes (visible as [xxxx]; gates list them)',
                  file=sys.stderr)
        return out
    import toolbelt
    return [(int(r['pos'], 16), r['text'])
            for r in toolbelt.read_extracted(f'psp_{region}', f'pack/dng/{sub}', optional=True)]


def cmd_talk_slots(lang=None, only=None):
    regions = (lang,) if lang else ('jp', 'us')
    holes = []
    for la in regions:
        names = [only] if only else sorted(f[:-4] for f in os.listdir(TALK_DIR[la]) if f.endswith('.BIN'))
        for name in names:
            refresh_talk_slots(name, la, holes=holes)
        print(f'{la}: answer slots -> {TALK_CACHE[la]} ({len(names)} files)')
    report_holes('psp pack/talk', holes)


def cmd_dng(sub=None, lang=None):
    regions = (lang,) if lang else ('jp', 'us')
    holes = []
    for la in regions:
        subs = [sub] if sub else sorted(os.listdir(DNG_DIR[la]))
        for s in subs:
            if os.path.exists(os.path.join(DNG_DIR[la], s, s + '.bin')):
                refresh_dng(s, la, holes=holes)
        print(f'{la}: dng boxes -> {DNG_CACHE[la]}')
    report_holes('psp pack/dng', holes)


def cmd_talk(name):
    import re
    for tag, base in (('PSX', os.path.join(ROOT, 'data', 'psx', 'TALK')),
                      ('JP', os.path.join(PJ, 'talk')),
                      ('US', os.path.join(PU, 'talk'))):
        d = open(os.path.join(base, f'{name}.BIN'), 'rb').read()
        hdr = list(struct.unpack('<5I', d[:20]))
        base_off = hdr[0]
        offs = []
        i = base_off
        while i + 4 <= len(d):
            v = struct.unpack('<I', d[i:i + 4])[0]
            if v == 0xFFFFFFFF:
                break
            offs.append(v)
            i += 4
        starts = [o + base_off for o in offs]
        pool = starts[0] if starts else None
        n_end = 0
        for s, t in zip(starts, starts[1:] + [hdr[1]]):
            seg = d[s:t]
            ends = [m.start() + 2 for m in re.finditer(b'\xff[\xf5\xef]', seg)]
            n_end += len(ends)
        print(f'{tag}: hdr={[hex(x) for x in hdr]} size={len(d)} units={len(offs)} '
              f'pool={pool:#x} endcodes={n_end}')


if __name__ == '__main__':
    if sys.argv[1] == 'cache':
        cmd_cache(sys.argv[2] if len(sys.argv) > 2 else None)
    elif sys.argv[1] == 'counts':
        cmd_counts()
    elif sys.argv[1] == 'talk':
        cmd_talk(sys.argv[2].upper())
    elif sys.argv[1] == 'talk-slots':
        cmd_talk_slots(sys.argv[2] if len(sys.argv) > 2 else None,
                        sys.argv[3].upper() if len(sys.argv) > 3 else None)
    elif sys.argv[1] == 'dng':
        cmd_dng(sys.argv[2] if len(sys.argv) > 2 else None,
                sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        cmd_dump(sys.argv[1].upper(), sys.argv[2] if len(sys.argv) > 2 else None)
