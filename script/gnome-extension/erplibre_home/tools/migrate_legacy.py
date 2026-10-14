#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Carry a workstation's state over from the extension's previous identity.

The extension was ``streamdeck-tiler@technolibre.ca`` before it became
``erplibre-home@technolibre.ca``. A workstation that ran it keeps, under
the old names: its entry in ``enabled-extensions``, a symlink (and maybe
hot-reload copies) in the extensions directory, a dconf path, data in the
XDG config, state and cache directories, and Claude hook entries pointing
at the old hook script. Each step below moves one of them over.

A pure function decides each step; the ``migrate_*`` functions apply the
decision. Every step is idempotent: a second run prints nothing but the
no-bus line. A failing step prints a warning and the next step runs; the
script always exits 0, so it never blocks the install that follows.
Uses the standard library only: it runs before any venv exists.

The order stops the old writer before touching what it writes. The old
Claude hook goes first, then the old extension is disabled over the
session bus; only then are its files and data directories moved, because a
shell that still has the old extension loaded recreates its directories on
its next write.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

LEGACY_UUID = "streamdeck-tiler@technolibre.ca"
NEW_UUID = "erplibre-home@technolibre.ca"
LEGACY_RELOAD_PREFIX = "streamdeck-tiler-reload-"
UUID_DOMAIN = "@technolibre.ca"
LEGACY_DCONF = "/org/gnome/shell/extensions/streamdeck-tiler/"
NEW_DCONF = "/org/gnome/shell/extensions/erplibre-home/"
LEGACY_DIR = "streamdeck-tiler"
NEW_DIR = "erplibre-home"
LEGACY_HOOK_SUFFIX = "/streamdeck-tiler-hook.py"

EXT_ROOT = Path(__file__).resolve().parent.parent
HOOKS_INSTALLER = EXT_ROOT / "hooks" / "install_claude_hooks.py"


def parse_strv(text: str) -> list[str]:
    """Parse the string array ``gsettings get`` prints.

    ``@as []`` is the empty array; any other value is a list literal of
    single-quoted strings, which Python reads as is.
    """
    text = text.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    if not text:
        return []
    value = ast.literal_eval(text)
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"not a list: {text}")
    return [str(item) for item in value]


def format_strv(items: list[str]) -> str:
    """The inverse of parse_strv, as ``gsettings set`` accepts it."""
    return "[" + ", ".join(repr(item) for item in items) + "]"


def plan_enabled(current: list[str]) -> list[str] | None:
    """The enabled-extensions list with the old UUID replaced in place.

    Returns None when the old UUID is not listed. When the new UUID is
    already listed, the old one is dropped; order is otherwise kept.
    """
    if LEGACY_UUID not in current:
        return None
    out: list[str] = []
    for uuid in current:
        if uuid == LEGACY_UUID:
            uuid = NEW_UUID
        if uuid not in out:
            out.append(uuid)
    return out


def legacy_extension_entries(names: list[str]) -> list[str]:
    """Entries of the extensions directory that belong to the old UUID."""
    return sorted(
        name for name in names
        if name == LEGACY_UUID
        or (name.startswith(LEGACY_RELOAD_PREFIX)
            and name.endswith(UUID_DOMAIN)))


def plan_dconf(old_dump: str, new_dump: str) -> bool:
    """Copy the old dconf path only into a new path that holds no key."""
    return bool(old_dump.strip()) and not new_dump.strip()


def plan_data_dir(src: Path, dst: Path) -> str | None:
    """'move', 'conflict' when both exist, or None when src is absent."""
    if not (src.exists() or src.is_symlink()):
        return None
    if dst.exists() or dst.is_symlink():
        return "conflict"
    return "move"


def legacy_hook_commands(settings: dict) -> list[str]:
    """Hook commands in a Claude settings dict that run the old script."""
    found: list[str] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return found
    for matchers in hooks.values():
        if not isinstance(matchers, list):
            continue
        for matcher in matchers:
            if not isinstance(matcher, dict):
                continue
            for hook in matcher.get("hooks") or []:
                command = hook.get("command") if isinstance(hook, dict) \
                    else None
                if isinstance(command, str) \
                        and hook.get("type") == "command" \
                        and command.endswith(LEGACY_HOOK_SUFFIX) \
                        and command not in found:
                    found.append(command)
    return found


def xdg_bases(env: dict, home: Path) -> list[Path]:
    """The XDG config, state and cache directories, in that order."""
    return [
        Path(env.get("XDG_CONFIG_HOME") or home / ".config"),
        Path(env.get("XDG_STATE_HOME") or home / ".local" / "state"),
        Path(env.get("XDG_CACHE_HOME") or home / ".cache"),
    ]


def extensions_dir(env: dict, home: Path) -> Path:
    data = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    return data / "gnome-shell" / "extensions"


def session_bus_env(env: dict) -> dict | None:
    """The environment to reach the session bus with, or None.

    An address already in the environment wins. Otherwise the user bus
    socket under XDG_RUNTIME_DIR (``/run/user/<uid>`` by default) is the
    one a systemd-managed desktop session uses, also from an ssh login.
    """
    if env.get("DBUS_SESSION_BUS_ADDRESS"):
        return dict(env)
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    sock = Path(runtime) / "bus"
    if sock.is_socket():
        return {**env, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={sock}"}
    return None


def make_runner(env: dict):
    """A runner: run(cmd, stdin=None) -> (returncode, stdout or error)."""
    def run(cmd: list[str], stdin: str | None = None) -> tuple[int, str]:
        try:
            proc = subprocess.run(cmd, input=stdin, capture_output=True,
                                  text=True, timeout=30, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 127, str(exc)
        if proc.returncode:
            return proc.returncode, (proc.stderr or proc.stdout).strip()
        return 0, proc.stdout
    return run


def migrate_enabled(run, say, warn) -> None:
    rc, out = run(["gsettings", "get", "org.gnome.shell",
                   "enabled-extensions"])
    if rc:
        warn(f"enabled-extensions not read: {out}")
        return
    try:
        new = plan_enabled(parse_strv(out))
    except (ValueError, SyntaxError, TypeError) as exc:
        warn(f"enabled-extensions not understood: {exc}")
        return
    if new is None:
        return
    rc, err = run(["gsettings", "set", "org.gnome.shell",
                   "enabled-extensions", format_strv(new)])
    if rc:
        warn(f"enabled-extensions not written: {err}")
        return
    say(f"enabled-extensions: {LEGACY_UUID} replaced by {NEW_UUID}")


def migrate_dconf(run, say, warn) -> None:
    rc_old, old = run(["dconf", "dump", LEGACY_DCONF])
    rc_new, new = run(["dconf", "dump", NEW_DCONF]) if not rc_old \
        else (rc_old, old)
    if rc_old or rc_new:
        warn(f"dconf not read: {old if rc_old else new}")
        return
    if not plan_dconf(old, new):
        return
    rc, err = run(["dconf", "load", NEW_DCONF], stdin=old)
    if rc:
        warn(f"dconf not written: {err}")
        return
    say(f"dconf: {LEGACY_DCONF} copied to {NEW_DCONF}")


def migrate_data_dirs(bases: list[Path], say, warn) -> None:
    for base in bases:
        src, dst = base / LEGACY_DIR, base / NEW_DIR
        action = plan_data_dir(src, dst)
        if action == "move":
            try:
                os.rename(src, dst)
            except OSError as exc:
                warn(f"{src} not moved: {exc}")
                continue
            say(f"{src} moved to {dst}")
        elif action == "conflict":
            warn(f"{src} and {dst} both exist, both kept; once logged out "
                 f"of the old extension, merge what is needed from {src} "
                 f"into {dst} and remove {src}")


def remove_legacy_extensions(ext_dir: Path, say, warn) -> None:
    if not ext_dir.is_dir():
        return
    names = [entry.name for entry in ext_dir.iterdir()]
    for name in legacy_extension_entries(names):
        path = ext_dir / name
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
        except OSError as exc:
            warn(f"{path} not removed: {exc}")
            continue
        say(f"{path} removed")


def load_hooks_installer():
    spec = importlib.util.spec_from_file_location(
        "install_claude_hooks", HOOKS_INSTALLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrate_hooks(installer, say, warn) -> None:
    """Replace hook entries that run the old script with the new hook.

    ``installer`` is the hooks installer module; its SETTINGS, HOOK_PATH,
    remove, install, backup and write do the work, so the file is backed
    up and rewritten atomically the same way a manual install does.
    """
    settings = installer.SETTINGS
    if not settings.exists():
        return
    try:
        text = settings.read_text(encoding="utf-8")
        original = json.loads(text)
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"{settings} not read: {exc}")
        return
    legacy = legacy_hook_commands(data)
    if not legacy:
        return
    for command in legacy:
        installer.remove(data, command, events=tuple(data.get("hooks", {})))
    installer.install(data, str(installer.HOOK_PATH))
    try:
        installer.backup(original)
        installer.write(data)
    except OSError as exc:
        warn(f"{settings} not written: {exc}")
        return
    say(f"Claude hooks: {len(legacy)} legacy command(s) replaced in "
        f"{settings}")


def steps(env: dict, home: Path, say, warn) -> list:
    """The migration steps as (name, callable) pairs, in the order to run.

    The old writers are stopped first (hook, then extension through the
    session bus); the files they write are moved afterwards. Without a
    session bus the bus steps are replaced by one line saying so.
    """
    def hooks() -> None:
        migrate_hooks(load_hooks_installer(), say, warn)

    def no_bus() -> None:
        say("no session bus: enabled-extensions and dconf are left for "
            "the next run")

    bus_env = session_bus_env(env)
    if bus_env is None:
        bus_steps = [("session bus", no_bus)]
    else:
        run = make_runner(bus_env)
        bus_steps = [
            ("enabled-extensions", lambda: migrate_enabled(run, say, warn)),
            ("dconf", lambda: migrate_dconf(run, say, warn)),
        ]
    return [
        ("Claude hooks", hooks),
        *bus_steps,
        ("extensions", lambda: remove_legacy_extensions(
            extensions_dir(env, home), say, warn)),
        ("data directories", lambda: migrate_data_dirs(
            xdg_bases(env, home), say, warn)),
    ]


def main() -> int:
    env = dict(os.environ)
    home = Path(env.get("HOME") or Path.home())

    def say(msg: str) -> None:
        print(f"migrate: {msg}")

    def warn(msg: str) -> None:
        print(f"migrate: warning: {msg}", file=sys.stderr)

    for name, step in steps(env, home, say, warn):
        try:
            step()
        except Exception as exc:  # the install must go on whatever happens
            warn(f"{name} not migrated: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
