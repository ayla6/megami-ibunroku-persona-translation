# Test timing and verification scope

Collect timings without changing the selected tests:

    python tools/run_tests.py --timings build/qa/tests.tsv 'test_mod_*'

The TSV separates module-import time from suite execution and lists individual
cases from slowest to fastest. Individual durations are contained within suite
execution; do not add them to that phase total. Skipped tests remain reported by
unittest. With no --timings argument, normal output is unchanged.

The recorded 15m04s release separately timed 13.4s of test-suite commands,
45.3s of assembly write guards and 23.5s of source/read-back QA. These 82.2s are
a lower bound, not the complete verification cost: final browser/standalone
parity and orchestrator merge comparisons were not separately instrumented.
The remaining time must not be labelled solely as production work.

Clone censuses filter candidate instruction positions by opcode and still
perform the original complete signature comparisons and patch-site assertions.
The assembled-name CPU checks and all tested overlays remain covered.
Build-orchestration unit tests mock their cleanup, cache restoration and assembly
publication so they cannot rewrite a real build while asserting command order.

An earlier full verified release completed in 751.638 seconds. Its final browser disc,
browser PPF and standalone PPF comparison against the native builder took
186.015 seconds, including native image generation and byte comparisons.
All 20 compressed layers were read back and matched their staged parts.
Evidence: build/qa/release-final/release.log and build/qa/release-profile.tsv.
The profile's parent-function timings are inclusive and nested; do not sum them.
The current default verification run also passed with the Base negotiation
inset setting: all 20 layers are marked `verified`, and the browser disc,
browser PPF and standalone PPF match the native builder byte for byte.
Evidence: `/tmp/persona-default-verified-release.log`.

Release verification runs by default. `--no-verify-release` explicitly skips
those checks and marks files untested. A resumed production-only run took
6m 44s with 34 cached native trees and 47 new assemblies. It produced all 20
layers with zero test-runner or disc-build calls. This excludes time already
spent on the interrupted attempt.

Movie-sector batching uses the same vectorized Form 1 checksum generator as
ordinary data files, in batches capped at 4,096 sectors. Form 2 audio retains
its stored EDC. On the saved all-layer input, native construction measured
72.779 seconds before and 15.150 seconds after; the complete disc bytes were
identical. Movie writes themselves measured 64.969 and 3.572 seconds. This
is an isolated native-builder measurement, not a full release time. Evidence
is under build/qa/release-performance.

The browser verifier compares its complete disc Blob stream against the
native disc without writing another disc file. Both PPFs are still applied
while comparing against the native disc. Size/content mismatch tests prove
that the streaming comparison rejects differences and leaves its input intact.

The structural disc audit reads up to 4,096 adjacent raw sectors from each
image before comparing user bytes. This retains every original sector/ownership
comparison while avoiding one seek between images per sector on rotating disks.
The 16 structural-audit tests pass, including corruption rejection.

The dub's retail twin lookup now discovers equal sector bodies once per image
identity/index and stores a verified TSV. Subsequent lookups, including after
clearing process-local state, do not reread movie payloads. The real 41-entry
retail index produced two reciprocal links; the fresh-cache smoke test forbade
movie reads and passed. Evidence: build/qa/release-performance/
persona-retail-movie-twins-smoke.log. Changes to image identity force discovery.

Movie and battle-voice cache dependencies resolve shared codec/build helpers
through toolpath.script, so relocated helpers are actual inputs rather than
missing paths beside the mod.

Retail duplicate discovery filters by occupied sector count and first-sector
body before hashing complete candidates. Its exact groups and member order
matched the verified base layer on the real disc (33 groups; 53,795 sector
reads). The result is stored in a verified TSV keyed by the retail image,
index and discovery code; changed inputs or damaged output force rediscovery.

Dub rendering keys use render_inputs.py: the renderer's local function graph,
referenced scalar constants and imported module dependencies. Unrelated output
driver changes are excluded; dynamic global lookup and unsupported global
state retain the defining module as a conservative dependency. The caller
still supplies movie bytes, tracks and cue timing as separate inputs.

Incremental native references have a targeted integration check under
build/qa/incremental-release: one real Run in Dungeons configuration was
built and replayed. Replay reused 125 identical changed files without invoking
the main assembler. The focused suite ran 48 tests; no full matrix was launched.
These checks establish reuse and invalidation behavior, not a new full-release
speed measurement. Shared preparation may still run when its inputs change.

Release composition caches snapshot bytes by full file identity, so identical
hard links in separate native trees share a read. A replay of 84 existing
snapshots matched every stored SHA-1 while reducing file reads from 7,485 to
373 and bytes requested from 6.34 GB to 431 MB. This counts reads through the
filesystem API, including page-cache hits. It is not a full release timing.
