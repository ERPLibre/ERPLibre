#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'environnement de lecture des fichiers externes, posé à la demande.

Excel et Access exigent des bibliothèques qui ne sont dans aucun venv du
dépôt : `.venv.erplibre` porte l'outillage du CLI, le venv Odoo porte celui
d'Odoo, et charger l'un ou l'autre de ces lecteurs les mélangerait à un
sujet qui n'est pas le leur. D'où un venv dédié, bâti au premier besoin.

Les formats en pur stdlib n'en ont PAS besoin, et c'est ce que
`available()` et `engine_python()` tiennent à la place des appelants : un
CSV ne doit jamais déclencher la construction d'un venv.

La pose d'un paquet SYSTÈME ne se réécrit pas ici : `todo_install` la fait
déjà pour les quatre familles, et il est testé. On l'appelle.
"""

from __future__ import annotations

import os
import subprocess
import sys

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


try:
    from script.todo import todo_install
except Exception:  # pragma: no cover - repli hors dépôt
    todo_install = None

NOM_VENV = ".venv.todo.external_data"
REQUIREMENTS = os.path.join("requirement", "todo_external_data.txt")

# Ce que chaque format exige d'importable. Les formats absents de cette
# table sont en pur stdlib et ne demandent rien.
IMPORTS_PAR_FORMAT = {
    "xlsx": ("openpyxl",),
    "xls": ("xlrd",),
    "access": ("access_parser",),
}

# Les formats servis par l'interpréteur du CLI, sans venv.
FORMATS_STDLIB = ("csv", "json", "xml", "macros")

# mdbtools rend les requêtes enregistrées d'une base Access lisibles.
# PAS d'entrée `pacman` : le paquet n'est pas dans les dépôts officiels
# d'Arch — seulement l'AUR — et `install_command` doit alors rendre None
# plutôt qu'une commande qui échoue APRÈS le mot de passe sudo.
PAQUETS_ACCESS = {
    "apt-get": ["mdbtools"],
    "dnf": ["mdbtools"],
    "zypper": ["mdbtools"],
}


def racine() -> str:
    """La racine du dépôt, quel que soit le répertoire courant."""
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )


def venv_path() -> str:
    return os.path.join(racine(), NOM_VENV)


def python_path() -> str | None:
    """L'interpréteur du venv dédié, ou None s'il n'existe pas."""
    candidat = os.path.join(venv_path(), "bin", "python")
    return candidat if os.path.isfile(candidat) else None


def engine_python(fmt: str | None = None) -> str:
    """L'interpréteur qui servira ce format.

    `sys.executable` pour les formats en pur stdlib — le moteur s'y importe
    déjà, ses imports tiers étant paresseux — et en repli quand le venv
    dédié n'existe pas encore, pour que l'appelant obtienne toujours un
    chemin exécutable plutôt qu'un None à tester.
    """
    if fmt in FORMATS_STDLIB:
        return sys.executable
    return python_path() or sys.executable


def _importable_par(interpreteur: str, module: str) -> bool:
    try:
        acheve = subprocess.run(
            [interpreteur, "-c", f"import {module}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        return acheve.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def available(fmt: str | None = None) -> bool:
    """Ce format est-il lisible ici, maintenant ?

    Vrai d'office pour les formats en pur stdlib : exiger un venv pour lire
    un CSV ferait construire un environnement pour rien.
    """
    if fmt in FORMATS_STDLIB:
        return True
    interpreteur = python_path()
    if not interpreteur:
        return False
    modules = IMPORTS_PAR_FORMAT.get(fmt) if fmt else ("openpyxl",)
    return all(_importable_par(interpreteur, m) for m in modules or ())


def capabilities() -> dict:
    """Format -> lisible. Pour l'entrée « Que sait lire cette machine ? »."""
    etat = {nom: True for nom in FORMATS_STDLIB}
    for fmt in IMPORTS_PAR_FORMAT:
        etat[fmt] = available(fmt)
    etat["xlsb"] = False
    return etat


def create(ask=input, executeur=None) -> bool:
    """Bâtir le venv puis y poser les requirements. Booléen.

    La commande s'affiche AVANT la question : on approuve ce qu'on a lu.
    """
    cible = venv_path()
    requirements = os.path.join(racine(), REQUIREMENTS)
    if not os.path.isfile(requirements):
        print(f"  ⚠ {t('Not readable: check the permissions.')}")
        print(f"    {requirements}")
        return False

    creation = [sys.executable, "-m", "venv", cible]
    print(f"  {t('Will execute:')} {' '.join(creation)}")
    print(
        f"  {t('Will execute:')} {os.path.join(cible, 'bin', 'pip')}"
        f" install -r {REQUIREMENTS}"
    )
    if not _oui(ask(t("Create it now? (Y/n): "))):
        print(t("Nothing to do."))
        return False

    if not python_path():
        code = _lancer(creation, executeur)
        if code:
            print(f"  ⚠ {t('python -m venv exited with')} {code}")
            return False
    pip = os.path.join(cible, "bin", "pip")
    code = _lancer([pip, "install", "-r", requirements], executeur)
    if code:
        print(f"  ⚠ {t('pip exited with')} {code}")
    if available("xlsx"):
        print(f"✅ {t('The environment is ready.')}")
        return True
    print(f"  ⚠ {t('Creation finished but the libraries are still missing.')}")
    return False


def _lancer(commande, executeur=None) -> int:
    if executeur is not None:
        return executeur(commande)
    try:
        return subprocess.run(commande).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  ⚠ {exc}")
        return 1


def _oui(reponse) -> bool:
    """« Défaut oui » : la réponse vide accepte."""
    valeur = str(reponse or "").strip().lower()
    return valeur == "" or valeur in ("y", "yes", "o", "oui")


def ensure(fmt: str, prompt: bool = True, ask=input) -> bool:
    """Le format est-il lisible ? Sinon, proposer d'y remédier.

    `prompt=False` se contente de constater — pour les appels qui ne
    peuvent pas poser de question.
    """
    if available(fmt):
        return True
    print(
        f"\n⚠ {t('A dedicated environment is required to read this format.')}"
    )
    if not prompt:
        return False
    return create(ask=ask)


def system_packages_cmd():
    """La commande qui pose `mdbtools`, ou None si personne ne le connaît.

    Un simple passe-plat vers `todo_install`, qui décide déjà de la famille
    par l'ID de /etc/os-release avant le PATH. Écrire une cascade de plus
    serait refaire le défaut que ce module a supprimé.
    """
    if todo_install is None:  # pragma: no cover - hors dépôt
        return None
    return todo_install.install_command(PAQUETS_ACCESS)
