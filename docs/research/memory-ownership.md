# Memory ownership audit

The current patch has bounded reservations and overlap guards; it does not
have a general-purpose free-space allocator. Dependency order determines who
writes first and does not establish that an address is free.

The runtime scratch registry (`base/asm/common/scratch_map.tsv`) currently has
11 regions. `scratch_map.py verify` passes: overlaps have reciprocal owners
and an explicit lifetime reason. CONTACT stock names and ANALYZE rows share
parts of the primary battle buffer under the documented scene constraints;
battle item names share the second buffer only outside negotiation. ADV and
DNG scratch share an overlay slot because both overlays cannot be live together.
This verifies the registered intervals, not every potential unregistered write.

Battle pacing occupies `0x8002902C..0x800290AC` in the resident reclaimed
libgte function, after Western Controls' reservation. The shared wide-box
margin uses an in-place constant at `0x8007D008`.
The battle string renderer's reclaimed span ends at `0x8007C068`; the Rev 0
routines starting there are live and reserved for the game.

BTLP immutable names occupy `0x800F8BC4..0x800F9148`; the latter is the first
sound-work buffer, not extra allocatable space. Keep the image limit there.
The resident CD flags around `0x80055C10/0x80055C34` are also live and cannot
be reclaimed. These constraints remain in `addresses.inc` and assembly guards.

The preferred-mod assembled build passes write guards and the complete disc
readback audit. Full ownership proof would additionally inventory every dynamic
allocation and alternate overlay lifetime, then require allocations through a
single registry. That broader work remains open; the current checks establish
only the explicitly bounded and registered regions.
