'use strict';
/* PPF 3.0 from two equal-length images, for players whose emulator or
 * frontend soft-patches with .ppf instead of loading a patched .bin.
 *
 * A PPF overwrites bytes at offsets and can neither grow nor shrink a file,
 * so it exists only for a chain whose result is the source's length: Rev 0
 * (every release image keeps retail's length). A Rev 1 disc is shorter than
 * Rev 0, so its result has no PPF.
 *
 * Layout (PPF3.0, encoding method 2): "PPF30", 0x02, a 50-byte description,
 * image type 0 (BIN), block check 1, undo 0, one zero byte, then the 1024
 * source bytes at 0x9320 the applier compares before patching, then records
 * of u64 LE offset, u8 length (1..255) and that many bytes. Two changed runs
 * with no more than one record header of unchanged bytes between them are
 * joined: the gap costs no more than the header it saves.
 */

(function () {
  const BLOCK_AT = 0x9320;
  const BLOCK_BYTES = 1024;
  const RECORD_HEAD = 9;           // u64 offset + u8 length
  const RECORD_MAX = 255;
  const CHUNK = 8 * 1024 * 1024;

  function header(description, block) {
    const head = new Uint8Array(60 + BLOCK_BYTES);
    head.set([0x50, 0x50, 0x46, 0x33, 0x30, 0x02]);   // "PPF30", method 2
    const text = new TextEncoder().encode(description).subarray(0, 50);
    head.fill(0x20, 6, 56);
    head.set(text, 6);
    head[56] = 0;                  // image type: BIN
    head[57] = 1;                  // block check
    head[58] = 0;                  // no undo data
    head[59] = 0;
    head.set(block, 60);
    return head;
  }

  /* `regions` is an iterable of {base, source, target}: stretches in offset
   * order where the target may differ from the source, both images' bytes
   * for it (bytes outside every region are equal). `block` is the source's
   * 1024 bytes at 0x9320. Returns the .ppf as an array of Uint8Array parts
   * (hand it to a Blob). */
  function fromRegions(block, regions, description) {
    if (block.length !== BLOCK_BYTES) throw new Error('image too small for a PPF');
    const parts = [header(description, block)];
    let out = new Uint8Array(1 << 20);
    let used = 0;
    const emit = (offset, data) => {
      for (let pos = 0; pos < data.length; pos += RECORD_MAX) {
        const piece = data.subarray(pos, Math.min(pos + RECORD_MAX, data.length));
        if (used + RECORD_HEAD + piece.length > out.length) {
          parts.push(out.subarray(0, used));
          out = new Uint8Array(1 << 20);
          used = 0;
        }
        let at = offset + pos;
        for (let k = 0; k < 8; k++) {   // u64 LE; image offsets fit 2^53
          out[used + k] = at % 256;
          at = Math.floor(at / 256);
        }
        out[used + 8] = piece.length;
        out.set(piece, used + RECORD_HEAD);
        used += RECORD_HEAD + piece.length;
      }
    };
    let runStart = -1;   // offset of the open run (changed bytes plus the
    let run = new Uint8Array(4096);   // short unchanged gaps joined into it)
    let runLength = 0;
    const flush = () => {
      if (runStart >= 0) emit(runStart, run.subarray(0, runLength));
      runStart = -1;
      runLength = 0;
    };
    const extend = bytes => {
      if (runLength + bytes.length > run.length) {
        const grown = new Uint8Array(Math.max(run.length * 2, runLength + bytes.length));
        grown.set(run.subarray(0, runLength));
        run = grown;
      }
      run.set(bytes, runLength);
      runLength += bytes.length;
    };
    for (const {base, source, target} of regions) {
      const length = source.length;
      if (target.length !== length) throw new Error('PPF region sizes differ');
      // equal stretches (almost the whole image) are skipped a word at a time
      const words = source.byteOffset % 4 || target.byteOffset % 4 ? 0 : length >> 2;
      const source32 = words ? new Int32Array(source.buffer, source.byteOffset, words) : null;
      const target32 = words ? new Int32Array(target.buffer, target.byteOffset, words) : null;
      let i = 0;
      while (i < length) {
        if ((i & 3) === 0 && (i >> 2) < words) {
          let w = i >> 2;
          while (w < words && source32[w] === target32[w]) w++;
          if (w << 2 !== i) { i = w << 2; continue; }
        }
        if (source[i] === target[i]) { i++; continue; }
        let j = i + 1;
        while (j < length && source[j] !== target[j]) j++;
        const runEnd = runStart + runLength;
        // a gap from the previous chunk is no longer at hand: close the run
        if (runStart >= 0 && (base + i - runEnd > RECORD_HEAD || runEnd < base)) flush();
        if (runStart < 0) runStart = base + i;
        extend(target.subarray(runStart + runLength - base, j));
        i = j;
      }
    }
    flush();
    parts.push(out.subarray(0, used));
    return parts;
  }

  /* Two whole images, read CHUNK bytes at a time: `read(which, offset,
   * length)` returns the source (which = 0) or the target (which = 1). */
  function build(size, read, description) {
    function* chunks() {
      for (let base = 0; base < size; base += CHUNK) {
        const length = Math.min(CHUNK, size - base);
        const source = read(0, base, length);
        const target = read(1, base, length);
        if (source.length !== length || target.length !== length) {
          throw new Error('short read while writing the PPF');
        }
        yield {base, source, target};
      }
    }
    return fromRegions(read(0, BLOCK_AT, BLOCK_BYTES), chunks(), description);
  }

  globalThis.PPF = {build, fromRegions, BLOCK_AT, BLOCK_BYTES};
})();
