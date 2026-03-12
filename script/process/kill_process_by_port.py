#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
import argparse
import sys

import psutil

WRAPPER_SCRIPT_NAMES = ["./odoo_bin.sh", "./run.sh"]

# Processes that must never be killed — killing these
# can crash the desktop session or the system.
PROTECTED_NAMES = {
    "systemd",
    "init",
    "gnome-session",
    "gnome-session-binary",
    "gnome-shell",
    "gdm",
    "gdm3",
    "gdm-session-worker",
    "lightdm",
    "sddm",
    "Xorg",
    "Xwayland",
    "plasmashell",
    "kwin_wayland",
    "kwin_x11",
    "loginctl",
    "login",
    "sshd",
    "tmux: server",
}


def proc_desc(p: psutil.Process) -> str:
    try:
        cmd = " ".join(p.cmdline()) if p.cmdline() else p.name()
        return f"pid={p.pid} user={p.username()} name={p.name()} cmd={cmd}"
    except psutil.Error:
        return f"pid={p.pid}"


def get_ancestry(pid: int):
    """
    Returns list of psutil.Process from child -> parent -> ... until PID 1 or missing.
    """
    chain = []
    try:
        p = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return chain

    while True:
        chain.append(p)
        try:
            ppid = p.ppid()
        except psutil.Error:
            break
        if ppid <= 0 or ppid == p.pid:
            break
        try:
            p = psutil.Process(ppid)
        except psutil.NoSuchProcess:
            break
        if p.pid == 1:
            chain.append(p)
            break
    return chain


def choose_target(chain, parent_depth):
    """
    Decide which process to kill.
    Default: kill the highest ancestor before PID 1 (so not systemd).
    """
    if not chain:
        return None

    ancestors = []
    for proc in chain:
        ancestors.append(proc)
        for wrapper in WRAPPER_SCRIPT_NAMES:
            if wrapper in proc.cmdline():
                return proc, ancestors
    return chain[parent_depth - 1], [chain[parent_depth - 1]]


def kill_process(p: psutil.Process, force: bool):
    if force:
        p.kill()
    else:
        p.terminate()


def kill_tree(root: psutil.Process, force: bool):
    """
    Kill root and all its children (best-effort).
    """
    children = root.children(recursive=True)
    # terminate children first
    for ch in children:
        try:
            kill_process(ch, force=force)
        except psutil.Error:
            pass
    try:
        kill_process(root, force=force)
    except psutil.Error:
        pass

    # wait a bit
    gone, alive = psutil.wait_procs(children + [root], timeout=3)
    return alive


def find_listeners(port: int):
    pids = set()
    for c in psutil.net_connections(kind="tcp"):
        if (
            c.laddr
            and c.laddr.port == port
            and c.status == psutil.CONN_LISTEN
            and c.pid
        ):
            pids.add(c.pid)
    return sorted(pids)


def main():
    ap = argparse.ArgumentParser(
        description="Free a TCP port by killing the parent (or process tree) of the listener."
    )
    ap.add_argument("port", type=int, help="TCP port (1-65535)")
    ap.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be killed, do nothing",
    )
    ap.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Use SIGKILL instead of SIGTERM",
    )
    ap.add_argument(
        "--kill-tree",
        action="store_true",
        help="Kill target and all its children recursively",
    )
    ap.add_argument(
        "--nb_parent",
        dest="parent_depth",
        type=int,
        default=1,
        help="Kill parent too",
    )
    ap.add_argument(
        "--automatic",
        action="store_true",
        help="Ignore ask confirmation before killing",
    )
    args = ap.parse_args()

    if not (1 <= args.port <= 65535):
        print("Invalid port (1-65535).", file=sys.stderr)
        return 2

    pids = find_listeners(args.port)
    if not pids:
        print(f"No process listening on port {args.port}.")
        return 1

    for pid in pids:
        chain = get_ancestry(pid)
        if not chain:
            continue

        target, target_chain = choose_target(chain, args.parent_depth)

        print(f"\nListener PID {pid} ancestry:")
        for i, p in enumerate(chain):
            prefix = " " + ("-> " if p == target else "  ")
            print(f"[{i}]" + prefix + proc_desc(p))

        if target is None:
            continue

        if target.pid == 1:
            print(
                "Refused: target is PID 1 (systemd)."
                " Use systemctl to stop the service"
                " instead.",
            )
            continue
        if target.name() in PROTECTED_NAMES:
            print(
                f"Refused: process '{target.name()}' is protected and dangerous to kill.",
            )
            continue

        action = "KILL" if args.force else "TERM"

        if not args.automatic:
            has_response = False
            ignore_kill = False
            while not has_response and not ignore_kill:
                confirm = (
                    input(
                        f"Kill process at index {args.parent_depth} (enter) or enter "
                        f"index [0 to {len(chain) - 1}] of "
                        f"process to kill, (c/C) to cancel: \n"
                    )
                    .strip()
                    .lower()
                )
                if not confirm:
                    has_response = True
                    continue
                if confirm == "c":
                    ignore_kill = True
                    print("Cancel")
                    continue
                if confirm.isdigit():
                    has_response = True
                    target = chain[int(confirm)]
            if ignore_kill:
                continue

        if args.kill_tree:
            print(f"Target: pid={target.pid} ({action}) + children (tree)")
            if not args.dry_run:
                alive = kill_tree(target, force=args.force)
                if alive:
                    print(
                        "Still alive:",
                        ", ".join(str(p.pid) for p in alive),
                    )
        else:
            print(f"Target: pid={target.pid} ({action})")
            if not args.dry_run:
                try:
                    kill_process(target, force=args.force)
                except psutil.AccessDenied as e:
                    print(
                        f"AccessDenied: {e} (run the script with sudo).",
                        file=sys.stderr,
                    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
