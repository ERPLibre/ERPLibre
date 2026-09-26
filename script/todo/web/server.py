#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Hub local de l'interface web de TODO, un par checkout.

Deux entrées dans une même boucle asyncio :

- HTTP tornado sur 127.0.0.1, port libre : la page et son API ;
- une socket Unix 0600 (`ctl.sock`), réservée au compte de l'utilisateur :
  une commande par ligne — `mint` (code de connexion à usage unique),
  `status`, `stop`, `tasks`.

Chaque requête HTTP passe par `Guard.prepare` : `Host` dans la liste (port
exigé, contre le rebinding DNS) ; hors GET et HEAD, comme pour toute poignée
de main WebSocket, une Origin égale à `http://<Host>` (absente = refus) ;
pour un POST autre que la connexion, le jeton CSRF de la session dans
`X-CSRF-Token`. L'API exige le cookie de session, nommé par port. Le hub
n'importe jamais todo.py.

    python -m script.todo.web.server --root <checkout> [--idle-seconds N]
"""

import argparse
import asyncio
import base64
import errno
import fcntl
import hashlib
import json
import logging
import os
import re
import secrets
import signal
import socket
import sys
import time
from pathlib import Path

import tornado.httpserver
import tornado.netutil
import tornado.web
from tornado.web import HTTPError

from script.todo import todo_i18n
from script.todo.web import paths

log = logging.getLogger(__name__)

CODE_TTL = 120.0
# Corps HTTP et messages WebSocket : tornado accepte 100 Mo par défaut.
MAX_BODY = 64 * 1024
IDLE_SECONDS = 1800.0
PROBE_TIMEOUT = 0.3
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
CSP = (
    "default-src 'none'; script-src 'self'{import_map} 'unsafe-eval'; "
    "style-src 'self'; connect-src 'self'; img-src 'self' data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
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


class Guard:
    """Contrôles communs à chaque handler ; mélangé avant la classe tornado."""

    # Seule la connexion reçoit un POST sans session ni jeton CSRF.
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
        unsafe = self.request.method not in ("GET", "HEAD")
        if unsafe or upgrade == "websocket":
            if self.request.headers.get("Origin") != f"http://{host}":
                raise HTTPError(403)
        if self.request.method == "POST" and not self.anonymous_post:
            csrf = self.require_session()
            sent = self.request.headers.get("X-CSRF-Token", "")
            if not secrets.compare_digest(sent.encode(), csrf.encode()):
                raise HTTPError(403)

    def check_origin(self, origin):
        """Origin d'une poignée de main WebSocket : `http://<Host>` exacte.

        tornado ne l'appelle que si l'en-tête est présent, et sa version
        ne compare que l'hôte, quel que soit le schéma ; prepare() refuse
        déjà une Origin absente.
        """
        host = (self.request.headers.get("Host") or "").lower()
        return origin == f"http://{host}"

    def require_session(self) -> str:
        """Jeton CSRF de la session du cookie ; 403 sans session.

        Une requête authentifiée compte comme activité : elle repousse
        l'arrêt à l'inactivité.
        """
        token = self.get_cookie(self.hub.cookie)
        csrf = self.hub.sessions.get(token) if token else None
        if csrf is None:
            raise HTTPError(403)
        self.hub.touch()
        return csrf


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

    def routes(self) -> list:
        return [
            (r"/", Static),
            (r"/static/.*", Static),
            (r"/api/login", Login),
            (r"/api/session", Session),
        ]

    async def start(self, host="127.0.0.1", port=0):
        self.ctl_path = paths.ctl_path(self.root)
        self.state_path = paths.state_path(self.root)
        self.redirect_path = paths.redirect_path(self.root)
        self.lock_fd = _hold_lock(paths.lock_path(self.root))
        try:
            ctl = _claim_ctl(self.ctl_path)
        except BaseException:
            os.close(self.lock_fd)
            raise
        [sock] = tornado.netutil.bind_sockets(
            port, host, family=socket.AF_INET
        )
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
        log.info("listening on 127.0.0.1:%s for %s", self.port, self.root)
        return self

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
        # Le fichier de redirection porte un code : il a servi.
        self.redirect_path.unlink(missing_ok=True)
        return True

    def open_session(self) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = secrets.token_urlsafe(32)
        return token

    def status(self) -> dict:
        """`sessions` : sessions ouvertes depuis le démarrage ; `running` :
        sessions qui exécutent une commande, aucune dans un hub qui ne lance
        rien."""
        return {
            "pid": os.getpid(),
            "port": self.port,
            "root": self.root,
            "sessions": len(self.sessions),
            "running": 0,
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
        period = max(0.05, min(60.0, self.idle_seconds / 4))
        while True:
            await asyncio.sleep(period)
            if time.monotonic() - self.last_activity >= self.idle_seconds:
                log.info("idle for %ss, stopping", self.idle_seconds)
                self.request_stop()
                return

    def request_stop(self):
        if self.stopping is None:
            self.stopping = asyncio.ensure_future(self.stop())

    async def stop(self):
        """Retire l'état, ferme les sockets, relâche le verrou, puis signale
        `stopped`.

        state.json, redirect.html et ctl.sock partent pendant que le verrou
        est tenu : aucun autre hub ne démarre avant, rien de ce qui est
        retiré ne lui appartient. Fermer le serveur Unix retire ctl.sock
        (asyncio vérifie que l'inode est toujours le sien).
        """
        self.idle_task.cancel()
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
