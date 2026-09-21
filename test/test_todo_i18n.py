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

    # L'ARBRE, ET NON LES LIGNES. Un motif de texte ne voit qu'une ligne à
    # la fois : un appel coupé sur plusieurs lignes — la forme que prennent
    # justement les clés longues — lui échappe entièrement. Il lisait 2829
    # clés là où le code en porte 2888 : soixante n'étaient confrontées à
    # la table par personne, et les plus longues sont celles qu'on oublie
    # d'y mettre.
    #
    # Il en INVENTAIT une, de surcroît : « … », prise dans une docstring.
    # C'est la preuve qu'il lisait du texte et non du code.
    #
    # L'analyseur traite le ternaire sans qu'on l'en prie : `t("a" if x
    # else "b")` a pour argument une expression, pas une constante, donc
    # il n'est pas une clé littérale et sort de lui-même.

    @staticmethod
    def _cle_litterale(noeud):
        """La clé d'un appel `t("…")`, ou None si ce n'en est pas un.

        `t(...)` comme `objet.t(...)` : le second n'existe pas aujourd'hui
        dans script/, et l'accepter coûte une ligne plutôt qu'une reprise
        le jour où il apparaît.
        """
        import ast

        if not isinstance(noeud, ast.Call):
            return None
        cible = noeud.func
        nom = getattr(cible, "id", None) or getattr(cible, "attr", None)
        if nom != "t" or len(noeud.args) != 1 or noeud.keywords:
            return None
        arg = noeud.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return None

    @classmethod
    def cles_du_depot(cls):
        """{clé: [fichier:ligne]} pour tout `t("...")` de script/."""
        import ast

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
                    arbre = ast.parse(fichier.read(), filename=chemin)
                court = os.path.relpath(chemin, racine)
                for noeud in ast.walk(arbre):
                    cle = cls._cle_litterale(noeud)
                    if cle is not None:
                        vues.setdefault(cle, []).append(
                            f"{court}:{noeud.lineno}"
                        )
        return vues

    def test_every_literal_key_is_in_the_table(self):
        absentes = [
            f"{ou[0]} : « {cle} »"
            for cle, ou in sorted(self.cles_du_depot().items())
            if cle not in todo_i18n.TRANSLATIONS
        ]
        self.assertEqual([], absentes)

    def cles_du_texte(self, source):
        """Les clés d'un extrait, par le même chemin que le dépôt."""
        import ast

        return {
            cle
            for noeud in ast.walk(ast.parse(source))
            if (cle := self._cle_litterale(noeud)) is not None
        }

    def test_a_call_split_over_lines_is_seen(self):
        """LE TROU QUI A JUSTIFIÉ L'ARBRE. Un motif de texte ne lit qu'une
        ligne à la fois, et c'est la forme que prennent les clés LONGUES —
        celles qu'on oublie le plus souvent d'ajouter à la table."""
        self.assertEqual(
            {"une clé longue coupée en deux"},
            self.cles_du_texte(
                'x = t(\n    "une clé longue coupée en deux"\n)\n'
            ),
        )

    def test_a_docstring_that_mentions_a_call_is_not_a_key(self):
        """Le motif en inventait une, prise dans une docstring : la preuve
        qu'il lisait du texte et non du code."""
        self.assertEqual(
            set(), self.cles_du_texte('"""Un exemple : t(\'…\')."""\n')
        )

    def test_a_ternary_is_not_a_literal_key(self):
        """Les deux branches sont des clés ; l'expression qui choisit n'en
        est pas une, et la prendre pour telle ferait chercher dans la
        table quelque chose qui n'y sera jamais."""
        self.assertEqual(
            set(), self.cles_du_texte('x = t("a" if cond else "b")\n')
        )

    def test_a_computed_key_is_not_claimed_to_be_literal(self):
        """Contrôle de portée : cette garde ne tient QUE les littérales.
        Prétendre autre chose ferait croire le reste couvert."""
        self.assertEqual(set(), self.cles_du_texte("x = t(variable)\n"))

    def test_an_ordinary_call_is_still_seen(self):
        """Contrôle positif : ne rien voir satisferait tout ce qui
        précède."""
        self.assertEqual({"clé"}, self.cles_du_texte('x = t("clé")\n'))

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
        with (
            patch.object(
                todo_i18n,
                "ENV_VAR_FILE",
                "/nonexistent/path",
            ),
            patch.dict(os.environ, {"EL_LANG": "en"}),
        ):
            result = todo_i18n.get_lang()
        self.assertEqual(result, "en")

    def test_default_is_fr(self):
        with (
            patch.object(
                todo_i18n,
                "ENV_VAR_FILE",
                "/nonexistent/path",
            ),
            patch.dict(os.environ, {}, clear=True),
        ):
            result = todo_i18n.get_lang()
        self.assertEqual(result, "fr")

    def test_invalid_lang_in_file_falls_through(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write('EL_LANG="de"\n')
            f.flush()
            try:
                with (
                    patch.object(todo_i18n, "ENV_VAR_FILE", f.name),
                    patch.dict(os.environ, {}, clear=True),
                ):
                    result = todo_i18n.get_lang()
                self.assertEqual(result, "fr")
            finally:
                os.unlink(f.name)


def _references_set_lang(arbre):
    """Chaque nœud qui désigne set_lang : un appel, mais aussi la fonction
    passée en argument — addCleanup(set_lang, …), side_effect=set_lang — et
    un alias d'import."""
    noms = {"set_lang"} | {
        alias.asname
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.ImportFrom)
        for alias in noeud.names
        if alias.name == "set_lang" and alias.asname
    }
    for noeud in ast.walk(arbre):
        if (isinstance(noeud, ast.Name) and noeud.id in noms) or (
            isinstance(noeud, ast.Attribute) and noeud.attr == "set_lang"
        ):
            yield noeud


def _detourne(expr):
    """patch.object(…, "ENV_VAR_FILE", …), patch("….ENV_VAR_FILE", …), ou
    la même cible passée par mot-clé."""
    if not isinstance(expr, ast.Call):
        return False
    valeurs = list(expr.args) + [kw.value for kw in expr.keywords]
    return any(kw.arg == "ENV_VAR_FILE" for kw in expr.keywords) or any(
        isinstance(a, ast.Constant)
        and isinstance(a.value, str)
        and a.value.split(".")[-1] == "ENV_VAR_FILE"
        for a in valeurs
    )


def _sous_detournement(noeud, parents):
    """Le nœud est-il sous un « with » ou un décorateur qui détourne
    ENV_VAR_FILE ?"""
    while noeud in parents:
        noeud = parents[noeud]
        if isinstance(noeud, (ast.With, ast.AsyncWith)):
            if any(_detourne(item.context_expr) for item in noeud.items):
                return True
        elif isinstance(
            noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            if any(_detourne(d) for d in noeud.decorator_list):
                return True
    return False


class TestLesChampsDesTraductions(unittest.TestCase):
    def test_each_translation_keeps_the_fields_of_its_key(self):
        """Une traduction qui perd, ajoute ou renomme un champ {…} fait
        lever .format() là où le texte sert : dans une commande d'effacement,
        le suivi tomberait au lieu d'afficher son refus."""
        import string

        def champs(texte):
            return {
                f
                for _l, f, _s, _c in string.Formatter().parse(texte)
                if f is not None
            }

        ecarts = [
            (cle, langue)
            for cle, entree in todo_i18n.TRANSLATIONS.items()
            for langue in ("fr", "en")
            if champs(entree[langue]) != champs(cle)
        ]
        self.assertEqual([], ecarts)


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

    def test_no_test_writes_the_repository_env_var_sh(self):
        """Un set_lang() hors d'un détournement de ENV_VAR_FILE réécrit le
        ./env_var.sh du dépôt : suivi par git, et lu par les autres tests de
        la suite parallèle, qui changent alors de langue en cours de route.
        Un test qui veut une langue fixe `_current_lang`, sans persister.

        Seules les références directes à set_lang sont lues : un test qui
        mène TODO._change_language() ou _ask_language() y arrive sans le
        nommer."""
        racine = os.path.dirname(os.path.abspath(__file__))
        fautifs = []
        for nom in sorted(os.listdir(racine)):
            if not (nom.startswith("test_") and nom.endswith(".py")):
                continue
            with open(os.path.join(racine, nom), encoding="utf-8") as fh:
                arbre = ast.parse(fh.read())
            parents = {
                enfant: noeud
                for noeud in ast.walk(arbre)
                for enfant in ast.iter_child_nodes(noeud)
            }
            for noeud in _references_set_lang(arbre):
                if not _sous_detournement(noeud, parents):
                    fautifs.append(f"{nom}:{noeud.lineno}")
        self.assertEqual([], fautifs)


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
