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
import email.utils
import functools
import hashlib
import os
import shutil
import sqlite3
import stat
import threading
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from script.todo.mail.crypto import build_crypto, new_key
from script.todo.todo_i18n import t

SCHEMA_VERSION = 2
EPHEMERAL_PREFIX = "erplibre-mail-"
VALID_MODES = ("clear", "encrypted", "ephemeral")

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
  UNIQUE(folder_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_msg_date ON messages(folder_id, date DESC);
"""


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
    for nom in ("in_reply_to_hash", "references_hashes"):
        if nom not in presentes:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {nom} TEXT")
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


class StoreError(Exception):
    """Cache inutilisable : clé manquante, base corrompue, disque refusé."""


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


def _addresses(value: str) -> list[str]:
    """« Alice <a@x.ca>, b@y.ca » → ["a@x.ca", "b@y.ca"], en minuscules.

    On compte les ADRESSES, pas les libellés : le même correspondant écrit
    tantôt « Alice », tantôt « Alice Tremblay », tantôt rien. Compter les
    libellés éclaterait une personne en trois lignes du classement.
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


def resolve_mode(account, prefs_get=None) -> str:
    """Le mode du compte, sinon le défaut général, sinon `clear`.

    Un défaut général illisible ne doit pas empêcher d'ouvrir le cache :
    on retombe sur le mode le plus permissif, jamais sur une erreur.
    """
    if account.cache_mode in VALID_MODES:
        return account.cache_mode
    if prefs_get is None:
        from script.todo import todo_prefs

        prefs_get = todo_prefs.get
    general = prefs_get("mail_cache_mode", "clear")
    return general if general in VALID_MODES else "clear"


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
    ) -> None:
        self.account = account
        self.mode = mode or resolve_mode(account)
        self.root = cache_root(account, self.mode, base)
        self._key = key
        self._secrets = secrets
        self._conn: sqlite3.Connection | None = None
        self._crypto = None
        self._lock = threading.RLock()

    # -- Cycle de vie ---------------------------------------------------

    @_locked
    def open(self) -> None:
        if self._conn is not None:
            return
        self._crypto = build_crypto(self.mode, self._resolve_key())
        self._prepare_root()
        db_path = self.root / "cache.db"
        conn = None
        try:
            # `check_same_thread=False` parce que le TUI synchronise dans un
            # thread de travail : sans ça, la première passe lèverait
            # ProgrammingError. La sûreté vient du verrou, pas de ce drapeau.
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA)
            _ensure_columns(conn)
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
        # Publié SEULEMENT une fois le schéma en place. `sqlite3.connect` est
        # paresseux : une base corrompue n'échoue qu'à `executescript`, donc
        # affecter `self._conn` plus tôt laisserait un open() raté derrière lui
        # un handle sans schéma — et le open() suivant, voyant `_conn` non nul,
        # réussirait en silence sur une base inutilisable.
        self._conn = conn
        if db_path.exists():
            os.chmod(db_path, 0o600)

    @_locked
    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.commit()
        except sqlite3.Error:
            # Fermer prime sur sauver : un commit refusé ne doit pas laisser la
            # connexion ouverte pour toujours.
            pass
        finally:
            self._conn.close()
            self._conn = None

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
        stored = self._secrets.get(ref)
        if stored is None:
            self._key = new_key()
            self._secrets.set(ref, base64.b64encode(self._key).decode())
        else:
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
        salt = self._key or b"clear"
        return hashlib.sha256(salt + (msgid or "").encode("utf-8")).hexdigest()

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
    def purge_folder(self, name: str) -> None:
        db = self._db()
        row = db.execute(
            "SELECT id FROM folders WHERE name = ?", (name,)
        ).fetchone()
        if row:
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
            )
            for m in metas
        ]
        db.executemany(
            "INSERT INTO messages(folder_id, uid, date, size, flags,"
            " msgid_hash, sealed_msgid, sealed_from, sealed_to,"
            " sealed_subject, sealed_snippet,"
            " in_reply_to_hash, references_hashes)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
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
            "   references_hashes = excluded.references_hashes",
            rows,
        )
        db.commit()
        return len(rows)

    # -- Statistiques (phase 3) -----------------------------------------

    BUCKETS = {
        "day": "%Y-%m-%d",
        "week": "%Y-S%W",
        "month": "%Y-%m",
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
    def stats_folders(self) -> list[dict]:
        """Par dossier : total, non-lus, octets. Tout est en clair, donc SQL."""
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
                " FROM folders f LEFT JOIN messages m ON m.folder_id = f.id"
                " GROUP BY f.id ORDER BY n DESC"
            )
        ]

    @_locked
    def stats_correspondents(
        self, direction="from", folder_id=None, since=None, until=None
    ) -> dict:
        """Adresse → nombre. Le SEUL agrégat qui déchiffre.

        `sealed_from`/`sealed_to` sont scellés : impossible de compter en
        SQL. On descelle en mémoire, ligne par ligne, sans jamais réécrire
        en clair — c'est le compromis annoncé au devis.
        """
        colonne = "sealed_to" if direction == "to" else "sealed_from"
        where, params = self._filtre(folder_id, since, until)
        compte: dict = {}
        for (blob,) in self._db().execute(
            f"SELECT {colonne} FROM messages WHERE {where}", params
        ):
            for adresse in _addresses(self._open(blob)):
                compte[adresse] = compte.get(adresse, 0) + 1
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
        """
        clauses = [
            "reponse.in_reply_to_hash IS NOT NULL",
            "reponse.date > 0",
            "original.date > 0",
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
    def update_flags(self, folder_id: int, uid: int, flags: str) -> None:
        db = self._db()
        db.execute(
            "UPDATE messages SET flags = ? WHERE folder_id = ? AND uid = ?",
            (flags, folder_id, uid),
        )
        db.commit()

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
        path = self._body_path(folder_name, uid)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        # `write_bytes` puis `chmod` laisserait le corps du message — scellé,
        # mais destiné à rester privé même déchiffré — lisible à l'umask du
        # process le temps entre les deux appels : le fichier est donc créé
        # DÉJÀ en 0600.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(self._crypto.seal(raw))
        os.chmod(path, 0o600)
        db = self._db()
        db.execute(
            "UPDATE messages SET has_body = 1 WHERE uid = ? AND folder_id ="
            " (SELECT id FROM folders WHERE name = ?)",
            (uid, folder_name),
        )
        db.commit()

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
        db.execute("DELETE FROM messages")
        db.execute("DELETE FROM folders")
        db.commit()
        for child in self.root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
