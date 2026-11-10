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
| `memory_audit.py` | Writes `build/memory-audit/allocations.tsv` and `indexed-leads.tsv` for one overlay, using the newest armips listing. |
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
python src/injection_tools/memory_audit.py --image BTLP.BIN
```

This writes two TSVs under `build/memory-audit/`:

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

## BTLP audit (current state)

The first inventory covered 859 assembled runs and 2,284 indexed references.
All 15 `base-inside-write` leads are reviewed:

- **Battle command strings** (`0x800CB330..0x800CB459`, pointer table
  `0x800CB45C..0x800CB4EC`): patch-owned. `btlcmd.py` repacks all 36 command
  strings, rewrites every pointer, and places the ANALYZE trait helper in the
  freed tail. The retail reader at `0x8007C174` computes a base of
  `0x800CB44C`, four entries before the table, and indexes with `a0*4`; its
  call sites supply `a0 = 1` for the first text group, so it reads the real
  table at `0x800CB45C`. The helper is not read by it.
- **Generated battle tables** at `0x800C9F98`, `0x800CC5E8`, `0x800D24F0`,
  `0x800D25F4`, `0x800D265C`, `0x800D92F4` and `0x800D96BC`: patch-owned data
  placed where the retail readers already point. These are intended consumers,
  not collisions.
- **Skill-menu descriptors** (`0x800DD788` and `0x800DDD68`): the retail store
  at `0x800AC904` writes the padding byte after each descriptor's glyph count
  (`0x800DD791 + 12*k`), not the pointer or count the patch writes.

No near store currently targets an all-zero retail run. That is not proof that
the remaining 760 near leads are safe; they still need review when their
screen is touched. The inventory is a snapshot of one build and must be
regenerated after allocation changes.

## Known blind spots

This process cannot see:

- DMA, GPU or SPU transfers, including text-cell uploads and sound banks;
- indirect tables whose base comes from another load, the stack or the heap;
- array extents, loop bounds, or whether a writer is reachable in a variant;
- unlisted overlays, runtime-generated code, or retail self-modification;
- a range that is written only on one map, fight, menu or animation.

Those need their own live checks. In particular, missing battle percussion
remains an unproven sound-space issue; CPU RAM evidence says nothing about it.
