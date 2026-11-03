#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le journal de session du TODO : ce que le terminal montre, gardé.

Chaque lancement ouvre un fichier neuf sous
`$XDG_STATE_HOME/erplibre/todo/` (`~/.local/state/erplibre/todo/` par
défaut), commun à tous les checkouts du compte : son en-tête nomme le
checkout. Il reçoit les messages des loggers et, pour chaque commande que
lance `Execute.exec_command_live`, la commande, sa sortie et son code de
retour, caviardés comme à l'écran. Les réponses tapées au clavier n'y passent
pas : ni `input()` ni `getpass` n'écrivent ce qu'on y saisit.

Le fichier est créé en 0600, le dossier en 0700 : une sortie de commande peut
nommer des bases et des hôtes. Les `GARDER` journaux les plus récents restent,
les plus anciens sont effacés à l'ouverture. `ERPLIBRE_TODO_LOG=0` n'ouvre
rien. Aucune erreur d'ici n'empêche le TODO de démarrer : sans journal, il
tourne comme avant.
"""

import datetime
import logging
import os

from script.execute import execute

GARDER = 30
PREFIXE = "todo_"
SUFFIXE = ".log"
FORMAT = (
    "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
    " %(message)s"
)

_ouvert = {"fichier": None, "handler": None}


def dossier_journaux(environ=None):
    """Le dossier des journaux du TODO, sans le créer."""
    environ = os.environ if environ is None else environ
    base = environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(base, "erplibre", "todo")


def elaguer(dossier, garder=GARDER):
    """Efface les journaux du TODO au-delà des `garder` plus récents.

    Seuls les fichiers todo_*.log du dossier sont comptés et touchés ; un
    fichier qui disparaît ou résiste est laissé de côté.
    """
    journaux = []
    for nom in os.listdir(dossier):
        if nom.startswith(PREFIXE) and nom.endswith(SUFFIXE):
            chemin = os.path.join(dossier, nom)
            try:
                journaux.append((os.path.getmtime(chemin), chemin))
            except OSError:
                continue
    journaux.sort(reverse=True)
    for _date, chemin in journaux[garder:]:
        try:
            os.remove(chemin)
        except OSError:
            pass


def ouvrir(environ=None, maintenant=None, garder=GARDER):
    """Ouvre le journal de la session ; rend son chemin, ou None.

    None quand ERPLIBRE_TODO_LOG vaut 0, ou que le fichier ne peut pas être
    créé : le TODO démarre alors sans journal, avec un avertissement.
    """
    environ = os.environ if environ is None else environ
    if environ.get("ERPLIBRE_TODO_LOG", "").strip() == "0":
        return None
    maintenant = maintenant or datetime.datetime.now()
    dossier = dossier_journaux(environ)
    nom = f"{PREFIXE}{maintenant:%Y-%m-%d_%Hh%Mm%Ss}_{os.getpid()}{SUFFIXE}"
    chemin = os.path.join(dossier, nom)
    try:
        os.makedirs(dossier, mode=0o700, exist_ok=True)
        descripteur = os.open(
            chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        # Tampon par ligne : un TODO tué garde ce qu'il a déjà écrit.
        fichier = os.fdopen(descripteur, "w", encoding="utf-8", buffering=1)
    except OSError as e:
        print(f"⚠️ Journal de session non ouvert ({e}).")
        return None
    fichier.write(
        f"# TODO ERPLibre, {maintenant:%Y-%m-%d %H:%M:%S},"
        f" checkout {os.getcwd()}, pid {os.getpid()}\n"
    )
    handler = logging.StreamHandler(fichier)
    handler.setFormatter(logging.Formatter(FORMAT, "%Y-%m-%d:%H:%M:%S"))
    logging.getLogger().addHandler(handler)
    execute.set_session_journal(fichier)
    _ouvert.update(fichier=fichier, handler=handler)
    try:
        elaguer(dossier, garder)
    except OSError:
        pass
    return chemin


def noter_exception():
    """Écrit au journal le traceback de l'exception en cours de traitement."""
    import traceback

    execute._journaliser(traceback.format_exc())


def fermer():
    """Ferme le journal ouvert par ouvrir() ; sans effet sinon."""
    execute.set_session_journal(None)
    if _ouvert["handler"] is not None:
        logging.getLogger().removeHandler(_ouvert["handler"])
    if _ouvert["fichier"] is not None:
        try:
            _ouvert["fichier"].close()
        except OSError:
            pass
    _ouvert.update(fichier=None, handler=None)
