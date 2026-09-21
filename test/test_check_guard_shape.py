#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le détecteur de gardes épinglés au texte : ce qu'il voit, ce qu'il laisse.

DEUX ERREURS, ET LA SECONDE EST LA PIRE. Ne pas voir un garde épinglé le
laisse passer une régression ; crier au loup sur un contrôle légitime apprend
à désarmer l'outil. Les deux sont éprouvées ici, et les cas réellement
rencontrés dans ce dépôt servent de témoins.

Les extraits analysés sont écrits en CHAÎNES : les poser en vrai code de ce
fichier ferait de ce fichier même une trouvaille, ce qui est vrai mais
inutile.
"""

import os
import sys
import tempfile
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.analyse import check_guard_shape as G  # noqa: E402


class CasDeDetecteur(unittest.TestCase):
    def analyse(self, source):
        """Les trouvailles d'un extrait, écrit dans un fichier jetable."""
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "test_extrait.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(source)
            return G.inspect(chemin)

    def extraits(self, source):
        return [f["excerpt"] for f in self.analyse(source)]


class TestCeQuIlVoit(CasDeDetecteur):
    def test_a_fragment_compared_to_getsource(self):
        """La forme la plus courante, et celle qui a coûté le plus."""
        self.assertEqual(
            ["if name in lst_known"],
            self.extraits(
                "import inspect\n"
                "def test_x(self):\n"
                "    source = inspect.getsource(outil.verifie)\n"
                "    self.assertIn('if name in lst_known', source)\n"
            ),
        )

    def test_a_fragment_compared_to_a_module_read_from_disk(self):
        """Le chemin est souvent posé loin de la lecture."""
        self.assertEqual(
            ["return result.stdout"],
            self.extraits(
                "MOTEUR = 'script/analyse/outil.py'\n"
                "def test_x(self):\n"
                "    source = open(MOTEUR).read()\n"
                "    self.assertIn('return result.stdout', source)\n"
            ),
        )

    def test_the_negative_form_too(self):
        """« ce texte ne s'y trouve pas » est le même pari sur
        l'orthographe, et c'est lui qui laissait passer trois écritures."""
        self.assertEqual(
            ['open(path, "w"'],
            self.extraits(
                "import inspect\n"
                "def test_x(self):\n"
                "    s = inspect.getsource(m.verifie)\n"
                "    self.assertNotIn('open(path, \"w\"', s)\n"
            ),
        )

    def test_a_call_with_an_argument_pins_its_shape(self):
        """« image_path(image) » n'est plus un câblage : c'est la forme de
        l'appel, et un argument renommé la fait rougir pour rien."""
        self.assertEqual(
            ["image_path(image)"],
            self.extraits(
                "import inspect\n"
                "def test_x(self):\n"
                "    s = inspect.getsource(m.verifie)\n"
                "    self.assertIn('image_path(image)', s)\n"
            ),
        )

    def test_the_sql_fragment_that_stayed_green_on_the_inversion(self):
        """Témoin pris dans ce dépôt : il rougissait sur un préfixe changé
        et restait vert sur l'inversion des deux bras, qui casse tout."""
        self.assertEqual(
            ["'id:' || id::text"],
            self.extraits(
                "import inspect\n"
                "def test_x(self):\n"
                "    self.assertIn(\"'id:' || id::text\","
                " inspect.getsource(q.inspect))\n"
            ),
        )


class TestCeQuIlLaisse(CasDeDetecteur):
    """Un garde qui rougit à tort est un garde qu'on apprend à désarmer."""

    def test_a_bare_name_is_a_wiring_check(self):
        """« ce chemin passe-t-il par là » est une propriété réelle."""
        self.assertEqual(
            [],
            self.analyse(
                "import inspect\n"
                "def test_x(self):\n"
                "    s = inspect.getsource(m.ecran)\n"
                "    self.assertIn('run_psql', s)\n"
            ),
        )

    def test_a_name_with_empty_parentheses_is_one_too(self):
        self.assertEqual(
            [],
            self.analyse(
                "import inspect\n"
                "def test_x(self):\n"
                "    s = inspect.getsource(m.ecran)\n"
                "    self.assertIn('self._qemu_recover_files()', s)\n"
            ),
        )

    def test_a_rendered_output_is_not_source(self):
        """Vérifier qu'un rendu porte une ligne, c'est mesurer ce que le
        code FAIT. C'est la moitié des épreuves du dépôt."""
        self.assertEqual(
            [],
            self.analyse(
                "def test_x(self):\n"
                "    texte = DQ.build_cloud_config(args, None, [])\n"
                "    self.assertIn('nft -f /etc/regles.nft', texte)\n"
            ),
        )

    def test_reading_a_file_that_is_not_a_module(self):
        self.assertEqual(
            [],
            self.analyse(
                "def test_x(self):\n"
                "    s = open('conf/exemple.json').read()\n"
                "    self.assertIn('\"port\": 8069', s)\n"
            ),
        )

    def test_an_equality_is_not_a_text_comparison(self):
        """Sur un source entier, `assertEqual` ne peut que constater
        l'identité — personne ne l'écrit ; sur un extrait, il compare autre
        chose. L'inclure noierait le signal."""
        self.assertEqual(
            [],
            self.analyse(
                "import inspect\n"
                "def test_x(self):\n"
                "    s = inspect.getsource(m.ecran)\n"
                "    self.assertEqual(ATTENDU, s)\n"
            ),
        )


class TestLOutilSurLuiMeme(unittest.TestCase):
    def test_its_own_docstring_is_not_a_finding(self):
        """Il CITE les formes qu'il cherche. Des citations sont du texte, et
        non des appels : rien ne doit y correspondre."""
        self.assertEqual([], G.inspect(G.__file__))

    def test_it_finds_something_on_this_repository(self):
        """Un détecteur qui ne détecte rien passe tous les tests d'à côté
        sans rien garder."""
        trouves = []
        for chemin in G.etend([os.path.join(RACINE, "test")]):
            trouves.extend(G.inspect(chemin))
        self.assertGreater(len(trouves), 10)

    def test_a_file_that_does_not_parse_is_not_a_failure(self):
        """Un hook ne doit pas s'arrêter sur un fichier en cours
        d'écriture ; le reste de l'outillage le dira mieux."""
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "casse.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write("def x(:\n")
            self.assertEqual([], G.inspect(chemin))


class TestLesCodesDeSortie(unittest.TestCase):
    """La convention partagée des outils du dépôt : 0 rien, 1 trouvailles,
    2 l'outil a échoué."""

    def lance(self, *argv):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            code = G.main(list(argv))
        return code, sortie.getvalue()

    def test_a_clean_file_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "propre.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write("def x():\n    return 1\n")
            code, texte = self.lance(chemin, "--no-color")
        self.assertEqual(0, code)
        self.assertEqual("", texte)

    def test_a_finding_exits_one_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "test_pris.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(
                    "import inspect\n"
                    "def test_x(self):\n"
                    "    s = inspect.getsource(m.ecran)\n"
                    "    self.assertIn('if a == 1:', s)\n"
                )
            code, texte = self.lance(chemin, "--no-color")
        self.assertEqual(1, code)
        self.assertIn("if a == 1:", texte)

    def test_the_json_form_carries_what_was_scanned(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "propre.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            _code, texte = self.lance(chemin, "--json", "--no-color")
        self.assertEqual(1, json.loads(texte)["scanned"])


class TestLeHookLeLance(unittest.TestCase):
    """Le hook porte DEUX outils, et la liste est la seule chose à toucher.

    Un second lancement écrit à côté du premier aurait donné deux façons de
    se taire, et un plafond appliqué à l'un et pas à l'autre.
    """

    HOOK = os.path.join(RACINE, "script", "git", "hooks", "pre-commit")

    def hook(self):
        with open(self.HOOK, encoding="utf-8") as fh:
            return fh.read()

    def test_the_hook_carries_this_tool(self):
        self.assertIn("check_guard_shape.py", self.hook())

    def test_the_tools_are_a_list_not_two_copies(self):
        """DÉRIVÉ : la mécanique de lancement ne doit exister qu'une fois.
        Deux copies divergent — un plafond changé d'un côté, un délai de
        l'autre — et le second outil se tait sans qu'on le voie."""
        import ast

        arbre = ast.parse(self.hook())
        lances = [
            n.lineno
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "run"
            and getattr(n.func.value, "id", "") == "subprocess"
        ]
        self.assertEqual(
            1, len(lances), f"subprocess.run écrit {len(lances)} fois"
        )

    def test_both_tools_are_declared_in_the_same_place(self):
        import ast

        arbre = ast.parse(self.hook())
        outils = [
            n.value
            for n in ast.walk(arbre)
            if isinstance(n, ast.Assign)
            and any(
                isinstance(c, ast.Name) and c.id == "OUTILS" for c in n.targets
            )
        ]
        self.assertEqual(1, len(outils), "OUTILS n'est pas déclaré une fois")
        self.assertGreaterEqual(len(outils[0].elts), 2)

    def test_every_tool_declares_what_to_do_about_it(self):
        """Un rapport sans pied dit QUOI sans dire quoi en faire, et un
        lecteur qui ne sait pas agir apprend à ne plus lire."""
        import ast

        arbre = ast.parse(self.hook())
        for n in ast.walk(arbre):
            if not (
                isinstance(n, ast.Assign)
                and any(
                    isinstance(c, ast.Name) and c.id == "OUTILS"
                    for c in n.targets
                )
            ):
                continue
            for entree in n.value.elts:
                clefs = {
                    k.value for k in entree.keys if isinstance(k, ast.Constant)
                }
                self.assertEqual({"script", "titre", "pied"}, clefs)


if __name__ == "__main__":
    unittest.main()
