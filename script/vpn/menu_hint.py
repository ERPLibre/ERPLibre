#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le chemin de menu où l'on règle un VPN, composé et non recopié.

DEUX MESSAGES L'ÉCRIVAIENT À LA MAIN, et tous deux disaient
« Déploiement » là où le fil d'Ariane affiche « Deploy » : ses libellés
partent tels quels, sans passer par la traduction. Quelqu'un qui cherchait
« Déploiement » dans le menu ne le trouvait pas.

ICI ET PAS DANS CHACUN DES DEUX : une seconde copie diverge de la première
au premier renommage, ce qui est exactement ce qui vient d'arriver.

L'IMPORT EST DIFFÉRÉ. Le menu importe ce paquet ; l'importer en retour au
chargement fermerait le cycle. Dans un message affiché une fois, le coût
ne se voit pas, et le cycle, lui, casserait tout.
"""

from __future__ import annotations

MENUS = (
    "run",
    "prompt_execute",
    "prompt_execute_deploy",
    "prompt_execute_vpn",
)


def chemin_vpn() -> str:
    """« TODO › Execute › Deploy › VPN », depuis la table des menus.

    Lève si un de ces menus quitte la table : un chemin qui ne mène nulle
    part se découvre alors à l'épreuve, et non devant quelqu'un qui le
    tape.
    """
    from script.todo.todo import TODO

    return TODO.menu_path(*MENUS)
