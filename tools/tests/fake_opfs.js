'use strict';
/* A tiny OPFS stand-in for the Node harness. The browser API is async and
 * backed by the real origin-private filesystem; this version backs the same
 * surface with ordinary files in a temp directory, which is enough to run
 * webpatcher/opfsfs.js under Node and catch Emscripten FS integration bugs.
 * It is never used by the page. */

const fs = require('fs');
const path = require('path');

class FakeSyncAccessHandle {
  constructor(filePath) {
    this.path = filePath;
    this.fd = fs.openSync(filePath, 'r+');
  }

  read(buffer, options = {}) {
    return fs.readSync(this.fd, buffer, 0, buffer.length, options.at || 0);
  }

  write(buffer, options = {}) {
    return fs.writeSync(this.fd, buffer, 0, buffer.length, options.at || 0);
  }

  truncate(size) { fs.ftruncateSync(this.fd, size); }
  flush() { fs.fsyncSync(this.fd); }
  getSize() { return fs.fstatSync(this.fd).size; }
  close() {
    if (this.fd !== null) {
      fs.closeSync(this.fd);
      this.fd = null;
    }
  }
}

class FakeFileHandle {
  constructor(filePath, name) {
    this.path = filePath;
    this.name = name;
  }

  get kind() { return 'file'; }

  async createSyncAccessHandle() {
    return new FakeSyncAccessHandle(this.path);
  }

  async getFile() {
    return new Blob([fs.readFileSync(this.path)]);
  }
}

class FakeDirHandle {
  constructor(dirPath) {
    this.path = dirPath;
  }

  get kind() { return 'directory'; }

  async getDirectoryHandle(name, options = {}) {
    const child = path.join(this.path, name);
    if (options.create) fs.mkdirSync(child, {recursive: true});
    return new FakeDirHandle(child);
  }

  async getFileHandle(name, options = {}) {
    const child = path.join(this.path, name);
    if (options.create && !fs.existsSync(child)) {
      fs.closeSync(fs.openSync(child, 'w'));
    } else if (!fs.existsSync(child)) {
      throw new Error('NotFoundError');
    }
    return new FakeFileHandle(child, name);
  }

  async removeEntry(name, options = {}) {
    fs.rmSync(path.join(this.path, name),
              {recursive: !!options.recursive, force: true});
  }

  async *entries() {
    for (const entry of fs.readdirSync(this.path, {withFileTypes: true})) {
      const child = path.join(this.path, entry.name);
      yield [entry.name, entry.isDirectory()
          ? new FakeDirHandle(child)
          : new FakeFileHandle(child, entry.name)];
    }
  }
}

module.exports = {FakeDirHandle};
