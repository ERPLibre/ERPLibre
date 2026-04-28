#!/usr/bin/env python3
"""Stream Deck Tiler — Claude Code session-state hook.

Maintains one JSON file per Claude session under
`$XDG_STATE_HOME/streamdeck-tiler/claude/{session_id}.json` so the
GNOME Shell extension can show how many sessions are running and
which ones are awaiting user input.

The file stores three independent timestamps (ms epoch):

* ``ts_active`` — last user activity (SessionStart, UserPromptSubmit,
  PreToolUse, PostToolUse, SubagentStop, PreCompact)
* ``ts_stop`` — last Stop hook (assistant turn ended, awaiting user)
* ``ts_notification`` — last Notification hook (permission / idle alert)

Status is derived in the extension by picking the most recent of the
three. A user-driven event (UserPromptSubmit, PreTool/PostTool…)
therefore *clears* a stale Stop or Notification by bumping
``ts_active`` past them, so the badge does not stay red after the
user types again.

This script is meant to be wired into Claude Code via
`~/.claude/settings.json`. See `hooks/README.md` for the snippet.
Exit code is always 0 — hook failures must never block Claude.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


TS_ACTIVE = "ts_active"
TS_STOP = "ts_stop"
TS_NOTIFICATION = "ts_notification"

# Maps a hook event name to the timestamp field it should update.
#
# `Stop` must be the most recent event after a Ctrl+C interrupt, so we
# deliberately leave PreToolUse, PostToolUse, SubagentStop and PreCompact
# OUT of this map. Otherwise an interrupted tool's PostToolUse fires
# AFTER Stop and bumps `ts_active` past `ts_stop`, making the status
# look like the assistant is working again when it has actually been
# stopped by the user.
EVENT_FIELD = {
    "SessionStart": TS_ACTIVE,
    "UserPromptSubmit": TS_ACTIVE,
    "Stop": TS_STOP,
    "Notification": TS_NOTIFICATION,
}


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
        "~/.local/state")
    p = Path(base) / "streamdeck-tiler" / "claude"
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


def find_claude_ancestor() -> int:
    """Walk parent PIDs to find the closest ancestor whose comm is 'claude'.

    Returns 0 when the chain cannot be inspected.
    """
    pid = os.getppid()
    for _ in range(12):
        if pid <= 1:
            return 0
        try:
            comm = (Path(f"/proc/{pid}/comm").read_text(
                encoding="utf-8", errors="replace").strip())
        except OSError:
            return 0
        if comm == "claude":
            return pid
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            return 0
        rparen = stat.rfind(")")
        if rparen < 0:
            return 0
        rest = stat[rparen + 2:].split()
        if len(rest) < 2:
            return 0
        try:
            pid = int(rest[1])
        except ValueError:
            return 0
    return 0


def capture_focused_window_id() -> int:
    """Ask the GNOME extension for the currently focused window id.

    Falls back to 0 when D-Bus is unavailable. Returns a stable
    Mutter window id (Meta.Window.get_stable_sequence) so the same
    window can be re-focused later regardless of title changes.
    """
    try:
        out = subprocess.run([
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Shell",
            "--object-path",
            "/org/gnome/Shell/Extensions/StreamDeckTiler",
            "--method",
            "org.gnome.Shell.Extensions.StreamDeckTiler"
            ".GetFocusedWindowId",
        ], capture_output=True, text=True, timeout=2)
        if out.returncode != 0:
            return 0
        m = re.search(r"'(\d+)'", out.stdout)
        return int(m.group(1)) if m else 0
    except (subprocess.SubprocessError, FileNotFoundError, ValueError):
        return 0


def load_existing(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> None:
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}

    event = payload.get("hook_event_name") or (
        sys.argv[1] if len(sys.argv) > 1 else "")
    session_id = (payload.get("session_id") or "").strip()
    if not session_id:
        return

    target = state_dir() / f"{session_id}.json"

    if event == "SessionEnd":
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return

    field = EVENT_FIELD.get(event)
    if field is None:
        return

    now = int(time.time() * 1000)
    existing = load_existing(target) or {}
    record = {
        "session_id": session_id,
        "pid": existing.get("pid") or find_claude_ancestor(),
        "cwd": payload.get("cwd") or existing.get("cwd") or os.getcwd(),
        "description": existing.get("description") or "",
        "last_prompt": existing.get("last_prompt") or "",
        "window_id": int(existing.get("window_id") or 0),
        TS_ACTIVE: int(existing.get(TS_ACTIVE) or 0),
        TS_STOP: int(existing.get(TS_STOP) or 0),
        TS_NOTIFICATION: int(existing.get(TS_NOTIFICATION) or 0),
    }
    record[field] = now

    # Refresh the stored window id only on user-driven events: those
    # fire while the terminal is focused. Stop/Notification can fire
    # while the user looks at another window, so reusing the previous
    # value avoids capturing the wrong target.
    if event in ("SessionStart", "UserPromptSubmit"):
        wid = capture_focused_window_id()
        if wid > 0:
            record["window_id"] = wid

    if event == "UserPromptSubmit":
        prompt = (payload.get("prompt") or "").strip()
        first_line = (prompt.splitlines() or [""])[0][:120]
        if first_line:
            record["last_prompt"] = first_line
            if not record["description"]:
                record["description"] = first_line

    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    tmp.replace(target)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
