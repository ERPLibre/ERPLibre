#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'exécuteur des gestes du moteur : argv cité, environnement neuf, verdict lu.

Trois règles, et chacune répare une façon précise de se tromper.

**L'ENVIRONNEMENT EST CONSTRUIT À NEUF**, jamais hérité. Hérité, il porte
trois choses qui décident à la place de l'opérateur : un `CONFIRMER=true`
resté d'un geste précédent, que les applicateurs du moteur lisent pour écrire
au lieu de simuler ; les surcharges du make parent (`MAKEFLAGS`, `MAKELEVEL`),
puisque todo se lance lui-même par `make todo` ; et les `ANSIBLE_*` ou
`SETOPS_*` que le moteur laisse gagner sur ses propres défauts — dont celui
qui désigne la grappe sur laquelle un geste destructeur porterait.

**LA COMMANDE PORTE SON `CONFIRMER`**, en clair, sur la ligne qu'on affiche.
Une variable passée à `make` sur la ligne de commande arrive dans
l'environnement du script appelé ET l'emporte sur celle qui serait héritée :
la ligne montrée est donc la ligne qui décide, et un `CONFIRMER=false` visible
vaut mieux qu'une absence qu'il faut savoir interpréter.

**LE VERDICT SE LIT**, code ET sortie. Plusieurs gestes du moteur rendent 0 en
ayant trouvé un écart : le code seul ne suffit pas, et un appelant qui ne lit
rien annonce une réussite qui n'a pas eu lieu.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import shlex
import subprocess
from typing import NamedTuple

# Les seules variables qui traversent. Tout le reste est écarté, y compris
# ce qui semble inoffensif : une liste blanche se relit, une liste noire
# s'oublie. `SSH_AUTH_SOCK` est là parce que les gestes qui joignent une
# machine passent par l'agent ; `XDG_CONFIG_HOME` et `HOME` disent où le
# moteur cherche les clés de voûte.
ENV_TRANSMIS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_MESSAGES",
    "LOGNAME",
    "PATH",
    "SSH_AUTH_SOCK",
    "TERM",
    "USER",
    "XDG_CONFIG_HOME",
)

# Le venv d'ERPLibre n'a rien à faire dans le PATH d'un geste du moteur : il
# porte un autre Python et d'autres bibliothèques, et la garde du moteur
# interroge `python3` NU. Ses entrées sont retirées du PATH transmis.
VENV_ERPLIBRE = ".venv.erplibre"

# Le nom que les applicateurs du moteur lisent dans l'environnement. Rien
# d'autre que la chaîne « true » ne les fait écrire.
CONFIRMER = "CONFIRMER"
CONFIRME = "true"
SIMULE = "false"

# Borne d'un geste, en secondes. Un déploiement dure des minutes ; la borne
# existe pour qu'une machine qui ne répond plus rende la main.
DELAI = 3600


# OÙ LE VERROU DES GESTES VIT, et c'est hors du moteur. Un fichier posé dans son
# clone apparaîtrait comme non suivi dans son état git, et un exploitant qui
# regarde ce qu'il a modifié y verrait un reste dont il ne sait rien.
DOSSIER_VERROUS = os.path.join(".erplibre", "setops")


def chemin_verrou(moteur):
    """Le fichier-verrou des gestes de CE moteur. Ou « » sans moteur.

    UN VERROU PAR CLONE, et non un pour la machine : deux clones sont deux
    moteurs, avec chacun son instance montée, et les faire s'attendre ferait
    refuser un geste qui ne touche rien de commun.

    Le nom porte le dossier du moteur ET une empreinte de son chemin complet :
    le dossier seul se répète d'un checkout à l'autre — deux clones s'appellent
    volontiers pareil — et l'empreinte seule ne se lit pas.
    """
    nu = (moteur or "").strip().rstrip(os.sep)
    if not nu:
        return ""
    entier = os.path.abspath(nu)
    marque = hashlib.sha256(entier.encode("utf-8")).hexdigest()[:12]
    return os.path.join(
        os.path.expanduser("~"),
        DOSSIER_VERROUS,
        f"{os.path.basename(entier)}-{marque}.lock",
    )


@contextlib.contextmanager
def verrou_du_moteur(moteur):
    """Tient le verrou exclusif des gestes de `moteur` le temps du bloc.

    Rend True s'il est à nous, False s'il est tenu ailleurs. NE LÈVE JAMAIS.

    LE MOTEUR N'EN A PAS HORS DE SA CONSOLE. Deux gestes menés en même temps sur
    le même clone se disputent son instance montée, ses fichiers générés et la
    grappe : le second réécrit ce que le premier vient d'appliquer, et le
    résultat ne ressemble à aucun des deux.

    NON BLOQUANT : un second terminal est refusé sur-le-champ plutôt que mis en
    attente d'un déploiement qui dure des dizaines de minutes. Le verrou tombe
    avec le descripteur, donc aussi à la mort du processus, même brutale : aucun
    reste à nettoyer, et rien à purger après un arrêt qui s'est mal passé.

    UN FICHIER IMPOSSIBLE À OUVRIR REND TRUE, comme un système de fichiers qui
    ne sait pas verrouiller. Le verrou ferme une course entre deux terminaux ; en
    faire une condition d'exécution empêcherait tout geste sur un poste dont le
    dossier personnel est en lecture seule, alors que les gardes qui comptent —
    la barrière, la retape, le verdict — tiennent encore.
    """
    chemin = chemin_verrou(moteur)
    if not chemin:
        yield True
        return
    try:
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        descripteur = os.open(chemin, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        yield True
        return
    try:
        try:
            fcntl.flock(descripteur, fcntl.LOCK_EX | fcntl.LOCK_NB)
            libre = True
        except BlockingIOError:
            libre = False
        except OSError:
            libre = True
        yield libre
    finally:
        os.close(descripteur)


class Verdict(NamedTuple):
    """Ce qu'un geste a rendu.

    `code` vaut None quand le processus n'a pas pu tourner jusqu'au bout —
    introuvable, délai dépassé, argument invalide. C'est un verdict, pas une
    absence de verdict : l'appelant doit le distinguer d'un zéro.
    """

    code: int | None
    sortie: str

    @property
    def reussi(self) -> bool:
        """Le geste a-t-il rendu zéro ? Une panne de lancement vaut non."""
        return self.code == 0


def sans_venv_erplibre(path):
    """`path`, débarrassé des entrées qui vivent dans le venv d'ERPLibre.

    La comparaison porte sur un SEGMENT de chemin entier, jamais sur une
    sous-chaîne : un dossier qui contiendrait ce nom sans être ce venv reste
    en place, et une entrée relative n'est pas jugée sur son orthographe.
    """
    gardees = [
        entree
        for entree in (path or "").split(os.pathsep)
        if entree and VENV_ERPLIBRE not in entree.split(os.sep)
    ]
    return os.pathsep.join(gardees)


def base(source=None):
    """L'environnement d'un geste, construit à neuf : `ENV_TRANSMIS` seul.

    `source` remplace `os.environ` pour les épreuves. Le PATH transmis est
    débarrassé du venv d'ERPLibre ; `CONFIRMER` n'est PAS transmis, si bien
    qu'un `true` resté d'ailleurs ne peut pas atteindre le moteur.
    """
    vu = os.environ if source is None else source
    env = {cle: vu[cle] for cle in ENV_TRANSMIS if cle in vu}
    if "PATH" in env:
        env["PATH"] = sans_venv_erplibre(env["PATH"])
    return env


def cite(argv) -> str:
    """La commande, telle qu'un shell la lirait — ce qu'on affiche.

    Dérivée de l'argv et non écrite à côté : une ligne montrée qui n'est pas
    la ligne lancée est pire que pas de ligne du tout.
    """
    return shlex.join(argv)


def cible(moteur, nom, variables=(), confirmer=False):
    """L'argv d'une cible `make` du moteur, `CONFIRMER` toujours écrit.

    `variables` est une suite de (nom, valeur) posées après la cible, comme
    `make` les attend. `CONFIRMER` vient EN DERNIER et n'est jamais omis :
    une ligne sans lui laisse ignorer si le geste simule ou écrit.
    """
    # `--no-print-directory` retire les deux lignes « on entre / on quitte
    # le répertoire » : elles encadrent toute sortie, portent un chemin
    # absolu — donc un nom de compte — et un adaptateur fermé par défaut
    # les prendrait pour une forme inattendue.
    argv = ["make", "--no-print-directory", "-C", moteur, nom]
    argv += [f"{cle}={valeur}" for cle, valeur in variables]
    argv.append(f"{CONFIRMER}={CONFIRME if confirmer else SIMULE}")
    return tuple(argv)


def jouer(
    argv,
    env=None,
    cwd=None,
    capture=True,
    delai=DELAI,
    fusionner=True,
    entree=None,
):
    """Joue `argv` et rend son `Verdict`. Ne lève jamais.

    `entree` PASSE UN TEXTE SUR L'ENTRÉE STANDARD, sans le poser sur le disque.
    C'est le seul chemin par lequel un secret atteint l'outil qui le chiffre :
    écrit en clair puis chiffré, il resterait dans les blocs libérés et dans
    toute sauvegarde prise entre les deux gestes. Sans lui l'entrée reste
    FERMÉE, ce qui fait échouer tout de suite un geste qui réclamerait une
    phrase de passe, au lieu de le laisser attendre jusqu'à la borne.

    Sans `capture`, la sortie va au terminal de l'opérateur et le verdict ne
    porte que le code : c'est ce qu'il faut d'un geste long, qu'on regarde
    avancer, ou d'un geste qui demande une phrase de passe.

    `fusionner` mêle la sortie d'erreur à la sortie standard, ce que veut un
    geste dont on lit le compte rendu. Une SONDE la refuse : un avertissement
    imprimé sur l'erreur ferait passer une réponse d'une ligne pour une
    réponse bavarde, donc illisible.
    """
    sortie = subprocess.PIPE if capture else None
    erreur = (
        (subprocess.STDOUT if fusionner else subprocess.DEVNULL)
        if capture
        else None
    )
    try:
        fait = subprocess.run(
            list(argv),
            env=env,
            cwd=cwd,
            # `input` OU `stdin`, JAMAIS LES DEUX : les passer ensemble lève
            # une ValueError, que ce module attrape — le geste rendrait alors
            # « n'a pas pu tourner » sur un argument, ce qui se diagnostique
            # très loin de sa cause. Avec `input`, l'outil ouvre le tube lui-même.
            **(
                {"input": entree}
                if entree is not None
                else {"stdin": subprocess.DEVNULL}
            ),
            stdout=sortie,
            stderr=erreur,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=delai,
            check=False,
        )
    except subprocess.TimeoutExpired as souci:
        # CE QUI A DÉJÀ ÉTÉ DIT EST GARDÉ. Jeté, le verdict d'un déploiement
        # qui a tourné une heure en imprimant son avancement devenait celui
        # d'un binaire introuvable, et l'écran annonçait « n'a pas pu tourner
        # du tout » — faux, et sans la moindre trace de ce qui s'est passé.
        return Verdict(None, souci.output or "" if capture else "")
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return Verdict(None, "")
    return Verdict(fait.returncode, fait.stdout or "")


def detacher(argv, env=None, cwd=None, journal=None):
    """Lance `argv` détaché et rend son PID, ou None. Ne lève jamais.

    NOUVELLE SESSION, ET C'EST CE QUI PERMET DE L'ARRÊTER. Le processus
    devient chef de sa propre session, donc de son propre groupe : un signal
    au GROUPE atteint la recette `make` et le serveur qu'elle lance. Sans
    cela, arrêter `make` laisserait le serveur tenir le port, et le port
    occupé ferait croire à une console que todo ne saurait plus joindre.

    LE TERMINAL NE LUI EST PAS RENDU. Son entrée est fermée et sa sortie va au
    journal : un processus détaché qui écrirait sur le terminal brouillerait
    le menu, et l'un qui attendrait une réponse sur son entrée bloquerait sans
    que rien ne le dise.

    Le PID rendu est celui du CHEF DE GROUPE. Il ne prouve pas que le service
    a démarré — un détaché échoue en silence — seulement qu'il a été lancé.
    """
    flux = subprocess.DEVNULL
    if journal:
        try:
            # 0600 ET SANS SUIVRE DE LIEN. Le dossier de repli est partagé : un
            # autre compte peut y poser ce NOM en lien vers un fichier qu'on a
            # le droit d'écrire, et le journal du détaché irait chez lui. Le
            # mode par défaut d'`open` est 0666 moins l'umask, donc lisible par
            # tout le monde sur un poste ordinaire.
            flux = os.fdopen(
                os.open(
                    journal,
                    os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                    0o600,
                ),
                "ab",
            )
        except OSError as souci:
            # L'APPELANT A DEMANDÉ UN JOURNAL. Muet, il nommerait ensuite un
            # fichier qui n'a jamais été ouvert — sur le seul chemin de
            # diagnostic d'un geste dont la sortie ne se voit pas.
            print(f"  ⚠ journal indisponible ({souci.strerror or souci})")
            flux = subprocess.DEVNULL
    try:
        fils = subprocess.Popen(
            list(argv),
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=flux,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None
    finally:
        if flux is not subprocess.DEVNULL:
            flux.close()
    return fils.pid
