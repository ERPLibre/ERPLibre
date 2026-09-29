#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le point d'entrée du paquet social : ouvrir l'écran, rapporter les fils.

C'est ici, et nulle part ailleurs dans le paquet, qu'un gestionnaire de
journal se branche. Les modules en dessous ne font qu'appeler leur logger :
poser un gestionnaire est le travail de L'APPLICATION, pas d'une
bibliothèque. Jamais vers la console non plus — Textual possède le terminal
pendant tout l'écran, et une ligne de journal qui s'y mêlerait corromprait
l'affichage.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import click

from script.todo.social import accounts as social_accounts
from script.todo.todo_i18n import t

# `True` une fois le journal branché : rouvrir le menu dans le même processus
# ne doit pas empiler un second gestionnaire, qui écrirait chaque ligne deux
# fois.
_LOG_CONFIGURED = False


def social_log_path() -> Path:
    """Le chemin du journal du paquet — SOURCE UNIQUE, pour que rien n'en
    dérive deux formules différentes."""
    return Path(os.path.expanduser("~/.erplibre")) / "social.log"


def _configure_social_logging() -> None:
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    chemin = social_log_path()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    poignee = logging.FileHandler(chemin)
    poignee.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    journal = logging.getLogger("script.todo.social")
    journal.addHandler(poignee)
    journal.setLevel(logging.INFO)
    # `todo.py` pose un gestionnaire sur le logger RACINE à l'import.
    # `propagate` valant `True` par défaut, chaque ligne du paquet y
    # remonterait AUSSI — donc sur le terminal que Textual possède, et dans
    # la sortie pointillée d'une suite de tests.
    journal.propagate = False
    _LOG_CONFIGURED = True


def secret_store_for(todo):
    """Le coffre du CLI : son kdbx s'il en a un, sinon le trousseau."""
    from script.todo.mail.secrets import SecretStore

    return SecretStore(
        kdbx_manager=getattr(todo, "kdbx_manager", None), use_keyring=True
    )


def _load_accounts() -> list:
    try:
        return social_accounts.load()
    except social_accounts.SocialAccountError as exc:
        print(exc)
        return []


def prompt_execute_social(todo) -> None:
    _configure_social_logging()
    while True:
        help_info = f"""{todo._menu_header()}
[1] {t("social_open_tui")}
[2] {t("social_sync_now")}
[0] {t("Back")}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            _open_tui(todo)
        elif status == "2":
            _sync_now(todo)
        else:
            print(t("Command not found !"))


def _open_tui(todo, base=None) -> None:
    from script.todo.social.tui import open_sessions, run_tui

    comptes = _load_accounts()
    if not comptes:
        print(t("social_no_account"))
        return
    sessions = open_sessions(comptes, secret_store_for(todo), base=base)
    try:
        run_tui(sessions=sessions, base=base)
    finally:
        for session in sessions:
            session.close()


def _sync_now(todo, base=None) -> None:
    """Rapporte les fils SANS écran, pour qu'un compte se vérifie depuis un
    script. Un compte qui échoue est nommé et n'empêche pas les autres."""
    from script.todo.social.tui import open_sessions, sync_session

    comptes = _load_accounts()
    if not comptes:
        print(t("social_no_account"))
        return
    sessions = open_sessions(comptes, secret_store_for(todo), base=base)
    try:
        for session in sessions:
            print(f"\n=== {session.account.name} ===")
            if session.error:
                print(f"  {session.error}")
                continue
            if not session.peut_lire():
                print(f"  {t('social_no_feed')}")
                continue
            try:
                print(f"  {t('social_sync_done')} {sync_session(session)}")
            except Exception as exc:
                print(f"  {exc}")
    finally:
        for session in sessions:
            session.close()
