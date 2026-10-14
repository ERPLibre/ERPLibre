#!/usr/bin/env python3
"""Extract YouTube URLs from every open tab of every running Firefox
profile.

Reads `sessionstore-backups/recovery.jsonlz4` under each profile and
prints a JSON array of `{"url": str, "title": str}` to stdout. Used
by the Stream Deck Tiler GNOME extension's prefs Film page to bulk
import the user's currently-open YouTube videos.

Requires `python3-lz4` (Debian / Ubuntu) for the mozLz4 decompression.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys


YT_RE = re.compile(
    r"(?:youtube\.com/watch\?|youtu\.be/|youtube\.com/shorts/|"
    r"music\.youtube\.com/watch\?)",
    re.IGNORECASE,
)


def _find_recovery_files() -> list[str]:
    base = os.path.expanduser("~/.mozilla/firefox")
    paths = []
    paths += glob.glob(
        os.path.join(base, "*", "sessionstore-backups",
                     "recovery.jsonlz4"))
    paths += glob.glob(
        os.path.join(base, "*", "sessionstore-backups",
                     "recovery.baklz4"))
    # Fallback: live `sessionstore.jsonlz4` (only present after a
    # clean shutdown but worth checking).
    paths += glob.glob(
        os.path.join(base, "*", "sessionstore.jsonlz4"))
    return paths


def _decompress_mozlz4(path: str) -> bytes:
    import lz4.block  # type: ignore
    with open(path, "rb") as f:
        magic = f.read(8)
        if magic != b"mozLz40\x00":
            raise ValueError(f"{path}: not a mozLz4 file")
        return lz4.block.decompress(f.read())


def _walk_session(session: dict) -> list[dict]:
    out = []
    for win in session.get("windows", []) or []:
        for tab in win.get("tabs", []) or []:
            entries = tab.get("entries", []) or []
            if not entries:
                continue
            # The current entry is at `index - 1` (1-based).
            idx = max(0, (tab.get("index", 1) or 1) - 1)
            entry = entries[min(idx, len(entries) - 1)]
            url = entry.get("url", "") or ""
            title = entry.get("title", "") or ""
            if not url or not YT_RE.search(url):
                continue
            out.append({"url": url, "title": title})
    return out


def main() -> int:
    try:
        import lz4.block  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "python3-lz4 not installed — sudo apt install python3-lz4\n")
        print("[]")
        return 2

    seen_urls = set()
    out = []
    for path in _find_recovery_files():
        try:
            data = _decompress_mozlz4(path)
            session = json.loads(data)
        except Exception as e:
            sys.stderr.write(f"skip {path}: {e}\n")
            continue
        for entry in _walk_session(session):
            if entry["url"] in seen_urls:
                continue
            seen_urls.add(entry["url"])
            out.append(entry)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
