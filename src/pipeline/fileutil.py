"""Filesystem helpers shared by the disc builders.

A release image is ~700 MB and only a small fraction of it changes from one
variant to the next. Copying the whole file for every variant is the largest
single cost of a release build on a slow disk, so the builders ask the
filesystem to share extents (reflink) when it can and fall back to a normal
byte copy when it cannot (tmpfs, ext4 without reflink, other platforms).
"""
import errno
import fcntl
import shutil
import sys


# FICLONE from linux/fs.h: _IOW(0x94, 9, int).
FICLONE = 0x40049409
_UNSUPPORTED = (errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTTY,
                errno.EINVAL, errno.ENOSYS, errno.ENOTSUP)


def reflink(src, dst):
    """Create `dst` sharing `src`'s extents; False when the filesystem can't."""
    if not sys.platform.startswith('linux'):
        return False
    try:
        with open(src, 'rb') as source, open(dst, 'wb') as target:
            fcntl.ioctl(target.fileno(), FICLONE, source.fileno())
        return True
    except OSError as error:
        if error.errno in _UNSUPPORTED:
            return False
        raise


def clone_file(src, dst):
    """Copy `src` to `dst`, sharing extents when the filesystem supports it.

    A reflink copy is O(1), and - the part that matters here - a later write
    to `dst` copies only the sectors it touches. The caller may therefore
    clone a whole disc and then rewrite just the files that differ, which is
    exactly what a variant image needs.
    """
    if not reflink(src, dst):
        shutil.copyfile(src, dst)
