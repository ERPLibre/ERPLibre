#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lance les scénarios du générateur de code Odoo en parallèle, un
processus et une session par scénario.

    run_odoo_scenarios.py [--json FICHIER] [--scenario NOM]... [-k MOTIF]...
                          [--failed] [--tui] [--junit FICHIER]
                          [--slowest N] [--jobs N] [--timeout S]
                          [--coverage] [--keep_cache]
                          [--ignore_init_check_git]
    run_odoo_scenarios.py --purge [--oui]

Appelé par run_odoo_scenarios.sh, qui fournit l'interpréteur de
.venv.erplibre. Les scénarios sont les entrées actives de
script/test/config_testcase.odoo<V>.json, validées par un schéma strict
(scenarios_odoo.py) ; chacun est exécuté par scenario_odoo.py.

Déroulé :
 1. validation du JSON et choix des scénarios (--scenario : noms exacts,
    -k : sous-chaîne ou motif fnmatch, --failed : en échec au passage
    précédent) ;
 2. verrou des campagnes : ni la suite unitaire ni une autre campagne ne
    tournent sur la base en même temps ;
 3. contrôle git des dépôts du générateur (sauf --ignore_init_check_git) :
    un dépôt modifié annule le passage, le résultat d'un scénario
    dépendant de ce qui est commité ;
 4. phases, par `sequence` croissante, avec barrière ; avant chaque phase
    suivante, les fichiers déclarés du dépôt d'origine sont restaurés ;
 5. démontage, quelle que soit l'issue : suppression des bases du passage
    (test_scn_<passage>_…), restauration des fichiers déclarés, puis
    contrôle git des dépôts du générateur — un dépôt propre au départ et
    sale à la fin fait échouer la campagne.

Chaque scénario reçoit un environnement nettoyé : .venv.erplibre/bin puis
les doublures (sudo, ssh, virsh… refusés) en tête du PATH ; ni PYTHONPATH,
ni ODOO_RC, ni ODOO_MODE_*, ni COVERAGE_* hérités du shell. Il a
ODOO_SCENARIO_TIMEOUT secondes (3600), puis SIGTERM, 60 s de grâce pour
supprimer sa base, et SIGKILL. `--jobs` (ou ODOO_SCENARIO_JOBS) borne le
parallélisme ; par défaut, tous les scénarios d'une phase partent
ensemble.

--keep_cache garde les bacs à sable sous
~/.cache/erplibre/odoo_scenarios/<passage>/<scénario>/ et les bases.
--coverage mesure les processus Odoo (jeu « odoo » de couverture.py,
conf/coverage.odoo.cfg) puis fusionne et historise. --purge supprime,
après confirmation, les bases test_scn_* et test_demo_* que des passages
tués ont laissées.

Les journaux des scénarios sont concaténés dans
./.venv.<.erplibre-version>/make_test.log, que lit check_result_test.sh.
"""

import argparse
import configparser
import os
import signal
import subprocess
import sys
import threading

_ICI = os.path.dirname(os.path.abspath(__file__))
_RACINE = os.path.dirname(os.path.dirname(_ICI))
if _RACINE not in map(os.path.abspath, sys.path):
    sys.path.append(_RACINE)

from script.test import couverture  # noqa: E402
from script.test import lanceur as moteur  # noqa: E402
from script.test import scenario_odoo, scenarios_odoo  # noqa: E402
from script.test import unit_selection  # noqa: E402

ROUGE = moteur.ROUGE
VERT = moteur.VERT
JAUNE = moteur.JAUNE
FIN = moteur.FIN

NOM = "scénarios Odoo"
SCENARIO = os.path.join(_ICI, "scenario_odoo.py")

# Les commandes refusées et le code d'échec que leur appelant attend.
REFUSEES = {
    "sudo": 1,
    "pkexec": 1,
    "doas": 1,
    "virsh": 1,
    "ssh": 255,
    "adb": 1,
}

# Variables du shell qui changent ce que font run.sh et odoo_bin.sh.
_RETIREES = ("PYTHONPATH", "ODOO_RC")
_PREFIXES_RETIRES = ("ODOO_MODE_", "COVERAGE_")


def cache_erplibre():
    return os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
        "erplibre",
    )


def poser_doublures(dossier):
    """Écrit dans `dossier` les commandes refusées ; rend `dossier`."""
    os.makedirs(dossier, exist_ok=True)
    for cmd, code in REFUSEES.items():
        chemin = os.path.join(dossier, cmd)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(
                "#!/bin/sh\n"
                f'echo "run_odoo_scenarios : « {cmd} $* » refusé, un'
                " scénario ne touche pas l'hôte\" >&2\n"
                f"exit {code}\n"
            )
        os.chmod(chemin, 0o755)
    return dossier


def environnement(base, racine, doublures=None, extra=None):
    """L'environnement des scénarios, tiré de `base` : .venv.erplibre/bin
    puis `doublures` (si donné) en tête du PATH, sans les variables qui
    changeraient le lancement d'Odoo, plus `extra`."""
    env = {
        k: v
        for k, v in base.items()
        if k not in _RETIREES and not k.startswith(_PREFIXES_RETIRES)
    }
    tete = [os.path.join(racine, ".venv.erplibre", "bin")]
    if doublures:
        tete.append(doublures)
    env["PATH"] = os.pathsep.join(tete + [base.get("PATH", "")])
    env.update(extra or {})
    return env


def environnement_pg(racine, base):
    """`base` complété pour que « psql » joigne le serveur et le rôle
    d'Odoo : db_host, db_port, db_user et db_password de config.conf
    quand ils portent une valeur (Odoo écrit « False » sinon)."""
    env = dict(base)
    lecteur = configparser.RawConfigParser()
    try:
        lecteur.read(os.path.join(racine, "config.conf"))
    except configparser.Error:
        pass
    for option, variable in (
        ("db_host", "PGHOST"),
        ("db_port", "PGPORT"),
        ("db_user", "PGUSER"),
        ("db_password", "PGPASSWORD"),
    ):
        valeur = lecteur.get("options", option, fallback="").strip()
        if valeur and valeur != "False":
            env[variable] = valeur
    env["PGDATABASE"] = "postgres"
    env["PGCONNECT_TIMEOUT"] = "10"
    return env


def lister_bases(racine, env):
    """Les noms de toutes les bases du serveur, ou None si « psql » ne
    répond pas. « -X » écarte le ~/.psqlrc, « -w » toute invite."""
    try:
        res = subprocess.run(
            ["psql", "-XtAqw", "-c", "SELECT datname FROM pg_database"],
            # Hors du groupe du terminal : un Ctrl+C pendant le démontage ne
            # coupe pas la commande en cours.
            start_new_session=True,
            cwd=racine,
            env=environnement_pg(racine, env),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    return [
        ligne.strip() for ligne in res.stdout.splitlines() if ligne.strip()
    ]


def supprimer_base(racine, env, odoo_bin, nom):
    """Rend (code, sortie) de « odoo_bin.sh db drop --if-exists nom ».

    Borné par DELAI_DROP : le démontage attend sa fin sans céder à Ctrl+C,
    et un DROP qui attend un verrou le figerait sinon. Au délai, le code
    est 124 et la sortie le dit."""
    try:
        res = subprocess.run(
            [odoo_bin, "db", "drop", "--if-exists", nom],
            # Hors du groupe du terminal : un Ctrl+C pendant le démontage
            # ne coupe pas un DROP en cours.
            start_new_session=True,
            cwd=racine,
            env=dict(env, PGCONNECT_TIMEOUT="10"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=scenario_odoo.DELAI_DROP,
        )
    except subprocess.TimeoutExpired:
        return 124, f"délai de {scenario_odoo.DELAI_DROP} s dépassé"
    return res.returncode, (res.stdout + res.stderr).strip()


def depot_propre(racine, depot):
    """True si `git status --porcelain` est vide, False sinon, None si le
    dépôt est absent ; et la sortie de git."""
    chemin = os.path.join(racine, depot)
    if not os.path.isdir(chemin):
        return None, ""
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=chemin,
        capture_output=True,
        text=True,
        # Hors du groupe du terminal : un Ctrl+C pendant le démontage ne
        # le tue pas, ce qui le ferait passer pour un dépôt modifié.
        start_new_session=True,
        stdin=subprocess.DEVNULL,
    )
    return res.returncode == 0 and not res.stdout.strip(), res.stdout


class CampagneOdoo(moteur.Campagne):
    """Les scénarios du générateur : un scénario par élément, verdict par
    code de retour, phases tirées de `sequence`, démontage par préfixe de
    passage. Voir le docstring du module."""

    unite = "scénarios"
    prefixe = "odoo_scenarios."
    si_abandon = (
        "Des bases du passage peuvent rester, et des fichiers du"
        " générateur rester modifiés : ./script/test/run_odoo_scenarios.sh"
        " --purge les supprime, git status les montre."
    )
    tranches = False
    signal = 300
    grace = 60.0

    def __init__(
        self,
        json,
        run_id,
        entrees,
        version,
        racine=_RACINE,
        coverage=False,
        keep_cache=False,
    ):
        self.json = os.path.abspath(json)
        self.run_id = run_id
        self.entrees = entrees
        self.version = version
        self.racine = racine
        self.coverage = coverage
        self.keep_cache = keep_cache
        self.odoo_bin = "./odoo_bin.sh"
        cache = cache_erplibre()
        self.fichier_durees = os.path.join(cache, "odoo_scenarios.durations")
        self.fichier_echecs = os.path.join(cache, "odoo_scenarios.failed")
        self.dossier_bacs = os.path.join(cache, "odoo_scenarios", run_id)
        self.depots = scenarios_odoo.depots_du_generateur(version)
        self.chemins_declares = sorted(
            {c for e in entrees for c in scenarios_odoo.chemins_origine(e)}
        )
        # Rempli par releve_initial().
        self.propres_au_depart = {}
        self.restaurables = []
        # Ce que le démontage rapporte, affiché après le passage : le
        # démontage tourne dans le fil du lanceur, sous la TUI peut-être.
        self.messages = []
        # Les défauts qui font échouer la campagne.
        self.problemes = []
        self.env_scenarios = None
        self.demonte = threading.Event()

    def releve_initial(self):
        """Note quels dépôts du générateur et quels chemins déclarés sont
        propres avant le passage : seuls ceux-là sont restaurés, puis
        contrôlés, à la fin."""
        for depot in self.depots:
            self.propres_au_depart[depot] = depot_propre(self.racine, depot)[0]
        self.restaurables = [
            c
            for c in self.chemins_declares
            if scenario_odoo.chemin_propre(self.racine, c)
        ]

    def commande(self, lanceur, element, base):
        cmd = [
            lanceur.py,
            "-u",
            SCENARIO,
            "--json",
            self.json,
            "--name",
            element.fichier,
            "--run-id",
            self.run_id,
            "--detail",
            base + ".json",
            "--racine",
            self.racine,
        ]
        if self.coverage:
            cmd.append("--coverage")
        if self.keep_cache:
            cmd += [
                "--keep-cache",
                os.path.join(self.dossier_bacs, element.fichier),
            ]
        return cmd

    def env(self, lanceur, travail):
        extra = couverture.env("odoo") if self.coverage else {}
        self.env_scenarios = environnement(
            os.environ,
            self.racine,
            poser_doublures(os.path.join(travail, "bin")),
            extra,
        )
        return self.env_scenarios

    def restaurer(self):
        """git checkout des chemins déclarés propres au départ et modifiés
        depuis."""
        for chemin in self.restaurables:
            if scenario_odoo.chemin_propre(self.racine, chemin):
                continue
            rc, sortie = scenario_odoo.restaurer_chemin(self.racine, chemin)
            if rc == 0:
                self.messages.append(f"{chemin} restauré")
            else:
                self.problemes.append(
                    f"{chemin} : restauration en échec ({rc}) {sortie}"
                )

    def entre_phases(self, lanceur, phase):
        self.restaurer()

    def supprimer_bases(self):
        """Supprime les bases du passage trouvées dans pg_database, et
        elles seules."""
        env = self.env_scenarios or dict(os.environ)
        prefixe = scenarios_odoo.prefixe_bases(self.run_id)
        bases = lister_bases(self.racine, env)
        if bases is None:
            self.problemes.append(
                "psql ne répond pas : les bases du passage"
                f" ({prefixe}*) n'ont pas pu être vérifiées"
            )
            return
        for nom in sorted(b for b in bases if b.startswith(prefixe)):
            if self.keep_cache:
                self.messages.append(f"base gardée : {nom}")
                continue
            rc, sortie = supprimer_base(self.racine, env, self.odoo_bin, nom)
            if rc == 0:
                self.messages.append(f"base {nom} supprimée au démontage")
            else:
                self.problemes.append(
                    f"base {nom} : suppression en échec ({rc}) {sortie}"
                )

    def controle_final(self):
        for depot in self.depots:
            avant = self.propres_au_depart.get(depot)
            if avant is None:
                continue
            if avant is False:
                self.messages.append(
                    f"{depot} était déjà modifié au départ : non contrôlé"
                )
                continue
            propre, sortie = depot_propre(self.racine, depot)
            if propre is False:
                self.problemes.append(
                    f"{depot} modifié par le passage :\n{sortie.rstrip()}"
                )

    def demontage(self, lanceur):
        try:
            self.supprimer_bases()
            self.restaurer()
            self.controle_final()
        finally:
            self.demonte.set()


def controle_initial(racine, depots):
    """Le contrôle git des dépôts du générateur, par le script que les
    scénarios utilisent. Rend vrai si tous sont propres."""
    ok = True
    for depot in depots:
        res = subprocess.run(
            [scenario_odoo.CHECK_GIT, depot],
            cwd=racine,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        print((res.stdout + res.stderr).rstrip())
        ok = ok and res.returncode == 0
    return ok


def ecrire_make_test_log(lanceur, chemin):
    """Les journaux des scénarios, dans l'ordre du lanceur, chacun sous
    un en-tête « Test execution N - PASS|FAIL - nom »."""
    with open(chemin, "w", encoding="utf-8") as fh:
        for rang, f in enumerate(lanceur.fichiers, start=1):
            etat = (
                f"{VERT}PASS{FIN}"
                if f.etat == moteur.OK
                else f"{ROUGE}FAIL{FIN}"
            )
            fh.write(f"\nTest execution {rang} - {etat} - {f.nom}\n\n")
            texte = moteur._lire(f.log) if f.log else ""
            if texte:
                fh.write(texte)
                fh.write("\n")


def chemin_make_test_log(racine):
    try:
        with open(os.path.join(racine, ".erplibre-version")) as fh:
            version = fh.read().strip()
    except OSError:
        return None
    dossier = os.path.join(racine, f".venv.{version}")
    if not version or not os.path.isdir(dossier):
        return None
    return os.path.join(dossier, "make_test.log")


def rapports(lanceur, args):
    if args.slowest:
        print(f"  Les {args.slowest} étapes les plus lentes :")
        for duree, fichier, ident in moteur.plus_lents(lanceur, args.slowest):
            print(f"    {duree:8.2f} s  {fichier}  {ident.split('.', 1)[-1]}")
    if args.junit:
        moteur.ecrire_junit(lanceur, args.junit)
        print(f"  JUnit : {args.junit}")


def couverture_finale(lanceur, args):
    """Fusionne, produit le JSON et historise le jeu « odoo »."""
    try:
        if not couverture.combiner("odoo"):
            print(f"  {JAUNE}Couverture : aucun processus n'a écrit{FIN}")
            return
        couverture.produire_json("odoo")
        couverture.historiser(
            "odoo",
            # Un passage interrompu n'a pas tout mesuré : il ne sert
            # jamais de référence.
            complet=not (args.k or args.scenario or args.failed)
            and not any(
                f.etat in (moteur.ARRETE, moteur.ATTENTE, moteur.EN_COURS)
                for f in lanceur.fichiers
            ),
            incomplets=[
                f.fichier
                for f in lanceur.fichiers
                if f.etat in (moteur.DELAI, moteur.ARRETE)
            ],
            duree=lanceur.fin - lanceur.debut,
        )
        print(f"  {couverture.ligne_de_bilan('odoo')}")
    except RuntimeError as exc:
        print(f"  {ROUGE}Couverture : {exc}{FIN}")


def purger(racine, oui):
    """Supprime les bases test_scn_* et test_demo_* après confirmation."""
    env = environnement(os.environ, racine)
    bases = lister_bases(racine, env)
    if bases is None:
        print(f"  {ROUGE}psql ne répond pas.{FIN}")
        return 1
    cibles = sorted(
        b for b in bases if b.startswith(("test_scn_", "test_demo_"))
    )
    if not cibles:
        print("  Aucune base test_scn_* ni test_demo_* à purger.")
        return 0
    for nom in cibles:
        print(f"    {nom}")
    if not oui:
        if not sys.stdin.isatty():
            print("  --purge sans terminal : confirmer par --oui.")
            return 1
        reponse = input(f"  Supprimer ces {len(cibles)} bases ? [o/N] ")
        if reponse.strip().lower() not in ("o", "oui", "y", "yes"):
            print("  Rien supprimé.")
            return 0
    code = 0
    for nom in cibles:
        rc, sortie = supprimer_base(racine, env, "./odoo_bin.sh", nom)
        if rc:
            code = 1
            print(f"  {ROUGE}{nom} : {sortie}{FIN}")
        else:
            print(f"  {nom} supprimée")
    return code


def passage(args, racine, version, json, choisis):
    """Un passage complet sur les entrées `choisis` ; rend le code de
    sortie. Appelé sous le verrou des campagnes."""
    if not args.ignore_init_check_git:
        depots = scenarios_odoo.depots_du_generateur(version)
        if not controle_initial(racine, depots):
            print(
                f"  {ROUGE}✗ Dépôts du générateur modifiés : passage"
                f" annulé (--ignore_init_check_git pour passer outre).{FIN}"
            )
            return 1
    if args.coverage:
        if not couverture.disponible("odoo"):
            print(
                f"  {ROUGE}✗ --coverage : coverage manque dans"
                f" {couverture.jeu('odoo').python}.{FIN}"
            )
            return 1
        couverture.effacer("odoo")
    run_id = scenarios_odoo.nouveau_run_id()
    campagne = CampagneOdoo(
        json,
        run_id,
        choisis,
        version,
        racine=racine,
        coverage=args.coverage,
        keep_cache=args.keep_cache,
    )
    campagne.releve_initial()
    jobs = (
        args.jobs
        or int(os.environ.get("ODOO_SCENARIO_JOBS") or 0)
        or scenarios_odoo.jobs_par_defaut(choisis)
    )
    lanceur = moteur.Lanceur(
        scenarios_odoo.elements(choisis),
        py=sys.executable,
        jobs=jobs,
        delai=args.timeout,
        durees=moteur.lire_durees(campagne.fichier_durees),
        detaille=bool(args.slowest or args.junit),
        campagne=campagne,
    )
    print(
        f"  passage {run_id} : {len(choisis)} scénario(s),"
        f" {lanceur.jobs} en parallèle, délai {args.timeout} s"
    )
    try:
        code = None
        if args.tui and sys.stdout.isatty():
            code = moteur.tui(lanceur, titre="Scénarios Odoo")
            if code is None:
                print("  Textual absent : affichage en ligne.")
        if code is None:
            code = moteur.en_ligne(lanceur)
        rapports(lanceur, args)
        for message in campagne.messages:
            print(f"  {message}")
        for probleme in campagne.problemes:
            print(f"  {ROUGE}✗ {probleme}{FIN}")
        if campagne.problemes:
            code = code or 1
        moteur.ecrire_durees(lanceur.fichiers, campagne.fichier_durees)
        passes, echoues = moteur.bilan_des_echecs(lanceur.fichiers)
        unit_selection.retenir_echecs(
            campagne.fichier_echecs, passes=passes, echoues=echoues
        )
        if args.coverage:
            couverture_finale(lanceur, args)
        if args.keep_cache:
            print(f"  Bacs gardés sous {campagne.dossier_bacs}")
        journal = chemin_make_test_log(racine)
        if journal:
            ecrire_make_test_log(lanceur, journal)
            print(
                f"  Log file {journal if code == 0 else ROUGE + journal + FIN}"
            )
        return code
    finally:
        lanceur.arreter()
        lanceur.nettoyer()


def _interrompre(_signal, _cadre):
    raise KeyboardInterrupt


def analyser(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", metavar="FICHIER")
    parser.add_argument(
        "--scenario", action="append", default=[], metavar="NOM"
    )
    parser.add_argument("-k", action="append", default=[], metavar="MOTIF")
    parser.add_argument("--failed", action="store_true")
    parser.add_argument("--tui", action="store_true")
    parser.add_argument("--junit", metavar="FICHIER")
    parser.add_argument("--slowest", type=int, default=0, metavar="N")
    parser.add_argument(
        "--jobs", "-p", "--max_process", type=int, default=0, metavar="N"
    )
    parser.add_argument(
        "--no_parallel", dest="jobs", action="store_const", const=1
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("ODOO_SCENARIO_TIMEOUT") or 3600),
    )
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--keep_cache", action="store_true")
    parser.add_argument("--ignore_init_check_git", action="store_true")
    parser.add_argument("--purge", action="store_true")
    parser.add_argument("--oui", action="store_true")
    return parser.parse_args(argv)


def main(argv=None, racine=_RACINE):
    args = analyser(argv)
    # SIGTERM comme Ctrl+C : les scénarios tournent dans leur propre
    # session, et un lanceur tué sans les arrêter laisserait leurs bases.
    signal.signal(signal.SIGTERM, _interrompre)
    os.chdir(racine)
    try:
        version = scenarios_odoo.lire_version(racine)
    except OSError as exc:
        print(f"  {ROUGE}✗ .odoo-version illisible : {exc}{FIN}")
        return 2
    json = args.json or scenarios_odoo.json_par_defaut(racine, version)
    try:
        with open(json, encoding="utf-8") as fh:
            entrees = scenarios_odoo.charger_et_valider(fh.read())
    except (OSError, scenarios_odoo.SchemaInvalide) as exc:
        print(f"  {ROUGE}✗ {json} : {exc}{FIN}")
        return 2
    echecs = None
    if args.failed:
        echecs = unit_selection.echecs_retenus(
            os.path.join(cache_erplibre(), "odoo_scenarios.failed")
        )
    try:
        choisis = scenarios_odoo.selectionner(
            entrees, args.k, args.scenario, echecs
        )
    except ValueError as exc:
        print(f"  {ROUGE}✗ {exc}{FIN}")
        return 2
    if not args.purge and not choisis:
        print("  Aucun scénario à lancer.")
        return 0
    try:
        with moteur.verrou_campagne(NOM):
            if args.purge:
                return purger(racine, args.oui)
            return passage(args, racine, version, json, choisis)
    except moteur.CampagneOccupee as exc:
        print(f"  {ROUGE}✗ {exc}{FIN}")
        return 1
    except KeyboardInterrupt:
        print(f"\n  {JAUNE}Interrompu.{FIN}")
        return 130


if __name__ == "__main__":
    sys.exit(main())
