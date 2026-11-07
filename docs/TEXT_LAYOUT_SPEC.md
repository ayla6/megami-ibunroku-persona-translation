# Text layout & box spec

What this file is: the single statement of every rule that decides how an
English line is spelled, broken, labelled and boxed on this disc. Code that
disagrees with it is a bug in the code. Wording is never decided here - the
user owns the wording and the PSP-US script is copied verbatim; this is only
about the shape the words take on screen.

Read it top to bottom: glyphs -> lines -> boxes -> labels -> gates.

---

## 0. Where the rules live (one owner each)

| rule | owner |
|---|---|
| which glyph a character prints as, and its advance | `src/injection_tools/make_vwf_font.py` -> `src/asm/font/vwf_*.bin` |
| where a line breaks | `src/injection_tools/vwf_wrap.py` (`flow_layout` / `flow_lines`) |
| how many boxes, and where a scroll is | `src/extraction_tools/matching/port_story.py` (`paginate`) |
| code pairing, labels, gates | `src/extraction_tools/matching/port_derive.py` (`fit_codes`, `codes_match`, `derive`) |
| what a family's box can hold | `src/extraction_tools/matching/port_caps.py` |
| which ADV messages have a one-row viewport, and how wide | `src/injection_tools/sysmsg.py` (`display_size`) |
| which words a description abbreviates | `src/extraction_tools/matching/port_descs.py` (`house_style`) |
| build-time proof (bytes on the disc) | `src/injection_tools/tstatus.py qa`, `tools/verify_disc.py` |
| looking at all of it | `tools/textvis/` (page + `serve.py`) |

Nothing else decides a break, a box or a glyph. A porter that hand-places a
line is a bug; a table that stores a fixed break is a bug unless the source
broke there.

---

## 1. Glyphs and the font

The regular small-font sheet supplies proportional Latin artwork; the compact
Latin-only sheet supplies an independently editable narrower face. The primary
ADVCMD menu page retains the original fixed-cell font plus the existing lowercase
extension in its text band. The two normalised Latin sprite faces are stored in
text-band cells the translated game never prints as kana: every page copy
already receives those 84 rows, so the art survives the menus' later TIM
uploads and the shorter 2D/D0x pages. Cells the retail renderer still reads -
the ASCII repertoire, the blank space cell, the lowercase extension and the
punctuation fallbacks - are never claimed; the regular face takes the first
spare cells and the compact face the next, in encoder order. Their allocation
is derived from the encoder and bounded at build time. Other page copies retain
their own UI/palette data and receive only the original-font text band; they
must not receive a whole-page overwrite. Battle retains the original fixed-cell
Latin face at its retail coordinates. Its proportional Latin art occupies a
separate encoder-derived kana-cell run in the same short page; only registered
VWF name rows remap their texture coordinates into that run. The battle short
page owns its own art from cell 0xCD up (battle icons), so the full-width
punctuation fallbacks (`smallfont_vwf.PUNCT_FALLBACK`) are ADV/DNG/S2D-only:
a character the tables print on every page must be a redrawn `smallfont_lc`
glyph (`,` `.` `'`), whose cell lives in the rows the battle copy carries
from retail. Small-font names retain their
complete encoded wording; the retail caller's cell count limits only its
logical map write, not the VWF name. Dungeon FF0A skill-name inserts use the
existing dialogue VWF printer with a scratch buffer of `SKILL_MAXLEN + 1`
bytes (the name bound plus the FF terminator); the builder must still reject
any name that cannot fit every destination. The persona status bottom bar is
sprite cells, not a text row, and every overlay carries its own copy: ADV and
DNG (which also draw the fusion bar) and S2D's overworld status page. Each
overlay's rewritten `CellsWriteRow` stores the regular face's cell coordinates
- the same mapping `sf_variant_uv` gives the text renderer - plus the glyph's
advance. Its cel list reproduces
retail's two entries: the arcana row at dx=0/dy=0 and the name row at retail's
dx=0x58/dy=4, expanded from ten cells to sixteen. That is retail's second
cel-entry line: eighty-eight pixels right of the arcana's origin and four
pixels (half a character) lower. Bit 7 of the writer's page
argument selects that remap and pins the regular face (the writer has no text
tier); every other `CellsWriteRow` caller keeps the retail fixed-cell atlas.
DNG's dungeon-menu Persona Data page uses the same sprite-cell path for its
race + demon-name bar: both cel entries are marked, the race block keeps
retail's six cells and the name block grows from ten to twenty cells in the
image extension, with retail's dx=0x40/dy=0xC placement unchanged. ADV's
Velvet Room card page draws the same race + demon-name bar: its ten-cell name
block sits immediately before the page's cel list and cannot grow in place,
so the name entry points at the status bar's sixteen-cell block instead. The
card page and the status page are separate layouts; each rewrites that block
before its own slot renders, so the shared cells never carry a stale name.
The race block keeps retail's six cells and the card list keeps retail's
dx=0x40/dy=0xC placement. Skill
rows are ordinary recorder rows: every overlay copy of `DrawSpellName`
(ADV, DNG and S2D) builds the complete name with `skill_name_copy` in that
overlay's scratch and the tiered row keeps the caller's ten-cell (80 px)
footprint, so a long skill name is drawn whole rather than cut to its
ten-glyph record head.
Family storage/scratch bounds remain enforced. In battle object text,
source-proven translated skill and Persona slots read the battle width table's
packed bearing and advance through `sf_glyph_layout`; the field kit reads its
own table's normal/compact nibbles through `sf_field_metric`. Both keep a
1-px letter gap. The battle adapter only supplies retail row state and packet
coordinates; it does not define another font, mapping or layout rule. The
row's mode and pen are latched for the whole draw; rows with kana or other
non-text cells retain the retail path. The build
verifies every translated skill's rendered width against the skill menu's
120 px name column (`skills.NAME_PX`), not against a glyph count, and checks
all skill and Persona glyph cells in each battle font page.
The battle skill-menu header's "Cost" label is a static row whose string lives
in the Persona header bank's fourth slot (`BATTLE_LABEL_BUF`). It is outside
the owned Persona range, so it keeps the retail fixed-width path (8 px steps
and fixed atlas cells), matching the original label. Numeric rows and image
labels are not registered.

BTLP's second text window (battle help lines, definition texts and choice
help) draws one 16×16 sprite per **staged cell**, not per retail character.
The window keeps two counters: `+0x1C` is the retail character cursor, which
is also the VWF engine's `pos`, so it never claims a line start it has not
reached; `+0x20` is the staging counter, which `btlp_activate` leaves at the
highest activated cell of the row + 1. A row whose pen reaches the fifteenth
cell (225-240 px) therefore has `pos` 14 but fifteen staged cells, and a draw
bounded by `pos` loses that cell's sprite (the final glyph of the line). Both
BTLP text windows draw by `+0x20`; `btlp/vwf_hooks.asm` rewrites every loop
bound of `BtlTextWindowDraw` (`tools/tests/test_btlp_help_sprite_count.py`).

The battle name ownership map is one 16-bit bitmap with two buffers beside it:
the three Persona header name slots own bits 0..2 (`PERSONA_HDR_BUF`, 48 bytes
at `PERSONA_HDR_STRIDE` = 16) and skill slot `i` owns bit
`SKILL_BIT_OFFSET + i` (`SKILL_MENU_BUF`, seven 24-byte slots,
`SKILL_MENU_STRIDE` = 24, bits 3..9). The Persona bank's fourth slot holds the
static "Cost" label but is not owned. Each Persona
producer resets or updates ownership before buffer reuse; untranslated IDs
retain retail rendering. Numeric rows and image labels are not registered.
Persona ink is checked against the
actual PRS-CHG frame/background and adjacent column, and against the header label;
the retail packet count, transforms and animation remain unchanged. The item-list
name producer writes complete source-English names into twelve 21-byte slots.
The two-column list reserves 100 pixels per name and shifts each count 12 pixels
right; the build checks the ink of every eligible item against that width. The
alternate spell-list producer uses the same slots, terminates its retail ten-cell
names, and retains retail rendering. The shared semantic lookup reads the current packed
item-ID vector; a generation byte is cleared before either producer reuses the
buffer and committed only after the item writer finishes. The alternate skill
writer invalidates item ownership. Item descriptors reference the expanded slots;
count data, transforms and animation stay retail, and atlas/ink checks cover all
eligible item IDs. Count buffers and labels are
outside the registered ranges; within a registered range no glyph or colour
test grants ownership. Outside every registered range the shared lookup keeps
the original font and 8-px pitch, including party HUDs, fixed labels and card
personality rows. Glyph content does not opt a literal or member name into VWF.
The party marker name retains retail `x = 12 - n * 4` centring.
Literal battle-board headings at the top of a text list, straddling its local
origin and carrying equal nonempty space padding on both sides, are centred
on that origin with `x = -(cell_count * 8 // 2)`. The builder discovers
these from validated retail 8×12 text-list descriptors and the shared text-cell
class, not wording or row addresses. Only x changes; padding, count, colours,
transforms and unpadded/left-aligned or non-text rows remain untouched.
`battle_text_layout.py` generates the positions with the font metrics and
verifies their assembled halfwords; without `SF_VWF` they stay retail.
Skill names are stored in `SKILL_MAXLEN`-glyph (`SKILL_MENU_STRIDE`-byte, 24)
slots and accepted by measured rendered width (120 px), not by a glyph
count; the full-name copy helper prints the whole stored name and ends it with
FF, so the descriptor's `SKILL_MAXLEN` count is an upper bound and short names
cost only their own glyphs, not blank padding. Small-font sprites are clipped to the signed GsBG viewport: `[x-mx+drawX, x-mx+drawX+w)` by
`[y-my+drawY, y-my+drawY+h)`. Scroll shifts the text within that viewport,
not the viewport itself. Vertical scroll uses the retail signed modulo of the
map height: a row wholly above the viewport can reappear at the next ring copy.
The VWF pass only claims 8×12 text-cell maps; maps with other cell geometry stay
with the retail sorter. The pre-pass and emitter select the same copy, including partially clipped rows.
If a row needs multiple simultaneous vertical copies, it remains with the retail
sorter rather than suppressing text the bounded VWF path cannot emit whole.
Horizontal scroll is normalized by the map width; pre-pass and emitter select the
same visible ring copy. Retained full-name and pool tails may extend beyond the
physical map edge when their single visible copy fits the viewport. If a viewport
exceeds the map width, an earlier copy is visible, or both counted horizontal
copies are visible, retail retains the row: this fallback may show only the
caller's logical cell count and is not evidence that a retained tail is visible.
These geometries remain unsupported for complete full-name display until a QA
proof or a renderer that handles their copies is available. Cropped left/top pixels advance texture U/V
equally; empty intersections emit nothing, but every glyph still advances the pen.
A claimed row is one GPU packet: an 8-byte header (the tag plus one draw mode
shared by the row's glyphs, since every atlas cell uses the same page) and
16 bytes per visible glyph (four GP0 words). Only visible glyphs reserve space.
The blank word-space cell advances the pen but reserves and emits no sprite.
The tag's length is written after the row ends: one draw-mode word plus four
words for each sprite. Whole-row fallback retains retail text when capacity is
unavailable; temporary suppression always restores the complete logical cell
run. Row records and full-name scratch belong to the
loaded overlay, with free slots reused before another live row is evicted.

The small-font item and demon name row is retail's ten 8-px cells (80 px);
the count column and every following field start after them. A full name is
measured head plus tail. Uncentered full-name rows choose the least aggressive
font/spacing tier that fits their caller's fixed-cell footprint: tier 0 uses
the regular face and 4-px spaces; tier 1 keeps that face and reduces word
spaces to 2 px; tier 2 selects the compact face, whose word spaces are
1 px (4 >> tier). Both faces
retain a 1-px letter gap. Their ink is left-normalised into separate cells;
the advance includes the final letter gap (80 px advance permits 79 px ink).
Reservation and emission select the same metric nibble, font atlas and
word-space shift (4 >> tier). A
blank in both faces is marked 0x11 and advances 1 without a sprite. Centered
rows keep the regular face. The row never grows and
wording never changes. If no tier fits, the porter refuses the name
(`over limit Npx/80px`, reporting natural width), queues its draft in manual,
and leaves Japanese on disc.

Font style and row spacing are independent of wording. Structurally identified
Char.name producers and statically addressed 3/4/5-cell captions mark their rows
fixed-cell (a3 bit 14); they retain the original font and 8-px pitch. The
recorder still retires overwritten rows but the sorter never suppresses a
fixed-cell row. Variable item/demon/skill lists and ordinary proportional
labels keep VWF. Atlas/UI bitmap elements remain with their original renderer.
The compact face is separately authored artwork with its own measured
advances, not a squeeze of the regular face; normal builds never regenerate or
overwrite either authored sheet. Both sheets are Latin-only 14-column grids;
a new compact template copies complete regular glyphs without resampling.

The overworld arrival banner and plate use the same temporary +240-px viewport
offset on every draw, including interpolated 60fps subframes. That offset is
restored after the text draw; it is not an animation counter to gate on real ticks.

Small-font rows whose original producer centers a field retain that intent:
the producer marks its row, and its VWF origin moves by
`(8 * cell_count - sum(packed advances)) // 2`. Reservation and emission use
the same origin. Unmarked rows and rows containing tabs keep their original
origin regardless of wording, length, or padding. The controller title and
place-label producers are discovered from the original writer instructions;
all their branches use the same rule. This is the tile-map counterpart to
the battle heading rule.

In small-font option rows `<TAB>` represents the next 40-pixel stop relative
to the row origin, matching the option markers. It draws no glyph. TSV uses a
token because literal tabs separate columns. Tabs follow a bank-zero glyph;
their encoded cell is the blank first cell of the next atlas bank.

The opt-in `saves` patch (`--qol=saves`) uses the same bottom-aligned, single 320×192
panel in ADV and OPEN: x=0, y=40, bottom=232, raised eight pixels so the
bottom border meets the visible screen edge rather than being clipped.
There are no SLOT headers,
plates or per-card outer frames. The LOAD/AGASTYA badge remains visible.
Agastya opens this list directly, with no SAVE / GAME END selector. Only its
badge is initialized before card checking; the parent selector's text and
cursor are never drawn. Cancel from the list closes the facility.
The facility prepares the full list before its shared fade-in, so badge,
frame, cursor and text appear together. Initial card/format prompts fade up
before becoming interactive, rather than waiting for input behind a black screen.
Save-menu entry returns to the unmodified retail facility fade setup and call:
step 4, limit 128, 33 displayed frames including the final frame. Initial
prompts use the same retail rate. After card loading and list setup, hidden preparation
renders 30 black frames before the fade. DuckStation accelerates 30 frames after the
last card access; this phase keeps that acceleration out of the visible ramp. It adds
about half a second without card fast-forward, including on real hardware. There is
no fade-speed override; other facilities' entry rates and the tree's fade-out are unchanged.
Before a still-hidden prepared screen fades up, both the six BG-layer RGB
triplets and the independent sprite fade level are reset to black. The retail
fade terminates from BG layer 0's brightness; slot blackout alone is insufficient
and can reduce it to one frame. Already-visible initial prompts are not reset.
`save_ui.py` composes OPEN's panel from ADV's retail frame tiles and the same
40×16 tile map that ADV's window/box routines draw; it stores eight shared
160×12 8bpp strips in OPEN.BIN, wholly below resident FONT.BIN at 0x801E0000,
and uploads them to build two texture halves at VRAM x=832/912, y=256, with
32 palette entries at x=288,y=480. Outer tiles retain retail palette 0 and
inner boxes palette 1, combined losslessly into one indexed palette. The
second half starts at u=32 in texture page 0x9E. Both panel sprites set
attribute bit 24 for 8bpp: GsSortFastSprite masks the tpage field to 0x1F,
so the tpage field alone cannot select texture depth. Upload follows card scanning
on every list rebuild. It does not replace the title's confirmation art.

The title's memory-card messages share texture page 0x1D with the panel:
`OpenMessageOpen` (0x800861D0) uploads each 16×16 cell to
`(0x340 + j*4, 0x100 + i*16)` and samples it at `v = i*16`, i.e. the panel's
top-left rows. The save patch moves that scratch to `y = 0x1C0` (448), the
first row below the panel's 256..447 strips, and adds `0xC0` to the sprite
`v`; the rect and the sprite therefore still agree. 448..495 at x=832 is
otherwise free (ADVCMD0's frame starts at x=896), so "Loading data" and the
other card messages no longer erase the panel while a card is read.

Text starts at x=12/172,y=52, eight name cells on line 1. On line 2, the
retail 16px level-label artwork is at relative x=0, the two-digit level at
x=24, retail 32px TIME artwork at x=48, and `hh:mm` at x=88. There are no
seconds. Level and hour tens are blank when zero; minutes keep their zero.
The text is 128px wide, rows are 24px apart, and columns are 160px apart.
The cursor occupies the 144×24 inner row at x=8/168,y=52+24*row.
Both badges place the sphere at (16,8) and the lettering at (8,16).
`qol/saves.inc` owns the shared offsets and label UVs. The TIME strip is
u=16,v=108 (retail cell 0x364), not u=0,v=96. Labels are atlas art, never letters.
Empty/unreadable rows retain those labels and colons, with retail dash
cells in the name and numeric fields. FF ends a saved name, and a redraw
clears its remaining cells. Serials are ordering metadata, not row text. An
out-of-range level (outside 1..99) makes a summary unreadable, including
checksum-valid all-FF headers. FFFF is an unset serial, never the newest order;
new serials advance from the highest usable counter, saturating at FFFE.
OPEN's 238 text sprites fit below confirmation slots 262..268; its LOAD badge
sprites 10/11 are never cleared by list initialization. List text/cursor/panel
sort at depths 4/5/6, behind confirmation labels/cursor/backing at 0/1/2.
Empty-row dashes use a separate CLUT at (320,480), with ink extracted from
ADV's grey font bank. Labels and colons keep their normal palette. This is
not sprite brightness, which the title draw loop resets every frame.
The SLOT 1/2 bitmap
builder used outside the unified list assigns its shadow a nontransparent
black CLUT entry (0x8000), preserving index zero for transparency. The label is
one artwork for every atlas that carries it: it is composed from the letters of
OPEN's label atlas (S from "YES", L from "LOAD", O from "OK?", T from
"CONTINUE", the digits from the kana row), so OPEN's buttons and ADV's slot
header cells at u=96/144,v=48 draw the same pixels, centred in their 48px cell
as the retail kana was. A retail cell's ink is
palette indices 1..14 only; index 15 is that cell's own shadow and is never
copied as a letter. The label's shadow is derived from the finished label: the
same pixels in black, one pixel right and one pixel down.

Dialogue control operands are raw bytes, not printable VWF glyphs. The codec
decodes operands of FF05/FF06/FF0E/FF0F as explicit `<xx>` tokens; legacy blank
operands encode as zero, never the visible-space byte 0x88. System-message
choices show warning text with one wait, then clear to a fresh question page;
there is no wait between the question and its choice command.

With `SF_VWF` enabled, the BTLP CONTACT offer uses a separate transformed-quad
small-font path. Its private personality records retain the complete PSP-US wording, with one FF
terminator per record. Only pointers into that private bank, and the offer name
in the Persona-header scratch, use the small-font bearing and advance table
(offer_position/offer_advance), and those same two ranges alone also sample the
proportional atlas: the quad renderer's eight glyph loads route through the
shared `btl_sf_art_code` selector, so a VWF pen row never renders fixed-cell
artwork. Every other effect row retains retail 8px advances and retail cells.

The row's art mode travels in `at`, which the glyph loop reads nowhere else:
the gate's position phase records 0 for those two ranges and -1 for every other
row, and the selector leaves a negative mode raw. It stays valid for all eight
loads of the row because the selector's own remapping paths leave `at`
non-negative, and because the loop's one `at` use - the retail advance hook's
delay-slot store - reloads it first. The advance phase therefore never writes
`at`: its window exit (`offer_name_ret`) masks with `t4-1` instead, so the
position phase gets -1 and the advance phase keeps the loaded address. The four
`a0` sites call the selector directly; the four `v0` sites need the answer in
`v0` and use the six-instruction wrapper at `offer_art_v`
(`vwf/vwf_offer_art.asm`).
The existing four-column/two-row frame, bit associations, GTE transform, texture,
palette, packet format, OT linking and animation are unchanged. Full labels use
one quad per glyph and therefore more packets than the shorter retail labels;
the offer name uses those same packed advances and bearings. Its producer
copies the full PSP-derived demon name, including any tail beyond the ten-byte
record head, into the mutually exclusive Persona-header scratch. The builder
checks its complete quad footprint against the CARD column.
The ANALYZE status board's translated rows are registered by their producer
buffers, never by descriptor address or by glyph content. The header name row,
the six spell rows and the affinity value line are always-owned spans
(`ANALYZE_NAME/SPELL/TRAIT_BUF.._END` in `addresses.inc`), checked only when
the producer-range directory has no match. The header uses the same
source-derived tails after its race prefix; its existing 24-byte row holds the
complete name and terminator. The affinity value line is the record's own
25-cell head plus, when the English is longer, exactly the pool tail the field
kit already appends (`build/affinity_pool.bin`). That pool holds 120 u16
tail offsets plus one copy of each distinct `FF`-terminated ending: a tail
that ends another tail reuses its suffix, so the blob fits beside the code.
It must end below `0x800F85B0`, the first word the battle runtime writes in
that run (a heap pointer), so no live BTLP state is overwritten. The battle
producer finishes
the line in a 47-cell buffer and the row descriptor follows that buffer and
its cell bound; the drawer stops at the line's FF, so the unanalysed three-cell
`?` row is unchanged. Every other board row - ailments, full-width
rank/kind labels, the "MAG ATK" / "MAG DEF" label slots at
`0x800DEA2C`/`0x800DEA34`, the "TRAIT:" label at `0x800DEA3C`, the
untranslated label block above them and the shared kana label bank - stays
outside the spans and keeps the retail 8 px path. A board row's glyphs are not
all text: inside an owned row the battle bridge renders a text cell
proportionally but leaves every non-text cell (numbers, icons, kana and the
unanalysed `?` placeholder) on its original small-font cell at the retail
8 px pitch. The battle width table encodes that split; the unanalysed trait
placeholder is the retail `?` cell, not a proportional glyph. The builder checks
storage and the status column; the suite binds the spans to the live board
list, rejects any other static list that points into them, and drives the
installed lookup over all 37 rows.
the total concurrent UI packet-buffer bound is not yet proved. The builder checks the
full 8px quad bounds of both rows in every column against the 208px frame and
checks that neighboring columns cannot overlap; unencodable or non-fitting
source wording is not shortened.

The held-START dungeon strip is ten 16px cells wide, not a dialogue box.
Its field uploader matches the original 20-byte floor field to the shared
PSP-title table, then centers the entire title using the dialogue font's
advances. It composites all 16 rows into a 160x16 4bpp image with the field
renderer’s ink and one-pixel shadow and uploads it to the same VRAM strip.
Unmatched fields keep the retail glyph-ID path. A title wider than 160px,
with non-VWF bytes, or missing its allocated glyph is a build error; wording
is never shortened or replaced to fit.

1. **One code space.** The encoder prints `ASCII 0x20..0x7E` plus the extras
   (`…` `￥`), which take the codes immediately above. The renderer's
   printable range **must equal** that whole space: a byte the encoder can
   emit but the renderer refuses is drawn as a **space**, silently.
   (`make_vwf_font.asm_code_space()` fails the build if the two disagree.)
2. **Every printed character has ink.** A character the wording prints but the
   sheet leaves blank is a build error, not a rendering surprise. A character
   that *folds* (section 1.4) needs no cell of its own.
3. **The sheet is the art.** The sheet's cells win over anything drawn in
   code; a stand-in glyph is only allowed to fill a cell that has no ink at
   all, and it must say so at build time. Font allocation subtracts every
   declared resident small-font gate, replay and registration range. Identical
   adjacent glyph-row bytes may share storage; the resulting complete glyphs
   remain byte-identical to the sheet. After assembly, the build reads back all
   allocated glyphs, lookup tables and non-spare retail atlas cells.
4. **Spelling folds, never wording.** A typographic mark and its ASCII twin
   are the same character: `’`->`'`, `“”`->`"`, `–—`->`-`, `−`->`-`. The fold
   happens where text becomes bytes or pixels (`etext.spell`), never in a
   table. **A character whose PSP glyph-table entry already spells it the
   ASCII way is not a fold at all** - the table is the source (`＊` is `*`
   because `src/extraction_tools/psp_glyphs.tsv` unit `0x0056` says so).
5. **Codes with parameters are never printed.** `<FFFD>x` (a branch) and the
   name slots `<FF07|0F|08>` take a parameter byte/character. Neither the
   code nor its parameter is a glyph: they measure 0, draw 0, and are skipped
   whole by every reader. The message-machine name inserts below are the one
   exception: their code measures the room the inserted name takes, while
   their parameter still measures 0.
6. **Shadow** is drawn at `+1,+1` and only from rows 0-14 (row 15 has no room
   in the cell). It is derived from the glyph's own ink. Each overlay's
   entry establishes its palette indices before drawing: BTLP uses retail
   ink 1 / shadow 2, while ADV uses 2 / 1. BTLP's 4bpp overlap uses the
   shared OR compositor (index 3), whose battle text CLUT is the ink colour.
7. **The player's name** is a slot 8 glyphs wide (the entry's cap; the
   nickname was always 8). Any measure that has to price it prices it as 8
   of the widest glyph.

---

## 2. Lines (the break rules)

The box is **240 px**; a line may use **239** so the engine's own wrap never
skips a line, and only the final line of a run may use the full 240.

The **battle** text box pads 6 px horizontally instead of 12, so its frame
leaves a 251 px line (`vwf_wrap.BATTLE_BOX_WIDTH`). The VWF engine still draws
the original 15-cell grid there (240 px), so battle text - negotiation lines
and the player's answers (`talktl.ANS_W`, no cursor indent) - is laid out at
239 px until the engine draws a 16th cell per battle row.

The **description bank** - the skill/item one-line help - is PSP-US wording in
a 239 px line. Its porter applies three token abbreviations before measuring,
so a re-port produces them: `damage` -> `DMG` (the amount; the hazard in
"damage floors" stays prose), a trailing ` status` after the status' own name,
and `Instant` -> `Insta`. Wording still wider than the line is routed to manual
as a draft; no other word is shortened automatically.

**A one-row message viewport has no second line.** Some ADV system messages
(the Velvet Room's yes/no prompts, the coin-shop notices, ...) are drawn by
`BgMapInit` into `g_bg_layers[4]` with a rectangle the call site chooses.
When that block proves `h == 0x10`, the viewport is one 16 px row: a line or
page move has no row to move to, so it is spelled as the word gap it stood
for and the whole wording must fit the line that rectangle shows - `w` px,
read from the same block. That is 240 px for the 15-cell messages; the
coin-shop notice draws into 11 cells and its line is 176 px, so the default
240 px budget never applies where the code proves less. `sysmsg.display_size()`
reads the rectangle from the code that opens each message (not from a list of
messages); `port_caps.dest_cap` reports a proven one-row row as a fixed
one-line destination, `port_caps.dest_line_px` carries the proven width, and
`sysmsg.build` / `port_derive.lay_out` collapse `<FF03>`/`<FFF6>`/`<FF04>` to
spaces. A call site that proves no local geometry because it inherits one from
an earlier screen is not guessed: it stays an ordinary box. Wording wider than
the line never ships: the message keeps its Japanese, a tool's wording is
routed to manual as `over limit Npx/Mpx; <draft>`, a human's filled row is
kept and reported (`build/sysmsg_drafts.tsv`, which names the row, its width
and the draft), and no wording is ever shortened automatically. Nothing here
fails the build - an unshortened draft is work, not a broken box.

The two battle text windows share the byte-pair decoder, not its output
buffer. The primary window owns `BTLEVT_BUF_ADDR` (1024 bytes); the second
status window owns `BTL_SECOND_BUF_ADDR` (512 bytes after the compositor
ring, ending before the resident CD sector buffer). Opening either window
must preserve the other's read pointer and text. Negotiation payloads are
byte-aligned and enter the decoder after the story-only halfword marker
check. Build bounds and assembled-CPU tests cover the status table, including
plain sequencer entries, without changing source wording or line layout.

Order of preference, highest first - a lower rule NEVER beats a higher one:

1. **Fewest lines.** A break is only ever placed to fit the box; text is never
   spread over more lines for looks.
2. **Do not split a word.** Hyphenated words and code runs may split, but only
   when that saves a line or avoids an overflow. **A run of ellipses is ONE
   word**: `... ... ...` (even split by pause codes, `...<FF05><10><00>...`) is
   a single dramatic beat and never breaks inside it.
3. **Do not split a proper name or short quoted term.** "Ms. Saeko", "St. Hermelin High", "Mikage
   Hospital", "Saeko Takami". Not a wall: it is a cost, so it loses to 1-2 and
   beats everything below. Names are derived from capitalisation and sentence
   shape - never from a list. A comma or semicolon ends a name run; separate
   names in a list are not one full name. A glued atom is judged by the words
   that touch the break, not by its first letter: `the Peace | Diner on` still
   splits the name "Peace Diner", even though the first atom begins lowercase. A double-quoted term of up to four
   words that fits a line has the same soft protection. Neither may buy an
   extra line or scroll.
4. **Do not clip a tiny fragment onto a speaker label.** At the same line
   count, prefer a label-only line to a speech fragment occupying at most
   one fifth of the box width. Also discourage a mid-clause split of speech
   that fits whole on the following line. A useful comma/sentence boundary
   still competes normally. A standalone label is not a speech line for the
   width-transition or short-tail tests.
   When the complete speech fits under the label, a comma break that leaves
   its closing line under half the preceding width is also a clipped fragment.
5. **End lines where the sentence breathes**: full stop > comma/semicolon/colon
   > mid-clause. Merely ending on a connector is not a punctuation boundary
   and must not force a growing triangle of short fragments.
   A comma/semicolon/colon boundary that strands a final line under one third
   of the preceding width costs two additional rhythm points; a minor pause
   must not force a severely short orphan. Full sentence boundaries are exempt.
6. **Balance and gently taper the block, without adding lines.** Minimize
   `sum(line_width² // remaining_lines)` plus squared adjacent width changes
   (a downward increase costs
   twice as much as a decrease). This favours square, smoothly tapering blocks
   rather than an overfull first line or a hollow middle. The optimizer retains
   alternatives by both suffix line count and first-line width, so it scores
   the entire block, not just locally balanced suffixes.
7. **Avoid tiny tails and big rises.** These are shape costs, not sentence
   boundary vetoes: a final line less than half the preceding width adds
   `(previous - 2 * final)²`; otherwise a following line over 40% wider adds
   `(following - previous)²`. Neither ever buys lines or scrolls.

Glue (what a break may not fall inside):

- **Articles and possessives bind FORWARD**: `a, an, the, this, these, those,
  its, their, his, her, our, your, my` stay with the word after them. A line
  may therefore BEGIN with one - `the hospital` on a fresh line is correct.
- **Connectors bind BACKWARD**: `to, of, in, on, at, with, from, for, by, as,
  and, or, but, nor, than, that, into, onto, about, over, under, off, upon,
  without, through, toward(s), between, among, against, because, while, when,
  where, if, so, yet` end the line they sit on. A line never STARTS with one
  (the one exception: the connector's left neighbour is itself a break).
  A comma, semicolon or colon boundary releases the connector: the clause
  ends there, so the connector may start the next clause's line
  (`C'mon, <FFF3>,<FFF6>if ya don't laugh...` keeps its comma break).
- **A PROSE newline in the source is not a break of ours.** The PSP broke its
  lines where ITS 16px glyphs ran out, and English has different widths.
  The flow owns every line break in prose.
- **A STRUCTURAL line keeps its own line**: a card's nameplate, and a newline
  typed in the viewer (that one is a deliberate break, never moved, merged or
  balanced across). A speaker label is NOT structural: it flows with speech
  (section 4.2).
- **Instruction captions are structural too.** A complete `【…】`, `＞…＞`
  or `＜…＞` caption followed by a source newline keeps that newline before
  its body. Brackets and bullets are visible source glyphs, not disposable
  icons. Ordinary prose still reflows by width.
  A marked `＞ Title Case` line with at least two capitalized words and only
  title words/articles/connectors is also a title; a marked first line of
  ordinary prose is not. Title classification uses source casing, never names.
  Classify before removing PSP-only head furniture, then measure only the
  glyphs that will actually render; a removed mark must not consume line width.
- **Head marks are PSP furniture, decided per mark.** The PSP opens a line
  with `＞` (box head), `＜` (the dungeon family's narration) or `＾` (a
  title), and the PSX draws one only where its own bytes carry it. Each mark
  is kept when the row's own Japanese carries THAT mark and deleted
  otherwise: a `＜` the Japanese never wrote is furniture even on a row whose
  Japanese carries a `＞`. The tables spell the pair fullwidth (`＞` `＜`) and
  the injection spells them ASCII (`>` `<`), which is what the font carries -
  so `＜Before starting＞` is written and priced as `<Before starting>`. A
  literal `<` in a table still opens a control-code token; only the injection
  emits the glyph.
- **Physical controls follow the PSX instructions.** Before wrapping, pair
  symbolic button / L/R shoulder-reference groups in message order when both
  sides have the same number of groups. Only the control identifiers change;
  English words and descriptive labels (e.g. directional buttons) stay PSP-US.
  A single PSP shoulder reference can expand to the PSX's `L1・L2` or `R1・R2`.
  An unequal sequence is left unchanged rather than guessed. No global symbol
  swap, per-message table or post-write rewriting pass is used.
  Japanese-remnant guards match Japanese letters, not shared punctuation:
  `・` is a valid separator/bullet and must not make an English row a gap.
- A closer (`. , ! ? ; : …`) never starts a line; the tail it closes moves
  down with it. A leading `...` may start one (it is a pause). A break that
  is immediately followed by punctuation is not a break: the punctuation moves
  up to the line it belongs to (`<FF03>: ` -> `:<FF03>`, and the same for
  `. , ; ! ?`). Two colons in a row are one colon.

---

## 3. Boxes (pagination)

A box shows **3 lines** and may scroll **once** to the next 3 - six lines,
one click. That is the whole model; "four clicks in one box" is a bug.

1. **Authored boxes are kept, always.** The PSP script draws a fresh box
   where the writer asked for one (often repeating the speaker's name first).
   That split is the author's pagination and is **never merged away** - not
   even to match a smaller PSX box count. The PSX holds as many boxes as the
   text needs, so there is nothing to trade: a run of PSP boxes stays a run of
   boxes, and a box whose English needs more than 3 lines scrolls once instead
   of the words being re-flowed to hit someone else's line count. The PSX
   line count is still
   preferred *when it fits without issues*; it is never paid for with merges,
   stuffing or squeezing.
2. **Overflow creates boxes.** A box's text is laid out 3 lines at a time:
   chunk 1 visible, chunk 2 that box's one scroll, chunk 3 onwards a NEW box.
3. **Line breaks are the author's; page marks are ours.** A `<FF03>`/`<FFF6>`
   in the source is a deliberate line and is KEPT (for example, a profile
   card's name line). The flow only breaks such a line further when
   it overflows the box. `<FF02>`/`<FF04>` are a different thing: they were
   placed for 3 lines of 16px glyphs and land mid-sentence after the English
   reflow, so the waits are re-placed by our own line count (section 3.2).
   A card always keeps its name line: the PSP puts the name (and nickname) on
   a line of its own before the description.
4. **A box ends with its dismissal wait.** `<FF02><FF01>` is what makes the box
   WAIT for the press that closes it. Pagination leaves exactly one dismissal
   wait in front of the end code, and never an empty intermediate scroll.
5. **A scroll is `<FF02><FF03>` - wait FIRST, then the line.** That is the
   engine's own order (the PSX corpus spells it 1,796 times against 17 of the
   reverse) and it is what moves the pen to the new last line. `<FF03><FF02>`
   leaves the pen at the end of the line above, so the scrolled text is
   APPENDED to it instead of redrawn. A new box is `<FF02><FF04>`.
6. **An empty scroll is not a scroll.** A `<FF02>` with nothing after it in
   its box (right before a box break or the end) is dropped.
7. **An advance ends its line.** A `<FF02>`/`<FF04>` that sits mid-line glues
   the words around it and makes every line-splitting reader (the QA width
   gate included) see one over-wide line.
7. **Prefer the PSP's box size when the PSX one is clearly too small**: the
   box's capacity is the family's, not the Japanese line's.
8. **The option block's arming line is part of the box, and a full prompt
   gates it.** `<FF0E>` arms the choice list on a line of its own, and the
   list needs that line plus one row per option, so a prompt that already
   reaches the box's last visible row (`prompt lines >= 3 - 1`) cannot show
   its options without scrolling. That scroll is the PLAYER'S, never the
   engine's: the line is written `<FF02><FF03><FF0E>` (the PSX corpus' own
   spelling, 463 rows, against 47 bare ones - and every bare one is a
   ONE-line prompt). A two-line prompt therefore shows no options at all
   until the player presses; the press scrolls one row and the options
   appear (`Could you tell Maki... / book next time...?` then
   `book next time...? / Sure. / No way.`). A one-line prompt arms bare
   (`<FF03><FF0E>`), with no wait: a press there is a press for nothing.
   This is layout, not wording: the JP's own wait is not copied, because the
   JP prompt and the English prompt have different lengths.
9. **In a choice prompt the speaker label MAY take a line of its own.** A label
   is prose (4.2) and shares line 1 - unless the label eats so much of the line
   that the question splits in two. Retail's own shape is the label, a break,
   and the whole question on one line (`アガスティアの木：<FF03>汝の記録を　我に
   刻むのか？`), and it matters twice: the player reads the question whole while
   picking, and a one-line question is what the option block can follow without
   a press (rule 8). So `vwf_wrap.prompt_label_line` moves the one break when
   (a) the box is the prompt's own (after its last page move), (b) the text
   after the label is ONE complete sentence that fits the box, and (c) the box
   carries no other code (a name insert or a pause keeps the flow's own
   spacing). The gate then counts the prompt's TEXT lines, never the
   nameplate's: `Agastya Tree:` / the question arms bare.
10. **The authored boxes join down to the JP's own box count.** A PSP row that
   spells a prompt's lead-in and its question as two boxes is one box in the
   JP (the press scrolls), so `port_story.merge_boxes` joins them wherever the
   joined text fits 3 lines: the press the player makes then buys the scroll
   instead of a second box. The option block is NOT scroll content - `<FF0E>`
   arms on a line of its own and the wait in front of it gates that line - so
   a choice row is joinable like any other, and the joined row ends with the
   block (`...?<FF02><FF03><FF0E><01><FF01>`): a dismissal wait after the
   block stops the options arming.

**S2D overworld portrait dialogue.** The generic 15x3 text object treats
`<FF02>` as a wait in place and `<FF04>` as a page advance. For complete
PSP portrait rows, the S2D porter retains the authored waits and pages in
order, emits the source speaker as an inline label when it changes, suppresses
consecutive repetitions of the same speaker across pages, and reflows prose
with the shared font metrics. Each authored page must fit three lines. An
inline wait followed by more prose, an unsupported control, or an overfull
page remains a gap rather than resetting the pen, changing timing, or
shortening text. PSP line breaks after hyphens rejoin without a space.

**S2D overworld 1-row objects.** The area labels are 8x1 text objects and the
arrival banner is 15x1. The label path stops its pen at 224 px (14 cells) and
the banner path at the screen width (320 px); a glyph that would cross the cap
is skipped, and the renderer never wraps or rewinds. The clip is presentation
only: the wording is never cut.

An 8x1 label owns a 128 px VRAM strip, narrower than the renderer's pen cap,
so map wording is kept within that strip by the wording itself; a label wider
than 128 px draws into the neighbouring label's strip.

**S2D location slot: banner name and map label.** A location slot feeds two
consumers, and the builder gives them separate strings. The slot's own row is
the arrival / current-location banner name, capped at the banner's strip
(`s2d.BANNER_LIMIT`, 240 px). The 8x1 map labels reach the slot through
pointer words in the label-entry tables; every such word is rewired to a label
string, which by default is the same wording as the name. A manual row keyed
at any of the slot's map-label pointer words (never at the slot's own pos,
which is the banner) supplies shorter map wording; it is a normal filled
manual row, so the wording is the user's. A label whose name is wider than
its 128 px strip is queued in manual as an over-limit draft
(`over limit Npx/128px; <name>`) while the banner keeps the full name; the
draft row is the place to shorten the map wording.

**Name inserts.** PSP-US wording determines which name is meant; translate the
insert to the destination interpreter, never to match the Japanese row. The
PSP's bare inserts have no member parameter. `<FF07>` selects the given name
and `<FF0F>` the family name in PSP-US and the original PSX interpreters; do
not swap them. The PSX ADV dialogue window uses `<01>` for the hero, while
the dungeon field script uses `<00>`. The distinction is per interpreter,
not per overlay: DNG also contains the separate dialogue window. The PSP's
full name `<FF10>` is spelled given, space, family. `port_dng.clean_us` adds
the field operand and expands the full name before layout; the shared
`toolbelt.fix_textbox` handles the dialogue-window form. `tstatus.py` flags a
bare insert but does not validate the destination-specific operand. The retail
dispatch and party-name slots, not the reversed labels in the reference
decompilation, establish the opcode meanings (test `DungeonNameCodes`).
Translate before layout so the flow measures the text that will draw. If text
changes after layout, reflow before measuring it again.
Dialogue name opcodes are not battle opcodes: a battle row with an untranslated
dialogue name opcode fails the code gate rather than copying a Japanese insert.

**Inserted records.** The message machine also prints whole records, not just
the player's slots: `<FF09>` item, `<FF0A>` skill, `<FF0B>` demon, `<FF0C>`
Persona in ADV (a demon in the DNG field script), and `<FF13>` arcana. A
layout prices each code at the **widest name that code can print**, because
the insert's parameter is written at run time and the line must hold every
legal value. Which name is widest is a fact about the ported wording, so the
PORT derives it: `port_widths.py` measures the canonical name tables (manual
wins) plus retail's own arcana cells with the dialogue VWF advances and
writes `translation/generated/insert_widths.tsv`; `vwf_wrap.insert_widths()`
reads that table. The current maxima are 140 px (item), 127 px (skill),
112 px (demon), 122 px (Persona) and 82 px (arcana); `<FF0C>` takes the
larger of Persona and demon, since ADV and the DNG field script read it
differently. Regenerate the table with its owner (a port run); never widen a
line by hand because an insert "might" be long.
The gift speech row carries its own layout (three lines a page, laid once
through the shared flow with these widths priced); `giftmsg.py` encodes the
row verbatim and fails the build if a page outgrows the contract. The same
rule holds at the other messages' only writes: `fusionmsg.py` measures every
line of the fusion speech, and the script-message rows carry their
breaks in the row (their insert heads are the source's literal tokens -
static ids, so each line is measured with the name its id actually
prints, and scriptmsg fails the build when a line does not hold).

Codes: `<FF03>` (dialogue) / `<FFF6>` (battle) separate lines; field `<FF02>`
is a wait/scroll and `<FF04>` is a new box; `<FF01>`/`<FFEF>`/`<FFF5>` end.
The battle interpreter does not recognize field `<FF02>` or `<FF04>`. For a
battle message, a terminal PSP `<FF02>` is represented by the caller-controlled
wait at the original `<FFF5>` end. Interior PSP waits/pages without a proven
battle equivalent fail closed; authored battle timing is never discarded. Page and
line advance are **presentation**: they are excluded from the code comparison
against the Japanese. Only the end codes are structural (exactly one).

---

## 4. Labels (speaker names)

1. The PSP spells a speaker line `￥N` + name + break; the PSX spells it
   `<FF1B>name<FF03>`. Both are the same construct, and **the nameplate is
   structure both builds need** - it is never paired away against the Japanese
   and never dropped.
2. The box prints the label as **`Name:`** and the label is **PROSE, not a
   forced nameplate**: it is ONE atom (a multi-word name never splits) that
   shares line 1 with as much of the text as fits, and the colon goes on the
   name's line, never at the start of the next one. A punctuation-only body
   retains its source space after the colon and stays with the label. When an
   untranslated battle message starts with a visible insert and colon, preserve
   its original glyphs and add the same label/body gap before visible text.
   The PSP prints every name
   alone (`<FF1B>name<FF03>`); that does not force our line break -
   the PSX writes it inline (`南条：俺のと交換でいいんだな？`, 6 200 rows
   against 453). Keeping a separate label line can force a two-line choice
   question into its scroll (section 3.8). The flow may give the label its own
   line under section 2.4, never at the cost of extra lines or a scroll.
3. **A card's name is a nameplate, not a speaker label: NO colon after the
   name** - but the nickname slot inside it keeps the PSP's own colon:
   `Yukino Mayuzumi (Nickname: Yukino)`, never `(Nickname Yukino)`.
   The head takes its own line only when that line costs nothing: the card is
   laid out both ways (name line then description, and `Name - description`)
   and the form with FEWER scroll presses wins. A tie keeps the PSP's own
   break. An authored name/description comma stays a comma and preserves its
   inline source form when it costs no extra press. A nickname's parenthesized
   header can flow into its description with a space, including a hyphen split
   when that saves a scroll; “Nickname” is never shortened. The dash is only
   offered for a bare header that fits as one unit, and only used when it
   strictly saves a press; a dash must never split the name. The PSP
   writes it alone on its line (`＞ Saeko Takami`), so a card reads
   `Saeko Takami` then the description; a colon there is our invention and
   exists in neither script. The renorm never re-derives a card (`<FF06>`
   frame) - the card builder owns that structure.
4. A repeated nameplate at a new box starts that box (section 3.1) and is not
   printed twice on one line.

---

## 5. Gates (what a build must prove)

**Casino prize bars.** A CASINO row is the complete visible prize, name and
bonus together. The porter composes it once; the builder appends nothing.
`+` denotes the retail bonus separator tile (stored as full-width 9), and
`C` in a numeric bonus denotes the coin icon, not the word “Coins”. Numeric
amounts are preserved. The current retail converter has twenty halfword
slots, with only nineteen tiles visible; the limit applies to the whole row.
Longer complete lines stay as drafts until the renderer/storage can carry
them safely. Raising the constant alone would write beyond the tile buffer.
In the project CASINO binary (base `0x800643C4`), the converter is
`0x8008CC48`, called at `0x800892E4`. The two alternating prize objects at
`0x800A36C4` and `0x800A36DC` each reserve twenty display entries and point
to adjacent forty-byte tile-ID arrays at `0x800A3674` and `0x800A369C`.
`0x80068EF8` updates their display entries through `0x80069A34`; the font
descriptors at `0x8009D1B0` describe 8×16 tiles. A capacity change must cover
both objects' storage, display-entry reservations and visible geometry.

**Dungeon map titles.** `MapDrawName` (DNG `0x80096D2C`) hands
`g_map_name_cells` to `BgMapInit` as a script. The hook matches the map pack's
20-byte field against the generated table and writes the full PSP-US name and
`FF 01` into the cells; the cells' script area is `0x22` bytes, so a title is
at most 32 glyph bytes and `dngnames.py` refuses a longer one. The strip hugs
the text (`x = 0xAA - width/2`) only while the row's width stays `0..0xA0`.
Every check failure resumes the retail ten-pair body, which still needs the
hook's saved `ra`, `a0` and the `0x801D0000` pack base: the BIOS `bzero` the
hook calls does not preserve caller-saved registers, so the matched row
pointer and the fallback's entry state live in the hook's frame, never in
`t*`. `tools/tests/test_map_title.py` executes every row and every fallback
with the same caller-saved clobber the console's BIOS performs, with RAM
poisoned so a read of unwritten state is visible, and with a write ledger
that fails on any store outside the hook's frame, the cells' `0x22` bytes,
the strip words and the shown-bits word. It also sweeps every width byte and
malformed blob offsets, and proves incoming garbage in the caller-saved
registers cannot change the outcome. `mips_cpu.clobber_bios_registers` and
`CPU.fill`/`CPU.track_writes` are the shared harness for that rule;
`tools/tests/test_field_pause_title.py` applies the same write ledger and
poisoned-register rule to the held-START renderer.

- **One-row destinations** (`sysmsg.display_size`): a proven one-row message
  carries no line/page move into the disc; its wording is measured as one
  line of the width that viewport proves (`sysmsg.line_px`). An over-limit
  wording stays out of the disc (the Japanese shows) and is named in
  `build/sysmsg_drafts.tsv`; the build still completes.
- `tstatus.py qa`: **errors: none**. Its width model
  splits lines on the line codes AND respects the box advance.
- `verify_disc.py`: level 1 (every built file byte-identical on the disc),
  level 2 (rows decoded back from disc bytes), level 3 (translated rows found
  in the disc). All three pass or the disc is not shipped.
- **Stability**: two consecutive ports produce byte-identical tables. A layout
  that flaps between runs is a bug in the flow, not a cache.
- **Generated holds English only.** A row whose source is still Japanese is a
  GAP, never `en`. The writer enforces it for every porter.
- Placing bytes at an address another feature claims is a build error, never a
  silent overwrite.

---

## 6. The viewer (`tools/textvis/`)

`python tools/textvis/serve.py [port]` -> http://127.0.0.1:8765/

- Draws with **the disc's own font** (`/font` serves the live `vwf_font.bin`
  and `vwf_width.bin`), so a width on screen is the width in game.
- Picking a row shows **every box as stored**, the row's **file / id / pos**,
  and the **sources** side by side: the PSP-US wording and the PSX Japanese,
  each with its own breaks.
- Typing re-lays out live; a newline is a line break and a blank line is a new
  box; the rule checks are listed under the box.
- Rows can be filtered by family, by text, and "3+ words only" hides the one-
  and two-word cells that are not textboxes.
- The list is the WHOLE table: rows append as you scroll (400 at a time), so
  every row is a real, clickable element.
- The canvas never collapses: it sits in its own scroll container with a
  minimum height that follows the canvas, and the lines table and the sources
  scroll inside their own panes.

## The small font

`SF_LATIN` (the latin cells on the font page) and `SF_VWF` (the small-font VWF kit)
are two subsystems with two gates - see **docs/SMALLFONT.md** before touching
either, including the open picker-bar bug and the dead-run byte budgets.

An affinity row is one line, so it never wraps: the record's 25 cells are its
head and the kit's pool carries the FF-terminated tail, which the recorder
appends before laying the row out. The two halves are one drawn row capped at
47 glyphs (`SF_POOL_LINE_MAX`, `affinity.LINE_MAX`); the head alone is never
reported as the wording, and no tail is clipped to fit a record.
