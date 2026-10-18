# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Accessibility page: font scale and labels on icon keys."""

from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin,
)
from erplibre_streamdeck.ui import colors, render
from erplibre_streamdeck.ui.render import (
    FONT_SCALE_DEFAULT, FONT_SCALE_STEP,
)


def _keys(geo):
    """A11Y page keys. Needs >= 4 cols and >= 2 rows, else None; the
    labels toggle exists from 5 cols."""
    if geo.cols < 4 or geo.rows < 2:
        return None
    keys = {
        "back": 0,
        "font_down": geo.cols + 1,
        "font_up": geo.cols + 2,
        "font_reset": geo.cols + 3,
    }
    if geo.cols >= 5:
        keys["labels_toggle"] = geo.cols + 4
    return keys


def _render(ctx):
    ak = ctx.keys
    if not ak:
        render.too_small(ctx)
        return
    style = ctx.style
    scale_lbl = f"SCALE\n{style.font_scale:.1f}x"
    labels_lbl = f"LABELS\n{'ON' if style.show_labels else 'OFF'}"
    # The insertion order is the paint order: on a deck where the scale
    # key (total_keys // 2) is also FONT+, the scale label wins.
    assignments = {
        ak["back"]: (colors.BACK, ctx.t("BACK")),
        ak["font_down"]: (colors.FONT_STEP, "FONT\n-"),
        ak["font_up"]: (colors.FONT_STEP, "FONT\n+"),
        ak["font_reset"]: (colors.FONT_RESET, ctx.t("RESET")),
        ctx.geo.total_keys // 2: (colors.EMPTY, scale_lbl),
    }
    if "labels_toggle" in ak:
        color = colors.MUTE_OFF if style.show_labels else colors.BT_OFF
        assignments[ak["labels_toggle"]] = (color, labels_lbl)
    for key in range(ctx.geo.total_keys):
        if key in assignments:
            color, label = assignments[key]
            ctx.set_key(key, color, label)
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _handle(ctx, key):
    ak = ctx.keys
    if not ak:
        ctx.home()
        return
    if key == ak["back"]:
        ctx.home()
        return
    style = ctx.style
    if key == ak["font_down"]:
        style.set_font_scale(style.font_scale - FONT_SCALE_STEP, ctx.settings)
    elif key == ak["font_up"]:
        style.set_font_scale(style.font_scale + FONT_SCALE_STEP, ctx.settings)
    elif key == ak["font_reset"]:
        style.set_font_scale(FONT_SCALE_DEFAULT, ctx.settings)
    elif key == ak.get("labels_toggle"):
        style.toggle_labels(ctx.settings)
    else:
        return
    ctx.render()


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("a11y", _keys, _render, _handle)],
    home_button=HomeButton(
        60,
        face=lambda ctx: KeyFace(colors.A11Y_TITLE, "A11Y", icon="a11y"),
        press=lambda ctx: ctx.goto("a11y"),
    ),
)
