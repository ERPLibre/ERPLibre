#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le journal de session du TODO : ce que le terminal montre, gardé.

Chaque lancement ouvre un fichier neuf sous
`$XDG_STATE_HOME/erplibre/todo/` (`~/.local/state/erplibre/todo/` par
défaut), commun à tous les checkouts du compte : son en-tête nomme le
checkout. Il reçoit ce que le TODO affiche (sys.stdout, voir Duplicateur),
les messages des loggers — DEBUG compris pour ceux du dépôt, que la console
ne montre pas — et, pour chaque commande que lance
`Execute.exec_command_live` ou `lancer_journalise`, la commande, sa sortie
et son code de retour ; pour `lancer_au_terminal`, la commande et son code,
la sortie restant au terminal. Tout y passe par `redact_secrets`, messages et
traceback compris. Les réponses tapées au clavier n'y passent pas : ni
`input()` ni `getpass` n'écrivent ce qu'on y saisit.

Le masquage est un dernier rempart : un secret imprimé sous une forme qu'il
ne connaît pas passe. Le fichier est donc créé en 0600, le dossier en 0700,
d'autant qu'une sortie de commande peut nommer des bases et des hôtes. Les
`GARDER` journaux les plus récents restent, les plus anciens sont effacés à
l'ouverture. `ERPLIBRE_TODO_LOG=0` n'ouvre rien. Aucune erreur d'ici
n'empêche le TODO de démarrer : sans journal, il tourne comme avant.
"""

import collections
import datetime
import logging
import os
import re
import subprocess
import sys

from script.execute import execute
from script.todo.todo_i18n import t

GARDER = 30
PREFIXE = "todo_"
SUFFIXE = ".log"
FORMAT = (
    "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
    " %(message)s"
)

_ouvert = {
    "chemin": None,
    "fichier": None,
    "handler": None,
    "stdout": None,
    "niveaux": [],
}

# Les séquences de contrôle d'un terminal : couleurs et curseur (CSI), titres
# (OSC), et les échappements d'un seul caractère. Le journal n'en garde que le
# texte.
RE_ANSI = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]"
)
# L'écran alternatif qu'ouvre une interface plein terminal (urwid) : ce qui
# s'y dessine est un redessin d'écran, pas un texte à garder.
RE_ECRAN_ALTERNE_DEBUT = re.compile(r"\x1b\[\?(?:1049|1047|47)h")
RE_ECRAN_ALTERNE_FIN = re.compile(r"\x1b\[\?(?:1049|1047|47)l")
# Une écriture d'au moins tant de lignes est un bloc, un menu le plus souvent :
# le même bloc réaffiché ne s'écrit qu'une fois parmi les derniers retenus.
LIGNES_BLOC = 3
BLOCS_RETENUS = 8
# Les loggers dont le DEBUG va au journal. Ceux des bibliothèques restent à
# INFO : leur DEBUG noierait le reste.
LOGGERS_DEBUG = ("script", "__main__")


class FormatCaviarde(logging.Formatter):
    """Le format du journal, passé par redact_secrets.

    Les loggers du processus écrivent ce qu'on leur donne, une commande
    entière comprise : sans ce filtre, ils seraient la seule voie vers le
    journal à ne rien masquer. La ligne finale est filtrée, traceback compris.
    """

    def format(self, record):
        return execute.redact_secrets(super().format(record))


class Duplicateur:
    """sys.stdout qui recopie au journal ce qu'il affiche.

    L'écran reçoit tout, inchangé. Le journal reçoit les lignes complètes,
    caviardées et sans séquences ANSI, sauf :

    - pendant exec_command_live, qui journalise déjà commande et sortie ;
    - pendant un écran alternatif (interface plein terminal) ;
    - un bloc identique à un bloc récent, remplacé par une mention.

    flush() pousse la ligne en cours : une invite sans saut de ligne, que
    click.prompt et input() vident avant de lire, arrive ainsi au journal
    avant ce qui suit. Ce qu'on tape n'est pas écrit par le programme, et
    n'y arrive donc pas. Tout autre attribut — fileno, isatty, encoding —
    est celui du vrai flux : input() y retrouve le terminal et l'édition de
    ligne.
    """

    def __init__(self, ecran, ecrire):
        self._ecran = ecran
        self._ecrire = ecrire
        self._ligne = ""
        self._plein_ecran = False
        self._blocs = collections.deque(maxlen=BLOCS_RETENUS)

    def write(self, texte):
        retour = self._ecran.write(texte)
        try:
            self._copier(texte)
        except Exception:
            # Le journal ne doit jamais faire échouer un affichage.
            pass
        return retour

    def flush(self):
        self._ecran.flush()
        try:
            self._vider()
        except Exception:
            pass

    def __getattr__(self, nom):
        return getattr(self._ecran, nom)

    def _copier(self, texte):
        if not isinstance(texte, str) or execute.commande_en_cours():
            return
        if self._plein_ecran:
            if RE_ECRAN_ALTERNE_FIN.search(texte):
                self._plein_ecran = False
            return
        if RE_ECRAN_ALTERNE_DEBUT.search(texte):
            self._vider()
            self._plein_ecran = not RE_ECRAN_ALTERNE_FIN.search(texte)
            self._ecrire(f"({t('full-screen display')})\n")
            return
        if texte.count("\n") >= LIGNES_BLOC:
            empreinte = hash(texte)
            if empreinte in self._blocs:
                self._vider()
                self._ecrire(f"({t('menu redisplayed')})\n")
                return
            self._blocs.append(empreinte)
        *completes, self._ligne = (self._ligne + texte).split("\n")
        for ligne in completes:
            self._ecrire_ligne(ligne)

    def _ecrire_ligne(self, ligne):
        ligne = RE_ANSI.sub("", ligne)
        # Une barre de progression réécrit sa ligne par « \r » : seul son
        # dernier état compte.
        ligne = ligne.rsplit("\r", 1)[-1]
        self._ecrire(execute.redact_secrets(ligne) + "\n")

    def _vider(self):
        if self._ligne.strip():
            self._ecrire_ligne(self._ligne)
        self._ligne = ""


class FiltreJournal(logging.Filter):
    """INFO et au-delà pour tous ; DEBUG pour les loggers du dépôt seuls."""

    def filter(self, record):
        if record.levelno >= logging.INFO:
            return True
        return record.name.startswith(LOGGERS_DEBUG)


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
    racine = logging.getLogger()
    # La console reste à INFO : le DEBUG des loggers du dépôt, ouvert
    # ci-dessous, ne doit atteindre que le journal.
    niveaux = []
    for existant in racine.handlers:
        if existant.level == logging.NOTSET:
            existant.setLevel(logging.INFO)
            niveaux.append((existant, logging.NOTSET))
    for nom in LOGGERS_DEBUG:
        logger = logging.getLogger(nom)
        niveaux.append((logger, logger.level))
        logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(fichier)
    handler.setLevel(logging.DEBUG)
    handler.addFilter(FiltreJournal())
    handler.setFormatter(FormatCaviarde(FORMAT, "%Y-%m-%d:%H:%M:%S"))
    racine.addHandler(handler)
    execute.set_session_journal(fichier)
    stdout = sys.stdout
    sys.stdout = Duplicateur(stdout, execute._journaliser)
    _ouvert.update(
        chemin=chemin,
        fichier=fichier,
        handler=handler,
        stdout=stdout,
        niveaux=niveaux,
    )
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


def session_en_cours():
    """{"nom", "affichage"} du journal ouvert par ce processus, ou None.

    « affichage » dit si sys.stdout passe encore par le Duplicateur : un
    code qui le remplace à son tour coupe la copie sans rien dire.
    """
    if _ouvert["fichier"] is None:
        return None
    return {
        "nom": os.path.basename(_ouvert["chemin"] or ""),
        "affichage": isinstance(sys.stdout, Duplicateur),
    }


def lancer_journalise(cmd, libelle=None, **kwargs):
    """Lance `cmd` sortie au terminal ET au journal ; rend son code.

    Pour un sous-processus qui ne passe pas par exec_command_live : lancé
    tel quel, il écrit sur le descripteur du terminal, que la copie de
    sys.stdout ne voit pas. Sa sortie passe ici par un tube, caviardée à
    l'écran comme au journal, au prix du terminal : un programme qui
    demande une saisie ou dessine l'écran se lance sans cette aide.

    `libelle` remplace la commande au journal quand elle porte un script
    entier, illisible sur une ligne.
    """
    affichee = execute.redact_secrets(libelle or " ".join(map(str, cmd)))
    heure = f"{datetime.datetime.now():%H:%M:%S}"
    execute._journaliser(f"\n[{heure}] $ {affichee}\n")
    try:
        processus = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            **kwargs,
        )
    except OSError as err:
        execute._journaliser(f"{err}\n[code 127]\n", deja_caviarde=False)
        print(err)
        return 127
    for ligne in processus.stdout:
        propre = execute.redact_secrets(ligne)
        ecran = _ouvert["stdout"] or sys.stdout
        ecran.write(propre)
        ecran.flush()
        execute._journaliser(propre)
    code = processus.wait()
    execute._journaliser(f"[code {code}]\n")
    return code


def lancer_au_terminal(cmd, **kwargs):
    """subprocess.run qui laisse le terminal au programme ; rend son résultat.

    Pour une commande qui a besoin du terminal — une invite, un mot de passe,
    un affichage plein écran, ssh avec tty — et que lancer_journalise ne
    peut donc pas faire passer par un tube. Sa sortie reste à l'écran,
    hors du journal ; la commande et son code de retour y vont. Mêmes
    arguments et mêmes exceptions que subprocess.run.
    """
    texte = cmd if isinstance(cmd, str) else " ".join(map(str, cmd))
    heure = f"{datetime.datetime.now():%H:%M:%S}"
    execute._journaliser(
        f"\n[{heure}] $ {execute.redact_secrets(texte)}"
        f"  ({t('output on the terminal')})\n"
    )
    try:
        fini = subprocess.run(cmd, **kwargs)
    except subprocess.CalledProcessError as err:
        execute._journaliser(f"[code {err.returncode}]\n")
        raise
    except (OSError, subprocess.SubprocessError) as err:
        execute._journaliser(f"{err}\n[code 127]\n", deja_caviarde=False)
        raise
    execute._journaliser(f"[code {fini.returncode}]\n")
    return fini


def fermer():
    """Ferme le journal ouvert par ouvrir() ; sans effet sinon."""
    execute.set_session_journal(None)
    if _ouvert["stdout"] is not None:
        if isinstance(sys.stdout, Duplicateur):
            sys.stdout.flush()
        sys.stdout = _ouvert["stdout"]
    for objet, niveau in _ouvert["niveaux"]:
        objet.setLevel(niveau)
    if _ouvert["handler"] is not None:
        logging.getLogger().removeHandler(_ouvert["handler"])
    if _ouvert["fichier"] is not None:
        try:
            _ouvert["fichier"].close()
        except OSError:
            pass
    _ouvert.update(
        chemin=None, fichier=None, handler=None, stdout=None, niveaux=[]
    )
