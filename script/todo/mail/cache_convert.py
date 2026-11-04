#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La conversion d'un cache persistant d'un mode à l'autre, et sa reprise.

`convert_cache` recopie un cache `clear` en `encrypted` ou l'inverse (ou
rescelle un cache `encrypted` qui garde des restes clairs) sans rien
perdre : journal des règles, file d'envoi, `auto_sent`, corps, état lu et
répondu, époque du cache. Elle n'ouvre jamais l'ancienne base dans le
nouveau mode : elle construit une base NEUVE à côté, y recopie chaque
table ligne à ligne (scellés descellés puis rescellés, empreintes
recalculées sous le nouveau sel ou traduites, identifiants de ligne
conservés), recopie chaque corps, vérifie tout, puis échange les racines.
Une base chiffrée issue d'une conversion ne contient donc aucune page où
un texte clair aurait vécu.

Protocole sur le disque, sous `<base>/.cache_ctl/<compte>/` : l'état
`convert.json` passe par `building` (copie en cours dans `new/<compte>`),
puis `swapping` (copie complète et vérifiée : point de non-retour), la
racine part en `old/<compte>`, la copie neuve prend sa place, puis
`cleaning` pendant l'effacement sûr de l'ancienne copie ; l'état est retiré
EN DERNIER. Chaque transition est écrite atomiquement. À tout instant une
seule racine est ouvrable ; un processus tué à n'importe quel point laisse
un état que `recover` achève ou défait, selon `store.recovery_plan`.

Ce module est le compagnon de `store` : il lit les membres privés de
`Store` (`_db`, `_crypto`, `_open`, `_msgid_hash`, `_body_path`,
`_write_body_file`, `_reindexer`), et rien d'autre ne doit le faire.
"""

from __future__ import annotations

import base64
import contextlib
import errno
import hashlib
import json
import logging
import math
import os
import secrets as _secrets
import shutil
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from script.todo.mail import store as store_mod
from script.todo.mail.crypto import CryptoError, new_key
from script.todo.mail.rules import storage
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.store import (
    CONVERT_STATE_NAME,
    HASHED_COLUMNS,
    LEGACY_KEY_PREFIX,
    LEGACY_SOURCE_COLUMNS,
    PERSISTENT_MODES,
    PROBE_UNKNOWN,
    SCHEMA,
    SEALED_COLUMNS,
    CacheKeyMissing,
    Store,
    StoreError,
    _addresses,
    cache_ctl_dir,
    cache_exclusive,
    default_base,
    has_clear_residue,
    inscribed_mode,
    probe_connection,
    read_convert_state,
    recovery_plan,
    rw_uri,
    salted_hash,
    shown_mode,
)
from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

CONVERT_PHASES = store_mod.CONVERT_PHASES
REASONS = (
    "no_cache",
    "same_mode",
    "invalid_mode",
    "unreadable_cache",
    "unsupported_root",
    "no_key",
    "busy_open",
    "busy_rules",
    "no_space",
    "declined",
    "unreadable",
    "verify_failed",
    "failed",
    "incomplete",
)
# La clé i18n du texte de chaque raison ; `failed` y ajoute le nom de la
# classe de la cause.
_REASON_KEYS = {
    "no_cache": "mail_cache_convert_no_cache",
    "same_mode": "mail_cache_convert_same_mode",
    "invalid_mode": "mail_err_cache_mode_invalid",
    "unreadable_cache": "mail_cache_unreadable",
    "unsupported_root": "mail_cache_convert_unsupported_root",
    "no_key": "mail_cache_convert_no_key",
    "busy_open": "mail_cache_convert_busy_open",
    "busy_rules": "mail_cache_convert_busy_rules",
    "no_space": "mail_cache_convert_no_space",
    "declined": "mail_cache_convert_declined",
    "unreadable": "mail_cache_convert_unreadable",
    "verify_failed": "mail_cache_convert_verify_failed",
    "failed": "mail_cache_convert_failed",
    "incomplete": "mail_cache_convert_incomplete",
}
# Les tables recopiées, dans l'ordre de la copie ; `messages_fts`, ses
# tables d'ombre et `sqlite_*` sont ignorées, toute autre table refuse.
COPIED_TABLES = (
    "meta",
    "folders",
    "messages",
    "outbox",
    "rule_log",
    "auto_sent",
)
# Les clés de `meta` que la base neuve écrit elle-même.
_META_OWN_KEYS = ("cache_mode", "schema_version", "cache_epoch_check")
# Les préimages que la conversion peut compléter quand la source ne les a
# pas : elles sont exemptées de l'égalité des scellés à la vérification.
_FILLED_PREIMAGES = {
    ("rule_log", "sealed_msg_ref"),
    ("auto_sent", "sealed_msgid"),
}
# Lignes écrites par lot, et intervalle des appels de `progress`.
BATCH_ROWS = 1000
PROGRESS_EVERY = 500
# Marge d'espace libre exigée en plus de la taille du cache.
SPACE_MARGIN_BYTES = 16 * 1024 * 1024
_MIB = 1024 * 1024


class ConvertError(StoreError):
    """Conversion refusée ou annulée ; `reason` est l'un de `REASONS`.
    `committed` dit que l'état `swapping` était écrit : le cache est dans
    la cible, ou le sera à la prochaine ouverture. Sinon le cache
    d'origine reste la référence, intacte."""

    def __init__(self, reason: str, message: str, committed: bool = False):
        self.reason = reason
        self.committed = committed
        super().__init__(message)


class UnknownSchema(StoreError):
    """Une table ou une colonne de la source que cette version ne sait pas
    convertir : elle pourrait porter des scellés ou des empreintes."""


class _VerifyFailed(Exception):
    """La copie neuve ne correspond pas à la source."""


@dataclass(frozen=True)
class ConvertResult:
    source: str
    target: str
    messages: int
    bodies: int
    outbox: int
    rule_log: int
    auto_sent: int
    legacy_keys: int
    legacy_auto_sent: int
    merged_auto_sent: int
    dropped_hashes: int
    resealed: bool
    # Faux si `on_committed` a levé : le cache est converti, le réglage du
    # compte n'a pas été enregistré.
    mode_saved: bool


def _error(
    reason: str, account: str, committed: bool = False, **fields
) -> ConvertError:
    texte = t(_REASON_KEYS[reason]).format(account=account, **fields)
    return ConvertError(reason, texte, committed)


# -- Disque -------------------------------------------------------------


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_state(
    ctl: Path, phase: str, source: str, target: str, started: int
) -> None:
    """Écrit `convert.json` atomiquement : temporaire synchronisé, puis
    `os.replace`, puis synchronisation du dossier."""
    data = json.dumps(
        {
            "version": 1,
            "phase": phase,
            "source": source,
            "target": target,
            "started_at": started,
        }
    ).encode("utf-8")
    tmp = ctl / f".{CONVERT_STATE_NAME}.{os.urandom(4).hex()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, ctl / CONVERT_STATE_NAME)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    _fsync_dir(ctl)


def _remove_state(ctl: Path) -> None:
    try:
        os.unlink(ctl / CONVERT_STATE_NAME)
    except FileNotFoundError:
        pass
    _fsync_dir(ctl)


def _erase_file(path: Path) -> None:
    """Un fichier régulier à lien unique est réécrit en zéros puis
    supprimé ; tout le reste (lien symbolique, lien dur, autre type) est
    seulement supprimé. Un échec de réécriture est consigné, sans contenu,
    et la suppression a lieu quand même."""
    flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return
    except OSError:
        fd = None
    if fd is not None:
        try:
            info = os.fstat(fd)
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                try:
                    zeros = bytes(min(info.st_size, _MIB) or 1)
                    reste = info.st_size
                    os.lseek(fd, 0, os.SEEK_SET)
                    while reste > 0:
                        reste -= os.write(fd, zeros[: min(len(zeros), reste)])
                    os.fsync(fd)
                except OSError as exc:
                    _logger.warning(
                        "effacement sûr : réécriture impossible (%s), fichier"
                        " supprimé sans réécriture",
                        errno.errorcode.get(exc.errno, exc.errno),
                    )
        finally:
            os.close(fd)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def secure_erase(path: Path) -> None:
    """Efface un fichier, un lien ou un dossier entier, au mieux.

    Chaque fichier régulier qui n'a qu'un lien est réécrit en zéros sur
    toute sa taille et synchronisé avant d'être supprimé ; un fichier à
    plusieurs liens durs (réécrire toucherait l'autre nom) ou un lien
    symbolique (jamais suivi) est seulement supprimé ; les dossiers sont
    retirés de bas en haut. Sur SSD, système de fichiers à copie sur
    écriture ou sous instantanés, des blocs survivent : le chiffrement du
    disque reste la vraie protection. Absent : rien."""
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(info.st_mode):
        _erase_file(path)
        return
    for dossier, sous, noms in os.walk(path, topdown=False):
        for nom in noms:
            _erase_file(Path(dossier) / nom)
        for nom in sous:
            chemin = Path(dossier) / nom
            if os.path.islink(chemin):
                _erase_file(chemin)
            else:
                os.rmdir(chemin)
    os.rmdir(path)


def _tree_size(root: Path) -> int:
    total = 0
    for dossier, _sous, noms in os.walk(root):
        for nom in noms:
            try:
                total += os.lstat(Path(dossier) / nom).st_size
            except OSError:
                continue
    return total


def _fsync_tree(root: Path) -> None:
    for dossier, _sous, _noms in os.walk(root):
        _fsync_dir(Path(dossier))


def _is_locked(exc: BaseException) -> bool:
    """Vrai si `exc`, ou l'une de ses causes, est le refus d'une base
    SQLite verrouillée par un autre processus."""
    courant, vus = exc, 0
    while courant is not None and vus < 5:
        if isinstance(courant, sqlite3.OperationalError):
            texte = str(courant).lower()
            if "locked" in texte or "busy" in texte:
                return True
        courant = courant.__cause__ or courant.__context__
        vus += 1
    return False


@contextlib.contextmanager
def hold_writers(db_path: Path) -> Iterator[bool]:
    """Tient le verrou d'écriture SQLite de `db_path` (`BEGIN IMMEDIATE`)
    le temps du bloc et rend vrai ; rend faux, sans rien tenir, si un
    autre processus écrit encore au-delà de `STORE_BUSY_TIMEOUT_S`.

    Le verrou d'usage ne retient que les processus qui le prennent : un
    client lancé avant qu'il n'existe écrit sans lui. Sous ce verrou, ses
    écritures échouent (« database is locked ») au lieu de se perdre dans
    une copie bientôt effacée ; ses lectures continuent. Une base absente,
    ou trop abîmée pour être verrouillée, rend vrai sans rien tenir :
    personne n'y valide plus rien."""
    conn = None
    tenu = True
    if os.path.lexists(db_path):
        try:
            conn = sqlite3.connect(
                rw_uri(db_path),
                uri=True,
                timeout=store_mod.STORE_BUSY_TIMEOUT_S,
            )
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            tenu = not _is_locked(exc)
            if conn is not None:
                conn.close()
                conn = None
    try:
        yield tenu
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


# -- Reprise ------------------------------------------------------------


def recover(account_name: str, base: Path | None = None) -> str:
    """Achève ou défait une conversion interrompue, selon
    `store.recovery_plan`. L'appelant tient `cache_exclusive`.

    Rend "none", "rolled_back", "rolled_forward" ou "cleaned" ; lève
    `StoreError` (`mail_err_cache_convert_inconsistent`) sur un état
    impossible, sans rien toucher. Après toute action, `ctl/old` puis
    `ctl/new` sont retirés, et l'état EN DERNIER : un processus tué entre
    les deux laisse un état sans copies, que la reprise suivante solde.
    Chaque action est idempotente : un renommage fait se relit comme la
    ligne suivante de la table."""
    base = Path(base) if base is not None else default_base()
    nom = account_name
    racine = base / nom
    ctl = cache_ctl_dir(nom, base)
    ancienne, neuve = ctl / "old", ctl / "new"
    etat = read_convert_state(nom, base)
    if (
        etat is None
        and not os.path.lexists(ancienne)
        and not os.path.lexists(neuve)
    ):
        return "none"
    r = os.path.lexists(racine)
    o = os.path.lexists(ancienne / nom)
    n = os.path.lexists(neuve / nom)
    action, issue = recovery_plan(r, o, n, (etat or {}).get("phase"))
    if action == "inconsistent":
        raise StoreError(
            t("mail_err_cache_convert_inconsistent").format(path=ctl)
        )
    if action == "erase_new":
        secure_erase(neuve)
    elif action == "forward":
        if r:
            ancienne.mkdir(mode=0o700, exist_ok=True)
            os.rename(racine, ancienne / nom)
            _fsync_dir(base)
            _fsync_dir(ancienne)
        os.rename(neuve / nom, racine)
        _fsync_dir(base)
        secure_erase(ancienne)
    elif action == "restore_old":
        os.rename(ancienne / nom, racine)
        _fsync_dir(base)
        secure_erase(neuve)
    elif action == "erase_old":
        secure_erase(ancienne)
    secure_erase(ancienne)
    secure_erase(neuve)
    _fsync_dir(ctl)
    _remove_state(ctl)
    _logger.info("reprise de conversion : %s", issue)
    return issue


# -- Contrôles en lecture -----------------------------------------------


def _target_columns() -> dict:
    """Les colonnes d'un cache neuf, par table, dans l'ordre du schéma."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA)
        return {
            table: [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            for table in COPIED_TABLES
        }
    finally:
        conn.close()


def _check_schema(conn) -> None:
    """Refuse une table inconnue, ou une colonne de la source absente d'un
    cache neuf et de `LEGACY_SOURCE_COLUMNS` (`UnknownSchema`)."""
    cibles = _target_columns()
    for (nom,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ):
        if (
            nom.startswith("sqlite_")
            or nom == "messages_fts"
            or nom.startswith("messages_fts_")
        ):
            continue
        if nom not in cibles:
            raise UnknownSchema(f"table {nom}")
        for (colonne,) in (
            (r[1],) for r in conn.execute(f"PRAGMA table_info({nom})")
        ):
            if (
                colonne not in cibles[nom]
                and (nom, colonne) not in LEGACY_SOURCE_COLUMNS
            ):
                raise UnknownSchema(f"colonne {nom}.{colonne}")


# -- Copie --------------------------------------------------------------


class _Copier:
    """La traduction et la copie d'une source ouverte vers une cible.

    Les sels source sont la clé de la source, plus le sel clair quand la
    source est chiffrée (un cache mêlé porte des lignes salées en clair).
    `ids` et `adrs` associent une empreinte source à sa préimage ; ils sont
    construits avant que la cible n'existe, ce qui permet d'annoncer les
    pertes de reconnaissance avant d'écrire quoi que ce soit."""

    def __init__(self, src: Store, progress):
        self.src = src
        self.dst: Store | None = None
        self.progress = progress
        sels = [src._key or b"clear"]
        if src.mode != "clear" and b"clear" not in sels:
            sels.append(b"clear")
        self.sels = sels
        self.ids: dict[str, str] = {}
        self.adrs: dict[str, str] = {}
        self.legacy_values: set[str] = set()
        self.legacy_auto_sent = 0
        self.dropped = 0
        self.memo: dict[str, str] = {}
        self.auto_sent_map: list[tuple[str, int]] = []
        self.body_hashes: dict[tuple[str, int], str] = {}

    # -- Première passe --------------------------------------------------

    def _open(self, blob) -> str | None:
        if blob is None:
            return None
        return self.src._crypto.open(bytes(blob)).decode("utf-8", "replace")

    def _add_id(self, pre: str) -> None:
        if pre:
            for sel in self.sels:
                self.ids.setdefault(salted_hash(sel, pre), pre)

    def _add_address(self, adresse: str) -> None:
        adresse = (adresse or "").strip().lower()
        if adresse:
            for sel in self.sels:
                self.adrs.setdefault(
                    salted_hash(sel, "addr:" + adresse), adresse
                )

    def _add_addresses(self, texte: str | None) -> None:
        if not texte:
            return
        self._add_address(texte)
        for adresse in _addresses(texte):
            self._add_address(adresse)

    def first_pass(self) -> None:
        db = self.src._db()
        uidv = {
            r[0]: r[1]
            for r in db.execute("SELECT id, uidvalidity FROM folders")
        }
        for folder_id, uid, scelle, de, a in db.execute(
            "SELECT folder_id, uid, sealed_msgid, sealed_from, sealed_to"
            " FROM messages ORDER BY id"
        ):
            brut = self._open(scelle) or ""
            self._add_id(brut)
            self._add_id(brut.strip())
            if uidv.get(folder_id) is not None:
                self._add_id(f" uid:{int(uidv[folder_id])}:{int(uid)}")
            self._add_addresses(self._open(de))
            self._add_addresses(self._open(a))
        for ref, expediteur, cible in db.execute(
            "SELECT sealed_msg_ref, sealed_sender, sealed_target FROM rule_log"
        ):
            self._add_id(self._open(ref) or "")
            self._add_addresses(self._open(expediteur))
            self._add_addresses(self._open(cible))
        for (scelle,) in db.execute("SELECT sealed_msgid FROM auto_sent"):
            self._add_id((self._open(scelle) or "").strip())
        valeurs = [r[0] for r in db.execute("SELECT msg_key FROM rule_log")]
        valeurs += [
            r[0]
            for r in db.execute(
                "SELECT source_key FROM outbox WHERE source_key IS NOT NULL"
            )
        ]
        self.legacy_values = {
            v
            for v in valeurs
            if not v.startswith(LEGACY_KEY_PREFIX) and v not in self.ids
        }
        for (valeur,) in db.execute("SELECT msgid_hash FROM auto_sent"):
            if (
                not valeur.startswith(LEGACY_KEY_PREFIX)
                and valeur not in self.ids
            ):
                self.legacy_auto_sent += 1

    # -- Traductions -----------------------------------------------------

    def _seal(self, blob):
        if blob is None:
            return None
        return self.dst._crypto.seal(self.src._crypto.open(bytes(blob)))

    def _seal_text(self, texte: str) -> bytes:
        return self.dst._crypto.seal(texte.encode("utf-8"))

    def translate_key(self, valeur):
        """`msg_key` ou `source_key` → (valeur cible, préimage ou None)."""
        if valeur is None:
            return None, None
        if valeur.startswith(LEGACY_KEY_PREFIX):
            return valeur, None
        pre = self.ids.get(valeur)
        if valeur not in self.memo:
            if pre is not None:
                self.memo[valeur] = self.dst._msgid_hash(pre)
            else:
                self.memo[valeur] = LEGACY_KEY_PREFIX + _secrets.token_hex(16)
        return self.memo[valeur], pre

    def _verified_address(self, blob, valeur) -> str | None:
        texte = self._open(blob)
        if not texte:
            return None
        candidats = [texte.strip().lower(), *_addresses(texte)]
        for adresse in candidats:
            if adresse and any(
                salted_hash(sel, "addr:" + adresse) == valeur
                for sel in self.sels
            ):
                return adresse
        return None

    def translate_address(self, valeur, blob=None):
        if valeur is None:
            return None
        adresse = self._verified_address(blob, valeur) or self.adrs.get(valeur)
        if adresse is None:
            self.dropped += 1
            return None
        return self.dst.address_hash(adresse)

    def translate_id(self, valeur):
        if valeur is None:
            return None
        pre = self.ids.get(valeur)
        if pre is None:
            self.dropped += 1
            return None
        return self.dst._msgid_hash(pre)

    def translate_refs(self, valeur):
        if not valeur:
            return valeur
        jetons = [self.translate_id(j) for j in valeur.split()]
        gardes = [j for j in jetons if j]
        return " ".join(gardes) if gardes else None

    # -- Copie des tables ------------------------------------------------

    def _write(self, table, colonnes, lignes, sql_suffix=""):
        db = self.dst._db()
        sql = (
            f"INSERT INTO {table}({', '.join(colonnes)})"
            f" VALUES({', '.join('?' for _ in colonnes)}){sql_suffix}"
        )
        for debut in range(0, len(lignes), BATCH_ROWS):
            db.executemany(sql, lignes[debut : debut + BATCH_ROWS])

    def copy(self, total_rows: int) -> None:
        src_db, dst_db = self.src._db(), self.dst._db()
        cibles = _target_columns()
        self.done = 0
        self.total = total_rows

        def avance():
            self.done += 1
            if self.progress and self.done % PROGRESS_EVERY == 0:
                self.progress("rows", self.done, self.total)

        # meta : tout sauf ce que la base neuve écrit elle-même.
        lignes = [
            (k, v)
            for k, v in src_db.execute(
                "SELECT key, value FROM meta ORDER BY key"
            )
            if k not in _META_OWN_KEYS
        ]
        self._write("meta", ("key", "value"), lignes)
        if any(k == "cache_epoch" for k, _v in lignes):
            dst_db.execute(
                "INSERT OR REPLACE INTO meta(key, value)"
                " VALUES('cache_epoch_check', ?)",
                (self.dst._msgid_hash("cache_epoch"),),
            )
        dst_db.commit()
        for table in COPIED_TABLES[1:]:
            presentes = {
                r[1] for r in src_db.execute(f"PRAGMA table_info({table})")
            }
            for t_, colonne in LEGACY_SOURCE_COLUMNS:
                if t_ == table and colonne in presentes:
                    if src_db.execute(
                        f"SELECT 1 FROM {table} WHERE {colonne} IS NOT NULL LIMIT 1"
                    ).fetchone():
                        raise UnknownSchema(
                            f"colonne {table}.{colonne} non vide"
                        )
            colonnes = [c for c in cibles[table] if c in presentes]
            ordre = "ORDER BY id" if "id" in colonnes else ""
            transformer = getattr(self, f"_row_{table}", None)
            lignes = []
            for row in src_db.execute(
                f"SELECT {', '.join(colonnes)} FROM {table} {ordre}"
            ):
                valeurs = dict(zip(colonnes, row, strict=True))
                for colonne in SEALED_COLUMNS.get(table, ()):
                    if colonne in valeurs:
                        valeurs[colonne] = self._seal(valeurs[colonne])
                if transformer is not None:
                    transformer(valeurs, row, colonnes)
                lignes.append(tuple(valeurs[c] for c in colonnes))
                avance()
            suffixe = ""
            if table == "auto_sent":
                suffixe = (
                    " ON CONFLICT(msgid_hash) DO UPDATE SET"
                    " at = min(at, excluded.at),"
                    " rule_id = CASE WHEN coalesce(rule_id, '') = ''"
                    " THEN excluded.rule_id ELSE rule_id END,"
                    " sealed_msgid = coalesce(sealed_msgid, excluded.sealed_msgid)"
                )
            self._write(table, colonnes, lignes, suffixe)
            dst_db.commit()
        if self.progress:
            self.progress("rows", self.done, self.total)

    def _row_messages(self, v, row, colonnes):
        brut = (
            self._open(
                dict(zip(colonnes, row, strict=True)).get("sealed_msgid")
            )
            or ""
        )
        v["msgid_hash"] = self.dst._msgid_hash(brut)
        if "in_reply_to_hash" in v:
            v["in_reply_to_hash"] = self.translate_id(v["in_reply_to_hash"])
        if "references_hashes" in v:
            v["references_hashes"] = self.translate_refs(
                v["references_hashes"]
            )

    def _row_outbox(self, v, row, colonnes):
        if "source_key" in v:
            v["source_key"], _pre = self.translate_key(v["source_key"])

    def _row_rule_log(self, v, row, colonnes):
        source = dict(zip(colonnes, row, strict=True))
        v["msg_key"], pre = self.translate_key(source["msg_key"])
        if pre is not None and source.get("sealed_msg_ref") is None:
            v["sealed_msg_ref"] = self._seal_text(pre)
        expediteur = source.get("sender_hash")
        v["sender_hash"] = self.translate_address(
            expediteur, source.get("sealed_sender")
        )
        cible = source.get("target_hash")
        if cible is None:
            v["target_hash"] = None
        else:
            adresse = self._verified_address(
                source.get("sealed_target"), cible
            )
            if adresse is not None:
                v["target_hash"] = self.dst.address_hash(adresse)
            elif (
                expediteur is not None
                and cible == expediteur
                and v["sender_hash"]
            ):
                v["target_hash"] = v["sender_hash"]
            else:
                v["target_hash"] = self.translate_address(cible)

    def _row_auto_sent(self, v, row, colonnes):
        source = dict(zip(colonnes, row, strict=True))
        valeur = source["msgid_hash"]
        if valeur.startswith(LEGACY_KEY_PREFIX):
            cible = valeur
        else:
            pre = self.ids.get(valeur)
            if pre is not None:
                cible = self.dst._msgid_hash(pre)
                if source.get("sealed_msgid") is None:
                    v["sealed_msgid"] = self._seal_text(pre)
            else:
                cible = LEGACY_KEY_PREFIX + _secrets.token_hex(16)
        v["msgid_hash"] = cible
        self.auto_sent_map.append((cible, int(source["at"])))

    # -- Corps -----------------------------------------------------------

    def copy_bodies(self) -> int:
        presents = []
        for uid, dossier in self.src._db().execute(
            "SELECT m.uid, f.name FROM messages m JOIN folders f"
            " ON f.id = m.folder_id ORDER BY m.id"
        ):
            chemin = self.src._body_path(dossier, uid)
            if chemin.exists():
                presents.append((dossier, uid, chemin))
        total = len(presents)
        for rang, (dossier, uid, chemin) in enumerate(presents, start=1):
            clair = self.src._crypto.open(chemin.read_bytes())
            self.dst._write_body_file(dossier, uid, clair)
            self.body_hashes[(dossier, uid)] = hashlib.sha256(
                clair
            ).hexdigest()
            if self.progress and (rang % PROGRESS_EVERY == 0):
                self.progress("bodies", rang, total)
        if self.progress:
            self.progress("bodies", total, total)
        return total

    # -- Vérification ----------------------------------------------------

    def verify(self, target: str) -> None:
        src_db, dst_db = self.src._db(), self.dst._db()
        dst = self.dst
        if dst_db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise _VerifyFailed("quick_check")
        compte = lambda db, table: db.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0]  # noqa: E731
        for table in ("folders", "messages", "outbox", "rule_log"):
            if compte(src_db, table) != compte(dst_db, table):
                raise _VerifyFailed(f"lignes {table}")
        if (
            compte(dst_db, "auto_sent")
            != compte(src_db, "auto_sent") - self.merged()
        ):
            raise _VerifyFailed("lignes auto_sent")
        for cible, at in self.auto_sent_map:
            ligne = dst_db.execute(
                "SELECT at FROM auto_sent WHERE msgid_hash = ?", (cible,)
            ).fetchone()
            if ligne is None or ligne[0] > at:
                raise _VerifyFailed("auto_sent")
        src_meta = dict(
            src_db.execute("SELECT key, value FROM meta").fetchall()
        )
        dst_meta = dict(
            dst_db.execute("SELECT key, value FROM meta").fetchall()
        )
        attendu = len([k for k in src_meta if k not in _META_OWN_KEYS]) + 2
        if "cache_epoch" in src_meta:
            attendu += 1
            if dst_meta.get("cache_epoch") != src_meta[
                "cache_epoch"
            ] or dst_meta.get("cache_epoch_check") != dst._msgid_hash(
                "cache_epoch"
            ):
                raise _VerifyFailed("époque")
        if len(dst_meta) != attendu or dst_meta.get("cache_mode") != target:
            raise _VerifyFailed("meta")
        for table in ("folders", "messages", "outbox", "rule_log"):
            self._verify_rows(table)
        for (dossier, uid), empreinte in self.body_hashes.items():
            lu = dst.read_body(dossier, uid)
            if lu is None or hashlib.sha256(lu).hexdigest() != empreinte:
                raise _VerifyFailed("corps")
        fts = dst_db.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'messages_fts'"
        ).fetchone()
        if target == "clear":
            if fts is None or compte(dst_db, "messages_fts") != compte(
                dst_db, "messages"
            ):
                raise _VerifyFailed("index")
        elif fts is not None:
            raise _VerifyFailed("index")

    def merged(self) -> int:
        return len(self.auto_sent_map) - len(
            {c for c, _at in self.auto_sent_map}
        )

    def _verify_rows(self, table: str) -> None:
        src_db, dst_db = self.src._db(), self.dst._db()
        src_cols = {
            r[1] for r in src_db.execute(f"PRAGMA table_info({table})")
        }
        dst_cols = [
            r[1] for r in dst_db.execute(f"PRAGMA table_info({table})")
        ]
        colonnes = [c for c in dst_cols if c in src_cols]
        scellees = SEALED_COLUMNS.get(table, ())
        empreintes = HASHED_COLUMNS.get(table, ())
        requete = f"SELECT {', '.join(colonnes)} FROM {table} ORDER BY id"
        dst_rows = dst_db.execute(requete)
        for src_row in src_db.execute(requete):
            dst_row = dst_rows.fetchone()
            if dst_row is None:
                raise _VerifyFailed(f"ligne {table}")
            a = dict(zip(colonnes, src_row, strict=True))
            b = dict(zip(colonnes, dst_row, strict=True))
            for colonne in colonnes:
                if colonne in empreintes:
                    continue
                if colonne in scellees:
                    if (
                        a[colonne] is None
                        and (table, colonne) in _FILLED_PREIMAGES
                    ):
                        continue
                    ouvert_a = (
                        None
                        if a[colonne] is None
                        else self.src._crypto.open(bytes(a[colonne]))
                    )
                    ouvert_b = (
                        None
                        if b[colonne] is None
                        else self.dst._crypto.open(bytes(b[colonne]))
                    )
                    if ouvert_a != ouvert_b:
                        raise _VerifyFailed(f"{table}.{colonne}")
                elif a[colonne] != b[colonne]:
                    raise _VerifyFailed(f"{table}.{colonne}")
            if table == "messages":
                brut = self._open_dst(b.get("sealed_msgid")) or ""
                if b["msgid_hash"] != self.dst._msgid_hash(brut):
                    raise _VerifyFailed("messages.msgid_hash")
            if table == "rule_log" and not b["msg_key"].startswith(
                LEGACY_KEY_PREFIX
            ):
                ref = self._open_dst(b.get("sealed_msg_ref"))
                if ref is None or b["msg_key"] != self.dst._msgid_hash(ref):
                    raise _VerifyFailed("rule_log.msg_key")
        if dst_rows.fetchone() is not None:
            raise _VerifyFailed(f"ligne {table}")

    def _open_dst(self, blob) -> str | None:
        if blob is None:
            return None
        return self.dst._crypto.open(bytes(blob)).decode("utf-8", "replace")


# -- Conversion ---------------------------------------------------------


def _is_disk_full(exc: BaseException) -> bool:
    courant, vus = exc, 0
    while courant is not None and vus < 5:
        if isinstance(courant, OSError) and courant.errno in (
            errno.ENOSPC,
            errno.EDQUOT,
        ):
            return True
        if (
            isinstance(courant, sqlite3.OperationalError)
            and "full" in str(courant).lower()
        ):
            return True
        courant = courant.__cause__ or courant.__context__
        vus += 1
    return False


def _space(base: Path, racine: Path) -> tuple[int, int]:
    """(espace exigé, espace libre), en octets."""
    taille = _tree_size(racine)
    besoin = taille + taille // 5 + SPACE_MARGIN_BYTES
    return besoin, shutil.disk_usage(base).free


def _no_space(nom: str, base: Path, racine: Path) -> ConvertError:
    besoin, libre = _space(base, racine)
    return _error(
        "no_space",
        nom,
        need=math.ceil(besoin / _MIB),
        free=math.ceil(libre / _MIB),
    )


def convert_cache(
    account,
    target: str,
    *,
    secrets,
    base: Path | None = None,
    rules_lock_wait: float = storage.UI_LOCK_WAIT_S,
    progress: Callable[[str, int, int], None] | None = None,
    confirm_losses: Callable[[int, int], bool] | None = None,
    on_committed: Callable[[str], None] | None = None,
    fault: Callable[[str], None] | None = None,
) -> ConvertResult:
    """Recopie le cache persistant du compte dans le mode `target`.

    Sous le verrou de compte des règles (attente `rules_lock_wait`) puis le
    verrou d'usage du cache en exclusif, sans attente : une passe de règles
    en cours refuse (`busy_rules`), un cache ouvert ailleurs aussi
    (`busy_open`). Dès l'ouverture de la source et jusqu'à l'effacement de
    l'ancienne copie, son verrou d'écriture SQLite est tenu
    (`hold_writers`) ; un processus qui y écrit au-delà du délai refuse
    aussi (`busy_open`). `confirm_losses(lignes, envois)` est appelé au
    plus une fois, avant toute écriture dans la copie neuve, quand des
    lignes du journal ou des envois inscrits ne retrouveront plus leur
    message ; faux annule (`declined`). `on_committed(target)` est appelé
    dès que l'état `swapping` est écrit, avant le premier renommage, ou
    après la reprise quand cette écriture a levé une fois l'état en
    place : il règle le compte sur la cible ; son exception est consignée
    et rendue par `ConvertResult.mode_saved`. `progress(étape, fait, total)` reçoit
    "rows" puis "bodies". `fault(point)` sert aux tests seulement.

    Lève `ConvertError` : avant le point de non-retour, la source est
    intacte et la copie neuve effacée ; après, seulement `incomplete`,
    avec `committed` vrai. Un Ctrl-C pendant la copie efface la copie
    neuve puis remonte tel quel.
    """
    if target not in PERSISTENT_MODES:
        raise ValueError(target)
    base = Path(base) if base is not None else default_base()
    nom = account.name
    with file_lock(
        storage.lock_path(nom, base), wait=rules_lock_wait
    ) as regles:
        if not regles:
            raise _error("busy_rules", nom)
        with cache_exclusive(nom, base) as tenu:
            if not tenu:
                raise _error("busy_open", nom)
            return _convert_locked(
                account,
                target,
                secrets=secrets,
                base=base,
                progress=progress,
                confirm_losses=confirm_losses,
                on_committed=on_committed,
                fault=fault or (lambda _point: None),
            )


@dataclass
class _Run:
    """Ce qu'une conversion sait d'elle-même entre ses étapes."""

    account: object
    target: str
    secrets: object
    base: Path
    source: str = ""
    resealed: bool = False
    started: int = 0
    # Ce qui doit tenir jusqu'à la fin de l'échange (`hold_writers`).
    pile: contextlib.ExitStack | None = None

    @property
    def nom(self) -> str:
        return self.account.name

    @property
    def racine(self) -> Path:
        return self.base / self.nom

    @property
    def ctl(self) -> Path:
        return cache_ctl_dir(self.nom, self.base)


def _convert_locked(
    account,
    target,
    *,
    secrets,
    base,
    progress,
    confirm_losses,
    on_committed,
    fault,
) -> ConvertResult:
    run = _Run(account, target, secrets, base, started=int(time.time()))
    recover(run.nom, base)
    _check_before_writing(run)
    with contextlib.ExitStack() as pile:
        run.pile = pile
        copieur, bodies, compte = _build_copy(
            run, progress, confirm_losses, fault
        )
        mode_saved = _swap(run, on_committed, fault)
    resultat = ConvertResult(
        source=run.source,
        target=target,
        messages=compte["messages"],
        bodies=bodies,
        outbox=compte["outbox"],
        rule_log=compte["rule_log"],
        auto_sent=compte["auto_sent"],
        legacy_keys=len(copieur.legacy_values),
        legacy_auto_sent=copieur.legacy_auto_sent,
        merged_auto_sent=copieur.merged(),
        dropped_hashes=copieur.dropped,
        resealed=run.resealed,
        mode_saved=mode_saved,
    )
    _logger.info(
        "cache converti %s → %s : %d messages, %d corps, %d lignes de journal,"
        " %d clés héritées, %d envois hérités, %d envois fusionnés",
        run.source,
        target,
        resultat.messages,
        resultat.bodies,
        resultat.rule_log,
        resultat.legacy_keys,
        resultat.legacy_auto_sent,
        resultat.merged_auto_sent,
    )
    return resultat


def _check_before_writing(run: _Run) -> None:
    """Tous les refus qui ne demandent qu'une lecture : mode inscrit,
    racine, espace, schéma, clé de la source. Rien n'est écrit : les
    octets de `cache.db` restent ceux d'avant. Fixe `run.source` et
    `run.resealed`."""
    nom, target, racine = run.nom, run.target, run.racine
    source = inscribed_mode(run.account, run.base)
    if source is None:
        raise _error("no_cache", nom, target=target)
    if source == PROBE_UNKNOWN:
        raise _error("unreadable_cache", nom)
    if source not in PERSISTENT_MODES:
        raise _error("invalid_mode", nom, inscribed=shown_mode(source))
    run.source = source
    db_path = racine / "cache.db"
    if source == target:
        with probe_connection(db_path) as conn:
            restes = conn is not None and has_clear_residue(conn, racine)
        if target != "encrypted" or not restes:
            raise _error("same_mode", nom, target=target)
        run.resealed = True
    info = os.lstat(racine)
    if stat.S_ISLNK(info.st_mode) or info.st_dev != os.lstat(run.ctl).st_dev:
        raise _error("unsupported_root", nom)
    besoin, libre = _space(run.base, racine)
    if libre < besoin:
        raise _no_space(nom, run.base, racine)
    try:
        with probe_connection(db_path) as conn:
            if conn is not None:
                _check_schema(conn)
    except (UnknownSchema, sqlite3.Error) as exc:
        _logger.error("conversion de cache refusée : %s", exc)
        raise ConvertError(
            "failed", f"{t('mail_cache_convert_failed')} {type(exc).__name__}"
        ) from exc
    if source == "encrypted" and (
        run.secrets is None
        or run.secrets.get(run.account.cache_key_ref()) is None
    ):
        raise _error("no_key", nom)


def _new_target_key(run: _Run) -> bytes | None:
    """La clé à tirer pour une cible chiffrée quand le coffre n'en a pas.
    Elle n'est écrite au coffre qu'une fois la copie vérifiée : une
    conversion abandonnée n'y laisse rien."""
    if (
        run.target == "encrypted"
        and run.source == "clear"
        and run.secrets is not None
        and run.secrets.get(run.account.cache_key_ref()) is None
    ):
        return new_key()
    return None


def _build_copy(run: _Run, progress, confirm_losses, fault):
    """Construit et vérifie la copie neuve sous `ctl/new`. Rend le
    copieur, le nombre de corps et les comptes de la cible. Toute
    exception ferme les deux caches, efface la copie neuve et retire
    l'état ; un Ctrl-C remonte tel quel, le reste en `ConvertError`."""
    nom, ctl = run.nom, run.ctl
    neuve = ctl / "new"
    src = Store(
        run.account,
        mode=run.source,
        secrets=run.secrets,
        base=run.base,
        lock_held=True,
    )
    dst = None
    etat_ecrit = False
    try:
        src.open()
        if not run.pile.enter_context(hold_writers(src.root / "cache.db")):
            raise _error("busy_open", nom)
        copieur = _Copier(src, progress)
        copieur.first_pass()
        pertes = (len(copieur.legacy_values), copieur.legacy_auto_sent)
        if (
            confirm_losses is not None
            and any(pertes)
            and not confirm_losses(*pertes)
        ):
            raise _error("declined", nom)
        _write_state(ctl, "building", run.source, run.target, run.started)
        etat_ecrit = True
        secure_erase(neuve)
        neuve.mkdir(mode=0o700)
        cle_neuve = _new_target_key(run)
        dst = Store(
            run.account,
            mode=run.target,
            key=cle_neuve,
            secrets=run.secrets,
            base=neuve,
            lock_held=True,
        )
        dst.open()
        copieur.dst = dst
        db = src._db()
        copieur.copy(
            sum(
                db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in COPIED_TABLES[1:]
            )
        )
        bodies = copieur.copy_bodies()
        if run.target == "clear":
            dst._reindexer()
        dst._db().commit()
        copieur.verify(run.target)
        if cle_neuve is not None:
            _store_new_key(run.secrets, run.account.cache_key_ref(), cle_neuve)
        compte = {
            table: dst._db()
            .execute(f"SELECT count(*) FROM {table}")
            .fetchone()[0]
            for table in ("messages", "outbox", "rule_log", "auto_sent")
        }
        dst.close()
        src.close()
        _fsync_tree(neuve)
        fault("built")
    except BaseException as exc:
        for magasin in (dst, src):
            if magasin is not None:
                try:
                    magasin.close()
                except Exception:
                    pass
        if etat_ecrit or os.path.lexists(neuve):
            secure_erase(neuve)
            _remove_state(ctl)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        traduite = _map_before_swap(exc, nom, run.base, run.racine)
        if traduite is exc:
            raise
        raise traduite from exc
    return copieur, bodies, compte


def _swapping_written(run: _Run) -> bool:
    """Vrai si `convert.json` dit `swapping` ou `cleaning` : la reprise
    mènera la racine à la cible."""
    try:
        etat = read_convert_state(run.nom, run.base)
    except (StoreError, OSError):
        return False
    return etat is not None and etat.get("phase") in ("swapping", "cleaning")


def _swap(run: _Run, on_committed, fault) -> bool:
    """Le point de non-retour puis l'échange. Rend faux si `on_committed`
    a levé.

    Le point de non-retour est l'état `swapping` lu sur le disque, même
    quand son écriture lève après coup (synchronisation du dossier) :
    `on_committed` est alors appelé après la reprise. Un Ctrl-C laisse la
    fin à la prochaine ouverture (`incomplete`, `committed` selon
    l'état) ; toute autre panne est achevée ou défaite par `recover` sous
    l'exclusif encore tenu. Défaite, elle est rendue comme une panne
    d'avant l'échange ; achevée hors de la cible, ou reprise en échec,
    elle donne `incomplete`."""
    nom, ctl, racine, base = run.nom, run.ctl, run.racine, run.base
    neuve, ancienne = ctl / "new", ctl / "old"
    suivi = {"engage": False, "regle": False, "saved": True}

    def regler() -> None:
        suivi["regle"] = True
        if on_committed is None:
            return
        try:
            on_committed(run.target)
        except Exception as exc:
            suivi["saved"] = False
            _logger.error(
                "conversion du cache de %s : mode du compte non"
                " enregistré (%s)",
                nom,
                exc,
            )

    try:
        _write_state(ctl, "swapping", run.source, run.target, run.started)
        suivi["engage"] = True
        regler()
        fault("marked")
        ancienne.mkdir(mode=0o700, exist_ok=True)
        os.rename(racine, ancienne / nom)
        _fsync_dir(base)
        _fsync_dir(ancienne)
        fault("moved_old")
        os.rename(neuve / nom, racine)
        _fsync_dir(base)
        fault("moved_new")
        _write_state(ctl, "cleaning", run.source, run.target, run.started)
        secure_erase(ancienne)
        fault("erased")
        secure_erase(neuve)
        _remove_state(ctl)
    except KeyboardInterrupt:
        engage = suivi["engage"] or _swapping_written(run)
        raise _error(
            "incomplete", nom, committed=engage, target=run.target
        ) from None
    except Exception as exc:
        engage = suivi["engage"] or _swapping_written(run)
        _logger.warning(
            "conversion du cache de %s : échange interrompu (%s)", nom, exc
        )
        try:
            recover(nom, base)
        except Exception as reprise:
            _logger.error("reprise de conversion impossible : %s", reprise)
            raise _error(
                "incomplete", nom, committed=engage, target=run.target
            ) from exc
        if not engage:
            # La reprise a remis la source en racine et effacé la copie.
            raise _map_before_swap(exc, nom, base, racine) from exc
        if inscribed_mode(run.account, base) != run.target:
            raise _error(
                "incomplete", nom, committed=True, target=run.target
            ) from exc
        if not suivi["regle"]:
            regler()
    return suivi["saved"]


def _store_new_key(secrets, ref: str, cle: bytes) -> None:
    """Écrit au coffre la clé de la copie neuve, sous le verrou du coffre
    quand il en a un (`update`). Une autre clé apparue entre-temps lève
    `StoreError` : la copie neuve, scellée par la nôtre, serait
    illisible."""
    encodee = base64.b64encode(cle).decode()
    update = getattr(secrets, "update", None)
    if callable(update):
        gardee = update(ref, lambda courante: courante or encodee)
    else:
        if secrets.get(ref) is None:
            secrets.set(ref, encodee)
        gardee = secrets.get(ref)
    if gardee != encodee:
        raise StoreError("une autre clé du cache est apparue au coffre")


def _map_before_swap(
    exc: BaseException, nom: str, base: Path, racine: Path
) -> ConvertError:
    """L'exception levée avant le point de non-retour, en `ConvertError`.
    Le texte d'une cause inattendue va à `mail.log`, jamais à l'écran : il
    peut citer une adresse."""
    if isinstance(exc, ConvertError):
        return exc
    if isinstance(exc, CacheKeyMissing):
        return _error("no_key", nom)
    if isinstance(exc, CryptoError) or isinstance(exc.__cause__, CryptoError):
        return _error("unreadable", nom)
    if _is_disk_full(exc):
        return _no_space(nom, base, racine)
    if _is_locked(exc):
        return _error("busy_open", nom)
    if isinstance(exc, _VerifyFailed):
        _logger.error(
            "conversion du cache de %s : vérification refusée (%s)", nom, exc
        )
        return _error("verify_failed", nom)
    _logger.error("conversion du cache de %s annulée : %s", nom, exc)
    return ConvertError(
        "failed", f"{t('mail_cache_convert_failed')} {type(exc).__name__}"
    )
