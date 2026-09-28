#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fenêtre bureautique de TODO : la page du hub web dans une fenêtre
native pywebview, sans code d'interface propre.

La fenêtre charge la même page que le navigateur, sur le même hub
(`launcher.ensure_running`), et vit dans CE processus : le lien et son code
de connexion vont de `launcher.mint_code` à `webview.create_window` sans
passer par un argv ni par un fichier. Fermer la fenêtre termine ce
processus seulement : le hub et ses sessions restent, et la fenêtre
suivante les retrouve dans la vue Sessions.

La page n'atteint que les trois fonctions de `bridge`, le titre de la
fenêtre, une notification de bureau et le dialogue de fichiers du système,
par un jeton que chaque fenêtre tire pour elle seule, et seulement tant que
la fenêtre montre une page du hub.
Sans pywebview ou sans moteur web, `main` le dit, donne les commandes
d'installation (`install_hint`), que rien ne lance, et ouvre la page dans
le navigateur ; sans affichage, il dit seulement « no display on this
host » et ouvre le navigateur. En ligne de commande (messages anglais, sans
traduction, comme le lanceur) :

    python -m script.todo.web.desktop open [--view V] [--root R]
    python -m script.todo.web.desktop install [--root R]

Le menu de TODO lance `open` dans un processus détaché (`spawn`) ;
`install` écrit l'entrée du menu des applications du bureau
(`install_entry`). La langue de la page vient de TODO_LANG, sinon de
`todo_i18n.get_lang`.
"""

import argparse
import ctypes.util
import hmac
import html
import importlib.util
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from script.todo import todo_i18n, todo_install
from script.todo.web import launcher, paths

ROOT = launcher.ROOT
TITLE = "ERPLibre TODO"
WIDTH, HEIGHT = 1200, 800
# Longueurs gardées d'un titre et du corps d'une notification.
TITLE_MAX = 200
BODY_MAX = 300
NOTIFY_TIMEOUT = 5.0
# Secondes entre deux notifications de la page : un appel plus rapproché
# est ignoré, et la page ne lance jamais plus d'un notify-send par seconde.
NOTIFY_INTERVAL = 1.0
# pywebview et son moteur Qt, en roues binaires : un venv qui ne voit pas
# les paquets Python du système n'a pas d'autre moteur sans compilation.
# Sous macOS, pywebview prend le moteur du système (`PYWEBVIEW_MACOS`).
PYWEBVIEW = "pywebview[qt]>=5,<6"
PYWEBVIEW_MACOS = "pywebview>=5,<6"
# Bibliothèques système que QtWebEngine charge et qu'un poste de bureau
# n'a pas toujours, par famille de gestionnaire (`todo_install`).
QT_LIBRARIES = {
    "apt-get": ["libxkbfile1", "libxcb-cursor0"],
    "dnf": ["libxkbfile", "xcb-util-cursor"],
    "pacman": ["libxkbfile", "xcb-util-cursor"],
    "zypper": ["libxkbfile1", "libxcb-cursor0"],
}
QT_BINDINGS = ("PyQt6", "PySide6", "PyQt5", "PySide2")
# Secondes pendant lesquelles le menu attend le processus de la fenêtre :
# sorti avant, il n'a pas ouvert de fenêtre, et son journal dit pourquoi.
SPAWN_GRACE = 1.5
# Lignes du journal des fenêtres que le menu affiche.
LOG_TAIL = 8
# Icône de l'entrée du bureau : un nom générique de la spécification des
# noms d'icônes freedesktop, que tout thème porte.
ICON = "applications-system"
# Caractères qui obligent à citer un argument de la clé Exec (Desktop Entry
# Specification).
EXEC_RESERVED = frozenset(" \t\n\"'\\><~|&;$*?#()`")


def _webview():
    """Le module pywebview, ou None s'il ne s'importe pas, quelle qu'en soit
    la raison : un paquet cassé ne vaut pas mieux qu'un paquet absent."""
    try:
        import webview
    except Exception:
        return None
    return webview


def _found(name) -> bool:
    """Vrai si le module `name` est installé, sans l'importer (ses paquets
    parents, eux, s'importent) ; faux si l'un d'eux échoue."""
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _qt_libraries() -> bool:
    """Vrai si l'éditeur de liens trouve libxkbfile, sans laquelle
    QtWebEngine ne s'importe pas, et libxcb-cursor quand Qt prendra la
    plateforme xcb : sans elle, Qt 6.5 et plus arrête le processus
    (SIGABRT) avant toute exception. La plateforme est QT_QPA_PLATFORM,
    sinon wayland sous WAYLAND_DISPLAY, sinon xcb."""
    platform = os.environ.get("QT_QPA_PLATFORM") or (
        "wayland" if os.environ.get("WAYLAND_DISPLAY") else "xcb"
    )
    needed = ["xkbfile"]
    if platform.startswith("xcb"):
        needed.append("xcb-cursor")
    return all(ctypes.util.find_library(name) for name in needed)


def engine():
    """Le moteur que pywebview prendra : `"cocoa"` sous macOS, sinon
    `"gtk"` (PyGObject, GTK 3 et WebKit2 4.1 ou 4.0) puis `"qt"` (QtPy, un
    QtWebEngine et ses bibliothèques système, `_qt_libraries`), dans
    l'ordre où pywebview les essaie sous Linux ; None sans pywebview ou
    sans moteur. Rien de graphique ne se charge : un moteur qui échoue
    malgré tout fait lever `open_window` (`kind="engine"`)."""
    if _webview() is None:
        return None
    if sys.platform == "darwin":
        return "cocoa"
    try:
        import gi
    except Exception:
        gi = None
    if gi is not None:
        for version in ("4.1", "4.0"):
            try:
                gi.require_version("Gtk", "3.0")
                gi.require_version("WebKit2", version)
            except ValueError:
                continue
            return "gtk"
    if (
        _found("qtpy")
        and any(
            _found(f"{binding}.QtWebEngineWidgets") for binding in QT_BINDINGS
        )
        and _qt_libraries()
    ):
        return "qt"
    return None


def available() -> bool:
    """Vrai si pywebview et un moteur web sont installés (`engine`)."""
    return engine() is not None


def has_display() -> bool:
    """Vrai sous macOS, ou avec DISPLAY ou WAYLAND_DISPLAY."""
    return sys.platform == "darwin" or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )


def install_hint(root=ROOT) -> list:
    """Commandes à taper pour que la fenêtre s'ouvre, une par ligne : pip
    dans le venv d'outillage de `root`, puis, quand la famille de la
    distribution est connue, les bibliothèques que QtWebEngine charge.
    Rien ne s'exécute ici."""
    package = PYWEBVIEW_MACOS if sys.platform == "darwin" else PYWEBVIEW
    pip = [launcher.venv_python(root), "-m", "pip", "install", package]
    lines = [shlex.join(pip)]
    system = todo_install.install_command(QT_LIBRARIES)
    if system:
        lines.append(shlex.join(system))
    return lines


def _clean(text, limit) -> str:
    """`text` en une ligne d'au plus `limit` caractères : chaque caractère
    de contrôle ou de format (retour à la ligne, échappement, inversion du
    sens d'écriture) devient une espace, et les espaces se resserrent."""
    kept = "".join(
        " " if unicodedata.category(char).startswith("C") else char
        for char in str(text)
    )
    return " ".join(kept.split())[:limit]


def send_notification(title, body) -> bool:
    """Notification de bureau par notify-send, lancé avec une liste
    d'arguments, jamais par un shell ; `--` clôt ses options, si bien qu'un
    titre qui commence par « - » reste un titre. Le corps, que le serveur de
    notifications lit comme du balisage, a `&`, `<` et `>` échappés. Faux,
    sans rien lever, si notify-send manque, échoue ou dépasse
    NOTIFY_TIMEOUT s."""
    program = shutil.which("notify-send")
    if program is None:
        return False
    argv = [
        program,
        f"--app-name={TITLE}",
        "--",
        _clean(title, TITLE_MAX) or TITLE,
        html.escape(_clean(body, BODY_MAX), quote=False),
    ]
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=NOTIFY_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def bridge(window, origin, secret):
    """Les trois fonctions que la page de `window` atteint, `set_title`,
    `notify` et `pick_path`, à passer à `window.expose` : pywebview ne les
    trouve que par leur nom exact. Un `js_api` n'est jamais donné, car
    pywebview y suit tout chemin pointé que la page envoie, `_privé` et
    `__dunder__` compris.

    Le canal qui les porte reste ouvert à tout document de la fenêtre dès
    son premier script, chargement en cours compris. Chaque appel porte
    donc d'abord un jeton, que `hmac.compare_digest` compare à `secret`,
    non vide : `open_window` le tire pour cette fenêtre seule et le met
    dans le fragment du lien, d'où la page du hub le garde dans le
    sessionStorage de son origine, qu'aucune autre origine ne lit. Un appel
    sans ce jeton est refusé sans rien toucher.

    En défense de plus, un appel n'agit que si la fenêtre montre une page
    de `origin` (`http://127.0.0.1:P`), lue sans attendre : `load_url`
    baisse `events.loaded` avant que le moteur ne change de page, et
    `get_current_url` attendrait qu'il se relève, puis rendrait l'URL de la
    page suivante. Un appel reçu drapeau baissé est donc refusé, comme
    celui dont la lecture l'a vu retomber. Le drapeau `hub` suit le
    chargement : `events.before_load` le baisse (au chargement fini, avant
    que pywebview n'injecte son API) ; au signal `events.loaded`, un fil
    démon lit l'URL courante — une page du hub reçoit le dernier titre
    accepté, puis relève `hub` ; toute autre page, un lien suivi par
    exemple, est remplacée par `origin + "/"`, que le cookie de session
    garde connectée. Si ce fil échoue, fenêtre fermée pendant la lecture
    par exemple, `hub` reste baissé et le type de l'exception va sur la
    sortie d'erreur, le journal de la fenêtre. Un titre n'est gardé que
    d'un appel accepté."""
    if not secret:
        raise ValueError("the bridge needs a secret")
    expected = secret.encode()
    state = {
        "hub": False,
        "title": TITLE,
        "notified": None,
        "picking": False,
        "loads": 0,
    }
    lock = threading.Lock()
    loaded = window.events.loaded

    def on_hub(url):
        return url == origin or url.startswith(origin + "/")

    def accepted(token):
        """Vrai si `token` est celui de la fenêtre et si une page du hub y
        est chargée à l'instant de l'appel ; jamais d'attente."""
        if not isinstance(token, str):
            return False
        given = token.encode("utf-8", "surrogatepass")
        if not hmac.compare_digest(given, expected):
            return False
        if not loaded.is_set():
            return False
        try:
            url = window.get_current_url() or ""
        except Exception:
            return False
        return loaded.is_set() and on_hub(url)

    def on_before_load():
        with lock:
            state.update(hub=False, title=TITLE, loads=state["loads"] + 1)

    def check():
        try:
            if not on_hub(window.get_current_url() or ""):
                window.load_url(origin + "/")
                return
            with lock:
                window.set_title(state["title"])
                state["hub"] = True
        except Exception as exc:
            print(
                f"desktop window: page check failed: {type(exc).__name__}",
                file=sys.stderr,
            )

    def on_loaded():
        threading.Thread(target=check, daemon=True).start()

    window.events.before_load += on_before_load
    window.events.loaded += on_loaded

    def set_title(token, text):
        """Titre de la fenêtre, en une ligne ; vide, TITLE."""
        cleaned = _clean(text, TITLE_MAX) or TITLE
        if not accepted(token):
            return
        with lock:
            state["title"] = cleaned
            if state["hub"]:
                window.set_title(cleaned)

    def notify(token, title, body):
        """Notification de bureau (`send_notification`) ; rend si elle est
        partie."""
        if not accepted(token):
            return False
        with lock:
            now = time.monotonic()
            last = state["notified"]
            if not state["hub"] or (
                last is not None and now - last < NOTIFY_INTERVAL
            ):
                return False
            state["notified"] = now
        return send_notification(title, body)

    def pick_path(token, start, directory):
        """Le dialogue de fichiers du système, ouvert sur le répertoire
        `start` : un fichier à ouvrir, ou un répertoire quand `directory`
        est vrai (`OPEN_DIALOG`, `FOLDER_DIALOG` de pywebview). Rend le
        chemin choisi, ou None : renoncé, refusé, ou un dialogue déjà
        ouvert, la page n'en ouvrant qu'un à la fois. Le dialogue, modal,
        peut rester ouvert longtemps : le chemin n'est rendu que si la page
        qui l'a demandé est encore là quand il se ferme, aucun chargement
        fini entre-temps (`loads`, que `before_load` compte) et une page du
        hub encore montrée (`accepted`). Un dialogue qui lève rend None, et
        le type de l'exception va au journal de la fenêtre."""
        if not accepted(token):
            return None
        with lock:
            if not state["hub"] or state["picking"]:
                return None
            state["picking"] = True
            load = state["loads"]
        try:
            webview = _webview()
            if directory is True:
                kind = webview.FOLDER_DIALOG
            else:
                kind = webview.OPEN_DIALOG
            folder = start if isinstance(start, str) else ""
            chosen = window.create_file_dialog(kind, directory=folder)
        except Exception as exc:
            print(
                f"desktop window: file dialog failed: {type(exc).__name__}",
                file=sys.stderr,
            )
            return None
        finally:
            with lock:
                state["picking"] = False
                still = state["hub"] and state["loads"] == load
        if not still or not accepted(token):
            return None
        if isinstance(chosen, str):
            return chosen
        if chosen and isinstance(chosen[0], str):
            return chosen[0]
        return None

    return set_title, notify, pick_path


def open_window(root, view="telemetry", lang=None) -> int:
    """Ouvre la page `view` du hub de `root` dans une fenêtre native, et
    rend 0 quand elle se ferme. S'appelle depuis le fil principal, comme
    pywebview et GTK l'exigent.

    Le hub est démarré ou réutilisé ; le lien
    `http://127.0.0.1:P/#login=<code>&view=<view>[&lang=<lang>]&bridge=<jeton>`
    porte dans son fragment un code neuf et le jeton du pont, tiré ici pour
    cette fenêtre (`bridge`), et ne quitte pas ce processus. pywebview
    choisit son moteur, en mode privé (aucun cookie gardé d'une fenêtre à
    l'autre), ses données sous `paths.data_dir(root)/desktop` (0700). La
    page n'atteint que les trois fonctions de `bridge`. Fermer la fenêtre
    n'envoie rien au hub.

    `ValueError` pour une vue ou une langue invalide. `LaunchError` sous
    root (`kind="root"`), avant tout fichier ; sans affichage
    (`"display"`) ; sans pywebview (`"missing"`, `pkg="pywebview"`) ;
    quand le hub ne démarre pas (celles de `ensure_running`, dont
    `"missing"` avec `pkg="tornado"`) ; quand pywebview ne charge aucun
    moteur ou échoue à démarrer (`"engine"`).
    """
    if not re.fullmatch(r"[a-z]+", view):
        raise ValueError(f"invalid view: {view!r}")
    if lang is not None and lang not in todo_i18n.LANGUAGES:
        raise ValueError(f"unknown language: {lang!r}")
    if os.geteuid() == 0:
        raise launcher.LaunchError(
            "the desktop window refuses to run as root", kind="root"
        )
    if not has_display():
        raise launcher.LaunchError("no display on this host", kind="display")
    webview = _webview()
    if webview is None:
        raise launcher.LaunchError(
            "pywebview is not installed", kind="missing", pkg="pywebview"
        )
    if engine() is None:
        raise launcher.LaunchError(
            "pywebview finds no web engine", kind="engine"
        )
    info = launcher.ensure_running(root)
    origin = f"http://127.0.0.1:{info['port']}"
    fragment = {"login": launcher.mint_code(root), "view": view}
    if lang:
        fragment["lang"] = lang
    secret = secrets.token_urlsafe(32)
    fragment["bridge"] = secret
    window = webview.create_window(
        TITLE, f"{origin}/#{urlencode(fragment)}", width=WIDTH, height=HEIGHT
    )
    window.expose(*bridge(window, origin, secret))
    storage = paths.private_dir(paths.data_dir(root) / "desktop")
    try:
        webview.start(private_mode=True, storage_path=str(storage))
    except Exception as exc:
        raise launcher.LaunchError(
            f"pywebview did not start: {type(exc).__name__}: {exc}",
            kind="engine",
        ) from exc
    return 0


def log_path(root) -> Path:
    """Journal des fenêtres que lance `spawn`."""
    return paths.data_dir(root) / "desktop.log"


def log_tail(root) -> list:
    """Les LOG_TAIL dernières lignes de `log_path`, sans les lignes vides
    qui le terminent ; vide s'il ne se lit pas."""
    try:
        text = log_path(root).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.rstrip().splitlines()[-LOG_TAIL:]


def spawn(root, view="telemetry", lang=None) -> subprocess.Popen:
    """Lance `open_window` dans un processus détaché, et le rend.

    L'argv est fixe, le python du venv et `-m script.todo.web.desktop open
    --view <view>`, et ne porte aucun code : le processus émet le sien. La
    langue passe par TODO_LANG. Nouvelle session, stdin sur /dev/null,
    sorties dans `log_path` (0600, vidé à chaque lancement) : Ctrl+C dans
    le terminal de TODO n'atteint pas la fenêtre, qui survit à TODO. Un
    fil démon attend sa fin : une fenêtre fermée ne reste pas zombie, et
    `returncode` se remplit sans autre appel. `ValueError` pour une vue ou
    une langue invalide ; `LaunchError` sous root, avant tout fichier ;
    `OSError` si le journal ou le python ne s'ouvrent pas.
    """
    if not re.fullmatch(r"[a-z]+", view):
        raise ValueError(f"invalid view: {view!r}")
    if lang is not None and lang not in todo_i18n.LANGUAGES:
        raise ValueError(f"unknown language: {lang!r}")
    if os.geteuid() == 0:
        raise launcher.LaunchError(
            "the desktop window refuses to run as root", kind="root"
        )
    root = os.path.realpath(root)
    env = {k: v for k, v in os.environ.items() if k != "TODO_LANG"}
    if lang:
        env["TODO_LANG"] = lang
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_TRUNC
    fd = os.open(log_path(root), flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        proc = subprocess.Popen(
            [launcher.venv_python(root), "-m", "script.todo.web.desktop"]
            + ["open", "--view", view],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=fd,
            stderr=fd,
            start_new_session=True,
        )
    finally:
        os.close(fd)
    threading.Thread(target=proc.wait, daemon=True).start()
    return proc


def entry_path(root) -> Path:
    """`applications/erplibre-todo-<empreinte>.desktop` sous
    XDG_DATA_HOME, s'il est absolu, sinon sous `~/.local/share`."""
    data = os.environ.get("XDG_DATA_HOME", "")
    if not os.path.isabs(data):
        data = Path.home() / ".local" / "share"
    name = f"erplibre-todo-{paths.checkout_id(root)}.desktop"
    return Path(data, "applications", name)


def _exec_arg(arg) -> str:
    """`arg` tel que la clé Exec le lit : « % » doublé ; cité s'il porte un
    caractère réservé, « " », « ` », « $ » et « \\ » échappés dans la
    citation ; puis chaque « \\ » doublé, l'échappement de toute valeur
    du fichier."""
    arg = arg.replace("%", "%%")
    if EXEC_RESERVED.intersection(arg):
        arg = '"' + re.sub(r'(["`$\\])', r"\\\1", arg) + '"'
    return arg.replace("\\", "\\\\")


def install_entry(root=ROOT) -> Path:
    """Écrit l'entrée du menu des applications qui ouvre la fenêtre de
    `root`, et rend son chemin (`entry_path`).

    Le fichier, 0600, remplacé d'un coup, lance le python du venv par son
    chemin absolu, `-m script.todo.web.desktop open`, depuis la racine
    (`Path=`), sous le nom ERPLibre TODO ; `Comment=` nomme le checkout,
    quand plusieurs ont leur entrée, et `TryExec=` retire l'entrée du menu
    quand ce python n'existe plus. Puis `update-desktop-database`, s'il
    existe, relit le répertoire ; son échec ne change rien. `ValueError`
    pour un chemin non imprimable (un retour à la ligne y écrirait une
    autre clé) ; `LaunchError` sous root, avant tout fichier.
    """
    if os.geteuid() == 0:
        raise launcher.LaunchError(
            "refusing to install the desktop entry as root", kind="root"
        )
    root = os.path.realpath(root)
    python = launcher.venv_python(root)
    if not (root.isprintable() and python.isprintable()):
        raise ValueError(f"unprintable path: {root!r}")
    argv = [python, "-m", "script.todo.web.desktop", "open"]
    folder = root.replace("\\", "\\\\")
    text = "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={TITLE}",
            f"Comment={folder}",
            "TryExec=" + python.replace("\\", "\\\\"),
            "Exec=" + " ".join(_exec_arg(arg) for arg in argv),
            f"Path={folder}",
            f"Icon={ICON}",
            "Terminal=false",
            "Categories=Development;",
            "",
        ]
    )
    path = entry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    paths.write_private(path, text)
    program = shutil.which("update-desktop-database")
    if program:
        try:
            subprocess.run(
                [program, str(path.parent)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    return path


def _falls_back(exc) -> bool:
    """Vrai pour un `LaunchError` après lequel `main` ouvre le navigateur :
    aucun affichage, aucun moteur, ou pywebview absent. Un hub qui ne
    démarre pas, faute de tornado aussi, ne s'ouvrirait pas mieux dans le
    navigateur."""
    if exc.kind in ("display", "engine"):
        return True
    return exc.kind == "missing" and exc.pkg == "pywebview"


def _browser(root, view, lang) -> int:
    """La page dans le navigateur (`launcher.open_page`), le repli de
    `main`. Le lien de connexion, et le tunnel sans affichage, ne
    s'impriment que sur un terminal : lancée par le menu ou par le bureau,
    la sortie de ce processus va dans un journal."""
    try:
        page = launcher.open_page(root, view=view, lang=lang)
    except launcher.LaunchError as exc:
        print(exc.message, file=sys.stderr)
        if exc.log_tail:
            print(exc.log_tail, file=sys.stderr)
        return 1
    print(f"url: {page.url}")
    if sys.stdout.isatty():
        if page.headless:
            port = urlsplit(page.url).port
            print(f"tunnel: ssh -L {port}:127.0.0.1:{port} <this host>")
        print(f"link: {page.link}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m script.todo.web.desktop",
        description="Open the TODO web interface in a desktop window.",
    )
    parser.add_argument("action", choices=("open", "install"))
    parser.add_argument("--view", default="telemetry")
    parser.add_argument("--root", default=str(ROOT), help="ERPLibre checkout")
    args = parser.parse_args(argv)
    if args.action == "install":
        try:
            print(f"desktop entry: {install_entry(args.root)}")
        except (ValueError, launcher.LaunchError, OSError) as exc:
            print(getattr(exc, "message", exc), file=sys.stderr)
            return 1
        return 0
    if os.environ.get("TODO_LANG") in todo_i18n.LANGUAGES:
        todo_i18n.use_lang(os.environ["TODO_LANG"])
    lang = todo_i18n.get_lang()
    try:
        return open_window(args.root, args.view, lang)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    except launcher.LaunchError as exc:
        print(exc.message, file=sys.stderr)
        if exc.log_tail:
            print(exc.log_tail, file=sys.stderr)
        if not _falls_back(exc):
            return 1
        if exc.kind != "display":
            print("install it with:", file=sys.stderr)
            for line in install_hint(args.root):
                print(f"  {line}", file=sys.stderr)
    print("opening the page in the browser instead", file=sys.stderr)
    return _browser(args.root, args.view, lang)


if __name__ == "__main__":
    sys.exit(main())
