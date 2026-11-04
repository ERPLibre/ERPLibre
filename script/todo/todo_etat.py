#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le bilan que le TODO affiche à son ouverture.

Chaque vérification est locale et ne touche pas au réseau : elle lit un
fichier ou lance une commande git qui répond en quelques millisecondes,
bornée par un délai. Aucune ne lève : une vérification qui échoue retire sa
ligne du bilan et n'empêche jamais le menu de s'ouvrir.
"""

import json
import os
import re
import subprocess

from script.todo.todo_i18n import t

DELAI_GIT = 3

# Les hooks que le dépôt fournit, et l'endroit où core.hooksPath doit pointer.
HOOKS_GIT = ("commit-msg", "pre-commit")
CHEMIN_HOOKS_GIT = os.path.join("script", "git", "hooks")

# Les versions d'Odoo installées et leur Python : l'état d'ERPLibre d'abord,
# la liste de .repo/ à défaut ; le catalogue donne le Python d'une version que
# ni l'un ni l'autre ne précise.
ETAT_ERPLIBRE = ".erplibre-state.json"
VERSIONS_INSTALLEES = os.path.join(".repo", "installed_odoo_version.txt")
CATALOGUE = os.path.join("conf", "supported_version_erplibre.json")
# Le Python du venv d'outillage (.venv.erplibre), distinct de celui d'Odoo.
PYTHON_OUTILLAGE = os.path.join("conf", "python-erplibre-version")

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


def _json(chemin):
    """Le contenu JSON d'un fichier, ou {} s'il est absent ou illisible."""
    try:
        with open(chemin, encoding="utf-8") as fh:
            donnees = json.load(fh)
    except (OSError, ValueError):
        return {}
    return donnees if isinstance(donnees, dict) else {}


def _cle_version(version):
    """« 18.0 » → (18, 0) : « 9.0 » se range sous « 18.0 », pas au-dessus."""
    return tuple(int(x) if x.isdigit() else 0 for x in version.split("."))


def versions_odoo(racine):
    """[(odoo, python, active)] : l'active d'abord, puis les autres versions
    installées, de la plus récente à la plus ancienne. python vaut "" quand
    rien ne le donne."""
    catalogue = {
        entree.get("odoo_version"): entree.get("python_version", "")
        for entree in _json(os.path.join(racine, CATALOGUE)).values()
        if isinstance(entree, dict)
    }
    installees = {}
    etat = _json(os.path.join(racine, ETAT_ERPLIBRE)).get("odoo_versions")
    if isinstance(etat, dict):
        for version, fiche in etat.items():
            if isinstance(fiche, dict) and fiche.get("installed"):
                installees[version] = fiche.get("python") or ""
    else:
        lignes = _lire(os.path.join(racine, VERSIONS_INSTALLEES)).splitlines()
        for ligne in lignes:
            version = ligne.strip().removeprefix("odoo")
            if version:
                installees[version] = ""
    versions = []
    active = _lire(os.path.join(racine, ".odoo-version"))
    if active:
        python = _lire(os.path.join(racine, ".python-odoo-version"))
        versions.append(
            (
                active,
                python or installees.get(active) or catalogue.get(active, ""),
                True,
            )
        )
    for version in sorted(
        set(installees) - {active}, key=_cle_version, reverse=True
    ):
        python = installees[version] or catalogue.get(version, "")
        versions.append((version, python, False))
    return versions


def lignes_versions(racine):
    """Les lignes de versions, sans les absentes.

    « ERPLibre 1.8.0 · Python 3.15.2 », le Python étant celui de
    l'outillage (.venv.erplibre), puis une ligne par version d'Odoo
    installée avec son Python — l'active marquée dès qu'il y en a d'autres.
    """
    lignes = []
    morceaux = []
    erplibre = version_erplibre(racine)
    if erplibre:
        morceaux.append(f"ERPLibre {erplibre}")
    outillage = _lire(os.path.join(racine, PYTHON_OUTILLAGE))
    if outillage:
        morceaux.append(f"Python {outillage}")
    if morceaux:
        lignes.append(" · ".join(morceaux))
    versions = versions_odoo(racine)
    for odoo, python, active in versions:
        ligne = f"Odoo {odoo}"
        if python:
            ligne += f" · Python {python}"
        if active and len(versions) > 1:
            ligne += f"  {t('(active)')}"
        lignes.append(ligne)
    return lignes


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
    for verification in (lignes_versions, ligne_hooks_git):
        try:
            sortie = verification(racine)
        except Exception:
            sortie = ""
        if isinstance(sortie, str):
            sortie = [sortie]
        lignes.extend(ligne for ligne in sortie if ligne)
    return lignes


def afficher(racine):
    for ligne in bilan(racine):
        print(f"   {ligne}")
