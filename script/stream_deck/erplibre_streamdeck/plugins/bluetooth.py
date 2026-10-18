# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Bluetooth page: adapter power and paired devices.

A poll reads the adapter every 2 s while the page shows, away from the
lock, into `state().bt` as (powered, devices). The page draws from it
and a press acts on it: the toggle's direction is the cached power, a
device key's device the cached device at its slot."""

import shutil
import subprocess
import sys

from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin, Poll,
)
from erplibre_streamdeck.ui import colors, render


def _bt_powered():
    """Return True/False/None. None = unable to determine."""
    if shutil.which("bluetoothctl"):
        try:
            r = subprocess.run(
                ["bluetoothctl", "show"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if line.strip().startswith("Powered:"):
                        return line.split(":", 1)[1].strip() == "yes"
        except Exception as e:
            print(f"bluetoothctl show error: {e}", file=sys.stderr, flush=True)
    if shutil.which("rfkill"):
        try:
            r = subprocess.run(
                ["rfkill", "list", "bluetooth"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0 and r.stdout.strip():
                for line in r.stdout.splitlines():
                    if line.strip().startswith("Soft blocked:"):
                        return line.split(":", 1)[1].strip() == "no"
        except Exception as e:
            print(f"rfkill list error: {e}", file=sys.stderr, flush=True)
    return None


def _bt_list_paired():
    """Return [(mac, name, connected)] for paired devices via bluetoothctl."""
    paired = []
    if not shutil.which("bluetoothctl"):
        return paired
    try:
        r = subprocess.run(
            ["bluetoothctl", "devices", "Paired"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.split(maxsplit=2)
                if len(parts) >= 3 and parts[0] == "Device":
                    paired.append((parts[1], parts[2]))
    except Exception as e:
        print(
            f"bluetoothctl devices Paired error: {e}",
            file=sys.stderr, flush=True,
        )
        return []
    connected = set()
    try:
        r = subprocess.run(
            ["bluetoothctl", "devices", "Connected"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.split(maxsplit=2)
                if len(parts) >= 2 and parts[0] == "Device":
                    connected.add(parts[1])
    except Exception:
        pass
    return [(mac, name, mac in connected) for mac, name in paired]


def _bt_connect(mac):
    """Connect a paired device; True on exit 0. Runs as a job, outside
    the lock: only `mac`."""
    if not shutil.which("bluetoothctl"):
        return False
    try:
        r = subprocess.run(
            ["bluetoothctl", "connect", mac],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"bluetoothctl connect error: {e}", file=sys.stderr, flush=True)
        return False


def _bt_disconnect(mac):
    """Disconnect a device; True on exit 0. Runs as a job, outside the
    lock: only `mac`."""
    if not shutil.which("bluetoothctl"):
        return False
    try:
        r = subprocess.run(
            ["bluetoothctl", "disconnect", mac],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception as e:
        print(
            f"bluetoothctl disconnect error: {e}", file=sys.stderr, flush=True
        )
        return False


def _bt_set_power(on):
    """Switch the adapter on or off; True on success. Runs as a job,
    outside the lock: only `on`."""
    if shutil.which("bluetoothctl"):
        try:
            r = subprocess.run(
                ["bluetoothctl", "power", "on" if on else "off"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                return True
        except Exception as e:
            print(
                f"bluetoothctl power error: {e}", file=sys.stderr, flush=True
            )
    if shutil.which("rfkill"):
        try:
            r = subprocess.run(
                ["rfkill", "unblock" if on else "block", "bluetooth"],
                capture_output=True, text=True, timeout=3,
            )
            return r.returncode == 0
        except Exception as e:
            print(f"rfkill error: {e}", file=sys.stderr, flush=True)
    return False


def _keys(geo):
    """Bluetooth page keys. Needs >= 2 cols and >= 2 rows, else None;
    paired-device slots fill row 1 after the toggle."""
    if geo.cols < 2 or geo.rows < 2:
        return None
    return {
        "back": 0,
        "toggle": geo.cols + 1,
        "devices": list(range(geo.cols + 2, 2 * geo.cols)),
    }


# What the page shows before its first poll: what a missing adapter
# gives (power unknown, no device).
NO_BT = (None, [])


def _read():
    """(powered, devices) of the adapter, the poll's read: no Context,
    no lock. The paired devices are listed even with the adapter off,
    since a device key acts on them."""
    return _bt_powered(), _bt_list_paired()


def _store(ctx, data):
    """Keep the poll's data as state().bt; True when it changed."""
    st = ctx.state()
    changed = st.bt != data
    st.bt = data
    return changed


def _shown(ctx):
    """The page shows at a size that draws the adapter."""
    return ctx.page == "bluetooth" and bool(ctx.keys)


def _setup(ctx):
    ctx.state().bt = None


def _render(ctx):
    bk = ctx.keys
    if not bk:
        render.too_small(ctx)
        return
    powered, devices = ctx.state().bt or NO_BT
    if powered is None:
        toggle_color, toggle_label = colors.BT_NA, ctx.t("BT\nN/A")
    elif powered:
        toggle_color, toggle_label = colors.BT_ON, "BT\nON"
    else:
        toggle_color, toggle_label = colors.BT_OFF, "BT\nOFF"
    assignments = {
        bk["back"]: (colors.BACK, ctx.t("BACK")),
        bk["toggle"]: (toggle_color, toggle_label),
    }
    # Device names show only when the adapter is powered; the slots
    # still act on the cached devices otherwise (see _handle).
    device_keys = bk.get("devices", [])
    if powered and device_keys:
        for i, k in enumerate(device_keys):
            if i >= len(devices):
                break
            mac, name, connected = devices[i]
            words = name.split()
            short = words[-1][:6] if words else name[:6]
            color = colors.BT_ON if connected else colors.BT_OFF
            assignments[k] = (color, short)
    for key in range(ctx.geo.total_keys):
        if key in assignments:
            color, label = assignments[key]
            ctx.set_key(key, color, label)
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _job(action):
    """work() of a bluetooth job: action(), then the adapter read again
    (`_read`), so the result carries the state the action left. Runs
    outside the lock: only `action` and module functions."""

    def work():
        action()
        return _read()

    return work


def _render_then(ctx, data, error):
    """then() of a bluetooth job: the adapter read after the action
    goes into the cache, as the poll stores it, and the page is drawn
    again, with no flash, success or not."""
    if error is None:
        _store(ctx, data)
    ctx.render()


def _handle(ctx, key):
    bk = ctx.keys
    if not bk:
        ctx.home()
        return
    if key == bk["back"]:
        ctx.home()
        return
    powered, devices = ctx.state().bt or NO_BT
    if key == bk["toggle"]:
        if powered is None:
            ctx.flash(
                False, "bluetooth: bluetoothctl unavailable or no adapter"
            )
            ctx.render()
            return
        ctx.run_blocking(
            _job(lambda: _bt_set_power(not powered)), _render_then
        )
        return
    # A device key is live even when blank (adapter off): the press
    # acts on the cached device at its slot.
    if key in bk.get("devices", []):
        idx = bk["devices"].index(key)
        if idx < len(devices):
            mac, _name, connected = devices[idx]
            switch = _bt_disconnect if connected else _bt_connect
            ctx.run_blocking(_job(lambda: switch(mac)), _render_then)


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("bluetooth", _keys, _render, _handle)],
    home_button=HomeButton(
        70,
        face=lambda ctx: KeyFace(colors.BT_TITLE, "BT", icon="bt"),
        press=lambda ctx: ctx.goto("bluetooth"),
    ),
    polls=[Poll(2.0, _shown, _read, _store)],
    setup=_setup,
)
