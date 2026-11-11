#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Écarts entre un venv et un fichier d'exigences pip, sans lock.

Le venv de l'outillage s'installe depuis
requirement/erplibre_require-ments.txt, dont presque rien n'est épinglé :
il n'y a pas de version attendue à comparer, seulement des bornes. Ce
script dit donc :

- les exigences manquantes : aucune distribution installée ne les porte ;
- les exigences hors bornes : installées, mais à une version que leur
  spécificateur refuse (« black==26.10.1 » quand 25.1.0 est là) ;
- les paquets de trop : installés, mais qu'aucune exigence ne demande, ni
  directement ni par les dépendances déclarées des paquets demandés,
  extras compris. pip, setuptools et wheel n'y figurent jamais : ils
  outillent le venv lui-même.

Il tourne avec l'interpréteur DU VENV examiné : les marqueurs
(« python_version », « sys_platform ») s'évaluent pour lui, et
importlib.metadata y lit ses distributions. Il lui faut `packaging`, que
l'outillage installe en premier. Sortie : un objet JSON sur stdout ;
code 2 si le fichier ou `packaging` manque.

    <venv>/bin/python script/poetry/venv_requirements_drift.py <exigences>
"""

import importlib.metadata as metadata
import json
import os
import sys

OUTILS_DU_VENV = {"pip", "setuptools", "wheel"}


def lire_exigences(chemin, vus=None):
    """Les lignes d'exigence de `chemin`, « -r autre.txt » suivi, sans
    commentaires ni options pip."""
    vus = vus if vus is not None else set()
    chemin = os.path.abspath(chemin)
    if chemin in vus:
        return []
    vus.add(chemin)
    lignes = []
    with open(chemin, encoding="utf-8") as fh:
        for brute in fh:
            ligne = brute.split(" #", 1)[0].strip()
            if not ligne or ligne.startswith("#"):
                continue
            if ligne.startswith(("-r ", "--requirement ")):
                inclus = ligne.split(None, 1)[1]
                lignes += lire_exigences(
                    os.path.join(os.path.dirname(chemin), inclus), vus
                )
            elif not ligne.startswith("-"):
                lignes.append(ligne)
    return lignes


def analyser(lignes, distributions=None):
    """{« manquantes », « hors_bornes », « de_trop », « exigences »} pour
    les `lignes` d'exigence face aux `distributions` installées."""
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name

    if distributions is None:
        distributions = list(metadata.distributions())
    installees = {}
    for dist in distributions:
        nom = dist.metadata["Name"]
        if nom:
            installees.setdefault(canonicalize_name(nom), dist)

    manquantes, hors_bornes, illisibles = [], [], []
    a_voir = []
    for ligne in lignes:
        try:
            exigence = Requirement(ligne)
        except InvalidRequirement:
            illisibles.append(ligne)
            continue
        if exigence.marker and not exigence.marker.evaluate():
            continue
        nom = canonicalize_name(exigence.name)
        dist = installees.get(nom)
        if dist is None:
            manquantes.append(ligne)
            continue
        version = dist.version
        if exigence.specifier and not exigence.specifier.contains(
            version, prereleases=True
        ):
            hors_bornes.append({"exigence": ligne, "installee": version})
        a_voir.append((nom, frozenset(exigence.extras)))

    # Tout ce que les exigences tirent, par les dépendances déclarées des
    # distributions installées, extras demandés compris.
    tirees = set()
    while a_voir:
        nom, extras = a_voir.pop()
        if (nom, extras) in tirees:
            continue
        tirees.add((nom, extras))
        dist = installees.get(nom)
        if dist is None:
            continue
        for texte in dist.requires or []:
            try:
                dependance = Requirement(texte)
            except InvalidRequirement:
                continue
            if dependance.marker:
                contextes = [{"extra": e} for e in extras] or [{"extra": ""}]
                if not any(dependance.marker.evaluate(c) for c in contextes):
                    continue
            a_voir.append(
                (
                    canonicalize_name(dependance.name),
                    frozenset(dependance.extras),
                )
            )
    noms_tires = {nom for nom, _extras in tirees}
    de_trop = sorted(
        (installees[nom].metadata["Name"], installees[nom].version)
        for nom in installees
        if nom not in noms_tires and nom not in OUTILS_DU_VENV
    )
    return {
        "exigences": len(lignes),
        "manquantes": manquantes,
        "hors_bornes": hors_bornes,
        "illisibles": illisibles,
        "de_trop": [list(paire) for paire in de_trop],
    }


def main(argv):
    if len(argv) != 1 or not os.path.isfile(argv[0]):
        print(json.dumps({"erreur": "requirements file not found"}))
        return 2
    try:
        import packaging  # noqa: F401
    except ImportError:
        print(
            json.dumps({"erreur": "packaging is not installed in this venv"})
        )
        return 2
    print(json.dumps(analyser(lire_exigences(argv[0]))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
