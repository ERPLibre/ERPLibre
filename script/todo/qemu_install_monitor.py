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

from script.todo.qemu_privilege import sudo_prefix
from pathlib import Path

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


EXIT_MARKER = "__ERPLIBRE_EXIT__"

# Installations qui posent un NOYAU : elles ne valent rien avant un
# redémarrage, et le script ne peut pas survivre au sien. La table dit quoi
# attendre APRÈS — un motif à trouver dans « uname -r », donc une preuve et
# non une supposition.
#
# Proxmox VE en est le seul cas aujourd'hui, et il est systématique : notre
# install_proxmox.sh pose proxmox-default-kernel sans redémarrer — lancé par
# ssh, un reboot couperait la session et ferait passer l'installation pour un
# échec. La VM restait donc sur le noyau cloud de Debian, dépouillé de tout
# netfilter : ni pont NAT, ni invité. On le découvrait des jours plus tard.
REBOOT_AFTER = (("install_proxmox.sh", "-pve"),)

# Attente maximale du retour de la machine, en tours de cinq secondes.
# Généreuse : un hyperviseur imbriqué redémarre lentement, et échouer trop
# tôt marquerait rouge une installation qui a réussi.
REBOOT_TOURS = 180


def reboot_expected(remote_cmd) -> str:
    """Motif à trouver dans « uname -r » après redémarrage, ou "".

    Jugé sur la COMMANDE effective de la VM, pas sur sa distribution : un parc
    mixte est le cas normal, et c'est ce qu'on installe qui décide."""
    for marque, motif in REBOOT_AFTER:
        if marque in (remote_cmd or ""):
            return motif
    return ""


SSH_OPTS = (
    "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
    "-o ConnectTimeout=8"
)
# Pour les ssh NON INTERACTIFS : « -n » branche leur entrée sur /dev/null.
# Ceinture et bretelles avec le stdin du processus détaché — un ssh qui lit le
# terminal vole les frappes du shell, et le diagnostic est très difficile.
# Jamais pour un ssh interactif (touche « s »), qui doit garder le clavier.
SSH_OPTS_BATCH = f"{SSH_OPTS} -n"


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


def _reboot_steps(log_q: str, motif: str, tours: int = REBOOT_TOURS) -> str:
    """Shell qui redémarre la VM, attend son retour, et vérifie son noyau.

    Trois choses valent d'être dites.

    Le redémarrage n'a lieu QUE si l'installation a réussi : redémarrer après
    un échec effacerait la seule machine sur laquelle on pouvait chercher.

    On n'attend pas que ssh « revienne » — sshd répond encore une seconde ou
    deux après l'ordre de redémarrage, et on lirait alors l'ANCIEN noyau en
    croyant avoir la réponse. On attend que « uname -r » porte le motif ; tant
    qu'il porte l'ancien, la machine n'est pas revenue.

    `tours` est un paramètre pour que ce shell soit ÉPROUVABLE : un garde
    qu'on ne sait pas exécuter s'ouvre le jour où il casse.

    Et l'échec est un vrai échec : sans le noyau attendu, l'hyperviseur n'a ni
    table NAT ni module bridge. Le dire ✅ serait le mensonge qui a coûté deux
    jours à le comprendre."""
    msg_reboot = t("Rebooting to boot the new kernel")
    msg_wait = t("waiting for the machine to come back")
    msg_ok = t("kernel booted:")
    msg_ko = t("the machine did not come back on the expected kernel:")
    return (
        'if [ "$rc" = 0 ]; then '
        f"echo {shlex.quote('== ' + msg_reboot + ' ==')} >> {log_q}; "
        # « || true » : la session MEURT avec le redémarrage, et son code 255
        # ne dit rien de l'ordre lui-même.
        f'ssh {SSH_OPTS_BATCH} "erplibre@$ip" '
        # « sudo -n » : cette enveloppe tourne DÉTACHÉE, sans terminal. Un
        # sudo qui demande son mot de passe échoue alors tout de suite au lieu
        # d'attendre une frappe que personne ne fera.
        "'sudo -n systemctl reboot' "
        f">> {log_q} 2>&1 || true; "
        f"echo {shlex.quote('   ' + msg_wait)} >> {log_q}; "
        "krn=''; "
        f"for i in $(seq 1 {tours}); do sleep ${{ERPLIBRE_REBOOT_SLEEP:-5}}; "
        f'k=$(ssh {SSH_OPTS_BATCH} -o BatchMode=yes "erplibre@$ip" '
        "'uname -r' 2>/dev/null); "
        f'case "$k" in *{motif}*) krn="$k"; break;; esac; '
        "if [ $((i % 6)) -eq 0 ]; then "
        f'echo "   ... $((i*5))s" >> {log_q}; fi; '
        "done; "
        'if [ -n "$krn" ]; then '
        f'echo "   {msg_ok} $krn" >> {log_q}; '
        f'else echo "   ⚠ {msg_ko} {motif}" >> {log_q}; rc=1; fi; '
        "fi; "
    )


def _launch_one(
    ip: str,
    remote_cmd: str,
    log_path: str,
    name: str = "",
    installs: bool = True,
    pve: bool = False,
    reboot: str = "",
) -> None:
    """Lance une install SSH DÉTACHÉE : attend le sshd, exécute, journalise
    la sortie puis écrit le marqueur de fin avec le code de sortie.

    `reboot` : motif attendu dans « uname -r » APRÈS un redémarrage. Non
    vide, l'installation réussie est suivie d'un reboot, de l'attente du
    retour, et d'une vérification du noyau — le succès n'est écrit qu'ensuite.
    C'est ici et non dans la VM parce qu'un script ne survit pas à son propre
    redémarrage : cette enveloppe, elle, tourne sur NOTRE machine.

    `pve` : la VM vit sur un hôte Proxmox. On ne RÉ-RÉSOUT alors PAS son
    adresse par virsh — et c'est vital. Vécu le 24 août 2026 : une VM
    « erplibre-ubuntu-2604 » déployée sur Proxmox portait le nom d'un domaine
    LOCAL existant ; la ré-résolution a trouvé le domaine local et
    l'installation d'ERPLibre + Odoo est partie sur la mauvaise machine, sans
    que rien ne le dise. Pour une VM distante, l'alias ~/.ssh/config est la
    seule vérité : il porte le rebond par l'hôte."""
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
    # « installation ERPLibre en cours » sur un déploiement qui n'installe
    # RIEN était un mensonge du journal : la ligne dit maintenant ce qui suit.
    msg_ready = (
        t("VM ready - starting the ERPLibre install")
        if installs
        else t("VM ready - taking its measurements")
    )
    msg_giveup = t(
        "cloud-init still running after 20 min - install starts anyway"
        " (it waits for cloud-init first)"
    )
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
            "for c in $cands; do "
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
        if name and not pve
        else ""
    )
    wrapper = (
        f"ip={shlex.quote(ip)}; "
        f"{vsh if name and not pve else ''}"
        f"echo {shlex.quote('== ' + msg_wait + ' ==')} >> {log_q}; "
        f"echo {shlex.quote('   ' + msg_slow)} >> {log_q}; "
        f"seen=0; "
        f"for i in $(seq 1 240); do "
        f"{refresh}"
        f'st=$(ssh {SSH_OPTS_BATCH} -o BatchMode=yes "erplibre@$ip" '
        f"{shlex.quote(ci_probe)} 2>/dev/null); "
        f'case "$st" in '
        f"*done*|*disabled*|*error*|*degraded*|*nocloudinit*) seen=1; break;; "
        f"esac; "
        f"if [ $((i % 6)) -eq 0 ]; then "
        f'echo "   ... $((i*5))s ($ip)" >> {log_q}; fi; '
        f"sleep 5; done; "
        # La boucle peut s'ÉPUISER au lieu de rompre : sous émulation,
        # cloud-init dépasse volontiers 20 min. Annoncer « VM prête » dans les
        # deux cas donnait un message faux juste avant le plus long silence du
        # log — c'est l'installation qui attend alors la fin de cloud-init.
        f'if [ "$seen" = 1 ]; then '
        f"echo {shlex.quote('== ' + msg_ready + ' ==')} >> {log_q}; "
        f"else echo {shlex.quote('== ' + msg_giveup + ' ==')} >> {log_q}; fi; "
        f'echo "   → $ip" >> {log_q}; '
        f'ssh {SSH_OPTS_BATCH} "erplibre@$ip" {shlex.quote(remote_cmd)} '
        f">> {log_q} 2>&1; rc=$?; "
        + (_reboot_steps(log_q, reboot) if reboot else "")
        + f'echo "{EXIT_MARKER} $rc" >> {log_q}'
    )
    # setsid -f : le process survit à la fermeture du menu / du dashboard.
    # stdin sur /dev/null : SANS lui, le descripteur 0 du processus détaché
    # reste le TERMINAL. « setsid » lui retire le terminal de contrôle, mais ne
    # ferme aucun descripteur — et ssh, lui, LIT son entrée pour la transmettre
    # à la commande distante. Deux lecteurs se partagent alors le clavier : une
    # frappe sur deux part vers l'installation au lieu du shell, et il faut
    # appuyer plusieurs fois pour qu'une lettre arrive. Le symptôme survit à
    # todo.py, puisque l'installation continue une demi-heure après sa
    # fermeture — d'où un terminal qui « bogue » sans cause visible.
    subprocess.Popen(
        ["setsid", "-f", "bash", "-c", wrapper],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _log_header(vm: dict, branch: str, when: str) -> str:
    """En-tête du log : date, VM, distribution, version, architecture, branche.
    Permet d'identifier l'installation d'un coup d'œil (et de ne jamais laisser
    le log vide pendant l'attente du boot).

    Sans branche, il n'y a rien à installer : le titre le dit et la ligne
    « Branche » disparaît, au lieu d'annoncer une installation ERPLibre qui
    n'aura pas lieu.
    """
    distro = vm.get("distro") or "?"
    version = vm.get("version") or ""
    arch = vm.get("arch") or "?"
    bar = "=" * 64
    titre = t("installation") if branch else t("VM start-up")
    ligne_branche = f"  Branche      : {branch}\n" if branch else ""
    return (
        f"{bar}\n"
        f"  ERPLibre — {titre}\n"
        f"  Date         : {when}\n"
        f"  VM           : {vm['name']}\n"
        f"  Distribution : {distro} {version}\n"
        f"  Architecture : {arch}\n"
        f"{ligne_branche}"
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
        # Une VM peut porter SA commande : depuis que le type de VM (serveur
        # ou bureau) se choisit machine par machine, le script distant n'est
        # plus le même pour toutes. `remote_cmd` reste le défaut, ce qui laisse
        # intacts les appelants qui n'en fournissent qu'une.
        cmd_vm = vm.get("remote_cmd") or remote_cmd
        _launch_one(
            vm["ip"],
            cmd_vm,
            log_path,
            vm["name"],
            installs=bool(branch),
            pve=bool(vm.get("pve")),
            # Une installation qui pose un NOYAU ne vaut rien avant le
            # redémarrage : l'enveloppe s'en charge et ne conclut qu'après.
            reboot=reboot_expected(cmd_vm),
        )
        entree = {
            "name": vm["name"],
            "ip": vm["ip"],
            "distro": vm.get("distro"),
            "version": vm.get("version"),
            "arch": vm.get("arch"),
            "log": log_path,
            "ssh": f"ssh erplibre@{vm['ip']}",
        }
        # Une VM posée sur un hôte Proxmox : c'est LUI qui connaît son état.
        if vm.get("pve"):
            entree["pve"] = vm["pve"]
        else:
            # L'UUID du domaine, relevé MAINTENANT : c'est le seul instant où
            # l'on sait que ce nom désigne bien cette machine. Rouvert des
            # semaines plus tard, le suivi ne peut plus le savoir — et c'est
            # lui qui arme le garde de la suppression.
            entree["uuid"] = local_uuid(vm["name"])
        entries.append(entree)
    manifest = {
        "branch": branch,
        "started": time.time(),
        "vms": entries,
    }
    manifest_path = str(logdir / "session.json")
    Path(manifest_path).write_text(json.dumps(manifest, indent=2))
    return manifest_path


def local_uuid(name: str) -> str:
    """UUID du domaine libvirt local, ou "" s'il est illisible.

    Sans sudo d'abord : l'appartenance au groupe libvirt suffit souvent. Une
    chaîne vide DÉSARME le garde plutôt que de bloquer — mieux vaut la
    protection d'avant que refuser toute suppression sur un poste où virsh
    demande un mot de passe."""
    base = ["virsh", "--connect", "qemu:///system", "domuuid", name]
    for argv in (base, ["sudo", "-n"] + base):
        try:
            res = subprocess.run(
                argv, capture_output=True, text=True, timeout=15
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    return ""


def finished_at(log_path: str, fallback: float) -> float:
    """Instant où l'installation s'est RÉELLEMENT arrêtée.

    La dernière écriture dans le log, c'est-à-dire le marqueur de sortie. On
    ne peut pas prendre « maintenant » : le suivi est détachable, et il
    observe souvent l'état final longtemps après. Rouvrir le tableau de bord
    une heure plus tard ajoutait cette heure à la durée affichée, comme si
    l'installation avait tourné pendant tout ce temps."""
    try:
        return os.path.getmtime(log_path)
    except OSError:
        return fallback


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


# Au-delà de ce silence, la colonne d'état le DIT. Ce n'est pas un verdict mais
# un chiffre : plusieurs étapes sont légitimement muettes, leur sortie partant
# ailleurs. Mesuré sur une installation réelle : le téléchargement d'Android
# Studio tient ~5 min sans une ligne, et l'étape « APK debug » davantage — son
# détail va dans le journal de la VM. Dix minutes passent donc au-dessus du
# premier sans attendre le second, qui reste bruyant par nature.
#
# À 48 minutes, le chiffre est accablant : une installation est morte ainsi,
# session ssh emportée, et le sablier tournait toujours.
IDLE_HINT_SECS = 600


def log_idle(log_path: str) -> float:
    """Secondes depuis la dernière écriture dans le journal. -1 s'il manque.

    La date de modification du fichier, et non un compte de lignes : c'est la
    seule mesure qui distingue « rien n'avance » de « rien ne s'affiche »."""
    try:
        return max(0.0, time.time() - os.path.getmtime(log_path))
    except OSError:
        return -1.0


def state_mark(icon: str, idle: float) -> str:
    """Icône d'état, suivie du silence du journal quand il dépasse le seuil.

    Le silence est une INFORMATION, pas un diagnostic : plusieurs étapes sont
    muettes longtemps sans rien avoir de cassé. Mais le sablier seul ne
    distingue pas une installation qui travaille d'une qui est morte, et c'est
    arrivé — 48 minutes de sablier sur une session ssh déjà emportée."""
    if idle > IDLE_HINT_SECS:
        return f"{icon} {t('silent')} {_fmt_secs(idle)}"
    return icon


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
    # ssh annonce l'ajout d'une clé d'hôte à chaque PREMIÈRE connexion à une
    # VM neuve. Ce n'est pas un avertissement d'installation : compté, il
    # allumait la colonne ⚠ sur TOUTE installation, dès sa première ligne.
    "Warning: Permanently added",
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


# Signaux d'échec qui ne contiennent NI « error » NI « warning ». Sans eux, le
# scan par sous-chaîne rate des installations franchement ratées : le journal de
# la VM erplibre-ubuntu-2604-gnome, dont la compilation de l'APK a été tuée par
# le noyau, ne portait AUCUNE ligne « error » — mesuré, 0 sur 8765 lignes —
# pendant que « ⚠ ÉCHEC : APK debug (gradle) », « FAILURE: Build failed » et
# « daemon disappeared unexpectedly » y étaient. Le détail des erreurs annonçait
# donc « aucune erreur détectée » sur une installation en échec.
#
# Chaque motif est là parce qu'il est apparu dans un vrai journal, pas par
# précaution : Gradle dit « FAILURE », Python « Traceback », git « fatal: », apt
# « Unable to locate package », le noyau « Killed » ou « Cannot allocate
# memory », et nos propres étapes « ⚠ ÉCHEC ».
_LST_HARD_MARKERS = (
    "⚠ échec",
    "failed:",
    "failure",
    "traceback (most recent call last)",
    "fatal:",
    "command not found",
    # PAS « no such file or directory » : sur le journal de référence, 5 de ses
    # 7 occurrences étaient des sondes bénignes (« cat: .odoo-version »), et le
    # bruit dilue un résumé dont l'intérêt est justement d'être court. Un
    # fichier vraiment manquant fait échouer une ÉTAPE, elle-même captée.
    "permission denied",
    "unable to locate package",
    "disappeared unexpectedly",
    "outofmemory",
    "cannot allocate memory",
    "segmentation fault",
    "core dumped",
    "killed process",
)
# Étape en échec, telle que la pose « mstep » : « ⚠ ÉCHEC : <libellé> ». C'est
# le signal AUTORITAIRE — il nomme l'étape, là où « FAILURE » ne nomme que
# l'outil.
_RE_FAILED_STEP = re.compile(r"⚠\s*(?:ÉCHEC|FAILED)\s*:?\s*(.+)")
# Début d'une autre étape ou d'une section : borne du diagnostic qui suit.
_RE_STEP_BOUND = re.compile(r"^\s*(?:->|==)\s")


def _is_hard_signal(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in _LST_HARD_MARKERS)


def _error_signature(line: str) -> str:
    """Ligne réduite à sa FORME, pour regrouper les répétitions.

    Un journal d'installation répète la même erreur des centaines de fois avec
    un chemin ou un numéro qui change. Regrouper sur cette forme donne « ×342 »
    au lieu de 342 lignes à faire défiler."""
    sig = re.sub(r"\d+", "#", line)
    sig = re.sub(r"0x[0-9a-fA-F]+", "#", sig)
    sig = re.sub(r"/\S+", "/…", sig)
    return re.sub(r"\s+", " ", sig).strip()[:160]


def scan_log_summary(log_path: str, diag_cap: int = 14) -> dict:
    """Résumé d'un journal d'installation : ce qui a échoué, puis le reste.

    Rend {steps, hard, groups, nerr, nwarn} où « steps » liste les étapes en
    échec AVEC leur diagnostic, « hard » les autres signaux durs dédupliqués, et
    « groups » les lignes « error »/« warning » regroupées par forme et comptées.

    L'ordre n'est pas cosmétique : une étape en échec nommée vaut mille lignes,
    et c'est elle qu'on veut lire d'abord."""
    try:
        lines = Path(log_path).read_text(errors="replace").splitlines()
    except OSError:
        return {"steps": [], "hard": [], "groups": [], "nerr": 0, "nwarn": 0}

    steps, hard, groups = [], {}, {}
    nerr = nwarn = 0
    for i, line in enumerate(lines, 1):
        if EXIT_MARKER in line:
            continue
        low = line.lower()
        match = _RE_FAILED_STEP.search(line)
        if match:
            # Le diagnostic suit l'échec, jusqu'à l'étape suivante : c'est lui
            # qui porte la cause, l'échec ne portant que le nom.
            diag = []
            for nxt in lines[i : i + 60]:
                if _RE_STEP_BOUND.match(nxt) or _RE_FAILED_STEP.search(nxt):
                    break
                if EXIT_MARKER in nxt:
                    continue
                if nxt.strip() and len(diag) < diag_cap:
                    diag.append(nxt.rstrip())
            steps.append(
                {"line": i, "label": match.group(1).strip(), "diag": diag}
            )
            continue
        if _is_hard_signal(line):
            sig = _error_signature(line)
            entry = hard.setdefault(
                sig, {"line": i, "text": line.strip(), "count": 0}
            )
            entry["count"] += 1
            continue
        if "error" in low and not any(ig in line for ig in _LST_IGNORE_ERROR):
            nerr += 1
            key = ("error", _error_signature(line))
            groups.setdefault(
                key, {"line": i, "text": line.strip(), "count": 0}
            )["count"] += 1
        if "warning" in low and not any(
            ig in line for ig in _LST_IGNORE_WARNING
        ):
            nwarn += 1
            key = ("warning", _error_signature(line))
            groups.setdefault(
                key, {"line": i, "text": line.strip(), "count": 0}
            )["count"] += 1
    ordered = sorted(
        ({"kind": k[0], **v} for k, v in groups.items()),
        key=lambda g: (-g["count"], g["line"]),
    )
    return {
        "steps": steps,
        "hard": sorted(hard.values(), key=lambda h: h["line"]),
        "groups": ordered,
        "nerr": nerr,
        "nwarn": nwarn,
    }


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
        if _is_hard_signal(line) and len(errs) < cap:
            errs.append(f"{i}: {line}")
            continue
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
        # Un échec d'étape EST une erreur, même sans le mot « error » : sinon le
        # tableau de bord affiche « 0 erreur » sur une installation ratée —
        # mesuré sur erplibre-ubuntu-2604-gnome, 0 ligne « error » pour un APK
        # tué par le noyau.
        if _is_hard_signal(line):
            nerr += 1
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


def _host_mem() -> tuple:
    """(total, disponible, swap_total, swap_libre) en octets, lus dans /proc.

    /proc/meminfo plutôt qu'une dépendance : psutil n'est pas garanti dans le
    venv d'outils, et ce suivi tourne sur l'hyperviseur — donc sous Linux, d'où
    viennent déjà getloadavg() et libvirt.

    « MemAvailable » et non « MemFree » : le noyau y répond ce qu'il peut
    rendre sans échanger, cache réclamable compris. MemFree seul affiche
    presque rien sur une machine qui travaille, et alarmerait pour rien.
    """
    wanted = ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")
    vals = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                if key in wanted:
                    vals[key] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return (0, 0, 0, 0)
    return tuple(vals.get(k, 0) for k in wanted)


def _mem_tele(total, avail, sw_total, sw_free) -> str:
    """Segment « RAM » de la barre de télémétrie. Vide si /proc n'a rien dit.

    Le swap n'apparaît que s'il existe : l'afficher à « 0/0 » sur une machine
    qui n'en a pas occupe une place pour ne rien dire. Quand il existe, il est
    montré même à zéro — une VM qui a commencé à échanger explique une lenteur,
    et c'est précisément ce qu'on cherche dans un suivi d'installation.
    """
    if not total:
        return ""
    used = max(0, total - avail)
    out = (
        f"🧠 RAM {_fmt_size(used)}/{_fmt_size(total)}"
        f" ({int(used / total * 100)}%)"
        f" · {t('free space')} {_fmt_size(avail)}"
    )
    if sw_total:
        out += (
            f" · swap {_fmt_size(max(0, sw_total - sw_free))}"
            f"/{_fmt_size(sw_total)}"
        )
    return out


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


# Navigateurs CLI installables via apt/dnf/pacman (nom de paquet = binaire).
# browsh/carbonyl ne sont pas dans les dépôts standard -> non proposés ici.
INSTALLABLE_BROWSERS = (
    ("w3m", "w3m — léger, rend un peu de HTML"),
    ("lynx", "lynx — navigateur texte"),
    ("links", "links — texte / graphique"),
    ("elinks", "elinks — texte, onglets"),
)


def browser_install_command(browser="w3m") -> list | None:
    """Commande d'installation du navigateur CLI `browser`, ou None si aucun
    gestionnaire de paquets connu.

    Les navigateurs proposés portent le même nom de paquet dans les quatre
    familles ; todo_install choisit la commande. Cette écriture-ci ne
    connaissait pas zypper, et openSUSE ne pouvait donc en installer aucun."""
    # Importé ici et non en tête : l'import de todo_i18n de ce module est
    # protégé pour qu'il tourne en autonome, et todo_install en dépend.
    from script.todo import todo_install

    return todo_install.install_command([browser])


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


# Fenêtre du débit d'écriture. Dix secondes : le disque d'une VM en
# installation travaille par rafales — « apt » décompresse, « poetry » compile,
# puis plus rien pendant trois secondes. Un instantané de deux secondes affiche
# donc tantôt 0, tantôt 200 Mo/s, et ne dit rien. Sur dix secondes, le chiffre
# devient un débit qu'on peut comparer d'une VM à l'autre.
WRITE_WINDOW = 10.0

# Âge maximal d'un relevé du ballon mémoire. Au-delà, la valeur est TAISÉE
# plutôt que montrée : virtio-balloon ne publie ses compteurs que si une
# période de collecte est armée, et une valeur figée depuis une demi-heure
# ferait croire à une VM au repos alors qu'elle compile.
BALLOON_MAX_AGE = 30.0

# Les compteurs du ballon sont en kibioctets ; ceux des blocs, en octets.
_KIB = 1024


def parse_domstats(text: str) -> dict:
    """Sortie de « virsh domstats » -> {nom: relevé}.

    Un relevé porte : ram_used / ram_total (octets), ram_at (horodatage du
    dernier rapport du ballon), wr_bytes (cumul écrit depuis le démarrage du
    processus QEMU), disk_used / disk_total (octets).

    Le seed ISO est ÉCARTÉ des disques : monté en lecture seule, il n'est
    jamais écrit, et sa capacité (quelques mégaoctets) l'aurait fait passer
    pour le disque système sur une VM dont le qcow2 n'est pas encore alloué.
    """
    out = {}
    nom = None
    brut = {}

    def clore():
        if nom is None:
            return
        rec = {
            "ram_used": 0,
            "ram_total": 0,
            "ram_at": 0,
            "wr_bytes": 0,
            "disk_used": 0,
            "disk_total": 0,
        }
        dispo = brut.get("balloon.available")
        util = brut.get("balloon.usable")
        if dispo:
            rec["ram_total"] = dispo * _KIB
            if util is not None:
                rec["ram_used"] = max(0, (dispo - util)) * _KIB
        rec["ram_at"] = brut.get("balloon.last-update") or 0
        # Disques : on parcourt les index déclarés par block.count.
        meilleur = 0
        for i in range(int(brut.get("block.count") or 0)):
            chemin = brut.get(f"block.{i}.path.str") or ""
            if chemin.lower().endswith(".iso"):
                continue
            rec["wr_bytes"] += brut.get(f"block.{i}.wr.bytes") or 0
            cap = brut.get(f"block.{i}.capacity") or 0
            if cap >= meilleur:
                meilleur = cap
                rec["disk_total"] = cap
                rec["disk_used"] = brut.get(f"block.{i}.allocation") or 0
        out[nom] = rec

    for ligne in (text or "").splitlines():
        ligne = ligne.strip()
        if ligne.startswith("Domain:"):
            clore()
            nom = ligne.split("'")[1] if "'" in ligne else None
            brut = {}
            continue
        if nom is None or "=" not in ligne:
            continue
        cle, _, val = ligne.partition("=")
        try:
            brut[cle] = int(val)
        except ValueError:
            # Les valeurs non numériques (chemins, noms de device) sont
            # gardées à part : « block.0.path » en est une, et c'est elle qui
            # démasque le seed ISO.
            brut[f"{cle}.str"] = val
    clore()
    return out


class WriteWindow:
    """Débit d'écriture moyen par VM, sur une fenêtre glissante."""

    def __init__(self, window=WRITE_WINDOW):
        self.window = window
        self._hist = {}

    def add(self, name, wr_bytes, now):
        hist = self._hist.setdefault(name, [])
        # Un compteur qui RECULE veut dire que le domaine a redémarré : le
        # processus QEMU est neuf, ses compteurs repartent de zéro. Sans ce
        # garde, le débit affiché serait négatif, puis énorme au relevé
        # suivant. Une installation redémarre la VM : le cas est la règle.
        if hist and wr_bytes < hist[-1][1]:
            hist.clear()
        hist.append((now, wr_bytes))
        limite = now - self.window
        while len(hist) > 2 and hist[1][0] < limite:
            hist.pop(0)

    def rate(self, name):
        """Octets/s, ou None tant que la fenêtre n'a pas de quoi conclure."""
        hist = self._hist.get(name) or []
        if len(hist) < 2:
            return None
        span = hist[-1][0] - hist[0][0]
        if span < 1.0:
            return None
        return max(0.0, (hist[-1][1] - hist[0][1]) / span)

    def total(self, name):
        """Écrit depuis le premier relevé de la fenêtre (octets)."""
        hist = self._hist.get(name) or []
        return hist[-1][1] if hist else None


def fmt_rate(bps) -> str:
    """Octets/s -> « 12.3M/s ». « - » tant qu'on ne sait pas."""
    return "-" if bps is None else f"{_fmt_size(int(bps))}/s"


def _fmt_tight(nbytes) -> str:
    """Comme _fmt_size, mais sans décimale au-delà de dix unités.

    « 63G » plutôt que « 62.6G » : dans une colonne de tableau, ces deux
    caractères décident si « Disque » reste visible ou sort de l'écran, et la
    décimale n'apprend rien à côté d'un total de 65 Go.
    """
    if nbytes is None:
        return "-"
    for unit, div in (("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20)):
        if nbytes >= div:
            val = nbytes / div
            return f"{val:.0f}{unit}" if val >= 10 else f"{val:.1f}{unit}"
    return f"{max(0, int(nbytes)) // 1024}K"


def fmt_pair(used, total) -> str:
    """« 1.1G/12G », « 63G/65G ». « - » si le total manque : « ?/12G »
    n'informe pas."""
    if not total:
        return "-"
    return f"{_fmt_tight(used)}/{_fmt_tight(total)}"


def fmt_pct(used, total) -> str:
    return f" ({int(used / total * 100)}%)" if total else ""


def ram_pair(rec, now, max_age=BALLOON_MAX_AGE) -> str:
    """RAM utilisée/totale de la VM, ou « - » si le relevé est PÉRIMÉ."""
    if not rec or not rec.get("ram_total"):
        return "-"
    at = rec.get("ram_at") or 0
    if at and now - at > max_age:
        return "-"
    return fmt_pair(rec.get("ram_used"), rec["ram_total"])


def vm_stats_line(name, rec, bps, now, ecrit=None) -> str:
    """Section statistiques d'UNE VM, en une ligne dense.

    Le tableau porte les mêmes chiffres en colonnes, pour tout le parc d'un
    coup d'œil ; cette ligne les détaille pour la VM sélectionnée — celle dont
    le journal et la commande SSH sont déjà affichés.
    """
    if not rec:
        return f"  📊 {name} · {t('no statistics yet')}"
    bits = [f"✍ {fmt_rate(bps)} ({t('10s average')})"]
    if ecrit:
        bits.append(f"{t('total written')} {_fmt_size(ecrit)}")
    ram = ram_pair(rec, now)
    if ram != "-":
        bits.append(
            f"🧠 RAM {ram}{fmt_pct(rec['ram_used'], rec['ram_total'])}"
        )
    if rec.get("disk_total"):
        bits.append(
            f"💾 {t('disk')} "
            f"{fmt_pair(rec['disk_used'], rec['disk_total'])}"
            f"{fmt_pct(rec['disk_used'], rec['disk_total'])}"
        )
    return f"  📊 {name} · " + " · ".join(bits)


def read_domstats() -> str:
    """Sortie brute de « virsh domstats --balloon --block » (tout le parc).

    UN appel pour toutes les VM — 0,03 s mesuré sur deux domaines. Le suivi
    relève toutes les deux secondes : une commande par VM y coûterait N
    processus à chaque tour."""
    try:
        res = subprocess.run(
            ["sudo", "virsh", "domstats", "--balloon", "--block"],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout if res.returncode == 0 else ""


# UN appel par HÔTE : « /cluster/resources » rend l'état, la mémoire, le
# disque et le cumul écrit de TOUTES ses VM d'un coup. Le « du » qui suit
# donne la taille RÉELLEMENT occupée : sur un stockage en fichiers, Proxmox
# rapporte « disk: 0 » — il ne la calcule pas.
#
# « -sB1 » et NON « -sb » : le second rend la taille APPARENTE, et un disque
# raw creux de 6 Go la donne entière. La colonne affichait donc « 6.0G/6.0G »,
# un disque plein, quand l'invité n'avait écrit que 1,2 Go — rapporté.
PVE_STATS_CMD = (
    "pvesh get /cluster/resources --type vm --output-format json;"
    " echo '---ERPLIBRE-DU---';"
    " du -sB1 /var/lib/vz/images/*/ 2>/dev/null || true"
)
# Une VM distante se relève moins souvent qu'une locale : chaque tour coûte
# une poignée de main ssh (mesuré 1 s), quand « virsh domstats » coûte 0,03 s
# pour tout le parc. Cinq secondes suffisent à voir une installation avancer.
PVE_STATS_INTERVAL = 5.0

# Une VM locale DÉJÀ verte est resondée à cette cadence, pas à chaque tour.
# La sonde est un connect() TCP par VM : à chaque tour (2 s) c'est cher pour
# une réponse qui ne bouge presque jamais, jamais c'est un mensonge — Odoo
# redémarre au moins une fois pendant l'installation, et il lui arrive de
# mourir. Trente secondes bornent le mensonge à un demi-écran de journal.
ODOO_RECHECK = 30.0


def odoo_reading(vm, releve, deja_vert, dernier, maintenant, sonde):
    """Odoo répond-il sur cette VM ? (état ou None, sondé ?)

    None veut dire « pas de réponse ce tour-ci », et NON « Odoo est tombé » :
    l'appelant garde alors le dernier état connu. C'est toute la différence
    entre un hôte muet et une VM qui ne sert plus rien.

    Deux voies, parce que la sonde n'a pas le même prix. Sur une VM Proxmox
    le port a été testé DEPUIS L'HÔTE, dans l'appel des statistiques — d'ici,
    une adresse de pont interne ne répond jamais — donc c'est gratuit et relu
    à chaque tour. Sur une VM locale c'est un connect() TCP par VM : on la
    refait tant qu'elle est rouge, puis seulement toutes les ODOO_RECHECK
    secondes.

    Ce qu'on ne fait plus, c'est ne jamais la refaire. « Odoo ne redescend pas
    en cours d'install » était faux : le service redémarre au moins une fois,
    et il lui arrive de mourir. Le 🟢 restait alors acquis pour toujours.
    """
    if vm.get("pve"):
        return (bool(releve.get("odoo")) if releve else None), False
    if deja_vert and maintenant - dernier < ODOO_RECHECK:
        return None, False
    return bool(sonde(vm.get("ip"), 8069)), True


# Proxmox dit « running » / « stopped » ; le suivi raisonne en états libvirt.
# Une VM absente de la réponse de l'hôte a vraiment disparu.
PVE_ETATS = {"running": "running", "stopped": "shut off", "paused": "paused"}
_PVE_CACHE = {"at": 0.0, "stats": {}, "ok": False}


def pve_stats_cmd(adresses=()) -> str:
    """PVE_STATS_CMD, plus un test du port 8069 pour les adresses données.

    Dans le MÊME appel : la colonne Odoo teste ce port depuis le poste, et une
    VM sur pont interne n'y répond jamais — elle restait « — » quel que soit
    l'état d'Odoo. Depuis l'hôte, elle répond. Un aller-retour ssh de plus par
    tour aurait coûté une seconde ; celui-ci est déjà payé.
    """
    if not adresses:
        return PVE_STATS_CMD
    liste = " ".join(shlex.quote(a) for a in adresses)
    return (
        PVE_STATS_CMD
        + "; echo '---ERPLIBRE-ODOO---'; for a in "
        + liste
        + '; do timeout 2 bash -c "echo > /dev/tcp/$a/8069" 2>/dev/null'
        + ' && echo "ODOO $a"; done'
    )


def _resources_parsable(text: str) -> bool:
    """La sortie porte-t-elle une LISTE de ressources lisible ?

    C'est la seule preuve que l'hôte a répondu : le code de sortie est celui
    du dernier maillon de la suite, pas celui de « pvesh ».
    """
    brut, _, _ = (text or "").partition("---ERPLIBRE-DU---")
    try:
        return isinstance(json.loads(brut.strip() or "null"), list)
    except ValueError:
        return False


def parse_odoo_probe(text: str) -> set:
    """Adresses dont le port 8069 a répondu, d'après pve_stats_cmd."""
    _, _, bloc = (text or "").partition("---ERPLIBRE-ODOO---")
    return {
        ligne.split()[1]
        for ligne in bloc.splitlines()
        if ligne.startswith("ODOO ") and len(ligne.split()) == 2
    }


def parse_pvestats(text: str) -> dict:
    """Sortie de PVE_STATS_CMD -> {VMID: relevé}, même forme que domstats.

    Par VMID et non par NOM, et c'est tout le sujet. « /cluster/resources »
    est bâti par pvestatd ; celui-ci arrêté, l'hôte rend quand même une entrée
    par VM, mais SQUELETTIQUE :

        {"id":"qemu/100","node":"…","status":"unknown","type":"qemu",
         "vmid":100}

    Ni nom, ni mémoire, ni disque. Indexée par nom, cette entrée disparaissait
    — la VM était donc « absente du relevé » alors que l'hôte venait de la
    nommer. Trois tours plus tard : 🗑, état TERMINAL, et le suivi annonçait
    « 1/1 terminées » au bout de neuf secondes sur une installation qui
    tournait. Le VMID, lui, est toujours là ; c'est d'ailleurs le seul
    identifiant unique d'un hôte Proxmox.

    Même forme que domstats exprès : les colonnes, le débit d'écriture et la
    RAM se calculent alors sans savoir d'où vient la mesure.
    """
    brut, _, tailles = (text or "").partition("---ERPLIBRE-DU---")
    try:
        ressources = json.loads(brut.strip() or "[]")
    except ValueError:
        return {}
    # {vmid: octets} depuis « du -sB1 /var/lib/vz/images/<vmid>/ ».
    occupe = {}
    for ligne in tailles.splitlines():
        parts = ligne.split()
        if len(parts) == 2 and parts[0].isdigit():
            vmid = parts[1].rstrip("/").rsplit("/", 1)[-1]
            if vmid.isdigit():
                occupe[int(vmid)] = int(parts[0])
    out = {}
    maintenant = time.time()
    for r in ressources if isinstance(ressources, list) else ():
        vmid = int(r.get("vmid") or 0)
        if not vmid:
            continue
        total = int(r.get("maxdisk") or 0)
        utilise = int(r.get("disk") or 0) or occupe.get(vmid, 0)
        out[vmid] = {
            # Le nom reste DANS le relevé : il ne sert plus de clé, mais il
            # aide à lire un journal quand les deux divergent.
            "name": r.get("name") or "",
            "ram_used": int(r.get("mem") or 0),
            "ram_total": int(r.get("maxmem") or 0),
            # Le relevé vient d'être fait : il n'est pas périmé, et c'est ce
            # que `ram_pair` vérifie avant d'afficher quoi que ce soit.
            "ram_at": maintenant,
            "wr_bytes": int(r.get("diskwrite") or 0),
            "disk_used": utilise,
            "disk_total": total,
            "state": r.get("status") or "",
            "uptime": int(r.get("uptime") or 0),
        }
    return out


# Combien de relevés SUCCESSIFS sans la VM avant de la déclarer effacée. Un
# seul silence ne prouve rien : l'hôte peut être occupé, la VM en train de
# démarrer, le relevé en cache d'avant sa création. Or « effacée » est un état
# TERMINAL — la ligne gèle sur 🗑 et ne revient jamais. Vécu sur une VM Arch
# déployée sur Proxmox : poubelle dès le premier tour.
PVE_ABSENCES_AVANT_EFFACEE = 3


def read_pvestats_detail(vms, now=None):
    """(relevés, l'hôte a-t-il répondu ?).

    La nuance décide de tout : sans réponse, on ne sait RIEN — et ne rien
    savoir n'est pas la même chose que savoir que la VM a disparu.
    """
    stats, ok = _read_pvestats(vms, now)
    return stats, ok


def read_pvestats(vms, now=None) -> dict:
    """{nom: relevé} des VM posées sur un hôte Proxmox, ou {}."""
    return _read_pvestats(vms, now)[0]


def drop_local_twins(stats, vms) -> dict:
    """Retire des relevés LOCAUX ceux d'une VM qui vit ailleurs.

    « virsh domstats » indexe par NOM, et un nom se partage : une VM posée
    sur un Proxmox distant héritait des chiffres du domaine local homonyme.
    Vécu sur trois VM — « erplibre-ubuntu-2604 » affichait 1,5 Gio de RAM sur
    12 et 58 Gio de disque sur 65, tout cela appartenant à la machine locale
    du même nom, pendant que la vraie tournait avec 3 Gio et 25.

    Retirés AVANT d'ajouter ceux de l'hôte : ainsi un hôte muet laisse la
    colonne VIDE — ce qui est vrai — au lieu de la remplir avec la mauvaise
    machine. Une colonne vide se remarque ; une colonne juste et fausse, non.
    """
    for vm in vms or ():
        if vm.get("pve"):
            stats.pop(vm.get("name"), None)
    return stats


def _read_pvestats(vms, now=None):
    """({nom: relevé}, succès). Un appel par hôte, mis en cache
    PVE_STATS_INTERVAL secondes.

    Les VM concernées sont celles dont le manifeste porte un bloc « pve »
    (adresse de l'hôte, sudo, vmid).
    """
    hotes = {}
    for vm in vms or ():
        info = vm.get("pve") or {}
        if info.get("target"):
            hotes[(info["target"], info.get("sudo") or "")] = info
    if not hotes:
        return {}, False
    maintenant = now if now is not None else time.time()
    # « at > 0 » explicitement : sans lui, un tout PREMIER relevé pris moins de
    # cinq secondes après l'époque tombait dans un cache vide et rendait
    # « l'hôte n'a pas répondu » sans avoir rien demandé. Invisible en
    # production, mais c'est la logique qui est fausse.
    if (
        _PVE_CACHE["at"] > 0
        and maintenant - _PVE_CACHE["at"] < PVE_STATS_INTERVAL
    ):
        return dict(_PVE_CACHE["stats"]), bool(_PVE_CACHE.get("ok"))
    try:
        from script.proxmox import proxmox_deploy as pve
    except ImportError:  # pragma: no cover - le module est dans le dépôt
        return {}, False
    # {nom: adresse interne} — ce qui permet de tester Odoo depuis l'hôte.
    adresses = {
        vm["name"]: (vm.get("pve") or {}).get("addr")
        for vm in vms or ()
        if (vm.get("pve") or {}).get("addr")
    }
    stats, ok = {}, False
    for (target, sudo), info in hotes.items():
        siennes = [
            a
            for nom, a in adresses.items()
            if (
                (
                    next((v for v in vms if v["name"] == nom), {}).get("pve")
                    or {}
                ).get("target")
                == target
            )
        ]
        _code, sortie = pve.run(
            {"target": target, "sudo": sudo, "jump": info.get("jump", "")},
            pve_stats_cmd(siennes),
            40,
        )
        # Le code de sortie ne prouve RIEN, dans AUCUN sens. La commande
        # est une SUITE (pvesh ; echo ; du ; echo ; boucle) et son code est
        # celui du DERNIER maillon — la sonde Odoo. Un pvesh en panne rendait
        # donc 0, « l'hôte a répondu, la VM n'y est plus », et trois tours
        # plus tard la poubelle ; c'est ce qu'on avait corrigé. Mais
        # l'exiger à 0 était l'erreur SYMÉTRIQUE : tant qu'Odoo n'écoute pas
        # — c'est-à-dire pendant TOUTE l'installation, précisément quand on
        # regarde — la boucle finit en échec et le relevé, parfait, était
        # jeté. Mesuré sur trois VM : colonnes vides côté Proxmox, et les
        # lignes qui avaient un homonyme LOCAL affichaient ses chiffres.
        #
        # Ce qui prouve une réponse, c'est une LISTE de ressources
        # analysable. Rien d'autre, et surtout pas le code.
        if _resources_parsable(sortie):
            ok = True
            # {VMID: relevé} -> {nom du manifeste: relevé}. La correspondance
            # se fait ICI, où le manifeste est sous les yeux : lui seul dit
            # quel VMID porte quel nom, et l'hôte peut très bien ne pas
            # nommer ses VM (pvestatd arrêté).
            releves = parse_pvestats(sortie)
            ouverts = parse_odoo_probe(sortie)
            for vm in vms or ():
                pve_info = vm.get("pve") or {}
                if pve_info.get("target") != target:
                    continue
                rec = releves.get(int(pve_info.get("vmid") or 0))
                if not rec:
                    continue
                rec["odoo"] = adresses.get(vm["name"]) in ouverts
                stats[vm["name"]] = rec
    _PVE_CACHE.update({"at": maintenant, "stats": stats, "ok": ok})
    return dict(stats), ok


def web_tunnel_argv(info, port=18069, cible_port=8069):
    """argv d'un tunnel local vers le port web d'une VM distante, ou None.

    Une VM sur pont interne n'est pas routable d'ici : un navigateur ne peut
    pas l'atteindre, et la touche « w » ouvrait une page morte. Le tunnel
    passe par l'hôte, dure le temps de la visite, et se referme par son PID —
    « pkill -f <motif> » tuait le shell qui l'avait lancé, le motif figurant
    dans sa propre ligne de commande.
    """
    info = info or {}
    if not (info.get("addr") and info.get("target")):
        return None
    argv = ["ssh", "-N", "-o", "ExitOnForwardFailure=yes"]
    if info.get("jump"):
        argv += ["-J", info["jump"]]
    argv += ["-L", f"{port}:{info['addr']}:{cible_port}", info["target"]]
    return argv


def vm_ssh_prefix(vm) -> str:
    """« ssh … » pour entrer dans CETTE VM, adresse comprise.

    Une VM d'un hôte Proxmox vit derrière lui : son adresse n'est pas
    routable d'ici, et seul le rebond y mène. On le construit explicitement
    plutôt que de compter sur un alias ~/.ssh/config, qui peut ne pas exister
    — ou, pire, désigner une VM LOCALE homonyme. C'est ce qui a fait ouvrir
    la mauvaise machine avec « s ».
    """
    info = (vm or {}).get("pve") or {}
    adresse = info.get("addr")
    if info.get("target") and adresse:
        saut = f"-J {shlex.quote(info['jump'])} " if info.get("jump") else ""
        return (
            f"ssh {SSH_OPTS} {saut}-J {shlex.quote(info['target'])} "
            f"erplibre@{adresse}"
        )
    return f"ssh {SSH_OPTS} erplibre@{(vm or {}).get('ip')}"


def pve_host_cmd(info, remote, tty=False) -> str:
    """Commande shell qui exécute `remote` SUR l'hôte Proxmox d'une VM.

    Chaque action du tableau de bord qui parlait à libvirt par le NOM frappait
    la mauvaise machine dès qu'un domaine local portait le même : la console
    ouvrait celle de la VM locale, la pause suspendait la locale. L'hôte est
    la seule autorité pour une VM distante, et le VMID son seul identifiant.
    """
    sudo = (info or {}).get("sudo") or ""
    cible = (info or {}).get("target") or ""
    prefixe = f"{sudo}sh -c {shlex.quote(remote)}" if sudo else remote
    saut = (
        f"-J {shlex.quote(info['jump'])} " if (info or {}).get("jump") else ""
    )
    return (
        f"ssh {'-t ' if tty else ''}{saut}{shlex.quote(cible)} "
        f"{shlex.quote(prefixe)}"
    )


def arm_balloon(names) -> None:
    """Arme la période de collecte du ballon (5 s) sur chaque VM.

    Sans elle, « balloon.available » et « balloon.usable » restent FIGÉS sur le
    dernier rapport du pilote : mesuré sur une VM fraîche, 388 Mo annoncés
    contre 1,1 Go réellement occupés, avec un horodatage vieux d'une
    demi-heure. La période se perd quand le domaine redémarre — ce qu'une
    installation fait — donc on la réarme à intervalle lent.
    """
    for name in names or ():
        try:
            subprocess.run(
                [
                    "sudo",
                    "virsh",
                    "dommemstat",
                    name,
                    "--period",
                    "5",
                    "--live",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            )
        except (OSError, subprocess.SubprocessError):
            continue


# --------------------------------------------------------------------------- #
# Dashboard Textual
# --------------------------------------------------------------------------- #
# Largeurs de colonnes du tableau de suivi. Une seule source : la
# construction du tableau les lit ici, et « 0 » y revient. Les redéclarer à
# deux endroits, c'est garantir qu'un jour la remise à zéro rendra autre chose
# que ce qui était affiché au départ.
COL_DEFAULT_WIDTHS = {
    "seq": 3,
    # 21 : un caractère de moins que l'ancien 22, et c'est lui qui fait tenir
    # la ligne entière sur un terminal de 150 colonnes. « + » l'élargit, et
    # c'est déjà la colonne visée par défaut.
    "vm": 21,
    # 5 : « amd64 », « s390x », « arm64 » font cinq caractères, et l'en-tête
    # « Arch » quatre. Les deux de plus ne servaient rien.
    "arch": 5,
    "err": 4,
    "state": 8,
    # 4 : une icône (🟢) ou un tiret, sous un en-tête de quatre lettres.
    "odoo": 4,
    # 6 : « 125:30 » est le pire cas d'une installation de deux heures.
    "elapsed": 6,
    # Section statistiques de la VM : ce qu'elle écrit, sa RAM, son disque.
    # « 12.3M/s » tient en 7 et « 1.1G/12G » en 9 : au-delà, « Disque » sortait
    # de l'écran sur un terminal de 150 colonnes, moitié prise par le journal.
    "wr": 7,
    # 10 et non 9 : sur une VM de 128 Go, « 1001M/128G » fait dix caractères.
    "ram": 10,
    "disk": 9,
}


# Parties d'une remise à jour, dans l'ordre où elles doivent tourner : les
# paquets système d'abord (compilateurs et en-têtes), le code ensuite, les
# dépendances Python en dernier — elles se compilent contre les deux premiers.
UPDATE_PARTS = (
    ("system", "Paquets systeme (apt/dnf/pacman/zypper)"),
    ("git", "Depots git (ERPLibre + addons)"),
    ("python", "Dependances Python (poetry)"),
)
EL_DIR = "~/git/erplibre"


def update_remote_cmd(parts) -> str:
    """Commande exécutée DANS la VM pour remettre à jour ce qui est coché.

    Rien n'est enchaîné par « && » : une partie qui échoue ne doit pas
    empêcher les suivantes, et son code de retour se lit dans la sortie.
    Chaque bloc s'annonce, sinon un log de mise à jour est illisible."""
    chosen = [p for p in parts if p in dict(UPDATE_PARTS)]
    if not chosen:
        return ""
    out = ["set -u"]
    if "system" in chosen:
        out.append(
            'echo "== Paquets systeme =="; '
            "if command -v apt-get >/dev/null 2>&1; then "
            "sudo apt-get -o DPkg::Lock::Timeout=600 update -qq "
            "&& sudo DEBIAN_FRONTEND=noninteractive "
            "apt-get -o DPkg::Lock::Timeout=600 -y upgrade; "
            "elif command -v dnf >/dev/null 2>&1; then "
            "sudo dnf -y upgrade --refresh; "
            "elif command -v pacman >/dev/null 2>&1; then "
            # Arch ne supporte pas la mise à jour partielle : -Syu, jamais -S.
            "pgrep -x pacman >/dev/null 2>&1 "
            "|| sudo rm -f /var/lib/pacman/db.lck; "
            "sudo pacman -Syu --noconfirm; "
            "elif command -v zypper >/dev/null 2>&1; then "
            ". /etc/os-release; "
            'case "$ID" in *tumbleweed*) '
            "sudo zypper --non-interactive dup "
            "--auto-agree-with-licenses --allow-vendor-change;; "
            "*) sudo zypper --non-interactive up "
            "--auto-agree-with-licenses;; esac; "
            'else echo "Gestionnaire de paquets inconnu"; fi; '
        )
    if "git" in chosen:
        out.append(
            'echo "== Depots git =="; '
            f"cd {EL_DIR} || exit 1; "
            # --ff-only : une VM ne doit jamais fusionner toute seule. Un
            # historique divergent s'arrête ici, visiblement.
            "git pull --ff-only; "
            # Les addons viennent de Google Repo, pas de git : c'est le script
            # de l'installation qui sait les synchroniser.
            "./script/install/install_git_repo.sh; "
        )
    if "python" in chosen:
        out.append(
            'echo "== Dependances Python =="; '
            f"cd {EL_DIR} || exit 1; "
            # La phase « poetry » seule : ni venvs ni repo, juste les paquets.
            "EL_PHASE=poetry ./script/install/install_locally.sh; "
        )
    out.append('echo "== Mise a jour terminee =="')
    return "".join(out[:1]) + "; " + "".join(out[1:])


def restart_odoo_cmd() -> str:
    """Redémarre le service ERPLibre, ou le lance à la main s'il n'existe pas.

    Une VM installée sans profil de production n'a pas forcément l'unité
    systemd : le repli dit quoi faire plutôt que d'échouer sans un mot."""
    return (
        "if systemctl list-unit-files 2>/dev/null | grep -q '^erplibre'; then "
        "sudo systemctl restart erplibre.service "
        "&& sudo systemctl --no-pager --lines=15 status erplibre.service; "
        "else echo 'Pas de service erplibre : lancez ./run.sh dans "
        f"{EL_DIR}'; fi"
    )


def pve_identity_guard(vmid: int, name: str) -> str:
    """Shell qui S'ARRÊTE si le VMID ne porte plus ce nom.

    Un VMID libéré est RÉATTRIBUÉ, et le suivi se rouvre sur un manifeste qui
    peut avoir des semaines : effacer « le 101 » d'un run de mars, c'est
    effacer ce qui porte le 101 aujourd'hui.

    Une fonction à part, et exécutable telle quelle : c'est ce qui la rend
    vérifiable. Enfouie dans la commande, elle ne se testait qu'à travers deux
    « shlex.quote » — et un garde qu'on ne sait pas éprouver s'OUVRE le jour
    où il casse, au lieu de se fermer."""
    q = shlex.quote(name)
    return (
        f"vu=$(qm config {int(vmid)} 2>/dev/null"
        " | sed -n 's/^name: //p' | head -1); "
        f'if [ "$vu" != {q} ]; then '
        f'echo "REFUS : le VMID {int(vmid)} porte maintenant $vu,"'
        f' "et non {name}. Rien n\'a ete efface."; exit 1; fi; '
    )


def delete_vm_cmd_pve(info, purge: bool = True, name: str = "") -> str:
    """Efface une VM sur son hôte PROXMOX, par son VMID.

    « virsh undefine <nom> » y aurait effacé le domaine LOCAL homonyme — le
    même piège que partout ailleurs, avec la pire conséquence.

    `name` arme le garde d'identité (voir `pve_identity_guard`) : sans lui, la
    commande efface le VMID quoi qu'il porte aujourd'hui."""
    vmid = int((info or {}).get("vmid") or 0)
    suite = pve_identity_guard(vmid, name) if name else ""
    suite += (
        f"qm stop {vmid} --skiplock 1 || true; "
        f"qm destroy {vmid}"
        f"{' --purge 1 --destroy-unreferenced-disks 1' if purge else ''}"
    )
    return pve_host_cmd(info, suite)


def delete_lines(vm) -> list:
    """Ce qui va RÉELLEMENT disparaître, dit selon l'endroit où la VM vit.

    L'écran annonçait à toute VM « son disque qcow2 EFFACÉ », puis nommait
    /var/lib/libvirt/images/<nom>.qcow2. Sur une VM Proxmox ce fichier
    n'existe pas : son disque vit dans un stockage que seul l'hôte connaît, et
    la ligne désignait donc un fichier local — au mieux inexistant, au pire
    celui d'une autre VM du même nom. C'est exactement la peur qui a fait
    remonter le nettoyage : « le nettoyage risque d'effacer des VM en
    production ».

    Une confirmation doit nommer ce qu'elle détruit, sur la machine où elle
    le détruit."""
    info = vm.get("pve")
    if not info:
        return [
            "La VM est arrêtée, sa définition retirée,",
            "et son disque qcow2 EFFACÉ. Rien n'est récupérable.",
            "",
            f"  /var/lib/libvirt/images/{vm['name']}.qcow2",
        ]
    hote = info.get("target") or "?"
    return [
        f"Sur l'hôte Proxmox {hote}, la VM {info.get('vmid')} est arrêtée",
        "puis DÉTRUITE avec ses disques. Rien n'est récupérable.",
        "",
        f"  qm destroy {info.get('vmid')} --purge",
        "",
        "Aucun fichier n'est touché ici : le disque vit dans le",
        "stockage de l'hôte.",
    ]


def delete_vm_cmd(name: str, with_disks: bool, uuid: str = "") -> str:
    """Efface la VM sur l'HÔTE. Même séquence que « TODO._qemu_delete_vm » :
    arrêt, retrait de la définition (nvram si UEFI, repli sinon), puis les
    disques à la demande.

    `uuid` arme un GARDE. Le suivi se rouvre sur un manifeste passé, et un nom
    de domaine se réemploie : « erplibre-ubuntu-2604 » d'un run de mars n'est
    pas forcément celui d'aujourd'hui. L'UUID, lui, naît avec le domaine et
    meurt avec lui — c'est la seule chose qui distingue deux machines du même
    nom."""
    q = shlex.quote(name)
    cmd = ""
    if uuid:
        cmd = (
            f"vu=$({sudo_prefix()}virsh domuuid {q} 2>/dev/null"
            " | tr -d '[:space:]'); "
            f'if [ "$vu" != {shlex.quote(uuid)} ]; then '
            f'echo "REFUS : {name} n\'est plus le même domaine"'
            f' "($vu). Rien n\'a été effacé."; exit 1; fi; '
        )
    cmd += (
        f"{sudo_prefix()}virsh destroy {q} 2>/dev/null; "
        f"{sudo_prefix()}virsh undefine {q} --nvram 2>/dev/null "
        f"|| {sudo_prefix()}virsh undefine {q}"
    )
    if with_disks:
        disk = shlex.quote(f"/var/lib/libvirt/images/{name}.qcow2")
        seed = shlex.quote(f"/var/lib/libvirt/images/iso/{name}-seed.iso")
        cmd += f"; sudo rm -f {disk} {seed}"
    return cmd


def run_monitor(manifest_path: str, run_app: bool = True):
    """Ouvre le dashboard Textual sur un manifeste d'installation. `run_app`
    à False renvoie l'instance sans la lancer (tests headless)."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import (
        Button,
        Checkbox,
        DataTable,
        Footer,
        Header,
        RichLog,
        Static,
    )

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

        def __init__(self, vm_name, errs, warns, summary=None):
            super().__init__()
            self._vm = vm_name
            self._errs = errs
            self._warns = warns
            self._sum = summary or {}

        def compose(self) -> ComposeResult:
            nsteps = len(self._sum.get("steps", []))
            head = (
                f"  {self._vm} — ⚠ {len(self._errs)} "
                f"{t('errors')} · ⚡ {len(self._warns)} {t('warnings')}"
            )
            # Le nombre d'étapes en échec passe DEVANT : c'est la seule ligne du
            # bandeau qui dise si l'installation a abouti.
            if nsteps:
                head = (
                    f"  {self._vm} — 🛑 {nsteps} "
                    f"{t('failed steps')} · ⚠ {len(self._errs)} "
                    f"{t('errors')} · ⚡ {len(self._warns)} {t('warnings')}"
                )
            with Vertical(id="errbox"):
                yield Static(f"{head}   ({t('Esc to close')})", id="errtitle")
                yield RichLog(
                    id="errlog", highlight=False, markup=False, wrap=True
                )

        def on_mount(self) -> None:
            log = self.query_one("#errlog", RichLog)
            steps = self._sum.get("steps", [])
            hard = self._sum.get("hard", [])
            groups = self._sum.get("groups", [])

            # -- Le résumé, d'abord. Une étape nommée vaut mille lignes.
            if steps:
                log.write(f"── {t('Failed steps')} ──")
                for st in steps:
                    log.write(f"🛑 {st['label']}   ({t('line')} {st['line']})")
                    for line in st["diag"]:
                        log.write(f"     {line.strip()}")
                    log.write("")
            if hard:
                log.write(f"── {t('Hard signals')} ──")
                for h in hard:
                    mult = f" ×{h['count']}" if h["count"] > 1 else ""
                    log.write(f"{h['line']}:{mult} {h['text']}")
                log.write("")
            if groups:
                # Regroupé par FORME : un journal répète la même erreur des
                # centaines de fois avec un chemin qui change.
                log.write(f"── {t('Grouped by shape')} ──")
                for g in groups[:60]:
                    mark = "⚠" if g["kind"] == "error" else "⚡"
                    mult = f" ×{g['count']}" if g["count"] > 1 else ""
                    log.write(f"{mark} {g['line']}:{mult} {g['text']}")
                log.write("")

            # -- Puis le détail brut, pour qui veut tout lire.
            if self._errs:
                log.write(f"── {t('errors').capitalize()} ──")
                for line in self._errs:
                    log.write(line)
            if self._warns:
                log.write(f"── {t('warnings').capitalize()} ──")
                for line in self._warns:
                    log.write(line)
            if not (steps or hard or self._errs or self._warns):
                log.write(t("No error detected."))

        def action_dismiss(self) -> None:
            self.dismiss()

    class ConfirmScreen(ModalScreen):
        """Confirmation d'une action irréversible. Le bouton dangereux n'est
        PAS le défaut : il faut le viser, pas juste appuyer sur Entrée."""

        BINDINGS = [("escape", "cancel", "Annuler")]

        def __init__(self, title, lines, danger_label):
            super().__init__()
            self._title = title
            self._lines = lines
            self._danger = danger_label

        def compose(self) -> ComposeResult:
            with Vertical(id="confbox"):
                yield Static(self._title, id="conftitle")
                for line in self._lines:
                    yield Static(line)
                with Horizontal(id="confbtns"):
                    yield Button("Annuler", variant="primary", id="c_no")
                    yield Button(self._danger, variant="error", id="c_yes")

        def on_button_pressed(self, event) -> None:
            self.dismiss(event.button.id == "c_yes")

        def action_cancel(self) -> None:
            self.dismiss(False)

    class VmActionsScreen(ModalScreen):
        """Les opérations d'une VM, rassemblées en un seul endroit.

        Plutôt que trois touches de plus dans un pied de page qui en compte
        déjà neuf : on voit ce qu'on va faire, et sur quelle machine."""

        BINDINGS = [("escape", "cancel", "Fermer")]

        def __init__(self, vm):
            super().__init__()
            self._vm = vm

        def compose(self) -> ComposeResult:
            with Vertical(id="actbox"):
                yield Static(
                    f"Actions — {self._vm['name']}  ({self._vm.get('ip') or '?'})",
                    id="acttitle",
                )
                yield Static("Remettre à jour", classes="actgroup")
                for key, label in UPDATE_PARTS:
                    yield Checkbox(label, value=True, id=f"u_{key}")
                yield Button(
                    "Lancer la mise à jour",
                    variant="primary",
                    id="a_update",
                )
                yield Static("Service", classes="actgroup")
                yield Button("Redémarrer Odoo", id="a_restart")
                yield Static("Irréversible", classes="actdanger")
                yield Button(
                    "Supprimer la VM et ses disques",
                    variant="error",
                    id="a_delete",
                )

        def on_button_pressed(self, event) -> None:
            if event.button.id == "a_update":
                parts = [
                    k
                    for k, _lbl in UPDATE_PARTS
                    if self.query_one(f"#u_{k}", Checkbox).value
                ]
                self.dismiss(("update", parts))
            elif event.button.id == "a_restart":
                self.dismiss(("restart", []))
            elif event.button.id == "a_delete":
                self.dismiss(("delete", []))

        def action_cancel(self) -> None:
            self.dismiss(None)

    ICON = {
        "pending": "⏳",
        "running": "⏳",
        "done": "✅",
        "failed": "❌",
    }

    class Monitor(App):
        CSS = """
        /* « width: 74 » figeait la table : au-delà, les colonnes élargies
        n'étaient plus atteignables, et la barre horizontale ne s'affichait
        pas faute de place réservée. « scrollbar-size » la rend VISIBLE plutôt
        que devinable, et « max-width » laisse la table suivre l'élargissement
        des colonnes sans manger tout l'écran. */
        DataTable {
            width: auto; max-width: 66%; height: 1fr;
            overflow-x: auto; overflow-y: auto;
            scrollbar-size-horizontal: 1; scrollbar-size-vertical: 1;
            border: solid $accent;
        }
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
        VmActionsScreen { align: center middle; }
        #actbox {
            width: 62; height: auto; padding: 1 2;
            border: thick $accent; background: $surface;
        }
        #acttitle { color: $accent; text-style: bold; padding-bottom: 1; }
        .actgroup { color: $accent; text-style: bold; padding: 1 0 0 0; }
        .actdanger { color: $error; text-style: bold; padding: 1 0 0 0; }
        ConfirmScreen { align: center middle; }
        #confbox {
            width: 66; height: auto; padding: 1 2;
            border: thick $error; background: $surface;
        }
        #conftitle { color: $error; text-style: bold; padding-bottom: 1; }
        #confbtns { height: auto; padding-top: 1; }
        """
        BINDINGS = [
            ("q", "quit", "Quitter (détaché)"),
            ("s", "ssh", "SSH"),
            ("v", "console", "Console (virsh)"),
            ("w", "web", "Web (navigateur CLI)"),
            ("f", "follow", "Suivre"),
            ("c", "copy_log", "Copier log"),
            ("d", "details", "Détails erreurs"),
            ("a", "vm_actions", "Actions VM"),
            # Mêmes touches que la TUI mail, qui redimensionne ses volets :
            # « + » élargit, « - » rétrécit, « 0 » remet tout d'aplomb.
            ("plus", "col_grow", "Colonne +"),
            ("minus", "col_shrink", "Colonne -"),
            ("0", "col_reset", "Colonnes par défaut"),
            ("less_than_sign", "col_prev", "Colonne précédente"),
            ("greater_than_sign", "col_next", "Colonne suivante"),
            ("p", "pause_all", "Pause tout"),
            ("o", "resume_all", "Reprendre tout"),
        ]

        def __init__(self):
            super().__init__()
            self._offsets = {vm["name"]: 0 for vm in vms}
            # Colonne visee par « + » / « - » : le nom de VM, celle qu'on a
            # vraiment besoin d'elargir. « < » et « > » la deplacent.
            self._col_target = list(COL_DEFAULT_WIDTHS).index("vm")
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
            # Statistiques par VM : dernier relevé libvirt, et la fenêtre
            # glissante qui en tire un débit d'écriture.
            self._vmstats = {}
            self._wrate = WriteWindow()
            # Erreurs détectées dans le log à la complétion : {nom: (err, warn)}.
            self._errcount = {}
            # Sommaire de stats déplié (clic) ou non.
            self._stats_open = False
            # VM dont l'UI Odoo (:8069) répond. RELUE, et non accumulée :
            # « Odoo ne redescend pas en cours d'install » est faux — il
            # redémarre au moins une fois (service systemd), et il lui arrive
            # de mourir. Un 🟢 acquis pour toujours affirmait alors qu'une VM
            # servait Odoo alors qu'elle ne servait plus rien.
            self._odoo_up = set()
            # Dernier tour où le port d'une VM DÉJÀ verte a été retesté. Sur
            # une VM locale la sonde est un connect() TCP par VM : la refaire
            # à chaque tour pour rien serait cher, la refaire jamais serait
            # faux. Sur Proxmox la question ne se pose pas — la réponse vient
            # avec les statistiques, gratuitement.
            self._odoo_revu = {}
            # Relevés SUCCESSIFS sans la VM, par nom : « effacée » est un état
            # terminal, il se mérite.
            self._pve_absences = {}
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
            table.add_column("#", key="seq", width=COL_DEFAULT_WIDTHS["seq"])
            table.add_column("VM", key="vm", width=COL_DEFAULT_WIDTHS["vm"])
            # L'architecture explique à elle seule qu'une installation dure
            # dix fois plus longtemps : s390x et arm64 sont ÉMULÉES sur un
            # hôte amd64. La voir évite de chercher la panne ailleurs.
            table.add_column(
                "Arch", key="arch", width=COL_DEFAULT_WIDTHS["arch"]
            )
            table.add_column("⚠", key="err", width=COL_DEFAULT_WIDTHS["err"])
            # width=8 : le plus long libellé restant est « ⏸ pause » (7) —
            # « effacée » (10) est remplacé par l'icône 🗑 (voir plus bas).
            table.add_column(
                "État", key="state", width=COL_DEFAULT_WIDTHS["state"]
            )
            # « Odoo » : l'UI web répond-elle sur :8069 ? (🟢 up / — down)
            table.add_column(
                "Odoo", key="odoo", width=COL_DEFAULT_WIDTHS["odoo"]
            )
            table.add_column(
                "Durée", key="elapsed", width=COL_DEFAULT_WIDTHS["elapsed"]
            )
            # Statistiques de la VM. « Écrit/s » est une MOYENNE sur dix
            # secondes : le disque d'une installation travaille par rafales,
            # et l'instantané n'y montrait que des 0 et des pics.
            table.add_column(
                "Écrit/s", key="wr", width=COL_DEFAULT_WIDTHS["wr"]
            )
            table.add_column("RAM", key="ram", width=COL_DEFAULT_WIDTHS["ram"])
            table.add_column(
                "Disque", key="disk", width=COL_DEFAULT_WIDTHS["disk"]
            )
            for i, vm in enumerate(vms, 1):
                table.add_row(
                    str(i),
                    vm["name"],
                    vm.get("arch") or "?",
                    "",
                    # « rien encore », comme ses voisines : « ⏳ » affirmerait
                    # qu'on attend quelque chose, alors qu'on ne sait rien du
                    # tout — le journal n'a pas encore parlé. Le sablier
                    # apparaît dès que l'attente est constatée.
                    "-",
                    "—",
                    "--:--",
                    "-",
                    "-",
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
            # Section statistiques de la VM SÉLECTIONNÉE : les mêmes chiffres
            # que ses colonnes, mais détaillés (pourcentages, cumul écrit).
            # Une ligne par VM du parc aurait chassé le pied de page dès cinq
            # machines ; la sélection suit déjà le journal et la barre SSH.
            yield Static("", id="vmstats")
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
            self._refresh_vmstats()
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

        def _refresh_vmstats(self):
            """Ligne de statistiques de la VM sélectionnée."""
            name = self._selected
            if not name:
                return
            try:
                bar = self.query_one("#vmstats", Static)
            except Exception:
                return
            bar.update(
                vm_stats_line(
                    name,
                    self._vmstats.get(name),
                    self._wrate.rate(name),
                    time.time(),
                    self._wrate.total(name),
                )
            )

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
                # La RAM va entre le CPU et le disque : c'est la ressource dont
                # l'épuisement ne se voit nulle part ailleurs. Une compilation
                # mobile a été tuée par le noyau sur une VM de 12 Go sans swap,
                # et ce suivi n'en montrait rien.
                mem = _mem_tele(*_host_mem())
                return (
                    f"  ⚙ CPU {min(999, int(load1 / ncpu * 100))}% "
                    f"({t('load')} {load1:.1f}/{ncpu})   "
                    + (f"{mem}   " if mem else "")
                    + f"💽 {self._disk_dir}: {_fmt_size(du.used)}/"
                    f"{_fmt_size(du.total)} ({used_pct}%) · "
                    f"{t('free space')} {_fmt_size(du.free)}"
                )
            except Exception:
                return ""

        def _collect_table(self):
            """(THREAD) statut + taille disque de chaque VM + télémétrie. AUCUNE
            mise à jour d'UI ici : uniquement des I/O bloquantes déportées."""
            disks, status, errors, odoo = {}, {}, {}, {}
            # UN appel virsh pour tout le parc, dans ce thread : le débit se
            # calcule sur les relevés successifs, donc il faut échantillonner
            # à chaque tour (2 s) et non au rythme lent des états.
            stats = parse_domstats(read_domstats())
            drop_local_twins(stats, vms)
            # Les VM d'un hôte Proxmox distant : virsh ne les voit pas, leurs
            # colonnes restaient vides. Même forme de relevé, donc la suite ne
            # change pas d'un iota.
            stats.update(read_pvestats(vms))
            now_s = maintenant = time.time()
            for name, rec in stats.items():
                self._wrate.add(name, rec["wr_bytes"], now_s)
            self._vmstats = stats
            wr, ram = {}, {}
            for vm in vms:
                name = vm["name"]
                rec = stats.get(name)
                wr[name] = fmt_rate(self._wrate.rate(name))
                ram[name] = ram_pair(rec, now_s)
                if rec and rec.get("disk_total"):
                    disks[name] = fmt_pair(rec["disk_used"], rec["disk_total"])
                else:
                    # Domaine pas encore défini (conversion de l'image, tout
                    # début de l'installation) : le qcow2 existe déjà, et
                    # st_blocks dit ce qu'il occupe. Sans total à annoncer.
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
                # Odoo up ? La réponse est RENDUE À CHAQUE TOUR pour les
                # VM sondées, pas accumulée : la colonne doit pouvoir
                # redescendre à « — ».
                if self._domstate.get(name) != "gone":
                    etat, sonde = odoo_reading(
                        vm,
                        (self._vmstats or {}).get(name) or {},
                        name in self._odoo_up,
                        self._odoo_revu.get(name, 0.0),
                        maintenant,
                        _port_open,
                    )
                    if sonde:
                        self._odoo_revu[name] = maintenant
                    if etat is not None:
                        odoo[name] = etat
            return disks, status, self._collect_tele(), errors, odoo, wr, ram

        async def _tick_table(self):
            # I/O (lectures de logs, stat disque, /proc) DÉPORTÉES en thread ->
            # la boucle d'événements Textual reste fluide même sous forte
            # charge ou disque lent. Les mises à jour d'UI restent sur la boucle.
            try:
                (
                    disks,
                    status,
                    tele,
                    errors,
                    odoo,
                    wr,
                    ram,
                ) = await asyncio.to_thread(self._collect_table)
            except Exception:
                return
            self._errcount.update(errors)
            # Remplacement et non union : une VM sondée qui ne répond
            # plus doit repasser à « — ». Les VM absentes du relevé (hôte
            # muet, VM effacée) gardent leur dernier état connu.
            for nom_vm, vivant in odoo.items():
                if vivant:
                    self._odoo_up.add(nom_vm)
                else:
                    self._odoo_up.discard(nom_vm)
            try:
                table = self.query_one("#vms", DataTable)
                now = time.time()
                remaining = []
                for vm in vms:
                    name = vm["name"]
                    self._set_cell(table, name, "disk", disks.get(name, "-"))
                    self._set_cell(table, name, "wr", wr.get(name, "-"))
                    self._set_cell(table, name, "ram", ram.get(name, "-"))
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
                        # Même bornage que les autres états terminaux : une
                        # VM effacée ne « tourne » plus depuis la dernière
                        # ligne de son log.
                        self._final[name] = (
                            "deleted",
                            None,
                            max(0.0, finished_at(vm["log"], now) - started),
                        )
                        # Icône seule (VM effacée) : évite « ❌ effacée » (10
                        # cellules) qui forçait une colonne État large.
                        self._set_cell(table, name, "state", "🗑")
                        continue
                    st = status.get(name)
                    if st is None:
                        continue
                    state, code = st
                    if state in ("done", "failed"):
                        # Bornée à la dernière écriture du log, pas à l'instant
                        # présent : le suivi peut être rouvert bien plus tard.
                        elapsed = max(
                            0.0, finished_at(vm["log"], now) - started
                        )
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
                        self._set_cell(
                            table,
                            name,
                            "state",
                            state_mark(ICON[state], log_idle(vm["log"])),
                        )
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
                    f"{self._fmt(self._total_elapsed(now, started))}"
                    f"{eta}{maxd}"
                )
                if tele:
                    self.query_one("#telemetry", Static).update(tele)
                self._update_stats()
                # Les chiffres de la VM sélectionnée viennent d'être relevés :
                # sa section les redit ici, détaillés.
                self._refresh_vmstats()
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
            # Une VM posée sur un hôte Proxmox est ABSENTE de « virsh list » :
            # elle passait donc pour EFFACÉE, ce qui éteignait du même coup
            # ses colonnes vivantes. Son état vient de l'hôte.
            distants, hote_ok = await asyncio.to_thread(
                read_pvestats_detail, vms
            )
            for vm in vms:
                nom = vm["name"]
                if vm.get("pve"):
                    if not hote_ok:
                        # L'hôte n'a pas répondu : on ne sait RIEN. Conclure
                        # « effacée » ici gelait la ligne sur 🗑 dès le premier
                        # tour, pour toujours — vécu sur une VM Arch à peine
                        # déployée. Et on OUBLIE les absences déjà comptées :
                        # elles ne prouvent une disparition que si elles se
                        # SUIVENT, l'hôte répondant à chaque fois.
                        self._pve_absences[nom] = 0
                        continue
                    releve = distants.get(nom)
                    if releve:
                        self._pve_absences[nom] = 0
                        # PRÉSENTE dans le relevé : elle existe, quel que soit
                        # le mot employé. Proxmox en a d'autres que les trois
                        # attendus — « prelaunch », « suspended »,
                        # « internal-error », « hibernated » — et les traduire
                        # en « gone » mettait à la poubelle une VM bien vivante.
                        self._domstate[nom] = PVE_ETATS.get(
                            releve.get("state"), "running"
                        )
                        continue
                    # L'hôte a répondu SANS elle : peut-être en cours de
                    # création, peut-être vraiment partie. On compte.
                    self._pve_absences[nom] = (
                        self._pve_absences.get(nom, 0) + 1
                    )
                    if self._pve_absences[nom] >= PVE_ABSENCES_AVANT_EFFACEE:
                        self._domstate[nom] = "gone"
                    continue
                if not states:
                    # « virsh list » n'a rien rendu : soit l'hôte n'a plus une
                    # seule VM, soit l'appel a échoué (libvirtd qui redémarre,
                    # sudo qui expire). On ne peut pas trancher, et conclure
                    # « effacées » mettait TOUT le parc local à la poubelle,
                    # définitivement. Même règle que pour l'hôte distant : on
                    # compte avant de conclure.
                    self._pve_absences[nom] = (
                        self._pve_absences.get(nom, 0) + 1
                    )
                    if self._pve_absences[nom] >= PVE_ABSENCES_AVANT_EFFACEE:
                        self._domstate[nom] = "gone"
                    continue
                self._pve_absences[nom] = 0
                self._domstate[nom] = states.get(nom, "gone")
            # Réarmer la période du ballon sur les VM qui tournent : sans elle
            # la RAM affichée serait celle du dernier rapport du pilote, et une
            # installation redémarre la VM — ce qui remet la période à zéro.
            # Les VM distantes en sont exclues : « virsh dommemstat » ne les
            # atteint pas, et l'hôte donne déjà leur mémoire.
            vivantes = [
                vm["name"]
                for vm in vms
                if not vm.get("pve") and states.get(vm["name"]) == "running"
            ]
            if vivantes:
                await asyncio.to_thread(arm_balloon, vivantes)

            # L'adresse est relue au même rythme. Le processus détaché suivait
            # déjà la VM quand son bail changeait, mais les VUES gardaient celle
            # du lancement : la barre proposait « ssh erplibre@…222 » alors que
            # l'installation parlait à …223, et la touche « s » y menait aussi.
            # Rafraîchir ici plutôt que dans un tick à part évite un second
            # appel virsh par VM — celui-ci est déjà le relevé lent.
            changed = False
            for vm in vms:
                if self._domstate.get(vm["name"]) == "gone" or vm.get("pve"):
                    # Une VM distante n'a pas de bail chez nous : son adresse
                    # est celle que cloud-init a posée, et virsh ne la voit
                    # pas. La chercher rendrait « gone » à chaque tour.
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
            self._refresh_vmstats()
            self._load_selected_log(reset=True)

        def action_follow(self) -> None:
            self._follow = not self._follow

        def action_ssh(self) -> None:
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            cmd = vm_ssh_prefix(vm)
            with self.suspend():
                print(f"\n→ {cmd}\n")
                os.system(f"{cmd} || true")

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
            info = vm.get("pve")
            if info:
                # VM d'un hôte Proxmox : sa console est « qm terminal », sur
                # l'hôte. « virsh console <nom> » ouvrait celle du domaine
                # LOCAL homonyme — la mauvaise machine, sans le dire.
                cmd = pve_host_cmd(
                    info, f"qm terminal {int(info.get('vmid') or 0)}", tty=True
                )
                titre = (
                    f"qm terminal {info.get('vmid')} @ {info.get('target')}"
                )
                sortie = "Ctrl+O"
            else:
                cmd = f"{sudo_prefix()}virsh console {shlex.quote(vm['name'])}"
                titre = f"virsh console {vm['name']}"
                sortie = "Ctrl+]"
            with self.suspend():
                # La console n'affiche que ce qui arrive APRÈS l'attachement :
                # sur une VM déjà démarrée l'écran reste noir tant qu'on n'a
                # rien envoyé. On le dit, plutôt que de laisser croire à un gel.
                print(f"\n→ {titre}")
                print(
                    "   Écran vide ? Appuyez sur Entrée : la console ne montre"
                    " que la sortie qui suit l'attachement."
                )
                print(f"   {sortie} puis Entrée pour revenir au suivi.\n")
                os.system(f"{cmd} || true")

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
            port = 18069
            argv_tunnel = web_tunnel_argv(vm.get("pve"), port)
            url = (
                f"http://127.0.0.1:{port}"
                if argv_tunnel
                else f"http://{vm['ip']}:8069"
            )
            with self.suspend():
                proc = None
                if argv_tunnel:
                    print("→ " + " ".join(shlex.quote(a) for a in argv_tunnel))
                    try:
                        proc = subprocess.Popen(argv_tunnel)
                        time.sleep(2)
                    except (OSError, subprocess.SubprocessError) as exc:
                        print(f"   ⚠ {exc}")
                print(f"→ {browser} {url}")
                rc = os.system(f"{browser} {shlex.quote(url)}")
                if proc:
                    proc.terminate()
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
            summary = scan_log_summary(vm["log"])
            self.push_screen(
                ErrorLinesScreen(vm["name"], errs, warns, summary)
            )

        def on_click(self, event) -> None:
            # Clic sur le sommaire de stats -> déplie / replie le détail.
            w = getattr(event, "widget", None)
            if w is not None and getattr(w, "id", None) == "stats":
                self._stats_open = not self._stats_open
                self.query_one("#statsdetail").display = self._stats_open
                self._update_stats()

        # -- pause / reprise de tout le parc -------------------------------- #
        @staticmethod
        def _virsh_bulk(action, cibles):
            """Suspend/reprend chaque VM, chacune par SON hyperviseur.

            `cibles` : [(nom, info_pve|None)]. Une VM distante se suspend par
            son VMID sur son hôte — « virsh suspend <nom> » aurait mis en
            pause le domaine LOCAL homonyme."""
            for nom, info in cibles:
                try:
                    if info:
                        vmid = int(info.get("vmid") or 0)
                        subprocess.run(
                            pve_host_cmd(info, f"qm {action} {vmid}"),
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                    else:
                        subprocess.run(
                            ["sudo", "virsh", action, nom],
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                except (OSError, subprocess.SubprocessError):
                    pass

        # -- largeur des colonnes ---------------------------------------- #
        COL_STEP = 2
        COL_MIN = 3
        COL_MAX = 60

        def _cursor_column(self):
            """Colonne VISEE par le redimensionnement.

            Surtout pas « table.cursor_column » : le curseur est en mode
            LIGNE, sa colonne reste donc a 0 quoi qu'on fasse. Chaque « + » ou
            « - » tombait sur « # », large de 3 et deja a sa butee — d'ou un
            avertissement en boucle et aucune colonne atteignable.

            La cible se deplace avec « < » et « > », et part sur le nom de VM,
            la seule qu'on ait vraiment besoin d'elargir."""
            table = self.query_one("#vms", DataTable)
            keys = list(table.columns)
            if not keys:
                return None, None
            index = max(0, min(self._col_target, len(keys) - 1))
            return table, keys[index]

        def _apply_column_widths(self, table) -> None:
            """Fait PRENDRE les largeurs à l'écran.

            « refresh(layout=True) » ne suffit pas, et c'est le piège :
            mesuré sur Textual 8.2.8, la largeur de la colonne passe bien de
            22 à 34, mais la taille virtuelle du tableau reste à 81 — donc
            rien ne bouge. « clear_cached_dimensions » et « refresh_column »
            n'y changent rien non plus ; seul le recalcul des dimensions la
            porte à 93.

            C'est une API privée, d'où le repli : une version future de
            Textual dégradera l'ajustement au lieu de casser le suivi."""
            try:
                table._update_dimensions(list(table.rows))
            except Exception:
                table.refresh(layout=True)

        def _resize_column(self, delta) -> None:
            table, key = self._cursor_column()
            if key is None:
                return
            col = table.columns[key]
            width = max(
                self.COL_MIN, min(self.COL_MAX, (col.width or 0) + delta)
            )
            if width == col.width:
                # Butée atteinte : le SEUL cas où il faut le dire, puisque
                # rien ne bougera à l'écran pour l'expliquer.
                self.notify(
                    f"{col.label} : {width} (butee {self.COL_MIN}-{self.COL_MAX})",
                    severity="warning",
                )
                return
            col.width = width
            # auto_width écraserait la largeur au prochain rendu : on la coupe,
            # sinon le réglage ne survit pas à la première mise à jour.
            col.auto_width = False
            # Pas de notification quand ça marche : le changement se VOIT, et
            # une bulle par frappe rendait l'ajustement pénible.
            self._apply_column_widths(table)

        def _move_col_target(self, delta) -> None:
            """Deplace la cible, en boucle sur les colonnes."""
            table = self.query_one("#vms", DataTable)
            keys = list(table.columns)
            if not keys:
                return
            self._col_target = (self._col_target + delta) % len(keys)
            self.notify(
                f"Colonne visee : {table.columns[keys[self._col_target]].label}"
            )

        def action_col_prev(self) -> None:
            self._move_col_target(-1)

        def action_col_next(self) -> None:
            self._move_col_target(1)

        def action_col_grow(self) -> None:
            self._resize_column(self.COL_STEP)

        def action_col_shrink(self) -> None:
            self._resize_column(-self.COL_STEP)

        def action_col_reset(self) -> None:
            """Rend aux colonnes les largeurs déclarées à la construction."""
            table = self.query_one("#vms", DataTable)
            for key, width in COL_DEFAULT_WIDTHS.items():
                if key in table.columns:
                    table.columns[key].width = width
                    table.columns[key].auto_width = False
            self._apply_column_widths(table)

        def _total_elapsed(self, now, started):
            """Durée globale. Elle se FIGE quand plus rien ne tourne : sinon
            le total continuait de courir sur un parc entièrement terminé,
            et repartait de plus belle à chaque réouverture."""
            if len(self._final) < len(vms) or not self._final:
                return now - started
            return max(e for _s, _c, e in self._final.values())

        def action_vm_actions(self) -> None:
            """Ouvre les actions de la VM sélectionnée."""
            vm = self._vm_by_name(self._selected)
            if not vm:
                return

            def chosen(result):
                if not result:
                    return
                kind, parts = result
                if kind == "update":
                    self._run_update(vm, parts)
                elif kind == "restart":
                    self._run_in_vm(
                        vm, restart_odoo_cmd(), "Redemarrage d'Odoo"
                    )
                elif kind == "delete":
                    self._ask_delete(vm)

            self.push_screen(VmActionsScreen(vm), chosen)

        def _run_in_vm(self, vm, cmd, title) -> None:
            """Exécute une commande DANS la VM, terminal rendu.

            « suspend() » comme pour SSH et la console : sudo peut demander son
            mot de passe et la sortie est longue ; la garder derrière Textual
            la rendrait illisible. La pause finale évite que l'écran reparte
            avant qu'on ait lu le résultat."""
            if not vm.get("ip"):
                self.notify("Pas d'IP pour cette VM.", severity="error")
                return
            with self.suspend():
                print(f"\n=== {title} — {vm['name']} ===")
                os.system(
                    f"{vm_ssh_prefix(vm)} " f"{shlex.quote(cmd)} || true"
                )
                input("\nEntrée pour revenir au suivi… ")

        def _run_update(self, vm, parts) -> None:
            cmd = update_remote_cmd(parts)
            if not cmd:
                self.notify("Rien de coché.", severity="warning")
                return
            self._run_in_vm(vm, cmd, "Mise a jour")

        def _ask_delete(self, vm) -> None:
            """Suppression : jamais sans une seconde main."""

            def confirmed(yes):
                if not yes:
                    return
                info = vm.get("pve")
                # Le garde d'identité voyage avec la VM : c'est ce qui
                # rend une suppression sûre depuis un suivi ROUVERT, dont le
                # manifeste peut avoir des semaines.
                cmd = (
                    delete_vm_cmd_pve(info, name=vm["name"])
                    if info
                    else delete_vm_cmd(vm["name"], True, vm.get("uuid") or "")
                )
                with self.suspend():
                    print(f"\n=== Suppression — {vm['name']} ===")
                    print(f"→ {cmd}\n")
                    os.system(cmd + " || true")
                    input("\nEntrée pour revenir au suivi… ")

            self.push_screen(
                ConfirmScreen(
                    f"Supprimer {vm['name']} ?",
                    delete_lines(vm),
                    "Supprimer définitivement",
                ),
                confirmed,
            )

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
                (vm["name"], vm.get("pve"))
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
