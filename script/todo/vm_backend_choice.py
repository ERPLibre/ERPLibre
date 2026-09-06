#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Quel backend de VM cette machine emploie, et pourquoi celui-là.

LA PRÉFÉRENCE EST INDICATIVE. Elle préselectionne et elle informe ; elle ne
route rien. Le chemin de déploiement local est libvirt de bout en bout — il
vérifie /dev/kvm puis énumère les domaines par virsh avant même d'ouvrir son
écran — et une préférence qui l'aiguillerait ailleurs enverrait une
description de machine dans un chemin qui ne sait pas la lire. Le jour où ce
chemin saura, c'est LUI qui changera ; ce module dira la même chose.

Les fonctions sont PURES et reçoivent l'hôte et ses capacités en paramètres.
Deux conséquences : la résolution s'éprouve pour un système qu'on n'a pas
sous la main, et rien ici ne sonde la machine au milieu d'un écran.
"""

from __future__ import annotations

from script.todo import host_os
from script.vm import backend as vm

# Ce que la préférence peut valoir. « auto » n'est pas un backend : c'est
# l'absence de choix, et elle se résout par le système.
AUTO = "auto"
CHOIX = (AUTO, vm.LIBVIRT, vm.PVE, vm.LIMA)


def effective(pref: str, jeton_hote: str, limactl: bool = False) -> str:
    """Le backend réellement employé, une fois « auto » résolu.

    La règle d'« auto » n'est pas inventée : c'est celle que le dépôt
    applique déjà. Sur Linux, libvirt. Sur macOS, l'outil d'instances s'il
    est là — libvirt n'y existe pas, faute de /dev/kvm et des ponts sur
    lesquels son réseau est bâti. Sans lui, il reste l'hôte distant, ce que
    le menu local dit déjà en toutes lettres quand il se retire.

    Une préférence hors vocabulaire retombe sur « auto » plutôt que de
    figer un nom que personne ne sait servir.
    """
    voulu = str(pref or AUTO).strip().lower()
    if voulu in CHOIX and voulu != AUTO:
        return voulu
    if jeton_hote == host_os.MACOS:
        return vm.LIMA if limactl else vm.PVE
    return vm.LIBVIRT


def conseil(backend: str, jeton_hote: str) -> str:
    """La clé i18n qui dit ce que ce backend vaut ICI, ou "".

    Un conseil et non un refus : sur un système où l'outil d'instances
    pilote le même hyperviseur que libvirt, le choisir FONCTIONNE — il
    n'apporte simplement rien. Cacher l'entrée répondrait à la question par
    son absence.
    """
    if backend == vm.LIMA and jeton_hote != host_os.MACOS:
        return "Here it drives the same hypervisor as libvirt; it earns its place on macOS."
    if backend == vm.LIBVIRT and jeton_hote == host_os.MACOS:
        return (
            "libvirt does not exist here: no /dev/kvm, and no Linux bridges."
        )
    return ""
