"""Transcribe the subtitled ranges of PSX movie STRs (Japanese audio -> text+times).

Usage: python src/extraction_tools/psp/transcribe_fmv.py MV11 [MV12 ...]
Output: /tmp/opencode/fmv/<MV>.json [{start, end, text}] (times = movie seconds)

Reads sectors from the local JP disc image via build/fmv mvidx ranges.
"""
import json
import os
import struct
import subprocess
import sys
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DISC = os.path.join(ROOT, 'data', 'discs', 'Megami Ibunroku Persona - Be Your True Mind (Japan)',
                     'Megami Ibunroku Persona - Be Your True Mind (Japan).bin')
TMP = '/tmp/opencode/fmv'

# (movie, wav-start-s, wav-end-s, str-first-sector, str-last-sector)
JOBS = {
    'MV11': (40.0, 64.0, 168201, 177820),
    'MV12': (0.0, 78.0, 177821, 190134),
    'MV13': (3.0, 43.0, None, None),
    'MV14': (3.0, 57.0, None, None),
    'MV15': (3.0, 51.0, None, None),
    'MV16': (3.0, 55.0, None, None),
    'MV17': (3.0, 48.0, None, None),
    'MV1B': (4.0, 50.0, None, None),
}


def sector_range(mv):
    for ln in open('/tmp/opencode/mvidx.txt', encoding='utf-8', errors='replace'):
        if f'ID:STR1/{mv}.STR|' in ln:
            for fld in ln.split('|'):
                if fld.startswith('Sectors:'):
                    a, b = fld[len('Sectors:'):].split('-')
                    return int(a), int(b)
    raise SystemExit(f'no STR range for {mv}')


def extract(mv):
    s0, s1 = sector_range(mv)
    path = os.path.join(TMP, mv.lower() + 'full.str')
    if not os.path.exists(path):
        with open(DISC, 'rb') as f, open(path, 'wb') as out:
            for s in range(s0, s1 + 1):
                f.seek(s * 2352)
                out.write(f.read(2352))
    return path


def to_wav(str_path, mv, t0, t1):
    wav = os.path.join(TMP, f'{mv.lower()}_{int(t0)}_{int(t1)}.wav')
    if not os.path.exists(wav):
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'psxstr', '-i', str_path,
                        '-map', '0:a', '-ss', str(t0), '-t', str(t1 - t0),
                        '-ar', '16000', '-ac', '1', wav, '-y'], check=True)
    return wav


def load_mono16(wav):
    w = wave.open(wav, 'rb')
    raw = w.readframes(w.getnframes())
    n = len(raw) // (2 * w.getnchannels())
    a = np.frombuffer(raw, dtype=np.int16).reshape(n, w.getnchannels()).mean(axis=1)
    return (a / 32768.0).astype(np.float32)


def main():
    from faster_whisper import WhisperModel
    model = WhisperModel('small', device='cpu', compute_type='int8')
    for mv in sys.argv[1:]:
        t0, t1, _, _ = JOBS[mv]
        str_path = extract(mv)
        wav = to_wav(str_path, mv, max(0.0, t0 - 2.0), t1 + 1.0)
        audio = load_mono16(wav)
        segs, info = model.transcribe(audio, language='ja', beam_size=5)
        out = []
        for s in segs:
            out.append({'start': round(s.start + max(0.0, t0 - 2.0), 1),
                        'end': round(s.end + max(0.0, t0 - 2.0), 1),
                        'text': s.text.strip()})
        jp = os.path.join(TMP, f'{mv.lower()}_ja.json')
        json.dump(out, open(jp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'{mv}: {len(out)} segments -> {jp}')
        for s in out:
            print(f"  [{s['start']}-{s['end']}] {s['text']}")


if __name__ == '__main__':
    main()
