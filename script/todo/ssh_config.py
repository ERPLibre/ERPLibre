#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'est un nom de machine dans ~/.ssh/config, décidé en un seul endroit.

Trois lecteurs de ce fichier vivent dans ce dépôt — l'énumération des alias,
le menu de montage qui veut aussi l'adresse, et l'inventaire des entrées de
VM — et ils divergeaient sur la MÊME question. L'un comparait le mot-clé avec
la casse, un autre exigeait un espace là où une tabulation est légale, un
troisième laissait passer le motif nié. Un alias déclaré `host exo` était donc
vu par l'un et invisible aux autres, ce qui se lit comme une panne
intermittente de la découverte.

Le module ne lit aucun fichier et ne suit pas `Include` : il tranche une
ligne, rien de plus. Un alias déclaré dans un fichier inclus reste donc
invisible aux trois lecteurs, alors même que `ssh -G` le résoudrait — la
source est incomplète sans être fausse.
"""
from __future__ import annotations

import re

# Le mot-clé, suivi d'au moins un blanc. ssh_config ne distingue pas la casse
# de ses mots-clés, et sépare par espace OU tabulation. Le blanc est exigé
# sans quoi `HostName` serait lu comme une déclaration d'hôte.
DECLARATION = re.compile(r"^[ \t]*host[ \t]+", re.IGNORECASE)


def declared_names(line) -> list | None:
    """Les noms de machine d'une ligne « Host », ou None si ce n'en est pas une.

    Rend None pour toute autre ligne, et une liste — possiblement VIDE —
    quand la ligne est une déclaration. Distinguer les deux compte : `Host *`
    EST une déclaration qui ne nomme aucune machine, et un lecteur qui
    accumule un bloc doit clore le précédent malgré tout. Rendre `[]` dans
    les deux cas rattachait les directives d'un bloc générique au bloc
    précédent.

    Trois formes ne désignent aucune machine et sortent : les jokers `*` et
    `?`, qui décrivent une règle appliquée à plusieurs hôtes, et le motif NIÉ
    `!nom`, qui RETIRE un nom de l'ensemble que la ligne vient de décrire.
    Retenir un motif nié rend une cible dont le nom commence par `!`, que ssh
    ne résoudra jamais.
    """
    if not DECLARATION.match(line or ""):
        return None
    return [
        nom
        for nom in line.split()[1:]
        if "*" not in nom and "?" not in nom and not nom.startswith("!")
    ]
