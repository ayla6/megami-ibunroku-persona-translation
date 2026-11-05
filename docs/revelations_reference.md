# Revelations: Persona (US PS1) — reference-disc notes

User-supplied reference disc: `data/discs/Revelations - Persona (USA)/Persona (USA).bin`
(git-ignored, like all disc data). Extracted to `scratch/revel/data/` with the
`src/extraction_tools/psx/extract.py` logic, bypassing the disc guard.

## Layout

- Same 349-file tree as JP; main EXE is `SLUS_003.39` (JP: `SLPS_005.00`).
- **US overlay slot = 0x80065A84** (JP rev0: 0x800643C4, rev1: 0x800643A0),
  proven by the loader table at SLUS file offset 0x94C (same table position
  revdiag used for the JP slot).
- Same file set overall; NAME.BIN (87,176 B) is 6 KB smaller than JP's.

## E*.BIN container (verified against E0.BIN)

The community `EBIN_Structure.md` / `persona_ps1_ebin.bt` description
matches the PSX event files:

- Sector 0 is a zero-terminated table of cumulative `u16` sector offsets.
  Entry `i` is sectors `t[i]..t[i+1]`; byte offset = sector × `0x800`.
  The community doc calls these "pointers multiplied by 0x800"; that is
  the same cumulative table.
- Each entry starts `08 00 10 80` = `0x80100008`, then a `u32` end
  address. The image base is `0x80100000`.
- The section header is `0x1F8` bytes (the first 8 are the load/end
  words), metadata is `0xED0` bytes, and the command stream/text pool
  starts at section + `0x10C8`. The metadata is not text and `efile.py`
  preserves it as opaque bytes.
- Text boxes end in `FF 01` and are zero-padded to 4 bytes;
  `FF 55 00 00 <u32>` says "box at this address". Command ops are
  `FF op` with `op >= 0x20`; text control codes have `op < 0x20`.
- The last sector-table value is EOF, not another entry (hence the
  `i < count-1` rule in the community template).

## Box geometry and scroll

The retail box is 15 cells wide and 4 rows tall, with three visible lines
and a fourth scroll row. A scroll is not a page turn:

- `<FF02>` waits and scrolls; the box keeps its context. In ADV it belongs
  after line 3, before the fourth line in the retail text.
- `<FF04>` clears to a fresh window and counts as a new box.
- BTLP/BTLEVT use the same box, with `<FFF6>` for a line; the interpreter
  waits when its 3×15-cell window fills and scrolls the fourth line in.
  `<FFFB><FFF7>` is the hold/pause page skeleton, not a clear.
- The Revelations README's 30-character-per-line limit is the retail
  fixed-cell renderer's budget. Current port layout is defined in
  [TEXT_LAYOUT_SPEC.md](TEXT_LAYOUT_SPEC.md); do not apply the retail
  character budget or scroll model to its builders.

## Dialog engine: NOT variable-width

The US release kept the fixed 16px-cell interpreter:

- Same `sltiu v0, a2, 0x80` single/two-byte classify (US ADV.BIN file offset
  0x337C → VA slot+0x337C).
- Same cell math: VRAM glyph cache slot `((pos+1) % 16, (pos+1) & ~0xF)`,
  x = col*4 + 0x3C0 halfwords, y = row + 0x100 — identical to JP retail.
- Glyph renderer (`jal` after classify): 2bpp 8×16 font (FONT.BIN is 8 KB,
  256 glyphs, game-code ordered: 0x01-0x1A a-z, 0x31-0x4A a-z again,
  0x76-0x8F A-Z, 0x90-0x99 0-9), source at `code*32` from 0x801E0000,
  composited into the 16px cell with a separate 1px-offset shadow pass.
- **No width table, no pen** — each letter occupies a full 16px cell.
- Bottom pen marker: same `pos` cell counter retail JP uses; nothing
  smarter.

Conclusion: our VWF engine (pixel-granular pen, proportional widths) is
strictly better than what Atlus USA shipped; there was nothing to port.

## Text encoding

- US event text (ADV/E0-E3.BIN) is single-byte game codes; **0x00 is the
  space**; the same FF02/FF03/FF04 control codes as JP.
- Two-byte `80 xx` codes address the same 256-glyph font (glyph xx).
- The name-screen message pages inside US NAME.BIN are still Japanese glyph
  data — the US release shipped Japanese text on that screen.

### Control codes — which ones count as a textbox

These codes distinguish a new textbox from a scroll within one textbox.

| code | meaning | counts a box? |
|------|---------|---------------|
| `FF01` | end of message (dismiss) | — |
| `FF02` | **wait** — press to scroll; the box **keeps** its context | no |
| `FF03` | newline within the box | no |
| `FF04` | **page** — clears to a **fresh** window | **yes** |
| `FF05 xx xx` | pause | no |
| `FF0E xx` | scroll-to-choice | no (its structure is the box) |
| `FF06 xx` | original: font colour (00 white, 01 yellow, 02 blue, 03 purple); port: portrait/style card | no (its structure is the box) |
| `FF07`/`FF08`/`FF0F xx` | name insert | no |

So a message's box count is **`1 + count(FF04)`**. `FF02` is a scroll, not
a boundary — `FF02 FF04` is "wait, then turn the page", while `FF02 FF03`
is "wait, then carry on in the same box". Counting `FF02` too double-counts
every page turn and adds a phantom box for every scroll.

## Name entry

- US: **one keyboard page** (6 rows × 13 keys, letters/digits/marks in the
  US font), `g_name_field` initialized to **2** ("asks for the hero's name
  only, so it starts on the third field" — the Nick-only US flow).
- US name buffer: **8 single-byte chars** (JP: 5 wide slots of u16). The port
  uses the JP 5-wide layout for save compatibility; widening would touch the
  save field and every name-display path.
- JP: 4 keyboard pages (`g_keyboard[4][6][10]` at NAME.BIN 0x4310: hiragana,
  katakana, ABC, dakuten), grid columns 0 and 11 are the button columns
  (tabs / side buttons), SELECT cycles pages `(page + 1) & 3`.

## JP NAME.BIN symbol table (bonus)

JP NAME.BIN's tail carries the whole game's linker symbol table (the US copy
is stripped to zeros): entries `[u8 0x9A][u32 VA][u8 module]` +
length-prefixed names — `name_entry`, `fmcur*` (name-form cursor),
`formnameawrt`, `formposmatch`, `formemptychk`, `advmes*`, `keymsg*`,
`curact*`, `savanm*`, plus the casino/battle/dungeon modules. Addresses are
from the monolithic pre-split link (not overlay VAs), but names and relative
order are real — use as a naming map when reverse-engineering any module.

## Map labels

US map-label data uses short names.
