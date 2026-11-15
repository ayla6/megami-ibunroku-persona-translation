'use strict';
/* Read the few sectors a PPF needs straight out of a CHD (MAME's compressed
 * disc format), without unpacking the rest.
 *
 * Follows libchdr (DuckStation's dep/libchdr): a version 5 header, the
 * Huffman-coded block map, and the CD codecs chdman writes by default -
 * `cdlz` (LZMA sector data, deflate subcode) and `cdzl` (deflate both) -
 * plus uncompressed blocks and blocks that repeat another one. LZMA comes
 * from lzma.js and deflate from inflate.js, both synchronous. Anything
 * else (`cdfl` FLAC, `cdzs` zstd, a parent CHD) is refused by name. Each
 * unpacked block is checked against the CRC-16 the map stores for it, and
 * the sync and ECC that chdman strips from a sector are rebuilt the way
 * libchdr does.
 *
 * A CHD stores frames of 2352 sector bytes plus 96 subcode bytes, tracks
 * padded to 4 frames, `hunkbytes / 2448` frames to a block. A single data
 * track's sectors are the .bin's sectors in order, so the .bin offset of
 * byte k is frame k / 2352, byte k % 2352.
 *
 *   CHD.headerSha1(readAt)    -> the disc's raw SHA-1 from the header alone, or null
 *   CHD.open(readAt)          -> {hunkBytes, frames, hunks, rawSha1, binBytes, ...}
 *                                readAt(offset, n) is async -> Uint8Array
 *   CHD.hunk(chd, index, readAt) -> Uint8Array of that block's sector bytes
 *                                (frames * 2352), async (for readAt only)
 *   CHD.portable(chd)         -> the parts another worker needs to unpack blocks
 *   CHD.hunksFor(chd, offset, n) -> block indices holding .bin bytes [offset, offset+n)
 */

(function () {
  const FRAME = 2448;            // CD_FRAME_SIZE
  const SECTOR = 2352;           // CD_MAX_SECTOR_DATA
  const SUBCODE = 96;            // CD_MAX_SUBCODE_DATA
  const SYNC = [0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x00];

  const COMPRESSION_NONE = 4, COMPRESSION_SELF = 5, COMPRESSION_PARENT = 6;
  const RLE_SMALL = 7, RLE_LARGE = 8, SELF_0 = 9, SELF_1 = 10;
  const PARENT_SELF = 11, PARENT_0 = 12, PARENT_1 = 13;

  const fourcc = bytes => String.fromCharCode(...bytes).replace(/\0+$/, '');
  const be = (bytes, at, n) => {
    let value = 0;
    for (let i = 0; i < n; i++) value = value * 256 + bytes[at + i];
    return value;
  };

  /* CRC-16/CCITT (poly 0x1021, start 0xffff), as libchdr's crc16. */
  const CRC_TABLE = (() => {
    const table = new Uint16Array(256);
    for (let i = 0; i < 256; i++) {
      let crc = i << 8;
      for (let k = 0; k < 8; k++) crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
      table[i] = crc;
    }
    return table;
  })();
  function crc16(bytes) {
    let crc = 0xffff;
    for (const byte of bytes) crc = ((crc << 8) ^ CRC_TABLE[((crc >>> 8) ^ byte) & 0xff]) & 0xffff;
    return crc;
  }

  /* MSB-first bit reader, as libchdr's bitstream. */
  class Bits {
    constructor(bytes) {
      this.bytes = bytes;
      this.pos = 0;              // bit position
    }
    read(count) {
      let value = 0;
      for (let i = 0; i < count; i++) {
        const byte = this.bytes[this.pos >>> 3];
        const b = byte === undefined ? 0 : (byte >>> (7 - (this.pos & 7))) & 1;
        value = value * 2 + b;
        this.pos++;
      }
      return value;
    }
  }

  /* The map's Huffman code: 16 symbols of at most 8 bits, its code lengths
   * RLE-coded in 4-bit fields (huffman_import_tree_rle), canonical codes. */
  function huffman(bits) {
    const NUM = 16, MAXBITS = 8, FIELD = 4;
    const lengths = [];
    while (lengths.length < NUM) {
      let value = bits.read(FIELD);
      if (value !== 1) {
        lengths.push(value);
      } else {
        value = bits.read(FIELD);
        if (value === 1) {
          lengths.push(1);
        } else {
          const repeat = bits.read(FIELD) + 3;
          if (lengths.length + repeat > NUM) throw new Error('CHD map: bad Huffman tree');
          for (let i = 0; i < repeat; i++) lengths.push(value);
        }
      }
    }
    // canonical codes, longest first (huffman_assign_canonical_codes)
    const histo = new Array(33).fill(0);
    for (const length of lengths) histo[length]++;
    let start = 0;
    for (let length = 32; length > 0; length--) {
      const next = (start + histo[length]) >>> 1;
      if (length !== 1 && next * 2 !== start + histo[length]) {
        throw new Error('CHD map: inconsistent Huffman tree');
      }
      histo[length] = start;
      start = next;
    }
    const lookup = new Int32Array(1 << MAXBITS).fill(-1);
    lengths.forEach((length, symbol) => {
      if (!length) return;
      const code = histo[length]++;
      const shift = MAXBITS - length;
      for (let k = code << shift; k < (code + 1) << shift; k++) lookup[k] = (symbol << 5) | length;
    });
    return () => {
      const save = bits.pos;
      const peek = bits.read(MAXBITS);
      const entry = lookup[peek];
      if (entry < 0) throw new Error('CHD map: bad Huffman code');
      bits.pos = save + (entry & 0x1f);
      return entry >>> 5;
    };
  }

  /* The raw SHA-1 from a CHD's 124-byte header, or null when the file is
   * not a version 5 CHD: enough to tell which disc it holds. */
  async function headerSha1(readAt) {
    const head = await readAt(0, 124);
    if (head.length < 124 || fourcc(head.subarray(0, 8)) !== 'MComprHD' || be(head, 12, 4) !== 5) {
      return null;
    }
    return [...head.subarray(64, 84)].map(b => b.toString(16).padStart(2, '0')).join('');
  }

  async function open(readAt) {
    const head = await readAt(0, 124);
    if (fourcc(head.subarray(0, 8)) !== 'MComprHD') throw new Error('not a CHD file');
    const version = be(head, 12, 4);
    if (version !== 5) {
      throw new Error(`this CHD is version ${version}; only version 5 CHDs (chdman 0.146`
          + ' and later) are supported - recompress it with chdman, or use the .bin');
    }
    const codecs = [0, 1, 2, 3].map(i => fourcc(head.subarray(16 + 4 * i, 20 + 4 * i)));
    const logicalBytes = be(head, 32, 8);
    const mapOffset = be(head, 40, 8);
    const metaOffset = be(head, 48, 8);
    const hunkBytes = be(head, 56, 4);
    const unitBytes = be(head, 60, 4);
    const rawSha1 = [...head.subarray(64, 84)].map(b => b.toString(16).padStart(2, '0')).join('');
    if ([...head.subarray(104, 124)].some(Boolean)) {
      throw new Error('this CHD needs a parent CHD; use a standalone CHD or the .bin');
    }
    if (unitBytes !== FRAME || hunkBytes % FRAME) {
      throw new Error('this CHD is not a CD image');
    }
    const hunks = Math.ceil(logicalBytes / hunkBytes);

    // tracks, from the CHT2 (or older CHTR) metadata entries
    const tracks = [];
    for (let at = metaOffset; at;) {
      const entry = await readAt(at, 16);
      const tag = fourcc(entry.subarray(0, 4));
      const length = be(entry, 5, 3);
      if (tag === 'CHT2' || tag === 'CHTR') {
        const text = fourcc(await readAt(at + 16, length));
        const field = name => (text.match(new RegExp(name + ':(\\S+)')) || [])[1];
        tracks.push({type: field('TYPE'), subtype: field('SUBTYPE'),
                     frames: Number(field('FRAMES'))});
      }
      at = be(entry, 8, 8);
    }
    if (tracks.length !== 1 || tracks[0].type !== 'MODE2_RAW' || !tracks[0].frames) {
      throw new Error('this CHD is not a single raw Mode 2 data track, so it is not'
          + ' this game\'s disc');
    }

    // the block map (decompress_v5_map)
    let map;
    if (!codecs[0]) {
      const raw = await readAt(mapOffset, hunks * 4);
      map = Array.from({length: hunks}, (_, i) => ({
        type: COMPRESSION_NONE, offset: be(raw, 4 * i, 4) * hunkBytes, length: hunkBytes, crc: -1}));
    } else {
      const top = await readAt(mapOffset, 16);
      const mapBytes = be(top, 0, 4);
      const firstOffset = be(top, 4, 6);
      const mapCrc = be(top, 10, 2);
      const lengthBits = top[12], selfBits = top[13], parentBits = top[14];
      const bits = new Bits(await readAt(mapOffset + 16, mapBytes));
      const next = huffman(bits);
      const types = new Uint8Array(hunks);
      let last = 0;
      for (let i = 0, repeat = 0; i < hunks; i++) {
        if (repeat > 0) {
          types[i] = last;
          repeat--;
          continue;
        }
        const value = next();
        if (value === RLE_SMALL) {
          types[i] = last;
          repeat = 2 + next();
        } else if (value === RLE_LARGE) {
          types[i] = last;
          repeat = 2 + 16 + (next() << 4);
          repeat += next();
        } else {
          types[i] = last = value;
        }
      }
      map = new Array(hunks);
      const raw = new Uint8Array(hunks * 12);    // for the map's own CRC
      let offset = firstOffset, lastSelf = 0, lastParent = 0;
      for (let i = 0; i < hunks; i++) {
        let type = types[i];
        let at = offset, length = 0, crc = 0;
        if (type < 4) {
          length = bits.read(lengthBits);
          offset += length;
          crc = bits.read(16);
        } else if (type === COMPRESSION_NONE) {
          length = hunkBytes;
          offset += length;
          crc = bits.read(16);
        } else if (type === COMPRESSION_SELF) {
          at = lastSelf = bits.read(selfBits);
        } else if (type === COMPRESSION_PARENT) {
          at = lastParent = bits.read(parentBits);
        } else if (type === SELF_0 || type === SELF_1) {
          if (type === SELF_1) lastSelf++;
          type = COMPRESSION_SELF;
          at = lastSelf;
        } else if (type === PARENT_SELF) {
          type = COMPRESSION_PARENT;
          at = lastParent = Math.floor(i * hunkBytes / unitBytes);
        } else if (type === PARENT_0 || type === PARENT_1) {
          if (type === PARENT_1) lastParent += hunkBytes / unitBytes;
          type = COMPRESSION_PARENT;
          at = lastParent;
        }
        map[i] = {type, offset: at, length, crc};
        const row = raw.subarray(i * 12, i * 12 + 12);
        row[0] = type;
        for (let k = 0; k < 3; k++) row[1 + k] = Math.floor(length / 256 ** (2 - k)) & 0xff;
        for (let k = 0; k < 6; k++) row[4 + k] = Math.floor(at / 256 ** (5 - k)) & 0xff;
        row[10] = crc >>> 8;
        row[11] = crc & 0xff;
      }
      if (crc16(raw) !== mapCrc) throw new Error('this CHD\'s block map is damaged (CRC)');
    }
    return {codecs, hunkBytes, hunks, map, rawSha1, framesPerHunk: hunkBytes / FRAME,
            frames: tracks[0].frames, binBytes: tracks[0].frames * SECTOR};
  }

  /* CD-ROM P/Q parity (ECMA-130), as libchdr's ecc_generate: GF(2^8) with
   * x^8+x^4+x^3+x^2+1, the P and Q vectors over the sector from byte 12,
   * the Mode 2 header bytes counted as zero. */
  const ECC_LOW = new Uint8Array(256), ECC_HIGH = new Uint8Array(256);
  for (let i = 0; i < 256; i++) {
    ECC_LOW[i] = ((i << 1) ^ (i & 0x80 ? 0x11d : 0)) & 0xff;
    ECC_HIGH[ECC_LOW[i] ^ i] = i;
  }
  function eccRows(sector, count, components, offsetOf, at) {
    const source = offset => (sector[15] === 2 && offset < 4) ? 0 : sector[12 + offset];
    for (let row = 0; row < count; row++) {
      let val1 = 0, val2 = 0;
      for (let c = 0; c < components; c++) {
        const byte = source(offsetOf(row, c));
        val1 ^= byte;
        val2 ^= byte;
        val1 = ECC_LOW[val1];
      }
      val1 = ECC_HIGH[ECC_LOW[val1] ^ val2];
      val2 ^= val1;
      sector[at + row] = val1;
      sector[at + count + row] = val2;
    }
  }
  function eccGenerate(sector) {
    eccRows(sector, 86, 24, (b, c) => ((b >> 1) + 43 * c) * 2 + (b & 1), 0x81c);
    eccRows(sector, 52, 43, (b, c) => (((b >> 1) * 86 + 88 * c) % 2236) + (b & 1), 0x81c + 172);
  }

  /* One CD codec block: ECC flags, the sector data's compressed length, the
   * sector data, the subcode. Rebuilds the whole block (frames of sector +
   * subcode) so it can be checked against the map's CRC. */
  function cdBlock(chd, src, sectorCodec) {
    const frames = chd.framesPerHunk;
    const eccBytes = (frames + 7) >> 3;
    const sizeBytes = chd.hunkBytes < 65536 ? 2 : 3;
    const head = eccBytes + sizeBytes;
    const baseLength = be(src, eccBytes, sizeBytes);
    const sectors = sectorCodec === 'cdlz'
        ? LZMA.decode(src.subarray(head, head + baseLength), frames * SECTOR,
                      {lc: 3, lp: 0, pb: 2})
        : INFLATE.raw(src.subarray(head, head + baseLength), frames * SECTOR);
    const subcode = INFLATE.raw(src.subarray(head + baseLength), frames * SUBCODE);
    if (sectors.length !== frames * SECTOR || subcode.length !== frames * SUBCODE) {
      throw new Error('this CHD has a damaged block (wrong unpacked size)');
    }
    const block = new Uint8Array(chd.hunkBytes);
    for (let f = 0; f < frames; f++) {
      const sector = block.subarray(f * FRAME, f * FRAME + SECTOR);
      sector.set(sectors.subarray(f * SECTOR, (f + 1) * SECTOR));
      block.set(subcode.subarray(f * SUBCODE, (f + 1) * SUBCODE), f * FRAME + SECTOR);
      if (src[f >> 3] & (1 << (f & 7))) {
        sector.set(SYNC, 0);
        eccGenerate(sector);
      }
    }
    return block;
  }

  async function wholeBlock(chd, index, readAt, depth = 0) {
    const entry = chd.map[index];
    if (entry.type === COMPRESSION_SELF) {
      if (depth > 8 || entry.offset >= chd.hunks) throw new Error('this CHD has a damaged block map');
      return wholeBlock(chd, entry.offset, readAt, depth + 1);
    }
    if (entry.type === COMPRESSION_PARENT) {
      throw new Error('this CHD needs a parent CHD; use a standalone CHD or the .bin');
    }
    const src = await readAt(entry.offset, entry.length);
    let block;
    if (entry.type === COMPRESSION_NONE) {
      block = src;
    } else {
      const codec = chd.codecs[entry.type];
      if (codec !== 'cdlz' && codec !== 'cdzl') {
        throw new Error(`this CHD stores sectors this patch needs with the ${codec || '?'}`
            + ' codec, which the patcher cannot read; recompress it with chdman\'s'
            + ' defaults or use the .bin');
      }
      block = cdBlock(chd, src, codec);
    }
    if (entry.crc >= 0 && crc16(block) !== entry.crc) {
      throw new Error('this CHD has a damaged block (CRC)');
    }
    return block;
  }

  async function hunk(chd, index, readAt) {
    const block = await wholeBlock(chd, index, readAt);
    const out = new Uint8Array(chd.framesPerHunk * SECTOR);
    for (let f = 0; f < chd.framesPerHunk; f++) {
      out.set(block.subarray(f * FRAME, f * FRAME + SECTOR), f * SECTOR);
    }
    return out;
  }

  function hunksFor(chd, offset, n) {
    const perHunk = chd.framesPerHunk * SECTOR;
    const out = [];
    for (let i = Math.floor(offset / perHunk); i <= Math.floor((offset + n - 1) / perHunk); i++) {
      out.push(i);
    }
    return out;
  }

  /* The codec each block uses, for reporting: {codec name: block count}. */
  function codecUse(chd) {
    const use = {};
    for (const entry of chd.map) {
      const name = entry.type < 4 ? chd.codecs[entry.type]
          : ['', '', '', '', 'none', 'self', 'parent'][entry.type];
      use[name] = (use[name] || 0) + 1;
    }
    return use;
  }

  /* What a block-unpacking worker needs (structured-clonable). */
  function portable(chd) {
    const {codecs, hunkBytes, hunks, map, framesPerHunk} = chd;
    return {codecs, hunkBytes, hunks, map, framesPerHunk};
  }

  globalThis.CHD = {open, headerSha1, hunk, hunksFor, codecUse, portable, SECTOR};
})();
