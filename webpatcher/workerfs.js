'use strict';
/* Minimal read-only WORKERFS for the vendored xdelta3 runtime.
 *
 * The wasm build exposes Emscripten's FS but not its workerfs library, so
 * FS.filesystems.WORKERFS is undefined and mounting the selected disc fails.
 * This is the same filesystem Emscripten ships (MIT, adapted from
 * src/lib/libworkerfs.js): files are read on demand through FileReaderSync,
 * so the 700 MB disc never has to be copied into the worker heap.
 *
 * If a future vendor rebuild does include workerfs, this leaves it alone.
 */
(function () {
  const FS = Module.FS;
  if (FS.filesystems && FS.filesystems.WORKERFS) return;

  const DIR_MODE = 0o40777;   // S_IFDIR | 0777
  const FILE_MODE = 0o100777; // S_IFREG | 0777
  const EPERM = 63, ENOENT = 44, EIO = 29, EINVAL = 28;

  let reader = null;
  const readAsArrayBuffer = blob =>
      new Uint8Array((reader ||= new FileReaderSync()).readAsArrayBuffer(blob));

  function createNode(parent, name, mode, contents) {
    const node = FS.createNode(parent, name, mode);
    node.mode = mode;
    node.node_ops = nodeOps;
    node.stream_ops = streamOps;
    node.atime = node.mtime = node.ctime =
        (contents && contents.lastModified) || Date.now();
    if (mode === FILE_MODE) {
      node.size = contents.size;
      node.contents = contents;
    } else {
      node.size = 4096;
      node.contents = {};
    }
    if (parent) parent.contents[name] = node;
    return node;
  }

  const nodeOps = {
    getattr(node) {
      return {
        dev: 1, ino: node.id, mode: node.mode, nlink: 1, uid: 0, gid: 0,
        rdev: 0, size: node.size, atime: new Date(node.atime),
        mtime: new Date(node.mtime), ctime: new Date(node.ctime),
        blksize: 4096, blocks: Math.ceil(node.size / 4096),
      };
    },
    setattr(node, attr) {
      for (const key of ['mode', 'atime', 'mtime', 'ctime']) {
        if (attr[key] != null) node[key] = attr[key];
      }
    },
    lookup() { throw new FS.ErrnoError(ENOENT); },
    mknod() { throw new FS.ErrnoError(EPERM); },
    rename() { throw new FS.ErrnoError(EPERM); },
    unlink() { throw new FS.ErrnoError(EPERM); },
    rmdir() { throw new FS.ErrnoError(EPERM); },
    readdir(node) { return ['.', '..', ...Object.keys(node.contents)]; },
    symlink() { throw new FS.ErrnoError(EPERM); },
  };

  const streamOps = {
    read(stream, buffer, offset, length, position) {
      if (position >= stream.node.size) return 0;
      const chunk = stream.node.contents.slice(position, position + length);
      const bytes = readAsArrayBuffer(chunk);
      buffer.set(bytes, offset);
      return bytes.length;
    },
    write() { throw new FS.ErrnoError(EIO); },
    llseek(stream, offset, whence) {
      let position = offset;
      if (whence === 1) position += stream.position;
      else if (whence === 2) position += stream.node.size;
      if (position < 0) throw new FS.ErrnoError(EINVAL);
      return position;
    },
  };

  const WORKERFS = {
    mount(mount) {
      const root = createNode(null, '/', DIR_MODE);
      const parents = new Map();
      const ensureParent = path => {
        const parts = path.split('/');
        let parent = root;
        for (let i = 0; i < parts.length - 1; i++) {
          const key = parts.slice(0, i + 1).join('/');
          if (!parents.has(key)) {
            parents.set(key, createNode(parent, parts[i], DIR_MODE));
          }
          parent = parents.get(key);
        }
        return parent;
      };
      const add = (path, contents) => {
        createNode(ensureParent(path), path.split('/').pop(), FILE_MODE, contents);
      };
      for (const file of mount.opts.files || []) add(file.name, file);
      for (const blob of mount.opts.blobs || []) add(blob.name, blob.data);
      return root;
    },
  };

  FS.filesystems = FS.filesystems || {};
  FS.filesystems.WORKERFS = WORKERFS;
})();
