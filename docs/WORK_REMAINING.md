# Requested work and current state

Gameplay checks are recorded in [IN_GAME_CHECKLIST.md](IN_GAME_CHECKLIST.md).
No unchecked gameplay item is implied complete by CPU or disc-byte QA.

## Implemented

- Battle and negotiation typing: both native glyph call sites batch two glyphs
  while retaining control boundaries, configured delays and staging limits.
  Five CPU tests pass in both font editions. The preferred eight-mod disc
  passed assembly/readback checks and its byte/text audit. The user confirmed
  the faster battle typing in-game. The hook now lives in a resident
  reservation so it leaves the adjacent live Rev 0 CONTACT routines intact.
- Base CONTACT margin correction: the main three-line window moves its text
  six pixels right for all messages in the shared frame, including CONTACT
  farewells. Base’s Negotiation Inset option defaults to the corrected inset and
  can be switched to the original inset. Typing timing stays the same. The user confirmed the
  corrected inset in-game.
- Dialogue font sheets take their cell order from `sheet-characters.tsv`.
  Four custom marks use one-byte codes and additional marks use a screened
  reclaimed-kanji list. Both editions encode, render and measure the 79
  extended cells currently on the sheets. White end columns set advances.
- Translation preparation: the English mod owns its TSV compilation recipe,
  porting/source QA and movie-text preparation. The alphabet owns cached font
  and character-table generation. Shared binary encoders remain shared; native
  tiers use the same recipe with blank English cells.
- Release production compresses each finished layer once and runs combined
  checks and the final cross-patcher audit by default. `--no-verify-release`
  explicitly skips full verification. Known higher-order interactions are mod-owned recipes.
  Unchecked source preparation cannot satisfy a checked cache request.
- Native variant snapshots use dependency-scoped keys and checked inventories.
  One real native/replay configuration produced the same 125 changed files;
  replay invoked no main assembly. The resumed production run finished in
  6m 44s with 34 reused trees and 47 assemblies. It wrote all 20 layers
  marked untested, with zero test-runner or full-disc calls.
- Dependency ordering applies to assembly and patch application. Identical
  preferred-mod builds under two Python hash seeds produced identical 173
  files, symbols and disc bytes. A general runtime allocator is still absent.
- Run in Dungeons: integer range 2–4, default 2, with CPU checks of endpoints,
  turning and mid-turn button transitions. Softer Menu Sounds: range 0–100,
  default 75; previews are explicit-only.
- UI dependency locking, mobile info, separate components, black setting
  inputs and removal of duplicate descriptions/yellow setting decoration.
- Single-patch rebuild via `tools/build_patch.py`; declarative image replacement
  via `images.tsv`, including Black Mark (its old `mark.py` is removed).
- Western Controls preserves native casino physical inputs and help symbols.
  The Velvet Room Persona-list hint has CPU QA. The original battle corner
  indicator is fixed too; TYPE 2 adaptation is optional, not a parity fix.
- General disc-file extraction and explicit TIM/MES image exports are available
  via `tools/extract_asset.py`. Broader inner format decoders remain possible.
- Close-call/Kandori/heart restoration: complete, confirmed by the user.

## Still requested

1. Broader memory ownership/allocator audit and Western Controls artwork audit.
2. After release: the English text of psp-items-and-skills ships as a part of
   the English layer for that mod, not in the English layer by default. Today
   the English port writes Clean Salt / Emergency Exit / Estoma into item
   records 110/111 and skill 0x70 (`boot_tables.py` `PSP_SLOTS`) whether the
   mod is on or not; without it those records are unreachable, so nothing
   shows, but the translation knows a mod's slots. The mod would own them
   (its `text.tsv` already lists the positions, and `PSP_SLOTS` moves into
   it), the English stays in translation/, and the mod's build step writes it.
   Descriptions share one packed zone, so that part is the rewritten zone.

DualShock movement and the Lone Prayer/music idea are deferred at the user’s request. Format magic stays P1MOD 1.
Do not commit or push without a fresh explicit request.
