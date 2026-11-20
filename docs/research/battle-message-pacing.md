# Battle message pacing

The Latin alphabet component batches two glyphs per typing step in both battle
windows, including negotiation and inserted names. Rev 0 call sites are
`0x8007CCD4` (script text) and `0x8007CF80` (inserted text). Both call
`btl_message_pace` in `latin-alphabet/asm/btlp/msg_pace.asm`.

The wrapper stops on a deferred glyph, an `FF` control/terminator boundary or
a full 45-cell staging row. It batches glyph emission only. The original
window state machine still handles controls, configured delays, waits,
dismissal and choices once. Its 128-byte reservation starts at `0x8002902C` in a reclaimed resident
libgte function. Live negotiation routines start at `0x8007C068`.

Five CPU tests execute the actual Rev 0 WindowType/WindowStep paths and the
assembled wrapper, covering both windows, glyph widths, controls, staging
limits, pointers and preserved registers. They pass in both font editions.
The preferred eight-mod large-font disc also passed assembly/readback checks
and its complete byte/text audit. Gameplay confirmation remains unchecked in
`docs/IN_GAME_CHECKLIST.md`.

Base uses the same six-pixel margin correction for all text in the main
three-line frame, including farewell dialogue after the CONTACT scene pops.
Typing and frame animation retain their existing timing.
