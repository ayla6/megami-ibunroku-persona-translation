'use strict';
/* Raw DEFLATE (RFC 1951) decoding, for a CHD block's deflate parts (the
 * `cdzl` codec's sectors, every CD block's subcode).
 *
 * The blocks are a few kilobytes each and there are thousands of them, so
 * this is a small synchronous decoder rather than a DecompressionStream per
 * block, whose setup costs more than the inflating.
 *
 *   INFLATE.raw(src, outSize) -> Uint8Array(outSize)
 */

(function () {
  const LENGTH_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
                       35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
  const LENGTH_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
                        3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  const DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
                     257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
                     8193, 12289, 16385, 24577];
  const DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
                      7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
  const CLEN_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];

  /* Canonical Huffman table: counts per length and symbols in code order. */
  function table(lengths) {
    const counts = new Uint16Array(16);
    for (const length of lengths) counts[length]++;
    counts[0] = 0;
    const offsets = new Uint16Array(16);
    for (let i = 1; i < 16; i++) offsets[i] = offsets[i - 1] + counts[i - 1];
    const symbols = new Uint16Array(lengths.length);
    lengths.forEach((length, symbol) => {
      if (length) symbols[offsets[length]++] = symbol;
    });
    return {counts, symbols};
  }

  const FIXED_LIT = table(Array.from({length: 288},
      (_, i) => (i < 144 ? 8 : i < 256 ? 9 : i < 280 ? 7 : 8)));
  const FIXED_DIST = table(new Array(30).fill(5));

  function raw(src, outSize) {
    const out = new Uint8Array(outSize);
    let pos = 0;              // output
    let at = 0;               // input byte
    let bitBuf = 0;
    let bitCount = 0;
    const bits = n => {
      while (bitCount < n) {
        if (at >= src.length) throw new Error('deflate input ended early');
        bitBuf |= src[at++] << bitCount;
        bitCount += 8;
      }
      const value = bitBuf & ((1 << n) - 1);
      bitBuf >>>= n;
      bitCount -= n;
      return value;
    };
    const symbol = ({counts, symbols}) => {
      let code = 0, first = 0, index = 0;
      for (let length = 1; length < 16; length++) {
        code |= bits(1);
        const count = counts[length];
        if (code - first < count) return symbols[index + code - first];
        index += count;
        first = (first + count) << 1;
        code <<= 1;
      }
      throw new Error('bad deflate code');
    };
    let last = 0;
    while (!last) {
      last = bits(1);
      const type = bits(2);
      if (type === 0) {
        bitBuf = 0;
        bitCount = 0;                       // to the byte boundary
        if (at + 4 > src.length) throw new Error('deflate input ended early');
        const length = src[at] | (src[at + 1] << 8);
        at += 4;
        if (pos + length > outSize || at + length > src.length) throw new Error('bad stored deflate block');
        out.set(src.subarray(at, at + length), pos);
        at += length;
        pos += length;
        continue;
      }
      let lit = FIXED_LIT, dist = FIXED_DIST;
      if (type === 2) {
        const nlen = bits(5) + 257, ndist = bits(5) + 1, nclen = bits(4) + 4;
        const clen = new Array(19).fill(0);
        for (let i = 0; i < nclen; i++) clen[CLEN_ORDER[i]] = bits(3);
        const lengthCode = table(clen);
        const lengths = [];
        while (lengths.length < nlen + ndist) {
          const sym = symbol(lengthCode);
          if (sym < 16) lengths.push(sym);
          else if (sym === 16) {
            if (!lengths.length) throw new Error('bad deflate lengths');
            const previous = lengths[lengths.length - 1];
            for (let n = 3 + bits(2); n > 0; n--) lengths.push(previous);
          } else if (sym === 17) {
            for (let n = 3 + bits(3); n > 0; n--) lengths.push(0);
          } else {
            for (let n = 11 + bits(7); n > 0; n--) lengths.push(0);
          }
        }
        lit = table(lengths.slice(0, nlen));
        dist = table(lengths.slice(nlen, nlen + ndist));
      } else if (type !== 1) {
        throw new Error('bad deflate block type');
      }
      for (;;) {
        const sym = symbol(lit);
        if (sym < 256) {
          if (pos >= outSize) throw new Error('deflate output too long');
          out[pos++] = sym;
        } else if (sym === 256) {
          break;
        } else {
          const l = sym - 257;
          if (l >= 29) throw new Error('bad deflate length');
          const length = LENGTH_BASE[l] + bits(LENGTH_EXTRA[l]);
          const d = symbol(dist);
          if (d >= 30) throw new Error('bad deflate distance');
          const distance = DIST_BASE[d] + bits(DIST_EXTRA[d]);
          if (distance > pos || pos + length > outSize) throw new Error('bad deflate copy');
          for (let k = 0; k < length; k++, pos++) out[pos] = out[pos - distance];
        }
      }
    }
    if (pos !== outSize) throw new Error('deflate output has the wrong size');
    return out;
  }

  globalThis.INFLATE = {raw};
})();
