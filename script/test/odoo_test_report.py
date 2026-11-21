#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lance les tests de modules Odoo et pousse leurs verdicts au registre.

    ./script/test/odoo_test_report.py --modules a,b [--keep-db]

Le lanceur installe les modules sur une base JETABLE,
`erplibre_odoo_test_<aléatoire>`, avec `--test-tags /a,/b
--stop-after-init --log-level=test`, lit dans le journal d'Odoo le
résultat de chaque test, supprime la base (sauf `--keep-db`), écrit un
bilan et rend le code des tests : 0 tout vert, 1 un test en échec ou en
erreur, 2 un passage qui ne prouve rien — Odoo arrêté avant la fin de ses
tests (module qui ne s'installe pas, test qui ne s'importe pas), aucun test
lancé, module ou configuration introuvable. 130 : interrompu par Ctrl+C ou
SIGTERM, rien n'est envoyé.

Odoo ne démarre jamais avec le config.conf du dépôt : une configuration
est générée dans un répertoire temporaire, qui n'en reprend que
`addons_path` et l'accès à PostgreSQL. HTTP n'écoute que sur 127.0.0.1, sur
deux ports libres pris au lancement hors de PORTS_RESERVES (un HttpCase a
besoin du serveur), sans liste des bases, sans worker ni cron. Le
répertoire, et le filestore qu'il porte, partent avec la base.

Un test se désigne comme la sorte `python` du registre le documente : le
chemin pointé de sa méthode,
`odoo.addons.<module>.tests.<fichier>.<Classe>.<méthode>`. Avec les
variables ERPLIBRE_REQUIREMENT_* (requirement_report.py en décrit le
contrat et les garanties), chaque ligne `python` déclarée sous
`odoo.addons.<module>.` d'un module lancé reçoit son verdict, par
`Registre.pousser_verdicts` ; sans elles, aucune connexion et aucune ligne
de plus. Odoo ne reçoit jamais ces variables.

Une erreur de setUpClass ou de tearDownClass n'a pas de méthode : elle
note le préfixe de sa classe, que chaque méthode déclarée de la classe
reçoit. Un passage complet — Odoo écrit son bilan final et rend le code
des tests — a lancé tous les tests standard des modules : une référence
déclarée d'un module que rien n'a notée désigne un test renommé, supprimé
ou hors des étiquettes standard, et passe en erreur. Après un passage
incomplet, un module qu'Odoo n'a pas atteint met ses références déclarées
en erreur avec les erreurs du journal ; une référence que rien n'a notée
dans un module atteint garde son dernier verdict.
"""

import argparse
import configparser
import contextlib
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from collections import namedtuple

import requirement_report as rr

SORTE = "python"
PREFIXE_BASE = "erplibre_odoo_test_"

# Les ports qu'une instance du poste occupe d'ordinaire : jamais pris, même
# libres au moment du tirage.
PORTS_RESERVES = frozenset({8016, 8017, 8018, 8069, 8072, 8080})

# Les clés de config.conf reprises : les addons et l'accès à PostgreSQL.
# Tout le reste — base, filtre, journal, ports, mot de passe maître — est
# celui du dépôt et ne regarde pas un passage de tests.
CLES_REPRISES = ("db_host", "db_port", "db_user", "db_password", "db_sslmode")

# Variables d'environnement qu'Odoo ne reçoit pas : la clé du registre, et
# les réglages de tests qui fausseraient la lecture du journal — une
# reprise note deux fois le même test, un plafond d'échecs saute la suite.
VARIABLES_RETIREES = frozenset(rr.VARIABLES) | {
    "ODOO_TEST_FAILURE_RETRIES",
    "ODOO_TEST_MAX_FAILED_TESTS",
}

# Délai, en secondes, qu'Odoo a pour s'arrêter proprement après Ctrl+C.
DELAI_ARRET = 60

# Combien d'erreurs du journal accompagnent la panne d'un module.
ERREURS_GARDEES = 5
LIGNES_DE_FIN = 40

# En-tête d'une ligne du journal d'Odoo : date, pid, niveau, base, logger.
# Une ligne sans en-tête continue l'enregistrement précédent (une trace).
EN_TETE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} \d+ (?P<niveau>[A-Z_]+)"
    r" \S+ (?P<logger>[^\s:]+): ?(?P<message>.*)$"
)
# Le logger d'un fichier de tests, celui sous lequel OdooTestResult écrit.
MODULE_DE_TESTS = re.compile(r"^odoo\.addons\.[^.]+\.tests(\.|$)")
DEBUT = re.compile(r"^Starting (?P<test>\S+) \.\.\.$")
IGNORE = re.compile(r"^skipped (?P<test>.+?) : (?P<raison>.*)$", re.S)
ECHEC = re.compile(r"^(?P<sorte>FAIL|ERROR): (?P<test>[^\n]+)", re.S)
FIXTURE = re.compile(
    r"^(?P<fixture>setUpClass|tearDownClass) \((?P<classe>[\w.]+)\)$"
)
BILAN = re.compile(
    r"^(\d+) failed, (\d+) error\(s\) of (\d+) tests when loading database"
)
DUREE = re.compile(r"^\s*(?P<test>[\w.]+): (?P<duree>[\d.]+)s \d+ queries$")
NOM_DE_MODULE = re.compile(r"^\w+$")

# `verdicts` : {référence ou préfixe de classe: verdict} ; `fin` : (échecs,
# erreurs, tests) du bilan final d'Odoo, None s'il ne l'a pas atteint ;
# `erreurs` : les derniers enregistrements ERROR ou CRITICAL qui ne sont
# pas le résultat d'un test.
Analyse = namedtuple("Analyse", "verdicts fin erreurs")


class ConfigurationInvalide(Exception):
    """Le dépôt ne permet pas de lancer Odoo ; le message est lisible."""


def _enregistrements(lignes):
    """(niveau, logger, message) de chaque enregistrement du journal, le
    message réunissant ses lignes de continuation, espaces de fin ôtés."""
    courant = None
    for ligne in lignes:
        ligne = ligne.rstrip()
        trouve = EN_TETE.match(ligne)
        if trouve:
            if courant:
                yield courant[0], courant[1], "\n".join(courant[2]).rstrip()
            courant = (trouve["niveau"], trouve["logger"], [trouve["message"]])
        elif courant:
            courant[2].append(ligne)
    if courant:
        yield courant[0], courant[1], "\n".join(courant[2]).rstrip()


def _cle(logger, test):
    """(clé, clé de durée) du test que décrit `test` sous `logger`, ou
    (None, None) pour ce qui n'est pas un test d'un module.

    « Classe.méthode » sous le logger de son fichier donne la référence
    complète ; un sous-test, « Subtest Classe.méthode (i=1) », est rangé
    sous sa méthode. « setUpClass (chemin.de.la.Classe) » donne le préfixe
    de la classe. La clé de durée est celle du rapport détaillé
    d'odoo.tests.stats, le chemin sans « odoo.addons. » ni « .tests »."""
    fixture = FIXTURE.match(test)
    if fixture:
        classe = fixture["classe"]
        if not MODULE_DE_TESTS.match(classe):
            return None, None
        return f"{classe}.", _cle_de_duree(f"{classe}.{fixture['fixture']}")
    if not MODULE_DE_TESTS.match(logger):
        return None, None
    test = test.removeprefix("Subtest ").split(" ", 1)[0]
    reference = f"{logger}.{test}"
    return reference, _cle_de_duree(reference)


def _cle_de_duree(chemin):
    module, _, reste = chemin.removeprefix("odoo.addons.").partition(".")
    return f"{module}.{reste.removeprefix('tests.')}"


def analyser(lignes):
    """L'Analyse des lignes d'un journal d'Odoo en `--log-level=test`.

    OdooTestResult écrit « Starting C.m ... » avant chaque test, puis
    « FAIL: », « ERROR: » ou « skipped » s'il ne réussit pas ; un test
    commencé sans rien de plus a réussi. Plusieurs notes d'un même test —
    ses sous-tests — se résument à la plus grave. La durée vient du rapport
    détaillé d'odoo.tests.stats (`--log-handler=odoo.tests.stats:DEBUG`),
    0.0 sans lui."""
    commences = []
    notes = {}
    durees = {}
    cles_de_duree = {}
    erreurs = []
    fin = None
    for niveau, logger, message in _enregistrements(lignes):
        debut = DEBUT.match(message)
        ignore = IGNORE.match(message)
        echec = ECHEC.match(message) if niveau == "ERROR" else None
        bilan = BILAN.match(message) if logger == "odoo.tests.result" else None
        if debut:
            cle, duree = _cle(logger, debut["test"])
            if cle:
                commences.append(cle)
                cles_de_duree[cle] = duree
            continue
        if ignore or echec:
            cle, duree = _cle(logger, (ignore or echec)["test"])
            if cle:
                cles_de_duree[cle] = duree
                if ignore:
                    note = ("skipped", ignore["raison"])
                elif echec["sorte"] == "FAIL":
                    note = ("failed", message)
                else:
                    note = ("error", message)
                notes.setdefault(cle, []).append(note)
                continue
        if bilan:
            fin = tuple(int(n) for n in bilan.groups())
        elif logger == "odoo.tests.stats":
            for ligne in message.splitlines()[1:]:
                trouve = DUREE.match(ligne)
                if trouve:
                    durees[trouve["test"]] = float(trouve["duree"])
        elif niveau in ("ERROR", "CRITICAL"):
            erreurs.append(message)
    for cle in commences:
        notes.setdefault(cle, [("passed", None)])
    verdicts = {}
    for cle, liste in notes.items():
        duree = durees.get(cles_de_duree.get(cle), 0.0)
        verdicts[cle] = rr._pire(
            [rr._verdict(resultat, log, duree) for resultat, log in liste]
        )
    return Analyse(
        verdicts, fin, "\n".join(erreurs[-ERREURS_GARDEES:]) or None
    )


def parse_odoo_test_log(lignes):
    """{référence: verdict} des tests que le journal `lignes` note ; une
    erreur de fixture de classe est notée sous le préfixe de sa classe,
    `odoo.addons.<module>.tests.<fichier>.<Classe>.`. Un verdict est
    {"result": passed|failed|error|skipped, "log": str|None, "duration"}."""
    return analyser(lignes).verdicts


def passage_complet(rc, analyse):
    """Vrai si Odoo a lancé tous les tests standard des modules : il a
    écrit son bilan final ET rendu le code des tests, 0 ou 1. Le bilan
    seul ne suffit pas : quand la phase post_install lève, Odoo 18 écrit
    quand même le bilan du registre déjà chargé, puis rend 255."""
    return analyse.fin is not None and rc in (0, 1)


def code_de_sortie(rc, analyse):
    """0 tout vert, 1 un test en échec ou en erreur, 2 un passage qui ne
    prouve rien : passage incomplet (`passage_complet`) ou aucun test
    lancé."""
    if not passage_complet(rc, analyse) or not analyse.fin[2]:
        return 2
    echecs, erreurs, _total = analyse.fin
    mauvais = any(
        v["result"] in ("failed", "error") for v in analyse.verdicts.values()
    )
    return 1 if rc or echecs or erreurs or mauvais else 0


def options_reprises(source):
    """{clé: valeur} que la configuration d'un passage reprend du texte
    `source` de config.conf : addons_path et CLES_REPRISES, quand elles
    ont une valeur. ConfigurationInvalide sans addons_path."""
    lu = configparser.ConfigParser(interpolation=None)
    try:
        lu.read_string(source)
    except configparser.Error as exc:
        raise ConfigurationInvalide(f"config.conf illisible : {exc}") from None
    options = lu["options"] if lu.has_section("options") else {}
    valeurs = {}
    for cle in ("addons_path",) + CLES_REPRISES:
        valeur = (options.get(cle) or "").strip()
        if valeur and valeur != "False":
            valeurs[cle] = valeur
    if "addons_path" not in valeurs:
        raise ConfigurationInvalide("config.conf ne donne pas d'addons_path")
    return valeurs


def configuration(source, data_dir, http_port, gevent_port):
    """Le texte de la configuration d'Odoo d'un passage, tirée du texte
    `source` de config.conf. ConfigurationInvalide sans addons_path."""
    valeurs = options_reprises(source)
    valeurs.update(
        {
            "data_dir": data_dir,
            "http_enable": "True",
            "http_interface": "127.0.0.1",
            "http_port": str(http_port),
            "gevent_port": str(gevent_port),
            "list_db": "False",
            "workers": "0",
            "max_cron_threads": "0",
        }
    )
    ecrit = configparser.ConfigParser(interpolation=None)
    ecrit["options"] = valeurs
    texte = []
    ecrit.write(_Lignes(texte))
    return "".join(texte)


class _Lignes:
    """Fichier minimal pour ConfigParser.write : garde ce qu'on y écrit."""

    def __init__(self, morceaux):
        self.write = morceaux.append


def ports_libres():
    """(http_port, gevent_port) : deux ports distincts, libres sur
    127.0.0.1 au moment du tirage, hors de PORTS_RESERVES."""
    exclus = set(PORTS_RESERVES)
    ports = []
    while len(ports) < 2:
        with socket.socket() as sonde:
            sonde.bind(("127.0.0.1", 0))
            port = sonde.getsockname()[1]
        if port not in exclus:
            exclus.add(port)
            ports.append(port)
    return tuple(ports)


def commande_odoo(python, odoo_bin, conf, base, modules):
    """La commande qui installe `modules` sur `base` et lance leurs tests
    standard, avec le rapport détaillé des durées."""
    return [
        python,
        odoo_bin,
        "-c",
        conf,
        "-d",
        base,
        "-i",
        ",".join(modules),
        "--test-tags",
        ",".join(f"/{m}" for m in modules),
        "--stop-after-init",
        "--log-level=test",
        "--log-handler=odoo.tests.stats:DEBUG",
    ]


def environnement_odoo(env):
    """`env` sans VARIABLES_RETIREES."""
    return {k: v for k, v in env.items() if k not in VARIABLES_RETIREES}


def chemins_odoo(racine):
    """(python, odoo-bin, texte de config.conf) du dépôt `racine`.

    La version d'Odoo vient de .odoo-version, le venv d'Odoo de
    .erplibre-version (`.venv.<contenu>`, comme odoo_bin.sh).
    ConfigurationInvalide si l'un manque."""

    def lire(nom):
        chemin = os.path.join(racine, nom)
        try:
            with open(chemin, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            raise ConfigurationInvalide(f"{nom} introuvable") from None

    version = lire(".odoo-version").strip()
    venv = lire(".erplibre-version").strip()
    python = os.path.join(racine, f".venv.{venv}", "bin", "python")
    odoo_bin = os.path.join(racine, f"odoo{version}", "odoo", "odoo-bin")
    for chemin in (python, odoo_bin):
        if not os.path.isfile(chemin):
            raise ConfigurationInvalide(
                f"{os.path.relpath(chemin, racine)} introuvable"
            )
    return python, odoo_bin, lire("config.conf")


def modules_absents(modules, addons_path, racine):
    """Les `modules` qu'aucun répertoire de `addons_path` ne porte ; un
    chemin relatif l'est à `racine`."""
    chemins = [
        os.path.join(racine, chemin.strip())
        for chemin in addons_path.split(",")
        if chemin.strip()
    ]
    return [
        m
        for m in modules
        if not any(
            os.path.isfile(os.path.join(c, m, "__manifest__.py"))
            for c in chemins
        )
    ]


def executer(commande, env, sortie=None):
    """(code, lignes) de `commande`, sa sortie et son erreur réunies,
    recopiées sur `sortie` au fil de l'eau quand elle est donnée.

    Le processus tourne dans sa propre session : Ctrl+C au terminal
    n'atteint que ce lanceur, qui demande alors à Odoo de s'arrêter
    (SIGTERM, puis SIGKILL après DELAI_ARRET) et relève KeyboardInterrupt."""
    processus = subprocess.Popen(
        commande,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    lignes = []
    try:
        for ligne in processus.stdout:
            lignes.append(ligne)
            if sortie is not None:
                sortie.write(ligne)
                sortie.flush()
        return processus.wait(), lignes
    except KeyboardInterrupt:
        processus.terminate()
        try:
            processus.wait(timeout=DELAI_ARRET)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            processus.kill()
            processus.wait()
        raise


@contextlib.contextmanager
def _sans_interruption():
    """Ctrl+C et SIGTERM ignorés le temps du bloc : la suppression de la
    base va à son terme. Hors du fil principal, où signal ne s'installe
    pas, le bloc s'exécute tel quel."""
    try:
        anciens = {
            s: signal.signal(s, signal.SIG_IGN)
            for s in (signal.SIGINT, signal.SIGTERM)
        }
    except ValueError:
        anciens = {}
    try:
        yield
    finally:
        for numero, ancien in anciens.items():
            signal.signal(numero, ancien)


def _supprimer(executant, python, odoo_bin, conf, base, env, sortie):
    """Supprime `base` et son filestore par `odoo-bin db drop` ; une ligne
    d'avertissement si elle reste, rien si elle n'a jamais été créée."""
    commande = [python, odoo_bin, "db", "-c", conf, "drop", base]
    with _sans_interruption():
        try:
            rc, lignes = executant(commande, env)
        except OSError as exc:
            rc, lignes = None, [str(exc)]
    if rc == 0 or any("does not exist" in ligne for ligne in lignes):
        return
    rr.avertir(
        f"base {base} non supprimée ({''.join(lignes[-1:]).strip()}) ;"
        f" à supprimer à la main : dropdb {base}",
        sortie=sortie,
    )


def _ecrire_bilan(analyse, modules, rc, code, sortie):
    """Le bilan du passage : un décompte, puis une ligne par test qui n'a
    pas réussi, ou la raison d'un passage qui ne prouve rien."""
    compte = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for verdict in analyse.verdicts.values():
        compte[verdict["result"]] += 1
    print(
        f"\n  Tests Odoo ({', '.join(modules)}) : {compte['passed']}"
        f" réussi(s), {compte['failed']} en échec, {compte['error']} en"
        f" erreur, {compte['skipped']} ignoré(s).",
        file=sortie,
    )
    for cle in sorted(analyse.verdicts):
        resultat = analyse.verdicts[cle]["result"]
        if resultat == "passed":
            continue
        nom = (
            f"{cle[:-1]} (setUpClass ou tearDownClass)"
            if cle.endswith(".")
            else cle
        )
        print(f"    {resultat:8} {nom}", file=sortie)
    if code == 2:
        if not passage_complet(rc, analyse):
            derniere = (analyse.erreurs or "").strip().splitlines()[-1:]
            raison = (
                f"Odoo s'est arrêté avant la fin de ses tests (code {rc})"
                + (f" : {derniere[0]}" if derniere else "")
            )
        else:
            raison = "aucun test lancé"
        print(
            f"  {rr.JAUNE}Passage sans preuve : {raison}.{rr.FIN}", file=sortie
        )


def _verdicts_a_pousser(analyse, modules, lignes, rc):
    """({clé: verdict}, {préfixe: libellé}) à résoudre contre le registre.

    Après un passage complet (`passage_complet`), chaque module est
    complet. Sinon, un module dont aucun test n'a été noté met ses
    références déclarées en erreur, avec les erreurs du journal ou, à
    défaut, sa fin ; un module dont un test a été noté garde ses verdicts,
    et ses références que rien n'a notées, leur dernier verdict."""
    verdicts = dict(analyse.verdicts)
    if passage_complet(rc, analyse):
        return verdicts, {
            f"odoo.addons.{m}.": f"odoo.addons.{m} (--test-tags /{m})"
            for m in modules
        }
    journal = analyse.erreurs or "".join(lignes[-LIGNES_DE_FIN:])
    for module in modules:
        prefixe = f"odoo.addons.{module}."
        if not any(cle.startswith(prefixe) for cle in verdicts):
            verdicts[prefixe] = rr._verdict(
                "error",
                f"Odoo s'est arrêté avant les tests de {module} :\n{journal}",
                0.0,
            )
    return verdicts, {}


def principal(
    argv=None, env=None, racine=None, executer=executer, sortie=None
):
    """Le passage entier ; rend le code de sortie."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--modules", required=True, help="modules à tester, séparés par ,"
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="garder la base et sa configuration après le passage",
    )
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    racine = racine or rr.RACINE
    sortie = sortie or sys.stdout

    modules = list(
        dict.fromkeys(m.strip() for m in args.modules.split(",") if m.strip())
    )
    invalides = [m for m in modules if not NOM_DE_MODULE.match(m)]
    if not modules or invalides:
        print(f"  Modules invalides : {args.modules!r}.", file=sortie)
        return 2
    try:
        python, odoo_bin, source = chemins_odoo(racine)
        addons_path = options_reprises(source)["addons_path"]
    except ConfigurationInvalide as exc:
        print(f"  Configuration du dépôt : {exc}.", file=sortie)
        return 2
    absents = modules_absents(modules, addons_path, racine)
    if absents:
        print(
            "  Module(s) introuvable(s) dans addons_path :"
            f" {', '.join(absents)}.",
            file=sortie,
        )
        return 2
    # Lu avant le passage : une configuration incomplète se dit tout de
    # suite, pas après de longues minutes de tests.
    registre = rr.depuis_environnement(env, sortie)

    base = PREFIXE_BASE + secrets.token_hex(4)
    dossier = tempfile.mkdtemp(prefix="odoo_test_report_")
    conf = os.path.join(dossier, "odoo.conf")
    descripteur = os.open(conf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as fh:
        fh.write(
            configuration(
                source, os.path.join(dossier, "data"), *ports_libres()
            )
        )
    env_odoo = environnement_odoo(env)
    print(
        f"  Tests Odoo de {', '.join(modules)} sur la base jetable {base}.",
        file=sortie,
    )
    rc, lignes, interrompu = None, [], False
    try:
        rc, lignes = executer(
            commande_odoo(python, odoo_bin, conf, base, modules),
            env_odoo,
            sortie,
        )
    except KeyboardInterrupt:
        interrompu = True
    except OSError as exc:
        lignes = [f"{exc}\n"]
    finally:
        if args.keep_db:
            print(f"  Base {base} gardée ; configuration {conf}.", file=sortie)
        else:
            _supprimer(
                executer, python, odoo_bin, conf, base, env_odoo, sortie
            )
            shutil.rmtree(dossier, ignore_errors=True)
    if interrompu:
        print("  Interrompu : aucun verdict envoyé.", file=sortie)
        return 130
    analyse = analyser(lignes)
    code = code_de_sortie(rc, analyse)
    _ecrire_bilan(analyse, modules, rc, code, sortie)
    if registre:
        verdicts, complets = _verdicts_a_pousser(analyse, modules, lignes, rc)
        registre.pousser_verdicts(
            verdicts,
            SORTE,
            [f"odoo.addons.{m}.%" for m in modules],
            racine=racine,
            sortie=sortie,
            complets=complets,
        )
    return code


def _interrompre(_signal, _cadre):
    raise KeyboardInterrupt


def main(argv=None):
    # SIGTERM comme Ctrl+C : Odoo est arrêté et la base supprimée.
    signal.signal(signal.SIGTERM, _interrompre)
    return principal(argv)


if __name__ == "__main__":
    sys.exit(main())
