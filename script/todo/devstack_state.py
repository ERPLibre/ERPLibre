#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Où en est l'intégration de devstack dans ERPLibre, DÉRIVÉ et non déclaré.

CE QUE CE MODULE REFUSE DE FAIRE. Un tableau d'avancement écrit à la main
vieillit sans un mot : il reste lisible, personne ne le relit, et il dit
« fait » longtemps après qu'on a défait. Chaque ligne d'ici se calcule donc
depuis ce qui décide VRAIMENT — la table des backends éprouvés, le registre
des postures, les profils, les cibles déclarées — et rien n'y est recopié.

TROIS ÉTATS, UN RENDU PARTAGÉ. Les états, la ligne et le rendu vivent dans
`script.todo.state_screen`, commun aux écrans d'état ; ce module n'en tire
que ses lignes.

LE RELEVÉ EST SÉPARÉ DE LA DÉCISION. `releve()` touche la configuration du
site ; `lignes()` est PURE et se relit sans machine ni fichier. C'est ce qui
permet d'éprouver chaque verdict, y compris ceux qu'on n'a pas sous la main.
"""

from __future__ import annotations

from typing import NamedTuple

from script.forge import mirror as forge_mirror
from script.forge import profiles as forge_profiles
from script.posture import registry as posture_registry
from script.posture import rules as posture_rules
from script.remote import deploy_target
from script.todo import vm_profiles

# Le rendu commun des écrans d'état. Réexporté tel quel : le menu devstack
# et ses épreuves lisent encore ces noms ICI.
from script.todo.state_screen import (  # noqa: F401
    A_REGLER,
    ABSENT,
    ETATS,
    MARQUES,
    PORTE,
    Ligne,
    compte,
    render,
)
from script.todo.todo_i18n import t
from script.vm import backend as vm_backend


class Releve(NamedTuple):
    """Ce que le dépôt et ce site disent, à un instant.

    Rassemblé en UNE fois : relire la configuration entre deux lignes
    rendrait un écran dont les lignes ne décrivent pas le même état.
    """

    backends_eprouves: tuple
    postures_armees: tuple
    profils_servant_le_web: tuple
    profils_forge: tuple
    cibles_sauvegarde: tuple
    # Le nom de la forge qui fait autorité, ou "" — pas un booléen : l'écran
    # la nomme, et un « oui » ne dirait pas laquelle.
    forge_canonique: str = ""
    # Les dépôts que ce site déclare pousser vers un amont.
    miroirs_sortants: tuple = ()


def releve(config_file=None) -> Releve:
    """L'état du dépôt et de ce site. Touche la configuration."""
    return Releve(
        backends_eprouves=tuple(
            n for n in vm_backend.BACKENDS if vm_backend.is_proven(n)
        ),
        postures_armees=tuple(
            n
            for n in posture_registry.posture_names()
            if posture_rules.wants_rules(posture_registry.get_posture(n))
        ),
        profils_servant_le_web=tuple(
            p.label for p in vm_profiles.profiles() if p.serves_web
        ),
        profils_forge=tuple(forge_profiles.names()),
        forge_canonique=_nom_de_l_autorite(config_file),
        miroirs_sortants=_miroirs_sortants(config_file),
        cibles_sauvegarde=tuple(
            c.get("name", "")
            for c in deploy_target.load_all(config_file)
            if c.get("kind") == deploy_target.KIND_BACKUP
        ),
    )


def _nom_de_l_autorite(config_file) -> str:
    """Le nom de la forge canonique, ou "".

    DEUX AUTORITÉS SONT UN RÉGLAGE À FAIRE, pas un écran cassé : le relevé
    rend "" et la ligne dira « à régler ici ». Laisser le refus traverser
    tuerait un écran qui ne fait que décrire.
    """
    try:
        profil = forge_profiles.canonical(config_file)
    except Exception:  # noqa: BLE001 - un relevé, pas le sujet
        return ""
    return (profil or {}).get("name", "")


def _miroirs_sortants(config_file) -> tuple:
    """Les dépôts que ce site déclare pousser vers un amont.

    Lu dans la CONFIGURATION et non sur la forge : cet écran doit se rendre
    sans réseau, et un appel d'API y ferait attendre une machine qui dort.

    DEMANDÉ À SON AUTORITÉ. La clé de section et le vocabulaire des sens
    vivent dans `script.forge.mirror` ; les relire ici en ferait une seconde
    déclaration, qui se tairait le jour où l'une des deux change.
    """
    try:
        return forge_mirror.sortants(config_file)
    except Exception:  # noqa: BLE001 - un relevé, pas le sujet
        return ()


def _porte_ou_a_regler(regle: bool, porte: str, a_regler: str) -> tuple:
    """Le couple (état, détail) d'un segment que le dépôt SAIT faire.

    Deux phrases distinctes, et non une phrase avec un « mais » : ce qui
    manque n'est pas un défaut du code, c'est un réglage de site, et les
    deux ne s'adressent pas à la même personne.
    """
    return (PORTE, porte) if regle else (A_REGLER, a_regler)


def lignes(vu: Releve) -> tuple:
    """Une ligne par segment de devstack. Fonction PURE.

    L'ordre suit celui du socle devstack, et non l'état : trier par avancement
    ferait bouger les lignes d'un lancement à l'autre, et l'œil perdrait ce
    qu'il avait appris à trouver au même endroit.
    """
    out = []

    n_backends = len(vu.backends_eprouves)
    out.append(
        Ligne(
            "host-base",
            PORTE if n_backends else ABSENT,
            f"{n_backends} {t('backends confronted with the real tool:')} "
            + ", ".join(vu.backends_eprouves),
            "script.vm.backend.PROVEN",
        )
    )

    out.append(
        Ligne(
            "sandbox-vm",
            PORTE,
            t("NAT: nothing is confined, and that is the point."),
            "script.posture.registry",
        )
    )

    for segment in ("ai-tools", "local-ai"):
        out.append(
            Ligne(
                segment,
                ABSENT,
                t(
                    "No AI gateway. The « ai-gateway » role exists in the"
                    " address book, and nothing opens it yet."
                ),
                "script.posture.allowlist",
            )
        )

    armees = [n for n in vu.postures_armees if n in ("connected", "paranoid")]
    out.append(
        Ligne(
            "connected-vm",
            PORTE if armees else ABSENT,
            f"{t('postures that write, load and arm rules:')} "
            + ", ".join(armees),
            "script.posture.rules.wants_rules",
        )
    )

    etat, detail = _porte_ou_a_regler(
        bool(vu.profils_forge),
        f"{t('forge profiles declared:')} " + ", ".join(vu.profils_forge),
        t(
            "The code drives Forgejo and Gitea; this site declares no"
            " profile yet."
        ),
    )
    out.append(Ligne("local-forge", etat, detail, "script.forge.profiles"))

    etat, detail = _porte_ou_a_regler(
        bool(vu.forge_canonique),
        f"{t('authority declared:')} {vu.forge_canonique}",
        t("The code carries the role and refuses two authorities; this")
        + t(" site declares none."),
    )
    out.append(Ligne("canonical-forge", etat, detail, "script.forge.profiles"))

    etat, detail = _porte_ou_a_regler(
        bool(vu.miroirs_sortants),
        f"{t('outbound mirrors declared:')} " + ", ".join(vu.miroirs_sortants),
        t("The code derives the direction and drives the push mirror;")
        + t(" this site declares no outbound one."),
    )
    out.append(Ligne("github-mirror", etat, detail, "script.forge.mirror"))

    for segment in ("openbao-master", "openbao-follower"):
        out.append(
            Ligne(
                segment,
                ABSENT,
                t(
                    "The vault is KeePassXC; no OpenBao, and no hardware"
                    " enclave."
                ),
                "script.todo.kdbx_manager",
            )
        )

    etat, detail = _porte_ou_a_regler(
        bool(vu.cibles_sauvegarde),
        f"{t('off-site targets declared:')} "
        + ", ".join(vu.cibles_sauvegarde),
        t(
            "The code ships and verifies the fingerprint there; this site"
            " declares no target yet."
        ),
    )
    out.append(
        Ligne(
            "sauvegarde-hors-instance",
            etat,
            detail,
            "script.remote" ".deploy_target",
        )
    )

    out.append(
        Ligne(
            "restore-test",
            PORTE,
            t(
                "The drill guard refuses to purge anything that is not a"
                " drill database, and names what it refused."
            ),
            "script.database.drill_guard",
        )
    )

    etat, detail = _porte_ou_a_regler(
        "local-only" in vu.postures_armees and bool(vu.profils_servant_le_web),
        f"{t('served profile:')} "
        + ", ".join(vu.profils_servant_le_web)
        + f" — {t('egress cut, port forward laid')}",
        t("No profile promises a web interface."),
    )
    out.append(Ligne("local-webui", etat, detail, "script.todo.vm_profiles"))

    return tuple(out)
