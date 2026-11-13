# Ending-page and FMV text sources

The ending text is stored as pixels rather than glyph strings, so it is
transcribed. Generated images stay in `/tmp`, never in the repository.

## PSP ending text images

The U.S. PSP `pack/end/ENDALL.BIN` GIM archive holds the ending text panels and
the staff roll. `python src/extraction_tools/psp/end_images.py gim <dir>`
writes all 116 standalone GIMs byte-for-byte; `get <entries> <dir>` converts
entries to PNG (ENDALL has a 16-byte container header before each GIM; the
image data starts at the frame offset in the GIM header).

`translation/manual/ending/ENDALL.tsv` is the transcription: one row
per entry (`entry`, `offset` = entry offset, `text` with literal `\n` line
breaks), read off the image. A credits job title keeps the image's own `■`
marker; a two-column screen reads column by column.
`end_images.py transcript` writes it to
`data/extracted_text/psp_us/pack/end/ENDALL.tsv`, which every reader uses.

| archive entry | entry offset | content |
|---|---:|---|
| `#17–23` | `0x15c000–0x17e800` | Seven character profile endings |
| `#24` | `0x184000` | "As for his fate... That's for you to decide." |
| `#25` | `0x185000` | SEBEC epilogue; final prose matches PS1 `MV25` |
| `#26` | `0x18d000` | SEBEC epilogue; final prose matches PS1 `MV1E` |
| `#31` | `0x1b8800` | Snow Queen good ending |
| `#32` | `0x1c0800` | Snow Queen bad ending |
| `#84` | `0x50f000` | Original Version Staff: Direction, Art Direction |
| `#85–90` | `0x51f800–0x572000` | Original Version Staff (job title, names) |
| `#92` | `0x593000` | `Cogito, ergo sum`, `-Rene Descartes`, `fin` |

Entries #50–58 repeat #81–90's original-staff text in another layout; #33–49,
#60–80 and #93–96 are the PSP remake and U.S. localization staff; #27–30 are
shadow/mask graphics.

`src/extraction_tools/matching/endtext_map.tsv` maps transcript lines to PS1
`EXE/END.BIN` TIM pages (`first_line`/`end_line` slice an entry; several rows
for one page join in order; a row with no entry is a page the PSP lacks).
The PSP text is images, so nothing is generated: `src/injection_tools/endtext.py`
cuts the transcription into pages itself when it draws them. The pages the
PSP lacks are written in `translation/manual/ending/pages.tsv`
(`page | about | text` - filled text also replaces a PSP page; empty keeps
the Japanese picture). `src/injection_tools/endtext.py` renders `build/EXE/END.BIN` and previews in
`build/previews/endtext/`. Layouts: `c` centred prose, `p` profile (name,
then paragraph), `n` credits (the retail roll's two columns: job titles right-aligned, names
beside them), `l` the roll's logo sheet (the names under Direction and Art
Direction, from #84); see docs/TEXT_LAYOUT_SPEC.md, "The ending pages".
Pages the PS1 roll lacks are written in `pages.tsv`: Voice Act, Velvet Room
Vocal and Debug, and two pages appended to END.BIN after the roll for the PSP
release's U.S. localization staff (executive producer to project
coordinator, translators, editors - from the PSP-US roll's #94/#95 screens;
its voice recording and QA are left out). `end_exe/roll.asm` shows them in
every ending with the roll, before the Presented By card. The
names in the white-on-transparent GIMs only show composited onto black. `--qol=debug`
starts any ending from the title (src/asm/qol/README.md). The PS1 credits pages for
Voice Act, Velvet Room Vocal and Debug have no PSP counterpart. The poem tails from
entries #25/#26 became the ending-movie poem overlays
(`translation/manual/fmv/poems.tsv`, laid out in
`src/injection_tools/fmv_layout.py`, rendered in-engine).

The PSP quote is extractable glyph data: `src/extraction_tools/psp/boot.py
extract` writes separate JP/US quote caches and the PSX target table
`translation/generated/fmv/opening.tsv` (`port_quote.py`) from `BOOT.BIN`.

## PSP video scenes versus PS1 in-game scenes

- The PS1 opening quote and ending poems are burned into PS1 movies. The PSP
  release uses different opening/ending anime. Its quote is in `BOOT.BIN`; its
  ending prose is in the `ENDALL.BIN` images above.
- PSP US `MV25.pmf` is an anime, not the PS1 graduation poem. There is no PSP
  `MV1E.pmf` counterpart for the PS1 hospital epilogue.
- PSP US `MV11` and `MV2D` have visible Japanese subtitle text despite the
  U.S. game release. Their exact in-video text and any subtitle tables are
  still being checked against the PSP files.
- ENDALL prose, character profiles, fate text, and Snow Queen endings are now
  mapped from entries #17–26 and #31–32. Other GIMs are credits/art assets.
