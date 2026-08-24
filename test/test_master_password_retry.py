#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une faute de frappe ne doit pas coûter une migration.

Le mot de passe maître était demandé UNE fois. Faux ? Odoo lève
`AccessDenied`, `check_output` lève `CalledProcessError`, rien ne
l'attrape, et la migration meurt sur une trace. Après une heure de
paliers, c'est cher payé pour une lettre.

La propriété qui porte tout : on ne redemande QUE sur un refus de mot de
passe. Reposer la question sur n'importe quel échec cacherait la vraie
panne derrière dix invites, et l'on chercherait un mot de passe alors
que la base est cassée.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.database import db_restore  # noqa: E402


class TestRecognisingTheRefusal(unittest.TestCase):
    def test_an_access_denied_is_a_refusal(self):
        self.assertTrue(
            db_restore.password_refused(
                "Traceback...\nodoo.exceptions.AccessDenied: Access Denied"
            )
        )

    def test_the_class_is_what_we_match_not_the_message(self):
        # Le message est traduit : « Accès refusé » en français. La
        # CLASSE, elle, ne bouge pas.
        self.assertTrue(
            db_restore.password_refused("odoo.exceptions.AccessDenied")
        )
        self.assertFalse(db_restore.password_refused("Accès refusé"))

    def test_anything_else_is_NOT_a_refusal(self):
        # C'est la protection : dix invites de mot de passe devant une
        # base cassée, et l'on cherche du mauvais côté.
        for sortie in (
            "psycopg2.OperationalError: could not connect",
            "FileNotFoundError: ./odoo_bin.sh",
            "",
            None,
        ):
            self.assertFalse(db_restore.password_refused(sortie), sortie)


class TestTheRetryLoop(unittest.TestCase):
    def setUp(self):
        self.vrais = (
            db_restore.get_master_password,
            db_restore.probe_master_password,
        )
        self.demandes = 0
        self.sondes = []

    def tearDown(self):
        (
            db_restore.get_master_password,
            db_restore.probe_master_password,
        ) = self.vrais

    def branche(self, mots, reponses):
        suite = iter(mots)
        rep = iter(reponses)

        def demander():
            self.demandes += 1
            return next(suite, "")

        def sonder(arg_base, mot):
            self.sondes.append((arg_base, mot))
            return next(rep, (False, "AccessDenied"))

        db_restore.get_master_password = demander
        db_restore.probe_master_password = sonder

    def lance(self, essais=10):
        tampon = io.StringIO()
        with redirect_stdout(tampon), redirect_stderr(tampon):
            return db_restore.ask_master_password("./odoo_bin.sh db", essais)

    def test_a_good_password_is_returned_at_once(self):
        self.branche(["bon"], [(True, "db1\ndb2")])
        self.assertEqual(self.lance(), "bon")
        self.assertEqual(self.demandes, 1)

    def test_a_typo_is_asked_again(self):
        self.branche(
            ["faux", "bon"],
            [(False, "odoo.exceptions.AccessDenied"), (True, "db1")],
        )
        self.assertEqual(self.lance(), "bon")
        self.assertEqual(self.demandes, 2)

    def test_it_stops_after_the_allowed_attempts(self):
        # Sans borne, une invite non lue tournerait toute la nuit.
        self.branche(["faux"] * 20, [(False, "AccessDenied")] * 20)
        self.assertIsNone(self.lance(essais=10))
        self.assertEqual(self.demandes, 10)

    def test_an_empty_prompt_gives_up_immediately(self):
        # Ctrl-D ou Entrée : on ne veut pas neuf invites de plus.
        self.branche([""], [])
        self.assertIsNone(self.lance())
        self.assertEqual(self.demandes, 1)
        self.assertEqual(self.sondes, [])

    def test_an_unrelated_failure_stops_instead_of_asking_again(self):
        # LA propriété. Une base injoignable n'est pas un mot de passe
        # faux, et redemander dix fois cacherait la vraie panne.
        self.branche(["bon"], [(False, "psycopg2.OperationalError: refused")])
        self.assertIsNone(self.lance())
        self.assertEqual(self.demandes, 1)

    def test_the_unrelated_failure_is_shown(self):
        self.branche(["bon"], [(False, "psycopg2.OperationalError: refused")])
        with self.assertLogs(db_restore._logger, level="ERROR") as journal:
            db_restore.ask_master_password("./odoo_bin.sh db")
        self.assertIn("OperationalError", "\n".join(journal.output))

    def test_the_probe_carries_the_password_and_touches_nothing(self):
        # Valider ici évite d'échouer à mi-parcours, une fois la base
        # déjà supprimée. La sonde demande un `drop` sur un nom qui
        # n'existe pas : `check_super` s'exécute AVANT `db_exists`, donc
        # elle répond sans rien toucher.
        self.branche(["bon"], [(True, "db1")])
        self.lance()
        self.assertEqual(len(self.sondes), 1)
        arg_base, mot = self.sondes[0]
        self.assertEqual(mot, "bon")
        # Le secret est passé À CÔTÉ de la commande, jamais dedans :
        # /proc/<pid>/cmdline est lisible par tout utilisateur de la
        # machine. C'est la garantie que ce test tient.
        self.assertNotIn("bon", arg_base)
        self.assertNotIn("--master_password", arg_base)

    def test_each_attempt_probes_with_ITS_password(self):
        self.branche(
            ["un", "deux"],
            [(False, "AccessDenied"), (True, "db1")],
        )
        self.lance()
        self.assertEqual([mot for _, mot in self.sondes], ["un", "deux"])
        for arg_base, _ in self.sondes:
            self.assertNotIn("--master_password", arg_base)


class TestTheWiring(unittest.TestCase):
    def source(self):
        with io.open(db_restore.__file__, encoding="utf-8") as handle:
            return handle.read()

    def test_the_flow_uses_the_retrying_version(self):
        src = self.source()
        self.assertIn("master_password = ask_master_password(arg_base)", src)

    def bloc_sonde(self):
        """Le CODE de la sonde, docstring retirée.

        La docstring EXPLIQUE pourquoi `--list` et `--restore` ne
        conviennent pas : un test qui lit tout le texte les y trouve et
        se croit trompé. Troisième fois que ce piège se referme sur moi
        dans ce dépôt — voir tasks/lessons.md.
        """
        import ast

        for noeud in ast.walk(ast.parse(self.source())):
            if (
                isinstance(noeud, ast.FunctionDef)
                and noeud.name == "probe_master_password"
            ):
                sans_texte = [
                    n
                    for n in noeud.body
                    if not (
                        isinstance(n, ast.Expr)
                        and isinstance(n.value, ast.Constant)
                        and isinstance(n.value.value, str)
                    )
                ]
                return ast.dump(ast.Module(body=sans_texte, type_ignores=[]))
        return ""

    def test_the_scan_finds_the_probe_at_all(self):
        # Sans cette borne, les tests suivants passeraient sur une chaîne
        # vide le jour où la fonction est renommée.
        self.assertTrue(self.bloc_sonde())

    def test_the_probe_uses_the_only_action_that_reads_the_password(self):
        # `--list` ne LIT jamais le mot de passe : mesuré,
        # MASTER_PWD="ceci_est_faux" … db --list sort en 0. La sonde
        # d'avant acceptait donc le premier mot saisi, et la boucle des
        # dix essais ne servait à rien. Seul `drop` consulte le secret.
        bloc = self.bloc_sonde()
        self.assertIn("--drop", bloc)
        self.assertNotIn("--list", bloc)

    def test_it_never_names_a_database_that_could_exist(self):
        # La sonde DEMANDE une suppression : sur un vrai nom et avec un
        # bon mot de passe, on perdrait la base. Le nom vient d'un uuid.
        bloc = self.bloc_sonde()
        # L'arbre nomme les appels : `Call(func=Name(id='probe_name'))`.
        self.assertIn("id='probe_name'", bloc)
        # …et jamais la base que l'appelant vise.
        self.assertNotIn("id='database'", bloc)

    def test_it_never_asks_to_restore_or_clone(self):
        bloc = self.bloc_sonde()
        for danger in ("--restore", "--clone"):
            self.assertNotIn(danger, bloc)

    def test_the_bound_is_ten(self):
        self.assertEqual(db_restore.MAX_ESSAIS_MOT_DE_PASSE, 10)


class TestTheProbeName(unittest.TestCase):
    """Le nom que la sonde demande de supprimer.

    C'est le seul endroit de cet outil où une erreur coûterait une base.
    """

    def test_it_is_prefixed_so_a_log_says_where_it_came_from(self):
        self.assertTrue(db_restore.probe_name().startswith("el_probe_"))

    def test_two_calls_never_give_the_same_name(self):
        noms = {db_restore.probe_name() for _ in range(50)}
        self.assertEqual(50, len(noms))

    def test_it_is_long_enough_to_be_unguessable(self):
        # Un uuid4 en hexadécimal : 32 caractères après le préfixe.
        self.assertGreaterEqual(
            len(db_restore.probe_name()), len("el_probe_") + 32
        )

    def test_it_is_a_legal_postgresql_identifier(self):
        # Un nom que PostgreSQL refuserait ferait échouer la sonde pour
        # une raison qui n'a rien à voir avec le mot de passe, et l'on
        # redemanderait dix fois un secret parfaitement bon.
        self.assertRegex(db_restore.probe_name(), r"^[a-z][a-z0-9_]{0,62}$")


if __name__ == "__main__":
    unittest.main()
