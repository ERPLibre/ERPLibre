#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fenêtre bureautique de TODO : le pont entre la page du hub web et la
fenêtre native pywebview qui la montre.

La page n'atteint que les deux fonctions de `bridge`, le titre de la
fenêtre et une notification de bureau, et seulement tant que la fenêtre
montre une page du hub.
"""

import html
import shutil
import subprocess
import threading
import time
import unicodedata

TITLE = "ERPLibre TODO"
# Longueurs gardées d'un titre et du corps d'une notification.
TITLE_MAX = 200
BODY_MAX = 300
NOTIFY_TIMEOUT = 5.0
# Secondes entre deux notifications de la page : un appel plus rapproché
# est ignoré, et la page ne lance jamais plus d'un notify-send par seconde.
NOTIFY_INTERVAL = 1.0


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


def bridge(window, origin):
    """Les deux fonctions que la page de `window` atteint, `set_title` et
    `notify`, à passer à `window.expose` : pywebview ne les trouve que par
    leur nom exact. Un `js_api` n'est jamais donné, car pywebview y suit
    tout chemin pointé que la page envoie, `_privé` et `__dunder__`
    compris.

    Elles n'agissent que tant que la fenêtre montre une page de `origin`
    (`http://127.0.0.1:P`). Le canal qui les porte à la page reste ouvert à
    tout document dès son premier script, chargement en cours compris :
    chaque appel relit donc `get_current_url` sur le fil qui l'a reçu, en
    plus du drapeau `hub`, avant d'agir. Ce drapeau suit le chargement de
    la page : `events.before_load` le baisse (au chargement fini, avant
    que pywebview n'injecte son API) ; puis un fil démon lit l'URL
    courante (`get_current_url`) au signal `events.loaded` — une page du
    hub le relève et applique le dernier titre demandé, toute autre page,
    un lien ou un fichier déposé par exemple, est remplacée par
    `origin + "/"`, que le cookie de session garde connectée. Une fenêtre
    fermée pendant la lecture ne retient pas ce fil, qui est démon."""
    state = {"hub": False, "title": TITLE, "notified": None}
    lock = threading.Lock()

    def on_origin():
        """Vrai si l'URL montrée à l'instant de l'appel est celle du hub,
        lue en direct : le drapeau `hub` seul retarde d'un chargement."""
        try:
            url = window.get_current_url() or ""
        except Exception:
            return False
        return url == origin or url.startswith(origin + "/")

    def on_before_load():
        with lock:
            state.update(hub=False, title=TITLE)

    def check():
        try:
            url = window.get_current_url() or ""
            if url != origin and not url.startswith(origin + "/"):
                window.load_url(origin + "/")
                return
            with lock:
                state["hub"] = True
                window.set_title(state["title"])
        except Exception:
            # La fenêtre s'est fermée pendant la lecture : plus rien à
            # garder.
            return

    def on_loaded():
        threading.Thread(target=check, daemon=True).start()

    window.events.before_load += on_before_load
    window.events.loaded += on_loaded

    def set_title(text):
        """Titre de la fenêtre, en une ligne ; vide, TITLE."""
        cleaned = _clean(text, TITLE_MAX) or TITLE
        reachable = on_origin()
        with lock:
            state["title"] = cleaned
            if state["hub"] and reachable:
                window.set_title(cleaned)

    def notify(title, body):
        """Notification de bureau (`send_notification`) ; rend si elle est
        partie."""
        if not on_origin():
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

    return set_title, notify
