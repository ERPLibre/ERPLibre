#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'identité d'une VM : ce qui l'ADRESSE, et ce qui le PROUVE.

Toute une famille de bugs vient d'une seule confusion : le nom qu'un humain
lit et la clé par laquelle une machine se commande ne sont pas la même chose,
et s'en servir comme si c'était le cas commande la mauvaise machine sans
jamais le dire. « virsh console <nom> » ouvre la console du domaine LOCAL
homonyme ; « qm destroy 101 » détruit ce qui porte le 101 AUJOURD'HUI.

Trois champs distincts, donc, et le fait qu'ils diffèrent est le sujet :

    name   ce que l'humain lit. Ne commande RIEN.
    key    ce que le backend adresse.
    proof  ce qui atteste que la clé désigne encore cette machine-là.

Leur appariement change d'un backend à l'autre, et c'est bien pour ça qu'on
ne peut pas s'en passer :

    libvirt   adresse par NOM (virsh le veut ainsi) et prouve par l'UUID,
              qui naît avec le domaine et meurt avec lui.
    pve       adresse par VMID et prouve par le nom, parce qu'un VMID libéré
              est RÉATTRIBUÉ.

Dans les deux cas la clé est réutilisable et la preuve ne l'est pas — c'est
la définition de ce qu'on cherche.

CE QUI REND LE SUJET URGENT : un suivi se rouvre sur un manifeste qui peut
avoir des semaines. Au moment où il a été écrit, on savait que ce nom
désignait cette machine ; à la relecture, plus rien ne le dit. La preuve est
ce qu'on a écrit à l'instant où on le savait.

Ce module ne commande rien et n'affiche rien : il NOMME. Les verbes viendront
s'appuyer dessus, un par un.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import NamedTuple

# Les backends connus, vocabulaire clos. Un nom hors liste se voit ici, où
# il est visible, et non au moment où une commande part sur une machine.
LIBVIRT = "libvirt"
PVE = "pve"
BACKENDS = (LIBVIRT, PVE)


class VmBackendError(Exception):
    """Ce qu'un backend refuse. Le message est destiné à l'utilisateur."""


class VerbNotImplemented(VmBackendError):
    """Ce backend ne sait pas faire ça, et ne le saura pas.

    Distinct d'une panne : un appelant peut retirer proprement l'entrée du
    menu, là où une erreur l'enverrait chercher ce qui ne va pas.
    """


class VmHandle(NamedTuple):
    """De quoi commander UNE machine, et vérifier que c'est la bonne.

    `host` porte la fiche de la machine qui l'héberge — vide en local. C'est
    ce qui permet à un verbe de savoir qu'il doit passer par quelqu'un
    d'autre pour l'atteindre.
    """

    backend: str
    name: str
    key: str
    proof: str
    # OÙ le service écoute. Distinct de la clé : une VM d'un hôte distant
    # s'adresse par son VMID et écoute sur une adresse que seul l'hôte
    # route. Vide quand elle n'est pas encore connue — ce qui n'est pas
    # « injoignable », et l'appelant doit pouvoir distinguer les deux.
    address: str = ""
    # Vue IMMUABLE par défaut : un dictionnaire nu serait partagé par toutes
    # les fiches qui l'omettent, et l'une d'elles finirait par le remplir
    # pour toutes les autres.
    host: dict = MappingProxyType({})


def pve_handle(info, name: str = "") -> VmHandle:
    """L'identité d'une VM d'hôte Proxmox, depuis la fiche de son hôte.

    UN SEUL endroit compose cette fiche. Chaque appelant qui la composait
    lui-même le faisait par position, et un champ ajouté au milieu les
    décalait tous en silence — l'hôte se retrouvant dans l'adresse, la
    commande partant vers une cible vide.
    """
    info = dict(info or {})
    return VmHandle(
        backend=PVE,
        name=name,
        key=str(int(info.get("vmid") or 0)),
        proof=name,
        address=str(info.get("addr") or ""),
        host=info,
    )


def libvirt_handle(name: str, uuid: str = "", ip: str = "") -> VmHandle:
    """L'identité d'une VM locale. Même raison qu'au-dessus."""
    return VmHandle(
        backend=LIBVIRT,
        name=name,
        key=name,
        proof=str(uuid or ""),
        address=str(ip or ""),
        host={},
    )


def handle_of(entry) -> VmHandle | None:
    """L'identité que porte une entrée de manifeste, ou None.

    Lit la forme que les manifestes ont AUJOURD'HUI : une entrée qui porte
    « pve » vit sur un hôte Proxmox, les autres sont locales. None quand
    l'entrée ne porte pas même un nom — elle ne désigne alors rien, et le
    dire vaut mieux que de rendre une identité vide qui commanderait au
    hasard.
    """
    entry = entry or {}
    nom = str(entry.get("name") or "")
    if not nom:
        return None
    info = entry.get("pve") or {}
    if info:
        # Le VMID adresse ; le nom prouve. Un VMID libéré est réattribué,
        # donc effacer « le 101 » d'un manifeste de mars, c'est effacer ce
        # qui porte le 101 aujourd'hui.
        return pve_handle(info, nom)
    # Le nom adresse — c'est virsh qui l'impose — et l'UUID prouve.
    return libvirt_handle(nom, uuid=entry.get("uuid"), ip=entry.get("ip"))


def addresses_by_name(handle) -> bool:
    """La clé est-elle le nom lui-même ?

    Quand c'est le cas, un homonyme suffit à commander la mauvaise machine,
    et la preuve n'est pas un luxe : c'est la seule chose qui sépare les
    deux.
    """
    return bool(handle) and handle.key == handle.name


def is_armed(handle) -> bool:
    """La preuve est-elle là ?

    Une preuve vide DÉSARME la vérification au lieu de bloquer : sur un poste
    où l'on n'a pas pu la relever, mieux vaut la prudence d'avant que refuser
    toute opération. Mais l'appelant doit pouvoir le SAVOIR, et le dire.
    """
    return bool(handle) and bool(handle.proof)


def same_machine(left, right) -> bool:
    """Ces deux identités désignent-elles la même machine ?

    Compare ce qui ADRESSE, pas ce qui s'affiche : deux entrées du même nom
    sur deux hôtes différents sont deux machines, et l'écran qui les
    confondrait est celui qui a fait ouvrir la mauvaise.
    """
    if not left or not right:
        return False
    return (
        left.backend == right.backend
        and left.key == right.key
        and left.host.get("target", "") == right.host.get("target", "")
    )
