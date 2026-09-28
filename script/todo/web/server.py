#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Hub local de l'interface web de TODO, un par checkout.

Deux entrées dans une même boucle asyncio :

- HTTP tornado sur 127.0.0.1, port libre : la page et son API ;
- une socket Unix 0600 (`ctl.sock`), réservée au compte de l'utilisateur :
  une commande par ligne — `mint` (code de connexion à usage unique),
  `status`, `stop`, `tasks`, `purge` et `purge all` (le journal des tâches).

Le WebSocket `/ws` porte les sessions TODO (`sessions.py`) : un worker par
session, jamais d'autre programme. Le hub ne s'arrête pas pour inactivité
tant qu'une session existe ; son arrêt les ferme toutes. Chaque session
tient le journal de ses tâches (`tasklog`), que `/api/tasks` relit.

Chaque requête HTTP passe par `Guard.prepare` : `Host` dans la liste (port
exigé, contre le rebinding DNS) ; hors GET et HEAD, comme pour toute poignée
de main WebSocket, une Origin égale à `http://<Host>` (absente = refus) ;
hors GET, HEAD et OPTIONS, sauf pour le POST de la connexion, la session et
son jeton CSRF dans `X-CSRF-Token`. L'API exige le cookie de session, nommé
par port ; `/api/fs`, qui lit le disque au chemin que la requête nomme,
exige aussi le jeton CSRF en GET. Le hub n'importe jamais todo.py.

    python -m script.todo.web.server --root <checkout> [--idle-seconds N]
"""

import argparse
import asyncio
import base64
import datetime
import errno
import fcntl
import hashlib
import heapq
import importlib
import json
import logging
import os
import re
import secrets
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import tornado.httpserver
import tornado.netutil
import tornado.web
import tornado.websocket
from tornado.web import HTTPError

from script.todo import todo_i18n, todo_telemetry
from script.todo.web import paths, sessions, tasklog

log = logging.getLogger(__name__)

CODE_TTL = 120.0
# Corps HTTP et messages WebSocket : tornado accepte 100 Mo par défaut.
MAX_BODY = 64 * 1024
IDLE_SECONDS = 1800.0
# Le relevé de température peut lancer `sensors` : au plus un appel sur ce
# nombre, le premier de chaque session compris.
SYSTEM_FULL_EVERY = 5
PROBE_TIMEOUT = 0.3
# Un worker de réserve fini avant d'être pris fait attendre le suivant ce
# nombre de secondes : la vue Sessions liste les sessions toutes les 2 s.
SPARE_RETRY = 60.0
# Délai du premier message d'un WebSocket, et bornes d'une taille de terminal.
HELLO_SECONDS = 10.0
MAX_TERMINAL = 1000
# Un client qui ne répond plus au ping (tunnel SSH d'un poste en veille) est
# fermé en moins d'une minute : l'envoi en attente échoue et la session le
# détache, au lieu de retenir la commande jusqu'à ce que TCP abandonne.
PING_SECONDS = 20.0
# Purge du journal des tâches : au démarrage, puis à cet intervalle.
PURGE_SECONDS = 6 * 3600.0
# Plafonds de `limit` : tâches d'une page de l'historique, enregistrements
# d'une page de journal.
TASKS_LIMIT = 200
LINES_LIMIT = 1000
# /api/fs : entrées au plus d'un répertoire listé ; lectures en cours au
# plus, et secondes qu'attend chacune. Une lecture sans réponse (un montage
# réseau mort) retient un fil démon et une place jusqu'à son retour, jamais
# la boucle, les fils des autres handlers ni l'arrêt du hub.
FS_LIMIT = 2000
FS_READERS = 4
FS_TIMEOUT = 10.0
STATIC_DIR = Path(__file__).parent / "static"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}
LICENSE_TYPE = "text/plain; charset=utf-8"
IMPORT_MAP = re.compile(rb'<script type="importmap">(.*?)</script>', re.S)
# 'unsafe-eval' : le compilateur de gabarits d'OWL passe par new Function.
# style-src 'unsafe-inline', pour les styles seulement : le rendu DOM de
# xterm.js crée des éléments <style> et pose des attributs style ; aucun
# script en ligne n'est admis pour autant.
CSP = (
    "default-src 'none'; script-src 'self'{import_map} 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
# Fichiers que lit build_code_tree : todo.py, les mixins qu'il importe et
# todo.json à côté ; « *.py » couvre aussi todo_i18n.py, rechargé quand il
# change. Les surcharges de private/todo/ n'en sont pas : build_code_tree ne
# lit que todo.json.
TREE_SOURCES = (
    "script/todo/*.py",
    "script/todo/todo.json",
)


class HubRunning(Exception):
    """Un hub répond déjà sur la socket de contrôle de ce checkout."""


def load_static(static_dir: Path) -> dict:
    """{chemin d'URL: (octets, type MIME)} des fichiers servables.

    Lu une fois, au démarrage : une requête ne construit jamais de chemin
    disque, une traversée (`/static/../server.py`) ne trouve donc rien. Seuls
    entrent les fichiers dont l'extension est dans STATIC_TYPES et les
    `LICENSE`, jamais un lien symbolique. `/` sert `index.html`.
    """
    table = {}
    for dirpath, _dirnames, filenames in os.walk(static_dir):
        for name in filenames:
            path = Path(dirpath, name)
            if name == "LICENSE":
                ctype = LICENSE_TYPE
            else:
                ctype = STATIC_TYPES.get(path.suffix)
            if ctype is None or path.is_symlink():
                continue
            url = "/static/" + path.relative_to(static_dir).as_posix()
            table[url] = (path.read_bytes(), ctype)
    if "/static/index.html" in table:
        table["/"] = table["/static/index.html"]
    return table


def content_security_policy(index_html) -> str:
    """CSP du hub ; l'import map inline d'`index_html` y entre par son hash.

    Le hash porte sur le texte exact entre les balises, comme le calcule le
    navigateur : reformater l'import map change le hash, recalculé ici à
    chaque démarrage.
    """
    match = IMPORT_MAP.search(index_html)
    extra = ""
    if match:
        digest = hashlib.sha256(match.group(1)).digest()
        extra = f" 'sha256-{base64.b64encode(digest).decode()}'"
    return CSP.format(import_map=extra)


def fingerprint(signature) -> str:
    """Empreinte courte d'une signature de `CodeTree` : elle change dès
    qu'une source change, s'ajoute ou disparaît."""
    text = json.dumps(sorted(signature.items()))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class CodeTree:
    """Arbre des menus de `build_code_tree`, refait quand une source change.

    La signature est {chemin: (mtime_ns, taille)} de chaque fichier de
    TREE_SOURCES : une entrée ajoutée ou retirée d'un menu, dans le code ou
    dans todo.json, change l'arbre servi à la requête suivante sans
    redémarrer le hub. Un todo_i18n.py modifié est rechargé, et ses libellés
    nouveaux arrivent traduits : le hub l'importe depuis la racine qu'il
    sert. L'analyse AST, coûteuse, tourne dans un thread, une à la fois : la
    boucle continue de répondre, socket de contrôle comprise. `code` est
    l'empreinte de la signature de l'arbre servi (`fingerprint`), que la
    page compare pour savoir que le code de TODO a changé.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.i18n_py = str(self.root / "script" / "todo" / "todo_i18n.py")
        self.signature = None
        self.code = None
        self.tree = None
        self.lock = asyncio.Lock()
        # Estampille du todo_i18n.py que le hub vient d'importer.
        self.i18n_stamp = self._signature().get(self.i18n_py)

    def _signature(self) -> dict:
        entries = {}
        for pattern in TREE_SOURCES:
            for path in self.root.glob(pattern):
                try:
                    st = path.stat()
                except OSError:
                    continue
                entries[str(path)] = (st.st_mtime_ns, st.st_size)
        return entries

    def _refresh(self):
        signature = self._signature()
        if signature == self.signature:
            return self.tree
        stamp = signature.get(self.i18n_py)
        if stamp != self.i18n_stamp:
            _reload_i18n()
            self.i18n_stamp = stamp
        todo_py = self.root / "script" / "todo" / "todo.py"
        try:
            self.tree = todo_telemetry.build_code_tree(todo_py)
        except Exception:
            log.exception("building the menu tree failed")
            self.tree = None
        self.signature = signature
        self.code = fingerprint(signature)
        return self.tree

    def stamp(self) -> str:
        """L'empreinte des sources telles qu'elles sont sur le disque, sans
        rien analyser : celle que `code` prendra à la requête suivante."""
        return fingerprint(self._signature())

    async def refresh(self):
        """L'arbre à jour, ou None si l'analyse échoue ou lève ; la table de
        traduction est rechargée au passage si todo_i18n.py a changé.

        Une exception de build_code_tree va au journal et ne remonte pas :
        /api/telemetry et /api/i18n répondent, l'arbre nul, et l'analyse
        n'est retentée qu'au changement suivant d'une source.
        """
        async with self.lock:
            return await asyncio.to_thread(self._refresh)


def _reload_i18n():
    # Un fichier à moitié écrit ne casse pas l'API : l'erreur va au journal,
    # et l'enregistrement suivant change la signature, donc recharge.
    try:
        importlib.reload(todo_i18n)
    except Exception:
        log.exception("reloading todo_i18n.py failed")


def localize(node, lang, parent=None) -> dict:
    """Nœud servi à la page.

    `key` : libellé brut ; `label` : sa traduction dans `lang` ; `path` : le
    chemin de télémétrie, les clés jointes par « › » comme TODO les
    enregistre ; `menu` ; `entry` : la traduction du libellé que le menu
    parent montre pour ce nœud, `label` quand l'arbre n'en porte pas
    d'autre, vide pour un nœud, feuille ou sous-menu, qu'il ne nomme pas ;
    `section` traduite pour une feuille qui en a une. Ni méthode ni
    arguments : un `entry` non vide suffit à trouver le nœud dans le menu
    de son parent ; un `entry` vide dit qu'aucune entrée ne lui répond.
    """
    key = node["label"]
    path = key if parent is None else f"{parent} › {key}"
    out = {
        "key": key,
        "label": todo_i18n.translate(key, lang),
        "path": path,
        "menu": node["is_menu"],
        "entry": todo_i18n.translate(node.get("entry", key), lang),
        "children": [localize(c, lang, path) for c in node["children"]],
    }
    if node.get("section"):
        out["section"] = todo_i18n.translate(node["section"], lang)
    return out


def _is_dir(entry) -> bool:
    """Vrai pour un répertoire, ou un lien vers un répertoire."""
    try:
        return entry.is_dir()
    except OSError:
        return False


def _file_size(path):
    """La taille du fichier `path`, lien suivi ; None pour un lien cassé ou
    illisible."""
    try:
        return os.stat(path).st_size
    except OSError:
        return None


def _sort_keys(scan, dirs):
    """La clé de tri de chaque entrée de `scan` : `(fichier, nom sans casse,
    nom)`, les répertoires d'abord ; aucun fichier avec `dirs`."""
    for entry in scan:
        is_dir = _is_dir(entry)
        if is_dir or not dirs:
            yield (not is_dir, entry.name.casefold(), entry.name)


def _fs_error(path, reason) -> dict:
    """La réponse de /api/fs pour `path` quand il ne se liste pas : `reason`
    dit pourquoi."""
    return {
        "path": path,
        "parent": None,
        "entries": [],
        "truncated": False,
        "error": reason,
        "file": False,
    }


def list_directory(path, dirs=False, limit=FS_LIMIT) -> dict:
    """Le répertoire `path` pour le sélecteur de chemins de la page.

    `path`, `~` développé, doit être absolu ; il est normalisé par
    `os.path.realpath` (liens et `..` résolus). Rend `{path, parent,
    entries, truncated}` : `parent`, le répertoire au-dessus, None à la
    racine ; `entries`, des {name, dir, size}, les répertoires d'abord (un
    lien vers un répertoire en est un), puis les fichiers, aucun avec
    `dirs`, chaque groupe trié sans casse, au plus `limit` ; `truncated`,
    vrai au-delà. `size` : les octets d'un fichier, None pour un répertoire
    ou un lien cassé. Seul le répertoire est lu : aucun fichier n'est
    ouvert, et seules les `limit` premières entrées restent en mémoire,
    quelle que soit la taille du répertoire. Un chemin qui ne se liste pas
    (relatif, absent, un fichier, refusé, un octet nul) rend `{path,
    parent, entries: [], truncated: false, error, file}` au lieu de lever :
    `error`, la raison du système ; `file`, vrai pour un fichier qui
    existe. Un fichier revient sous son répertoire résolu et son dernier
    nom tel quel, lien non suivi, comme le clic sur son entrée le nomme :
    c'est ce chemin-là qui est vérifié, et « lien/../x » y désigne le `x`
    où le lien mène, comme pour le noyau."""
    listing = {"path": path, "parent": None, "entries": [], "truncated": False}
    asked = None
    try:
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            raise ValueError("not an absolute path")
        bare = expanded.rstrip("/") or "/"
        asked = os.path.join(
            os.path.realpath(os.path.dirname(bare)), os.path.basename(bare)
        )
        real = os.path.realpath(expanded)
        up = os.path.dirname(real)
        listing.update(path=real, parent=up if up != real else None)
        with os.scandir(real) as scan:
            found = heapq.nsmallest(limit + 1, _sort_keys(scan, dirs))
    except (OSError, ValueError) as exc:
        reason = getattr(exc, "strerror", None) or str(exc)
        is_file = asked is not None and os.path.isfile(asked)
        if is_file:
            listing.update(path=asked, parent=os.path.dirname(asked))
        return {**listing, "error": reason, "file": is_file}
    listing["entries"] = [
        {
            "name": name,
            "dir": not is_file,
            "size": _file_size(os.path.join(real, name)) if is_file else None,
        }
        for is_file, _, name in found[:limit]
    ]
    listing["truncated"] = len(found) > limit
    return listing


class Guard:
    """Contrôles communs à chaque handler ; mélangé avant la classe tornado."""

    # Vrai pour la connexion seule : son POST se passe de session et de
    # jeton CSRF, ses autres méthodes non.
    anonymous_post = False

    @property
    def hub(self) -> "Hub":
        # Lu dans les réglages de l'application : set_default_headers est
        # appelé par le constructeur de tornado, avant initialize().
        return self.application.settings["hub"]

    def set_default_headers(self):
        self.clear_header("Server")
        self.set_header("Content-Security-Policy", self.hub.csp)
        self.set_header("X-Frame-Options", "DENY")
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Referrer-Policy", "no-referrer")
        self.set_header("Cache-Control", "no-store")

    def prepare(self):
        # request.host retombe sur « 127.0.0.1 » en HTTP/1.0 : lire l'en-tête.
        host = (self.request.headers.get("Host") or "").lower()
        if host not in self.hub.hosts:
            raise HTTPError(403)
        # Une poignée de main WebSocket est un GET : l'en-tête Upgrade la
        # désigne, lu comme tornado le lit avant de l'accepter.
        upgrade = self.request.headers.get("Upgrade", "").lower()
        method = self.request.method
        if method not in ("GET", "HEAD") or upgrade == "websocket":
            if self.request.headers.get("Origin") != f"http://{host}":
                raise HTTPError(403)
        # Toute méthode qui peut écrire, quel que soit le handler qui la
        # recevra, sauf le POST anonyme de la connexion.
        writes = method not in ("GET", "HEAD", "OPTIONS")
        if writes and not (self.anonymous_post and method == "POST"):
            self.require_csrf()

    def check_origin(self, origin):
        """Origin d'une poignée de main WebSocket : `http://<Host>` exacte.

        tornado ne l'appelle que si l'en-tête est présent, et sa version
        ne compare que l'hôte, quel que soit le schéma ; prepare() refuse
        déjà une Origin absente.
        """
        host = (self.request.headers.get("Host") or "").lower()
        return origin == f"http://{host}"

    def require_session(self, touch=True) -> str:
        """Jeton CSRF de la session du cookie ; 403 sans session.

        Une requête authentifiée compte comme activité : elle repousse
        l'arrêt à l'inactivité, sauf avec `touch` faux.
        """
        token = self.get_cookie(self.hub.cookie)
        csrf = self.hub.sessions.get(token) if token else None
        if csrf is None:
            raise HTTPError(403)
        if touch:
            self.hub.touch()
        return csrf

    def require_csrf(self) -> None:
        """La session du cookie (`require_session`) et son jeton CSRF dans
        l'en-tête `X-CSRF-Token` ; 403 sinon."""
        csrf = self.require_session()
        sent = self.request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(sent.encode(), csrf.encode()):
            raise HTTPError(403)

    def int_argument(self, name, default, most) -> int:
        """`?name=`, un entier de 1 à `most`, `default` sans lui ; 400
        sinon."""
        raw = self.get_argument(name, None)
        if raw is None:
            return default
        if not re.fullmatch(r"[0-9]{1,10}", raw) or not 1 <= int(raw) <= most:
            raise HTTPError(400)
        return int(raw)

    def lang_argument(self) -> str:
        """`?lang=` de la requête, langue TODO du serveur par défaut ;
        400 pour une langue que TRANSLATIONS ne porte pas."""
        lang = self.get_argument("lang", todo_i18n.get_lang())
        if lang not in todo_i18n.LANGUAGES:
            raise HTTPError(400)
        return lang


class Static(Guard, tornado.web.RequestHandler):
    def get(self):
        entry = self.hub.static.get(self.request.path)
        if entry is None:
            raise HTTPError(404)
        body, ctype = entry
        self.set_header("Content-Type", ctype)
        self.write(body)


class NotFound(Guard, tornado.web.RequestHandler):
    def prepare(self):
        super().prepare()
        raise HTTPError(404)


class Login(Guard, tornado.web.RequestHandler):
    """Échange un code à usage unique contre le cookie de session."""

    anonymous_post = True

    def post(self):
        try:
            code = json.loads(self.request.body)["code"]
        except (ValueError, KeyError, TypeError):
            raise HTTPError(400) from None
        if not self.hub.redeem(code):
            raise HTTPError(403)
        self.set_cookie(
            self.hub.cookie,
            self.hub.open_session(),
            httponly=True,
            samesite="Strict",
        )
        self.write({"ok": True})


class Session(Guard, tornado.web.RequestHandler):
    def get(self):
        csrf = self.require_session()
        self.write(
            {"csrf": csrf, "lang": todo_i18n.get_lang(), "root": self.hub.root}
        )


class Telemetry(Guard, tornado.web.RequestHandler):
    """`{tree, counts, updated, code}` : l'arbre des menus traduit, les
    compteurs de navigation par chemin, l'heure de leur dernière écriture
    et l'empreinte des sources de l'arbre (`CodeTree.code`). `?poll=1`, la
    relecture de fond d'une page ouverte, ne compte pas comme activité :
    une page qui reste ouverte ne garde pas le hub en vie."""

    async def get(self):
        self.require_session(touch=self.get_argument("poll", None) != "1")
        lang = self.lang_argument()
        tree = await self.hub.code_tree.refresh()
        # load() attend le verrou que TODO tient en écrivant : hors boucle.
        data = await asyncio.to_thread(todo_telemetry.load)
        counts = data.get("paths")
        self.write(
            {
                "tree": localize(tree, lang) if tree else None,
                "counts": counts if isinstance(counts, dict) else {},
                "updated": data.get("updated"),
                "code": self.hub.code_tree.code,
            }
        )


class I18n(Guard, tornado.web.RequestHandler):
    """Toute la table de traduction dans une langue : `{clé: valeur}`."""

    async def get(self):
        self.require_session()
        lang = self.lang_argument()
        await self.hub.code_tree.refresh()
        self.write(
            {
                key: todo_i18n.translate(key, lang)
                for key in todo_i18n.TRANSLATIONS
            }
        )


class System(Guard, tornado.web.RequestHandler):
    """`{metrics, full}` : le relevé de `todo_telemetry.system_snapshot`.

    Le relevé précédent, d'où se calculent les taux du processeur et du
    réseau, est gardé par session, une par navigateur : ses onglets
    partagent le cookie, donc le relevé, et chaque taux se calcule sur
    l'intervalle réel entre deux appels. `full`, qui ajoute la température,
    vaut vrai au premier appel d'une session puis une fois sur
    SYSTEM_FULL_EVERY ; entre deux, `metrics["temp"]` est null et la page
    garde la dernière reçue.
    """

    async def get(self):
        self.require_session()
        token = self.get_cookie(self.hub.cookie)
        state = self.hub.system.setdefault(token, {"prev": None, "calls": 0})
        full = state["calls"] % SYSTEM_FULL_EVERY == 0
        state["calls"] += 1
        # Lectures de /proc et de /sys, `sensors` peut-être : hors boucle.
        metrics, state["prev"] = await asyncio.to_thread(
            todo_telemetry.system_snapshot, state["prev"], full
        )
        self.write({"metrics": metrics, "full": full})


class Files(Guard, tornado.web.RequestHandler):
    """`?path=&dirs=` : le répertoire `path` pour le sélecteur de chemins
    (`list_directory`, FS_LIMIT entrées au plus), `~` sans `path`, ses
    sous-répertoires seuls avec `dirs=1` ; 400 pour un autre `dirs`. Le hub
    tourne sous le compte de l'utilisateur, dont la page lance déjà les
    commandes : il n'y lit rien que TODO ne lise.

    Un GET qui lit le disque au chemin qu'il nomme exige, en plus du
    cookie, le jeton CSRF dans `X-CSRF-Token` (403 sinon) : SameSite ne
    sépare pas les ports, et une autre page de 127.0.0.1 enverrait le
    cookie, jamais cet en-tête, qu'une requête sans CORS ne porte pas et
    qu'aucune réponse du hub n'autorise en CORS.

    Chaque lecture a son fil démon, FS_READERS au plus à la fois : au-delà,
    la réponse est l'erreur `busy`. Une lecture qui ne revient pas en
    FS_TIMEOUT s rend l'erreur `timed out` ; son fil garde sa place jusqu'à
    son retour, et une exception de la lecture devient une erreur nommée
    par son type."""

    async def get(self):
        self.require_csrf()
        path = self.get_argument("path", "", strip=False) or "~"
        dirs = self.get_argument("dirs", "0")
        if dirs not in ("0", "1"):
            raise HTTPError(400)
        hub = self.hub
        if hub.fs_readers >= FS_READERS:
            self.write(_fs_error(path, "busy"))
            return
        hub.fs_readers += 1
        loop = asyncio.get_running_loop()
        done = loop.create_future()

        def finish(listing):
            hub.fs_readers -= 1
            if not done.done():
                done.set_result(listing)

        def read():
            try:
                listing = list_directory(path, dirs == "1", FS_LIMIT)
            except Exception as exc:
                listing = _fs_error(path, type(exc).__name__)
            try:
                loop.call_soon_threadsafe(finish, listing)
            except RuntimeError:
                pass  # boucle fermée : le hub s'est arrêté entre-temps

        threading.Thread(target=read, name="todo-fs", daemon=True).start()
        try:
            listing = await asyncio.wait_for(done, FS_TIMEOUT)
        except TimeoutError:
            listing = _fs_error(path, "timed out")
        self.write(listing)


def _size(message):
    """`(cols, rows)` d'un message, entiers dans [1, MAX_TERMINAL], ou None."""
    size = (message.get("cols"), message.get("rows"))
    if all(type(n) is int and 0 < n <= MAX_TERMINAL for n in size):
        return size
    return None


def _hello(message, csrf):
    """Le `hello` d'un client, ou None s'il ne tient pas : texte JSON, `t`
    valant « hello », jeton CSRF de la session du cookie, langue de
    TRANSLATIONS, taille valide, `session` texte et `after` entier positif
    s'ils sont là."""
    try:
        hello = json.loads(message) if isinstance(message, str) else None
    except ValueError:
        return None
    if not isinstance(hello, dict) or hello.get("t") != "hello":
        return None
    sent = hello.get("csrf")
    if not isinstance(sent, str) or not secrets.compare_digest(
        sent.encode(), csrf.encode()
    ):
        return None
    sid, after = hello.get("session"), hello.get("after")
    if (
        hello.get("lang") not in todo_i18n.LANGUAGES
        or _size(hello) is None
        or not (sid is None or isinstance(sid, str))
        or not (after is None or (type(after) is int and after >= 0))
    ):
        return None
    return hello


def _consume(future):
    """Lit l'issue d'un envoi que personne n'attend : une connexion fermée
    entre-temps n'a rien à signaler."""
    if not future.cancelled():
        future.exception()


class Terminal(Guard, tornado.websocket.WebSocketHandler):
    """`/ws` : une session TODO, octets du PTY dans les deux sens.

    Le premier message, texte, est `{"t": "hello", "csrf", "lang", "cols",
    "rows", "session"?, "after"?}`, sous HELLO_SECONDS, sinon 1008. Sans
    `session`, une session s'ouvre (au-delà de MAX_SESSIONS, 1013) ; avec,
    le client s'y rattache (inconnue, 4404) et en prend le contrôle :
    l'ancien est fermé en 4001. Réponse `{"t": "session", "id", "offset",
    "truncated", "code"}`, `code` étant l'empreinte des sources que tourne
    la session (`Session.stamp`), puis la question ouverte du worker s'il en
    a une, puis `dropped` pour ce que la session a jeté d'un collage sans
    client (`Session.unreported`), puis trames binaires. Textes du client :
    `resize`, `interrupt`, `close`, `raw`, `secret`, `answer`, `cancel` ;
    du hub : `bye`, `tty_state`, `dropped`, et les messages du worker
    (`menu`, `ask`, `answered`, `notice`, `run_start`, `run_end`,
    `open_view`). Un type inconnu est ignoré, comme une réponse qui n'est
    pas celle de la question ouverte (`Session.answer`).

    Une trame binaire du client passe par `Session.gate`, sauf en mode brut
    (`{"t": "raw", "on": true}`) ; `dropped {bytes, reason}` dit combien
    d'octets n'ont pas passé (`unread`), ou combien la session a jeté de la
    suite d'un collage (`Session._drop_held`, avec sa raison). tornado
    attend la fin de `on_message` avant de lire le message suivant : les
    messages qui suivent une trame que `gate` fait attendre attendent
    derrière elle, dans l'ordre. Un onglet qui a perdu la session pendant
    cette attente n'écrit rien. `interrupt` ne passe jamais par ce filtre.
    `secret` annonce que la trame suivante est la réponse du champ masqué :
    elle n'est écrite que si le terminal attend encore un secret, sinon
    `dropped` a pour raison `secret` et rien n'atteint le PTY, dont l'écho
    l'afficherait.
    """

    session = None
    hello_timer = None
    raw = False
    secret_next = False

    def prepare(self):
        super().prepare()
        self.csrf = self.require_session()

    def open(self):
        loop = asyncio.get_running_loop()
        self.hello_timer = loop.call_later(
            HELLO_SECONDS, self.close, 1008, "hello expected"
        )

    async def on_message(self, message):
        if self.session is None:
            await self.hello(message)
        elif self.session.client is not self:
            return  # repris par un autre onglet : ce qui arrive encore d'ici
        elif isinstance(message, bytes):
            await self.type(message)
        else:
            self.control(message)

    async def type(self, data):
        # Hors mode brut, un collage part une ligne à la fois.
        lines = not self.raw
        if self.secret_next:
            self.secret_next = False
            if not self.session.asks_secret():
                self.dropped(len(data), "secret")
                return
            kept, lines = data, False
        else:
            kept = data if self.raw else await self.session.gate(data)
            if self.session.client is not self:
                return  # repris par un autre onglet pendant `gate`
            if len(kept) < len(data):
                self.dropped(len(data) - len(kept), "unread")
        if kept and not self.session.write(kept, lines):
            self.close(1008, "input overflow")

    async def hello(self, message):
        self.hello_timer.cancel()
        hello = _hello(message, self.csrf)
        if hello is None:
            self.close(1008, "hello expected")
            return
        sid, (cols, rows) = hello.get("session"), _size(hello)
        if sid is None:
            if len(self.hub.terminals) >= sessions.MAX_SESSIONS:
                self.close(1013, "try again later")
                return
            try:
                session = await self.hub.open_terminal(
                    hello["lang"], cols, rows
                )
            except OSError:
                self.close(1011, "the session did not start")
                return
            if self.ws_connection is None:
                # Connexion fermée pendant le lancement : la session reste
                # sans client et finit par inactivité, comme un onglet fermé.
                return
        else:
            session = self.hub.terminals.get(sid)
            if session is None:
                self.close(4404, "unknown session")
                return
            session.resize(cols, rows)
        self.session = session
        offset, truncated, previous = session.attach(self, hello.get("after"))
        self.event(
            {
                "t": "session",
                "id": session.id,
                "offset": offset,
                "truncated": truncated,
                "code": session.stamp,
            }
        )
        if session.asking is not None:
            self.event(session.asking)
        if session.unreported:
            # Jeté d'un collage pendant qu'aucun onglet n'était là.
            self.dropped(session.unreported, "detached")
            session.unreported = 0
        if previous is not None:
            previous.close(4001, "taken over")

    def control(self, message):
        try:
            data = json.loads(message)
            kind = data.get("t")
        except (ValueError, AttributeError):
            return
        if kind == "resize":
            size = _size(data)
            if size is not None:
                self.session.resize(*size)
        elif kind == "interrupt":
            self.session.interrupt()
        elif kind == "close":
            self.hub.keep(self.session.close())
        elif kind == "raw":
            self.raw = data.get("on") is True
        elif kind == "secret":
            self.secret_next = True
        elif kind in ("answer", "cancel"):
            self.session.answer(data)

    def dropped(self, size, reason):
        """`dropped` : `size` octets jetés, pour `reason`, une raison de
        `protocol.DROP_REASONS`."""
        self.event({"t": "dropped", "bytes": size, "reason": reason})

    # Client d'une session (sessions.py) : send, event, close.

    def send(self, data):
        return self.write_message(data, binary=True)

    def event(self, message):
        try:
            self.write_message(message).add_done_callback(_consume)
        except tornado.websocket.WebSocketClosedError:
            pass

    def on_close(self):
        if self.hello_timer is not None:
            self.hello_timer.cancel()
        if self.session is not None:
            self.session.detach(self)


class SessionList(Guard, tornado.web.RequestHandler):
    """`{sessions: [{id, running, attached}], max}` : les sessions ouvertes,
    dans l'ordre de leur ouverture. La vue Sessions la demande : le hub
    prépare alors un worker de réserve pour la session suivante."""

    async def get(self):
        self.require_session()
        await self.hub.warm()
        terminals = self.hub.terminals.values()
        self.write(
            {
                "sessions": [
                    {
                        "id": s.id,
                        "running": s.busy,
                        "attached": s.client is not None,
                    }
                    for s in terminals
                ],
                "max": sessions.MAX_SESSIONS,
            }
        )


class Tasks(Guard, tornado.web.RequestHandler):
    """`{tasks, more}` : au plus `limit` (1 à TASKS_LIMIT, 50 par défaut)
    entrées d'index des tâches closes, les plus récentes d'abord, toutes
    avant l'identifiant `before` ; `more`, vrai s'il en reste."""

    async def get(self):
        self.require_session()
        limit = self.int_argument("limit", 50, TASKS_LIMIT)
        before = self.get_argument("before", None)
        if before is not None and not tasklog.TASK_ID.fullmatch(before):
            raise HTTPError(400)
        found = await asyncio.to_thread(
            tasklog.entries, self.hub.tasks_dir, limit + 1, before
        )
        self.write({"tasks": found[:limit], "more": len(found) > limit})


class TaskLines(Guard, tornado.web.RequestHandler):
    """`{lines, next, eof, state}` (`tasklog.read`) : au plus `limit` (1 à
    LINES_LIMIT, 500 par défaut) enregistrements du journal d'une tâche, à
    partir du numéro `from`. 404 pour un identifiant hors TASK_ID, avant
    tout chemin, et pour une tâche inconnue."""

    async def get(self, task_id):
        self.require_session()
        if not tasklog.TASK_ID.fullmatch(task_id):
            raise HTTPError(404)
        start = self.int_argument("from", 1, 2**31)
        limit = self.int_argument("limit", 500, LINES_LIMIT)
        page = await asyncio.to_thread(
            tasklog.read, self.hub.tasks_dir, task_id, start, limit
        )
        if page is None:
            raise HTTPError(404)
        self.write(page)


class TasksPurge(Guard, tornado.web.RequestHandler):
    """`POST {before?}` → `{removed}` : retire du journal les jours
    antérieurs à la date `before` (AAAA-MM-JJ), ou tous sans elle, sauf une
    tâche ouverte. Le jeton CSRF est exigé, comme pour toute écriture
    (`Guard.prepare`)."""

    def post(self):
        try:
            before = json.loads(self.request.body or b"{}").get("before")
            if before is not None:
                before = datetime.date.fromisoformat(before)
        except (ValueError, AttributeError, TypeError):
            raise HTTPError(400) from None
        self.write({"removed": self.hub.purge_tasks(before)})


def _hold_lock(path: Path) -> int:
    """Descripteur de `path` (0600) sous verrou exclusif, ou `HubRunning`.

    Le hub le tient de son démarrage à son arrêt : deux démarrages
    simultanés qui trouvent la même socket morte ne la retirent pas chacun
    pour lier la leur. Le noyau relâche le verrou à la mort du processus,
    SIGKILL compris ; le fichier, vide, reste.
    """
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise HubRunning(path) from None
    return fd


def _claim_ctl(path: Path) -> socket.socket:
    """Socket de contrôle liée à `path` et à l'écoute, en 0600 dès sa
    naissance.

    Une socket qui répond appartient à un hub vivant : `HubRunning`, jamais
    de vol. Une socket laissée par un hub mort (ECONNREFUSED) est retirée.
    `listen` suit `bind` sans attendre asyncio : une socket liée qui
    n'écoute pas encore répond ECONNREFUSED, comme une morte. Sous Linux,
    fchmod avant bind donne son mode à l'inode dès sa création ; ailleurs,
    l'umask le fait.
    """
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(PROBE_TIMEOUT)
    try:
        probe.connect(os.fspath(path))
    except FileNotFoundError:
        pass
    except ConnectionRefusedError:
        path.unlink(missing_ok=True)
    except TimeoutError:
        raise HubRunning(path) from None
    else:
        raise HubRunning(path)
    finally:
        probe.close()
    ctl = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        if sys.platform.startswith("linux"):
            os.fchmod(ctl.fileno(), 0o600)
            ctl.bind(os.fspath(path))
        else:
            umask = os.umask(0o177)
            try:
                ctl.bind(os.fspath(path))
            finally:
                os.umask(umask)
        ctl.listen(16)
    except OSError as exc:
        ctl.close()
        if exc.errno == errno.EADDRINUSE:
            raise HubRunning(path) from exc
        raise
    return ctl


class Hub:
    """Serveur HTTP, socket de contrôle, codes, sessions et inactivité."""

    def __init__(
        self, root, *, idle_seconds=IDLE_SECONDS, static_dir=STATIC_DIR
    ):
        self.root = os.path.realpath(root)
        self.idle_seconds = idle_seconds
        self.static = load_static(Path(static_dir))
        index = self.static.get("/")
        self.csp = content_security_policy(index[0] if index else b"")
        self.codes = {}  # code -> expiration (horloge monotone)
        self.sessions = {}  # jeton du cookie -> jeton CSRF
        self.stopped = asyncio.Event()
        self.stopping = None
        self.last_activity = time.monotonic()
        self.code_tree = CodeTree(self.root)
        self.system = {}  # jeton du cookie -> {"prev", "calls"}
        self.fs_readers = 0  # lectures de /api/fs pas encore revenues
        self.terminals = {}  # identifiant -> sessions.Session ouverte
        self.opening = 0  # `open_terminal` ou `warm` en cours
        self.spare = None  # worker de réserve, sans session encore
        # Heure (time.monotonic) avant laquelle aucune réserve n'est lancée.
        self.spare_after = 0.0
        self.session_idle = sessions.IDLE_SECONDS
        self.pending = set()  # fermetures en cours
        self.ctl = None  # serveur asyncio de ctl.sock, une fois démarré
        self.http = None
        self.tasks_dir = None  # journal des tâches, une fois démarré

    def routes(self) -> list:
        return [
            (r"/", Static),
            (r"/static/.*", Static),
            (r"/api/login", Login),
            (r"/api/session", Session),
            (r"/api/telemetry", Telemetry),
            (r"/api/i18n", I18n),
            (r"/api/system", System),
            (r"/api/fs", Files),
            (r"/api/sessions", SessionList),
            (r"/api/tasks", Tasks),
            (r"/api/tasks/purge", TasksPurge),
            (r"/api/tasks/([^/]+)", TaskLines),
            (r"/ws", Terminal),
        ]

    async def start(self, host="127.0.0.1", port=0):
        """Prend le verrou, lie ctl.sock et le port HTTP, écrit state.json.

        Tout échec après la prise du verrou, `HubRunning` compris, passe par
        `_undo_start` avant de remonter : un démarrage suivant, dans ce
        processus ou un autre, trouve le verrou libre et aucune socket liée.
        """
        self.ctl_path = paths.ctl_path(self.root)
        self.state_path = paths.state_path(self.root)
        self.redirect_path = paths.redirect_path(self.root)
        self.tasks_dir = paths.tasks_dir(self.root)
        self.lock_fd = _hold_lock(paths.lock_path(self.root))
        ctl, socks = None, []
        try:
            self._tidy()
            ctl = _claim_ctl(self.ctl_path)
            socks = tornado.netutil.bind_sockets(
                port, host, family=socket.AF_INET
            )
            await self._listen(ctl, socks)
        except BaseException:
            self._undo_start(ctl, socks)
            raise
        return self

    async def _listen(self, ctl, socks):
        """Met les serveurs HTTP et de contrôle à l'écoute sur les sockets
        liées, écrit state.json et lance la surveillance d'inactivité."""
        [sock] = socks
        self.port = sock.getsockname()[1]
        self.hosts = {
            f"{name}:{self.port}"
            for name in ("127.0.0.1", "localhost", "[::1]")
        }
        self.cookie = f"erplibre_todo_{self.port}"
        app = tornado.web.Application(
            self.routes(),
            default_handler_class=NotFound,
            hub=self,
            xsrf_cookies=False,
            websocket_max_message_size=MAX_BODY,
            websocket_ping_interval=PING_SECONDS,
            # La table i18n entière pèse quelques centaines de Kio en JSON.
            compress_response=True,
        )
        # tornado lit le corps avant prepare() : le borner ici.
        self.http = tornado.httpserver.HTTPServer(app, max_body_size=MAX_BODY)
        self.http.add_sockets([sock])
        self.ctl = await asyncio.start_unix_server(self.control, sock=ctl)
        self.started = int(time.time())
        self.touch()
        state = {
            "pid": os.getpid(),
            "port": self.port,
            "root": self.root,
            "started": self.started,
        }
        paths.write_private(self.state_path, json.dumps(state))
        self.idle_task = asyncio.create_task(self.watch_idle())
        self.purge_task = asyncio.create_task(self.watch_purge())
        log.info("listening on 127.0.0.1:%s for %s", self.port, self.root)

    def _tidy(self):
        """Verrou tenu, avant toute session : retire les fichiers
        temporaires orphelins du répertoire d'exécution, et clôt les tâches
        restées ouvertes (`interrupted`). Un échec, fichier abîmé compris,
        va au journal sans empêcher le démarrage ni l'autre étape."""
        try:
            paths.remove_orphans(paths.runtime_dir(self.root))
        except Exception:
            log.exception("removing the orphan files failed")
        try:
            tasklog.recover(self.tasks_dir)
        except Exception:
            log.exception("closing the open task logs failed")

    def _recorder(self, sid):
        """Le journal des tâches de la session `sid`, ses délais planifiés
        dans la boucle du hub."""
        loop = asyncio.get_running_loop()
        return tasklog.Recorder(self.tasks_dir, sid, loop.call_later)

    def _undo_start(self, ctl, socks):
        """Ferme ce que `start` a ouvert : serveurs de contrôle et HTTP,
        socket de contrôle et sockets TCP ; retire ctl.sock s'il a été lié
        ici, puis relâche le verrou, en dernier comme dans `stop`. Un
        ctl.sock que `_claim_ctl` a refusé de prendre n'est pas touché."""
        if self.ctl is not None:
            self.ctl.close()
        if self.http is not None:
            self.http.stop()
        for sock in (ctl, *socks):
            if sock is not None:
                sock.close()
        if ctl is not None:
            self.ctl_path.unlink(missing_ok=True)
        os.close(self.lock_fd)

    def touch(self):
        self.last_activity = time.monotonic()

    def mint(self) -> str:
        """Nouveau code ; un code émis compte comme activité, la connexion
        qu'il annonce ne doit pas trouver le hub arrêté entre-temps."""
        now = time.monotonic()
        self.codes = {c: t for c, t in self.codes.items() if t > now}
        code = secrets.token_urlsafe(24)
        self.codes[code] = now + CODE_TTL
        self.touch()
        return code

    def redeem(self, code) -> bool:
        """Consomme `code` ; vrai s'il existait et n'avait pas expiré."""
        expiry = self.codes.pop(code, 0.0) if isinstance(code, str) else 0.0
        if expiry < time.monotonic():
            return False
        self.touch()
        self._drop_redirect(code)
        return True

    def _drop_redirect(self, code):
        """Retire redirect.html s'il porte `code`, qui vient de servir.

        Le lanceur le réécrit pour chaque code émis : un fichier qui porte un
        autre code mène à un lien qui n'a pas encore servi, et reste. Un
        fichier absent ou illisible ne change rien à la connexion.
        """
        try:
            text = self.redirect_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        if code in text:
            self.redirect_path.unlink(missing_ok=True)

    def open_session(self) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = secrets.token_urlsafe(32)
        return token

    async def open_terminal(self, lang, cols, rows):
        """Nouvelle session TODO, comptée dès avant son lancement : deux
        `hello` simultanés ne dépassent pas MAX_SESSIONS. Le worker de
        réserve la devient s'il vit et que les sources de l'arbre n'ont pas
        changé depuis son lancement (`stamp`) : il a déjà importé
        todo_i18n, et tournerait ses anciennes traductions. Sinon un worker
        neuf est lancé, qui porte l'empreinte des sources du moment. OSError
        si elle ne démarre pas, ou si le hub s'arrête."""
        if self.stopping is not None:
            raise OSError("the hub is stopping")
        sid = secrets.token_urlsafe(6)
        stamp = self.code_tree.stamp()
        spare, self.spare = self.spare, None
        if spare is not None and spare.ready and spare.stamp == stamp:
            spare.adopt(sid, lang, cols, rows, self._terminal_ended)
            spare.recorder = self._recorder(sid)
            self.terminals[sid] = spare
            return spare
        if spare is not None:
            self.keep(spare.close())
        session = sessions.Session(
            sid, self.root, lang, cols, rows, on_end=self._terminal_ended
        )
        session.recorder = self._recorder(sid)
        session.stamp = stamp
        self.terminals[sid] = session
        self.opening += 1
        try:
            await session.start()
            if session.closing:
                # `stop` l'a fermée pendant son lancement.
                raise OSError("the hub is stopping")
        except BaseException:
            self.terminals.pop(sid, None)
            raise
        finally:
            self.opening -= 1
        return session

    async def warm(self):
        """Lance un worker de réserve s'il n'y en a pas et qu'une session de
        plus tiendrait sous MAX_SESSIONS : la session suivante le prend au
        lieu d'attendre les imports de TODO. Un lancement qui échoue laisse
        la session suivante partir à froid ; aucun ne suit avant
        `spare_after`. Compté dans `opening` : l'arrêt du hub attend qu'il
        rende."""
        if (
            self.spare is not None
            or self.stopping is not None
            or len(self.terminals) >= sessions.MAX_SESSIONS
            or time.monotonic() < self.spare_after
        ):
            return
        spare = sessions.Session(
            None, self.root, None, 80, 24, on_end=self._spare_ended
        )
        spare.stamp = self.code_tree.stamp()
        self.spare = spare
        self.opening += 1
        try:
            await spare.start()
        except OSError:
            self._spare_ended(spare)
        finally:
            self.opening -= 1

    def _spare_ended(self, session):
        """Fin d'un worker de réserve qu'aucune session n'a pris : le
        suivant attend SPARE_RETRY secondes. Un worker qui ne démarre pas
        (venv cassé, bibliothèque qui lève à son import) n'est pas relancé
        à chaque liste des sessions. Une réserve que le hub a fermée
        (`closing`) ne retarde rien : `open_terminal` ferme celle qui se
        lance encore, `stop` celle qui reste."""
        if self.spare is session:
            self.spare = None
        if not session.closing:
            self.spare_after = time.monotonic() + SPARE_RETRY

    def _terminal_ended(self, session):
        self.terminals.pop(session.id, None)
        self.touch()

    def keep(self, coro):
        """Lance `coro` et garde sa tâche jusqu'à sa fin."""
        task = asyncio.ensure_future(coro)
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    def purge_tasks(self, before=None) -> int:
        """Tâches closes retirées du journal : les jours antérieurs à la
        date `before`, tous sans elle (`tasklog.purge`). Dans la boucle :
        aucune tâche ne s'ouvre pendant la purge."""
        removed = tasklog.purge(self.tasks_dir, before)
        log.info("task logs purged: %s", removed)
        return removed

    async def watch_purge(self):
        """Retire, au démarrage puis toutes les PURGE_SECONDS, les jours de
        plus de RETENTION_DAYS jours. Un échec, fichier abîmé compris, va au
        journal ; la purge suivante réessaie."""
        while True:
            try:
                self.purge_tasks(tasklog.expiry())
            except Exception:
                log.exception("purging the task logs failed")
            await asyncio.sleep(PURGE_SECONDS)

    def status(self) -> dict:
        """`sessions` : sessions TODO ouvertes ; `running` : celles dont le
        worker a lancé une commande ou un processus (`Session.busy`)."""
        terminals = self.terminals.values()
        return {
            "pid": os.getpid(),
            "port": self.port,
            "root": self.root,
            "sessions": len(terminals),
            "running": sum(s.busy for s in terminals),
            "started": self.started,
            "idle_seconds": int(time.monotonic() - self.last_activity),
        }

    def command(self, name: str) -> str:
        if name == "mint":
            return self.mint()
        if name == "status":
            return json.dumps(self.status())
        if name == "stop":
            self.request_stop()
            return "ok"
        if name == "tasks":
            return "\n".join(
                asyncio.format_call_graph(task) for task in asyncio.all_tasks()
            )
        if name in ("purge", "purge all"):
            before = None if name == "purge all" else tasklog.expiry()
            try:
                return str(self.purge_tasks(before))
            except Exception as exc:
                log.exception("purging the task logs failed")
                return f"error: {exc}"
        return "error: unknown command"

    async def control(self, reader, writer):
        """Une commande par ligne ; la réponse, puis la fermeture."""
        try:
            line = await reader.readline()
            reply = self.command(line.decode(errors="replace").strip())
            writer.write(reply.encode() + b"\n")
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    async def watch_idle(self):
        """Ferme une session sans client ni rien en cours depuis
        `session_idle` secondes ; tant qu'une session existe, le hub ne
        s'arrête pas."""
        period = max(0.05, min(60.0, self.idle_seconds / 4))
        while True:
            await asyncio.sleep(period)
            now = time.monotonic()
            for session in list(self.terminals.values()):
                idle = session.idle(now) >= self.session_idle
                if idle and not session.closing:
                    self.keep(session.close())
            if self.terminals:
                self.touch()
            elif now - self.last_activity >= self.idle_seconds:
                log.info("idle for %ss, stopping", self.idle_seconds)
                self.request_stop()
                return

    def request_stop(self):
        if self.stopping is None:
            self.stopping = asyncio.ensure_future(self.stop())

    async def stop(self):
        """Ferme les sessions et le worker de réserve, retire l'état, ferme
        les sockets, relâche le verrou, puis signale `stopped`.

        Chaque session raccroche son PTY ; ses groupes reçoivent SIGHUP, puis
        SIGKILL après REAP_SECONDS : aucun worker ne survit au hub. Une
        session encore en lancement rend `close` aussitôt et s'arrête une
        fois lancée : l'arrêt attend aussi qu'aucune session ne reste et que
        chaque `open_terminal` ou `warm` ait rendu, ce qu'il fait une fois
        l'arrêt de sa session fini, SIGKILL compris. L'attente est bornée :
        une session qui ne finit pas n'empêche pas l'arrêt.

        state.json, redirect.html et ctl.sock partent pendant que le verrou
        est tenu : aucun autre hub ne démarre avant, rien de ce qui est
        retiré ne lui appartient. Fermer le serveur Unix retire ctl.sock
        (asyncio vérifie que l'inode est toujours le sien).
        """
        self.idle_task.cancel()
        self.purge_task.cancel()
        spares = [self.spare] if self.spare is not None else []
        closing = [s.close() for s in (*self.terminals.values(), *spares)]
        try:
            async with asyncio.timeout(sessions.REAP_SECONDS + 2):
                await asyncio.gather(*closing)
                while self.terminals or self.opening:
                    await asyncio.sleep(0.05)
        except TimeoutError:
            log.warning("sessions still closing, stopping anyway")
        self.state_path.unlink(missing_ok=True)
        self.redirect_path.unlink(missing_ok=True)
        self.ctl.close()
        os.close(self.lock_fd)
        self.http.stop()
        await self.http.close_all_connections()
        log.info("stopped")
        self.stopped.set()


def log_to_file(root) -> logging.Handler:
    """Envoie tout journal du processus, `tornado.access` compris, dans
    server.log (0600) : jamais sur un terminal. Rend le handler posé."""
    os.close(paths.open_log(root))
    handler = logging.FileHandler(paths.log_path(root), encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    top = logging.getLogger()
    top.addHandler(handler)
    top.setLevel(logging.INFO)
    return handler


async def serve(root, idle_seconds) -> None:
    hub = await Hub(root, idle_seconds=idle_seconds).start()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, hub.request_stop)
    await hub.stopped.wait()


def main(argv=None) -> int:
    """0 à l'arrêt ; 2 si root ou chemin de socket trop long ; 3 si un hub
    sert déjà ce checkout. Les refus vont sur stderr ; celui de root précède
    toute création de fichier."""
    parser = argparse.ArgumentParser(
        prog="python -m script.todo.web.server",
        description="Local hub of the TODO web interface.",
    )
    parser.add_argument("--root", required=True, help="ERPLibre checkout")
    parser.add_argument(
        "--idle-seconds",
        type=float,
        default=IDLE_SECONDS,
        help="stop after this many seconds without activity",
    )
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        print("todo web: refusing to run as root", file=sys.stderr)
        return 2
    root = os.path.realpath(args.root)
    try:
        paths.ctl_path(root)
    except ValueError as exc:
        print(f"todo web: {exc}", file=sys.stderr)
        return 2
    handler = log_to_file(root)
    try:
        asyncio.run(serve(root, args.idle_seconds))
    except HubRunning:
        print("todo web: a hub already serves this checkout", file=sys.stderr)
        return 3
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
