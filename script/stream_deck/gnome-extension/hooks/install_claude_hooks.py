#!/usr/bin/env python3
"""Idempotent installer for the streamdeck-tiler Claude Code hooks.

Merges the absolute hook command into `~/.claude/settings.json` for the
five events the GNOME extension reacts to. Re-running the script is a
no-op once the entries are present.

The settings file is rewritten atomically and backed up to
`settings.json.bak-streamdeck-<ts>` before the first modification.

Usage:
    install_claude_hooks.py [--dry-run] [--remove]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parent / "streamdeck-tiler-hook.py"
SETTINGS = Path.home() / ".claude" / "settings.json"
EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "Stop",
    "Notification",
    "SessionEnd",
)
TAG = "streamdeck-tiler"


def load() -> dict:
    if not SETTINGS.exists():
        return {}
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {SETTINGS} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)


def backup(data: dict) -> Path | None:
    if not SETTINGS.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = SETTINGS.with_name(f"settings.json.bak-{TAG}-{stamp}")
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return target


def write(data: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(SETTINGS)


def has_entry(matchers: list, command: str) -> bool:
    for m in matchers:
        for h in m.get("hooks", []) or []:
            if h.get("type") == "command" and h.get("command") == command:
                return True
    return False


def install(data: dict, command: str) -> int:
    """Add hook entries; return number of events newly modified."""
    hooks = data.setdefault("hooks", {})
    changed = 0
    for event in EVENTS:
        matchers = hooks.setdefault(event, [])
        if not isinstance(matchers, list):
            print(
                f"WARN: hooks.{event} not a list, replacing", file=sys.stderr)
            matchers = []
            hooks[event] = matchers
        if has_entry(matchers, command):
            continue
        matchers.append(
            {"hooks": [{"type": "command", "command": command}]})
        changed += 1
    return changed


def remove(data: dict, command: str) -> int:
    hooks = data.get("hooks") or {}
    removed = 0
    for event in EVENTS:
        matchers = hooks.get(event)
        if not isinstance(matchers, list):
            continue
        new_matchers = []
        for m in matchers:
            kept = [
                h for h in (m.get("hooks") or [])
                if not (h.get("type") == "command"
                        and h.get("command") == command)
            ]
            if kept:
                m["hooks"] = kept
                new_matchers.append(m)
            else:
                removed += 1
        if new_matchers:
            hooks[event] = new_matchers
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks", None)
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change, write nothing.")
    ap.add_argument("--remove", action="store_true",
                    help="Remove the streamdeck-tiler hook entries.")
    args = ap.parse_args()

    if not HOOK_PATH.exists():
        print(f"ERROR: hook script missing at {HOOK_PATH}", file=sys.stderr)
        return 2
    if not os.access(HOOK_PATH, os.X_OK):
        print(f"ERROR: hook script not executable: chmod +x {HOOK_PATH}",
              file=sys.stderr)
        return 2

    command = str(HOOK_PATH)
    data = load()

    if args.remove:
        n = remove(data, command)
        verb = "would remove" if args.dry_run else "removed"
        print(f"{verb} {n} hook entries from {SETTINGS}")
    else:
        n = install(data, command)
        verb = "would add" if args.dry_run else "added"
        print(f"{verb} {n} hook entries in {SETTINGS}")
        if n == 0:
            print("(already up to date)")

    if args.dry_run:
        print("--- proposed JSON ---")
        print(json.dumps(data, indent=2))
        return 0

    if n > 0:
        bk = backup(load())
        if bk:
            print(f"backup: {bk}")
        write(data)
        print(f"wrote {SETTINGS}")
        print("Restart any running Claude Code sessions to pick up "
              "SessionStart; UserPromptSubmit fires on next message.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
