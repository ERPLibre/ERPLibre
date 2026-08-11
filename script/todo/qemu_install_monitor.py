#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Dashboard Textual : suivi des installations ERPLibre parallèles sur VM.

Principe « détachable » : chaque installation tourne dans un processus
DÉTACHÉ (setsid) qui écrit un fichier log et, à la fin, un marqueur
« __ERPLIBRE_EXIT__ <code> ». Ce module ne fait que VISUALISER ces fichiers :
quitter le dashboard n'arrête rien, on peut le rouvrir pour ré-attacher.

- launch_installs(...) : lance les process détachés + écrit un manifeste JSON.
- run_monitor(manifest_path) : ouvre le dashboard Textual sur un manifeste.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import time
from pathlib import Path

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


EXIT_MARKER = "__ERPLIBRE_EXIT__"
SSH_OPTS = (
    "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
    "-o ConnectTimeout=8"
)


def session_dir() -> Path:
    """Répertoire des logs/manifestes d'installation (créé au besoin)."""
    base = Path(os.path.expanduser("~/.erplibre/qemu-install"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def list_install_runs() -> list:
    """Runs d'installation passés (chacun a un session.json), TRIÉS du plus
    récent au plus ancien. Chaque entrée : dict {label, manifest, mtime,
    vms, branch}. Permet de ROUVRIR le suivi d'un run (le dashboard s'étant
    fermé sur un bug, on reprend l'analyse)."""
    runs = []
    for d in sorted(session_dir().glob("*/"), reverse=True):
        manifest = d / "session.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text())
            mtime = manifest.stat().st_mtime
        except (OSError, ValueError):
            continue
        runs.append(
            {
                "label": d.name.rstrip("/"),
                "manifest": str(manifest),
                "mtime": mtime,
                "vms": data.get("vms", []),
                "branch": data.get("branch", ""),
            }
        )
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs


def _launch_one(
    ip: str, remote_cmd: str, log_path: str, name: str = ""
) -> None:
    """Lance une install SSH DÉTACHÉE : attend le sshd, exécute, journalise
    la sortie puis écrit le marqueur de fin avec le code de sortie."""
    # Sonde de disponibilité : on attend que sshd réponde ET que cloud-init
    # soit TERMINÉ, via des connexions COURTES successives (jusqu'à ~20 min :
    # une architecture ÉMULÉE, s390x/arm64 sur hôte x86, boote lentement).
    # Au 1er boot, cloud-init régénère les clés d'hôte et REDÉMARRE sshd : une
    # session SSH longue (ex. « cloud-init status --wait ») serait alors tuée
    # (« Connection closed by remote host », exit 255 — cas Fedora). Chaque
    # itération étant une connexion neuve, un redémarrage de sshd ne casse que
    # la tentative en cours. On imprime toujours l'état (|| true) pour matcher
    # sur le TEXTE, « status: running » n'ayant pas de code de sortie fiable.
    ci_probe = (
        "if command -v cloud-init >/dev/null 2>&1; then "
        "cloud-init status 2>/dev/null || true; else echo nocloudinit; fi"
    )
    log_q = shlex.quote(log_path)
    # On écrit un message d'attente + un battement toutes les ~30 s : sinon le
    # log reste VIDE pendant tout le boot émulé et paraît « bloqué ».
    msg_wait = t("Waiting for the VM to start (boot + cloud-init)")
    msg_slow = t("(an emulated architecture can be slow; this is normal)")
    msg_ready = t("VM ready - starting the ERPLibre install")
    msg_novirsh = t(
        "WARNING libvirt unreachable: the IP will not be refreshed"
        " (libvirt group? re-login required)"
    )
    msg_moved = t("DHCP lease moved:")
    # L'IP est RÉSOLUE À CHAQUE TOUR, jamais figée. Au 1er boot la VM prend un
    # bail sous le nom par défaut de l'image, puis cloud-init pose le vrai nom
    # d'hôte et le client DHCP en redemande un AUTRE. L'adresse connue au
    # lancement devient donc morte en cours de route, et l'attente échouait
    # 20 minutes durant sur une VM parfaitement saine (vécu : bail .247 périmé
    # pendant que la VM vivait en .248).
    #
    # L'agent invité fait foi : il répond depuis l'intérieur, là où le bail
    # dnsmasq garde les deux adresses sans dire laquelle est vivante. « sudo -n »
    # car ce script tourne DÉTACHÉ : une demande de mot de passe le bloquerait
    # sans que personne ne la voie. Sans réponse, on garde l'adresse courante.
    # L'agent ne suffit PAS comme source unique : son paquet s'installe hors de
    # cloud-init pour ne pas retarder le démarrage, donc il arrive tard — et
    # pendant tout ce temps la ré-résolution ne renvoyait rien et gardait
    # l'adresse morte. C'est le défaut qui a fait échouer le premier correctif.
    #
    # Repli sur les baux : dnsmasq les garde tous les deux sans dire lequel est
    # vivant, on tranche donc en TESTANT le port 22 — le seul critère qui compte
    # ici, puisque c'est par là que l'installation passera. Le bail périmé ne
    # répond pas, le bon répond.
    # virsh SANS sudo d'abord. Ce script tourne détaché, sans tty : « sudo -n »
    # y échoue dès que l'hôte exige une authentification interactive — vécu sur
    # erplibre01 (« sudo-rs: interactive authentication is required »), et la
    # ré-résolution restait alors muette sans laisser la moindre trace.
    # Appartenir au groupe libvirt suffit pour joindre qemu:///system, ce que
    # « deploy_qemu.py --setup-host » configure déjà. sudo -n reste en repli
    # pour les hôtes où le groupe manque.
    name_q = shlex.quote(name) if name else ""
    vsh = (
        'vsh() { virsh --connect qemu:///system "$@" 2>/dev/null '
        '|| sudo -n virsh --connect qemu:///system "$@" 2>/dev/null; }; '
    )
    # Deux trous rendaient cette ré-résolution incapable de rattraper une IP
    # qui bouge — le cas exact où elle sert :
    #
    # - « vsh » est muet des deux côtés. Quand libvirt est injoignable (hors du
    #   groupe libvirt, et « sudo -n » refusé faute de tty dans ce processus
    #   détaché), la ré-résolution ne renvoie JAMAIS rien : l'IP de départ est
    #   gardée jusqu'au bout sans qu'une seule ligne du log ne le dise.
    # - le repli sur les baux exigeait une réponse sur le port 22. Or dnsmasq
    #   ne garde qu'un bail par MAC : quand cloud-init pose le vrai nom d'hôte
    #   et que le client DHCP redemande, le bail DÉPLACE l'adresse. L'ancienne
    #   n'appartient plus à cette VM, mais on l'attendait quand même — et sshd
    #   n'y répondra jamais.
    refresh = (
        (
            f"raw=$(vsh domifaddr {name_q} --source lease); vrc=$?; "
            'if [ $vrc -ne 0 ] && [ -z "$vwarn" ]; then vwarn=1; '
            f"echo {shlex.quote('   ' + msg_novirsh)} >> {log_q}; fi; "
            "cands=$(echo \"$raw\" | grep -oE '([0-9]{1,3}\\.){3}[0-9]{1,3}' "
            "| grep -v '^127\\.'); "
            f"n=$(vsh domifaddr {name_q} --source agent "
            "| grep -oE '([0-9]{1,3}\\.){3}[0-9]{1,3}' "
            "| grep -v '^127\\.' | head -1); "
            'if [ -z "$n" ]; then '
            'for c in $cands; do '
            'timeout 2 bash -c "echo > /dev/tcp/$c/22" 2>/dev/null '
            '&& n="$c"; done; fi; '
            # Le bail ne mentionne plus l'adresse courante : elle est périmée,
            # on suit le bail sans attendre que sshd réponde.
            'if [ -z "$n" ] && [ -n "$cands" ] && '
            '! echo "$cands" | grep -Fqx "$ip"; then '
            'n=$(echo "$cands" | tail -1); '
            f'echo "   {msg_moved} $ip -> $n" >> {log_q}; fi; '
            '[ -n "$n" ] && ip="$n"; '
        )
        if name
        else ""
    )
    wrapper = (
        f"ip={shlex.quote(ip)}; "
        f"{vsh if name else ''}"
        f"echo {shlex.quote('== ' + msg_wait + ' ==')} >> {log_q}; "
        f"echo {shlex.quote('   ' + msg_slow)} >> {log_q}; "
        f"for i in $(seq 1 240); do "
        f"{refresh}"
        f'st=$(ssh {SSH_OPTS} -o BatchMode=yes "erplibre@$ip" '
        f"{shlex.quote(ci_probe)} 2>/dev/null); "
        f'case "$st" in '
        f"*done*|*disabled*|*error*|*degraded*|*nocloudinit*) break;; "
        f"esac; "
        f"if [ $((i % 6)) -eq 0 ]; then "
        f'echo "   ... $((i*5))s ($ip)" >> {log_q}; fi; '
        f"sleep 5; done; "
        f"echo {shlex.quote('== ' + msg_ready + ' ==')} >> {log_q}; "
        f'echo "   → $ip" >> {log_q}; '
        f'ssh {SSH_OPTS} "erplibre@$ip" {shlex.quote(remote_cmd)} '
        f">> {log_q} 2>&1; "
        f'echo "{EXIT_MARKER} $?" >> {log_q}'
    )
    # setsid -f : le process survit à la fermeture du menu / du dashboard.
    subprocess.Popen(
        ["setsid", "-f", "bash", "-c", wrapper],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _log_header(vm: dict, branch: str, when: str) -> str:
    """En-tête du log : date, VM, distribution, version, architecture, branche.
    Permet d'identifier l'installation d'un coup d'œil (et de ne jamais laisser
    le log vide pendant l'attente du boot)."""
    distro = vm.get("distro") or "?"
    version = vm.get("version") or ""
    arch = vm.get("arch") or "?"
    bar = "=" * 64
    return (
        f"{bar}\n"
        f"  ERPLibre — {t('installation')}\n"
        f"  Date         : {when}\n"
        f"  VM           : {vm['name']}\n"
        f"  Distribution : {distro} {version}\n"
        f"  Architecture : {arch}\n"
        f"  Branche      : {branch}\n"
        f"  IP           : {vm['ip']}\n"
        f"{bar}\n\n"
    )


def launch_installs(vms: list[dict], branch: str, remote_cmd: str) -> str:
    """vms : [{name, ip, distro?, version?, arch?}]. Lance chaque install
    détachée, écrit un manifeste et retourne son chemin. remote_cmd : script
    exécuté dans chaque VM."""
    sdir = session_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    logdir = sdir / stamp
    logdir.mkdir(parents=True, exist_ok=True)
    entries = []
    for vm in vms:
        log_path = str(logdir / f"{vm['name']}.log")
        # En-tête d'emblée (date/distro/version/arch) : le log n'est jamais
        # vide, l'utilisateur voit tout de suite QUOI s'installe.
        Path(log_path).write_text(_log_header(vm, branch, when))
        _launch_one(vm["ip"], remote_cmd, log_path, vm["name"])
        entries.append(
            {
                "name": vm["name"],
                "ip": vm["ip"],
                "distro": vm.get("distro"),
                "version": vm.get("version"),
                "arch": vm.get("arch"),
                "log": log_path,
                "ssh": f"ssh erplibre@{vm['ip']}",
            }
        )
    manifest = {
        "branch": branch,
        "started": time.time(),
        "vms": entries,
    }
    manifest_path = str(logdir / "session.json")
    Path(manifest_path).write_text(json.dumps(manifest, indent=2))
    return manifest_path


def read_status(log_path: str) -> tuple[str, int | None]:
    """(état, code) d'un log : pending / running / done / failed. Ne lit que
    la FIN du fichier (le marqueur de sortie est sur la dernière ligne) : lire
    tout le log de 30 VM chaque seconde saturait la boucle d'événements du TUI
    (lag, interface figée quand l'I/O ralentit)."""
    try:
        size = os.path.getsize(log_path)
        if size == 0:
            return "pending", None
        with open(log_path, "rb") as fh:
            if size > 4096:
                fh.seek(-4096, os.SEEK_END)
            tail = fh.read().decode(errors="replace")
    except OSError:
        return "pending", None
    if not tail.strip():
        return "pending", None
    for line in reversed(tail.splitlines()):
        if EXIT_MARKER in line:
            try:
                code = int(line.split()[-1])
            except ValueError:
                code = 1
            return ("done" if code == 0 else "failed"), code
    return "running", None


def run_progress(run: dict) -> dict:
    """Avancement d'un run : combien de VM tournent encore, et depuis quand
    plus rien n'a été écrit. `idle` sert à distinguer une install vivante d'un
    run laissé pour mort — le marqueur de sortie manque dans les deux cas."""
    active = final = 0
    latest = 0.0
    for vm in run.get("vms", []):
        log = vm.get("log") or ""
        state, _code = read_status(log)
        if state in ("done", "failed"):
            final += 1
        else:
            active += 1
        try:
            latest = max(latest, os.path.getmtime(log))
        except OSError:
            pass
    return {
        "active": active,
        "final": final,
        "total": active + final,
        "idle": (time.time() - latest) if latest else None,
    }


def active_run():
    """Le run le PLUS RÉCENT s'il a encore des VM en cours, sinon None.

    Les installs tournent détachées (`setsid -f`) : fermer le terminal laisse
    le travail se poursuivre mais fait perdre la seule vue dessus. On ne
    regarde que le dernier run — un run ancien resté sans marqueur de sortie
    signalerait éternellement une install fantôme."""
    runs = list_install_runs()
    if not runs:
        return None
    run = dict(runs[0])
    run.update(run_progress(run))
    return run if run["total"] and run["active"] else None


# Listes d'ignore reprises de script/test/run_parallel_test.py (erreurs/
# avertissements connus et bénins) : on réutilise la MÊME logique de détection
# que la suite de tests ERPLibre pour analyser les logs d'installation.
_LST_IGNORE_WARNING = (
    "have the same label:",
    "odoo.addons.code_generator.extractor_module_file: Ignore next error about"
    " ALTER TABLE DROP CONSTRAINT.",
)
_LST_IGNORE_ERROR = (
    "fetchmail_notify_error_to_sender",
    'odoo.sql_db: bad query: ALTER TABLE "db_backup" DROP CONSTRAINT'
    ' "db_backup_db_backup_name_unique"',
    'ERROR: constraint "db_backup_db_backup_name_unique" of relation'
    ' "db_backup" does not exist',
    'odoo.sql_db: bad query: ALTER TABLE "db_backup" DROP CONSTRAINT'
    ' "db_backup_db_backup_days_to_keep_positive"',
    'ERROR: constraint "db_backup_db_backup_days_to_keep_positive" of relation'
    ' "db_backup" does not exist',
    "odoo.addons.code_generator.extractor_module_file: Ignore next error about"
    " ALTER TABLE DROP CONSTRAINT.",
)


def scan_log_error_lines(log_path: str, cap: int = 500) -> tuple[list, list]:
    """(lignes_erreur, lignes_avertissement) d'un log, même détection que
    scan_log_errors mais on RETIENT les lignes (bornées à `cap`) pour les
    afficher. Chaque ligne est préfixée de son numéro (1-indexé)."""
    try:
        text = Path(log_path).read_text(errors="replace")
    except OSError:
        return [], []
    errs, warns = [], []
    for i, line in enumerate(text.splitlines(), 1):
        if EXIT_MARKER in line:
            continue
        low = line.lower()
        if (
            "error" in low
            and not any(ig in line for ig in _LST_IGNORE_ERROR)
            and len(errs) < cap
        ):
            errs.append(f"{i}: {line}")
        if (
            "warning" in low
            and not any(ig in line for ig in _LST_IGNORE_WARNING)
            and len(warns) < cap
        ):
            warns.append(f"{i}: {line}")
    return errs, warns


def scan_log_errors(log_path: str) -> tuple[int, int]:
    """(nb_erreurs, nb_avertissements) dans un log d'installation, en
    réutilisant la détection de la suite de tests ERPLibre : sous-chaîne
    « error »/« warning » (insensible à la casse) moins les listes d'ignore.
    Lit le fichier COMPLET (appelé une seule fois, à la complétion d'une VM).
    """
    try:
        text = Path(log_path).read_text(errors="replace")
    except OSError:
        return 0, 0
    nerr = nwarn = 0
    for line in text.splitlines():
        low = line.lower()
        if EXIT_MARKER in line:
            continue
        if "error" in low and not any(ig in line for ig in _LST_IGNORE_ERROR):
            nerr += 1
        if "warning" in low and not any(
            ig in line for ig in _LST_IGNORE_WARNING
        ):
            nwarn += 1
    return nerr, nwarn


def _port_open(ip: str, port: int = 8069, timeout: float = 0.5) -> bool:
    """Vrai si un TCP connect réussit (l'UI web Odoo écoute sur :8069)."""
    if not ip:
        return False
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _read_new(path: str, offset: int) -> tuple[str, int]:
    """Lit le log à partir de `offset` (lecture incrémentale). Renvoie
    (nouveau_texte, nouvel_offset). Bloquant -> à appeler dans un thread."""
    try:
        with open(path, "r", errors="replace") as fh:
            fh.seek(offset)
            data = fh.read()
            return data, fh.tell()
    except OSError:
        return "", offset


def _read_tail(
    path: str, max_bytes: int = 131072, max_lines: int = 1000
) -> tuple[str, int]:
    """Lit uniquement la FIN du log (dernier `max_bytes`, tronqué à
    `max_lines` lignes) et renvoie (texte, TAILLE TOTALE du fichier). Utilisé
    au CHANGEMENT de VM : lire+réafficher le fichier ENTIER (offset 0) gelait
    l'UI sur les gros logs (250 Ko / milliers de lignes). L'offset renvoyé =
    taille totale -> le suivi incrémental (_tick_log) continue depuis la fin.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(-max_bytes, os.SEEK_END)
            raw = fh.read()
        text = raw.decode(errors="replace")
        # Si on a coupé au milieu d'une ligne, jeter la 1re ligne partielle.
        if size > max_bytes and "\n" in text:
            text = text.split("\n", 1)[1]
        lines = text.splitlines()
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        return "\n".join(lines), size
    except OSError:
        return "", 0


# --------------------------------------------------------------------------- #
# Télémétrie, historique de durées (ETA), navigateur CLI
# --------------------------------------------------------------------------- #
def _stats_path() -> Path:
    """Fichier d'historique persistant des installations. DÉDIÉ dans
    .venv.erplibre du dépôt (repli sur ~/.erplibre si le venv est absent)."""
    try:
        venv = Path(__file__).resolve().parents[2] / ".venv.erplibre"
        venv.mkdir(parents=True, exist_ok=True)
        return venv / "qemu_install_stats.json"
    except OSError:
        return session_dir() / "stats.json"


def load_stats() -> dict:
    try:
        return json.loads(_stats_path().read_text())
    except (OSError, ValueError):
        return {}


def record_duration(distro, version, arch, secs, ok=True) -> None:
    """Enregistre une install (distro + version + archi + durée + horodatage)
    dans l'historique, pour l'ETA et les moyennes par archi/distro. Garde les
    500 derniers runs.

    `ok=False` conserve la trace d'un ÉCHEC : sans elle aucun taux de réussite
    n'est calculable. Les échecs sont exclus des moyennes et de l'ETA (leur
    durée ne dit rien du temps d'une install qui aboutit)."""
    data = load_stats()
    runs = data.setdefault("runs", [])
    runs.append(
        {
            "distro": distro or "?",
            "version": version or "?",
            "arch": arch or "?",
            "seconds": int(secs),
            "ts": int(time.time()),
            "ok": bool(ok),
        }
    )
    data["runs"] = runs[-500:]
    try:
        _stats_path().write_text(json.dumps(data, ensure_ascii=False))
    except OSError:
        pass


def reset_stats() -> int:
    """Vide l'historique. Renvoie le nombre de runs effacés."""
    count = len(all_runs())
    try:
        _stats_path().write_text(json.dumps({"runs": []}))
    except OSError:
        pass
    return count


def all_runs(stats=None):
    """Tous les runs, succès ET échecs."""
    return (stats or load_stats()).get("runs", []) or []


def _runs(stats=None):
    """Runs RÉUSSIS seulement : base des moyennes et de l'ETA.

    Les entrées écrites avant l'ajout du champ « ok » n'en ont pas ; elles
    étaient forcément des succès (seuls ceux-là étaient enregistrés).
    """
    return [r for r in all_runs(stats) if r.get("ok", True)]


def stats_summary(stats=None):
    """Chiffres globaux de l'historique d'installation.

    Renvoie un dict vide quand rien n'a encore été enregistré, pour que
    l'appelant distingue « aucune donnée » de « zéro seconde »."""
    runs = all_runs(stats)
    if not runs:
        return {}
    ok = [r for r in runs if r.get("ok", True)]
    secs = sorted(r["seconds"] for r in ok)
    lst_ts = [r.get("ts", 0) for r in runs if r.get("ts")]
    return {
        "total": len(runs),
        "ok": len(ok),
        "failed": len(runs) - len(ok),
        "first_ts": min(lst_ts) if lst_ts else 0,
        "last_ts": max(lst_ts) if lst_ts else 0,
        "median": secs[len(secs) // 2] if secs else 0,
        "min": secs[0] if secs else 0,
        "max": secs[-1] if secs else 0,
        "total_secs": sum(secs),
    }


def stats_by(field, stats=None):
    """Agrège par « distro », « arch » ou « distro version ».

    Renvoie [(clé, nb_réussis, moyenne_secondes, nb_échecs)] trié du plus
    utilisé au moins utilisé."""
    dct = {}
    for run in all_runs(stats):
        if field == "version":
            key = f"{run.get('distro', '?')} {run.get('version', '?')}"
        else:
            key = run.get(field, "?")
        entry = dct.setdefault(key, {"secs": [], "failed": 0})
        if run.get("ok", True):
            entry["secs"].append(run["seconds"])
        else:
            entry["failed"] += 1
    lst = [
        (
            key,
            len(e["secs"]),
            int(sum(e["secs"]) / len(e["secs"])) if e["secs"] else 0,
            e["failed"],
        )
        for key, e in dct.items()
    ]
    return sorted(lst, key=lambda row: (-(row[1] + row[3]), row[0]))


def eta_reference(stats, arch):
    """Durée d'install de RÉFÉRENCE (médiane) pour cette archi ; repli toutes
    archis confondues. None si aucun historique."""
    runs = _runs(stats)
    secs = [r["seconds"] for r in runs if r.get("arch") == arch]
    if not secs:
        secs = [r["seconds"] for r in runs]
    if not secs:
        return None
    s = sorted(secs)
    return s[len(s) // 2]


def _avg(field, value, stats=None):
    secs = [r["seconds"] for r in _runs(stats) if r.get(field) == value]
    return (sum(secs) / len(secs)) if secs else None


def avg_by_arch(arch, stats=None):
    """(moyenne_secondes, nb_runs) pour cette archi, ou (None, 0)."""
    secs = [r["seconds"] for r in _runs(stats) if r.get("arch") == arch]
    return (sum(secs) / len(secs), len(secs)) if secs else (None, 0)


def avg_by_distro(distro, stats=None):
    """(moyenne_secondes, nb_runs) pour cette distro, ou (None, 0)."""
    secs = [r["seconds"] for r in _runs(stats) if r.get("distro") == distro]
    return (sum(secs) / len(secs), len(secs)) if secs else (None, 0)


def avg_by_version(distro, version, stats=None):
    """(moyenne_secondes, nb_runs) pour cette (distro, version), ou (None, 0)."""
    secs = [
        r["seconds"]
        for r in _runs(stats)
        if r.get("distro") == distro and r.get("version") == version
    ]
    return (sum(secs) / len(secs), len(secs)) if secs else (None, 0)


def last_run(stats=None):
    """Dernier run enregistré (dict) ou None."""
    runs = _runs(stats)
    return runs[-1] if runs else None


def _fmt_size(nbytes) -> str:
    """Octets -> « 1.2G » / « 345M » / « 12K »."""
    if nbytes is None:
        return "-"
    for unit, div in (("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20)):
        if nbytes >= div:
            return f"{nbytes / div:.1f}{unit}"
    return f"{nbytes // 1024}K"


def _fmt_secs(secs) -> str:
    """Secondes -> « 45s » / « 12m » / « 1h05 »."""
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}"


def vm_disk_path(vm: dict) -> str:
    """Chemin du qcow2 de la VM (défaut libvirt si non fourni)."""
    return vm.get("disk") or f"/var/lib/libvirt/images/{vm['name']}.qcow2"


def disk_actual_size(path: str) -> int | None:
    """Taille RÉELLEMENT occupée du qcow2 (creux) via st_blocks."""
    try:
        st = os.stat(path)
        return int(getattr(st, "st_blocks", 0)) * 512
    except OSError:
        return None


# Navigateurs web en ligne de commande, par ordre de préférence (rendu JS
# d'abord — utile pour l'UI Odoo — puis navigateurs texte classiques).
CLI_BROWSERS = ("browsh", "carbonyl", "w3m", "links", "elinks", "lynx")


def cli_browser() -> str | None:
    """Premier navigateur CLI disponible dans le PATH, sinon None."""
    for name in CLI_BROWSERS:
        if shutil.which(name):
            return name
    return None


def _os_id() -> str:
    """ID de la distribution hôte (/etc/os-release), ex. « ubuntu », « fedora »."""
    try:
        for line in open("/etc/os-release", encoding="utf-8"):
            if line.startswith("ID="):
                return line.split("=", 1)[1].strip().strip('"').lower()
    except OSError:
        pass
    return ""


# Navigateurs CLI installables via apt/dnf/pacman (nom de paquet = binaire).
# browsh/carbonyl ne sont pas dans les dépôts standard -> non proposés ici.
INSTALLABLE_BROWSERS = (
    ("w3m", "w3m — léger, rend un peu de HTML"),
    ("lynx", "lynx — navigateur texte"),
    ("links", "links — texte / graphique"),
    ("elinks", "elinks — texte, onglets"),
)


def browser_install_command(browser="w3m") -> list | None:
    """Commande d'installation du navigateur CLI `browser` adaptée à l'OS hôte :
    apt (Ubuntu/Debian), dnf (Fedora), pacman (Arch). None si gestionnaire
    inconnu."""
    apt = ["sudo", "apt-get", "install", "-y", browser]
    dnf = ["sudo", "dnf", "install", "-y", browser]
    pac = ["sudo", "pacman", "-S", "--needed", "--noconfirm", browser]
    by_id = {
        "ubuntu": apt,
        "debian": apt,
        "linuxmint": apt,
        "fedora": dnf,
        "arch": pac,
    }
    cmd = by_id.get(_os_id())
    if cmd:
        return cmd
    if shutil.which("apt-get"):
        return apt
    if shutil.which("dnf"):
        return dnf
    if shutil.which("pacman"):
        return pac
    return None


def virsh_ip(name: str) -> str:
    """Adresse ACTUELLE d'une VM, ou '' si indéterminable.

    Même logique que la sonde du wrapper détaché, et pour la même raison : le
    bail que la VM prend au premier démarrage sous le nom par défaut de l'image
    est remplacé dès que cloud-init pose le vrai nom d'hôte. L'agent invité fait
    foi ; sans lui, on départage les baux en testant le port 22.

    virsh SANS sudo d'abord (groupe libvirt), « sudo -n » en repli : sur un hôte
    exigeant une authentification interactive, sudo échoue et ne doit pas
    empêcher la lecture.
    """

    def run(source):
        for pre in ([], ["sudo", "-n"]):
            try:
                res = subprocess.run(
                    pre
                    + [
                        "virsh",
                        "--connect",
                        "qemu:///system",
                        "domifaddr",
                        name,
                        "--source",
                        source,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env={**os.environ, "LC_ALL": "C", "LANG": "C"},
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if res.returncode == 0:
                return res.stdout
        return ""

    found = re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})/", run("agent"))
    for ip in found:
        if not ip.startswith("127."):
            return ip
    # Sans agent : plusieurs baux possibles, dont un périmé. Le port 22 tranche.
    for ip in re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})/", run("lease")):
        if ip.startswith("127."):
            continue
        if _port_open(ip, 22):
            return ip
    return ""


def virsh_domstates() -> dict:
    """{nom: état} de tous les domaines libvirt (« virsh list --all »). Sert à
    détecter une VM EN PAUSE ou EFFACÉE pendant le suivi. Un seul appel virsh
    pour tout le parc (à interroger à intervalle LENT)."""
    try:
        res = subprocess.run(
            ["sudo", "virsh", "list", "--all"],
            capture_output=True,
            text=True,
            timeout=15,
            # LC_ALL=C : sortie en ANGLAIS (« running »/« paused »/« shut off »
            # + en-tête « Id Name State ») quelle que soit la locale de l'hôte.
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    states = {}
    for line in res.stdout.splitlines():
        parts = line.split()
        # Ignore l'en-tête (« Id Name State ») et le séparateur (« ---- »,
        # un seul token). Une VM éteinte a « - » en Id : à NE PAS ignorer.
        if len(parts) < 3 or parts[0] == "Id":
            continue
        states[parts[1]] = " ".join(parts[2:])
    return states


# --------------------------------------------------------------------------- #
# Dashboard Textual
# --------------------------------------------------------------------------- #
def run_monitor(manifest_path: str, run_app: bool = True):
    """Ouvre le dashboard Textual sur un manifeste d'installation. `run_app`
    à False renvoie l'instance sans la lancer (tests headless)."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import DataTable, Footer, Header, RichLog, Static

    manifest = json.loads(Path(manifest_path).read_text())
    started = manifest.get("started", time.time())
    vms = manifest["vms"]

    class ErrorLinesScreen(ModalScreen):
        """Petite fenêtre modale : liste les LIGNES d'erreurs/avertissements
        d'une VM pour les lire (défilable). Échap / q pour fermer."""

        BINDINGS = [
            ("escape", "dismiss", "Fermer"),
            ("q", "dismiss", "Fermer"),
        ]

        def __init__(self, vm_name, errs, warns):
            super().__init__()
            self._vm = vm_name
            self._errs = errs
            self._warns = warns

        def compose(self) -> ComposeResult:
            with Vertical(id="errbox"):
                yield Static(
                    f"  {self._vm} — ⚠ {len(self._errs)} "
                    f"{t('errors')} · ⚡ {len(self._warns)} {t('warnings')}"
                    f"   ({t('Esc to close')})",
                    id="errtitle",
                )
                yield RichLog(
                    id="errlog", highlight=False, markup=False, wrap=True
                )

        def on_mount(self) -> None:
            log = self.query_one("#errlog", RichLog)
            if self._errs:
                log.write(f"── {t('errors').capitalize()} ──")
                for line in self._errs:
                    log.write(line)
            if self._warns:
                log.write(f"── {t('warnings').capitalize()} ──")
                for line in self._warns:
                    log.write(line)
            if not self._errs and not self._warns:
                log.write(t("No error detected."))

        def action_dismiss(self) -> None:
            self.dismiss()

    ICON = {
        "pending": "⏳",
        "running": "⏳",
        "done": "✅",
        "failed": "❌",
    }

    class Monitor(App):
        CSS = """
        DataTable { width: 74; height: 1fr; overflow-x: auto; border: solid $accent; }
        RichLog { border: solid $accent; }
        #telemetry { height: 1; color: $text-muted; }
        #stats { height: 1; color: $accent; }
        #statsdetail { display: none; height: auto; color: $text-muted; }
        #sshbar { height: 2; color: $text-muted; }
        ErrorLinesScreen { align: center middle; }
        #errbox {
            width: 80%; height: 70%;
            border: thick $accent; background: $surface;
        }
        #errtitle { height: 1; color: $accent; text-style: bold; }
        #errlog { height: 1fr; border: solid $accent; }
        """
        BINDINGS = [
            ("q", "quit", "Quitter (détaché)"),
            ("s", "ssh", "SSH"),
            ("v", "console", "Console (virsh)"),
            ("w", "web", "Web (navigateur CLI)"),
            ("f", "follow", "Suivre"),
            ("c", "copy_log", "Copier log"),
            ("d", "details", "Détails erreurs"),
            ("p", "pause_all", "Pause tout"),
            ("o", "resume_all", "Reprendre tout"),
        ]

        def __init__(self):
            super().__init__()
            self._offsets = {vm["name"]: 0 for vm in vms}
            self._selected = vms[0]["name"] if vms else None
            self._follow = True
            # Statuts TERMINAUX mémorisés : une VM finie n'est plus relue
            # (réduit fortement l'I/O sur un gros parc). Valeur = (état, code,
            # durée à la complétion).
            self._final = {}
            # Cache des cellules AFFICHÉES : on n'appelle update_cell (donc on
            # ne re-render) que si la valeur CHANGE -> plus de churn de rendu.
            self._cells = {}
            # Historique de durées (ETA) + dossier disque à surveiller.
            self._stats = load_stats()
            self._disk_dir = (
                os.path.dirname(vm_disk_path(vms[0])) if vms else "/"
            )
            # État libvirt (running/paused/gone), rafraîchi à intervalle LENT.
            self._domstate = {}
            # Erreurs détectées dans le log à la complétion : {nom: (err, warn)}.
            self._errcount = {}
            # Sommaire de stats déplié (clic) ou non.
            self._stats_open = False
            # VM dont l'UI Odoo (:8069) répond déjà : une fois détectée « up »,
            # on ne re-teste plus (Odoo ne redescend pas en cours d'install).
            self._odoo_up = set()
            # Debounce du changement de VM : la sélection défile vite au
            # clavier ; on ne recharge le log qu'une fois le curseur STABILISÉ.
            self._pending_sel = None
            self._sel_timer = None

        @staticmethod
        def _fmt(secs):
            mm, ss = divmod(int(secs), 60)
            return f"{mm:02d}:{ss:02d}"

        def _set_cell(self, table, name, col, value):
            key = (name, col)
            if self._cells.get(key) == value:
                return
            self._cells[key] = value
            table.update_cell(name, col, value)

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            table = DataTable(id="vms", cursor_type="row")
            # Clés de colonnes explicites : update_cell() les référence.
            # La colonne « ⚠ » (erreurs détectées) est à GAUCHE d'« État ».
            # Largeurs FIXES pour les colonnes courtes -> l'État n'est plus
            # tronqué (« ❌ effacée », « ⏸ en pause » lisibles) ; la table
            # défile horizontalement (overflow-x) pour les noms de VM longs.
            # « # » : numéro de séquence de la VM (première colonne).
            table.add_column("#", key="seq", width=3)
            table.add_column("VM", key="vm", width=22)
            table.add_column("⚠", key="err", width=4)
            # width=8 : le plus long libellé restant est « ⏸ pause » (7) —
            # « effacée » (10) est remplacé par l'icône 🗑 (voir plus bas).
            table.add_column("État", key="state", width=8)
            # « Odoo » : l'UI web répond-elle sur :8069 ? (🟢 up / — down)
            table.add_column("Odoo", key="odoo", width=6)
            table.add_column("Durée", key="elapsed", width=7)
            table.add_column("Disque", key="disk", width=8)
            for i, vm in enumerate(vms, 1):
                table.add_row(
                    str(i),
                    vm["name"],
                    "",
                    "⏳",
                    "—",
                    "--:--",
                    "-",
                    key=vm["name"],
                )
            # max_lines borne la mémoire/rendu (un install verbeux × 30 VM).
            self._log = RichLog(
                id="log", highlight=False, markup=False, max_lines=5000
            )
            with Horizontal():
                yield table
                yield self._log
            # Barre de télémétrie hôte (CPU, disque, ETA parc).
            yield Static("", id="telemetry")
            # Sommaire de stats en CHIFFRES (cliquable -> détail).
            yield Static("", id="stats")
            yield Static("", id="statsdetail")
            yield Static("", id="sshbar")
            yield Footer()

        def on_mount(self) -> None:
            # Le NOMBRE de VM figure dans le titre ; le sous-titre suit la
            # progression (terminées / total + durée globale).
            self.title = (
                f"ERPLibre — {t('install monitoring')} ({len(vms)} VM)"
            )
            self.sub_title = f"0/{len(vms)} {t('completed')}"
            self._refresh_ssh()
            self._load_selected_log(reset=True)
            # Table toutes les 2 s (30 lectures de fin de log), suivi du log
            # sélectionné toutes les 1 s (une seule lecture incrémentale).
            self.set_interval(2.0, self._tick_table)
            self.set_interval(1.0, self._tick_log)
            # État libvirt (pause / effacée) : check LENT (appel virsh) toutes
            # les 10 s ; le tableau applique le cache à chaque tick (2 s).
            self.set_interval(10.0, self._tick_domstate)
            # Premier relevé domstate immédiat (async -> via worker).
            self.run_worker(self._tick_domstate(), exclusive=False)

        # -- helpers -------------------------------------------------------- #
        def _vm_by_name(self, name):
            return next((v for v in vms if v["name"] == name), None)

        def _refresh_ssh(self):
            vm = self._vm_by_name(self._selected)
            bar = self.query_one("#sshbar", Static)
            if vm:
                bar.update(
                    f"  {vm['ssh']}    (s = SSH · v = console · "
                    "w = web :8069 · c = copier le log · "
                    "d = détails erreurs · Maj+glisser = sélectionner)\n"
                    f"  Log : {vm['log']}"
                )

        def _load_selected_log(self, reset=False):
            # Au reset (changement de VM), on ne lit QUE LA FIN du log
            # (_read_tail) et on cale l'offset sur la taille totale : le suivi
            # incrémental (_tick_log) continue depuis la fin. Lire+réafficher
            # le fichier ENTIER gelait l'UI sur les gros logs.
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            name = vm["name"]
            if reset:
                self._log.clear()
                text, size = _read_tail(vm["log"])
                self._offsets[name] = size
                for line in text.splitlines():
                    if EXIT_MARKER not in line:
                        self._log.write(line)
                return
            new, off = _read_new(vm["log"], self._offsets.get(name, 0))
            self._offsets[name] = off
            for line in new.splitlines():
                if EXIT_MARKER not in line:
                    self._log.write(line)

        def _collect_tele(self):
            """(THREAD) chaîne de télémétrie hôte : CPU % + disque des images."""
            try:
                ncpu = os.cpu_count() or 1
                load1 = os.getloadavg()[0]
                du = shutil.disk_usage(self._disk_dir)
                used_pct = int(du.used / du.total * 100) if du.total else 0
                return (
                    f"  ⚙ CPU {min(999, int(load1 / ncpu * 100))}% "
                    f"(charge {load1:.1f}/{ncpu})   "
                    f"💽 {self._disk_dir}: {_fmt_size(du.used)}/"
                    f"{_fmt_size(du.total)} ({used_pct}%) · "
                    f"libre {_fmt_size(du.free)}"
                )
            except Exception:
                return ""

        def _collect_table(self):
            """(THREAD) statut + taille disque de chaque VM + télémétrie. AUCUNE
            mise à jour d'UI ici : uniquement des I/O bloquantes déportées."""
            disks, status, errors, odoo = {}, {}, {}, {}
            for vm in vms:
                name = vm["name"]
                disks[name] = _fmt_size(disk_actual_size(vm_disk_path(vm)))
                if (
                    name not in self._final
                    and self._domstate.get(name) != "gone"
                ):
                    st = read_status(vm["log"])
                    status[name] = st
                    # À la complétion (succès OU échec), on ANALYSE le log
                    # complet pour signaler les erreurs — même un « succès »
                    # peut contenir des erreurs passées inaperçues.
                    if st[0] in ("done", "failed") and name not in errors:
                        errors[name] = scan_log_errors(vm["log"])
                # Odoo up ? On ne teste que celles pas encore confirmées up
                # et non effacées (test TCP court sur :8069).
                if (
                    name not in self._odoo_up
                    and self._domstate.get(name) != "gone"
                ):
                    if _port_open(vm.get("ip"), 8069):
                        odoo[name] = True
            return disks, status, self._collect_tele(), errors, odoo

        async def _tick_table(self):
            # I/O (lectures de logs, stat disque, /proc) DÉPORTÉES en thread ->
            # la boucle d'événements Textual reste fluide même sous forte
            # charge ou disque lent. Les mises à jour d'UI restent sur la boucle.
            try:
                disks, status, tele, errors, odoo = await asyncio.to_thread(
                    self._collect_table
                )
            except Exception:
                return
            self._errcount.update(errors)
            self._odoo_up.update(odoo)
            try:
                table = self.query_one("#vms", DataTable)
                now = time.time()
                remaining = []
                for vm in vms:
                    name = vm["name"]
                    self._set_cell(table, name, "disk", disks.get(name, "-"))
                    # Colonne Odoo : 🟢 dès que :8069 répond, sinon « — ».
                    self._set_cell(
                        table,
                        name,
                        "odoo",
                        "🟢" if name in self._odoo_up else "—",
                    )
                    if name in self._final:
                        continue
                    ds = self._domstate.get(name)
                    if ds == "gone":
                        self._final[name] = ("deleted", None, now - started)
                        # Icône seule (VM effacée) : évite « ❌ effacée » (10
                        # cellules) qui forçait une colonne État large.
                        self._set_cell(table, name, "state", "🗑")
                        continue
                    st = status.get(name)
                    if st is None:
                        continue
                    state, code = st
                    if state in ("done", "failed"):
                        elapsed = now - started
                        self._final[name] = (state, code, elapsed)
                        # Les échecs sont enregistrés eux aussi (ok=False) :
                        # sans eux, aucun taux de réussite n'est calculable.
                        record_duration(
                            vm.get("distro"),
                            vm.get("version"),
                            vm.get("arch"),
                            elapsed,
                            ok=state == "done",
                        )
                        self._stats = load_stats()
                        lbl = "✅" if state == "done" else f"❌ ({code})"
                        self._set_cell(table, name, "state", lbl)
                        self._set_cell(
                            table, name, "elapsed", self._fmt(elapsed)
                        )
                        # Colonne ⚠ (à gauche d'État) : erreurs détectées dans
                        # le log, y compris pour un « succès ».
                        self._set_cell(
                            table,
                            name,
                            "err",
                            self._err_label(self._errcount.get(name)),
                        )
                    elif ds == "paused":
                        self._set_cell(
                            table, name, "state", f"⏸ {t('paused')}"
                        )
                    else:
                        self._set_cell(table, name, "state", ICON[state])
                        ref = eta_reference(self._stats, vm.get("arch"))
                        if ref is not None:
                            remaining.append(max(0, ref - (now - started)))
                done = len(self._final)
                eta = (
                    f" · ETA ~{_fmt_secs(max(remaining))}" if remaining else ""
                )
                # Max de durée : la VM TERMINÉE la plus lente (pire cas).
                max_dur = max(
                    (el for _s, _c, el in self._final.values()), default=0
                )
                maxd = f" · max {self._fmt(max_dur)}" if max_dur else ""
                self.sub_title = (
                    f"{done}/{len(vms)} {t('completed')} · "
                    f"{self._fmt(now - started)}{eta}{maxd}"
                )
                if tele:
                    self.query_one("#telemetry", Static).update(tele)
                self._update_stats()
            except Exception:
                pass

        @staticmethod
        def _err_label(counts):
            """Libellé de la colonne ⚠ : « ⚠N » si erreurs, « ⚡N » si seulement
            des avertissements, « ✓ » si log propre."""
            if not counts:
                return ""
            nerr, nwarn = counts
            if nerr:
                return f"⚠{nerr}"
            if nwarn:
                return f"⚡{nwarn}"
            return "✓"

        def _stats_counts(self):
            """Compte par catégorie (terminées, échecs, erreurs, etc.)."""
            done = fail = deleted = err_vms = warn_vms = 0
            for name, (state, _code, _el) in self._final.items():
                if state == "done":
                    done += 1
                elif state == "failed":
                    fail += 1
                elif state == "deleted":
                    deleted += 1
                counts = self._errcount.get(name)
                if counts:
                    if counts[0]:
                        err_vms += 1
                    elif counts[1]:
                        warn_vms += 1
            running = paused = 0
            for vm in vms:
                if vm["name"] in self._final:
                    continue
                if self._domstate.get(vm["name"]) == "paused":
                    paused += 1
                else:
                    running += 1
            return {
                "total": len(vms),
                "done": done,
                "fail": fail,
                "deleted": deleted,
                "running": running,
                "paused": paused,
                "err_vms": err_vms,
                "warn_vms": warn_vms,
            }

        def _update_stats(self):
            c = self._stats_counts()
            line = (
                f"  📊 {c['total']} VM · ✅ {c['done']} · ❌ {c['fail']} · "
                f"⏳ {c['running']} · ⏸ {c['paused']} · 🗑 {c['deleted']} · "
                f"⚠ {c['err_vms']} · ⚡ {c['warn_vms']}   "
                f"({t('click to expand')})"
            )
            self.query_one("#stats", Static).update(line)
            if self._stats_open:
                self.query_one("#statsdetail", Static).update(
                    self._render_stats_detail()
                )

        def _render_stats_detail(self):
            """Détail déplié : VM avec erreurs/avertissements + moyennes hist."""
            lines = []
            for name, (state, code, el) in self._final.items():
                counts = self._errcount.get(name)
                if counts and (counts[0] or counts[1]):
                    lines.append(
                        f"    • {name}: ⚠{counts[0]} erreurs, "
                        f"⚡{counts[1]} avert. ({self._fmt(el)})"
                    )
            if not lines:
                lines.append(f"    {t('No error detected.')}")
            return "\n".join(lines)

        async def _tick_log(self):
            if not self._follow:
                return
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            name = vm["name"]
            try:
                new, off = await asyncio.to_thread(
                    _read_new, vm["log"], self._offsets.get(name, 0)
                )
            except Exception:
                return
            self._offsets[name] = off
            for line in new.splitlines():
                if EXIT_MARKER not in line:
                    self._log.write(line)

        async def _tick_domstate(self):
            # Relevé LENT (subprocess virsh) DÉPORTÉ en thread : ne bloque plus
            # la boucle. Une VM absente de « virsh list » est EFFACÉE (« gone »).
            try:
                states = await asyncio.to_thread(virsh_domstates)
            except Exception:
                return
            for vm in vms:
                self._domstate[vm["name"]] = states.get(vm["name"], "gone")

            # L'adresse est relue au même rythme. Le processus détaché suivait
            # déjà la VM quand son bail changeait, mais les VUES gardaient celle
            # du lancement : la barre proposait « ssh erplibre@…222 » alors que
            # l'installation parlait à …223, et la touche « s » y menait aussi.
            # Rafraîchir ici plutôt que dans un tick à part évite un second
            # appel virsh par VM — celui-ci est déjà le relevé lent.
            changed = False
            for vm in vms:
                if self._domstate.get(vm["name"]) == "gone":
                    continue
                ip = await asyncio.to_thread(virsh_ip, vm["name"])
                if ip and ip != vm.get("ip"):
                    vm["ip"] = ip
                    vm["ssh"] = f"ssh erplibre@{ip}"
                    changed = True
            if changed:
                self._refresh_ssh()

        # -- events --------------------------------------------------------- #
        def on_data_table_row_highlighted(self, event) -> None:
            # DEBOUNCE : RowHighlighted se déclenche à CHAQUE mouvement du
            # curseur. Recharger le log à chaque pas (surtout en maintenant la
            # flèche) enchaînait les rechargements -> gros lag. On diffère de
            # 0,25 s et on ne charge que la DERNIÈRE VM sélectionnée.
            name = event.row_key.value
            if not name or name == self._selected:
                return
            self._pending_sel = name
            if self._sel_timer is not None:
                self._sel_timer.stop()
            self._sel_timer = self.set_timer(0.25, self._apply_pending_sel)

        def _apply_pending_sel(self) -> None:
            name = self._pending_sel
            self._sel_timer = None
            if not name or name == self._selected:
                return
            self._selected = name
            self._refresh_ssh()
            self._load_selected_log(reset=True)

        def action_follow(self) -> None:
            self._follow = not self._follow

        def action_ssh(self) -> None:
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            with self.suspend():
                os.system(f"ssh {SSH_OPTS} erplibre@{vm['ip']} || true")

        def action_console(self) -> None:
            """Console série de la VM, sans quitter le suivi.

            Le seul recours quand SSH ne répond pas : elle ne dépend ni du
            réseau de la VM, ni de sshd, ni d'une IP — donc elle montre un
            démarrage bloqué, un cloud-init encore en cours ou un réseau sans
            bail, que le suivi ne peut que constater de loin.

            « suspend() » rend le terminal avant d'appeler virsh : sudo peut y
            demander son mot de passe et la console prendre le clavier, ce qui
            casserait l'affichage si Textual le tenait encore.
            """
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            name = shlex.quote(vm["name"])
            with self.suspend():
                # La console n'affiche que ce qui arrive APRÈS l'attachement :
                # sur une VM déjà démarrée l'écran reste noir tant qu'on n'a
                # rien envoyé. On le dit, plutôt que de laisser croire à un gel.
                print(f"\n→ virsh console {vm['name']}")
                print(
                    "   Écran vide ? Appuyez sur Entrée : la console ne montre"
                    " que la sortie qui suit l'attachement."
                )
                print("   Ctrl+] puis Entrée pour revenir au suivi.\n")
                os.system(f"sudo virsh console {name} || true")

        def action_web(self) -> None:
            """Ouvre l'UI web de la VM (Odoo :8069) dans un navigateur CLI
            (browsh/carbonyl/w3m/links/elinks/lynx). Surtout utile une fois
            l'installation TERMINÉE."""
            vm = self._vm_by_name(self._selected)
            if not vm or not vm.get("ip"):
                self.notify("Pas d'IP pour cette VM.", title="Web")
                return
            browser = self._choose_browser()
            if not browser:
                return
            url = f"http://{vm['ip']}:8069"
            with self.suspend():
                print(f"→ {browser} {url}")
                rc = os.system(f"{browser} {shlex.quote(url)}")
                # Diagnostic : sinon le navigateur « clignote » et revient au
                # TUI sans qu'on voie l'erreur (souvent Odoo pas démarré).
                print(f"\n[{browser}] terminé (code {rc}).")
                if rc != 0:
                    print(
                        "La page ne s'est peut-être pas affichée : Odoo n'est "
                        "pas démarré sur :8069, ou réseau/pare-feu. Vérifie que "
                        "le service Odoo tourne dans la VM (make run / systemd)."
                    )
                try:
                    input("Entrée pour revenir au suivi… ")
                except EOFError:
                    pass

        def _choose_browser(self):
            """Offre la LISTE des navigateurs CLI installés et laisse choisir
            lequel utiliser pour voir la page. Si aucun n'est installé, propose
            d'en installer un. Renvoie le binaire choisi, ou None."""
            available = [b for b in CLI_BROWSERS if shutil.which(b)]
            if not available:
                browser = self._install_cli_browser()
                if not browser:
                    self.notify(
                        "Aucun navigateur CLI disponible.",
                        title="Web",
                        severity="warning",
                    )
                return browser
            with self.suspend():
                print("Quel navigateur utiliser pour voir la page ?")
                for i, b in enumerate(available, 1):
                    print(f"  [{i}] {b}{' *' if i == 1 else ''}")
                print("  [i] Installer un autre navigateur")
                sel = (
                    input(f"Choix (numéro, vide = {available[0]}) : ")
                    .strip()
                    .lower()
                )
                if sel == "i":
                    return self._install_cli_browser()
                if not sel:
                    return available[0]
                try:
                    idx = int(sel) - 1
                    if 0 <= idx < len(available):
                        return available[idx]
                except ValueError:
                    pass
                return available[0]

        def _install_cli_browser(self):
            """Demande QUEL navigateur CLI installer (w3m/lynx/links/elinks),
            affiche la commande, l'exécute après validation. Renvoie le binaire
            désormais disponible, ou None."""
            with self.suspend():
                print("Aucun navigateur CLI installé. Lequel installer ?")
                for i, (b, desc) in enumerate(INSTALLABLE_BROWSERS, 1):
                    print(f"  [{i}] {desc}{' *' if i == 1 else ''}")
                sel = input("Choix (numéro, vide = w3m) : ").strip()
                browser = INSTALLABLE_BROWSERS[0][0]
                try:
                    idx = int(sel) - 1
                    if 0 <= idx < len(INSTALLABLE_BROWSERS):
                        browser = INSTALLABLE_BROWSERS[idx][0]
                except ValueError:
                    pass
                cmd = browser_install_command(browser)
                if not cmd:
                    print(
                        "Gestionnaire de paquets inconnu : installez "
                        f"« {browser} » manuellement."
                    )
                    input("Entrée… ")
                    return None
                printable = " ".join(cmd)
                print(f"Commande : {printable}")
                ans = input("Installer maintenant ? (o/N) : ").strip().lower()
                if ans not in ("o", "oui", "y", "yes"):
                    return None
                rc = os.system(printable)
                print(f"\nInstallation terminée (code {rc}).")
                input("Entrée pour continuer… ")
            return cli_browser()

        def action_copy_log(self) -> None:
            """Copie le log complet de la VM sélectionnée dans le
            presse-papiers (OSC 52 ; marche aussi à travers SSH)."""
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            try:
                text = Path(vm["log"]).read_text(errors="replace")
            except OSError:
                return
            self.copy_to_clipboard(text)
            self.notify(
                f"Log de {vm['name']} copié ({len(text)} car.)",
                title="Presse-papiers",
            )

        def action_details(self) -> None:
            """Ouvre une petite fenêtre avec les LIGNES d'erreurs/avertissements
            de la VM sélectionnée (scan à la demande -> toujours à jour)."""
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            errs, warns = scan_log_error_lines(vm["log"])
            self.push_screen(ErrorLinesScreen(vm["name"], errs, warns))

        def on_click(self, event) -> None:
            # Clic sur le sommaire de stats -> déplie / replie le détail.
            w = getattr(event, "widget", None)
            if w is not None and getattr(w, "id", None) == "stats":
                self._stats_open = not self._stats_open
                self.query_one("#statsdetail").display = self._stats_open
                self._update_stats()

        # -- pause / reprise de tout le parc -------------------------------- #
        @staticmethod
        def _virsh_bulk(action, names):
            for n in names:
                try:
                    subprocess.run(
                        ["sudo", "virsh", action, n],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                except (OSError, subprocess.SubprocessError):
                    pass

        def action_pause_all(self) -> None:
            """Met en PAUSE (virsh suspend) toutes les VM en cours d'exécution.
            L'install reprend là où elle en était après « Reprendre »."""
            self.run_worker(self._bulk_worker("suspend"), exclusive=False)

        def action_resume_all(self) -> None:
            """REPREND (virsh resume) toutes les VM en pause ; le suivi des
            logs continue automatiquement (offsets conservés)."""
            self.run_worker(self._bulk_worker("resume"), exclusive=False)

        async def _bulk_worker(self, action):
            want = "running" if action == "suspend" else "paused"
            targets = [
                vm["name"]
                for vm in vms
                if self._domstate.get(vm["name"]) == want
            ]
            if not targets:
                self.notify(
                    t("No running VM to pause.")
                    if action == "suspend"
                    else t("No paused VM to resume.")
                )
                return
            await asyncio.to_thread(self._virsh_bulk, action, targets)
            verb = t("paused") if action == "suspend" else t("resumed")
            self.notify(f"{len(targets)} VM {verb}.")
            # Rafraîchit tout de suite l'état libvirt (pause/reprise visible).
            self.run_worker(self._tick_domstate(), exclusive=False)

    app = Monitor()
    if run_app:
        app.run()
    return app
