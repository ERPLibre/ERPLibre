#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La traduction du noyau des règles : son catalogue, la langue en
paramètre, le contexte `using_lang` et le réglage `configure`.

N'importe que la bibliothèque standard et `erplibre_mail_core` : la suite
tourne aussi sous le Python d'Odoo.
"""

import ast
import email
import email.policy
import re
import sys
import threading
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
NOYAU = RACINE / "script" / "lib" / "erplibre_mail_core"
if str(NOYAU) not in sys.path:
    sys.path.insert(0, str(NOYAU))

from erplibre_mail_core import i18n  # noqa: E402
from erplibre_mail_core.catalog import CATALOG  # noqa: E402

PAQUET = NOYAU / "erplibre_mail_core"
CLE = "mail_rules_err_kind"
CLE_RE = re.compile(r"mail_[a-z_]+")


def neutre(test: unittest.TestCase) -> None:
    """Remet le noyau sans configuration pour la durée du test, et repose
    ensuite le réglage d'avant : un client chargé dans le même processus
    garde le sien."""
    precedent = i18n.configure(default_lang=None, translator=None)
    test.addCleanup(lambda: i18n.configure(**precedent))


def constantes_de_cles(chemin: Path) -> set[str]:
    """Les constantes `str` d'un fichier qui sont entièrement une clé
    `mail_…`, hors morceaux d'une f-string."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    dans_fstring = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.JoinedStr):
            for valeur in noeud.values:
                dans_fstring.add(id(valeur))
    return {
        noeud.value
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Constant)
        and isinstance(noeud.value, str)
        and id(noeud) not in dans_fstring
        and CLE_RE.fullmatch(noeud.value)
    }


class TestCatalog(unittest.TestCase):
    def test_catalog_has_the_174_keys_in_both_languages(self):
        self.assertEqual(len(CATALOG), 174)
        for cle, entree in CATALOG.items():
            with self.subTest(cle=cle):
                self.assertTrue(entree.get("fr"))
                self.assertTrue(entree.get("en"))

    def test_every_key_constant_of_the_core_is_in_the_catalog(self):
        cles = set()
        for chemin in sorted(PAQUET.rglob("*.py")):
            if chemin.name == "catalog.py":
                continue
            cles |= constantes_de_cles(chemin)
        self.assertTrue(cles)
        for champ in ("from", "date", "to", "cc", "subject"):
            self.assertIn(f"mail_rules_fwd_{champ}", cles)
        self.assertEqual(sorted(cles - set(CATALOG)), [])

    def test_forwarded_field_labels_are_translated(self):
        from erplibre_mail_core import smtp

        neutre(self)
        message = email.message_from_bytes(
            b"From: Carole <carole.regle@example.org>\r\n"
            b"Date: Fri, 06 Nov 2026 10:00:00 -0500\r\n"
            b"To: boite.regles@example.org\r\n"
            b"Cc: denis.tri@example.org\r\n"
            b"Subject: Demande\r\n\r\nBonjour.\r\n",
            policy=email.policy.default,
        )
        cles = [f"mail_rules_fwd_{c}" for c in ("from", "date", "to", "cc")]
        cles.append("mail_rules_fwd_subject")
        for langue in ("fr", "en"):
            with self.subTest(langue=langue), i18n.using_lang(langue):
                libelles = [
                    libelle for libelle, _v in smtp.forwarded_fields(message)
                ]
                self.assertEqual(
                    libelles, [CATALOG[cle][langue] for cle in cles]
                )
                for libelle, cle in zip(libelles, cles, strict=True):
                    self.assertNotEqual(libelle, cle)

    def test_code_labels_are_in_the_catalog(self):
        from erplibre_mail_core.rules import guards, model, report

        attendues = set(report.REPORT_KEYS) | {"mail_stats_default_body"}
        raisons = (
            set(guards.REASONS)
            | set(guards.ENGINE_REASONS)
            | {"gone", "catchup_overflow"}
        ) - {guards.SEND}
        attendues |= {f"mail_rules_reason_{c}" for c in raisons}
        attendues |= {f"mail_rules_outcome_{o}" for o in model.OUTCOMES}
        attendues |= {f"mail_stats_var_{n}" for n in model.STATS_VARIABLES}
        self.assertEqual(sorted(attendues - set(CATALOG)), [])


class TestLanguage(unittest.TestCase):
    def setUp(self):
        neutre(self)

    def test_t_defaults_to_french(self):
        """Sans langue en paramètre, ni bloc, ni `configure`, le noyau
        parle français."""
        self.assertNotEqual(CATALOG[CLE]["fr"], CATALOG[CLE]["en"])
        self.assertEqual(i18n.DEFAULT_LANG, "fr")
        self.assertEqual(i18n.current_lang(), "fr")
        self.assertEqual(i18n.t(CLE), CATALOG[CLE]["fr"])
        self.assertEqual(i18n.t(CLE, ""), CATALOG[CLE]["fr"])

    def test_t_takes_the_language_as_a_parameter(self):
        for code in ("fr", "fr_CA", "FR", "fr-CA", "fr_FR.UTF-8"):
            with self.subTest(code=code):
                self.assertEqual(i18n.t(CLE, code), CATALOG[CLE]["fr"])
        for code in ("en", "en_US", "EN-gb"):
            with self.subTest(code=code):
                self.assertEqual(i18n.t(CLE, code), CATALOG[CLE]["en"])

    def test_an_unknown_language_falls_back_to_the_default(self):
        i18n.configure(default_lang="en")
        self.assertEqual(i18n.t(CLE), CATALOG[CLE]["en"])
        for code in ("de_DE", "xx"):
            with self.subTest(code=code):
                self.assertEqual(i18n.normalize_lang(code), "fr")
                self.assertEqual(i18n.t(CLE, code), CATALOG[CLE]["fr"])

    def test_an_entry_without_the_language_falls_back_to_french(self):
        cle = "mail_test_seulement_fr"
        CATALOG[cle] = {"fr": "seul"}
        self.addCleanup(CATALOG.pop, cle, None)
        self.assertEqual(i18n.lookup(cle, "en"), "seul")
        self.assertEqual(
            i18n.lookup("mail_cle_inconnue", "fr"), "mail_cle_inconnue"
        )

    def test_using_lang_scopes_and_restores(self):
        with i18n.using_lang("en") as code:
            self.assertEqual(code, "en")
            with i18n.using_lang("fr_CA"):
                self.assertEqual(i18n.t(CLE), CATALOG[CLE]["fr"])
                with i18n.using_lang("en"):
                    self.assertEqual(i18n.current_lang(), "en")
                self.assertEqual(i18n.current_lang(), "fr")
            self.assertEqual(i18n.current_lang(), "en")
        self.assertEqual(i18n.current_lang(), "fr")
        i18n.configure(default_lang="en")
        self.assertEqual(i18n.current_lang(), "en")

    def test_using_lang_is_per_thread(self):
        vu = []
        with i18n.using_lang("en"):
            fil = threading.Thread(
                target=lambda: vu.append(i18n.current_lang())
            )
            fil.start()
            fil.join()
            self.assertEqual(i18n.current_lang(), "en")
        self.assertEqual(vu, ["fr"])

    def test_configure_reads_a_callable_at_each_call(self):
        etat = ["fr"]
        i18n.configure(default_lang=lambda: etat[0])
        self.assertEqual(i18n.t(CLE), CATALOG[CLE]["fr"])
        etat[0] = "en"
        self.assertEqual(i18n.t(CLE), CATALOG[CLE]["en"])

    def test_configure_none_restores_the_default(self):
        i18n.configure(default_lang="en", translator=lambda k, lang: "X")
        i18n.configure(default_lang=None, translator=None)
        self.assertEqual(i18n.current_lang(), "fr")
        self.assertEqual(i18n.t(CLE), CATALOG[CLE]["fr"])

    def test_configure_returns_the_previous_settings(self):
        def defaut():
            return "en"

        def traducteur(cle, langue):
            return None

        i18n.configure(default_lang=defaut, translator=traducteur)
        precedent = i18n.configure(default_lang="fr", translator=None)
        self.assertIs(precedent["default_lang"], defaut)
        self.assertIs(precedent["translator"], traducteur)
        self.assertEqual(i18n.current_lang(), "fr")
        i18n.configure(**precedent)
        self.assertEqual(i18n.current_lang(), "en")
        self.assertIs(i18n.configure()["translator"], traducteur)

    def test_configure_keeps_an_omitted_setting(self):
        i18n.configure(default_lang="en")
        i18n.configure(translator=lambda k, lang: None)
        self.assertEqual(i18n.current_lang(), "en")

    def test_translator_overrides_and_none_falls_back(self):
        autre = "mail_rules_err_op"
        i18n.configure(
            translator=lambda cle, langue: "X" if cle == CLE else None
        )
        self.assertEqual(i18n.t(CLE, "fr"), "X")
        self.assertEqual(i18n.t(autre, "fr"), CATALOG[autre]["fr"])

    def test_the_translator_receives_the_normalized_language(self):
        recu = []
        i18n.configure(
            translator=lambda cle, langue: recu.append(langue) or None
        )
        i18n.t(CLE, "fr_CA")
        self.assertEqual(recu, ["fr"])

    def test_rule_errors_follow_the_language(self):
        """Les modules déplacés lisent le `t` du noyau : une règle invalide
        lève dans la langue du contexte."""
        from erplibre_mail_core.rules import model

        regle = model.new_rule("reply", "Essai")
        regle.action.kind = "inconnu"
        for langue in ("fr", "en"):
            with self.subTest(langue=langue), i18n.using_lang(langue):
                with self.assertRaises(model.RuleError) as ctx:
                    model.validate(regle)
                texte = str(ctx.exception)
                self.assertIn(CATALOG["mail_rules_err_invalid"][langue], texte)
                self.assertIn(CATALOG["mail_rules_err_kind"][langue], texte)


if __name__ == "__main__":
    unittest.main()
