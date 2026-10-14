#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Mark an extension enabled for the next login through gsettings.

Under Wayland, GNOME Shell scans the extensions directory only at login,
so ``gnome-extensions enable`` fails for an extension the running Shell
has not seen yet. The Shell reads ``org.gnome.shell enabled-extensions``
at login, so writing that key makes the extension load then.

``disabled-extensions`` wins over ``enabled-extensions``: the uuid is
removed from it as well. Every other entry and the order of both lists
are kept, and the uuid is never added twice.
Exits 0 once the settings are written, 1 when gsettings fails.
Uses the standard library only: it runs without any venv.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gsettings_strv import format_strv, parse_strv  # noqa: E402

SCHEMA = "org.gnome.shell"


def plan(enabled: list[str], disabled: list[str], uuid: str):
    """Return the new (enabled, disabled) lists for ``uuid``."""
    new_enabled = enabled if uuid in enabled else enabled + [uuid]
    return new_enabled, [i for i in disabled if i != uuid]


def gsettings(*args: str) -> str:
    return subprocess.run(
        ["gsettings", *args], check=True, capture_output=True, text=True
    ).stdout


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} UUID", file=sys.stderr)
        return 2
    uuid = argv[1]
    try:
        enabled = parse_strv(gsettings("get", SCHEMA, "enabled-extensions"))
        disabled = parse_strv(gsettings("get", SCHEMA, "disabled-extensions"))
        new_enabled, new_disabled = plan(enabled, disabled, uuid)
        # disabled first: a failure of the second write then leaves the
        # uuid in neither list, never "disabled" while enabled was written.
        if new_disabled != disabled:
            gsettings(
                "set", SCHEMA, "disabled-extensions", format_strv(new_disabled)
            )
        if new_enabled != enabled:
            gsettings(
                "set", SCHEMA, "enabled-extensions", format_strv(new_enabled)
            )
    except (
        OSError,
        subprocess.CalledProcessError,
        ValueError,
        SyntaxError,
    ) as e:
        detail = getattr(e, "stderr", None) or e
        print(
            f"gsettings failed, extension not enabled: {detail}",
            file=sys.stderr,
        )
        return 1
    print(f"{uuid} enabled for the next login (log out / log in to load it)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
