"""Retime the spoken-movie subtitles to the voice, in place:
translation/manual/fmv/subtitles.tsv.

  python tools/fmv_retime.py            rewrite the table
  python tools/fmv_retime.py --dry      print what it would write
  python tools/fmv_retime.py --dub      time the dub's own rows to the English
                                        voice (fmv_dub.py's map), in place:
                                        translation/manual/fmv/dub_subtitles.tsv
                                        (derive_dub; with --dry, print it)

Run by hand, not by the build: the table stays the one source the build
reads (fmv_subgen). Each row's wording is kept verbatim; its timing, its
line breaks and how many subtitles it is shown as come from the voice -
only its loudness: the audio is Japanese, so no word is recognised, but where
the speech starts, pauses and stops is plain in the voice band:
- the voice is found inside each row's window (widened by SEARCH, never
  into a neighbour's), so the score under it is never mistaken for speech;
- a row splits into several subtitles at the voice's own pauses, but only
  at an English sentence end (or a clause end when the voice takes a clear
  breath there): the Japanese word order differs inside a clause, so a pause
  is matched to the break that sits at the same share of the line;
  no subtitle holds more than two lines (the subtitling standard), and a row
  that cannot fit two splits at its best clause end even without a pause;
- a subtitle appears as its voice starts (the renderer's fade-in already
  runs FADE frames ahead), stays LINGER after it stops, never shows for less
  than MIN_SHOW, is stretched into the silence after it when it would read
  faster than CPS characters per second, and never overlaps the next one
  (fade-out and fade-in do not cross);
- the lines are broken by the textbox flow (vwf_wrap) measured in the movie
  font, so a subtitle follows the same phrase rules as every textbox.
Speed and chunking follow the subtitle research: phrase-sized blocks read
best (Rajendran et al. 2013), and English viewers keep comprehension up to
about 20 cps but read comfortably below it (Szarkowska & Gerber-Moron 2018).
The movies are read from the PSX Rev 0 disc image (ISO directory -> raw
sectors -> ffmpeg's psxstr demuxer), so no extracted STR file is needed.
A second run finds the same voice inside the retimed windows and keeps them.
"""
import os
import re
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import disc_data  # noqa: E402
import etext  # noqa: E402
import fmv_subgen  # noqa: E402
import strlib  # noqa: E402
import vwf_wrap  # noqa: E402

# a subtitle over a picture leans the other way from a textbox: upper line
# the shorter (vwf_wrap.TOP_HEAVY)
vwf_wrap.TOP_HEAVY = False
# and keeps the verb-phrase units whole, as the subtitling standard asks
# (vwf_wrap.VERB_UNITS)
vwf_wrap.VERB_UNITS = True

SOURCE = os.path.join(ROOT, 'translation', 'manual', 'fmv', 'subtitles.tsv')

RATE = 16000          # Hz the audio is decoded at (the voice band fits)
HOP = 0.02            # s between loudness frames
WIN = 0.04            # s of audio per frame
BAND = (300, 3400)    # Hz: the voice band
VOICE_DB = 12         # dB above the window's quiet floor that proves a stretch is voice
SOFT_DB = 6           # dB above the floor a voiced stretch extends through (its soft onset and tail)
EDGE = 0.1            # s: a stretch this close to the search window's edge was cut off by it
SOFT_REACH = 0.3      # s at most a stretch extends that way: a soft onset is a syllable, not room tone
FLOOR_PCT = 15        # the floor: this percentile of the frames around a moment
FLOOR_SPAN = 6.0      # s of audio the floor under a moment is taken from
SILENCE_DB = -60      # dB under which a frame is digital silence, not sound
PAUSE = 0.25          # s of quiet that ends a voiced stretch
MIN_VOICE = 0.08      # s: a shorter stretch is a click, not speech
SEARCH = 0.6          # s the manual window is widened by to find its voice
SENTENCE_PAUSE = 0.3  # s of pause that may end a subtitle at a sentence end
CLAUSE_PAUSE = 0.45  # s of pause that may end one at a clause end (, ; : -): a breath
MATCH = 0.18          # how far (share of the line) a pause and a break may sit
MIN_WORDS = 3         # words a clause-end piece holds at least ("However," alone is no subtitle)
MAX_LINES = 2
CONJUNCTIONS = {'and', 'or', 'but', 'nor', 'so', 'yet'}
PYRAMID_SLACK = 0.3   # rhythm points a bottom-heavy layout may cost: under the smallest line-end fault (half a point), so shape only settles near-ties
CPS = 17              # characters per second a subtitle should not exceed
MIN_SHOW = 1.2        # s a subtitle stays at least
LINGER = 0.3          # s a subtitle stays after its voice stops
PASSES = 5            # passes at most until the table stops changing
ALIGN_WEIGHT = 20     # cost of a cut a whole voiced time away from its character share, against log(pause / PAUSE)
JP_WEIGHT = 2       # cost per s a row starts away from its Japanese start
JP_REACH = 1.0        # s past which that cost stops growing
LEAD = 0.4            # s a subtitle too fast to read may come in before its voice
GAP = 2 * fmv_subgen.FADE / fmv_subgen.FPS   # s: fade-out and fade-in never cross


def movie_sectors(image):
    """{movie: (lba, sectors)} of every STR file in the image's ISO tree."""
    out = {}
    with open(image, 'rb') as f:
        def sector(n):
            f.seek(n * 2352 + 24)               # Mode 2 Form 1 user data
            return f.read(2048)

        def entries(lba, size):
            for s in range((size + 2047) // 2048):
                d, i = sector(lba + s), 0
                while i < 2048 and d[i]:
                    e = d[i:i + d[i]]
                    name = e[33:33 + e[32]]
                    if name not in (b'\0', b'\1'):
                        yield (name.decode('ascii', 'replace').split(';')[0],
                               struct.unpack('<I', e[2:6])[0],
                               struct.unpack('<I', e[10:14])[0], e[25] & 2)
                    i += d[i]
        root = sector(16)[156:190]
        for name, lba, size, is_dir in entries(struct.unpack('<I', root[2:6])[0],
                                               struct.unpack('<I', root[10:14])[0]):
            if is_dir and name.startswith('STR'):
                for fname, flba, fsize, _ in entries(lba, size):
                    if fname.endswith('.STR'):
                        out[fname[:-4]] = (flba, fsize // 2048)
    return out


def voice_band_db(image, lba, sectors):
    """Loudness (dB) of the movie's voice band, one value per HOP."""
    with open(image, 'rb') as f:
        f.seek(lba * 2352)
        raw = f.read(sectors * 2352)
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'psxstr', '-i', 'pipe:0',
                          '-map', '0:a', '-ar', str(RATE), '-ac', '1',
                          '-f', 's16le', 'pipe:1'],
                         input=raw, capture_output=True, check=True).stdout
    return band_db(np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768)


def band_power(a):
    """Power of mono RATE-Hz audio's voice band, one value per HOP."""
    n, h = int(WIN * RATE), int(HOP * RATE)
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    band = (freqs >= BAND[0]) & (freqs <= BAND[1])
    frames = np.lib.stride_tricks.sliding_window_view(a, n)[::h] * np.hanning(n)
    return (np.abs(np.fft.rfft(frames, axis=1)) ** 2)[:, band].sum(axis=1)


def band_db(a):
    """Loudness (dB) of mono RATE-Hz audio's voice band, one value per HOP."""
    return 10 * np.log10(band_power(a) + 1e-12)


def centre_db(stereo):
    """Loudness (dB) of the voice band of what sits in the centre of a stereo
    track: the mid's power less the side's. The voice is mixed mono, the
    score wide, so the score under it mostly cancels (the PSP movies' score
    is as loud as their voice)."""
    mid = band_power(stereo.mean(axis=1))
    side = band_power((stereo[:, 0] - stereo[:, 1]) / 2)
    return 10 * np.log10(np.maximum(mid - side, 0) + 1e-6)


def quiet_floor(db):
    """The quiet floor under each frame: the FLOOR_PCT percentile of the
    FLOOR_SPAN seconds around it. Local (a loud stretch of score raises its
    own floor) but the movie's, not a search window's - a window that moves
    by a frame never moves what counts as voice."""
    half = int(FLOOR_SPAN / HOP / 2)
    # digital silence (a movie opens on it) is no floor: only sound counts
    sound = np.where(db > SILENCE_DB, db, np.nan)
    padded = np.pad(sound, half, constant_values=np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * half + 1)
    with np.errstate(all='ignore'):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            floor = np.nanpercentile(windows, FLOOR_PCT, axis=1)[:len(db)]
    return np.where(np.isnan(floor), SILENCE_DB, floor)


def voiced(db, floor, t0, t1):
    """[(start, end)] voiced stretches inside [t0, t1] seconds."""
    a, b = max(0, int(round(t0 / HOP))), min(len(db), int(round(t1 / HOP)))
    if b <= a:
        return []
    # two thresholds: the stretches (and so the pauses between them) are
    # where the band is VOICE_DB over the floor; each then reaches out
    # through the frames still SOFT_DB over it - a soft onset ("You must
    # stop Kandori" opens quietly) and a fading tail belong to their stretch
    window, under = db[a:b], floor[a:b]
    soft, loud = window > under + SOFT_DB, window > under + VOICE_DB
    runs, k = [], 0
    while k < len(loud):
        if loud[k]:
            j = k
            while j + 1 < len(loud) and loud[j + 1]:
                j += 1
            runs.append([k, j])
            k = j + 1
        else:
            k += 1
    reach = int(round(SOFT_REACH / HOP))
    for n, run in enumerate(runs):
        lo = max(runs[n - 1][1] + 1 if n else 0, run[0] - reach)
        while run[0] > lo and soft[run[0] - 1]:
            run[0] -= 1
        hi = min(runs[n + 1][0] - 1 if n + 1 < len(runs) else len(soft) - 1,
                 run[1] + reach)
        while run[1] < hi and soft[run[1] + 1]:
            run[1] += 1
    out = []
    for s0, s1 in runs:
        t0, t1 = (a + s0) * HOP, (a + s1 + 1) * HOP
        if out and t0 - out[-1][1] <= PAUSE:
            out[-1][1] = t1
        else:
            out.append([t0, t1])
    out = [(t0, t1) for t0, t1 in out if t1 - t0 >= MIN_VOICE]
    # a stretch the window's edge cuts off is a neighbour's sound (the score
    # before the line, the next line's first syllable), not this row's voice
    edge = [(t0, t1) for t0, t1 in out
            if t0 < a * HOP + EDGE or t1 > b * HOP - EDGE]
    return [x for x in out if x not in edge] or out


class Movie:
    """The movie font's measure and the flow's two-line layout."""

    def __init__(self):
        (_cw, _ch), self.adv, _cells, self.ext = fmv_subgen.render_atlas()

    def measure(self, text):
        return fmv_subgen.ink_width(text, self.adv, self.ext) if text.strip() else 0

    def lines(self, text, box=MAX_LINES):
        """The flow's layout, BOTTOM-HEAVY: over a picture the upper line is
        the shorter one, so the text covers as little of the image as it
        can (Gerber-Moron & Szarkowska 2018, the subtitling guidelines'
        pyramid). Grouping beats shape (the same research): the flow still
        decides where a line may end, and of its layouts with the same line
        count and faults, one that widens toward the bottom wins only when
        it costs at most PYRAMID_SLACK rhythm points - less than any line-end
        fault, so shape settles near-ties and never buys a worse break."""
        ranked = vwf_wrap.weigh(text.split(' '), width=fmv_subgen.MAXW,
                                measure=self.measure, tail=0, box=box)
        if not ranked:
            return [text]
        best = ranked[0]
        for key, lines in ranked:
            if (len(lines) == len(best[1]) and key[:6] == best[0][:6]
                    and key[6] <= best[0][6] + PYRAMID_SLACK
                    and all(self.measure(a) <= self.measure(b)
                            for a, b in zip(lines, lines[1:]))):
                return lines
        return best[1]


def breaks(words):
    """[(word index the subtitle may end after, kind)]: 0 a sentence end,
    1 a clause end, 2 before a conjunction (a clause starts there), 3 before
    another connector (a phrase starts there) - 2 and 3 only for a piece that
    cannot fit MAX_LINES otherwise."""
    out = []
    for i, w in enumerate(words[:-1]):
        if re.search(r'[.!?]["”’)]*$', w) and not re.search(r'\.\.["”’)]*$', w):
            out.append((i, 0))
        elif re.search(r'[,;:]["”’)]*$|[-—]$', w) or words[i + 1] in ('-', '—'):
            out.append((i, 1))
        elif words[i + 1].lower() in CONJUNCTIONS:
            out.append((i, 2))
        elif words[i + 1].lower() in vwf_wrap.CONNECTORS:
            out.append((i, 3))
    return out


def split_row(text, voice, movie, until):
    """[(text, (start, end) or None)] - the row as subtitles: split at the
    voice's pauses where a sentence (or, at a clear breath, a clause) ends,
    then wherever a piece still needs more than MAX_LINES lines. `until` is
    when the row must be off screen (the next row's start)."""
    words = text.split(' ')
    total = sum(len(w) + 1 for w in words)
    cum = np.cumsum([len(w) + 1 for w in words]) / total
    spoken = sum(b - a for a, b in voice)
    pauses = []
    run = 0.0
    for (a0, a1), (b0, _b1) in zip(voice, voice[1:]):
        run += a1 - a0
        pauses.append((run / spoken, b0 - a1, a1, b0))
    cuts = []                                   # (word index, pause or None)
    for i, kind in breaks(words):
        if kind >= 2 or (kind == 1 and min(i + 1, len(words) - i - 1) < MIN_WORDS):
            continue
        need = SENTENCE_PAUSE if kind == 0 else CLAUSE_PAUSE
        near = [p for p in pauses if p[1] >= need - 1e-6 and abs(p[0] - cum[i]) <= MATCH
                and all(p[2:] != t for _j, t in cuts)]
        if near:
            p = min(near, key=lambda p: abs(p[0] - cum[i]))
            # both sides must be readable in the voice they get: a pause
            # after "If you pursue him," leaves it half a second
            # the time each side really has: the left one until the right
            # one comes in, the right one until the row must be gone
            left = (cuts[-1][1][1] if cuts and cuts[-1][1] else voice[0][0], p[3] - GAP)
            right = (p[3], max(voice[-1][1] + LINGER, until - GAP))
            lo = cuts[-1][0] + 1 if cuts else 0
            left_chars = len(' '.join(words[lo:i + 1]))
            right_chars = len(' '.join(words[i + 1:]))
            if (left_chars / max(left[1] - left[0], 0.01) <= CPS
                    and right_chars / max(right[1] - right[0], 0.01) <= CPS):
                cuts.append((i, (p[2], p[3])))    # (pause start, pause end)
    # a piece that cannot fit MAX_LINES splits at its best clause end, timed
    # by its share of the voice
    pieces = _pieces(words, cuts)
    changed = True
    while changed:
        changed = False
        for lo, hi in pieces:
            if len(movie.lines(' '.join(words[lo:hi + 1]))) <= MAX_LINES:
                continue
            inside = [(i, k) for i, k in breaks(words) if lo <= i < hi
                      and (k == 0 or min(i - lo + 1, hi - i) >= MIN_WORDS)]
            if not inside:
                continue
            mid = (cum[lo - 1] if lo else 0) + (cum[hi] - (cum[lo - 1] if lo else 0)) / 2
            # both pieces keep at least a quarter of the line ("If you
            # pursue him," alone would flash by); a lopsided cut only when
            # no other exists
            base = cum[lo - 1] if lo else 0
            span = cum[hi] - base
            even = [c for c in inside
                    if 0.25 <= (cum[c[0]] - base) / span <= 0.75] or inside
            i = min(even, key=lambda c: (c[1], abs(cum[c[0]] - mid)))[0]
            cuts.append((i, None))
            pieces = _pieces(words, cuts)
            changed = True
            break
    # a piece runs from the pause before it to the pause after it. A cut no
    # pause made has nothing in the voice to follow: the pieces between two
    # anchors (pauses, the row's start and the moment it must be gone) share
    # that time by their length, so they read at one pace
    at = {i: pause for i, pause in cuts}
    out = []
    group = []
    for n, (lo, hi) in enumerate(pieces):
        group.append((lo, hi))
        after = at.get(hi)
        if after is None and n + 1 < len(pieces):
            continue                        # the next cut is free: keep going
        g_lo = group[0][0]
        before = at.get(g_lo - 1)
        t0 = before[1] if before else voice[0][0]
        # a lone piece keeps its voice; pieces of a free cut share the
        # silence after the voice too
        t1 = (after[0] if after else voice[-1][1] if len(group) == 1
              else max(voice[-1][1] + LINGER, until - GAP))
        sizes = [len(' '.join(words[a:b + 1])) for a, b in group]
        t = t0
        for (a, b), size in zip(group, sizes):
            share = (t1 - t0) * size / sum(sizes)
            out.append((' '.join(words[a:b + 1]), (t, t + share)))
            t += share
        group = []
    return out


def _pieces(words, cuts):
    ends = sorted({i for i, _t in cuts})
    starts = [0] + [i + 1 for i in ends]
    return list(zip(starts, ends + [len(words) - 1]))


def time_movie(subs):
    """[(start, end)] for the movie's subtitles in order: on with the voice,
    off LINGER after it, at least MIN_SHOW, at most CPS, never crossing. A
    subtitle still too fast to read when its time after the voice runs out
    comes in up to LEAD early, into the silence before it."""
    out = []
    for k, (text, (v0, v1)) in enumerate(subs):
        start = v0
        if out and start < out[-1][1] + GAP:
            out[-1] = (out[-1][0], max(out[-1][0] + 0.5, start - GAP))
        want = max(MIN_SHOW, len(text) / CPS)
        end = max(v1 + LINGER, start + want)
        if k + 1 < len(subs):
            end = min(end, max(v1, subs[k + 1][1][0] - GAP))
        if end - start < want:
            earliest = max(v0 - LEAD, out[-1][1] + GAP if out else 0.0)
            start = max(earliest, min(start, end - want))
        out.append((start, end))
    return out


def derive():
    """[(movie, start_s, end_s, [line, ...], note)] for every row: a row
    split into several subtitles keeps its note on the first."""
    image = disc_data.resolve_psx()
    sectors = movie_sectors(image)
    rows = [r for r in strlib.tsv_rows(SOURCE, required=('movie', 'start_s', 'end_s', 'text'))
            if (r.get('text') or '').strip()]
    movie = Movie()
    out = []
    for mv in dict.fromkeys(r['movie'] for r in rows):
        mine = [r for r in rows if r['movie'] == mv]
        db = voice_band_db(image, *sectors[mv])
        floor = quiet_floor(db)
        subs = []                               # (text, (voice start, end), note)
        for k, r in enumerate(mine):
            s0, s1 = float(r['start_s']), float(r['end_s'])
            lo = s0 - SEARCH if k == 0 else max(s0 - SEARCH, float(mine[k - 1]['end_s']))
            hi = s1 + SEARCH if k + 1 == len(mine) else min(s1 + SEARCH, float(mine[k + 1]['start_s']))
            text = ' '.join(r['text'].replace('\\n', ' ').split())
            note = (r.get('note') or '').strip()
            voice = voiced(db, floor, lo, hi)
            # a voice that runs into the search window's edge has no onset
            # (or end) the loudness can show - the score under it is as loud:
            # the row keeps its own start (end) there, so a rerun settles
            if voice and voice[0][0] < lo + EDGE and s0 < voice[0][1]:
                voice[0] = (s0, voice[0][1])
            if voice and voice[-1][1] > hi - EDGE and s1 > voice[-1][0]:
                voice[-1] = (voice[-1][0], s1)
            if not voice:
                subs.append((text, (s0, s1), note))
                continue
            until = (float(mine[k + 1]['start_s']) if k + 1 < len(mine)
                     else voice[-1][1] + 2.0)
            for n, (piece, span) in enumerate(split_row(text, voice, movie, until)):
                subs.append((piece, span, note if n == 0 else ''))
        times = time_movie([(t, span) for t, span, _v in subs])
        for (text, _span, note), (start, end) in zip(subs, times):
            lines = movie.lines(text)
            if len(lines) > MAX_LINES:
                lines = movie.lines(text, box=len(lines))
            out.append((mv, round(start, 2), round(end, 2), lines, note))
    return out


def align(sizes, jp, voice):
    """[(start, end)] per row: the voice's stretches cut into len(sizes)
    runs in order. English speech runs at an even pace, so a row's share of
    the characters is its share of the voiced time; each cut sits in a pause,
    the longer the pause the likelier, near where the characters put it and
    near the row's Japanese start `jp` (the PSP dub keeps its lines within
    about half a second of the Japanese; the pull stops growing at JP_REACH,
    so a piece the English lengthens - MV11's Philemon - is not dragged
    back). Fewer stretches than rows: the longest splits in half until there
    are enough."""
    voice = list(voice)
    while len(voice) < len(sizes):
        k = max(range(len(voice)), key=lambda j: voice[j][1] - voice[j][0])
        a, b = voice[k]
        voice[k:k + 1] = [(a, (a + b) / 2), ((a + b) / 2, b)]
    dur = np.cumsum([0.0] + [b - a for a, b in voice])
    want = np.cumsum([0.0] + list(sizes)) / sum(sizes)
    n, rows = len(voice), len(sizes)

    def cost(i, k):              # row i starts at stretch k
        gap = max(voice[k][0] - voice[k - 1][1], HOP)
        return (ALIGN_WEIGHT * abs(dur[k] / dur[-1] - want[i])
                + JP_WEIGHT * min(abs(voice[k][0] - jp[i]), JP_REACH)
                - np.log(gap / PAUSE))
    best = {(0, 0): (0.0, [])}   # (rows placed, stretches used) -> (cost, starts)
    for i in range(1, rows):
        nxt = {}
        for (_i, k0), (c, starts) in best.items():
            for k in range(k0 + 1, n - (rows - i) + 1):
                cand = (c + cost(i, k), starts + [k])
                if (i, k) not in nxt or cand[0] < nxt[(i, k)][0]:
                    nxt[(i, k)] = cand
        best = nxt
    starts = [0] + min(best.values())[1] + [n]
    return [(voice[a][0], voice[b - 1][1]) for a, b in zip(starts, starts[1:])]


def derive_dub():
    """[(movie, row, start_s, end_s)]: the dub's own subtitle rows
    (dub_subtitles.tsv, what the English voice says) as they are, timed to
    the English voice of the dub (fmv_dub.py's map): the voice found in the
    centre of each piece of the PSP track (centre_db), at its place in the
    movie, the rows aligned to it (align) and timed by the same rules
    (time_movie)."""
    import fmv_dub
    rows = [r for r in strlib.tsv_rows(fmv_subgen.DUB_SUBTITLES,
                                       required=('movie', 'start_s', 'end_s', 'text'))
            if etext.has_text(r['text'])]
    out = []
    for mv, (psp, lines) in sorted(fmv_dub.read_map().items()):
        jp = [float(r['start_s']) for r in rows if r['movie'] == mv]
        mine = [' '.join(r['text'].replace('\\n', ' ').split()) for r in rows if r['movie'] == mv]
        if not mine:
            continue
        db = centre_db(fmv_dub.psp_track(psp, RATE))
        floor = quiet_floor(db)
        voice = []
        for at, p0, p1, *_v in fmv_dub.placements(lines):
            voice += [(t0 + at - p0, t1 + at - p0) for t0, t1 in voiced(db, floor, p0, p1)]
        subs = list(zip(mine, align([len(t) for t in mine], jp, sorted(voice))))
        for k, (start, end) in enumerate(time_movie(subs)):
            out.append((mv, k, round(start, 2), round(end, 2)))
    return out


def write(subs):
    with open(SOURCE, 'w', encoding='utf-8', newline='\n') as f:
        f.write('movie\tstart_s\tend_s\ttext\tnote\n')
        for m, a, b, lines, note in subs:
            f.write(f'{m}\t{a:.2f}\t{b:.2f}\t{"\\n".join(lines)}\t{note}\n')


def main():
    if '--dub' in sys.argv:
        subs = derive_dub()
        if '--dry' in sys.argv:
            text = {}
            for r in strlib.tsv_rows(fmv_subgen.DUB_SUBTITLES, required=('movie', 'text')):
                if etext.has_text(r['text']):
                    text.setdefault(r['movie'], []).append(r)
            for m, k, a, b in subs:
                r = text[m][k]
                print(f"{m} {a:6.2f}-{b:6.2f}  (JP {float(r['start_s']):6.2f}-{float(r['end_s']):6.2f})  "
                      f"{r['text'].replace(chr(92) + 'n', ' / ')}")
            return
        timed = {(m, k): (a, b) for m, k, a, b in subs}
        rows, seen = [], {}
        for r in strlib.tsv_rows(fmv_subgen.DUB_SUBTITLES, required=fmv_subgen.SUBTITLE_COLS):
            if etext.has_text(r['text']):
                k = seen[r['movie']] = seen.get(r['movie'], -1) + 1
                if (r['movie'], k) in timed:
                    a, b = timed[(r['movie'], k)]
                    r['start_s'], r['end_s'] = f'{a:.2f}', f'{b:.2f}'
            rows.append(r)
        with open(fmv_subgen.DUB_SUBTITLES, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\t'.join(fmv_subgen.SUBTITLE_COLS) + '\n')
            for r in rows:
                f.write('\t'.join(r[c] for c in fmv_subgen.SUBTITLE_COLS) + '\n')
        print(f'fmv_retime: {len(subs)} dub subtitles timed in '
              f'{os.path.relpath(fmv_subgen.DUB_SUBTITLES, ROOT)}')
        return
    if '--dry' in sys.argv:
        for m, a, b, lines, _n in derive():
            print(f'{m} {a:6.2f}-{b:6.2f}  {" / ".join(lines)}')
        return
    # the retimed windows are the next pass's search windows: run until a
    # pass changes nothing, so the table is its own fixed point and a rerun
    # (after a wording edit) moves only what the edit touched
    for passes in range(1, PASSES + 1):
        subs = derive()
        before = open(SOURCE, encoding='utf-8').read()
        write(subs)
        if open(SOURCE, encoding='utf-8').read() == before:
            break
    print(f'fmv_retime: {len(subs)} subtitles after {passes} pass(es) -> '
          f'{os.path.relpath(SOURCE, ROOT)}')


if __name__ == '__main__':
    main()
