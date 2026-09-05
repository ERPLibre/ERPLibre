#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les verbes, un par un, au-dessus d'une identité de VM.

Chaque verbe prend un `VmHandle` et rend une CHAÎNE à exécuter. Il n'exécute
rien lui-même : c'est ce qui permet de l'éprouver entièrement depuis une
station, sans machine, et de MONTRER la commande avant de la lancer — ce que
le tableau de bord fait déjà pour la suppression.

Rien n'est sondé ici. Ce qui dépend de la machine locale — faut-il sudo pour
joindre libvirt, à quelle URI — entre en PARAMÈTRE. Le module n'importe donc
que la bibliothèque standard, et une épreuve le vérifie : c'est ce qui le
garde utilisable par un backend qui n'existe pas encore.
"""

from __future__ import annotations

import shlex

from script.vm.backend import LIBVIRT, PVE, VerbNotImplemented

# L'URI libvirt par défaut. Passée en paramètre partout : un backend qui
# parle à une autre instance n'a pas à recompiler celui-ci.
LIBVIRT_URI = "qemu:///system"


def host_command(handle, remote: str, tty: bool = False) -> str:
    """Commande shell qui exécute `remote` SUR l'hôte qui porte la VM.

    Chaque action qui parlait à libvirt par le NOM frappait la mauvaise
    machine dès qu'un domaine local portait le même : la console ouvrait
    celle de la VM locale, la pause suspendait la locale. L'hôte est la seule
    autorité pour une VM distante, et sa clé le seul identifiant.
    """
    info = (handle.host if handle else None) or {}
    sudo = info.get("sudo") or ""
    cible = info.get("target") or ""
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
    """
    if not handle or not handle.proof:
        return ""
    if handle.backend == PVE:
        return _guard_pve(handle)
    if handle.backend == LIBVIRT:
        return _guard_libvirt(handle)
    raise VerbNotImplemented(
        f"identity_guard : backend « {handle.backend} » inconnu."
    )


def _guard_pve(handle) -> str:
    """Le VMID adresse, le nom prouve."""
    q = shlex.quote(handle.proof)
    return (
        f"vu=$(qm config {int(handle.key)} 2>/dev/null"
        " | sed -n 's/^name: //p' | head -1); "
        f'if [ "$vu" != {q} ]; then '
        f'echo "REFUS : le VMID {int(handle.key)} porte maintenant $vu,"'
        f' "et non {handle.proof}. Rien n\'a ete efface."; exit 1; fi; '
    )


def _guard_libvirt(handle, sudo: str = "", uri: str = LIBVIRT_URI) -> str:
    """Le nom adresse, l'UUID prouve : il naît et meurt avec le domaine."""
    q = shlex.quote(handle.key)
    return (
        f"vu=$({sudo}virsh --connect {uri} domuuid {q}"
        " 2>/dev/null"
        " | tr -d '[:space:]'); "
        f'if [ "$vu" != {shlex.quote(handle.proof)} ]; then '
        f'echo "REFUS : {handle.key} n\'est plus le même domaine"'
        f' "($vu). Rien n\'a été effacé."; exit 1; fi; '
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


def _delete_pve(handle, purge: bool) -> str:
    """« virsh undefine <nom> » aurait effacé le domaine LOCAL homonyme —
    le même piège que partout ailleurs, avec la pire conséquence."""
    vmid = int(handle.key)
    suite = identity_guard(handle)
    suite += (
        f"qm stop {vmid} --skiplock 1 || true; "
        f"qm destroy {vmid}"
        f"{' --purge 1 --destroy-unreferenced-disks 1' if purge else ''}"
    )
    return host_command(handle, suite)


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
