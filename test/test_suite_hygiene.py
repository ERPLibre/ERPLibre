#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La suite reste collectable et exécutable par pytest sans en dépendre.

Le lanceur exécute chaque fichier dans son propre processus, dans l'ordre
alphabétique des classes d'unittest ; pytest, lui, partage un processus
entre les fichiers et suit l'ordre de définition. Ce qui ne tient que grâce
au premier, ce garde le refuse, par une lecture statique (AST) de test/ :

- une fonction de module nommée test* : pytest la collecte comme un test,
  et ses paramètres comme des fixtures introuvables ;
- unittest.addModuleCleanup, n'importe où dans test/, aides comprises :
  pytest n'appelle jamais doModuleCleanups, le nettoyage ne tourne pas et
  un patch reste posé pour les fichiers suivants. setUpModule et
  tearDownModule, eux, sont honorés ;
- logging.basicConfig au niveau d'un module de test : sans effet dès que
  la racine a un handler, si bien que le résultat dépend de ce qui a été
  importé avant ;
- sys.argv réassigné au niveau du module à autre chose que ["todo.py"].
  Cette valeur-là est permise : les modules de script/todo lisent
  sys.argv à l'import, et un nom de programme seul leur donne une ligne de
  commande vide, la même sous le lanceur et sous pytest, quel que soit le
  fichier importé en dernier. Une autre valeur ferait dépendre l'import
  d'un fichier de celui qui l'a précédé dans le processus.

Pour tenir sous la seconde, seuls les fichiers dont le texte porte un motif
suspect sont analysés en AST.

La seconde moitié vérifie `script/test/unit_file.py` -k et
--ordre-aleatoire, le détecteur natif des dépendances à l'ordre, sur un
petit module de tests écrit dans un répertoire temporaire.
"""

import ast
import json
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_TEST = RACINE / "test"
UNIT_FILE = RACINE / "script" / "test" / "unit_file.py"

#: La seule réassignation de sys.argv permise au niveau d'un module.
ARGV_PERMIS = "['todo.py']"


# Repère, dans le texte, ce qui mérite une analyse AST. Un « def test » en
# colonne 0 est une fonction de module ; les autres motifs se confirment
# par l'AST (une mention en commentaire ou en docstring ne compte pas).
SUSPECT = re.compile(
    r"^(?:async[ \t]+)?def[ \t]+test"
    r"|addModuleCleanup|basicConfig"
    r"|^[ \t]*sys\.argv[ \t]*(?::[^=\n]*|\+)?=",
    re.M,
)
# Un « def test » indenté n'est une fonction de module que dans un bloc de
# niveau module (if/try/with/for/while) : chaque méthode de TestCase en est
# un aussi, et les analyser toutes ferait parcourir tout test/ en AST.
DEF_TEST_INDENTE = re.compile(r"^[ \t]+(?:async[ \t]+)?def[ \t]+test", re.M)
BLOC_DE_MODULE = re.compile(
    r"^(?:if(?![ \t]+__name__)|try|with|for|while"
    r"|async[ \t]+(?:with|for))\b",
    re.M,
)


def suspect(texte):
    """Vrai si `texte` mérite l'analyse AST : un motif refusé peut s'y
    trouver. Faux, il ne peut pas en porter."""
    return bool(
        SUSPECT.search(texte)
        or (DEF_TEST_INDENTE.search(texte) and BLOC_DE_MODULE.search(texte))
    )


def _bloc_principal(noeud):
    """Vrai pour `if __name__ == "__main__":`, que l'import n'exécute pas."""
    test = getattr(noeud, "test", None)
    return (
        isinstance(noeud, ast.If)
        and isinstance(test, ast.Compare)
        and getattr(test.left, "id", "") == "__name__"
        and len(test.comparators) == 1
        and getattr(test.comparators[0], "value", None) == "__main__"
    )


def _niveau_module(corps):
    """Les instructions exécutées à l'import : le corps du module et celui
    des if/try/with/for/while qui s'y trouvent, sans entrer dans les
    fonctions ni les classes, ni dans le bloc `if __name__ == "__main__":`
    (son `else` s'exécute, lui, à l'import)."""
    for noeud in corps:
        yield noeud
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(noeud, ast.ClassDef):
            continue
        if _bloc_principal(noeud):
            yield from _niveau_module(noeud.orelse)
            continue
        for champ in ("body", "orelse", "finalbody"):
            yield from _niveau_module(getattr(noeud, champ, []))
        for gestionnaire in getattr(noeud, "handlers", []):
            yield from _niveau_module(gestionnaire.body)


def _appels(noeud):
    """Les appels faits par l'instruction `noeud` elle-même, sans entrer
    dans les fonctions, classes ou lambdas qu'elle définit."""
    a_voir = [noeud]
    while a_voir:
        courant = a_voir.pop()
        if isinstance(courant, ast.Call):
            yield courant
        for enfant in ast.iter_child_nodes(courant):
            if isinstance(
                enfant,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Lambda,
                ),
            ):
                continue
            if isinstance(enfant, ast.stmt) and enfant is not noeud:
                # Les blocs imbriqués sont rendus par _niveau_module.
                continue
            a_voir.append(enfant)


def _nom_appele(appel):
    fonction = appel.func
    if isinstance(fonction, ast.Attribute):
        return fonction.attr
    if isinstance(fonction, ast.Name):
        return fonction.id
    return None


def _est_sys_argv(cible):
    return (
        isinstance(cible, ast.Attribute)
        and cible.attr == "argv"
        and isinstance(cible.value, ast.Name)
        and cible.value.id == "sys"
    )


def examiner(source, nom, module_de_test=True):
    """Les manquements de `source` : une liste de (ligne, règle, texte).

    `module_de_test` faux (une aide de test/) ne garde que la règle
    addModuleCleanup : les autres ne valent que pour les fichiers que
    pytest collecte."""
    arbre = ast.parse(source, nom)
    trouve = []
    for noeud in ast.walk(arbre):
        if (
            isinstance(noeud, ast.Attribute)
            and noeud.attr == "addModuleCleanup"
        ) or (isinstance(noeud, ast.Name) and noeud.id == "addModuleCleanup"):
            trouve.append(
                (
                    noeud.lineno,
                    "addModuleCleanup",
                    "pytest ne l'exécute pas : setUpModule/tearDownModule",
                )
            )
    if not module_de_test:
        return trouve
    for noeud in _niveau_module(arbre.body):
        if isinstance(
            noeud, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and noeud.name.startswith("test"):
            trouve.append(
                (
                    noeud.lineno,
                    "fonction test*",
                    f"« {noeud.name} » serait collectée par pytest : "
                    "la renommer",
                )
            )
        if isinstance(noeud, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            cibles = getattr(noeud, "targets", None) or [noeud.target]
            valeur = noeud.value
            if any(_est_sys_argv(c) for c in cibles) and (
                isinstance(noeud, ast.AugAssign)
                or valeur is None
                or ast.unparse(valeur) != ARGV_PERMIS
            ):
                trouve.append(
                    (
                        noeud.lineno,
                        "sys.argv",
                        f"seul sys.argv = {ARGV_PERMIS} est permis "
                        "au niveau du module",
                    )
                )
        if isinstance(
            noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        for appel in _appels(noeud):
            if _nom_appele(appel) == "basicConfig":
                trouve.append(
                    (
                        appel.lineno,
                        "basicConfig",
                        "sans effet si la racine a déjà un handler : "
                        "régler le niveau du journal dans le test",
                    )
                )
    return sorted(set(trouve))


def manquements():
    """Les manquements de test/, sous la forme « fichier:ligne règle »."""
    lignes = []
    for chemin in sorted(DOSSIER_TEST.glob("*.py")):
        texte = chemin.read_text(encoding="utf-8")
        if not suspect(texte):
            continue
        de_test = chemin.name.startswith("test_")
        for ligne, regle, message in examiner(texte, str(chemin), de_test):
            lignes.append(f"test/{chemin.name}:{ligne} {regle} — {message}")
    return lignes


class TestLaSuiteResteCompatibleAvecPytest(unittest.TestCase):
    def test_no_file_breaks_a_rule(self):
        self.assertEqual(manquements(), [])


class TestLeGardeVoitCeQuIlRefuse(unittest.TestCase):
    """Le garde sur des sources inventées : ce qu'il refuse, ce qu'il
    laisse passer."""

    def regles(self, source, module_de_test=True):
        source = textwrap.dedent(source)
        return [
            regle
            for _, regle, _ in examiner(source, "<essai>", module_de_test)
        ]

    def test_a_module_level_test_function_is_refused(self):
        self.assertEqual(
            self.regles("def test(ident, duree):\n    pass\n"),
            ["fonction test*"],
        )
        self.assertEqual(
            self.regles("async def test_aide():\n    pass\n"),
            ["fonction test*"],
        )

    def test_a_test_function_hidden_in_a_module_level_block_is_refused(self):
        source = """
            import sys
            if sys.platform:
                def test_cache(x):
                    pass
            """
        self.assertEqual(self.regles(source), ["fonction test*"])

    def test_test_methods_and_other_helpers_pass(self):
        source = """
            import unittest
            def entree(ident):
                return ident
            class TestX(unittest.TestCase):
                def test_y(self):
                    def test_interne():
                        pass
            """
        self.assertEqual(self.regles(source), [])

    def test_add_module_cleanup_is_refused_but_not_its_mention(self):
        source = """
            import unittest
            # addModuleCleanup : jamais exécuté par pytest.
            def setUpModule():
                unittest.addModuleCleanup(print)
            """
        self.assertEqual(self.regles(source), ["addModuleCleanup"])
        self.assertEqual(
            self.regles("X = 'addModuleCleanup'\n"),
            [],
        )

    def test_helpers_are_held_to_the_cleanup_rule_only(self):
        source = """
            import logging, unittest
            logging.basicConfig()
            def test_aide():
                unittest.addModuleCleanup(print)
            """
        self.assertEqual(
            self.regles(source, module_de_test=False), ["addModuleCleanup"]
        )

    def test_basic_config_at_import_is_refused(self):
        self.assertEqual(
            self.regles("import logging\nlogging.basicConfig(level=10)\n"),
            ["basicConfig"],
        )
        source = """
            try:
                from logging import basicConfig
            except ImportError:
                pass
            else:
                basicConfig()
            """
        self.assertEqual(self.regles(source), ["basicConfig"])

    def test_basic_config_inside_a_test_passes(self):
        source = """
            import logging, unittest
            class TestX(unittest.TestCase):
                def setUp(self):
                    logging.basicConfig()
            def aide():
                logging.basicConfig()
            rappel = lambda: logging.basicConfig()
            """
        self.assertEqual(self.regles(source), [])

    def test_only_the_todo_argv_is_allowed(self):
        self.assertEqual(
            self.regles("import sys\nsys.argv = ['todo.py']\n"), []
        )
        self.assertEqual(
            self.regles("import sys\nsys.argv = ['outil_invente.py', '-v']\n"),
            ["sys.argv"],
        )
        self.assertEqual(
            self.regles("import sys\nsys.argv += ['--vite']\n"), ["sys.argv"]
        )

    def test_the_prefilter_sees_every_refused_form(self):
        # Un fichier que le préfiltre écarte n'est jamais analysé.
        for source in (
            "def test(x):\n    pass\n",
            "async def test_x():\n    pass\n",
            "import unittest\nunittest.addModuleCleanup(print)\n",
            "import logging\nlogging.basicConfig()\n",
            "import sys\nif True:\n    sys.argv = ['x']\n",
            "import sys\nsys.argv: list = ['x']\n",
            "import sys\nsys.argv += ['x']\n",
            "if True:\n    def test_cache():\n        pass\n",
        ):
            with self.subTest(source=source):
                self.assertTrue(suspect(textwrap.dedent(source)))
                self.assertTrue(self.regles(source))

    def test_the_main_block_is_not_run_at_import(self):
        # Ce que fait le bloc principal ne touche pas les autres modules
        # d'un processus partagé : il ne s'exécute pas à l'import.
        source = (
            "import logging, sys, unittest\n"
            'if __name__ == "__main__":\n'
            "    sys.argv = ['autre']\n"
            "    logging.basicConfig()\n"
            "    unittest.main()\n"
        )
        self.assertEqual(self.regles(source), [])


#: Un petit module de tests : trois classes, une préparation de classe
#: qui s'annonce, et des noms qui se prêtent à -k.
ECHANTILLON = """
import unittest


class TestAlpha(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("PREPARATION Alpha", flush=True)

    def test_un_rouge(self):
        pass

    def test_deux_vert(self):
        pass

    def test_trois_bleu(self):
        pass


class TestBeta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("PREPARATION Beta", flush=True)

    def test_un_vert(self):
        pass

    def test_deux_rouge(self):
        pass

    def test_trois_jaune(self):
        pass


class TestGamma(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("PREPARATION Gamma", flush=True)

    def test_un_bleu(self):
        pass

    def test_deux_jaune(self):
        pass

    def test_trois_rouge(self):
        pass

    def test_quatre_vert(self):
        pass


if __name__ == "__main__":
    unittest.main()
"""


class TestUnitFileFiltreEtMelange(unittest.TestCase):
    """unit_file.py -k et --ordre-aleatoire, lancé comme le fait le
    lanceur : un sous-processus par passage, le détail dans un JSON."""

    @classmethod
    def setUpClass(cls):
        cls.dossier = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.dossier.cleanup)
        cls.module = Path(cls.dossier.name) / "test_echantillon_ordre.py"
        cls.module.write_text(ECHANTILLON, encoding="utf-8")
        cls.passages = 0

    def lancer(self, *options):
        """Lance unit_file.py ; rend (code, sortie, ids dans l'ordre)."""
        type(self).passages += 1
        sortie = Path(self.dossier.name) / f"detail_{self.passages}.json"
        fini = subprocess.run(
            [sys.executable, str(UNIT_FILE), str(self.module), str(sortie)]
            + list(options),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=self.dossier.name,
        )
        detail = json.loads(sortie.read_text(encoding="utf-8"))
        ids = [entree["id"].split(".", 1)[1] for entree in detail]
        return fini.returncode, fini.stdout + fini.stderr, ids

    @staticmethod
    def classes_groupees(ids):
        """Vrai si les tests de chaque classe se suivent."""
        vues = []
        for ident in ids:
            classe = ident.split(".")[0]
            if not vues or vues[-1] != classe:
                if classe in vues:
                    return False
                vues.append(classe)
        return True

    def test_k_selects_like_unittest(self):
        code, sortie, ids = self.lancer("-k", "rouge")
        self.assertEqual(code, 0, sortie)
        self.assertEqual(
            sorted(ids),
            [
                "TestAlpha.test_un_rouge",
                "TestBeta.test_deux_rouge",
                "TestGamma.test_trois_rouge",
            ],
        )

    def test_k_patterns_add_up_and_accept_wildcards(self):
        code, sortie, ids = self.lancer("-k", "jaune", "-k", "*Alpha.test_d*")
        self.assertEqual(code, 0, sortie)
        self.assertEqual(
            sorted(ids),
            [
                "TestAlpha.test_deux_vert",
                "TestBeta.test_trois_jaune",
                "TestGamma.test_deux_jaune",
            ],
        )

    def test_k_is_case_sensitive_like_unittest(self):
        _, _, ids = self.lancer("-k", "ROUGE")
        self.assertEqual(ids, [])

    def test_a_k_matching_nothing_succeeds(self):
        # Un passage -k sur toute la suite : un fichier sans test qui
        # corresponde ne compte pas comme un échec.
        code, sortie, ids = self.lancer("-k", "violet")
        self.assertEqual(code, 0, sortie)
        self.assertEqual(ids, [])
        self.assertRegex(sortie, r"(?m)^OK$")

    def test_without_options_the_order_is_unittest_order(self):
        code, sortie, ids = self.lancer()
        self.assertEqual(code, 0, sortie)
        self.assertEqual(len(ids), 10)
        self.assertEqual(ids, sorted(ids))

    def test_a_seed_gives_the_same_order_every_time(self):
        _, sortie, premier = self.lancer("--ordre-aleatoire=graine-essai")
        _, _, second = self.lancer("--ordre-aleatoire=graine-essai")
        self.assertEqual(premier, second)
        self.assertIn("graine graine-essai", sortie)
        _, _, defaut = self.lancer()
        self.assertEqual(sorted(premier), defaut)

    def test_seeds_really_shuffle_classes_and_methods(self):
        _, _, defaut = self.lancer()
        ordres = [
            self.lancer(f"--ordre-aleatoire={graine}")[2]
            for graine in ("1", "2", "3", "4")
        ]
        self.assertTrue(any(ordre != defaut for ordre in ordres))
        premieres = {ordre[0].split(".")[0] for ordre in ordres}
        self.assertGreater(len(premieres), 1, "les classes ne bougent pas")
        for ordre in ordres:
            self.assertTrue(self.classes_groupees(ordre), ordre)

    def test_a_class_is_prepared_once_under_shuffle(self):
        code, sortie, ids = self.lancer("--ordre-aleatoire=5")
        self.assertEqual(code, 0, sortie)
        for classe in ("Alpha", "Beta", "Gamma"):
            self.assertEqual(sortie.count(f"PREPARATION {classe}"), 1)

    def test_a_drawn_seed_is_printed_and_replays(self):
        _, sortie, ordre = self.lancer("--ordre-aleatoire")
        graine = re.search(r"--ordre-aleatoire=(\S+)", sortie)
        self.assertIsNotNone(graine, sortie)
        _, _, rejoue = self.lancer(f"--ordre-aleatoire={graine.group(1)}")
        self.assertEqual(ordre, rejoue)

    def test_shuffled_slices_share_the_tests_without_overlap(self):
        tranches = [
            self.lancer(
                "--tranche", f"{rang}/3", "--ordre-aleatoire=graine-essai"
            )[2]
            for rang in range(3)
        ]
        tous = [ident for tranche in tranches for ident in tranche]
        self.assertEqual(len(tous), len(set(tous)))
        self.assertEqual(sorted(tous), self.lancer()[2])
        for tranche in tranches:
            self.assertTrue(self.classes_groupees(tranche), tranche)

    def test_k_and_shuffle_combine(self):
        _, _, ids = self.lancer("-k", "vert", "--ordre-aleatoire=7")
        self.assertEqual(
            sorted(ids),
            [
                "TestAlpha.test_deux_vert",
                "TestBeta.test_un_vert",
                "TestGamma.test_quatre_vert",
            ],
        )


if __name__ == "__main__":
    unittest.main()
