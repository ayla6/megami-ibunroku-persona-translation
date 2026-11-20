"""English Persona calls in battle: the PSP-US voice in the PSX party's own banks.

  python src/mods/english-dub/battle_voice.py derive   write the call map
  python src/mods/english-dub/battle_voice.py build    write build/B/PS.BIN
  python src/mods/english-dub/battle_voice.py verify   decode build/ back and check
  python src/mods/english-dub/battle_voice.py retail   remove build/B/PS.BIN
  python src/mods/english-dub/battle_voice.py review [DIR]   every call as the game
                                     plays it, JP and English (build/dub_review/battle)

Run by build.py ONLY for --mods=english-dub (build, verify; retail before every
variant). Needs both PSP discs in data/discs: the JP one to find which PSX
call each PSP call is, the US one for the English.

The PSX voice of a battle is a party member's call as it summons its Persona.
A member's sound bank is an entry of B/PS.BIN (BtlLoadMemberBank: the
file's own sector table, by the member's key; an entry is a four-word head
of pointers into BTL_PACK_BUFFER, the VAB body, the VAB header, the SEP and
its end). A member bank's SEP holds seven sub-sequences and the summon plays
one of 3, 4, 5 at random (BtlMemberMotion06: BtlSePlay(3, rand() % 3 + 3)),
each one note of one tone of one VAG. The PSP plays the same calls from
SE_PRS.BIN, three banks of one VAG per character (bank 3(c-1)+r, r random)
- re-recorded, the PSP-JP calls are other takes of the PSX lines.

derive - which PSP character is which PSX bank, and which PSP call which
sub-sequence: the PSP-JP calls against the PSX ones, log-band spectrograms
correlated over small shifts; characters to banks and calls to
sub-sequences are the assignments with the best summed score (identical
banks - the disc stores one twice - are one bank). The map is
translation/generated_mappings/battle_voice.tsv: entry, sub-sequence, VAG,
PSP SE_PRS bank, score.

build - each call becomes its PSP-US take: silence trimmed (TRIM_DB under
its peak, TRIM_KEEP kept), at its own level (the PSP calls are mastered as
the PSX ones: the PSX calls over their PSP-JP takes, median -1.2 dB, within
the takes' own spread - so a call delivered softer or louder stays so) and
encoded to SPU ADPCM in the VAG layout of the disc (a zero block,
the data with the loop-start flag on its first block and the end flag on its
last, a silent repeat block). A bank's three calls share the bytes their JP
calls had: at the JP rate when the English fits, else at the highest rate a
whole semitone lower that does (the tone's centre note moves up with it, so
the call still plays at its own speed), the rest padded with silent blocks.
Every entry keeps its size and every other byte, so the sector table, the
RAM buffer and the SPU allocation are retail.
"""
import argparse
import hashlib
import itertools
import os
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import disc_data  # noqa: E402
import strlib  # noqa: E402
import xa  # noqa: E402
from audio import adpcm_decode, sound_banks  # noqa: E402

PACK = ('B', 'PS.BIN')
SOURCE = os.path.join(ROOT, 'data', 'psx', *PACK)
BUILT = os.path.join(ROOT, 'build', *PACK)
MAP = os.path.join(toolpath.TRANSLATION, 'generated_mappings', 'battle_voice.tsv')
FIELDS = ('entry', 'seq', 'vag', 'psp_bank', 'score')
PSP_CALLS = 'SE_PRS.BIN'
MEMBER_SEPS = 7          # sub-sequences of a member bank (BtlOpenMemberBank)
SUMMON = (3, 4, 5)       # the ones the summon picks from
BASE_RATE = 44100        # a tone plays its VAG at this rate on its centre note
BLOCK = 16
TRIM_DB = 40             # dB under the peak that is silence at a call's ends
TRIM_KEEP = 0.02         # s kept outside it
MIN_SNR = 20             # dB the decoded calls must reach
PEAK_MAX = 0.98          # the loudest call's peak (full scale 1.0)
SPEC_N, SPEC_HOP = 512, 220
LAG = 8                  # frames a call may be shifted against the other


# --- the PSX banks -------------------------------------------------------------

def sector_table(data):
    """Entry starts (sectors) of a pack: u16s from the top while they grow."""
    out = []
    for i in range(len(data) // 2):
        v = struct.unpack_from('<H', data, 2 * i)[0]
        if out and v < out[-1]:
            break
        out.append(v)
    return out


def sep_notes(b):
    """[(sub-sequence id, [(program, note)])] of a SEP (pPES) block."""
    if b[:4] != b'pPES':
        raise ValueError('not a SEP')

    def vlq(i):
        v = 0
        while True:
            c = b2[i]
            i += 1
            v = v << 7 | c & 0x7F
            if not c & 0x80:
                return v, i
    i, out = 6, []
    while i + 13 <= len(b):
        sid = struct.unpack_from('>H', b, i)[0]
        size = struct.unpack_from('>I', b, i + 9)[0]
        b2 = b[i + 13:i + 13 + size]
        notes, prog, status = [], None, 0
        _, j = vlq(0)
        while j < len(b2):
            if b2[j] & 0x80:
                status = b2[j]
                j += 1
            kind = status & 0xF0
            if status == 0xFF:
                meta = b2[j]
                j += 1
                if meta == 0x2F:
                    break
                if meta == 0x51:
                    j += 3
            elif kind == 0xC0:
                prog = b2[j]
                j += 1
            elif kind == 0x90:
                if b2[j + 1]:
                    notes.append((prog, b2[j]))
                j += 2
            elif kind in (0x80, 0xA0, 0xB0, 0xE0):
                j += 2
            elif kind == 0xD0:
                j += 1
            _, j = vlq(j)
        out.append((sid, notes))
        i += 13 + size
    return out


def member_banks(data):
    """[(entry, start, end, bank)] of every member bank of the pack, bank =
    dict(body, vh, sizes (VAG bytes), tones {vag: (offset, note, centre)},
    calls {sub-sequence: vag})."""
    table = sector_table(data)
    out = []
    for e in range(len(table) - 1):
        s, t = table[e] * 2048, table[e + 1] * 2048
        b = data[s:t]
        vb, vh, sq, end = struct.unpack_from('<4I', b, 0)
        base = vb - BLOCK                      # the head is the first 16 bytes
        vb, vh, sq, end = vb - base, vh - base, sq - base, end - base
        if b[vh:vh + 4] != b'pBAV' or b[sq:sq + 4] != b'pPES':
            continue
        seps = sep_notes(b[sq:end])
        if len(seps) != MEMBER_SEPS:
            continue
        progs, _tones, vags = struct.unpack_from('<HHH', b, vh + 0x12)
        tone_at = vh + 0x20 + 0x800
        table_at = tone_at + progs * 0x200
        sizes = [struct.unpack_from('<H', b, table_at + 2 * i)[0] * 8 for i in range(1, vags + 1)]
        tones = {}
        for p in range(progs):
            for i in range(b[vh + 0x20 + 16 * p]):
                at = tone_at + (p * 16 + i) * 32
                lo, hi = b[at + 6], b[at + 7]
                vag = struct.unpack_from('<h', b, at + 0x16)[0]
                tones[(p, lo, hi)] = (at, vag, b[at + 4])
        calls = {}
        for sid, notes in seps:
            if sid in SUMMON:
                (p, n), = notes
                (at, vag, centre), = [v for (tp, lo, hi), v in tones.items()
                                      if tp == p and lo <= n <= hi]
                calls[sid] = dict(vag=vag, tone=at, note=n, centre=centre,
                                  rate=BASE_RATE * 2 ** ((n - centre) / 12))
        used = {v for (tp, lo, hi), (at, v, c) in tones.items()}
        for sid, c in calls.items():
            # a call's tone and VAG are its own: moving them moves nothing else
            if sum(1 for (_p, _l, _h), (_a, v, _c) in tones.items() if v == c['vag']) != 1:
                raise ValueError(f'entry {e}: VAG {c["vag"]} is shared')
        offs = np.cumsum([vb] + sizes)
        out.append((e, s, t, dict(body=vb, table=table_at, sizes=sizes, offsets=offs.tolist(),
                                  calls=calls, used=used)))
    return out


def call_pcm(entry_bytes, bank, sid):
    v = bank['calls'][sid]['vag']
    o = bank['offsets'][v - 1]
    return adpcm_decode(entry_bytes[o:o + bank['sizes'][v - 1]])[0].astype(np.float32)


# --- the PSP calls -------------------------------------------------------------

def psp_calls(region):
    """[(SE_PRS bank, float samples, rate)] of a PSP disc."""
    disc_data.ensure_psp(region)
    path = os.path.join(ROOT, 'data', f'psp_{region}', 'PSP_GAME', 'USRDIR', 'sdata', PSP_CALLS)
    d = open(path, 'rb').read()
    out = []
    for b, (_start, waves, body) in enumerate(sound_banks(d)):
        (off, size, rate), = waves
        out.append((b, adpcm_decode(d[body + off:body + off + size])[0].astype(np.float32), rate))
    return out


def resample(x, rate, to):
    rate, to = int(round(rate)), int(round(to))
    if rate == to:
        return x
    return np.frombuffer(subprocess.run(
        ['ffmpeg', '-v', 'error', '-f', 'f32le', '-ar', str(rate), '-ac', '1', '-i', 'pipe:0',
         '-af', 'aresample=resampler=soxr', '-ar', str(to), '-f', 'f32le', 'pipe:1'],
        input=np.ascontiguousarray(x, np.float32).tobytes(), capture_output=True,
        check=True).stdout, np.float32)


def spectrogram(x, rate):
    """Log band energies (24 bands 150 Hz..10 kHz), voiced frames only."""
    x = resample(x, rate, 22050)
    x = x / (np.abs(x).max() + 1e-9)
    if len(x) < SPEC_N:
        x = np.pad(x, (0, SPEC_N - len(x)))
    f = np.lib.stride_tricks.sliding_window_view(x, SPEC_N)[::SPEC_HOP] * np.hanning(SPEC_N)
    p = np.abs(np.fft.rfft(f, axis=1)) ** 2
    fr = np.fft.rfftfreq(SPEC_N, 1 / 22050)
    edges = np.geomspace(150, 10000, 25)
    s = np.log10(np.stack([p[:, (fr >= a) & (fr < b)].sum(1) for a, b in zip(edges[:-1], edges[1:])], 1) + 1e-6)
    e = s.max(1)
    on = np.where(e > e.max() - 4)[0]
    return s[on[0]:on[-1] + 1]


def likeness(a, b):
    best = -1.0
    for lag in range(-LAG, LAG + 1):
        x, y = (a[lag:], b) if lag >= 0 else (a, b[-lag:])
        m = min(len(x), len(y))
        if m < 0.7 * max(len(a), len(b)):
            continue
        u, v = x[:m].ravel() - x[:m].mean(), y[:m].ravel() - y[:m].mean()
        best = max(best, float(u @ v / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9)))
    return best


def best_pairing(scores):
    """(total, permutation) maximising sum(scores[i][perm[i]])."""
    n = len(scores)
    return max((sum(scores[i][p[i]] for i in range(n)), p) for p in itertools.permutations(range(n)))


# --- derive --------------------------------------------------------------------

def derive():
    data = open(SOURCE, 'rb').read()
    banks = member_banks(data)
    # one bank stored twice is one bank
    unique, twins = [], {}
    for e, s, t, bank in banks:
        same = next((u for u in unique if data[u[1]:u[2]] == data[s:t]), None)
        if same:
            twins[e] = same[0]
        else:
            unique.append((e, s, t, bank))
    jp = psp_calls('jp')
    groups = [jp[i:i + len(SUMMON)] for i in range(0, len(jp), len(SUMMON))]
    if len(groups) != len(unique):
        raise ValueError(f'{len(groups)} PSP characters, {len(unique)} PSX member banks')
    specs = {(e, sid): spectrogram(call_pcm(data[s:t], bank, sid), bank['calls'][sid]['rate'])
             for e, s, t, bank in unique for sid in SUMMON}
    pair = {}
    for g, calls in enumerate(groups):
        js = [spectrogram(x, rate) for _b, x, rate in calls]
        for e, _s, _t, _bank in unique:
            m = [[likeness(j, specs[(e, sid)]) for sid in SUMMON] for j in js]
            pair[(g, e)] = best_pairing(m), m
    entries = [u[0] for u in unique]
    total, perm = max((sum(pair[(g, entries[p[g]])][0][0] for g in range(len(groups))), p)
                      for p in itertools.permutations(range(len(entries))))
    rows = {}
    for g, k in enumerate(perm):
        e = entries[k]
        (_tot, order), m = pair[(g, e)]
        for i, (b, _x, _r) in enumerate(groups[g]):
            sid = SUMMON[order[i]]
            for entry in [e] + [t for t, src in twins.items() if src == e]:
                bank = next(bk for ee, _s, _t, bk in banks if ee == entry)
                rows[(entry, sid)] = (bank['calls'][sid]['vag'], b, m[i][order[i]])
        print(f'battle_voice: PSP character {g + 1} -> PS.BIN entry {e}, '
              f'calls {[round(m[i][order[i]], 2) for i in range(len(order))]}')
    with open(MAP, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\t'.join(FIELDS) + '\n')
        for (e, sid), (vag, b, score) in sorted(rows.items()):
            f.write(f'{e}\t{sid}\t{vag}\t{b}\t{score:.3f}\n')
    print(f'battle_voice: wrote {os.path.relpath(MAP, ROOT)} ({len(rows)} calls, '
          f'mean likeness {total / len(groups) / len(SUMMON):.2f})')


def read_map():
    return {(int(r['entry']), int(r['seq'])): int(r['psp_bank'])
            for r in strlib.tsv_rows(MAP, required=FIELDS)}


# --- build ---------------------------------------------------------------------

def trimmed(x, rate):
    a = np.abs(x)
    on = np.where(a > a.max() * 10 ** (-TRIM_DB / 20))[0]
    keep = int(TRIM_KEEP * rate)
    return x[max(0, on[0] - keep):on[-1] + 1 + keep]


SPU_FILTERS = xa.FILTERS + ((122, -60),)      # the SPU has a fifth predictor


def encode_block(x, s1, s2):
    """One 28-sample block, closed loop: every filter at the smallest shift
    that holds its residual and the one under it. (param, nibbles, s1, s2)."""
    best = None
    for f, (k0, k1) in enumerate(SPU_FILTERS):
        # the open-loop residual sets the shift to try
        p1, p2, peak = s1, s2, 0
        for v in x:
            peak = max(peak, abs(v - (p1 * k0 + p2 * k1) / 64))
            p2, p1 = p1, v
        need = int(np.ceil(np.log2(max(peak, 1) / 7)))
        for r in {min(12, max(0, 12 - need)), min(12, max(0, 13 - need))}:
            step = 1 << (12 - r)
            a1, a2, err, nib = s1, s2, 0, []
            for v in x:
                pred = (a1 * k0 + a2 * k1 + 32) >> 6
                q = int(round((v - pred) / step))
                q = -8 if q < -8 else 7 if q > 7 else q
                d = (((q << 12) if q >= 0 else ((q << 12) & 0xFFFF) - 0x10000) >> r) + pred
                d = -32768 if d < -32768 else 32767 if d > 32767 else d
                err += (v - d) ** 2
                nib.append(q & 0xF)
                a2, a1 = a1, d
            if best is None or err < best[0]:
                best = (err, f << 4 | r, nib, a1, a2)
    return best[1:]


def vag_bytes(pcm16):
    """SPU ADPCM in the disc's VAG layout."""
    n = -(-len(pcm16) // xa.UNIT) * xa.UNIT
    pcm = np.pad(pcm16, (0, n - len(pcm16))).astype(int).tolist()
    out = bytearray(BLOCK)                                    # the zero block
    s1 = s2 = 0
    last = n // xa.UNIT - 1
    for k in range(n // xa.UNIT):
        param, nib, s1, s2 = encode_block(pcm[k * xa.UNIT:(k + 1) * xa.UNIT], s1, s2)
        flags = (4 if k == 0 else 0) | (1 if k == last else 0)
        out += bytes([param, flags]) + bytes(nib[i] | nib[i + 1] << 4 for i in range(0, xa.UNIT, 2))
    out += bytes([0, 7]) + bytes([7]) * 14                    # the silent repeat block
    return bytes(out)


def english(bank, us):
    """{sub-sequence: (pcm float at 1.0 = full scale, rate, PSP bank)}: the
    bank's PSP-US calls, trimmed, at their own level - the PSP calls are
    mastered as the PSX ones are (the PSX calls over their PSP-JP takes:
    median -1.2 dB, within the takes' own +-2 dB), so no gain; a bank whose
    loudest call would pass full scale is lowered as a whole (its calls keep
    their proportions)."""
    m = read_map()
    calls = {sid: us[m[(bank['entry'], sid)]] for sid in SUMMON}
    calls = {sid: (trimmed(x / 32768, rate), rate, b) for sid, (b, x, rate) in calls.items()}
    peak = max(float(np.abs(x).max()) for x, _r, _b in calls.values())
    gain = min(1.0, PEAK_MAX / max(peak, 1e-9))
    return {sid: (x * gain, rate, b) for sid, (x, rate, b) in calls.items()}


def render(data):
    """The pack with every member bank's calls in English, and a report."""
    out = bytearray(data)
    us = {b: (b, x, rate) for b, x, rate in psp_calls('us')}

    lines = []
    for e, s, t, bank in member_banks(data):
        bank['entry'] = e
        entry = bytearray(data[s:t])
        calls = english(bank, us)
        budget = sum(bank['sizes'][bank['calls'][sid]['vag'] - 1] for sid in SUMMON) // BLOCK
        jp_rate = min(c['rate'] for c in bank['calls'].values())
        step = 0
        while True:
            rate = jp_rate * 2 ** (-step / 12)
            coded = {sid: vag_bytes(np.clip(np.round(resample(x, r, int(round(rate))) * 32767),
                                            -32768, 32767).astype(np.int16))
                     for sid, (x, r, _b) in calls.items()}
            if sum(len(c) for c in coded.values()) <= budget * BLOCK:
                break
            step += 1
        # the calls go back where the JP ones were, in their order on disc
        order = sorted(SUMMON, key=lambda sid: bank['calls'][sid]['vag'])
        spare = budget * BLOCK - sum(len(c) for c in coded.values())
        coded[order[-1]] += bytes(spare)                       # silent blocks
        sizes = list(bank['sizes'])
        for sid in SUMMON:
            c = bank['calls'][sid]
            sizes[c['vag'] - 1] = len(coded[sid])
            # the tone's centre moves up by the semitones the rate went down
            entry[c['tone'] + 4] = c['centre'] + step
        offs = np.cumsum([bank['body']] + sizes).tolist()
        # the calls' VAGs and whatever lies between them shift together
        first, last = min(bank['calls'][sid]['vag'] for sid in SUMMON), \
            max(bank['calls'][sid]['vag'] for sid in SUMMON)
        old = bank['offsets']
        for v in range(first, last + 1):
            sid = next((sid for sid in SUMMON if bank['calls'][sid]['vag'] == v), None)
            piece = coded[sid] if sid is not None else data[s + old[v - 1]:s + old[v]]
            entry[offs[v - 1]:offs[v - 1] + len(piece)] = piece
        if offs[last] != old[last]:
            raise AssertionError(f'entry {e}: the calls moved the VAGs after them')
        for i, size in enumerate(sizes, 1):
            struct.pack_into('<H', entry, bank['table'] + 2 * i, size // 8)
        out[s:t] = entry
        lines.append(f'entry {e}: {len(SUMMON)} calls at {rate:.0f} Hz '
                     f'({step} semitone{"s" * (step != 1)} under the JP), '
                     f'{spare // BLOCK} spare blocks')
    return bytes(out), lines


# THE CALLS CACHE: the English pack is a pure function of this code, the
# retail pack, the call map and the PSP-US calls, so it is rendered once and
# kept (build/step_cache/battle-voice/PS.BIN, with PS.tsv vouching for it:
# the key, the bytes' SHA-1, whether verify passed them and the report). A
# build with nothing changed writes the cached bytes; verify skips the decode
# of a pack that is exactly the bytes it already passed.
CACHE = os.path.join(ROOT, 'build', 'step_cache', 'battle-voice')
CACHE_BIN = os.path.join(CACHE, 'PS.BIN')
CACHE_TSV = os.path.join(CACHE, 'PS.tsv')


def cache_key():
    import build_step_cache
    psp = [os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR', 'sdata', PSP_CALLS)]
    return build_step_cache.fingerprint(
        [toolpath.script(name) for name in ('battle_voice.py', 'xa.py', 'build_step_cache.py')]
        + [os.path.join(ROOT, 'src', 'extraction', 'psp', 'audio.py'), SOURCE] + psp,
        context=(np.__version__, build_step_cache._digest(Path(MAP))))


def cache_record():
    try:
        with open(CACHE_TSV, encoding='utf-8') as f:
            rows = [line.rstrip('\n').split('\t', 1) for line in f]
    except OSError:
        return {}
    if rows[:1] != [['field', 'value']]:
        return {}
    return dict(r for r in rows[1:] if len(r) == 2)


def cache_write(record):
    os.makedirs(CACHE, exist_ok=True)
    with open(CACHE_TSV + '.tmp', 'w', encoding='utf-8') as f:
        f.write('field\tvalue\n')
        for field in ('key', 'sha1', 'verified', 'report'):
            f.write(f'{field}\t{record[field]}\n')
    os.replace(CACHE_TSV + '.tmp', CACHE_TSV)


def build():
    if not os.path.exists(MAP):
        derive()
    disc_data.ensure_psp('us')                  # the PSP calls: part of the key
    key = cache_key()
    record = cache_record()
    built = None
    if record.get('key') == key:
        try:
            data = open(CACHE_BIN, 'rb').read()
        except OSError:
            data = None
        if data is not None and hashlib.sha1(data).hexdigest() == record.get('sha1'):
            built, lines = data, record['report'].split(' | ')
            lines = [line + ' (cached)' for line in lines]
    if built is None:
        built, lines = render(open(SOURCE, 'rb').read())
        if cache_key() == key:                  # no input moved while rendering
            os.makedirs(CACHE, exist_ok=True)
            with open(CACHE_BIN + '.tmp', 'wb') as f:
                f.write(built)
            os.replace(CACHE_BIN + '.tmp', CACHE_BIN)
            cache_write({'key': key, 'sha1': hashlib.sha1(built).hexdigest(),
                         'verified': 0, 'report': ' | '.join(lines)})
    os.makedirs(os.path.dirname(BUILT), exist_ok=True)
    with open(BUILT, 'wb') as f:
        f.write(built)
    for line in lines:
        print(f'battle_voice: {line}')


def verify():
    """The pack is retail outside the calls, their tones and the VAG size
    tables, every call decodes to its English within MIN_SNR, and plays at
    the English's own speed."""
    data = open(SOURCE, 'rb').read()
    got = open(BUILT, 'rb').read()
    key, record = cache_key(), cache_record()
    sha1 = hashlib.sha1(got).hexdigest()
    if (record.get('key') == key and record.get('sha1') == sha1
            and record.get('verified') == '1'):
        print('battle_voice: B/PS.BIN ok (the cached pack verified earlier)')
        return
    want, _lines = render(data)
    bad = 0
    if got != want:
        bad += 1
        print('FAIL B/PS.BIN: not what build writes')
    if len(got) != len(data):
        bad += 1
        print(f'FAIL B/PS.BIN: {len(got)} bytes, retail {len(data)}')
    us = {b: (b, x, rate) for b, x, rate in psp_calls('us')}

    old = {e: bank for e, _s, _t, bank in member_banks(data)}
    for e, s, t, bank in member_banks(got):
        ob = old[e]
        allowed = np.zeros(t - s, bool)
        allowed[ob['body']:ob['offsets'][-1]] = True
        allowed[ob['table']:ob['table'] + 512] = True
        for c in ob['calls'].values():
            allowed[c['tone'] + 4] = True
        diff = np.frombuffer(got[s:t], np.uint8) != np.frombuffer(data[s:t], np.uint8)
        if (diff & ~allowed).any():
            bad += 1
            print(f'FAIL entry {e}: changed outside the calls')
        for v in range(1, len(ob['sizes']) + 1):
            if v not in {c['vag'] for c in ob['calls'].values()} and \
                    got[s + bank['offsets'][v - 1]:s + bank['offsets'][v]] != \
                    data[s + ob['offsets'][v - 1]:s + ob['offsets'][v]]:
                bad += 1
                print(f'FAIL entry {e}: VAG {v} is not retail')
        ob['entry'] = e
        calls = english(ob, us)
        for sid, (x, rate, b) in calls.items():
            c = bank['calls'][sid]
            dec = call_pcm(got[s:t], bank, sid)[xa.UNIT:] / 32768     # past the zero block
            ref = resample(x, rate, int(round(c['rate'])))
            n = min(len(dec), len(ref))
            snr = 10 * np.log10(np.sum(ref[:n] ** 2) / max(np.sum((dec[:n] - ref[:n]) ** 2), 1e-12))
            if snr < MIN_SNR or abs(len(ref) - n) > xa.UNIT:
                bad += 1
                print(f'FAIL entry {e} call {sid}: SNR {snr:.1f} dB, {len(dec)} vs {len(ref)} samples')
    if bad:
        raise SystemExit(f'battle_voice: {bad} failure(s)')
    print('battle_voice: B/PS.BIN ok')
    if record.get('key') == key and record.get('sha1') == sha1:
        record['verified'] = 1
        cache_write(record)


def review(out):
    """<out>/entryEE_seqS_jp.wav and _en.wav: each call of build/B/PS.BIN
    and of the retail pack, decoded at the rate its tone plays it."""
    import wave
    os.makedirs(out, exist_ok=True)
    for name, path in (('jp', SOURCE), ('en', BUILT)):
        data = open(path, 'rb').read()
        for e, s, t, bank in member_banks(data):
            for sid in SUMMON:
                pcm = call_pcm(data[s:t], bank, sid).astype(np.int16)
                with wave.open(os.path.join(out, f'entry{e:02d}_seq{sid}_{name}.wav'), 'wb') as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(int(round(bank['calls'][sid]['rate'])))
                    w.writeframes(pcm.tobytes())
    print(f'battle_voice: review in {os.path.relpath(out, ROOT)}')


def retail():
    if os.path.exists(BUILT):
        os.unlink(BUILT)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cmd', choices=('derive', 'build', 'verify', 'retail', 'review'))
    ap.add_argument('out', nargs='?', default=os.path.join(ROOT, 'build', 'dub_review', 'battle'),
                    help='review: the folder to write')
    a = ap.parse_args()
    if a.cmd == 'review':
        review(a.out)
    else:
        {'derive': derive, 'build': build, 'verify': verify, 'retail': retail}[a.cmd]()


if __name__ == '__main__':
    main()
