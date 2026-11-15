'use strict';
/* Raw LZMA decoding, for the blocks of a CHD (its `cdlz` codec).
 *
 * A CHD block is a raw LZMA stream - no header, the properties fixed by the
 * encoder settings libchdr reproduces (level 9: lc 3, lp 0, pb 2) - that
 * decodes to exactly one block's sector data, with or without an end
 * marker. The output buffer is the whole dictionary: a block is never
 * larger than a few sectors, so nothing wraps. The decoder follows the
 * reference LzmaDec.c of the LZMA SDK (vendored in DuckStation's dep/lzma).
 *
 * The range coder is an object with plain fields and every probability
 * lives in one Uint16Array at fixed offsets, so the engine inlines the hot
 * bit decoding; closures over mutable locals were three times slower.
 *
 *   LZMA.decode(src, outSize, {lc, lp, pb}) -> Uint8Array(outSize)
 */

(function () {
  const PROB_INIT = 1024;          // kBitModelTotal / 2
  const STATES = 12;
  const POS_STATES_MAX = 16;
  const END_POS_MODEL = 14;
  const ALIGN_BITS = 4;
  const LEN_LOW = 8, LEN_MID = 8;

  // offsets into the one probability array
  const IS_MATCH = 0;
  const IS_REP = IS_MATCH + (STATES << 4);
  const IS_REP_G0 = IS_REP + STATES;
  const IS_REP_G1 = IS_REP_G0 + STATES;
  const IS_REP_G2 = IS_REP_G1 + STATES;
  const IS_REP0_LONG = IS_REP_G2 + STATES;
  const POS_SLOT = IS_REP0_LONG + (STATES << 4);
  const POS_SPECIAL = POS_SLOT + (4 << 6);
  const ALIGN = POS_SPECIAL + 115;  // 1 + kNumFullDistances - kEndPosModelIndex
  const LEN_SIZE = 2 + (POS_STATES_MAX << 3) * 2 + 256;
  const LEN_CODER = ALIGN + (1 << ALIGN_BITS);
  const REP_LEN_CODER = LEN_CODER + LEN_SIZE;
  const LITERALS = REP_LEN_CODER + LEN_SIZE;
  // within a length coder
  const CHOICE = 0, LOW = 2, MID = LOW + (POS_STATES_MAX << 3), HIGH = MID + (POS_STATES_MAX << 3);

  class Decoder {
    constructor(src, probs) {
      this.src = src;
      this.pos = 1;
      this.probs = probs;
      this.range = 0xffffffff;
      this.code = 0;
      if (src[0] !== 0) throw new Error('LZMA stream does not start with 0');
      for (let i = 0; i < 4; i++) this.code = ((this.code << 8) | this.next()) >>> 0;
    }
    next() {
      if (this.pos >= this.src.length) throw new Error('LZMA input ended early');
      return this.src[this.pos++];
    }
    bit(i) {
      const probs = this.probs;
      const prob = probs[i];
      const bound = (this.range >>> 11) * prob;
      let result;
      if (this.code < bound) {
        this.range = bound;
        probs[i] = prob + ((2048 - prob) >>> 5);
        result = 0;
      } else {
        this.range -= bound;
        this.code -= bound;
        probs[i] = prob - (prob >>> 5);
        result = 1;
      }
      if (this.range < 0x1000000) {
        this.range = (this.range * 256) >>> 0;
        this.code = ((this.code * 256) + this.next()) >>> 0;
      }
      return result;
    }
    direct(count) {
      let result = 0;
      for (; count > 0; count--) {
        this.range >>>= 1;
        let take = 0;
        if (this.code >= this.range) {
          this.code -= this.range;
          take = 1;
        }
        result = result * 2 + take;
        if (this.range < 0x1000000) {
          this.range = (this.range * 256) >>> 0;
          this.code = ((this.code * 256) + this.next()) >>> 0;
        }
      }
      return result;
    }
    tree(base, bits) {
      let m = 1;
      for (let i = 0; i < bits; i++) m = (m << 1) | this.bit(base + m);
      return m - (1 << bits);
    }
    reverse(base, bits) {
      let m = 1;
      let symbol = 0;
      for (let i = 0; i < bits; i++) {
        const b = this.bit(base + m);
        m = (m << 1) | b;
        symbol |= b << i;
      }
      return symbol;
    }
    length(coder, posState) {
      if (!this.bit(coder + CHOICE)) return this.tree(coder + LOW + (posState << 3), 3);
      if (!this.bit(coder + CHOICE + 1)) return LEN_LOW + this.tree(coder + MID + (posState << 3), 3);
      return LEN_LOW + LEN_MID + this.tree(coder + HIGH, 8);
    }
  }

  function decode(src, outSize, {lc = 3, lp = 0, pb = 2} = {}) {
    const probs = new Uint16Array(LITERALS + (0x300 << (lc + lp))).fill(PROB_INIT);
    const rc = new Decoder(src, probs);
    const out = new Uint8Array(outSize);
    let pos = 0;
    let state = 0;
    let rep0 = 0, rep1 = 0, rep2 = 0, rep3 = 0;
    const pbMask = (1 << pb) - 1;
    const lpMask = (1 << lp) - 1;
    while (pos < outSize) {
      const posState = pos & pbMask;
      if (!rc.bit(IS_MATCH + (state << 4) + posState)) {
        const prev = pos > 0 ? out[pos - 1] : 0;
        const base = LITERALS + 0x300 * (((pos & lpMask) << lc) + (prev >>> (8 - lc)));
        let symbol = 1;
        if (state >= 7) {
          if (rep0 >= pos) throw new Error('LZMA distance before the start');
          let matchByte = out[pos - rep0 - 1];
          while (symbol < 0x100) {
            const matchBit = (matchByte >>> 7) & 1;
            matchByte <<= 1;
            const b = rc.bit(base + ((1 + matchBit) << 8) + symbol);
            symbol = (symbol << 1) | b;
            if (matchBit !== b) break;
          }
        }
        while (symbol < 0x100) symbol = (symbol << 1) | rc.bit(base + symbol);
        out[pos++] = symbol & 0xff;
        state = state < 4 ? 0 : state < 10 ? state - 3 : state - 6;
        continue;
      }
      let len;
      if (rc.bit(IS_REP + state)) {
        if (pos === 0) throw new Error('LZMA repeat at the start');
        if (!rc.bit(IS_REP_G0 + state)) {
          if (!rc.bit(IS_REP0_LONG + (state << 4) + posState)) {
            state = state < 7 ? 9 : 11;
            out[pos] = out[pos - rep0 - 1];
            pos++;
            continue;
          }
        } else {
          let dist;
          if (!rc.bit(IS_REP_G1 + state)) {
            dist = rep1;
          } else {
            if (!rc.bit(IS_REP_G2 + state)) {
              dist = rep2;
            } else {
              dist = rep3;
              rep3 = rep2;
            }
            rep2 = rep1;
          }
          rep1 = rep0;
          rep0 = dist;
        }
        len = rc.length(REP_LEN_CODER, posState);
        state = state < 7 ? 8 : 11;
      } else {
        rep3 = rep2;
        rep2 = rep1;
        rep1 = rep0;
        len = rc.length(LEN_CODER, posState);
        state = state < 7 ? 7 : 10;
        const slot = rc.tree(POS_SLOT + ((len < 3 ? len : 3) << 6), 6);
        if (slot < 4) {
          rep0 = slot;
        } else {
          const directBits = (slot >>> 1) - 1;
          let dist = (2 | (slot & 1)) * (2 ** directBits);
          if (slot < END_POS_MODEL) {
            dist += rc.reverse(POS_SPECIAL + dist - slot, directBits);
          } else {
            dist += rc.direct(directBits - ALIGN_BITS) * (1 << ALIGN_BITS);
            dist += rc.reverse(ALIGN, ALIGN_BITS);
          }
          rep0 = dist;
          if (rep0 === 0xffffffff) break;   // end marker
        }
      }
      len += 2;
      if (rep0 >= pos) throw new Error('LZMA distance before the start');
      const end = Math.min(pos + len, outSize);
      for (; pos < end; pos++) out[pos] = out[pos - rep0 - 1];
    }
    if (pos !== outSize) throw new Error('LZMA stream ended before its block');
    return out;
  }

  globalThis.LZMA = {decode};
})();
