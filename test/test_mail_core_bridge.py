#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le branchement du client courriel sur le noyau des règles : anciens
chemins devenus alias, catalogue partagé, langue et traducteur du client,
journaux, amorce.

Seul fichier `test_mail_core_*` qui importe `script` : il vérifie le
client, pas le noyau seul.
"""

import ast
import importlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import script.todo.mail  # noqa: F401
from script.todo import todo_i18n
from script.todo.mail import _core_path, imap_sync, imap_transport

# isort: split
import erplibre_mail_core
from erplibre_mail_core import i18n as noyau
from erplibre_mail_core import imap
from erplibre_mail_core.catalog import CATALOG

RACINE = Path(__file__).resolve().parent.parent
LIB = str(RACINE / "script" / "lib" / "erplibre_mail_core")

ALIAS = {
    "script.todo.mail.charset": "erplibre_mail_core.charset",
    "script.todo.mail.claim": "erplibre_mail_core.claim",
    "script.todo.mail.tui_text": "erplibre_mail_core.mailtext",
    "script.todo.mail.stats": "erplibre_mail_core.stats",
    "script.todo.mail.smtp_send": "erplibre_mail_core.smtp",
    "script.todo.mail.rules.model": "erplibre_mail_core.rules.model",
    "script.todo.mail.rules.filter": "erplibre_mail_core.rules.filter",
    "script.todo.mail.rules.regex_worker": (
        "erplibre_mail_core.rules.regex_worker"
    ),
    "script.todo.mail.rules.guards": "erplibre_mail_core.rules.guards",
    "script.todo.mail.rules.markup": "erplibre_mail_core.rules.markup",
    "script.todo.mail.rules.report": "erplibre_mail_core.rules.report",
    "script.todo.mail.rules.svg": "erplibre_mail_core.rules.svg",
}


class LangCase(unittest.TestCase):
    """Rétablit la langue mémorisée du client après le test."""

    def setUp(self):
        ancienne = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)


class TestAliases(unittest.TestCase):
    def test_old_paths_are_the_core_modules(self):
        for ancien, neuf in ALIAS.items():
            with self.subTest(ancien=ancien):
                module = importlib.import_module(ancien)
                self.assertIs(module, importlib.import_module(neuf))
                parent, _, nom = ancien.rpartition(".")
                self.assertIs(
                    getattr(importlib.import_module(parent), nom), module
                )

    def test_core_is_loaded_from_this_checkout(self):
        """Le noyau vient de `script/lib/erplibre_mail_core` sous son seul
        nom de paquet : aucun module `script.lib.…`, qui en serait une
        seconde copie."""
        self.assertTrue(
            Path(erplibre_mail_core.__file__).resolve().is_relative_to(LIB)
        )
        doubles = [
            nom
            for nom in sys.modules
            if nom == "script.lib" or nom.startswith("script.lib.")
        ]
        self.assertEqual(doubles, [])

    def test_transport_reuses_the_core_classes(self):
        for nom in (
            "ImapError",
            "ImapAuthError",
            "extra_headers",
            "parse_fetch_headers",
            "EXTRA_HEADERS",
            "decode_header_value",
        ):
            with self.subTest(nom=nom):
                self.assertIs(getattr(imap_transport, nom), getattr(imap, nom))
        self.assertTrue(
            issubclass(imap_transport.ImaplibTransport, imap.ImapConnection)
        )
        for nom in ("HeaderInfo", "FolderInfo", "SelectInfo"):
            with self.subTest(nom=nom):
                self.assertIs(getattr(imap_sync, nom), getattr(imap, nom))

    def test_the_client_uses_the_core_forward_functions(self):
        """Le moteur du client transfère avec les fonctions du noyau, sous
        ses anciens noms : aucune copie locale."""
        from erplibre_mail_core.rules import forward

        from script.todo.mail.rules import engine

        self.assertIs(engine.forward_message, forward.forward_message)
        self.assertIs(engine.forward_reply_to, forward.forward_reply_to)
        self.assertIs(engine._first_msgid, forward.first_msgid)

    def test_the_client_uses_the_core_function(self):
        """La synchronisation du client reconnaît un message automatique
        par la fonction du noyau, sous son ancien nom : aucune copie
        locale."""
        from erplibre_mail_core import stats

        self.assertIs(imap_sync.is_automatic, stats.is_automatic)

    def test_an_alias_bootstraps_itself(self):
        """Un client ouvert avant la mise à jour garde l'ancien
        `__init__.py`, sans amorce, et l'ancien `todo_i18n`, sans
        `register_catalog` : l'alias importé à la demande fait l'amorce
        lui-même, ajoute au catalogue du client ses clés absentes et laisse
        les autres telles quelles."""
        code = r"""
import json, sys
import script.todo.mail
from script.todo import todo_i18n
lib, absente, gardee = sys.argv[1:4]
# L'ancien `todo_i18n` n'a pas `register_catalog` ; son catalogue peut
# manquer d'une clé du noyau ou en porter un autre texte.
del todo_i18n.register_catalog
del todo_i18n.TRANSLATIONS[absente]
todo_i18n.TRANSLATIONS[gardee] = {"fr": "texte du client", "en": "client text"}
while lib in sys.path:
    sys.path.remove(lib)
for nom in list(sys.modules):
    if nom.startswith("erplibre_mail_core") or nom in (
        "script.todo.mail._core_path", "script.todo.mail.rules.report"
    ):
        del sys.modules[nom]
# L'ancien `__init__.py` n'importait pas l'amorce : le paquet n'en porte
# pas l'attribut.
del script.todo.mail._core_path
import script.todo.mail.rules.report as report
from erplibre_mail_core import i18n
todo_i18n._current_lang = "fr"
fr = i18n.t("mail_rules_err_kind")
todo_i18n._current_lang = "en"
en = i18n.t("mail_rules_err_kind")
print(json.dumps({"compte": sys.path.count(lib), "fr": fr, "en": en,
                  "module": report.__name__,
                  "absente": todo_i18n.TRANSLATIONS.get(absente),
                  "gardee": todo_i18n.TRANSLATIONS[gardee],
                  "gardee_noyau": i18n.t(gardee, "fr")}))
"""
        absente = "mail_stats_report_col_day"
        gardee = "mail_rules_outcome_sent"
        self.assertIn(gardee, CATALOG)
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, PYTHONDONTWRITEBYTECODE="1")
            env["PYTHONPATH"] = str(RACINE)
            sortie = subprocess.run(
                [sys.executable, "-B", "-c", code, LIB, absente, gardee],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=RACINE,
                env=env,
            )
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        rapport = json.loads(sortie.stdout)
        self.assertEqual(rapport["compte"], 1)
        self.assertEqual(rapport["module"], "erplibre_mail_core.rules.report")
        self.assertEqual(rapport["fr"], CATALOG["mail_rules_err_kind"]["fr"])
        self.assertEqual(rapport["en"], CATALOG["mail_rules_err_kind"]["en"])
        self.assertEqual(rapport["absente"], CATALOG[absente])
        self.assertEqual(
            rapport["gardee"], {"fr": "texte du client", "en": "client text"}
        )
        self.assertEqual(rapport["gardee_noyau"], "texte du client")


class TestCatalog(LangCase):
    def test_client_catalog_holds_the_core_catalog(self):
        for cle, entree in CATALOG.items():
            with self.subTest(cle=cle):
                self.assertEqual(todo_i18n.TRANSLATIONS[cle], entree)

    def test_client_and_core_speak_the_same_language(self):
        for langue in ("fr", "en"):
            todo_i18n._current_lang = langue
            with self.subTest(langue=langue):
                self.assertEqual(noyau.current_lang(), langue)
                for cle, entree in CATALOG.items():
                    self.assertEqual(noyau.t(cle), todo_i18n.t(cle))
                    self.assertEqual(noyau.t(cle), entree[langue])

    def test_core_reads_the_client_catalog_at_each_call(self):
        cle = "mail_stats_report_col_day"
        with mock.patch.dict(
            todo_i18n.TRANSLATIONS, {cle: {"fr": "J<o>", "en": "D<a>"}}
        ):
            self.assertEqual(noyau.t(cle, "fr"), "J<o>")
            self.assertEqual(noyau.t(cle, "en"), "D<a>")
        self.assertEqual(noyau.t(cle, "fr"), CATALOG[cle]["fr"])

    def test_core_language_follows_a_patched_get_lang(self):
        for langue in ("en", "fr"):
            with self.subTest(langue=langue):
                with mock.patch.object(
                    todo_i18n, "get_lang", return_value=langue
                ):
                    self.assertEqual(noyau.current_lang(), langue)

    def test_no_core_key_is_written_in_the_client_file(self):
        chemin = RACINE / "script" / "todo" / "todo_i18n.py"
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        cles = set()
        for noeud in arbre.body:
            if (
                isinstance(noeud, ast.Assign)
                and getattr(noeud.targets[0], "id", None) == "TRANSLATIONS"
            ):
                cles = {k.value for k in noeud.value.keys}
        self.assertTrue(cles)
        self.assertEqual(sorted(cles & set(CATALOG)), [])
        familles = (
            "mail_rules_reason_",
            "mail_rules_outcome_",
            "mail_stats_var_",
        )
        self.assertEqual(sorted(c for c in cles if c.startswith(familles)), [])

    def test_register_catalog_refuses_a_conflicting_text(self):
        cle = "mail_rules_err_kind"
        avant = dict(todo_i18n.TRANSLATIONS[cle])
        with self.assertRaises(ValueError):
            todo_i18n.register_catalog({cle: {"fr": "autre", "en": "other"}})
        self.assertEqual(todo_i18n.TRANSLATIONS[cle], avant)

    def test_register_catalog_is_idempotent(self):
        taille = len(todo_i18n.TRANSLATIONS)
        todo_i18n.register_catalog(CATALOG)
        self.assertEqual(len(todo_i18n.TRANSLATIONS), taille)

    def test_register_catalog_adds_a_new_key(self):
        cle = "mail_test_cle_enregistree"
        self.addCleanup(todo_i18n.TRANSLATIONS.pop, cle, None)
        todo_i18n.register_catalog({cle: {"fr": "oui", "en": "yes"}})
        self.assertEqual(
            todo_i18n.TRANSLATIONS[cle], {"fr": "oui", "en": "yes"}
        )

    def test_bootstrap_puts_the_core_first_once(self):
        # D'autres modules de test du même processus peuvent avoir mis le
        # noyau sur `sys.path` : seul compte ce que l'amorce y ajoute.
        avant = sys.path.count(LIB)
        self.assertGreaterEqual(avant, 1)
        importlib.reload(_core_path)
        self.assertEqual(sys.path.count(LIB), avant)
        self.assertEqual(
            noyau.t("mail_rules_err_kind", "fr"),
            CATALOG["mail_rules_err_kind"]["fr"],
        )


class TestLogging(unittest.TestCase):
    def test_mail_logging_covers_the_core_loggers(self):
        from script.todo.mail import menu

        self.assertEqual(
            menu.MAIL_LOGGERS, ("script.todo.mail", "erplibre_mail_core")
        )
        etats = {
            nom: (
                list(logging.getLogger(nom).handlers),
                logging.getLogger(nom).level,
                logging.getLogger(nom).propagate,
            )
            for nom in menu.MAIL_LOGGERS
        }
        configure = menu._LOG_CONFIGURED
        racine = logging.getLogger()
        temoin = logging.Handler()
        temoin.emit = mock.Mock()
        temoin.setLevel(logging.DEBUG)
        racine.addHandler(temoin)
        home = tempfile.TemporaryDirectory()
        ancien_home = os.environ.get("HOME")

        def retablir():
            racine.removeHandler(temoin)
            fermes = set()
            for nom, (avant, niveau, propage) in etats.items():
                logger = logging.getLogger(nom)
                for handler in list(logger.handlers):
                    if handler not in avant:
                        logger.removeHandler(handler)
                        if id(handler) not in fermes:
                            fermes.add(id(handler))
                            handler.close()
                logger.setLevel(niveau)
                logger.propagate = propage
            menu._LOG_CONFIGURED = configure
            if ancien_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = ancien_home
            home.cleanup()

        self.addCleanup(retablir)
        os.environ["HOME"] = home.name
        menu._LOG_CONFIGURED = False
        menu._configure_mail_logging()
        logging.getLogger("erplibre_mail_core.smtp").info("ligne du noyau")
        journal = Path(home.name) / ".erplibre" / "mail.log"
        self.assertIn("erplibre_mail_core.smtp", journal.read_text())
        self.assertIn("ligne du noyau", journal.read_text())
        temoin.emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
