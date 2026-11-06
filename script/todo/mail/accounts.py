#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les comptes courriel : description, préréglages, fichier de config.

`accounts.json` ne contient QUE ce qui n'est pas secret. Le mot de passe vit
dans le coffre (voir `secrets.py`) et le fichier n'en garde qu'une référence.
Le fichier reste donc lisible, éditable à la main et réparable, sans devenir
un endroit d'où une fuite ferait mal.

Le fichier porte aussi, par compte, les empreintes de certificats TLS
épinglées (`tls_pins`) : des données publiques, que seul un geste humain
pose ou retire (`pin_certificate`, `unpin_certificate`). Une écriture
remplace le fichier d'un coup, sous un verrou de fichier, et garde les
épingles du disque : une liste lue avant une saisie ne perd ni ne
ressuscite une épingle posée ou retirée entre-temps.

Les préréglages `gmail`, `outlook` et `icloud` supposent un MOT DE PASSE
D'APPLICATION : l'authentification simple ne passe plus autrement chez ces
fournisseurs. C'est la limite assumée de la phase 1 ; la phase 2 apporte OAuth.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

from script.todo.mail import _core_path  # noqa: F401

# isort: split
from erplibre_mail_core import tls

from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

# La v2 ajoute `auth` à chaque compte, la v3 `signature`. Un fichier plus
# ancien se relit sans rien perdre : le champ manquant prend son défaut, qui
# est ce que faisait la version qui l'ignorait.
SCHEMA_VERSION = 3
SECURITIES = ("ssl", "starttls", "none")
# « login » couvre le mot de passe du compte comme le mot de passe
# d'application : du point de vue du transport, c'est le même dialogue LOGIN.
# Le mot « password » est écarté À DESSEIN de cette valeur : un test vérifie
# qu'il n'apparaît NULLE PART dans `accounts.json`, garde-fou volontairement
# grossier contre un secret qui s'y glisserait, et une valeur portant ce mot
# le désarmerait pour de bon.
AUTHS = ("login", "oauth")
# Le verrou des écritures d'`accounts.json`, à côté du fichier, et l'attente
# au plus d'un geste qui écrit pendant qu'un autre processus écrit.
ACCOUNTS_LOCK_NAME = "accounts.lock"
ACCOUNTS_LOCK_WAIT_S = 5.0

# Les deux préréglages Microsoft passent par le même point de service : le
# point « common » sert les comptes personnels comme les locataires, et un
# seul enregistrement d'application couvre donc les deux.
_OAUTH_MICROSOFT = {
    "auth_url": (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    ),
    "token_url": (
        "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    ),
    # Trois portées : lire, envoyer, et le droit de rafraîchir sans
    # redemander le consentement. Sans `offline_access`, il n'y a pas de
    # jeton de rafraîchissement du tout.
    "scope": (
        "https://outlook.office.com/IMAP.AccessAsUser.All"
        " https://outlook.office.com/SMTP.Send offline_access"
    ),
}

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
        # Les points de service sont publics et stables ; l'IDENTITÉ du
        # client, elle, n'est pas livrée ici — voir `oauth.settings_for`.
        "oauth": {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            # La seule portée qui ouvre IMAP et SMTP. Google la classe
            # « restreinte » : une application publiée qui la demande passe
            # par sa vérification.
            "scope": "https://mail.google.com/",
        },
    },
    # Les deux mondes Microsoft partagent leur hôte IMAP et PAS leur hôte
    # d'envoi : un préréglage unique en servirait un sur deux, et l'autre
    # échouerait à l'envoi seulement — après avoir relevé le courrier, donc
    # sans que la cause saute aux yeux.
    #
    # La clé `outlook` reste celle du compte PERSONNEL : un `accounts.json`
    # écrit avant la séparation la porte déjà, et la déplacer ferait pointer
    # ces comptes vers un préréglage inconnu.
    "outlook": {
        "label": "Microsoft / Outlook.com (personnel)",
        "imap": {
            "host": "outlook.office365.com",
            "port": 993,
            "security": "ssl",
        },
        "smtp": {
            "host": "smtp-mail.outlook.com",
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
        "oauth": _OAUTH_MICROSOFT,
    },
    "microsoft365": {
        "label": "Microsoft 365 (organisation)",
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
        "app_password": False,
        "note_key": "mail_preset_note_microsoft365",
        "oauth": _OAUTH_MICROSOFT,
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
    # Texte ajouté au bas d'un message écrit ou d'une réponse, séparé par le
    # délimiteur « -- ». Rien de secret : il vit donc ici et non au coffre.
    signature: str = ""
    # Empreintes de certificats TLS acceptées pour ce compte, par point
    # d'accès « hôte:port » ; aucune n'est un secret.
    tls_pins: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tls_pins = _checked_pins(self.name, self.tls_pins)
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
        """Le compte tel qu'il s'écrit ; `tls_pins` n'y figure que non
        vide, si bien qu'un compte sans épingle s'écrit comme avant que le
        champ n'existe."""
        data = asdict(self)
        if not data.get("tls_pins"):
            data.pop("tls_pins", None)
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
                signature=d.get("signature", ""),
                # Sans `or {}` : une valeur qui n'est pas un objet JSON est
                # signalée au journal, pas confondue avec « aucune ».
                tls_pins=d.get("tls_pins"),
            )
        except (KeyError, TypeError) as exc:
            raise AccountError(
                f"{t('mail_err_account_unreadable')} {exc}"
            ) from exc


def _checked_pins(name: str, pins) -> dict[str, str]:
    """Les épingles lisibles de `pins`, clés et valeurs normalisées.

    None ou absent : aucune, sans bruit. Une valeur qui n'est pas un
    dictionnaire, ou une entrée dont la clé ou l'empreinte ne se lit pas,
    est écartée avec une ligne `WARNING` (la valeur n'y est pas recopiée) ;
    jamais d'`AccountError` : une entrée corrompue ne rend pas le fichier
    illisible, et son point d'accès revient à la vérification normale.
    """
    if pins is None:
        return {}
    if not isinstance(pins, dict):
        _logger.warning(
            "épingle TLS illisible écartée : compte %s, champ tls_pins de"
            " type %s",
            name,
            type(pins).__name__,
        )
        return {}
    propres: dict[str, str] = {}
    for cle, valeur in pins.items():
        point = tls.split_pin_key(cle)
        empreinte = tls.parse_pin(valeur)
        if point is None or empreinte is None:
            _logger.warning(
                "épingle TLS illisible écartée : compte %s, clé %r", name, cle
            )
            continue
        propres[tls.pin_key(*point)] = tls.FINGERPRINT_PREFIX + empreinte
    return propres


def accounts_path() -> Path:
    return Path(os.path.expanduser("~/.erplibre/mail/accounts.json"))


# L'attribut qui rattache un compte au fichier d'où `load` l'a lu, ou où
# `save` l'a écrit. Hors des champs du dataclass : il ne s'écrit jamais,
# n'entre pas dans l'égalité, et une copie par `from_dict` ne le porte pas.
_SOURCE_ATTR = "_accounts_file"


def _tie(account, path: Path) -> None:
    """Rattache `account` au fichier `path` ; un objet qui refuse
    l'attribut reste sans fichier."""
    try:
        setattr(account, _SOURCE_ATTR, Path(path))
    except Exception:
        pass


def source_of(account) -> Path | None:
    """Le fichier d'où vient `account` (lu par `load`, écrit par `save`),
    ou None pour un compte construit en mémoire."""
    return getattr(account, _SOURCE_ATTR, None)


def _prepare_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)


def _write_private(path: Path, text: str) -> None:
    """Remplace `path` par `text`, dans un fichier en 0600 dès sa création.

    Écrire puis `chmod` laisserait le fichier — mot de passe absent, mais
    `secret_ref` et adresses y sont — lisible à l'umask du process le temps
    entre les deux appels. Le fichier temporaire est créé en 0600
    (`mkstemp`) dans le même dossier, écrit, synchronisé, puis substitué
    d'un coup (`os.replace`) : un lecteur voit l'ancien fichier ou le
    nouveau, jamais un fichier vide ou tronqué, et une panne au milieu
    laisse l'ancien intact. Le temporaire est retiré sur toute exception.

    Un `path` qui est un lien symbolique est suivi : le temporaire naît à
    côté de la cible, qui reçoit le contenu, et le lien reste un lien.
    Remplacer le lien lui-même couperait sans un mot un fichier tenu
    ailleurs (dossier de configuration versionné ou synchronisé).
    """
    path = Path(os.path.realpath(path))
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=".accounts.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)


@contextlib.contextmanager
def _accounts_lock(path: Path) -> Iterator[None]:
    """Le verrou des écritures d'`accounts.json`, à côté du fichier ; non
    obtenu à temps : `AccountError`. Le dossier est créé (0700) au
    besoin."""
    from script.todo.mail.rules.lock import file_lock

    _prepare_parent(path)
    with file_lock(
        path.parent / ACCOUNTS_LOCK_NAME, wait=ACCOUNTS_LOCK_WAIT_S
    ) as tenu:
        if not tenu:
            raise AccountError(t("mail_err_accounts_busy"))
        yield


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
    comptes = [Account.from_dict(d) for d in data.get("accounts", [])]
    for compte in comptes:
        _tie(compte, path)
    return comptes


def _write_accounts(accounts: list[Account], path: Path) -> None:
    """Écrit `accounts` tels quels, épingles comprises ; l'appelant tient
    le verrou."""
    names = [a.name for a in accounts]
    payload = {
        "version": SCHEMA_VERSION,
        "default_account": names[0] if names else None,
        "accounts": [a.to_dict() for a in accounts],
    }
    _write_private(path, json.dumps(payload, ensure_ascii=False, indent=2))


def save(accounts: list[Account], path: Path | None = None) -> None:
    """Écrit `accounts`, sous le verrou d'`accounts.json`.

    Les épingles appartiennent au disque : pour chaque compte dont le nom
    existe déjà dans le fichier relu sous le verrou, ce sont SES épingles
    qui s'écrivent, pas celles de la liste en mémoire ; un compte neuf
    s'écrit avec les siennes, et un fichier absent ou illisible laisse la
    liste telle quelle. Seuls `pin_certificate` et `unpin_certificate`
    changent les épingles d'un compte existant. Les autres champs suivent
    la liste : la dernière écriture l'emporte.
    """
    path = Path(path) if path else accounts_path()
    names = [a.name for a in accounts]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise AccountError(
            f"{t('mail_err_duplicate_account_names')} {sorted(duplicates)}"
        )
    with _accounts_lock(path):
        try:
            sur_disque = {a.name: a.tls_pins for a in load(path)}
        except AccountError:
            sur_disque = {}
        a_ecrire = []
        for account in accounts:
            if account.name in sur_disque:
                copie = Account.from_dict(account.to_dict())
                copie.tls_pins = dict(sur_disque[account.name])
                a_ecrire.append(copie)
            else:
                a_ecrire.append(account)
        _write_accounts(a_ecrire, path)
    for account in accounts:
        _tie(account, path)


def _change_pins(name: str, path: Path | None, change) -> Account:
    """Relit le fichier sous le verrou, applique `change(pins)` aux
    épingles du compte `name`, écrit s'il y a lieu et rend le compte relu.
    `change` rend vrai s'il a modifié les épingles."""
    path = Path(path) if path else accounts_path()
    with _accounts_lock(path):
        comptes = load(path)
        compte = find(comptes, name)
        if compte is None:
            raise AccountError(f"{t('mail_err_account_not_found')} {name!r}")
        if change(compte.tls_pins):
            _write_accounts(comptes, path)
        return compte


def pin_certificate(
    name: str,
    host: str,
    port: int,
    fingerprint: str,
    path: Path | None = None,
) -> Account:
    """Épingle `fingerprint` pour le compte `name` et le point d'accès
    `host:port`, en remplaçant l'épingle précédente de ce point d'accès.

    Le fichier est relu et écrit sous le verrou ; les autres comptes et
    champs restent tels qu'ils sont relus. Une empreinte invalide lève
    `AccountError` sans rien écrire. Rend le compte relu.
    """
    try:
        valeur = tls.pin_value(fingerprint)
    except ValueError as exc:
        raise AccountError(
            f"{t('mail_err_invalid_tls_pin')} {name!r}"
        ) from exc
    cle = tls.pin_key(host, port)

    def poser(pins):
        pins[cle] = valeur
        return True

    compte = _change_pins(name, path, poser)
    _logger.info(
        "empreinte TLS épinglée : compte %s, %s, sha256=%s",
        name,
        cle,
        tls.parse_pin(valeur),
    )
    return compte


def unpin_certificate(
    name: str, key: str, path: Path | None = None
) -> Account:
    """Retire l'épingle `key` du compte `name` ; une clé absente n'écrit
    rien. Rend le compte relu."""
    point = tls.split_pin_key(key)
    cle = tls.pin_key(*point) if point else key

    def retirer(pins):
        if cle not in pins:
            return False
        del pins[cle]
        return True

    compte = _change_pins(name, path, retirer)
    _logger.info("empreinte TLS retirée : compte %s, %s", name, cle)
    return compte


def pinned_certificates(accounts) -> list[tuple[str, str, str]]:
    """`(compte, clé, empreinte en 64 hex)` de chaque épingle, dans
    l'ordre des comptes puis des clés."""
    lignes = []
    for account in accounts:
        pins = getattr(account, "tls_pins", None) or {}
        for cle in sorted(pins):
            empreinte = tls.parse_pin(pins[cle])
            if empreinte:
                lignes.append((account.name, cle, empreinte))
    return lignes


def refresh_tls_pins(account, path: Path | None = None) -> None:
    """Pose sur `account` les épingles que le fichier porte pour son nom.

    Sert avant chaque connexion d'un processus qui dure : une épingle
    posée ou retirée ailleurs vaut dès la connexion suivante. Le fichier
    relu est `path`, sinon celui d'où vient le compte (`source_of`) ; un
    compte construit en mémoire, sans fichier, garde ses épingles et
    aucun fichier n'est ouvert. Lecture seule, sans verrou ; fichier
    absent ou illisible, ou compte absent : les épingles en mémoire
    restent, ligne `INFO`. Ne lève jamais.
    """
    nom = getattr(account, "name", None)
    path = path or source_of(account)
    if path is None:
        return
    try:
        relu = find(load(path), nom)
    except Exception as exc:
        _logger.info(
            "épingles TLS non relues pour %s : %s", nom, type(exc).__name__
        )
        return
    if relu is None:
        _logger.info("épingles TLS non relues : compte %s absent", nom)
        return
    try:
        setattr(account, "tls_pins", dict(relu.tls_pins))
    except Exception as exc:
        _logger.info(
            "épingles TLS non posées pour %s : %s", nom, type(exc).__name__
        )


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
