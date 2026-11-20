# PSP audio and the English dub

`--mods=english-dub` gives the spoken movies (Philemon's scenes, every movie with
rows in `translation/manual/fmv/subtitles.tsv`) the PSP-US English voice,
timed to the Japanese lines, and the party's Persona calls in battle their
PSP-US takes (section 4). Only the movies' XA audio and the calls in the
party's sound banks change; the video, the sector layouts, the players and
every other sound are retail. The PSP soundtrack and the PSP movie video do
not go in.

## 1. What the PSP-US disc holds

| where | what | format |
|---|---|---|
| `USRDIR/MOVIE/MVxx.pmf` | 44 movies, 1375.6 s | PSMF: H.264 480x272 29.97 fps + ATRAC3plus 44.1 kHz stereo |
| `USRDIR/sdata/bgmNN.at3`, `end_*.at3` | 43 music loops + 2 endings | RIFF ATRAC3plus 44.1 kHz stereo, `smpl` loop |
| `USRDIR/sdata/SE_*.BIN` | 10 sound-bank files, 724 waves | PPHD/PBD banks, PS-ADPCM, 8/11.025/48 kHz |

The movie tracks are the only streamed voice.

**PSMF audio.** A 0x800-byte `PSMF0015` header, then MPEG-PS. Audio is
private stream 1 (0xBD), sub-stream 0; each payload opens with a 4-byte
sub-stream header, and the payloads concatenate to ATRAC3plus frames of
`0F D0 pp pp 00 00 00 00` + 744 bytes (pp = 0x285C: 44.1 kHz, stereo,
(0x5C+1)*8 bytes). ffmpeg's PS demuxer does not list that track, so the
extractor demuxes it and hands ffmpeg the frames in an OMA (EA3) header.
Every movie demuxes to whole frames.

**at3.** `fact` = (samples, encoder delay); `smpl` loop points are in the
decoder's timeline, delay included, as ffmpeg outputs it. The extractor cuts
the delay and shifts the loop with it. The PSP plays them by id:
`PlayBgm(id)` (EBOOT .text 0xCCB0) names the file from the table at
.data+0x8C8 (va 0x263D88): id 1..0x2B = bgm01..bgm43, 0x2C/0x2D = the
endings.

**Banks.** Bank header (sound count, PHD size, PBD size, 0x2C, sound
table), PPHD (PPPG, PPTN, PPVA), the PBD body at the next 16-byte boundary.
PPVA = 0x20-byte header + 16-byte entries (body offset, rate, size, flags);
its chunk size stops 8 bytes into the last entry; all-FF entries are empty.

**The PSP movies are new footage with the same speech timing.** Their
pictures match no PSX movie (16x12 thumbnails slid against every PSX movie:
no sustained match), and their score matches no PSX track, but the English
lines of MV12..MV1B start within -0.6..+0.5 s of the Japanese ones (MV12 to
+1.4 s at its first line, where the opening score is as loud as the voice).
MV11's PSP cut is 21 s longer: its five lines sit 24-25 s later, with the
same line-to-line rhythm. The movie beds are not PSP bgm tracks (no
correlation), so the voice cannot be separated from the PSP score - the dub
carries the PSP score with it.

Extract everything with

```
python src/extraction/psp/audio.py [movie|bgm|se ...]
```

into `data/psp_audio/` (local): `movie/*.flac`, `bgm/*.flac`,
`se/<file>/<bank>_<n>.wav`, with `movie.tsv`, `bgm.tsv` (samples, loop
points) and `se.tsv`. Needs ffmpeg (atrac3plus decoder) and numpy.

## 2. The dub (`src/mods/english-dub/fmv_dub.py`)

The map (`translation/generated_mappings/fmv_dub.tsv`) is set by ear in the
editor: per movie one piece of the PSP English (MV11's is in PSP MV2C - the
PSP's MV11 is a Japanese copy), placed so its voice starts at `jp_start`,
fading in over `en_lead` and out over `en_trail`.

- **Mix.** The PSX audio is the complement of the English: gone under the
  voice (no JP leaks), crossfading back over the fades, whole wherever no
  English plays. The English plays at its own speed and keeps its own
  levels, scaled by one gain per movie: the PSX master against the PSP's,
  measured on the same Japanese voice (`fmv_dub.psp_gain`: the median over
  the movie's subtitle rows of the PSX level over the PSP-JP movie's,
  `data/psp_audio/movie_jp/`). The PSP master is 2-5 dB louder; a line the
  English cast delivered softer or louder than the Japanese stays so.
- **XA.** Written over the STR's own audio sectors (37.8 kHz stereo 4-bit,
  `xa.py`); MVFF, a copy of MV14, gets the same dub.

## 3. Review files

`python src/mods/english-dub/fmv_dub.py review [DIR]` renders from the line
map, the retail disc and the PSP audio (no build) into `build/dub_review/`:
`MVxx.mkv` (the movie's frames stored lossless - FFV1 320x240 15 fps, no
container players read holds MDEC - with audio tracks dub / retail Japanese
/ the PSP-US source unaligned and the subtitle rows as a track) and `MVxx.STR` (the
dubbed STR; `mpv`, `ffplay -f psxstr`).

`python src/mods/english-dub/dub_editor.py` (http://127.0.0.1:8765/) edits the line map by
ear: the movie timeline (subtitles, JP audio, the dub) over the PSP timeline
(the cuts), lines moved, trimmed, faded, added (a shout no subtitle holds)
or removed. Saved rows get manual = 1.

**Subtitles.** A dubbed movie has subtitles of its own:
`translation/manual/fmv/dub_subtitles.tsv` (movie, start_s, end_s, text,
note), what the PSP-US voice says - `subtitles.tsv` is the JP voice's, and the
two differ (the PSP's Philemon goes on "I am Philemon, a dweller between
consciousness and unconsciousness", the PSX voice stops at his name). Their
timing comes from `python tools/fmv_retime.py --dub` (`--dry` prints it), in
place: the English voice found
in the centre of each placed PSP piece (mid less side: the PSP score is wide
and as loud as the voice), the rows cut into its stretches by character share,
pause length and their Japanese start, then timed by the JP subtitles' rules.
The editor's subtitle lane (under the dub; the subtitle showing is under the
picture) adjusts it. `fmv_subgen.py` builds a second MOVIE.EXE payload with it
(`build/movie_subs_dub.bin`), which `subs_boot.asm` takes under `MOD_ENGLISH_DUB`; a
row the table lacks keeps its own timing, so with an empty table the two
payloads are identical. The credits of a dub build carry the English voice
cast (`translation/manual/ending/dub_pages.tsv`, `endtext.py --dub`).

## 4. Battle voices (`src/mods/english-dub/battle_voice.py`)

The PSX party speaks once in battle: its call as it summons a Persona.
`BtlMemberMotion06` plays `BtlSePlay(3, rand() % 3 + 3)` - one of
sub-sequences 3..5 of the member's own bank, an entry of `B/PS.BIN` picked
by its key (`BtlLoadMemberBank`), each one note of one tone of one VAG
(22050 Hz; 20812 Hz in entry 8). Entries 0 and 1 are the same bank. The
PSP plays the same calls from `SE_PRS`, three banks per character (bank
3(c-1)+r, r random, `BtlMemberMotion06` at US BOOT 0x98944), in another
character order: PSP character c is PS.BIN entry 0, 2, 5, 4, 3, 6, 7, 8, 9
- matched from the PSP-JP takes (re-recorded, so likeness 0.5-0.7, which
picks one bank in nine), consistent with Mark as PSX member 5 (`src/mods/black-mark/images.tsv`).
The map is `translation/generated_mappings/battle_voice.tsv`.

`--mods=english-dub` puts the PSP-US takes in their place: trimmed, at their own
level: the PSP calls are mastered as the PSX ones (the PSX calls over their
PSP-JP takes: median -1.2 dB, inside the takes' own +-2 dB), so no gain, and
a call delivered softer or louder than the Japanese stays so; a bank whose
loudest call would pass 0.98 of full scale is lowered as a whole. (The
movies do take a gain: their PSP master is 2-5 dB louder, measured on the
same Japanese recording, fmv_dub.psp_gain.) Encoded closed loop to SPU ADPCM in the disc's VAG layout. A bank's
three calls share their JP bytes; where the English is longer they go a
whole semitone or more lower in rate (19644 Hz in entries 0/1, 18542 Hz in
5 and 8, 17501 Hz in 7 and 9) and their tone's centre note goes up as much,
so they play at their own speed. PS.BIN keeps its size and every byte but
the calls, their tones' centre notes and the VAG size tables, so the sector
table, the pack buffer and the SPU allocation stay retail.
`battle_voice.py review` writes every call, JP and English, to
`build/dub_review/battle/`.

The PSP also gives each character an `SE_CHR` bank of four lines the PSX
has no counterpart for: melee attack (wave 0), gun attack (wave 1), taking
a blow (wave 2) and going down (wave 3), played from `BtlMemberMotion02`,
`BtlActorMotion07` and `BtlActorMotion08` (US BOOT 0x9AD18, 0x9B1B4,
0x7642C, 0x779D8; the PSP keeps the PSX's `g_btl_member_motion` table entry
for entry). They are not ported: the PSX's own hurt and down sounds are one
bank for everyone (slot 6) and no member bank has room for them.

## 5. Open

The PSP-US disc differs from the PSP-JP in the speech only: SE_PRS and
SE_CHR of the sound banks (every other bank, the music and the endings are
byte-identical) and the movies MV12..MV17, MV1B, MV2C (dubbed here) and
MV27, MV28, MV2A - animated scenes the PSP added, with no PSX movie.


- The voice outside the subtitle rows (shouts, the classroom lines before
  Philemon in MV11) stays Japanese.
