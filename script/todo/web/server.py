#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Hub local de l'interface web de TODO, un par checkout.

Une boucle asyncio porte deux entrées : un serveur HTTP tornado sur
127.0.0.1, port libre (la page et son API arrivent dans un commit
séparé) et une socket Unix 0600 (`ctl.sock`), réservée au compte de
l'utilisateur : une commande par ligne — `mint` (code de connexion à
usage unique), `status`, `stop`, `tasks`.

Un verrou (`hub.lock`) est tenu de bout en bout : deux démarrages
concurrents devant la même socket morte ne la retirent pas chacun pour
lier la leur. Le hub n'importe jamais `todo.py`.

    python -m script.todo.web.server --root <checkout> [--idle-seconds N]
"""

import argparse
import asyncio
import errno
import fcntl
import json
import logging
import os
import secrets
import signal
import socket
import sys
import time
from pathlib import Path

import tornado.httpserver
import tornado.netutil
import tornado.web

from script.todo.web import paths

log = logging.getLogger(__name__)

CODE_TTL = 120.0
# Corps HTTP et messages WebSocket : tornado accepte 100 Mo par défaut.
MAX_BODY = 64 * 1024
IDLE_SECONDS = 1800.0
PROBE_TIMEOUT = 0.3


class HubRunning(Exception):
    """Un hub répond déjà sur la socket de contrôle de ce checkout."""


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
    """Socket de contrôle, verrou et cycle de vie du hub, un par checkout."""

    def __init__(self, root, *, idle_seconds=IDLE_SECONDS):
        self.root = os.path.realpath(root)
        self.idle_seconds = idle_seconds
        self.codes = {}  # code -> expiration (horloge monotone)
        self.sessions = {}  # jeton du cookie -> jeton CSRF
        self.stopped = asyncio.Event()
        self.stopping = None
        self.last_activity = time.monotonic()

    def routes(self) -> list:
        return []

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

        state.json et redirect.html partent pendant que le verrou est tenu :
        aucun autre hub ne démarre avant, rien de ce qui est retiré ne lui
        appartient. Fermer le serveur Unix retire ctl.sock (asyncio vérifie
        que l'inode est toujours le sien).
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
