'use strict';
/* Scratch-directory lifecycle, shared by the page and the patch worker.
 *
 * The worker writes its output slots to OPFS under persona-patch-* names and
 * the page shows the final file as the download. A page that is still showing
 * that file holds a Web Lock named after the directory; a directory whose
 * lock is free belongs to a closed or crashed tab. The next page load or
 * patch run removes those, so a tab close that could not finish deleting the
 * file does not leave it on disk indefinitely.
 *
 * Without Web Locks, the fallback is the older one-day age rule. The age
 * check also protects the brief window between a lock request and its grant,
 * and any page still running an older build.
 */

(function () {
  const PREFIX = 'persona-patch-';
  const STALE_MS = 24 * 60 * 60 * 1000;
  const ORPHAN_MS = 10 * 60 * 1000;

  /* The timestamp leads the name so a directory can be aged without opening
   * it; the random suffix keeps two tabs apart. */
  function name(now) {
    const suffix = typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2);
    return PREFIX + now.toString(36) + '-' + suffix;
  }

  function stampOf(dirName) {
    return parseInt(dirName.slice(PREFIX.length).split('-')[0], 36);
  }

  async function cleanRoot(root, keep, current, locksOverride) {
    if (!root || typeof root.entries !== 'function') return;
    const locks = locksOverride !== undefined
        ? locksOverride
        : (typeof navigator !== 'undefined' && navigator.locks);
    const staleMs = locks ? ORPHAN_MS : STALE_MS;
    try {
      for await (const [entryName, handle] of root.entries()) {
        if (entryName === keep || entryName === current) continue;
        if (handle.kind !== 'directory' || !entryName.startsWith(PREFIX)) continue;
        const stamp = stampOf(entryName);
        if (!Number.isFinite(stamp) || Date.now() - stamp <= staleMs) continue;
        if (locks) {
          let free = false;
          try {
            await locks.request(entryName, {ifAvailable: true},
                                async lock => { free = !!lock; });
          } catch (err) {
            continue;
          }
          if (!free) continue;  // a page still shows this download
        }
        try { await root.removeEntry(entryName, {recursive: true}); } catch (err) {}
      }
    } catch (err) {}
  }

  async function clean(storageOverride, keep, current, locksOverride) {
    const storage = storageOverride ||
        (typeof navigator !== 'undefined' && navigator.storage);
    if (!storage || typeof storage.getDirectory !== 'function') return;
    try {
      const root = await storage.getDirectory();
      await cleanRoot(root, keep, current, locksOverride);
    } catch (err) {}
  }

  globalThis.ScratchSpace = {PREFIX, ORPHAN_MS, STALE_MS, name, clean, cleanRoot};
})();
