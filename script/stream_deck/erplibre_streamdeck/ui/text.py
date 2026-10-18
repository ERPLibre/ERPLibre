# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Cutting free text into the cells of a deck."""


def chunk_text_for_cells(text, num_cells, per_cell=12):
    """Split `text` into up to `num_cells` chunks of ~`per_cell` chars.

    Breaks at word boundaries when a space is available close to the
    target length so reading flows from one cell to the next.
    """
    text = (text or "").strip()
    if not text or num_cells <= 0:
        return []
    chunks = []
    remaining = text
    for _ in range(num_cells):
        if not remaining:
            break
        if len(remaining) <= per_cell:
            chunks.append(remaining)
            remaining = ""
            break
        cut = remaining.rfind(" ", 0, per_cell + 2)
        if cut < per_cell // 2:
            cut = per_cell
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return chunks


def wrap_chunk(text, line_chars=6):
    """Insert a newline near `line_chars` so set_key renders 2 lines
    instead of overflowing a narrow key."""
    text = (text or "").strip()
    if len(text) <= line_chars:
        return text
    cut = text.rfind(" ", 0, line_chars + 2)
    if cut < line_chars // 2:
        cut = line_chars
    return f"{text[:cut].rstrip()}\n{text[cut:].lstrip()}"


def wrap_button_label(text, max_chars=8, max_lines=2):
    """Wrap `text` for a deck button with up to `max_lines` lines of
    `max_chars` glyphs each. Breaks at spaces when possible, hard-
    breaks long words, and appends a trailing ellipsis when the
    label still overflows."""
    text = (text or "").strip()
    if not text:
        return ""
    lines = []
    rest = text
    while rest and len(lines) < max_lines:
        if len(rest) <= max_chars:
            lines.append(rest)
            rest = ""
            break
        cut = rest.rfind(" ", 0, max_chars + 1)
        if cut < 1:
            cut = max_chars
        lines.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        last = lines[-1]
        room = max_chars - 1
        lines[-1] = (last[:room] if len(last) >= room else last) + "…"
    return "\n".join(lines)
