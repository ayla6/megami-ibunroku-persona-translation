# Battle text and sound: investigation map

This is an investigation aid, not a complete allocation map. RAM, VRAM and
SPU RAM are different address spaces; an address or unused-looking bytes in
one do not establish free space in another. Ranges are half-open where known.
The reference decomp is **JP rev 1**, while this project patches **rev 0**;
its addresses below are leads, not validated rev-0 allocations.

`src/injection_tools/runtime-memory-map.tsv` is the machine-readable set of reviewed protected
ranges. `write_guard.py` checks every assembled write against those ranges
for the named image, including zero fills, and fails on overlap. This only
guards mapped ranges at assembly time; it cannot observe arbitrary runtime CPU
stores, DMA, GPU transfers, SPU RAM, or unlisted owners. The repeatable review
process is [MEMORY_AUDIT.md](../MEMORY_AUDIT.md). It inventories assembled
runs with `memory_audit.py` and cross-checks them against indexed rev-0 RAM
references from `runtime_map.py`. Its hits are leads, not inferred sizes or
proof of ownership; confirm extent, lifetime and active overlay before adding
a protected range.

## Rev-0 patch facts

| Owner | Space | Location / lifetime | Evidence |
| --- | --- | --- | --- |
| Battle 16-pixel string staging | RAM | glyph counter `0x800EBE44`, glyph ring begins `0x800EBE48`; shared with retail battle uploads | `src/asm/vwf/vwf_btlp_str16.asm`, `vwf_btlp_str16_act.asm` |
| Battle command strings | VRAM | each cell: x = `0x380 + 2*descriptor.x + 4*cell`, y = `0x150 + descriptor.y`, size 4 halfwords by 16 pixels | `vwf_btlp_str16_act.asm` |
| Battle interpreter text | VRAM | each cell: x = `text.tex_x + 4*(P % 15)`, y = `text.tex_y + 16*(P / 15)`; 4 halfwords by 16 pixels | `vwf_btlp_activate.asm` |
| Enemy species graphics pointers | RAM | `0x800F83BC..0x800F86DC` (200 pointers); **not free**, even where currently zero | rev-0 indexed store at `0x80081B74..0x80081B84`; reads at `0x800846F8..0x80084704` and `0x80084800..0x80084810`; rev-1 `g_btl_species_gfx` has size `0x320` |
| Battle script pack | RAM | scratch base `0x801C0000`; extent depends on loaded pack | `references/persona-decomp/src/btlp/message.c`; base also needs rev-0 verification for any new allocation |
| Persona stock-number rows | RAM | `0x800F7ED8..0x800F7FF8`, 12 records of 0x18 bytes | rev-0 indexed stores at `0x800776F4..0x80077818`; reference `src/btlp/stocklist.c` |

The former ANALYZE trait buffer, hook, and pool at `0x800F83C0..0x800F859E`
overlapped the species graphics pointer array. In the live pre-ANALYZE battle,
GDB read `0x801BC6B8` at `0x800F8444` in place of the hook's delay-slot
instruction, and another live pointer at `0x800F83DC` inside the trait buffer.
This confirms corruption in both directions; ending before `0x800F85B0` does
not make the preceding area safe. The current build relocates all three:
the row uses `0x80057700..0x8005772F` while story dialogue is inactive; code
uses reclaimed command strings and `0x800182B4..0x800182F8`; the compact pool
follows battle name data and is bounded below `0x800F9148`. Automated tests
exercise every affinity index. The array holds graphics pointers, so this
observation alone does not establish a cause for missing percussion.

The former battle text-ownership directory at `0x800F7F00` also overlapped
the stock-number rows and could be overwritten when the stock list was built.
The directory now uses compact entries in reclaimed immutable board text; the
stock array is protected by the assembly guard. The command-stage Persona-name
buffers also reuse part of this array, but are runtime scratch for a different,
mutually exclusive screen rather than persistent data.

The reported `FlattCan't` is consistent with an upload overwriting command
texture cells, but the above formulas alone do not prove the relevant live
descriptor coordinates or write order. Capture those coordinates and queued
uploads when the notice appears before relocating either surface. Text lengths
must not be reduced to hide a collision. `BtlTalkOpen` in the rev-1 decomp
queues the four command strings, level and name, then a clear for
`(0x380, 0x150, 0x40, 0x30)`; consult the rev-0 call sites and queue flush
order before treating this as an exclusive reservation.

The 16-pixel string path previously reserved 15 staging cells for every
string, even short ones. Six CONTACT strings therefore reserved 90 cells,
the entire `0x800EBE48..0x800EEB48` staging space, before any other producer.
It now reserves only the cells it queues. This removes one demonstrated
capacity hazard, but does not prove the screenshot's collision is resolved.

## Sound leads (rev 1, not a rev-0 memory claim)

`src/btlp/soundload.c` in the reference describes bank entries with VAB body,
VAB header and SEQ offsets relative to a caller-provided destination. Battle
music is unpacked similarly by `BtlBgmOpen`. The decomp's `sym.btlp.txt`
identifies sound-offset tables and bank state, but does not by itself establish
the live buffers, SPU sample destinations, or whether percussion is missing
from the original arrangement. Compare the same boss and timestamps on a
retail disc, then trace the rev-0 bank load and SPU transfers if they differ.
No audio corruption has yet been established from the report alone.
