#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cache courriel local : une base SQLite et des fichiers .eml par compte.

Une racine par compte, jamais une base partagée : c'est ce qui permet à un
compte d'être éphémère pendant qu'un autre persiste, sans mélanger deux modes
de chiffrement dans les mêmes lignes.

Ce qui reste EN CLAIR dans la base — uid, dossier, date, drapeaux, taille —
est exactement ce dont le SQL a besoin pour trier et filtrer. Ce qui identifie
des personnes — expéditeur, destinataires, sujet, extrait, Message-ID — est
scellé. Le Message-ID a en plus un haché salé par la clé, pour qu'on puisse
recoller les fils de discussion sans le lire.
"""

from __future__ import annotations

import base64
import contextlib
import email.utils
import fcntl
import functools
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import stat
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from script.todo.mail.crypto import (
    CLEAR_MAGIC,
    SEALED_MAGIC,
    build_crypto,
    new_key,
)
from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

SCHEMA_VERSION = 6
EPHEMERAL_PREFIX = "erplibre-mail-"
VALID_MODES = ("clear", "encrypted", "ephemeral")
# Les modes qui écrivent sur le disque : seuls ceux-là s'inscrivent dans
# une racine persistante et se convertissent l'un en l'autre.
PERSISTENT_MODES = ("clear", "encrypted")
# La clé de `meta` qui porte le mode inscrit.
CACHE_MODE_KEY = "cache_mode"
# Dossier de contrôle des caches, sous la base ; le point initial
# n'appartient à aucun compte.
CACHE_CTL_DIRNAME = ".cache_ctl"
CACHE_LOCK_NAME = "lock"
CONVERT_STATE_NAME = "convert.json"
# Les phases d'une conversion, dans l'ordre où elles s'écrivent dans
# `convert.json`.
CONVERT_PHASES = ("building", "swapping", "cleaning")
# Préfixe d'une clé de journal dont la préimage est perdue : elle ne
# correspond plus à aucun message.
LEGACY_KEY_PREFIX = "legacy:"
# Ce que rend la sonde quand `cache.db` existe mais ne se lit pas (base
# abîmée, occupée) : distinct de None, qui dit « aucun cache ». Hors
# `VALID_MODES`, il n'est jamais pris pour un mode.
PROBE_UNKNOWN = "<unreadable>"
# Colonnes qu'un cache ancien garde après migration et qu'un cache neuf
# n'a pas ; la conversion les laisse derrière elle. Chacune est vide
# (NULL) après migration.
LEGACY_SOURCE_COLUMNS = {("outbox", "last_error")}
# Les colonnes scellées de chaque table, que la conversion descelle puis
# rescelle et que la détection du mode lit.
SEALED_COLUMNS = {
    "messages": (
        "sealed_msgid",
        "sealed_from",
        "sealed_to",
        "sealed_subject",
        "sealed_snippet",
    ),
    "outbox": ("sealed_raw", "sealed_to", "sealed_subject", "sealed_error"),
    "rule_log": (
        "sealed_sender",
        "sealed_subject",
        "sealed_msg_ref",
        "sealed_target",
    ),
    "auto_sent": ("sealed_msgid",),
}
# Les colonnes d'empreintes salées par la clé, que la conversion
# recalcule ou traduit.
HASHED_COLUMNS = {
    "messages": ("msgid_hash", "in_reply_to_hash", "references_hashes"),
    "outbox": ("source_key",),
    "rule_log": ("msg_key", "sender_hash", "target_hash"),
    "auto_sent": ("msgid_hash",),
}

# Les issues du journal des règles qui comptent comme un ENVOI pour la limite
# par expéditeur : un message en file ou retenu partira, ou attend qu'on
# l'approuve, et répondre de nouveau entre-temps ferait deux réponses.
RULE_LOG_SEND_OUTCOMES = ("pending", "sent", "partial", "queued", "held")
# Issues hors `RULE_LOG_SEND_OUTCOMES` qui comptent pour la limite par
# expéditeur : un envoi fait par une autre machine, ou peut-être parti.
RULE_LOG_SEND_LIKE = (
    ("skipped", "claimed_elsewhere"),
    ("skipped", "claim_uncertain"),
    ("failed", "send_uncertain"),
)
# Les états d'une revendication locale ; `retry` et `intent` ne sont pas
# définitifs.
RULE_CLAIM_STATES = ("retry", "intent", "owned", "lost", "unclaimed")
RULE_CLAIM_FINAL = ("owned", "lost", "unclaimed")
# Les issues définitives : `rule_log_set_outcome` ne les modifie plus.
# `partial` (message parti vers une partie de ses destinataires) n'avance
# que par `rule_log_rcpt_result`, `rule_log_retry_closed` et
# `rule_log_retry_narrowed`.
RULE_LOG_TERMINAL = ("sent", "partial", "skipped", "failed", "expired")
# Les issues d'une ligne dont le message est réellement parti, vers tous
# ses destinataires ou une partie : ce que comptent les plafonds au départ.
RULE_LOG_DEPARTED = ("sent", "partial")
OUTBOX_MAX_ATTEMPTS = 3
# Types d'une entrée automatique de la file ; `auto_redirect` porte son
# enveloppe dans `sealed_to`.
OUTBOX_AUTO_KINDS = ("auto_reply", "auto_forward", "auto_redirect")
# Préfixe des octets scellés d'une `auto_redirect` : une ligne vide. Un code
# qui lit l'entrée comme un message (sans connaître ce type) n'y trouve
# alors aucun en-tête, donc aucun destinataire, et n'envoie rien ; sans lui,
# il enverrait l'original aux To/Cc d'origine au lieu de l'enveloppe.
# `queued_raw` le retire.
OUTBOX_REDIRECT_GUARD = b"\r\n"
# Une réservation de la file plus vieille que ce délai, en secondes, est
# celle d'un processus mort en plein envoi : une autre vidange la reprend.
OUTBOX_CLAIM_STALE_S = 600
# Intervalle, en secondes, auquel un envoi en cours rafraîchit sa
# réservation (`outbox_claim_refresh`) : bien en deçà de
# `OUTBOX_CLAIM_STALE_S`, un envoi lent, vivant, n'est jamais repris.
OUTBOX_CLAIM_REFRESH_S = 60
# Attente, en secondes, d'une base tenue en écriture par un autre processus
# (le client et le service partagent `cache.db`) avant `database is locked`.
# Valeur par défaut de `sqlite3`, rendue explicite : aucun écrivain public
# ne garde de transaction ouverte, l'attente réelle se compte donc en
# millisecondes.
STORE_BUSY_TIMEOUT_S = 5.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS folders (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  display     TEXT,
  role        TEXT,
  uidvalidity INTEGER,
  uidnext     INTEGER,
  last_uid    INTEGER NOT NULL DEFAULT 0,
  total       INTEGER NOT NULL DEFAULT 0,
  unseen      INTEGER NOT NULL DEFAULT 0,
  synced_at   INTEGER
);
-- v6 : `received_at` est l'INTERNALDATE du serveur, `seen_at` le moment où
-- le cache a VU le message passer à lu ; NULL quand il est inconnu.
CREATE TABLE IF NOT EXISTS messages (
  id             INTEGER PRIMARY KEY,
  folder_id      INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  uid            INTEGER NOT NULL,
  date           INTEGER,
  size           INTEGER,
  flags          TEXT,
  has_body       INTEGER NOT NULL DEFAULT 0,
  msgid_hash     TEXT,
  sealed_msgid   BLOB,
  sealed_from    BLOB,
  sealed_to      BLOB,
  sealed_subject BLOB,
  sealed_snippet BLOB,
  -- v2, fils de discussion. Des EMPREINTES, jamais les identifiants
  -- bruts : `msgid_hash` existe déjà pour ça, et en mode `encrypted`
  -- écrire des Message-ID en clair rendrait le chiffrement inutile pour
  -- relier les messages entre eux.
  in_reply_to_hash TEXT,
  references_hashes TEXT,
  received_at    INTEGER,
  seen_at        INTEGER,
  UNIQUE(folder_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_msg_date ON messages(folder_id, date DESC);
-- v4 : file d'attente d'envoi. Le message brut est SCELLÉ comme le reste —
-- il porte le corps entier, et un cache chiffré qui laisserait ses envois
-- en clair protégerait tout sauf ce qu'on vient d'écrire.
-- v5 : `sealed_error` l'est pour la même raison. Un refus SMTP cite le
-- destinataire qu'il refuse (« 550 <adresse> … ») : gardé en clair, il rend
-- lisible l'adresse que la colonne d'à côté protège, et c'est le serveur qui
-- l'y écrit.
-- Aucun commentaire DANS la parenthèse : SQLite reconstruit le `CREATE` pour
-- un `ALTER TABLE … DROP COLUMN`, et une ligne `--` restée à l'intérieur le
-- fait échouer sur « incomplete input ».
-- v6 : `kind` distingue l'envoi manuel de la réponse d'une règle
-- (`rule_id`, `source_key` = clé du message d'origine dans `rule_log`).
-- `expires_at` borne l'attente d'une réponse automatique, `max_attempts` et
-- `perm_attempts` comptent les refus définitifs, `claimed_at` réserve une
-- entrée à la vidange qui l'envoie.
-- `kind` vaut `manual`, ou l'un des types automatiques : `auto_reply`
-- (réponse), `auto_forward` (transfert, enveloppe dans les octets),
-- `auto_redirect` (redirection, enveloppe dans `sealed_to`).
-- `retry` vaut 1 pour le nouvel essai des destinataires refusés
-- temporairement d'un envoi parti en partie ; son enveloppe est dans
-- `sealed_to`, quel que soit `kind`.
CREATE TABLE IF NOT EXISTS outbox (
  id            INTEGER PRIMARY KEY,
  created_at    INTEGER NOT NULL,
  sealed_raw    BLOB NOT NULL,
  sealed_to     BLOB,
  sealed_subject BLOB,
  held          INTEGER NOT NULL DEFAULT 0,
  attempts      INTEGER NOT NULL DEFAULT 0,
  sealed_error  BLOB,
  kind          TEXT NOT NULL DEFAULT 'manual',
  rule_id       TEXT,
  source_key    TEXT,
  expires_at    INTEGER,
  max_attempts  INTEGER NOT NULL DEFAULT 3,
  perm_attempts INTEGER NOT NULL DEFAULT 0,
  claimed_at    INTEGER,
  retry         INTEGER NOT NULL DEFAULT 0
);
-- v6 : journal des règles, une ligne par (règle, message). Écrit AVANT
-- l'envoi : UNIQUE(rule_id, msg_key) rend l'envoi « au plus une fois »
-- entre processus. Expéditeur et sujet scellés, clés hachées.
-- Un départ refusé en partie y laisse des CODES SMTP, jamais d'adresse :
-- `rcpt_total` est la taille de l'enveloppe du premier départ,
-- `rcpt_dropped` les codes des destinataires abandonnés, `rcpt_pending`
-- ceux qui attendent dans l'entrée de nouvel essai (« 450,550 »).
-- `retry_sent_at` est le dernier départ d'un nouvel essai ; `sent_at`
-- reste le premier départ.
-- `sealed_msg_ref` et `sealed_target` sont les préimages scellées de
-- `msg_key` et `target_hash`, pour recalculer ces empreintes sous un autre
-- sel.
CREATE TABLE IF NOT EXISTS rule_log (
  id             INTEGER PRIMARY KEY,
  rule_id        TEXT NOT NULL,
  msg_key        TEXT NOT NULL,
  sender_hash    TEXT,
  target_hash    TEXT,
  fingerprint    TEXT,
  at             INTEGER NOT NULL,
  received_at    INTEGER,
  outcome        TEXT NOT NULL,
  reason         TEXT,
  queue_id       INTEGER,
  sealed_sender  BLOB,
  sealed_subject BLOB,
  sent_at        INTEGER,
  rcpt_total     INTEGER,
  rcpt_dropped   TEXT,
  rcpt_pending   TEXT,
  retry_sent_at  INTEGER,
  sealed_msg_ref BLOB,
  sealed_target  BLOB,
  UNIQUE(rule_id, msg_key)
);
CREATE INDEX IF NOT EXISTS idx_rule_log_sender
  ON rule_log(rule_id, sender_hash, at);
CREATE INDEX IF NOT EXISTS idx_rule_log_target
  ON rule_log(rule_id, target_hash, at);
CREATE INDEX IF NOT EXISTS idx_rule_log_at ON rule_log(at);
-- v6 : empreintes des Message-ID que les règles ont émis ; les
-- statistiques de réponse excluent ces envois.
-- `sealed_msgid` est la préimage scellée de `msgid_hash`, pour recalculer
-- cette empreinte sous un autre sel.
CREATE TABLE IF NOT EXISTS auto_sent (
  msgid_hash   TEXT PRIMARY KEY,
  rule_id      TEXT,
  at           INTEGER NOT NULL,
  sealed_msgid BLOB
);
-- Revendication côté serveur d'un message d'INBOX, une ligne par
-- (uidvalidity, uid) : `intent` est écrit avant le STORE du mot-clé,
-- `owned` quand le STORE est confirmé, `lost` quand le mot-clé était déjà
-- posé par un autre, `unclaimed` quand le serveur ne permet pas la
-- revendication, `retry` quand aucun STORE n'est en cours. `failures`
-- compte les passes dont la revendication a échoué. `mode` est celui du
-- serveur à ce moment. Ni scellé ni salé, et sans heure : un UID n'est
-- pas une donnée de message, et une heure le relierait à une action.
CREATE TABLE IF NOT EXISTS rule_claim (
  id          INTEGER PRIMARY KEY,
  uidvalidity INTEGER NOT NULL,
  uid         INTEGER NOT NULL,
  state       TEXT NOT NULL,
  mode        TEXT,
  failures    INTEGER NOT NULL DEFAULT 0,
  UNIQUE(uidvalidity, uid)
);
"""

# Les colonnes ajoutées à `messages` depuis sa forme d'origine, dans l'ordre
# où elles sont apparues, avec leur type.
MESSAGES_ADDED_COLUMNS = {
    "in_reply_to_hash": "TEXT",
    "references_hashes": "TEXT",
    "received_at": "INTEGER",
    "seen_at": "INTEGER",
}

# Les colonnes ajoutées à `outbox` par la v6, avec leur définition. SQLite
# accepte `NOT NULL` à l'`ADD COLUMN` quand un `DEFAULT` non nul
# l'accompagne : les lignes existantes reçoivent la valeur par défaut.
OUTBOX_V6_COLUMNS = {
    "kind": "TEXT NOT NULL DEFAULT 'manual'",
    "rule_id": "TEXT",
    "source_key": "TEXT",
    "expires_at": "INTEGER",
    "max_attempts": "INTEGER NOT NULL DEFAULT 3",
    "perm_attempts": "INTEGER NOT NULL DEFAULT 0",
    "claimed_at": "INTEGER",
}
# Les colonnes ajoutées à `outbox` après la v6, sans changer de version.
OUTBOX_ADDED_COLUMNS = {"retry": "INTEGER NOT NULL DEFAULT 0"}
# Les colonnes ajoutées à `rule_log` après sa création, sans changer de
# version, dans l'ordre où elles sont apparues.
RULE_LOG_ADDED_COLUMNS = {
    "sent_at": "INTEGER",
    "rcpt_total": "INTEGER",
    "rcpt_dropped": "TEXT",
    "rcpt_pending": "TEXT",
    "retry_sent_at": "INTEGER",
    "sealed_msg_ref": "BLOB",
    "sealed_target": "BLOB",
}
# Les colonnes ajoutées à `auto_sent` après sa création, sans changer de
# version.
AUTO_SENT_ADDED_COLUMNS = {"sealed_msgid": "BLOB"}


def _ensure_columns(conn) -> list[str]:
    """Ajoute les colonnes manquantes de `messages`. Renvoie les ajoutées.

    On lit les colonnes RÉELLES plutôt que `schema_version` : un
    `CREATE TABLE IF NOT EXISTS` ne touche pas une table déjà présente, donc
    un cache créé avant la v2 garde sa forme d'origine — et sa version
    stockée n'a jamais été relue par personne, donc rien ne garantit
    qu'elle dise la vérité. Se fier à ce qui EST plutôt qu'à ce qui est
    déclaré rend au passage la migration rejouable sans risque.
    """
    presentes = {
        row["name"] for row in conn.execute("PRAGMA table_info(messages)")
    }
    ajoutees = []
    for nom, genre in MESSAGES_ADDED_COLUMNS.items():
        if nom not in presentes:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {nom} {genre}")
            ajoutees.append(nom)
    # Après l'ALTER, jamais avant : sur un cache d'avant la v2 la colonne
    # n'existe pas encore quand `executescript(SCHEMA)` tourne, et un index
    # déclaré là-bas faisait échouer l'ouverture. Inconditionnel, pour
    # qu'un cache NEUF — qui ne migre rien — l'obtienne aussi.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_msg_reply"
        " ON messages(in_reply_to_hash)"
    )
    return ajoutees


def _ensure_rule_log_columns(conn) -> None:
    """Ajoute à un journal des règles chaque colonne de
    `RULE_LOG_ADDED_COLUMNS` qui lui manque, lu dans `PRAGMA table_info`
    comme pour `messages`. Les lignes existantes les gardent nulles :
    `at` tient lieu de `sent_at`, et une ligne sans décompte n'a vu aucun
    refus."""
    presentes = {
        row["name"] for row in conn.execute("PRAGMA table_info(rule_log)")
    }
    for nom, genre in RULE_LOG_ADDED_COLUMNS.items():
        if nom not in presentes:
            conn.execute(f"ALTER TABLE rule_log ADD COLUMN {nom} {genre}")


def _ensure_auto_sent_columns(conn) -> None:
    """Ajoute à `auto_sent` chaque colonne d'`AUTO_SENT_ADDED_COLUMNS` qui
    lui manque, lue dans `PRAGMA table_info`. Les lignes existantes la
    gardent nulle : leur préimage n'est pas connue."""
    presentes = {
        row["name"] for row in conn.execute("PRAGMA table_info(auto_sent)")
    }
    for nom, genre in AUTO_SENT_ADDED_COLUMNS.items():
        if nom not in presentes:
            conn.execute(f"ALTER TABLE auto_sent ADD COLUMN {nom} {genre}")


def _ensure_outbox_columns(conn) -> None:
    """Fait passer la file d'attente de la v4 à la v6.

    Les colonnes de la v6, puis celles d'`OUTBOX_ADDED_COLUMNS`,
    s'ajoutent si elles manquent, lues dans `PRAGMA table_info` comme pour
    `messages`.

    La v4 gardait `last_error` en clair. La migration ne peut pas sceller ce
    texte — il est déjà écrit en clair sur le disque, et le sceller n'en
    effacerait pas les traces — mais elle peut cesser de le garder. Effacer
    est le seul état honnête : la raison d'un échec vaut moins que l'adresse
    qu'elle expose.
    """
    presentes = {
        row["name"] for row in conn.execute("PRAGMA table_info(outbox)")
    }
    if "sealed_error" not in presentes:
        conn.execute("ALTER TABLE outbox ADD COLUMN sealed_error BLOB")
    for nom, definition in {
        **OUTBOX_V6_COLUMNS,
        **OUTBOX_ADDED_COLUMNS,
    }.items():
        if nom not in presentes:
            conn.execute(f"ALTER TABLE outbox ADD COLUMN {nom} {definition}")
    if "last_error" in presentes:
        conn.execute("UPDATE outbox SET last_error = NULL")


# Les colonnes d'une entrée de file que lit `Store.outbox`, octets exclus.
_OUTBOX_COLONNES = (
    "id, created_at, sealed_to, sealed_subject, held, attempts,"
    " sealed_error, kind, rule_id, source_key, expires_at, max_attempts,"
    " perm_attempts, claimed_at, retry"
)


class StoreError(Exception):
    """Cache inutilisable : clé manquante, base corrompue, disque refusé."""


def shown_mode(value) -> str:
    """Un mode tel qu'un message le montre : la valeur si elle est l'un de
    `VALID_MODES`, sinon sa `repr` tronquée à 20 caractères."""
    return value if value in VALID_MODES else repr(value)[:20]


class CacheModeMismatch(StoreError):
    """Ouverture refusée : le cache est inscrit dans un autre mode que
    celui demandé. `account`, `inscribed` (valeur lue, éventuellement
    hors `VALID_MODES`) et `requested` sont des attributs ; le texte est
    `mail_err_cache_mode_mismatch` formaté."""

    _TEXT_KEY = "mail_err_cache_mode_mismatch"

    def __init__(self, account: str, inscribed: str, requested: str):
        self.account = account
        self.inscribed = inscribed
        self.requested = requested
        super().__init__(
            t(self._TEXT_KEY).format(
                account=account,
                inscribed=shown_mode(inscribed),
                requested=shown_mode(requested),
            )
        )


class CacheModeInvalid(CacheModeMismatch):
    """Ouverture refusée : le cache porte une inscription hors
    `PERSISTENT_MODES` (version future, base retouchée, `ephemeral` dans
    une racine persistante). Le texte est `mail_err_cache_mode_invalid`
    formaté : il ne propose pas [2], qui n'y peut rien."""

    _TEXT_KEY = "mail_err_cache_mode_invalid"


class CacheNeedsReseal(CacheModeMismatch):
    """Ouverture en `encrypted` refusée : le cache inscrit `encrypted`, mais
    son contrôle d'époque est salé en clair (`epoch_salted_clear`), donc son
    journal des règles l'est aussi. Ouvert ainsi, le premier
    `cache_epoch()` prendrait ce sel pour une clé changée et viderait le
    journal ; seul le rescellement par `cache_convert` le traduit. Le
    texte est `mail_err_cache_needs_reseal` formaté."""

    _TEXT_KEY = "mail_err_cache_needs_reseal"


class CacheBusy(StoreError):
    """Le cache est tenu en exclusif (conversion en cours)."""


class CacheKeyMissing(StoreError):
    """Le cache est chiffré et sa clé manque au coffre ; aucune clé n'a
    été créée. Texte : `mail_err_cache_key_missing` formaté."""


def _codes_text(codes) -> str | None:
    """Codes SMTP en texte « 450,550 », croissants ; None si aucun. Un
    code qui n'est pas un entier s'écrit 0."""
    propres = sorted(
        c if isinstance(c, int) and not isinstance(c, bool) else 0
        for c in (codes or ())
    )
    return ",".join(str(c) for c in propres) if propres else None


def _codes_list(text) -> list[int]:
    """L'inverse de `_codes_text` ; un morceau illisible est ignoré."""
    codes = []
    for morceau in str(text or "").split(","):
        morceau = morceau.strip()
        if morceau.isdigit():
            codes.append(int(morceau))
    return codes


def _envelope_key(text) -> list[str]:
    """Les adresses d'une enveloppe écrite « a, b », sans casse ni blancs,
    triées : deux écritures de la même enveloppe se comparent égales."""
    return sorted(
        morceau.strip().lower()
        for morceau in str(text or "").split(",")
        if morceau.strip()
    )


class RcptResult(NamedTuple):
    """Ce qu'a fait `rule_log_rcpt_result` : `applied` faux quand la ligne
    était absente ou d'une issue terminale autre que `partial` ;
    `queue_id` est l'entrée de nouvel essai créée, ou None."""

    applied: bool
    queue_id: int | None = None


def _locked(method):
    """Sérialise l'accès à la connexion SQLite.

    `check_same_thread=False` lève l'interdiction de la stdlib, mais ne rend
    pas la connexion sûre pour autant : c'est CE verrou qui la rend sûre. Le
    TUI synchronise dans un thread de travail pendant que l'écran lit le cache
    depuis le thread principal — les deux se croisent vraiment, ce n'est pas
    une précaution théorique.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclass
class MessageMeta:
    uid: int
    date: int
    size: int
    flags: str
    msgid: str
    frm: str
    to: str
    subject: str
    snippet: str
    has_body: bool = False
    # Bruts, tels que le serveur les a envoyés. Le hachage appartient au
    # cache, qui seul connaît le sel : `MessageMeta` traverse le TUI et les
    # tests, où une empreinte ne servirait à rien.
    in_reply_to: str = ""
    references: str = ""
    # Remplis à la RELECTURE seulement : le cache seul connaît le sel, donc
    # personne ne peut les fournir en entrée. Ils servent au regroupement
    # par fil, qui doit pouvoir travailler sans rouvrir la base.
    msgid_hash: str = ""
    in_reply_to_hash: str = ""
    # La PROVENANCE, remplie par `search` seulement. Un résultat qui
    # traverse les dossiers ne dit plus d'où il vient par le dossier
    # ouvert : sans ces deux champs, l'écran afficherait le corps du
    # message qui porte le même UID dans le dossier courant, et les
    # touches de rangement agiraient dessus. `account` n'est pas rempli
    # ici — le cache ne connaît qu'un compte, c'est l'appelant qui les
    # assemble.
    folder: str = ""
    account: str = ""
    # v6. `received_at` est l'INTERNALDATE du serveur, fourni par la
    # synchronisation ; 0 = inconnu, stocké NULL. `seen_at` est rempli à la
    # RELECTURE seulement : c'est le cache qui le pose quand il voit le
    # message passer à lu.
    received_at: int = 0
    seen_at: int = 0


@dataclass(frozen=True)
class ActivityRow:
    """Un message de la boîte de réception vu par les statistiques
    d'activité : la première copie de son Message-ID.

    `received_at` > 0 (réception, ou date d'en-tête à défaut) ; `answered`
    est vrai pour `\\Answered` ou s'il existe une réponse non automatique
    dans Envoyés ; `first_reply_at` est la plus ancienne de ces réponses
    STRICTEMENT postérieure à la réception, ou None ; `sender` est
    l'adresse normalisée de From (`filter.sole_address`) quand elle est
    demandée, sinon « ».
    """

    received_at: int
    seen: bool
    answered: bool
    first_reply_at: int | None
    sender: str = ""


def _fts_query(texte: str) -> str:
    """Une saisie libre → une requête FTS5 sûre.

    Chaque mot devient un préfixe entre guillemets : l'utilisateur tape des
    mots, pas la syntaxe de FTS5, et un caractère comme `"` ou `*` y ferait
    lever une erreur de syntaxe au lieu de chercher.
    """
    mots = [m.replace('"', "") for m in texte.split()]
    return " ".join(f'"{m}"*' for m in mots if m)


def _ensure_fts(conn, mode: str) -> bool:
    """Crée l'index plein texte, et SEULEMENT en mode clair.

    FTS5 stocke en clair ce qu'il indexe. Le poser sur un cache chiffré
    rendrait lisibles les sujets et les extraits que la base principale
    scelle : le chiffrement ne protégerait plus que la moitié du dossier.
    En mode chiffré la recherche déchiffre à la volée, plus lentement, ce
    que l'écran annonce plutôt que de le laisser deviner.
    """
    if mode != "clear":
        # Un cache mêlé, détecté chiffré, garde sinon l'index constitué du
        # temps où il était clair : `messages` serait scellée, et la table
        # d'à côté rendrait les mêmes sujets et extraits par un simple
        # SELECT. Une conversion vers le mode clair le reconstruit.
        conn.execute("DROP TABLE IF EXISTS messages_fts")
        return False
    # Les colonnes RÉELLES décident, comme pour la migration : une table
    # créée par une version antérieure aurait moins de colonnes, et
    # `IF NOT EXISTS` la laisserait telle quelle — la recherche
    # répondrait alors différemment selon l'âge du cache.
    attendues = ["subject", "snippet", "frm", "adr_to"]
    presentes = [
        row[1] for row in conn.execute("PRAGMA table_info(messages_fts)")
    ]
    definition = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'messages_fts'"
    ).fetchone()
    # Une table `content=''` ne stocke rien et REFUSE les DELETE : une
    # resynchronisation ne pourrait alors pas remplacer l'entrée d'un
    # message déjà indexé. Les colonnes ne suffisent pas à distinguer les
    # deux formes, d'où la lecture de la définition elle-même.
    sans_contenu = bool(definition) and "content=''" in (definition[0] or "")
    if presentes and (presentes != attendues or sans_contenu):
        conn.execute("DROP TABLE messages_fts")
        presentes = []
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts"
        f" USING fts5({', '.join(attendues)})"
    )
    return not presentes


def _addresses(value: str) -> list[str]:
    """Un en-tête d'adresses → la liste des adresses seules, en minuscules.

    Accepte les deux formes que porte un en-tête RFC 5322 — « Libellé
    <adresse> » et l'adresse nue — et rend uniquement la partie adresse.
    Les libellés sont écartés : un même correspondant en emploie plusieurs
    au fil du temps, et compter les libellés éclate une personne en autant
    de lignes du classement. La casse est repliée pour la même raison.
    """
    if not value:
        return []
    return [
        adresse.lower()
        for _, adresse in email.utils.getaddresses([value])
        if "@" in adresse
    ]


def split_message_ids(value: str) -> list[str]:
    """« <a@x> <b@y> » → ["<a@x>", "<b@y>"].

    `References` est une liste séparée par des blancs, et certains serveurs
    y glissent des virgules. On garde les jetons entre chevrons et on
    ignore le reste : un fragment sans chevron n'est pas un Message-ID, et
    le hacher créerait un lien vers rien.
    """
    if not value:
        return []
    return [
        jeton
        for jeton in value.replace(",", " ").split()
        if jeton.startswith("<") and jeton.endswith(">")
    ]


def salted_hash(salt: bytes, text: str) -> str:
    """sha256(salt + texte UTF-8), en hexadécimal : l'empreinte de toutes
    les colonnes de `HASHED_COLUMNS`."""
    return hashlib.sha256(salt + (text or "").encode("utf-8")).hexdigest()


def mode_request(account, prefs_get=None) -> str | None:
    """Le mode DEMANDÉ : `account.cache_mode` valide, sinon la préférence
    générale lue avec le défaut "" si elle est valide, sinon None.
    `prefs_get(clé, défaut)` par défaut : `todo_prefs.get`.

    Le défaut "" compte : `todo_prefs.get` rendrait sinon sa propre valeur
    par défaut pour une clé absente ou un fichier illisible, qui se lirait
    comme une demande."""
    if getattr(account, "cache_mode", None) in VALID_MODES:
        return account.cache_mode
    if prefs_get is None:
        from script.todo import todo_prefs

        prefs_get = todo_prefs.get
    try:
        general = prefs_get("mail_cache_mode", "")
    except (OSError, ValueError, TypeError):
        return None
    return (
        general
        if isinstance(general, str) and general in VALID_MODES
        else None
    )


def _ctl_root(base: Path | None) -> Path:
    return (
        Path(base if base is not None else default_base()) / CACHE_CTL_DIRNAME
    )


def cache_ctl_dir(
    account_name: str, base: Path | None = None, *, create: bool = True
) -> Path:
    """`<base>/.cache_ctl/<compte>/`, créé en 0700 avec son parent quand
    `create` ; refuse un lien symbolique ou un dossier d'un autre
    utilisateur (`_assert_private_dir`), à chaque niveau, créé ou non.
    Sans `create`, un niveau absent n'est ni créé ni une erreur."""
    racine = _ctl_root(base)
    dossier = racine / account_name
    if create:
        racine.parent.mkdir(parents=True, exist_ok=True)
    for niveau in (racine, dossier):
        if create:
            try:
                niveau.mkdir(mode=0o700)
            except FileExistsError:
                pass
        try:
            _assert_private_dir(niveau)
        except FileNotFoundError:
            if create:
                raise
            break
        if create:
            os.chmod(niveau, 0o700)
    return dossier


def read_convert_state(
    account_name: str, base: Path | None = None
) -> dict | None:
    """L'état d'une conversion, `{"phase": "unreadable"}` s'il est
    illisible, None s'il n'existe pas. Ne crée rien.

    Est illisible tout fichier qui n'est pas un objet JSON de `version` 1,
    de phase dans `CONVERT_PHASES`, de source et cible dans
    `PERSISTENT_MODES`."""
    chemin = (
        cache_ctl_dir(account_name, base, create=False) / CONVERT_STATE_NAME
    )
    if not os.path.lexists(chemin):
        return None
    illisible = {"phase": "unreadable"}
    try:
        fd = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as handle:
            data = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError):
        return illisible
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or data.get("phase") not in CONVERT_PHASES
        or data.get("source") not in PERSISTENT_MODES
        or data.get("target") not in PERSISTENT_MODES
    ):
        return illisible
    return data


def rw_uri(db_path: Path) -> str:
    """L'URI SQLite `mode=rw` de `db_path`, chemin échappé : elle n'ouvre
    qu'une base existante, jamais ne la crée (voir `probe_connection`)."""
    return (
        "file:"
        + urllib.request.pathname2url(str(Path(db_path).absolute()))
        + "?mode=rw"
    )


@contextlib.contextmanager
def probe_connection(db_path: Path) -> Iterator[sqlite3.Connection | None]:
    """Une connexion de SONDE sur `db_path` : None si le fichier n'existe
    pas (`os.path.lexists`, aucune connexion tentée). Fermée à la sortie ;
    ne crée rien.

    L'URI porte le chemin ÉCHAPPÉ (`pathname2url`) : un nom de compte peut
    contenir `?`, `#` ou `%`, et non échappé, `<base>/a?b/cache.db` ferait
    ouvrir — et créer, la requête étant perdue — `<base>/a`, une base vide.
    `mode=rw` et non `mode=ro` : `rw` ne crée jamais la base, et rejoue un
    journal chaud (processus tué en pleine écriture), que `ro` refuse ; le
    rejeu ne change rien de ce qui était validé. Un fichier protégé en
    écriture est ouvert en lecture seule par SQLite."""
    if not os.path.lexists(db_path):
        yield None
        return
    conn = sqlite3.connect(
        rw_uri(db_path), uri=True, timeout=STORE_BUSY_TIMEOUT_S
    )
    try:
        yield conn
    finally:
        conn.close()


def _tables(conn) -> set:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _columns(conn, table: str) -> list:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _read_inscription(conn) -> str | None:
    """La valeur de `meta.cache_mode`, None si la table ou la clé manque."""
    if "meta" not in _tables(conn):
        return None
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", (CACHE_MODE_KEY,)
    ).fetchone()
    return None if row is None else row[0]


def _sealed_starts_with(conn, magic: bytes) -> bool:
    """Vrai si une colonne de `SEALED_COLUMNS` commence par `magic` ; les
    tables et colonnes absentes sont sautées."""
    for table, colonnes in SEALED_COLUMNS.items():
        # Une table absente n'a aucune colonne : elle est sautée aussi.
        presentes = set(_columns(conn, table))
        retenues = [c for c in colonnes if c in presentes]
        if not retenues:
            continue
        condition = " OR ".join(f"substr({c}, 1, 2) = ?" for c in retenues)
        if conn.execute(
            f"SELECT 1 FROM {table} WHERE {condition} LIMIT 1",
            (magic,) * len(retenues),
        ).fetchone():
            return True
    return False


def _has_body_file(root: Path, suffix: str) -> bool:
    """Vrai si un dossier de corps de `root` (sous-dossier direct) porte un
    fichier dont le nom finit par `suffix`. Aucun lien n'est suivi ; le
    parcours s'arrête au premier trouvé."""
    try:
        dossiers = list(os.scandir(root))
    except OSError:
        return False
    for dossier in dossiers:
        if not dossier.is_dir(follow_symlinks=False):
            continue
        try:
            with os.scandir(dossier.path) as entrees:
                for entree in entrees:
                    if entree.name.endswith(suffix) and entree.is_file(
                        follow_symlinks=False
                    ):
                        return True
        except OSError:
            continue
    return False


def _epoch_check(conn) -> str | None:
    if "meta" not in _tables(conn):
        return None
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'cache_epoch_check'"
    ).fetchone()
    return row[0] if row and row[0] else None


def detect_mode(conn, root: Path) -> str | None:
    """Le mode d'un cache sans inscription, d'après ce qu'il contient.

    Toute preuve de chiffrement l'emporte : une colonne scellée qui
    commence par `SEALED_MAGIC`, un contrôle d'époque salé par une clé, un
    corps `*.eml.enc`. À défaut, une preuve de clair : une colonne scellée
    qui commence par `CLEAR_MAGIC`, l'index plein texte, un contrôle
    d'époque salé en clair, un corps `*.eml`. Rien : None (cache vide).
    Un cache mêlé (lignes en clair ET scellées) est donc `encrypted` : seul
    ce mode les lit toutes. `conn` est lu, jamais écrit ; les tables et
    colonnes absentes sont sautées ; les fichiers ne sont parcourus que si
    la base ne tranche pas."""
    controle_clair = salted_hash(b"clear", "cache_epoch")
    controle = _epoch_check(conn)
    if _sealed_starts_with(conn, SEALED_MAGIC):
        return "encrypted"
    if controle is not None and controle != controle_clair:
        return "encrypted"
    if _has_body_file(root, ".eml.enc"):
        return "encrypted"
    if (
        _sealed_starts_with(conn, CLEAR_MAGIC)
        or "messages_fts" in _tables(conn)
        or controle == controle_clair
        or _has_body_file(root, ".eml")
    ):
        return "clear"
    return None


def epoch_salted_clear(conn) -> bool:
    """Vrai si `meta.cache_epoch_check` est salé en clair : le journal des
    règles a été écrit sous le sel clair. Sur un cache `encrypted`, il
    n'est lisible qu'après un rescellement."""
    return _epoch_check(conn) == salted_hash(b"clear", "cache_epoch")


def has_clear_residue(conn, root: Path) -> bool:
    """Vrai si un cache chiffré garde des restes clairs : une colonne
    scellée commençant par `CLEAR_MAGIC`, un contrôle d'époque salé en
    clair, un fichier `*.eml` dans un dossier de corps, ou la table
    `messages_fts`."""
    return (
        _sealed_starts_with(conn, CLEAR_MAGIC)
        or epoch_salted_clear(conn)
        or "messages_fts" in _tables(conn)
        or _has_body_file(root, ".eml")
    )


def _probe_root(root: Path) -> str | None:
    """Le mode inscrit dans `root/cache.db`, sinon `detect_mode`, par
    `probe_connection` ; None sans `cache.db` ou sur base sans aucune
    preuve ; `PROBE_UNKNOWN` sur toute `sqlite3.Error` ou `OSError` alors
    que `cache.db` existe (base abîmée, occupée au-delà du délai). Une
    valeur inscrite hors `VALID_MODES` est rendue telle quelle (le refus
    la montre). Ne crée rien."""
    db_path = Path(root) / "cache.db"
    if not os.path.lexists(db_path):
        return None
    try:
        with probe_connection(db_path) as conn:
            if conn is None:
                return None
            inscrit = _read_inscription(conn)
            if inscrit is not None:
                return inscrit
            return detect_mode(conn, Path(root))
    except (sqlite3.Error, OSError):
        return PROBE_UNKNOWN


def recovery_plan(
    r: bool, o: bool, n: bool, phase: str | None
) -> tuple[str, str]:
    """La décision de reprise d'une conversion, sans rien toucher.

    `r`, `o`, `n` disent si la racine, l'ancienne copie (`ctl/old`) et la
    copie neuve (`ctl/new`) existent ; `phase` est celle de `convert.json`,
    None (pas d'état) valant "unreadable". Rend `(action, issue)` :
    `action` ∈ "none", "erase_new", "forward", "restore_old", "erase_old",
    "inconsistent" ; `issue` ∈ "none", "rolled_back", "rolled_forward",
    "cleaned", "inconsistent". "forward" met la copie neuve à la place de
    la racine puis efface l'ancienne ; "restore_old" remet l'ancienne
    copie en racine puis efface la neuve. Une copie neuve qui n'a pas
    atteint `swapping` n'est jamais promue : elle n'est pas vérifiée.
    Partagée par `cache_convert.recover` et `inscribed_mode`."""
    phase = phase or "unreadable"
    incoherent = ("inconsistent", "inconsistent")
    apres_echange = phase in ("swapping", "cleaning")
    if r and o and n:
        return incoherent
    if not o and not n:
        return ("none", "none")
    if r and not o and n:
        if phase == "swapping":
            return ("forward", "rolled_forward")
        if phase == "cleaning":
            return incoherent
        return ("erase_new", "rolled_back")
    if not r and o and n:
        if apres_echange:
            return ("forward", "rolled_forward")
        return ("restore_old", "rolled_back")
    if not r and o and not n:
        return ("restore_old", "rolled_back")
    if r and o and not n:
        if apres_echange:
            return ("erase_old", "cleaned")
        return incoherent
    # Reste : ni racine ni ancienne copie, seulement la neuve.
    if phase == "swapping":
        return ("forward", "rolled_forward")
    return incoherent


def inscribed_mode(account, base: Path | None = None) -> str | None:
    """Le mode du cache PERSISTANT du compte, tel qu'il SERA après une
    éventuelle reprise de conversion.

    `recovery_plan` sur la racine, les copies et la phase, puis
    `_probe_root` de la copie qui sera la racine : la neuve quand l'issue
    est `rolled_forward`, l'ancienne quand elle revient, sinon la racine ;
    une issue incohérente sonde la racine si elle existe, sinon rend
    `PROBE_UNKNOWN`. Sans état ni copies : `_probe_root` de la racine. Ne
    crée rien, ne prend aucun verrou. `StoreError` ou `OSError` venues du
    dossier de contrôle : l'état est ignoré (la racine seule est sondée) ;
    venues de la sonde : `PROBE_UNKNOWN`."""
    base = Path(base) if base is not None else default_base()
    nom = account.name
    racine = base / nom
    cible = racine
    try:
        ctl = cache_ctl_dir(nom, base, create=False)
        etat = read_convert_state(nom, base)
        o = os.path.lexists(ctl / "old" / nom)
        n = os.path.lexists(ctl / "new" / nom)
        if etat is not None or o or n:
            r = os.path.lexists(racine)
            action, issue = recovery_plan(r, o, n, (etat or {}).get("phase"))
            if issue == "rolled_forward":
                cible = ctl / "new" / nom
            elif action == "restore_old":
                cible = ctl / "old" / nom
            elif issue == "inconsistent" and not r:
                return PROBE_UNKNOWN
    except (StoreError, OSError):
        cible = racine
    try:
        return _probe_root(cible)
    except (StoreError, OSError):
        return PROBE_UNKNOWN


def resolve_mode(account, prefs_get=None, base: Path | None = None) -> str:
    """Le mode dans lequel ouvrir le cache du compte.

    Dans l'ordre : `account.cache_mode` s'il est valide, puis la
    préférence générale si elle est valide (ce sont des DEMANDES, voir
    `mode_request`) ; à défaut le mode inscrit dans le cache persistant
    (`inscribed_mode`) s'il est l'un de `PERSISTENT_MODES` ; sinon `clear`,
    le mode d'un cache neuf. Jamais `clear` quand un cache existe sans
    demande lisible : préférences absentes, illisibles ou inconnues
    laissent le cache décider. Une inscription hors `PERSISTENT_MODES` ou
    illisible n'est jamais rendue : l'ouverture la refuse ou la tranche.
    Ne lève pas : `StoreError` et `OSError` sont interceptées."""
    demande = mode_request(account, prefs_get)
    if demande is not None:
        return demande
    try:
        inscrit = inscribed_mode(account, base)
    except (StoreError, OSError):
        inscrit = PROBE_UNKNOWN
    return inscrit if inscrit in PERSISTENT_MODES else "clear"


@contextlib.contextmanager
def cache_exclusive(
    account_name: str, base: Path | None = None
) -> Iterator[bool]:
    """`flock` EXCLUSIF sans attente sur le verrou d'usage du cache ; rend
    s'il est tenu. Le bloc s'exécute dans les deux cas, comme `file_lock`.
    Crée le dossier de contrôle. Un verrou inutilisable (lien symbolique,
    dossier refusé) lève `StoreError`."""
    fd = _open_usage_lock(account_name, base)
    held = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = True
        except BlockingIOError:
            held = False
        except OSError as exc:
            raise StoreError(
                f"{t('mail_err_cache_lock_unusable')} {exc}"
            ) from exc
        yield held
    finally:
        if held:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _open_usage_lock(account_name: str, base: Path | None) -> int:
    """Le descripteur du verrou d'usage `<base>/.cache_ctl/<compte>/lock`,
    créé en 0600, jamais à travers un lien. Toute panne devient
    `StoreError` : laissée en `OSError`, elle se lirait comme une panne
    réseau."""
    try:
        ctl = cache_ctl_dir(account_name, base)
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
        return os.open(ctl / CACHE_LOCK_NAME, flags, 0o600)
    except StoreError as exc:
        raise StoreError(f"{t('mail_err_cache_lock_unusable')} {exc}") from exc
    except OSError as exc:
        raise StoreError(f"{t('mail_err_cache_lock_unusable')} {exc}") from exc


def default_base() -> Path:
    return Path(os.path.expanduser("~/.erplibre/mail"))


def ephemeral_base() -> Path:
    """/dev/shm quand il est inscriptible, sinon le dossier temporaire."""
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        return shm
    import tempfile

    return Path(tempfile.gettempdir())


def cache_root(account, mode: str, base: Path | None = None) -> Path:
    if mode == "ephemeral":
        base = Path(base) if base else ephemeral_base()
        return base / f"{EPHEMERAL_PREFIX}{os.getpid()}" / account.name
    base = Path(base) if base else default_base()
    return base / account.name


# Noms qui, seuls, désigneraient autre chose que le dossier voulu.
DEGENERATE_DIRNAMES = {"": "_", ".": "%2E", "..": "%2E%2E"}


def folder_dirname(imap_name: str) -> str:
    """Un nom de dossier IMAP transformé en nom de dossier de fichiers.

    `quote` avec `safe=""` échappe tous les séparateurs, donc le résultat est
    toujours UN seul composant de chemin : « A/B » ne peut pas créer deux
    niveaux.

    Mais `quote` n'encode JAMAIS le point — la stdlib garde toujours
    « _.-~ » — et c'est voulu : beaucoup de serveurs IMAP séparent leur
    hiérarchie par des points, et « INBOX.Sent » doit rester lisible sur le
    disque. Le prix à payer est que « . » et « .. » traverseraient tels
    quels, puisque `racine / ".."` remonte d'un cran. Ces trois cas
    dégénérés sont donc les seuls réécrits.
    """
    quoted = urllib.parse.quote(imap_name, safe="")
    return DEGENERATE_DIRNAMES.get(quoted, quoted)


def _assert_private_dir(path: Path) -> None:
    """Refuse un dossier qu'on ne possède pas, ou qui est un lien symbolique."""
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise StoreError(f"{path} {t('mail_err_symlink_refused')}")
    if info.st_uid != os.getuid():
        raise StoreError(f"{path} {t('mail_err_owned_by_other_user')}")


def sweep_orphan_ephemeral(base: Path | None = None) -> int:
    """Efface les caches éphémères dont le processus n'existe plus.

    `atexit` et les gestionnaires de signaux couvrent les sorties normales ;
    un SIGKILL, lui, laisse un résidu. Ce balayage au démarrage est le filet.
    """
    base = Path(base) if base else ephemeral_base()
    removed = 0
    if not base.is_dir():
        return 0
    for path in base.glob(f"{EPHEMERAL_PREFIX}*"):
        if not path.is_dir():
            continue
        raw_pid = path.name[len(EPHEMERAL_PREFIX) :]
        if not raw_pid.isdigit():
            continue
        pid = int(raw_pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except PermissionError:
            # Le PID existe et appartient à quelqu'un d'autre : on n'y touche pas.
            continue
    return removed


class Store:
    """Le cache d'UN compte. À ouvrir, à fermer, éventuellement à effacer."""

    def __init__(
        self,
        account,
        *,
        mode: str | None = None,
        key: bytes | None = None,
        secrets=None,
        base: Path | None = None,
        lock_held: bool = False,
    ) -> None:
        """`mode` passé est une demande ferme ; None le résout par
        `resolve_mode` (avec `base`) et laisse l'ouverture adopter le mode
        inscrit quand le compte ne demande rien. `lock_held` dit que
        l'appelant tient déjà le verrou d'usage en exclusif (conversion) :
        l'ouverture ne prend alors ni verrou ni reprise."""
        self.account = account
        self._mode_explicit = mode is not None
        self.mode = mode or resolve_mode(account, base=base)
        self._base = base
        self.root = cache_root(account, self.mode, base)
        self._key = key
        self._key_given = key is not None
        self._secrets = secrets
        self._lock_held = lock_held
        self._usage_fd: int | None = None
        # Ce qu'a rendu la sonde de l'ouverture : None (aucun cache, ou
        # aucune preuve), un mode, ou `PROBE_UNKNOWN`. Seul None permet de
        # créer une clé au coffre.
        self._probed: str | None = None
        self._conn: sqlite3.Connection | None = None
        self._crypto = None
        self._lock = threading.RLock()

    # -- Cycle de vie ---------------------------------------------------

    def _persistent_base(self) -> Path:
        return Path(self._base) if self._base is not None else default_base()

    @_locked
    def open(self) -> None:
        """Ouvre le cache, dans cet ordre pour un cache persistant :
        reprise d'une conversion interrompue, verrou d'usage partagé,
        pré-contrôle du mode par la sonde (avant toute clé et toute
        écriture), puis ouverture et contrôle définitif sous le verrou
        d'écriture. Un refus de mode lève `CacheModeMismatch` (ou
        `CacheModeInvalid`, `CacheNeedsReseal`) sans rien écrire ; une
        conversion en cours lève
        `CacheBusy`. Un cache éphémère ne fait que s'inscrire."""
        if self._conn is not None:
            return
        if self.mode == "ephemeral":
            self._open_db()
            return
        if not self._lock_held:
            self._recover_if_needed()
            self._take_usage_lock()
        try:
            self._precheck()
            self._open_db()
        except BaseException:
            self._release_usage_lock()
            raise

    def _recover_if_needed(self) -> None:
        """Achève ou défait une conversion interrompue avant d'ouvrir.

        Lancée quand `convert.json` existe ou qu'une copie reste sous le
        dossier de contrôle, et seulement si le verrou exclusif s'obtient
        sans attente. Une reprise qui échoue laisse ouvrir la racine si
        elle existe (elle porte sa propre inscription, que le contrôle de
        mode protège) et consigne l'échec à `mail.log` ; sans racine,
        l'erreur remonte. Une racine absente à côté de copies n'est jamais
        recréée vide : `CacheBusy` si un autre tient le cache, sinon
        `StoreError`."""
        nom = self.account.name
        base = self._persistent_base()

        def restes() -> bool:
            try:
                ctl = cache_ctl_dir(nom, base, create=False)
                return (
                    read_convert_state(nom, base) is not None
                    or os.path.lexists(ctl / "old")
                    or os.path.lexists(ctl / "new")
                )
            except (StoreError, OSError):
                return False

        if not restes():
            return
        with cache_exclusive(nom, base) as tenu:
            if tenu:
                from script.todo.mail import cache_convert

                try:
                    cache_convert.recover(nom, base)
                except (StoreError, OSError) as exc:
                    if not os.path.lexists(base / nom):
                        raise
                    _logger.warning(
                        "reprise de conversion impossible, ouverture de la"
                        " racine : %s",
                        exc,
                    )
        if not self._mode_explicit:
            self.mode = resolve_mode(self.account, base=self._base)
            self.root = cache_root(self.account, self.mode, self._base)
        if (
            self.mode != "ephemeral"
            and not os.path.lexists(self.root)
            and restes()
        ):
            if not tenu:
                raise CacheBusy(t("mail_err_cache_busy_converting"))
            raise StoreError(
                t("mail_err_cache_convert_inconsistent").format(
                    path=_ctl_root(base) / nom
                )
            )

    def _take_usage_lock(self) -> None:
        """Prend le verrou d'usage en PARTAGÉ, sans attente, jusqu'à
        `close()`. Tenu en exclusif (conversion) : `CacheBusy`."""
        fd = _open_usage_lock(self.account.name, self._persistent_base())
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise CacheBusy(t("mail_err_cache_busy_converting")) from None
        except OSError as exc:
            os.close(fd)
            raise StoreError(
                f"{t('mail_err_cache_lock_unusable')} {exc}"
            ) from exc
        self._usage_fd = fd

    def _release_usage_lock(self) -> None:
        fd, self._usage_fd = self._usage_fd, None
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _refuse(self, inscrit: str) -> None:
        """Lève le refus qui correspond à `inscrit`, lu dans le cache."""
        if inscrit not in PERSISTENT_MODES:
            raise CacheModeInvalid(self.account.name, inscrit, self.mode)
        raise CacheModeMismatch(self.account.name, inscrit, self.mode)

    def _may_adopt(self) -> bool:
        """Vrai si l'ouverture peut prendre le mode inscrit à la place du
        sien : le `Store` n'a pas reçu de mode et le compte n'en demande
        aucun (préférences absentes, illisibles ou inconnues)."""
        return not self._mode_explicit and mode_request(self.account) is None

    def _adopt(self, inscrit: str) -> None:
        """Prend le mode inscrit ; une clé ne peut pas être créée pour lui."""
        self.mode = inscrit
        self._probed = inscrit
        if not self._key_given:
            self._key = None
        self._crypto = None

    def _precheck(self) -> None:
        """Pré-contrôle par la sonde, avant toute clé et toute écriture."""
        self._probed = _probe_root(self.root)
        sonde = self._probed
        if sonde is None or sonde == PROBE_UNKNOWN or sonde == self.mode:
            return
        if sonde in PERSISTENT_MODES and self._may_adopt():
            self._adopt(sonde)
            return
        self._refuse(sonde)

    def _settle_inscription(self, conn) -> str | None:
        """Le contrôle définitif, sous `BEGIN IMMEDIATE` : lit
        `meta.cache_mode`, sinon le détecte, sinon prend `self.mode`, et
        l'inscrit s'il manquait. Rend le mode à adopter quand il diffère et
        que l'adoption est permise ; lève le refus sinon, et
        `CacheNeedsReseal` pour un cache chiffré au journal salé en clair
        hors conversion ; None quand l'ouverture continue."""
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (CACHE_MODE_KEY,)
        ).fetchone()
        inscrit = row[0] if row is not None else None
        if self.mode == "ephemeral":
            if inscrit is None:
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                    (CACHE_MODE_KEY, self.mode),
                )
            return None
        absent = inscrit is None
        if absent:
            inscrit = detect_mode(conn, self.root) or self.mode
        if inscrit != self.mode:
            if inscrit in PERSISTENT_MODES and self._may_adopt():
                return inscrit
            self._refuse(inscrit)
        if (
            inscrit == "encrypted"
            and not self._lock_held
            and epoch_salted_clear(conn)
        ):
            # La conversion (`lock_held`) lit ce cache pour le resceller ;
            # toute autre ouverture viderait son journal des règles.
            raise CacheNeedsReseal(self.account.name, inscrit, self.mode)
        if absent:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                (CACHE_MODE_KEY, inscrit),
            )
        return None

    def _open_db(self) -> None:
        """Ouvre la base et la migre ; adopte au plus une fois le mode
        inscrit lu sous le verrou d'écriture (sonde refaite)."""
        adopte = None
        for _essai in range(2):
            if adopte is not None:
                self._adopt(adopte)
                self._precheck()
                # Une sonde muette ne fait pas oublier le mode lu sous le
                # verrou : aucune clé ne doit être créée pour ce cache.
                if self._probed in (None, PROBE_UNKNOWN):
                    self._probed = adopte
            adopte = self._open_db_once(allow_adopt=_essai == 0)
            if adopte is None:
                return
        raise CacheModeMismatch(self.account.name, adopte, self.mode)

    def _open_db_once(self, *, allow_adopt: bool) -> str | None:
        self._crypto = build_crypto(self.mode, self._resolve_key())
        self._prepare_root()
        db_path = self.root / "cache.db"
        conn = None
        try:
            # `check_same_thread=False` parce que le TUI synchronise dans un
            # thread de travail : sans ça, la première passe lèverait
            # ProgrammingError. La sûreté vient du verrou, pas de ce drapeau.
            conn = sqlite3.connect(
                db_path,
                check_same_thread=False,
                timeout=STORE_BUSY_TIMEOUT_S,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA)
            # La migration lit `PRAGMA table_info` puis ajoute ce qui
            # manque : sous le verrou d'écriture, pris AVANT la lecture,
            # un second processus qui ouvre le même cache attend qu'elle
            # finisse et relit des colonnes déjà là, au lieu d'ajouter
            # deux fois la même (« duplicate column name »).
            conn.execute("BEGIN IMMEDIATE")
            # Le mode se tranche AVANT `_ensure_fts`, qui supprimerait
            # l'index d'un cache clair ouvert en chiffré.
            adopte = self._settle_inscription(conn)
            if adopte is not None:
                if not allow_adopt:
                    self._refuse(adopte)
                conn.rollback()
                conn.close()
                return adopte
            _ensure_columns(conn)
            _ensure_outbox_columns(conn)
            _ensure_rule_log_columns(conn)
            _ensure_auto_sent_columns(conn)
            neuf = _ensure_fts(conn, self.mode)
            # REPLACE, pas IGNORE : un cache d'avant la v2 porte encore
            # « 1 », et l'ignorer laisserait la version mentir sur une base
            # qu'on vient justement de migrer.
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value)"
                " VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()
            raise StoreError(
                f"{t('mail_err_cache_unreadable')} {db_path} ({exc})"
            ) from exc
        except BaseException:
            if conn is not None:
                try:
                    conn.rollback()
                finally:
                    conn.close()
            raise
        # Publié SEULEMENT une fois le schéma en place. `sqlite3.connect` est
        # paresseux : une base corrompue n'échoue qu'à `executescript`, donc
        # affecter `self._conn` plus tôt laisserait un open() raté derrière lui
        # un handle sans schéma — et le open() suivant, voyant `_conn` non nul,
        # réussirait en silence sur une base inutilisable.
        self._conn = conn
        if neuf:
            # Un index vide répondrait « aucun résultat » sur une boîte
            # pleine, ce qui se lit comme une absence et non comme un index
            # à construire. On le remplit avec ce que le cache contient
            # déjà, sans rien redemander au serveur.
            self._reindexer()
        if db_path.exists():
            os.chmod(db_path, 0o600)
        return None

    @_locked
    def close(self) -> None:
        """Ferme la base, puis relâche le verrou d'usage."""
        try:
            if self._conn is None:
                return
            try:
                self._conn.commit()
            except sqlite3.Error:
                # Fermer prime sur sauver : un commit refusé ne doit pas
                # laisser la connexion ouverte pour toujours.
                pass
            finally:
                self._conn.close()
                self._conn = None
        finally:
            self._release_usage_lock()

    def cleanup(self) -> None:
        """Efface la racine du compte. Appelé à la sortie en mode éphémère.

        On n'efface QUE le dossier du compte : le dossier par PID est partagé
        avec les autres comptes éphémères du même processus, et l'effacer
        détruirait leurs caches vivants. Il ne part que s'il est vide.
        """
        self.close()
        if self.mode != "ephemeral":
            return
        shutil.rmtree(self.root, ignore_errors=True)
        parent = self.root.parent
        if parent.name.startswith(EPHEMERAL_PREFIX):
            try:
                parent.rmdir()
            except OSError:
                # Un autre compte éphémère l'occupe encore : c'est normal.
                pass

    def __enter__(self) -> "Store":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _prepare_root(self) -> None:
        """Crée la racine, en 0700 à chaque niveau qui nous appartient.

        `mkdir(parents=True)` crée les dossiers intermédiaires SANS appliquer
        le mode — c'est documenté dans la stdlib. En éphémère la racine vit
        sous `/dev/shm`, qui est en 1777 et partagé avec tous les utilisateurs
        locaux : un dossier par PID laissé à l'umask y rendrait les noms de
        comptes lisibles par n'importe qui, et un dossier pré-créé par un tiers
        à un chemin devinable lui permettrait de glisser un lien symbolique
        sous `write_body`.
        """
        parent = self.root.parent
        if self.mode == "ephemeral":
            parent.parent.mkdir(parents=True, exist_ok=True)
            parent.mkdir(mode=0o700, exist_ok=True)
            _assert_private_dir(parent)
        else:
            parent.mkdir(parents=True, exist_ok=True)
        os.chmod(parent, 0o700)
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _resolve_key(self) -> bytes | None:
        if self.mode == "clear":
            return None
        if self._key is not None:
            return self._key
        if self.mode == "ephemeral":
            # Tirée ici, gardée en RAM, jamais écrite : c'est tout l'intérêt.
            self._key = new_key()
            return self._key
        if self._secrets is None:
            raise StoreError(
                f"{t('mail_err_mode_prefix')} {self.mode}"
                f" {t('mail_err_mode_requires_key_no_vault')}"
            )
        ref = self.account.cache_key_ref()
        # Chemin rapide : une clé présente se lit sans verrou ni relecture
        # du coffre, qui coûteraient une dérivation de clé par compte.
        stored = self._secrets.get(ref)
        if stored is None and self._probed is not None:
            # Le cache existe déjà (inscrit, détecté chiffré, ou illisible) :
            # une clé neuve rendrait ses lignes scellées illisibles, et le
            # premier `cache_epoch()` viderait son journal des règles.
            raise CacheKeyMissing(
                t("mail_err_cache_key_missing").format(
                    account=self.account.name
                )
            )
        if stored is None:
            update = getattr(self._secrets, "update", None)
            if callable(update):
                # Créée SOUS le verrou du coffre, si elle manque encore
                # après relecture : deux processus qui ouvrent ensemble un
                # cache neuf gardent la même clé, au lieu d'en tirer deux
                # dont l'une chiffrerait des messages illisibles ensuite.
                stored = update(
                    ref,
                    lambda current: (
                        current or base64.b64encode(new_key()).decode()
                    ),
                )
            else:
                stored = base64.b64encode(new_key()).decode()
                self._secrets.set(ref, stored)
        self._key = base64.b64decode(stored)
        return self._key

    # -- Scellement -----------------------------------------------------

    def _seal(self, text: str) -> bytes:
        return self._crypto.seal((text or "").encode("utf-8"))

    def _open(self, blob) -> str:
        if blob is None:
            return ""
        return self._crypto.open(bytes(blob)).decode("utf-8", "replace")

    def _msgid_hash(self, msgid: str) -> str:
        return salted_hash(self._key or b"clear", msgid)

    def _hash_or_none(self, msgid: str):
        """L'empreinte, ou NULL si l'en-tête est absent.

        Hacher la chaîne vide donnerait à TOUS les messages sans
        `In-Reply-To` la même empreinte : ils se répondraient les uns aux
        autres. NULL ne joint rien, ce qui est exactement le sens de
        « ce message ne répond à personne ».
        """
        msgid = (msgid or "").strip()
        return self._msgid_hash(msgid) if msgid else None

    def _references_hashes(self, references: str):
        empreintes = [
            self._msgid_hash(m) for m in split_message_ids(references)
        ]
        return " ".join(empreintes) if empreintes else None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StoreError(t("mail_err_cache_not_open"))
        return self._conn

    # -- Dossiers -------------------------------------------------------

    @_locked
    def upsert_folder(
        self,
        name: str,
        display: str = "",
        role: str | None = None,
        uidvalidity: int | None = None,
        uidnext: int | None = None,
    ) -> int:
        db = self._db()
        db.execute(
            "INSERT INTO folders(name, display, role, uidvalidity, uidnext)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET"
            "   display = COALESCE(excluded.display, folders.display),"
            "   role = COALESCE(excluded.role, folders.role),"
            "   uidvalidity = COALESCE(excluded.uidvalidity, folders.uidvalidity),"
            "   uidnext = COALESCE(excluded.uidnext, folders.uidnext)",
            (name, display or None, role, uidvalidity, uidnext),
        )
        db.commit()
        # `display` vaut NULL tant qu'aucun nom affichable n'est connu : c'est
        # ce qui rend le COALESCE vivant, donc ce qui permet à une resync qui
        # ne repasse que le nom IMAP de NE PAS écraser un libellé déjà décodé.
        # Les lecteurs retombent sur `name` (voir mailbox_refs, tâche 9).
        return db.execute(
            "SELECT id FROM folders WHERE name = ?", (name,)
        ).fetchone()[0]

    @_locked
    def folders(self) -> list[dict]:
        """Les dossiers tels qu'ils sont en colonne, `unseen` compris.

        Une simple lecture, et c'est un choix MESURÉ : compter les non-lus
        ici à chaque appel coûte 95 ms sur un cache de 240 000 messages, or
        l'arbre se redessine à chaque touche qui change un drapeau. La
        colonne est donc tenue à jour par ceux qui la font varier —
        `update_flags`, `mark_all_seen`, `forget_message`, `purge_folder`,
        `upsert_messages` — chacun en temps constant sauf le dernier, qui
        recompte une fois pour son dossier parce qu'il écrit en lot.
        """
        return [
            dict(r)
            for r in self._db().execute("SELECT * FROM folders ORDER BY name")
        ]

    @_locked
    def folder_state(self, name: str) -> dict | None:
        row = (
            self._db()
            .execute("SELECT * FROM folders WHERE name = ?", (name,))
            .fetchone()
        )
        return dict(row) if row else None

    @_locked
    def set_folder_state(self, name: str, **fields) -> None:
        allowed = {
            "last_uid",
            "total",
            "unseen",
            "uidvalidity",
            "uidnext",
            "synced_at",
            "role",
            "display",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(
                f"{t('mail_err_unknown_folder_fields')} {sorted(unknown)}"
            )
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        db = self._db()
        db.execute(
            f"UPDATE folders SET {sets} WHERE name = ?",
            (*fields.values(), name),
        )
        db.commit()

    @_locked
    def forget_folder(self, name: str) -> None:
        """Retire le dossier du cache, messages et corps compris.

        Le serveur ne l'a plus : le garder localement afficherait dans
        l'arbre un dossier que la prochaine synchronisation ne retrouverait
        jamais, et qu'aucune action ne pourrait ouvrir.
        """
        db = self._db()
        ligne = db.execute(
            "SELECT id FROM folders WHERE name = ?", (name,)
        ).fetchone()
        if ligne:
            db.execute("DELETE FROM messages WHERE folder_id = ?", (ligne[0],))
        shutil.rmtree(self.root / folder_dirname(name), ignore_errors=True)
        db.execute("DELETE FROM folders WHERE name = ?", (name,))
        db.commit()

    @_locked
    def rename_folder(self, ancien: str, nouveau: str) -> None:
        """Suit un renommage côté serveur, sans reperdre les messages.

        Le nom est la clé du dossier ET le nom de son répertoire de corps :
        les deux suivent, sinon la prochaine passe téléchargerait de
        nouveau tout ce qui est déjà là.
        """
        db = self._db()
        db.execute(
            "UPDATE folders SET name = ? WHERE name = ?", (nouveau, ancien)
        )
        db.commit()
        source = self.root / folder_dirname(ancien)
        cible = self.root / folder_dirname(nouveau)
        if source.exists() and not cible.exists():
            source.rename(cible)

    @_locked
    def purge_folder(self, name: str) -> None:
        db = self._db()
        row = db.execute(
            "SELECT id FROM folders WHERE name = ?", (name,)
        ).fetchone()
        if row:
            # AVANT la suppression des messages : l'index se vide par les
            # identifiants de ligne, qui n'existent plus après. Un index
            # laissé derrière rendrait les sujets de messages effacés.
            self._desindexer(db, row[0])
            db.execute("DELETE FROM messages WHERE folder_id = ?", (row[0],))
            db.execute(
                "UPDATE folders SET last_uid = 0, total = 0, unseen = 0"
                " WHERE id = ?",
                (row[0],),
            )
            db.commit()
        shutil.rmtree(self.root / folder_dirname(name), ignore_errors=True)

    # -- Messages -------------------------------------------------------

    @_locked
    def upsert_messages(self, folder_id: int, metas: list[MessageMeta]) -> int:
        db = self._db()
        maintenant = int(time.time())
        rows = [
            (
                folder_id,
                m.uid,
                m.date,
                m.size,
                m.flags,
                self._msgid_hash(m.msgid),
                self._seal(m.msgid),
                self._seal(m.frm),
                self._seal(m.to),
                self._seal(m.subject),
                self._seal(m.snippet),
                self._hash_or_none(m.in_reply_to),
                self._references_hashes(m.references),
                int(getattr(m, "received_at", 0) or 0),
                maintenant,
            )
            for m in metas
        ]
        self._indexer(db, folder_id, metas)
        # `seen_at` reste NULL à l'insertion : un message déjà lu à son
        # arrivée dans le cache l'a été ailleurs, à un moment inconnu.
        # À la mise à jour, il suit la transition de `\Seen` comme dans
        # `update_flags`. Les expressions de `DO UPDATE` lisent toutes la
        # ligne d'AVANT la mise à jour : `messages.flags` y est l'ancien.
        db.executemany(
            "INSERT INTO messages(folder_id, uid, date, size, flags,"
            " msgid_hash, sealed_msgid, sealed_from, sealed_to,"
            " sealed_subject, sealed_snippet,"
            " in_reply_to_hash, references_hashes, received_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULLIF(?, 0))"
            " ON CONFLICT(folder_id, uid) DO UPDATE SET"
            "   date = excluded.date, size = excluded.size,"
            "   flags = excluded.flags, msgid_hash = excluded.msgid_hash,"
            "   sealed_msgid = excluded.sealed_msgid,"
            "   sealed_from = excluded.sealed_from,"
            "   sealed_to = excluded.sealed_to,"
            "   sealed_subject = excluded.sealed_subject,"
            "   sealed_snippet = excluded.sealed_snippet,"
            # Une resynchronisation doit POUVOIR remplir ces colonnes sur
            # un message déjà en cache : c'est le seul chemin par lequel
            # les messages d'avant la v2 les obtiendront.
            "   in_reply_to_hash = excluded.in_reply_to_hash,"
            "   references_hashes = excluded.references_hashes,"
            # Une resynchronisation sans INTERNALDATE garde celle déjà
            # connue plutôt que de l'effacer.
            "   received_at = COALESCE(NULLIF(excluded.received_at, 0),"
            "     messages.received_at),"
            "   seen_at = CASE"
            "     WHEN messages.flags NOT LIKE '%\\Seen%' ESCAPE '\\'"
            "      AND excluded.flags LIKE '%\\Seen%' ESCAPE '\\'"
            "     THEN ?"
            "     WHEN excluded.flags NOT LIKE '%\\Seen%' ESCAPE '\\'"
            "     THEN NULL"
            "     ELSE messages.seen_at END",
            rows,
        )
        self._indexer_apres(db, folder_id, metas)
        # Écriture en LOT : un recompte du dossier est ici négligeable, et il
        # rend `folders.unseen` auto-correcteur — les chemins en temps
        # constant qui l'ajustent message par message ne peuvent pas dériver
        # indéfiniment. Le `total`, lui, appartient au SERVEUR : la passe de
        # synchronisation l'écrit, un ajout au cache ne le décide pas.
        db.execute(
            "UPDATE folders SET unseen = ("
            "  SELECT COUNT(*) FROM messages"
            "  WHERE folder_id = ?"
            "  AND flags NOT LIKE '%\\Seen%' ESCAPE '\\'"
            ") WHERE id = ?",
            (folder_id, folder_id),
        )
        db.commit()
        return len(rows)

    # -- File d'attente d'envoi (v4, v6) --------------------------------

    def _sceller_file(
        self,
        raw: bytes,
        recipients: str,
        subject: str,
        *,
        kind: str,
        retry: bool = False,
    ) -> tuple[bytes, bytes, bytes]:
        """Les trois blobs scellés d'une entrée de file : octets,
        destinataires, sujet.

        Les octets d'une `auto_redirect` ou d'un nouvel essai (`retry`)
        sont scellés précédés d'`OUTBOX_REDIRECT_GUARD` : leur enveloppe
        est dans `sealed_to`, et un code qui lirait leurs en-têtes n'y
        trouve aucun destinataire. Appelable hors de toute transaction :
        sceller des dizaines de Mio ne tient pas le verrou d'écriture.
        """
        if kind == "auto_redirect" or retry:
            raw = OUTBOX_REDIRECT_GUARD + raw
        return (
            self._crypto.seal(raw),
            self._seal(recipients),
            self._seal(subject),
        )

    def _inserer_file(
        self,
        db,
        raw: bytes,
        recipients: str,
        subject: str,
        *,
        held: bool,
        kind: str,
        rule_id: str | None,
        source_key: str | None,
        expires_at: int | None,
        max_attempts: int,
        retry: bool = False,
        sealed: tuple[bytes, bytes, bytes] | None = None,
    ) -> int:
        """INSERT d'une entrée de file, SANS commit : l'appelant décide de
        la transaction qui l'englobe.

        `sealed`, rendu par `_sceller_file`, est écrit tel quel (`raw`,
        `recipients` et `subject` sont alors ignorés) ; sans lui, les blobs
        sont scellés ici. `retry` marque l'entrée de nouvel essai.
        """
        if sealed is None:
            sealed = self._sceller_file(
                raw, recipients, subject, kind=kind, retry=retry
            )
        scelle_raw, scelle_to, scelle_sujet = sealed
        curseur = db.execute(
            "INSERT INTO outbox(created_at, sealed_raw, sealed_to,"
            " sealed_subject, held, kind, rule_id, source_key, expires_at,"
            " max_attempts, retry) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(time.time()),
                scelle_raw,
                scelle_to,
                scelle_sujet,
                1 if held else 0,
                kind,
                rule_id,
                source_key,
                expires_at,
                int(max_attempts),
                1 if retry else 0,
            ),
        )
        return curseur.lastrowid

    @_locked
    def queue_message(
        self,
        raw: bytes,
        recipients: str,
        subject: str,
        *,
        held: bool = False,
        kind: str = "manual",
        rule_id: str | None = None,
        source_key: str | None = None,
        expires_at: int | None = None,
        max_attempts: int = OUTBOX_MAX_ATTEMPTS,
    ) -> int:
        """Met un message en attente. Rend son identifiant.

        Les arguments v6 sont des mots-clés seulement : un appel d'avant la
        v6, à trois arguments, met en file un envoi manuel comme avant.
        """
        db = self._db()
        queue_id = self._inserer_file(
            db,
            raw,
            recipients,
            subject,
            held=held,
            kind=kind,
            rule_id=rule_id,
            source_key=source_key,
            expires_at=expires_at,
            max_attempts=max_attempts,
        )
        db.commit()
        return queue_id

    @_locked
    def queue_auto(
        self,
        raw: bytes,
        recipients: str,
        subject: str,
        *,
        held: bool,
        rule_id: str,
        source_key: str,
        expires_at: int,
        outcome: str,
        reason: str,
        kind: str = "auto_reply",
    ) -> int:
        """Met en file l'envoi d'une règle ET l'inscrit au journal, dans
        UNE transaction. Rend l'identifiant de file.

        Une vidange, même dans un autre processus, ne voit donc jamais
        l'entrée de file avant que la ligne `rule_log` de `source_key` ne la
        nomme. Le journal n'avance que (voir `rule_log_set_outcome`) : une
        ligne déjà terminale garde son issue, l'entrée de file existe quand
        même.

        `kind` est l'un d'`OUTBOX_AUTO_KINDS`, sinon `ValueError` avant
        toute écriture. Pour `auto_redirect`, `recipients` EST l'enveloppe :
        les adresses d'envoi jointes par « , », que la vidange relit ; les
        autres types la portent dans leurs octets.
        """
        if kind not in OUTBOX_AUTO_KINDS:
            raise ValueError(kind)
        db = self._db()
        try:
            queue_id = self._inserer_file(
                db,
                raw,
                recipients,
                subject,
                held=held,
                kind=kind,
                rule_id=rule_id,
                source_key=source_key,
                expires_at=expires_at,
                max_attempts=OUTBOX_MAX_ATTEMPTS,
            )
            self._avancer_issue(
                db, rule_id, source_key, outcome, reason, queue_id
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return queue_id

    @_locked
    def outbox(self) -> list[dict]:
        """La file, du plus ancien au plus récent — l'ordre d'envoi.

        Les octets scellés ne sont pas lus : la liste se relit à chaque
        passe et à chaque rafraîchissement d'écran, et une entrée peut
        peser des dizaines de Mio. Ceux d'une entrée se lisent par
        `queued_raw`.
        """
        return [
            self._entree_file(r)
            for r in self._db().execute(
                f"SELECT {_OUTBOX_COLONNES} FROM outbox"
                " ORDER BY created_at, id"
            )
        ]

    @_locked
    def queued_entry(self, queue_id: int) -> dict | None:
        """L'entrée `queue_id` relue dans la base à l'instant, sous la forme
        d'un élément de `outbox` ; None si elle n'existe plus.

        Ce que la vidange envoie après avoir réservé l'entrée : l'instantané
        de `outbox` pris au début d'une passe ne voit pas une enveloppe
        réduite entre-temps par une vidange concurrente.
        """
        ligne = (
            self._db()
            .execute(
                f"SELECT {_OUTBOX_COLONNES} FROM outbox WHERE id = ?",
                (queue_id,),
            )
            .fetchone()
        )
        return self._entree_file(ligne) if ligne else None

    def _entree_file(self, r) -> dict:
        """Une ligne de `outbox` (colonnes `_OUTBOX_COLONNES`) en dict, les
        colonnes scellées ouvertes sauf les octets."""
        return {
            "id": r["id"],
            "created_at": r["created_at"],
            "to": self._open(r["sealed_to"]),
            "subject": self._open(r["sealed_subject"]),
            "held": bool(r["held"]),
            "attempts": r["attempts"],
            "last_error": self._open(r["sealed_error"]),
            "kind": r["kind"] or "manual",
            "rule_id": r["rule_id"],
            "source_key": r["source_key"],
            "expires_at": r["expires_at"],
            "max_attempts": r["max_attempts"],
            "perm_attempts": r["perm_attempts"],
            "claimed_at": r["claimed_at"],
            "retry": bool(r["retry"]),
        }

    @_locked
    def queued_raw(self, queue_id: int) -> bytes | None:
        """Les octets d'une entrée, tels que mis en file ; None si elle
        n'existe plus. Le préfixe d'une `auto_redirect` ou d'un nouvel
        essai est retiré."""
        ligne = (
            self._db()
            .execute(
                "SELECT sealed_raw, kind, retry FROM outbox WHERE id = ?",
                (queue_id,),
            )
            .fetchone()
        )
        if not ligne:
            return None
        raw = self._crypto.open(bytes(ligne[0]))
        if (ligne[1] == "auto_redirect" or ligne[2]) and raw.startswith(
            OUTBOX_REDIRECT_GUARD
        ):
            raw = raw[len(OUTBOX_REDIRECT_GUARD) :]
        return raw

    @_locked
    def set_held(self, queue_id: int, held: bool) -> None:
        """Retient un message, ou le relâche.

        Un message retenu ne part JAMAIS seul : c'est le sens de la
        retenue. Le relâcher est un geste, pas un délai qui expire.
        """
        db = self._db()
        db.execute(
            "UPDATE outbox SET held = ? WHERE id = ?",
            (1 if held else 0, queue_id),
        )
        db.commit()

    @_locked
    def drop_queued(self, queue_id: int) -> None:
        db = self._db()
        db.execute("DELETE FROM outbox WHERE id = ?", (queue_id,))
        db.commit()

    @_locked
    def outbox_claim(
        self, queue_id: int, now: int, stale_s: int = OUTBOX_CLAIM_STALE_S
    ) -> bool:
        """Réserve une entrée pour l'envoyer. Vrai si la réservation est à
        nous.

        Un seul UPDATE conditionnel : SQLite le rend atomique entre
        processus qui partagent `cache.db`, donc deux vidanges concurrentes
        n'envoient jamais la même entrée. Une réservation plus vieille que
        `stale_s` secondes est celle d'un processus mort en plein envoi, et
        se reprend.
        """
        db = self._db()
        curseur = db.execute(
            "UPDATE outbox SET claimed_at = ? WHERE id = ?"
            " AND (claimed_at IS NULL OR claimed_at < ?)",
            (int(now), queue_id, int(now) - int(stale_s)),
        )
        db.commit()
        return curseur.rowcount == 1

    @_locked
    def outbox_claim_refresh(self, queue_id: int, now: int) -> bool:
        """Rajeunit une réservation encore posée ; vrai si elle l'était.

        Appelé pendant l'envoi de l'entrée : un DATA long (gros transfert,
        lien lent) dépasse `OUTBOX_CLAIM_STALE_S`, et une autre vidange
        reprendrait sinon une entrée encore en cours d'envoi.
        """
        db = self._db()
        curseur = db.execute(
            "UPDATE outbox SET claimed_at = ?"
            " WHERE id = ? AND claimed_at IS NOT NULL",
            (int(now), queue_id),
        )
        db.commit()
        return curseur.rowcount == 1

    @_locked
    def outbox_held(self, queue_id: int) -> bool:
        """Vrai si l'entrée est retenue, lu dans la base à l'instant.

        Une retenue posée pendant une vidange (écran `o`, autre processus)
        n'est pas dans l'instantané qu'elle parcourt. Entrée absente :
        faux.
        """
        ligne = (
            self._db()
            .execute("SELECT held FROM outbox WHERE id = ?", (queue_id,))
            .fetchone()
        )
        return bool(ligne and ligne[0])

    @_locked
    def outbox_auto_held_count(self, now: int | None = None) -> int:
        """Le nombre d'entrées AUTOMATIQUES retenues de la file : celles
        qui attendent qu'on les relâche. Aucun octet scellé n'est lu.

        Avec `now`, une entrée dont l'échéance est passée n'est pas
        comptée : la vidange suivante la retire sans l'envoyer, il n'y a
        plus rien à approuver.
        """
        types = ", ".join("?" for _ in OUTBOX_AUTO_KINDS)
        requete = (
            f"SELECT COUNT(*) FROM outbox WHERE held = 1 AND kind IN ({types})"
        )
        valeurs: list = list(OUTBOX_AUTO_KINDS)
        if now is not None:
            requete += " AND (expires_at IS NULL OR expires_at >= ?)"
            valeurs.append(int(now))
        return self._db().execute(requete, valeurs).fetchone()[0]

    @_locked
    def outbox_release(self, queue_id: int) -> None:
        """Rend une entrée réservée à la file, sans compter d'échec."""
        db = self._db()
        db.execute(
            "UPDATE outbox SET claimed_at = NULL WHERE id = ?", (queue_id,)
        )
        db.commit()

    @_locked
    def record_send_failure(
        self,
        queue_id: int,
        message: str,
        *,
        permanent: bool = False,
        release: bool = True,
    ) -> dict:
        """Compte l'échec, garde SON texte scellé, et libère la réservation.

        Un compteur seul dirait qu'on a essayé cinq fois sans jamais dire
        pourquoi ça échoue, ce qui n'aide personne à corriger. Le texte vient
        du serveur et cite couramment le destinataire : il est scellé comme
        les autres colonnes de la ligne.

        `permanent` compte aussi le refus dans `perm_attempts`, que la
        vidange compare à `max_attempts`. Rend les trois compteurs après la
        mise à jour ; une entrée absente les rend à zéro.

        `release` faux garde la réservation : l'appelant écrit encore la
        suite du refus (clôture, enveloppe réduite) avant qu'une autre
        vidange puisse reprendre l'entrée, puis la rend (`outbox_release`).
        """
        db = self._db()
        db.execute(
            "UPDATE outbox SET attempts = attempts + 1, sealed_error = ?,"
            " perm_attempts = perm_attempts + ?,"
            " claimed_at = CASE WHEN ? THEN NULL ELSE claimed_at END"
            " WHERE id = ?",
            (
                self._seal((message or "")[:500]),
                1 if permanent else 0,
                1 if release else 0,
                queue_id,
            ),
        )
        db.commit()
        ligne = db.execute(
            "SELECT attempts, perm_attempts, max_attempts FROM outbox"
            " WHERE id = ?",
            (queue_id,),
        ).fetchone()
        if ligne is None:
            return {
                "attempts": 0,
                "perm_attempts": 0,
                "max_attempts": OUTBOX_MAX_ATTEMPTS,
            }
        return {
            "attempts": ligne["attempts"],
            "perm_attempts": ligne["perm_attempts"],
            "max_attempts": ligne["max_attempts"],
        }

    # -- Empreintes (v6) ------------------------------------------------

    def address_hash(self, address: str) -> str:
        """L'empreinte salée d'une adresse, insensible à la casse ; "" pour
        une adresse vide.

        Préfixée par « addr: » : une adresse et un Message-ID qui
        s'écriraient pareil ne donnent pas la même empreinte.
        """
        adresse = (address or "").strip().lower()
        return self._msgid_hash("addr:" + adresse) if adresse else ""

    @staticmethod
    def message_ref(msgid: str, uidvalidity: int, uid: int) -> str:
        """La préimage de la clé d'un message dans le journal des règles.

        Le Message-ID `strip()`é ; sans Message-ID,
        « ␠uid:<uidvalidity>:<uid> » : la chaîne vide serait commune à TOUS
        les messages sans Message-ID, et le premier journalisé ferait
        passer les autres pour des doublons.

        L'espace de tête rend les deux espaces de clés disjoints : un
        Message-ID passe par `strip()`, il ne commence donc jamais par un
        blanc. Sans lui, un tiers qui écrit `Message-ID: uid:1:7` occuperait
        d'avance la clé du message sans Message-ID d'UIDVALIDITY 1, UID 7.
        """
        msgid = (msgid or "").strip()
        if msgid:
            return msgid
        return f" uid:{int(uidvalidity)}:{int(uid)}"

    def message_key(self, msgid: str, uidvalidity: int, uid: int) -> str:
        """La clé d'un message dans le journal des règles : l'empreinte de
        `message_ref`. Avec un Message-ID, elle égale
        `messages.msgid_hash`."""
        return self._msgid_hash(self.message_ref(msgid, uidvalidity, uid))

    # -- Lecture pour le moteur de règles (v6) ---------------------------

    @_locked
    def uids_between(
        self, folder_id: int, after_uid: int, upto_uid: int
    ) -> list[int]:
        """Les UID en cache tels que `after_uid < uid <= upto_uid`,
        croissants."""
        return [
            r[0]
            for r in self._db().execute(
                "SELECT uid FROM messages WHERE folder_id = ?"
                " AND uid > ? AND uid <= ? ORDER BY uid",
                (folder_id, int(after_uid), int(upto_uid)),
            )
        ]

    # -- Journal des règles (v6) ----------------------------------------

    @_locked
    def rule_log_claim(
        self,
        rule_id: str,
        msg_key: str,
        *,
        outcome: str,
        at: int,
        reason: str | None = None,
        sender_hash: str | None = None,
        target_hash: str | None = None,
        fingerprint: str | None = None,
        received_at: int | None = None,
        sender: str = "",
        subject: str = "",
        queue_id: int | None = None,
        msg_ref: str | None = None,
        target: str = "",
    ) -> bool:
        """Inscrit (règle, message) au journal. Vrai si la ligne vient
        d'être créée.

        `INSERT OR IGNORE` sur `UNIQUE(rule_id, msg_key)` : de deux
        processus qui traitent le même message, un seul obtient `True`, et
        c'est lui seul qui envoie. Expéditeur et sujet sont scellés, comme
        `msg_ref` (la préimage de `msg_key`, `message_ref`) et `target`
        (l'adresse de `target_hash`) : une conversion recalcule ces
        empreintes sous un autre sel à partir d'eux.
        """
        db = self._db()
        curseur = db.execute(
            "INSERT OR IGNORE INTO rule_log(rule_id, msg_key, sender_hash,"
            " target_hash, fingerprint, at, received_at, outcome, reason,"
            " queue_id, sealed_sender, sealed_subject, sealed_msg_ref,"
            " sealed_target)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rule_id,
                msg_key,
                sender_hash,
                target_hash,
                fingerprint,
                int(at),
                received_at or None,
                outcome,
                reason,
                queue_id,
                self._seal(sender),
                self._seal(subject),
                self._seal(msg_ref) if msg_ref else None,
                self._seal(target) if target else None,
            ),
        )
        db.commit()
        return curseur.rowcount == 1

    @_locked
    def rule_log_seen(self, rule_id: str, msg_key: str) -> bool:
        """Vrai si (règle, message) est déjà au journal, quelle que soit
        l'issue."""
        return (
            self._db()
            .execute(
                "SELECT 1 FROM rule_log WHERE rule_id = ? AND msg_key = ?",
                (rule_id, msg_key),
            )
            .fetchone()
            is not None
        )

    def _avancer_issue(
        self, db, rule_id, msg_key, outcome, reason, queue_id, sent_at=None
    ) -> bool:
        """L'UPDATE de `rule_log_set_outcome`, SANS commit.

        `reason` remplace la raison précédente : elle explique la nouvelle
        issue, pas l'ancienne. `queue_id` absent garde celui déjà inscrit,
        pour que le lien vers la file survive au passage à `sent`.
        `sent_at` absent garde la valeur inscrite.
        """
        terminales = ",".join("?" for _ in RULE_LOG_TERMINAL)
        curseur = db.execute(
            "UPDATE rule_log SET outcome = ?, reason = ?,"
            " queue_id = COALESCE(?, queue_id),"
            " sent_at = COALESCE(?, sent_at)"
            " WHERE rule_id = ? AND msg_key = ?"
            f" AND outcome NOT IN ({terminales})",
            (
                outcome,
                reason,
                queue_id,
                None if sent_at is None else int(sent_at),
                rule_id,
                msg_key,
                *RULE_LOG_TERMINAL,
            ),
        )
        return curseur.rowcount > 0

    @_locked
    def rule_log_set_outcome(
        self,
        rule_id: str,
        msg_key: str,
        outcome: str,
        reason: str | None = None,
        queue_id: int | None = None,
        sent_at: int | None = None,
    ) -> bool:
        """Fait AVANCER l'issue d'une ligne. Vrai si une ligne a changé.

        Une issue de `RULE_LOG_TERMINAL` n'est jamais réécrite : une vidange
        concurrente peut avoir envoyé l'entrée de file avant que le moteur
        n'écrive `queued`, et rétrograder `sent` ferait croire à un envoi
        encore à faire. `partial` en est : un `expired` ou un `failed`
        effacerait des plafonds un message parti. `sent_at` est l'époque
        du départ réel, que lisent les plafonds par heure
        (`rule_log_recent_sends`, `rule_log_sent_since`).
        """
        db = self._db()
        change = self._avancer_issue(
            db, rule_id, msg_key, outcome, reason, queue_id, sent_at
        )
        db.commit()
        return change

    def _ecriture(self):
        """La connexion, sous le verrou d'écriture de SQLite pris AVANT la
        première lecture (`BEGIN IMMEDIATE`) : une méthode qui relit une
        ligne puis l'écrit ne croise pas un autre processus entre les
        deux."""
        db = self._db()
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        return db

    @_locked
    def rule_log_rcpt_result(
        self,
        rule_id: str,
        msg_key: str,
        *,
        total: int,
        dropped=(),
        pending=(),
        sent_at: int,
        retry_raw: bytes | None = None,
        retry_to: str = "",
        retry_subject: str = "",
        kind: str = "auto_reply",
        expires_at: int | None = None,
        drop_queue_id: int | None = None,
    ) -> RcptResult:
        """Inscrit le résultat d'un départ qui a servi au moins un
        destinataire et en a vu refuser, ou d'un nouvel essai parti.

        `total` est la taille de l'enveloppe essayée (gardée seulement au
        premier départ), `dropped` les codes des refusés abandonnés,
        `pending` ceux des refusés qu'un nouvel essai portera. `pending`
        non vide exige `retry_raw` et `retry_to` (octets et enveloppe de
        l'entrée de nouvel essai), et réciproquement ; `kind` est l'un
        d'`OUTBOX_AUTO_KINDS`. Sinon `ValueError`, avant toute écriture.

        Les blobs du nouvel essai sont scellés avant le verrou d'écriture.
        Puis, en UNE transaction : l'entrée de nouvel essai est créée
        (jamais retenue, échéance `expires_at`), l'entrée `drop_queue_id`
        (celle qui vient de partir) est retirée, et la ligne avance :
        `partial` (raison `rcpt_retry` si quelqu'un attend, sinon
        `rcpt_refused`), ou `sent` quand plus personne n'attend ni n'a été
        abandonné (raison `rcpt_retried` après un nouvel essai). Le
        premier départ écrit `sent_at`, un nouvel essai `retry_sent_at`.
        Une ligne absente, ou d'une issue terminale autre que `partial`,
        n'est pas touchée et rien n'est créé ; l'entrée `drop_queue_id`
        part quand même (le message est parti). Toute erreur annule la
        transaction entière.
        """
        if kind not in OUTBOX_AUTO_KINDS:
            raise ValueError(kind)
        dropped = list(dropped or ())
        pending = list(pending or ())
        if bool(pending) != bool(retry_raw is not None and retry_to):
            raise ValueError("pending")
        sealed = None
        if pending:
            sealed = self._sceller_file(
                retry_raw, retry_to, retry_subject, kind=kind, retry=True
            )
        db = self._ecriture()
        try:
            ligne = db.execute(
                "SELECT outcome, reason, rcpt_dropped FROM rule_log"
                " WHERE rule_id = ? AND msg_key = ?",
                (rule_id, msg_key),
            ).fetchone()
            if ligne is None or ligne["outcome"] not in (
                "pending",
                "queued",
                "held",
                "partial",
            ):
                if drop_queue_id is not None:
                    db.execute(
                        "DELETE FROM outbox WHERE id = ?", (drop_queue_id,)
                    )
                db.commit()
                return RcptResult(False)
            nouvel_essai = None
            if pending:
                # INSERT avant le DELETE : l'entrée neuve ne reprend jamais
                # l'identifiant de celle qui vient de partir, qu'une vidange
                # concurrente peut encore tenir dans son instantané.
                nouvel_essai = self._inserer_file(
                    db,
                    b"",
                    "",
                    "",
                    held=False,
                    kind=kind,
                    rule_id=rule_id,
                    source_key=msg_key,
                    expires_at=expires_at,
                    max_attempts=OUTBOX_MAX_ATTEMPTS,
                    retry=True,
                    sealed=sealed,
                )
            if drop_queue_id is not None:
                db.execute("DELETE FROM outbox WHERE id = ?", (drop_queue_id,))
            essai = ligne["outcome"] == "partial"
            anciens = _codes_list(ligne["rcpt_dropped"]) if essai else []
            abandon = sorted(anciens + dropped)
            attente = sorted(pending)
            if not abandon and not attente:
                issue = "sent"
                raison = "rcpt_retried" if essai else ligne["reason"]
            else:
                issue = "partial"
                raison = "rcpt_retry" if attente else "rcpt_refused"
            colonne = "retry_sent_at" if essai else "sent_at"
            db.execute(
                f"UPDATE rule_log SET outcome = ?, reason = ?, {colonne} = ?,"
                " rcpt_total = COALESCE(rcpt_total, ?),"
                " rcpt_dropped = ?, rcpt_pending = ?,"
                " queue_id = COALESCE(?, queue_id)"
                " WHERE rule_id = ? AND msg_key = ?",
                (
                    issue,
                    raison,
                    int(sent_at),
                    int(total),
                    _codes_text(abandon),
                    _codes_text(attente),
                    nouvel_essai,
                    rule_id,
                    msg_key,
                ),
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return RcptResult(True, nouvel_essai)

    @_locked
    def rule_log_retry_closed(
        self,
        rule_id: str,
        msg_key: str,
        reason: str,
        *,
        drop_queue_id: int | None = None,
        codes=None,
    ) -> bool:
        """Clôt sans départ le nouvel essai d'une ligne `partial` : retire
        l'entrée `drop_queue_id`, verse les codes en attente (ou `codes`,
        ceux du dernier refus, quand ils sont donnés) dans les abandonnés,
        la raison devient `reason`, l'issue reste `partial`.

        Vrai si une ligne a changé. Seule une ligne `partial` dont un
        nouvel essai attend (`rcpt_retry`) et qui nomme cette entrée
        (`queue_id`, quand `drop_queue_id` est donné) est touchée : une
        entrée égarée ne vide pas l'attente d'une autre. L'entrée est
        retirée quand même. Retrait et écriture forment UNE transaction :
        une ligne qui annonce un nouvel essai en file en a toujours un.
        """
        db = self._ecriture()
        try:
            if drop_queue_id is not None:
                db.execute("DELETE FROM outbox WHERE id = ?", (drop_queue_id,))
            ligne = db.execute(
                "SELECT outcome, reason, queue_id, rcpt_dropped, rcpt_pending"
                " FROM rule_log WHERE rule_id = ? AND msg_key = ?",
                (rule_id, msg_key),
            ).fetchone()
            if (
                ligne is None
                or ligne["outcome"] != "partial"
                or ligne["reason"] != "rcpt_retry"
                or (
                    drop_queue_id is not None
                    and ligne["queue_id"] != drop_queue_id
                )
            ):
                db.commit()
                return False
            verses = (
                list(codes)
                if codes is not None
                else _codes_list(ligne["rcpt_pending"])
            )
            abandon = _codes_list(ligne["rcpt_dropped"]) + verses
            db.execute(
                "UPDATE rule_log SET reason = ?, rcpt_dropped = ?,"
                " rcpt_pending = NULL WHERE rule_id = ? AND msg_key = ?",
                (reason, _codes_text(abandon), rule_id, msg_key),
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return True

    @_locked
    def rule_log_retry_narrowed(
        self,
        rule_id: str,
        msg_key: str,
        queue_id: int,
        *,
        retry_to: str,
        pending,
        dropped,
        tried=None,
    ) -> bool:
        """Réduit l'enveloppe de l'entrée de nouvel essai `queue_id` après
        un refus total où se mêlent des 4xx et d'autres codes :
        `sealed_to` = `retry_to`, `rcpt_pending` = `pending`, `dropped`
        ajoutés à `rcpt_dropped`.

        Vrai si la ligne, `partial/rcpt_retry` et liée à `queue_id`, a
        changé ; sinon rien n'est écrit. `pending` vide : `ValueError`
        (l'entrée n'a plus rien à réessayer). `retry_to` est scellé avant
        le verrou ; l'entrée et la ligne s'écrivent en UNE transaction.

        Idempotente : rien n'est écrit quand l'enveloppe en file vaut déjà
        `retry_to`, ni quand elle diffère de `tried` (l'enveloppe essayée,
        si elle est donnée). Un refus lu sur une enveloppe déjà réduite
        n'ajoute donc pas une seconde fois ses codes abandonnés.
        """
        pending = list(pending or ())
        if not pending:
            raise ValueError("pending")
        scelle_to = self._seal(retry_to)
        db = self._ecriture()
        try:
            ligne = db.execute(
                "SELECT outcome, reason, queue_id, rcpt_dropped FROM rule_log"
                " WHERE rule_id = ? AND msg_key = ?",
                (rule_id, msg_key),
            ).fetchone()
            entree = db.execute(
                "SELECT sealed_to FROM outbox WHERE id = ? AND retry = 1",
                (queue_id,),
            ).fetchone()
            actuelle = (
                _envelope_key(self._open(entree["sealed_to"]))
                if entree
                else None
            )
            if (
                ligne is None
                or entree is None
                or ligne["outcome"] != "partial"
                or ligne["reason"] != "rcpt_retry"
                or ligne["queue_id"] != queue_id
                or actuelle == _envelope_key(retry_to)
                or (
                    tried is not None
                    and actuelle != _envelope_key(", ".join(tried))
                )
            ):
                db.commit()
                return False
            curseur = db.execute(
                "UPDATE outbox SET sealed_to = ? WHERE id = ? AND retry = 1",
                (scelle_to, queue_id),
            )
            if curseur.rowcount != 1:
                db.rollback()
                return False
            abandon = _codes_list(ligne["rcpt_dropped"]) + list(dropped or ())
            db.execute(
                "UPDATE rule_log SET rcpt_pending = ?, rcpt_dropped = ?"
                " WHERE rule_id = ? AND msg_key = ?",
                (
                    _codes_text(pending),
                    _codes_text(abandon),
                    rule_id,
                    msg_key,
                ),
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return True

    @_locked
    def rule_log_retry_departed(
        self, rule_id: str, msg_key: str, sent_at: int
    ) -> bool:
        """Inscrit seulement l'époque du départ d'un nouvel essai
        (`retry_sent_at`) sur une ligne `partial`. Vrai si une ligne a
        changé.

        Le repli d'une vidange dont le journal complet n'a pas pu s'écrire :
        une transaction SMTP partie compte aux plafonds par heure même
        quand le reste de la ligne n'est pas à jour.
        """
        db = self._db()
        curseur = db.execute(
            "UPDATE rule_log SET retry_sent_at = ?"
            " WHERE rule_id = ? AND msg_key = ? AND outcome = 'partial'",
            (int(sent_at), rule_id, msg_key),
        )
        db.commit()
        return curseur.rowcount > 0

    @_locked
    def rule_log_state(self, rule_id: str, msg_key: str) -> dict | None:
        """`outcome`, `reason` et `queue_id` de la ligne, None si elle est
        absente : ce que la vidange vérifie avant d'envoyer un nouvel
        essai."""
        ligne = (
            self._db()
            .execute(
                "SELECT outcome, reason, queue_id FROM rule_log"
                " WHERE rule_id = ? AND msg_key = ?",
                (rule_id, msg_key),
            )
            .fetchone()
        )
        if ligne is None:
            return None
        return {
            "outcome": ligne["outcome"],
            "reason": ligne["reason"],
            "queue_id": ligne["queue_id"],
        }

    @_locked
    def rule_log_outcome(self, rule_id: str, msg_key: str) -> str | None:
        ligne = (
            self._db()
            .execute(
                "SELECT outcome FROM rule_log WHERE rule_id = ? AND msg_key = ?",
                (rule_id, msg_key),
            )
            .fetchone()
        )
        return ligne[0] if ligne else None

    @_locked
    def rule_log_fingerprint(self, rule_id: str, msg_key: str) -> str | None:
        ligne = (
            self._db()
            .execute(
                "SELECT fingerprint FROM rule_log"
                " WHERE rule_id = ? AND msg_key = ?",
                (rule_id, msg_key),
            )
            .fetchone()
        )
        return ligne[0] if ligne else None

    @_locked
    def rule_log_last_send(
        self,
        rule_id: str,
        sender_hash: str,
        target_hash: str | None = None,
    ) -> int | None:
        """Le moment du dernier envoi de CETTE règle vers cet expéditeur OU
        cette cible ; `None` s'il n'y en a pas.

        Compte comme envoi toute issue de `RULE_LOG_SEND_OUTCOMES`, et les
        couples (issue, raison) de `RULE_LOG_SEND_LIKE` : un message qu'une
        AUTRE machine a revendiqué y a reçu sa réponse, et un envoi
        interrompu est peut-être parti. Sans eux, deux machines
        répondraient chacune à un message différent du même expéditeur
        dans la fenêtre. L'heure comptée est celle où cette machine a écrit
        sa ligne, postérieure au départ réel : la fenêtre s'allonge un peu,
        jamais ne raccourcit.

        Le From est la clé principale : une adresse d'enveloppe qui change
        à chaque message (VERP, BATV, SRS) ne contourne donc pas la limite.
        Une empreinte vide ou `None` ne correspond à aucune ligne.
        """
        envois = ",".join("?" for _ in RULE_LOG_SEND_OUTCOMES)
        semblables = " OR ".join(
            "(outcome = ? AND reason = ?)" for _ in RULE_LOG_SEND_LIKE
        )
        ligne = (
            self._db()
            .execute(
                "SELECT MAX(at) FROM rule_log WHERE rule_id = ?"
                " AND (sender_hash = ? OR target_hash = ?)"
                f" AND (outcome IN ({envois}) OR {semblables})",
                (
                    rule_id,
                    sender_hash or None,
                    target_hash or None,
                    *RULE_LOG_SEND_OUTCOMES,
                    *(v for couple in RULE_LOG_SEND_LIKE for v in couple),
                ),
            )
            .fetchone()
        )
        return ligne[0] if ligne and ligne[0] is not None else None

    @_locked
    def rule_log_resume(self) -> tuple[int, int]:
        """Règle les lignes `pending` laissées par une passe morte ; rend
        `(supprimées, incertaines)`.

        Une ligne `pending` n'a d'autre écrivain que le moteur, toujours
        sous le verrou du compte, qui se relâche quand le processus meurt :
        appelée en début de passe sous ce verrou, toute ligne `pending` est
        celle d'une passe qui n'a pas fini. `pending/ready` (revendiqué,
        rien n'est parti) est SUPPRIMÉE : le message, curseur non avancé,
        est réévalué comme neuf. `pending/sending` (remis à l'envoi) et
        `pending` sans raison (ligne d'une version qui ne marquait pas
        l'envoi) passent en `failed/send_uncertain` : le message est
        peut-être parti avant que l'issue ne s'écrive, il n'est jamais
        renvoyé. En une transaction ; toute erreur annule tout.
        """
        db = self._ecriture()
        try:
            supprimees = db.execute(
                "DELETE FROM rule_log WHERE outcome = 'pending'"
                " AND reason = 'ready'"
            ).rowcount
            incertaines = db.execute(
                "UPDATE rule_log SET outcome = 'failed',"
                " reason = 'send_uncertain' WHERE outcome = 'pending'"
                " AND (reason IS NULL OR reason <> 'ready')"
            ).rowcount
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return supprimees, incertaines

    # -- Revendication des messages sur le serveur -------------------

    @_locked
    def rule_claim_state(self, uidvalidity: int, uid: int) -> str | None:
        """L'état de revendication inscrit pour ce message d'INBOX, None
        sans ligne."""
        ligne = (
            self._db()
            .execute(
                "SELECT state FROM rule_claim WHERE uidvalidity = ?"
                " AND uid = ?",
                (int(uidvalidity), int(uid)),
            )
            .fetchone()
        )
        return ligne[0] if ligne else None

    @_locked
    def rule_claim_intent(self, uidvalidity: int, uid: int) -> str:
        """Inscrit l'intention de revendiquer, et rend l'état inscrit.

        Validée AVANT que l'appelant n'envoie le STORE : un processus tué
        pendant le STORE laisse `intent`, que la passe suivante reconnaît.
        Seule une ligne `retry` (ou l'absence de ligne) devient `intent` ;
        un état final reste ce qu'il est.
        """
        db = self._db()
        db.execute(
            "INSERT INTO rule_claim(uidvalidity, uid, state, mode)"
            " VALUES(?, ?, 'intent', NULL)"
            " ON CONFLICT(uidvalidity, uid) DO UPDATE SET state = 'intent'"
            " WHERE rule_claim.state = 'retry'",
            (int(uidvalidity), int(uid)),
        )
        db.commit()
        return self._etat_revendication(db, uidvalidity, uid)

    @_locked
    def rule_claim_drop_intent(self, uidvalidity: int, uid: int) -> None:
        """Ramène une ligne `intent` à `retry`, compteur d'échecs gardé.

        Appelée quand le STORE n'a sûrement PAS été appliqué (MODIFIED,
        refus du serveur) : sinon un mot-clé posé ensuite par une autre
        machine se lirait comme une revendication peut-être nôtre.
        """
        db = self._db()
        db.execute(
            "UPDATE rule_claim SET state = 'retry' WHERE uidvalidity = ?"
            " AND uid = ? AND state = 'intent'",
            (int(uidvalidity), int(uid)),
        )
        db.commit()

    @_locked
    def rule_claim_set(
        self, uidvalidity: int, uid: int, state: str, *, mode: str = ""
    ) -> str:
        """Inscrit un état final (`RULE_CLAIM_FINAL`), et rend l'état
        inscrit après l'appel.

        Un état final n'est jamais réécrit : seules une ligne `intent` ou
        `retry`, ou l'absence de ligne, prennent `state`. Un état hors de
        `RULE_CLAIM_FINAL` lève `ValueError` avant toute écriture.
        """
        if state not in RULE_CLAIM_FINAL:
            raise ValueError(state)
        db = self._db()
        db.execute(
            "INSERT INTO rule_claim(uidvalidity, uid, state, mode)"
            " VALUES(?, ?, ?, ?)"
            " ON CONFLICT(uidvalidity, uid) DO UPDATE SET"
            " state = excluded.state, mode = excluded.mode"
            " WHERE rule_claim.state IN ('intent', 'retry')",
            (int(uidvalidity), int(uid), state, mode or None),
        )
        db.commit()
        return self._etat_revendication(db, uidvalidity, uid)

    @_locked
    def rule_claim_failed(self, uidvalidity: int, uid: int) -> int:
        """Compte une passe de plus dont la revendication a échoué, et rend
        le nouveau compte. L'état n'est pas touché : une `intent` reste
        `intent`."""
        db = self._db()
        db.execute(
            "INSERT INTO rule_claim(uidvalidity, uid, state, mode, failures)"
            " VALUES(?, ?, 'retry', NULL, 1)"
            " ON CONFLICT(uidvalidity, uid) DO UPDATE SET"
            " failures = rule_claim.failures + 1",
            (int(uidvalidity), int(uid)),
        )
        db.commit()
        ligne = db.execute(
            "SELECT failures FROM rule_claim WHERE uidvalidity = ?"
            " AND uid = ?",
            (int(uidvalidity), int(uid)),
        ).fetchone()
        return int(ligne[0]) if ligne else 0

    @staticmethod
    def _etat_revendication(db, uidvalidity, uid) -> str | None:
        ligne = db.execute(
            "SELECT state FROM rule_claim WHERE uidvalidity = ? AND uid = ?",
            (int(uidvalidity), int(uid)),
        ).fetchone()
        return ligne[0] if ligne else None

    @_locked
    def rule_log_sent_count(self, rule_id: str, fingerprint: str) -> int:
        """Combien de réponses de cette règle, sous cette empreinte, sont
        réellement parties, vers tous leurs destinataires ou une partie :
        une ligne par message, quel que soit le nombre de nouveaux essais.

        Une règle modifiée change d'empreinte : son compteur repart de zéro.
        """
        parties = ",".join("?" for _ in RULE_LOG_DEPARTED)
        return (
            self._db()
            .execute(
                "SELECT COUNT(*) FROM rule_log WHERE rule_id = ?"
                f" AND fingerprint = ? AND outcome IN ({parties})",
                (rule_id, fingerprint, *RULE_LOG_DEPARTED),
            )
            .fetchone()[0]
        )

    @_locked
    def outbox_rule_count(self, rule_id: str) -> int:
        """Le nombre d'entrées de la file mises par la règle `rule_id`,
        retenues ou non. Aucun octet scellé n'est lu."""
        return (
            self._db()
            .execute(
                "SELECT COUNT(*) FROM outbox WHERE rule_id = ?", (rule_id,)
            )
            .fetchone()[0]
        )

    @_locked
    def rule_log_recent_sends(self, since: int) -> int:
        """Combien d'envois automatiques du compte, toutes règles
        confondues, sont partis à `since` ou après, ou attendent en file,
        décidés à `since` ou après.

        Une issue `sent` compte à l'époque de son départ réel (`sent_at`,
        `at` à défaut) : une réponse partie d'une file vidée longtemps après
        sa décision occupe l'heure où elle part. Une issue `queued` compte à
        l'époque de sa décision (`at`). Une réponse retenue n'y entre pas
        tant qu'elle n'est pas partie : c'est le plafond glissant par heure
        qui la retient.

        Une issue `partial` compte comme `sent` à son premier départ, puis
        une fois de plus quand un nouvel essai part (`retry_sent_at` à
        `since` ou après) ; jamais aussi comme `queued` tant que son
        nouvel essai attend.
        """
        parties = ",".join("?" for _ in RULE_LOG_DEPARTED)
        depuis = int(since)
        return (
            self._db()
            .execute(
                "SELECT (SELECT COUNT(*) FROM rule_log WHERE"
                f" (outcome IN ({parties}) AND COALESCE(sent_at, at) >= ?)"
                " OR (outcome = 'queued' AND at >= ?))"
                " + (SELECT COUNT(*) FROM rule_log WHERE retry_sent_at >= ?)",
                (*RULE_LOG_DEPARTED, depuis, depuis, depuis),
            )
            .fetchone()[0]
        )

    @_locked
    def rule_log_sent_since(self, since: int) -> int:
        """Combien d'envois automatiques du compte sont réellement partis
        à `since` ou après (`sent_at`, `at` à défaut), file exclue : le
        compte que la vidange de la file oppose au plafond par heure.

        Chaque transaction SMTP qui a servi quelqu'un compte une fois, à
        l'instant où elle part : une ligne `sent` ou `partial` à son
        premier départ, plus une fois quand un nouvel essai part
        (`retry_sent_at`).
        """
        parties = ",".join("?" for _ in RULE_LOG_DEPARTED)
        depuis = int(since)
        return (
            self._db()
            .execute(
                "SELECT (SELECT COUNT(*) FROM rule_log WHERE"
                f" outcome IN ({parties}) AND COALESCE(sent_at, at) >= ?)"
                " + (SELECT COUNT(*) FROM rule_log WHERE retry_sent_at >= ?)",
                (*RULE_LOG_DEPARTED, depuis, depuis),
            )
            .fetchone()[0]
        )

    @_locked
    def rule_log_rule_sends(self, rule_id: str, since: int) -> int:
        """Les décisions d'envoi de CETTE règle à `since` ou après, issues
        `sent`, `partial`, `queued` et `held`.

        Une réponse retenue compte : elle est décidée, et partira si
        quelqu'un la libère.
        """
        return (
            self._db()
            .execute(
                "SELECT COUNT(*) FROM rule_log WHERE rule_id = ? AND at >= ?"
                " AND outcome IN ('sent', 'partial', 'queued', 'held')",
                (rule_id, int(since)),
            )
            .fetchone()[0]
        )

    @_locked
    def rule_log_entries(
        self, rule_id: str | None = None, limit: int = 200
    ) -> list[dict]:
        """Les lignes du journal, les plus récentes d'abord, expéditeur et
        sujet ouverts.

        `rcpt_total` (taille de l'enveloppe du premier départ, ou None),
        `rcpt_dropped` et `rcpt_pending` (codes SMTP des destinataires
        abandonnés et en attente d'un nouvel essai, listes d'entiers)
        décrivent un départ refusé en partie ; `sent_at` et
        `retry_sent_at` sont le premier départ et le dernier nouvel essai
        parti.
        """
        clause, params = "", []
        if rule_id is not None:
            clause = " WHERE rule_id = ?"
            params.append(rule_id)
        params.append(int(limit))
        return [
            {
                "rule_id": r["rule_id"],
                "at": r["at"],
                "received_at": r["received_at"],
                "outcome": r["outcome"],
                "reason": r["reason"],
                "sender": self._open(r["sealed_sender"]),
                "subject": self._open(r["sealed_subject"]),
                "queue_id": r["queue_id"],
                "rcpt_total": r["rcpt_total"],
                "rcpt_dropped": _codes_list(r["rcpt_dropped"]),
                "rcpt_pending": _codes_list(r["rcpt_pending"]),
                "sent_at": r["sent_at"],
                "retry_sent_at": r["retry_sent_at"],
            }
            for r in self._db().execute(
                f"SELECT * FROM rule_log{clause} ORDER BY at DESC, id DESC"
                " LIMIT ?",
                params,
            )
        ]

    # -- Envois automatiques (v6) ---------------------------------------

    @_locked
    def mark_auto_sent(self, msgid: str, rule_id: str, at: int) -> None:
        """Retient l'empreinte du Message-ID d'une réponse automatique.

        Un Message-ID vide n'est pas retenu : son empreinte serait celle de
        tous les messages sans Message-ID, qui sortiraient alors tous des
        statistiques.
        """
        msgid = (msgid or "").strip()
        if not msgid:
            return
        db = self._db()
        db.execute(
            "INSERT OR IGNORE INTO auto_sent(msgid_hash, rule_id, at,"
            " sealed_msgid) VALUES(?,?,?,?)",
            (self._msgid_hash(msgid), rule_id, int(at), self._seal(msgid)),
        )
        db.commit()

    @_locked
    def mark_auto_sent_many(self, items: list[tuple[str, str, int]]) -> None:
        """`mark_auto_sent` pour chaque (msgid, rule_id, at), en une
        transaction ; un Message-ID vide est ignoré."""
        rows = [
            (
                self._msgid_hash(msgid.strip()),
                rule_id,
                int(at),
                self._seal(msgid.strip()),
            )
            for msgid, rule_id, at in items
            if (msgid or "").strip()
        ]
        if not rows:
            return
        db = self._db()
        db.executemany(
            "INSERT OR IGNORE INTO auto_sent(msgid_hash, rule_id, at,"
            " sealed_msgid) VALUES(?,?,?,?)",
            rows,
        )
        db.commit()

    @_locked
    def is_auto_sent(self, msgid_hash: str) -> bool:
        return (
            self._db()
            .execute(
                "SELECT 1 FROM auto_sent WHERE msgid_hash = ?", (msgid_hash,)
            )
            .fetchone()
            is not None
        )

    @_locked
    def is_rule_send(self, msgid: str, rule_ids=None) -> bool:
        """Vrai si `msgid` est le Message-ID d'un envoi d'une règle.

        Les messages automatiques de tiers, inscrits dans `auto_sent` par la
        synchronisation avec un `rule_id` vide, n'en sont pas. `rule_ids`,
        s'il est fourni, restreint aux envois de ces règles ; vide, rien ne
        correspond.
        """
        msgid = (msgid or "").strip()
        if not msgid:
            return False
        sql = (
            "SELECT 1 FROM auto_sent WHERE msgid_hash = ?"
            " AND rule_id IS NOT NULL AND rule_id <> ''"
        )
        params = [self._msgid_hash(msgid)]
        if rule_ids is not None:
            ids = [str(r) for r in rule_ids]
            if not ids:
                return False
            sql += f" AND rule_id IN ({', '.join('?' for _ in ids)})"
            params.extend(ids)
        return self._db().execute(sql, params).fetchone() is not None

    # -- Époque du cache (v6) -------------------------------------------

    @_locked
    def cache_epoch(self) -> str:
        """Un jeton tiré une fois par fichier `cache.db` et par clé, puis
        stable.

        Le journal des règles vit dans ce fichier : un cache recréé le perd,
        et reçoit une époque neuve qui permet de le constater. `purge_all`
        garde `meta`, donc l'époque.

        Une clé changée sur un `cache.db` conservé vaut un cache recréé :
        chaque `msg_key` et chaque empreinte d'adresse est salée par la clé,
        donc l'ancien journal ne correspond plus à rien et la limite de
        débit le lirait vide. `cache_epoch_check` lie l'époque au sel ; s'il
        ne correspond plus, l'époque est retirée, et les lignes de
        `rule_log` et `auto_sent` écrites sous l'ancienne clé partent :
        illisibles, elles feraient lever `rule_log_entries`.

        Le tirage se fait sous `BEGIN IMMEDIATE` avec relecture : deux
        processus qui la tirent en même temps lisent la même.

        Une conversion recopie l'époque et recalcule son contrôle : elle
        n'est pas une recréation.
        """
        db = self._db()
        controle = self._msgid_hash("cache_epoch")

        def lire() -> dict:
            return {
                r[0]: r[1]
                for r in db.execute(
                    "SELECT key, value FROM meta"
                    " WHERE key IN ('cache_epoch', 'cache_epoch_check')"
                )
            }

        valeurs = lire()
        if (
            valeurs.get("cache_epoch")
            and valeurs.get("cache_epoch_check") == controle
        ):
            return valeurs["cache_epoch"]
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        try:
            valeurs = lire()
            if (
                valeurs.get("cache_epoch")
                and valeurs.get("cache_epoch_check") == controle
            ):
                db.commit()
                return valeurs["cache_epoch"]
            if valeurs.get("cache_epoch_check"):
                # Contrôle présent mais différent : la clé a changé.
                db.execute("DELETE FROM rule_log")
                db.execute("DELETE FROM auto_sent")
            epoque = os.urandom(8).hex()
            db.executemany(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                (("cache_epoch", epoque), ("cache_epoch_check", controle)),
            )
            db.commit()
            return epoque
        except BaseException:
            db.rollback()
            raise

    # -- Statistiques (phase 3) -----------------------------------------

    BUCKETS = {
        "day": "%Y-%m-%d",
        "week": "%Y-S%W",
        "month": "%Y-%m",
        "year": "%Y",
    }

    def _filtre(self, folder_id, since, until):
        """(fragment WHERE, paramètres). Un filtre absent ne filtre pas."""
        clauses, params = ["date > 0"], []
        if folder_id is not None:
            clauses.append("folder_id = ?")
            params.append(folder_id)
        if since is not None:
            clauses.append("date >= ?")
            params.append(int(since))
        if until is not None:
            clauses.append("date < ?")
            params.append(int(until))
        return " AND ".join(clauses), params

    @_locked
    def stats_volume(
        self, bucket="day", folder_id=None, since=None, until=None
    ) -> list[tuple]:
        """(étiquette, nombre, octets) par jour, semaine ou mois.

        `date = 0` marque une date illisible — voir `parse_fetch_headers`,
        où un en-tête invalide n'a jamais le droit de perdre le message.
        Ces messages existent, mais les ranger au 1er janvier 1970
        fabriquerait un pic qui n'a jamais eu lieu : ils sont exclus, et
        `stats_undated` les compte à part pour qu'on puisse le DIRE.
        """
        forme = self.BUCKETS.get(bucket, self.BUCKETS["day"])
        where, params = self._filtre(folder_id, since, until)
        return [
            (r[0], r[1], r[2] or 0)
            for r in self._db().execute(
                f"SELECT strftime('{forme}', date, 'unixepoch') AS tranche,"
                f" COUNT(*), SUM(size) FROM messages WHERE {where}"
                " GROUP BY tranche ORDER BY tranche",
                params,
            )
        ]

    @_locked
    def stats_undated(self, folder_id=None) -> int:
        clauses, params = ["date <= 0"], []
        if folder_id is not None:
            clauses.append("folder_id = ?")
            params.append(folder_id)
        return (
            self._db()
            .execute(
                f"SELECT COUNT(*) FROM messages WHERE {' AND '.join(clauses)}",
                params,
            )
            .fetchone()[0]
        )

    @_locked
    def stats_span(self, folder_id=None, since=None) -> tuple:
        """(nombre de messages datés, date la plus ancienne, la plus récente).

        Trois entiers rendus par une seule requête : de quoi choisir la
        granularité de l'histogramme et borner une progression sans
        rapatrier une seule ligne de message.

        `since` borne comme partout ailleurs. L'étendue sert à choisir le
        pas : mesurée sur toute la boîte alors que la période n'en montre
        qu'un mois, elle donnait l'année — une seule barre pour les trente
        jours affichés.
        """
        where, params = self._filtre(folder_id, since, None)
        ligne = (
            self._db()
            .execute(
                f"SELECT COUNT(*), MIN(date), MAX(date) FROM messages WHERE {where}",
                params,
            )
            .fetchone()
        )
        return (ligne[0] or 0, ligne[1] or 0, ligne[2] or 0)

    @_locked
    def stats_folders(self, since=None) -> list[dict]:
        """Par dossier : total, non-lus, octets. Tout est en clair, donc SQL.

        `since` borne les messages COMPTÉS, jamais les dossiers listés : le
        filtre vit dans le `ON` de la jointure et non dans un `WHERE`, donc
        un dossier que la période vide reste au tableau avec un zéro. L'en
        faire disparaître se lirait « ce dossier n'existe plus ».
        """
        jointure = "m.folder_id = f.id AND m.date > 0"
        params: list = []
        if since is not None:
            jointure += " AND m.date >= ?"
            params.append(int(since))
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "display": r["display"] or r["name"],
                "count": r["n"],
                "unseen": r["unseen"],
                "size": r["octets"] or 0,
            }
            for r in self._db().execute(
                "SELECT f.id, f.name, f.display, COUNT(m.id) AS n,"
                " SUM(CASE WHEN m.flags NOT LIKE '%\\Seen%' ESCAPE '\\'"
                "          THEN 1 ELSE 0 END) AS unseen,"
                " SUM(m.size) AS octets"
                f" FROM folders f LEFT JOIN messages m ON {jointure}"
                " GROUP BY f.id ORDER BY n DESC",
                params,
            )
        ]

    @_locked
    def stats_correspondents(
        self,
        direction="from",
        folder_id=None,
        since=None,
        until=None,
        progress=None,
    ) -> dict:
        """Adresse → nombre. Le SEUL agrégat qui déchiffre.

        `sealed_from`/`sealed_to` sont scellés : impossible de compter en
        SQL. On descelle en mémoire, ligne par ligne, sans jamais réécrire
        en clair — c'est le compromis annoncé au devis.
        """
        colonne = "sealed_to" if direction == "to" else "sealed_from"
        where, params = self._filtre(folder_id, since, until)
        compte: dict = {}
        # Une boîte de longue durée compte des centaines de milliers de
        # messages pour quelques centaines de correspondants. En mode clair
        # deux messages du même expéditeur portent le MÊME blob : le
        # mémoriser ramène le déchiffrement et l'analyse d'adresse au
        # nombre de correspondants distincts. En mode chiffré le nonce
        # diffère à chaque ligne, aucun blob ne se répète, et la mémoire
        # sert seulement de passage à vide.
        deja: dict = {}
        traites = 0
        for (blob,) in self._db().execute(
            f"SELECT {colonne} FROM messages WHERE {where}", params
        ):
            cle = bytes(blob) if blob else b""
            adresses = deja.get(cle)
            if adresses is None:
                adresses = _addresses(self._open(blob))
                deja[cle] = adresses
            for adresse in adresses:
                compte[adresse] = compte.get(adresse, 0) + 1
            traites += 1
            if progress is not None and traites % 5000 == 0:
                progress(traites)
        return compte

    @_locked
    def stats_reply_delays(
        self, folder_id=None, since=None, until=None
    ) -> list[int]:
        """Les délais, en secondes, entre un message et sa réponse.

        Jointure sur les EMPREINTES : `in_reply_to_hash` d'une réponse
        contre `msgid_hash` de l'original. Un délai négatif est écarté —
        une date d'en-tête peut mentir, et une réponse antérieure à son
        original n'est pas une réponse rapide, c'est une donnée fausse.

        Une réponse automatique (`auto_sent`) n'est pas une réponse : sa
        copie dans Envoyés porte `In-Reply-To` comme une autre, et ses
        quelques secondes de délai fausseraient le nombre et la médiane.
        """
        clauses = [
            "reponse.in_reply_to_hash IS NOT NULL",
            "reponse.date > 0",
            "original.date > 0",
            "NOT EXISTS (SELECT 1 FROM auto_sent"
            " WHERE auto_sent.msgid_hash = reponse.msgid_hash)",
        ]
        params: list = []
        if folder_id is not None:
            clauses.append("reponse.folder_id = ?")
            params.append(folder_id)
        if since is not None:
            clauses.append("reponse.date >= ?")
            params.append(int(since))
        if until is not None:
            clauses.append("reponse.date < ?")
            params.append(int(until))
        lignes = self._db().execute(
            "SELECT reponse.date - original.date"
            " FROM messages reponse"
            " JOIN messages original"
            "   ON original.msgid_hash = reponse.in_reply_to_hash"
            f" WHERE {' AND '.join(clauses)}",
            params,
        )
        return [delai for (delai,) in lignes if delai > 0]

    @_locked
    def activity_folders(self) -> tuple[list[int], list[int]]:
        """(ids des boîtes de réception, ids des dossiers Envoyés).

        Boîte de réception : rôle `inbox`, ou nom « INBOX » sans égard à la
        casse. Envoyés : rôle `sent`, ou nom égal au dossier d'envoi du
        compte.
        """
        sent_name = getattr(self.account, "sent_folder", "") or ""
        inbox, sent = [], []
        for row in self._db().execute(
            "SELECT id, name, role FROM folders ORDER BY id"
        ):
            name = row["name"] or ""
            if row["role"] == "inbox" or name.upper() == "INBOX":
                inbox.append(row["id"])
            if row["role"] == "sent" or (sent_name and name == sent_name):
                sent.append(row["id"])
        return inbox, sent

    @_locked
    def stats_activity(
        self, since: int, until: int, *, with_sender: bool = False
    ) -> list[ActivityRow]:
        """Les messages d'INBOX reçus dans [since, until), réception
        croissante.

        Réception = INTERNALDATE, à défaut la date d'en-tête ; un message
        sans l'une ni l'autre n'est pas rendu. Un Message-ID n'est compté
        qu'une fois, à sa PREMIÈRE copie d'INBOX (réception la plus
        ancienne, puis `id`), le rang étant pris sur toute la boîte et non
        sur la fenêtre : une copie ultérieure n'est ni reçue ni répondue.
        Les messages sans Message-ID partagent tous l'empreinte de « » et
        sont chacun leur propre première copie. Les messages dont
        l'empreinte est dans `auto_sent` sont écartés, comme les réponses
        automatiques classées dans Envoyés.

        Sans `with_sender`, aucune colonne scellée n'est lue.
        """
        inbox, sent = self.activity_folders()
        if not inbox:
            return []
        received = "COALESCE(o.received_at, NULLIF(o.date, 0))"
        reply_date = "COALESCE(NULLIF(r.date, 0), r.received_at)"
        not_auto = (
            "NOT EXISTS (SELECT 1 FROM auto_sent a"
            " WHERE a.msgid_hash = {}.msgid_hash)"
        )
        inbox_marks = ",".join("?" * len(inbox))
        if sent:
            sent_marks = ",".join("?" * len(sent))
            replies = (
                "EXISTS (SELECT 1 FROM messages r"
                " WHERE r.in_reply_to_hash = c.empreinte"
                f" AND r.folder_id IN ({sent_marks})"
                f" AND {not_auto.format('r')}) AS repondu,"
                f" (SELECT MIN({reply_date}) FROM messages r"
                " WHERE r.in_reply_to_hash = c.empreinte"
                f" AND r.folder_id IN ({sent_marks})"
                f" AND {reply_date} > c.recu"
                f" AND {not_auto.format('r')}) AS premiere"
            )
        else:
            replies = "0 AS repondu, NULL AS premiere"
        # La colonne scellée de From n'entre dans la requête que si
        # l'expéditeur est demandé : l'écran des statistiques n'en a pas
        # besoin et ne doit rien desceller.
        inner_sender = ", o.sealed_from AS sealed_from" if with_sender else ""
        outer_sender = ", c.sealed_from AS sealed_from" if with_sender else ""
        sql = (
            "SELECT c.recu AS recu, c.flags AS flags, "
            f"{replies}{outer_sender}"
            f" FROM (SELECT {received} AS recu, o.flags AS flags,"
            " o.msgid_hash AS empreinte,"
            " ROW_NUMBER() OVER ("
            " PARTITION BY CASE WHEN o.msgid_hash = ? THEN 'id:' || o.id"
            " ELSE o.msgid_hash END"
            f" ORDER BY {received}, o.id) AS rang{inner_sender}"
            " FROM messages o"
            f" WHERE o.folder_id IN ({inbox_marks})"
            f" AND {received} IS NOT NULL"
            f" AND {not_auto.format('o')}) c"
            " WHERE c.rang = 1 AND c.recu >= ? AND c.recu < ?"
            " ORDER BY c.recu"
        )
        # Les « ? » se lient dans l'ordre du TEXTE : les deux sous-requêtes
        # de réponse précèdent la sous-requête des originaux.
        params = [*sent, *sent] if sent else []
        params += [self._msgid_hash(""), *inbox, int(since), int(until)]
        if with_sender:
            from script.todo.mail.rules.filter import sole_address
        out = []
        for row in self._db().execute(sql, params):
            tokens = (row["flags"] or "").split()
            sender = ""
            if with_sender:
                sender = sole_address(self._open(row["sealed_from"]))
            out.append(
                ActivityRow(
                    received_at=int(row["recu"]),
                    seen="\\Seen" in tokens,
                    answered="\\Answered" in tokens or bool(row["repondu"]),
                    first_reply_at=(
                        int(row["premiere"])
                        if row["premiere"] is not None
                        else None
                    ),
                    sender=sender,
                )
            )
        return out

    def _fts_present(self, db) -> bool:
        """Vrai si l'index plein texte existe dans CE cache.

        Il n'existe qu'en mode clair, et un cache d'avant la v3 n'en a pas
        du tout : les fonctions qui le vident doivent pouvoir se taire
        plutôt que de lever sur une table absente.
        """
        return (
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'messages_fts'"
            ).fetchone()
            is not None
        )

    def _desindexer(self, db, folder_id: int) -> None:
        """Retire de l'index les messages d'un dossier."""
        if not self._fts_present(db):
            return
        db.execute(
            "DELETE FROM messages_fts WHERE rowid IN"
            " (SELECT id FROM messages WHERE folder_id = ?)",
            (folder_id,),
        )

    def _indexer(self, db, folder_id: int, metas: list) -> None:
        """Range sujet et extrait dans l'index plein texte.

        Appelée AVANT l'insertion : l'identifiant de ligne d'un message déjà
        connu ne change pas, et celui d'un message neuf n'existe pas encore
        — on le retrouve donc après coup par `(folder_id, uid)`. Un index
        qui n'existe pas (mode chiffré) fait de cette fonction un passage à
        vide.
        """
        if self.mode != "clear":
            return
        for m in metas:
            ligne = db.execute(
                "SELECT id FROM messages WHERE folder_id = ? AND uid = ?",
                (folder_id, m.uid),
            ).fetchone()
            if ligne is not None:
                db.execute(
                    "DELETE FROM messages_fts WHERE rowid = ?", (ligne[0],)
                )
        db.commit()

    def _indexer_apres(self, db, folder_id: int, metas: list) -> None:
        """Le second temps : les identifiants existent, on peut indexer."""
        if self.mode != "clear":
            return
        for m in metas:
            ligne = db.execute(
                "SELECT id FROM messages WHERE folder_id = ? AND uid = ?",
                (folder_id, m.uid),
            ).fetchone()
            if ligne is None:
                continue
            db.execute(
                "INSERT INTO messages_fts(rowid, subject, snippet,"
                " frm, adr_to) VALUES(?,?,?,?,?)",
                (
                    ligne[0],
                    m.subject or "",
                    m.snippet or "",
                    m.frm or "",
                    m.to or "",
                ),
            )

    def _reindexer(self) -> None:
        """Remplit l'index depuis les lignes déjà en cache.

        Sans ce rattrapage, un cache existant chercherait dans un index
        vide : la recherche rendrait zéro résultat sur une boîte pleine,
        ce qui se lit comme « rien ne correspond » et non comme « l'index
        n'existe pas encore ».
        """
        if self.mode != "clear":
            return
        db = self._db()
        db.execute("DELETE FROM messages_fts")
        for row in db.execute(
            "SELECT id, sealed_subject, sealed_snippet, sealed_from,"
            " sealed_to FROM messages"
        ).fetchall():
            db.execute(
                "INSERT INTO messages_fts(rowid, subject, snippet,"
                " frm, adr_to) VALUES(?,?,?,?,?)",
                (
                    row[0],
                    self._open(row[1]),
                    self._open(row[2]),
                    self._open(row[3]),
                    self._open(row[4]),
                ),
            )
        db.commit()

    @_locked
    def search(self, query: str, folder_id=None, limit: int = 500) -> list:
        """Cherche dans TOUT le cache, pas seulement dans ce qui est chargé.

        En mode clair l'index FTS5 répond ; en mode chiffré il n'existe pas
        et on déchiffre ligne à ligne, ce qui coûte du temps sur une grande
        boîte. `search_is_indexed` dit lequel des deux a servi, pour que
        l'écran puisse l'annoncer.
        """
        query = (query or "").strip()
        if not query:
            return []
        if self.mode == "clear":
            return self._search_fts(query, folder_id, limit)
        return self._search_scan(query, folder_id, limit)

    def search_is_indexed(self) -> bool:
        """Vrai si la recherche passe par l'index plutôt que par un
        balayage. Ce n'est pas une préférence : c'est la conséquence du mode
        de cache, et l'écran le dit."""
        return self.mode == "clear"

    def _search_fts(self, query, folder_id, limit) -> list:
        motif = _fts_query(query)
        if not motif:
            # Une saisie qui ne laisse aucun terme utilisable — un
            # guillemet seul — donnerait une requête vide, que FTS5 refuse
            # par une erreur de syntaxe. Aucun terme, aucun résultat.
            return []
        clauses = ["messages_fts MATCH ?"]
        params: list = [motif]
        if folder_id is not None:
            clauses.append("m.folder_id = ?")
            params.append(folder_id)
        params.append(limit)
        rows = (
            self._db()
            .execute(
                "SELECT m.*, f.name AS folder_name FROM messages_fts"
                " JOIN messages m ON m.id = messages_fts.rowid"
                " JOIN folders f ON f.id = m.folder_id"
                f" WHERE {' AND '.join(clauses)}"
                " ORDER BY m.date DESC LIMIT ?",
                params,
            )
            .fetchall()
        )
        return [self._row_to_meta(r) for r in rows]

    def _search_scan(self, query, folder_id, limit) -> list:
        from script.todo.mail.tui_text import fold

        aiguille = fold(query)
        clauses, params = ["1=1"], []
        if folder_id is not None:
            clauses.append("m.folder_id = ?")
            params.append(folder_id)
        trouves = []
        for row in self._db().execute(
            "SELECT m.*, f.name AS folder_name FROM messages m"
            " JOIN folders f ON f.id = m.folder_id"
            f" WHERE {' AND '.join(clauses)}"
            " ORDER BY m.date DESC",
            params,
        ):
            meta = self._row_to_meta(row)
            foin = f"{meta.subject} {meta.frm} {meta.to} {meta.snippet}"
            if aiguille in fold(foin):
                trouves.append(meta)
                if len(trouves) >= limit:
                    break
        return trouves

    @_locked
    def update_flags(self, folder_id: int, uid: int, flags: str) -> None:
        """Remplace les drapeaux d'un message, et suit `folders.unseen`.

        Le compteur bouge d'UN au plus, calculé sur la transition du seul
        `\\Seen` : le recompter coûterait un balayage du dossier à chaque
        touche (voir `folders`). `MAX(0, ...)` borne une colonne qu'une
        version antérieure du cache a pu laisser fausse, pour qu'un
        compteur déjà à zéro ne devienne jamais négatif.
        """
        db = self._db()
        ancien = db.execute(
            "SELECT flags FROM messages WHERE folder_id = ? AND uid = ?",
            (folder_id, uid),
        ).fetchone()
        if ancien is None:
            return
        etait_non_lu = "\\Seen" not in (ancien["flags"] or "")
        est_non_lu = "\\Seen" not in (flags or "")
        db.execute(
            "UPDATE messages SET flags = ? WHERE folder_id = ? AND uid = ?",
            (flags, folder_id, uid),
        )
        if etait_non_lu != est_non_lu:
            # `seen_at` suit la même transition : posé au passage à lu,
            # effacé au retour à non-lu, inchangé sinon.
            db.execute(
                "UPDATE messages SET seen_at = ?"
                " WHERE folder_id = ? AND uid = ?",
                (
                    None if est_non_lu else int(time.time()),
                    folder_id,
                    uid,
                ),
            )
            db.execute(
                "UPDATE folders SET unseen ="
                " MAX(0, COALESCE(unseen, 0) + ?) WHERE id = ?",
                (1 if est_non_lu else -1, folder_id),
            )
        db.commit()

    @_locked
    def mark_all_seen(self, folder_id: int) -> int:
        """Pose `\\Seen` sur tout le dossier, et rend le nombre de lignes
        qui ont changé.

        Le compte est celui des messages qui étaient NON LUS : c'est ce que
        l'écran annonce, et le total du dossier ne le dirait pas.

        `flags` est en clair même en mode chiffré — c'est la condition qui
        permet de compter les non-lus en SQL — donc la mise à jour se fait
        ici plutôt que ligne à ligne en Python.
        """
        db = self._db()
        non_lus = db.execute(
            "SELECT COUNT(*) FROM messages"
            " WHERE folder_id = ? AND flags NOT LIKE '%\\Seen%' ESCAPE '\\'",
            (folder_id,),
        ).fetchone()[0]
        if not non_lus:
            return 0
        db.execute(
            "UPDATE messages SET flags ="
            " TRIM(COALESCE(flags, '') || ' \\Seen'), seen_at = ?"
            " WHERE folder_id = ? AND flags NOT LIKE '%\\Seen%' ESCAPE '\\'",
            (int(time.time()), folder_id),
        )
        # Le dossier n'a plus un seul non-lu : le compteur de l'arbre le dit
        # sans attendre la passe de synchronisation suivante.
        db.execute("UPDATE folders SET unseen = 0 WHERE id = ?", (folder_id,))
        db.commit()
        return non_lus

    def _row_to_meta(self, row) -> MessageMeta:
        return MessageMeta(
            uid=row["uid"],
            date=row["date"],
            size=row["size"],
            flags=row["flags"] or "",
            msgid=self._open(row["sealed_msgid"]),
            frm=self._open(row["sealed_from"]),
            to=self._open(row["sealed_to"]),
            subject=self._open(row["sealed_subject"]),
            snippet=self._open(row["sealed_snippet"]),
            has_body=bool(row["has_body"]),
            msgid_hash=row["msgid_hash"] or "",
            in_reply_to_hash=(
                row["in_reply_to_hash"]
                if "in_reply_to_hash" in row.keys()
                else ""
            )
            or "",
            folder=(row["folder_name"] if "folder_name" in row.keys() else "")
            or "",
            received_at=(
                row["received_at"] if "received_at" in row.keys() else 0
            )
            or 0,
            seen_at=(row["seen_at"] if "seen_at" in row.keys() else 0) or 0,
        )

    @_locked
    def list_messages(
        self, folder_id: int, limit: int = 500, offset: int = 0
    ) -> list[MessageMeta]:
        rows = (
            self._db()
            .execute(
                "SELECT * FROM messages WHERE folder_id = ?"
                " ORDER BY date DESC, uid DESC LIMIT ? OFFSET ?",
                (folder_id, limit, offset),
            )
            .fetchall()
        )
        return [self._row_to_meta(r) for r in rows]

    @_locked
    def forget_message(self, folder_id: int, uid: int) -> None:
        """Retire une ligne du cache, sans toucher au serveur.

        Appelée APRÈS un déplacement accepté par le serveur : le cache ne
        doit jamais devancer ce que le serveur a fait, sinon un message
        disparu de l'écran revient à la passe suivante et l'utilisateur ne
        sait plus ce qui est vrai.
        """
        db = self._db()
        ligne = db.execute(
            "SELECT id, flags FROM messages WHERE folder_id = ? AND uid = ?",
            (folder_id, uid),
        ).fetchone()
        if ligne is None:
            return
        if self._fts_present(db):
            db.execute("DELETE FROM messages_fts WHERE rowid = ?", (ligne[0],))
        db.execute("DELETE FROM messages WHERE id = ?", (ligne[0],))
        # Les compteurs du dossier suivent le retrait : sans cela l'arbre
        # annoncerait des non-lus qu'il n'a plus jusqu'à la passe suivante.
        db.execute(
            "UPDATE folders SET total = MAX(0, COALESCE(total, 0) - 1)"
            " WHERE id = ?",
            (folder_id,),
        )
        if "\\Seen" not in (ligne["flags"] or ""):
            db.execute(
                "UPDATE folders SET unseen ="
                " MAX(0, COALESCE(unseen, 0) - 1) WHERE id = ?",
                (folder_id,),
            )
        db.commit()

    @_locked
    def missing_uids(self, folder_id: int, uids: list[int]) -> list[int]:
        """Ceux de `uids` que ce dossier n'a pas encore, dans l'ordre reçu.

        Une requête plutôt qu'une lecture de tout le dossier : la question
        se pose sur les quelques centaines d'UID qu'une recherche serveur
        rapporte, pas sur les deux cent mille que la boîte peut porter.
        """
        if not uids:
            return []
        trous = ",".join("?" for _ in uids)
        connus = {
            r[0]
            for r in self._db().execute(
                f"SELECT uid FROM messages WHERE folder_id = ?"
                f" AND uid IN ({trous})",
                [folder_id, *uids],
            )
        }
        return [u for u in uids if u not in connus]

    @_locked
    def known_uids(self, folder_id: int, last_n: int = 500) -> list[int]:
        rows = (
            self._db()
            .execute(
                "SELECT uid FROM messages WHERE folder_id = ?"
                " ORDER BY uid DESC LIMIT ?",
                (folder_id, last_n),
            )
            .fetchall()
        )
        return [r[0] for r in rows]

    @_locked
    def count_messages(self, folder_id: int) -> int:
        """Combien de messages le CACHE tient pour ce dossier.

        À ne pas confondre avec le `total` du dossier, qui est celui du
        SERVEUR : une boîte à peine synchronisée annonce des milliers de
        messages dont le cache n'a encore aucun. C'est ce compte-ci qui dit
        s'il reste une page à charger.
        """
        return (
            self._db()
            .execute(
                "SELECT COUNT(*) FROM messages WHERE folder_id = ?",
                (folder_id,),
            )
            .fetchone()[0]
        )

    @_locked
    def count_unseen(self, folder_id: int) -> int:
        """Les non-lus. `flags` est en clair, donc c'est du SQL, pas du déchiffrement."""
        return (
            self._db()
            .execute(
                "SELECT COUNT(*) FROM messages"
                " WHERE folder_id = ? AND flags NOT LIKE '%\\Seen%' ESCAPE '\\'",
                (folder_id,),
            )
            .fetchone()[0]
        )

    @_locked
    def set_snippet(self, folder_id: int, uid: int, text: str) -> None:
        """L'extrait n'existe qu'une fois le corps téléchargé : ENVELOPE ne le donne pas."""
        db = self._db()
        db.execute(
            "UPDATE messages SET sealed_snippet = ?"
            " WHERE folder_id = ? AND uid = ?",
            (self._seal(text), folder_id, uid),
        )
        db.commit()

    # -- Corps ----------------------------------------------------------

    def _body_path(self, folder_name: str, uid: int) -> Path:
        suffix = ".eml" if self.mode == "clear" else ".eml.enc"
        return self.root / folder_dirname(folder_name) / f"{uid}{suffix}"

    @_locked
    def write_body(self, folder_name: str, uid: int, raw: bytes) -> None:
        """Écrit le corps scellé (`_write_body_file`) puis marque le message
        `has_body`."""
        self._write_body_file(folder_name, uid, raw)
        db = self._db()
        db.execute(
            "UPDATE messages SET has_body = 1 WHERE uid = ? AND folder_id ="
            " (SELECT id FROM folders WHERE name = ?)",
            (uid, folder_name),
        )
        db.commit()

    def _write_body_file(self, folder_name: str, uid: int, raw: bytes) -> None:
        """Le corps scellé, écrit atomiquement à `_body_path`, SANS toucher
        la base."""
        path = self._body_path(folder_name, uid)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        # Le corps s'écrit dans un temporaire du même dossier, synchronisé
        # puis renommé : un processus tué en pleine écriture laisse
        # l'ancien fichier ou aucun, jamais un corps tronqué que
        # `read_body` rendrait pour toujours. Le temporaire naît DÉJÀ en
        # 0600 (`O_EXCL`, jamais un lien) : le corps, même scellé, n'est
        # lisible à aucun moment à l'umask du processus.
        sealed = self._crypto.seal(raw)
        tmp = path.with_name(f".{path.name}.{os.urandom(6).hex()}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(tmp, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(sealed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        os.chmod(path, 0o600)

    @_locked
    def read_body(self, folder_name: str, uid: int) -> bytes | None:
        path = self._body_path(folder_name, uid)
        if not path.exists():
            return None
        return self._crypto.open(path.read_bytes())

    # -- Entretien ------------------------------------------------------

    @_locked
    def size_bytes(self) -> int:
        return sum(
            p.stat().st_size for p in self.root.rglob("*") if p.is_file()
        )

    @_locked
    def purge_all(self) -> None:
        db = self._db()
        if self._fts_present(db):
            db.execute("DELETE FROM messages_fts")
        db.execute("DELETE FROM messages")
        db.execute("DELETE FROM folders")
        db.commit()
        for child in self.root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
