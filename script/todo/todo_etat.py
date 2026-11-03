#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le bilan que le TODO affiche à son ouverture.

Chaque vérification est locale et ne touche pas au réseau : elle lit un
fichier ou lance une commande git qui répond en quelques millisecondes,
bornée par un délai. Aucune ne lève : une vérification qui échoue retire sa
ligne du bilan et n'empêche jamais le menu de s'ouvrir.
"""

import os
import re
import subprocess

from script.todo.todo_i18n import t

DELAI_GIT = 3

# Les hooks que le dépôt fournit, et l'endroit où core.hooksPath doit pointer.
HOOKS_GIT = ("commit-msg", "pre-commit")
CHEMIN_HOOKS_GIT = os.path.join("script", "git", "hooks")

# « v1.8.0 », ou « v1.8.0-391-g48722e8c » quand des commits suivent le tag.
RE_DESCRIBE = re.compile(r"^v?(\d+\.\d+\.\d+)(?:-(\d+)-g([0-9a-f]+))?$")
# Le premier titre de version publiée du CHANGELOG, « ## [1.8.0] - … ».
RE_CHANGELOG = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.M)

OK = "✅"
ALERTE = "⚠️ "


def _git(racine, *args):
    """La sortie de `git -C racine args`, ou None si git échoue."""
    try:
        sortie = subprocess.run(
            ["git", "-C", racine, *args],
            capture_output=True,
            text=True,
            timeout=DELAI_GIT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if sortie.returncode:
        return None
    return sortie.stdout.strip()


def _lire(chemin):
    """Le contenu d'un fichier, sans espaces autour ; "" s'il est illisible."""
    try:
        with open(chemin, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def version_erplibre(racine):
    """La version d'ERPLibre du checkout, ou "" si rien ne la donne.

    `git describe` donne le dernier tag de version, suivi du nombre de commits
    qui le suivent et du commit courant : « 1.8.0 +391 (48722e8c) ». Sans
    historique git ni tag, comme dans une archive ou un clone superficiel,
    la première version publiée du CHANGELOG la remplace.
    """
    decrit = _git(racine, "describe", "--tags", "--match", "v[0-9]*")
    trouve = RE_DESCRIBE.match(decrit or "")
    if trouve:
        version, ecart, commit = trouve.groups()
        if ecart and ecart != "0":
            return f"{version} +{ecart} ({commit})"
        return version
    journal = _lire(os.path.join(racine, "CHANGELOG.md"))
    trouve = RE_CHANGELOG.search(journal)
    return trouve.group(1) if trouve else ""


def ligne_versions(racine):
    """« ERPLibre 1.8.0 · Odoo 18.0 · Python 3.12.16 », sans les absents."""
    morceaux = []
    erplibre = version_erplibre(racine)
    if erplibre:
        morceaux.append(f"ERPLibre {erplibre}")
    odoo = _lire(os.path.join(racine, ".odoo-version"))
    if odoo:
        morceaux.append(f"Odoo {odoo}")
    python = _lire(os.path.join(racine, ".python-odoo-version"))
    if python:
        morceaux.append(f"Python {python}")
    return " · ".join(morceaux)


def ligne_hooks_git(racine):
    """L'état des hooks git du checkout, une ligne avec son icône.

    Les hooks ne tournent que si core.hooksPath pointe sur le dossier du
    dépôt ET si chaque hook porte le bit d'exécution : git saute sans rien
    dire un hook qui ne l'a pas. "" hors d'un checkout git, où la question ne
    se pose pas.
    """
    if _git(racine, "rev-parse", "--git-dir") is None:
        return ""
    chemin = _git(racine, "config", "--get", "core.hooksPath")
    if not chemin:
        return f"{ALERTE} {t('Git hooks missing: Execute › Git › Settings')}"
    if os.path.normpath(chemin) != CHEMIN_HOOKS_GIT:
        return f"{ALERTE} {t('Git hooks point elsewhere: ')}{chemin}"
    absolu = os.path.join(racine, CHEMIN_HOOKS_GIT)
    inertes = [
        hook
        for hook in HOOKS_GIT
        if not os.access(os.path.join(absolu, hook), os.X_OK)
    ]
    if inertes:
        return (
            f"{ALERTE} {t('Git hooks not executable: ')}{', '.join(inertes)}"
        )
    return f"{OK} {t('Git hooks installed')}"


def bilan(racine):
    """Les lignes du bilan d'ouverture, dans l'ordre d'affichage."""
    lignes = []
    for verification in (ligne_versions, ligne_hooks_git):
        try:
            ligne = verification(racine)
        except Exception:
            ligne = ""
        if ligne:
            lignes.append(ligne)
    return lignes


def afficher(racine):
    for ligne in bilan(racine):
        print(f"   {ligne}")
