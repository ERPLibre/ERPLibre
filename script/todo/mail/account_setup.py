#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La logique d'ajout de compte et de mise en place du coffre, sans UI.

`menu._add_account` et `menu._ensure_kdbx` mêlaient cette logique — pas
triviale, elle annule l'écriture du secret si la sauvegarde du compte échoue
— à des `input()`/`getpass.getpass()`. Le CLI et le TUI ont chacun leur façon
de demander l'information, mais doivent appeler exactement le même code une
fois qu'ils l'ont : sinon les deux copies dérivent. Ce module ne connaît ni
`input`, ni Textual, ni aucune bibliothèque d'interface.
"""
from __future__ import annotations

import os

from script.todo.mail import accounts as mail_accounts
from script.todo.mail.accounts import AccountError
from script.todo.mail.secrets import SecretError, create_kdbx
from script.todo.todo_i18n import t

# Chemin proposé par défaut pour un kdbx nouvellement créé. `private/` est un
# dossier versionné, mais `private/.gitignore` y ignore déjà `*.kdbx` : c'est
# la convention du dépôt pour les fichiers de coffre.
DEFAULT_KDBX_PATH = "private/erplibre.kdbx"


def save_new_account(secret_store, accounts, account, password) -> None:
    """Écrit le mot de passe puis sauvegarde `accounts` (qui doit déjà
    contenir `account`, à la place voulue par l'appelant).

    Si la sauvegarde échoue, le secret est retiré du coffre avant que
    l'exception ne remonte : l'y laisser sous une référence qu'aucune
    configuration ne désigne en ferait un déchet invisible.
    """
    secret_store.set(account.secret_ref, password)
    try:
        mail_accounts.save(accounts)
    except (AccountError, OSError):
        try:
            secret_store.delete(account.secret_ref)
        except SecretError:
            pass
        raise


def kdbx_is_configured(config_file) -> bool:
    """Vrai si un kdbx est déjà désigné dans la configuration."""
    return bool(config_file.get_config_value(["kdbx", "path"]))


def create_vault(config_file, path: str, password: str) -> None:
    """Crée un nouveau kdbx à `path`, puis l'enregistre comme coffre actif."""
    create_kdbx(path, password)
    config_file.set_config_value(["kdbx", "path"], path)


def use_existing_vault(config_file, path: str) -> None:
    """Adopte un kdbx déjà présent sur disque comme coffre actif."""
    if not path or not os.path.isfile(path):
        raise SecretError(f"{t('mail_kdbx_path_not_found')} {path}")
    config_file.set_config_value(["kdbx", "path"], path)
