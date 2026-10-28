#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Règles, état du moteur et images d'un compte, sur le disque.

Disposition, sous la même base que le cache (`base_of`) :

    <base>/.rules/<compte>/rules.json   règles (0600)
    <base>/.rules/<compte>/state.json   curseur du moteur (0600)
    <base>/.rules/<compte>/report_snapshot.json
                                        partie boîte du rapport du jour (0600)
    <base>/.rules/<compte>/lock         verrou des mutations et des passes
    <base>/.rules/<compte>/media/       images copiées (0700, fichiers 0600)

`.rules` et non `rules` : le cache d'un compte vit en `<base>/<compte>/`,
et un compte nommé `rules` y collisionnerait. Un nom de compte ne commence
jamais par un point, donc `.rules` n'appartient à aucun compte. Sous
`.rules`, un dossier par compte : un nom de compte n'interdit que « / » et
le point initial, et des fichiers `<compte>.json` côte à côte laisseraient
le compte « perso.state » viser l'état du compte « perso ».

Toute écriture est atomique (fichier temporaire du même dossier, `fsync`,
`os.replace`) et toute mutation des règles prend le verrou du compte, sauf
`lock_held=True` quand l'appelant le tient déjà pour sa passe. Les fonctions
de chemin créent leurs dossiers en 0700 ; les lectures (`load`,
`load_state`) n'en créent aucun.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import mimetypes
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from script.todo.mail.rules import svg
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.rules.model import (
    FORMATS,
    IMAGE_MIMES,
    MAX_IMAGE_BYTES,
    SCHEMA_VERSION,
    Armed,
    MediaRef,
    Rule,
    RuleError,
    RulesBusy,
    is_safe_media_name,
    rules_from_dict,
    rules_to_dict,
    validate,
)
from script.todo.mail.store import default_base
from script.todo.todo_i18n import t

RULES_DIRNAME = ".rules"
# Attente du verrou par l'écran des règles : court, l'utilisateur attend.
UI_LOCK_WAIT_S = 2.0
STATE_VERSION = 1
_RULES_FILE = "rules.json"
_STATE_FILE = "state.json"
_LOCK_FILE = "lock"
_MEDIA_DIR = "media"
# Plafonds d'envois automatiques par compte quand `rules.json` ne les
# règle pas (clé racine « caps ») : par passe du moteur, et par heure
# glissante.
DEFAULT_CAP_PER_PASS = 20
DEFAULT_CAP_PER_HOUR = 60
_CAPS_KEY = "caps"
# Réglages du rapport de statistiques (clé racine « report ») : bornes et
# défauts. `weeks` = 0 retire le tableau hebdomadaire ; sa borne haute
# limite la part du rapport qui repose sur des drapeaux que la
# synchronisation ne relit plus.
DEFAULT_REPORT_DAYS = 7
REPORT_DAYS_MAX = 31
DEFAULT_REPORT_WEEKS = 4
REPORT_WEEKS_MAX = 8
DEFAULT_DELAY_WINDOW_DAYS = 30
DELAY_WINDOW_DAYS_MAX = 365
# "" : la langue de l'interface.
REPORT_LANGS = ("", "fr", "en")
AUTH_SERV_ID_MAX = 255
_REPORT_KEY = "report"
_SNAPSHOT_FILE = "report_snapshot.json"
_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]")
_DOTS_RE = re.compile(r"\.{2,}")


@dataclass
class EngineState:
    """Ce que le moteur garde d'une passe à l'autre, hors du cache.

    `cursor` est le plus haut UID de la boîte de réception déjà évalué ;
    `cache_epoch` l'époque du cache vue à la dernière passe ; avant
    `hold_until` (époque), tout envoi automatique est retenu. `done` liste
    les UID au-dessus du curseur déjà évalués (un trou les précède) : le
    moteur ne les réévalue pas.
    """

    uidvalidity: int | None = None
    cursor: int | None = None
    cache_epoch: str | None = None
    hold_until: int = 0
    done: list = dataclasses.field(default_factory=list)


@dataclass
class Caps:
    """Plafonds d'envois automatiques d'un compte, entiers ≥ 1.

    `per_pass` borne les envois d'une passe du moteur ; `per_hour` ceux
    décidés dans les 3600 dernières secondes, toutes passes et toutes
    règles confondues. Au-delà, la réponse est retenue (approbation par
    `o`), jamais perdue.
    """

    per_pass: int = DEFAULT_CAP_PER_PASS
    per_hour: int = DEFAULT_CAP_PER_HOUR


@dataclass
class ReportSettings:
    """Réglages du rapport de statistiques d'un compte.

    `days` jours clos et `weeks` semaines ISO complètes dans les tableaux ;
    `delay_window_days` jours pour les délais de réponse ; `format` celui
    des nouvelles règles stats ; `lang` la langue des libellés du rapport
    (« » : celle de l'interface) ; `auth_serv_id` l'identifiant exigé du
    premier Authentication-Results (« » : non vérifié).
    """

    days: int = DEFAULT_REPORT_DAYS
    weeks: int = DEFAULT_REPORT_WEEKS
    delay_window_days: int = DEFAULT_DELAY_WINDOW_DAYS
    format: str = "markdown"
    lang: str = ""
    auth_serv_id: str = ""


# -- Chemins -----------------------------------------------------------


def _check_private_dir(path: Path) -> None:
    """Refuse un dossier qui est un lien symbolique ou appartient à autrui."""
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise RuleError(f"{path} {t('mail_err_symlink_refused')}")
    if info.st_uid != os.getuid():
        raise RuleError(f"{path} {t('mail_err_owned_by_other_user')}")


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_private_dir(path)
    os.chmod(path, 0o700)
    return path


def _check_account_name(account_name: str) -> str:
    """Un nom de compte qui reste UN composant sous `.rules`."""
    if (
        not isinstance(account_name, str)
        or not account_name
        or "/" in account_name
        or "\0" in account_name
        or account_name.startswith(".")
    ):
        raise RuleError(f"{t('mail_rules_err_invalid')} {account_name!r}")
    return account_name


def _rules_root(base: Path | None) -> Path:
    return Path(base if base is not None else default_base()) / RULES_DIRNAME


def _account_root(account_name: str, base: Path | None) -> Path:
    """Le dossier du compte, sans le créer."""
    return _rules_root(base) / _check_account_name(account_name)


def rules_dir(base: Path | None = None) -> Path:
    """`<base>/.rules`, créé en 0700 ; base par défaut `~/.erplibre/mail`."""
    root = _rules_root(base)
    root.parent.mkdir(parents=True, exist_ok=True)
    return _private_dir(root)


def account_dir(account_name: str, base: Path | None = None) -> Path:
    """`<base>/.rules/<compte>/`, créé en 0700."""
    rules_dir(base)
    return _private_dir(_account_root(account_name, base))


def rules_path(account_name: str, base: Path | None = None) -> Path:
    return account_dir(account_name, base) / _RULES_FILE


def state_path(account_name: str, base: Path | None = None) -> Path:
    return account_dir(account_name, base) / _STATE_FILE


def lock_path(account_name: str, base: Path | None = None) -> Path:
    return account_dir(account_name, base) / _LOCK_FILE


def media_dir(account_name: str, base: Path | None = None) -> Path:
    return _private_dir(account_dir(account_name, base) / _MEDIA_DIR)


def base_of(store) -> Path | None:
    """La base des règles d'un cache : SOURCE UNIQUE pour tout appelant.

    Le parent de la racine du cache, clair ou chiffré (la racine est
    `<base>/<compte>`) ; None pour un cache éphémère, où les règles sont
    désactivées. Un cache ouvert sous un dossier temporaire donne donc des
    règles sous ce même dossier, jamais dans le vrai dossier personnel.

    None n'est PAS une base à transmettre : `base=None` désigne, pour les
    autres fonctions de ce module, le dossier par défaut
    `~/.erplibre/mail`. L'appelant teste None et s'arrête avant tout appel,
    sinon un cache éphémère chargerait et exécuterait les règles du
    dossier personnel.
    """
    if getattr(store, "mode", None) == "ephemeral":
        return None
    return Path(store.root).parent


# -- Écriture et lecture -----------------------------------------------


def _write_atomic(path: Path, data: bytes) -> None:
    """Remplace `path` d'un coup : un lecteur voit l'ancien ou le nouveau.

    Le temporaire naît en 0600 dans le même dossier (`O_EXCL` : jamais un
    fichier préexistant ni un lien), est synchronisé, puis renommé.
    """
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    with contextlib.suppress(OSError):
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _write_json(path: Path, data: dict) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    _write_atomic(path, text.encode("utf-8"))


def _read_json(path: Path):
    """Le JSON de `path`, ou None s'il n'existe pas."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise RuleError(f"{t('mail_rules_err_bad_json')} {exc}") from exc
    try:
        return json.loads(text)
    except ValueError as exc:
        raise RuleError(f"{t('mail_rules_err_bad_json')} {exc}") from exc


def _read_rules(account_name: str, base: Path | None) -> list[Rule]:
    data = _read_json(_account_root(account_name, base) / _RULES_FILE)
    if data is None:
        return []
    return rules_from_dict(data)


def _write_rules(
    account_name: str,
    base: Path | None,
    rules: list[Rule],
    root: dict | None = None,
) -> None:
    """Réécrit le fichier des règles, appelant sous verrou.

    Les clés RACINE que le modèle ne connaît pas (plafonds, réglages d'un
    lot ultérieur) sont reprises du fichier en place : aucune mutation ne
    les efface. `root` en remplace certaines, pour qui les modifie.

    Le contenu est relu par `rules_from_dict` AVANT d'écrire : une règle
    qu'un `load` refuserait ensuite (identifiant vide, type inattendu,
    valeur non sérialisable, `id` en double) lève `RuleError` et laisse
    le fichier intact, au lieu de rendre illisibles toutes les règles du
    compte.
    """
    path = rules_path(account_name, base)
    data = rules_to_dict(account_name, rules)
    current = _read_json(path)
    if isinstance(current, dict):
        for key, value in current.items():
            data.setdefault(key, value)
    data.update(root or {})
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    except (TypeError, ValueError) as exc:
        raise RuleError(f"{t('mail_rules_err_bad_json')} {exc}") from exc
    rules_from_dict(json.loads(text))
    _write_atomic(path, text.encode("utf-8"))


@contextlib.contextmanager
def _mutation(
    account_name: str, base: Path | None, lock_held: bool, wait: float
):
    """Tient le verrou du compte pendant le bloc, sauf s'il est déjà tenu.

    Verrou non obtenu dans `wait` secondes : `RulesBusy`, rien n'est écrit.
    """
    if lock_held:
        yield
        return
    with file_lock(lock_path(account_name, base), wait=wait) as held:
        if not held:
            raise RulesBusy(t("mail_rules_busy"))
        yield


def _by_order(rules: list[Rule]) -> list[Rule]:
    return sorted(rules, key=lambda rule: rule.order)


# -- Règles ------------------------------------------------------------


def rules_exist(account_name: str, base: Path | None = None) -> bool:
    """Vrai si le fichier des règles du compte existe ; ne crée rien.

    Distingue « aucun fichier » d'un fichier qui ne contient plus une
    règle donnée : `load` rend [] dans les deux cas.
    """
    return (_account_root(account_name, base) / _RULES_FILE).is_file()


def load(account_name: str, base: Path | None = None) -> list[Rule]:
    """Les règles du compte, triées par `order` ; fichier absent : [].

    JSON illisible ou version future : `RuleError`, fichier intact.
    """
    return _by_order(_read_rules(account_name, base))


def _stored_armed(rule: Rule, on_disk: Rule | None, rearm: Armed | None):
    """L'armement à écrire pour `rule` par `upsert_rule`.

    `rearm` fourni l'emporte. Sinon l'armement du DISQUE est conservé :
    le moteur a pu réarmer la règle pendant son édition. Deux exceptions :
    une règle désactivée est désarmée, et une règle qui était désactivée
    sur le disque repart désarmée ; le moteur l'arme à sa passe suivante,
    et elle n'agit pas sur ce qui est arrivé pendant qu'elle dormait.
    """
    if rearm is not None:
        return rearm
    if not rule.enabled:
        return None
    if on_disk is None:
        return rule.armed
    if not on_disk.enabled:
        return None
    return on_disk.armed


def upsert_rule(
    account_name: str,
    rule: Rule,
    *,
    rearm: Armed | None = None,
    base: Path | None = None,
    lock_held: bool = False,
    wait: float = UI_LOCK_WAIT_S,
) -> None:
    """Ajoute ou remplace la règle de même `id`, fichier relu sous verrou.

    La règle est validée d'abord (`RuleError`). Une règle absente est
    ajoutée en fin, `order` = plus grand ordre + 10.
    """
    validate(rule)
    with _mutation(account_name, base, lock_held, wait):
        rules = _read_rules(account_name, base)
        for index, existing in enumerate(rules):
            if existing.id == rule.id:
                armed = _stored_armed(rule, existing, rearm)
                rules[index] = dataclasses.replace(rule, armed=armed)
                break
        else:
            order = max((r.order for r in rules), default=0) + 10
            armed = _stored_armed(rule, None, rearm)
            rules.append(dataclasses.replace(rule, order=order, armed=armed))
        _write_rules(account_name, base, rules)


def delete_rule(
    account_name: str,
    rule_id: str,
    *,
    base: Path | None = None,
    wait: float = UI_LOCK_WAIT_S,
) -> None:
    """Retire la règle ; ses images restent, une autre règle peut les citer."""
    with _mutation(account_name, base, False, wait):
        rules = _read_rules(account_name, base)
        kept = [rule for rule in rules if rule.id != rule_id]
        if len(kept) != len(rules):
            _write_rules(account_name, base, kept)


def move_rule(
    account_name: str,
    rule_id: str,
    delta: int,
    *,
    base: Path | None = None,
    wait: float = UI_LOCK_WAIT_S,
) -> None:
    """Déplace la règle de `delta` rangs, puis renumérote 10, 20, 30…

    Le déplacement s'arrête aux extrémités ; un `id` inconnu ne change rien.
    """
    with _mutation(account_name, base, False, wait):
        rules = _by_order(_read_rules(account_name, base))
        ids = [rule.id for rule in rules]
        if rule_id not in ids:
            return
        index = ids.index(rule_id)
        target = max(0, min(len(rules) - 1, index + delta))
        rules.insert(target, rules.pop(index))
        for rank, rule in enumerate(rules, start=1):
            rule.order = rank * 10
        _write_rules(account_name, base, rules)


def set_enabled(
    account_name: str,
    rule_id: str,
    enabled: bool,
    *,
    armed: Armed | None,
    base: Path | None = None,
    wait: float = UI_LOCK_WAIT_S,
) -> None:
    """Active ou désactive une règle.

    Activer une règle désactivée pose `armed` (None : armée à la passe
    suivante) ; désactiver la désarme. Une règle déjà dans l'état demandé
    garde son armement : le moteur peut l'avoir réarmée entre-temps.
    """
    with _mutation(account_name, base, False, wait):
        rules = _read_rules(account_name, base)
        for rule in rules:
            if rule.id != rule_id or rule.enabled == enabled:
                continue
            rule.enabled = enabled
            rule.armed = armed if enabled else None
            _write_rules(account_name, base, rules)
            return


def set_armed(
    account_name: str,
    armed_by_id: dict[str, Armed],
    *,
    base: Path | None = None,
    lock_held: bool = False,
) -> None:
    """Pose l'armement des règles nommées ; les autres sont inchangées."""
    with _mutation(account_name, base, lock_held, UI_LOCK_WAIT_S):
        rules = _read_rules(account_name, base)
        changed = False
        for rule in rules:
            if rule.id in armed_by_id:
                rule.armed = armed_by_id[rule.id]
                changed = True
        if changed:
            _write_rules(account_name, base, rules)


# -- Plafonds ----------------------------------------------------------


def caps_from_dict(raw) -> Caps:
    """Les plafonds de la clé « caps » ; absente (None) : les défauts.

    Chaque clé absente prend son défaut ; une clé présente doit être un
    entier ≥ 1 (un booléen n'en est pas un), sinon `RuleError`. Le moteur
    s'arrête alors plutôt que d'envoyer sous un plafond qu'on n'a pas su
    lire.
    """
    if raw is None:
        return Caps()
    if not isinstance(raw, dict):
        raise RuleError(f"{t('mail_rules_err_invalid')} {_CAPS_KEY}")
    values = {}
    for field in dataclasses.fields(Caps):
        value = raw.get(field.name, field.default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RuleError(
                f"{t('mail_rules_err_invalid')} {_CAPS_KEY}.{field.name}"
            )
        values[field.name] = value
    return Caps(**values)


def load_caps(account_name: str, base: Path | None = None) -> Caps:
    """Les plafonds du compte ; fichier absent ou sans « caps » : défauts.

    JSON illisible, version future ou valeur invalide : `RuleError`.
    """
    data = _read_json(_account_root(account_name, base) / _RULES_FILE)
    if data is None:
        return Caps()
    if not isinstance(data, dict):
        raise RuleError(f"{t('mail_rules_err_bad_json')} {_CAPS_KEY}")
    version = data.get("version", SCHEMA_VERSION)
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise RuleError(f"{t('mail_rules_err_future_version')} {version}")
    return caps_from_dict(data.get(_CAPS_KEY))


def save_caps(
    account_name: str,
    caps: Caps,
    *,
    base: Path | None = None,
    lock_held: bool = False,
    wait: float = UI_LOCK_WAIT_S,
) -> None:
    """Écrit les plafonds dans `rules.json`, règles relues sous verrou.

    Les valeurs sont vérifiées d'abord (`RuleError`, rien n'est écrit) ;
    les règles et les autres clés racine restent telles quelles.
    """
    data = {"per_pass": caps.per_pass, "per_hour": caps.per_hour}
    caps_from_dict(data)
    with _mutation(account_name, base, lock_held, wait):
        rules = _read_rules(account_name, base)
        _write_rules(account_name, base, rules, root={_CAPS_KEY: data})


# -- Réglages du rapport -----------------------------------------------

# (minimum, maximum) des réglages entiers.
_REPORT_INT_BOUNDS = {
    "days": (1, REPORT_DAYS_MAX),
    "weeks": (0, REPORT_WEEKS_MAX),
    "delay_window_days": (1, DELAY_WINDOW_DAYS_MAX),
}


def _report_fault(name: str) -> RuleError:
    return RuleError(f"{t('mail_rules_err_invalid')} {_REPORT_KEY}.{name}")


def _valid_auth_serv_id(value) -> bool:
    """Chaîne d'au plus `AUTH_SERV_ID_MAX` caractères ASCII imprimables
    33..126, sans « ; » ; vide admis."""
    return (
        isinstance(value, str)
        and len(value) <= AUTH_SERV_ID_MAX
        and all(33 <= ord(char) <= 126 and char != ";" for char in value)
    )


def report_from_dict(raw) -> ReportSettings:
    """Les réglages de la clé « report » ; absente (None) : les défauts.

    Chaque sous-clé absente prend son défaut ; une valeur hors bornes, ou
    d'un autre type (un booléen n'est pas un entier), lève `RuleError`
    qui nomme le champ. Les sous-clés inconnues sont ignorées.
    """
    if raw is None:
        return ReportSettings()
    if not isinstance(raw, dict):
        raise RuleError(f"{t('mail_rules_err_invalid')} {_REPORT_KEY}")
    values = {}
    for field in dataclasses.fields(ReportSettings):
        value = raw.get(field.name, field.default)
        bounds = _REPORT_INT_BOUNDS.get(field.name)
        if bounds is not None:
            low, high = bounds
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not low <= value <= high
            ):
                raise _report_fault(field.name)
        elif field.name == "format":
            if value not in FORMATS:
                raise _report_fault(field.name)
        elif field.name == "lang":
            if value not in REPORT_LANGS:
                raise _report_fault(field.name)
        elif not _valid_auth_serv_id(value):
            raise _report_fault(field.name)
        values[field.name] = value
    return ReportSettings(**values)


def _rules_root_data(account_name: str, base: Path | None):
    """Le contenu de `rules.json` (dict) ou None s'il n'existe pas.

    Une racine qui n'est pas un objet, ou une version future, lève
    `RuleError`.
    """
    data = _read_json(_account_root(account_name, base) / _RULES_FILE)
    if data is None:
        return None
    if not isinstance(data, dict):
        raise RuleError(f"{t('mail_rules_err_bad_json')} {_REPORT_KEY}")
    version = data.get("version", SCHEMA_VERSION)
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise RuleError(f"{t('mail_rules_err_future_version')} {version}")
    return data


def load_report(account_name: str, base: Path | None = None) -> ReportSettings:
    """Les réglages du rapport ; fichier absent ou sans « report » :
    défauts.

    JSON illisible, version future ou valeur invalide : `RuleError`.
    """
    data = _rules_root_data(account_name, base)
    if data is None:
        return ReportSettings()
    return report_from_dict(data.get(_REPORT_KEY))


def save_report(
    account_name: str,
    settings: ReportSettings,
    *,
    base: Path | None = None,
    lock_held: bool = False,
    wait: float = UI_LOCK_WAIT_S,
) -> None:
    """Écrit les réglages du rapport dans `rules.json`, sous verrou.

    Les valeurs sont vérifiées d'abord (`RuleError`, rien n'est écrit).
    Les sous-clés de « report » que ce module ne connaît pas sont gardées ;
    les règles et les autres clés racine restent telles quelles.
    """
    known = dataclasses.asdict(settings)
    report_from_dict(known)
    with _mutation(account_name, base, lock_held, wait):
        rules = _read_rules(account_name, base)
        current = _read_json(_account_root(account_name, base) / _RULES_FILE)
        merged = {}
        if isinstance(current, dict) and isinstance(
            current.get(_REPORT_KEY), dict
        ):
            merged.update(current[_REPORT_KEY])
        merged.update(known)
        _write_rules(account_name, base, rules, root={_REPORT_KEY: merged})


def load_report_snapshot(
    account_name: str, base: Path | None = None
) -> dict | None:
    """Le contenu de l'instantané du rapport, ou None s'il est absent ou
    illisible ; ne lève jamais : un instantané abîmé se recalcule."""
    try:
        path = _account_root(account_name, base) / _SNAPSHOT_FILE
        data = _read_json(path)
    except (RuleError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_report_snapshot(
    account_name: str,
    data: dict,
    *,
    base: Path | None = None,
    lock_held: bool = False,
) -> None:
    """Remplace l'instantané du rapport (0600, écriture atomique), sous le
    verrou du compte sauf `lock_held`."""
    with _mutation(account_name, base, lock_held, UI_LOCK_WAIT_S):
        _write_json(account_dir(account_name, base) / _SNAPSHOT_FILE, data)


# -- État du moteur ----------------------------------------------------


def _optional(data: dict, key: str, kind: type):
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, kind):
        raise RuleError(f"{t('mail_rules_err_bad_json')} {key}")
    return value


def load_state(account_name: str, base: Path | None = None) -> EngineState:
    """L'état du moteur ; fichier absent : état neuf.

    JSON illisible ou version future : `RuleError`. Le moteur s'arrête
    alors plutôt que de repartir d'un curseur nul sans le dire.
    """
    data = _read_json(_account_root(account_name, base) / _STATE_FILE)
    if data is None:
        return EngineState()
    if not isinstance(data, dict):
        raise RuleError(f"{t('mail_rules_err_bad_json')} state")
    version = data.get("version", STATE_VERSION)
    if isinstance(version, int) and version > STATE_VERSION:
        raise RuleError(f"{t('mail_rules_err_future_version')} {version}")
    return EngineState(
        uidvalidity=_optional(data, "uidvalidity", int),
        cursor=_optional(data, "cursor", int),
        cache_epoch=_optional(data, "cache_epoch", str),
        hold_until=_optional(data, "hold_until", int) or 0,
        done=_uid_list(data, "done"),
    )


def _uid_list(data: dict, key: str) -> list:
    """Une liste facultative d'entiers ; absente : vide. Autre forme :
    `RuleError`, comme pour les autres champs de l'état."""
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(
        isinstance(v, bool) or not isinstance(v, int) for v in value
    ):
        raise RuleError(f"{t('mail_rules_err_bad_json')} {key}")
    return sorted(set(value))


def save_state(
    account_name: str,
    state: EngineState,
    *,
    base: Path | None = None,
    lock_held: bool = False,
) -> None:
    with _mutation(account_name, base, lock_held, UI_LOCK_WAIT_S):
        _write_json(
            state_path(account_name, base),
            {"version": STATE_VERSION, **dataclasses.asdict(state)},
        )


# -- Images ------------------------------------------------------------


def _safe_media_name(name: str, mime: str) -> str:
    """Nom de base réduit à `[A-Za-z0-9._-]`, sans point initial ni « .. »."""
    cleaned = _DOTS_RE.sub(".", _UNSAFE_CHARS_RE.sub("_", name)).lstrip(".")
    stem, dot, _suffix = cleaned.rpartition(".")
    if not dot or not stem:
        extension = mimetypes.guess_extension(mime) or ""
        cleaned = (cleaned or "image") + extension
    return cleaned


def _candidates(name: str):
    """Le nom, puis `-2`, `-3`… avant l'extension."""
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    yield name
    index = 2
    while True:
        yield f"{stem}-{index}{dot}{suffix}"
        index += 1


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(_read_private(path)).hexdigest()
    except (OSError, RuleError):
        return None


def _read_private(path: Path) -> bytes:
    """Les octets d'une image, lien symbolique refusé, taille bornée."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise RuleError(f"{t('mail_rules_err_image_size')} {path.name}")
    return data


def import_media(
    account_name: str, src: Path, *, base: Path | None = None
) -> MediaRef:
    """Copie une image dans le dossier des médias du compte.

    Refuse un type hors `IMAGE_MIMES` (deviné par l'extension) et une
    image de plus de `MAX_IMAGE_BYTES`. Un SVG (`.svg`, `.svgz`) est
    converti en PNG par `svg.svg_to_png` et rangé sous son nom en `.png` :
    le SVG lui-même n'est jamais copié. Le nom est assaini ; un fichier de
    même nom au contenu différent fait essayer `-2`, `-3`… ; un fichier de
    même contenu est réutilisé tel quel. La copie naît en 0600 par
    `O_EXCL` : deux imports concurrents n'écrasent jamais le fichier
    l'un de l'autre.
    """
    src = Path(src)
    if svg.is_svg_name(src.name):
        data = svg.svg_to_png(src)
        mime, stored_name = "image/png", svg.png_name(src.name)
    else:
        mime, stored_name = mimetypes.guess_type(src.name)[0], src.name
        if mime not in IMAGE_MIMES:
            raise RuleError(
                f"{t('mail_rules_err_image_type')}"
                f" {mime or src.suffix or src.name}"
            )
        try:
            with open(src, "rb") as handle:
                data = handle.read(MAX_IMAGE_BYTES + 1)
        except OSError as exc:
            raise RuleError(
                f"{t('mail_rules_err_image_missing')} {src.name}"
            ) from exc
        if len(data) > MAX_IMAGE_BYTES:
            raise RuleError(f"{t('mail_rules_err_image_size')} {src.name}")
    digest = hashlib.sha256(data).hexdigest()
    folder = media_dir(account_name, base)
    for name in _candidates(_safe_media_name(stored_name, mime)):
        dest = folder / name
        if dest.exists() or dest.is_symlink():
            if _file_sha256(dest) == digest:
                return MediaRef(file=name, sha256=digest, mime=mime)
            continue
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            fd = os.open(dest, flags, 0o600)
        except FileExistsError:
            if _file_sha256(dest) == digest:
                return MediaRef(file=name, sha256=digest, mime=mime)
            continue
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(dest)
            raise
        return MediaRef(file=name, sha256=digest, mime=mime)
    # `_candidates` ne s'épuise jamais : la boucle sort par un `return`.
    raise AssertionError(name)


def read_media(
    account_name: str, ref: MediaRef, *, base: Path | None = None
) -> bytes:
    """Les octets d'une image de règle, empreinte vérifiée.

    Nom hors du dossier, fichier absent ou lien : `RuleError`
    « introuvable » ; contenu différent de `ref.sha256` : `RuleError`
    « modifiée » ; jamais une image autre que celle validée à l'ajout.
    """
    if not is_safe_media_name(ref.file):
        raise RuleError(f"{t('mail_rules_err_image_missing')} {ref.file!r}")
    path = media_dir(account_name, base) / ref.file
    try:
        data = _read_private(path)
    except OSError as exc:
        raise RuleError(
            f"{t('mail_rules_err_image_missing')} {ref.file}"
        ) from exc
    if hashlib.sha256(data).hexdigest() != ref.sha256:
        raise RuleError(f"{t('mail_rules_err_image_changed')} {ref.file}")
    return data
