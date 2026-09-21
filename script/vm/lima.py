#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La configuration d'une instance Lima, et ce qu'elle ne sait pas tenir.

CE MODULE NE COMPOSE ET N'ANALYSE QUE DU TEXTE. Ce que l'outil en fait ne s'y
lit pas : une description d'instance peut se relire parfaitement en YAML et
être refusée au démarrage, le champ « arch » ayant son propre vocabulaire.
C'est `long_test/lima_confront.py` qui mesure cela sur une machine, et c'est
lui qui a levé la mention « non éprouvé » du backend.

Le rendu est écrit LIGNE À LIGNE plutôt que sérialisé : la configuration
d'une instance se relit à la main, et un commentaire qui explique un réglage
vaut mieux qu'un champ nu. Une épreuve la relit avec un analyseur YAML, ce
qui rattrape ce que l'écriture manuelle risque de casser.

DEUX RÉGLAGES N'EXISTENT QUE SUR macOS, et les poser ailleurs fait échouer
le démarrage : « vmType: vz » demande Virtualization.framework, et le bloc
« networks » demande socket_vmnet. Ailleurs, l'instance se contente du réseau
en mode utilisateur — ce qui suffit à sortir, et ne suffit pas à être jointe.
"""

from __future__ import annotations

import json
from typing import NamedTuple

# Le montage de l'hôte est VIDE, et c'est un choix. Lima monte par défaut le
# répertoire personnel dans l'invité : une VM censée être confinée y lirait
# alors tout ce que l'utilisateur possède, sans qu'une seule règle réseau
# soit en cause. Une VM ERPLibre n'en a pas besoin — elle reçoit son code par
# le canal d'exec.
MOUNTS_VIDES = "mounts: []"

# Ce que « vmType » vaut là où il existe. Ailleurs, on ne l'écrit pas du
# tout : Lima choisit alors son moteur, et un « vz » posé sur un système qui
# n'a pas Virtualization.framework fait échouer le démarrage.
VM_TYPE_MACOS = "vz"

# Le bloc qui donne une adresse joignable depuis l'hôte. UNE constante,
# parce que `render_config` l'écrit et `config_limits` le relit : deux
# littéraux voisins cesseraient de correspondre au premier ajustement, et
# l'écran annoncerait « joignable » sur une instance qui ne l'est pas.
NETWORK_SHARED = "  - lima: shared"

# Le champ « arch » d'une description d'instance a son PROPRE vocabulaire,
# et ce n'est ni celui du dépôt ni celui des images. L'outil refuse le
# démarrage sur un jeton hors liste, en nommant la liste :
#
#     field `arch` must be one of [x86_64 aarch64 armv7l ppc64le riscv64
#     s390x]
#
# Une image Ubuntu, elle, s'appelle « amd64 ». Les deux mots désignent la
# même machine et voyagent dans le même appel : traduire ICI est ce qui
# évite qu'un appelant choisisse au hasard lequel des deux poser.
#
# Un jeton inconnu passe TEL QUEL : l'outil le refuse alors en nommant sa
# liste, ce qu'une correspondance devinée ici ne ferait pas.
ARCH_CONFIG = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}


def config_arch(jeton: str) -> str:
    """Le jeton d'architecture tel qu'une description d'instance l'écrit."""
    return ARCH_CONFIG.get((jeton or "").strip().lower(), jeton)


def render_config(
    image: str,
    arch: str = "",
    cpus: int = 2,
    memory: str = "4GiB",
    disk: str = "30GiB",
    macos: bool = False,
    reachable: bool = False,
    load_host_keys: bool = False,
    provision_script: str = "",
) -> str:
    """Le YAML d'une instance, prêt à écrire. Fonction PURE.

    `reachable` demande une adresse joignable depuis l'hôte. Elle passe par
    socket_vmnet, qui n'existe que sur macOS : demandée ailleurs, elle est
    ignorée plutôt que d'écrire un bloc qui ferait échouer le démarrage.

    `load_host_keys` à FAUX par défaut : Lima injecte sinon les clés
    publiques du répertoire personnel dans l'invité. Le canal d'exec n'en a
    pas besoin — il passe par la clé que Lima génère — et une VM confinée n'a
    pas à connaître les identités de son hôte.

    `provision_script` pose un verrou DANS L'INVITÉ. La description
    d'instance ne sait pas borner des destinations — c'est ce que
    `unenforceable` nomme — et sa docstring donne la sortie : « poser le
    verrou ailleurs, dans l'invité ». Le provisionnement est cet ailleurs.

    Le script arrive COMPOSÉ. Ce paquet ne connaît pas les postures — une
    épreuve tient qu'il ne dépend de rien du dépôt — et c'est l'appelant
    qui rapproche les deux. Vide, aucun bloc n'est écrit : un bloc sans
    script se lirait comme un provisionnement qui a tourné.
    """
    lignes = [
        "# Généré par ERPLibre. Les commentaires expliquent les réglages qui",
        "# ne se devinent pas ; le reste est la taille demandée.",
    ]
    if macos:
        lignes += [
            "# Virtualization.framework : n'existe que sur macOS 13+, et y",
            "# vaut nettement mieux que l'émulation.",
            f"vmType: {VM_TYPE_MACOS}",
        ]
    jeton = config_arch(arch)
    if arch:
        lignes.append(f"arch: {jeton}")
    lignes += [
        "images:",
        f'  - location: "{image}"',
    ]
    if arch:
        lignes.append(f"    arch: {jeton}")
    lignes += [
        f"cpus: {int(cpus)}",
        f'memory: "{memory}"',
        f'disk: "{disk}"',
        "# Rien de l'hôte n'est monté : une VM confinée n'a pas à lire le",
        "# répertoire personnel de qui la lance.",
        MOUNTS_VIDES,
        "ssh:",
        f"  loadDotSSHPubKeys: {str(bool(load_host_keys)).lower()}",
    ]
    if reachable and macos:
        lignes += [
            "# Adresse joignable depuis l'hôte. Passe par socket_vmnet, qui",
            "# demande une installation privilégiée à part.",
            "networks:",
            NETWORK_SHARED,
        ]
    lignes += _lignes_provisionnement(provision_script)
    return "\n".join(lignes) + "\n"


def _lignes_provisionnement(script: str) -> list:
    """Le bloc YAML qui porte un script de provisionnement système.

    Le document est écrit en bloc littéral : un script porte des accolades,
    des guillemets et des sauts de ligne qu'une chaîne simple ferait
    échapper.
    """
    if not (script or "").strip():
        return []
    lignes = [
        "# Le verrou se pose DANS l'invité : la description d'instance ne",
        "# sait pas borner des destinations, et Lima ne le fera pas pour",
        "# nous. « mode: system » parce que nft et systemctl demandent root.",
        "provision:",
        "  - mode: system",
        "    script: |",
    ]
    # LIGNE À LIGNE, et une ligne vide reste VIDE : dans un bloc littéral,
    # seule la première ligne d'une chaîne multiligne reçoit l'indentation,
    # et les suivantes retombent en colonne zéro — ce qui ferme le bloc.
    lignes += [
        f"      {ligne}" if ligne else ""
        for ligne in script.rstrip("\n").splitlines()
    ]
    return lignes


def config_limits(rendered: str) -> tuple:
    """Ce que la configuration RENDUE n'offre pas, lu dans son texte.

    TROIS QUESTIONS VOISINES, et un écran a besoin de celle-ci.
    `unenforceable` répond « que promet cette POSTURE que la configuration
    ne tient pas ». `host_limits` répond « que cet HÔTE ne peut pas offrir
    du tout ». Celle-ci répond « que CETTE configuration n'offre pas », et
    c'est la seule que le lecteur d'un écran de création veut savoir : sur
    macOS, l'adresse joignable est POSSIBLE, et pourtant elle n'est pas là
    si personne ne l'a demandée.

    Lue dans le TEXTE et non déduite des arguments : c'est la seule forme
    qui ne peut pas mentir. Un jour où le rendu cesserait d'écrire le bloc —
    parce que la demande a été ignorée sur cet hôte — une déduction faite
    sur les arguments dirait encore « joignable ».
    """
    return () if NETWORK_SHARED in (rendered or "") else ("reachable-address",)


def host_limits(macos: bool = False) -> tuple:
    """Ce qu'une instance ne sait pas offrir SUR CET HÔTE, posture ou non.

    QUESTION DISTINCTE de `unenforceable`, qui répond « que promet cette
    POSTURE que la configuration ne tient pas ». Ici il n'y a pas de
    posture : c'est l'hôte qui borne, et le dire ne demande pas d'avoir
    choisi un profil. Un écran qui montre une configuration avant de la
    jouer a besoin de celle-ci, pas de l'autre.

    Sans socket_vmnet — qui n'existe que sur macOS — l'invité SORT mais ne
    se laisse pas joindre. C'est la seule limite que l'hôte impose à lui
    seul, et `unenforceable` la reprend d'ici plutôt que d'en garder une
    copie.
    """
    return () if macos else ("reachable-address",)


def unenforceable(posture, macos: bool = False) -> tuple:
    """Ce que la configuration d'instance ne sait PAS tenir de cette posture.

    Une configuration muette sur ce qu'elle n'applique pas est ce qui fait
    croire à un confinement qui n'existe pas. Elle rend ici la LISTE de ce
    qui manque, en jetons non traduits, et l'appelant décide : renoncer, ou
    poser le verrou ailleurs — dans l'invité, où il attrape ce que la
    configuration ne peut pas.

    Rend un tuple VIDE quand tout est tenable. Une posture absente ne promet
    rien, donc rien ne manque.
    """
    if posture is None:
        return ()
    manques = []
    # Le réseau en mode utilisateur donne TOUJOURS la sortie, et aucun
    # réglage d'instance ne la retire. Annoncer « rien ne sort » sur cette
    # base serait faux.
    if posture.egress == "none":
        manques.append("egress-none")
    # Une liste blanche se pose dans l'invité, pas dans la description de
    # l'instance.
    if posture.destinations_bounded:
        manques.append("destinations-bounded")
    # Ce que l'hôte borne à lui seul, lu d'un seul endroit.
    manques.extend(host_limits(macos))
    return tuple(manques)


# Le binaire de l'outil. Nommé une fois : un jour où il s'appellerait
# autrement, ou vivrait ailleurs, il n'y a qu'ici à toucher.
LIMACTL = "limactl"

# CE QUI REND UN DÉMARRAGE JOUABLE DEPUIS UN MENU. Sans « --tty=false »,
# l'outil ouvre une conversation — un éditeur sur la configuration, une
# question à confirmer. Un menu qui la reçoit se figeait sur une invite que
# personne ne voit, et il ne reste que Ctrl-C.
SANS_INVITE = "--tty=false"

# « -f » sur l'arrêt et sur la suppression : les deux posent sinon leur
# propre question. L'écran a déjà demandé, et le redemander là où la sortie
# n'est plus lue revient à ne rien demander.
SANS_QUESTION = "-f"

# Les actions du cycle de vie, vocabulaire clos. Ce ne sont PAS
# « suspend »/« resume » : `verbs.power_command` les refuse pour ce backend
# exprès, parce qu'un arrêt n'est pas une pause — confondre les deux perd
# l'état d'une VM qu'on croyait seulement mettre de côté.
LIFECYCLE = ("start", "stop", "delete")


def list_argv() -> list:
    """L'inventaire, en JSON. Rend un ARGV, donc aucun shell n'intervient.

    « --json » et non la sortie tabulée : cette dernière change de colonnes
    selon la version, et l'analyser reviendrait à parier sur une mise en
    page. `parse_instances` lit ce que cet appel rend.
    """
    return [LIMACTL, "list", "--json"]


def start_argv(name: str, config: str = "") -> list:
    """Démarre l'instance, en la créant depuis `config` s'il est donné.

    Le chemin de configuration vient EN DERNIER, comme un argument
    positionnel, parce que c'est ainsi que l'outil le prend. Sans lui,
    l'appel démarre une instance déjà décrite.
    """
    argv = [LIMACTL, "start", "--name", str(name), SANS_INVITE]
    if config:
        argv.append(str(config))
    return argv


def stop_argv(name: str) -> list:
    """Arrête l'instance. Ce n'est pas une pause : l'état vif est perdu."""
    return [LIMACTL, "stop", SANS_QUESTION, str(name)]


def delete_argv(name: str) -> list:
    """Détruit l'instance et son disque. Sans retour.

    L'écran qui appelle DOIT avoir fait retaper le nom : « -f » retire la
    dernière question, et un nom mal tapé détruit alors sans un mot.
    """
    return [LIMACTL, "delete", SANS_QUESTION, str(name)]


def shell_argv(name: str, remote: str = "") -> list:
    """Ouvre un shell dans l'instance, ou y joue une suite de commandes.

    « bash -c » est indispensable pour une SUITE : l'outil exécute des
    arguments, si bien que « a && b » lui arriverait comme une liste de mots.
    Sans `remote`, c'est une session interactive et « bash -c » n'a rien à
    faire là — il attendrait une commande qui ne vient pas.
    """
    argv = [LIMACTL, "shell", str(name)]
    if remote:
        argv += ["--", "bash", "-c", str(remote)]
    return argv


def display(argv) -> str:
    """La commande telle qu'on la MONTRE avant de la jouer.

    `shlex.join` et non un espace : une valeur qui porte une espace se
    relirait comme deux arguments, et la ligne affichée ne serait plus celle
    qui s'exécute — ce qui est pire que ne rien montrer.
    """
    import shlex

    return shlex.join(str(mot) for mot in argv or ())


# Ce que l'inventaire de Lima rend, et ce qu'on en garde. Les autres champs
# existent ; on ne les lit pas, donc on ne s'engage pas sur eux.
class Instance(NamedTuple):
    """Une instance vue par l'inventaire. Les champs absents sont vides."""

    name: str
    status: str
    arch: str = ""
    ssh_port: str = ""


# Ce que l'outil appelle « en marche ». Comparé sans la casse : la valeur
# est un mot anglais capitalisé, et un jour minuscule ferait passer une
# instance vivante pour éteinte.
RUNNING = "running"


def parse_instances(text: str) -> tuple:
    """Les instances décrites par l'inventaire, quelle qu'en soit la forme.

    DEUX FORMES SONT ACCEPTÉES, et ce n'est pas de l'indécision : selon la
    version, l'inventaire rend soit un objet JSON PAR LIGNE, soit un tableau
    unique. Parier sur l'une des deux rendrait une liste vide sur l'autre —
    et une liste vide se lit comme « aucune instance », ce qui est un
    mensonge tranquille.

    Une ligne illisible est SAUTÉE plutôt que de faire échouer la lecture
    entière : une instance en cours de création peut très bien produire une
    ligne partielle, et perdre les autres pour elle serait pire.
    """
    brut = (text or "").strip()
    if not brut:
        return ()
    objets = _comme_tableau(brut)
    if objets is None:
        objets = _ligne_a_ligne(brut)
    lues = []
    for objet in objets:
        nom = str(objet.get("name") or "")
        if not nom:
            continue
        lues.append(
            Instance(
                name=nom,
                status=str(objet.get("status") or ""),
                arch=str(objet.get("arch") or ""),
                ssh_port=str(objet.get("sshLocalPort") or ""),
            )
        )
    return tuple(lues)


def _comme_tableau(brut: str):
    """Le tout comme un tableau JSON, ou None si ce n'en est pas un."""
    try:
        charge = json.loads(brut)
    except ValueError:
        return None
    if isinstance(charge, list):
        return [item for item in charge if isinstance(item, dict)]
    if isinstance(charge, dict):
        return [charge]
    return None


def _ligne_a_ligne(brut: str) -> list:
    """Un objet par ligne, les lignes illisibles sautées."""
    objets = []
    for ligne in brut.splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            charge = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(charge, dict):
            objets.append(charge)
    return objets


def is_running(instance) -> bool:
    """Cette instance tourne-t-elle ?"""
    return bool(instance) and instance.status.lower() == RUNNING


def find(instances, name: str):
    """L'instance qui porte ce nom, ou None."""
    for instance in instances or ():
        if instance.name == name:
            return instance
    return None
