#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
import argparse
import sys

import psutil

STOP_PARENT_KILL = ["./odoo_bin.sh", "./run.sh"]


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


def choose_target(chain, nb_parent):
    """
    Decide which process to kill.
    Default: kill the highest ancestor before PID 1 (so not systemd).
    """
    if not chain:
        return None

    lst_chain_parent = []
    for pid in chain:
        lst_chain_parent.append(pid)
        for str_to_stop in STOP_PARENT_KILL:
            if str_to_stop in pid.cmdline():
                return pid, lst_chain_parent
    return chain[nb_parent - 1], [chain[nb_parent - 1]]


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
        type=int,
        default=1,
        help="Kill parent too",
    )
    args = ap.parse_args()

    if not (1 <= args.port <= 65535):
        print("Port invalide (1-65535).", file=sys.stderr)
        return 2

    pids = find_listeners(args.port)
    if not pids:
        print(f"Aucun process en LISTEN sur {args.port}.")
        return 1

    for pid in pids:
        chain = get_ancestry(pid)
        if not chain:
            continue

        target, lst_target = choose_target(chain, args.nb_parent)

        print(f"\nListener PID {pid} ancestry:")
        for i, p in enumerate(chain):
            prefix = "  " + ("-> " if p == target else "   ")
            print(prefix + proc_desc(p))

        if target is None:
            continue

        if target.pid == 1 and not args.allow_pid1:
            print(
                "Refus: la cible est PID 1 (systemd). Utilise plutôt systemctl pour arrêter le service.",
                file=sys.stderr,
            )
            continue

        action = "KILL" if args.force else "TERM"
        if args.kill_tree:
            print(f"Target: pid={target.pid} ({action}) + children (tree)")
            if not args.dry_run:
                alive = kill_tree(target, force=args.force)
                if alive:
                    print(
                        "Toujours vivants:",
                        ", ".join(str(p.pid) for p in alive),
                        file=sys.stderr,
                    )
        else:
            print(f"Target: pid={target.pid} ({action})")
            if not args.dry_run:
                try:
                    kill_process(target, force=args.force)
                except psutil.AccessDenied as e:
                    print(
                        f"AccessDenied: {e} (lance le script avec sudo).",
                        file=sys.stderr,
                    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
