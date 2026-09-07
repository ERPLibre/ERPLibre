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

import re
from types import MappingProxyType
from typing import NamedTuple

# Les backends connus, vocabulaire clos. Un nom hors liste se voit ici, où
# il est visible, et non au moment où une commande part sur une machine.
LIBVIRT = "libvirt"
PVE = "pve"
LIMA = "lima"
BACKENDS = (LIBVIRT, PVE, LIMA)

# Ce qui a réellement tourné contre une machine, et ce qui n'a que des
# épreuves unitaires. « Non éprouvé » ne veut pas dire douteux : il veut dire
# NON CONFRONTÉ, et un écran qui ne le dit pas laisse croire l'inverse. La
# même distinction que les pilotes de tunnel portent déjà.
PROVEN = {LIBVIRT: True, PVE: True, LIMA: False}


def is_proven(backend) -> bool:
    """Ce backend a-t-il déjà tourné contre une vraie machine ?"""
    return bool(PROVEN.get(backend))


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
    # Le nom qu'un ~/.ssh/config sait résoudre seul, quand il existe. Pour
    # une VM d'hôte distant ce n'est PAS son adresse : celle-ci n'est
    # routable que depuis l'hôte, l'alias porte le chemin complet.
    alias: str = ""
    # Vue IMMUABLE par défaut : un dictionnaire nu serait partagé par toutes
    # les fiches qui l'omettent, et l'une d'elles finirait par le remplir
    # pour toutes les autres.
    host: dict = MappingProxyType({})


def pve_handle(info, name: str = "", alias: str = "") -> VmHandle:
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
        alias=str(alias or ""),
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


# La forme d'un UUID libvirt : 8-4-4-4-12 chiffres hexadécimaux. Elle sert
# à reconnaître la COLONNE, et non à valider la valeur : si l'inventaire
# changeait l'ordre de ses colonnes un jour, une ligne dont le premier champ
# n'a pas cette forme ne doit pas voir son nom pris pour une preuve.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def parse_uuid_listing(text: str) -> tuple:
    """Les domaines de « virsh list --all --uuid --name », dans l'ordre.

    UN SEUL APPEL donne le nom ET la preuve. Les deux options ne s'excluent
    pas, et la sortie porte l'UUID EN TÊTE quel que soit l'ordre où on les
    écrit — mesuré contre le pilote de test intégré, qui a toujours un
    domaine et ne demande aucun hyperviseur.

    LE DÉCOUPAGE EST PAR LIGNE, puis en DEUX champs. Un découpage sur tout
    blanc rendrait [uuid, nom, uuid, nom…] : un écran qui numérote cette
    liste proposerait des UUID comme s'ils étaient des machines. Deux champs
    et non plus : un nom de domaine peut porter un espace, et il est ce qui
    reste après la preuve.

    Une ligne dont le premier champ n'a pas la forme d'un UUID rend un
    handle SANS preuve, nom entier conservé : la faire disparaître de la
    liste cacherait une machine, alors que l'appelant doit pouvoir la nommer
    pour la refuser.
    """
    domaines = []
    for ligne in (text or "").splitlines():
        nu = ligne.strip()
        if not nu:
            continue
        champs = nu.split(None, 1)
        if len(champs) == 2 and _UUID_RE.match(champs[0]):
            domaines.append(libvirt_handle(champs[1], uuid=champs[0]))
        else:
            domaines.append(libvirt_handle(nu))
    return tuple(domaines)


def lima_handle(name: str, ip: str = "") -> VmHandle:
    """L'identité d'une VM Lima. Elle s'adresse par son NOM, sans adresse.

    C'est le seul apport que Lima ait sur un hôte qui a déjà libvirt, et
    c'est celui qui compte sur macOS : il n'y a pas là de réseau libvirt à
    interroger pour obtenir un bail, donc pas d'adresse à relire.

    LA PREUVE MANQUE, et c'est dit plutôt que fabriqué. Un nom d'instance se
    réutilise comme un nom de domaine ; il faudrait quelque chose qui naisse
    et meure avec l'instance. Reste à établir si l'inventaire de Lima en
    expose un — cela se mesure sur une machine, pas ici, et `long_test/`
    porte la question. Jusque-là la fiche est DÉSARMÉE, ce que `is_armed`
    dit, et la suppression retombe sur la confirmation à deux mains.
    """
    return VmHandle(
        backend=LIMA,
        name=name,
        key=name,
        proof="",
        address=str(ip or ""),
        alias="",
        host={},
    )


def handle_of(entry) -> VmHandle | None:
    """L'identité que porte une entrée de manifeste, ou None.

    Lit la forme que les manifestes ont AUJOURD'HUI : une entrée qui porte
    « pve » vit sur un hôte Proxmox, les autres sont locales.

    None quand rien n'est ADRESSABLE, et non quand un champ manque. Ce qui
    adresse n'est pas le même des deux côtés : une VM locale sans nom ne
    désigne rien, puisque virsh l'appelle par son nom ; une VM d'hôte
    distant s'adresse par son VMID et reste donc commandable sans nom —
    simplement DÉSARMÉE, ce que `is_armed` dit. Les confondre refuserait de
    lire une entrée parfaitement utilisable, ou pire, la ferait passer pour
    locale.
    """
    entry = entry or {}
    nom = str(entry.get("name") or "")
    if entry.get("lima"):
        # Le nom EST la clé : sans lui, il n'y a rien à viser.
        return lima_handle(nom, ip=entry.get("ip")) if nom else None
    info = entry.get("pve") or {}
    if info:
        if not (nom or int(info.get("vmid") or 0)):
            return None
        # Le VMID adresse ; le nom prouve. Un VMID libéré est réattribué,
        # donc effacer « le 101 » d'un manifeste de mars, c'est effacer ce
        # qui porte le 101 aujourd'hui.
        return pve_handle(info, nom, alias=entry.get("ip"))
    if not nom:
        return None
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


def resolves_locally(handle) -> bool:
    """L'adresse de cette VM se relit-elle par l'hyperviseur LOCAL ?

    Faux dès qu'un hôte la porte : ré-résoudre par virsh y trouve le domaine
    local homonyme, et l'installation part sur la mauvaise machine — sans
    rien dire, puisque le domaine trouvé répond très bien.
    """
    return bool(handle) and handle.backend == LIBVIRT


def is_hosted(handle) -> bool:
    """Une AUTRE machine porte-t-elle cette VM ?

    C'est le fait dont découle tout ce qui suit : ses commandes passent par
    quelqu'un d'autre, et son service ne se sonde pas d'ici — son adresse
    interne ne répond qu'à l'hôte, qui la teste donc pour nous.

    Distinct de `resolves_locally`, et pas seulement par la formulation. Les
    deux répondent aujourd'hui l'inverse l'une de l'autre parce qu'il n'y a
    que deux backends ; un backend LOCAL qui n'est pas libvirt les fera
    diverger, et les confondre lui ferait alors prendre le mauvais chemin
    sans que rien ne le dise.
    """
    return bool(handle) and handle.backend == PVE


def group_by_host(handles) -> dict:
    """Les fiches regroupées par MACHINE PORTEUSE, dans l'ordre rencontré.

    UN relevé par hôte, et non par VM. Chaque aller-retour coûte une poignée
    de main ssh ; un hôte rapporte toutes ses VM d'un coup. Interroger VM par
    VM multiplierait ce coût par leur nombre, sur le chemin le plus chaud du
    suivi — celui qui se rejoue à chaque tour.

    La clé est le couple (cible, élévation) : deux comptes différents sur la
    même machine sont deux connexions, et les fondre en une ferait jouer la
    commande sous le mauvais.

    Les fiches que personne ne porte n'y figurent pas : il n'y a pas d'hôte
    à qui les demander.
    """
    groupes = {}
    for handle in handles or ():
        if not is_hosted(handle):
            continue
        cible = handle.host.get("target") or ""
        if not cible:
            continue
        groupes.setdefault((cible, handle.host.get("sudo") or ""), []).append(
            handle
        )
    return groupes


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
