#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""script/lib_ops/odoo_conf.py et script/odoo/odoo_conf_check.py.

Chaque refus est confronté à configparser STRICT et aux convertisseurs
d'optparse, les deux briques qu'Odoo emploie : une erreur annoncée doit
être une erreur que ces briques lèvent, et un fichier qu'elles acceptent
ne doit pas être refusé. Les fichiers de configuration sont inventés, un
par version d'Odoo de 12 à 18 ; l'outil en ligne de commande est appelé en
processus, avec un systemctl de théâtre.
"""

import ast
import configparser
import contextlib
import io
import json
import optparse
import os
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from profil_isole import profil_isole  # noqa: E402

from script.lib_ops import odoo_conf  # noqa: E402
from script.odoo import odoo_conf_check as occ  # noqa: E402

MO = 1024 * 1024


def setUpModule():
    profil_isole()


def codes(verification, niveau=None):
    return [
        c.code
        for c in verification.constats
        if niveau is None or c.niveau == niveau
    ]


def refuse_par_odoo(texte, version):
    """True si configparser strict ou une conversion d'optparse lève,
    comme dans `odoo/tools/config.py`."""
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(texte)
    except configparser.Error:
        return True
    if not parser.has_section("options"):
        return False
    types = odoo_conf.types_options(version)
    for cle, valeur in parser.items("options"):
        cle = odoo_conf.ANCIENS_NOMS.get(cle, cle)
        if cle not in types or valeur in odoo_conf.BOOLEENS:
            continue
        if types[cle] == "choice":
            option = optparse.Option(
                "--x", type="choice", choices=list(odoo_conf.CHOIX[cle])
            )
        else:
            option = optparse.Option("--x", type=types[cle])
        try:
            optparse.Option.TYPE_CHECKER[types[cle]](option, "x", valeur)
        except optparse.OptionValueError:
            return True
    return False


# Un fichier valide par version, aux valeurs inventées : ce que chaque
# version lit sans erreur.
VALIDES = {
    12: (
        "[options]\naddons_path = /srv/exemple/addons\nxmlrpc_port = 8069\n"
        "longpolling_port = 8072\nworkers = 2\nosv_memory_age_limit = 1.0\n"
        "db_name = exemple_db\n"
    ),
    14: (
        "[options]\nhttp_port = 8069\nlongpolling_port = 8072\n"
        "transient_age_limit = 1.5\nworkers = 3\n"
    ),
    16: (
        "[options]\nhttp_port = 8069\ngevent_port = 8072\nworkers = 2\n"
        "limit_memory_soft = 2147483648\nlimit_memory_hard = 2684354560\n"
    ),
    17: (
        "[options]\nhttp_port = 8069\ngevent_port = 8072\n"
        "osv_memory_age_limit = 1.0\nmax_cron_threads = 1\n"
    ),
    18: (
        "[options]\nhttp_port = 8069\ngevent_port = 8072\nworkers = 4\n"
        "limit_memory_soft = 2147483648\nlimit_memory_hard = 2684354560\n"
        "limit_memory_soft_gevent = 2147483648\n"
        "limit_memory_hard_gevent = 2684354560\n"
        "transient_age_limit = 1.0\nlimit_time_worker_cron = 0\n"
        "addons_path = /srv/exemple/addons,\n    /srv/exemple/autres\n"
        "list_db = False\n"
    ),
}


class TestStructure(unittest.TestCase):
    def test_fichiers_valides_par_version(self):
        for version, texte in VALIDES.items():
            with self.subTest(version=version):
                self.assertFalse(refuse_par_odoo(texte, version))
                verification = odoo_conf.verifier_texte(texte, version)
                self.assertEqual(verification.erreurs(), [])
                self.assertFalse(verification.refuse)

    def test_cle_repetee_toutes_relevees(self):
        texte = (
            "[options]\nworkers = 2\nhttp_port = 8069\nworkers = 3\n"
            "http_port = 8070\n"
        )
        self.assertTrue(refuse_par_odoo(texte, 18))
        verification = odoo_conf.verifier_texte(texte, 18)
        doublons = [c for c in verification.erreurs() if c.code == "duplicate"]
        self.assertEqual(
            [(c.ligne, c.cle, c.valeurs["first"]) for c in doublons],
            [(4, "workers", 2), (5, "http_port", 3)],
        )
        # configparser ne voit que la première : pas de second constat.
        self.assertNotIn("syntax_other", codes(verification))

    def test_cle_repetee_casse_differente(self):
        texte = "[options]\nWorkers = 2\nworkers = 3\n"
        self.assertTrue(refuse_par_odoo(texte, 18))
        self.assertIn(
            "duplicate", codes(odoo_conf.verifier_texte(texte, 18), "error")
        )

    def test_meme_cle_dans_deux_sections_admise(self):
        texte = "[options]\nchannels = a\n[queue_job]\nchannels = b\n"
        self.assertFalse(refuse_par_odoo(texte, 18))
        self.assertEqual(odoo_conf.verifier_texte(texte, 18).erreurs(), [])

    def test_section_repetee(self):
        texte = "[options]\nworkers = 2\n\n[options]\nhttp_port = 8069\n"
        self.assertTrue(refuse_par_odoo(texte, 18))
        (erreur,) = odoo_conf.verifier_texte(texte, 18).erreurs()
        self.assertEqual(erreur.code, "duplicate_section")
        self.assertEqual(erreur.ligne, 4)

    def test_ligne_hors_section(self):
        texte = "workers = 2\n[options]\nhttp_port = 8069\n"
        self.assertTrue(refuse_par_odoo(texte, 18))
        (erreur,) = odoo_conf.verifier_texte(texte, 18).erreurs()
        self.assertEqual((erreur.code, erreur.ligne), ("outside", 1))

    def test_ligne_sans_egal(self):
        texte = "[options]\nworkers\nhttp_port = 8069\n"
        self.assertTrue(refuse_par_odoo(texte, 18))
        (erreur,) = odoo_conf.verifier_texte(texte, 18).erreurs()
        self.assertEqual((erreur.code, erreur.ligne), ("syntax", 2))

    def test_continuation_et_commentaires_admis(self):
        texte = (
            "; en-tête\n[options]\n# workers = 9\naddons_path = /a,\n"
            "    /b,\n\n    /c\nworkers = 2\n"
        )
        self.assertFalse(refuse_par_odoo(texte, 18))
        verification = odoo_conf.verifier_texte(texte, 18)
        self.assertEqual(verification.erreurs(), [])
        self.assertEqual(verification.valeurs["addons_path"], "/a,\n/b,\n\n/c")

    def test_sans_section_options(self):
        """Odoo démarre avec ses valeurs par défaut : un avertissement, pas
        un refus."""
        texte = "[queue_job]\na = 1\n"
        self.assertFalse(refuse_par_odoo(texte, 18))
        verification = odoo_conf.verifier_texte(texte, 18)
        self.assertEqual(codes(verification, "warning"), ["no_options"])
        self.assertFalse(verification.refuse)
        self.assertEqual(verification.valeurs, {})

    def test_fichier_vide(self):
        for texte in ("", "# seulement un commentaire\n"):
            with self.subTest(texte=texte):
                self.assertFalse(refuse_par_odoo(texte, 18))
                verification = odoo_conf.verifier_texte(texte, 18)
                self.assertEqual(
                    codes(verification, "warning"), ["no_options"]
                )
                self.assertFalse(verification.refuse)


class TestTypes(unittest.TestCase):
    def test_commentaire_apres_une_valeur_typee(self):
        texte = "[options]\nlimit_memory_soft_gevent = 2147483648 # 2048 Mo\n"
        self.assertTrue(refuse_par_odoo(texte, 18))
        (erreur,) = odoo_conf.verifier_texte(texte, 18).erreurs()
        self.assertEqual(erreur.code, "inline_typed")
        self.assertEqual(erreur.valeurs["clean"], "2147483648")
        self.assertIn(
            "limit_memory_soft_gevent = 2147483648", erreur.message()
        )

    def test_commentaire_apres_une_valeur_texte_avertit(self):
        texte = "[options]\nlist_db = False # cache le gestionnaire\n"
        self.assertFalse(refuse_par_odoo(texte, 18))
        verification = odoo_conf.verifier_texte(texte, 18)
        self.assertEqual(verification.erreurs(), [])
        self.assertEqual(codes(verification, "warning"), ["inline_text"])

    def test_option_a_choix(self):
        """log_level et db_sslmode passent par le convertisseur « choice »
        d'optparse : une valeur hors de la liste, casse comprise, ou suivie
        d'un commentaire arrête Odoo."""
        for ligne, code in (
            ("log_level = warn", None),
            ("log_level = debug_rpc_answer", None),
            ("log_level = False", None),
            ("db_sslmode = verify-full", None),
            ("log_level = warning", "choice"),
            ("log_level = INFO", "choice"),
            ("log_level = warn # plus calme", "inline_choice"),
            ("db_sslmode = required", "choice"),
        ):
            texte = f"[options]\n{ligne}\n"
            for version in (12, 16, 18, None):
                with self.subTest(ligne=ligne, version=version):
                    self.assertEqual(
                        refuse_par_odoo(texte, version), code is not None
                    )
                    verification = odoo_conf.verifier_texte(texte, version)
                    self.assertEqual(
                        codes(verification, "error"), [code] if code else []
                    )
        (erreur,) = odoo_conf.verifier_texte(
            "[options]\nlog_level = warn # plus calme\n", 18
        ).erreurs()
        self.assertIn("log_level = warn'", erreur.message())
        self.assertIn("debug_rpc_answer", erreur.message())

    def test_choix_ceux_d_odoo_18(self):
        """CHOIX reprend les listes du config.py d'Odoo 18 du checkout,
        quand il est là."""
        chemin = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "odoo18.0",
            "odoo",
            "odoo",
            "tools",
            "config.py",
        )
        if not os.path.isfile(chemin):
            self.skipTest("odoo18.0 absent")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        trouves = {}
        for noeud in ast.walk(arbre):
            if (
                isinstance(noeud, ast.Assign)
                and len(noeud.targets) == 1
                and getattr(noeud.targets[0], "id", "") == "levels"
            ):
                trouves["log_level"] = tuple(ast.literal_eval(noeud.value))
            if isinstance(noeud, ast.Call):
                mots = {k.arg: k.value for k in noeud.keywords}
                if "choices" in mots and "dest" in mots:
                    dest = ast.literal_eval(mots["dest"])
                    if dest in odoo_conf.CHOIX and isinstance(
                        mots["choices"], ast.List
                    ):
                        trouves[dest] = tuple(
                            ast.literal_eval(mots["choices"])
                        )
        self.assertEqual(trouves, odoo_conf.CHOIX)

    def test_commentaire_apres_une_cle_de_connexion(self):
        """Odoo lit le fichier, mais passe la valeur telle quelle à
        PostgreSQL ou au socket : une erreur. db_password reste un
        avertissement, un mot de passe pouvant contenir « # »."""
        for ligne, niveau in (
            ("db_host = localhost # socket local", "error"),
            ("db_user = exemple ; compte", "error"),
            ("db_name = exemple_db # base", "error"),
            ("http_interface = 192.0.2.10 ; local", "error"),
            ("xmlrpc_interface = 192.0.2.10 ; local", "error"),
            ("db_password = mdp-invente # note", "warning"),
            ("dbfilter = ^exemple$ # filtre", "warning"),
        ):
            texte = f"[options]\n{ligne}\n"
            with self.subTest(ligne=ligne):
                self.assertFalse(refuse_par_odoo(texte, 18))
                verification = odoo_conf.verifier_texte(texte, 18)
                self.assertEqual(len(verification.de_niveau(niveau)), 1)
                (constat,) = verification.de_niveau(niveau)
                self.assertEqual(
                    constat.code,
                    "inline_connection"
                    if niveau == "error"
                    else "inline_text",
                )

    def test_secret_jamais_cite(self):
        texte = (
            "[options]\nadmin_passwd = mdp-invente-4f2a # note\n"
            "db_password = autre-mdp-invente-9b1c # note\n"
        )
        verification = odoo_conf.verifier_texte(texte, 18)
        tout = json.dumps(verification.json()) + "".join(
            c.decrire() for c in verification.constats
        )
        self.assertNotIn("mdp-invente-4f2a", tout)
        self.assertNotIn("autre-mdp-invente-9b1c", tout)
        self.assertEqual(len(verification.avertissements()), 2)

    def test_compte_d_une_adresse_jamais_cite(self):
        """Une clé au nom de secret (`sentry_dsn`) est masquée ; le compte
        et le mot de passe d'une adresse le sont quelle que soit la clé."""
        texte = (
            "[options]\n"
            "sentry_dsn = https://cle-inventee:mdp-invente-7d3e"
            "@sentry.example.org/1  # note\n"
            "proxy_url = https://compte:mdp-invente-2c8f"
            "@proxy.example.org/  # note\n"
        )
        verification = odoo_conf.verifier_texte(texte, 18)
        tout = json.dumps(verification.json()) + "".join(
            c.decrire() for c in verification.constats
        )
        for secret in ("mdp-invente-7d3e", "mdp-invente-2c8f", "cle-inventee"):
            self.assertNotIn(secret, tout)
        self.assertIn("https://***@proxy.example.org/", tout)
        self.assertEqual(len(verification.avertissements()), 2)

    def test_conversions_d_optparse(self):
        """Ce qu'optparse accepte passe ; « 08 » (octal) et « 2048MB »
        non, comme dans Odoo."""
        for valeur, refuse in (
            ("4", False),
            ("-1", False),
            ("0x10", False),
            ("1_000", False),
            ("True", False),
            ("false", False),
            ("TRUE", True),
            ("08", True),
            ("2048MB", True),
            ("", True),
            ("4.0", True),
        ):
            texte = f"[options]\nworkers = {valeur}\n"
            with self.subTest(valeur=valeur):
                self.assertEqual(refuse_par_odoo(texte, 18), refuse)
                verification = odoo_conf.verifier_texte(texte, 18)
                self.assertEqual(verification.refuse, refuse)

    def test_decimal(self):
        texte = "[options]\ntransient_age_limit = une heure\n"
        verification = odoo_conf.verifier_texte(texte, 18)
        self.assertEqual(codes(verification, "error"), ["float"])
        self.assertFalse(
            odoo_conf.verifier_texte(
                "[options]\ntransient_age_limit = 1e1\n", 18
            ).refuse
        )

    def test_types_selon_la_version(self):
        """Une option typée dans une version, texte ou inconnue dans une
        autre : refusée seulement là où Odoo la convertit."""
        for cle, valeur, refusee_dans in (
            ("longpolling_port", "x", (12, 13, 14, 15, 16)),
            ("gevent_port", "x", (16, 17, 18)),
            ("limit_memory_soft_gevent", "x", (18,)),
            ("db_replica_port", "x", (18,)),
            ("osv_memory_age_limit", "x", (12, 13, 14, 15, 16, 17)),
            ("transient_age_limit", "x", (14, 15, 16, 17, 18)),
            ("xmlrpc_port", "x", (12, 13, 14, 15, 16, 17, 18)),
        ):
            texte = f"[options]\n{cle} = {valeur}\n"
            for version in range(12, 19):
                with self.subTest(cle=cle, version=version):
                    attendu = version in refusee_dans
                    self.assertEqual(refuse_par_odoo(texte, version), attendu)
                    self.assertEqual(
                        odoo_conf.verifier_texte(texte, version).refuse,
                        attendu,
                    )

    def test_version_inconnue_types_communs(self):
        verification = odoo_conf.verifier_texte(
            "[options]\ngevent_port = x\nworkers = x\n"
        )
        self.assertEqual([c.cle for c in verification.erreurs()], ["workers"])
        self.assertIn("version_unknown", codes(verification, "info"))

    def test_default_s_applique_a_options(self):
        texte = "[DEFAULT]\nworkers = deux\n[options]\nhttp_port = 8069\n"
        self.assertTrue(refuse_par_odoo(texte, 18))
        self.assertEqual(
            codes(odoo_conf.verifier_texte(texte, 18), "error"), ["int"]
        )


class TestNoms(unittest.TestCase):
    def test_longpolling_selon_la_version(self):
        texte = "[options]\nlongpolling_port = 8073\n"
        self.assertEqual(
            codes(odoo_conf.verifier_texte(texte, 18), "warning"),
            ["longpolling_ignored"],
        )
        self.assertIn(
            "longpolling_alias", codes(odoo_conf.verifier_texte(texte, 16))
        )
        self.assertNotIn(
            "longpolling_alias", codes(odoo_conf.verifier_texte(texte, 15))
        )

    def test_ancien_nom_et_conflit(self):
        verification = odoo_conf.verifier_texte(
            "[options]\nxmlrpc_port = 8069\n", 18
        )
        self.assertEqual(codes(verification, "info")[:1], ["old_name"])
        verification = odoo_conf.verifier_texte(
            "[options]\nhttp_port = 8069\nxmlrpc_port = 8070\n", 18
        )
        (avertissement,) = verification.avertissements()
        self.assertEqual(avertissement.code, "old_name_conflict")
        self.assertEqual(avertissement.valeurs["kept"], "xmlrpc_port")


class TestMemoire(unittest.TestCase):
    def test_limite_ecrite_en_mo(self):
        texte = "[options]\nworkers = 2\nlimit_memory_hard = 2560\n"
        verification = odoo_conf.verifier_texte(texte, 18)
        (erreur,) = verification.erreurs()
        self.assertEqual(erreur.code, "bytes")
        self.assertEqual(erreur.valeurs["bytes"], 2560 * MO)

    def test_zero_admis(self):
        texte = "[options]\nlimit_memory_hard = 0\n"
        self.assertEqual(odoo_conf.verifier_texte(texte, 18).erreurs(), [])

    def test_douce_au_dessus_de_la_dure(self):
        texte = (
            "[options]\nlimit_memory_soft = 3221225472\n"
            "limit_memory_hard = 2147483648\n"
        )
        self.assertEqual(
            codes(odoo_conf.verifier_texte(texte, 18), "warning"),
            ["soft_hard"],
        )

    def test_douce_trop_basse_avec_workers(self):
        texte = "[options]\nworkers = 2\nlimit_memory_soft = 671088640\n"
        self.assertIn(
            "soft_low", codes(odoo_conf.verifier_texte(texte, 18), "warning")
        )
        sans_workers = texte.replace("workers = 2", "workers = 0")
        self.assertNotIn(
            "soft_low", codes(odoo_conf.verifier_texte(sans_workers, 18))
        )

    def test_limites_gevent_en_18_seulement(self):
        texte = "[options]\nworkers = 2\n"
        constats = [
            c
            for c in odoo_conf.verifier_texte(texte, 18).infos()
            if c.code == "gevent_unset"
        ]
        self.assertEqual(len(constats), 1)
        self.assertIn("limit_memory_hard_gevent", constats[0].cle)
        self.assertNotIn(
            "gevent_unset", codes(odoo_conf.verifier_texte(texte, 16))
        )


class TestConseils(unittest.TestCase):
    def conseils(self, texte, cpus, memoire):
        valeurs, _ = odoo_conf._valeurs_options(texte)
        return odoo_conf.conseiller(valeurs, cpus, memoire)

    def test_sans_ressources_aucun_conseil(self):
        self.assertEqual(self.conseils("[options]\n", None, 8192), [])
        self.assertEqual(self.conseils("[options]\n", 4, None), [])

    def test_workers_zero(self):
        (constat,) = self.conseils("[options]\n", 4, 16384)
        self.assertEqual(constat.code, "workers0")
        self.assertEqual(constat.niveau, "info")
        self.assertLessEqual(constat.valeurs["suggested"], 9)

    def test_trop_de_workers(self):
        codes_ = [
            c.code
            for c in self.conseils("[options]\nworkers = 12\n", 2, 65536)
        ]
        self.assertIn("too_many", codes_)

    def test_memoire_trop_courte(self):
        constats = self.conseils("[options]\nworkers = 12\n", 8, 4096)
        codes_ = {c.code: c for c in constats}
        self.assertIn("memory_short", codes_)
        self.assertIn("memory_need", codes_)
        self.assertGreater(codes_["memory_short"].valeurs["ram_needed"], 4096)

    def test_limites_conseillees(self):
        constats = self.conseils("[options]\nworkers = 4\n", 4, 8192)
        (limites,) = [c for c in constats if c.code == "limits"]
        self.assertLess(limites.valeurs["soft"], limites.valeurs["hard"])
        self.assertEqual(
            limites.valeurs["hard_bytes"], limites.valeurs["hard"] * MO
        )

    def test_plan_memoire(self):
        plan = odoo_conf.plan_memoire(16384, 4, 2)
        self.assertFalse(plan.trop)
        self.assertGreaterEqual(plan.souple, plan.plancher)
        self.assertLess(plan.souple, plan.dure)
        plan = odoo_conf.plan_memoire(2048, 8, 2)
        self.assertTrue(plan.trop)
        self.assertEqual(plan.souple, plan.plancher)
        self.assertGreater(plan.ram_necessaire, 2048)

    def test_memoire_necessaire(self):
        self.assertEqual(odoo_conf.memoire_necessaire(100, 8192), 8192)
        self.assertGreater(odoo_conf.memoire_necessaire(20000, 8192), 20000)


class TestVersionsEtRessources(unittest.TestCase):
    def test_version_majeure(self):
        for texte, attendu in (
            ("18.0", 18),
            ("12.0\n", 12),
            (16, 16),
            ("11.0", None),
            ("19.0", None),
            ("", None),
            ("abc", None),
        ):
            with self.subTest(texte=texte):
                self.assertEqual(odoo_conf.version_majeure(texte), attendu)

    def test_version_instance(self):
        with tempfile.TemporaryDirectory() as dossier:
            self.assertIsNone(odoo_conf.version_instance(dossier))
            self.assertEqual(
                odoo_conf.version_instance(
                    dossier, ["/srv/exemple/odoo16.0/odoo/odoo-bin"]
                ),
                16,
            )
            with open(os.path.join(dossier, ".odoo-version"), "w") as f:
                f.write("17.0\n")
            self.assertEqual(
                odoo_conf.version_instance(
                    dossier, ["/srv/exemple/odoo16.0/odoo/odoo-bin"]
                ),
                17,
            )

    def test_ressources_hote(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "meminfo")
            with open(chemin, "w") as f:
                f.write("MemTotal:        8388608 kB\nMemFree: 1 kB\n")
            cpus, memoire = odoo_conf.ressources_hote(chemin)
            self.assertEqual(memoire, 8192)
            self.assertGreaterEqual(cpus, 1)
            self.assertIsNone(
                odoo_conf.ressources_hote(os.path.join(dossier, "absent"))[1]
            )

    def test_verifier_laisse_remonter_oserror(self):
        with self.assertRaises(OSError):
            odoo_conf.verifier("/nonexistent/exemple.conf", 18)


class FauxSysteme(occ.Systeme):
    """Un systemctl de théâtre pour l'unité `erplibre_exemple.service`
    dont le dossier de travail est `wd` ; ressources fixées."""

    def __init__(self, wd):
        super().__init__()
        self.wd = wd
        self.appels = []

    def lanceur(self, argv, timeout=60):
        self.appels.append(list(argv))
        if argv[:2] == ["systemctl", "show"]:
            return 0, (
                "LoadState=loaded\nActiveState=active\nUser=exemple\n"
                f"WorkingDirectory={self.wd}\n"
                "ExecStart={ path=/bin/bash ; argv[]=/bin/bash"
                f" {self.wd}/run.sh ; ignore_errors=no }}\n"
                "Environment=\n"
            )
        return 1, "commande inattendue"

    def ressources(self):
        return 4, 8192


class TestOutil(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.wd = d.name
        with open(os.path.join(self.wd, "run.sh"), "w") as f:
            f.write("#!/bin/bash\n")
        with open(os.path.join(self.wd, ".odoo-version"), "w") as f:
            f.write("18.0\n")

    def ecrire(self, texte, nom="config.conf"):
        chemin = os.path.join(self.wd, nom)
        with open(chemin, "w") as f:
            f.write(texte)
        return chemin

    def lancer(self, *argv):
        sortie, erreurs = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            code = occ.main(list(argv), FauxSysteme(self.wd), sortie)
        return code, sortie.getvalue(), erreurs.getvalue()

    def test_unite_et_fichier_valides(self):
        self.ecrire(VALIDES[18])
        code, sortie, _ = self.lancer("--service", "erplibre_exemple")
        self.assertEqual(code, occ.CODE_OK, sortie)
        self.assertIn(os.path.join(self.wd, "config.conf"), sortie)
        self.assertIn("erplibre_exemple.service", sortie)

    def test_doublon_rend_1(self):
        self.ecrire("[options]\nworkers = 2\nworkers = 3\n")
        code, sortie, _ = self.lancer("--service", "erplibre_exemple")
        self.assertEqual(code, occ.CODE_ERREUR)
        self.assertIn("workers", sortie)

    def test_json_anglais_et_stable(self):
        chemin = self.ecrire(
            "[options]\nworkers = 2\nlimit_memory_hard = 2560\n", "autre.conf"
        )
        code, sortie, _ = self.lancer("--file", chemin, "--json")
        self.assertEqual(code, occ.CODE_ERREUR)
        resume = json.loads(sortie)
        self.assertEqual(resume["tool"], "odoo_conf_check")
        self.assertEqual(resume["odoo_version"], 18)
        self.assertEqual(resume["host"], {"cpus": 4, "memory_mb": 8192})
        self.assertEqual(resume["summary"]["error"], 1)
        (erreur,) = [f for f in resume["findings"] if f["level"] == "error"]
        self.assertEqual(
            (erreur["code"], erreur["line"], erreur["key"]),
            ("bytes", 3, "limit_memory_hard"),
        )
        self.assertIn("bytes", erreur["message"])

    def test_version_et_ressources_de_la_ligne_de_commande(self):
        chemin = self.ecrire(
            "[options]\nlongpolling_port = 8072\nworkers = 2\n", "v16.conf"
        )
        code, sortie, _ = self.lancer(
            "--file",
            chemin,
            "--odoo-version",
            "16.0",
            "--cpus",
            "2",
            "--memory-mb",
            "4096",
            "--json",
        )
        self.assertEqual(code, occ.CODE_OK)
        resume = json.loads(sortie)
        self.assertEqual(resume["odoo_version"], 16)
        self.assertEqual(resume["host"], {"cpus": 2, "memory_mb": 4096})
        self.assertIn(
            "longpolling_alias", [f["code"] for f in resume["findings"]]
        )

    def test_fichier_absent_rend_2(self):
        code, _sortie, erreurs = self.lancer(
            "--file", os.path.join(self.wd, "absent.conf")
        )
        self.assertEqual(code, occ.CODE_REFUS)
        self.assertIn("absent.conf", erreurs)

    def test_fichier_illisible_conseille_sudo(self):
        if os.geteuid() == 0:
            self.skipTest("root lit tout")
        chemin = self.ecrire(VALIDES[18])
        os.chmod(chemin, 0)
        self.addCleanup(os.chmod, chemin, 0o600)
        code, _sortie, erreurs = self.lancer("--file", chemin)
        self.assertEqual(code, occ.CODE_REFUS)
        self.assertIn("sudo", erreurs)

    def test_sans_configuration_rend_2(self):
        code, _sortie, erreurs = self.lancer("--service", "erplibre_exemple")
        self.assertEqual(code, occ.CODE_REFUS)
        self.assertIn("--file", erreurs)

    def test_file_et_service_exclusifs(self):
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as fin,
        ):
            occ.analyser(["--file", "/var/tmp/e.conf", "--service", "x"])
        self.assertEqual(fin.exception.code, 2)

    def test_lecture_seule(self):
        chemin = self.ecrire("[options]\nworkers = 2 # deux\n")
        avant = os.stat(chemin)
        listing = sorted(os.listdir(self.wd))
        self.assertEqual(self.lancer("--file", chemin)[0], occ.CODE_ERREUR)
        apres = os.stat(chemin)
        self.assertEqual(
            (apres.st_mtime_ns, apres.st_size),
            (avant.st_mtime_ns, avant.st_size),
        )
        self.assertEqual(sorted(os.listdir(self.wd)), listing)


if __name__ == "__main__":
    unittest.main()
