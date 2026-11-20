"""Dry menu-cue reconstructions for relative level and spectral analysis.

Uses retail SEQ notes and the shared VAB's decoded ADPCM, pitch and gains.
This is not SPU emulation: ADSR, reverb and interpolation differ from hardware.
WAVs retain relative gain; no individual normalization is performed.
"""
from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
import struct
import sys
import wave
from typing import Final
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import toolpath
from audio import adpcm_decode
import menu_sounds

ROOT: Final = Path(toolpath.ROOT)
RATE: Final = 44100
PREVIEW_GAIN: Final = 0.5  # shared headroom, never per-cue normalization
ROLES: Final = ('back', 'navigation-list', 'confirm', 'navigation-wheel', 'confirm-alternate', 'open-back-alternate')

@dataclass(frozen=True)
class Note:
    start: float
    end: float
    program: int
    key: int
    velocity: int

@dataclass(frozen=True)
class Tone:
    sample: np.ndarray
    loop: int | None
    centre: int
    fine: int
    gain: float


def notes(data: bytes, start: int) -> list[Note]:
    division = int.from_bytes(data[start + 8:start + 10], 'big')
    tempo = int.from_bytes(data[start + 10:start + 13], 'big')
    at, status, tick = start + 15, 0, 0.0
    programs = [0] * 16
    active: dict[tuple[int, int], tuple[float, int, int]] = {}
    result: list[Note] = []
    while at < len(data):
        delta, at = menu_sounds.vlq(data, at)
        tick += delta * tempo / division / 1000000
        if data[at] >= 128:
            status = data[at]; at += 1
        if status == 255:
            kind = data[at]; length, at = menu_sounds.vlq(data, at + 1)
            if kind == 81:
                tempo = int.from_bytes(data[at:at + length], 'big')
            at += length
            if kind == 47: break
            continue
        kind, channel = status >> 4, status & 15
        count = 1 if kind in (12, 13) else 2
        values = data[at:at + count]; at += count
        if kind == 12: programs[channel] = values[0]
        if kind == 9 and values[1]:
            active[channel, values[0]] = (tick, programs[channel], values[1])
        elif kind == 8 or (kind == 9 and not values[1]):
            item = active.pop((channel, values[0]), None)
            if item:
                first, program, velocity = item
                result.append(Note(first, tick, program, values[0], velocity))
    if active: raise ValueError('unterminated menu notes')
    return result


def bank() -> dict[tuple[int, int], list[Tone]]:
    data = (ROOT / 'data/psx/S2D.BIN').read_bytes()
    candidates = []
    start = 0
    while (start := data.find(b'pBAV', start)) >= 0:
        programs, _tones, vags = struct.unpack_from('<HHH', data, start + 18)
        size = 0x820 + programs * 512 + 512
        if size == 0x2C20: candidates.append(data[start:start + size])
        start += 4
    if len(candidates) != 1: raise ValueError('ambiguous shared menu VAB')
    header = candidates[0]
    programs, _tones, vags = struct.unpack_from('<HHH', header, 18)
    sizes = struct.unpack_from(f'<{vags + 1}H', header, 0x820 + programs * 512)
    lts = (ROOT / 'data/psx/2D/2DLTS00.BIN').read_bytes()
    offset = struct.unpack_from('<I', lts, 12)[0] + sizes[0] * 8
    waves: list[tuple[np.ndarray, int | None]] = []
    for size in sizes[1:]:
        samples, loop = adpcm_decode(lts[offset:offset + size * 8]); offset += size * 8
        waves.append((samples.astype(np.float64) / 32768, None if loop is None else loop * 28))
    result: dict[tuple[int, int], list[Tone]] = {}
    compact = 0
    for program in range(128):
        info = header[32 + program * 16:48 + program * 16]
        if not info[0]: continue
        for index in range(info[0]):
            tone = header[0x820 + (compact * 16 + index) * 32:0x840 + (compact * 16 + index) * 32]
            vag = struct.unpack_from('<h', tone, 22)[0]
            if not 1 <= vag <= len(waves): raise ValueError('bad tone sample')
            sample, loop = waves[vag - 1]
            gain = (header[24] / 127) * (info[1] / 127) * (tone[2] / 127)
            for key in range(tone[6], tone[7] + 1):
                result.setdefault((program, key), []).append(Tone(sample, loop, tone[4], tone[5], gain))
        compact += 1
    return result


def render(events: list[Note], tones: dict[tuple[int, int], list[Tone]]) -> np.ndarray:
    result = np.zeros(int((max(n.end for n in events) + 0.05) * RATE))
    for note in events:
        for tone in tones[note.program, note.key]:
            count = max(1, int((note.end - note.start) * RATE))
            positions = np.arange(count) * 2 ** ((note.key - tone.centre + tone.fine / 128) / 12)
            if tone.loop is not None and len(tone.sample) > tone.loop:
                positions = np.where(positions < len(tone.sample), positions,
                                     tone.loop + (positions - tone.loop) % (len(tone.sample) - tone.loop))
            pcm = np.interp(positions, np.arange(len(tone.sample)), tone.sample, right=0)
            pcm *= tone.gain * note.velocity / 127
            fade = min(len(pcm), int(RATE * 0.005))
            pcm[-fade:] *= np.linspace(1, 0, fade)
            first = int(note.start * RATE)
            result[first:first + len(pcm)] += pcm
    return result


def main() -> None:
    out = ROOT / 'build/menu-sound-analysis'; out.mkdir(exist_ok=True)
    tones = bank(); data = (ROOT / 'data/psx/ADV/ADVCMD.BIN').read_bytes()
    with (out / 'measurements.tsv').open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(('role', 'archive_index', 'seconds', 'peak_dbfs', 'rms_100ms_dbfs', 'centroid_hz', 'energy_2_8khz_percent', 'energy_above_8khz_percent'))
        for index, role in enumerate(ROLES, 8):
            start = struct.unpack_from('<I', data, index * 4)[0]
            pcm = render(notes(data, start), tones)
            peak = np.max(np.abs(pcm)); window = min(len(pcm), RATE // 10)
            rms = np.sqrt(np.max(np.convolve(pcm * pcm, np.ones(window) / window, mode='valid')))
            power = np.abs(np.fft.rfft(pcm)) ** 2; frequencies = np.fft.rfftfreq(len(pcm), 1 / RATE)
            centroid = np.sum(power * frequencies) / np.sum(power)
            band = np.sum(power[(frequencies >= 2000) & (frequencies <= 8000)]) / np.sum(power) * 100
            writer.writerow((role, index, round(len(pcm) / RATE, 3), round(20 * np.log10(peak), 2),
                             round(20 * np.log10(rms), 2), round(centroid), round(band, 2), round(100 * np.sum(power[frequencies >= 8000]) / np.sum(power), 2)))
            with wave.open(str(out / (role + '.wav')), 'wb') as wav:
                wav.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
                wav.writeframes((np.clip(pcm * PREVIEW_GAIN, -1, 1) * 32767).astype('<i2').tobytes())
    print((out / 'measurements.tsv').read_text())

if __name__ == '__main__': main()
