# Documentation map

Start here if you are new to the tree. Everything below assumes the local
game files described in [DATA.md](DATA.md); none of them are tracked.

## Build and verification

- [BUILD_PIPELINE.md](BUILD_PIPELINE.md) — how `build.py` turns translation
  tables into a patched disc: the assembler write guard, the finished-disc
  audit, incremental caches, batch variants, and the xdelta3 release builder
  plus its browser patcher (`../webpatcher/`).
- [DATA.md](DATA.md) — which game files and images the tools expect under
  `data/`, and what is tracked versus local-only.
- [MEMORY_AUDIT.md](MEMORY_AUDIT.md) — how assembled allocations are compared
  with live retail RAM, how leads are resolved, and which ranges are protected.

## Text system

- [TEXT_ARCHITECTURE.md](TEXT_ARCHITECTURE.md) — the one-TSV-per-disc-file
  layout, row schemas, and the provenance rules that decide where wording
  may live (generated, manual, notes).
- [TEXT_LAYOUT_SPEC.md](TEXT_LAYOUT_SPEC.md) — the rules that decide a line
  break, a box, a label, or a glyph: wrapping, pagination, and budgets.
- [SMALLFONT.md](SMALLFONT.md) — the small-font kit: font page, subsystems,
  build variants, and the byte budgets behind them.
- [MAPPINGS.md](MAPPINGS.md) — the tracked correspondence snapshots under
  `translation/generated_mappings/`: who produces each file and what it
  needs to regenerate.

## Reference material

- [PERSONA_TYPES_REFERENCE.md](PERSONA_TYPES_REFERENCE.md) — type, subtype,
  and affinity terminology for localization, credited to the Megami Tensei
  Wiki.
- [revelations_reference.md](revelations_reference.md) — notes from the US
  Revelations: Persona disc, kept as a comparison reference.
- [research/](research/) — investigations behind specific features (in-engine
  FMV subtitles, 60 fps, renderer performance, ending panels).
