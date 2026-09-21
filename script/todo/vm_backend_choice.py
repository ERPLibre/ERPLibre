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
from script.todo.todo_i18n import t
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


# La légende de l'étoile, reprise mot pour mot des pilotes de tunnel : elle
# dit ce qui MANQUE — la confrontation au terrain — et non que le code serait
# douteux. Les épreuves unitaires, elles, sont là.
UNPROVEN_NOTE = "never run against the real tool: only unit tests cover it"

# Largeur de la colonne des libellés. Une seule source : l'étoile et le
# conseil s'alignent dessus, et deux valeurs voisines cessent de s'aligner
# entre elles au premier libellé plus long.
LARGEUR = 46


def render(pref: str, jeton_hote: str, limactl: bool = False) -> list:
    """L'écran des backends, en lignes prêtes à imprimer.

    Fonction PURE : elle reçoit l'hôte et ses capacités, donc l'écran de
    macOS se relit depuis n'importe où.

    DEUX MARQUES, ET ELLES NE DISENT PAS LA MÊME CHOSE. « ← » désigne ce qui
    est CHOISI ; l'étoile, ce qui n'a jamais été confronté au vrai outil. Une
    seule marque pour les deux ferait lire « non éprouvé » sur le backend
    actif.

    La ligne « automatique » ne porte NI étoile NI conseil : ils
    appartiennent au backend, et les lui emprunter les afficherait deux fois
    — une fois sur elle, une fois sur celui qu'elle désigne. Elle dit à quoi
    elle se résout, ce qui est sa seule information propre.

    Le conseil va sur SA ligne : accolé, il déborde du terminal dès que le
    libellé est long, et c'est la fin de la phrase qui disparaît.
    """
    from script.todo.todo import TODO

    _titre, options = TODO._PREF_CHOICES["vm_backend"]
    employe = effective(pref, jeton_hote, limactl)
    lignes, etoile_posee = [], False
    for rang, (valeur, label) in enumerate(options, 1):
        marque = f"  ← {t('chosen')}" if valeur == pref else ""
        if valeur == AUTO:
            # Ce que « automatique » donnerait, et NON ce que la préférence
            # courante donne : sur une machine où l'on a choisi autre chose,
            # les deux diffèrent, et afficher le second ferait croire
            # qu'automatique mène là aussi.
            lignes.append(
                f"  [{rang}] {t(label)} →"
                f" {effective(AUTO, jeton_hote, limactl)}{marque}"
            )
            continue
        etoile = " *" if not vm.is_proven(valeur) else ""
        etoile_posee = etoile_posee or bool(etoile)
        lignes.append(f"  [{rang}] {t(label)}{etoile}{marque}")
        cle = conseil(valeur, jeton_hote)
        if cle:
            lignes.append(f"        {t(cle)}")
    lignes.append("")
    lignes.append(f"  {t('In use:')} {employe}")
    if etoile_posee:
        lignes.append(f"  * {t(UNPROVEN_NOTE)}")
    return lignes
