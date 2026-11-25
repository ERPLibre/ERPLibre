#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Méta-test du catalogue des profils, sur les VRAIS parsers des outils.

Chaque option argparse de chaque outil de `profil.OUTILS` est un champ
(F), un alias (A) ou une exclusion justifiée (X) ; aucune entrée des
tables ne vise une option disparue ; un nom de secret ou de geste
dangereux est classé ; un secret ne s'écrit jamais en clair ; et une ligne
de commande valide le reste avec un profil plein.

Un échec nomme l'option et la table à compléter : ajouter une option à un
outil demande une ligne dans `CHAMPS`, `ALIAS` ou `EXCLUSIONS`.

`profil_isole` arme la couture `RACINE_PROFILS` et la garde du vrai
`private/production`. Les profils pleins vivent dans un dossier temporaire
hors de la couture et ne sont lus que par `--profile` explicite. Les
valeurs sont inventées (`odoo-exemple.service`, `exemple_db`,
`example.org`).
"""

import contextlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RACINE_DEPOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
sys.path.append(RACINE_DEPOT)
# Importé par son dossier et non par `test.` : sous le python3 du système,
# `test` est le paquet des tests de la bibliothèque standard.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from profil_isole import profil_isole  # noqa: E402

from script.lib_ops import profil  # noqa: E402

SERVICE = "odoo-exemple.service"
URL = "https://odoo.example.org"
SECRET_EN_CLAIR = "cle-en-clair-0d1e2f"

# Une valeur valide par champ F : le profil « plein » de la comparaison.
EXEMPLES = {
    "instance": {"db": "exemple_db"},
    "update_module": {
        "timeout": 600,
        "start_wait": 30,
        "ignore_error": ["exemple_module: champ obsolete"],
        "log_dir": "/var/tmp/exemple/journaux",
        "warmup_deep": True,
        "verbose": True,
    },
    "backup": {
        "dest": "/var/backups/exemple",
        "state_dir": "/var/lib/exemple/etat",
        "keep_daily": 5,
        "keep_weekly": 3,
        "keep_monthly": 6,
        "keep_recent_days": 1,
        "copy_to": "sauvegarde@backup.example.org:/srv/exemple",
        "max_age": 30,
        "timeout": 7200,
        "verbose": True,
    },
    "backup_timer": {
        "on_calendar": "*-*-* 02:30:00",
        "randomized_delay": "15min",
        "verbose": True,
    },
    "log_check": {
        "namespace": "exemple",
        "days": 5,
        "ignore": ["exemple_module: champ obsolete"],
        "state_dir": "/var/lib/exemple/log_check",
        "full_trace": True,
        "top": 5,
        "timeout": 60,
        "verbose": True,
    },
    "mail_retry": {"days": 14, "timeout": 120, "verbose": True},
    "health_check": {
        "url": [URL],
        "mail_domain": "example.org",
        "dkim_selector": "exemple",
        "timeout": 20,
        "verbose": True,
    },
    "warmup": {
        "timeout": 30,
        "max_pages": 10,
        "repeat": 2,
        "login": "lecteur_exemple",
        "api_key_file": "/var/lib/exemple/cle_api",
        "models": "res.partner,res.users",
        "strict": True,
    },
    "odoo_conf": {"cpus": 4, "memory_mb": 8192, "verbose": True},
    "host_perf_audit": {
        "duration": "5m",
        "interval": 10,
        "no_guests": True,
        "top": 4,
        "verbose": True,
    },
}

# Les modes de chaque outil : (argv, code sans profil, code avec le profil
# plein). Une ligne valide (0) le reste toujours ; un profil peut
# compléter une ligne incomplète (2, 0), jamais l'inverse.
CAS = {
    "update_module": [
        (["--module", "all", "--dry-run"], 0, 0),
        (
            [
                "--module",
                "base",
                "--db",
                "autre_db",
                "--no-backup",
                "--force",
                "--dry-run",
            ],
            0,
            0,
        ),
        (["--module", "base", "--ignore-error", "exemple: avis"], 0, 0),
        (["--module", "all", "--module", "base"], 2, 2),
    ],
    "backup": [
        (["--dry-run"], 0, 0),
        (["--status"], 0, 0),
        (["--test-restore", "--file", "/var/tmp/exemple.zip"], 0, 0),
        (
            [
                "--restore",
                "--file",
                "/var/tmp/exemple.zip",
                "--into",
                "autre_db",
            ],
            0,
            0,
        ),
        (["--keep-daily", "0", "--keep-weekly", "0", "--dry-run"], 0, 0),
        (["--into", "autre_db"], 2, 2),
        (["--restore"], 2, 2),
    ],
    "backup_timer": [
        (["--dry-run"], 0, 0),
        (["--uninstall", "--dry-run"], 0, 0),
        (
            [
                "--on-calendar",
                "daily",
                "--randomized-delay",
                "5min",
                "--keep-daily",
                "0",
                "--dry-run",
            ],
            0,
            0,
        ),
        (["--on-calendar", "02:30 \x1b"], 2, 2),
    ],
    "log_check": [
        (["--since-last"], 0, 0),
        (["--last", "3600", "--json"], 0, 0),
        (["--file", "/var/tmp/exemple.log", "--since-last"], 0, 0),
        (["--since", "2026-01-01", "--until", "2026-01-02"], 0, 0),
        (["--since-last", "--until", "2026-01-02"], 2, 2),
        (
            [
                "--namespace",
                "autre",
                "--file",
                "/var/tmp/exemple.log",
                "--since-last",
            ],
            2,
            2,
        ),
    ],
    "mail_retry": [
        (["--list"], 0, 0),
        (["--list", "--details", "--json"], 0, 0),
        (["--resend", "oldest", "3", "--yes"], 0, 0),
        (["--resend", "ids", "4,5", "--dry-run"], 0, 0),
        (["--resend", "jamais"], 2, 2),
        (["--list", "--resend", "all"], 2, 2),
    ],
    "health_check": [
        (["--local"], 0, 0),
        (["--url", "https://autre.example.org"], 0, 0),
        (["--local", "--mail-domain", "example.net"], 0, 0),
        (["--local", "--service", "odoo-exemple", "--json"], 0, 0),
        ([], 2, 0),
        (["--local", "--dkim-selector", "autre"], 2, 0),
        (["--url", URL, "--service", "odoo-exemple"], 2, 2),
    ],
    "warmup": [
        (["--deep", "--local"], 0, 0),
        (["--deep", "--url", "https://autre.example.org"], 0, 0),
        (["--deep", "--local", "--repeat", "1", "--strict"], 0, 0),
        (["--deep", "--local", "--login", "autre"], 2, 0),
        (["--deep", "--local", "--profile-unset", "login"], 0, 0),
        (["--deep", "--local", "--profile-unset", "api-key-file"], 0, 0),
        (["--deep", "--service", "odoo-exemple"], 2, 2),
    ],
    "odoo_conf": [
        ([], 0, 0),
        (["--file", "/var/tmp/exemple.conf", "--json"], 0, 0),
        (["--service", "odoo-exemple", "--odoo-version", "16"], 0, 0),
        (["--cpus", "2", "--memory-mb", "4096"], 0, 0),
        (["--odoo-version", "11"], 2, 2),
        (["--file", "/var/tmp/exemple.conf", "--service", "x"], 2, 2),
    ],
    "host_perf_audit": [
        ([], 0, 0),
        (["--duration", "90", "--json"], 0, 0),
        (["--no-guests", "--top", "2", "--csv", "/var/tmp/e.csv"], 0, 0),
        (["--duration", "0"], 2, 2),
    ],
}


def setUpModule():
    global DOSSIER_PROFILS
    DOSSIER_PROFILS = profil_isole()


def module_de(outil):
    return importlib.import_module(outil.module)


def parseur_de(outil):
    """Le parser de l'outil, méta-options comprises : `analyser` les
    ajoute aux outils de `lib_ops`, l'audit porte déjà son `--profile`."""
    module = module_de(outil)
    parser = module.construire_parseur()
    if outil.groupe != profil.GROUPE_HOTE:
        profil.ajouter_meta(parser, module.t)
    return parser


def actions(parser):
    return {action.dest: action for action in parser._actions}


def interdit(*args, **kwargs):
    raise AssertionError(f"process started: {args!r}")


class TestCouverture(unittest.TestCase):
    """Chaque option est F, A ou X ; aucune entrée de table n'est périmée."""

    def test_chaque_option_est_classee(self):
        for outil in profil.OUTILS:
            for dest, action in actions(parseur_de(outil)).items():
                with self.subTest(outil=outil.groupe, dest=dest):
                    self.assertIsNotNone(
                        profil.classer(outil.groupe, dest),
                        f"option {profil.option(action)} of"
                        f" {outil.groupe} has no field: add it to CHAMPS,"
                        " ALIAS or EXCLUSIONS with a reason",
                    )

    def test_un_seul_classement_par_option(self):
        for outil in profil.OUTILS:
            groupe = outil.groupe
            for dest in actions(parseur_de(outil)):
                tables = [
                    nom
                    for nom, table in (
                        ("CHAMPS", profil.CHAMPS.get(groupe, ())),
                        ("ALIAS", profil.ALIAS.get(groupe, {})),
                        ("EXCLUSIONS", profil.exclusions(groupe)),
                    )
                    if dest in table
                ]
                with self.subTest(outil=groupe, dest=dest):
                    self.assertLessEqual(len(tables), 1, tables)

    def test_aucun_champ_perime(self):
        parseurs = {o.groupe: actions(parseur_de(o)) for o in profil.OUTILS}
        parseurs[profil.GROUPE_INSTANCE] = parseurs["backup"]
        for groupe, cles in profil.CHAMPS.items():
            for cle in cles:
                with self.subTest(table="CHAMPS", champ=f"{groupe}.{cle}"):
                    self.assertIn(cle, parseurs[groupe])

    def test_aucun_alias_ni_exclusion_perime(self):
        for outil in profil.OUTILS:
            dests = actions(parseur_de(outil))
            for nom, table in (
                ("ALIAS", profil.ALIAS.get(outil.groupe, {})),
                ("EXCLUSIONS", profil.EXCLUSIONS.get(outil.groupe, {})),
            ):
                for dest in table:
                    with self.subTest(
                        table=nom, dest=f"{outil.groupe}.{dest}"
                    ):
                        self.assertIn(dest, dests)
        groupes = {o.groupe for o in profil.OUTILS}
        self.assertEqual(set(profil.ALIAS) - groupes, set())
        self.assertEqual(set(profil.EXCLUSIONS) - groupes, set())

    def test_exclusions_communes_presentes(self):
        """`help` et les méta-options existent dans chaque outil de
        `lib_ops` ; l'audit n'a que `--profile`."""
        for outil in profil.OUTILS:
            dests = actions(parseur_de(outil))
            attendues = set(profil.EXCLUSIONS_COMMUNES)
            if outil.groupe == profil.GROUPE_HOTE:
                attendues = {"help", "profile"}
            with self.subTest(outil=outil.groupe):
                self.assertEqual(attendues - set(dests), set())

    def test_regles_sur_des_options_existantes(self):
        parseurs = {o.groupe: actions(parseur_de(o)) for o in profil.OUTILS}
        parseurs[profil.GROUPE_INSTANCE] = parseurs["backup"]
        regles = {
            "CHEMINS": set(profil.CHEMINS),
            "MOTIFS": set(profil.MOTIFS),
            "INSTALLATION": set(profil.INSTALLATION),
            "BORNES": set(profil.BORNES),
            "SECRETS": set(profil.SECRETS),
            "NON_SECRETS": set(profil.NON_SECRETS),
            "ANODINS": set(profil.ANODINS),
            "DEPENDANCES": set(profil.DEPENDANCES)
            | set(profil.DEPENDANCES.values()),
        }
        groupe, cles, _minimum = profil.BORNE_SOMME
        regles["BORNE_SOMME"] = {(groupe, cle) for cle in cles}
        for nom, entrees in regles.items():
            for groupe, cle in entrees:
                with self.subTest(table=nom, champ=f"{groupe}.{cle}"):
                    self.assertIn(cle, profil.CHAMPS.get(groupe, ()))
                    self.assertIn(cle, parseurs[groupe])
        for conflit in profil.CONFLITS:
            with self.subTest(table="CONFLITS", dest=conflit.dest):
                dests = parseurs[conflit.groupe]
                self.assertIn(
                    profil.classer(conflit.groupe, conflit.dest), ("F", "A")
                )
                self.assertIn(conflit.dest, dests)
                for present in conflit.presents:
                    self.assertIn(present, dests)

    def test_raisons_connues(self):
        for outil in profil.OUTILS:
            for dest, raison in profil.exclusions(outil.groupe).items():
                with self.subTest(outil=outil.groupe, dest=dest):
                    self.assertIn(raison, profil.RAISONS)

    def test_alias_vers_un_champ(self):
        for groupe, alias in profil.ALIAS.items():
            for dest, (cible, cle) in alias.items():
                with self.subTest(alias=f"{groupe}.{dest}"):
                    self.assertIn(cle, profil.CHAMPS.get(cible, ()))
                    self.assertNotEqual(cible, groupe)

    def test_metadonnees_lisibles(self):
        """Chaque champ et alias porte un genre connu et une aide."""
        for outil in profil.OUTILS:
            parser = parseur_de(outil)
            champs = profil.champs(parser, outil.groupe)
            champs += profil.alias(parser, outil.groupe)
            for champ in champs:
                with self.subTest(outil=outil.groupe, dest=champ.dest):
                    self.assertIn(
                        champ.genre,
                        (
                            "bool_vrai",
                            "bool_faux",
                            "valeur",
                            "liste_append",
                            "liste_nargs",
                        ),
                    )
                    self.assertTrue(champ.aide)


class TestGardesParNom(unittest.TestCase):
    """Un nom de secret ou de geste dangereux n'échappe à aucune table."""

    def secret_classe(self, groupe, dest):
        classe = profil.classer(groupe, dest)
        if classe == "X":
            return True
        cible = (groupe, dest)
        if classe == "A":
            cible = profil.ALIAS[groupe][dest]
        return cible in profil.SECRETS or cible in profil.NON_SECRETS

    def test_garde_des_secrets(self):
        for outil in profil.OUTILS:
            for dest in actions(parseur_de(outil)):
                if not profil.GARDE_SECRETS.search(dest):
                    continue
                with self.subTest(outil=outil.groupe, dest=dest):
                    self.assertTrue(
                        self.secret_classe(outil.groupe, dest),
                        f"{outil.groupe}.{dest} looks like a secret: add it"
                        " to SECRETS, NON_SECRETS or EXCLUSIONS",
                    )

    def test_garde_des_gestes_dangereux(self):
        for outil in profil.OUTILS:
            for dest in actions(parseur_de(outil)):
                if not profil.GARDE_DANGER.search(dest):
                    continue
                with self.subTest(outil=outil.groupe, dest=dest):
                    self.assertTrue(
                        profil.classer(outil.groupe, dest) == "X"
                        or (outil.groupe, dest) in profil.ANODINS,
                        f"{outil.groupe}.{dest} is a dangerous action:"
                        " exclude it or add it to ANODINS with a reason",
                    )


class TestSecrets(unittest.TestCase):
    """Un secret ne s'écrit jamais en clair, ni ne s'affiche."""

    def setUp(self):
        temporaire = tempfile.TemporaryDirectory(prefix="erplibre-profil-")
        self.addCleanup(temporaire.cleanup)
        self.dossier = temporaire.name

    def champs_secrets(self):
        resultat = []
        for outil in profil.OUTILS:
            parser = parseur_de(outil)
            for champ in profil.champs(parser, outil.groupe):
                if champ.secret:
                    resultat.append(champ)
        return resultat

    def test_chaque_secret_est_un_champ_marque(self):
        secrets = {(c.groupe, c.cle) for c in self.champs_secrets()}
        self.assertEqual(secrets, set(profil.SECRETS))
        for champ in self.champs_secrets():
            self.assertEqual(champ.genre, "valeur")
            self.assertIsNone(champ.defaut)

    def test_valeur_en_clair_refusee_sans_echo(self):
        for champ in self.champs_secrets():
            for brut in (SECRET_EN_CLAIR, 42, {"kdbx": ""}):
                with self.subTest(champ=champ.cle, brut=brut):
                    with self.assertRaises(profil.ErreurProfil) as err:
                        profil.convertir(champ, brut)
                    self.assertNotIn(SECRET_EN_CLAIR, str(err.exception))

    def test_formes_admises(self):
        for champ in self.champs_secrets():
            self.assertEqual(
                profil.convertir(champ, "/var/lib/exemple/cle"),
                "/var/lib/exemple/cle",
            )
            self.assertIsInstance(
                profil.convertir(champ, {"kdbx": "Production/exemple"}),
                profil.Kdbx,
            )

    def test_ecriture_refusee_sans_fichier(self):
        chemin = os.path.join(self.dossier, SERVICE + ".json")
        for groupe, cle in profil.SECRETS:
            doc = {
                "version": profil.VERSION,
                "service": SERVICE,
                groupe: {cle: SECRET_EN_CLAIR},
            }
            with self.subTest(champ=f"{groupe}.{cle}"):
                with self.assertRaises(profil.ErreurProfil) as err:
                    profil.ecrire(chemin, doc)
                self.assertNotIn(SECRET_EN_CLAIR, str(err.exception))
                self.assertFalse(os.path.exists(chemin))

    def test_outil_refuse_sans_echo(self):
        """Le vrai outil sort en code 2 et ne cite pas la valeur."""
        warmup = profil.outil("warmup")
        chemin = os.path.join(self.dossier, SERVICE + ".json")
        with open(chemin, "w", encoding="utf-8") as fichier:
            json.dump(
                {
                    "version": 1,
                    "service": SERVICE,
                    "warmup": {"api_key_file": SECRET_EN_CLAIR},
                },
                fichier,
            )
        sortie, erreurs = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie):
            with contextlib.redirect_stderr(erreurs):
                with self.assertRaises(SystemExit) as fin:
                    module_de(warmup).analyser_profond(
                        ["--deep", "--local", "--profile", chemin]
                    )
        self.assertEqual(fin.exception.code, 2)
        self.assertIn("warmup.api_key_file", erreurs.getvalue())
        self.assertNotIn(SECRET_EN_CLAIR, erreurs.getvalue())
        self.assertNotIn(SECRET_EN_CLAIR, sortie.getvalue())


class TestProfilPlein(unittest.TestCase):
    """Une ligne de commande valide reste valide avec un profil plein."""

    @classmethod
    def setUpClass(cls):
        temporaire = tempfile.TemporaryDirectory(prefix="erplibre-profil-")
        cls.addClassCleanup(temporaire.cleanup)
        dossier = temporaire.name
        cls.profil_plein = os.path.join(dossier, SERVICE + ".json")
        doc = {"version": profil.VERSION, "service": SERVICE}
        for groupe, valeurs in EXEMPLES.items():
            if groupe != profil.GROUPE_HOTE:
                doc[groupe] = valeurs
        profil.ecrire(cls.profil_plein, doc)
        os.mkdir(os.path.join(dossier, "host"))
        cls.profil_hote = os.path.join(dossier, "host", "local.json")
        profil.ecrire(
            cls.profil_hote,
            {
                "version": profil.VERSION,
                "host": "local",
                profil.GROUPE_HOTE: EXEMPLES[profil.GROUPE_HOTE],
            },
        )

    def test_exemples_couvrent_chaque_champ(self):
        self.assertEqual(
            {g: set(v) for g, v in EXEMPLES.items()},
            {g: set(c) for g, c in profil.CHAMPS.items()},
        )
        self.assertEqual(
            set(CAS), {o.groupe for o in profil.OUTILS}, "a tool has no CAS"
        )

    def lancer(self, outil, argv):
        """(code, args) de l'entrée de l'outil, sans lanceur ni
        processus : 0 quand l'analyse aboutit, le code de SystemExit
        sinon."""
        entree = getattr(module_de(outil), outil.entree)
        with (
            mock.patch.object(subprocess, "Popen", interdit),
            mock.patch.object(subprocess, "run", interdit),
            mock.patch.object(os, "system", interdit),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            try:
                resultat = entree(list(argv))
            except SystemExit as fin:
                return fin.code, None
        if isinstance(resultat, tuple):
            resultat = resultat[0]
        return 0, resultat

    def profil_de(self, outil):
        if outil.groupe == profil.GROUPE_HOTE:
            return self.profil_hote
        return self.profil_plein

    def test_argv_minimal_valide_avec_le_profil_plein(self):
        for outil in profil.OUTILS:
            argv = list(outil.argv_minimal)
            argv += ["--profile", self.profil_de(outil)]
            with self.subTest(outil=outil.groupe):
                code, args = self.lancer(outil, argv)
                self.assertEqual(code, 0)
                if outil.groupe == profil.GROUPE_HOTE:
                    self.assertTrue(args.profil["values"])
                    self.assertEqual(args.profil["warnings"], [])
                else:
                    self.assertTrue(args.profil.actif)
                    self.assertTrue(args.profil.valeurs)
                    self.assertEqual(args.profil.inconnues, [])

    def test_meme_code_sans_et_avec_profil(self):
        for outil in profil.OUTILS:
            for argv, sans, avec in CAS[outil.groupe]:
                with self.subTest(outil=outil.groupe, argv=argv):
                    code, args = self.lancer(outil, argv)
                    self.assertEqual(code, sans, "without profile")
                    if args is not None:
                        if outil.groupe == profil.GROUPE_HOTE:
                            self.assertIsNone(args.profil)
                        else:
                            self.assertFalse(args.profil.actif)
                    argv_avec = argv + ["--profile", self.profil_de(outil)]
                    code, args = self.lancer(outil, argv_avec)
                    self.assertEqual(code, avec, "with the full profile")
                    if sans == 0:
                        self.assertEqual(code, 0)


# Profils PARTIELS : (groupe, réglages du profil, argv valide sans profil).
# Le profil plein porte toujours les deux moitiés d'une paire et des
# bornes respectées ; ces profils-ci n'en portent qu'une, ou des valeurs
# que la ligne de commande remplace toutes.
PARTIELS = (
    (
        "warmup",
        {"warmup": {"api_key_file": "/srv/cle"}},
        ["--deep", "--local"],
    ),
    (
        "warmup",
        {"warmup": {"api_key_file": "/srv/cle"}},
        ["--deep", "--url", URL],
    ),
    (
        "warmup",
        {"warmup": {"login": "lecteur_exemple"}},
        ["--deep", "--local"],
    ),
    (
        "backup",
        {
            "backup": {
                "keep_daily": 1,
                "keep_weekly": 0,
                "keep_monthly": 0,
                "keep_recent_days": 0,
            }
        },
        [
            "--dry-run",
            "--keep-daily",
            "7",
            "--keep-weekly",
            "4",
            "--keep-monthly",
            "6",
            "--keep-recent-days",
            "2",
        ],
    ),
    (
        "backup_timer",
        {
            "backup": {
                "keep_daily": 1,
                "keep_weekly": 0,
                "keep_monthly": 0,
                "keep_recent_days": 0,
            }
        },
        [
            "--dry-run",
            "--keep-daily",
            "7",
            "--keep-weekly",
            "4",
            "--keep-monthly",
            "6",
            "--keep-recent-days",
            "2",
        ],
    ),
)


class TestProfilPartiel(unittest.TestCase):
    """Un profil partiel ne fait pas échouer une ligne valide non plus."""

    def test_ligne_valide_avec_un_profil_partiel(self):
        lanceur = TestProfilPlein("test_meme_code_sans_et_avec_profil")
        with tempfile.TemporaryDirectory(prefix="erplibre-profil-") as bac:
            for rang, (groupe, reglages, argv) in enumerate(PARTIELS):
                outil = profil.outil(groupe)
                dossier = os.path.join(bac, str(rang))
                chemin = os.path.join(dossier, SERVICE + ".json")
                doc = {"version": profil.VERSION, "service": SERVICE}
                doc.update(reglages)
                profil.ecrire(chemin, doc)
                with self.subTest(groupe=groupe, argv=argv, doc=reglages):
                    code, _args = lanceur.lancer(outil, argv)
                    self.assertEqual(code, 0, "without profile")
                    code, args = lanceur.lancer(
                        outil, argv + ["--profile", chemin]
                    )
                    self.assertEqual(code, 0, "with the partial profile")
                    self.assertTrue(args.profil.actif)


class TestSansEffetDeBord(unittest.TestCase):
    """Importer un outil et construire son parser ne lance rien."""

    def test_construire_parseur_sans_processus(self):
        for outil in profil.OUTILS:
            module = module_de(outil)
            with self.subTest(outil=outil.groupe):
                with (
                    mock.patch.object(subprocess, "Popen", interdit),
                    mock.patch.object(subprocess, "run", interdit),
                    mock.patch.object(os, "system", interdit),
                ):
                    module.construire_parseur()

    def test_import_sans_processus(self):
        """Dans un interpréteur neuf, les imports des modules des outils ne
        lancent aucun processus."""
        modules = [o.module for o in profil.OUTILS]
        programme = (
            "import os, subprocess, sys, importlib\n"
            f"sys.path.insert(0, {RACINE_DEPOT!r})\n"
            "def interdit(*a, **k):\n"
            "    raise SystemExit('process started: %r' % (a,))\n"
            "subprocess.Popen = subprocess.run = os.system = interdit\n"
            f"for nom in {modules!r}:\n"
            "    importlib.import_module(nom).construire_parseur()\n"
        )
        resultat = subprocess.run(
            [sys.executable, "-c", programme],
            cwd=tempfile.gettempdir(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=120,
        )
        self.assertEqual(resultat.returncode, 0, resultat.stderr)


class TestNomsDesOptions(unittest.TestCase):
    def test_option_la_plus_longue(self):
        """Le nom affiché d'un champ est son option longue."""
        for outil in profil.OUTILS:
            parser = parseur_de(outil)
            for champ in profil.champs(parser, outil.groupe):
                with self.subTest(outil=outil.groupe, dest=champ.dest):
                    self.assertTrue(
                        re.fullmatch(r"--[a-z0-9-]+", champ.option),
                        champ.option,
                    )


if __name__ == "__main__":
    unittest.main()
