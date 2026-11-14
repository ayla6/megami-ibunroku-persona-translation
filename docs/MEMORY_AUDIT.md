# Memory audit

The patch can only be safe where its assembled data and code do not collide
with memory the game still uses. This document is the repeatable process for
finding those collisions before they become in-game corruption.

It is an allocation audit, not a proof of safety. An address is not free
because it looks free, because it is zero at boot, or because one run did not
write it. A range enters the protected map only after its owner, extent and
lifetime are known well enough to state the evidence.

## Spaces and terms

RAM, VRAM and SPU RAM are separate address spaces. A finding in one says
nothing about another. DMA and GPU/SPU transfers must be audited separately.

- **Reviewed range**: a half-open `[start, end)` in
  [`src/injection_tools/runtime-memory-map.tsv`](../src/injection_tools/runtime-memory-map.tsv).
  `write_guard.py` fails the build if an assembled write overlaps one.
- **Allocation**: one contiguous run of assembled statements in the listing,
  merged only when the same source file writes adjacent/overlapping bytes of
  the same kind (code/data versus padding). Different sources never merge.
- **Lead**: an indexed retail RAM reference whose base is inside or shortly
  before a patch allocation. A lead is a question, not an overlap.
- **Patch-owned range**: retail data the patch deliberately replaces at its
  original address, usually a text pool and its pointer table. The patch is
  expected to write it; it is not a protected range.

## Tools

| Tool | Purpose |
| --- | --- |
| `runtime_map.py` | Scans a retail overlay for indexed base/access sequences. The underlying lead generator. |
| `memory_audit.py` | Writes one directory per image under `build/memory-audit/` with `allocations.tsv` and `indexed-leads.tsv`, plus one `summary.tsv` for the run. `--all` audits every image the listing writes; repeat `--image NAME` for a chosen set. |
| `write_guard.py` | Fails assembly if a write overlaps a reviewed range in the TSV. |
| `verify_disc.py` | Checks the finished disc's structure and placed bytes. It does not detect RAM collisions. |

The audit reads the **listing and retail image belonging to the same build
variant and game revision**. A listing from a different variant makes the
allocation list wrong. The reference decomp is JP rev 1; this project patches
rev 0, so decomp names and addresses are leads until rev-0 instructions
confirm them.

## Process

### 1. Build, then inventory

Build with the variant under test, then:

```sh
python src/injection_tools/memory_audit.py --all
```

`--image NAME` audits one image and can be repeated. `--all` writes a
directory per image and a `summary.tsv`; the counts below come from that
summary. Each image directory holds two TSVs:

- `allocations.tsv`: every assembled run, its source file and line, byte size,
  whether it is padding, and whether the retail bytes it replaces were zero.
- `indexed-leads.tsv`: every indexed retail access whose base is inside a run
  (`base-inside-write`) or up to `--lookahead` bytes before one
  (`base-before-write`).

`--lookahead` is deliberately small. A huge window produces thousands of
unrelated rows and hides the useful ones.

### 2. Resolve exact leads first

Sort by `relation`: `base-inside-write` rows are the priority. For each one:

1. Disassemble the retail instruction and the address construction around it.
2. Work out the **actual table base and index origin**. A `lui`/`addiu`
   constant is often four or more entries before the first used pointer.
3. Read the retail pointer table. If the allocation is a pointer table the
   patch regenerates, the retail reader is an intended consumer.
4. Check the patch source that owns the range. Does it rewrite every pointer
   or descriptor that can reach the bytes?
5. Only then decide: intended consumer, harmless unused tail, or collision.

### 3. Review near stores

Rows with `access` starting with `s` and `relation == base-before-write` are
stores whose base is before an allocation. Find the real store offset and
stride; the base alone is not the address. A store into descriptor padding is
harmless. A store into a pointer, count or text byte is a collision.

Pay particular attention to stores before an allocation whose retail bytes are
`all-zero`. That combination is common for a runtime-initialized array. It is
not proof, but it is the shape of the bugs found so far.

### 4. Confirm live when static evidence is ambiguous

DuckStation's GDB server is at `127.0.0.1:2345`. Set a watchpoint on the
suspicious range, exercise the owning screen or transition, and record the
writing instruction and call path. For a table, confirm the live base and
index range rather than assuming them. Do not use save states as evidence.

Reading the same value at one moment proves only that moment. A range must
survive every writer whose code path can run while the patch data is live.

### 5. Record the result

Add a confirmed protected range to the TSV with:

- image and address space,
- half-open start/end,
- owner,
- `no-assembly-writes`,
- evidence: rev-0 instruction addresses, call sites, decomp reference, and the
  live check that established the extent.

If the range is patch-owned, document it as such in the research notes and in
the owning builder description instead of adding it as protected. Do not add a
range simply because a scan produced a lead.

### 6. Regression tests

Every confirmed overlap gets a test. The useful tests check the rule, not one
address: the lookup must work after the live writer runs, every index must be
covered, and the directory or buffer must stay outside the protected range.
`tools/tests/test_btlp_analyze_ownership.py`,
`test_runtime_map.py` and `test_memory_audit.py` are the current examples.

## Zero-fill tails

A retail image's trailing zero bytes are not free space. They are the
uninitialized part of the overlay's BSS-style storage, and rev-0 code may
address it directly or through an index. Retail bytes being zero proves only
that the boot image does not initialize them.

The rule: when rev-0 code demonstrably reads or writes the trailing zero run
of an image, protect the whole run as `[last nonzero byte + 1, file end)`.
That range is one reviewed row; it bans assembled data there, not the game's
own runtime stores. Keep narrower rows inside it when a specific owner is
known, because those rows document the owner even if the blanket row changes.

The rule is applied to SLPS_005.00, BTLP.BIN, DNG.BIN and OPEN.EXE. It is not
applied to MOVIE.EXE (the scan found no direct rev-0 access to its tail), nor to
the 2–5 byte tails of ADV.BIN, S2D.BIN and NAME.BIN, where no owner is known.
Reviewed rows may overlap: a narrow row inside a blanket tail keeps the
specific owner documented, and the blanket row catches anything else.

## Current audit (all built images)

`python src/injection_tools/memory_audit.py --all` covers every image the
listing writes. The counts below are for a listing assembled with every QoL
option defined (`--listing` of `armips main.asm` with each `QOL_*` label), so
every option's writes are audited at once:

| Image | Ranges | Indexed refs | Exact | Near stores | Near loads |
| --- | ---: | ---: | ---: | ---: | ---: |
| SLPS_005.00 | 1136 | 43 | 1 | 0 | 13 |
| ADV.BIN | 197 | 592 | 6 | 0 | 200 |
| BTLP.BIN | 925 | 2284 | 16 | 87 | 831 |
| DNG.BIN | 162 | 436 | 3 | 0 | 164 |
| S2D.BIN | 601 | 404 | 3 | 1 | 111 |
| NAME.BIN | 48 | 134 | 14 | 72 | 727 |
| OPEN.BIN | 1130 | 0 | 0 | 0 | 0 |
| OPEN.EXE | 36 | 83 | 0 | 0 | 0 |
| MOVIE.EXE | 7 | 23 | 0 | 0 | 0 |
| END.EXE | 24 | 87 | 0 | 0 | 1 |
| FONT.BIN | 9 | 0 | 0 | 0 | 0 |
| NAMEDT.BIN | 116 | 0 | 0 | 0 | 0 |

All exact leads are reviewed:

- **BTLP battle command strings** (`0x800CB330..0x800CB459`, pointer table
  `0x800CB45C..0x800CB4EC`): patch-owned. `btlcmd.py` repacks all 36 command
  strings, rewrites every pointer, and places the ANALYZE trait helper in the
  freed tail. The retail reader at `0x8007C174` computes a base of
  `0x800CB44C`, four entries before the table, and indexes with `a0*4`; its
  call sites supply `a0 = 1` for the first text group, so it reads the real
  table at `0x800CB45C`. The helper is not read by it.
- **BTLP generated tables** at `0x800C9F98..0x800C9FDC`,
  `0x800CC5E8..0x800CC778`, `0x800D24F0..0x800D24F8`,
  `0x800D25F4..0x800D2600`, `0x800D265C..0x800D26DC` and
  `0x800D92F4..0x800D9860`: patch-owned data placed where the retail readers
  already point. Intended consumers, not collisions.
- **ADV race table** (`0x800B23C0..0x800B245C`): regenerated in place by
  `build/races_adv.asm`. The personality reader at `0x80098EE4` uses base
  `0x800B245B` plus a 1-based race, so it starts at `0x800B245C`, exactly
  after the race table. DNG `0x8009AEB0..0x8009AF4C`
  and S2D `0x8009DA40..0x8009DADC` have the same shape and readers.
- **ADV system-message pointers** (`0x800BB518..0x800BB544`): the 11-word
  table is rewritten by `sysmsg.asm`; reader `0x8009C1FC` indexes it with
  `a0`, and callers pass `a0 = 0..8`. Intended.
- **ADV script messages** (`0x800BC634..0x800BC696`): patch-owned text copied
  by retail at `0x8008B068` and `0x8008B180`. Intended.
- **S2D location-name pointers** (`0x800A54DC..0x800A5598`): 47 words
  rewritten by `s2d.asm`; reader `0x8008A028` stops at the `-1` sentinel.
  Intended.
- **NAME geometry** (`0x800682DC..0x800682DF`, `0x800682E4..0x800682E7`):
  `long_names.asm` writes `g_name_x` and `g_name_len`; 14 `lbu` sites read
  them. Intended.
- **SLPS event sector table** (`0x8004DFDC..0x8004E0DE`): 129 halfwords from
  `event_tables.asm`; reader `0x80015B74` indexes with `(s1 & 0xff) * 2`.
  Intended.
- **QoL tables placed where retail readers point**: the `western` controller
  page layouts (ADV `0x800B983C`, reader `0x8008C35C`; S2D `0x8009F6A8`,
  reader `0x80080814`), `encounters`' divisor table (DNG `0x80099ED0`,
  reader `0x800709EC`, the per-step roll), `run`'s pad-layout entry (DNG
  `0x8009CB18`, reader `0x800906E4`) and `range`'s sword and gun entries of
  `g_btl_command_fn` (BTLP `0x800D22E0`, reader `0x8009E8D4` in
  BtlCommandEntry). Intended consumers.

The BTLP, NAME and S2D near-store leads reviewed below do not reach patch
data:

- NAME bases `0x800682AE`/`0x800682D0` target records `0x800682A0..0x800682D2`;
  the patch writes at `0x800682DC` and later.
- `0x800ABAAC` fills the five-slot array `0x800D26E0..0x800D26F4`; the patch's
  FORM data is at `0x800D2868`.
- `0x800AC904`/`0x800AC960` and `0x8009DFD4` write the descriptor clut byte at
  `+9`; the patch writes pointer `+4` and count `+8`.
- `0x800AACC0` (s6 max `0x120`) reaches `0x800DF75D`; `0x800AABD4` (v0
  `0x120..0xB4`) reaches `0x800DF799`; the patch data starts at `0x800DF7AC`.
- `0x800AE060` (v1 `0x37`) reaches `0x800F87B7`; `0x800AB340` (s0 `0..4`)
  reaches `0x800F87F0`; `0x80084130`/`0x80084140` (s0 ≤ `0xE`) reach
  `0x800F8873`; `0x800849F4` (slots 5..9) reaches `0x800F8866`. All end
  before `rewards`' data at `0x800F8900` and the patch extension at
  `0x800F8960`.
- S2D `0x8008C62C` stores the config value at `0x800A5424 + row * 4`; the row
  (`0x800A5434`) wraps within `0..11` or `0..4` and every other store to it
  is zero, so it ends by `0x800A5453`, before the location-name pointers at
  `0x800A54DC`.
- The `0x800AB340` writer is inside the board23 branch that
  `board23_names.asm` rewrites, so its scratch is dead under the patch.

The remaining near leads are unproven, not safe. Review one when its screen or
transition is touched. The inventory is a snapshot of one build and must be
regenerated after allocation changes.

## Reclaimed space

- The CD path-table cache (`0x800569F4`, 44 bytes per directory) holds as many
  entries as the disc's ISO path table has (15). Its tail up to the resident
  scratch is runtime scratch: the battle skill slots (`SKILL_MENU_BUF`, the
  lowest scratch byte `RESIDENT_SCRATCH_ADDR`), the battle decompressor's
  buffer and the dialogue compositor ring. `build_disc.py` fails a disc whose
  path table would reach `RESIDENT_SCRATCH_ADDR`.
- The dead code run the skill slots used to occupy (`BTL_ORIG_WIDTH_ADDR`)
  holds the battle's original-font advances.
- BTLP's retail text-window glyph function (`BTLP_GLYPH_FREE_ADDR`, 392 bytes):
  both calls go to the VWF emitter and nothing else reaches it.
- The top of RAM above the game's last global (`g_seq_handle`,
  `0x801F537C + 0x40 = 0x801F53BC`) holds no fixed data: the main stack grows
  down from the EXE header's `0x801FFFF0` (about 2.6 KB deep in a measured
  ADV session), and the sub-EXE stack `0x801FBFF0` (LoadAndExecPsExe) and the
  OPEN/CASINO buffers there only live while ADV is not loaded (both replace
  it, and ADV comes back fresh). ADV's small-font row table
  (`ADV_SF_TABLE_ADDR`, 96 x 56 bytes, `0x801F53C0..0x801F68C0`) is runtime
  scratch at its bottom, about 38 KB below the stack's start; the recorder
  frees its slots whenever ADV's state is fresh. Measured: an ADV session
  (menus, item scrolling, shop, save, NPCs) left a fill pattern in
  `0x801F53BC..0x801FBB18` untouched.
- `D_8004EC70` (`0x8004EC94..`) is libetc's interrupt-handler stack.

## Borrowed primitive slots

The static audit cannot see writes through a pointer the game computes at
runtime. The battle's per-frame primitive pool is reached that way, and so is
covered by its own rule. `BtlInitObjects` tags every slot of six typed runs
once per battle (SPRT, TILE, POLY_FT4, POLY_F4, POLY_G4, LINE_G2; cursors
`BTL_*_NEXT` in addresses.inc). The game's users take a slot by advancing a
run's cursor and rewrite only colours and corners, never the header. Patch
code that takes a slot must write it as the run's own primitive, header
included, and must not touch any other byte of the pool apart from the ordering
table links. A slot left as another primitive breaks the next retail user of
that slot: the range overlay's flat quads in POLY_G4 slots made the level-up
board's stat bars screen-wide triangles.

The runs have fixed sizes, and retail never checks them. The text renderers
take one slot per drawn cell (flat text a SPRT, scaled or rotated text - a
board opening or closing - a POLY_FT4), 450 of each per frame. A user that
takes more writes its primitives over the next run, whose slots keep their own
headers: the overrun draws as screen-wide quads, and an overwritten link can
leave the GPU's list DMA in a loop, which also starves the SPU's DMA (a
sound-bank wait that never ends); the slots it wrote keep the wrong shape
for the rest of the battle, since the runs are tagged once. Every object
drawer that takes SPRT or POLY_FT4 slots (flat and rotated text, and the
drawers at 0x80088AF4 and 0x80089A2C) now ends its object when the run is
full (`btlp/text_slot_bound.asm`): an overrun loses cells instead of the
frame. The longer English board text is what fills the POLY_FT4 run while a
board animates during a turn, so the demand still has to stay low: a row in
borrowed scratch is filled before its board's first frame, so leftovers are
never drawn.

`tools/tests/test_prim_pool_borrowers.py` finds every patched BTLP instruction
that reaches a cursor and fails unless its source file is registered with a
contract test. A contract test runs the game's own `BtlInitObjects`, then the
patch at its heaviest, and checks that the pool is unchanged outside the slots
taken and that every taken slot keeps its type
(`test_qol_range.Range.test_borrowed_slots_keep_the_games_shape`).

## Shared runtime scratch

`src/asm/common/scratch_map.tsv` lists every region the patch writes at
runtime outside its own images (the resident path-table cache tail, the
overlays' small-font tables and buffers), with its users. Two regions may
overlap only when each names the other and the row says why they are never
live together; `tools/scratch_map.py verify` runs in every build and fails on
anything else. Where a reason is a size (an unpacked battle line stays below
the ANALYZE rows), the tool that makes the bytes enforces it (`btlp.py`,
`UNPACK_ROOM`).

## The BIOS kernel pool tail

`0x8000EA00..0x8000FFF0` (about 5.6 KB) is unused and in reserve. The BIOS kernel takes its
control blocks from the pool at `0x8000E000..0x8000FFFF` only at boot, sized by
SYSTEM.CNF (`TCB = 4`, `EVENT = 16`: about 0x500 bytes, measured as
`0x8000E000..0x8000E59F` with Sony's BIOS). The tail is free under that BIOS.
OpenBIOS, Unirom and cheat cartridges are unchecked. Code placed there needs a
boot stub that copies it in before the original entry point (`0x80011930`),
because the PS-EXE loader cannot load below the executable's own `t_addr`.
The ancestor translation (Redeted's) ships its full-name renderer this way.

## DNG's image room

DNG's image may grow to `0x800C0000`, the work area. Its small-font row table
(`DNG_SF_TABLE_ADDR`, 96 x 56 bytes, `0x800BEB00..0x800C0000`) is runtime
scratch at the top of that room, and `DNG_ITEM_DATA_END` (the image's ceiling)
stops below it. While DNG runs the room holds only a stale copy of the
previously loaded overlay's image (checked with gdb in a DNG menu: its last
non-zero byte is ADV's extension end); the recorder frees the table's slots
whenever DNG's state is fresh.

## Known blind spots

This process cannot see:

- DMA, GPU or SPU transfers, including text-cell uploads and sound banks;
- indirect tables whose base comes from another load, the stack or the heap;
- array extents, loop bounds, or whether a writer is reachable in a variant;
- unlisted overlays, runtime-generated code, or retail self-modification;
- a range that is written only on one map, fight, menu or animation.

Those need their own live checks. In particular, missing battle percussion
remains an unproven sound-space issue; CPU RAM evidence says nothing about it.
