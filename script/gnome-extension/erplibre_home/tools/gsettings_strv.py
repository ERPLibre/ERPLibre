# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Read and write the string arrays ``gsettings`` prints and accepts.

Shared by the tools that edit ``org.gnome.shell`` lists. Standard library
only: the tools run before any venv exists.
"""

from __future__ import annotations

import ast


def parse_strv(text: str) -> list[str]:
    """Parse the string array ``gsettings get`` prints.

    ``@as []`` is the empty array; any other value is a list literal of
    single-quoted strings, which Python reads as is. Raises ValueError
    (or SyntaxError) on anything that is not such a list.
    """
    text = text.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    if not text:
        return []
    value = ast.literal_eval(text)
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"not a list: {text}")
    return [str(item) for item in value]


def format_strv(items: list[str]) -> str:
    """The inverse of parse_strv, as ``gsettings set`` accepts it."""
    return "[" + ", ".join(repr(item) for item in items) + "]"
