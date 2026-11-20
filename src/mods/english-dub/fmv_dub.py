"""English dub of the spoken movies: the PSP-US voice, laid onto the JP movies.

  python src/mods/english-dub/fmv_dub.py build     write build/STR*/MVxx.STR
  python src/mods/english-dub/fmv_dub.py verify    decode build/ back and check
  python src/mods/english-dub/fmv_dub.py retail    remove the dubbed STRs
  python src/mods/english-dub/fmv_dub.py review [DIR]   the movies with dub, JP
                                                  and subtitles (build/dub_review)

Run by build.py ONLY for --mods=english-dub (build, verify; retail before every
variant). Only the STR's XA audio sectors change: the video, the sector
layout, the subheaders and the movie player are retail. An STR that is a
sector-for-sector copy of a dubbed one (the disc stores MV14 twice) gets the
same dub. Needs the PSP-US disc in data/discs (the movie audio is extracted
from it on first use, src/extraction/psp/audio.py).

The map, translation/generated_mappings/fmv_dub.tsv, is set by ear in
src/mods/english-dub/dub_editor.py: per movie its PSP movie and its pieces (seconds) - the
PSP English from en_start to en_end, played with en_start at jp_start, fading
in over en_lead before it and out over en_trail after it (equal power; a
piece with neither fades over EDGE_FADE at its own edges); mute_from/mute_to
is PSP English silenced before anything is laid in. jp_end, en_cut and
manual are the editor's.

The movie keeps its own (PSX) audio - score, sound effects, everything
around the voice - as the complement of the English: gone under the voice,
so no JP is heard, crossfading back over every fade, and whole wherever no
English plays. The PSP English keeps its own levels and takes one gain: the
difference between the PSX master and the PSP's, measured on the same
Japanese voice (psp_gain: the PSX movie against the PSP-JP one over the
subtitle rows), so a line the English cast delivered softer or louder than
the Japanese stays so. The mix is written over the STR's own audio sectors (xa.py).
"""
import argparse
import csv
from collections import Counter
from functools import lru_cache
from pathlib import Path
import hashlib
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import cdsector  # noqa: E402
import disc_data  # noqa: E402
import build_step_cache  # noqa: E402  (stamp, clone)
import strlib  # noqa: E402
import xa  # noqa: E402

MAP = os.path.join(toolpath.TRANSLATION, 'generated_mappings', 'fmv_dub.tsv')
SUBTITLES = os.path.join(toolpath.TRANSLATION, 'manual', 'fmv', 'subtitles.tsv')
PSP_AUDIO = os.path.join(ROOT, 'data', 'psp_audio', 'movie')
BUILD = os.path.join(ROOT, 'build')
XA_RATE = 37800         # the STR's XA: coding 0x01 = 37.8 kHz stereo 4-bit
EDGE_FADE = 0.12        # s a piece with no lead-in or tail fades over at its own edges
MUTE_FADE = 0.03        # s a muted stretch of the PSP fades over
MIN_SNR = 20            # dB the decoded XA must reach against the track


# --- inputs ------------------------------------------------------------------

def str_index(image):
    """{movie: (path in the disc tree, lba, sectors)} of every STR file."""
    out = {}
    with open(image, 'rb') as f:
        def user(n):
            f.seek(n * cdsector.SECTOR + 24)
            return f.read(2048)

        def entries(lba, size):
            for s in range((size + 2047) // 2048):
                d, i = user(lba + s), 0
                while i < 2048 and d[i]:
                    e = d[i:i + d[i]]
                    name = e[33:33 + e[32]]
                    if name not in (b'\0', b'\1'):
                        yield (name.decode('ascii').split(';')[0],
                               struct.unpack_from('<I', e, 2)[0],
                               struct.unpack_from('<I', e, 10)[0], e[25] & 2)
                    i += d[i]
        root = user(16)[156:190]
        for name, lba, size, is_dir in entries(struct.unpack_from('<I', root, 2)[0],
                                               struct.unpack_from('<I', root, 10)[0]):
            if is_dir:
                for fname, flba, fsize, _ in entries(lba, size):
                    if fname.upper().endswith('.STR'):
                        out[fname[:-4].upper()] = (f'{name}/{fname}', flba, (fsize + 2047) // 2048)
    return out


def str_sectors(image, lba, count):
    with open(image, 'rb') as f:
        f.seek(lba * cdsector.SECTOR)
        return bytearray(f.read(count * cdsector.SECTOR))


def psp_track(mv, rate, region='us'):
    """The PSP movie's audio at `rate`: the PSP-US English (region 'us') or
    the PSP-JP Japanese (the dub's level reference, psp_gain)."""
    folder = PSP_AUDIO if region == 'us' else PSP_AUDIO + '_' + region
    path = os.path.join(folder, mv + '.flac')
    if not os.path.exists(path):
        disc_data.ensure_psp(region)
        import audio
        audio.extract_movies(os.path.dirname(PSP_AUDIO), region)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ar', str(rate), '-ac', '2',
                          '-f', 'f32le', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2)


def retail_audio(image, lba, count, rate, channels):
    raw = bytes(str_sectors(image, lba, count))
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'psxstr', '-i', 'pipe:0', '-map', '0:a',
                          '-ar', str(rate), '-ac', str(channels), '-f', 'f32le', 'pipe:1'],
                         input=raw, capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.float32).reshape(-1, channels)


def psp_movies():
    if not os.path.isdir(PSP_AUDIO) or not os.listdir(PSP_AUDIO):
        psp_track('MV00', XA_RATE)               # extracts them all
    return sorted(os.path.splitext(f)[0] for f in os.listdir(PSP_AUDIO) if f.endswith('.flac'))


FIELDS = ('psp', 'jp_start', 'jp_end', 'en_start', 'en_end', 'en_cut', 'en_lead',
          'en_trail', 'mute_from', 'mute_to', 'manual')


def map_rows():
    """{(movie, line): {field: text}} of the line map, empty when there is none."""
    if not os.path.exists(MAP):
        return {}
    return {(r['movie'], int(r['line'])): {f: (r.get(f) or '').strip() for f in FIELDS}
            for r in strlib.tsv_rows(MAP, required=('movie', 'line'))}


def write_map(rows):
    """Write the line map: {(movie, line): {field: text}}."""
    with open(MAP, 'w', encoding='utf-8', newline='\n') as f:
        f.write('movie\tline\t' + '\t'.join(FIELDS) + '\n')
        for (mv, k), r in sorted(rows.items()):
            f.write(f'{mv}\t{k}\t' + '\t'.join(r.get(c, '') for c in FIELDS) + '\n')


def read_map():
    """{movie: (PSP movie, [(jp start, jp end, en start, en end, cut, lead,
    trail, mute from, mute to, manual)])}."""
    out = {}
    for (mv, _k), r in sorted(map_rows().items()):
        out.setdefault(mv, (r['psp'], []))[1].append(
            tuple(float(r[c]) for c in ('jp_start', 'jp_end', 'en_start', 'en_end'))
            + (r['en_cut'] == '1', float(r['en_lead']), float(r['en_trail']),
               float(r['mute_from']), float(r['mute_to']), r.get('manual') == '1'))
    if not out:
        raise FileNotFoundError(MAP)
    return {mv: (psp, sorted(lines)) for mv, (psp, lines) in out.items()}


# --- build -------------------------------------------------------------------

def placements(lines):
    """[(movie time the piece starts, PSP start, PSP end, movie time of its
    voice start, of its voice end, JP end)] per piece of the map."""
    return [(js - lead, es - lead, ee + trail, js, js + (ee - es), je)
            for js, je, es, ee, _cut, lead, trail, *_rest in sorted(lines)]


def level(x, spans, rate):
    sel = np.concatenate([x[int(a * rate):int(b * rate)] for a, b in spans])
    return float(np.sqrt(np.mean(sel ** 2)) + 1e-9)


def ramp_to(n, rising):
    if n <= 0:
        return np.zeros(0, np.float32)
    r = np.sin(np.linspace(0, np.pi / 2, n, dtype=np.float32)) ** 2
    return r if rising else r[::-1]


def psp_gain(mv, retail, jp, lines):
    """The PSP-US track's gain into the movie: how much quieter the PSX
    master is than the PSP's, measured on the same Japanese voice - the
    median over the movie's subtitle rows (subtitles.tsv, the JP voice's
    timing) of the PSX level over the PSP-JP level there, each row read at
    its place in the PSP timeline (the piece that holds it, else the
    nearest). One gain for the whole English track: a line the English
    cast delivered softer or louder than the Japanese stays so."""
    pieces = placements(lines)
    ratios = []
    # Gain uses voice-cue timing even when no subtitle wording is enabled.
    for r in strlib.tsv_rows(SUBTITLES, required=('movie', 'start_s', 'end_s')):
        if r['movie'] != mv:
            continue
        a, b = float(r['start_s']), float(r['end_s'])
        at, p0, *_rest = min(pieces, key=lambda p: 0 if p[0] <= a <= p[0] + (p[2] - p[1])
                             else min(abs(a - p[0]), abs(a - p[0] - (p[2] - p[1]))))
        q0, q1 = a - at + p0, b - at + p0
        if q0 < 0 or q1 * XA_RATE > len(jp) or b * XA_RATE > len(retail):
            continue
        ratios.append(level(retail, [(a, b)], XA_RATE) / level(jp, [(q0, q1)], XA_RATE))
    if not ratios:
        raise SystemExit(f'fmv_dub: {mv}: no subtitle row lies in the PSP-JP movie '
                         f'to measure the level by')
    return float(np.median(ratios))


def mix(retail, track, lines, gain):
    """The retail audio with the English pieces laid in (module doc)."""
    track = track.copy()
    ramp = int(MUTE_FADE * XA_RATE)
    for *_l, m0, m1 in lines:
        if m1 > m0:
            # English no row holds is gone from the PSP before anything is
            # laid in: no margin or fade can carry it
            a, b = int(round(m0 * XA_RATE)), int(round(m1 * XA_RATE))
            track[max(0, a):b] = 0
            if a > 0:
                track[max(0, a - ramp):a] *= ramp_to(min(ramp, a), False)[:, None]
            track[b:b + ramp] *= ramp_to(len(track[b:b + ramp]), True)[:, None]
    pieces = placements(lines)
    n = len(retail)
    psp = np.zeros_like(retail)
    pw = np.zeros(n, np.float32)              # weight of the English
    sec = lambda t: int(round(t * XA_RATE))
    for at, p0, p1, v0, v1, _span_end in pieces:
        a, b = sec(at), sec(at + (p1 - p0))
        src0 = sec(p0)
        lo, hi = max(0, a), min(n, b)
        take = track[src0 + (lo - a):src0 + (hi - a)] * gain
        hi = lo + len(take)
        if hi <= lo:
            continue
        w = np.ones(hi - lo, np.float32)
        # the voice is always whole: the fades are the margins around it, the
        # lead-in fading in and the tail fading out over their whole length
        # (a piece with no margin fades over EDGE_FADE at its own edges)
        fin = max(0, sec(v0) - lo) or min(sec(EDGE_FADE), (hi - lo) // 2)
        fout = max(0, hi - sec(v1)) or min(sec(EDGE_FADE), (hi - lo) // 2)
        w[:fin] = ramp_to(fin, True)
        if fout:
            w[len(w) - fout:] = ramp_to(fout, False)
        psp[lo:hi] += take * w[:, None]
        pw[lo:hi] = np.maximum(pw[lo:hi], w)
    # the PSX audio fills whatever the English leaves: none under the voice,
    # crossfading over the fades, all of it where no English plays
    out = retail * (1 - pw)[:, None] + psp
    return out, gain


def audio_layout(raw):
    """(audio sector indices, channels) of a raw STR."""
    idx = [i for i in range(len(raw) // cdsector.SECTOR)
           if raw[i * cdsector.SECTOR + 18] & 0x04]
    codings = {raw[i * cdsector.SECTOR + 19] for i in idx}
    if codings != {0x01}:
        raise ValueError(f'XA coding {sorted(codings)}: only 37.8 kHz stereo 4-bit (0x01) is handled')
    return idx, 2


def render(image, mv, psp, lba, count, lines):
    """(raw STR bytes, intended PCM at the XA rate, report) for one movie."""
    raw = str_sectors(image, lba, count)
    idx, channels = audio_layout(raw)
    need = len(idx) * xa.samples_per_sector(channels)
    retail = retail_audio(image, lba, count, XA_RATE, channels)
    retail = retail[:need] if len(retail) >= need else np.pad(retail, ((0, need - len(retail)), (0, 0)))
    track = psp_track(psp, XA_RATE)
    gain = psp_gain(mv, retail, psp_track(psp, XA_RATE, 'jp'), lines)
    dub, gain = mix(retail, track, lines, gain)
    peak = float(np.abs(dub).max())
    pcm16 = np.clip(np.round(dub * 32767), -32768, 32767).astype(np.int16)
    for i, payload in zip(idx, xa.encode_sectors(pcm16, channels)):
        o = i * cdsector.SECTOR
        raw[o + 24:o + 24 + xa.SECTOR_DATA] = payload
        raw[o + 2348:o + 2352] = b'\0\0\0\0'          # retail leaves the Form 2 EDC unused
    report = (f'{len(lines)} pieces from PSP {psp}, PSP gain {20 * np.log10(gain):+.1f} dB, '
              f'peak {20 * np.log10(max(peak, 1e-9)):+.1f} dBFS')
    return bytes(raw), pcm16, report


@lru_cache(maxsize=2)
def _copy_map(image: str, identity: tuple[int, ...],
              entries: tuple[tuple[str, tuple[str, int, int]], ...]) -> dict[str, list[str]]:
    """Discover retail twins once per image identity, with a verified disk cache."""
    table = Path(CACHE) / 'copies.tsv'

    def discover() -> None:
        groups: dict[int, list[tuple[str, str, bytes]]] = {}
        rows: list[tuple[str, str]] = []
        counts = Counter(entry[1][2] for entry in entries)
        for movie, (relative, lba, count) in entries:
            if counts[count] < 2:
                continue
            raw = str_sectors(image, lba, count)
            body = b''.join(raw[o + 16:o + cdsector.SECTOR]
                            for o in range(0, len(raw), cdsector.SECTOR))
            group = groups.setdefault(count, [])
            for other, other_path, other_body in group:
                if body == other_body:
                    rows.extend(((movie, other_path), (other, relative)))
            group.append((movie, relative, body))
        table.parent.mkdir(parents=True, exist_ok=True)
        with table.open('w', newline='') as stream:
            writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
            writer.writerow(('movie', 'copy'))
            writer.writerows(rows)

    build_step_cache.run('retail movie twins', [Path(image), Path(__file__)],
                         [table], discover, Path(CACHE) / 'copies-inputs.tsv',
                         context=(repr(entries), str(cdsector.SECTOR)))
    result: dict[str, list[str]] = {}
    with table.open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != ['movie', 'copy']:
            raise ValueError('invalid retail movie twins map')
        for row in reader:
            result.setdefault(row['movie'], []).append(row['copy'])
    return result


def copies(image, index, movie):
    """Other paths with identical retail sector bodies; no repeat movie reads."""
    import file_digest
    identity = file_digest.signature(Path(image))
    return list(_copy_map(os.path.realpath(image), identity,
                          tuple(sorted(index.items()))).get(movie, ()))


# THE DUB CACHE: a dubbed movie is a pure function of this code, the
# movie's retail sectors, its PSP audio and its map row, so it is rendered
# once and kept (build/step_cache/fmv-dub/<MV>.STR, with <MV>.tsv vouching
# for it: the key, the bytes' SHA-1, the file's size and mtime when it was
# hashed, and whether verify passed them). A build with nothing changed reads
# nothing big: the retail sectors' digest is remembered per disc image
# (retail.tsv, by the image's size and mtime), the cached movie is trusted
# while its size and mtime are the ones it was hashed at, and it reaches
# build/ as a copy-on-write clone (no bytes copied where the filesystem has
# clones). Verify skips the decode of a file that is exactly the bytes it
# already passed.
CACHE = os.path.join(BUILD, 'step_cache', 'fmv-dub')


def movie_key(retail_sha1, psp, lines):
    """What one dubbed movie depends on (the bytes of the code, the retail
    movie - its SHA-1 - and the PSP track, and the map row)."""
    import render_inputs
    code = render_inputs.fingerprint(render, context=(np.__version__,),
                                     data_globals=frozenset({'SUBTITLES', 'PSP_AUDIO'}))
    h = hashlib.sha1()
    for part in (code, retail_sha1, psp, repr(lines)):
        h.update(str(part).encode('utf-8') + b'\0')
    for track in (os.path.join(PSP_AUDIO, psp + '.flac'),
                  os.path.join(PSP_AUDIO + '_jp', psp + '.flac')):
        h.update(build_step_cache._digest(__import__('pathlib').Path(track)).encode()
                 if os.path.exists(track) else b'missing')
    timing = [(row['movie'], float(row['start_s']), float(row['end_s']))
              for row in strlib.tsv_rows(SUBTITLES, required=('movie', 'start_s', 'end_s'))]
    h.update(repr(timing).encode('utf-8'))
    return h.hexdigest()


def retail_sha1(image, lba, count):
    """SHA-1 of a movie's retail sectors, remembered per image (retail.tsv:
    image path, its stamp, lba, count, digest) - the image never changes, so
    its 700 MB are not read again on every build."""
    memo = os.path.join(CACHE, 'retail.tsv')
    ident = f'{os.path.realpath(image)}\t{build_step_cache.stamp(image)}\t{lba}\t{count}'
    known = {}
    try:
        with open(memo, encoding='utf-8') as f:
            for line in f:
                head, _tab, digest = line.rstrip('\n').rpartition('\t')
                known[head] = digest
    except OSError:
        pass
    if ident not in known:
        known[ident] = hashlib.sha1(bytes(str_sectors(image, lba, count))).hexdigest()
        os.makedirs(CACHE, exist_ok=True)
        with open(memo + '.tmp', 'w', encoding='utf-8') as f:
            f.writelines(f'{head}\t{digest}\n' for head, digest in known.items())
        os.replace(memo + '.tmp', memo)
    return known[ident]


def cache_record(mv):
    try:
        with open(os.path.join(CACHE, mv + '.tsv'), encoding='utf-8') as f:
            rows = [line.rstrip('\n').split('\t') for line in f]
    except OSError:
        return {}
    return dict(r for r in rows[1:] if len(r) == 2) if rows[:1] == [['field', 'value']] else {}


def cache_write(mv, record):
    os.makedirs(CACHE, exist_ok=True)
    tmp = os.path.join(CACHE, mv + '.tsv.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('field\tvalue\n')
        for field in ('key', 'sha1', 'stamp', 'verified', 'report'):
            f.write(f'{field}\t{record.get(field, "")}\n')
    os.replace(tmp, os.path.join(CACHE, mv + '.tsv'))


def cached(mv, key):
    """(path, report) of the cached dub for key, or None. The file is hashed
    only when its size or mtime moved since it was last vouched for."""
    record = cache_record(mv)
    if record.get('key') != key:
        return None
    path = os.path.join(CACHE, mv + '.STR')
    try:
        now = build_step_cache.stamp(path)
    except OSError:
        return None
    if record.get('stamp') != now:
        if hashlib.sha1(open(path, 'rb').read()).hexdigest() != record.get('sha1'):
            return None
        record['stamp'] = now
        cache_write(mv, record)
    return path, record.get('report', '')


def build():
    image = disc_data.resolve_psx()
    index = str_index(image)
    mapping = read_map()
    wanted = {path for mv in mapping for path in
              [index[mv][0]] + copies(image, index, mv)}
    # An edited declaration can remove a dub too. Keep selected outputs only;
    # ordinary variant changes need not delete and recopy unchanged movies.
    for rel, _lba, _count in index.values():
        dest = os.path.join(BUILD, *rel.split('/'))
        if rel not in wanted and os.path.exists(dest):
            os.unlink(dest)
    for mv, (psp, lines) in mapping.items():
        rel, lba, count = index[mv]
        if not os.path.exists(os.path.join(PSP_AUDIO, psp + '.flac')):
            psp_track(psp, XA_RATE)             # extracts the PSP audio on first use
        if not os.path.exists(os.path.join(PSP_AUDIO + '_jp', psp + '.flac')):
            psp_track(psp, XA_RATE, 'jp')       # and the PSP-JP level reference
        key = movie_key(retail_sha1(image, lba, count), psp, lines)
        hit = cached(mv, key)
        if hit:
            source, report = hit
            report += ' (cached)'
        else:
            raw, _pcm, report = render(image, mv, psp, lba, count, lines)
            os.makedirs(CACHE, exist_ok=True)
            source = os.path.join(CACHE, mv + '.STR')
            with open(source + '.tmp', 'wb') as f:
                f.write(raw)
            os.replace(source + '.tmp', source)
            cache_write(mv, {'key': key, 'sha1': hashlib.sha1(raw).hexdigest(),
                             'stamp': build_step_cache.stamp(source), 'verified': 0, 'report': report})
        for path in [rel] + copies(image, index, mv):
            dest = os.path.join(BUILD, *path.split('/'))
            if not (os.path.isfile(dest) and os.path.getsize(dest) == os.path.getsize(source)
                    and build_step_cache._digest(dest) == build_step_cache._digest(source)):
                build_step_cache.clone(source, dest)
        print(f'fmv_dub: {rel}: {report}')


def verify():
    """Every dubbed STR: retail outside the audio payloads, and its XA decodes
    (ffmpeg's own psxstr reader) to the intended track within MIN_SNR."""
    image = disc_data.resolve_psx()
    index = str_index(image)
    bad = 0
    for mv, (psp, lines) in read_map().items():
        rel, lba, count = index[mv]
        dest = os.path.join(BUILD, *rel.split('/'))
        got = open(dest, 'rb').read()
        retail = str_sectors(image, lba, count)
        key = movie_key(hashlib.sha1(bytes(retail)).hexdigest(), psp, lines)
        record = cache_record(mv)
        sha1 = hashlib.sha1(got).hexdigest()
        if (record.get('key') == key and record.get('sha1') == sha1
                and record.get('verified') == '1'):
            print(f'fmv_dub: {rel} ok (the cached dub verified earlier)')
            for path in copies(image, index, mv):
                if open(os.path.join(BUILD, *path.split('/')), 'rb').read() != got:
                    bad += 1
                    print(f'FAIL {path}: not the same dub as its twin {rel}')
            continue
        idx, _ch = audio_layout(retail)
        audio = set(idx)
        for i in range(len(retail) // cdsector.SECTOR):
            o = i * cdsector.SECTOR
            same = (got[o:o + 24] == retail[o:o + 24] if i in audio
                    else got[o:o + cdsector.SECTOR] == retail[o:o + cdsector.SECTOR])
            if not same:
                bad += 1
                print(f'FAIL {rel}: sector {i} differs outside the audio payload')
                break
        _raw, want, _report = render(image, mv, psp, lba, count, lines)
        dec = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'psxstr', '-i', 'pipe:0', '-map', '0:a',
                              '-f', 's16le', 'pipe:1'], input=got, capture_output=True,
                             check=True).stdout
        dec = np.frombuffer(dec, np.int16).reshape(-1, 2).astype(np.float64)
        n = min(len(dec), len(want))
        w = want[:n].astype(np.float64)
        snr = 10 * np.log10((w ** 2).sum() / max(((dec[:n] - w) ** 2).sum(), 1e-9))
        if len(dec) != len(want) or snr < MIN_SNR:
            bad += 1
            print(f'FAIL {rel}: decoded {len(dec)} vs {len(want)} samples, SNR {snr:.1f} dB')
        else:
            print(f'fmv_dub: {rel} ok, XA SNR {snr:.1f} dB')
            if record.get('key') == key and record.get('sha1') == sha1:
                record['verified'] = 1
                cache_write(mv, record)
        for path in copies(image, index, mv):
            if open(os.path.join(BUILD, *path.split('/')), 'rb').read() != got:
                bad += 1
                print(f'FAIL {path}: not the same dub as its twin {rel}')
    if bad:
        raise SystemExit(f'fmv_dub: {bad} failure(s)')


def srt_time(t):
    ms = int(round(t * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def review(out):
    """Files to judge the dub outside the game, rendered from the line map,
    the retail disc and the PSP audio (no build needed), one per dubbed movie:

      <out>/MVxx.mkv   the movie's own frames (decoded and stored lossless:
                       FFV1 320x240 15 fps - no container players read holds
                       MDEC), audio tracks dub / retail Japanese / the PSP-US
                       track as it is, and the subtitle rows as a track
      <out>/MVxx.STR   the dubbed STR itself (mpv, ffplay -f psxstr)
    """
    image = disc_data.resolve_psx()
    index = str_index(image)
    subs = {}
    for r in strlib.tsv_rows(SUBTITLES, required=('movie', 'start_s', 'end_s', 'text')):
        if (r.get('text') or '').strip():
            subs.setdefault(r['movie'], []).append(
                (float(r['start_s']), float(r['end_s']), r['text'].replace('\\n', '\n')))
    os.makedirs(out, exist_ok=True)
    for mv, (psp, lines) in read_map().items():
        rel, lba, count = index[mv]
        raw, _pcm, report = render(image, mv, psp, lba, count, lines)
        dub = os.path.join(out, mv + '.STR')
        with open(dub, 'wb') as f:
            f.write(raw)
        retail_str = os.path.join(out, f'.{mv}.retail.STR')
        srt = os.path.join(out, f'.{mv}.srt')
        with open(retail_str, 'wb') as f:
            f.write(str_sectors(image, lba, count))
        with open(srt, 'w', encoding='utf-8') as f:
            for n, (a, b, text) in enumerate(subs.get(mv, []), 1):
                f.write(f'{n}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'psxstr', '-i', dub,
                        '-f', 'psxstr', '-i', retail_str, '-i', os.path.join(PSP_AUDIO, psp + '.flac'),
                        '-i', srt,
                        '-map', '0:v', '-map', '0:a', '-map', '1:a', '-map', '2:a', '-map', '3:s',
                        '-c:v', 'ffv1', '-c:a', 'flac', '-c:s', 'srt',
                        '-metadata:s:a:0', 'title=English dub', '-metadata:s:a:0', 'language=eng',
                        '-metadata:s:a:1', 'title=Japanese (retail)', '-metadata:s:a:1', 'language=jpn',
                        '-metadata:s:a:2', f'title=PSP-US {psp}, unaligned',
                        '-metadata:s:s:0', 'title=Subtitles', '-metadata:s:s:0', 'language=eng',
                        '-disposition:s:0', 'default',
                        os.path.join(out, mv + '.mkv')], check=True)
        os.unlink(retail_str)
        os.unlink(srt)
        print(f'fmv_dub: review {mv}: {report}')


def retail():
    for rel, _lba, _count in str_index(disc_data.resolve_psx()).values():
        dest = os.path.join(BUILD, *rel.split('/'))
        if os.path.exists(dest):
            os.unlink(dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cmd', choices=('build', 'verify', 'retail', 'review'))
    ap.add_argument('out', nargs='?', default=os.path.join(BUILD, 'dub_review'),
                    help='review: the folder to write')
    a = ap.parse_args()
    if a.cmd == 'review':
        review(a.out)
    else:
        {'build': build, 'verify': verify, 'retail': retail}[a.cmd]()


if __name__ == '__main__':
    main()
