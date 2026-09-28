#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cache local des billets : un SQLite par compte social.

Un schéma à part de celui du courriel, et non le sien tordu. Le courriel
parle de dossiers et d'UID — des entiers croissants, propres à un dossier,
qu'un serveur promet de ne pas réutiliser. Un fil parle de billets dont
l'identifiant est une CHAÎNE choisie par la plateforme : un compteur à
flocon ici, une URI `at://…` là. Les ranger dans une colonne d'entiers
obligerait à inventer une correspondance que rien ne garantit stable.

La reprise incrémentale suit le même principe : le cache garde un CURSEUR
opaque par fil, rendu tel quel à la plateforme, sans jamais l'interpréter.
Une plateforme pagine par « depuis tel identifiant », une autre par un jeton
de continuation ; supposer l'une des deux formes ici casserait l'autre.

Ce qui est SCELLÉ en mode chiffré : l'auteur, son nom affiché, le texte,
l'adresse du billet et ses pièces. C'est le fil de quelqu'un — qui il lit et
ce qu'il lit — donc la matière que le chiffrement existe pour couvrir. La
date reste en clair : elle sert à trier, et un tri qui déchiffrerait chaque
ligne rendrait un fil de dix mille billets inutilisable.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from script.todo import cache_dirs
from script.todo.mail.crypto import build_crypto, new_key
from script.todo.todo_i18n import t

SCHEMA_VERSION = 1
EPHEMERAL_PREFIX = "erplibre-social-"
VALID_MODES = ("clear", "encrypted", "ephemeral")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS feeds (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE,
  display   TEXT,
  cursor    TEXT,
  total     INTEGER NOT NULL DEFAULT 0,
  unseen    INTEGER NOT NULL DEFAULT 0,
  synced_at INTEGER
);
CREATE TABLE IF NOT EXISTS posts (
  id                 INTEGER PRIMARY KEY,
  feed_id            INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
  post_id            TEXT NOT NULL,
  created_at         INTEGER,
  seen               INTEGER NOT NULL DEFAULT 0,
  uri_hash           TEXT,
  reply_to           TEXT,
  boost_of           TEXT,
  sealed_uri         BLOB,
  sealed_author      BLOB,
  sealed_author_name BLOB,
  sealed_text        BLOB,
  sealed_url         BLOB,
  sealed_media       BLOB,
  UNIQUE(feed_id, post_id)
);
CREATE INDEX IF NOT EXISTS idx_post_date ON posts(feed_id, created_at DESC);
"""


class SocialStoreError(Exception):
    """Cache impossible : illisible, non ouvert, ou mode sans clé."""


def _locked(method):
    """Sérialise l'accès à la connexion SQLite.

    `check_same_thread=False` lève l'interdiction de la stdlib mais ne rend
    pas la connexion sûre : c'est CE verrou qui la rend sûre. Un fil de
    travail rapporte un fil pendant que l'écran lit le cache — les deux se
    croisent vraiment.
    """
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclass
class Media:
    """Une pièce attachée à un billet : son adresse, son genre, sa
    description — celle que l'auteur a écrite pour qui ne voit pas
    l'image."""

    url: str = ""
    kind: str = ""
    description: str = ""


@dataclass
class PostMeta:
    """Un billet tel que le cache le rend.

    `post_id` est l'identifiant DE LA PLATEFORME, jamais un entier de ce
    cache : c'est lui qu'il faut renvoyer pour agir sur le billet.
    """

    post_id: str
    created_at: int = 0
    author: str = ""
    author_name: str = ""
    text: str = ""
    url: str = ""
    uri: str = ""
    reply_to: str = ""
    boost_of: str = ""
    media: list = field(default_factory=list)
    seen: bool = False
    feed: str = ""


def resolve_mode(account, prefs_get=None) -> str:
    """Le mode du compte, sinon le défaut général, sinon `clear`.

    Un défaut général illisible ne doit pas empêcher d'ouvrir le cache : on
    retombe sur le mode le plus permissif, jamais sur une erreur.
    """
    if account.cache_mode in VALID_MODES:
        return account.cache_mode
    if prefs_get is None:
        from script.todo import todo_prefs

        prefs_get = todo_prefs.get
    general = prefs_get("social_cache_mode", "clear")
    return general if general in VALID_MODES else "clear"


def default_base() -> Path:
    return Path(os.path.expanduser("~/.erplibre/social"))


def cache_root(account, mode: str, base: Path | None = None) -> Path:
    if mode == "ephemeral":
        base = Path(base) if base else cache_dirs.ephemeral_base()
        return base / f"{EPHEMERAL_PREFIX}{os.getpid()}" / account.name
    base = Path(base) if base else default_base()
    return base / account.name


def sweep_orphan_ephemeral(base: Path | None = None) -> int:
    """Efface les caches sociaux éphémères dont le processus n'existe plus.

    Le préfixe borne le ménage à CE cache : les dossiers éphémères du cache
    courriel vivent au même endroit et ne regardent pas celui-ci.
    """
    return cache_dirs.sweep_orphan_ephemeral(EPHEMERAL_PREFIX, base)


class Store:
    """Le cache d'UN compte social. À ouvrir, à fermer, éventuellement à
    effacer."""

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
        cache_dirs.prepare_private_root(
            self.root,
            ephemeral=self.mode == "ephemeral",
            erreur=SocialStoreError,
        )
        db_path = self.root / "cache.db"
        conn = None
        try:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value)"
                " VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()
            raise SocialStoreError(
                f"{t('social_err_cache_unreadable')} {db_path} ({exc})"
            ) from exc
        # Publié SEULEMENT une fois le schéma en place : `sqlite3.connect`
        # est paresseux, et une base corrompue n'échoue qu'à
        # `executescript`. Affecter plus tôt laisserait derrière un open()
        # raté un handle sans schéma, que le open() suivant accepterait en
        # voyant `_conn` non nul.
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
            # Fermer prime sur sauver : un commit refusé ne doit pas laisser
            # la connexion ouverte pour toujours.
            pass
        finally:
            self._conn.close()
            self._conn = None

    def cleanup(self) -> None:
        """Efface la racine du compte. Appelée à la sortie en mode éphémère.

        On n'efface QUE le dossier du compte : le dossier par PID est
        partagé avec les autres comptes éphémères du même processus, et
        l'effacer détruirait leurs caches vivants. Il ne part que s'il est
        vide.
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
            raise SocialStoreError(
                f"{t('mail_err_mode_prefix')} {self.mode}"
                f" {t('mail_err_mode_requires_key_no_vault')}"
            )
        import base64

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

    def _uri_hash(self, uri: str):
        """L'empreinte d'une URI, ou NULL quand il n'y en a pas.

        Hacher la chaîne vide donnerait la MÊME empreinte à tous les billets
        sans URI, qui se reconnaîtraient alors les uns les autres. NULL ne
        joint rien, ce qui est le sens de « celui-ci n'en a pas ».

        Salée par la clé du cache : une URI publique reste publique, mais
        une empreinte non salée se retrouve par dictionnaire, et la liste
        des comptes suivis se reconstituerait ainsi sans la clé.
        """
        import hashlib

        uri = (uri or "").strip()
        if not uri:
            return None
        salt = self._key or b"clear"
        return hashlib.sha256(salt + uri.encode("utf-8")).hexdigest()

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise SocialStoreError(t("social_err_cache_not_open"))
        return self._conn

    # -- Fils -----------------------------------------------------------

    @_locked
    def upsert_feed(self, name: str, display: str = "") -> int:
        db = self._db()
        db.execute(
            "INSERT INTO feeds(name, display) VALUES(?,?)"
            " ON CONFLICT(name) DO UPDATE SET"
            "   display = COALESCE(NULLIF(excluded.display, ''),"
            "                      feeds.display)",
            (name, display or None),
        )
        db.commit()
        return db.execute(
            "SELECT id FROM feeds WHERE name = ?", (name,)
        ).fetchone()[0]

    @_locked
    def feeds(self) -> list[dict]:
        return [
            dict(r)
            for r in self._db().execute("SELECT * FROM feeds ORDER BY name")
        ]

    @_locked
    def feed_state(self, name: str) -> dict | None:
        row = (
            self._db()
            .execute("SELECT * FROM feeds WHERE name = ?", (name,))
            .fetchone()
        )
        return dict(row) if row else None

    @_locked
    def set_feed_state(self, name: str, **fields) -> None:
        allowed = {"display", "cursor", "total", "unseen", "synced_at"}
        unknown = set(fields) - allowed
        if unknown:
            raise SocialStoreError(
                f"{t('social_err_unknown_feed_fields')} {sorted(unknown)}"
            )
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        db = self._db()
        db.execute(
            f"UPDATE feeds SET {sets} WHERE name = ?",
            (*fields.values(), name),
        )
        db.commit()

    @_locked
    def purge_feed(self, name: str) -> None:
        db = self._db()
        row = db.execute(
            "SELECT id FROM feeds WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return
        db.execute("DELETE FROM posts WHERE feed_id = ?", (row[0],))
        db.execute(
            "UPDATE feeds SET total = 0, unseen = 0, cursor = NULL"
            " WHERE id = ?",
            (row[0],),
        )
        db.commit()

    # -- Billets --------------------------------------------------------

    @_locked
    def upsert_posts(self, feed_id: int, metas: list) -> int:
        """Écrit ou met à jour des billets. Rend le nombre reçu.

        Un billet déjà connu est MIS À JOUR plutôt qu'ignoré : son texte est
        modifiable chez plusieurs plateformes, et son compteur de partages
        bouge sans arrêt. Ce qui ne bouge pas est `seen` — il appartient au
        lecteur, pas à la plateforme, et une passe l'écraserait.
        """
        if not metas:
            return 0
        db = self._db()
        db.executemany(
            "INSERT INTO posts(feed_id, post_id, created_at, uri_hash,"
            " reply_to, boost_of, sealed_uri, sealed_author,"
            " sealed_author_name, sealed_text, sealed_url, sealed_media)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(feed_id, post_id) DO UPDATE SET"
            "   created_at = excluded.created_at,"
            "   uri_hash = excluded.uri_hash,"
            "   reply_to = excluded.reply_to,"
            "   boost_of = excluded.boost_of,"
            "   sealed_uri = excluded.sealed_uri,"
            "   sealed_author = excluded.sealed_author,"
            "   sealed_author_name = excluded.sealed_author_name,"
            "   sealed_text = excluded.sealed_text,"
            "   sealed_url = excluded.sealed_url,"
            "   sealed_media = excluded.sealed_media",
            [
                (
                    feed_id,
                    m.post_id,
                    int(m.created_at or 0),
                    self._uri_hash(m.uri),
                    m.reply_to or None,
                    m.boost_of or None,
                    self._seal(m.uri),
                    self._seal(m.author),
                    self._seal(m.author_name),
                    self._seal(m.text),
                    self._seal(m.url),
                    self._seal(_media_json(m.media)),
                )
                for m in metas
            ],
        )
        self._recompter(db, feed_id)
        db.commit()
        return len(metas)

    def _recompter(self, db, feed_id: int) -> None:
        """Remet les compteurs du fil d'aplomb, en une fois.

        L'écriture est en LOT, donc ce recompte est négligeable, et il rend
        les colonnes AUTO-CORRECTRICES : les chemins qui les ajustent d'un
        cran ne peuvent pas dériver indéfiniment. L'écran, lui, les lit à
        chaque redessin — les recompter LÀ coûterait un balayage du fil à
        chaque touche.
        """
        db.execute(
            "UPDATE feeds SET"
            "  total = (SELECT COUNT(*) FROM posts WHERE feed_id = ?),"
            "  unseen = (SELECT COUNT(*) FROM posts"
            "            WHERE feed_id = ? AND seen = 0)"
            " WHERE id = ?",
            (feed_id, feed_id, feed_id),
        )

    def _row_to_meta(self, row) -> PostMeta:
        return PostMeta(
            post_id=row["post_id"],
            created_at=row["created_at"] or 0,
            author=self._open(row["sealed_author"]),
            author_name=self._open(row["sealed_author_name"]),
            text=self._open(row["sealed_text"]),
            url=self._open(row["sealed_url"]),
            uri=self._open(row["sealed_uri"]),
            reply_to=row["reply_to"] or "",
            boost_of=row["boost_of"] or "",
            media=_media_from_json(self._open(row["sealed_media"])),
            seen=bool(row["seen"]),
            feed=row["feed_name"] if "feed_name" in row.keys() else "",
        )

    @_locked
    def list_posts(
        self, feed_id: int, limit: int = 200, offset: int = 0
    ) -> list[PostMeta]:
        """Les billets du fil, le plus récent d'abord.

        Paginé : un fil se compte en dizaines de milliers de billets, et
        tout rendre construirait autant de lignes à chaque ouverture.
        """
        rows = self._db().execute(
            "SELECT p.*, f.name AS feed_name FROM posts p"
            " JOIN feeds f ON f.id = p.feed_id"
            " WHERE p.feed_id = ?"
            " ORDER BY p.created_at DESC, p.id DESC"
            " LIMIT ? OFFSET ?",
            (feed_id, limit, offset),
        )
        return [self._row_to_meta(r) for r in rows]

    @_locked
    def get_post(self, feed_id: int, post_id: str) -> PostMeta | None:
        row = (
            self._db()
            .execute(
                "SELECT p.*, f.name AS feed_name FROM posts p"
                " JOIN feeds f ON f.id = p.feed_id"
                " WHERE p.feed_id = ? AND p.post_id = ?",
                (feed_id, post_id),
            )
            .fetchone()
        )
        return self._row_to_meta(row) if row else None

    @_locked
    def count_posts(self, feed_id: int) -> int:
        return (
            self._db()
            .execute(
                "SELECT COUNT(*) FROM posts WHERE feed_id = ?", (feed_id,)
            )
            .fetchone()[0]
        )

    @_locked
    def count_unseen(self, feed_id: int) -> int:
        return (
            self._db()
            .execute(
                "SELECT COUNT(*) FROM posts WHERE feed_id = ? AND seen = 0",
                (feed_id,),
            )
            .fetchone()[0]
        )

    @_locked
    def mark_seen(self, feed_id: int, post_id: str, seen: bool = True) -> None:
        """Marque un billet lu ou non lu, et suit le compteur du fil.

        Le compteur bouge d'UN au plus, sur la transition seule : le
        recompter coûterait un balayage du fil à chaque touche.
        """
        db = self._db()
        ligne = db.execute(
            "SELECT seen FROM posts WHERE feed_id = ? AND post_id = ?",
            (feed_id, post_id),
        ).fetchone()
        if ligne is None:
            return
        if bool(ligne["seen"]) == bool(seen):
            return
        db.execute(
            "UPDATE posts SET seen = ? WHERE feed_id = ? AND post_id = ?",
            (1 if seen else 0, feed_id, post_id),
        )
        db.execute(
            "UPDATE feeds SET unseen = MAX(0, COALESCE(unseen, 0) + ?)"
            " WHERE id = ?",
            (-1 if seen else 1, feed_id),
        )
        db.commit()

    @_locked
    def mark_all_seen(self, feed_id: int) -> int:
        """Marque tout le fil lu. Rend le nombre de billets qui ont changé."""
        db = self._db()
        non_lus = db.execute(
            "SELECT COUNT(*) FROM posts WHERE feed_id = ? AND seen = 0",
            (feed_id,),
        ).fetchone()[0]
        if not non_lus:
            return 0
        db.execute(
            "UPDATE posts SET seen = 1 WHERE feed_id = ? AND seen = 0",
            (feed_id,),
        )
        db.execute("UPDATE feeds SET unseen = 0 WHERE id = ?", (feed_id,))
        db.commit()
        return non_lus

    @_locked
    def forget_post(self, feed_id: int, post_id: str) -> None:
        """Retire un billet du cache, sans rien demander à la plateforme.

        Appelée quand la plateforme ne le sert plus — retiré par son auteur,
        ou masqué. Les compteurs du fil suivent : sans cela l'écran
        annoncerait des non-lus qu'il n'a plus.
        """
        db = self._db()
        ligne = db.execute(
            "SELECT seen FROM posts WHERE feed_id = ? AND post_id = ?",
            (feed_id, post_id),
        ).fetchone()
        if ligne is None:
            return
        db.execute(
            "DELETE FROM posts WHERE feed_id = ? AND post_id = ?",
            (feed_id, post_id),
        )
        db.execute(
            "UPDATE feeds SET total = MAX(0, COALESCE(total, 0) - 1)"
            " WHERE id = ?",
            (feed_id,),
        )
        if not ligne["seen"]:
            db.execute(
                "UPDATE feeds SET unseen = MAX(0, COALESCE(unseen, 0) - 1)"
                " WHERE id = ?",
                (feed_id,),
            )
        db.commit()


def _media_json(media) -> str:
    """Les pièces en JSON, prêtes à sceller. Vide quand il n'y en a pas.

    Une colonne plutôt qu'une table : une pièce ne se cherche jamais seule,
    elle n'existe que par son billet, et une table la ferait vivre déscellée
    à côté du texte qu'on vient de sceller.
    """
    if not media:
        return ""
    return json.dumps(
        [
            {
                "url": m.url,
                "kind": m.kind,
                "description": m.description,
            }
            for m in media
        ],
        ensure_ascii=False,
    )


def _media_from_json(texte: str) -> list:
    """Relit les pièces. Un JSON abîmé rend une liste vide.

    Le billet reste lisible sans ses pièces ; lever ici ferait disparaître
    tout le fil pour une colonne tronquée.
    """
    if not texte:
        return []
    try:
        brut = json.loads(texte)
    except ValueError:
        return []
    if not isinstance(brut, list):
        return []
    return [
        Media(
            url=str(d.get("url", "")),
            kind=str(d.get("kind", "")),
            description=str(d.get("description", "")),
        )
        for d in brut
        if isinstance(d, dict)
    ]
