#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Disponibilité de Textual, et installation à la demande.

Les écrans TUI du CLI TODO (télémétrie, dashboard d'installation, formulaire
de déploiement, reprise de migration) dépendent tous de Textual. Sans lui, ils
se contentaient d'un « Installez textual (pip) » qui laissait l'utilisateur
chercher la bonne commande pour son système.

`ensure(...)` répond à la question à sa place : Textual est-il là, et sinon
veut-on l'installer maintenant ?

Module à part, et non une méthode de `TODO` : `todo_upgrade` en a besoin
aussi, et il est importé PAR `todo` — le mettre là créerait un cycle.
"""
from __future__ import annotations

import importlib
import importlib.util  # « import importlib » seul n'expose PAS .util
import subprocess
import sys

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


def available() -> bool:
    """Textual est-il importable maintenant ?"""
    return importlib.util.find_spec("textual") is not None


def in_venv() -> bool:
    """Vrai si l'interpréteur courant est dans un environnement virtuel."""
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def install_command():
    """Commande d'installation adaptée à l'interpréteur QUI TOURNE.

    C'est lui qui devra importer Textual, pas le python du système : viser
    `sys.executable` évite d'installer un paquet distribution que le venv ne
    verrait jamais. Hors venv, « --user » contourne le refus des
    distributions dont l'environnement est « externally managed » (PEP 668).
    """
    cmd = [sys.executable, "-m", "pip", "install", "textual"]
    if not in_venv():
        cmd.insert(4, "--user")
    return cmd


def ensure(prompt=True, ask=input):
    """Textual disponible ? Sinon proposer de l'installer. Renvoie un booléen.

    `prompt=False` se contente de constater — pour les appels qui ne peuvent
    pas poser de question. `ask` est injectable pour les tests.
    """
    if available():
        return True
    print(f"\n⚠  {t('Textual is required for this screen.')}")
    if not prompt:
        return False
    answer = ask(t("Install it now? (Y/n): ")).strip().lower()
    if answer and answer not in ("y", "yes", "o", "oui"):
        return False

    cmd = install_command()
    print(f"  {t('Will execute:')} {' '.join(cmd)}")
    try:
        status = subprocess.run(cmd).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  ⚠ {exc}")
        return False

    # Un import négatif est mémorisé : sans purge du cache, Textual resterait
    # « absent » pour ce processus alors qu'il vient d'être installé.
    importlib.invalidate_caches()
    if available():
        print(f"✅ {t('Textual is installed.')}")
        return True
    print(f"  ⚠ {t('Installation finished but textual is still missing.')}")
    if status:
        print(f"    {t('pip exited with')} {status}")
    print(f"    {t('Your distribution may package it as python3-textual.')}")
    return False
