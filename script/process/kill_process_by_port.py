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

Une cible au-dessus du processus qui écoute est arrêtée avec toute sa
descendance : bash ne relaie pas SIGTERM à son enfant, et un run.sh tué
seul laisserait Odoo orphelin, le port toujours tenu. Un processus placé
dans une unité systemd *.service est refusé : l'unité peut le relancer
(Restart=always). L'outil nomme l'unité et la commande systemctl qui
l'arrête, à n'employer que si cette unité est bien le service d'Odoo.

Après SIGTERM, l'arrêt propre d'Odoo peut traîner — il attend ses requêtes
et ses threads : l'outil attend que le port se libère, et propose SIGKILL
s'il reste tenu, sur les seuls arbres arrêtés au premier passage.
"""

import argparse
import os
import re
import sys
import time

import psutil

# Les programmes qui forment l'exécution d'Odoo : odoo-bin, le script
# console « odoo » (aussi le module de « python -m odoo »), et les deux
# scripts qui les enveloppent. Comparés au NOM du programme exécuté (voir
# `executed_program`), pour reconnaître « ./run.sh » comme « /chemin/run.sh »
# ou « bash run.sh ».
ODOO_EXECUTION_NAMES = {"odoo-bin", "odoo", "odoo_bin.sh", "run.sh"}

# Les interpréteurs et lanceurs qui exécutent le programme nommé après leurs
# options : le programme est alors le premier argument qui n'est pas une
# option. « coverage » prend en plus la sous-commande « run ».
INTERPRETER_RE = re.compile(r"^(?:(?:ba|da|z|k)?sh|python[0-9.]*)$")
LAUNCHER_NAMES = {"coverage", "debugpy"}

# Les options de ces interpréteurs et lanceurs qui consomment l'argument
# suivant : sans elles, la valeur de « --listen 5678 » passerait pour le
# programme. Une forme « --option=valeur » ne consomme rien.
OPTIONS_WITH_VALUE = {
    # python
    "-W",
    "-X",
    # bash
    "-o",
    "-O",
    "+O",
    # debugpy
    "--listen",
    "--connect",
    "--log-to",
    # coverage run
    "--rcfile",
    "--source",
    "--include",
    "--omit",
    "--context",
    "--data-file",
    "--concurrency",
}

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
    "sshd-session",
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
    "code-oss",
    "codium",
    "electron",
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


def executed_program(args):
    """Le nom (basename) du programme qu'exécute la ligne de commande `args`.

    C'est argv[0], sauf pour un interpréteur ou un lanceur : leurs options
    sont sautées, « -m module » rend le module, et le programme est le
    premier argument restant. Les arguments qui le suivent sont les SIENS et
    ne sont jamais lus : « terminal ./run.sh » exécute « terminal ». Rend None
    pour une ligne vide ou un code passé par « -c »."""
    i = 0
    while i < len(args):
        name = os.path.basename(args[i])
        i += 1
        if name == "coverage" and i < len(args) and args[i] == "run":
            i += 1
        elif not (INTERPRETER_RE.match(name) or name in LAUNCHER_NAMES):
            return name
        while i < len(args) and args[i][:1] in ("-", "+"):
            opt = args[i]
            i += 1
            if opt in ("-m", "--"):
                break
            if opt == "-c":
                return None
            if opt in OPTIONS_WITH_VALUE or opt.startswith("--configure-"):
                i += 1
    return None


def is_odoo_execution(p: psutil.Process) -> bool:
    """Le processus fait-il partie de l'exécution d'Odoo ?"""
    try:
        args = p.cmdline()
    except psutil.Error:
        return False
    return executed_program(args) in ODOO_EXECUTION_NAMES


def service_of_cgroup(text):
    """(unité, est_utilisateur) si le contenu de /proc/<pid>/cgroup place le
    processus dans une unité systemd *.service, sinon None.

    Lit la hiérarchie unifiée (« 0::/chemin ») ou celle nommée systemd
    (« N:name=systemd:/chemin ») ; seul le DERNIER élément du chemin compte :
    une session de bureau vit sous l'unité du gestionnaire de l'utilisateur,
    mais dans un .scope. Un terminal ou un multiplexeur lancé comme service
    (son nom est dans PROTECTED_NAMES) héberge des shells, il ne supervise
    pas Odoo."""
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3 or parts[1] not in ("", "name=systemd"):
            continue
        unit = parts[2].rstrip("/").rsplit("/", 1)[-1]
        if not unit.endswith(".service") or unit.startswith("user@"):
            continue
        if unit[: -len(".service")] in PROTECTED_NAMES:
            continue
        return unit, "/user@" in parts[2]
    return None


def systemd_service(pid: int):
    """`service_of_cgroup` appliqué au processus `pid` ; None si son
    /proc/<pid>/cgroup est illisible (processus disparu, autre système)."""
    try:
        with open(f"/proc/{pid}/cgroup") as fh:
            return service_of_cgroup(fh.read())
    except OSError:
        return None


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


def tree_of(root: psutil.Process):
    """`root` et tous ses descendants, les descendants d'abord. Un `root`
    disparu entre-temps rend sa seule entrée : le signal l'ignorera."""
    try:
        children = root.children(recursive=True)
    except psutil.Error:
        children = []
    return children + [root]


def stop_procs(procs, force: bool):
    """Signale chaque processus de `procs`, puis attend au plus 3 s la fin
    de ceux qui ont reçu le signal.

    Rend (encore_vivants, refusés), deux listes disjointes : un processus
    déjà disparu est ignoré, un refus de permission est collecté pour être
    rapporté, pas avalé, et n'est pas attendu puisqu'il n'a rien reçu."""
    denied = []
    signalled = []
    for p in procs:
        try:
            kill_process(p, force=force)
        except psutil.AccessDenied:
            denied.append(p)
            continue
        except psutil.Error:
            pass
        signalled.append(p)
    _gone, alive = psutil.wait_procs(signalled, timeout=3)
    return alive, denied


def report(alive, denied):
    """Affiche les refus de permission sur stderr, puis les survivants."""
    for p in denied:
        print(
            f"AccessDenied: {proc_desc(p)} (run the script with sudo).",
            file=sys.stderr,
        )
    for p in alive:
        print(f"Still running: {proc_desc(p)}")


def unique(procs):
    """`procs` sans doublon de pid, dans l'ordre."""
    seen = set()
    result = []
    for p in procs:
        if p.pid not in seen:
            seen.add(p.pid)
            result.append(p)
    return result


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
        description="Free a TCP port by stopping the Odoo execution that"
        " listens on it: the highest recognized odoo-bin, odoo_bin.sh or"
        " run.sh above the listener, with all its children."
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
        help="Also stop the children of the target when the target is the"
        " listener itself. A target above the listener (run.sh,"
        " odoo_bin.sh) is always stopped with all its children: bash does"
        " not forward SIGTERM, and Odoo would be left holding the port.",
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
    # Les processus que le premier passage signale, cibles et descendants :
    # le second passage (SIGKILL) ne force qu'eux et leur descendance.
    stopped = []
    for pid in pids:
        chain = get_ancestry(pid)
        if not chain:
            continue
        target, _ancestors = choose_target(chain, args.parent_depth)
        # psutil rapporte un seul pid par socket, même quand les workers
        # d'Odoo en héritent ; deux sockets distincts (IPv4 et IPv6) peuvent
        # toutefois mener à la même cible, qui n'est arrêtée qu'une fois.
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
        service = systemd_service(pid)
        if service:
            unit, user = service
            scope = " --user" if user else ""
            print(
                f"Refused: pid={pid} runs under the systemd unit {unit},"
                " which may restart it. If this unit is the Odoo service,"
                f" stop it with: systemctl{scope} stop {unit}"
            )
            continue
        recognized = is_odoo_execution(target)
        if not recognized:
            print(
                "Warning: the target is not recognized as an Odoo"
                " execution (odoo-bin, odoo, odoo_bin.sh, run.sh)."
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
        whole_tree = args.kill_tree or target.pid != pid
        procs = tree_of(target) if whole_tree else [target]
        stopped.extend(procs)
        tree = " + children (tree)" if whole_tree else ""
        print(f"Target: pid={target.pid} ({action}){tree}")
        if args.dry_run:
            for p in procs:
                print(f"  would stop {proc_desc(p)}")
            continue
        report(*stop_procs(procs, force=args.force))

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
    # Seuls les arbres confirmés au premier passage sont forcés, avec la
    # descendance apparue depuis : un maître tué par SIGKILL laisserait ses
    # workers tenir le socket dont ils ont hérité. Un écouteur hors de ces
    # arbres — refusé, annulé — est signalé et laissé en place.
    forced = unique(q for p in stopped if p.is_running() for q in tree_of(p))
    forced_pids = {p.pid for p in forced}
    for pid in find_listeners(args.port):
        if pid not in forced_pids:
            print(f"Listener pid={pid} was not confirmed: left alone.")
    report(*stop_procs(forced, force=True))
    if wait_port_free(args.port, GRACE_SECONDS):
        print(f"Port {args.port} is free.")
        return 0
    print(f"Port {args.port} is still held.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
