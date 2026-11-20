"""Edit the English movie dub by ear: python src/mods/english-dub/dub_editor.py [--port N]

Opens a page on http://127.0.0.1:PORT/ (this machine only) with two
timelines. The movie timeline holds the subtitles, the JP audio, the dub
and each line's English piece where it plays, beside the movie's pictures
(the PSX movie for the dub and the JP, the PSP movie for the PSP; browser
copies made once into build/dub_editor/). The PSP timeline holds the PSP
English and each line's cut: full volume between its start and end, fading
in and out over the slopes before and after. Drag a cut's start, end, fade
or body, or a piece in the movie timeline; add a line (a shout no subtitle
holds) from the two cursors or delete one; the dub re-renders by itself and
plays from the cursor with a playhead on both timelines.

The subtitles have a lane of their own under the dub: their timing in the
dub build (--mods=english-dub), dragged by their edges or whole, shown under the
picture as the dub plays: the dub's own rows (what the English voice says),
saved into translation/manual/fmv/dub_subtitles.tsv (fmv_subgen reads it;
their text is edited there). The lane above is subtitles.tsv, the JP's.

Save writes the movie's rows into translation/generated_mappings/fmv_dub.tsv
numbered in the order they play, with manual = 1 on every row changed or
added here (on all of them when lines were added or removed). The PSP source of a movie can be switched too (it is a column
of the same rows).

Reads the retail PSX disc, the PSP movies and their extracted audio
(data/psp_audio/, see src/extraction/psp/audio.py); writes nothing else
but the line map and the preview videos.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import disc_data  # noqa: E402
import etext  # noqa: E402
import fmv_dub as dub  # noqa: E402
import fmv_subgen  # noqa: E402
import xa  # noqa: E402

PAGE = os.path.join(HERE, 'dub_editor.html')
VIEW_HOP = 0.01          # s per drawn point
NUMBERS = ('jp_start', 'jp_end', 'en_start', 'en_end', 'en_lead', 'en_trail',
           'mute_from', 'mute_to')

_lock = threading.RLock()        # cached values are built from other cached values
_cache = {}


def cached(key, make):
    with _lock:
        if key not in _cache:
            _cache[key] = make()
        return _cache[key]


def image():
    return cached('image', disc_data.resolve_psx)


def index():
    return cached('index', lambda: dub.str_index(image()))


def retail(mv):
    """The movie's retail audio at the XA rate, cut to its audio sectors."""
    def make():
        _rel, lba, count = index()[mv]
        raw = dub.str_sectors(image(), lba, count)
        idx, channels = dub.audio_layout(raw)
        need = len(idx) * xa.samples_per_sector(channels)
        pcm = dub.retail_audio(image(), lba, count, dub.XA_RATE, channels)
        return pcm[:need] if len(pcm) >= need else np.pad(pcm, ((0, need - len(pcm)), (0, 0)))
    return cached(('retail', mv), make)


def psp(name, region='us'):
    return cached(('psp', name, region), lambda: dub.psp_track(name, dub.XA_RATE, region))


def view(stereo, rate):
    """What a track is drawn from: its peak per VIEW_HOP (0-100)."""
    mono = np.ascontiguousarray(stereo.mean(axis=1))
    hop = int(VIEW_HOP * rate)
    n = len(mono) // hop
    peaks = np.abs(mono[:n * hop]).reshape(n, hop).max(axis=1)
    peaks = np.round(np.clip(peaks / max(peaks.max(), 1e-6), 0, 1) * 100).astype(int)
    return {'hop': VIEW_HOP, 'duration': len(mono) / rate, 'peaks': peaks.tolist()}


def wav_bytes(stereo, rate):
    pcm = np.clip(np.round(stereo * 32767), -32768, 32767).astype('<i2')
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(stereo.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


VIDEO_DIR = os.path.join(ROOT, 'build', 'dub_editor')


def preview_video(which, name):
    """A browser-playable copy of a movie's pictures, for the editor only
    (H.264, no sound, made once into build/dub_editor/): the retail PSX movie
    (which = jp) or a PSP movie (which = psp)."""
    os.makedirs(VIDEO_DIR, exist_ok=True)
    out = os.path.join(VIDEO_DIR, f'{name}_{which}.mp4')
    if os.path.exists(out):
        return out
    encode = ['-an', '-vf', 'setpts=PTS-STARTPTS', '-c:v', 'libx264', '-preset', 'veryfast',
              '-crf', '24', '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
    tmp = out + '.part.mp4'
    if which == 'jp':
        _rel, lba, count = index()[name]
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'psxstr', '-i', 'pipe:0', *encode, tmp],
                       input=bytes(dub.str_sectors(image(), lba, count)), check=True)
    else:
        pmf = os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR', 'MOVIE', name + '.pmf')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', pmf, '-map', '0:v', *encode, tmp],
                       check=True)
    os.replace(tmp, out)
    return out


def jp_subtitles(mv):
    """The movie's subtitles as the JP voice has them (subtitles.tsv)."""
    return [{'start': float(r['start_s']), 'end': float(r['end_s']),
             'text': r['text'].replace('\\n', ' ')}
            for r in fmv_subgen.subtitle_rows() if r['movie'] == mv]


def subtitles(mv):
    """The dub's own subtitle rows of the movie (dub_subtitles.tsv: what
    the English voice says), with their timing in the dub."""
    rows = []
    for r in fmv_subgen.subtitle_rows(dub=True):
        if r['movie'] == mv:
            rows.append({'row': len(rows), 'dub_start': float(r['start_s']),
                         'dub_end': float(r['end_s']), 'text': r['text'].replace('\\n', ' ')})
    return rows


def save_subtitles(mv, subs):
    """The movie's dub subtitle timing into fmv_subgen.DUB_SUBTITLES (its
    text and notes stay as they are)."""
    times = {int(r['row']): (f"{float(r['dub_start']):.2f}", f"{float(r['dub_end']):.2f}")
             for r in subs}
    cols = fmv_subgen.SUBTITLE_COLS
    rows, k = [], 0
    for r in dub.strlib.tsv_rows(fmv_subgen.DUB_SUBTITLES, required=cols):
        if r['movie'] == mv and etext.has_text(r['text']):
            if k in times:
                r['start_s'], r['end_s'] = times[k]
            k += 1
        rows.append(r)
    with open(fmv_subgen.DUB_SUBTITLES, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\t'.join(cols) + '\n')
        for r in rows:
            f.write('\t'.join(r[c] for c in cols) + '\n')


def movie_lines(mv):
    rows = dub.map_rows()
    out = []
    for (m, k), r in sorted(rows.items()):
        if m == mv:
            line = {'line': k, 'cut': r['en_cut'] == '1', 'manual': r.get('manual') == '1'}
            line.update({f: float(r[f]) for f in NUMBERS})
            out.append(line)
    out.sort(key=lambda l: (l['jp_start'], l['en_start']))     # the order they play in
    return out, next(r['psp'] for (m, _k), r in sorted(rows.items()) if m == mv)


def as_tuples(lines):
    return [(l['jp_start'], l['jp_end'], l['en_start'], l['en_end'], bool(l['cut']),
             l['en_lead'], l['en_trail'], l['mute_from'], l['mute_to'], bool(l.get('manual')))
            for l in lines]


def render(mv, source, lines):
    """The dub of the values given (not saved): its audio and what to draw."""
    tuples = as_tuples(lines)
    gain = dub.psp_gain(mv, retail(mv), psp(source, 'jp'), tuples)
    mixed, gain = dub.mix(retail(mv), psp(source), tuples, gain)
    mixed = np.clip(mixed, -1, 1)
    with _lock:
        _cache[('dub', mv)] = wav_bytes(mixed, dub.XA_RATE)
    pieces = [{'at': p[0], 'from': p[1], 'to': p[2], 'voice_start': p[3], 'voice_end': p[4]}
              for p in dub.placements(as_tuples(lines))]
    return {'view': view(mixed, dub.XA_RATE), 'pieces': pieces,
            'gain_db': round(20 * float(np.log10(gain)), 1)}


def save(mv, source, lines):
    """The movie's lines as its rows of the line map, numbered in the order
    they play. A line changed or added here gets manual = 1; when lines were
    added or removed, every line of the movie does."""
    if not lines:
        raise ValueError('a movie keeps at least one line')
    rows = dub.map_rows()
    old = [r for key, r in rows.items() if key[0] == mv]
    for key in [key for key in rows if key[0] == mv]:
        del rows[key]
    lines = sorted(lines, key=lambda l: (float(l['jp_start']), float(l['en_start'])))
    reshaped = len(lines) != len(old)
    for k, l in enumerate(lines):
        new = {'psp': source, 'en_cut': '1' if l['cut'] else '0'}
        new.update({f: f'{float(l[f]):.2f}' for f in NUMBERS})
        was = next((r for r in old if all(r.get(f) == v for f, v in new.items())), None)
        hand = reshaped or was is None or was.get('manual') == '1' or l.get('manual')
        new['manual'] = '1' if hand else ''
        rows[(mv, k)] = new
    dub.write_map(rows)
    return movie_lines(mv)[0]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, body, kind='application/json', status=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        # byte ranges, so the browser can seek inside audio and video
        rng = self.headers.get('Range', '')
        start, end = 0, len(body) - 1
        if status == 200 and rng.startswith('bytes='):
            a, _, b = rng[6:].split(',')[0].partition('-')
            if a:
                start, end = int(a), min(int(b) if b else end, end)
            elif b:
                start = max(0, len(body) - int(b))
            status = 206
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(body)}')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body[start:end + 1])
        except (BrokenPipeError, ConnectionResetError):
            pass                                 # the browser dropped a range it no longer needs

    def query(self):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        q = self.query()
        try:
            if path == '/':
                self.send(open(PAGE, 'rb').read(), 'text/html; charset=utf-8')
            elif path == '/api/movies':
                self.send({'movies': sorted(dub.read_map()), 'psp': dub.psp_movies()})
            elif path == '/api/movie':
                mv = q['mv']
                lines, source = movie_lines(mv)
                source = q.get('psp') or source
                self.send({'movie': mv, 'psp': source, 'lines': lines, 'subs': subtitles(mv), 'jp': jp_subtitles(mv),
                           'jp': cached(('view-jp', mv), lambda: view(retail(mv), dub.XA_RATE)),
                           'en': cached(('view-en', source), lambda: view(psp(source), dub.XA_RATE))})
            elif path == '/audio':
                mv, which = q['mv'], q['which']
                if which == 'jp':
                    body = cached(('wav-jp', mv), lambda: wav_bytes(retail(mv), dub.XA_RATE))
                elif which == 'en':
                    body = cached(('wav-en', q['psp']), lambda: wav_bytes(psp(q['psp']), dub.XA_RATE))
                else:
                    body = _cache.get(('dub', mv))
                    if body is None:
                        return self.send({'error': 'render the dub first'}, status=404)
                self.send(body, 'audio/wav')
            elif path == '/video':
                which = q['which']
                name = q['mv'] if which == 'jp' else q['psp']
                path = cached(('video', which, name), lambda: preview_video(which, name))
                self.send(open(path, 'rb').read(), 'video/mp4')
            else:
                self.send({'error': 'not found'}, status=404)
        except Exception as e:                       # shown in the page
            self.send({'error': f'{type(e).__name__}: {e}'}, status=500)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if path == '/api/render':
                self.send(render(data['movie'], data['psp'], data['lines']))
            elif path == '/api/save':
                save_subtitles(data['movie'], data['subs'])
                self.send({'lines': save(data['movie'], data['psp'], data['lines']),
                           'subs': subtitles(data['movie'])})
            else:
                self.send({'error': 'not found'}, status=404)
        except Exception as e:
            self.send({'error': f'{type(e).__name__}: {e}'}, status=500)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--port', type=int, default=8765)
    port = ap.parse_args().port
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'dub editor: http://127.0.0.1:{port}/  (Ctrl+C to stop)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
