#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Libère un port TCP en arrêtant l'exécution d'Odoo qui l'écoute.

La cible se choisit par ce qu'elle EST, et non par un nombre de niveaux :
depuis le processus qui écoute, on remonte tant que l'ancêtre fait partie
de l'exécution d'Odoo — odoo-bin, odoo_bin.sh, run.sh — et l'on s'arrête
au premier inconnu. Un nombre de niveaux ne sait pas ce qu'il désigne :
selon la façon dont Odoo a été lancé, deux niveaux plus haut se trouvent un
shell interactif, un terminal, un IDE, une VM, ou systemd pour un Odoo
devenu orphelin. On ne tue jamais au-delà de ce qu'on a reconnu.

Après SIGTERM, l'arrêt propre d'Odoo peut traîner — il attend ses requêtes
et ses threads : l'outil attend que le port se libère, et propose SIGKILL
s'il reste tenu.
"""

import argparse
import os
import sys
import time

import psutil

# Les noms de fichier qui, dans une ligne de commande, désignent l'exécution
# d'Odoo : le programme, et les deux scripts qui l'enveloppent. Comparés au
# NOM de chaque argument, pour reconnaître « ./run.sh » comme
# « /chemin/run.sh » ou « bash run.sh ».
ODOO_EXECUTION_NAMES = {"odoo-bin", "odoo_bin.sh", "run.sh"}
WRAPPER_SCRIPT_NAMES = ["./odoo_bin.sh", "./run.sh"]

# Secondes laissées à l'arrêt propre avant de proposer SIGKILL.
GRACE_SECONDS = 5

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
    # Terminaux, multiplexeurs, éditeurs et hyperviseurs : un Odoo lancé
    # depuis l'un d'eux l'a pour ancêtre, et le tuer fermerait bien plus
    # qu'Odoo.
    "tmux",
    "screen",
    "gnome-terminal-server",
    "konsole",
    "kitty",
    "alacritty",
    "xterm",
    "wezterm-gui",
    "foot",
    "code",
    "pycharm",
    "pycharm.sh",
    "java",
    "qemu-system-x86_64",
    "qemu-system-aarch64",
    "libvirtd",
    "virtqemud",
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


def is_protected(p: psutil.Process) -> bool:
    """PID 1, ou un processus dont la mort emporterait bien plus qu'Odoo."""
    if p.pid == 1:
        return True
    try:
        return p.name() in PROTECTED_NAMES
    except psutil.Error:
        return True


def is_odoo_execution(p: psutil.Process) -> bool:
    """Le processus fait-il partie de l'exécution d'Odoo ?"""
    try:
        args = p.cmdline()
    except psutil.Error:
        return False
    return any(os.path.basename(a) in ODOO_EXECUTION_NAMES for a in args)


def choose_target(chain, parent_depth=None):
    """(cible, ancêtres jusqu'à elle), ou None pour une chaîne vide.

    Sans `parent_depth` : le plus haut ancêtre qui fait encore partie de
    l'exécution d'Odoo, la remontée s'arrêtant au premier inconnu ou au
    premier protégé. Pour un Odoo orphelin, c'est lui-même ; lancé par
    run.sh, c'est run.sh. Si le processus qui écoute n'est pas reconnu, il
    reste la cible — `is_odoo_execution` le dit, et l'appelant demande.

    Avec `parent_depth` : ce nombre de parents au-dessus du processus qui
    écoute (0 = lui-même), mais jamais au-delà d'un protégé."""
    if not chain:
        return None
    if parent_depth is None:
        index = 0
        for i, proc in enumerate(chain):
            if is_protected(proc) or not is_odoo_execution(proc):
                break
            index = i
    else:
        index = 0
        for i, proc in enumerate(chain[: max(0, parent_depth) + 1]):
            if is_protected(proc):
                break
            index = i
    return chain[index], chain[: index + 1]


def wait_port_free(port: int, seconds: float) -> bool:
    """Attend que plus rien n'écoute sur `port`, au plus `seconds`."""
    fin = time.monotonic() + seconds
    while time.monotonic() < fin:
        if not find_listeners(port):
            return True
        time.sleep(0.2)
    return not find_listeners(port)


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


def ask_target(chain, default):
    """La cible confirmée : Entrée garde `default`, un index en choisit une
    autre, « c » annule (None). Un index protégé est refusé et redemandé :
    la question reste posée tant que la réponse n'est pas sûre."""
    default_index = chain.index(default)
    while True:
        reply = (
            input(
                f"Kill process at index {default_index} (enter), or enter"
                f" an index [0 to {len(chain) - 1}], or (c/C) to cancel: \n"
            )
            .strip()
            .lower()
        )
        if not reply:
            return default
        if reply == "c":
            return None
        if reply.isdigit() and int(reply) < len(chain):
            choice = chain[int(reply)]
            if is_protected(choice):
                print(f"Refused: pid={choice.pid} is protected.")
                continue
            return choice
        print("Invalid answer.")


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
        default=None,
        help="Parents above the listener to target (0 = the listener"
        " itself), never past a protected process. By default, the"
        " highest ancestor recognized as part of the Odoo execution.",
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

    action = "KILL" if args.force else "TERM"
    done = set()
    for pid in pids:
        chain = get_ancestry(pid)
        if not chain:
            continue
        target, _ancestors = choose_target(chain, args.parent_depth)
        # Plusieurs processus d'un même Odoo écoutent le port (le maître et
        # ses workers) : leur cible commune n'est arrêtée qu'une fois.
        if target.pid in done:
            continue

        print(f"\nListener PID {pid} ancestry:")
        for i, p in enumerate(chain):
            mark = "-> " if p == target else "   "
            note = "  (protected)" if is_protected(p) else ""
            print(f"[{i}] {mark}{proc_desc(p)}{note}")

        if is_protected(target):
            print(
                f"Refused: the listener pid={target.pid} is itself"
                " protected. Use systemctl to stop a service instead."
            )
            continue
        recognized = is_odoo_execution(target)
        if not recognized:
            print(
                "Warning: the target is not recognized as an Odoo"
                " execution (odoo-bin, odoo_bin.sh, run.sh)."
            )
            if args.automatic:
                print("Refused in --automatic mode: confirm it by hand.")
                continue

        if not args.automatic:
            target = ask_target(chain, target)
            if target is None:
                print("Cancel")
                continue

        done.add(target.pid)
        tree = " + children (tree)" if args.kill_tree else ""
        print(f"Target: pid={target.pid} ({action}){tree}")
        if args.dry_run:
            continue
        try:
            if args.kill_tree:
                kill_tree(target, force=args.force)
            else:
                kill_process(target, force=args.force)
        except psutil.AccessDenied as e:
            print(
                f"AccessDenied: {e} (run the script with sudo).",
                file=sys.stderr,
            )
            continue

    if args.dry_run or not done:
        return 0
    if wait_port_free(args.port, GRACE_SECONDS):
        print(f"Port {args.port} is free.")
        return 0
    print(
        f"Port {args.port} is still held after {GRACE_SECONDS} s:"
        " Odoo's graceful shutdown may be waiting on requests or threads."
    )
    if args.force or args.automatic:
        return 1
    confirm = input("Force it (SIGKILL)? [y/N] ").strip().lower()
    if confirm not in ("y", "yes", "o", "oui"):
        return 1
    # Aussi prudent que le premier passage : seuls une exécution d'Odoo ou
    # un processus déjà confirmé sont forcés.
    for pid in find_listeners(args.port):
        choice = choose_target(get_ancestry(pid), args.parent_depth)
        if not choice or is_protected(choice[0]):
            continue
        if is_odoo_execution(choice[0]) or choice[0].pid in done:
            kill_tree(choice[0], force=True)
    if wait_port_free(args.port, GRACE_SECONDS):
        print(f"Port {args.port} is free.")
        return 0
    print(f"Port {args.port} is still held.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
