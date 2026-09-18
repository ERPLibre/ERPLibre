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
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from script.todo.mail.crypto import build_crypto, new_key
from script.todo.todo_i18n import t

SCHEMA_VERSION = 5
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
CREATE TABLE IF NOT EXISTS outbox (
  id            INTEGER PRIMARY KEY,
  created_at    INTEGER NOT NULL,
  sealed_raw    BLOB NOT NULL,
  sealed_to     BLOB,
  sealed_subject BLOB,
  held          INTEGER NOT NULL DEFAULT 0,
  attempts      INTEGER NOT NULL DEFAULT 0,
  sealed_error  BLOB
);
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


def _ensure_outbox_columns(conn) -> None:
    """Fait passer la file d'attente de la v4 à la v5.

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
    if "last_error" in presentes:
        conn.execute("UPDATE outbox SET last_error = NULL")


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
        # Un cache passé en chiffré garde sinon l'index constitué du temps
        # où il était clair : `messages` serait scellée, et la table d'à
        # côté rendrait les mêmes sujets et extraits par un simple SELECT.
        # Le retour au mode clair le reconstruit depuis le cache.
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
            _ensure_outbox_columns(conn)
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
        self._indexer(db, folder_id, metas)
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
        self._indexer_apres(db, folder_id, metas)
        db.commit()
        return len(rows)

    # -- File d'attente d'envoi (v4) ------------------------------------

    @_locked
    def queue_message(self, raw: bytes, recipients: str, subject: str) -> int:
        """Met un message en attente. Rend son identifiant."""
        db = self._db()
        curseur = db.execute(
            "INSERT INTO outbox(created_at, sealed_raw, sealed_to,"
            " sealed_subject) VALUES(?,?,?,?)",
            (
                int(time.time()),
                self._crypto.seal(raw),
                self._seal(recipients),
                self._seal(subject),
            ),
        )
        db.commit()
        return curseur.lastrowid

    @_locked
    def outbox(self) -> list[dict]:
        """La file, du plus ancien au plus récent — l'ordre d'envoi."""
        return [
            {
                "id": r["id"],
                "created_at": r["created_at"],
                "to": self._open(r["sealed_to"]),
                "subject": self._open(r["sealed_subject"]),
                "held": bool(r["held"]),
                "attempts": r["attempts"],
                "last_error": self._open(r["sealed_error"]),
            }
            for r in self._db().execute(
                "SELECT * FROM outbox ORDER BY created_at, id"
            )
        ]

    @_locked
    def queued_raw(self, queue_id: int) -> bytes | None:
        ligne = (
            self._db()
            .execute("SELECT sealed_raw FROM outbox WHERE id = ?", (queue_id,))
            .fetchone()
        )
        return self._crypto.open(bytes(ligne[0])) if ligne else None

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
    def record_send_failure(self, queue_id: int, message: str) -> None:
        """Compte l'échec et garde SON texte, scellé.

        Un compteur seul dirait qu'on a essayé cinq fois sans jamais dire
        pourquoi ça échoue, ce qui n'aide personne à corriger. Le texte vient
        du serveur et cite couramment le destinataire : il est scellé comme
        les autres colonnes de la ligne.
        """
        db = self._db()
        db.execute(
            "UPDATE outbox SET attempts = attempts + 1, sealed_error = ?"
            " WHERE id = ?",
            (self._seal(message[:500]), queue_id),
        )
        db.commit()

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
        db = self._db()
        db.execute(
            "UPDATE messages SET flags = ? WHERE folder_id = ? AND uid = ?",
            (flags, folder_id, uid),
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
            " TRIM(COALESCE(flags, '') || ' \\Seen')"
            " WHERE folder_id = ? AND flags NOT LIKE '%\\Seen%' ESCAPE '\\'",
            (folder_id,),
        )
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
            "SELECT id FROM messages WHERE folder_id = ? AND uid = ?",
            (folder_id, uid),
        ).fetchone()
        if ligne is None:
            return
        if self._fts_present(db):
            db.execute("DELETE FROM messages_fts WHERE rowid = ?", (ligne[0],))
        db.execute("DELETE FROM messages WHERE id = ?", (ligne[0],))
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
        if self._fts_present(db):
            db.execute("DELETE FROM messages_fts")
        db.execute("DELETE FROM messages")
        db.execute("DELETE FROM folders")
        db.commit()
        for child in self.root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
