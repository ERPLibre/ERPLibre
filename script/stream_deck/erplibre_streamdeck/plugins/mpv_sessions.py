# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""mpv sessions: dashboard tiles and the per-player action page.

Players come from the state directory the extension writes, one JSON
file per player. A tile opens the action page of its player; the page
sends commands to it through the extension's MpvSendCommand method."""

import json
import os

from erplibre_streamdeck import liveness, paths
from erplibre_streamdeck.plugin import (
    PLUGIN_API, KeyFace, Page, Plugin, TileProvider,
)
from erplibre_streamdeck.ui import colors
from erplibre_streamdeck.ui.text import chunk_text_for_cells, wrap_chunk

PAGE_ID = "mpv_session"

# Command -> stays on the page (volume nudges repeat).
_COMMANDS = (
    ("play_pause", False),
    ("quit", False),
    ("vol_down", True),
    ("vol_up", True),
)


def load_sessions():
    """Return live mpv players, newest first: [{pid, title, url,
    started_at}]. Reads $XDG_STATE_HOME/erplibre-home/mpv/*.json at call
    time. Drops entries whose pid is gone."""
    state = paths.state_dir() / "mpv"
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
        started_at = int(d.get("started_at") or 0)
        if pid > 0:
            if started_at > 0:
                if not liveness.alive(pid, started_at):
                    continue
            elif not os.path.exists(f"/proc/{pid}"):
                continue
        out.append({
            "pid": pid,
            "title": d.get("title", "") or d.get("url", ""),
            "url": d.get("url", ""),
            "started_at": started_at,
        })
    out.sort(key=lambda s: -s.get("started_at", 0))
    return out


def page_keys(geo):
    """BACK / PLAY-PAUSE / QUIT on the first row; VOL- / VOL+ on the
    second row when there is one. {} below 3 columns."""
    if geo.cols < 3:
        return {}
    keys = {"back": 0, "play_pause": 1, "quit": 2}
    if geo.rows >= 2:
        keys["vol_down"] = geo.cols
        keys["vol_up"] = geo.cols + 1
    return keys


def _send(dbus, log, pid, command):
    """MpvSendCommand(pid, command); True when the extension answers
    `true`. A failure goes to the journal. Runs as a job, outside the
    lock: only `dbus`, `log` and its arguments."""
    r = dbus.call("MpvSendCommand", str(int(pid)), command, timeout=2)
    if not r.true:
        out = (r.stdout + r.stderr).strip()
        verb = "returned" if r.ok else "failed"
        log(f"MpvSendCommand({pid}, {command!r}) {verb}: {out}")
    return r.true


def _sent(stay_on_page):
    """then() of a command: OK or ERR, then the page again for a
    volume nudge (it repeats), the home screen otherwise."""

    def then(ctx, ok, error):
        ctx.flash(bool(ok) and error is None)
        if stay_on_page:
            ctx.render()
        else:
            ctx.home()

    return then


def _render(ctx):
    ms = page_keys(ctx.geo)
    pid = ctx.state().pid
    sess = None
    for s in load_sessions():
        if s.get("pid") == pid:
            sess = s
            break
    text_keys = [
        k for k in range(ctx.geo.total_keys) if k not in ms.values()
    ]
    title = (sess or {}).get("title") or (sess or {}).get("url") or ""
    chunks = chunk_text_for_cells(title, len(text_keys))
    chunk_by_key = dict(zip(text_keys, chunks))
    faces = {
        "back": (colors.TITLE, ctx.t("BACK")),
        "play_pause": (colors.MPV_ACTIVE, ctx.t("PLAY\nPAUSE")),
        "quit": (colors.CANCEL, ctx.t("QUIT")),
        "vol_down": (colors.MPV_ACTIVE, ctx.t("VOL\n−")),
        "vol_up": (colors.MPV_ACTIVE, ctx.t("VOL\n+")),
    }
    by_key = {key: faces[name] for name, key in ms.items()}
    for key in range(ctx.geo.total_keys):
        if key in by_key:
            ctx.set_key(key, *by_key[key])
        elif key in chunk_by_key:
            ctx.set_key(key, colors.EMPTY, wrap_chunk(chunk_by_key[key]))
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _handle(ctx, key):
    ms = page_keys(ctx.geo)
    pid = ctx.state().pid
    if not ms or key == ms.get("back") or not pid:
        ctx.home()
        return
    dbus, log = ctx.dbus, ctx.log
    for command, stay_on_page in _COMMANDS:
        if key == ms.get(command):
            ctx.run_blocking(
                lambda: _send(dbus, log, pid, command), _sent(stay_on_page)
            )
            return


def _setup(ctx):
    ctx.state().pid = None


def _face(ctx, session):
    title = (session.get("title") or session.get("url") or "mpv")[:18]
    return KeyFace(colors.MPV_ACTIVE, wrap_chunk(title))


def _press(ctx, session):
    ctx.state().pid = session["pid"]
    ctx.goto(PAGE_ID)


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page(PAGE_ID, page_keys, _render, _handle)],
    tiles=[
        TileProvider(10, lambda ctx: load_sessions(), _face, _press)
    ],
    setup=_setup,
)
