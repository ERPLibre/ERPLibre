#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le journal de session du TODO : ce que le terminal montre, gardé.

Chaque lancement ouvre un fichier neuf sous
`$XDG_STATE_HOME/erplibre/todo/` (`~/.local/state/erplibre/todo/` par
défaut), commun à tous les checkouts du compte : son en-tête nomme le
checkout. Il reçoit les messages des loggers et, pour chaque commande que
lance `Execute.exec_command_live`, la commande, sa sortie et son code de
retour. Tout y passe par `redact_secrets`, messages et traceback compris.
Les réponses tapées au clavier n'y passent pas : ni `input()` ni `getpass`
n'écrivent ce qu'on y saisit.

Le masquage est un dernier rempart : un secret imprimé sous une forme qu'il
ne connaît pas passe. Le fichier est donc créé en 0600, le dossier en 0700,
d'autant qu'une sortie de commande peut nommer des bases et des hôtes. Les `GARDER` journaux les plus récents restent,
les plus anciens sont effacés à l'ouverture. `ERPLIBRE_TODO_LOG=0` n'ouvre
rien. Aucune erreur d'ici n'empêche le TODO de démarrer : sans journal, il
tourne comme avant.
"""

import datetime
import logging
import os
import re

from script.execute import execute

GARDER = 30
PREFIXE = "todo_"
SUFFIXE = ".log"
FORMAT = (
    "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
    " %(message)s"
)

_ouvert = {"fichier": None, "handler": None}


class FormatCaviarde(logging.Formatter):
    """Le format du journal, passé par redact_secrets.

    Les loggers du processus écrivent ce qu'on leur donne, une commande
    entière comprise : sans ce filtre, ils seraient la seule voie vers le
    journal à ne rien masquer. La ligne finale est filtrée, traceback compris.
    """

    def format(self, record):
        return execute.redact_secrets(super().format(record))


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
    handler.setFormatter(FormatCaviarde(FORMAT, "%Y-%m-%d:%H:%M:%S"))
    logging.getLogger().addHandler(handler)
    execute.set_session_journal(fichier)
    _ouvert.update(fichier=fichier, handler=handler)
    try:
        elaguer(dossier, garder)
    except OSError:
        pass
    return chemin


# Des secrets que redact_secrets ne masque pas, reconnaissables à leur seule
# forme : la détection les signale pour qu'on les traite, sans les réécrire.
SUSPECTS = (
    ("AWS access key", re.compile(r"\bA(?:KIA|SIA)[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[0-9A-Za-z-]{10,}")),
    ("API key sk-", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("Stripe key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{16,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("JWT", re.compile(r"\beyJ[\w-]{8,}\.eyJ[\w-]{8,}\.[\w-]{8,}")),
)


def secrets_suspects(lignes):
    """[(numéro, nature)] des lignes qui portent probablement un secret.

    Deux familles : une forme que redact_secrets SAIT masquer mais qui est
    restée en clair — un journal écrit avant que la forme soit connue — et
    une forme de jeton qu'il ne masque pas. Seule la nature est rendue,
    jamais la valeur : le rapport qui la cite ne doit pas la recopier.
    """
    trouvees = []
    for numero, ligne in enumerate(lignes, 1):
        if execute.redact_secrets(ligne) != ligne:
            trouvees.append((numero, "unmasked known form"))
            continue
        for nature, motif in SUSPECTS:
            if motif.search(ligne):
                trouvees.append((numero, nature))
                break
    return trouvees


def analyser(chemin):
    """secrets_suspects() d'un fichier de journal, [] s'il est illisible."""
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fichier:
            return secrets_suspects(fichier)
    except OSError:
        return []


def noter_exception():
    """Écrit au journal le traceback de l'exception en cours de traitement."""
    import traceback

    execute._journaliser(traceback.format_exc(), deja_caviarde=False)


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
