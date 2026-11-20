"""Extract every PSP-US sound: movie audio, streamed music, sound banks.

  python src/extraction/psp/audio.py [movie|bgm|se ...] [--out DIR]

Writes under data/psp_audio/ (local, never tracked), one index TSV per kind:

  movie/MVxx.flac   the movie's ATRAC3plus track, 44.1 kHz stereo
  movie.tsv         movie, frames, seconds, video_seconds
  movie_jp/, movie_jp.tsv   the same from the PSP-JP disc (extract_movies(out,
                    'jp'), on demand: the English dub's level reference)
  bgm/<name>.flac   one ATRAC3plus .at3 file, encoder delay trimmed
  bgm.tsv           name, samples, loop_start, loop_end (samples, trimmed
                    timeline; empty when the file carries no loop)
  se/<file>/<bank>_<n>.wav   one PS-ADPCM sample of a sound bank
  se.tsv            file, bank, n, offset, size, rate, loop, seconds

Formats (read off the files, see docs/research/psp-audio.md):

- MOVIE/*.pmf is PSMF: a 0x800-byte header, then MPEG-PS. Video is H.264
  480x272 at 29.97 fps (stream 0xE0). Audio is private stream 1 (0xBD),
  sub-stream 0: every payload starts with a 4-byte sub-stream header, and the
  concatenated payloads are ATRAC3plus frames, each an 8-byte `0F D0 pp pp
  00 00 00 00` header (pp = codec parameters, low 10 bits = frame size / 8 -
  1) and the frame. ffmpeg does not see that track in the PS stream, so it
  is demuxed here and handed to ffmpeg as an OMA file (EA3 header, codec 1 =
  ATRAC3plus, same parameters).
- sdata/*.at3 is RIFF WAVE_FORMAT_EXTENSIBLE ATRAC3plus that ffmpeg decodes
  directly. `fact` holds (samples, encoder delay); `smpl` the loop in the
  decoder's own timeline (delay included, as ffmpeg outputs it), so the
  delay is cut off the front and from both loop points.
- sdata/SE_*.BIN are PSP sound banks: a bank header (sound count, PHD size,
  PBD size, 0x2C, the sound table), then a PPHD header (PPPG programs, PPTN
  tones, PPVA waves), then the PBD body - PS-ADPCM, the same codec as the
  PS1 SPU - at the next 16-byte boundary. PPVA lists every wave: (offset in
  the body, rate, size, flags), all-FF for an empty slot. A file holds one bank or a table of banks;
  every PPHD in it is one bank.
"""
import argparse
import csv
import os
import struct
import subprocess
import sys
import tempfile
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
USRDIR = os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR')
OUT = os.path.join(ROOT, 'data', 'psp_audio')


def write_tsv(path, cols, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(cols)
        w.writerows(rows)


def ffprobe_seconds(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'csv=p=0', path], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


# --- movies ----------------------------------------------------------------

def pmf_audio(data):
    """The concatenated ATRAC3plus elementary stream of a PSMF file."""
    i = struct.unpack_from('>I', data, 8)[0]
    es = bytearray()
    while i < len(data) - 6:
        if data[i:i + 3] != b'\0\0\1':
            i += 1
            continue
        sid = data[i + 3]
        if sid == 0xBA:                                  # pack header
            i += 14 + (data[i + 13] & 7)
            continue
        if sid == 0xB9:                                  # program end
            break
        length = struct.unpack_from('>H', data, i + 4)[0]
        if sid == 0xBD:
            payload = data[i + 9 + data[i + 8]:i + 6 + length]
            if payload and payload[0] == 0:
                es += payload[4:]
        i += 6 + length
    return bytes(es)


def at3p_frames(es):
    """(codec parameters, [frame bytes]) of a 0FD0-framed ATRAC3plus stream."""
    if es[:2] != b'\x0f\xd0':
        raise ValueError(f'not an ATRAC3plus stream: {es[:8].hex()}')
    params = struct.unpack_from('>H', es, 2)[0]
    size = ((params & 0x3FF) + 1) * 8
    frames, i = [], 0
    while i + 8 + size <= len(es):
        if es[i:i + 2] != b'\x0f\xd0' or struct.unpack_from('>H', es, i + 2)[0] != params:
            raise ValueError(f'frame header lost at {i:#x}: {es[i:i + 8].hex()}')
        frames.append(es[i + 8:i + 8 + size])
        i += 8 + size
    if i != len(es):
        raise ValueError(f'{len(es) - i} bytes after the last frame')
    return params, frames


def oma(params, frames):
    head = bytearray(96)
    head[0:3] = b'EA3'
    head[3] = 1
    head[5] = 0x60
    head[6] = head[7] = 0xFF                             # not encrypted
    head[32] = 1                                         # ATRAC3plus
    head[33:36] = bytes([0, params >> 8, params & 0xFF])
    return bytes(head) + b''.join(frames)


def extract_movies(out, region='us'):
    """The movies' audio: movie/ from the PSP-US disc, movie_jp/ from the
    PSP-JP one (the dub's level reference, fmv_dub.py)."""
    src = os.path.join(ROOT, 'data', f'psp_{region}', 'PSP_GAME', 'USRDIR', 'MOVIE')
    dst = os.path.join(out, 'movie' if region == 'us' else 'movie_' + region)
    os.makedirs(dst, exist_ok=True)
    rows = []
    for name in sorted(os.listdir(src)):
        if not name.lower().endswith('.pmf'):
            continue
        path = os.path.join(src, name)
        params, frames = at3p_frames(pmf_audio(open(path, 'rb').read()))
        movie = os.path.splitext(name)[0]
        flac = os.path.join(dst, movie + '.flac')
        with tempfile.NamedTemporaryFile(suffix='.oma', dir=dst) as tmp:
            tmp.write(oma(params, frames))
            tmp.flush()
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmp.name, '-c:a', 'flac', flac],
                           check=True)
        rows.append((movie, len(frames), f'{len(frames) * 2048 / 44100:.3f}',
                     f'{ffprobe_seconds(path):.3f}'))
        print(f'movie {movie}: {len(frames)} frames')
    write_tsv(os.path.join(out, os.path.basename(dst) + '.tsv'),
              ('movie', 'frames', 'seconds', 'video_seconds'), rows)


# --- streamed music --------------------------------------------------------

def riff_chunks(data):
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('not a RIFF WAVE file')
    i, out = 12, {}
    while i + 8 <= len(data):
        cid, size = data[i:i + 4], struct.unpack_from('<I', data, i + 4)[0]
        out.setdefault(cid, data[i + 8:i + 8 + size])
        i += 8 + size + (size & 1)
    return out


def extract_bgm(out):
    src = os.path.join(USRDIR, 'sdata')
    dst = os.path.join(out, 'bgm')
    os.makedirs(dst, exist_ok=True)
    rows = []
    for name in sorted(os.listdir(src)):
        if not name.lower().endswith('.at3'):
            continue
        path = os.path.join(src, name)
        chunks = riff_chunks(open(path, 'rb').read())
        samples, delay = struct.unpack_from('<II', chunks[b'fact'], 0)
        loop = ('', '')
        smpl = chunks.get(b'smpl')
        if smpl and struct.unpack_from('<I', smpl, 28)[0]:
            start, end = struct.unpack_from('<II', smpl, 36 + 8)
            loop = (start - delay, end - delay)
        stem = os.path.splitext(name)[0]
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path,
                        '-af', f'atrim=start_sample={delay}:end_sample={delay + samples}',
                        '-c:a', 'flac', os.path.join(dst, stem + '.flac')], check=True)
        rows.append((stem, samples, *loop))
        print(f'bgm {stem}: {samples} samples, loop {loop}')
    write_tsv(os.path.join(out, 'bgm.tsv'), ('name', 'samples', 'loop_start', 'loop_end'), rows)


# --- sound banks -----------------------------------------------------------

ADPCM_FILTERS = ((0, 0), (60, 0), (115, -52), (98, -55), (122, -60))


def adpcm_decode(blocks):
    """PS-ADPCM (SPU / VAG) blocks -> int16 samples, (loop start block or None)."""
    out = np.empty(len(blocks) // 16 * 28, dtype=np.int16)
    s1 = s2 = 0
    loop = None
    n = 0
    for b in range(0, len(blocks) - 15, 16):
        head, flags = blocks[b], blocks[b + 1]
        shift, filt = head & 0xF, min(head >> 4, 4)
        f0, f1 = ADPCM_FILTERS[filt]
        if flags & 4 and loop is None:
            loop = b // 16
        for byte in blocks[b + 2:b + 16]:
            for nib in (byte & 0xF, byte >> 4):
                v = (nib << 12) & 0xFFFF
                v = (v - 0x10000 if v & 0x8000 else v) >> shift
                v += (s1 * f0 + s2 * f1 + 32) >> 6
                v = max(-32768, min(32767, v))
                out[n] = v
                n += 1
                s2, s1 = s1, v
        if flags & 1:                                    # end of the wave
            break
    return out[:n], loop


def sound_banks(data):
    """[(bank start, [(offset, size, rate)], body offset)] for every PPHD."""
    banks, at = [], data.find(b'PPHD')
    while at >= 0:
        start = at & ~0x7FF
        phd = struct.unpack_from('<I', data, start + 4)[0]
        body = (at + phd + 15) & ~15
        ppva = at + struct.unpack_from('<I', data, at + 0x18)[0]
        if data[ppva:ppva + 4] != b'PPVA':
            raise ValueError(f'PPHD at {at:#x}: no PPVA chunk')
        # 16-byte entries after a 0x20 header; the chunk size stops 8 bytes
        # into the last one. All-FF entries are empty slots.
        count = (struct.unpack_from('<I', data, ppva + 4)[0] - 0x20 + 8) // 16
        waves = []
        for k in range(count):
            off, rate, size, _ = struct.unpack_from('<IIIi', data, ppva + 0x20 + 16 * k)
            if off != 0xFFFFFFFF:
                waves.append((off, size, rate))
        banks.append((start, waves, body))
        at = data.find(b'PPHD', at + 4)
    return banks


def write_wav(path, pcm, rate):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def extract_se(out):
    src = os.path.join(USRDIR, 'sdata')
    rows = []
    for name in sorted(os.listdir(src)):
        if not (name.upper().startswith('SE_') and name.upper().endswith('.BIN')):
            continue
        data = open(os.path.join(src, name), 'rb').read()
        stem = os.path.splitext(name)[0]
        dst = os.path.join(out, 'se', stem)
        os.makedirs(dst, exist_ok=True)
        count = 0
        for bank, (start, waves, body) in enumerate(sound_banks(data)):
            for n, (off, size, rate) in enumerate(waves):
                pcm, loop = adpcm_decode(data[body + off:body + off + size])
                write_wav(os.path.join(dst, f'{bank:02d}_{n:03d}.wav'), pcm, rate)
                rows.append((stem, bank, n, f'{body + off:#x}', size, rate,
                             '' if loop is None else loop * 28, f'{len(pcm) / rate:.3f}'))
                count += 1
        print(f'se {stem}: {count} waves')
    write_tsv(os.path.join(out, 'se.tsv'),
              ('file', 'bank', 'n', 'offset', 'size', 'rate', 'loop', 'seconds'), rows)


KINDS = {'movie': extract_movies, 'bgm': extract_bgm, 'se': extract_se}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('kinds', nargs='*', metavar='|'.join(sorted(KINDS)))
    ap.add_argument('--out', default=OUT)
    args = ap.parse_args()
    for kind in args.kinds:
        if kind not in KINDS:
            ap.error(f'unknown kind {kind!r}')
    if not os.path.isdir(USRDIR):
        sys.exit(f'{USRDIR}: missing, run tools/prepare_data.py first')
    os.makedirs(args.out, exist_ok=True)
    for kind in args.kinds or sorted(KINDS):
        KINDS[kind](args.out)


if __name__ == '__main__':
    main()
