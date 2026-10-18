# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Atomic replacement of the JSON files the deck writes."""

import json
import os
import tempfile


def _read_umask():
    """The process umask, read by setting it and restoring it: done once
    at import, since the pair is not atomic and a file another thread
    creates in between would get the wrong mode."""
    mask = os.umask(0)
    os.umask(mask)
    return mask


# The mode a new file gets is 0o666 minus this mask, as open() gives.
_UMASK = _read_umask()


def write_atomic(path, data, indent=2):
    """Write `data` as JSON to `path` through a temporary file in the
    same directory, flushed and fsynced, then os.replace: a reader sees
    the old file or the new one, never a truncated one. The directory is
    created when missing; the temporary file is removed on failure.
    A symbolic link is followed: the temporary file lives next to the
    real file and replaces it, so the link stays a link. An existing
    file keeps its permission bits; a new one gets 0o666 minus umask."""
    path = os.path.realpath(os.fspath(path))
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    text = json.dumps(data, indent=indent)
    fd, tmp = tempfile.mkstemp(
        prefix=".", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            mode = os.stat(path).st_mode & 0o7777
        except OSError:
            mode = 0o666 & ~_UMASK
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

