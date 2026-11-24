#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lance des fichiers de tests unitaires en parallèle, isolés de l'hôte.

Appelé par `run_unit_test.sh`, qui vérifie l'environnement et dresse la
liste des fichiers ; ce module ne choisit rien, il exécute ce qu'on lui
donne :

    run_unit_test.py [--tui] [--changed[=REF]] [--failed] [--watch]
                     [--repeat N] [--slowest N] [--junit FICHIER]
                     [--coverage] [-k MOTIF] [--ordre-aleatoire[=GRAINE]]
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

`--coverage` mesure la couverture du code ERPLibre (jeu « erplibre » de
couverture.py) : chaque fichier tourne sous « coverage run -p », ses
sous-processus Python compris, puis les données sont fusionnées, le JSON
produit et le passage ajouté à l'historique. Un passage partiel —
--changed, --failed, -k, des fichiers nommés — y est marqué comme tel. Les
durées n'en sont pas retenues : mesurées sous coverage, elles fausseraient
l'ordre et les tranches du passage suivant.

`-k MOTIF` ne garde que les tests dont le nom contient MOTIF, comme
unittest ; `--ordre-aleatoire[=GRAINE]` mélange les classes, et les tests
de chaque classe, dans un ordre rejouable : la graine est imprimée. Tous
deux passent chaque fichier par unit_file.py. Un test qui dépend d'un autre
du même fichier s'y révèle.

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
 - sudo, pkexec, doas, virsh, ssh et adb sont remplacés, en tête du PATH,
   par une commande qui refuse en le disant : un appel non bouchonné échoue
   de la même façon sur tous les postes, au lieu d'interroger les VM du
   poste ou le téléphone qui y est branché ;
 - chaque fichier a son propre TMPDIR, sous le répertoire de travail du
   lanceur : ce qu'un test oublie d'y supprimer est compté, nommé au bilan
   pour un fichier qui a fini de lui-même, puis supprimé dans tous les cas.
   La suite n'échoue pas pour autant ;
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
import glob
import os
import random
import re
import signal
import sys
import time

import couverture
import lanceur as moteur
import requirement_report
import unit_selection
from lanceur import (  # noqa: F401  (noms publics, repris par les tests)
    ARRETE,
    ATTENTE,
    DELAI,
    ECHEC,
    EN_COURS,
    FIN,
    JAUNE,
    OK,
    ROUGE,
    VERT,
    _lire,
    bilan,
    bilan_des_echecs,
    couleur,
    ecoule_total,
    ecrire_junit,
    en_ligne,
    instables,
    ligne,
    ordonner,
    plus_lents,
    restes_temporaires,
    tui,
)

# Un fichier dont la dernière durée connue dépasse ce nombre de secondes
# tourne en plusieurs processus, chacun avec une tranche de ses tests (voir
# unit_file.py) : la suite dure alors moins que son fichier le plus long.
# UNIT_TRANCHE=0 n'en découpe aucun.
SEUIL_TRANCHE = int(os.environ.get("UNIT_TRANCHE") or 30)

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
REFUSEES = {
    "sudo": 1,
    "pkexec": 1,
    "doas": 1,
    "virsh": 1,
    "ssh": 255,
    "adb": 1,
}

# Ce qu'une doublure accepte quand même : une question qui ne touche ni
# l'hôte ni le réseau. « ssh -V » en est une, et git-repo la pose à chaque
# « repo sync », même vers des dépôts file:// ; refusée, elle arrête la
# synchronisation sur « unable to detect ssh version ». La réponse suit le
# format d'OpenSSH, que git-repo analyse.
ACCEPTEES = {
    "ssh": {"-V": "OpenSSH_9.0p1, run_unit_test"},
}


# Un fichier de tests est un élément du moteur.
Fichier = moteur.Element


def lire_durees(chemin=DURATIONS):
    """{nom: secondes} du passage précédent ; vide si illisible."""
    return moteur.lire_durees(chemin)


def ecrire_durees(fichiers, chemin=DURATIONS):
    """Remplace les durées des fichiers finis, garde celles des autres
    (voir lanceur.ecrire_durees)."""
    moteur.ecrire_durees(fichiers, chemin)


def nombre_de_tranches(duree, jobs, seuil=None):
    """En combien de tranches lancer un fichier de durée connue `duree`
    (None si inconnue) : une par tranche de `seuil` secondes commencée, au
    plus `jobs`. Un seuil nul ne découpe rien."""
    seuil = SEUIL_TRANCHE if seuil is None else seuil
    return moteur.nombre_de_tranches(duree, jobs, seuil)


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
        # Comme le vrai ssh, « -V » répond sur la sortie d'erreur.
        accepte = "".join(
            f'[ "$*" = "{arg}" ] && {{ echo "{rep}" >&2; exit 0; }}\n'
            for arg, rep in ACCEPTEES.get(cmd, {}).items()
        )
        contenu = (
            "#!/bin/sh\n"
            + accepte
            + f'echo "run_unit_test : « {cmd} $* » refusé, un test'
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


def doublures(travail):
    """Le répertoire des doublures : DOUBLURES, ou `travail`/bin si
    DOUBLURES ne peut être créé ni écrit — un cache en lecture seule ne
    doit pas empêcher la suite de tourner, seulement le cache de « go
    test » de servir."""
    try:
        return poser_doublures(DOUBLURES)
    except OSError:
        return poser_doublures(os.path.join(travail, "bin"))


class CampagneUnitaire(moteur.Campagne):
    """Les tests unitaires : un fichier par élément, découpé en tranches
    au-delà de SEUIL_TRANCHE secondes, hermétique (doublures en tête du
    PATH, PYTHONPATH à la racine), et vert seulement si unittest l'a dit
    (« OK ») et que le code de retour est nul."""

    unite = "tests"
    prefixe = "run_unit_test."
    tranches = True
    fichier_durees = DURATIONS
    fichier_echecs = ECHECS

    def __init__(
        self, grace=None, couverture=False, motifs=(), ordre_aleatoire=None
    ):
        # UNIT_GRACE : secondes laissées à SIGTERM avant SIGKILL quand un
        # fichier est arrêté (délai, Ctrl+C). 0 par défaut : un test n'a
        # rien à sauver. Sous couverture, coverage écrit ses données sur
        # SIGTERM (sigterm = true) : 5 s par défaut.
        defaut = 5 if couverture else 0
        self.grace = (
            float(os.environ.get("UNIT_GRACE") or defaut)
            if grace is None
            else grace
        )
        self.couverture = couverture
        self.motifs = list(motifs)
        self.ordre_aleatoire = ordre_aleatoire

    # Lus au moment du lancement, pas à l'import : un test peut les régler.
    @property
    def seuil_tranche(self):
        return SEUIL_TRANCHE

    @property
    def signal(self):
        return SIGNAL

    def commande(self, lanceur, element, base):
        # « -u » : le journal reçoit la sortie standard ET la sortie
        # d'erreur. Sans terminal, la première ne se vide qu'à la fin du
        # processus, APRÈS le verdict qu'unittest écrit sur la seconde : les
        # dernières lignes que bilan() affiche montreraient ce que le test
        # imprime, et non l'erreur. L'option plutôt que PYTHONUNBUFFERED :
        # un programme que le test lance garde le tampon qu'il aurait hors
        # du lanceur.
        cmd = [lanceur.py, "-u", element.chemin]
        # Le fichier fixe sys.argv à l'import : -k ne lui parviendrait pas
        # en argument. unit_file.py filtre et mélange lui-même.
        if (
            lanceur.detaille
            or element.tranche
            or self.motifs
            or self.ordre_aleatoire
        ):
            cmd = [lanceur.py, "-u", UNIT_FILE, element.chemin, base + ".json"]
        if element.tranche:
            cmd += ["--tranche", f"{element.tranche[0]}/{element.tranche[1]}"]
        for motif in self.motifs:
            cmd += ["-k", motif]
        if self.ordre_aleatoire:
            cmd += [f"--ordre-aleatoire={self.ordre_aleatoire}"]
        if self.couverture:
            cmd = couverture.envelopper("erplibre", cmd)
        return cmd

    def env(self, lanceur, travail):
        # Les variables du registre des requis ne vont pas aux tests : aucun
        # n'en a besoin, et un test qui affiche son environnement mettrait
        # la clé dans son journal, donc dans le registre.
        env = {
            nom: valeur
            for nom, valeur in os.environ.items()
            if nom not in requirement_report.VARIABLES
        }
        env.update(
            PATH=doublures(travail) + os.pathsep + os.environ.get("PATH", ""),
            PYTHONPATH=".",
        )
        # Les données vont dans le répertoire du jeu, HORS du TMPDIR de
        # chaque fichier, que le lanceur supprime.
        if self.couverture:
            env.update(couverture.env("erplibre"))
        return env

    def verdict(self, rc, texte, element):
        if rc == 0 and re.search(r"^OK", texte, re.M):
            return OK
        return ECHEC


class Lanceur(moteur.Lanceur):
    """Le moteur, réglé par défaut pour les tests unitaires."""

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
        super().__init__(
            fichiers,
            py,
            jobs,
            delai,
            durees,
            passages,
            detaille,
            campagne or CampagneUnitaire(),
        )


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


def passage_complet(fichiers, args):
    """Vrai si le passage couvre TOUTE la suite : tous les test/test_*.py,
    sans sélection. Seul un passage complet se compare à un autre dans
    l'historique de couverture."""
    tous = {os.path.normpath(c) for c in glob.glob("test/test_*.py")}
    return (
        not (args.changed or args.failed or args.k)
        and {os.path.normpath(c) for c in fichiers} == tous
    )


def couvrir(lanceur, complet):
    """Après un passage sous --coverage : fusion, JSON, historique, et la
    ligne du bilan. Une couverture qui échoue ne change pas le verdict des
    tests : elle le dit."""
    incomplets = [
        f.nom for f in lanceur.fichiers if f.etat in (moteur.DELAI, ARRETE)
    ]
    try:
        if not couverture.combiner("erplibre"):
            print(f"  {JAUNE}Couverture : aucune donnée écrite.{FIN}")
            return
        couverture.produire_json("erplibre")
        couverture.historiser(
            "erplibre",
            complet=complet,
            incomplets=incomplets,
            duree=lanceur.fin - lanceur.debut,
        )
    except RuntimeError as exc:
        print(f"  {ROUGE}Couverture : {exc}{FIN}")
        return
    print(f"  {couverture.ligne_de_bilan('erplibre')}")
    print(f"    {couverture.chemin_json('erplibre')}")


def essais(lanceur):
    """Les fichiers finis, sous la forme que le registre des requis lit.

    Un fichier arrêté par Ctrl+C n'a rien prouvé et n'y figure pas. Un
    fichier en échec ou tué par le délai sans aucun test noté porte la fin
    de son journal comme panne : ses tests déclarés passent en erreur."""
    return [
        requirement_report.Essai(
            f.chemin,
            f.tests,
            (
                _lire(f.log, fin=40)
                if not f.tests and f.etat in (ECHEC, DELAI)
                else None
            ),
        )
        for f in lanceur.fichiers
        if f.etat in (OK, ECHEC, DELAI)
    ]


def lancer_une_fois(fichiers, args, surveille=False):
    """Un passage complet sur `fichiers` : exécution, bilan, rapports, et
    mise à jour des durées et des échecs retenus. Rend le code de sortie.

    Le verrou des campagnes est tenu tout le passage : une autre suite, ou
    les scénarios Odoo, partagent le serveur PostgreSQL.

    Avec les variables ERPLIBRE_REQUIREMENT_* (requirement_report.py),
    chaque test est noté puis son verdict poussé au registre des requis,
    après les rapports et les caches. Quand Ctrl+C ou SIGTERM arrête
    l'envoi, le code rendu reste celui de la suite ; sous --watch
    (`surveille`), c'est 130, qui met fin à la surveillance comme un
    Ctrl+C pendant les tests. Sans ces variables, rien de cela : ni détail
    par test, ni connexion."""
    try:
        with moteur.verrou_campagne("tests unitaires"):
            return _lancer_une_fois(fichiers, args, surveille)
    except moteur.CampagneOccupee as exc:
        print(f"  {ROUGE}{exc}{FIN}")
        print("  Attendre sa fin, ou l'arrêter, puis relancer.")
        return 2


def _lancer_une_fois(fichiers, args, surveille=False):
    registre = requirement_report.depuis_environnement()
    mesure = getattr(args, "coverage", False)
    if mesure:
        couverture.effacer("erplibre")
    graine = getattr(args, "ordre_aleatoire", None)
    if graine == "auto":
        # UNE graine pour tout le passage, imprimée : le même ordre se
        # rejoue par --ordre-aleatoire=GRAINE.
        graine = str(random.randrange(1, 1_000_000))
    if graine:
        print(f"  Ordre aléatoire, graine {graine}")
    lanceur = Lanceur(
        fichiers,
        py=sys.executable,
        jobs=args.jobs or os.cpu_count() or 4,
        delai=args.timeout,
        durees=lire_durees(),
        passages=args.repeat,
        detaille=bool(args.slowest or args.junit or registre),
        campagne=CampagneUnitaire(
            couverture=mesure,
            motifs=getattr(args, "k", None) or (),
            ordre_aleatoire=graine,
        ),
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
        filtre = bool(getattr(args, "k", None))
        if mesure:
            # Un passage interrompu n'a pas tout mesuré : il ne sert jamais
            # de référence.
            complet = passage_complet(fichiers, args) and not any(
                f.etat == ARRETE for f in lanceur.fichiers
            )
            couvrir(lanceur, complet)
        elif not filtre:
            # Sous -k, un fichier ne lance qu'une partie de ses tests : sa
            # durée fausserait l'ordre et les tranches du passage suivant.
            ecrire_durees(lanceur.fichiers)
        passes, echoues = bilan_des_echecs(lanceur.fichiers)
        if filtre:
            # Un fichier vert sous -k n'a passé que les tests retenus : il
            # ne sort pas des échecs retenus.
            passes = []
        unit_selection.retenir_echecs(ECHECS, passes=passes, echoues=echoues)
        # En dernier : un envoi lent, ou interrompu, ne coûte ni les durées
        # ni les échecs retenus. Une suite arrêtée par Ctrl+C n'envoie rien.
        if registre and code == 130:
            requirement_report.avertir(
                "suite interrompue, aucun verdict envoyé."
            )
        elif registre and registre.pousser(essais(lanceur)) and surveille:
            return 130
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
            # Un Ctrl+C pendant le passage — reçu par l'affichage, qui
            # arrête les tests, ou par l'envoi au registre — rend 130 : c'est
            # aussi la fin de --watch.
            if (
                concernes
                and lancer_une_fois(concernes, args, surveille=True) == 130
            ):
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
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("-k", action="append", metavar="MOTIF")
    parser.add_argument(
        "--ordre-aleatoire",
        dest="ordre_aleatoire",
        nargs="?",
        const="auto",
        metavar="GRAINE",
    )
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
        if args.coverage:
            # Chaque relance effacerait les données de la précédente : le
            # rapport ne dirait rien de cohérent.
            print("  --coverage ne se combine pas avec --watch.")
            return 2
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
