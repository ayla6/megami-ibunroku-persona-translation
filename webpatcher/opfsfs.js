'use strict';
/* Optional writable scratch space for the patch chain, backed by OPFS.
 *
 * The 700 MB disc does not have to sit in memory while the chain runs: both
 * output slots are real files in the Origin Private File System, written
 * through FileSystemSyncAccessHandle. xdelta still sees an ordinary POSIX
 * filesystem; only the bytes live on disk instead of in a Uint8Array.
 *
 * MEMFS is the default. The page opens this space only when the user picks
 * "I don't have enough RAM mode" (or the page turns it on automatically for
 * a device that is likely short on memory); worker.js then falls back to
 * MEMFS when OPFS or a sync access handle is unavailable (older browsers,
 * private modes, a denied or exhausted quota), so the patcher still works
 * everywhere it did before.
 *
 * Directory names and the orphan cleanup rule live in scratch.js, which the
 * page also loads so it can sweep on every visit.
 *
 * The public surface is deliberately small:
 *   OPFSWorkspace.open(names, storage?, keep?, dirName?, locks?)
 *                                              -> workspace | null
 *   OPFSWorkspace.mount(FS, ws, dir) -> mounts ws.files at `dir`
 *   OPFSWorkspace.finish(ws, path)   -> File (a Blob)      (async)
 *   OPFSWorkspace.close(ws)          -> closes handles     (async)
 *
 * finish() keeps the directory that backs the returned File: Chrome resolves
 * a File lazily, so removing its entry would break the download link. close()
 * then only closes handles; the page removes the directory when the result is
 * replaced or the page goes away. Without finish(), close() removes the whole
 * scratch directory.
 */

(function () {
  const FS = Module.FS;

  const DIR_MODE = 0o40777;   // S_IFDIR | 0777
  const FILE_MODE = 0o100777; // S_IFREG | 0777
  const EPERM = 63, ENOENT = 44, EIO = 29, EINVAL = 28, ENOSPC = 51;

  function createNode(parent, name, mode) {
    const node = FS.createNode(parent, name, mode);
    node.mode = mode;
    node.node_ops = nodeOps;
    node.stream_ops = streamOps;
    node.atime = node.mtime = node.ctime = Date.now();
    node.contents = {};
    node.size = 0;
    if (FS.isDir(mode)) node.size = 4096;
    if (parent) parent.contents[name] = node;
    return node;
  }

  /* Map browser storage failures onto the errno xdelta understands. A quota
   * error is the important one: it is the difference between "your disc is
   * wrong" and "there is no room for the scratch file". */
  function fsError(err) {
    const name = err && err.name;
    if (name === 'QuotaExceededError' || name === 'NS_ERROR_DOM_QUOTA_REACHED') {
      return new FS.ErrnoError(ENOSPC);
    }
    return new FS.ErrnoError(EIO);
  }

  const nodeOps = {
    getattr(node) {
      const size = FS.isDir(node.mode) ? 4096 : node.size;
      return {
        dev: 1, ino: node.id, mode: node.mode, nlink: 1, uid: 0, gid: 0,
        rdev: 0, size, atime: new Date(node.atime), mtime: new Date(node.mtime),
        ctime: new Date(node.ctime), blksize: 4096,
        blocks: Math.ceil(size / 4096),
      };
    },
    setattr(node, attr) {
      for (const key of ['mode', 'atime', 'mtime', 'ctime']) {
        if (attr[key] != null) node[key] = attr[key];
      }
      if (attr.size != null && FS.isFile(node.mode)) {
        try {
          node.handle.truncate(attr.size);
        } catch (err) {
          throw fsError(err);
        }
        node.size = attr.size;
      }
    },
    lookup(parent, name) {
      if (!parent.contents[name]) throw new FS.ErrnoError(ENOENT);
      return parent.contents[name];
    },
    /* The mount pre-creates both output slots, because a sync access handle
     * can only be obtained asynchronously and mknod is synchronous. xdelta
     * opens the paths it was given, so it never needs a new name here. */
    mknod() { throw new FS.ErrnoError(EPERM); },
    rename() { throw new FS.ErrnoError(EPERM); },
    unlink() { throw new FS.ErrnoError(EPERM); },
    rmdir() { throw new FS.ErrnoError(EPERM); },
    readdir(node) { return ['.', '..', ...Object.keys(node.contents)]; },
    symlink() { throw new FS.ErrnoError(EPERM); },
  };

  const streamOps = {
    read(stream, buffer, offset, length, position) {
      const node = stream.node;
      if (position >= node.size) return 0;
      const want = Math.min(length, node.size - position);
      let done = 0;
      while (done < want) {
        let got;
        try {
          got = node.handle.read(
              buffer.subarray(offset + done, offset + want), {at: position + done});
        } catch (err) {
          throw fsError(err);
        }
        if (!got) break;
        done += got;
      }
      return done;
    },
    write(stream, buffer, offset, length, position, canOwn) {
      if (!length) return 0;
      const node = stream.node;
      const data = buffer.subarray(offset, offset + length);
      let done = 0;
      try {
        while (done < length) {
          const wrote = node.handle.write(data.subarray(done), {at: position + done});
          if (!wrote) throw new Error('short OPFS write');
          done += wrote;
        }
      } catch (err) {
        throw fsError(err);
      }
      node.size = Math.max(node.size, position + length);
      node.mtime = node.ctime = Date.now();
      return length;
    },
    llseek(stream, offset, whence) {
      let position = offset;
      if (whence === 1) position += stream.position;
      else if (whence === 2) position += stream.node.size;
      if (position < 0) throw new FS.ErrnoError(EINVAL);
      return position;
    },
    fsync(stream) {
      try { stream.node.handle.flush(); } catch (err) {}
      return 0;
    },
    /* Keep the sync access handle open: the two slots are reused by later
     * steps, and the final one is still needed for getFile(). */
    close() {},
  };

  const OPFSFS = {
    mount(mount) {
      const root = createNode(null, '/', DIR_MODE);
      for (const file of mount.opts.files || []) {
        const node = createNode(root, file.name, FILE_MODE);
        node.handle = file.handle;
        node.fileHandle = file.fileHandle;
        node.size = file.size || 0;
      }
      return root;
    },
  };

  async function open(names, storageOverride, keep, wantedName, locksOverride) {
    const storage = storageOverride ||
        (typeof navigator !== 'undefined' && navigator.storage);
    if (!storage || typeof storage.getDirectory !== 'function') return null;
    let root = null;
    let dirName = null;
    let files = [];
    try {
      root = await storage.getDirectory();
      dirName = typeof wantedName === 'string'
              && wantedName.startsWith(ScratchSpace.PREFIX)
          ? wantedName
          : ScratchSpace.name(Date.now());
      await ScratchSpace.cleanRoot(root, keep, dirName, locksOverride);
      const dir = await root.getDirectoryHandle(dirName, {create: true});
      for (const name of names) {
        const fileHandle = await dir.getFileHandle(name, {create: true});
        const handle = await fileHandle.createSyncAccessHandle();
        await handle.truncate(0);
        files.push({name, handle, fileHandle, size: 0});
      }
      return {root, dir, dirName, files, keep: false};
    } catch (err) {
      for (const file of files) {
        try { file.handle.close(); } catch (closeErr) {}
      }
      if (root && dirName) {
        try { await root.removeEntry(dirName, {recursive: true}); } catch (rmErr) {}
      }
      return null;
    }
  }

  function mount(fs, workspace, path) {
    fs.mkdir(path);
    fs.mount(OPFSFS, {files: workspace.files}, path);
  }

  /* Return the final output as an OPFS-backed File and keep that one file.
   * Deleting it would invalidate the File (Chrome resolves it lazily), so
   * the page owns the directory until the download link is replaced. */
  async function finish(workspace, path) {
    const name = path.slice(path.lastIndexOf('/') + 1);
    const file = workspace.files.find(entry => entry.name === name);
    if (!file) throw new Error('missing scratch file ' + name);
    await file.handle.flush();
    const blob = await file.fileHandle.getFile();

    // The other slot is dead weight once the chain is done.
    for (const entry of workspace.files) {
      if (entry === file) continue;
      try { entry.handle.close(); } catch (err) {}
      try { await workspace.dir.removeEntry(entry.name); } catch (err) {}
    }
    try { file.handle.close(); } catch (err) {}
    workspace.keep = true;
    return blob;
  }

  async function close(workspace) {
    for (const file of workspace.files) {
      try { file.handle.close(); } catch (err) {}
    }
    if (!workspace.keep && workspace.root && workspace.dirName) {
      try {
        await workspace.root.removeEntry(workspace.dirName, {recursive: true});
      } catch (err) {}
    }
  }

  FS.filesystems = FS.filesystems || {};
  FS.filesystems.OPFSFS = OPFSFS;
  globalThis.OPFSWorkspace = {open, mount, finish, close};
})();
