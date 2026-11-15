"""Preview the spoken-movie subtitles: one .mp4 per subtitled movie, to watch.

  python tools/fmv_preview.py [--table PATH] [--tag NAME] [MV12 ...]

Writes scratch/fmv_preview/<movie>_<tag>.mp4 (tag 'now' by default) from a
subtitle table (default translation/manual/fmv/subtitles.tsv): the movie read
from the PSX Rev 0 disc image, upscaled 3x, with the subtitles burned in the
way MOVIE.EXE draws them - the movie font, white over a black outline, each
line at the renderer's own position (fmv_subgen LINE_BASE / LINE_STEP) and
the FADE ramp at both ends. A look for timing and line breaks; the shipped
pixels are the renderer's (fmv_subgen), not these.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, HERE)
import disc_data  # noqa: E402
import fmv_subgen as fs  # noqa: E402
import strlib  # noqa: E402
from fmv_retime import movie_sectors, SOURCE  # noqa: E402

OUT = os.path.join(ROOT, 'scratch', 'fmv_preview')
SCALE = 3


def stamp(t):
    t = max(0.0, t)
    return f'{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}'


def ass(rows):
    fade = int(fs.FADE / fs.FPS * 1000)
    out = ['[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {fs.FRAME_W}',
           'PlayResY: 240', 'ScaledBorderAndShadow: yes', '',
           '[V4+ Styles]',
           'Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, '
           'BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, '
           'MarginR, MarginV',
           f'Style: Sub,Public Sans Medium,{fs.FONT_PX + 1},&H00FFFFFF,&H00000000,'
           '&H00000000,0,1,1.3,0,8,0,0,0', '',
           '[Events]', 'Format: Layer, Start, End, Style, Text']
    for start, end, lines in rows:
        n = len(lines)
        for k, line in enumerate(lines):
            y = fs.LINE_BASE + (k + (2 - n)) * fs.LINE_STEP - 12
            out.append(f'Dialogue: 0,{stamp(start - fade / 1000)},'
                       f'{stamp(end + fade / 1000)},Sub,'
                       f'{{\\pos({fs.FRAME_W // 2},{y})\\fad({fade},{fade})}}{line}')
    return '\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--table', default=SOURCE)
    ap.add_argument('--tag', default='now')
    ap.add_argument('movies', nargs='*')
    args = ap.parse_args()
    rows = list(strlib.tsv_rows(args.table, required=('movie', 'start_s', 'end_s', 'text')))
    movies = args.movies or list(dict.fromkeys(r['movie'] for r in rows))
    image = disc_data.resolve_psx()
    sectors = movie_sectors(image)
    os.makedirs(OUT, exist_ok=True)
    for mv in movies:
        subs = [(float(r['start_s']), float(r['end_s']), r['text'].split('\\n'))
                for r in rows if r['movie'] == mv and r['text'].strip()]
        sub_path = os.path.join(OUT, f'{mv}_{args.tag}.ass')
        with open(sub_path, 'w', encoding='utf-8') as f:
            f.write(ass(subs))
        lba, count = sectors[mv]
        with open(image, 'rb') as f:
            f.seek(lba * 2352)
            raw = f.read(count * 2352)
        out = os.path.join(OUT, f'{mv}_{args.tag}.mp4')
        fonts = os.path.dirname(fs.font())
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'psxstr', '-i', 'pipe:0',
                        '-vf', f'scale={fs.FRAME_W * SCALE}:{240 * SCALE}:flags=neighbor,'
                               f'ass={sub_path}:fontsdir={fonts}',
                        '-c:v', 'libx264', '-crf', '18', '-preset', 'veryfast',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', out],
                       input=raw, check=True)
        print(f'fmv_preview: {mv} ({len(subs)} subtitles) -> {os.path.relpath(out, ROOT)}')


if __name__ == '__main__':
    main()
