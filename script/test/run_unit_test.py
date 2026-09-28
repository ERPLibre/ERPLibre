#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lance des fichiers de tests unitaires en parallèle, isolés de l'hôte.

Appelé par `run_unit_test.sh`, qui vérifie l'environnement et dresse la
liste des fichiers ; ce module ne choisit rien, il exécute ce qu'on lui
donne :

    run_unit_test.py [--jobs N] [--timeout S] fichier...

Chaque fichier tourne dans son propre processus, `--jobs` à la fois, les
plus LONGS d'abord d'après les durées du passage précédent (DURATIONS) : la
durée totale devient celle du fichier le plus long plutôt que la somme de
tous. Un fichier sans durée connue passe devant, puisqu'on ignore s'il est
court.

HERMÉTIQUE. Un test unitaire ne touche pas l'hôte :
 - chaque fichier ouvre sa propre SESSION, sans terminal de contrôle, et lit
   /dev/null. Un sudo qui échappe aux doublures — un test qui remplace tout
   le PATH, par exemple — échoue aussitôt sur « a terminal is required » au
   lieu de demander un mot de passe que personne ne voit, et un input()
   oublié échoue sur EOFError au lieu d'attendre ;
 - sudo, pkexec, doas, virsh et ssh sont remplacés, en tête du PATH, par une
   commande qui refuse en le disant : un appel non bouchonné échoue de la
   même façon sur tous les postes, au lieu d'interroger les VM du poste ;
 - `--timeout` secondes par fichier : au-delà, le groupe entier du fichier
   est tué et le fichier marqué DÉLAI.

La session a un prix : Ctrl+C n'atteint plus les tests. Le lanceur le reçoit
seul, tue les groupes en cours et NOMME les fichiers qui tournaient — la
question qu'on se pose justement quand on l'interrompt.

L'affichage : une ligne par fichier quand il FINIT, donc dans le désordre,
et un rappel pour tout fichier qui dure plus de SIGNAL secondes
(UNIT_SIGNAL, 60 par défaut) ; les sorties des échecs suivent, dans
l'ordre des noms.
"""

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

ROUGE = "\033[0;31m"
VERT = "\033[0;32m"
JAUNE = "\033[0;33m"
FIN = "\033[0m"

ATTENTE = "en attente"
EN_COURS = "en cours"
OK = "OK"
ECHEC = "ÉCHEC"
DELAI = "DÉLAI"
ARRETE = "arrêté"

# Un fichier qui dure plus que cela est signalé, puis de nouveau à chaque
# intervalle : c'est la réponse à « lequel bloque ? » sans tout interrompre.
# Le plus long fichier de la suite tient sous la minute, même sous charge.
SIGNAL = int(os.environ.get("UNIT_SIGNAL") or 60)

DURATIONS = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "erplibre",
    "run_unit_test.durations",
)

# Les commandes refusées et le code d'échec que leur appelant attend.
REFUSEES = {"sudo": 1, "pkexec": 1, "doas": 1, "virsh": 1, "ssh": 255}


class Fichier:
    """Un fichier de tests et ce qu'on sait de son passage."""

    def __init__(self, chemin):
        self.chemin = chemin
        self.nom = os.path.basename(chemin)
        self.etat = ATTENTE
        self.debut = 0.0
        self.duree = 0.0
        self.ran = "?"
        self.skipped = ""
        self.log = ""
        self.proc = None

    def ecoule(self):
        """Secondes écoulées : figées une fois fini, courantes sinon."""
        if self.etat == EN_COURS:
            return time.monotonic() - self.debut
        return self.duree

    def echoue(self):
        return self.etat in (ECHEC, DELAI, ARRETE)


def lire_durees(chemin=DURATIONS):
    """{nom: secondes} du passage précédent ; vide si illisible."""
    durees = {}
    try:
        with open(chemin, encoding="utf-8") as fh:
            for ligne in fh:
                morceaux = ligne.split(maxsplit=1)
                if len(morceaux) == 2 and morceaux[0].isdigit():
                    durees[morceaux[1].strip()] = int(morceaux[0])
    except OSError:
        pass
    return durees


def ecrire_durees(fichiers, chemin=DURATIONS):
    """Remplace les durées des fichiers finis, garde celles des autres.

    Un fichier arrêté par Ctrl+C n'a pas de durée qui vaille : on garde
    l'ancienne plutôt que d'en inventer une."""
    durees = lire_durees(chemin)
    for f in fichiers:
        if f.etat in (OK, ECHEC, DELAI):
            durees[f.nom] = int(round(f.duree))
    try:
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        provisoire = chemin + ".tmp"
        with open(provisoire, "w", encoding="utf-8") as fh:
            for nom, secondes in sorted(durees.items()):
                fh.write(f"{secondes} {nom}\n")
        os.replace(provisoire, chemin)
    except OSError:
        pass


def ordonner(fichiers, durees):
    """Durée connue décroissante, inconnue d'abord."""
    return sorted(fichiers, key=lambda f: -durees.get(f.nom, 10**9))


def poser_doublures(dossier):
    """Écrit les commandes refusées dans `dossier`, qui ira en tête du
    PATH. Chacune écrit pourquoi sur la sortie d'erreur du test."""
    os.makedirs(dossier, exist_ok=True)
    for cmd, code in REFUSEES.items():
        chemin = os.path.join(dossier, cmd)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(
                "#!/bin/sh\n"
                f'echo "run_unit_test : « {cmd} $* » refusé, un test'
                " unitaire ne touche pas l'hôte\" >&2\n"
                f"exit {code}\n"
            )
        os.chmod(chemin, 0o755)


class Lanceur:
    """Exécute les fichiers et tient leur état à jour.

    Les états sont écrits par les fils d'exécution et lus par l'affichage,
    qui ne fait que les lire : pas de verrou, une valeur lue au milieu
    d'une mise à jour est simplement rafraîchie au tour suivant."""

    def __init__(self, fichiers, py, jobs, delai, durees):
        self.fichiers = ordonner([Fichier(c) for c in fichiers], durees)
        self.py = py
        self.jobs = max(1, jobs)
        self.delai = delai
        self.arret = threading.Event()
        self.debut = 0.0
        self.fin = 0.0
        self.travail = tempfile.mkdtemp(prefix="run_unit_test.")
        poser_doublures(os.path.join(self.travail, "bin"))
        self.env = dict(
            os.environ,
            PATH=os.path.join(self.travail, "bin")
            + os.pathsep
            + os.environ.get("PATH", ""),
            PYTHONPATH=".",
        )

    def _un(self, f):
        if self.arret.is_set():
            f.etat = ARRETE
            return
        f.log = os.path.join(self.travail, f.nom + ".log")
        f.debut = time.monotonic()
        f.etat = EN_COURS
        with open(f.log, "wb") as sortie:
            f.proc = subprocess.Popen(
                [self.py, f.chemin],
                stdin=subprocess.DEVNULL,
                stdout=sortie,
                stderr=subprocess.STDOUT,
                env=self.env,
                start_new_session=True,
            )
            try:
                rc = f.proc.wait(timeout=self.delai)
            except subprocess.TimeoutExpired:
                _tuer(f.proc)
                f.proc.wait()
                rc = None
        f.duree = time.monotonic() - f.debut
        texte = _lire(f.log)
        ran = re.findall(r"Ran (\d+)", texte)
        f.ran = ran[-1] if ran else "?"
        skipped = re.findall(r"skipped=\d+", texte)
        f.skipped = skipped[-1] if skipped else ""
        if self.arret.is_set() and rc != 0:
            f.etat = ARRETE
        elif rc is None:
            f.etat = DELAI
        elif rc == 0 and re.search(r"^OK", texte, re.M):
            f.etat = OK
        else:
            f.etat = ECHEC

    def lancer(self, fini=None):
        """Exécute tout ; `fini(f)` est appelé à la fin de chaque fichier."""
        self.debut = time.monotonic()

        def un(f):
            self._un(f)
            if fini:
                fini(f)

        with ThreadPoolExecutor(max_workers=self.jobs) as pool:
            list(pool.map(un, self.fichiers))
        self.fin = time.monotonic()

    def arreter(self):
        """Plus rien ne démarre, et les groupes en cours sont tués."""
        self.arret.set()
        for f in self.fichiers:
            if f.etat == EN_COURS and f.proc is not None:
                _tuer(f.proc)

    def en_cours(self):
        return [f for f in self.fichiers if f.etat == EN_COURS]

    def nettoyer(self):
        shutil.rmtree(self.travail, ignore_errors=True)


def _tuer(proc):
    """Tue le groupe entier : le test ET ce qu'il a lancé."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _lire(chemin, fin=None):
    """Le journal en texte ; ses `fin` dernières lignes si demandé."""
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            texte = fh.read()
    except OSError:
        return ""
    if fin is None:
        return texte
    return "\n".join(texte.rstrip("\n").split("\n")[-fin:])


def couleur(etat):
    if etat == OK:
        return VERT
    if etat == ATTENTE:
        return ""
    if etat in (EN_COURS, ARRETE):
        return JAUNE
    return ROUGE


def ligne(f, delai):
    etat = f"{DELAI} {delai}s" if f.etat == DELAI else f.etat
    return "  %-42s %5s tests %-14s %s%s%s" % (
        f.nom,
        f.ran,
        f.skipped,
        couleur(f.etat),
        etat,
        FIN,
    )


def bilan(lanceur):
    """Les sorties des échecs, dans l'ordre des noms, puis le total.

    Rend le code de sortie : 0 si tout est vert."""
    echecs = sorted(
        (f for f in lanceur.fichiers if f.echoue() and f.log),
        key=lambda f: f.nom,
    )
    for f in echecs:
        print(f"\n  {ROUGE}── {f.nom}{FIN}")
        print(_lire(f.log, fin=12))
    total = sum(int(f.ran) for f in lanceur.fichiers if f.ran.isdigit())
    duree = f"{lanceur.fin - lanceur.debut:.0f} s, {lanceur.jobs} en parallèle"
    print("  ─────")
    arretes = [f for f in lanceur.fichiers if f.etat == ARRETE]
    if arretes:
        print(f"  {JAUNE}interrompu{FIN} ({duree})")
        return 130
    if any(f.echoue() for f in lanceur.fichiers):
        print(f"  {ROUGE}des échecs ci-dessus{FIN} ({duree})")
        return 1
    print(f"  {VERT}{total} tests, tout vert{FIN} ({duree})")
    return 0


def en_ligne(lanceur):
    """L'affichage par défaut : une ligne par fichier fini, un rappel pour
    ceux qui s'éternisent, et les fichiers en cours nommés à Ctrl+C."""
    fil = threading.Thread(
        target=lanceur.lancer,
        kwargs={"fini": lambda f: print(ligne(f, lanceur.delai), flush=True)},
        daemon=True,
    )
    fil.start()
    signale = {}
    try:
        while fil.is_alive():
            fil.join(timeout=1)
            for f in lanceur.en_cours():
                ecoule = f.ecoule()
                if (
                    ecoule >= SIGNAL
                    and ecoule - signale.get(f.nom, 0) >= SIGNAL
                ):
                    signale[f.nom] = ecoule
                    print(
                        f"  {JAUNE}… {f.nom} en cours depuis"
                        f" {ecoule:.0f} s{FIN}",
                        flush=True,
                    )
    except KeyboardInterrupt:
        tournaient = [(f.nom, f.ecoule()) for f in lanceur.en_cours()]
        lanceur.arreter()
        print(f"\n  {JAUNE}Interrompu. En cours à cet instant :{FIN}")
        for nom, ecoule in sorted(tournaient, key=lambda x: -x[1]):
            print(f"    {nom}  {ecoule:.0f} s")
        fil.join()
    return bilan(lanceur)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("fichiers", nargs="+")
    parser.add_argument(
        "--jobs", type=int, default=int(os.environ.get("UNIT_JOBS") or 0)
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("UNIT_TIMEOUT") or 300),
    )
    args = parser.parse_args(argv)
    lanceur = Lanceur(
        args.fichiers,
        py=sys.executable,
        jobs=args.jobs or os.cpu_count() or 4,
        delai=args.timeout,
        durees=lire_durees(),
    )
    try:
        code = en_ligne(lanceur)
        ecrire_durees(lanceur.fichiers)
        return code
    finally:
        lanceur.arreter()
        lanceur.nettoyer()


if __name__ == "__main__":
    sys.exit(main())
