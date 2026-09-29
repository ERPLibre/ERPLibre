#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lance des fichiers de tests unitaires en parallèle, isolés de l'hôte.

Appelé par `run_unit_test.sh`, qui vérifie l'environnement et dresse la
liste des fichiers ; ce module ne choisit rien, il exécute ce qu'on lui
donne :

    run_unit_test.py [--tui] [--changed[=REF]] [--failed] [--watch]
                     [--repeat N] [--slowest N] [--junit FICHIER]
                     [--jobs N] [--timeout S] -- fichier...

`--changed` ne garde que les fichiers de tests qu'un fichier modifié depuis
REF (HEAD par défaut : ce qui n'est pas commité) peut toucher ; `--failed`,
ceux qui ont échoué au passage précédent. Les deux s'additionnent. Le
choix est fait par unit_selection.py, qui en décrit les règles. `--watch`
relance, à chaque fichier enregistré, les tests que ce fichier atteint.

`--repeat N` lance chaque fichier N fois et nomme ceux dont l'issue varie :
un test instable sous la charge. `--slowest N` liste les N TESTS les plus
lents, et `--junit FICHIER` écrit le résultat de chaque test au format
JUnit XML ; ces deux-là passent chaque fichier par unit_file.py, qui note
chaque test, au lieu de le lancer comme programme.

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

Deux affichages :
 - en ligne (défaut) : une ligne par fichier quand il FINIT, donc dans le
   désordre, et un rappel pour tout fichier qui dure plus de SIGNAL
   secondes (UNIT_SIGNAL, 60 par défaut) ; les sorties des échecs suivent,
   dans l'ordre des noms ;
 - `--tui` : un tableau Textual, attente / en cours / fini avec la durée,
   et la fin du journal du fichier sélectionné. Sans Textual ou sans
   terminal, retombe sur l'affichage en ligne.
"""

import argparse
import json
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

import unit_selection

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

# Les fichiers en échec au passage précédent, pour --failed.
ECHECS = os.path.join(os.path.dirname(DURATIONS), "run_unit_test.failed")

# L'enveloppe qui note chaque test, pour --slowest et --junit.
UNIT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "unit_file.py"
)

# Les commandes refusées et le code d'échec que leur appelant attend.
REFUSEES = {"sudo": 1, "pkexec": 1, "doas": 1, "virsh": 1, "ssh": 255}


class Fichier:
    """Un fichier de tests et ce qu'on sait de son passage."""

    def __init__(self, chemin, passage=0, passages=1):
        self.chemin = chemin
        # Le nom du FICHIER, sur lequel se règlent les durées et les échecs
        # retenus ; `nom` est celui qu'on affiche, un passage de --repeat
        # y portant son rang.
        self.fichier = os.path.basename(chemin)
        self.passage = passage
        self.nom = self.fichier
        if passages > 1:
            self.nom += f" #{passage + 1}"
        self.etat = ATTENTE
        self.tests = []
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
            durees[f.fichier] = int(round(f.duree))
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
    return sorted(
        fichiers, key=lambda f: (-durees.get(f.fichier, 10**9), f.passage)
    )


# Les doublures vivent à un chemin FIXE, hors du dépôt, et non dans le
# répertoire temporaire de chaque passage : le PATH des tests est alors le
# même d'un passage à l'autre. Un outil qui met ses résultats en cache selon
# l'environnement — « go test », qui retient le PATH d'un test qui lance des
# commandes — retrouve ainsi son cache au lieu de tout refaire.
DOUBLURES = os.path.join(os.path.dirname(DURATIONS), "run_unit_test.bin")


def poser_doublures(dossier=DOUBLURES):
    """Écrit les commandes refusées dans `dossier`, qui ira en tête du
    PATH. Chacune écrit pourquoi sur la sortie d'erreur du test.

    Un fichier déjà identique n'est pas réécrit : sa date reste la même, et
    un cache qui la compare n'est pas invalidé. L'écriture passe par un
    fichier provisoire renommé, pour que deux lanceurs simultanés ne se
    voient jamais une doublure à moitié écrite."""
    os.makedirs(dossier, exist_ok=True)
    for cmd, code in REFUSEES.items():
        chemin = os.path.join(dossier, cmd)
        contenu = (
            "#!/bin/sh\n"
            f'echo "run_unit_test : « {cmd} $* » refusé, un test'
            " unitaire ne touche pas l'hôte\" >&2\n"
            f"exit {code}\n"
        )
        try:
            with open(chemin, encoding="utf-8") as fh:
                if fh.read() == contenu and os.access(chemin, os.X_OK):
                    continue
        except OSError:
            pass
        provisoire = f"{chemin}.{os.getpid()}.tmp"
        with open(provisoire, "w", encoding="utf-8") as fh:
            fh.write(contenu)
        os.chmod(provisoire, 0o755)
        os.replace(provisoire, chemin)
    return dossier


class Lanceur:
    """Exécute les fichiers et tient leur état à jour.

    Les états sont écrits par les fils d'exécution et lus par l'affichage,
    qui ne fait que les lire : pas de verrou, une valeur lue au milieu
    d'une mise à jour est simplement rafraîchie au tour suivant."""

    def __init__(
        self, fichiers, py, jobs, delai, durees, passages=1, detaille=False
    ):
        self.fichiers = ordonner(
            [
                Fichier(c, k, passages)
                for c in fichiers
                for k in range(max(1, passages))
            ],
            durees,
        )
        self.detaille = detaille
        self.py = py
        self.jobs = max(1, jobs)
        self.delai = delai
        self.arret = threading.Event()
        self.debut = 0.0
        self.fin = 0.0
        self.travail = tempfile.mkdtemp(prefix="run_unit_test.")
        self.env = dict(
            os.environ,
            PATH=poser_doublures() + os.pathsep + os.environ.get("PATH", ""),
            PYTHONPATH=".",
        )

    def _un(self, f):
        if self.arret.is_set():
            f.etat = ARRETE
            return
        base = os.path.join(self.travail, f"{f.fichier}.{f.passage}")
        f.log = base + ".log"
        cmd = [self.py, f.chemin]
        if self.detaille:
            cmd = [self.py, UNIT_FILE, f.chemin, base + ".json"]
        f.debut = time.monotonic()
        f.etat = EN_COURS
        with open(f.log, "wb") as sortie:
            f.proc = subprocess.Popen(
                cmd,
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
        if self.detaille:
            try:
                with open(base + ".json", encoding="utf-8") as fh:
                    f.tests = json.load(fh)
            except (OSError, ValueError):
                f.tests = []
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


def tui(lanceur):
    """Le tableau Textual. Rend None si Textual manque : l'appelant
    retombe alors sur l'affichage en ligne."""
    try:
        from rich.text import Text
        from textual.app import App
        from textual.containers import Vertical
        from textual.widgets import DataTable, Footer, Header, Static
    except ImportError:
        return None

    colonnes = ("Fichier", "État", "Tests", "Durée")

    class Vue(App):
        TITLE = "Tests unitaires"
        CSS = """
        DataTable { height: 2fr; }
        #journal { height: 1fr; border-top: solid $accent; padding: 0 1; }
        """
        BINDINGS = [("q", "quitter", "Quitter (arrête les tests)")]

        def compose(self):
            yield Header()
            with Vertical():
                yield DataTable(cursor_type="row", zebra_stripes=True)
                yield Static("", id="journal")
            yield Footer()

        def on_mount(self):
            table = self.query_one(DataTable)
            for nom in colonnes:
                table.add_column(nom, key=nom)
            for f in lanceur.fichiers:
                table.add_row(*self._cellules(f), key=f.nom)
            self.fil = threading.Thread(target=lanceur.lancer, daemon=True)
            self.fil.start()
            self.set_interval(0.5, self._rafraichir)

        def _cellules(self, f):
            duree = f"{f.ecoule():.0f} s" if f.etat != ATTENTE else ""
            return (f.nom, f.etat, f.ran if f.ran != "?" else "", duree)

        def _rafraichir(self):
            table = self.query_one(DataTable)
            for f in lanceur.fichiers:
                for colonne, valeur in zip(colonnes, self._cellules(f)):
                    table.update_cell(f.nom, colonne, valeur)
            faits = sum(
                f.etat not in (ATTENTE, EN_COURS) for f in lanceur.fichiers
            )
            rouges = sum(f.echoue() for f in lanceur.fichiers)
            ecoule = time.monotonic() - lanceur.debut if lanceur.debut else 0
            fin = "" if self.fil.is_alive() else " — terminé, q pour quitter"
            self.sub_title = (
                f"{faits}/{len(lanceur.fichiers)} finis,"
                f" {len(lanceur.en_cours())} en cours, {rouges} en échec,"
                f" {ecoule:.0f} s{fin}"
            )
            ligne_choisie = table.cursor_row
            if 0 <= ligne_choisie < len(lanceur.fichiers):
                f = lanceur.fichiers[ligne_choisie]
                journal = self.query_one("#journal", Static)
                # La FIN du journal, à la hauteur du panneau : c'est là que
                # unittest écrit l'erreur et le verdict.
                hauteur = max(3, journal.size.height - 1)
                texte = _lire(f.log, fin=hauteur) if f.log else "(pas démarré)"
                # Du texte brut, jamais du balisage : un journal porte des
                # crochets et des codes ANSI, que le balisage de Textual
                # prendrait pour les siens et refuserait.
                contenu = Text(f"{f.nom} — {f.etat}\n", style="bold")
                contenu.append_text(Text.from_ansi(texte))
                journal.update(contenu)

        def action_quitter(self):
            lanceur.arreter()
            self.exit()

    Vue().run()
    lanceur.arreter()
    # Les fils finissent sur les groupes tués : attendre qu'ils aient posé
    # leur état avant le bilan.
    while lanceur.en_cours():
        time.sleep(0.1)
    if not lanceur.fin:
        lanceur.fin = time.monotonic()
    for f in lanceur.fichiers:
        print(ligne(f, lanceur.delai))
    return bilan(lanceur)


def choisir(fichiers, reference, echecs):
    """Les `fichiers` que --changed et --failed retiennent, par union.

    Annonce chaque sélection et ce qui l'a produite ; rend None si la
    référence git est illisible."""
    choisis = set()
    if reference:
        try:
            modifies = unit_selection.fichiers_modifies(".", reference)
        except ValueError as exc:
            print(f"  {ROUGE}--changed : {exc}{FIN}")
            return None
        concernes = unit_selection.concernes(".", fichiers, modifies)
        print(
            f"  --changed ({reference}) : {len(modifies)} fichier(s)"
            f" modifié(s) → {len(concernes)} fichier(s) de tests"
        )
        choisis |= set(concernes)
    if echecs:
        noms = unit_selection.echecs_retenus(ECHECS)
        echoues = [f for f in fichiers if os.path.basename(f) in noms]
        print(
            f"  --failed : {len(echoues)} fichier(s) en échec la dernière fois"
        )
        choisis |= {os.path.normpath(f) for f in echoues}
    return [f for f in fichiers if os.path.normpath(f) in choisis]


def instables(lanceur):
    """Les fichiers dont l'issue a varié d'un passage de --repeat à
    l'autre, avec le décompte de leurs issues."""
    par_fichier = {}
    for f in lanceur.fichiers:
        if f.etat in (OK, ECHEC, DELAI):
            par_fichier.setdefault(f.fichier, []).append(f.etat)
    return {
        nom: {e: etats.count(e) for e in sorted(set(etats))}
        for nom, etats in sorted(par_fichier.items())
        if len(set(etats)) > 1
    }


def plus_lents(lanceur, combien):
    """Les `combien` tests les plus lents : (secondes, fichier, id). Un test
    répété par --repeat compte pour sa durée la plus longue."""
    pire = {}
    for f in lanceur.fichiers:
        for t in f.tests:
            cle = (f.fichier, t["id"])
            pire[cle] = max(pire.get(cle, 0.0), t["duree"])
    return sorted(
        ((d, fichier, ident) for (fichier, ident), d in pire.items()),
        reverse=True,
    )[:combien]


def ecrire_junit(lanceur, chemin):
    """Le résultat de chaque test au format JUnit XML, une suite par
    fichier. Un fichier sans détail — tué par le délai, ou mort avant
    d'écrire — y figure comme une erreur, pour ne pas disparaître."""
    import xml.etree.ElementTree as ET

    racine = ET.Element("testsuites")
    for f in lanceur.fichiers:
        suite = ET.SubElement(
            racine, "testsuite", name=f.nom, time=f"{f.duree:.3f}"
        )
        comptes = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        tests = f.tests or [
            {
                "classe": "",
                "nom": f.fichier,
                "duree": f.duree,
                "etat": "erreur",
                "message": f"{f.etat} : aucun résultat par test",
            }
        ]
        for t in tests:
            comptes["tests"] += 1
            cas = ET.SubElement(
                suite,
                "testcase",
                classname=f"{f.fichier[:-3]}.{t['classe']}".rstrip("."),
                name=t["nom"],
                time=f"{t['duree']:.3f}",
            )
            balise = {
                "echec": ("failure", "failures"),
                "erreur": ("error", "errors"),
                "ignore": ("skipped", "skipped"),
            }.get(t["etat"])
            if balise:
                comptes[balise[1]] += 1
                message = t.get("message") or ""
                ET.SubElement(
                    cas,
                    balise[0],
                    message=message.splitlines()[-1:][0] if message else "",
                ).text = message
        for cle, valeur in comptes.items():
            suite.set(cle, str(valeur))
    ET.ElementTree(racine).write(
        chemin, encoding="utf-8", xml_declaration=True
    )


def rapports(lanceur, args):
    """Ce que --repeat, --slowest et --junit demandent, après le bilan.

    Rend 1 si des fichiers se sont montrés instables, 0 sinon."""
    code = 0
    if args.repeat > 1:
        variables = instables(lanceur)
        if variables:
            code = 1
            print(f"  {JAUNE}Instables sur {args.repeat} passages :{FIN}")
            for nom, issues in variables.items():
                detail = ", ".join(f"{n} {e}" for e, n in issues.items())
                print(f"    {nom}  ({detail})")
        else:
            print(f"  Aucun fichier instable sur {args.repeat} passages.")
    if args.slowest:
        print(f"  Les {args.slowest} tests les plus lents :")
        for duree, fichier, ident in plus_lents(lanceur, args.slowest):
            print(f"    {duree:6.2f} s  {fichier}  {ident.split('.', 1)[-1]}")
    if args.junit:
        ecrire_junit(lanceur, args.junit)
        print(f"  JUnit : {args.junit}")
    return code


def bilan_des_echecs(fichiers):
    """(passés, échoués) : les noms de fichiers à retirer des échecs
    retenus, et ceux à y ajouter.

    Un fichier ne sort des échecs retenus que si TOUS ses passages ont
    réussi : un seul échec sur N le garde, c'est ce qu'il faut relancer.
    Un passage arrêté n'a rien prouvé, dans un sens ni dans l'autre."""
    issues = {}
    for f in fichiers:
        issues.setdefault(f.fichier, set()).add(f.etat)
    passes = [n for n, e in issues.items() if e == {OK}]
    echoues = [n for n, e in issues.items() if e & {ECHEC, DELAI}]
    return passes, echoues


def lancer_une_fois(fichiers, args):
    """Un passage complet sur `fichiers` : exécution, bilan, rapports, et
    mise à jour des durées et des échecs retenus. Rend le code de sortie."""
    lanceur = Lanceur(
        fichiers,
        py=sys.executable,
        jobs=args.jobs or os.cpu_count() or 4,
        delai=args.timeout,
        durees=lire_durees(),
        passages=args.repeat,
        detaille=bool(args.slowest or args.junit),
    )
    try:
        code = None
        if args.tui and sys.stdout.isatty():
            code = tui(lanceur)
            if code is None:
                print("  Textual absent : affichage en ligne.")
        if code is None:
            code = en_ligne(lanceur)
        # Toujours produits : c'est après un échec qu'on en a besoin.
        instable = rapports(lanceur, args)
        code = code or instable
        ecrire_durees(lanceur.fichiers)
        passes, echoues = bilan_des_echecs(lanceur.fichiers)
        unit_selection.retenir_echecs(ECHECS, passes=passes, echoues=echoues)
        return code
    finally:
        lanceur.arreter()
        lanceur.nettoyer()


def releve(fichiers):
    """{chemin: date de modification} des fichiers du dépôt."""
    etat = {}
    for chemin in fichiers:
        try:
            etat[chemin] = os.stat(chemin).st_mtime_ns
        except OSError:
            pass
    return etat


def surveiller(tests, args, pause=1.0):
    """--watch : à chaque fichier enregistré, les tests qu'il atteint.

    Le relevé est refait à chaque tour — la liste des fichiers du dépôt
    comprise, pour voir un fichier créé —, et coûte quelques millisecondes.
    Ctrl+C sort."""
    avant = releve(unit_selection.fichiers_du_depot("."))
    print("  --watch : j'attends un fichier enregistré (Ctrl+C pour sortir).")
    try:
        while True:
            time.sleep(pause)
            apres = releve(unit_selection.fichiers_du_depot("."))
            modifies = sorted(
                c
                for c in set(avant) | set(apres)
                if avant.get(c) != apres.get(c)
            )
            if not modifies:
                continue
            avant = apres
            concernes = unit_selection.concernes(".", tests, modifies)
            print(
                f"\n  --watch : {', '.join(modifies[:3])}"
                f"{' …' if len(modifies) > 3 else ''}"
                f" → {len(concernes)} fichier(s) de tests"
            )
            # Un Ctrl+C pendant le passage est reçu par l'affichage, qui
            # arrête les tests et rend 130 : c'est aussi la fin de --watch.
            if concernes and lancer_une_fois(concernes, args) == 130:
                print("  --watch : fin.")
                return 130
            # Un test qui écrit dans le dépôt relancerait la boucle : ce
            # qu'il a touché pendant le passage fait partie du relevé.
            avant = releve(unit_selection.fichiers_du_depot("."))
    except KeyboardInterrupt:
        print("\n  --watch : fin.")
        return 0


def _interrompre(_signal, _cadre):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("fichiers", nargs="+")
    parser.add_argument("--tui", action="store_true")
    parser.add_argument("--changed", nargs="?", const="HEAD", metavar="REF")
    parser.add_argument("--failed", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--repeat", type=int, default=1, metavar="N")
    parser.add_argument("--slowest", type=int, default=0, metavar="N")
    parser.add_argument("--junit", metavar="FICHIER")
    parser.add_argument(
        "--jobs", type=int, default=int(os.environ.get("UNIT_JOBS") or 0)
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("UNIT_TIMEOUT") or 300),
    )
    args = parser.parse_args(argv)
    # SIGTERM comme Ctrl+C : les tests tournent dans leur propre session, et
    # un lanceur tué sans les arrêter les laisserait tourner jusqu'au délai.
    signal.signal(signal.SIGTERM, _interrompre)
    if args.watch:
        return surveiller(args.fichiers, args)
    fichiers = args.fichiers
    if args.changed or args.failed:
        fichiers = choisir(fichiers, args.changed, args.failed)
        if fichiers is None:
            return 2
        if not fichiers:
            print("  Aucun fichier de tests à lancer.")
            return 0
    return lancer_une_fois(fichiers, args)


if __name__ == "__main__":
    sys.exit(main())
