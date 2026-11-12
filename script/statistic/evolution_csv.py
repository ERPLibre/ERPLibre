#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Exporter en CSV les statistiques de show_evolution_module.py.

Chaque fichier « evolution_modules*.json » du dossier des clones devient
un CSV du même nom, à côté de lui, au format long que lit un tableur :
une rangée par (date, dépôt, version) avec le nombre de modules. Le dépôt
« ALL » porte le total de l'année pour chaque version ; la version
« unique » porte les modules uniques, toutes versions confondues. Le
détail par dépôt n'existe que pour une passe qui l'a enregistré.

    evolution_csv.py [DOSSIER]
"""

import csv
import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.statistic import evolution_tui  # noqa: E402

ENTETES = ["date", "repository", "version", "modules"]
TOUS = "ALL"
UNIQUE = "unique"


def rangees(donnees):
    """Les rangées du CSV de `donnees`, sans l'en-tête : par année, le
    total par version, les uniques, puis chaque dépôt par version."""
    res = []
    for annee in donnees.get("annees") or []:
        date = annee.get("date") or ""
        for version, nombre in (annee.get("par_version") or {}).items():
            res.append([date, TOUS, version, nombre])
        res.append([date, TOUS, UNIQUE, annee.get("uniques", 0)])
        for depot, versions in (annee.get("par_depot") or {}).items():
            for version, nombre in versions.items():
                res.append([date, depot, version, nombre])
    return res


def exporter(dossier):
    """Écrit le CSV de chaque jeu de `dossier` ; rend leurs chemins. Le
    fichier passe par un nom provisoire renommé, comme le JSON."""
    chemins = []
    for chemin_json, donnees in evolution_tui.lire_jeux(dossier):
        chemin = os.path.splitext(chemin_json)[0] + ".csv"
        provisoire = f"{chemin}.{os.getpid()}.tmp"
        with open(provisoire, "w", encoding="utf-8", newline="") as fh:
            ecrivain = csv.writer(fh)
            ecrivain.writerow(ENTETES)
            ecrivain.writerows(rangees(donnees))
        os.replace(provisoire, chemin)
        chemins.append(chemin)
    return chemins


if __name__ == "__main__":
    from script.statistic.show_evolution_module import CACHE_CLONE_PATH

    ecrits = exporter(sys.argv[1] if len(sys.argv) > 1 else CACHE_CLONE_PATH)
    for ecrit in ecrits:
        print(ecrit)
    if not ecrits:
        print("No module statistics yet.", file=sys.stderr)
    raise SystemExit(0 if ecrits else 1)
