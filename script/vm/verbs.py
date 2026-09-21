#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les verbes, un par un, au-dessus d'une identité de VM.

Chaque verbe prend un `VmHandle` et rend une CHAÎNE à exécuter. Il n'exécute
rien lui-même : c'est ce qui permet de l'éprouver entièrement depuis une
station, sans machine, et de MONTRER la commande avant de la lancer — ce que
le tableau de bord fait déjà pour la suppression.

Rien n'est sondé ici. Ce qui dépend de la machine locale — faut-il sudo pour
joindre libvirt, à quelle URI — entre en PARAMÈTRE. Le module ne sort donc
pas de son paquet : la bibliothèque standard et ses voisins de `script.vm`,
rien d'autre — pas d'écran, pas de configuration, pas de posture. Une épreuve
tient cette frontière pour le paquet entier, et c'est ce qui le garde
utilisable par un backend qui n'existe pas encore.
"""

from __future__ import annotations

import shlex
from typing import NamedTuple

from script.vm import lima
from script.vm.backend import (
    LIBVIRT,
    LIMA,
    PVE,
    VerbNotImplemented,
    is_hosted,
)

# L'URI libvirt par défaut. Passée en paramètre partout : un backend qui
# parle à une autre instance n'a pas à recompiler celui-ci.
LIBVIRT_URI = "qemu:///system"

# Ce qu'on sait faire à l'alimentation d'une VM, vocabulaire clos. Une
# action hors liste se voit ici, et non en composant une commande que
# l'hyperviseur rejettera sans qu'on sache laquelle des VM a échoué.
POWER_ACTIONS = ("suspend", "resume")


def host_command(handle, remote: str, tty: bool = False) -> str:
    """Commande shell qui exécute `remote` SUR l'hôte qui porte la VM.

    Chaque action qui parlait à libvirt par le NOM frappait la mauvaise
    machine dès qu'un domaine local portait le même : la console ouvrait
    celle de la VM locale, la pause suspendait la locale. L'hôte est la seule
    autorité pour une VM distante, et sa clé le seul identifiant.
    """
    info = (handle.host if handle else None) or {}
    cible = info.get("target") or ""
    if not cible:
        # Sans porteuse, il n'y a personne à qui parler. Composer quand même
        # donnait « ssh '' <commande> » : une cible VIDE, que ssh refuse par
        # un message qui ne nomme aucune machine.
        raise VerbNotImplemented(
            "host_command : aucune machine porteuse à qui parler."
        )
    sudo = info.get("sudo") or ""
    prefixe = f"{sudo}sh -c {shlex.quote(remote)}" if sudo else remote
    saut = f"-J {shlex.quote(info['jump'])} " if info.get("jump") else ""
    return (
        f"ssh {'-t ' if tty else ''}{saut}{shlex.quote(cible)} "
        f"{shlex.quote(prefixe)}"
    )


def identity_guard(handle) -> str:
    """Shell qui S'ARRÊTE si la clé ne désigne plus cette machine.

    Une clé se réutilise et une preuve non : un VMID libéré est RÉATTRIBUÉ,
    un nom de domaine se réemploie. Effacer « le 101 » d'un manifeste de mars,
    c'est effacer ce qui porte le 101 aujourd'hui.

    Rend « » quand la preuve manque. C'est un DÉSARMEMENT assumé : sur un
    poste où l'on n'a pas pu la relever, mieux vaut la prudence d'avant que
    refuser toute opération. L'appelant peut le voir avec `is_armed`.

    Une fonction à part, et exécutable telle quelle : c'est ce qui la rend
    vérifiable. Enfouie dans la commande, elle ne s'éprouvait qu'à travers
    deux « shlex.quote » — et un garde qu'on ne sait pas éprouver s'OUVRE le
    jour où il casse, au lieu de se fermer.

    Les valeurs passent par des VARIABLES de shell, assignées une fois et
    citées. Interpolées dans le message, elles y étaient relues par le shell :
    un nom portant une substitution de commande la faisait exécuter, à
    l'endroit précis où le garde annonce qu'il n'a rien fait — et sur l'hôte,
    sous élévation. Une variable se développe sans être réévaluée.
    """
    if handle is None:
        raise VerbNotImplemented("identity_guard : aucune identité.")
    # LE BACKEND D'ABORD, la preuve ensuite. Répondre « désarmé » sur un
    # backend qu'on ne connaît pas serait un échec OUVERT : on ne sait même
    # pas ce qui prouverait son identité, donc pas davantage que sa preuve
    # manque.
    if handle.backend not in (PVE, LIBVIRT, LIMA):
        raise VerbNotImplemented(
            f"identity_guard : backend « {handle.backend} » inconnu."
        )
    if not handle.proof:
        return ""
    if handle.backend == PVE:
        return _guard_pve(handle)
    if handle.backend == LIBVIRT:
        return _guard_libvirt(handle)
    raise VerbNotImplemented(
        f"identity_guard : backend « {handle.backend} » sans preuve connue."
    )


def _guard_pve(handle) -> str:
    """Le VMID adresse, le nom prouve."""
    return (
        f"el_attendu={shlex.quote(handle.proof)}; "
        f"el_vu=$(qm config {int(handle.key)} 2>/dev/null"
        " | sed -n 's/^name: //p' | head -1); "
        'if [ "$el_vu" != "$el_attendu" ]; then '
        f'echo "REFUS : le VMID {int(handle.key)} porte maintenant $el_vu,"'
        ' "et non $el_attendu. Rien n\'a ete efface."; exit 1; fi; '
    )


def _guard_libvirt(handle, sudo: str = "", uri: str = LIBVIRT_URI) -> str:
    """Le nom adresse, l'UUID prouve : il naît et meurt avec le domaine."""
    return (
        f"el_nom={shlex.quote(handle.key)}; "
        f"el_attendu={shlex.quote(handle.proof)}; "
        f'el_vu=$({sudo}virsh --connect {uri} domuuid "$el_nom"'
        " 2>/dev/null"
        " | tr -d '[:space:]'); "
        'if [ "$el_vu" != "$el_attendu" ]; then '
        'echo "REFUS : $el_nom n\'est plus le même domaine"'
        ' "($el_vu). Rien n\'a été effacé."; exit 1; fi; '
    )


def delete_command(
    handle,
    with_disks: bool = True,
    sudo: str = "",
    uri: str = LIBVIRT_URI,
) -> str:
    """Efface la VM LÀ OÙ ELLE VIT, garde d'identité en tête.

    `sudo` et `uri` ne servent qu'au backend local : ils décrivent la station
    d'ici, que ce module ne sonde pas.
    """
    if handle is None:
        raise VerbNotImplemented("delete_command : aucune identité.")
    if handle.backend == PVE:
        return _delete_pve(handle, with_disks)
    if handle.backend == LIBVIRT:
        return _delete_libvirt(handle, with_disks, sudo, uri)
    raise VerbNotImplemented(
        f"delete_command : backend « {handle.backend} » inconnu."
    )


def pve_delete_suite(handle, purge: bool = True) -> str:
    """La suite à jouer SUR l'hôte Proxmox : garde, arrêt, destruction.

    Une SUITE et non une commande : elle ne porte aucun ssh, parce que deux
    appelants la mènent à l'hôte par des chemins différents — l'un compose
    la ligne ssh ici, l'autre a déjà son transport ouvert. Écrite deux fois,
    elle divergerait, et c'est le chemin recopié qui perdrait le garde.

    UNE SEULE CHAÎNE, ET C'EST LE POINT. Rendue en deux morceaux joués dans
    deux shells, le « exit 1 » du garde ne fermait que le premier : la
    destruction partait quand même. Le garde ne vaut que dans le shell qu'il
    peut arrêter.
    """
    if handle is None:
        raise VerbNotImplemented("pve_delete_suite : aucune identité.")
    if handle.backend != PVE:
        raise VerbNotImplemented(
            f"pve_delete_suite : backend « {handle.backend} » — cette suite"
            " ne parle qu'à un hôte Proxmox."
        )
    vmid = int(handle.key)
    return identity_guard(handle) + (
        f"qm stop {vmid} --skiplock 1 || true; "
        f"qm destroy {vmid}"
        f"{' --purge 1 --destroy-unreferenced-disks 1' if purge else ''}"
    )


def _delete_pve(handle, purge: bool) -> str:
    """« virsh undefine <nom> » aurait effacé le domaine LOCAL homonyme —
    le même piège que partout ailleurs, avec la pire conséquence."""
    return host_command(handle, pve_delete_suite(handle, purge))


def _delete_libvirt(handle, with_disks: bool, sudo: str, uri: str) -> str:
    """Arrêt, retrait de la définition (nvram si UEFI, repli sinon), puis
    les disques à la demande."""
    q = shlex.quote(handle.key)
    cmd = _guard_libvirt(handle, sudo, uri) if handle.proof else ""
    cmd += (
        f"{sudo}virsh --connect {uri} destroy {q} 2>/dev/null; "
        f"{sudo}virsh --connect {uri} "
        f"undefine {q} --nvram 2>/dev/null "
        f"|| {sudo}virsh --connect {uri} undefine {q}"
    )
    if with_disks:
        disk = shlex.quote(f"/var/lib/libvirt/images/{handle.name}.qcow2")
        seed = shlex.quote(
            f"/var/lib/libvirt/images/iso/{handle.name}-seed.iso"
        )
        cmd += f"; sudo rm -f {disk} {seed}"
    return cmd


class Console(NamedTuple):
    """Comment ouvrir la console d'une VM, et comment en SORTIR.

    La séquence d'échappement appartient au backend et non à l'écran : elle
    n'est pas la même selon l'outil qui attache, et la donner fausse laisse
    l'utilisateur enfermé dans une console dont il ne sait plus sortir.
    """

    command: str
    label: str
    escape: str


def console(handle, sudo: str = "", uri: str = LIBVIRT_URI) -> Console:
    """De quoi ouvrir la console série de la VM.

    C'est le seul recours quand SSH ne répond pas : elle ne dépend ni du
    réseau de la VM, ni de sshd, ni d'une IP. Elle montre donc un démarrage
    bloqué ou un cloud-init encore en cours, que le suivi ne peut que
    constater de loin.

    Le piège est le même que partout : « virsh console <nom> » ouvre celle du
    domaine LOCAL homonyme, la mauvaise machine, sans le dire.
    """
    if handle is None:
        raise VerbNotImplemented("console : aucune identité.")
    if handle.backend == PVE:
        vmid = int(handle.key)
        hote = handle.host.get("target") or "?"
        return Console(
            command=host_command(handle, f"qm terminal {vmid}", tty=True),
            label=f"qm terminal {vmid} @ {hote}",
            # « qm terminal » relaie une console série : c'est Ctrl+O qui la
            # rend, et non la séquence de virsh.
            escape="Ctrl+O",
        )
    if handle.backend == LIBVIRT:
        q = shlex.quote(handle.key)
        return Console(
            command=f"{sudo}virsh --connect {uri} console {q}",
            label=f"virsh console {handle.key}",
            escape="Ctrl+]",
        )
    raise VerbNotImplemented(
        f"console : backend « {handle.backend} » inconnu."
    )


class WebAccess(NamedTuple):
    """Comment atteindre le service web d'une VM depuis ICI.

    `tunnel` vide veut dire que l'adresse est joignable telle quelle. Une
    URL vide veut dire qu'on ne sait pas encore où elle écoute — ce qui
    n'est pas « la page est morte », et l'écran doit pouvoir le dire.
    """

    url: str
    tunnel: tuple


def web_access(handle, port: int = 18069, service: int = 8069) -> WebAccess:
    """L'URL du service web, et le tunnel qu'il faut pour l'atteindre.

    Une VM sur un pont interne n'est pas routable d'ici : un navigateur ne
    peut pas l'atteindre, et la page reste morte sans que rien ne dise
    pourquoi. Le tunnel passe par l'hôte et dure le temps de la visite.

    Il se referme par son PID et non par « pkill -f <motif> » : le motif
    figure dans la ligne de commande du shell qui l'a lancé, qui se faisait
    donc tuer avec lui.
    """
    if handle is None:
        raise VerbNotImplemented("web_access : aucune identité.")
    if handle.backend not in (LIBVIRT, PVE, LIMA):
        # Composer une URL pour un backend inconnu, c'est affirmer qu'on
        # sait où son service écoute. On ne le sait pas.
        raise VerbNotImplemented(
            f"web_access : backend « {handle.backend} » inconnu."
        )
    if not handle.address:
        return WebAccess("", ())
    if handle.backend == PVE and handle.host.get("target"):
        argv = ["ssh", "-N", "-o", "ExitOnForwardFailure=yes"]
        if handle.host.get("jump"):
            argv += ["-J", handle.host["jump"]]
        argv += [
            "-L",
            f"{port}:{handle.address}:{service}",
            handle.host["target"],
        ]
        return WebAccess(f"http://127.0.0.1:{port}", tuple(argv))
    return WebAccess(f"http://{handle.address}:{service}", ())


def ssh_prefix(handle, user: str = "erplibre", options: str = "") -> str:
    """« ssh … » pour entrer dans CETTE VM, adresse comprise.

    Une VM d'hôte distant vit derrière lui : son adresse n'est routable que
    de là, et seuls les rebonds y mènent. On les compose explicitement
    plutôt que de compter sur un alias ~/.ssh/config, qui peut ne pas
    exister — ou, pire, désigner une VM LOCALE homonyme.

    LES REBONDS SE SÉPARENT PAR DES VIRGULES. Répéter « -J » ne les
    accumule pas : ssh refuse la ligne entière — « Only a single -J option
    is permitted » — et rend 255. Toute VM dont l'hôte est lui-même derrière
    un rebond était donc injoignable, sans que l'erreur dise laquelle des
    deux machines posait problème.
    """
    if handle is None:
        raise VerbNotImplemented("ssh_prefix : aucune identité.")
    if handle.backend == LIMA:
        # On n'entre pas par ssh dans une instance qui n'a pas d'adresse.
        # Son outil ouvre lui-même un shell, et la forme diffère selon
        # qu'on veut une session ou une commande : ce verbe ne peut pas
        # rendre les deux, et en choisir une en silence donnerait à
        # l'appelant une ligne qui marche une fois sur deux.
        raise VerbNotImplemented(
            "ssh_prefix : cette VM ne s'atteint pas par ssh ;"
            " voir exec_prefix."
        )
    if handle.backend not in (LIBVIRT, PVE):
        # Un quatrième nom n'hérite du chemin d'aucun des trois. Le laisser
        # tomber ici composait une ligne ssh pour une machine dont personne
        # n'a dit qu'elle en acceptait une.
        raise VerbNotImplemented(
            f"ssh_prefix : backend « {handle.backend} » inconnu."
        )
    if not (handle.address or handle.alias):
        # Sans adresse ni alias, la ligne composée serait « ssh compte@ » —
        # une cible VIDE que ssh refuse par un message qui ne nomme aucune
        # machine. Le silence est ici le pire des rendus.
        raise VerbNotImplemented(
            "ssh_prefix : aucune adresse ni alias pour joindre cette VM."
        )
    debut = f"ssh {options} " if options else "ssh "
    rebonds = [
        saut
        for saut in (handle.host.get("jump"), handle.host.get("target"))
        if saut
    ]
    if rebonds and handle.address:
        chaine = ",".join(shlex.quote(saut) for saut in rebonds)
        return f"{debut}-J {chaine} {user}@{handle.address}"
    return f"{debut}{user}@{handle.alias or handle.address}"


def connect_command(handle, user: str = "erplibre", options: str = "") -> str:
    """La ligne qu'un HUMAIN recopie pour ouvrir une session dans la VM.

    LA TROISIÈME FORME, et `ssh_prefix` la nommait déjà en creux : « la
    forme diffère selon qu'on veut une session ou une commande ». Celle-ci
    est la SESSION. `exec_prefix`, lui, prépare une commande et finit donc
    par « bash -c » : le recopier ouvrirait un shell qui attend une commande
    qui ne vient jamais.

    Rendue pour TOUS les backends, y compris celui que `ssh_prefix` refuse.
    Il n'y a rien à refuser ici : chaque backend a une façon d'entrer, et
    c'est justement ce qu'un tableau de bord affiche pour qu'on la recopie.
    Composer « ssh compte@instance » pour une VM qui ne s'atteint pas par
    ssh donnerait une ligne qui échoue chez celui qui la recopie, et rien
    dans le message de ssh ne dirait que le backend était le mauvais.
    """
    if handle is None:
        raise VerbNotImplemented("connect_command : aucune identité.")
    if handle.backend == LIMA:
        # Le NOM suffit, et la forme vient du module de l'outil : ce fichier
        # nommait « limactl » en dur, et deux littéraux voisins cessent de
        # correspondre au premier ajustement.
        return lima.display(lima.shell_argv(handle.key))
    return ssh_prefix(handle, user=user, options=options)


def power_command(
    handle, action: str, sudo: str = "", uri: str = LIBVIRT_URI
) -> str:
    """Suspend ou reprend la VM, LÀ OÙ ELLE VIT.

    « virsh suspend <nom> » mettait en pause le domaine LOCAL homonyme. La
    pause est le pire endroit pour se tromper de machine : rien ne casse, rien
    n'alerte, et la VM figée est celle qu'on n'a pas regardée.

    Rend une CHAÎNE dans les deux cas, comme la suppression : les deux
    formes — argv ici, chaîne là-bas — obligeaient l'appelant à savoir
    laquelle il tenait, donc à connaître le backend.
    """
    if handle is None:
        raise VerbNotImplemented("power_command : aucune identité.")
    if action not in POWER_ACTIONS:
        connues = ", ".join(POWER_ACTIONS)
        raise VerbNotImplemented(
            f"power_command : action « {action} » inconnue."
            f" Connues : {connues}."
        )
    if handle.backend == PVE:
        return host_command(handle, f"qm {action} {int(handle.key)}")
    if handle.backend == LIBVIRT:
        q = shlex.quote(handle.key)
        return f"{sudo}virsh --connect {uri} {action} {q}"
    raise VerbNotImplemented(
        f"power_command : backend « {handle.backend} » inconnu."
    )


def arm(handle, probe=None):
    """Relève la preuve d'identité MAINTENANT, et rend la fiche armée.

    C'est le seul instant où l'on sait que ce nom désigne cette machine :
    on vient de la créer. Rouvert des semaines plus tard, un manifeste ne
    peut plus le savoir, et c'est cette preuve-là qui armera le garde de la
    suppression.

    `probe` est la fonction qui va CHERCHER la preuve sur la machine —
    injectée, donc éprouvable sans hyperviseur. Une preuve déjà là n'est pas
    re-relevée ; un backend dont la preuve se déduit du nom n'a rien à
    sonder du tout.

    Une sonde muette laisse la fiche DÉSARMÉE plutôt que d'échouer : mieux
    vaut la protection d'avant que refuser de créer la machine.
    """
    if handle is None:
        raise VerbNotImplemented("arm : aucune identité.")
    if handle.proof or probe is None:
        return handle
    if handle.backend != LIBVIRT:
        return handle
    return handle._replace(proof=str(probe(handle.key) or ""))


def identity_fields(handle) -> dict:
    """Ce qu'une entrée de manifeste doit porter pour RETROUVER la machine.

    L'inverse de `handle_of` : ce que celui-ci lit, celui-là l'écrit. Les
    deux se font face, et une épreuve d'aller-retour tient leur accord —
    sans quoi une identité écrite d'une façon et relue d'une autre désigne
    tranquillement autre chose.
    """
    if handle is None:
        raise VerbNotImplemented("identity_fields : aucune identité.")
    if handle.backend == PVE:
        return {"pve": dict(handle.host)}
    if handle.backend == LIBVIRT:
        return {"uuid": handle.proof}
    if handle.backend == LIMA:
        # Un drapeau, et non une preuve : il n'y en a pas encore. Il dit
        # seulement quel backend relira cette entrée.
        return {"lima": True}
    raise VerbNotImplemented(
        f"identity_fields : backend « {handle.backend} » inconnu."
    )


def exec_address(handle) -> str:
    """L'adresse par laquelle on ENTRE dans la VM pour y travailler.

    Ce n'est pas celle où son service écoute. Une VM d'hôte distant écoute
    sur une adresse que seul l'hôte route ; d'ici on passe par l'alias de
    ~/.ssh/config, qui porte le rebond. Les confondre fait attendre vingt
    minutes une adresse qui ne répondra jamais, sur une VM parfaitement
    saine.
    """
    if handle is None:
        raise VerbNotImplemented("exec_address : aucune identité.")
    if handle.backend == LIMA:
        # On entre par le NOM. C'est tout l'apport de ce backend, et sur un
        # système sans réseau d'hyperviseur à interroger, c'est le seul
        # moyen : il n'y a aucun bail à relire.
        return handle.key
    if is_hosted(handle):
        entree = handle.alias or handle.address
        if not entree:
            # REFUSER plutôt que rendre le vide : l'appelant en fait « ip= »,
            # et « ssh "compte@$ip" » part alors vers personne pendant les
            # vingt minutes d'attente prévues pour un boot émulé. Le vide
            # n'est tenable que là où l'adresse se ré-résout en chemin, ce
            # qui demande un hyperviseur LOCAL — et une VM portée par un
            # hôte n'en a pas.
            raise VerbNotImplemented(
                "exec_address : aucune adresse ni alias pour entrer dans"
                " cette VM, et aucun hyperviseur local ne la relira."
            )
        return entree
    return handle.address or handle.alias


def exec_prefix(handle, options: str = "", user: str = "erplibre") -> str:
    """Le début de commande qui exécute DANS la VM, commande non comprise.

    L'adresse y est une VARIABLE de shell et non une valeur : le script
    détaché la ré-résout en cours de route quand le bail bouge, et la figer
    ici ferait attendre une adresse morte. C'est l'appelant qui définit
    « ip », une fois, avec `exec_address`.

    C'est LA couture qu'un backend sans adresse impose : là où celui-ci rend
    « ssh … », un autre rendra une commande qui joint la VM par son NOM.
    """
    if handle is None:
        raise VerbNotImplemented("exec_prefix : aucune identité.")
    if handle.backend in (LIBVIRT, PVE):
        espace = f"{options} " if options else ""
        return f'ssh {espace}"{user}@$ip"'
    if handle.backend == LIMA:
        # « bash -c » est indispensable ICI et inutile pour ssh : le premier
        # exécute des ARGUMENTS, si bien qu'une suite (« a && b ») lui
        # arriverait comme une liste de mots ; le second passe la commande
        # au shell distant de lui-même.
        #
        # Ni compte ni adresse : l'instance appartient à l'utilisateur qui
        # la lance, et le nom suffit à la joindre.
        base = lima.display(lima.shell_argv(handle.key))
        return f"{base} -- bash -c"
    raise VerbNotImplemented(
        f"exec_prefix : backend « {handle.backend} » inconnu."
    )
