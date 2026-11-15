'use strict';
/* Follow the release patches' VCDIFF instructions without applying them.
 *
 * An image is held as a list of segments covering it in order: a run of the
 * ORIGINAL disc's bytes from some offset (`f`), or literal bytes (`d`). The
 * original disc is the user's file and is never copied; a patch step maps
 * one image onto the next by its instructions alone - an unchanged 8 MB
 * window is a single same-offset COPY, so it stays one segment - and only
 * the bytes a patch really adds are held. Comparing two images then reads
 * the original only where they differ, which is all a PPF needs, and an
 * image can be handed out as a Blob of slices of the original file plus the
 * added bytes, with nothing disc-sized in memory.
 *
 * Only plain RFC 3284 is understood: the default code table, no secondary
 * compression (the release encodes with `xdelta3 -S none`), plus xdelta3's
 * application header and per-window Adler-32 field, both skipped. A patch
 * that uses anything else is refused by name. The window checksums are not
 * computed (that would read the whole disc per step): the disc is
 * identified by xdelta3 itself before this runs, every patch file's SHA-256
 * is checked against the manifest, and every step's output size is checked.
 *
 *   VCDIFF.original(size)                 -> image of the untouched disc
 *   VCDIFF.apply(image, patchBytes, read) -> the next image
 *   VCDIFF.read(image, offset, n, read)   -> Uint8Array of the image
 *   VCDIFF.differences(a, b, read)        -> yields {base, source, target}
 *                                            where image b may differ from a,
 *                                            in order, one at a time
 *   VCDIFF.blobParts(image, file)         -> Blob parts for the whole image
 *   VCDIFF.cachedReader(read, size)       -> `read` through a block cache
 *
 * `read(offset, n)` returns n bytes of the original disc.
 */

(function () {
  const NOOP = 0, ADD = 1, RUN = 2, COPY = 3;
  const NEAR = 4, SAME = 3;

  /* RFC 3284 section 5.6: the default instruction code table. */
  const TABLE = (() => {
    const table = [];
    const entry = (t1, s1, m1, t2 = NOOP, s2 = 0, m2 = 0) =>
        table.push([t1, s1, m1, t2, s2, m2]);
    entry(RUN, 0, 0);
    for (let size = 0; size <= 17; size++) entry(ADD, size, 0);
    for (let mode = 0; mode < 9; mode++) {
      entry(COPY, 0, mode);
      for (let size = 4; size <= 18; size++) entry(COPY, size, mode);
    }
    for (let mode = 0; mode < 6; mode++) {
      for (let add = 1; add <= 4; add++) {
        for (let size = 4; size <= 6; size++) entry(ADD, add, 0, COPY, size, mode);
      }
    }
    for (let mode = 6; mode < 9; mode++) {
      for (let add = 1; add <= 4; add++) entry(ADD, add, 0, COPY, 4, mode);
    }
    for (let mode = 0; mode < 9; mode++) entry(COPY, 4, mode, ADD, 1, 0);
    if (table.length !== 256) throw new Error('VCDIFF code table is not 256 entries');
    return table;
  })();

  /* An image under construction: segments appended in order. Literal bytes
   * are copied into shared chunks, so consecutive literals (an ADD between
   * two short COPYs, again and again) stay one segment. */
  const CHUNK = 1 << 20;

  class Builder {
    constructor() {
      this.segs = [];
      this.size = 0;
      this.chunk = null;      // the chunk the last data segment ends in
      this.used = 0;
    }
    original(from, n) {
      if (!n) return;
      const last = this.segs[this.segs.length - 1];
      if (last && last.d === null && last.f + last.n === from) {
        last.n += n;
      } else {
        this.segs.push({s: this.size, n, f: from, d: null});
      }
      this.size += n;
    }
    bytes(data) {
      const n = data.length;
      if (!n) return;
      const last = this.segs[this.segs.length - 1];
      const extend = last && last.d !== null && this.chunk
          && last.d.buffer === this.chunk.buffer
          && last.d.byteOffset + last.n === this.chunk.byteOffset + this.used;
      if (this.used + n > (this.chunk ? this.chunk.length : 0)) {
        this.chunk = new Uint8Array(Math.max(CHUNK, n));
        this.used = 0;
        this.chunk.set(data, 0);
        this.used = n;
        this.segs.push({s: this.size, n, f: -1, d: this.chunk.subarray(0, n)});
      } else {
        this.chunk.set(data, this.used);
        if (extend) {
          last.n += n;
          last.d = this.chunk.subarray(this.used + n - last.n, this.used + n);
        } else {
          this.segs.push({s: this.size, n, f: -1,
                          d: this.chunk.subarray(this.used, this.used + n)});
        }
        this.used += n;
      }
      this.size += n;
    }
    piece(piece) {
      if (piece.d === null) this.original(piece.f, piece.n);
      else this.bytes(piece.d);
    }
  }

  /* `read(offset, n)` through a cache of whole blocks: the patches' pieces
   * of the original are small and close together, and one read of a File
   * costs far more than the bytes in it. */
  function cachedReader(read, size, block = 1 << 16, slots = 256) {
    const cache = new Map();          // block index -> bytes, oldest first
    const blockAt = index => {
      let bytes = cache.get(index);
      if (bytes) {
        cache.delete(index);
      } else {
        const start = index * block;
        bytes = read(start, Math.min(block, size - start));
        if (cache.size >= slots) cache.delete(cache.keys().next().value);
      }
      cache.set(index, bytes);
      return bytes;
    };
    return (offset, n) => {
      const first = Math.floor(offset / block);
      const last = Math.floor((offset + n - 1) / block);
      if (first === last) {
        // a copy: a view would keep the whole block alive with the caller
        const skip = offset - first * block;
        return blockAt(first).slice(skip, skip + n);
      }
      const out = new Uint8Array(n);
      for (let index = first, pos = 0; index <= last; index++) {
        const bytes = blockAt(index);
        const skip = Math.max(0, offset - index * block);
        const take = Math.min(bytes.length - skip, n - pos);
        out.set(bytes.subarray(skip, skip + take), pos);
        pos += take;
      }
      return out;
    };
  }

  function original(size) {
    const image = new Builder();
    image.original(0, size);
    return image;
  }

  /* The segment holding offset `at` (binary search). */
  function find(image, at) {
    const segs = image.segs;
    let lo = 0;
    let hi = segs.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (segs[mid].s <= at) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  }

  /* The pieces of image[at, at + n): {n, f, d} clipped to the range. */
  function pieces(image, at, n) {
    if (at < 0 || at + n > image.size) {
      throw new Error('VCDIFF copy reaches outside its source');
    }
    const out = [];
    if (!n) return out;
    for (let k = find(image, at); n > 0; k++) {
      const seg = image.segs[k];
      const skip = at - seg.s;
      const take = Math.min(seg.n - skip, n);
      out.push(seg.d === null
          ? {n: take, f: seg.f + skip, d: null}
          : {n: take, f: -1, d: seg.d.subarray(skip, skip + take)});
      at += take;
      n -= take;
    }
    return out;
  }

  function read(image, at, n, readOriginal) {
    const out = new Uint8Array(n);
    let pos = 0;
    for (const piece of pieces(image, at, n)) {
      out.set(piece.d === null ? readOriginal(piece.f, piece.n) : piece.d, pos);
      pos += piece.n;
    }
    return out;
  }

  function apply(source, patch, readOriginal) {
    let p = 0;
    const varint = (bytes, at) => {
      let value = 0;
      for (;;) {
        if (at.i >= bytes.length) throw new Error('truncated VCDIFF');
        const byte = bytes[at.i++];
        value = value * 128 + (byte & 0x7f);
        if (!(byte & 0x80)) return value;
      }
    };
    const top = {i: 0};
    if (patch[0] !== 0xd6 || patch[1] !== 0xc3 || patch[2] !== 0xc4 || patch[3] !== 0) {
      throw new Error('not a VCDIFF patch');
    }
    const header = patch[4];
    top.i = 5;
    if (header & 0x01) {
      throw new Error('this patch uses secondary compression; it was made'
          + ' by an older release build - reload the page for the current release');
    }
    if (header & 0x02) throw new Error('VCDIFF custom code tables are not supported');
    if (header & 0x04) top.i += varint(patch, top);   // xdelta3 application header
    const out = new Builder();
    while (top.i < patch.length) {
      const indicator = patch[top.i++];
      let segLength = 0;
      let segPosition = 0;
      if (indicator & 0x03) {
        segLength = varint(patch, top);
        segPosition = varint(patch, top);
      }
      const segImage = indicator & 0x02 ? out : source;
      const deltaLength = varint(patch, top);
      const deltaEnd = top.i + deltaLength;
      const targetLength = varint(patch, top);
      if (patch[top.i++]) throw new Error('VCDIFF compressed sections are not supported');
      const dataLength = varint(patch, top);
      const instLength = varint(patch, top);
      const addrLength = varint(patch, top);
      if (indicator & 0x04) top.i += 4;                // xdelta3 Adler-32
      p = top.i;
      const data = patch.subarray(p, p + dataLength);
      const inst = patch.subarray(p + dataLength, p + dataLength + instLength);
      const addr = patch.subarray(p + dataLength + instLength,
                                  p + dataLength + instLength + addrLength);
      if (p + dataLength + instLength + addrLength !== deltaEnd) {
        throw new Error('VCDIFF window sections do not add up');
      }
      top.i = deltaEnd;

      const near = new Array(NEAR).fill(0);
      const same = new Array(SAME * 256).fill(0);
      let nextSlot = 0;
      const at = {data: 0, inst: {i: 0}, addr: {i: 0}};
      const windowStart = out.size;
      let t = 0;                       // target bytes produced in this window
      const address = (here, mode) => {
        let value;
        if (mode === 0) value = varint(addr, at.addr);
        else if (mode === 1) value = here - varint(addr, at.addr);
        else if (mode < 2 + NEAR) value = near[mode - 2] + varint(addr, at.addr);
        else {
          if (at.addr.i >= addr.length) throw new Error('truncated VCDIFF');
          value = same[(mode - 2 - NEAR) * 256 + addr[at.addr.i++]];
        }
        near[nextSlot] = value;
        nextSlot = (nextSlot + 1) % NEAR;
        same[value % (SAME * 256)] = value;
        return value;
      };
      while (at.inst.i < inst.length) {
        const code = TABLE[inst[at.inst.i++]];
        for (let half = 0; half < 6; half += 3) {
          const type = code[half];
          if (type === NOOP) continue;
          const size = code[half + 1] || varint(inst, at.inst);
          if (type === ADD) {
            out.bytes(data.subarray(at.data, at.data + size));
            at.data += size;
          } else if (type === RUN) {
            out.bytes(new Uint8Array(size).fill(data[at.data++]));
          } else {
            const from = address(segLength + t, code[half + 2]);
            let n = size;
            let a = from;
            if (a < segLength) {        // from the source segment
              const take = Math.min(n, segLength - a);
              for (const piece of pieces(segImage, segPosition + a, take)) out.piece(piece);
              a += take;
              n -= take;
            }
            if (n) {                    // from this window's own target
              const start = a - segLength;
              const produced = t + (size - n);
              if (start + n <= produced) {
                for (const piece of pieces(out, windowStart + start, n)) out.piece(piece);
              } else {
                // overlapping: the copy repeats what it is writing, so its
                // pattern is read out (from the original where it is there)
                const period = produced - start;
                const pattern = read(out, windowStart + start, period, readOriginal);
                const bytes = new Uint8Array(n);
                for (let k = 0; k < n; k++) bytes[k] = pattern[k % period];
                out.bytes(bytes);
              }
            }
          }
          t += size;
        }
      }
      if (t !== targetLength) throw new Error('VCDIFF window has the wrong length');
    }
    return out;
  }

  /* Where image b may differ from image a: every stretch that is not the
   * same original bytes in both, with both images' bytes for it. */
  function* differences(a, b, readOriginal) {
    if (a.size !== b.size) throw new Error('images differ in size');
    for (const seg of b.segs) {
      let at = seg.s;
      for (const piece of pieces(a, seg.s, seg.n)) {
        const offset = at - seg.s;
        const sameOriginal = seg.d === null && piece.d === null
            && seg.f + offset === piece.f;
        if (!sameOriginal) {
          yield {
            base: at,
            source: piece.d === null ? readOriginal(piece.f, piece.n) : piece.d,
            target: seg.d === null
                ? readOriginal(seg.f + offset, piece.n)
                : seg.d.subarray(offset, offset + piece.n),
          };
        }
        at += piece.n;
      }
    }
  }

  function blobParts(image, file) {
    return image.segs.map(seg => seg.d === null
        ? file.slice(seg.f, seg.f + seg.n) : seg.d);
  }

  globalThis.VCDIFF = {original, apply, read, differences, blobParts, cachedReader};
})();
