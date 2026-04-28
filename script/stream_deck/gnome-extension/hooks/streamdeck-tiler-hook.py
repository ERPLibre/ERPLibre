#!/usr/bin/env python3
"""Stream Deck Tiler — Claude Code session-state hook.

Drop a single state file per Claude session under
`$XDG_STATE_HOME/streamdeck-tiler/claude/{session_id}.json` so the
GNOME Shell extension can show how many sessions are running and
which ones are awaiting user input.

This script is meant to be wired into Claude Code via
`~/.claude/settings.json`. See `hooks/README.md` for the snippet.

Exit code is always 0 — hook failures must never block Claude.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


STATUS_ACTIVE = "active"
STATUS_AWAIT_STOP = "awaiting_stop"
STATUS_AWAIT_NOTIFY = "awaiting_notification"

STATUS_BY_EVENT = {
    "SessionStart": STATUS_ACTIVE,
    "UserPromptSubmit": STATUS_ACTIVE,
    "PreToolUse": STATUS_ACTIVE,
    "PostToolUse": STATUS_ACTIVE,
    "SubagentStop": STATUS_ACTIVE,
    "PreCompact": STATUS_ACTIVE,
    "Stop": STATUS_AWAIT_STOP,
    "Notification": STATUS_AWAIT_NOTIFY,
    "SessionEnd": None,  # delete the state file
}


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
        "~/.local/state")
    p = Path(base) / "streamdeck-tiler" / "claude"
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


def find_claude_ancestor() -> int:
    """Walk parent PIDs to find the closest ancestor whose comm is 'claude'.

    Returns 0 when the chain cannot be inspected — the extension treats
    PID 0 as "alive" so the file persists until SessionEnd.
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
        # Format: pid (comm) state ppid …  comm may include spaces.
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


def main() -> None:
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}

    event = payload.get("hook_event_name") or (
        sys.argv[1] if len(sys.argv) > 1 else "")
    session_id = (payload.get("session_id") or "").strip()
    if not session_id:
        return  # nothing to track

    target = state_dir() / f"{session_id}.json"

    if event == "SessionEnd" or STATUS_BY_EVENT.get(event) is None:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return

    record = {
        "session_id": session_id,
        "pid": find_claude_ancestor(),
        "cwd": payload.get("cwd") or os.getcwd(),
        "status": STATUS_BY_EVENT.get(event, STATUS_ACTIVE),
        "ts": int(time.time() * 1000),
    }
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    tmp.replace(target)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Hook must never break Claude. Swallow and exit cleanly.
        pass
