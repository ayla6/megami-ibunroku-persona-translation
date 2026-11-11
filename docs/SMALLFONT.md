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
stores one copy per distinct ending, not one per record. BTLP stores a
byte-indexed copy below its sound-work buffer, with a build-time bound; its
helper and displayed row are outside the live species-graphics pointer array.
See `docs/research/battle-memory-investigation.md`. The whole drawn row
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

The persona status bottom bar does not go through the recorder and renderer,
and each overlay compiles its own copy of it: ADV and DNG (which also draw
the fusion bar) and S2D's overworld status page. Each copy's sprite-cell
writer stores the regular face's cell coordinates - the same mapping
`sf_variant_uv` gives the text renderer - and the glyph's advance; bit 7 of
the writer's page argument selects the face, so every other `CellsWriteRow`
caller keeps the retail fixed-cell atlas. The bar
keeps retail's two cel entries: the arcana row at dx=0/dy=0 and the name row
at retail's dx=0x58/dy=4 (expanded to sixteen cells), so the name is its own
cel-entry line, 88 px right of the arcana and 4 px (half a character) lower,
as in the Japanese original.

DNG's dungeon-menu Persona Data page uses the same sprite-row path for its
race + demon-name bar. Both cel entries carry `SF_BAR_MARK`; the race block
keeps retail's six cells (race names are at most six glyphs) and the
demon-name block grows from ten cells to twenty in the image extension, so
`demon_name_copy_dng` can place the full name. Retail's dx=0x40/dy=0xC
placement of the name entry is unchanged.

S2D's overworld Persona Data page (`s2d/pdata.asm`) is the same rewrite on
its own copy of `PersonaDataDraw`. It keeps retail's six-cell race block and
two-entry cel list, but its name entry points at the status bar's shared
sixteen-cell block (the S2D image has no free sixteen-cell run), and both
pages rewrite that block before their own slot renders. Retail's old
ten-cell name block is the helper's 88-byte home; the full name comes from
`demon_name_copy_s2d`, and both rows pass page bit 7 so the race codes map to
the regular VWF Latin face. The overworld status page, the Analyze page's
demon/card views and the dungeon/ADV copies therefore draw the same bar from
the same code shape.

The empty-slot rule under a skill row is retail's eight long-vowel marks
(`*_SPELL_RULE_GLYPHS`, eight `0xCC` cells). With base `0xD7` those codes
land inside the small-font atlas, so the recorder claims the row and the
renderer advances it like any other row; a wrong table address makes the
recorder claim a different run and draw its codes as Latin glyphs. A rule
constant must therefore name an address the overlay's own retail code
materialises (S2D's skill row builds `0x8009E5F4` at six sites), never a
hand-picked neighbour.

The same screen is linked into several overlays: ADV, DNG and S2D each carry
a copy of `PersonaDataDraw`'s bar tail, `StatusPersonaNames`, `CellsWriteRow`
and `DrawSpellName` (DNG's skill row is compiled with different defines).
`tools/tests/test_overlay_clones.py` fingerprints those retail copies by
instruction shape (data literals masked) and fails when a copy exists that
is not a declared, rewritten patch site; a new clone is a build-visible
decision instead of a screen that silently stays retail.

The script VM (`MsgStep` cases 9-12: item, skill, demon, Persona inserts)
is linked into ADV, DNG and S2D too, and each copy resolved only the
record's ten-glyph head. All three now divert the case to a stub that
copies the complete FF-terminated name into the overlay's scratch and
enters the insert loop with `left = 0xFF`; `tools/tests/test_msg_name_inserts.py`
executes each overlay's stubs on the R3000 and checks every translated row
reaches the loop intact. S2D carries the identical VM, so a new overlay
with the same cases is a stub to add, not a screen to leave truncated.

`DrawSpellName` builds the full name with `skill_name_copy` into the
overlay's name scratch and hands that to the recorder; the recorder's tiered
row still occupies the caller's ten-cell (80 px) footprint. That is the rule
in all three copies of the function - ADV (`adv/draw_spell.asm`), DNG
(`dng/pdata.asm`, every caller: status menu, status Persona page, skill draw
and Persona Data) and S2D (`s2d/draw_spell.asm`) - so a long skill name is
drawn whole instead of being cut to its ten-glyph record head.

The sorter reserves complete rows before temporarily marking their map cells
empty. It restores the logical map before returning. A page clear or rewrite
therefore retires the corresponding records. Each claimed row becomes a chain
of packets: one draw mode shared by the row (every atlas cell is on the same
page; the bank only changes CLUTs), then packets of at most `SF_NODE_SPRITES`
(3) sprites, four GP0 words each, so no linked-list node exceeds the GPU's
16-word command FIFO.
The two packet buffers follow the active libgs framebuffer. All ordering
tables sorted within that frame share its cursor; an ordering-table change
does not reset it or overwrite packets still linked by another table.
Sprites include libgs' signed framebuffer origin, and packet storage is
separate for the two active OTs.

## Battle configuration and controller boards

BTLP draws its config, control-key, tactics and flavour boards as
`BtlGfxTextList` records through `BtlDrawObjText`, not through the ADV/DNG/S2D
tilemap path. `battle_board_text.py` discovers the lists structurally
(`scan_lists`) and translates one only when every visible row has English and
fits before the next row at the same y; otherwise the whole list keeps its
Japanese (`plan()['deferred']`). Rows behind `count == 0` descriptors and
deliberate blank runs are structural, not missing text.

English is deduplicated and packed longest-first into the union of the shipped
lists' source pools. Records another descriptor still reads are protected, and
records behind hidden rows are reusable; over-capacity is a build error. A
runtime-assigned value (`Normal`/`Easy`) keeps its own retail record, and the
shared descriptor's count covers the longer word with the shorter value
space-padded. A sole top row that straddles the list origin is centred with
`x = -(rendered_width // 2)`.

The resident `btl_owned_span` lookup reads the ownership directory at
`BTL_BOARD_SPANS_ADDR`. The builder places its compact entries in reclaimed,
immutable board text; it lists every arena pool plus the ANALYZE
name/spell/trait buffers. The debug board's fitting English is included in the
same producer-owned VWF path. Rows without a consumer stay Japanese and
`verify_disc.py` reports them.

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
