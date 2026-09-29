#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les comptes de réseaux sociaux : description, préréglages, fichier.

`accounts.json` ne contient QUE ce qui n'est pas secret. Le jeton — ou le
mot de passe d'application — vit dans le coffre (`mail/secrets.py`) et le
fichier n'en garde qu'une référence. Même règle que pour le courriel, pour
la même raison : le fichier reste lisible et réparable sans devenir un
endroit d'où une fuite ferait mal.

Aucun IDENTIFIANT CLIENT n'est livré ici. Les trois plateformes offrent un
chemin où la personne obtient elle-même son jeton — Préférences ›
Développement chez Mastodon, un mot de passe d'application chez Bluesky,
une application enregistrée chez LinkedIn. Le dépôt n'a donc pas à porter
une identité d'application, qui serait publique dès le premier clone.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from script.todo.todo_i18n import t

SCHEMA_VERSION = 1

# Ce qu'une plateforme laisse faire, et rien de plus. C'est une CONSTATATION
# sur les API publiées, pas un réglage : le fil d'un membre LinkedIn ne se
# lit pas en libre-service — il faut `r_member_social`, accordé à quelques
# développeurs choisis, et l'API « Activity Feed » est dépréciée. Un compte
# LinkedIn a donc un fil vide par construction, et l'écran doit le dire
# plutôt que de laisser passer ça pour une panne.
CAPACITES = ("read", "write")

PRESETS: dict[str, dict] = {
    "mastodon": {
        "label": "Mastodon",
        # L'instance varie d'une personne à l'autre : c'est elle qui donne
        # l'hôte, il n'y a pas d'hôte par défaut qui vaille.
        "base_url": "",
        "capacites": ("read", "write"),
        "note_key": "social_preset_note_mastodon",
    },
    "bluesky": {
        "label": "Bluesky",
        # Le service par défaut du réseau. Un compte hébergé sur son propre
        # PDS remplace cette valeur.
        "base_url": "https://bsky.social",
        "capacites": ("read", "write"),
        "note_key": "social_preset_note_bluesky",
    },
    "linkedin": {
        "label": "LinkedIn",
        "base_url": "https://api.linkedin.com",
        # Publier seulement : voir le commentaire de `CAPACITES`.
        "capacites": ("write",),
        "note_key": "social_preset_note_linkedin",
    },
}


class SocialAccountError(Exception):
    """Compte impossible : champ manquant, valeur inconnue, fichier illisible."""


@dataclass
class SocialAccount:
    name: str
    handle: str
    platform: str
    secret_ref: str
    base_url: str = ""
    display_name: str = ""
    cache_mode: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise SocialAccountError(t("social_err_account_needs_name"))
        if (
            "/" in self.name
            or os.sep in self.name
            or self.name.startswith(".")
        ):
            # Le nom sert de nom de DOSSIER pour le cache : une barre
            # oblique y écrirait ailleurs que prévu, un point initial le
            # cacherait à qui vient inspecter.
            raise SocialAccountError(
                f"{t('social_err_invalid_account_name')} {self.name!r}"
            )
        if self.platform not in PRESETS:
            raise SocialAccountError(
                f"{t('social_err_unknown_platform')} {self.platform!r}"
                f" {t('mail_err_expected')} {tuple(PRESETS)})"
            )
        if self.cache_mode not in (None, "clear", "encrypted", "ephemeral"):
            raise SocialAccountError(
                f"{t('mail_err_unknown_cache_mode')} {self.cache_mode!r}"
            )
        if not self.base_url:
            self.base_url = PRESETS[self.platform]["base_url"]
        if not self.base_url:
            # Mastodon n'a pas d'hôte par défaut : sans instance, il n'y a
            # tout simplement pas de serveur à qui parler.
            raise SocialAccountError(
                f"{t('social_err_needs_base_url')} {self.platform!r}"
            )
        self.base_url = self.base_url.rstrip("/")

    @property
    def capacites(self) -> tuple:
        return PRESETS[self.platform]["capacites"]

    def peut_lire(self) -> bool:
        return "read" in self.capacites

    def peut_publier(self) -> bool:
        return "write" in self.capacites

    def cache_key_ref(self) -> str:
        """Référence de la clé du cache, distincte de celle du jeton.

        Deux références pour un compte : le secret de connexion et la clé
        du cache. Les confondre ferait qu'un jeton renouvelé rendrait le
        cache illisible.
        """
        return f"{self.secret_ref}/cache-key"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SocialAccount":
        try:
            return cls(
                name=d["name"],
                handle=d["handle"],
                platform=d["platform"],
                secret_ref=d["secret_ref"],
                base_url=d.get("base_url", ""),
                display_name=d.get("display_name", ""),
                cache_mode=d.get("cache_mode"),
                enabled=d.get("enabled", True),
            )
        except KeyError as exc:
            raise SocialAccountError(
                f"{t('social_err_account_missing_field')} {exc}"
            ) from exc


def accounts_path() -> Path:
    return Path(os.path.expanduser("~/.erplibre/social/accounts.json"))


def _prepare_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)


def _write_private(path: Path, text: str) -> None:
    """Écrit `text` dans un fichier créé en 0600 dès sa création.

    Écrire puis `chmod` laisserait le fichier — le jeton n'y est pas, mais
    `secret_ref` et les handles y sont — lisible à l'umask du process le
    temps entre les deux appels.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def account_from_preset(
    name: str,
    handle: str,
    platform: str,
    *,
    base_url: str = "",
    display_name: str = "",
    vault: str = "kdbx",
) -> SocialAccount:
    if platform not in PRESETS:
        raise SocialAccountError(
            f"{t('social_err_unknown_platform')} {platform!r}"
        )
    ref = (
        f"kdbx:ERPLibre/Social/{name}"
        if vault == "kdbx"
        else f"keyring:{name}"
    )
    return SocialAccount(
        name=name,
        handle=handle,
        platform=platform,
        secret_ref=ref,
        base_url=base_url,
        display_name=display_name,
    )


def load(path: Path | None = None) -> list[SocialAccount]:
    path = Path(path) if path else accounts_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise SocialAccountError(
            f"{path} {t('mail_err_not_valid_json')} {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise SocialAccountError(
            f"{path} {t('mail_err_should_contain_json_object')}"
        )
    # Un fichier d'une version future se lirait champ par champ, perdant en
    # silence ce que cette version ne connaît pas, puis se réécrirait amputé
    # par-dessus l'original. Refuser le rend réparable ; deviner le détruit.
    version = data.get("version", SCHEMA_VERSION)
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise SocialAccountError(
            f"{path} {t('social_err_accounts_from_the_future')}"
            f" {version} > {SCHEMA_VERSION}"
        )
    return [
        SocialAccount.from_dict(d)
        for d in data.get("accounts", [])
        if isinstance(d, dict)
    ]


def save(accounts: list[SocialAccount], path: Path | None = None) -> None:
    path = Path(path) if path else accounts_path()
    names = [a.name for a in accounts]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise SocialAccountError(
            f"{t('social_err_duplicate_account_names')} {sorted(duplicates)}"
        )
    _prepare_parent(path)
    payload = {
        "version": SCHEMA_VERSION,
        "accounts": [a.to_dict() for a in accounts],
    }
    _write_private(path, json.dumps(payload, ensure_ascii=False, indent=2))


def find(accounts: list[SocialAccount], name: str) -> SocialAccount | None:
    return next((a for a in accounts if a.name == name), None)
