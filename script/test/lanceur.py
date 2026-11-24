# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur des lanceurs de tests : des éléments lancés en parallèle,
chacun dans son propre groupe de processus, et une CAMPAGNE qui décide du
reste.

Un ÉLÉMENT est une commande : un fichier de tests unitaires, une tranche
d'un fichier lent, un scénario Odoo. Chacun tourne dans sa propre session
(lib_processus), lit /dev/null, écrit son journal dans un fichier et reçoit
son propre TMPDIR : ce qu'il y laisse est compté, puis supprimé. Au délai,
son groupe entier est tué, après la grâce de la campagne.

La CAMPAGNE porte ce qui change d'une famille d'éléments à l'autre : la
commande et l'environnement de chaque élément, le verdict tiré du code de
retour et du journal, le découpage en tranches, la grâce SIGTERM, les
fichiers d'état (durées, échecs) et les crochets `entre_phases` et
`demontage`. `run_unit_test.py` en définit une pour les tests unitaires,
`run_odoo_scenarios.py` une pour les scénarios Odoo.

Les PHASES ordonnent les éléments : la phase N+1 ne démarre qu'à la fin de
toute la phase N — une barrière —, même après des ÉCHECS, jamais après un
arrêt. À l'intérieur d'une phase, les éléments les plus longs partent
d'abord, d'après les durées du passage précédent : la phase dure alors le
plus long de ses éléments plutôt que la somme.

Ctrl+C, SIGTERM ou `q` dans la TUI : plus rien ne démarre, les groupes en
cours reçoivent SIGTERM puis, après la grâce, SIGKILL ; les éléments qui
tournaient sont nommés. `demontage` tourne dans tous les cas, après la
mort de tous les groupes.
"""

import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Le moteur se charge comme script (sys.path[0] = script/test) : la racine
# du dépôt s'ajoute EN FIN de chemin, pour que script/git ne masque jamais
# un paquet du même nom (GitPython).
_RACINE = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if os.path.abspath(_RACINE) not in map(os.path.abspath, sys.path):
    sys.path.append(os.path.abspath(_RACINE))

from script import lib_processus  # noqa: E402

ROUGE = "\033[0;31m"
VERT = "\033[0;32m"
JAUNE = "\033[0;33m"
FIN = "\033[0m"

# Ctrl+C pendant le démontage au-delà duquel on l'abandonne.
ABANDON = 3

ATTENTE = "en attente"
EN_COURS = "en cours"
OK = "OK"
ECHEC = "ÉCHEC"
DELAI = "DÉLAI"
ARRETE = "arrêté"


# Une seule campagne à la fois : la suite unitaire et les scénarios Odoo
# partagent le serveur PostgreSQL (bases à nom fixe, bases de passage) et
# les dépôts du générateur de code, et deux suites simultanées se prennent
# pour une descente en cours.
VERROU = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "erplibre",
    "campagne.lock",
)


# Posée dans l'environnement de chaque élément : un processus lancé par une
# campagne en fait partie, et le verrou qu'elle tient ne le refuse pas — un
# test qui exécute un passage du lanceur, par exemple.
DANS_UNE_CAMPAGNE = "ERPLIBRE_CAMPAGNE"


class CampagneOccupee(RuntimeError):
    """Une autre campagne tient le verrou ; le message la nomme."""


@contextlib.contextmanager
def verrou_campagne(nom, chemin=None):
    """Tient le verrou des campagnes le temps du `with`, ou lève
    CampagneOccupee en nommant celle qui le tient (nom, pid).

    Un verrou flock : il tombe avec le processus qui le tient, même tué
    sans pouvoir nettoyer, et ne laisse donc jamais de verrou orphelin."""
    if os.environ.get(DANS_UNE_CAMPAGNE):
        yield
        return
    chemin = chemin or VERROU
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    fd = os.open(chemin, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            detenteur = os.pread(fd, 200, 0).decode(errors="replace").strip()
            raise CampagneOccupee(
                f"une autre campagne tourne déjà ({detenteur or 'inconnue'})"
            ) from None
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{nom}, pid {os.getpid()}\n".encode(), 0)
        try:
            yield
        finally:
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class Element:
    """Un élément d'une campagne et ce qu'on sait de son passage.

    `chemin` désigne ce qu'on lance ; `nom`, s'il est donné, remplace son
    nom de fichier comme clé des durées et des échecs retenus."""

    def __init__(
        self, chemin, passage=0, passages=1, tranche=None, phase=0, nom=None
    ):
        self.chemin = chemin
        # (rang, nombre) quand le fichier tourne en tranches, sinon None.
        self.tranche = tranche
        self.phase = phase
        # Le nom du FICHIER, sur lequel se règlent les durées et les échecs
        # retenus ; `nom` est celui qu'on affiche, un passage de --repeat
        # y portant son rang.
        self.fichier = nom or os.path.basename(chemin)
        self.passage = passage
        self.nom = self.fichier
        if tranche:
            self.nom += f" [{tranche[0] + 1}/{tranche[1]}]"
        if passages > 1:
            self.nom += f" #{passage + 1}"
        self.etat = ATTENTE
        self.tests = []
        self.debut = 0.0
        self.duree = 0.0
        self.ran = "?"
        self.skipped = ""
        self.log = ""
        # Le groupe de processus de l'élément pendant qu'il tourne.
        self.groupe = None
        # Le rang de l'élément dans le lanceur, qui nomme ses fichiers de
        # travail : deux éléments de même nom — dans deux répertoires, ou le
        # même donné deux fois — ne partagent ni journal ni TMPDIR.
        self.rang = 0
        # Entrées que l'élément a laissées dans son TMPDIR : le lanceur les
        # supprime et les signale au bilan.
        self.restes = 0

    def ecoule(self):
        """Secondes écoulées : figées une fois fini, courantes sinon."""
        if self.etat == EN_COURS:
            return time.monotonic() - self.debut
        return self.duree

    def echoue(self):
        return self.etat in (ECHEC, DELAI, ARRETE)


class Campagne:
    """Ce qui distingue une famille d'éléments. Les valeurs par défaut
    décrivent un élément qui est un programme : verdict par code de
    retour, sans tranche ni grâce.

    `commande`, `env` et `verdict` sont appelés depuis les fils
    d'exécution ; `entre_phases` et `demontage` depuis le fil qui lance."""

    # Le mot du bilan : « 12 éléments, tout vert ».
    unite = "éléments"
    # Découper un élément lent en tranches parallèles (tests unitaires).
    tranches = False
    seuil_tranche = 30
    # Secondes avant de signaler un élément qui s'éternise, puis de nouveau
    # à chaque intervalle.
    signal = 60
    # Secondes entre SIGTERM et SIGKILL quand un groupe est arrêté.
    grace = 0.0
    # Préfixe du répertoire de travail du passage, sous TMPDIR.
    prefixe = "lanceur."
    # Ce qu'il faut faire quand le démontage est abandonné.
    si_abandon = ""
    # Fichiers d'état ; None : rien n'est retenu d'un passage à l'autre.
    fichier_durees = None
    fichier_echecs = None

    def commande(self, lanceur, element, base):
        """La commande de `element` ; `base` préfixe ses fichiers de
        travail (journal, détail JSON)."""
        return [lanceur.py, "-u", element.chemin]

    def env(self, lanceur, travail):
        """L'environnement commun des éléments ; chacun y reçoit en plus
        son TMPDIR."""
        return dict(os.environ)

    def verdict(self, rc, texte, element):
        """OK ou ÉCHEC d'un élément sorti de lui-même avec `rc`."""
        return OK if rc == 0 else ECHEC

    def entre_phases(self, lanceur, phase):
        """Avant la phase `phase`, la précédente finie."""

    def demontage(self, lanceur):
        """Après tout, groupes morts compris, quelle que soit l'issue."""


def lire_durees(chemin):
    """{nom: secondes} du passage précédent ; vide si illisible."""
    durees = {}
    if not chemin:
        return durees
    try:
        with open(chemin, encoding="utf-8") as fh:
            for ligne in fh:
                morceaux = ligne.split(maxsplit=1)
                if len(morceaux) == 2 and morceaux[0].isdigit():
                    durees[morceaux[1].strip()] = int(morceaux[0])
    except OSError:
        pass
    return durees


def ecrire_durees(fichiers, chemin):
    """Remplace les durées des éléments finis, garde celles des autres.

    Un élément arrêté par Ctrl+C n'a pas de durée qui vaille : on garde
    l'ancienne plutôt que d'en inventer une. Un fichier en tranches retient
    la SOMME de ses tranches, sa durée d'un seul tenant : c'est elle qui
    décide de le découper au passage suivant, qui le découpe donc de même,
    et seulement si toutes ses tranches ont fini."""
    if not chemin:
        return
    durees = lire_durees(chemin)
    par_passage = {}
    for f in fichiers:
        par_passage.setdefault((f.fichier, f.passage), []).append(f)
    for (nom, _passage), groupe in par_passage.items():
        if all(f.etat in (OK, ECHEC, DELAI) for f in groupe):
            durees[nom] = int(round(sum(f.duree for f in groupe)))
    try:
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        provisoire = chemin + ".tmp"
        with open(provisoire, "w", encoding="utf-8") as fh:
            for nom, secondes in sorted(durees.items()):
                fh.write(f"{secondes} {nom}\n")
        os.replace(provisoire, chemin)
    except OSError:
        pass


def nombre_de_tranches(duree, jobs, seuil):
    """En combien de tranches lancer un fichier de durée connue `duree`
    (None si inconnue) : une par tranche de `seuil` secondes commencée, au
    plus `jobs`. Un seuil nul ne découpe rien."""
    if not seuil or not duree or duree <= seuil:
        return 1
    return max(1, min(jobs, -(-duree // seuil)))


def ordonner(fichiers, durees):
    """Phase croissante ; dans une phase, durée connue décroissante,
    inconnue d'abord. Une tranche compte pour sa part de la durée de son
    fichier."""

    def estimation(f):
        duree = durees.get(f.fichier, 10**9)
        return duree / f.tranche[1] if f.tranche else duree

    return sorted(fichiers, key=lambda f: (f.phase, -estimation(f), f.passage))


class Lanceur:
    """Exécute les éléments et tient leur état à jour.

    `fichiers` : des chemins, que la campagne découpe en tranches s'il le
    faut, ou des Element déjà construits (phases, noms). Les états sont
    écrits par les fils d'exécution et lus par l'affichage, qui ne fait que
    les lire : pas de verrou, une valeur lue au milieu d'une mise à jour est
    simplement rafraîchie au tour suivant."""

    def __init__(
        self,
        fichiers,
        py,
        jobs,
        delai,
        durees,
        passages=1,
        detaille=False,
        campagne=None,
    ):
        self.campagne = campagne or Campagne()
        self.jobs = max(1, jobs)
        elements = []
        for c in fichiers:
            if isinstance(c, Element):
                elements.append(c)
                continue
            nombre = 1
            if self.campagne.tranches:
                nombre = nombre_de_tranches(
                    durees.get(os.path.basename(c)),
                    self.jobs,
                    self.campagne.seuil_tranche,
                )
            for k in range(max(1, passages)):
                for rang in range(nombre):
                    elements.append(
                        Element(
                            c,
                            k,
                            passages,
                            tranche=(rang, nombre) if nombre > 1 else None,
                        )
                    )
        self.fichiers = ordonner(elements, durees)
        for rang, f in enumerate(self.fichiers):
            f.rang = rang
        self.detaille = detaille
        self.py = py
        self.delai = delai
        self.arret = threading.Event()
        self.lot = lib_processus.Lot(grace=self.campagne.grace)
        self.debut = 0.0
        self.fin = 0.0
        self.travail = tempfile.mkdtemp(prefix=self.campagne.prefixe)
        self.env = self.campagne.env(self, self.travail)
        self.env[DANS_UNE_CAMPAGNE] = self.campagne.prefixe.rstrip(".")

    def _un(self, f):
        if self.arret.is_set():
            f.etat = ARRETE
            return
        base = os.path.join(self.travail, f"{f.rang}.{f.fichier}")
        f.log = base + ".log"
        cmd = self.campagne.commande(self, f, base)
        # Un TMPDIR par élément, sous le répertoire de travail : ce qu'un
        # test oublie de supprimer y reste, est compté puis supprimé, au lieu
        # de s'accumuler dans /tmp jusqu'à en épuiser les inodes.
        tmp = base + ".tmp"
        os.makedirs(tmp, exist_ok=True)
        f.debut = time.monotonic()
        f.etat = EN_COURS
        with open(f.log, "wb") as sortie:
            f.groupe = self.lot.lancer(
                cmd,
                stdout=sortie,
                stderr=subprocess.STDOUT,
                env=dict(self.env, TMPDIR=tmp),
            )
            if f.groupe is None:
                # Le lot a été arrêté entre le test du drapeau et le
                # lancement : rien n'a démarré.
                f.duree = 0.0
                f.etat = ARRETE
                shutil.rmtree(tmp, ignore_errors=True)
                return
            try:
                rc = f.groupe.attendre(timeout=self.delai)
            except subprocess.TimeoutExpired:
                f.groupe.tuer()
                rc = None
        f.duree = time.monotonic() - f.debut
        try:
            restes = len(os.listdir(tmp))
        except OSError:
            restes = 0
        shutil.rmtree(tmp, ignore_errors=True)
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
        else:
            f.etat = self.campagne.verdict(rc, texte, f)
        # Un élément tué — délai ou Ctrl+C — n'a pas eu le temps de
        # nettoyer derrière lui : ses restes ne disent rien du test.
        if f.etat in (OK, ECHEC):
            f.restes = restes

    def phases(self):
        """Les numéros de phase présents, croissants."""
        return sorted({f.phase for f in self.fichiers})

    def lancer(self, fini=None):
        """Exécute tout, phase par phase ; `fini(f)` est appelé à la fin de
        chaque élément. Le démontage de la campagne tourne dans tous les
        cas, après la mort de tous les groupes."""
        self.debut = time.monotonic()

        def un(f):
            try:
                self._un(f)
            except Exception as exc:  # noqa: BLE001
                # Une faute du lanceur sur un élément le fait échouer, lui,
                # et le nomme ; elle n'arrête pas le passage en silence.
                f.etat = ECHEC
                f.duree = time.monotonic() - f.debut if f.debut else 0.0
                f.erreur_lanceur = f"{type(exc).__name__}: {exc}"
            if fini:
                fini(f)

        try:
            for rang, phase in enumerate(self.phases()):
                elements = [f for f in self.fichiers if f.phase == phase]
                if self.arret.is_set():
                    for f in elements:
                        f.etat = ARRETE
                    continue
                if rang:
                    self.campagne.entre_phases(self, phase)
                with ThreadPoolExecutor(max_workers=self.jobs) as pool:
                    list(pool.map(un, elements))
        finally:
            self.fin = time.monotonic()
            # Rien ne tourne plus : le démontage peut supprimer ce que les
            # éléments partageaient, bases comprises.
            self.lot.arreter(grace=0)
            self.campagne.demontage(self)

    def arreter(self, grace=None):
        """Plus rien ne démarre, et les groupes en cours sont arrêtés :
        SIGTERM, la grâce de la campagne, puis SIGKILL. Idempotent ; un
        second Ctrl+C pendant la grâce tue aussitôt."""
        self.arret.set()
        self.lot.arreter(grace)

    def arreter_et_attendre(self, fil):
        """Arrête le passage et attend la fin de `fil`, qui l'exécute :
        démontage de la campagne compris, qui supprime ce que les éléments
        partageaient (bases de test).

        Un Ctrl+C pendant la grâce passe aussitôt à SIGKILL. Pendant le
        démontage, chaque Ctrl+C est dit et l'attente reprend ; au
        ABANDON-ième, on rend la main en disant ce qui peut rester et
        comment le retirer."""
        try:
            self.arreter()
        except KeyboardInterrupt:
            try:
                self.lot.arreter(grace=0)
            except KeyboardInterrupt:
                pass
        interruptions = 0
        while fil.is_alive():
            try:
                fil.join()
            except KeyboardInterrupt:
                interruptions += 1
                if interruptions >= ABANDON:
                    print(
                        f"\n  {ROUGE}Démontage abandonné.{FIN}"
                        f" {self.campagne.si_abandon}",
                        flush=True,
                    )
                    return
                print(
                    f"\n  {JAUNE}Démontage en cours : ce que le passage a"
                    " créé se supprime, un instant"
                    f" (Ctrl+C encore {ABANDON - interruptions} fois pour"
                    f" abandonner).{FIN}",
                    flush=True,
                )

    def en_cours(self):
        return [f for f in self.fichiers if f.etat == EN_COURS]

    def nettoyer(self):
        shutil.rmtree(self.travail, ignore_errors=True)


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


def ligne(f, delai, unite="tests"):
    etat = f"{DELAI} {delai}s" if f.etat == DELAI else f.etat
    # Un élément qui n'est pas un fichier unittest — un scénario — n'a pas
    # de compte de tests : sa durée le remplace.
    compte = (
        f"{f.ran:>5} tests" if unite == "tests" else f"{f.duree:>5.0f} s    "
    )
    return "  %-42s %s %-14s %s%s%s" % (
        f.nom,
        compte,
        f.skipped,
        couleur(f.etat),
        etat,
        FIN,
    )


def restes_temporaires(lanceur):
    """Lignes d'avertissement : les éléments qui ont laissé des entrées
    dans leur TMPDIR. Le lanceur les a supprimées ; le test reste à
    corriger, car lancé hors du lanceur il les laisse dans /tmp. N'échoue
    pas la suite."""
    fautifs = sorted(
        (f for f in lanceur.fichiers if getattr(f, "restes", 0)),
        key=lambda f: f.nom,
    )
    if not fautifs:
        return []
    lignes = [
        f"  {JAUNE}Temporaires laissés (supprimés par le lanceur) :{FIN}"
    ]
    lignes += [f"    {f.nom}  ({f.restes})" for f in fautifs]
    return lignes


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
    if any(f.ran.isdigit() for f in lanceur.fichiers):
        total = sum(int(f.ran) for f in lanceur.fichiers if f.ran.isdigit())
        unite = "tests"
    else:
        # Des éléments qui ne sont pas des fichiers unittest : on les
        # compte eux-mêmes.
        total = len(lanceur.fichiers)
        unite = lanceur.campagne.unite
    # Un élément resté en attente ou en cours : le passage s'est arrêté
    # sans lui, ce n'est pas un succès.
    oublies = [f for f in lanceur.fichiers if f.etat in (ATTENTE, EN_COURS)]
    for f in lanceur.fichiers:
        if getattr(f, "erreur_lanceur", ""):
            print(f"  {ROUGE}{f.nom} : {f.erreur_lanceur}{FIN}")
    duree = f"{lanceur.fin - lanceur.debut:.0f} s, {lanceur.jobs} en parallèle"
    for texte in restes_temporaires(lanceur):
        print(texte)
    print("  ─────")
    arretes = [f for f in lanceur.fichiers if f.etat == ARRETE]
    if arretes:
        print(f"  {JAUNE}interrompu{FIN} ({duree})")
        return 130
    if oublies:
        print(f"  {ROUGE}{len(oublies)} élément(s) jamais terminé(s) :{FIN}")
        for f in sorted(oublies, key=lambda x: x.nom):
            print(f"    {f.nom}")
        return 1
    if any(f.echoue() for f in lanceur.fichiers):
        print(f"  {ROUGE}des échecs ci-dessus{FIN} ({duree})")
        return 1
    if unite == "tests" and not total:
        # -k qui ne retient rien, ou des fichiers vides : rien n'a été
        # vérifié, et le dire vaut mieux qu'un vert.
        print(f"  {JAUNE}aucun test exécuté{FIN} ({duree})")
        return 5
    print(f"  {VERT}{total} {unite}, tout vert{FIN} ({duree})")
    return 0


def en_ligne(lanceur):
    """L'affichage par défaut : une ligne par élément fini, un rappel pour
    ceux qui s'éternisent, et les éléments en cours nommés à Ctrl+C."""
    fil = threading.Thread(
        target=lanceur.lancer,
        kwargs={
            "fini": lambda f: print(
                ligne(f, lanceur.delai, lanceur.campagne.unite), flush=True
            )
        },
        daemon=True,
    )
    fil.start()
    rappel = lanceur.campagne.signal
    signale = {}
    try:
        while fil.is_alive():
            fil.join(timeout=1)
            for f in lanceur.en_cours():
                ecoule = f.ecoule()
                if (
                    ecoule >= rappel
                    and ecoule - signale.get(f.nom, 0) >= rappel
                ):
                    signale[f.nom] = ecoule
                    print(
                        f"  {JAUNE}… {f.nom} en cours depuis"
                        f" {ecoule:.0f} s{FIN}",
                        flush=True,
                    )
    except KeyboardInterrupt:
        tournaient = [(f.nom, f.ecoule()) for f in lanceur.en_cours()]
        print(f"\n  {JAUNE}Interrompu. En cours à cet instant :{FIN}")
        for nom, ecoule in sorted(tournaient, key=lambda x: -x[1]):
            print(f"    {nom}  {ecoule:.0f} s")
        lanceur.arreter_et_attendre(fil)
    return bilan(lanceur)


def ecoule_total(lanceur, maintenant=None):
    """Le temps écoulé depuis le début de la passe, arrêté à sa fin : une
    passe finie garde sa durée au lieu de compter jusqu'à ce qu'on quitte
    l'affichage."""
    if not lanceur.debut:
        return 0.0
    fin = lanceur.fin or (maintenant or time.monotonic())
    return fin - lanceur.debut


def tui(lanceur, titre="Tests unitaires"):
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
        TITLE = titre
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
            ecoule = ecoule_total(lanceur)
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
            # Quitter seulement : l'arrêt, qui attend la grâce, suit la
            # fermeture de l'écran au lieu de le geler.
            lanceur.arret.set()
            self.exit()

    vue = Vue()
    try:
        vue.run()
    finally:
        # Le fil du passage finit sur les groupes tués, puis démonte la
        # campagne : l'attendre avant le bilan, qui en dépend — y compris
        # quand un SIGTERM a fait sortir l'écran.
        fil = getattr(vue, "fil", None)
        if fil is not None and fil.is_alive():
            tournent = lanceur.en_cours()
            if tournent:
                print(
                    f"  {JAUNE}Arrêt : {len(tournent)} élément(s) reçoivent"
                    f" SIGTERM, {lanceur.campagne.grace:.0f} s de grâce"
                    f" (Ctrl+C pour tuer tout de suite).{FIN}",
                    flush=True,
                )
            lanceur.arreter_et_attendre(fil)
        else:
            lanceur.arreter()
    if not lanceur.fin:
        lanceur.fin = time.monotonic()
    for f in lanceur.fichiers:
        print(ligne(f, lanceur.delai, lanceur.campagne.unite))
    return bilan(lanceur)


def instables(lanceur):
    """Les éléments dont l'issue a varié d'un passage de --repeat à
    l'autre, avec le décompte de leurs issues."""
    # Un passage en tranches a une seule issue : la pire de ses tranches.
    # Comparées entre elles, deux tranches d'un même passage passeraient
    # pour un fichier instable.
    gravite = {OK: 0, DELAI: 1, ECHEC: 2}
    par_passage = {}
    for f in lanceur.fichiers:
        if f.etat in gravite:
            cle = (f.fichier, f.passage)
            pire = par_passage.get(cle)
            if pire is None or gravite[f.etat] > gravite[pire]:
                par_passage[cle] = f.etat
    par_fichier = {}
    for (nom, _passage), etat in par_passage.items():
        par_fichier.setdefault(nom, []).append(etat)
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
    élément. Un élément sans détail — tué par le délai, ou mort avant
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
                "etat": "erreur" if f.etat != OK else "ok",
                "message": ""
                if f.etat == OK
                else f"{f.etat} : aucun résultat par test",
            }
        ]
        for t in tests:
            comptes["tests"] += 1
            cas = ET.SubElement(
                suite,
                "testcase",
                classname=f"{os.path.splitext(f.fichier)[0]}"
                f".{t['classe']}".rstrip("."),
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


def bilan_des_echecs(fichiers):
    """(passés, échoués) : les noms d'éléments à retirer des échecs
    retenus, et ceux à y ajouter.

    Un élément ne sort des échecs retenus que si TOUS ses passages ont
    réussi : un seul échec sur N le garde, c'est ce qu'il faut relancer.
    Un passage arrêté n'a rien prouvé, dans un sens ni dans l'autre."""
    issues = {}
    for f in fichiers:
        issues.setdefault(f.fichier, set()).add(f.etat)
    passes = [n for n, e in issues.items() if e == {OK}]
    echoues = [n for n, e in issues.items() if e & {ECHEC, DELAI}]
    return passes, echoues
