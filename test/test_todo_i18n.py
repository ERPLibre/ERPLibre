#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import ast
import collections
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from script.todo import todo_i18n


class TestTranslations(unittest.TestCase):
    """Test TRANSLATIONS dictionary integrity."""

    def test_all_entries_have_fr_and_en(self):
        for key, entry in todo_i18n.TRANSLATIONS.items():
            self.assertIn("fr", entry, f"Key '{key}' missing 'fr' translation")
            self.assertIn("en", entry, f"Key '{key}' missing 'en' translation")

    def test_no_empty_translations(self):
        for key, entry in todo_i18n.TRANSLATIONS.items():
            for lang in ("fr", "en"):
                self.assertTrue(
                    len(entry[lang]) > 0,
                    f"Key '{key}' has empty '{lang}' translation",
                )

    def test_translations_not_empty(self):
        self.assertGreater(len(todo_i18n.TRANSLATIONS), 0)


class TestAucuneCleAffichableNEchappeALaTable(unittest.TestCase):
    """Une clé absente de la table s'affiche EN ANGLAIS, sans rien dire.

    `t()` rend la clé quand elle ne la connaît pas — c'est le bon repli,
    mais il est SILENCIEUX : au milieu d'une interface française, une
    phrase anglaise se lit comme un oubli de traduction, pas comme un
    défaut, et personne ne la signale.

    Neuf clés étaient dans cet état, dont cinq sur un même écran d'analyse
    et deux sur un message de refus de Proxmox — celui-là s'affiche
    justement quand quelque chose va mal.

    LE CONTRÔLE PORTE SUR LES CLÉS LITTÉRALES. Une clé calculée —
    `t(controle["title"])` — ne se lit pas dans le source, et c'est une
    autre affaire, plus vaste, que cette garde ne prétend pas couvrir.
    """

    # Le motif accepte les deux guillemets, et exige la frontière de mot :
    # sans `\b`, il attrape la fin de « print( ».
    #
    # Le contenu ne peut porter AUCUN guillemet : sans cette contrainte le
    # motif traverse une expression entière et prend
    # `t("a" if x else "b")` pour une clé unique — qui n'existe évidemment
    # pas dans la table. Les deux branches y sont, elles, et un ternaire
    # n'est pas une clé littérale.
    MOTIF = re.compile(r"""\bt\(\s*(["'])([^"']*)\1\s*\)""")

    @classmethod
    def cles_du_depot(cls):
        """{clé: [fichier:ligne]} pour tout `t("...")` de script/."""
        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        vues = {}
        for dossier, _sous, fichiers in os.walk(
            os.path.join(racine, "script")
        ):
            for nom in sorted(fichiers):
                if not nom.endswith(".py") or nom == "todo_i18n.py":
                    continue
                chemin = os.path.join(dossier, nom)
                with open(chemin, encoding="utf-8") as fichier:
                    for numero, ligne in enumerate(fichier, 1):
                        for _q, cle in cls.MOTIF.findall(ligne):
                            court = os.path.relpath(chemin, racine)
                            vues.setdefault(cle, []).append(
                                f"{court}:{numero}"
                            )
        return vues

    def test_every_literal_key_is_in_the_table(self):
        absentes = [
            f"{ou[0]} : « {cle} »"
            for cle, ou in sorted(self.cles_du_depot().items())
            if cle not in todo_i18n.TRANSLATIONS
        ]
        self.assertEqual([], absentes)

    def test_the_scan_actually_finds_keys(self):
        """Sur zéro clé trouvée, la garde passe et ne tient rien : c'est
        ici qu'un motif cassé doit tomber, pas dans un silence vert."""
        self.assertGreater(len(self.cles_du_depot()), 500)


class TestT(unittest.TestCase):
    """Test t() translation function."""

    def setUp(self):
        todo_i18n._current_lang = None

    def tearDown(self):
        todo_i18n._current_lang = None

    def test_returns_french_when_lang_fr(self):
        todo_i18n._current_lang = "fr"
        result = todo_i18n.t("Quit")
        self.assertEqual(result, "Quitter")

    def test_returns_english_when_lang_en(self):
        todo_i18n._current_lang = "en"
        result = todo_i18n.t("Quit")
        self.assertEqual(result, "Quit")

    def test_unknown_key_returns_key(self):
        todo_i18n._current_lang = "fr"
        result = todo_i18n.t("nonexistent_key_xyz")
        self.assertEqual(result, "nonexistent_key_xyz")

    def test_fallback_to_fr_if_lang_missing(self):
        todo_i18n._current_lang = "de"
        result = todo_i18n.t("Quit")
        self.assertEqual(result, "Quitter")


class TestGetLang(unittest.TestCase):
    """Test get_lang() function."""

    def setUp(self):
        todo_i18n._current_lang = None

    def tearDown(self):
        todo_i18n._current_lang = None

    def test_returns_cached_lang(self):
        todo_i18n._current_lang = "en"
        result = todo_i18n.get_lang()
        self.assertEqual(result, "en")

    def test_reads_from_env_var_sh(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write('EL_LANG="en"\n')
            f.flush()
            try:
                with patch.object(todo_i18n, "ENV_VAR_FILE", f.name):
                    result = todo_i18n.get_lang()
                self.assertEqual(result, "en")
            finally:
                os.unlink(f.name)

    def test_reads_unquoted_lang(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write("EL_LANG=fr\n")
            f.flush()
            try:
                with patch.object(todo_i18n, "ENV_VAR_FILE", f.name):
                    result = todo_i18n.get_lang()
                self.assertEqual(result, "fr")
            finally:
                os.unlink(f.name)

    def test_env_variable_fallback(self):
        with patch.object(
            todo_i18n,
            "ENV_VAR_FILE",
            "/nonexistent/path",
        ), patch.dict(os.environ, {"EL_LANG": "en"}):
            result = todo_i18n.get_lang()
        self.assertEqual(result, "en")

    def test_default_is_fr(self):
        with patch.object(
            todo_i18n,
            "ENV_VAR_FILE",
            "/nonexistent/path",
        ), patch.dict(os.environ, {}, clear=True):
            result = todo_i18n.get_lang()
        self.assertEqual(result, "fr")

    def test_invalid_lang_in_file_falls_through(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write('EL_LANG="de"\n')
            f.flush()
            try:
                with patch.object(
                    todo_i18n, "ENV_VAR_FILE", f.name
                ), patch.dict(os.environ, {}, clear=True):
                    result = todo_i18n.get_lang()
                self.assertEqual(result, "fr")
            finally:
                os.unlink(f.name)


class TestSetLang(unittest.TestCase):
    """Test set_lang() function."""

    def setUp(self):
        todo_i18n._current_lang = None

    def tearDown(self):
        todo_i18n._current_lang = None

    def test_sets_current_lang(self):
        # Détourner ENV_VAR_FILE comme le font les trois tests suivants :
        # `set_lang()` PERSISTE, et sans ce détournement celui-ci écrivait
        # dans le ./env_var.sh du dépôt, suivi par git.
        with patch.object(todo_i18n, "ENV_VAR_FILE", "/nonexistent/path"):
            todo_i18n.set_lang("en")
        self.assertEqual(todo_i18n._current_lang, "en")

    def test_persists_to_file_update(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write('EL_LANG="fr"\nOTHER=value\n')
            f.flush()
            try:
                with patch.object(todo_i18n, "ENV_VAR_FILE", f.name):
                    todo_i18n.set_lang("en")
                with open(f.name) as rf:
                    content = rf.read()
                self.assertIn('EL_LANG="en"', content)
                self.assertIn("OTHER=value", content)
            finally:
                os.unlink(f.name)

    def test_persists_to_file_append(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write("SOME_VAR=123\n")
            f.flush()
            try:
                with patch.object(todo_i18n, "ENV_VAR_FILE", f.name):
                    todo_i18n.set_lang("en")
                with open(f.name) as rf:
                    content = rf.read()
                self.assertIn('EL_LANG="en"', content)
                self.assertIn("SOME_VAR=123", content)
            finally:
                os.unlink(f.name)

    def test_nonexistent_file_no_crash(self):
        with patch.object(
            todo_i18n,
            "ENV_VAR_FILE",
            "/nonexistent/path",
        ):
            todo_i18n.set_lang("en")
        self.assertEqual(todo_i18n._current_lang, "en")


class TestLangIsConfigured(unittest.TestCase):
    """Test lang_is_configured() function."""

    def test_returns_true_when_configured(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write('EL_LANG="fr"\n')
            f.flush()
            try:
                with patch.object(todo_i18n, "ENV_VAR_FILE", f.name):
                    result = todo_i18n.lang_is_configured()
                self.assertTrue(result)
            finally:
                os.unlink(f.name)

    def test_returns_false_when_not_configured(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write("SOME_VAR=123\n")
            f.flush()
            try:
                with patch.object(todo_i18n, "ENV_VAR_FILE", f.name):
                    result = todo_i18n.lang_is_configured()
                self.assertFalse(result)
            finally:
                os.unlink(f.name)

    def test_returns_false_when_file_missing(self):
        with patch.object(
            todo_i18n,
            "ENV_VAR_FILE",
            "/nonexistent/path",
        ):
            result = todo_i18n.lang_is_configured()
        self.assertFalse(result)


class TestAucuneCleRepetee(unittest.TestCase):
    """Une clé répétée écrase la précédente EN SILENCE.

    Le dictionnaire est un littéral Python de plusieurs milliers d'entrées :
    rien n'avertit, rien ne lève, et la deuxième définition gagne. Le prix
    s'est déjà payé une fois en étiquette de menu principal — la traduction
    lue n'était pas celle qu'on venait d'écrire, et le fichier montrait la
    bonne à qui la cherchait.

    Le contrôle lit l'ARBRE et non le dictionnaire construit : une fois
    construit, le doublon a déjà disparu, et il n'y a plus rien à voir. C'est
    la seule façon de poser la question.
    """

    def _cles(self):
        chemin = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "script",
            "todo",
            "todo_i18n.py",
        )
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        litteral = None
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id == "TRANSLATIONS"
                for c in noeud.targets
            ):
                litteral = noeud.value
        self.assertIsInstance(litteral, ast.Dict)
        return [
            c.value
            for c in litteral.keys
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        ]

    def test_the_literal_was_actually_read(self):
        """Sinon un dictionnaire vide passerait le test suivant."""
        self.assertGreater(len(self._cles()), 2000)

    def test_no_key_is_declared_twice(self):
        compte = collections.Counter(self._cles())
        doublons = sorted(k for k, n in compte.items() if n > 1)
        self.assertEqual(
            doublons,
            [],
            "clés déclarées deux fois : la seconde écrase la première",
        )

    def test_every_key_survives_the_build(self):
        """Le compte du littéral et celui du dictionnaire s'accordent.

        C'est la même vérité dite autrement, et elle tombe d'elle-même le
        jour où une clé se répète."""
        self.assertEqual(len(self._cles()), len(todo_i18n.TRANSLATIONS))


class TestChaqueCleDitSesDeuxLangues(unittest.TestCase):
    """Une clé sans « fr » ou sans « en » ne lève rien au chargement.

    t() retombe alors sur la clé elle-même, si bien que l'écran montre
    l'anglais à qui a choisi le français, ou l'inverse, sans que rien ne le
    signale.
    """

    def test_every_key_carries_fr_and_en(self):
        manques = sorted(
            k
            for k, v in todo_i18n.TRANSLATIONS.items()
            if not isinstance(v, dict) or "fr" not in v or "en" not in v
        )
        self.assertEqual(manques, [], "traductions incomplètes")


if __name__ == "__main__":
    unittest.main()
