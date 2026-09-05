#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Parler à une appliance par ssh : monter la commande, la jouer, la lire.

Ces cinq fonctions ne savent rien du produit qui tourne en face — elles
savent composer une ligne ssh depuis une fiche d'hôte, élever une SUITE de
commandes, jouer sans jamais lever, et nettoyer ce que ssh ajoute de
lui-même. Elles vivaient dans le module d'une appliance parce que c'est là
qu'on en a eu besoin d'abord ; une seconde en aurait fait une copie.

Une FICHE D'HÔTE est un dictionnaire : « target » suffit quand l'alias vient
de ~/.ssh/config, qui porte déjà l'utilisateur, le port et le rebond ; les
clés « jump », « port » et « sudo » les imposent au besoin.
"""

from __future__ import annotations

import re
import shlex
import subprocess


def ssh_argv(host: dict, remote: str, tty: bool = False) -> list:
    """Commande ssh complète pour exécuter `remote` sur l'hôte distant.

    `host` : {"target": "root@203.0.113.5", "jump": "rebond", "port": "22"} —
    « target » suffit quand l'alias vient de ~/.ssh/config, qui porte déjà
    l'utilisateur, le port et le ProxyJump.
    """
    argv = ["ssh"]
    if not tty:
        argv += ["-o", "BatchMode=yes"]
    argv += ["-o", "ConnectTimeout=10"]
    if host.get("port"):
        argv += ["-p", str(host["port"])]
    if host.get("jump"):
        argv += ["-J", host["jump"]]
    if tty:
        argv.append("-t")
    argv += [host["target"], remote]
    return argv


def wrap_privilege(remote: str, prefix: str) -> str:
    """Enveloppe la commande pour qu'elle tourne en root, si nécessaire.

    « sudo sh -c '<tout>' » et non « sudo <tout> » : une commande d'appliance
    est souvent une SUITE (« mkdir && if … fi », une boucle for, une
    redirection).
    Préfixer par sudo n'élèverait que le premier mot, et la redirection
    resterait celle du shell non privilégié — donc « permission denied » sur
    /root ou /boot/efi.
    """
    if not prefix:
        return remote
    return "sudo sh -c " + shlex.quote(remote)


# Ce que ssh écrit de lui-même, et qui n'est pas la réponse de l'hôte. Retiré
# à la SOURCE : un avertissement laissé dans la sortie se fait analyser comme
# une donnée de l'hôte, et la parenthèse du type de clé, reprise dans une
# commande enrobée de « sudo sh -c », y ouvre une erreur de syntaxe du shell.
# Filtrer chez chaque lecteur laisse le suivant retomber dans le piège.
_BRUIT_SSH = (
    "Warning: Permanently added",
    "Pseudo-terminal will not be allocated",
    "Connection to ",
    "Shared connection to ",
    "Killed by signal",
    "mesg: ttyname failed",
    "stdin: is not a tty",
)


def strip_ssh_noise(text: str) -> str:
    """La sortie de l'hôte, débarrassée de ce que ssh y a ajouté.

    Ce sont des lignes de ssh lui-même (clé d'hôte enregistrée, pseudo-terminal
    refusé, connexion fermée) : elles n'apprennent rien sur la commande et
    n'ont donc rien à faire dans ce qu'on analyse ou affiche.
    """
    gardees = [
        ligne
        for ligne in (text or "").splitlines()
        if not ligne.strip().startswith(_BRUIT_SSH)
    ]
    return "\n".join(gardees) + ("\n" if gardees else "")


# Ce que ssh dit quand il ne CONNAÎT pas encore la clé d'une machine, ou
# qu'elle a changé. Trois formulations selon la version et le type de clé ;
# les chercher toutes évite de conclure « injoignable » sur une machine qui
# répond très bien et n'attend qu'un accord.
_CLE_INCONNUE = (
    "host key verification failed",
    "authenticity of host",
    "no ed25519 host key is known",
)


def hostkey_missing(text: str) -> bool:
    """La sortie de ssh dénonce-t-elle une clé d'hôte inconnue ou changée ?"""
    bas = (text or "").lower()
    return any(motif in bas for motif in _CLE_INCONNUE)


# Les lignes d'AVANCEMENT : « transferred 1.2 GiB of 3.0 GiB (40%) » répété
# cent fois par une copie de disque, les points d'un téléchargement. Elles ne
# disent qu'une chose, et la dernière la dit aussi bien.
_RE_PROGRES = re.compile(
    r"^\s*(transferred\s+[\d.]+|\d+K\s+\.|.*\.{10}.*\d+%)"
)


def collapse_progress(text: str) -> str:
    """Ne garde que la DERNIÈRE ligne de chaque salve d'avancement.

    Une salve d'avancement noie l'erreur utile dans un journal qu'on relit :
    cent lignes « transferred … » pour une ligne qui explique la panne. Un
    avancement compte pendant qu'il défile, pas dans un fichier qu'on relit.
    """
    sortie, salve = [], 0
    for ligne in (text or "").splitlines():
        if _RE_PROGRES.match(ligne):
            salve += 1
            continue
        if salve:
            sortie.append(f"   … {salve} lignes d'avancement …")
            salve = 0
        sortie.append(ligne)
    if salve:
        sortie.append(f"   … {salve} lignes d'avancement …")
    return "\n".join(sortie)


def run(host: dict, remote: str, timeout: int = 120) -> tuple:
    """(code, sortie) de `remote` exécuté sur l'hôte. Ne lève jamais.

    `host["sudo"]` non vide -> la commande passe par sudo. L'administration
    d'une appliance exige les privilèges, et le compte qu'un accès de parc
    offre ne les a pas.
    """
    remote = wrap_privilege(remote, host.get("sudo") or "")
    try:
        res = subprocess.run(
            ssh_argv(host, remote),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 255, "timeout"
    except (OSError, subprocess.SubprocessError) as exc:
        return 255, str(exc)
    return res.returncode, strip_ssh_noise(
        (res.stdout or "") + (res.stderr or "")
    )
