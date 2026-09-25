#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'exécuteur des gestes du moteur : ce qu'il laisse passer, ce qu'il coupe.

Rien ici ne touche au moteur : les gestes joués sont un `make` de banc et un
`python3` qui rapporte ce qu'il voit dans son environnement. Ce qui est
éprouvé, ce sont les PROPRIÉTÉS — une liste blanche qui coupe vraiment, un
PATH jugé par segments et non par sous-chaînes, une ligne affichée qui est la
ligne lancée, et un verdict qui distingue « rendu non nul » de « n'a pas pu
tourner ».

Les noms de variables et de dossiers inventés ici n'apparaissent nulle part
ailleurs dans le dépôt.
"""

import os
import shlex
import shutil
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import runner as R  # noqa: E402

# Un environnement de poste tel qu'il arrive vraiment : ce qui doit passer,
# et quatre choses qui décideraient à la place de l'opérateur.
SOURCE = {
    "HOME": "/foyer-fictif",
    "PATH": "/usr/bin:/bin",
    "LANG": "fr_CA.UTF-8",
    "TERM": "xterm",
    "USER": "compte-fictif",
    "SSH_AUTH_SOCK": "/agent-fictif/sock",
    R.CONFIRMER: R.CONFIRME,
    "MAKEFLAGS": "-j8",
    "MAKELEVEL": "1",
    "SETOPS_UNDERLAY": "grappe-fictive-serpentine",
    "ANSIBLE_FORCE_COLOR": "1",
}


class TestLEnvironnementEstNeuf(unittest.TestCase):
    """Hérité, l'environnement décide à la place de l'opérateur."""

    def test_only_the_whitelist_survives(self):
        garde = R.base(SOURCE)
        self.assertEqual(
            {
                "HOME",
                "PATH",
                "LANG",
                "TERM",
                "USER",
                "SSH_AUTH_SOCK",
            },
            set(garde),
        )

    def test_a_confirmation_left_behind_never_reaches_the_engine(self):
        """Les applicateurs du moteur écrivent sur « true » lu dans
        l'environnement : un reste de geste précédent vaut ordre d'écrire."""
        self.assertNotIn(R.CONFIRMER, R.base(SOURCE))

    def test_the_parent_make_overrides_are_dropped(self):
        """todo se lance lui-même par `make todo` : ses surcharges
        traverseraient jusqu'au Makefile du moteur."""
        self.assertNotIn("MAKEFLAGS", R.base(SOURCE))
        self.assertNotIn("MAKELEVEL", R.base(SOURCE))

    def test_the_variables_the_engine_lets_win_are_dropped(self):
        """Le moteur pose ses défauts en `?=` : une valeur héritée gagne, et
        l'une d'elles désigne la grappe qu'un geste destructeur viserait."""
        self.assertNotIn("SETOPS_UNDERLAY", R.base(SOURCE))
        self.assertNotIn("ANSIBLE_FORCE_COLOR", R.base(SOURCE))

    def test_an_empty_source_gives_an_empty_environment(self):
        self.assertEqual({}, R.base({}))


class TestLePathEstJugeParSegments(unittest.TestCase):
    """Le venv d'ERPLibre porte un autre Python et d'autres bibliothèques."""

    def chemin(self, path):
        return R.base({"PATH": path})["PATH"].split(os.pathsep)

    def test_the_erplibre_venv_is_removed(self):
        self.assertEqual(
            ["/usr/bin", "/bin"],
            self.chemin(f"/depot/{R.VENV_ERPLIBRE}/bin:/usr/bin:/bin"),
        )

    def test_a_folder_that_merely_starts_the_same_stays(self):
        """Juger par sous-chaîne couperait un dossier voisin, et un PATH
        amputé se diagnostique très mal."""
        voisin = f"/depot/{R.VENV_ERPLIBRE}-de-cote/bin"
        self.assertIn(voisin, self.chemin(f"{voisin}:/usr/bin"))

    def test_an_empty_entry_is_dropped(self):
        """Une entrée vide vaut « le dossier courant » pour un shell, ce
        qu'aucun geste n'a demandé."""
        self.assertEqual(["/usr/bin"], self.chemin(":/usr/bin:"))

    def test_nothing_to_remove_leaves_the_path_alone(self):
        self.assertEqual(["/usr/bin", "/bin"], self.chemin("/usr/bin:/bin"))


class TestLaLigneMontreeEstLaLigneLancee(unittest.TestCase):
    MOTEUR = "/depot-fictif/moteur"

    def test_a_target_always_carries_its_confirmation(self):
        """Une ligne sans `CONFIRMER` laisse ignorer si le geste simule
        ou écrit, ce qui est la seule chose qu'on relit avant de valider."""
        argv = R.cible(self.MOTEUR, "instances")
        self.assertEqual(f"{R.CONFIRMER}={R.SIMULE}", argv[-1])

    def test_confirming_writes_it_on_the_line_too(self):
        argv = R.cible(self.MOTEUR, "instance-creer", confirmer=True)
        self.assertEqual(f"{R.CONFIRMER}={R.CONFIRME}", argv[-1])

    def test_the_confirmation_comes_last_whatever_the_variables(self):
        """Posée avant les variables, elle se perdrait de vue dans une ligne
        longue — et c'est la seule qu'on relit avant de valider."""
        argv = R.cible(
            self.MOTEUR,
            "instance-creer",
            [("NOM", "ecosysteme-fictif-cassiterite"), ("MODELE", "socle")],
        )
        self.assertTrue(argv[-1].startswith(R.CONFIRMER + "="))

    def test_the_variables_reach_the_line_as_make_expects_them(self):
        argv = R.cible(self.MOTEUR, "x", [("NOM", "un-nom-fictif")])
        self.assertIn("NOM=un-nom-fictif", argv)

    def test_what_is_shown_parses_back_to_what_is_run(self):
        """L'affichage est DÉRIVÉ de l'argv : une ligne montrée qui n'est
        pas la ligne lancée est pire que pas de ligne du tout."""
        argv = R.cible(self.MOTEUR, "x", [("NOM", "un nom avec des espaces")])
        self.assertEqual(list(argv), shlex.split(R.cite(argv)))


class TestLeVerdict(unittest.TestCase):
    """« Rendu non nul » et « n'a pas pu tourner » sont deux nouvelles."""

    def test_a_success_is_zero_and_reads_as_such(self):
        vu = R.jouer((sys.executable, "-c", "pass"))
        self.assertEqual(0, vu.code)
        self.assertTrue(vu.reussi)

    def test_a_refusal_carries_its_code(self):
        vu = R.jouer((sys.executable, "-c", "raise SystemExit(2)"))
        self.assertEqual(2, vu.code)
        self.assertFalse(vu.reussi)

    def test_a_command_that_does_not_exist_is_not_a_zero(self):
        """Rendre 0 ferait annoncer une réussite à un geste qui n'a jamais
        commencé."""
        vu = R.jouer(("/nulle-part-fictif/rien",))
        self.assertIsNone(vu.code)
        self.assertFalse(vu.reussi)

    def test_a_gesture_past_its_delay_is_not_a_zero(self):
        vu = R.jouer(
            (sys.executable, "-c", "import time; time.sleep(5)"), delai=1
        )
        self.assertIsNone(vu.code)
        self.assertFalse(vu.reussi)

    def test_the_output_is_carried_back(self):
        vu = R.jouer((sys.executable, "-c", "print('un-mot-fictif')"))
        self.assertIn("un-mot-fictif", vu.sortie)

    def test_the_error_output_is_carried_back_too(self):
        """Un geste qui explique son refus le fait souvent sur l'erreur :
        la perdre laisserait un code nu, sans raison."""
        vu = R.jouer(
            (
                sys.executable,
                "-c",
                "import sys; print('sur-erreur-fictif', file=sys.stderr)",
            )
        )
        self.assertIn("sur-erreur-fictif", vu.sortie)


class TestDeBoutEnBout(unittest.TestCase):
    """La chaîne entière : `make`, sa variable de ligne, et ce que le script
    appelé voit dans SON environnement."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        sonde = (
            f"import os; print('vu=' + repr(os.environ.get({R.CONFIRMER!r})))"
        )
        with open(
            os.path.join(self.dossier, "Makefile"), "w", encoding="utf-8"
        ) as fichier:
            fichier.write(
                "sonde:\n"
                f"\t@{shlex.quote(sys.executable)} -c {shlex.quote(sonde)}\n"
            )

    def vu(self, env, confirmer=False):
        verdict = R.jouer(
            R.cible(self.dossier, "sonde", confirmer=confirmer), env=env
        )
        self.assertEqual(0, verdict.code, verdict.sortie)
        return verdict.sortie.strip()

    def test_the_line_decides_and_the_environment_does_not(self):
        """`make` met une variable de ligne dans l'environnement du script
        appelé, ET elle l'emporte sur celle qui serait héritée. C'est ce qui
        fait du `CONFIRMER` affiché la garde réelle, et non un ornement."""
        pollue = dict(R.base(SOURCE))
        pollue[R.CONFIRMER] = R.CONFIRME
        self.assertEqual(f"vu={R.SIMULE!r}", self.vu(pollue))

    def test_confirming_reaches_the_called_script(self):
        """Contrôle positif : sans lui, une sonde qui ne verrait JAMAIS
        « true » passerait l'épreuve précédente sans rien prouver."""
        self.assertEqual(
            f"vu={R.CONFIRME!r}", self.vu(R.base(SOURCE), confirmer=True)
        )


if __name__ == "__main__":
    unittest.main()
