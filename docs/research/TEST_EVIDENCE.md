# Test evidence and limits

The Python suite includes source-data checks, builder unit tests, assembled
MIPS execution, and disc/patch tooling tests. These check different layers;
passing one layer does not establish in-game behavior.

- The bounded CPU in `tools/tests/mips_cpu.py` models integer instructions,
  load and branch delays, but not GPU execution, BIOS behavior, DMA timing,
  or instruction cycle timing. Individual tests model the services they need.
- A mocked `LoadImage` must not assume the pixels were copied at the call:
  GPU work can retain the source until completion. `test_s2d_label_strip.py`
  exercises deferred reads through `DrawSync`, including a 15-cell strip on
  the 12-cell compositor ring. `test_qol_saves.py` also checks its upload
  sources at the sync. These models do not emulate the complete GPU queue.
- Many runtime tests consume files already in `build/`; they do not establish
  those files are current, nor that a disc contains them. Assemble the intended
  variant first and separately check the disc bytes when validating a disc.
  Despite its filename, `test_s2d_script_disc_readback.py` reads `build/S2D.BIN`,
  not a disc image.
- Tests that derive both expected and actual data using the same encoder or
  source parser can detect relocation and corruption, but not a shared error
  in that encoder or parser. Source-text and opcode checks prove only the
  specific structure asserted, not the complete runtime behavior.
- Some tests intentionally skip when optional data, a particular variant, or
  a captured RAM image is unavailable. Read the skip reasons; a green run is
  not evidence for those paths. Required symbols missing from an otherwise
  assembled build are errors in the relevant renderer/readback tests.

This is a risk inventory, not a proof that every test oracle or hardware
assumption is complete. In-game reports and QA remain necessary.
