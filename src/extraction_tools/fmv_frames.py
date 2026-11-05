"""FMV frame extraction + measurement for the in-engine subtitle renderer.

  python src/extraction_tools/fmv_frames.py frames   decode movie frames (dev aid, needs ffmpeg)
  python src/extraction_tools/fmv_frames.py measure  measure plates/curves/patch -> src/assets/fmv/

The renderer draws over the game's own frames, so the videos that carry burned-in
text (the opening quote's moon card and the two ending poems) are composited as

    out = plate*(1-filter) + ink*text        (intro: the ink adds)
    out = plate*(1-filter), ink pastes       (poems: standard alpha paste)

where `plate` is one clean frame of the scene, `filter` is the dark layer the
game fades over it and `text` is the burned-in text's own fade. All three are
MEASURED here and committed as data; the build reads the data and never touches
ffmpeg or Java:

  src/assets/fmv/<MV>.png         the full plate frame (cropped only at build time)
  src/assets/fmv/<MV>.timing.tsv  per frame: scale (=1-filter) + one text alpha per band
  src/assets/fmv/<MV>.patch.tsv   every pixel the burned-in overlay touches (dilated),
                            with the plate's colour there - what the renderer
                            repaints each frame so the original text is gone

Frame numbers are 0-based stream frames (g_movie_frame's units).
"""
import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psx'))
import fmv_layout  # noqa: E402

IMAGE = os.environ.get('PERSONA_IMAGE') or os.path.join(
    ROOT, 'data', 'discs', 'Megami Ibunroku Persona - Be Your True Mind (Japan)',
    'Megami Ibunroku Persona - Be Your True Mind (Japan).bin')
PSX = os.path.join(ROOT, 'data', 'psx')          # the extracted disc tree (build's extractor)
WORK = os.path.join(ROOT, 'build', 'fmv_frames')
OUT = os.path.join(ROOT, 'src', 'assets', 'fmv')

ZOOM_VARY = 20                # per mille: a picture that changes size less
                              # than this over the entry is a still, and the
                              # pan's one-rectangle patch already covers it


def movie_raw(mv, path):
    """Raw-sector movie file from the extracted disc tree; the centralised
    extractor (extract.py) fills the tree in when the file is missing."""
    dest = os.path.join(PSX, path)
    if not os.path.exists(dest):
        subprocess.run([sys.executable,
                        os.path.join(ROOT, 'src', 'extraction_tools', 'psx', 'extract.py'),
                        IMAGE, PSX, path], check=True)
    return dest


def frames_dir(mv):
    return os.path.join(WORK, mv)


def bands_of(mv):
    """[(y0, y1, first_frame, last_frame), ...] the original text's line bands.
    The quote's bands come from the cards (each card's lines live in its own
    frame window); the poem is one block that fades as a whole."""
    if mv == 'MV1C':
        out = []
        for first, last, bands, _lines in fmv_layout.quote_cards():
            out += [(y0, y1, first, last) for y0, y1 in bands]
        return out
    first, last, rect, _top, _lines = fmv_layout.poem_cards()[mv]
    _x0, y0, _x1, y1 = rect
    return [(y0, y1, first, last)]


def cmd_frames():
    for mv, (_no, path, _plate, (s0, s1)) in fmv_layout.MOVIES.items():
        raw = movie_raw(mv, path)
        d = frames_dir(mv)
        os.makedirs(d, exist_ok=True)
        # only the text span (with margin) is ever read again - keep the cache small
        lo, hi = max(0, s0 - 8), s1 + 8
        for f in os.listdir(d):
            n = int(f[1:6])
            if not (lo <= n <= hi):
                os.remove(os.path.join(d, f))
        subprocess.run(['ffmpeg', '-v', 'error', '-i', raw, '-vsync', '0',
                        '-vf', f'select=between(n\\,{lo}\\,{hi})', '-start_number', str(lo),
                        os.path.join(d, 'f%05d.png'), '-y'], check=True)
        print(f'{mv}: frames {lo}..{hi} in {d}')


def gray(mv, f):
    import cv2
    return cv2.cvtColor(cv2.imread(os.path.join(frames_dir(mv), 'f%05d.png' % f)),
                        cv2.COLOR_BGR2GRAY).astype('float32')


def cmd_measure():
    import cv2
    import numpy as np
    if not os.path.isdir(WORK):
        raise SystemExit('fmv_frames: run "frames" first (needs ffmpeg, dev only)')
    os.makedirs(OUT, exist_ok=True)
    for mv, (_no, _path, plate_f, (s0, s1)) in fmv_layout.MOVIES.items():
        plate_img = cv2.imread(os.path.join(frames_dir(mv), 'f%05d.png' % plate_f))
        plate = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY).astype('float32')
        h, w = plate.shape
        bands = bands_of(mv)

        top = min(y0 for y0, _y1, _f, _l in bands)
        bot = max(y1 for _y0, y1, _f, _l in bands)

        def filter_of(f):
            # the dark filter's opacity from text-free strips strictly above and
            # below every text band
            g = gray(mv, f)
            strips = []
            if top >= 24:
                strips.append(slice(0, top - 4))
            if h - bot >= 24:
                strips.append(slice(bot + 4, h))
            if not strips:
                raise SystemExit(f'fmv_frames: {mv} has no text-free strip')
            strip = np.concatenate([g[s].ravel() for s in strips])
            ref = np.concatenate([plate[s].ravel() for s in strips])
            a = 1.0 - float(strip.mean()) / max(float(ref.mean()), 1e-6)
            return min(1.0, max(0.0, a))

        fas = {f: filter_of(f) for f in range(s0, s1 + 1)}

        def ink_of(f, a):
            # the ink's contribution in out = plate*(1-filter) + ink*text: the
            # plate term cancels the scene, so no texture/noise floor remains
            return gray(mv, f) - plate * (1.0 - a)

        # the replace patch: the pixels the burned-in overlay touches, inside the
        # text bands only. The ink is static and fades as a block per band, so
        # the mask is where that band's text is at full strength, averaged over
        # its plateau frames (a single frame's noise must not pick pixels), 3x3
        # keeps any antialiased fringe covered. Binary row runs; the colours are
        # read from the PNG at build.
        over = np.zeros((h, w), bool)
        band_masks = []
        for y0, y1, first, last in bands:
            fw = {f: a for f, a in fas.items() if first <= f <= last}
            means = {f: float(ink_of(f, a)[y0:y1].mean()) for f, a in fw.items()}
            peak = max(means.values())
            if peak <= 0:
                raise SystemExit(f'fmv_frames: band {y0}-{y1} of {mv} has no ink')
            plateau = [f for f, v in means.items() if v >= 0.9 * peak]
            avg = np.mean([ink_of(f, fas[f]) for f in plateau], axis=0)
            # any pixel the overlay modified - the white strokes (bright) and
            # the black outline (dark) both repaint, or the outline ghosts
            band = np.abs(avg) > 25
            band_masks.append((y0, y1, plateau, band))
            over[y0:y1] |= band[y0:y1]
        over[:, :8] = False       # the frame border carries decoder artefacts
        over[:, w - 8:] = False
        over = cv2.dilate(over.astype('uint8'), np.ones((3, 3), np.uint8)) > 0

        # per band: text alpha = the ink's mean contribution over that band's pixels
        curves = []
        for y0, y1, _plateau, band in band_masks:
            m = np.zeros((h, w), bool)
            m[y0:y1] = band[y0:y1]
            if not m.any():
                raise SystemExit(f'fmv_frames: band {y0}-{y1} of {mv} has no ink')
            best = max(float(ink_of(f, a)[m].mean()) for f, a in fas.items())
            curves.append([min(1.0, max(0.0, float(ink_of(f, a)[m].mean()) / max(best, 1e-6)))
                           for f, a in fas.items()])

        # the picture drifts a few pixels under the burned text while it fades
        # out, so the band - painted from the plate's frame - has to follow the
        # same drift or it sits off by a couple of rows. Measure the vertical
        # pan of every frame the fade leaves bright enough to see, in 1/8 px,
        # by shifting the plate by the fade and matching it to the frame on
        # every pixel the overlay does not touch.
        ok = ~over
        ok[:16] = False
        ok[h - 16:] = False
        ok[:, :8] = False
        ok[:, w - 8:] = False

        def moved(ref, dy):
            m = np.float32([[1, 0, 0], [0, 1, float(dy)]])
            return cv2.warpAffine(ref, m, (w, h), flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_REPLICATE)

        pans = {plate_f: 0.0}
        for f in range(s0, s1 + 1):
            if f == plate_f or (1.0 - fas[f]) < 24 / 255.0:
                continue
            g = gray(mv, f)
            ref = plate * (1.0 - fas[f])

            def err(d):
                return float(np.abs(moved(ref, d) - g)[ok].mean())

            coarse = min(range(-6, 7), key=err)
            pans[f] = min(((coarse * 8 + k) / 8.0 for k in range(-4, 5)), key=err)
        with open(os.path.join(OUT, mv + '.pan.tsv'), 'w') as o:
            o.write('frame\tdy8\n')
            for f in range(s0, s1 + 1):
                v = pans.get(f)
                o.write(f'{f}\t{"" if v is None else int(round(v * 8))}\n')

        # the picture can also change size under the burned text: the opening
        # quote's moon card shrinks ~3% while it brightens, which no pan can
        # follow and which pulls the band's edges a couple of pixels off. Fit
        # a similarity (scale about the frame centre + a small shift) on the
        # gradient magnitudes - gradients are blind to the fade's brightness
        # and colour grading - with the text and its halo masked out. The
        # scale is only worth a pre-scaled patch when it changes over the
        # entry; a still like the ending poems keeps the pan's path.
        okz = cv2.dilate(over.astype('uint8'), np.ones((15, 15), np.uint8)) == 0
        okz[:8] = False
        okz[h - 8:] = False
        okz[:, :8] = False
        okz[:, w - 8:] = False

        def gradients(im):
            gx = cv2.Sobel(im, cv2.CV_32F, 1, 0, ksize=3) / 8.0
            gy = cv2.Sobel(im, cv2.CV_32F, 0, 1, ksize=3) / 8.0
            return np.sqrt(gx * gx + gy * gy)

        gy_, gx_ = np.mgrid[0:h, 0:w].astype(np.float32)

        def similarity(ref_grad, frame_grad):
            """(scale, dx, dy) that maps the plate onto the frame:
            x' = s*(x-160)+160+dx, y' = s*(y-120)+120+dy."""

            def sample(s, dx, dy):
                sx = np.ascontiguousarray((gx_ - 160.0 - dx) / s + 160.0,
                                          dtype=np.float32)
                sy = np.ascontiguousarray((gy_ - 120.0 - dy) / s + 120.0,
                                          dtype=np.float32)
                return cv2.remap(ref_grad, sx, sy, cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)

            def score(s, dx, dy):
                a = sample(s, dx, dy)[okz]
                b = frame_grad[okz]
                a = a - a.mean()
                b = b - b.mean()
                d = np.sqrt(float((a * a).sum()) * float((b * b).sum()))
                return float((a * b).sum()) / d if d else -1.0

            best = (-2.0, (1.0, 0.0, 0.0))
            for s in np.arange(0.96, 1.0501, 0.01):
                for dx in np.arange(-3.0, 3.01, 1.0):
                    for dy in np.arange(-3.0, 3.01, 1.0):
                        v = score(s, dx, dy)
                        if v > best[0]:
                            best = (v, (s, dx, dy))
            s0, dx0, dy0 = best[1]
            for s in np.arange(s0 - 0.01, s0 + 0.0101, 0.002):
                for dx in np.arange(dx0 - 1.0, dx0 + 1.01, 0.25):
                    for dy in np.arange(dy0 - 1.0, dy0 + 1.01, 0.25):
                        v = score(s, dx, dy)
                        if v > best[0]:
                            best = (v, (s, dx, dy))
            return best[1]

        plate_grad = gradients(plate)
        zooms = {plate_f: 1000}
        seen = {}
        for f in range(s0, s1 + 1):
            if f == plate_f or (1.0 - fas[f]) < 24 / 255.0:
                continue
            key = hashlib.md5(open(os.path.join(frames_dir(mv), 'f%05d.png' % f),
                                   'rb').read()).digest()
            if key in seen:
                zooms[f] = seen[key]
                continue
            s, _dx, _dy = similarity(plate_grad, gradients(gray(mv, f)))
            zooms[f] = int(round(s * 1000))
            seen[key] = zooms[f]
            print(f'  {mv} {f}: zoom {zooms[f]}/1000', flush=True)
        vis = [v for f, v in zooms.items()
               if (1.0 - fas[f]) >= 24 / 255.0]
        zpath = os.path.join(OUT, mv + '.zoom.tsv')
        if vis and max(vis) - min(vis) >= ZOOM_VARY:
            with open(zpath, 'w') as o:
                o.write('frame\tzoom\n')
                for f in range(s0, s1 + 1):
                    v = zooms.get(f)
                    o.write(f'{f}\t{"" if v is None else int(v)}\n')
        elif os.path.exists(zpath):
            os.remove(zpath)
        print(f'{mv}: plate {plate_f} bands {len(bands)} patch {int(over.sum())}px -> {OUT}/{mv}.*')


if __name__ == '__main__':
    (cmd_frames if 'frames' in sys.argv[1:] else cmd_measure)()
