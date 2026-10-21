#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les paquets déjà installés que poetry.lock épingle à une autre version.

Lit sur l'entrée standard la sortie de « pip list --format=freeze » d'un venv,
et imprime « nom==version » pour chaque paquet installé que le verrou
épingle autrement.

Sert avant « poetry install » : Poetry, installé dans le venv qu'il remplit,
y amène ses propres dépendances. Quand le verrou en épingle une autre
version — virtualenv en tête —, Poetry la remplace PENDANT l'installation
parallèle, alors que ses ouvriers s'en servent pour créer les environnements
isolés des compilations : l'un d'eux trouve alors un fichier supprimé
(« No such file or directory: …/virtualenv/…/_virtualenv.py »). Aligner ces
paquets AVANT laisse Poetry ne rien avoir à remplacer en cours de route.

Un paquet présent plusieurs fois dans le verrou (versions distinctes selon
un marqueur de plateforme) est laissé à Poetry, seul à savoir laquelle
s'applique. Python 3.11+ (tomllib) : c'est l'interpréteur d'outillage qui le
lance, jamais celui d'Odoo.

« --contraintes FICHIER » y écrit en plus « nom==version » pour TOUS les
paquets du verrou à version unique. Passé à « pip install -c », il laisse
pip résoudre les dépendances des paquets alignés — une nouvelle version peut
en réclamer une nouvelle, que « --no-deps » laisserait manquer —, mais
seulement aux versions du verrou, marqueurs évalués par pip lui-même.
"""

import re
import sys
import tomllib


def normaliser(nom):
    """Nom de distribution comparable (PEP 503)."""
    return re.sub(r"[-_.]+", "-", nom).lower()


def versions_du_verrou(chemin):
    """{nom normalisé: version} des paquets à version UNIQUE dans le verrou."""
    with open(chemin, "rb") as fh:
        verrou = tomllib.load(fh)
    vues = {}
    for paquet in verrou.get("package", []):
        vues.setdefault(normaliser(paquet["name"]), set()).add(
            paquet["version"]
        )
    return {nom: v.pop() for nom, v in vues.items() if len(v) == 1}


def a_aligner(installes, verrou):
    """« nom==version » pour chaque paquet installé que le verrou épingle
    autrement. `installes` : lignes « nom==version » de pip freeze."""
    sortie = []
    for ligne in installes:
        nom, sep, version = ligne.strip().partition("==")
        if not sep:
            continue
        voulue = verrou.get(normaliser(nom))
        if voulue and voulue != version:
            sortie.append(f"{nom}=={voulue}")
    return sortie


def main():
    args = sys.argv[1:]
    contraintes = None
    if len(args) == 3 and args[0] == "--contraintes":
        contraintes, args = args[1], args[2:]
    if len(args) != 1:
        sys.exit(
            "usage : pip list --format=freeze | poetry_lock_align.py"
            " [--contraintes FICHIER] <poetry.lock>"
        )
    verrou = versions_du_verrou(args[0])
    if contraintes:
        with open(contraintes, "w", encoding="utf-8") as fh:
            for nom, version in sorted(verrou.items()):
                fh.write(f"{nom}=={version}\n")
    for ligne in a_aligner(sys.stdin, verrou):
        print(ligne)


if __name__ == "__main__":
    main()
