#!/usr/bin/env python3
"""Compile po/{lang}.po → locale/{lang}/LC_MESSAGES/streamdeck-tiler.mo.

Uses polib (`apt install python3-polib`). System gettext's `msgfmt` is
the alternative but not pre-installed on Debian 13's gettext-base.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import polib
except ImportError:
    sys.stderr.write(
        "polib missing — sudo apt install python3-polib\n")
    sys.exit(2)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    po_dir = root / "po"
    locale_dir = root / "locale"
    count = 0
    for po_path in sorted(po_dir.glob("*.po")):
        lang = po_path.stem
        if lang == "streamdeck-tiler":
            continue  # template
        dst = locale_dir / lang / "LC_MESSAGES" / "streamdeck-tiler.mo"
        dst.parent.mkdir(parents=True, exist_ok=True)
        po = polib.pofile(str(po_path))
        po.save_as_mofile(str(dst))
        print(f"compiled {lang}: {len(po)} entries -> {dst}")
        count += 1
    if count == 0:
        sys.stderr.write("no .po files found\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
