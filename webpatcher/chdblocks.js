'use strict';
/* Unpack a list of CHD blocks for the patch worker, so several of these run
 * side by side on a multi-core machine (LZMA is the slow part of building a
 * PPF from a CHD).
 *
 * Message in:  {file, chd: CHD.portable(...), indices}
 * Message out: {blocks: [[index, Uint8Array], ...]}  (buffers transferred)
 *              {error}
 */

importScripts('lzma.js', 'inflate.js', 'chd.js');

self.onmessage = async ({data}) => {
  try {
    const {file, chd, indices} = data;
    const readAt = async (offset, length) =>
        new Uint8Array(await file.slice(offset, offset + length).arrayBuffer());
    const blocks = [];
    for (const index of indices) blocks.push([index, await CHD.hunk(chd, index, readAt)]);
    postMessage({blocks}, blocks.map(([, bytes]) => bytes.buffer));
  } catch (err) {
    postMessage({error: String((err && err.message) || err)});
  }
};
