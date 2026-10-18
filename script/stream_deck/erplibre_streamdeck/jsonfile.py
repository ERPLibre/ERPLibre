# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Atomic replacement of the JSON files the deck writes."""

import json
import os
import tempfile


def write_atomic(path, data, indent=2):
    """Write `data` as JSON to `path` through a temporary file in the
    same directory, flushed and fsynced, then os.replace: a reader sees
    the old file or the new one, never a truncated one. The directory is
    created when missing; the temporary file is removed on failure."""
    path = os.fspath(path)
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
        os.chmod(tmp, 0o666 & ~_umask())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _umask():
    """The process umask (read by setting it and restoring it)."""
    mask = os.umask(0)
    os.umask(mask)
    return mask
