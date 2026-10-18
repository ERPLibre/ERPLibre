# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The one client of the ERPLibre Home extension's D-Bus interface.

call() runs `gdbus call` and returns a Reply; it never raises: a
missing gdbus, a timeout or undecodable output give returncode None.
The callers read the reply the way their method answers."""

import subprocess
from dataclasses import dataclass

DEST = "org.gnome.Shell"
PATH = "/org/gnome/Shell/Extensions/ERPLibreHome"
IFACE = "org.gnome.Shell.Extensions.ERPLibreHome"


def parse_string_tuple(output):
    """The string of a gdbus answer of the form ('...',), or None.

    GVariant single-quoted strings escape only backslash and single
    quote; double quotes from JSON content pass through."""
    s = output.strip()
    if not (s.startswith("('") and s.endswith("',)")):
        return None
    inner = s[2:-3]
    # \x00 holds the place of \\ so it is not unescaped twice.
    return (
        inner.replace("\\\\", "\x00")
        .replace("\\'", "'")
        .replace("\x00", "\\")
    )


@dataclass(frozen=True)
class Reply:
    returncode: int | None
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self):
        return self.returncode == 0

    @property
    def true(self):
        """Exit 0 and a `true` in the answer, as `(true,)`."""
        return self.ok and "true" in self.stdout.lower()

    @property
    def string(self):
        return parse_string_tuple(self.stdout) if self.ok else None


def call(method, *args, timeout=3):
    argv = [
        "gdbus", "call", "--session",
        "--dest", DEST,
        "--object-path", PATH,
        "--method", f"{IFACE}.{method}",
    ] + [str(a) for a in args]
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return Reply(None, "", str(exc))
    return Reply(done.returncode, done.stdout or "", done.stderr or "")


def available():
    """The extension is loaded: introspection lists TileWindow."""
    try:
        done = subprocess.run(
            [
                "gdbus", "introspect", "--session",
                "--dest", DEST,
                "--object-path", PATH,
            ],
            capture_output=True, text=True, timeout=3,
        )
        return "TileWindow" in done.stdout
    except Exception:
        return False
