'use strict';
/* Run xdelta3's main and return its exit status.
 *
 * The vendored Emscripten build returns the command's status from callMain
 * (and may throw it as ExitStatus). Never assume success: decoding from a
 * mismatched source prints a warning and returns 1, and that status is how
 * disc identification and every chain step tell a good decode from a bad
 * one. */
function runXdelta(args) {
  try {
    const status = Module.callMain(args);
    return typeof status === 'number' ? status : 0;
  } catch (err) {
    if (err && typeof err.status === 'number') return err.status;  // ExitStatus
    throw err;
  }
}
