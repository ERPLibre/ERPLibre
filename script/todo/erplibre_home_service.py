#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le service Stream Deck d'ERPLibre Home, vu de TODO : noms, chemins,
réglages, et l'appel d'une commande.

Les mêmes règles que script/install/erplibre_home_settings.sh, que lisent
l'installateur, le point d'entrée du service et l'outil de passation :
lignes « CLÉ=valeur », jamais sourcées, la dernière ligne d'une clé
l'emporte, $XDG_CONFIG_HOME prime sur ~/.config. Les fonctions prennent
`environ` pour que les tests désignent un HOME jetable.
"""

import os
import subprocess

UNIT_NAME = "erplibre-home-streamdeck.service"
PROGRAMS = ("tiler", "controller", "none")
DEFAULTS = {"DECK_PROGRAM": "tiler", "RESTART_AFTER_GAME": "yes"}


def config_home(environ=None):
    """$XDG_CONFIG_HOME, ou ~/.config quand il est vide ou absent."""
    environ = os.environ if environ is None else environ
    return environ.get("XDG_CONFIG_HOME") or os.path.join(
        environ.get("HOME", ""), ".config"
    )


def settings_path(environ=None):
    return os.path.join(
        config_home(environ), "erplibre-home", "streamdeck.conf"
    )


def unit_path(environ=None):
    return os.path.join(config_home(environ), "systemd", "user", UNIT_NAME)


def read_settings(path):
    """DEFAULTS, puis chaque ligne « CLÉ=valeur » de `path` ; la dernière
    ligne d'une clé l'emporte. Un fichier absent ou illisible rend
    DEFAULTS. Une ligne sans « = » est ignorée."""
    settings = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            lignes = fh.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return settings
    for ligne in lignes:
        cle, egal, valeur = ligne.partition("=")
        if egal and cle and not cle.startswith("#"):
            settings[cle] = valeur
    return settings


def settings_text(current, updates):
    """Le texte `current` avec chaque clé de `updates` posée : la ligne de
    la clé remplacée sur place, une clé absente ajoutée à la fin, toute
    autre ligne gardée dans son ordre. Rend un texte fini par « \\n »."""
    vues = set()
    lignes = []
    for ligne in current.splitlines():
        cle = ligne.partition("=")[0]
        if "=" in ligne and cle in updates:
            ligne = "%s=%s" % (cle, updates[cle])
            vues.add(cle)
        lignes.append(ligne)
    for cle, valeur in updates.items():
        if cle not in vues:
            lignes.append("%s=%s" % (cle, valeur))
    return "".join(ligne + "\n" for ligne in lignes)


def write_settings(path, updates):
    """Pose `updates` dans le fichier de réglages `path`, créé au besoin.
    N'écrit que si le texte change ; rend vrai quand il a écrit."""
    try:
        with open(path, encoding="utf-8") as fh:
            avant = fh.read()
    except FileNotFoundError:
        avant = ""
    apres = settings_text(avant, updates)
    if apres == avant:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporaire = path + ".tmp"
    with open(temporaire, "w", encoding="utf-8") as fh:
        fh.write(apres)
    os.replace(temporaire, path)
    return True


def run_command(argv, timeout=20):
    """(code, sortie standard) de `argv`, lancé sans shell. Une commande
    absente ou qui dépasse `timeout` secondes rend (None, "")."""
    try:
        fini = subprocess.run(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return fini.returncode, fini.stdout
