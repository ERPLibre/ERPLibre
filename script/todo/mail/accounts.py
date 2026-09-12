#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les comptes courriel : description, préréglages, fichier de config.

`accounts.json` ne contient QUE ce qui n'est pas secret. Le mot de passe vit
dans le coffre (voir `secrets.py`) et le fichier n'en garde qu'une référence.
Le fichier reste donc lisible, éditable à la main et réparable, sans devenir
un endroit d'où une fuite ferait mal.

Les préréglages `gmail`, `outlook` et `icloud` supposent un MOT DE PASSE
D'APPLICATION : l'authentification simple ne passe plus autrement chez ces
fournisseurs. C'est la limite assumée de la phase 1 ; la phase 2 apporte OAuth.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from script.todo.todo_i18n import t

# La v2 ajoute `auth` à chaque compte. Un fichier de v1 se relit sans rien
# perdre — le champ manquant vaut « password », ce qu'un compte de v1 faisait
# de toute façon.
SCHEMA_VERSION = 2
SECURITIES = ("ssl", "starttls", "none")
# « login » couvre le mot de passe du compte comme le mot de passe
# d'application : du point de vue du transport, c'est le même dialogue LOGIN.
# Le mot « password » est écarté À DESSEIN de cette valeur : un test vérifie
# qu'il n'apparaît NULLE PART dans `accounts.json`, garde-fou volontairement
# grossier contre un secret qui s'y glisserait, et une valeur portant ce mot
# le désarmerait pour de bon.
AUTHS = ("login", "oauth")

PRESETS: dict[str, dict] = {
    "gmail": {
        "label": "Google / Gmail",
        "imap": {"host": "imap.gmail.com", "port": 993, "security": "ssl"},
        "smtp": {
            "host": "smtp.gmail.com",
            "port": 587,
            "security": "starttls",
        },
        "sent_folder": "[Gmail]/Sent Mail",
        "app_password": True,
        "note_key": "mail_preset_note_gmail",
    },
    "outlook": {
        "label": "Microsoft / Outlook",
        "imap": {
            "host": "outlook.office365.com",
            "port": 993,
            "security": "ssl",
        },
        "smtp": {
            "host": "smtp.office365.com",
            "port": 587,
            "security": "starttls",
        },
        "sent_folder": "Sent Items",
        # Microsoft a retiré l'authentification simple d'IMAP : un mot de
        # passe d'application est de l'authentification simple, donc il est
        # refusé lui aussi. Le drapeau dit « ce fournisseur prend un mot de
        # passe d'application » — ici, il n'en prend plus aucun.
        "app_password": False,
        "note_key": "mail_preset_note_outlook",
    },
    "icloud": {
        "label": "Apple / iCloud",
        "imap": {"host": "imap.mail.me.com", "port": 993, "security": "ssl"},
        "smtp": {
            "host": "smtp.mail.me.com",
            "port": 587,
            "security": "starttls",
        },
        "sent_folder": "Sent Messages",
        "app_password": True,
        "note_key": "mail_preset_note_icloud",
    },
    "generic": {
        "label": "Serveur standard (IMAP/SMTP)",
        "imap": {"host": "", "port": 993, "security": "ssl"},
        "smtp": {"host": "", "port": 587, "security": "starttls"},
        "sent_folder": "Sent",
        "app_password": False,
        "note_key": "mail_preset_note_generic",
    },
}


class AccountError(Exception):
    """Configuration de compte invalide, illisible ou en conflit."""


@dataclass
class ServerConf:
    host: str
    port: int
    security: str
    user: str

    def __post_init__(self) -> None:
        if self.security not in SECURITIES:
            raise AccountError(
                f"{t('mail_err_unknown_security')} {self.security!r}"
                f" {t('mail_err_expected')} {SECURITIES})"
            )


@dataclass
class Account:
    name: str
    email: str
    imap: ServerConf
    smtp: ServerConf
    secret_ref: str
    display_name: str = ""
    preset: str = "generic"
    cache_mode: str | None = None
    sent_folder: str = "Sent"
    enabled: bool = True
    auth: str = "login"

    def __post_init__(self) -> None:
        if not self.name:
            raise AccountError(t("mail_err_account_needs_name"))
        if (
            "/" in self.name
            or os.sep in self.name
            or self.name.startswith(".")
        ):
            raise AccountError(
                f"{t('mail_err_invalid_account_name')} {self.name!r}"
                f" {t('mail_err_account_name_reason')}"
            )
        if self.cache_mode not in (None, "clear", "encrypted", "ephemeral"):
            raise AccountError(
                f"{t('mail_err_unknown_cache_mode')} {self.cache_mode!r}"
            )
        if self.auth not in AUTHS:
            raise AccountError(
                f"{t('mail_err_unknown_auth')} {self.auth!r}"
                f" {t('mail_err_expected')} {AUTHS})"
            )

    def cache_key_ref(self) -> str:
        """Référence de la clé de chiffrement, distincte du mot de passe."""
        return f"{self.secret_ref}/cache-key"

    def refresh_token_ref(self) -> str:
        """Référence du jeton OAuth, À CÔTÉ du mot de passe et non dessus.

        Trois références distinctes pour un compte : le secret de connexion,
        la clé du cache, le jeton. Les confondre ferait qu'un compte repassé
        au mot de passe perdrait le sien, sans moyen de le retrouver.
        """
        return f"{self.secret_ref}/oauth-token"

    def from_header(self) -> str:
        return (
            f"{self.display_name} <{self.email}>"
            if self.display_name
            else self.email
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        try:
            return cls(
                name=d["name"],
                email=d["email"],
                imap=ServerConf(**d["imap"]),
                smtp=ServerConf(**d["smtp"]),
                secret_ref=d["secret_ref"],
                display_name=d.get("display_name", ""),
                preset=d.get("preset", "generic"),
                cache_mode=d.get("cache_mode"),
                sent_folder=d.get("sent_folder", "Sent"),
                enabled=d.get("enabled", True),
                auth=d.get("auth", "login"),
            )
        except (KeyError, TypeError) as exc:
            raise AccountError(
                f"{t('mail_err_account_unreadable')} {exc}"
            ) from exc


def accounts_path() -> Path:
    return Path(os.path.expanduser("~/.erplibre/mail/accounts.json"))


def _prepare_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)


def _write_private(path: Path, text: str) -> None:
    """Écrit `text` dans un fichier créé en 0600 dès sa création.

    Écrire puis `chmod` laisserait le fichier — mot de passe absent, mais
    `secret_ref` et adresses y sont — lisible à l'umask du process le temps
    entre les deux appels. `os.open` avec le mode dès l'ouverture ferme cette
    fenêtre ; le `chmod` qui suit corrige aussi un fichier déjà là écrit par
    un umask permissif.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def account_from_preset(
    name: str,
    email: str,
    preset_key: str,
    *,
    user: str | None = None,
    display_name: str = "",
    vault: str = "kdbx",
    auth: str = "login",
) -> Account:
    preset = PRESETS.get(preset_key)
    if preset is None:
        raise AccountError(f"{t('mail_err_unknown_preset')} {preset_key!r}")
    login = user or email
    ref = (
        f"kdbx:ERPLibre/Mail/{name}" if vault == "kdbx" else f"keyring:{name}"
    )
    return Account(
        name=name,
        email=email,
        display_name=display_name,
        preset=preset_key,
        imap=ServerConf(user=login, **preset["imap"]),
        smtp=ServerConf(user=login, **preset["smtp"]),
        secret_ref=ref,
        cache_mode=None,
        sent_folder=preset["sent_folder"],
        enabled=True,
        auth=auth,
    )


def load(path: Path | None = None) -> list[Account]:
    path = Path(path) if path else accounts_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise AccountError(
            f"{path} {t('mail_err_not_valid_json')} {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise AccountError(
            f"{path} {t('mail_err_should_contain_json_object')}"
        )
    # La version était ÉCRITE sans jamais être relue. Un fichier d'une
    # version future se lisait alors champ par champ, perdant en silence ce
    # que cette version ne connaît pas — puis se réécrivait amputé par-dessus
    # l'original. Refuser rend le fichier réparable ; deviner le détruit.
    version = data.get("version", SCHEMA_VERSION)
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise AccountError(
            f"{path} {t('mail_err_accounts_from_the_future')}"
            f" {version} > {SCHEMA_VERSION}"
        )
    return [Account.from_dict(d) for d in data.get("accounts", [])]


def save(accounts: list[Account], path: Path | None = None) -> None:
    path = Path(path) if path else accounts_path()
    names = [a.name for a in accounts]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise AccountError(
            f"{t('mail_err_duplicate_account_names')} {sorted(duplicates)}"
        )
    _prepare_parent(path)
    payload = {
        "version": SCHEMA_VERSION,
        "default_account": names[0] if names else None,
        "accounts": [a.to_dict() for a in accounts],
    }
    _write_private(path, json.dumps(payload, ensure_ascii=False, indent=2))


def find(accounts: list[Account], name: str) -> Account | None:
    return next((a for a in accounts if a.name == name), None)


def write_template(path: Path | None = None, force: bool = False) -> Path:
    """Écrit un accounts.json d'exemple, un compte désactivé par préréglage.

    JSON n'a pas de commentaires : les explications passent par des clés
    `_comment`, que `Account.from_dict` ignore.
    """
    path = Path(path) if path else accounts_path()
    if path.exists() and not force:
        raise AccountError(f"{path} {t('mail_err_already_exists_relaunch')}")
    examples = []
    for key, preset in PRESETS.items():
        acc = account_from_preset(
            f"exemple-{key}", f"vous@exemple.ca", key
        ).to_dict()
        acc["enabled"] = False
        acc["_comment"] = t(preset["note_key"])
        examples.append(acc)
    payload = {
        "version": SCHEMA_VERSION,
        "_comment": (
            "Modèle ERPLibre. Aucun mot de passe ici : `secret_ref` pointe"
            " vers le coffre. Passez `enabled` à true une fois rempli."
            " `cache_mode` à null hérite du réglage général."
        ),
        "default_account": None,
        "accounts": examples,
    }
    _prepare_parent(path)
    _write_private(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return path
