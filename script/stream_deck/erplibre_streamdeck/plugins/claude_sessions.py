# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Claude sessions: dashboard tiles and the per-session action page.

Sessions come from the state directory the Claude hook writes, one JSON
file per session. A tile opens the action page of its session; the page
calls the extension over D-Bus with the session id."""

import json
import os

from erplibre_streamdeck import liveness, paths
from erplibre_streamdeck.plugin import (
    PLUGIN_API, KeyFace, Page, Plugin, TileProvider,
)
from erplibre_streamdeck.ui import colors
from erplibre_streamdeck.ui.text import chunk_text_for_cells, wrap_chunk

PAGE_ID = "claude_session"

# Page key name -> extension method it calls with the session id.
_ACTIONS = (
    ("focus", "FocusClaudeSession"),
    ("accept", "AcceptClaudeSession"),
    ("set_window", "SetClaudeSessionWindow"),
    ("kill", "KillClaudeSession"),
)


def load_sessions():
    """Return live Claude sessions, newest first: [{session_id, cwd,
    description, notification_message, status, ts}]. Reads
    $XDG_STATE_HOME/erplibre-home/claude/*.json at call time. Drops
    files whose PID is no longer running (best-effort). The status
    comes from the latest of the hook timestamps."""
    state = paths.state_dir() / "claude"
    out = []
    if not os.path.isdir(state):
        return out
    for name in sorted(os.listdir(state)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(state, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        pid = int(d.get("pid") or 0)
        ts_active = int(d.get("ts_active") or 0)
        ts_stop = int(d.get("ts_stop") or 0)
        ts_notif = int(d.get("ts_notification") or 0)
        ts_tool = int(d.get("ts_tool") or 0)
        stamps = [
            t for t in (ts_active, ts_stop, ts_notif, ts_tool) if t > 0
        ]
        if pid > 0:
            if stamps:
                if not liveness.alive(pid, min(stamps)):
                    continue
            elif not os.path.exists(f"/proc/{pid}"):
                continue
        ts = max(ts_active, ts_stop, ts_notif, ts_tool)
        if ts == ts_notif and ts_notif > 0:
            status = "awaiting_notification"
        elif ts == ts_stop and ts_stop > 0:
            status = "awaiting_stop"
        elif ts == ts_tool and ts_tool > 0:
            status = "working"
        else:
            status = "active"
        out.append({
            "session_id": d.get("session_id", ""),
            "cwd": d.get("cwd", ""),
            "description": d.get("description", "")
                or d.get("last_prompt", ""),
            "notification_message": d.get("notification_message", ""),
            "status": status,
            "ts": ts,
        })
    out.sort(key=lambda s: -s.get("ts", 0))
    return out


def session_color(session):
    if session.get("status") == "awaiting_notification":
        return colors.CLAUDE_AWAIT_NOTIFY
    if session.get("status") == "awaiting_stop":
        return colors.CLAUDE_AWAIT_STOP
    if session.get("status") == "working":
        return colors.CLAUDE_WORKING
    return colors.CLAUDE_ACTIVE


def session_label(session, max_chars=18):
    """Two short lines for the button."""
    desc = (session.get("description") or "").strip()
    if not desc:
        return ""
    if len(desc) <= max_chars:
        return desc
    # Word-break at a space close to the middle.
    cut = desc.rfind(" ", 0, max_chars)
    if cut < max_chars // 2:
        cut = max_chars
    return desc[:cut].rstrip()


def page_keys(geo):
    """BACK / FOCUS / ACCEPT / SET WINDOW / KILL fill row 0 left to
    right as the deck has more columns. {} below 2 columns."""
    if geo.cols < 2:
        return {}
    keys = {"back": 0, "focus": 1}
    if geo.cols >= 3:
        keys["accept"] = 2
    if geo.cols >= 4:
        keys["set_window"] = 3
    if geo.cols >= 5:
        keys["kill"] = 4
    return keys


def _call(dbus, log, method, sid):
    """Call the extension with the session id; True when it answers
    `true`. A failure goes to the journal. Runs as a job, outside the
    lock: only `dbus`, `log` and its arguments."""
    r = dbus.call(method, sid, timeout=2)
    if not r.true:
        out = (r.stdout + r.stderr).strip()
        verb = "returned" if r.ok else "failed"
        log(f"{method}({sid}) {verb}: {out}")
    return r.true


def _flash_home(ctx, ok, error):
    """then() of a session action: OK or ERR, then the home screen."""
    ctx.flash(bool(ok) and error is None)
    ctx.home()


def _render(ctx):
    cs = page_keys(ctx.geo)
    sid = ctx.state().sid
    session = None
    for s in load_sessions():
        if s.get("session_id") == sid:
            session = s
            break
    text_keys = [
        k for k in range(ctx.geo.total_keys) if k not in cs.values()
    ]
    # A session that needs the user shows what it asks, not the stale
    # topic description.
    if (
        session
        and session.get("status")
        in ("awaiting_notification", "awaiting_stop")
        and session.get("notification_message")
    ):
        text_to_show = session["notification_message"]
    else:
        text_to_show = (session or {}).get("description") or ""
    chunks = chunk_text_for_cells(text_to_show, len(text_keys))
    chunk_by_key = dict(zip(text_keys, chunks))
    accept = session_color(session) if session else (
        colors.CLAUDE_AWAIT_STOP
    )
    faces = {
        "back": (colors.TITLE, ctx.t("BACK"), None),
        "focus": (colors.VOL, ctx.t("FOCUS"), "robot"),
        "accept": (accept, ctx.t("ACCEPT\n↵"), None),
        "set_window": (colors.LAYOUT_TITLE, ctx.t("SET\nWIN"), None),
        "kill": (colors.CANCEL, ctx.t("KILL"), None),
    }
    by_key = {key: faces[name] for name, key in cs.items()}
    for key in range(ctx.geo.total_keys):
        if key in by_key:
            color, label, icon = by_key[key]
            ctx.set_key(key, color, label, icon=icon)
        elif key in chunk_by_key:
            ctx.set_key(key, colors.EMPTY, wrap_chunk(chunk_by_key[key]))
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _handle(ctx, key):
    cs = page_keys(ctx.geo)
    sid = ctx.state().sid
    if not cs or key == cs.get("back") or not sid:
        ctx.home()
        return
    dbus, log = ctx.dbus, ctx.log
    for name, method in _ACTIONS:
        if name in cs and key == cs[name]:
            ctx.run_blocking(
                lambda: _call(dbus, log, method, sid), _flash_home
            )
            return


def _setup(ctx):
    ctx.state().sid = None


def _face(ctx, session):
    return KeyFace(
        session_color(session), session_label(session), icon="robot"
    )


def _press(ctx, session):
    sid = session.get("session_id") or ""
    if sid:
        ctx.state().sid = sid
        ctx.goto(PAGE_ID)


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page(PAGE_ID, page_keys, _render, _handle)],
    tiles=[
        TileProvider(20, lambda ctx: load_sessions(), _face, _press)
    ],
    setup=_setup,
)
