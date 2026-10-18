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
import stat
import subprocess

UNIT_NAME = "erplibre-home-streamdeck.service"
PROGRAMS = ("tiler", "controller", "none")
GAMES_VALUES = ("on", "off")
DEFAULTS = {
    "DECK_PROGRAM": "tiler",
    "RESTART_AFTER_GAME": "yes",
    "GAMES": "on",
    "DECK_PLUGINS_OFF": "",
}


def games_enabled(settings):
    """Vrai quand les réglages lus par read_settings activent les jeux :
    GAMES vaut « on », ou manque (DEFAULTS). « off » et toute autre valeur
    les coupent, comme deck_games_enabled du shell."""
    return settings.get("GAMES", DEFAULTS["GAMES"]) == "on"


def plugins_off(settings):
    """Les identifiants que DECK_PLUGINS_OFF coupe, comme deck_plugins_off
    du shell : valeur coupée aux virgules, tous les blancs retirés, morceau
    vide ignoré."""
    morceaux = (
        "".join(part.split())
        for part in settings.get("DECK_PLUGINS_OFF", "").split(",")
    )
    return [part for part in morceaux if part]


def deck_plugin_ids(repo_root, environ=None):
    """Les identifiants des plugins du deck présents sur disque, triés et
    sans doublon : ceux du dépôt et ceux de l'utilisateur. Les fichiers
    « _* » sont ignorés, et rien n'est importé : l'import demande le venv
    Stream Deck."""
    dossiers = (
        os.path.join(
            repo_root,
            "script",
            "stream_deck",
            "erplibre_streamdeck",
            "plugins",
        ),
        os.path.join(config_home(environ), "erplibre-home", "deck-plugins"),
    )
    ids = set()
    for dossier in dossiers:
        try:
            noms = os.listdir(dossier)
        except OSError:
            continue
        for nom in noms:
            if nom.endswith(".py") and not nom.startswith("_"):
                ids.add(nom[:-3])
    return sorted(ids)


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
    DEFAULTS. Une ligne sans « = » est ignorée. Les lignes se coupent sur
    « \\n » seul, comme la lecture du shell. Un octet hors UTF-8 devient
    U+FFFD : une clé ou une valeur ASCII se lit comme dans le shell, qui
    compare des octets, et une valeur qui en porte reste affichable et
    hors PROGRAMS."""
    settings = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            lignes = fh.read().split("\n")
    except OSError:
        return settings
    for ligne in lignes:
        cle, egal, valeur = ligne.partition("=")
        if egal and cle and not cle.startswith("#"):
            settings[cle] = valeur
    return settings


def settings_text(current, updates):
    """Le texte `current` avec chaque clé de `updates` posée : la ligne de
    la clé remplacée sur place, une clé absente ajoutée à la fin, toute
    autre ligne gardée dans son ordre. Rend un texte fini par « \\n ».
    Les lignes se coupent sur « \\n » seul, comme settings_content de
    l'installateur : un « \\r » ou tout autre séparateur Unicode reste
    dans sa ligne, et une dernière ligne sans « \\n » compte."""
    vues = set()
    lignes = []
    morceaux = current.split("\n")
    if morceaux[-1] == "":
        morceaux.pop()
    for ligne in morceaux:
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
    N'écrit que si le texte change ; rend vrai quand il a écrit. Le
    fichier se lit et s'écrit sans traduction des fins de ligne, et sous
    « surrogateescape » : un octet hors UTF-8 se relit en substitut et se
    réécrit en lui-même, si bien que seules les lignes des clés posées
    changent, octet pour octet, comme avec settings_content."""
    try:
        with open(
            path, encoding="utf-8", errors="surrogateescape", newline=""
        ) as fh:
            avant = fh.read()
    except FileNotFoundError:
        avant = ""
    apres = settings_text(avant, updates)
    if apres == avant:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporaire = path + ".tmp"
    with open(
        temporaire,
        "w",
        encoding="utf-8",
        errors="surrogateescape",
        newline="",
    ) as fh:
        fh.write(apres)
    os.replace(temporaire, path)
    return True


def user_bus_env(environ=None, runtime_root="/run/user", uid=None):
    """Les variables du bus utilisateur qui manquent à `environ`, prises
    sous <runtime_root>/<uid> comme le fait l'installateur : rend
    XDG_RUNTIME_DIR quand il manque et que ce répertoire existe,
    DBUS_SESSION_BUS_ADDRESS quand il manque et que son socket « bus »
    existe. Sous su ou sudo -u, ces deux variables manquent, et
    systemctl --user ne trouve alors pas le gestionnaire du compte. Une
    variable déjà posée, même ailleurs, est gardée ; rend {} quand rien ne
    manque ou que rien n'existe. `uid` None prend celui du processus."""
    environ = os.environ if environ is None else environ
    uid = os.getuid() if uid is None else uid
    runtime = os.path.join(runtime_root, str(uid))
    ajouts = {}
    if not environ.get("XDG_RUNTIME_DIR") and os.path.isdir(runtime):
        ajouts["XDG_RUNTIME_DIR"] = runtime
    bus = os.path.join(runtime, "bus")
    try:
        socket_bus = stat.S_ISSOCK(os.stat(bus).st_mode)
    except OSError:
        socket_bus = False
    if not environ.get("DBUS_SESSION_BUS_ADDRESS") and socket_bus:
        ajouts["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + bus
    return ajouts


def run_command(argv, timeout=20):
    """(code, sortie standard) de `argv`, lancé sans shell, dans
    l'environnement du processus complété par user_bus_env. Une commande
    absente ou qui dépasse `timeout` secondes rend (None, "")."""
    env = dict(os.environ)
    env.update(user_bus_env(env))
    try:
        fini = subprocess.run(
            list(argv),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return fini.returncode, fini.stdout
