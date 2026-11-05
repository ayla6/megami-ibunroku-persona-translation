# The small font

## Font page and subsystems

The retail small font (menus, item / skill / Persona names, battle panels,
choice lists) uses a 4bpp 256×256 page with 8×12 cells: glyph `g` is at row
`g // 31`, column `g % 31`. Each character byte already identifies a glyph;
there are no free codes or Latin alphabet in the retail page.

- **`SF_LATIN`** — `src/injection_tools/smallfont_lc.py` draws `a..z` over
  26 rare hiragana plus `'` and `.`. The alphabet uses the low bytes of
  full-width `ａ..ｚ`, because name entry stores only the low byte of a typed
  character. These cells make English readable through the retail renderer.
- **`SF_VWF`** — `smallfont_vwf.py`, `vwf/smallfont.asm`,
  `vwf/sf_font.asm`, `vwf/sf_stubs.asm`, and per-overlay `smallfont.asm`
  files provide proportional widths, the TileMapWriteRow recorder, sorter
  hooks, the resident FONT.BIN anchor, the affinity pool, and renderers.

## Feature gates

`features.py` writes `build/features.inc`, shared by builders, assembly,
and verification. `SF_VWF` requires `SF_LATIN`; `features.check` rejects
an incompatible combination because the kit's widths and atlas assume
the Latin page.

| Gates | Page | Renderer |
|---|---|---|
| both on (default) | original fixed UI + separate regular/compact Latin atlases | producer-selected fixed/VWF |
| `--no-sf-vwf` | retail page + Latin cells | retail, readable English |
| `--no-sf-latin --no-sf-vwf` | untouched retail | retail, kana glyphs |

`--no-sf-kit` is an alias for `--no-sf-vwf`.

An affinity record's own 25-cell slot is the head of its line. A longer
line continues in the VWF kit's pool (`affinity_pool.bin`, 120 u16 offsets
plus FF-terminated tails, `smallfont_vwf.write_pool`); the recorder
appends that tail when it draws the row, so wording is never shortened to
fit the slot. Tails that end another tail share its suffix, so the blob
stores one copy per distinct ending, not one per record. In BTLP the pool
must end below `0x800F85B0`: the battle runtime writes a live heap pointer
there, so the zero words above it are not spare data. The whole drawn row
is capped at 47 glyphs (`SF_POOL_LINE_MAX`). With `SF_VWF` off those rows are not written and keep
their Japanese; `affinity.py` lists them in `build/affinity_gated.tsv`, and
`verify_disc.py` reports them as pool-carried rather than missing. Type and
subtype terminology used by those rows is summarized in
**docs/PERSONA_TYPES_REFERENCE.md**.

Diagnostic gates:

- `SF_NOCLEAR` (`--sf-noclear=1`) replaces the pre-pass clearing store in
  `@@blank_do` with a `nop`. Retail and VWF text both draw; keep it off
  in normal builds.
- `DIAG` enables counters in `sf_state` for inspection through gdb.

## Known limitation: choice picker bar

With `SF_VWF` on, ADV `<FF0E>` choices have a reported missing picker bar,
although the cursor moves and selects options. The expected bar is a
pulsating, semi-transparent red line, two pixels tall, with two pixels of
margin below the font's white baseline. The bar is visible with
`SF_VWF` off. Text QA and disc-byte verification do not prove this visual
interaction correct; check it in game with the patch enabled.

## Font-page ownership

The regular authored sheet supplies proportional Latin art. The primary
ADVCMD menu page keeps the original fixed font (with the existing lowercase
extension) in its text band and packs regular/compact Latin sprite pairs into
the bounded rectangle x=16..239, y=196..255. The palette strip and choice picker
are preserved. Other page copies own different bottom-half artwork/palettes:
only their text band is updated, not this rectangle. The field menu loaders
load the full ADVCMD page before drawing proportional menus. Battle's shorter
page keeps its current proportional art and does not use the field atlases.

## Row lifetime and rendering

The recorder retains complete names separately from the caller's logical cell
count. Items and demons use a terminated 21-byte scratch buffer; fixed record
heads and tail banks remain bounded by their actual storage. Item and demon
names keep their 80-pixel fields and full PSP-US wording: uncentered full-name
rows select natural advances, 2 px word spaces, or compact glyph artwork
with 1 px word spaces (4 >> stage), choosing the first stage that fits. Both
font faces retain a 1px letter gap. Names no tier can fit remain drafts;
centered rows keep natural advances. Reservation and emission share the
recorded tier; see the text-layout specification.

The sorter reserves complete rows before temporarily marking their map cells
empty. It restores the logical map before returning. A page clear or rewrite
therefore retires the corresponding records. Sprites include libgs' signed
framebuffer origin, and packet storage is separate for the two active OTs.

## Placement and data safety

- ADV's packed extension is bounded by `ADV_SF_EXTENSION_END`; DNG/S2D's
  recorder/centering and renderer runs are bounded by their `SF_HELP_SIZE`
  and `SF_ROW_SIZE` definitions. Assembly assertions enforce these budgets;
  an overrun is a build error. Item/demon copy wrappers share their head/tail
  traversal to keep complete names within the overlay-owned storage.
- The recorder's bank walk divides by `SF_GLYPHS = 215`, not a power of
  two. `SF_BANKS = 4` banks alias the same cells under another CLUT.
- Regenerate derived translations and font products with their owning
  tools (`port.py`, `make_vwf_font.py`, `smallfont_vwf.py build`), never by
  restoring them from Git. The authored art
  (`src/asm/font/sheet.png`, `src/assets/fonts/smallfont_page_modified.png`,
  `src/assets/fonts/smallfont_page_compact.png`) is preserved; keep
  working-tree edits.
- Scroll order, choice gates, and nameplate rules are specified in
  [TEXT_LAYOUT_SPEC.md](TEXT_LAYOUT_SPEC.md). Family porters own their
  rows; the last-resort porter must not rewrite those tables.

## Condensed-name QA

`test_condensed_names.py` checks least-tier selection, minimum advances,
iterator inputs and the shared builder/porter gate. `test_smallfont_runtime.py`
executes the assembled MIPS recorder and emitter with R3000 load/branch delays:
all 35 over-natural-width item names and both demon names retain their full
wording and expected glyph positions in ADV/DNG/S2D through both sorter paths.
It also checks every CLUT bank, all three stages (stage 3 draws the compact
face with 1 px word spaces), unchanged centered and non-name rows, the
fixed-cell producer flag, blank markers, and the measured compact advance.
Producer-owned character-name rows and statically addressed 3/4-cell captions
carry a fixed-cell flag. They retain original artwork and 8px spacing; their
classification uses source instructions and the Char layout, not names or
per-screen exceptions. Atlas bitmap labels stay bitmap labels.

The GPU sorter body is intercepted; this is renderer QA, not an in-game
playtest. Run `smallfont_vwf.py verify` after assembly for disc-file readback.

## Editing and measuring the compact face

See [`src/assets/fonts/README.md`](../src/assets/fonts/README.md) for the
Latin-only editable sheet, generated cell index and live stage/width report.
The compact face is authored art with its own measured advances; the regular
face is unchanged. Builds never overwrite either authored PNG.
