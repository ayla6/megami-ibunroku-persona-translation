"""Audit: every control code in generated English must come from PSP data.

For each ported row, the US source box/unit is resolved exactly like the
porter does (align.tsv + align_fix.tsv for ADV incl. cross-file sources;
index pairing for TALK). Every code op in the EN must either occur in that
US source or belong to the structural allowlist (pagination/terminal/cards/
choices, all positioned by explicit rules). ADV pause params must be verbatim
US params. Private sentinels (US_BRK) must never leak into output.

Usage: python src/extraction_tools/matching/audit_markers.py
Exit 1 with a list of violations.
"""
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'matching'))
import etext  # noqa: E402
from text import load_psp  # noqa: E402
import strlib              # noqa: E402
import port_story as ps  # noqa: E402

CODE = re.compile(r'<FF([0-9A-F]{2})>((?:<[0-9A-F]{2}>)*)')
TALK_CODE = re.compile(r'<FF([0-9A-F]{2,4})>')
# ops that may be introduced by structural rules (never synthesized params)
STRUCTURAL = {0x01, 0x02, 0x03, 0x04, 0x0E}
SENTINEL = chr(0xE000)


def _ff_params(raw, i, n):
    """Word count of a PSP FF-code parameter block starting at raw[i]."""
    op = raw[i + 1]
    if op in (0x05, 0x06, 0x0E, 0x1A):
        return 1
    if op in (0x18, 0x19):
        if i + 3 < n and raw[i + 2] != 0xFF:
            import struct as _st
            first = _st.unpack_from('>H', raw, i + 2)[0]
            if first in (0x0200, 0x0300):
                return 2
        return 1
    return 0


def us_box_ops(raw):
    """[op] for every FF code in a PSP-US box/unit byte stream."""
    out = []
    i, n = 0, len(raw)
    while i + 1 < n:
        if raw[i] == 0xFF:
            out.append(raw[i + 1])
            i += 2 + 2 * _ff_params(raw, i - 2, n)
            continue
        i += 2
    return out


def us_pause_params(raw):
    """{param word} of FF05 pauses in a PSP-US box."""
    out = set()
    i, n = 0, len(raw)
    while i + 1 < n:
        if raw[i] == 0xFF:
            if raw[i + 1] == 0x05 and i + 3 < n and raw[i + 2] != 0xFF:
                out.add(struct.unpack_from('>H', raw, i + 2)[0])
            i += 2 + 2 * _ff_params(raw, i, n)
            continue
        i += 2
    return out


def check_adv():
    bad = []
    idx = ps.align_idx()
    for f in ('E0', 'E1', 'E2', 'E3'):
        path = os.path.join(ROOT, 'translation', 'generated', 'ADV', f + '.tsv')
        if not os.path.exists(path):
            continue
        for r in strlib.tsv_rows(path, required=('entry', 'box', 'ja', 'en', 'source')):
            ei, k = int(r['entry']), int(r['box'])
            ja, en = r['ja'], r['en']
            if SENTINEL in en:
                bad.append((f'{f}/{ei}/{k}', 'leaked US_BRK sentinel'))
                continue
            r = idx.get((f, ei), {}).get(k)
            us_raw = None
            if r is not None and len(r) > 7 and isinstance(r[7], tuple):
                sf, sei, sk = r[7]
                us_raw = ps.usp_entries(sf)[sei].box_bytes(sk)
            elif r is not None and len(r) > 4 and str(r[4]).isdigit():
                us_raw = ps.usp_entries(f)[ei].box_bytes(int(r[4]))
            if us_raw is None:
                bad.append((f'{f}/{ei}/{k}', 'no US source for generated row'))
                continue
            us_opset = set(us_box_ops(us_raw))
            psx_raw = ps.psx_entries(f)[ei].box_bytes(k)
            ja_opset = set()
            i, n = 0, len(psx_raw)
            while i + 1 < n:
                c = psx_raw[i]
                if c == 0xFF:
                    ja_opset.add(psx_raw[i + 1])
                    i += 2
                elif 0x80 <= c <= 0x87:
                    i += 2
                else:
                    i += 1
            for m in CODE.finditer(en):
                op = int(m.group(1), 16)
                if op in STRUCTURAL or op in us_opset:
                    continue
                # skeleton codes (names / card wrappers / value inserts)
                # ride the JA box by rule: allowed only if the JA box
                # carries them too, never invented.
                if op in (0x06, 0x07, 0x08, 0x0F, 0x11, 0x12) and op in ja_opset:
                    continue
                bad.append((f'{f}/{ei}/{k}',
                            f'op FF{op:02X} in EN but in neither US nor JA box'))
            for m in re.finditer(r'<FF05>(<[0-9A-F]{2}><[0-9A-F]{2}>)', en):
                word = int(m.group(1)[1:3] + m.group(1)[5:7], 16)
                if word not in us_pause_params(us_raw):
                    bad.append((f'{f}/{ei}/{k}',
                                f'FF05 param {word:04X} not from US box'))
                    break
    return bad


def port_talk_units(name):
    d = open(os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR', 'pack', 'talk',
                           name + '.BIN'), 'rb').read()
    h = struct.unpack_from('<6I', d, 0)
    first = struct.unpack_from('<I', d, h[0])[0]
    tab, i = [], h[0]
    while i < first:
        v = struct.unpack_from('<I', d, i)[0]
        if v == 0xFFFFFFFF:
            break
        tab.append(v)
        i += 4
    ends = tab[1:] + [h[1]]
    return [d[s:e] for s, e in zip(tab, ends)]


def check_talk():
    """Same rule for generated TALK rows: every code op in the EN must be
    in the index-paired PSP-US unit or be structural/JA-skeleton."""
    import glob as _glob
    from talk import Talk as _Talk
    bad = []
    for path in sorted(_glob.glob(os.path.join(ROOT, 'translation', 'generated', 'TALK', '*.tsv'))):
        name = os.path.basename(path)[:-4]
        if name in ('ANSWERS', 'ANSWERS_SLOT', 'ERRORS'):
            continue
        t = _Talk(name, open(os.path.join(ROOT, 'data', 'psx', 'TALK', name + '.BIN'), 'rb').read())
        if not t.ok:
            continue
        praw = port_talk_units(name)
        for r in strlib.tsv_rows(path, required=('unit', 'ja', 'en')):
            unit = int(r['unit'])
            en = r['en']
            if SENTINEL in en:
                bad.append((f'{name}/{unit}', 'leaked US_BRK sentinel'))
                continue
            if unit >= len(praw) or unit >= len(t.units):
                continue
            us_opset = set(us_box_ops(praw[unit]))
            ja_opset = set()
            for m in TALK_CODE.finditer(etext.decode(t.units[unit])):
                try:
                    ja_opset.add(int(m.group(1), 16))
                except ValueError:
                    pass
            for m in TALK_CODE.finditer(en):
                try:
                    op = int(m.group(1), 16)
                except ValueError:
                    bad.append((f'{name}/{f[0]}', f'unparseable code {m.group(0)}'))
                    continue
                if op in us_opset:
                    continue
                if op in (0xF5, 0xEF, 0xF6, 0xFC, 0xFB, 0xF7, 0xFD):
                    continue
                if op in ja_opset:
                    continue
                bad.append((f'{name}/{f[0]}', f'op FF{m.group(1)} in EN but untraced'))
    return bad


def main():
    bad = check_adv() + check_talk()
    print(f'marker audit: {len(bad)} violations')
    for loc, msg in bad[:30]:
        print(f'  {loc}: {msg}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
