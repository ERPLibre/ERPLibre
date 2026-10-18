# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Tracker timers: the TIMER page, its reset confirmation and the
running timers on the home dashboard.

The timers come from the tracker extension through the ERPLibre Home
extension's D-Bus methods. `state().timers` is the last list read: the
home dashboard and the TIMER page both draw from it. A poll reads it
every 2 s, away from the lock, while either shows; the RFSH key and the
export read it at the press."""

import csv
import json
import os
import shutil
import subprocess
import sys

from erplibre_streamdeck import dbus as dbus_mod
from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin, Poll, TileProvider,
)
from erplibre_streamdeck.ui import colors

LIST = "timer_list"
CONFIRM = "timer_reset_confirm"
REFRESH_SEC = 2.0


def _list_timers(dbus, log):
    """The tracker's timers as a list of dicts; [] when unavailable."""
    r = dbus.call("ListTrackerTimers")
    if not r.ok:
        log(f"Timer list dbus: {r.stderr}")
        return []
    payload = r.string
    if not payload:
        return []
    try:
        return json.loads(payload)
    except Exception as e:
        log(f"Timer list error: {e}")
        return []


def _log(msg):
    """Context.log's line, for the poll's read, which has no Context."""
    print(f"[erplibre-home] timers: {msg}", file=sys.stderr, flush=True)


def _read():
    """The poll's read: the timers, without Context or lock."""
    return _list_timers(dbus_mod, _log)


# The three tracker actions run as jobs, outside the lock: they use
# only `dbus` and `log`.


def _toggle_timer(dbus, log, timer_id):
    r = dbus.call("ToggleTrackerTimer", timer_id)
    if not r.true:
        log(f"Timer toggle dbus: {r.stdout} {r.stderr}")
    return r.true


def _add_timer(dbus, log):
    """Id answered by AddTrackerTimer, '' on failure."""
    r = dbus.call("AddTrackerTimer")
    if not r.ok:
        log(f"Timer add dbus: {r.stderr}")
        return ""
    return r.string or ""


def _reset_all_timers(dbus, log):
    r = dbus.call("ResetAllTrackerTimers")
    if not r.true:
        log(f"Timer reset dbus: {r.stdout} {r.stderr}")
    return r.true


def _ask_save_path():
    """Prompt the user for a file path via zenity. Returns '' if cancelled."""
    if not shutil.which("zenity"):
        print("zenity not installed — cannot open file dialog.")
        return ""
    try:
        result = subprocess.run(
            [
                "zenity", "--file-selection", "--save",
                "--confirm-overwrite",
                "--file-filter=CSV files | *.csv",
                "--filename=timers.csv",
            ],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            return ""  # cancelled
        path = result.stdout.strip()
        if path and not path.lower().endswith(".csv"):
            path += ".csv"
        return path
    except Exception as e:
        print(f"File dialog error: {e}", file=sys.stderr, flush=True)
        return ""


def _csv_rows(timers):
    """[name, seconds, HH:MM:SS] of each timer, the CSV export's rows."""
    rows = []
    for t in timers:
        elapsed = int(t.get("elapsed") or 0)
        hh = elapsed // 3600
        mm = (elapsed % 3600) // 60
        ss = elapsed % 60
        rows.append(
            [t.get("name") or "", elapsed, f"{hh:02d}:{mm:02d}:{ss:02d}"]
        )
    return rows


def _export_timers_csv(path, rows):
    """Write the CSV rows to path. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "seconds", "time"])
            writer.writerows(rows)
        return True
    except Exception as e:
        print(f"CSV write error: {e}", file=sys.stderr, flush=True)
        return False


def _export(rows):
    """The save dialog, then the CSV write: one job, outside the lock.
    None when the dialog is cancelled, else whether the write
    succeeded."""
    path = _ask_save_path()
    if not path:
        return None
    return _export_timers_csv(path, rows)


def _label_for_timer(timer):
    """Build a short 2-line label: first word of name + mm:ss."""
    name = timer.get("name") or "?"
    first = name.split()[0] if name.split() else name
    if len(first) > 6:
        first = first[:6]
    elapsed = int(timer.get("elapsed") or 0)
    mm = elapsed // 60
    ss = elapsed % 60
    return f"{first}\n{mm:02d}:{ss:02d}"


def _setup(ctx):
    st = ctx.state()
    st.timers = []
    st.key_map = {}
    st.hidden = set()


def _list_keys(geo):
    """Key map of the timer page: BACK, then the timer slots, then the
    action keys on the last five keys."""
    n = geo.total_keys
    return {
        "back": 0, "clean": n - 5, "export": n - 4, "new": n - 3,
        "reset": n - 2, "refresh": n - 1, "slots": list(range(1, n - 5)),
    }


def _store(ctx, timers):
    """Keep the timers in the state and map them onto the slots; True
    when the list changed."""
    st = ctx.state()
    changed = st.timers != timers
    st.timers = timers
    st.key_map = {}
    slots = _list_keys(ctx.geo)["slots"]
    for idx, timer in enumerate(st.timers):
        if idx >= len(slots):
            break
        st.key_map[slots[idx]] = timer.get("id")
    return changed


def _refresh(ctx):
    """Read the timers now, under the lock, into the state."""
    _store(ctx, _list_timers(ctx.dbus, ctx.log))


def _shown(ctx):
    """The home screen ("idle") or the timer page shows the timers."""
    return ctx.page in ("idle", LIST)


def enter(ctx):
    """Open the timer page on the cached list; the poll, active from
    this page on, reads it again on the next pass."""
    ctx.goto(LIST)


def _render_list(ctx):
    st = ctx.state()
    k = _list_keys(ctx.geo)
    for key in range(ctx.geo.total_keys):
        if key == k["back"]:
            ctx.set_key(key, colors.BACK, ctx.t("BACK"))
            continue
        if key == k["refresh"]:
            ctx.set_key(key, colors.REFRESH, ctx.t("RFSH"))
            continue
        if key == k["reset"]:
            ctx.set_key(key, colors.RESET, ctx.t("RESET\nALL"))
            continue
        if key == k["new"]:
            ctx.set_key(key, colors.NEW, ctx.t("NEW"))
            continue
        if key == k["export"]:
            ctx.set_key(key, colors.EXPORT, ctx.t("EXPT\nCSV"))
            continue
        if key == k["clean"]:
            ctx.set_key(key, colors.TIMER_PAUSED, ctx.t("CLEAN\nDASH"))
            continue
        timer_id = st.key_map.get(key)
        if not timer_id:
            # Empty slot: the hint shows only when no timer exists.
            if not st.timers and key == 1:
                ctx.set_key(key, colors.EMPTY, ctx.t("NO\nTIMERS"))
            else:
                ctx.set_key(key, colors.EMPTY, "")
            continue
        timer = next(
            (t for t in st.timers if t.get("id") == timer_id), None
        )
        if not timer:
            ctx.set_key(key, colors.EMPTY, "")
            continue
        color = (
            colors.TIMER_RUNNING if timer.get("running")
            else colors.TIMER_PAUSED
        )
        ctx.set_key(key, color, _label_for_timer(timer))


def _render_or_flash(reason):
    """then() of a toggle or add job: on failure ERR with `reason` in
    the journal; renders the page shown, from the cache, which the next
    poll brings up to date."""

    def then(ctx, ok, error):
        if not ok or error is not None:
            ctx.flash(False, reason)
        ctx.render()

    return then


def _export_done(ctx, ok, error):
    # Cancelled (None, no error): no flash, the page renders again.
    if ok is not None or error is not None:
        ctx.flash(bool(ok) and error is None)
    ctx.render()


def _handle_export(ctx):
    # The list is read first so the export is current; the dialog
    # waits on the user, so it and the write run as one job.
    _refresh(ctx)
    rows = _csv_rows(ctx.state().timers)
    ctx.run_blocking(lambda: _export(rows), _export_done)


def _handle_list(ctx, key):
    st = ctx.state()
    k = _list_keys(ctx.geo)
    if key == k["back"]:
        ctx.home()
        return
    if key == k["refresh"]:
        _refresh(ctx)
        ctx.render()
        return
    if key == k["reset"]:
        ctx.goto(CONFIRM)
        return
    dbus, log = ctx.dbus, ctx.log
    if key == k["new"]:
        ctx.run_blocking(
            lambda: _add_timer(dbus, log),
            _render_or_flash("AddTrackerTimer returned no id"),
        )
        return
    if key == k["export"]:
        _handle_export(ctx)
        return
    if key == k["clean"]:
        # Hide every running timer from the home dashboard: they keep
        # ticking in the tracker, only the main screen drops them.
        st.hidden = {
            t.get("id") for t in (st.timers or [])
            if t.get("running") and t.get("id")
        }
        ctx.flash(True)
        ctx.render()
        return
    timer_id = st.key_map.get(key)
    if not timer_id:
        return
    ctx.run_blocking(
        lambda: _toggle_timer(dbus, log, timer_id),
        _render_or_flash(f"ToggleTrackerTimer({timer_id}) failed"),
    )


def _confirm_keys(geo):
    return {
        "cancel": 0, "ok": geo.total_keys - 1, "mid": geo.total_keys // 2,
    }


def _render_confirm(ctx):
    k = _confirm_keys(ctx.geo)
    mid_key = k["mid"]
    for key in range(ctx.geo.total_keys):
        if key == k["cancel"]:
            ctx.set_key(key, colors.CANCEL, ctx.t("CANCEL"))
        elif key == k["ok"]:
            ctx.set_key(key, colors.CONFIRM, ctx.t("OK"))
        elif key == mid_key - 1 and ctx.geo.cols >= 3:
            ctx.set_key(key, colors.EMPTY, ctx.t("RESET"))
        elif key == mid_key and ctx.geo.cols >= 3:
            ctx.set_key(key, colors.EMPTY, ctx.t("ALL?"))
        elif key == mid_key:
            ctx.set_key(key, colors.EMPTY, ctx.t("RESET\nALL?"))
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _handle_confirm(ctx, key):
    k = _confirm_keys(ctx.geo)
    if key == k["cancel"]:
        ctx.goto(LIST)
        return
    if key == k["ok"]:
        dbus, log = ctx.dbus, ctx.log
        ctx.run_blocking(
            lambda: _reset_all_timers(dbus, log), _reset_done
        )
    # Other keys: ignored, the choice is explicit.


def _reset_done(ctx, ok, error):
    if ok and error is None:
        ctx.flash(True)
    else:
        ctx.flash(False, "ResetAllTrackerTimers failed via D-Bus")
    ctx.goto(LIST)


def _running(ctx):
    """Running timers the dashboard shows. A hidden id leaves the set
    once its timer stops, so a stop + start brings the timer back."""
    st = ctx.state()
    timers = st.timers or []
    st.hidden &= {t.get("id") for t in timers if t.get("running")}
    return [
        t for t in timers
        if t.get("running") and t.get("id") not in st.hidden
    ]


PLUGIN = Plugin(
    api=PLUGIN_API,
    setup=_setup,
    pages=[
        Page(LIST, None, _render_list, _handle_list),
        Page(CONFIRM, _confirm_keys, _render_confirm, _handle_confirm),
    ],
    home_button=HomeButton(
        20,
        face=lambda ctx: KeyFace(
            colors.TIMER_TITLE, ctx.t("TIMER"), icon="timer"
        ),
        press=enter,
    ),
    tiles=[
        TileProvider(
            30,
            items=_running,
            face=lambda ctx, t: KeyFace(
                colors.TIMER_RUNNING, _label_for_timer(t), icon="timer"
            ),
            press=lambda ctx, t: enter(ctx),
        )
    ],
    polls=[Poll(REFRESH_SEC, _shown, _read, _store)],
)
