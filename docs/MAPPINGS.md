# Mappings

## Generated

`translation/generated_mappings/` contains tracked, shareable generated
snapshots. `port.py` and `build.py` generate missing files before starting
readers. Outputs are validated and published atomically; invalid existing files
fail validation rather than being silently replaced. Regeneration still
requires game inputs. When committing a regeneration, include the updated
`translation/generated_mappings/` files; other build products stay in `build/`
and remain ignored.

| File | Producer in `src/extraction_tools/matching/` |
|---|---|
| `align.tsv` | `align.py`: PSX ADV E0–E3 and both PSP story trees |
| `map_jp_psx.tsv`, `map_us_jp.tsv` | `split_maps.py`: projections of `align.tsv` |
| `labels.tsv` | `port_story.collect_labels()`: PSP-US E0–E4 speaker labels |
| `psp_pairs.tsv` | `boot_pairs.py`: JP/US EBOOT extracts, PSX text, verified family-port pointers and reviewed pairs |
| `s2d_port_plan.tsv` | `s2d_port_plan.py`: text-free S2D source offsets and input hashes from a strict two-region match |
| `dng_port_plan.tsv` | `dng_port_plan.py`: text-free dungeon source offsets, matching modes and input hashes |
| `story_port_plan.tsv` | `story_port_plan.py`: speaker-arbitration and slot-join decisions |
| `btlevt_port_plan.tsv` | `btlevt_port_plan.py`: per-message US span, speaker and shared-box cut |
| `dngname_port_plan.tsv` | `dngnames.py plan`: PSX name field to PSP-US floor-name row |
| `answers_port_plan.tsv` | `answers_port_plan.py`: answer and answer-slot source locators |
| `eboot_twin_port_plan.tsv` | `eboot_twin_plan.py`: boot-string PSX key to PSP-US EBOOT offset, including the notice/control consumer proofs |
| `reward_notice_port_plan.tsv` | `reward_notice.py`: corroborated reward notice to PSP-US EBOOT record |

Pair generation requires raw JP BOOT, US EBOOT, PSX SLPS/S2D/BTLP files and
independently ported EBOOT provenance in the corresponding generated tables.
It refreshes EBOOT extracts and the full PSX text corpus with `--no-worklists`,
without modifying manual worklists. It cannot bootstrap absent family-port
provenance.

Every plan contains no Japanese PSP text or English wording: only source
offsets, decisions, and digests of the inputs and matching rules that produced
them. Capture a plan with its producer while both PSP regions are available;
replay it with the porter's `--without-psp-jp` flag. A replay validates the PSX
and PSP-US inputs and the rule files, then reruns the owning porter's wording,
layout and gates. A stale or damaged plan fails loudly instead of dropping or
guessing a row. `port.py` passes `--without-psp-jp` automatically for every
porter whose plans are present.

The S2D plan additionally validates the PSX overlay, the PSP-US BOOT and each
individual US source unit. The dungeon plan records the actual selected US
source offsets and whether the original match used an anchor or similarity.
The story, battle-dialogue, dungeon-name and answer plans record their own
selection and slot-join decisions. The EBOOT twin plan records the boot-string
PSX-key to PSP-US offset decisions, including which notices and controls the
executable-consumer proofs selected; the reward-notice plan records its two
corroborated notices. Plans freeze the correspondences a two-region pass found;
discovering new ones requires a fresh capture.

## Authored structural inputs

These files live in `src/extraction_tools/matching/`.

| File | Purpose / consumer |
|---|---|
| `accept.tsv` | reviewed story reattributions; port_story |
| `align_fix.tsv` | story overrides and explicit gaps; port_story, tstatus, qa_alignment |
| `boot_btlmsg.tsv` | PSX slot ↔ JP/US BOOT offsets; boot_btlmsg |
| `boot_s2dnames.tsv` | PSX label slot ↔ US BOOT offset; port_s2d, boot_s2dnames |
| `btlneg_map.tsv` | contact clusters, segments and strategies; port_btlneg |
| `descs_bank.tsv` | description slot ↔ BOOT bank offset; port_descs, descs_extend |
| `dng_map.tsv` | dungeon anchors and fixups; port_dng |
| `endtext_map.tsv` | image/page/line geometry; endtext |
| `s2d_map.tsv` | PSX box ↔ BOOT ranges and verification keys; port_s2d |
| `psp_pairs_extra.tsv` | reviewed PSP-JP ↔ PSP-US pairs; boot_pairs |
| `psx_jp_extra.tsv` | reviewed PSX ↔ PSP-JP anchors; match_jp |

`descs_extend.py` requires the verified seed in `descs_bank.tsv`.
`repair_alignment.py` appends proposals to `align_fix.tsv`; blank override
cells designate gaps. Neither tool reconstructs these authored inputs.

## Glyphs and wording

- `src/extraction_tools/psp_glyphs.tsv`: the shared PSP glyph table for both regions.
- `translation/manual/terms.tsv`: the `domain/key/en/note` wording dictionary,
  read by `strlib` through `toolbelt.GLOSSARY`.

The optional QA speaker glossary, `translation/manual/glossary.tsv`, uses a
separate `ja/en/category` schema, not the wording-dictionary schema.
