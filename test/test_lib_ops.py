#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""script/lib_ops : lecture d'unité, instance Odoo, verrou, rapport,
rétention, PostgreSQL, journal d'Odoo et causes d'échec d'envoi.

Aucun systemctl réel n'est appelé : chaque fonction de `systemd` reçoit un
lanceur fabriqué qui répond depuis une table. Les fichiers (configuration,
addons, /proc) sont fabriqués dans un dossier temporaire. Les dates de la
rétention sont inventées.
"""

import contextlib
import datetime
import fcntl
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.lib_ops import (  # noqa: E402
    journal,
    lock,
    mail_diagnostic,
    odoo_instance,
    postgres,
    report,
    retention,
    service,
    systemd,
)

DUMP = b"--\n-- PostgreSQL database dump complete\n--\n\\unrestrict abc\n"
MANIFESTE = json.dumps({"odoo_dump": "1", "modules": {"base": "18.0.1.3"}})


def dossier_temporaire(test):
    d = tempfile.TemporaryDirectory()
    test.addCleanup(d.cleanup)
    return d.name


def ecrire(chemin, texte=""):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w") as f:
        f.write(texte)
    return chemin


class FauxLanceur:
    """Répond depuis `reponses` : {tuple(argv): (code, sortie)}.

    Une commande absente de la table rend (1, "") ; chaque appel est noté.
    """

    def __init__(self, reponses=None, defaut=(1, "")):
        self.reponses = reponses or {}
        self.defaut = defaut
        self.appels = []

    def __call__(self, argv, timeout=60):
        self.appels.append(list(argv))
        return self.reponses.get(tuple(argv), self.defaut)


def cle_show(unite, *noms):
    argv = ["systemctl", "show"]
    for nom in noms:
        argv += ["-p", nom]
    return tuple(argv + ["--", unite])


class TestNomUnite(unittest.TestCase):
    def test_un_nom_sans_point_recoit_service(self):
        self.assertEqual(
            systemd.nom_unite("erplibre_demo"), "erplibre_demo.service"
        )

    def test_un_nom_complet_reste_tel_quel(self):
        self.assertEqual(systemd.nom_unite("odoo.service"), "odoo.service")

    def test_un_nom_qui_porte_un_shell_est_refuse(self):
        for nom in ("", "a b", "x;rm -rf /", "a$(id)", "a\\b"):
            with self.subTest(nom=nom):
                with self.assertRaises(ValueError):
                    systemd.nom_unite(nom)


class TestLectureUnite(unittest.TestCase):
    EXECSTART = (
        "{ path=/bin/bash ; argv[]=/bin/bash /srv/demo/run.sh -d demo_db"
        " -p 8090 ; ignore_errors=no ; start_time=[n/a] ; pid=0 }"
    )

    def test_argv_execstart(self):
        self.assertEqual(
            systemd.argv_execstart(self.EXECSTART),
            ["/bin/bash", "/srv/demo/run.sh", "-d", "demo_db", "-p", "8090"],
        )

    def test_execstart_vide(self):
        self.assertEqual(systemd.argv_execstart(""), [])

    def test_environnement_avec_guillemets(self):
        self.assertEqual(
            systemd.environnement('ODOO_RC=/srv/a.conf "MSG=deux mots"'),
            {"ODOO_RC": "/srv/a.conf", "MSG": "deux mots"},
        )

    def test_dossier_de_travail_prefixes(self):
        self.assertEqual(systemd.dossier_de_travail("-/srv/x"), "/srv/x")
        self.assertEqual(systemd.dossier_de_travail("~", "/srv/h"), "/srv/h")
        self.assertEqual(systemd.dossier_de_travail(""), "")

    def test_lire_proprietes(self):
        lanceur = FauxLanceur(
            {
                cle_show("demo.service", "LoadState", "User"): (
                    0,
                    "LoadState=loaded\nUser=demo\n",
                )
            }
        )
        self.assertEqual(
            systemd.lire_proprietes(
                "demo.service", ("LoadState", "User"), lanceur
            ),
            {"LoadState": "loaded", "User": "demo"},
        )

    def test_lire_proprietes_systemctl_muet(self):
        with self.assertRaises(systemd.ErreurUnite):
            systemd.lire_proprietes("demo.service", ("User",), FauxLanceur())

    def test_est_actif(self):
        actif = FauxLanceur(
            {("systemctl", "is-active", "--", "a.service"): (0, "active\n")}
        )
        self.assertTrue(systemd.est_actif("a.service", actif))
        inactif = FauxLanceur(
            {("systemctl", "is-active", "--", "a.service"): (3, "inactive\n")}
        )
        self.assertFalse(systemd.est_actif("a.service", inactif))

    def test_etat(self):
        cle = cle_show("a.service", "ActiveState")
        for sortie, attendu in (
            ("ActiveState=active\n", "active"),
            ("ActiveState=deactivating\n", "deactivating"),
            ("ActiveState=\n", ""),
        ):
            with self.subTest(sortie=sortie):
                lanceur = FauxLanceur({cle: (0, sortie)})
                self.assertEqual(systemd.etat("a.service", lanceur), attendu)
        # systemctl muet ou hors délai : état inconnu, jamais « arrêté ».
        for reponse in ((124, "timeout"), (1, "")):
            with self.subTest(reponse=reponse):
                lanceur = FauxLanceur({cle: reponse})
                self.assertEqual(systemd.etat("a.service", lanceur), "")

    def test_est_arrete(self):
        for valeur in ("inactive", "failed"):
            self.assertTrue(systemd.est_arrete(valeur), valeur)
        for valeur in ("active", "deactivating", "activating", "", "timeout"):
            self.assertFalse(systemd.est_arrete(valeur), valeur)

    def test_journal_depuis_une_epoque(self):
        lanceur = FauxLanceur(defaut=(0, "ligne\n"))
        self.assertEqual(
            systemd.journal_depuis("a.service", 1700000000.7, lanceur),
            "ligne\n",
        )
        self.assertIn("@1700000000", lanceur.appels[0])
        self.assertIn("cat", lanceur.appels[0])


class TestDevinerUnite(unittest.TestCase):
    LISTE = (
        "systemctl",
        "list-units",
        "--type=service",
        "--all",
        "--no-legend",
        "--plain",
    )

    def lanceur(self, lignes, dossiers):
        reponses = {self.LISTE: (0, "\n".join(lignes) + "\n")}
        for nom, dossier in dossiers.items():
            reponses[cle_show(nom, "WorkingDirectory")] = (
                0,
                f"WorkingDirectory={dossier}\n",
            )
        return FauxLanceur(reponses)

    def test_le_dossier_de_ce_checkout_l_emporte(self):
        racine = dossier_temporaire(self)
        lanceur = self.lanceur(
            [
                "erplibre_a.service loaded active running A",
                "erplibre_b.service loaded inactive dead B",
                "nginx.service loaded active running web",
            ],
            {
                "erplibre_a.service": "/srv/ailleurs",
                "erplibre_b.service": racine,
            },
        )
        self.assertEqual(
            systemd.deviner_unite(racine, lanceur),
            ("erplibre_b.service", "workdir"),
        )

    def test_sinon_la_seule_active(self):
        lanceur = self.lanceur(
            [
                "● erplibre.service loaded inactive dead A",
                "odoo.service loaded active running B",
            ],
            {},
        )
        self.assertEqual(
            systemd.deviner_unite("/srv/nulle_part", lanceur),
            ("odoo.service", "active"),
        )

    def test_deux_actives_sont_ambigues(self):
        lanceur = self.lanceur(
            [
                "erplibre.service loaded active running A",
                "odoo.service loaded active running B",
            ],
            {},
        )
        with self.assertRaises(systemd.ErreurUnite) as ctx:
            systemd.deviner_unite("/srv/nulle_part", lanceur)
        self.assertEqual(str(ctx.exception), "ambiguous")
        self.assertEqual(
            sorted(ctx.exception.candidates),
            ["erplibre.service", "odoo.service"],
        )

    def test_aucune_candidate(self):
        lanceur = self.lanceur(["nginx.service loaded active running w"], {})
        with self.assertRaises(systemd.ErreurUnite) as ctx:
            systemd.deviner_unite("/srv/x", lanceur)
        self.assertEqual(ctx.exception.candidates, [])


class TestConfigEtBase(unittest.TestCase):
    def setUp(self):
        self.wd = dossier_temporaire(self)

    def test_run_sh_lit_config_conf_du_dossier(self):
        conf = ecrire(os.path.join(self.wd, "config.conf"), "[options]\n")
        argv = ["/bin/bash", os.path.join(self.wd, "run.sh")]
        self.assertEqual(
            odoo_instance.trouver_config(argv, self.wd, {"ODOO_RC": "/x"}),
            (conf, "run.sh"),
        )

    def test_run_sh_ignore_odoo_rc(self):
        local = os.path.join(self.wd, "config.conf")
        rc = os.path.join(self.wd, "rc.conf")
        argv = ["/bin/bash", os.path.join(self.wd, "run.sh")]
        presents = {local, rc, odoo_instance.CONFIG_SYSTEME}
        self.assertEqual(
            odoo_instance.trouver_config(
                argv, self.wd, {"ODOO_RC": rc}, existe=presents.__contains__
            ),
            (local, "run.sh"),
        )

    def test_run_sh_sans_config_conf_lit_le_systeme(self):
        rc = os.path.join(self.wd, "rc.conf")
        argv = ["/bin/bash", os.path.join(self.wd, "run.sh")]
        presents = {rc, odoo_instance.CONFIG_SYSTEME}
        self.assertEqual(
            odoo_instance.trouver_config(
                argv, self.wd, {"ODOO_RC": rc}, existe=presents.__contains__
            ),
            (odoo_instance.CONFIG_SYSTEME, "run.sh"),
        )

    def test_c_de_la_ligne_de_commande_l_emporte(self):
        argv = ["odoo-bin", "-c", "autre.conf"]
        self.assertEqual(
            odoo_instance.trouver_config(argv, self.wd, existe=lambda p: True),
            (os.path.join(self.wd, "autre.conf"), "argv"),
        )

    def test_odoo_rc_de_l_unite_hors_run_sh(self):
        rc = ecrire(os.path.join(self.wd, "rc.conf"), "[options]\n")
        ecrire(os.path.join(self.wd, "config.conf"), "[options]\n")
        self.assertEqual(
            odoo_instance.trouver_config(
                ["odoo-bin"], self.wd, {"ODOO_RC": rc}
            ),
            (rc, "ODOO_RC"),
        )

    def test_explicite_absent_est_une_erreur(self):
        with self.assertRaises(odoo_instance.ErreurDetection):
            odoo_instance.trouver_config(
                [], self.wd, explicite=os.path.join(self.wd, "absent.conf")
            )

    def test_rien_trouve(self):
        with self.assertRaises(odoo_instance.ErreurDetection):
            odoo_instance.trouver_config(
                ["odoo-bin"], self.wd, existe=lambda p: False
            )

    def test_lire_config(self):
        conf = ecrire(
            os.path.join(self.wd, "c.conf"),
            "[options]\ndb_name = demo_db\nhttp_port = 8070\n",
        )
        self.assertEqual(
            odoo_instance.lire_config(conf),
            {"db_name": "demo_db", "http_port": "8070"},
        )
        self.assertEqual(
            odoo_instance.lire_config(os.path.join(self.wd, "x")), {}
        )

    def test_base_ordre(self):
        argv = ["run.sh", "-d", "base_argv"]
        conf = {"db_name": "base_conf"}
        self.assertEqual(
            odoo_instance.trouver_base("base_cli", argv, conf),
            ("base_cli", "--db"),
        )
        self.assertEqual(
            odoo_instance.trouver_base(None, argv, conf), ("base_argv", "argv")
        )
        self.assertEqual(
            odoo_instance.trouver_base(None, ["--database=b2"], conf),
            ("b2", "argv"),
        )
        self.assertEqual(
            odoo_instance.trouver_base(None, ["run.sh", "-db3"], conf),
            ("b3", "argv"),
        )
        self.assertEqual(
            odoo_instance.trouver_base(None, [], conf),
            ("base_conf", "db_name"),
        )

    def test_db_name_false_ou_liste_ne_designe_pas_une_base(self):
        for valeur in ("False", "", "a,b"):
            with self.subTest(valeur=valeur):
                self.assertEqual(
                    odoo_instance.trouver_base(None, [], {"db_name": valeur}),
                    (None, None),
                )


class TestAdresseHttp(unittest.TestCase):
    def test_argv_l_emporte(self):
        for argv in (
            ["-p", "8090"],
            ["-p8090"],
            ["--http-port", "8090"],
            ["--http-port=8090"],
            ["--xmlrpc-port", "8090"],
            ["--xmlrpc-port=8090"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(
                    odoo_instance.adresse_http(argv, {"http_port": "8070"}),
                    ("127.0.0.1", 8090),
                )

    def test_http_port_puis_xmlrpc_port_puis_defaut(self):
        self.assertEqual(
            odoo_instance.adresse_http(
                [], {"http_port": "8070", "xmlrpc_port": "8071"}
            )[1],
            8070,
        )
        self.assertEqual(
            odoo_instance.adresse_http([], {"xmlrpc_port": "8071"})[1], 8071
        )
        self.assertEqual(odoo_instance.adresse_http([], {})[1], 8069)

    def test_interface(self):
        self.assertEqual(
            odoo_instance.adresse_http([], {"xmlrpc_interface": "192.0.2.10"})[
                0
            ],
            "192.0.2.10",
        )
        for valeur in ("", "0.0.0.0", "False"):
            with self.subTest(valeur=valeur):
                self.assertEqual(
                    odoo_instance.adresse_http([], {"http_interface": valeur})[
                        0
                    ],
                    "127.0.0.1",
                )

    def test_interface_de_la_ligne_de_commande_l_emporte(self):
        config = {"http_interface": "192.0.2.10"}
        for argv in (
            ["--http-interface", "192.0.2.20"],
            ["--http-interface=192.0.2.20"],
            ["--xmlrpc-interface", "192.0.2.20"],
            ["--xmlrpc-interface=192.0.2.20"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(
                    odoo_instance.adresse_http(argv, config)[0], "192.0.2.20"
                )
        self.assertEqual(
            odoo_instance.adresse_http(["--http-interface=0.0.0.0"], config)[
                0
            ],
            "127.0.0.1",
        )

    def test_fichier_journal(self):
        self.assertIsNone(
            odoo_instance.fichier_journal([], {"logfile": "False"}, "/srv")
        )
        self.assertEqual(
            odoo_instance.fichier_journal([], {"logfile": "odoo.log"}, "/srv"),
            "/srv/odoo.log",
        )
        self.assertEqual(
            odoo_instance.fichier_journal(
                ["--logfile=/var/x.log"], {"logfile": "odoo.log"}, "/srv"
            ),
            "/var/x.log",
        )


class TestModules(unittest.TestCase):
    def setUp(self):
        self.wd = dossier_temporaire(self)
        for nom in ("my_module_a", "my_module_b", "other_module"):
            ecrire(
                os.path.join(self.wd, "custom", nom, "__manifest__.py"), "{}"
            )
        ecrire(
            os.path.join(self.wd, "custom", "my_module_nomanifest", "readme")
        )
        ecrire(
            os.path.join(self.wd, "addons", "base", "__manifest__.py"), "{}"
        )
        self.chemins = odoo_instance.chemins_addons(
            {"addons_path": "addons, custom ,absent"}, self.wd
        )

    def test_chemins_relatifs_resolus_et_absents_ignores(self):
        self.assertEqual(
            self.chemins,
            [os.path.join(self.wd, "addons"), os.path.join(self.wd, "custom")],
        )

    def test_motif_sans_les_dossiers_sans_manifest(self):
        modules, absents, vides = odoo_instance.developper_modules(
            ["my_module_*"], self.chemins
        )
        self.assertEqual(modules, ["my_module_a", "my_module_b"])
        self.assertEqual((absents, vides), ([], []))

    def test_nom_exact_absent_et_motif_vide(self):
        modules, absents, vides = odoo_instance.developper_modules(
            ["base", "zzz", "yyy_*", "base"], self.chemins
        )
        self.assertEqual(modules, ["base"])
        self.assertEqual(absents, ["zzz"])
        self.assertEqual(vides, ["yyy_*"])

    def test_motifs_refuses(self):
        for motif in ("", "My_Module", "a;rm -rf /", "../x", "a b", "a,b"):
            with self.subTest(motif=motif):
                self.assertFalse(odoo_instance.motif_valide(motif))
        self.assertTrue(odoo_instance.motif_valide("my_module_?x*"))


class TestProcessus(unittest.TestCase):
    def setUp(self):
        self.proc = dossier_temporaire(self)
        self.faire(
            101,
            [
                "python3",
                "./odoo18.0/odoo/odoo-bin",
                "-c",
                "c.conf",
                "-d",
                "demo_db",
            ],
        )
        self.faire(102, ["python3", "odoo-bin", "--database=autre_db"])
        self.faire(103, ["bash", "-c", "echo -d demo_db"])
        self.faire(104, ["/bin/bash", "/srv/x/run.sh", "-d", "demo_db"])
        os.makedirs(os.path.join(self.proc, "self"))

    def faire(self, pid, argv):
        ecrire(os.path.join(self.proc, str(pid), "cmdline"), "")
        with open(os.path.join(self.proc, str(pid), "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in argv) + b"\0")

    def test_seuls_les_lanceurs_odoo_de_la_meme_base(self):
        liste = odoo_instance.lister_processus(self.proc)
        self.assertEqual(len(liste), 4)
        trouves = odoo_instance.processus_odoo("demo_db", liste)
        self.assertEqual(sorted(pid for pid, _ in trouves), [101, 104])

    def test_exclus(self):
        liste = odoo_instance.lister_processus(self.proc)
        trouves = odoo_instance.processus_odoo("demo_db", liste, exclus=(101,))
        self.assertEqual([pid for pid, _ in trouves], [104])

    def test_racine_absente(self):
        self.assertEqual(odoo_instance.lister_processus("/proc_absent_x"), [])


class TestLireAjout(unittest.TestCase):
    def test_lire_ajout(self):
        d = dossier_temporaire(self)
        chemin = ecrire(os.path.join(d, "odoo.log"), "ancien\n")
        debut = odoo_instance.taille(chemin)
        with open(chemin, "a") as f:
            f.write("nouveau\n")
        self.assertEqual(odoo_instance.lire_ajout(chemin, debut), "nouveau\n")
        # Un fichier renouvelé (plus court) se relit depuis le début.
        ecrire(chemin, "x\n")
        self.assertEqual(odoo_instance.lire_ajout(chemin, debut), "x\n")
        self.assertEqual(
            odoo_instance.lire_ajout(os.path.join(d, "absent"), 0), ""
        )
        self.assertEqual(odoo_instance.taille(None), 0)


@contextlib.contextmanager
def fuseau(nom):
    """Le fuseau local forcé à `nom` le temps du bloc."""
    ancien = os.environ.get("TZ")
    os.environ["TZ"] = nom
    time.tzset()
    try:
        yield
    finally:
        if ancien is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = ancien
        time.tzset()


def recs(texte):
    return list(journal.enregistrements(texte.splitlines()))


TRACE_CHAINEE = """\
2026-01-15 03:00:00,123 4242 ERROR base_essai odoo.http: Exception during request handling.
Traceback (most recent call last):
  File "/srv/odoo/odoo/http.py", line 10, in dispatch
    return self._call()
KeyError: 'x'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/srv/odoo/odoo/models.py", line 20, in read
    raise ValueError("y")
ValueError: y

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/srv/odoo/odoo/service/model.py", line 30, in retrying
    raise odoo.exceptions.UserError("z") from err
odoo.exceptions.UserError: z
"""


class TestJournalEntetes(unittest.TestCase):
    """J1 : les formes d'en-tête de 12 à 18 et des sorties de journalctl."""

    def un(self, ligne):
        (rec,) = recs(ligne)
        return rec

    def test_formes_d_odoo(self):
        for ligne, niveau, base, logger, message in (
            (
                "2026-01-15 03:00:00,123 4242 ERROR base_essai"
                " odoo.modules.loading: boom",
                "ERROR",
                "base_essai",
                "odoo.modules.loading",
                "boom",
            ),
            (
                "2026-01-15 03:00:00,123 4242 INFO base_essai"
                " odoo.service.server: HTTP service running ",
                "INFO",
                "base_essai",
                "odoo.service.server",
                "HTTP service running",
            ),
            (
                "2026-01-15 03:00:00,123 4242 INFO base_essai werkzeug:"
                ' 192.0.2.10 - - [15/Jan/2026 03:00:00] "GET /web HTTP/1.1"'
                " 200 - - - -",
                "INFO",
                "base_essai",
                "werkzeug",
                '192.0.2.10 - - [15/Jan/2026 03:00:00] "GET /web HTTP/1.1"'
                " 200 - - - -",
            ),
            (
                "2026-01-15 03:00:00,123 4242 WARNING ? odoo.addons.base: x",
                "WARNING",
                "?",
                "odoo.addons.base",
                "x",
            ),
            (
                "2026-01-15 03:00:00,123 4242 \x1b[1;31m\x1b[1;49mERROR"
                "\x1b[0m base_essai odoo.http: boom",
                "ERROR",
                "base_essai",
                "odoo.http",
                "boom",
            ),
            (
                "2026-01-15 03:00:00,123 4242 INFO base_essai odoo: un"
                " message qui cite ERROR",
                "INFO",
                "base_essai",
                "odoo",
                "un message qui cite ERROR",
            ),
        ):
            with self.subTest(ligne=ligne):
                rec = self.un(ligne)
                self.assertEqual(
                    (rec.niveau, rec.base, rec.logger, rec.message),
                    (niveau, base, logger, message),
                )
                self.assertEqual(rec.pid, 4242)
                self.assertNotIn("\x1b", rec.entete)

    def test_prefixes_de_journalctl(self):
        entete = "2026-03-04 10:06:07,000 77 ERROR base_essai odoo.http: boom"
        with fuseau("UTC"):
            for prefixe, attendu in (
                ("2026-03-04T05:06:07-0500", "2026-03-04T10:06:07+00:00"),
                ("2026-03-04T06:06:07-04:00", "2026-03-04T10:06:07+00:00"),
                ("2026-03-04T10:06:07Z", "2026-03-04T10:06:07+00:00"),
                (
                    "2026-03-04T10:06:07.123456+0000",
                    "2026-03-04T10:06:07+00:00",
                ),
            ):
                with self.subTest(prefixe=prefixe):
                    rec = self.un(f"{prefixe} hote odoo-bin[77]: {entete}")
                    self.assertEqual(journal.iso(rec.quand), attendu)
                    self.assertEqual(rec.entete, entete)


class TestJournalTraces(unittest.TestCase):
    def test_j2_chaine_le_titre_est_l_exception_externe(self):
        (rec,) = recs(TRACE_CHAINEE)
        self.assertEqual(rec.titre, "odoo.exceptions.UserError: z")
        self.assertEqual(len(rec.lignes), TRACE_CHAINEE.count("\n"))

    def test_j3_noms_d_exception(self):
        for derniere, suite, attendu in (
            ("odoo.exceptions.AccessDenied: Access Denied", [], None),
            (
                "psycopg2.errors.UniqueViolation: duplicate key value"
                ' violates unique constraint "res_users_login_key"',
                ["DETAIL:  Key (login)=(user@example.org) already exists."],
                None,
            ),
            ("KeyboardInterrupt", [], None),
            (
                "odoo.exceptions.ValidationError: première ligne",
                ["Seconde ligne du message", "Fin"],
                None,
            ),
        ):
            with self.subTest(derniere=derniere):
                lignes = [
                    "2026-01-15 03:00:00,123 1 ERROR b odoo.http: x",
                    journal.DEBUT_TRACE,
                    '  File "x.py", line 1, in f',
                    "    f()",
                    derniere,
                ] + suite
                self.assertEqual(
                    journal.titre_trace(lignes), attendu or derniere
                )

    def test_j4_bloc_de_donnees_jamais_titre(self):
        blob = "QUJD" * 60
        lignes = [
            "2026-01-15 03:00:00,123 1 WARNING b odoo.addons.mass_mailing: x",
            journal.DEBUT_TRACE,
            '  File "x.py", line 3, in f',
            "PIL.UnidentifiedImageError: cannot identify image file",
            blob,
        ]
        self.assertEqual(
            journal.titre_trace(lignes),
            "PIL.UnidentifiedImageError: cannot identify image file",
        )
        sans = lignes[:3] + ["    données reçues non valides", blob]
        self.assertEqual(
            journal.titre_trace(sans), "données reçues non valides"
        )
        self.assertLessEqual(len(journal.abreger("x" * 500)), 200)
        abrege = journal.abreger("image " + blob)
        self.assertNotIn(blob, abrege)
        self.assertIn(f"[data: {len(blob)} chars]", abrege)
        self.assertIsNone(journal.titre_trace(lignes[:1]))


def trace(heure, titre, pid=10, logger="odoo.http", niveau="ERROR"):
    return (
        f"2026-01-15 {heure},000 {pid} {niveau} base_essai {logger}:"
        " Exception during request handling\n"
        f"{journal.DEBUT_TRACE}\n"
        '  File "/srv/odoo/x.py", line 1, in f\n'
        f"{titre}\n"
    )


class TestCommandeJournal(unittest.TestCase):
    def test_bornes_et_curseur(self):
        self.assertEqual(
            systemd.commande_journal("u.service", 1000.7, 2000),
            [
                "journalctl",
                "-u",
                "u.service",
                "-o",
                "short-iso",
                "--no-pager",
                "--since",
                "@1000",
                "--until",
                "@2000",
                "--show-cursor",
            ],
        )
        argv = systemd.commande_journal("u.service", 1000, None, "s=1")
        self.assertIn("--after-cursor", argv)
        self.assertNotIn("--since", argv)
        self.assertNotIn("-q", argv)


class TestJournalGroupes(unittest.TestCase):
    def test_j5_regroupement(self):
        texte = "".join(
            [
                trace(
                    "03:00:02",
                    "odoo.exceptions.MissingError: Record does not exist:"
                    " res.partner(12,)",
                ),
                trace(
                    "03:00:01",
                    "odoo.exceptions.MissingError: Record does not exist:"
                    " res.partner(11,)",
                ),
                trace(
                    "03:00:03",
                    "odoo.exceptions.MissingError: Record does not exist:"
                    " res.partner(13,)",
                ),
                trace("03:00:04", "KeyError: 'x'"),
            ]
        )
        with fuseau("UTC"):
            analyse = journal.analyser(recs(texte))
        groupes = analyse.groupes_tracebacks()
        self.assertEqual([g.nombre for g in groupes], [3, 1])
        self.assertEqual(journal.iso(groupes[0].premier)[11:19], "03:00:01")
        self.assertEqual(journal.iso(groupes[0].dernier)[11:19], "03:00:03")
        self.assertIn("res.partner(12,)", groupes[0].titre)
        self.assertEqual(analyse.a_revoir, 4)

    def test_j6_entrelacement_systemd_et_curseur(self):
        lignes = [
            "ligne perdue avant tout en-tête",
            "-- Boot 0123 --",
            "2026-01-15T03:00:00+0000 hote odoo-bin[10]: 2026-01-15"
            " 03:00:00,000 10 ERROR base_essai odoo.http: A",
            "2026-01-15T03:00:00+0000 hote odoo-bin[10]: "
            + journal.DEBUT_TRACE,
            "2026-01-15T03:00:01+0000 hote odoo-bin[10]: 2026-01-15"
            " 03:00:01,000 11 ERROR base_essai odoo.http: B",
            "2026-01-15T03:00:02+0000 hote systemd[1]: Stopping demo...",
            "2026-01-15T03:00:02+0000 hote odoo-bin[10]: suite orpheline",
            "-- cursor: s=abc;i=2a",
        ]
        decoupeur = journal.Decoupeur()
        trouves = list(journal.enregistrements(lignes, decoupeur))
        self.assertEqual([r.message for r in trouves], ["A", "B"])
        self.assertEqual(len(trouves[0].lignes), 2)
        self.assertEqual(trouves[1].lignes, [trouves[1].entete])
        self.assertEqual(decoupeur.curseur, "s=abc;i=2a")

    def test_j7_fuseau(self):
        ligne = "2026-01-15 03:00:00,000 1 ERROR b odoo.http: x"
        with fuseau("America/Toronto"):
            (rec,) = recs(ligne)
            self.assertEqual(
                journal.iso(rec.quand), "2026-01-14T22:00:00-05:00"
            )
            (rec,) = recs(
                f"2026-01-15T08:30:00-0500 hote odoo-bin[1]: {ligne}"
            )
            self.assertEqual(
                journal.iso(rec.quand), "2026-01-15T08:30:00-05:00"
            )

    def test_j8_requetes_refusees(self):
        def requete(sql, raison):
            texte = (
                "2026-01-15 03:00:00,000 1 ERROR base_essai odoo.sql_db:"
                f" bad query: {sql}\n"
            )
            return texte + (f"ERROR: {raison}\n" if raison else "")

        texte = "".join(
            [
                requete(
                    "INSERT INTO res_partner (name) VALUES ('a')",
                    'duplicate key value violates unique constraint "k1"',
                ),
                requete(
                    'UPDATE "res_users" SET x = 1 WHERE id = 4',
                    "value too long for type character varying(64)",
                ),
                requete(
                    "DELETE FROM mail_mail WHERE id = 9", "deadlock detected"
                ),
                requete('SELECT id FROM "res_partner" WHERE id = 3', ""),
                requete(
                    'UPDATE "res_users" SET x = 2 WHERE id = 5',
                    "value too long for type character varying(32)",
                ),
            ]
        )
        analyse = journal.analyser(recs(texte), builtin=False)
        tables = {(g.table, g.nombre) for g in analyse.groupes_sql()}
        self.assertEqual(
            tables,
            {
                ("res_partner", 1),
                ("res_users", 2),
                ("mail_mail", 1),
                ("res_partner", 1),
            },
        )
        cles = [g.cle for g in analyse.groupes_sql()]
        self.assertIn("res_partner: " + journal.RAISON_ABSENTE, cles)
        self.assertIn(
            "res_users: value too long for type character varying(N)", cles
        )
        self.assertEqual(analyse.a_revoir, 5)


class TestJournalBruit(unittest.TestCase):
    """J9 : bruit connu sur l'en-tête ou le titre seulement."""

    def test_bruit_connu_et_ce_qui_reste(self):
        texte = "".join(
            [
                "2026-01-15 03:00:00,000 1 ERROR base_essai"
                " odoo.addons.web.controllers.binary: .map should have been"
                " generated through debug assets, (version 0a1b2c3 most"
                " likely outdated)\n",
                "2026-01-15 03:00:00,000 1 ERROR base_essai odoo.sql_db: bad"
                " query: UPDATE website_visitor SET x = 1\n"
                "ERROR: could not serialize access due to concurrent"
                " update\n",
                trace(
                    "03:00:01",
                    "psycopg2.errors.SerializationFailure: could not"
                    " serialize access due to concurrent update",
                ),
                trace(
                    "03:00:02", "odoo.exceptions.AccessDenied: Access Denied"
                ),
                trace(
                    "03:00:03",
                    "odoo.addons.mail.tools.jwt.InvalidVapidError: Invalid"
                    " VAPID public key",
                ),
            ]
        )
        analyse = journal.analyser(recs(texte))
        self.assertEqual(
            dict(analyse.ignores),
            {"sourcemap": 1, "serialization_retry": 1, "vapid": 1},
        )
        titres = [g.titre for g in analyse.groupes_tracebacks()]
        self.assertEqual(len(titres), 2)
        self.assertTrue(any("SerializationFailure" in t for t in titres))
        self.assertTrue(any("AccessDenied" in t for t in titres))
        self.assertEqual(analyse.a_revoir, 2)
        sans = journal.analyser(recs(texte), builtin=False)
        self.assertEqual(sans.a_revoir, 5)

    def test_ignorer_ne_lit_pas_les_cadres(self):
        import re

        texte = trace("03:00:00", "KeyError: 'x'")
        cadre = [re.compile(r"/srv/odoo/x\.py")]
        self.assertEqual(journal.analyser(recs(texte), cadre).a_revoir, 1)
        for motif in (r"odoo\.http", r"KeyError"):
            with self.subTest(motif=motif):
                analyse = journal.analyser(recs(texte), [re.compile(motif)])
                self.assertEqual(analyse.a_revoir, 0)
                self.assertEqual(list(analyse.ignores), ["--ignore " + motif])


class TestJournalHeuresEtJson(unittest.TestCase):
    def test_j10_matrice(self):
        texte = "".join(
            trace(heure, "KeyError: 'x'")
            for heure in ("03:00:00", "03:10:00", "19:00:00")
        )
        with fuseau("UTC"):
            analyse = journal.analyser(recs(texte))
        self.assertEqual(
            dict(analyse.par_heure),
            {("2026-01-15", 3): 2, ("2026-01-15", 19): 1},
        )
        jours = [f"2026-01-{j:02d}" for j in range(1, 16)]
        par_heure = dict(analyse.par_heure)
        par_heure[("2026-01-14", 3)] = 1234
        lignes = journal.tableau_horaire(par_heure, jours, "h", "total")
        self.assertEqual(len(lignes), 4)
        self.assertEqual(len(lignes[0].split()), 1 + 14 + 1)
        self.assertNotIn("01-01", lignes[0])
        self.assertIn("1234", lignes[1])
        self.assertNotIn("1,234", "\n".join(lignes))
        self.assertTrue(lignes[1].startswith("03 h"))
        self.assertIn("█", lignes[1])
        self.assertLessEqual(lignes[1].count("█"), journal.BARRE_MAX)
        self.assertTrue(lignes[-1].split()[-1] == "1237")
        self.assertEqual(
            journal.plages_sans({3, 19, 20, 21, 22, 23}),
            "00 h–02 h, 04 h–18 h",
        )
        self.assertEqual(journal.plages_sans(set(range(24)) - {5}), "05 h")
        self.assertEqual(journal.tableau_horaire({}, jours), [])

    def test_j11_cles_json_stables(self):
        from script.todo import todo_i18n

        with mock.patch.object(todo_i18n, "get_lang", return_value="fr"):
            resume = journal.resume_json(journal.analyser(recs(TRACE_CHAINEE)))
        self.assertEqual(
            list(resume),
            [
                "version",
                "source",
                "window",
                "records",
                "to_review",
                "tracebacks",
                "errors",
                "sql",
                "mail",
                "ignored",
                "by_hour",
                "state",
                "exit_code",
            ],
        )
        self.assertEqual(
            list(resume["tracebacks"][0]),
            [
                "key",
                "headline",
                "logger",
                "db",
                "count",
                "first",
                "last",
                "sample",
                "sql",
            ],
        )
        json.dumps(resume)

    def test_j12_ligne_demesuree(self):
        import time as horloge

        ligne = "2026-01-15 03:00:00,000 1 ERROR b odoo.http: " + "a" * 200000
        debut = horloge.monotonic()
        (rec,) = recs(ligne + "\n" + "b" * 200000 + " :")
        self.assertLess(horloge.monotonic() - debut, 2)
        self.assertEqual(len(rec.entete), journal.LIGNE_MAX)
        self.assertLessEqual(len(rec.lignes[1]), journal.LIGNE_MAX)


def courriel(classe_smtp, detail, mid=7404, preambule=None):
    """Un échec d'envoi tel qu'Odoo le journalise : en-tête, trace de
    smtplib, puis MailDeliveryException avec la phrase traduite."""
    preambule = preambule or "Mail delivery failed via SMTP server 'None'."
    return (
        f"2026-01-15 03:00:00,000 7 ERROR base_essai"
        f" odoo.addons.mail.models.mail_mail: failed sending mail (id: {mid})"
        " due to Mail Delivery Failed\n"
        f"{journal.DEBUT_TRACE}\n"
        '  File "/srv/odoo/odoo/addons/base/models/ir_mail_server.py",'
        " line 769, in send_email\n"
        "    smtp.send_message(message, smtp_from, smtp_to_list)\n"
        f"smtplib.{classe_smtp}: {detail}\n"
        "\nDuring handling of the above exception, another exception"
        " occurred:\n\n"
        f"{journal.DEBUT_TRACE}\n"
        "odoo.addons.base.models.ir_mail_server.MailDeliveryException:"
        f" ('Mail Delivery Failed', \"{preambule}\\n{classe_smtp}: {detail}\")\n"
    )


class TestDiagnosticCourriel(unittest.TestCase):
    CAS = (
        (
            "SMTPDataError",
            "(452, b'4.4.5 Maximum number of messages per session exceeded')",
            "rate_limit",
            False,
        ),
        (
            "SMTPDataError",
            "(421, b'4.7.0 Try again later')",
            "rate_limit",
            False,
        ),
        (
            "SMTPDataError",
            "(550, b'5.4.5 Daily user sending quota exceeded')",
            "rate_limit",
            False,
        ),
        (
            "SMTPSenderRefused",
            "(503, b'5.5.1 Multiple MAIL commands not allowed', 'a@example.org')",
            "cascade_503",
            False,
        ),
        (
            "SMTPAuthenticationError",
            "(535, b'5.7.8 Username and Password not accepted')",
            "auth",
            True,
        ),
        (
            "SMTPRecipientsRefused",
            "{'x@example.org': (554, b'5.7.1 Relay access denied')}",
            "relay",
            True,
        ),
        (
            "SMTPDataError",
            "(550, b'You are not allowed to send emails as"
            ' "a@example.org" (header From) while using'
            ' "b@example.org" as envelope sender\')',
            "sender",
            True,
        ),
        (
            "SMTPSenderRefused",
            "(553, b'5.7.1 Sender address rejected', 'a@example.org')",
            "sender",
            True,
        ),
        (
            "SSLError",
            "[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1006)",
            "tls",
            True,
        ),
        (
            "SMTPNotSupportedError",
            "STARTTLS extension not supported by server.",
            "tls",
            True,
        ),
        (
            "SMTPServerDisconnected",
            "Connection unexpectedly closed: timed out",
            "connection",
            False,
        ),
        (
            "SMTPRecipientsRefused",
            "{'x@example.net': (550, b'5.1.1 User unknown')}",
            "recipient",
            True,
        ),
    )

    def test_d1_chaque_classe(self):
        for exc, detail, attendu, permanent in self.CAS:
            with self.subTest(attendu=attendu, detail=detail):
                classe = mail_diagnostic.classer(courriel(exc, detail))
                self.assertEqual(classe.id, attendu)
                self.assertEqual(classe.permanent, permanent)
        texte = (
            "MailDeliveryException: ConnectionRefusedError:"
            " [Errno 111] Connection refused"
        )
        self.assertEqual(mail_diagnostic.classer(texte).id, "connection")

    def test_d2_pas_de_contexte_pas_de_courriel(self):
        texte = (
            "2026-01-15 03:00:00,000 7 ERROR base_essai"
            " odoo.addons.base.models.res_partner: Connection refused par le"
            " service de géocodage\n"
            f"{journal.DEBUT_TRACE}\n"
            "ConnectionRefusedError: [Errno 111] Connection refused"
        )
        self.assertIsNone(mail_diagnostic.classer(texte))
        self.assertEqual(
            mail_diagnostic.classer(texte, contexte_requis=False).id,
            "connection",
        )

    def test_d3_independant_de_la_langue(self):
        detail = (
            "(452, b'4.4.5 Maximum number of messages per session exceeded')"
        )
        anglais = (
            "Mail Delivery Failed\nMail delivery failed via SMTP server"
            f" 'None'.\nSMTPDataError: {detail}"
        )
        francais = (
            "Échec de l'envoi\nÉchec de l'envoi de l'e-mail via le serveur"
            f" SMTP 'None'.\nSMTPDataError: {detail}"
        )
        for raison in (anglais, francais, francais.replace("\n", " ")):
            with self.subTest(raison=raison):
                self.assertEqual(
                    mail_diagnostic.classer_echec(raison).id, "rate_limit"
                )
                cause = mail_diagnostic.cause_courte(raison)
                self.assertTrue(cause.startswith("SMTPDataError: (452, "))
                self.assertLessEqual(len(cause), 70)
        self.assertEqual(
            mail_diagnostic.classer(courriel("SMTPDataError", detail)).id,
            mail_diagnostic.classer(
                courriel(
                    "SMTPDataError",
                    detail,
                    preambule="Échec de l'envoi via le serveur SMTP 'None'.",
                )
            ).id,
        )
        self.assertEqual(mail_diagnostic.cause_courte(""), "")
        self.assertEqual(
            mail_diagnostic.cause_courte("ligne une\nsans exception"),
            "sans exception",
        )

    def test_d4_type_d_echec(self):
        classe = mail_diagnostic.classer_echec("", "mail_email_invalid")
        self.assertEqual(
            (classe.id, classe.permanent), ("invalid_address", True)
        )
        self.assertEqual(
            mail_diagnostic.classer_echec("", "mail_from_missing").id, "sender"
        )
        texte = "SMTPDataError: (452, b'4.4.5 Too many messages')"
        self.assertEqual(
            mail_diagnostic.classer_echec(texte, "mail_smtp").id, "rate_limit"
        )
        self.assertEqual(
            mail_diagnostic.classer_echec(texte, None).id, "rate_limit"
        )
        self.assertIsNone(mail_diagnostic.classer_echec("", None))

    def test_d5_reglage_selon_la_version(self):
        r14 = mail_diagnostic.reglage("sender", 14)
        self.assertIn("mail.default.from", r14)
        self.assertNotIn("From Filter", r14)
        r16 = mail_diagnostic.reglage("sender", 16)
        self.assertIn("From Filter", r16)
        self.assertIn("mail.catchall.domain", r16)
        r18 = mail_diagnostic.reglage("sender", 18)
        self.assertIn("Alias Domains", r18)
        self.assertNotIn("mail.catchall.domain", r18)
        generique = mail_diagnostic.reglage("sender", None)
        self.assertIn("15+", generique)
        self.assertIn("17+", generique)
        self.assertEqual(mail_diagnostic.reglage("inconnue"), "")
        self.assertEqual(mail_diagnostic.version_majeure("18.0.1.3"), 18)
        self.assertIsNone(mail_diagnostic.version_majeure(None))

    def test_classe_dans_le_journal(self):
        texte = "".join(
            courriel(exc, detail, mid=7404 + rang)
            for rang, (exc, detail, _a, _p) in enumerate(self.CAS[:2])
        )
        analyse = journal.analyser(recs(texte))
        (groupe,) = analyse.groupes_courriels()
        self.assertEqual(
            (groupe.classe.id, groupe.nombre, sorted(groupe.ids)),
            ("rate_limit", 2, [7404, 7405]),
        )
        # Chaque échec reste aussi une trace à revoir, comptée une fois ;
        # les deux réponses du serveur diffèrent, d'où deux groupes.
        self.assertEqual(analyse.a_revoir, 2)
        self.assertEqual(
            [g.nombre for g in analyse.groupes_tracebacks()], [1, 1]
        )


class TestVerifierSauvegarde(unittest.TestCase):
    CONTENUS = {"dump.sql": DUMP, "manifest.json": MANIFESTE}

    def zip(self, noms, contenus=None):
        contenus = dict(self.CONTENUS, **(contenus or {}))
        d = dossier_temporaire(self)
        chemin = os.path.join(d, "s.zip")
        with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as z:
            for nom in noms:
                z.writestr(nom, contenus.get(nom, "x"))
        return chemin

    def test_dump_sans_marque_de_fin(self):
        chemin = self.zip(
            ["dump.sql", "manifest.json"], {"dump.sql": b"-- tronque\n"}
        )
        self.assertEqual(
            odoo_instance.verifier_sauvegarde(chemin),
            (False, ["dump.sql incomplete"]),
        )

    def test_manifeste_illisible(self):
        chemin = self.zip(
            ["dump.sql", "manifest.json"], {"manifest.json": "pas du json"}
        )
        self.assertEqual(
            odoo_instance.verifier_sauvegarde(chemin),
            (False, ["manifest.json unreadable"]),
        )

    def test_crc_faux(self):
        chemin = self.zip(
            ["dump.sql", "manifest.json", "filestore/ab/cd"],
            {"filestore/ab/cd": b"A" * 4000},
        )
        with zipfile.ZipFile(chemin) as z:
            info = z.getinfo("filestore/ab/cd")
            debut = info.header_offset + 30 + len(info.filename)
        with open(chemin, "r+b") as f:
            f.seek(debut + 2)
            octet = f.read(1)
            f.seek(debut + 2)
            f.write(bytes([octet[0] ^ 0xFF]))
        self.assertFalse(odoo_instance.verifier_sauvegarde(chemin)[0])

    def test_fichier_ouvert(self):
        chemin = self.zip(["dump.sql", "manifest.json", "filestore/a"])
        with open(chemin, "rb") as f:
            self.assertEqual(odoo_instance.verifier_sauvegarde(f), (True, []))

    def test_complete(self):
        chemin = self.zip(["dump.sql", "manifest.json", "filestore/ab/cd"])
        self.assertEqual(odoo_instance.verifier_sauvegarde(chemin), (True, []))

    def test_sans_filestore(self):
        chemin = self.zip(["dump.sql", "manifest.json"])
        self.assertEqual(
            odoo_instance.verifier_sauvegarde(chemin), (True, ["filestore"])
        )

    def test_sans_dump(self):
        chemin = self.zip(["manifest.json"])
        self.assertEqual(
            odoo_instance.verifier_sauvegarde(chemin), (False, ["dump.sql"])
        )

    def test_illisible(self):
        d = dossier_temporaire(self)
        chemin = ecrire(os.path.join(d, "s.zip"), "pas un zip")
        self.assertFalse(odoo_instance.verifier_sauvegarde(chemin)[0])


class TestVerrou(unittest.TestCase):
    def test_un_second_detenteur_est_refuse(self):
        d = dossier_temporaire(self)
        with lock.Verrou("erplibre-db-demo_db", d) as premier:
            self.assertTrue(premier.chemin.startswith(d))
            with self.assertRaises(lock.VerrouPris) as ctx:
                lock.Verrou("erplibre-db-demo_db", d).acquerir()
            self.assertEqual(ctx.exception.chemin, premier.chemin)
        # Relâché : on le reprend.
        with lock.Verrou("erplibre-db-demo_db", d):
            pass

    def test_detenu_par_un_flock_exterieur(self):
        d = dossier_temporaire(self)
        chemin = lock.chemin_verrou("x", d)
        with open(chemin, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(lock.VerrouPris):
                lock.Verrou("x", d).acquerir()

    def test_dossier_non_inscriptible_se_replie(self):
        self.assertEqual(
            lock.dossier_verrou("/dossier/qui/n/existe/pas"),
            tempfile.gettempdir(),
        )

    def test_fichier_en_lecture_seule_se_prend_quand_meme(self):
        """Créé par un autre compte en 0644 : le nôtre ne peut pas l'ouvrir
        en écriture, mais flock n'en demande pas."""
        d = dossier_temporaire(self)
        chemin = lock.chemin_verrou("erplibre-db-demo_db", d)
        ecrire(chemin)
        os.chmod(chemin, 0o444)
        if os.access(chemin, os.W_OK):
            self.skipTest("root écrit partout")
        with lock.Verrou("erplibre-db-demo_db", d, strict=True):
            with self.assertRaises(lock.VerrouPris):
                lock.Verrou("erplibre-db-demo_db", d, strict=True).acquerir()

    def test_un_fichier_existant_s_ouvre_sans_o_creat(self):
        d = dossier_temporaire(self)
        chemin = ecrire(lock.chemin_verrou("x", d))
        vrai = os.open
        drapeaux = []

        def espion(p, flags, *reste):
            drapeaux.append(flags)
            return vrai(p, flags, *reste)

        with mock.patch.object(lock.os, "open", side_effect=espion):
            with lock.Verrou("x", d):
                pass
        self.assertEqual(len(drapeaux), 1)
        self.assertFalse(drapeaux[0] & os.O_CREAT)
        self.assertEqual(drapeaux[0] & os.O_ACCMODE, os.O_RDONLY)
        self.assertTrue(os.path.exists(chemin))

    def test_un_fichier_cree_est_lisible_par_tous(self):
        d = dossier_temporaire(self)
        ancien = os.umask(0o077)
        try:
            with lock.Verrou("x", d) as v:
                mode = os.stat(v.chemin).st_mode & 0o777
        finally:
            os.umask(ancien)
        self.assertEqual(mode, 0o644)

    def test_strict_ne_se_replie_jamais(self):
        with self.assertRaises(lock.VerrouIndisponible):
            lock.Verrou("x", "/dossier/qui/n/existe/pas", strict=True)
        if os.geteuid() == 0:
            self.skipTest("root écrit partout")
        d = dossier_temporaire(self)
        os.chmod(d, 0o555)
        self.addCleanup(os.chmod, d, 0o755)
        verrou = lock.Verrou("x", d, strict=True)
        self.assertEqual(os.path.dirname(verrou.chemin), d)
        with self.assertRaises(lock.VerrouIndisponible) as ctx:
            verrou.acquerir()
        self.assertIsInstance(ctx.exception, OSError)

    def test_nom_refuse(self):
        with self.assertRaises(ValueError):
            lock.chemin_verrou("../x")


class TestDataDir(unittest.TestCase):
    """Le dossier de données qu'Odoo utilise, dans son ordre."""

    HOME = "/srv/home/demo"

    def data_dir(self, argv=(), config=None, env=None, existe=True):
        return odoo_instance.data_dir(
            list(argv),
            config or {},
            self.HOME,
            "/srv/demo/odoo",
            env or {},
            existe=lambda p: existe,
        )

    def test_argv_l_emporte_sur_la_configuration(self):
        config = {"data_dir": "/srv/conf_data"}
        for argv in (["-D", "/srv/a"], ["--data-dir=/srv/a"], ["-D/srv/a"]):
            with self.subTest(argv=argv):
                self.assertEqual(
                    self.data_dir(argv, config), ("/srv/a", "argv")
                )

    def test_tilde_du_compte_de_l_unite(self):
        self.assertEqual(
            self.data_dir(config={"data_dir": "~/odoo-data"}),
            (self.HOME + "/odoo-data", "data_dir"),
        )

    def test_chemin_relatif_depuis_le_dossier_de_travail(self):
        self.assertEqual(
            self.data_dir(config={"data_dir": "data"}),
            ("/srv/demo/odoo/data", "data_dir"),
        )

    def test_xdg_data_home_de_l_unite(self):
        self.assertEqual(
            self.data_dir(env={"XDG_DATA_HOME": "/srv/xdg"}),
            ("/srv/xdg/Odoo", "XDG_DATA_HOME"),
        )

    def test_home_puis_var_lib_odoo(self):
        self.assertEqual(
            self.data_dir(config={"data_dir": "False"}),
            (self.HOME + "/.local/share/Odoo", "home"),
        )
        self.assertEqual(
            self.data_dir(existe=False), ("/var/lib/odoo", "default")
        )

    def test_filestore(self):
        self.assertEqual(
            odoo_instance.filestore("/srv/d", "demo_db"),
            "/srv/d/filestore/demo_db",
        )


class TestMembres(unittest.TestCase):
    def test_seuls_dump_et_filestore_sont_extraits(self):
        extraire, dangereux = odoo_instance.membres_a_extraire(
            [
                "dump.sql",
                "manifest.json",
                "filestore/ab/f0",
                "filestore/",
                "autre.txt",
            ]
        )
        self.assertEqual(extraire, ["dump.sql", "filestore/ab/f0"])
        self.assertEqual(dangereux, [])

    def test_chemins_dangereux(self):
        for nom in ("../../etc/x", "/abs", "a\\..\\b", "filestore/../x"):
            with self.subTest(nom=nom):
                self.assertEqual(
                    odoo_instance.membres_a_extraire(["dump.sql", nom])[1],
                    [nom],
                )


def j(texte):
    return datetime.datetime.strptime(texte, "%Y-%m-%d %H:%M")


def nom(texte, base="demo"):
    return retention.nom_sauvegarde(base, j(texte))


class TestRetention(unittest.TestCase):
    """La rétention, sur des dates inventées."""

    def gardes(self, noms, *garde, recents=0, aujourd_hui=None):
        supprimes = retention.a_supprimer(
            noms,
            "demo",
            *garde,
            recents_jours=recents,
            aujourd_hui=aujourd_hui,
        )
        return sorted(set(noms) - supprimes), supprimes

    def test_nom(self):
        self.assertEqual(
            nom("2031-03-01 03:04"), "demo_2031-03-01_03h04m00s.zip"
        )
        self.assertEqual(
            retention.date_de("demo_2031-03-01_03h04m05s.zip", "demo"),
            datetime.datetime(2031, 3, 1, 3, 4, 5),
        )

    def test_r1_une_par_jour_pendant_trois_mois(self):
        jour = datetime.date(2031, 1, 1)
        noms = []
        while jour <= datetime.date(2031, 3, 31):
            noms.append(nom(f"{jour.isoformat()} 03:00"))
            jour += datetime.timedelta(days=1)
        gardes, _ = self.gardes(noms, 7, 4, 12)
        attendus = [nom(f"2031-03-{d:02d} 03:00") for d in range(25, 32)]
        attendus += [
            nom("2031-03-23 03:00"),
            nom("2031-03-16 03:00"),
            nom("2031-02-28 03:00"),
            nom("2031-01-31 03:00"),
        ]
        self.assertEqual(gardes, sorted(attendus))
        self.assertEqual(len(gardes), 11)

    def test_r2_meme_jour(self):
        noms = [
            nom("2031-03-09 03:00"),
            nom("2031-03-10 03:00"),
            nom("2031-03-10 14:00"),
        ]
        gardes, supprimes = self.gardes(noms, 7, 4, 12)
        self.assertEqual(supprimes, {nom("2031-03-10 03:00")})
        gardes, supprimes = self.gardes(
            noms, 7, 4, 12, recents=2, aujourd_hui=datetime.date(2031, 3, 10)
        )
        self.assertEqual(supprimes, set())

    def test_r2_limite_des_jours_recents(self):
        """`recents=2` le 10 : le 10 et le 9 gardés en entier, le 8 n'a que
        sa plus récente, gardée par la règle quotidienne."""
        noms = [
            nom("2031-03-08 03:00"),
            nom("2031-03-08 14:00"),
            nom("2031-03-09 03:00"),
            nom("2031-03-09 14:00"),
            nom("2031-03-10 03:00"),
        ]
        _gardes, supprimes = self.gardes(
            noms, 7, 0, 0, recents=2, aujourd_hui=datetime.date(2031, 3, 10)
        )
        self.assertEqual(supprimes, {nom("2031-03-08 03:00")})

    def test_r3_une_interruption_n_efface_pas_tout(self):
        noms = [
            nom("2031-01-05 03:00"),
            nom("2031-02-20 03:00"),
            nom("2031-03-01 03:00"),
        ]
        gardes, _ = self.gardes(noms, 2, 0, 0)
        self.assertEqual(
            gardes, sorted([nom("2031-02-20 03:00"), nom("2031-03-01 03:00")])
        )

    def test_r4_semaine_iso_a_cheval_sur_deux_annees(self):
        noms = [nom("2030-12-30 03:00"), nom("2031-01-01 03:00")]
        # Même semaine ISO 2031-W01 : une seule gardée par la règle hebdo.
        self.assertEqual(self.gardes(noms, 0, 2, 0)[0], [noms[1]])
        # Deux mois : les deux gardées par la règle mensuelle.
        self.assertEqual(self.gardes(noms, 0, 0, 2)[0], sorted(noms))

    def test_r5_les_autres_noms_ne_sont_jamais_candidats(self):
        autres = [
            "demo_bar_2031-03-01_03h00m00s.zip",
            "notes.zip",
            "demo_2031-03-01.zip",
            nom("2031-03-01 03:00") + ".partial",
            "demo_2031-13-45_03h00m00s.zip",
        ]
        noms = autres + [nom("2031-01-01 03:00"), nom("2031-03-02 03:00")]
        supprimes = retention.a_supprimer(noms, "demo", 0, 0, 0)
        self.assertEqual(supprimes, {nom("2031-01-01 03:00")})
        self.assertTrue(retention.est_partiel(autres[3], "demo"))
        self.assertFalse(retention.est_partiel(autres[0], "demo"))

    def test_r7_la_plus_recente_est_toujours_gardee(self):
        noms = [nom("2031-01-01 03:00"), nom("2031-03-02 03:00")]
        self.assertEqual(self.gardes(noms, 0, 0, 0)[0], [noms[1]])
        with self.assertRaises(ValueError):
            retention.a_supprimer(noms, "demo", -1, 0, 0)

    def test_plus_recente_par_le_nom(self):
        noms = [nom("2031-03-02 03:00"), nom("2031-03-10 03:00"), "x.zip"]
        self.assertEqual(retention.plus_recente(noms, "demo"), noms[1])
        self.assertIsNone(retention.plus_recente(["x.zip"], "demo"))


class TestPostgres(unittest.TestCase):
    CONFIG = {
        "db_host": "192.0.2.10",
        "db_port": "5433",
        "db_user": "demo",
        "db_password": "secret-demo",
        "db_sslmode": "False",
    }

    def test_env_pg(self):
        variables = postgres.env_pg(self.CONFIG)
        self.assertEqual(variables["PGHOST"], "192.0.2.10")
        self.assertEqual(variables["PGPASSWORD"], "secret-demo")
        self.assertNotIn("PGSSLMODE", variables)
        self.assertNotIn("PGOPTIONS", variables)
        self.assertEqual(variables["PSQLRC"], "")
        lecture = postgres.env_pg(self.CONFIG, lecture_seule=True, delai=30)
        self.assertIn("default_transaction_read_only=on", lecture["PGOPTIONS"])
        self.assertIn("statement_timeout=30s", lecture["PGOPTIONS"])

    def test_masquer(self):
        masque = postgres.masquer(postgres.env_pg(self.CONFIG))
        self.assertEqual(masque["PGPASSWORD"], "***")
        self.assertEqual(masque["PGUSER"], "demo")

    def test_outil_dans_pg_path(self):
        config = {"pg_path": "/opt/pg16/bin"}
        self.assertEqual(
            postgres.outil("pg_dump", config, existe=lambda p: True),
            "/opt/pg16/bin/pg_dump",
        )
        self.assertEqual(
            postgres.outil("pg_dump", config, existe=lambda p: False),
            "pg_dump",
        )
        self.assertEqual(postgres.outil("psql", {"pg_path": "None"}), "psql")

    def test_noms(self):
        self.assertTrue(postgres.nom_valide("demo_db.1-a"))
        for valeur in ("", "-x", "a b", "a;b", "x" * 64, "a=b"):
            with self.subTest(valeur=valeur):
                self.assertFalse(postgres.nom_valide(valeur))

    def test_nom_temporaire_tient_en_63_octets(self):
        court = postgres.nom_temporaire("demo_db", "20310301030000")
        self.assertEqual(court, "demo_db_restoretest_20310301030000")
        long_ = postgres.nom_temporaire("d" * 70, "20310301030000")
        self.assertEqual(len(long_.encode()), 63)
        self.assertTrue(long_.endswith("_restoretest_20310301030000"))
        self.assertNotEqual(
            long_, postgres.nom_temporaire("d" * 70, "20310301030001")
        )

    def test_version_pg(self):
        self.assertEqual(postgres.version_pg(160004), "16.0")
        self.assertEqual(postgres.version_pg(90624), "9.6")
        self.assertEqual(postgres.version_pg(120017), "12.0")

    def test_erreurs_graves(self):
        lignes = [
            "psql:<stdin>:10: ERROR:  must be owner of extension plpgsql",
            'psql:<stdin>:11: ERROR:  extension "plpgsql" already exists',
            'psql:<stdin>:12: ERROR:  relation "x" does not exist',
            "NOTICE: rien",
        ]
        self.assertEqual(postgres.erreurs_graves(lignes), [lignes[2]])

    def test_lire_json(self):
        self.assertEqual(postgres.lire_json('\n{"a": 1}\n'), {"a": 1})
        self.assertIsNone(postgres.lire_json("rien"))


class TestRefus(unittest.TestCase):
    def test_modele_traduit_par_l_appelant(self):
        err = service.Refus("Service {unit} not found.", unit="a.service")
        self.assertEqual(str(err), "Service a.service not found.")
        self.assertEqual(
            err.message(lambda k: k.replace("Service", "Unité")),
            "Unité a.service not found.",
        )
        self.assertEqual(
            service.Refus("déjà formé {x}").message(str), "déjà formé {x}"
        )


class TestRapport(unittest.TestCase):
    def test_sans_couleur_hors_terminal(self):
        flux = io.StringIO()
        r = report.Rapport(flux=flux, total=3)
        r.etape("arrêt")
        r.ok("fait")
        r.attn("regard")
        r.fail("raté")
        r.skip("non vérifié")
        r.sim("systemctl stop x")
        texte = flux.getvalue()
        self.assertNotIn("\x1b[", texte)
        self.assertIn("▶ [1/3] arrêt", texte)
        self.assertIn("✔ fait", texte)
        self.assertIn("⚠ [ATTN] regard", texte)
        self.assertIn("✖ [FAIL] raté", texte)
        self.assertIn("– [SKIP] non vérifié", texte)
        self.assertIn("(simulation) systemctl stop x", texte)

    def test_couleur_forcee(self):
        flux = io.StringIO()
        report.Rapport(flux=flux, couleur=True).fail("raté")
        self.assertIn("\x1b[", flux.getvalue())

    def test_no_color(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True

        from unittest import mock

        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertFalse(report.couleur_permise(Terminal()))
        with mock.patch.dict(os.environ, {"NO_COLOR": ""}):
            self.assertTrue(report.couleur_permise(Terminal()))

    def test_flux_qui_ne_recoit_plus_ne_leve_pas(self):
        import errno

        class Casse(io.StringIO):
            def __init__(self, erreur):
                super().__init__()
                self.erreur = erreur

            def write(self, _texte):
                raise self.erreur

        for erreur in (
            OSError(errno.EIO, "Input/output error"),
            BrokenPipeError(),
            ValueError("I/O operation on closed file"),
        ):
            with self.subTest(erreur=type(erreur).__name__):
                r = report.Rapport(flux=Casse(erreur), erreurs=Casse(erreur))
                r.etape("x")
                r.fail("x")
                r.erreur("x")

    def test_erreur_sur_stderr(self):
        sortie, erreurs = io.StringIO(), io.StringIO()
        report.Rapport(flux=sortie, erreurs=erreurs).erreur("non")
        self.assertEqual(sortie.getvalue(), "")
        self.assertIn("non", erreurs.getvalue())


if __name__ == "__main__":
    unittest.main()
