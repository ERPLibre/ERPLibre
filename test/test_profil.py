#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""script/lib_ops/profil : résolution, lecture sûre, validation,
application à un parser, écriture atomique, tables.

La bibliothèque est essayée seule : les parsers sont des répliques réduites
de ceux des outils, avec leurs vraies `dest`. Aucun systemctl réel n'est
appelé, aucun profil réel n'est lu : `profil_isole` arme la couture
`RACINE_PROFILS` et une garde fait échouer tout accès au vrai
`private/production`. Les noms sont inventés (`odoo-exemple.service`,
`exemple_db`, `example.org`).
"""

import argparse
import collections
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)
# Importé par son dossier et non par `test.` : sous le python3 du système,
# `test` est le paquet des tests de la bibliothèque standard.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from profil_isole import VRAI_DOSSIER, etat, profil_isole  # noqa: E402

from script.lib_ops import profil, service  # noqa: E402

SERVICE = "odoo-exemple.service"
ENV_SOUS_PROCESSUS = "ERPLIBRE_TEST_PROFIL_SOUS_PROCESSUS"


def setUpModule():
    global DOSSIER_MODULE, ETAT_INITIAL
    ETAT_INITIAL = etat()
    DOSSIER_MODULE = profil_isole()


def t(texte):
    return texte


TYPES = service.types_argparse(t)


def _type_regex(valeur):
    try:
        return re.compile(valeur)
    except re.error as err:
        raise argparse.ArgumentTypeError(str(err))


Cible = collections.namedtuple("Cible", "hote")


def _type_url(valeur):
    if not valeur.startswith("https://"):
        raise argparse.ArgumentTypeError(f"invalid URL: {valeur}")
    return Cible(valeur[len("https://") :])


def p_update():
    p = argparse.ArgumentParser(prog="update_module")
    p.add_argument("--module", dest="modules", action="append", required=True)
    p.add_argument("--service", type=TYPES.unite)
    p.add_argument("--db", type=TYPES.base)
    p.add_argument("--odoo-conf")
    p.add_argument("--user", type=TYPES.utilisateur)
    p.add_argument("--timeout", type=TYPES.secondes, default=1800)
    p.add_argument("--start-wait", type=TYPES.secondes, default=90)
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--backup-dest", default="/var/backups/erplibre")
    p.add_argument("--state-dir", default="/var/lib/erplibre-backup")
    p.add_argument("--force", action="store_true")
    p.add_argument(
        "--ignore-error", action="append", type=_type_regex, default=[]
    )
    p.add_argument("--log-dir")
    p.add_argument("--warmup-deep", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def p_backup():
    p = argparse.ArgumentParser(prog="odoo_backup")
    modes = p.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--test-restore", action="store_true")
    modes.add_argument("--restore", action="store_true")
    p.add_argument("--file")
    p.add_argument("--into", type=TYPES.base)
    p.add_argument("--service", type=TYPES.unite)
    p.add_argument("--db", type=TYPES.base)
    p.add_argument("--odoo-conf")
    p.add_argument("--user", type=TYPES.utilisateur)
    p.add_argument("--dest", default="/var/backups/erplibre")
    p.add_argument("--state-dir", default="/var/lib/erplibre-backup")
    p.add_argument("--keep-daily", type=TYPES.entier, default=7)
    p.add_argument("--keep-weekly", type=TYPES.entier, default=4)
    p.add_argument("--keep-monthly", type=TYPES.entier, default=12)
    p.add_argument("--keep-recent-days", type=TYPES.entier, default=2)
    p.add_argument("--copy-to")
    p.add_argument("--max-age", type=TYPES.secondes, default=26)
    p.add_argument("--force-space", action="store_true")
    p.add_argument("--timeout", type=TYPES.secondes, default=21600)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def p_log(exclusif_days=False):
    p = argparse.ArgumentParser(prog="log_check")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--service", type=TYPES.unite)
    source.add_argument("--file")
    p.add_argument("--namespace")
    fenetre = p.add_mutually_exclusive_group()
    fenetre.add_argument("--since-last", action="store_true")
    fenetre.add_argument("--last", type=TYPES.secondes)
    fenetre.add_argument("--since")
    fenetre.add_argument("--by-hour", action="store_true")
    if exclusif_days:
        fenetre.add_argument("--days", type=TYPES.secondes, default=7)
    else:
        p.add_argument("--days", type=TYPES.secondes, default=7)
    p.add_argument("--until")
    p.add_argument("--ignore", action="append", type=_type_regex, default=[])
    p.add_argument("--state-dir", default="/var/lib/erplibre-logcheck")
    p.add_argument("--json", action="store_true")
    p.add_argument("--full-trace", action="store_true")
    p.add_argument("--top", type=TYPES.secondes, default=15)
    p.add_argument("--timeout", type=TYPES.secondes, default=300)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def p_health():
    p = argparse.ArgumentParser(prog="health_check")
    p.add_argument("--url", action="append", type=_type_url, default=[])
    p.add_argument("--local", action="store_true")
    p.add_argument("--service", type=TYPES.unite)
    p.add_argument("--mail-domain")
    p.add_argument("--dkim-selector")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--json", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def p_warmup(type_cle=None):
    p = argparse.ArgumentParser(prog="warmup_http")
    p.add_argument("-c", "--config")
    p.add_argument("-d", "--database")
    p.add_argument("--log")
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--deep", action="store_true")
    p.add_argument("--url")
    p.add_argument("--local", action="store_true")
    p.add_argument("--service")
    p.add_argument("--max-pages", type=int, default=20)
    p.add_argument("--repeat", type=int, default=4)
    p.add_argument("--login")
    p.add_argument("--api-key-file", type=type_cle)
    p.add_argument("--models", default="res.partner")
    p.add_argument("--strict", action="store_true")
    p.add_argument("odoo_args", nargs="*")
    return p


class FauxLanceur:
    """Répond depuis une table {argv joint: (code, sortie)} et note les
    appels."""

    def __init__(self, reponses=None, interdit=False):
        self.reponses = reponses or {}
        self.interdit = interdit
        self.appels = []

    def __call__(self, argv, timeout=60):
        if self.interdit:
            raise AssertionError(f"unexpected command: {argv}")
        self.appels.append(list(argv))
        return self.reponses.get(" ".join(argv), (1, "unknown"))


def lanceur_devinette(racine, unite=SERVICE):
    return FauxLanceur(
        {
            "systemctl list-units --type=service --all --no-legend --plain": (
                0,
                f"{unite} loaded active running Odoo\n",
            ),
            f"systemctl show -p WorkingDirectory -- {unite}": (
                0,
                f"WorkingDirectory={racine}\n",
            ),
        }
    )


class Base(unittest.TestCase):
    """Un dossier de profils et un faux checkout propres à chaque test."""

    def setUp(self):
        temporaire = tempfile.TemporaryDirectory(prefix="erplibre-profil-")
        self.addCleanup(temporaire.cleanup)
        self.tmp = temporaire.name
        self.profils = os.path.join(self.tmp, "profils")
        os.mkdir(self.profils, 0o755)
        self.racine = os.path.join(self.tmp, "checkout")
        os.mkdir(self.racine, 0o755)
        patch = mock.patch.object(profil, "RACINE_PROFILS", self.profils)
        patch.start()
        self.addCleanup(patch.stop)

    def poser(self, doc, service_=SERVICE, dossier=None, mode=0o644):
        """Écrit `doc` tel quel (dict ou texte) ; rend le chemin."""
        dossier = dossier or self.profils
        chemin = os.path.join(dossier, f"{service_}.json")
        texte = doc if isinstance(doc, str) else json.dumps(doc)
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write(texte)
        os.chmod(chemin, mode)
        return chemin

    def doc(self, **groupes):
        resultat = {"version": 1, "service": SERVICE}
        resultat.update(groupes)
        return resultat

    def analyser(self, parser, argv, groupe, **options):
        """`profil.analyser` ; rend (args, application, stderr)."""
        erreurs = io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            resultat = profil.analyser(
                parser, argv, groupe, t, self.racine, **options
            )
        return resultat[0], resultat[-1], erreurs.getvalue()

    def refus(self, parser, argv, groupe, **options):
        """`profil.analyser` qui doit sortir en code 2 ; rend stderr."""
        erreurs = io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            with self.assertRaises(SystemExit) as sortie:
                profil.analyser(
                    parser, argv, groupe, t, self.racine, **options
                )
        self.assertEqual(sortie.exception.code, 2, erreurs.getvalue())
        return erreurs.getvalue()


class TestResolution(Base):
    def test_explicite_pose_le_service(self):
        chemin = self.poser(
            self.doc(update_module={"timeout": 60}), dossier=self.tmp
        )
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertTrue(app.actif)
        self.assertEqual(app.chemin, chemin)
        self.assertEqual(args.timeout, 60)
        self.assertEqual(args.service, SERVICE)
        self.assertEqual(app.origine("service"), "profil")
        self.assertEqual(app.origine("timeout"), "profil")
        self.assertEqual(app.origine("start_wait"), "defaut")
        self.assertIs(args.profil, app)

    def test_par_service_normalise(self):
        self.poser(self.doc(update_module={"timeout": 61}))
        lanceur = FauxLanceur(interdit=True)
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--service", "odoo-exemple"],
            "update_module",
            lanceur=lanceur,
        )
        self.assertEqual(args.timeout, 61)
        self.assertEqual(args.service, SERVICE)
        self.assertEqual(app.origine("service"), "cli")
        self.assertIsNone(app.unite_devinee)

    def test_devinette_avec_un_lanceur(self):
        self.poser(self.doc(update_module={"timeout": 62}))
        lanceur = lanceur_devinette(self.racine)
        args, app, _ = self.analyser(
            p_update(), ["--module", "all"], "update_module", lanceur=lanceur
        )
        self.assertEqual(app.unite_devinee, (SERVICE, "workdir"))
        self.assertEqual(args.timeout, 62)
        # L'unité devinée n'est pas posée : la détection garde son origine.
        self.assertIsNone(args.service)

    def test_sans_lanceur_aucune_devinette(self):
        self.poser(self.doc(update_module={"timeout": 63}))
        args, app, _ = self.analyser(
            p_update(), ["--module", "all"], "update_module"
        )
        self.assertFalse(app.actif)
        self.assertEqual(args.timeout, 1800)

    def test_predicat_faux_aucune_devinette(self):
        self.poser(self.doc(log_check={"days": 3}))
        lanceur = FauxLanceur(interdit=True)
        args, app, _ = self.analyser(
            p_log(),
            ["--file", "/var/log/exemple.log"],
            "log_check",
            lanceur=lanceur,
            utilise_service=profil.outil("log_check").avec_service,
        )
        self.assertFalse(app.actif)
        self.assertEqual(args.days, 7)

    def test_devinette_qui_echoue_donne_aucun_profil(self):
        lanceur = FauxLanceur({})
        args, app, erreurs = self.analyser(
            p_update(), ["--module", "all"], "update_module", lanceur=lanceur
        )
        self.assertFalse(app.actif)
        self.assertIsNone(app.unite_devinee)
        self.assertEqual(erreurs, "")

    def test_fichier_absent_sans_message(self):
        args, app, erreurs = self.analyser(
            p_update(),
            ["--module", "all", "--service", "odoo-exemple"],
            "update_module",
        )
        self.assertFalse(app.actif)
        self.assertEqual(erreurs, "")
        self.assertEqual(args.profil.json(), None)

    def test_profile_required(self):
        erreurs = self.refus(
            p_update(),
            [
                "--module",
                "all",
                "--service",
                "odoo-exemple",
                "--profile-required",
            ],
            "update_module",
        )
        self.assertIn("--profile-required", erreurs)

    def test_profile_explicite_absent(self):
        erreurs = self.refus(
            p_update(),
            ["--module", "all", "--profile", os.path.join(self.tmp, "x.json")],
            "update_module",
        )
        self.assertIn("file not found", erreurs)

    def test_no_profile(self):
        self.poser(self.doc(update_module={"timeout": 64}))
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--service", SERVICE, "--no-profile"],
            "update_module",
        )
        self.assertFalse(app.actif)
        self.assertEqual(args.timeout, 1800)

    def test_aucun_processus_si_explicite(self):
        chemin = self.poser(self.doc(update_module={"timeout": 65}))
        interdit = mock.Mock(side_effect=AssertionError("subprocess"))
        with (
            mock.patch("subprocess.run", interdit),
            mock.patch("subprocess.Popen", interdit),
            mock.patch("os.system", interdit),
        ):
            for argv in (
                ["--module", "all", "--service", SERVICE],
                ["--module", "all", "--profile", chemin],
            ):
                args, _app, _ = self.analyser(
                    p_update(),
                    argv,
                    "update_module",
                    lanceur=FauxLanceur(interdit=True),
                )
                self.assertEqual(args.timeout, 65)

    def test_service_divergent(self):
        chemin = self.poser(self.doc())
        erreurs = self.refus(
            p_update(),
            [
                "--module",
                "all",
                "--service",
                "odoo-autre",
                "--profile",
                chemin,
            ],
            "update_module",
        )
        self.assertIn("differs", erreurs)

    def test_service_du_profil_normalise(self):
        """Un `service` sans `.service` (fichier `odoo-exemple.json`) se
        normalise : la valeur posée et la comparaison avec --service
        portent sur l'unité complète."""
        court = SERVICE[: -len(".service")]
        chemin = self.poser(
            {"version": 1, "service": court}, service_=court, dossier=self.tmp
        )
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertEqual(args.service, SERVICE)
        self.assertEqual(app.service, SERVICE)
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin, "--service", court],
            "update_module",
        )
        self.assertEqual(args.service, SERVICE)

    @unittest.skipIf(os.geteuid() == 0, "root reads any file")
    def test_profil_decouvert_illisible(self):
        """Un profil découvert que ce compte ne peut pas ouvrir vaut « pas
        de profil », avec un ATTN ; nommé par --profile ou exigé, il
        refuse."""
        chemin = self.poser(self.doc(update_module={"timeout": 61}), mode=0)
        args, app, erreurs = self.analyser(
            p_update(),
            ["--module", "all", "--service", "odoo-exemple"],
            "update_module",
        )
        self.assertFalse(app.actif)
        self.assertEqual(args.timeout, 1800)
        self.assertIn("[ATTN]", erreurs)
        self.assertIn(chemin, erreurs)
        for argv in (
            ["--profile", chemin],
            ["--service", "odoo-exemple", "--profile-required"],
        ):
            with self.subTest(argv=argv):
                self.refus(
                    p_update(), ["--module", "all"] + argv, "update_module"
                )

    def test_service_non_pose_sans_local(self):
        chemin = self.poser(
            self.doc(health_check={"url": ["https://erp.example.org"]})
        )
        avec = profil.outil("health_check").avec_service
        args, app, _ = self.analyser(
            p_health(),
            ["--profile", chemin],
            "health_check",
            utilise_service=avec,
        )
        self.assertIsNone(args.service)
        self.assertEqual(args.url, [Cible("erp.example.org")])
        args, app, _ = self.analyser(
            p_health(),
            ["--profile", chemin, "--local"],
            "health_check",
            utilise_service=avec,
        )
        self.assertEqual(args.service, SERVICE)

    def test_predicats_des_outils(self):
        self.assertFalse(profil.outil("backup").avec_service({"status"}))
        self.assertTrue(profil.outil("backup").avec_service({"dry_run"}))
        self.assertFalse(profil.outil("log_check").avec_service({"file"}))
        self.assertFalse(profil.outil("health_check").avec_service(set()))
        self.assertTrue(profil.outil("warmup").avec_service({"local"}))
        self.assertFalse(profil.outil("host_perf_audit").avec_service(set()))


class TestDocument(Base):
    def test_version_plus_recente(self):
        chemin = self.poser({"version": 2, "service": SERVICE})
        erreurs = self.refus(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertIn("newer ERPLibre", erreurs)

    def test_version_invalide(self):
        for version in ("1", True, 0, None):
            with self.subTest(version=version):
                chemin = self.poser({"version": version, "service": SERVICE})
                self.refus(
                    p_update(),
                    ["--module", "all", "--profile", chemin],
                    "update_module",
                )

    def test_service_different_du_nom_de_fichier(self):
        chemin = self.poser({"version": 1, "service": "odoo-autre.service"})
        erreurs = self.refus(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertIn("does not match the file name", erreurs)

    def test_cle_inconnue_attn(self):
        chemin = self.poser(
            self.doc(
                update_module={"timeout": 70, "bidule": 1},
                instance={"autre": 1},
                bakup={"dest": "/srv"},
                log_check={"days": 3},
            )
        )
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertEqual(args.timeout, 70)
        self.assertEqual(
            sorted(app.inconnues),
            ["bakup", "instance.autre", "update_module.bidule"],
        )
        avertissements = app.avertissements(t)
        self.assertIn(
            "unknown key update_module.bidule, ignored", avertissements
        )
        # Le groupe d'un autre outil est ignoré sans message.
        self.assertFalse(any("log_check" in a for a in avertissements))

    def test_profil_d_hote_ignore_le_groupe_instance(self):
        """Comme le lecteur interne de l'audit : `instance` n'est pas lu
        par le profil d'hôte, ses clés n'y sont pas signalées."""
        parser = argparse.ArgumentParser(prog="host_perf_audit")
        parser.add_argument("--top", type=int, default=8)
        parser.add_argument("--profile")
        chemin = self.poser(
            {
                "version": 1,
                "host": "local",
                profil.GROUPE_HOTE: {"top": 3, "duree": 1},
                "instance": {"autre": 1},
            },
            "local",
        )
        args, app, _ = self.analyser(
            parser,
            ["--profile", chemin],
            profil.GROUPE_HOTE,
            utilise_service=profil.outil(profil.GROUPE_HOTE).avec_service,
        )
        self.assertEqual(args.top, 3)
        self.assertEqual(app.inconnues, ["host_perf_audit.duree"])

    def test_cle_aliasee_dans_son_groupe_est_inconnue(self):
        chemin = self.poser(self.doc(update_module={"db": "exemple_db"}))
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertIsNone(args.db)
        self.assertEqual(app.inconnues, ["update_module.db"])

    def test_cle_exclue_ignoree(self):
        chemin = self.poser(
            self.doc(backup={"force_space": True, "keep_daily": 9})
        )
        args, app, _ = self.analyser(
            p_backup(), ["--profile", chemin], "backup"
        )
        self.assertFalse(args.force_space)
        self.assertEqual(args.keep_daily, 9)
        self.assertEqual(
            [(e.cle, e.raison) for e in app.ecartees],
            [("backup.force_space", "exclue")],
        )
        self.assertIn("is not a profile setting", app.avertissements(t)[0])

    def test_groupe_qui_n_est_pas_un_objet(self):
        chemin = self.poser(self.doc(backup=[1]))
        self.refus(p_backup(), ["--profile", chemin], "backup")

    def test_refus_o_plus_w(self):
        chemin = self.poser(self.doc(), mode=0o646)
        erreurs = self.refus(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertIn("writable by every account", erreurs)

    def test_refus_d_un_lien(self):
        cible = self.poser(self.doc(), dossier=self.tmp)
        lien = os.path.join(self.profils, f"{SERVICE}.json")
        os.symlink(cible, lien)
        for argv in (
            ["--module", "all", "--profile", lien],
            ["--module", "all", "--service", SERVICE],
        ):
            with self.subTest(argv=argv):
                erreurs = self.refus(p_update(), argv, "update_module")
                self.assertIn("symbolic link refused", erreurs)

    def test_refus_trop_gros(self):
        doc = self.doc(update_module={"timeout": 5})
        doc["remplissage"] = "x" * (profil.TAILLE_MAX + 1)
        chemin = self.poser(doc)
        erreurs = self.refus(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertIn("larger than 256 KiB", erreurs)

    def test_refus_caractere_de_controle_sans_la_valeur(self):
        for doc in (
            self.doc(backup={"copy_to": "sauvegarde@example.org:/srv\u0007x"}),
            self.doc(backup={"copy_to\u001b": "x"}),
            self.doc(health_check={"url": ["https://a.example.org\u0000"]}),
        ):
            with self.subTest(doc=doc):
                chemin = self.poser(doc)
                erreurs = self.refus(
                    p_backup(), ["--profile", chemin], "backup"
                )
                self.assertIn("control character", erreurs)
                self.assertNotIn("example.org:/srv", erreurs)
        chemin = self.poser(
            self.doc(backup={"copy_to": "sauvegarde@example.org:/srv\u0007x"})
        )
        erreurs = self.refus(p_backup(), ["--profile", chemin], "backup")
        self.assertIn("backup.copy_to", erreurs)

    def test_refus_nan_et_json_invalide(self):
        for texte in (
            '{"version": 1, "service": "%s", "backup": {"max_age": NaN}}'
            % SERVICE,
            "{",
            "[1]",
        ):
            with self.subTest(texte=texte):
                chemin = self.poser(texte)
                self.refus(p_backup(), ["--profile", chemin], "backup")


class TestSousRoot(Base):
    """euid 0 simulé : `os.geteuid` rend 0."""

    def setUp(self):
        super().setUp()
        patch = mock.patch("os.geteuid", return_value=0)
        patch.start()
        self.addCleanup(patch.stop)

    def test_fichier_inscriptible_par_le_groupe(self):
        chemin = self.poser(self.doc(), mode=0o664)
        erreurs = self.refus(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertIn("writable by its group", erreurs)

    def test_dossier_inscriptible_par_le_groupe(self):
        os.chmod(self.profils, 0o775)
        self.poser(self.doc())
        erreurs = self.refus(
            p_update(),
            ["--module", "all", "--service", SERVICE],
            "update_module",
        )
        self.assertIn("its directory is writable", erreurs)

    def test_proprietaire_etranger(self):
        chemin = self.poser(self.doc())
        if os.stat(chemin).st_uid == 0:
            self.skipTest("lancé en root : le fichier appartient à root")
        with mock.patch.object(
            profil, "_proprietaires_admis", return_value={0}
        ):
            erreurs = self.refus(
                p_update(),
                ["--module", "all", "--profile", chemin],
                "update_module",
            )
        self.assertIn("owned by uid", erreurs)

    def test_proprietaire_admis(self):
        chemin = self.poser(self.doc(update_module={"timeout": 71}))
        admis = {0, os.stat(chemin).st_uid}
        with mock.patch.object(
            profil, "_proprietaires_admis", return_value=admis
        ):
            args, _app, _ = self.analyser(
                p_update(),
                ["--module", "all", "--profile", chemin],
                "update_module",
            )
        self.assertEqual(args.timeout, 71)

    def test_sudo_uid_admis(self):
        with mock.patch.dict(os.environ, {"SUDO_UID": "4242"}):
            self.assertIn(4242, profil._proprietaires_admis())

    def test_realpath_hors_racine(self):
        ailleurs = os.path.join(self.tmp, "ailleurs")
        os.mkdir(ailleurs, 0o755)
        self.poser(self.doc(update_module={"timeout": 72}), dossier=ailleurs)
        lien = os.path.join(self.tmp, "profils_lien")
        os.symlink(ailleurs, lien)
        admis = {0, os.getuid()}
        with (
            mock.patch.object(profil, "RACINE_PROFILS", lien),
            mock.patch.object(
                profil, "_proprietaires_admis", return_value=admis
            ),
        ):
            erreurs = self.refus(
                p_update(),
                ["--module", "all", "--service", SERVICE],
                "update_module",
            )
            self.assertIn("outside", erreurs)
            # Un `--profile` explicite n'a pas de racine à respecter.
            args, _app, _ = self.analyser(
                p_update(),
                [
                    "--module",
                    "all",
                    "--profile",
                    os.path.join(lien, f"{SERVICE}.json"),
                ],
                "update_module",
            )
            self.assertEqual(args.timeout, 72)


class TestConversion(Base):
    def champ(self, parser, groupe, dest):
        return [c for c in profil.champs(parser, groupe) if c.dest == dest][0]

    def test_entier(self):
        champ = self.champ(p_backup(), "backup", "keep_daily")
        self.assertEqual(profil.convertir(champ, 10), 10)
        self.assertEqual(profil.convertir(champ, "10"), 10)
        for brut in (True, "abc", [1], None, -1):
            with self.subTest(brut=brut):
                with self.assertRaises(profil.ErreurProfil) as err:
                    profil.convertir(champ, brut)
                self.assertEqual(err.exception.cle, "backup.keep_daily")

    def test_erreur_de_type_code_2_avec_la_cle(self):
        chemin = self.poser(self.doc(backup={"keep_weekly": "abc"}))
        erreurs = self.refus(p_backup(), ["--profile", chemin], "backup")
        self.assertIn(f"Profile {chemin}: backup.keep_weekly:", erreurs)

    def test_booleen(self):
        champ = self.champ(p_update(), "update_module", "warmup_deep")
        self.assertIs(profil.convertir(champ, True), True)
        self.assertIs(profil.convertir(champ, False), False)
        for brut in ("true", 1, None):
            with self.subTest(brut=brut):
                with self.assertRaises(profil.ErreurProfil):
                    profil.convertir(champ, brut)

    def test_bool_faux(self):
        p = argparse.ArgumentParser()
        p.add_argument("--no-guests", dest="no_guests", action="store_false")
        champ = profil._champ(p._actions[-1], "host_perf_audit", "no_guests")
        self.assertEqual(champ.genre, "bool_faux")
        self.assertIs(profil.convertir(champ, True), False)

    def test_append(self):
        champ = self.champ(p_update(), "update_module", "ignore_error")
        motifs = profil.convertir(champ, ["^odoo\\.addons\\.exemple_bruit"])
        self.assertEqual(
            [m.pattern for m in motifs], ["^odoo\\.addons\\.exemple_bruit"]
        )
        for brut in ("^odoo", [["x"]], [True]):
            with self.subTest(brut=brut):
                with self.assertRaises(profil.ErreurProfil):
                    profil.convertir(champ, brut)

    def test_nargs(self):
        p = argparse.ArgumentParser()
        p.add_argument("--codes", nargs="+", type=int)
        champ = profil._champ(p._actions[-1], "exemple", "codes")
        self.assertEqual(champ.genre, "liste_nargs")
        self.assertEqual(profil.convertir(champ, [1, "2"]), [1, 2])
        with self.assertRaises(profil.ErreurProfil):
            profil.convertir(champ, [])
        with self.assertRaises(profil.ErreurProfil):
            profil.convertir(champ, ["x"])

    def test_choices(self):
        p = argparse.ArgumentParser()
        p.add_argument("--mode", choices=["a", "b"])
        champ = profil._champ(p._actions[-1], "exemple", "mode")
        self.assertEqual(profil.convertir(champ, "a"), "a")
        with self.assertRaises(profil.ErreurProfil) as err:
            profil.convertir(champ, "c")
        self.assertIn("choose from a, b", str(err.exception))

    def test_genre_non_porte(self):
        p = argparse.ArgumentParser()
        action = p.add_argument("-q", action="count")
        with self.assertRaises(ValueError):
            profil.genre(action)

    def test_secret_sans_echo(self):
        valeur = "s3cr3t-valeur-inventee"

        def type_cle(texte):
            raise argparse.ArgumentTypeError(f"refused: {texte}")

        for parser, brut in (
            (p_warmup(), valeur),
            (p_warmup(), {"kdbx": 1}),
            (p_warmup(), {"kdbx": "x", "autre": valeur}),
            (p_warmup(), [valeur]),
            (p_warmup(type_cle), "/run/" + valeur),
        ):
            with self.subTest(brut=brut):
                chemin = self.poser(self.doc(warmup={"api_key_file": brut}))
                erreurs = self.refus(
                    parser,
                    ["--deep", "--profile", chemin],
                    "warmup",
                    connus=True,
                )
                self.assertIn("warmup.api_key_file", erreurs)
                self.assertNotIn(valeur, erreurs)

    def test_secret_chemin_absolu(self):
        chemin = self.poser(
            self.doc(
                warmup={
                    "api_key_file": "/run/exemple/cle",
                    "login": "warmup-bot",
                }
            )
        )
        args, _restes, app = profil.analyser(
            p_warmup(),
            ["--deep", "--profile", chemin],
            "warmup",
            t,
            self.racine,
            connus=True,
        )
        self.assertEqual(args.api_key_file, "/run/exemple/cle")
        self.assertEqual(args.login, "warmup-bot")

    def test_secret_kdbx_non_resolu_ecarte_le_login(self):
        chemin = self.poser(
            self.doc(
                warmup={
                    "api_key_file": {
                        "kdbx": "ERPLibre/Production/x/warmup.api_key"
                    },
                    "login": "warmup-bot",
                    "repeat": 2,
                }
            )
        )
        args, _restes, app = profil.analyser(
            p_warmup(),
            ["--deep", "--profile", chemin],
            "warmup",
            t,
            self.racine,
            connus=True,
        )
        self.assertIsNone(args.api_key_file)
        self.assertIsNone(args.login)
        self.assertEqual(args.repeat, 2)
        self.assertEqual(
            sorted((e.dest, e.raison) for e in app.ecartees),
            [("api_key_file", "secret"), ("login", "dependance")],
        )
        self.assertEqual(
            app.secrets_kdbx,
            {
                "api_key_file": (
                    "ERPLibre/Production/x/warmup.api_key",
                    "warmup.api_key",
                )
            },
        )

    def test_secret_kdbx_resolu_par_le_credential(self):
        """Une référence KeePass n'a pas de valeur pour l'outil, mais dans
        une unité qui reçoit le credential du secret, ce fichier la
        remplace : le secret est effectif, `login` est gardé, et warmup
        reçoit les deux ensemble. Sans le credential, les deux sont
        écartés (test précédent)."""
        credentials = os.path.join(self.tmp, "creds")
        os.mkdir(credentials, 0o700)
        fichier = os.path.join(credentials, "warmup.api_key")
        with open(fichier, "w") as f:
            f.write("x")
        chemin = self.poser(
            self.doc(
                warmup={"api_key_file": {"kdbx": "r"}, "login": "warmup-bot"}
            )
        )
        with mock.patch.dict(
            os.environ, {"CREDENTIALS_DIRECTORY": credentials}
        ):
            args, _restes, app = profil.analyser(
                p_warmup(),
                ["--deep", "--profile", chemin],
                "warmup",
                t,
                self.racine,
                connus=True,
            )
        self.assertEqual(args.login, "warmup-bot")
        self.assertEqual(args.api_key_file, fichier)
        self.assertEqual(app.origine("api_key_file"), "systemd")
        self.assertEqual(app.ecartees, [])

    def test_cle_sans_login_ecartee(self):
        """`api_key_file` sans `login` effectif est écarté : warmup refuse
        l'une sans l'autre. `--login` sur la ligne de commande le garde."""
        chemin = self.poser(self.doc(warmup={"api_key_file": "/srv/cle"}))
        args, _restes, app = profil.analyser(
            p_warmup(),
            ["--deep", "--profile", chemin],
            "warmup",
            t,
            self.racine,
            connus=True,
        )
        self.assertIsNone(args.api_key_file)
        self.assertEqual(
            [(e.dest, e.raison) for e in app.ecartees],
            [("api_key_file", "dependance")],
        )
        args, _restes, app = profil.analyser(
            p_warmup(),
            ["--deep", "--profile", chemin, "--login", "warmup-bot"],
            "warmup",
            t,
            self.racine,
            connus=True,
        )
        self.assertEqual(args.api_key_file, "/srv/cle")
        chemin = self.poser(
            self.doc(warmup={"api_key_file": "/srv/cle", "login": "bot"})
        )
        args, _restes, app = profil.analyser(
            p_warmup(),
            ["--deep", "--profile", chemin, "--profile-unset", "login"],
            "warmup",
            t,
            self.racine,
            connus=True,
        )
        self.assertIsNone(args.login)
        self.assertIsNone(args.api_key_file)


class TestRegles(Base):
    def test_chemins_relatifs_refuses(self):
        for parser, groupe, doc, cle, argv in (
            (
                p_update(),
                "update_module",
                {"update_module": {"log_dir": "log"}},
                "update_module.log_dir",
                ["--module", "all"],
            ),
            (
                p_update(),
                "update_module",
                {"backup": {"dest": "sauvegardes"}},
                "backup.dest",
                ["--module", "all"],
            ),
            (
                p_backup(),
                "backup",
                {"backup": {"state_dir": "./etat"}},
                "backup.state_dir",
                [],
            ),
            (
                p_log(),
                "log_check",
                {"log_check": {"state_dir": "etat"}},
                "log_check.state_dir",
                [],
            ),
        ):
            with self.subTest(cle=cle):
                chemin = self.poser(self.doc(**doc))
                erreurs = self.refus(
                    parser, argv + ["--profile", chemin], groupe
                )
                self.assertIn(cle, erreurs)
                self.assertIn("absolute path", erreurs)

    def test_bornes(self):
        for backup, cle in (
            ({"keep_daily": 0}, "backup.keep_daily"),
            ({"max_age": 200}, "backup.max_age"),
            (
                {
                    "keep_daily": 1,
                    "keep_weekly": 0,
                    "keep_monthly": 0,
                    "keep_recent_days": 0,
                },
                "backup.keep_*",
            ),
        ):
            with self.subTest(backup=backup):
                chemin = self.poser(self.doc(backup=backup))
                erreurs = self.refus(
                    p_backup(), ["--profile", chemin], "backup"
                )
                self.assertIn(cle, erreurs)
        chemin = self.poser(self.doc(backup={"max_age": 168, "keep_daily": 1}))
        args, _app, _ = self.analyser(
            p_backup(), ["--profile", chemin], "backup"
        )
        self.assertEqual((args.max_age, args.keep_daily), (168, 1))

    def test_somme_sur_les_seules_valeurs_retenues(self):
        """Des `keep_*` du profil sous la borne, tous remplacés par la
        ligne de commande, ne s'appliquent pas : aucun refus. Retirés par
        --profile-unset non plus."""
        chemin = self.poser(
            self.doc(
                backup={
                    "keep_daily": 1,
                    "keep_weekly": 0,
                    "keep_monthly": 0,
                    "keep_recent_days": 0,
                }
            )
        )
        cli = [
            "--keep-daily",
            "7",
            "--keep-weekly",
            "4",
            "--keep-monthly",
            "6",
            "--keep-recent-days",
            "2",
        ]
        args, app, _ = self.analyser(
            p_backup(), ["--profile", chemin] + cli, "backup"
        )
        self.assertEqual(
            (args.keep_daily, args.keep_weekly, args.keep_monthly),
            (7, 4, 6),
        )
        self.assertEqual(app.valeurs, {})
        unset = []
        for nom in ("keep-weekly", "keep-monthly", "keep-recent-days"):
            unset += ["--profile-unset", nom]
        args, app, _ = self.analyser(
            p_backup(), ["--profile", chemin] + unset, "backup"
        )
        self.assertEqual(args.keep_daily, 1)
        # Les valeurs retenues se comptent avec le défaut de l'outil pour
        # celle que la ligne de commande remplace : 0 + 0 + 0 + 7.
        args, app, _ = self.analyser(
            p_backup(), ["--profile", chemin, "--keep-daily", "1"], "backup"
        )
        self.assertEqual((args.keep_daily, args.keep_weekly), (1, 0))
        # Toutes retenues, elles restent sous la borne : refus.
        erreurs = self.refus(p_backup(), ["--profile", chemin], "backup")
        self.assertIn("backup.keep_*", erreurs)

    def test_zero_reste_permis_sur_la_ligne_de_commande(self):
        chemin = self.poser(self.doc(backup={"keep_weekly": 3}))
        args, _app, _ = self.analyser(
            p_backup(),
            ["--profile", chemin, "--keep-daily", "0", "--keep-monthly", "0"],
            "backup",
        )
        self.assertEqual(
            (args.keep_daily, args.keep_weekly, args.keep_monthly), (0, 3, 0)
        )

    def test_motifs(self):
        champ = [
            c
            for c in profil.champs(p_log(), "log_check")
            if c.dest == "ignore"
        ][0]
        for motif in (
            ".*",
            "ERROR",
            "^",
            "CRITICAL|x",
            "",
            "Error",
            "^[\\w.]+: ",
            "UniqueViolation",
        ):
            with self.subTest(motif=motif):
                with self.assertRaises(profil.ErreurProfil) as err:
                    profil.convertir(champ, [motif])
                self.assertIn("too broad", str(err.exception))
        self.assertEqual(
            len(profil.convertir(champ, ["^odoo\\.addons\\.exemple_bruit"])), 1
        )

    def test_motif_trop_large_dans_un_profil(self):
        chemin = self.poser(
            self.doc(update_module={"ignore_error": ["ERROR"]})
        )
        erreurs = self.refus(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertIn("update_module.ignore_error", erreurs)


class TestPrecedence(Base):
    def test_scalaire_la_ligne_de_commande_gagne(self):
        chemin = self.poser(self.doc(update_module={"timeout": 60}))
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin, "--timeout", "30"],
            "update_module",
        )
        self.assertEqual(args.timeout, 30)
        self.assertEqual(app.origine("timeout"), "cli")
        self.assertEqual([e.raison for e in app.ecartees], ["cli"])
        self.assertIn("command line wins", app.avertissements(t)[0])

    def test_append_remplace(self):
        chemin = self.poser(
            self.doc(update_module={"ignore_error": ["^a\\.b", "^c\\.d"]})
        )
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin, "--ignore-error", "^e"],
            "update_module",
        )
        self.assertEqual([m.pattern for m in args.ignore_error], ["^e"])
        self.assertIn("2 value(s) of --ignore-error", app.avertissements(t)[0])

    def test_append_du_profil_sans_concatenation(self):
        chemin = self.poser(
            self.doc(update_module={"ignore_error": ["^a\\.b", "^c\\.d"]})
        )
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertEqual(
            [m.pattern for m in args.ignore_error], ["^a\\.b", "^c\\.d"]
        )
        self.assertEqual(
            app.details(t),
            [
                "--ignore-error ^a\\.b (profile)",
                "--ignore-error ^c\\.d (profile)",
            ],
        )

    def test_profile_unset(self):
        chemin = self.poser(
            self.doc(backup={"keep_daily": 9, "keep_weekly": 5})
        )
        for nom in ("keep-daily", "keep_daily"):
            with self.subTest(nom=nom):
                args, app, _ = self.analyser(
                    p_backup(),
                    ["--profile", chemin, "--profile-unset", nom],
                    "backup",
                )
                self.assertEqual((args.keep_daily, args.keep_weekly), (7, 5))
                self.assertEqual(
                    [(e.dest, e.raison) for e in app.ecartees],
                    [("keep_daily", "unset")],
                )
        erreurs = self.refus(
            p_backup(),
            ["--profile", chemin, "--profile-unset", "service"],
            "backup",
        )
        self.assertIn("unknown setting for --profile-unset: service", erreurs)

    def test_membre_d_un_groupe_exclusif(self):
        chemin = self.poser(self.doc(log_check={"days": 3}))
        args, app, _ = self.analyser(
            p_log(exclusif_days=True),
            ["--profile", chemin, "--since-last"],
            "log_check",
        )
        self.assertEqual(args.days, 7)
        self.assertEqual(app.ecartees[0].raison, "exclusif")
        self.assertIn(
            "--since-last is on the command line", app.avertissements(t)[0]
        )

    def test_conflits(self):
        chemin = self.poser(
            self.doc(log_check={"namespace": "exemple", "days": 3})
        )
        args, app, _ = self.analyser(
            p_log(),
            ["--profile", chemin, "--file", "/var/log/x.log"],
            "log_check",
        )
        self.assertIsNone(args.namespace)
        self.assertEqual(args.days, 3)
        self.assertEqual([e.raison for e in app.ecartees], ["conflit"])
        chemin = self.poser(self.doc(instance={"db": "exemple_db"}))
        args, app, _ = self.analyser(
            p_backup(), ["--profile", chemin, "--status"], "backup"
        )
        self.assertIsNone(args.db)
        self.assertEqual([e.raison for e in app.ecartees], ["conflit"])
        args, app, _ = self.analyser(
            p_backup(),
            ["--profile", chemin, "--status", "--db", "autre_db"],
            "backup",
        )
        self.assertEqual(args.db, "autre_db")
        self.assertEqual([e.raison for e in app.ecartees], ["cli"])
        args, app, _ = self.analyser(
            p_backup(), ["--profile", chemin], "backup"
        )
        self.assertEqual(args.db, "exemple_db")

    def test_conflit_days_avec_resend(self):
        """`--resend` choisit dans la liste de `--days` : une fenêtre du
        profil n'élargit pas un renvoi, seul le défaut ou --days tapé
        s'applique."""
        p = argparse.ArgumentParser(prog="mail_retry")
        p.add_argument("--days", type=int, default=30)
        p.add_argument("--resend", nargs="+")
        p.add_argument("--list", action="store_true")
        chemin = self.poser(self.doc(mail_retry={"days": 3650}))
        args, app, _ = self.analyser(
            p, ["--profile", chemin, "--resend", "all"], "mail_retry"
        )
        self.assertEqual(args.days, 30)
        self.assertEqual([e.raison for e in app.ecartees], ["conflit"])
        self.assertIn("--resend", app.avertissements(t)[0])
        args, app, _ = self.analyser(
            p, ["--profile", chemin, "--list"], "mail_retry"
        )
        self.assertEqual(args.days, 3650)

    def test_dependances(self):
        chemin = self.poser(self.doc(warmup={"login": "warmup-bot"}))
        args, _r, app = profil.analyser(
            p_warmup(),
            ["--deep", "--profile", chemin],
            "warmup",
            t,
            self.racine,
            connus=True,
        )
        self.assertIsNone(args.login)
        self.assertEqual(app.ecartees[0].raison, "dependance")
        self.assertIn(
            "--api-key-file is not available", app.avertissements(t)[0]
        )
        args, _r, app = profil.analyser(
            p_warmup(),
            ["--deep", "--profile", chemin, "--api-key-file", "/run/x/cle"],
            "warmup",
            t,
            self.racine,
            connus=True,
        )
        self.assertEqual(args.login, "warmup-bot")
        chemin = self.poser(
            self.doc(
                health_check={
                    "mail_domain": "example.org",
                    "dkim_selector": "exemple",
                }
            )
        )
        args, app, _ = self.analyser(
            p_health(),
            ["--profile", chemin, "--profile-unset", "mail-domain"],
            "health_check",
        )
        self.assertIsNone(args.mail_domain)
        self.assertIsNone(args.dkim_selector)
        self.assertEqual(
            [(e.dest, e.raison) for e in app.ecartees],
            [("mail_domain", "unset"), ("dkim_selector", "dependance")],
        )

    def test_type_appele_une_seule_fois(self):
        appels = []

        def compteur(texte):
            appels.append(texte)
            return int(texte)

        p = p_backup()
        for action in p._actions:
            if action.dest == "keep_weekly":
                action.type = compteur
        chemin = self.poser(self.doc(backup={"keep_weekly": 5}))
        args, _app, _ = self.analyser(p, ["--profile", chemin], "backup")
        self.assertEqual(args.keep_weekly, 5)
        self.assertEqual(appels, ["5"])

    def test_brut_serialisable(self):
        chemin = self.poser(
            self.doc(
                health_check={"url": ["https://erp.example.org"], "timeout": 3}
            )
        )
        args, app, _ = self.analyser(
            p_health(), ["--profile", chemin], "health_check"
        )
        self.assertEqual(args.timeout, 3.0)
        json.dumps(app.json())
        self.assertEqual(
            app.json()["values"],
            {"--url": ["https://erp.example.org"], "--timeout": 3},
        )
        chemin = self.poser(
            self.doc(update_module={"ignore_error": ["^x\\.y"]})
        )
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertEqual(
            json.loads(json.dumps(app.json()))["values"],
            {"--ignore-error": ["^x\\.y"]},
        )

    def test_alias(self):
        chemin = self.poser(
            self.doc(
                instance={"db": "exemple_db"},
                backup={
                    "dest": "/srv/sauvegardes",
                    "state_dir": "/srv/etat",
                    "keep_daily": 3,
                },
            )
        )
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertEqual(args.db, "exemple_db")
        self.assertEqual(args.backup_dest, "/srv/sauvegardes")
        self.assertEqual(args.state_dir, "/srv/etat")
        self.assertEqual(app.valeurs["backup_dest"].cle, "backup.dest")
        self.assertFalse(hasattr(args, "keep_daily"))
        self.assertEqual(app.inconnues, [])

    def test_affichage(self):
        chemin = self.poser(
            self.doc(
                update_module={"warmup_deep": True, "timeout": 99, "bidule": 1}
            )
        )
        args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        flux = io.StringIO()
        rapport = types.SimpleNamespace(
            champ=lambda e, v: flux.write(f"champ {e} {v}\n"),
            detail=lambda m: flux.write(f"detail {m}\n"),
            attn=lambda m: flux.write(f"attn {m}\n"),
        )
        profil.afficher(app, rapport, t)
        self.assertEqual(
            flux.getvalue().splitlines(),
            [
                f"champ Profile {chemin} — 2 value(s)",
                "detail --timeout 99 (profile)",
                "detail --warmup-deep (profile)",
                "attn unknown key update_module.bidule, ignored",
            ],
        )

    def test_origine_affichee(self):
        chemin = self.poser(self.doc(instance={"db": "exemple_db"}))
        _args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--profile", chemin],
            "update_module",
        )
        self.assertEqual(
            profil.origine_affichee(app, "db", "--db", t), "profile"
        )
        self.assertEqual(
            profil.origine_affichee(app, "timeout", "db_name", t), "db_name"
        )
        self.assertEqual(
            profil.origine_affichee(None, "db", "--db", t), "--db"
        )
        _args, app, _ = self.analyser(
            p_update(),
            ["--module", "all", "--db", "autre_db", "--profile", chemin],
            "update_module",
        )
        self.assertEqual(profil.origine_affichee(app, "db", "--db", t), "--db")


class TestPrePasse(Base):
    def test_un_seul_message_sur_une_option_invalide(self):
        chemin = self.poser(self.doc(update_module={"timeout": 60}))
        erreurs = self.refus(
            p_update(),
            ["--module", "all", "--profile", chemin, "--timeout", "abc"],
            "update_module",
        )
        self.assertEqual(erreurs.count("error:"), 1)
        self.assertEqual(erreurs.count("usage:"), 1)

    def test_aide_sans_lanceur_ni_lecture(self):
        self.poser("{ invalide")
        for argv in (["-h"], ["--service", SERVICE, "-h"]):
            with self.subTest(argv=argv):
                sortie = io.StringIO()
                with (
                    contextlib.redirect_stdout(sortie),
                    mock.patch.object(
                        profil, "lire", side_effect=AssertionError("lire")
                    ),
                ):
                    with self.assertRaises(SystemExit) as fin:
                        profil.analyser(
                            p_update(),
                            argv,
                            "update_module",
                            t,
                            self.racine,
                            lanceur=FauxLanceur(interdit=True),
                        )
                self.assertEqual(fin.exception.code, 0)
                self.assertEqual(sortie.getvalue().count("usage:"), 1)
                self.assertIn("--profile-unset", sortie.getvalue())

    def test_abreviation_et_egal(self):
        chemin = self.poser(self.doc(backup={"keep_daily": 9, "timeout": 50}))
        args, app, _ = self.analyser(
            p_backup(),
            ["--profile", chemin, "--keep-d", "3", "--timeout=40"],
            "backup",
        )
        self.assertEqual((args.keep_daily, args.timeout), (3, 40))
        self.assertEqual({"keep_daily", "timeout"} - app.presents, set())

    def test_dest_apres_double_tiret_ignoree(self):
        chemin = self.poser(self.doc(warmup={"timeout": 9}))
        args, restes, app = profil.analyser(
            p_warmup(),
            ["--deep", "--profile", chemin, "--", "--timeout", "1"],
            "warmup",
            t,
            self.racine,
            connus=True,
        )
        self.assertEqual(args.timeout, 9.0)
        self.assertEqual(app.origine("timeout"), "profil")

    def test_parser_rendu_intact(self):
        p = p_backup()
        avant = [(a.dest, a.default) for a in p._actions]
        p.set_defaults(exemple="x")
        chemin = self.poser(self.doc(backup={"keep_daily": 9}))
        args, _app, _ = self.analyser(p, ["--profile", chemin], "backup")
        self.assertEqual(args.exemple, "x")
        self.assertEqual(
            [(a.dest, a.default) for a in p._actions][: len(avant)], avant
        )
        for nom in ("error", "exit", "_print_message"):
            self.assertNotIn(nom, p.__dict__)

    def test_meta_options_ajoutees_une_fois(self):
        p = p_update()
        p.add_argument("--profile")
        profil.ajouter_meta(p, t)
        profil.ajouter_meta(p, t)
        options = [o for a in p._actions for o in a.option_strings]
        for nom, _o in profil.META:
            self.assertEqual(options.count(nom), 1)

    def test_no_ambigu_refuse(self):
        p = argparse.ArgumentParser()
        p.add_argument("--no-backup", action="store_true")
        erreurs = io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            with self.assertRaises(SystemExit):
                profil.analyser(p, ["--no"], "update_module", t, self.racine)
        self.assertIn("ambiguous", erreurs.getvalue())


class TestEmpreinte(Base):
    def test_sha256(self):
        chemin = self.poser(self.doc(backup={"keep_daily": 9}))
        _a, app, _ = self.analyser(p_backup(), ["--profile", chemin], "backup")
        self.assertEqual(app.empreinte, profil.empreinte_fichier(chemin))
        args, _app, _ = self.analyser(
            p_backup(),
            ["--profile", chemin, "--profile-sha256", app.empreinte.upper()],
            "backup",
        )
        self.assertEqual(args.keep_daily, 9)
        erreurs = self.refus(
            p_backup(),
            ["--profile", chemin, "--profile-sha256", "0" * 64],
            "backup",
        )
        self.assertIn("changed since the simulation", erreurs)
        self.refus(
            p_backup(),
            ["--profile", chemin, "--profile-sha256", "abc"],
            "backup",
        )


class TestEcriture(Base):
    def test_modes_sous_umask_077_et_ordre(self):
        dossier = os.path.join(self.tmp, "private", "production")
        chemin = os.path.join(dossier, f"{SERVICE}.json")
        ancien = os.umask(0o077)
        try:
            empreinte = profil.ecrire(
                chemin,
                {
                    "backup": {"keep_daily": 3, "dest": "/srv/sauvegardes"},
                    "service": SERVICE,
                    "instance": {"db": "exemple_db"},
                    "version": 1,
                },
            )
        finally:
            os.umask(ancien)
        self.assertEqual(os.stat(chemin).st_mode & 0o777, 0o644)
        self.assertEqual(os.stat(dossier).st_mode & 0o777, 0o755)
        self.assertEqual(
            os.stat(os.path.dirname(dossier)).st_mode & 0o777, 0o755
        )
        with open(chemin, encoding="utf-8") as fichier:
            texte = fichier.read()
        self.assertTrue(texte.endswith("}\n"))
        self.assertEqual(
            list(json.loads(texte)),
            ["version", "service", "instance", "backup"],
        )
        self.assertEqual(
            list(json.loads(texte)["backup"]), ["dest", "keep_daily"]
        )
        self.assertEqual(empreinte, profil.empreinte_fichier(chemin))
        self.assertEqual(os.listdir(dossier), [f"{SERVICE}.json"])

    def test_echec_garde_l_ancien_fichier(self):
        chemin = self.poser(self.doc(backup={"keep_daily": 3}))
        with open(chemin, "rb") as fichier:
            avant = fichier.read()
        with mock.patch("os.replace", side_effect=OSError("disque plein")):
            with self.assertRaises(OSError):
                profil.ecrire(chemin, self.doc(backup={"keep_daily": 4}))
        with open(chemin, "rb") as fichier:
            self.assertEqual(fichier.read(), avant)
        self.assertEqual(os.listdir(self.profils), [f"{SERVICE}.json"])

    def test_verrou_optimiste(self):
        chemin = os.path.join(self.profils, f"{SERVICE}.json")
        lue = profil.ecrire(chemin, self.doc(backup={"keep_daily": 3}), "")
        with self.assertRaises(profil.ErreurProfil):
            profil.ecrire(chemin, self.doc(), "")
        with open(chemin, "a") as fichier:
            fichier.write(" ")
        with self.assertRaises(profil.ErreurProfil) as err:
            profil.ecrire(chemin, self.doc(backup={"keep_daily": 5}), lue)
        self.assertIn("modified elsewhere", str(err.exception))
        with open(chemin, encoding="utf-8") as fichier:
            self.assertEqual(json.load(fichier)["backup"], {"keep_daily": 3})
        nouvelle = profil.empreinte_fichier(chemin)
        profil.ecrire(chemin, self.doc(backup={"keep_daily": 5}), nouvelle)

    def test_refus_a_l_ecriture(self):
        chemin = os.path.join(self.profils, f"{SERVICE}.json")
        for doc in (
            self.doc(update_module={"db": "exemple_db"}),
            self.doc(bakup={}),
            self.doc(backup={"inconnue": 1}),
            self.doc(warmup={"api_key_file": "relatif"}),
            self.doc(warmup={"api_key_file": {"kdbx": "x", "valeur": "y"}}),
            self.doc(warmup={"api_key_file": {"kdbx": ""}}),
            self.doc(warmup={"api_key_file": {"kdbx": "  "}}),
            self.doc(backup={"copy_to": "a\nb"}),
            self.doc(backup={"copy_to": {"x": 1}}),
            {"version": 2, "service": SERVICE},
            {"version": 1},
        ):
            with self.subTest(doc=doc):
                with self.assertRaises(profil.ErreurProfil):
                    profil.ecrire(chemin, doc)
        self.assertFalse(os.path.exists(chemin))

    def test_aller_retour(self):
        chemin = os.path.join(self.profils, f"{SERVICE}.json")
        profil.ecrire(
            chemin,
            self.doc(
                warmup={"api_key_file": {"kdbx": "ERPLibre/x"}},
                log_check={"days": 14, "ignore": ["^odoo\\.addons\\.exemple"]},
            ),
        )
        args, app, _ = self.analyser(
            p_log(), ["--service", SERVICE], "log_check"
        )
        self.assertEqual(args.days, 14)
        self.assertEqual(len(app.valeurs), 2)


class TestUnitesCitant(Base):
    def test_unites(self):
        dossier = os.path.join(self.tmp, "system")
        os.mkdir(dossier)
        cible = os.path.join(self.tmp, f"{SERVICE}.json")
        unites = {
            "erplibre-backup-odoo-exemple.service": (
                f"ExecStart=/usr/bin/python3 x.py --profile {cible}"
                " --profile-required\n"
            ),
            "erplibre-autre.service": f"ExecStart=x --profile '{cible}'\n",
            "erplibre-voisin.service": f"ExecStart=x --profile {cible}.bak\n",
            "odoo-exemple.service": f"ExecStart=x --profile {cible}\n",
            "erplibre-backup.timer": f"# {cible}\n",
        }
        for nom, texte in unites.items():
            with open(os.path.join(dossier, nom), "w") as fichier:
                fichier.write(texte)
        self.assertEqual(
            profil.unites_citant(cible, dossier),
            ["erplibre-autre.service", "erplibre-backup-odoo-exemple.service"],
        )
        self.assertEqual(
            profil.unites_citant(cible, os.path.join(self.tmp, "absent")), []
        )


class TestTables(unittest.TestCase):
    def champs_f(self):
        return {(g, c) for g, cles in profil.CHAMPS.items() for c in cles}

    def test_quarante_huit_champs(self):
        self.assertEqual(len(self.champs_f()), 48)

    def test_alias_vers_un_champ(self):
        for groupe, alias in profil.ALIAS.items():
            for dest, cible in alias.items():
                with self.subTest(groupe=groupe, dest=dest):
                    self.assertIn(cible, self.champs_f())
                    self.assertNotEqual(cible[0], groupe)
                    self.assertNotIn(dest, profil.CHAMPS.get(groupe, ()))

    def test_exclusions_et_raisons(self):
        for groupe in profil.CHAMPS:
            for dest, raison in profil.exclusions(groupe).items():
                with self.subTest(groupe=groupe, dest=dest):
                    self.assertIn(raison, profil.RAISONS)
                    self.assertNotIn(dest, profil.CHAMPS.get(groupe, ()))
                    self.assertNotIn(dest, profil.ALIAS.get(groupe, {}))

    def test_regles_sur_des_champs(self):
        champs = self.champs_f()
        for table in (
            profil.CHEMINS,
            profil.MOTIFS,
            profil.INSTALLATION,
            set(profil.BORNES),
            set(profil.SECRETS),
            set(profil.DEPENDANCES),
            set(profil.DEPENDANCES.values()),
            set(profil.ANODINS),
        ):
            self.assertEqual(set(table) - champs, set())
        groupe, cles, _minimum = profil.BORNE_SOMME
        self.assertEqual({(groupe, c) for c in cles} - champs, set())
        for conflit in profil.CONFLITS:
            self.assertIn(
                profil.classer(conflit.groupe, conflit.dest), ("F", "A")
            )

    def test_gardes_par_nom(self):
        for groupe, cle in self.champs_f():
            with self.subTest(champ=f"{groupe}.{cle}"):
                if profil.GARDE_SECRETS.search(cle):
                    self.assertTrue(
                        (groupe, cle) in profil.SECRETS
                        or (groupe, cle) in profil.NON_SECRETS
                    )
                if profil.GARDE_DANGER.search(cle):
                    self.assertIn((groupe, cle), profil.ANODINS)
        for groupe, alias in profil.ALIAS.items():
            for dest in alias:
                self.assertIsNone(profil.GARDE_DANGER.search(dest))

    def test_outils(self):
        self.assertEqual(
            [o.groupe for o in profil.OUTILS],
            [g for g in profil.CHAMPS if g != profil.GROUPE_INSTANCE],
        )
        for o in profil.OUTILS:
            self.assertIsInstance(o.argv_minimal, tuple)
            self.assertTrue(callable(o.avec_service))
        with self.assertRaises(KeyError):
            profil.outil("inconnu")

    def test_catalogue(self):
        catalogue = profil.catalogue(
            {
                "backup": p_backup(),
                "update_module": p_update(),
                "warmup": p_warmup(),
                "health_check": p_health(),
            }
        )
        self.assertEqual(
            list(catalogue),
            ["instance", "update_module", "backup", "health_check", "warmup"],
        )
        instance = catalogue["instance"][0]
        self.assertEqual(
            (instance.dest, instance.portee), ("db", "installation")
        )
        par_dest = {c.dest: c for c in catalogue["warmup"]}
        self.assertTrue(par_dest["api_key_file"].secret)
        self.assertEqual(
            par_dest["login"].depend_de, ("warmup", "api_key_file")
        )
        self.assertEqual(par_dest["strict"].genre, "bool_vrai")
        backup = {c.dest: c for c in catalogue["backup"]}
        self.assertEqual(backup["keep_daily"].portee, "direct")
        self.assertEqual(backup["copy_to"].portee, "installation")
        self.assertEqual(backup["keep_daily"].defaut, 7)
        self.assertEqual(backup["keep_daily"].option, "--keep-daily")
        update = {c.dest: c for c in catalogue["update_module"]}
        self.assertEqual(update["ignore_error"].genre, "liste_append")
        self.assertEqual(update["verbose"].option, "--verbose")
        alias = {
            c.dest: (c.groupe, c.cle)
            for c in profil.alias(p_update(), "update_module")
        }
        self.assertEqual(alias["backup_dest"], ("backup", "dest"))


class TestDetecterUnite(unittest.TestCase):
    def test_unite_devinee_reprise_sans_second_appel(self):
        lanceur = FauxLanceur(
            {
                "systemctl show -p LoadState -p ActiveState -p User"
                " -p WorkingDirectory -p ExecStart -p Environment"
                f" -p LogNamespace -- {SERVICE}": (0, "LoadState=loaded\n"),
            }
        )
        systeme = types.SimpleNamespace(lanceur=lanceur)
        plan = types.SimpleNamespace()
        service.detecter_unite(
            None, systeme, "/x", plan, devinee=(SERVICE, "active")
        )
        self.assertEqual((plan.unite, plan.origine_unite), (SERVICE, "active"))
        self.assertEqual(
            [a[:2] for a in lanceur.appels], [["systemctl", "show"]]
        )


class TestCouture(unittest.TestCase):
    def test_couture_armee(self):
        self.assertEqual(profil.RACINE_PROFILS, DOSSIER_MODULE)
        self.assertNotEqual(
            os.path.realpath(profil.racine_profils()),
            os.path.realpath(VRAI_DOSSIER),
        )

    def test_la_garde_refuse_le_vrai_dossier(self):
        for chemin in (
            VRAI_DOSSIER,
            os.path.join(VRAI_DOSSIER, f"{SERVICE}.json"),
            os.path.join(VRAI_DOSSIER, "host", "local.json"),
        ):
            with self.subTest(chemin=chemin):
                with self.assertRaises(AssertionError):
                    os.open(chemin, os.O_RDONLY)
        with self.assertRaises(AssertionError):
            os.mkdir(VRAI_DOSSIER)
        profil_reel = os.path.join(VRAI_DOSSIER, f"{SERVICE}.json")
        for ouvrir in (open, io.open):
            with self.subTest(ouvrir=ouvrir):
                with self.assertRaises(AssertionError):
                    ouvrir(profil_reel, "rb")
                with self.assertRaises(AssertionError):
                    ouvrir(profil_reel, "w")
        with self.assertRaises(AssertionError):
            profil.empreinte_fichier(profil_reel)
        with self.assertRaises(AssertionError):
            profil.ecrire(profil_reel, {"version": 1, "service": SERVICE}, "")
        with self.assertRaises(AssertionError):
            profil.ecrire(
                os.path.join(VRAI_DOSSIER, f"{SERVICE}.json"),
                {"version": 1, "service": SERVICE},
            )

    def test_le_vrai_dossier_est_intact(self):
        self.assertEqual(etat(), ETAT_INITIAL)


class TestGitignore(unittest.TestCase):
    def test_production_hors_suivi(self):
        if shutil.which("git") is None:
            self.skipTest("git absent")
        racine = profil.RACINE
        dans_un_depot = subprocess.run(
            ["git", "-C", racine, "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
        )
        if dans_un_depot.returncode != 0:
            self.skipTest("hors d'un dépôt git")
        for chemin in (
            "private/production/x.json",
            "private/production/host/y.json",
        ):
            with self.subTest(chemin=chemin):
                fin = subprocess.run(
                    ["git", "-C", racine, "check-ignore", "-q", chemin]
                )
                self.assertEqual(fin.returncode, 0)


class TestAutrePython(unittest.TestCase):
    """La pré-passe touche `_actions`, `_defaults` et `_print_message` :
    la même suite tourne sous le python3 du système s'il diffère."""

    SYSTEME = "/usr/bin/python3"

    def test_suite_sous_le_python_du_systeme(self):
        if os.environ.get(ENV_SOUS_PROCESSUS):
            self.skipTest("déjà dans le sous-processus")
        if not os.access(self.SYSTEME, os.X_OK):
            self.skipTest(f"{self.SYSTEME} absent")
        version = subprocess.run(
            [self.SYSTEME, "-c", "import sys; print(sys.version_info[:3])"],
            stdout=subprocess.PIPE,
            universal_newlines=True,
        ).stdout.strip()
        if version == str(tuple(sys.version_info[:3])):
            self.skipTest("même version que ce python")
        environ = dict(os.environ, **{ENV_SOUS_PROCESSUS: "1"})
        fin = subprocess.run(
            [self.SYSTEME, os.path.abspath(__file__)],
            cwd=profil.RACINE,
            env=environ,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=300,
        )
        self.assertEqual(fin.returncode, 0, fin.stdout[-3000:])


if __name__ == "__main__":
    unittest.main()
