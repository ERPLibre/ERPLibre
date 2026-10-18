# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Window layouts: three slots saved from and applied to the extension
(ListWindows / ApplyLayout), stored in layouts.json."""

import json
import os
import re
from datetime import datetime

from erplibre_streamdeck import paths
from erplibre_streamdeck.plugin import (
    PLUGIN_API, Fixture, HomeButton, KeyFace, Page, Plugin,
)
from erplibre_streamdeck.ui import colors, render

NUM_LAYOUT_SLOTS = 3


def _layouts_load():
    try:
        with open(paths.LAYOUTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"slots": {}}


def _layouts_save(data):
    os.makedirs(paths.CONFIG_DIR, exist_ok=True)
    with open(paths.LAYOUTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _list_windows_dbus(ctx):
    """Query the extension for all live windows. Returns list of dicts."""
    try:
        r = ctx.dbus.call("ListWindows", timeout=3)
        if not r.ok:
            ctx.log(f"ListWindows dbus: {r.stderr}")
            return []
        payload = r.string
        return json.loads(payload) if payload else []
    except Exception as e:
        ctx.log(f"ListWindows error: {e}")
        return []


def _apply_layout_dbus(ctx, windows):
    """Apply a list of window records via D-Bus. Returns matched count."""
    try:
        payload = json.dumps(windows)
        r = ctx.dbus.call("ApplyLayout", payload, timeout=10)
        if not r.ok:
            ctx.log(f"ApplyLayout dbus: {r.stderr}")
            return 0
        m = re.search(r"\((\d+),\)", r.stdout.strip())
        return int(m.group(1)) if m else 0
    except Exception as e:
        ctx.log(f"ApplyLayout error: {e}")
        return 0


def _save_layout_slot(ctx, slot_id):
    windows = _list_windows_dbus(ctx)
    if not windows:
        return False
    data = _layouts_load()
    data.setdefault("slots", {})[str(slot_id)] = {
        "saved_at": datetime.now().strftime("%H:%M"),
        "count": len(windows),
        "windows": windows,
    }
    _layouts_save(data)
    return True


def _load_layout_slot(ctx, slot_id):
    data = _layouts_load()
    slot = data.get("slots", {}).get(str(slot_id))
    if not slot:
        return False
    matched = _apply_layout_dbus(ctx, slot.get("windows") or [])
    return matched > 0


def _delete_layout_slot(slot_id):
    data = _layouts_load()
    slots = data.get("slots", {})
    if str(slot_id) not in slots:
        return False
    del slots[str(slot_id)]
    _layouts_save(data)
    return True


def _draw_layout_preview(draw, w, h, windows, slot_num=None):
    """Render a thumbnail of saved layout windows on a button-sized canvas.
    Bounding box is computed from the windows themselves to keep the
    preview readable even when only a sub-region of the screen is used."""
    if not windows:
        return
    margin = 2
    cw = max(1, w - 2 * margin)
    ch = max(1, h - 2 * margin)
    xs = [win.get("x", 0) for win in windows]
    ys = [win.get("y", 0) for win in windows]
    xs2 = [win.get("x", 0) + win.get("w", 0) for win in windows]
    ys2 = [win.get("y", 0) + win.get("h", 0) for win in windows]
    bx0, by0 = min(xs), min(ys)
    bx1, by1 = max(xs2), max(ys2)
    bw = max(1, bx1 - bx0)
    bh = max(1, by1 - by0)
    scale = min(cw / bw, ch / bh)
    sw = bw * scale
    sh = bh * scale
    ox = margin + (cw - sw) / 2
    oy = margin + (ch - sh) / 2
    for win in sorted(windows, key=lambda v: v.get("stacking", 0)):
        x = ox + (win.get("x", 0) - bx0) * scale
        y = oy + (win.get("y", 0) - by0) * scale
        rw = max(2, win.get("w", 0) * scale)
        rh = max(2, win.get("h", 0) * scale)
        draw.rectangle(
            (x, y, x + rw, y + rh),
            outline=(220, 220, 220), width=1,
            fill=(60, 90, 130),
        )
    if slot_num is not None:
        font = render.load_label_font(14)
        draw.text((3, 1), str(slot_num), fill=(255, 220, 0), font=font)


def _keys(geo):
    """Layout page keys: back at 0, then SAVE / LOAD / DELETE rows of
    three slots. Needs >= 4 cols and >= 3 rows, else None; the DELETE
    row needs a fourth row."""
    if geo.cols < 4 or geo.rows < 3:
        return None
    c = geo.cols
    return {
        "back": 0,
        "save": [c + 1 + i for i in range(NUM_LAYOUT_SLOTS)],
        "load": [2 * c + 1 + i for i in range(NUM_LAYOUT_SLOTS)],
        "delete": (
            [3 * c + 1 + i for i in range(NUM_LAYOUT_SLOTS)]
            if geo.rows >= 4 else []
        ),
    }


def _render_layout(ctx):
    lk = ctx.keys
    if not lk:
        render.too_small(ctx)
        return

    data = _layouts_load()
    slots = data.get("slots", {})
    # Each entry: (color, label, extra_draw_or_None)
    assignments = {lk["back"]: (colors.BACK, ctx.t("BACK"), None)}
    for i, save_key in enumerate(lk["save"]):
        assignments[save_key] = (
            colors.SAVE, f"{ctx.t('SAVE')}\n{i + 1}", None)
    for i, load_key in enumerate(lk["load"]):
        slot = slots.get(str(i + 1))
        if slot:
            windows = slot.get("windows") or []
            slot_num = i + 1

            def _make_preview(_windows, _num):
                return lambda d, w, h: _draw_layout_preview(
                    d, w, h, _windows, slot_num=_num,
                )

            assignments[load_key] = (
                colors.LOAD_FILLED, "",
                _make_preview(windows, slot_num),
            )
        else:
            assignments[load_key] = (
                colors.LOAD_EMPTY, f"LOAD {i + 1}\n{ctx.t('EMPTY')}", None,
            )
    for i, del_key in enumerate(lk["delete"]):
        if str(i + 1) in slots:
            assignments[del_key] = (colors.CANCEL, f"DEL {i + 1}", None)
        else:
            assignments[del_key] = (colors.EMPTY, "", None)
    for key in range(ctx.geo.total_keys):
        if key in assignments:
            color, label, extra = assignments[key]
            ctx.set_key(key, color, label, extra_draw=extra)
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _handle_layout(ctx, key):
    lk = ctx.keys
    if not lk:
        ctx.home()
        return
    if key == lk["back"]:
        ctx.home()
        return
    if key in lk["save"]:
        slot = lk["save"].index(key) + 1
        if _save_layout_slot(ctx, slot):
            ctx.flash(True)
        else:
            ctx.flash(False, f"layout save slot {slot} failed")
        ctx.render()
        return
    if key in lk["load"]:
        slot = lk["load"].index(key) + 1
        if _load_layout_slot(ctx, slot):
            ctx.flash(True)
        else:
            ctx.flash(False, f"layout load slot {slot} failed")
        ctx.render()
        return
    if key in lk["delete"]:
        slot = lk["delete"].index(key) + 1
        if str(slot) not in _layouts_load().get("slots", {}):
            return  # empty slot: no-op
        ctx.state().delete_pending = slot
        ctx.goto("layout_delete_confirm")


def _render_confirm(ctx):
    slot = ctx.state().delete_pending or "?"
    total = ctx.geo.total_keys
    mid_key = total // 2
    for key in range(total):
        if key == 0:
            ctx.set_key(key, colors.CANCEL, ctx.t("CANCEL"))
        elif key == total - 1:
            ctx.set_key(key, colors.CONFIRM, ctx.t("OK"))
        elif key == mid_key - 1 and ctx.geo.cols >= 3:
            ctx.set_key(key, colors.EMPTY, ctx.t("DELETE"))
        elif key == mid_key and ctx.geo.cols >= 3:
            ctx.set_key(key, colors.EMPTY, f"SLOT\n{slot}?")
        elif key == mid_key:
            ctx.set_key(key, colors.EMPTY, f"DEL\n{slot}?")
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _handle_confirm(ctx, key):
    st = ctx.state()
    if key == 0:
        # Cancel
        st.delete_pending = None
        ctx.goto("layout")
        return
    if key == ctx.geo.total_keys - 1:
        # Confirm
        slot = st.delete_pending
        ok = _delete_layout_slot(slot) if slot else False
        st.delete_pending = None
        if ok:
            ctx.flash(True)
        else:
            ctx.flash(False, f"layout delete slot {slot} failed")
        ctx.goto("layout")
    # Other keys ignored (force explicit choice)


def _shortcut_place(geo, home_keys):
    """The three slot shortcuts: last row, starting under the LAYOUT
    key; none when the LAYOUT key is absent or the three do not fit
    in the row."""
    lk = home_keys.get("layouts", -1)
    if lk < 0 or geo.rows < 2 or lk + NUM_LAYOUT_SLOTS > geo.cols:
        return []
    base = (geo.rows - 1) * geo.cols + lk
    return [base + i for i in range(NUM_LAYOUT_SLOTS)]


def _shortcut_face(ctx, key, index):
    slot = index + 1
    if str(slot) not in _layouts_load().get("slots", {}):
        return None
    return KeyFace(colors.LOAD_FILLED, f"*\n{slot}")


def _shortcut_press(ctx, key, index):
    slot = index + 1
    if str(slot) not in _layouts_load().get("slots", {}):
        return
    if _load_layout_slot(ctx, slot):
        ctx.flash(True)
    else:
        ctx.flash(False, f"layout shortcut load slot {slot} failed")
    ctx.render()


def _setup(ctx):
    ctx.state().delete_pending = None


PLUGIN = Plugin(
    api=PLUGIN_API,
    setup=_setup,
    pages=[
        Page("layout", _keys, _render_layout, _handle_layout),
        Page(
            "layout_delete_confirm", lambda geo: {},
            _render_confirm, _handle_confirm,
        ),
    ],
    home_button=HomeButton(
        50,
        face=lambda ctx: KeyFace(
            colors.LAYOUT_TITLE, ctx.t("LAYOUT"), icon="layout"
        ),
        press=lambda ctx: ctx.goto("layout"),
    ),
    fixtures=[
        Fixture(20, _shortcut_place, _shortcut_face, _shortcut_press)
    ],
)
