#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lanceur du hub web de TODO : démarrer ou réutiliser, émettre un code de
connexion, ouvrir la page, arrêter, interroger.

Tout passe par la socket de contrôle du checkout (`paths.ctl_path`), et
`status` écarte un hub qui annonce une autre racine. Le code de connexion ne
paraît dans aucun argv, que tout compte local lit dans /proc : le navigateur
reçoit le chemin d'un fichier de redirection 0600, et le lien complet n'est
rendu qu'à l'appelant, qui l'affiche dans le terminal de l'utilisateur.

API du menu TODO : `status`, `ensure_running`, `mint_code`, `open_page`,
`stop`, `LaunchError`, `OpenResult`. Elles ne lèvent que `ValueError`
(argument invalide) ou `LaunchError`. Sous root, aucune ne crée de fichier :
le hub refuse root, et un répertoire créé par root sous le HOME de
l'utilisateur (`sudo -E`) bloquerait ses lancements suivants. En ligne de
commande (messages anglais, sans traduction) :

    python -m script.todo.web.launcher open|stop|status [--view V]
                                       [--no-browser] [--root R]
"""

import argparse
import html
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from script.todo import todo_i18n
from script.todo.web import paths

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CTL_TIMEOUT = 0.3
START_TIMEOUT = 5.0
STOP_TIMEOUT = 5.0
POLL = 0.1
LOG_TAIL = 5
# Page locale, ouverte en file:// : elle mène au lien sans JavaScript.
REDIRECT = """<!doctype html>
<meta charset="utf-8">
<meta name="referrer" content="no-referrer">
<meta http-equiv="refresh" content="0;url={link}">
<title>ERPLibre TODO</title>
<p><a href="{link}">ERPLibre TODO</a></p>
"""

# Hubs lancés par CE processus, par pid : les attendre une fois arrêtés
# évite un zombie, et un Popen détruit sans attente avertit.
_SPAWNED = {}


class LaunchError(Exception):
    """Le hub n'a pas démarré. `log_tail` : fin de son journal, ou vide."""

    def __init__(self, message, log_tail=""):
        super().__init__(message)
        self.message = message
        self.log_tail = log_tail


@dataclass(frozen=True)
class OpenResult:
    url: str  # adresse du hub, sans code
    link: str  # lien de connexion, code à usage unique dans le fragment
    opened: bool  # le navigateur a été appelé et l'a accepté
    headless: bool  # ni DISPLAY ni WAYLAND_DISPLAY, hors macOS


def venv_python(root) -> str:
    """Python du venv d'outillage, nommé par conf/python-erplibre-venv
    (première ligne non vide et non commentée), comme le lit todo.py."""
    name = ".venv.erplibre"
    conf = Path(root, "conf", "python-erplibre-venv")
    try:
        for line in conf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                name = line
                break
    except (OSError, UnicodeDecodeError):
        pass
    return str(Path(root, name, "bin", "python"))


def _ctl(root, command):
    """Réponse du hub à `command`, None si rien ne répond à temps.

    Un chemin de socket trop long pour AF_UNIX (`ValueError`) vaut aussi
    None : aucun hub ne peut y écouter, et celui que lance ensure_running
    s'arrête en l'écrivant dans son journal, que LaunchError rapporte. Sous
    root, None avant tout chemin : `paths` créerait les répertoires.
    """
    if os.geteuid() == 0:
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(CTL_TIMEOUT)
            sock.connect(os.fspath(paths.ctl_path(root)))
            sock.sendall(command.encode() + b"\n")
            chunks = []
            while chunk := sock.recv(65536):
                chunks.append(chunk)
    except (OSError, ValueError):
        return None
    return b"".join(chunks).decode(errors="replace").strip()


def _reap():
    for pid, proc in list(_SPAWNED.items()):
        if proc.poll() is not None:
            del _SPAWNED[pid]


def _tail(root) -> str:
    try:
        text = paths.log_path(root).read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-LOG_TAIL:])


def status(root):
    """dict `{pid, port, root, sessions, running, started, idle_seconds}`
    du hub de `root`, ou None si aucun ne répond en CTL_TIMEOUT s, et sous
    root. `sessions` compte les sessions ouvertes depuis le démarrage,
    `running` celles qui exécutent une commande. Un hub qui annonce une
    autre racine n'est pas celui de ce checkout : None, et un avertissement
    dans le journal."""
    _reap()
    reply = _ctl(root, "status")
    try:
        info = json.loads(reply) if reply else None
    except ValueError:
        return None
    if not isinstance(info, dict):
        return None
    if info.get("root") != os.path.realpath(root):
        log.warning(
            "ignoring the hub of another checkout (%s) on %s",
            info.get("root"),
            paths.ctl_path(root),
        )
        return None
    return info


def ensure_running(root) -> dict:
    """État du hub de `root`, lancé s'il ne répond pas.

    Le hub est détaché (nouvelle session, stdin sur /dev/null, sorties dans
    server.log, vidé à chaque lancement) : Ctrl+C dans le terminal de TODO ne
    l'atteint pas. `status` est sondé toutes les POLL s pendant
    START_TIMEOUT s, et encore après une sortie en code 3 du hub lancé ici :
    le hub d'un autre lanceur répond alors à sa place. Sans réponse, le hub
    est tué et `LaunchError` porte la fin du journal. `LaunchError` aussi
    sous root, et quand le journal ne peut pas être ouvert.
    """
    if os.geteuid() == 0:
        raise LaunchError("the web hub refuses to run as root")
    info = status(root)
    if info is not None:
        return info
    root = os.path.realpath(root)
    python = venv_python(root)
    try:
        fd = paths.open_log(root)
    except OSError as exc:
        raise LaunchError(f"cannot open the web hub log: {exc}") from exc
    try:
        os.ftruncate(fd, 0)
        proc = subprocess.Popen(
            [python, "-m", "script.todo.web.server", "--root", root],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=fd,
            stderr=fd,
            start_new_session=True,
        )
    except OSError as exc:
        raise LaunchError(f"cannot run {python}: {exc}") from exc
    finally:
        os.close(fd)
    _SPAWNED[proc.pid] = proc
    deadline = time.monotonic() + START_TIMEOUT
    while True:
        info = status(root)
        if info is not None:
            return info
        # Code 3 : un autre lanceur tient le verrou ou sert déjà ce
        # checkout, et son hub est attendu comme le nôtre. Tout autre code
        # de sortie est un échec sans attente.
        if time.monotonic() >= deadline or proc.poll() not in (None, 3):
            break
        time.sleep(POLL)
    if proc.poll() is None:
        proc.kill()
        proc.wait()
    _SPAWNED.pop(proc.pid, None)
    raise LaunchError("the web hub did not start", _tail(root))


def mint_code(root) -> str:
    """Code de connexion neuf (usage unique, 120 s) du hub de `root`."""
    code = _ctl(root, "mint")
    if not code or code.startswith("error"):
        raise LaunchError("the web hub is not running")
    return code


def open_page(root, view="telemetry", lang=None, browser=True) -> OpenResult:
    """Démarre ou réutilise le hub, émet un code et ouvre la page.

    Le lien `http://127.0.0.1:P/#login=<code>&view=<view>[&lang=<lang>]`
    porte le code dans le fragment, que le navigateur n'envoie jamais au
    serveur. Il est écrit dans redirect.html (0600) ; avec un affichage et
    `browser`, le navigateur reçoit le chemin file:// de ce fichier. Le lien
    est toujours rendu : un navigateur confiné (snap, flatpak) ne lit pas
    $XDG_RUNTIME_DIR, et l'utilisateur le copie alors depuis le terminal.
    Sous macOS, qui n'a pas de DISPLAY, le navigateur est toujours appelé.
    `ValueError` pour une vue ou une langue invalide, `LaunchError` pour
    tout autre échec.
    """
    if not re.fullmatch(r"[a-z]+", view):
        raise ValueError(f"invalid view: {view!r}")
    if lang is not None and lang not in todo_i18n.LANGUAGES:
        raise ValueError(f"unknown language: {lang!r}")
    info = ensure_running(root)
    url = f"http://127.0.0.1:{info['port']}/"
    fragment = {"login": mint_code(root), "view": view}
    if lang:
        fragment["lang"] = lang
    link = f"{url}#{urlencode(fragment)}"
    try:
        redirect = paths.redirect_path(root)
        paths.write_private(redirect, REDIRECT.format(link=html.escape(link)))
    except OSError as exc:
        raise LaunchError(f"cannot write the redirect file: {exc}") from exc
    display = (
        sys.platform == "darwin"
        or os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
    )
    opened = False
    if browser and display:
        opened = bool(webbrowser.open_new_tab(redirect.as_uri()))
    return OpenResult(url, link, opened, not display)


def stop(root) -> bool:
    """Arrête le hub de `root`. Vrai s'il répondait et ne répond plus avant
    STOP_TIMEOUT s ; faux s'il ne tournait pas, ou tourne encore."""
    info = status(root)
    if info is None:
        return False
    _ctl(root, "stop")
    deadline = time.monotonic() + STOP_TIMEOUT
    while True:
        now = status(root)
        if now is None or now.get("pid") != info["pid"]:
            break
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL)
    proc = _SPAWNED.pop(info["pid"], None)
    if proc is not None:
        try:
            proc.wait(max(POLL, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _SPAWNED[proc.pid] = proc
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m script.todo.web.launcher",
        description="Start, open or stop the TODO web interface.",
    )
    parser.add_argument("action", choices=("open", "stop", "status"))
    parser.add_argument("--view", default="telemetry")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--root", default=str(ROOT), help="ERPLibre checkout")
    args = parser.parse_args(argv)
    if args.action == "status":
        info = status(args.root)
        print(json.dumps(info) if info else "not running")
        return 0 if info else 1
    if args.action == "stop":
        if status(args.root) is None:
            print("not running")
            return 0
        if stop(args.root):
            print("stopped")
            return 0
        print("the web hub did not stop", file=sys.stderr)
        return 1
    try:
        result = open_page(
            args.root,
            view=args.view,
            lang=todo_i18n.get_lang(),
            browser=not args.no_browser,
        )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    except LaunchError as exc:
        print(exc.message, file=sys.stderr)
        if exc.log_tail:
            print(exc.log_tail, file=sys.stderr)
        return 1
    print(f"url: {result.url}")
    if result.headless:
        port = urlsplit(result.url).port
        print(f"tunnel: ssh -L {port}:127.0.0.1:{port} <this host>")
    print(f"link: {result.link}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
