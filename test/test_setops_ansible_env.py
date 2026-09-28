#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La couche qui pose l'environnement Ansible du contrôleur.

Rien ici ne touche au réseau ni à un vrai interpréteur : le moteur est
fabriqué dans un dossier jetable, et le venv est un dossier de scripts shell
qui répondent ce qu'on leur fait dire. Ce qui est éprouvé, ce sont les
PROPRIÉTÉS que la pose doit tenir — l'ordre des gestes, le PATH, ce qui est
montré face à ce qui est lancé, et les refus.

Les noms de moteur, d'écosystème et de paquet fictif sont inventés et
n'apparaissent nulle part ailleurs dans le dépôt.
"""

import os
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import ansible_env as A  # noqa: E402

PLAGE = "ansible-core>=2.18,<2.19"

REQUIREMENTS_PY = """# Un commentaire, puis deux épingles et une non-épingle.
paquet-fictif-glauconie==1.4.2
autre-fictif-celadonite==0.9
sans-epingle-fictive-natrolite>=2
"""

REQUIREMENTS_YML = """---
collections:
  - name: fictive.glauconie
    version: 3.10.2
  - name: fictive.celadonite
    version: 1.6.2
  - name: fictive.sans_version
"""


def ecrire(chemin, contenu, mode=0o644):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as fichier:
        fichier.write(contenu)
    os.chmod(chemin, mode)


class CasDeBanc(unittest.TestCase):
    """Une racine jetable portant un moteur fabriqué et un venv de scripts."""

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        self.moteur = os.path.join(self.racine, "moteur-fictif-glauconie")
        ecrire(
            os.path.join(self.moteur, A.DEFAULTS_ANSIBLE),
            f'serveur_ops_ansible: "{PLAGE}"\n',
        )
        ecrire(os.path.join(self.moteur, A.REQUIREMENTS_PY), REQUIREMENTS_PY)
        ecrire(os.path.join(self.moteur, A.REQUIREMENTS_YML), REQUIREMENTS_YML)
        self.venv = A.chemin_venv(self.racine)

    def poser_venv(self, python="echo 9.9.9", python3="echo 9.9"):
        """Un venv de banc : deux scripts qui répondent ce qu'on leur dit."""
        ecrire(
            os.path.join(self.venv, "bin", "python"),
            f"#!/bin/sh\n{python}\n",
            0o755,
        )
        ecrire(
            os.path.join(self.venv, "bin", "python3"),
            f"#!/bin/sh\n{python3}\n",
            0o755,
        )


class TestCeQueLeMoteurExige(CasDeBanc):
    def test_the_range_is_read_in_the_engine(self):
        self.assertEqual(PLAGE, A.plage_ansible(self.moteur))

    def test_a_missing_engine_gives_no_range(self):
        self.assertIsNone(A.plage_ansible(os.path.join(self.racine, "nulle")))

    def test_only_exact_pins_are_kept(self):
        """Une ligne sans « == » ne dit pas quoi vérifier après la pose."""
        self.assertEqual(
            (
                ("paquet-fictif-glauconie", "1.4.2"),
                ("autre-fictif-celadonite", "0.9"),
            ),
            A.bibliotheques_epinglees(self.moteur),
        )

    def test_collections_keep_only_the_entries_that_carry_a_version(self):
        self.assertEqual(
            (
                ("fictive.glauconie", "3.10.2"),
                ("fictive.celadonite", "1.6.2"),
            ),
            A.collections_epinglees(self.moteur),
        )


class TestLisibleNestPasVide(CasDeBanc):
    """« Le moteur n'épingle rien » et « on ne sait pas » sont deux choses.

    Les confondre ferait porter la ligne d'état sur un fichier illisible, en
    annonçant zéro écart — le pire des verdicts, puisqu'il rassure.
    """

    def test_an_unreadable_library_file_is_unknown(self):
        os.remove(os.path.join(self.moteur, A.REQUIREMENTS_PY))
        self.assertIsNone(A.bibliotheques_epinglees(self.moteur))

    def test_an_unreadable_collection_file_is_unknown(self):
        os.remove(os.path.join(self.moteur, A.REQUIREMENTS_YML))
        self.assertIsNone(A.collections_epinglees(self.moteur))

    def test_a_collection_file_without_the_list_is_unknown(self):
        """Une forme inattendue refuse au lieu de deviner qu'il n'y a rien."""
        ecrire(
            os.path.join(self.moteur, A.REQUIREMENTS_YML), "autre_chose: 1\n"
        )
        self.assertIsNone(A.collections_epinglees(self.moteur))

    def test_a_file_that_pins_nothing_is_empty_and_not_unknown(self):
        ecrire(os.path.join(self.moteur, A.REQUIREMENTS_PY), "# rien\n")
        ecrire(
            os.path.join(self.moteur, A.REQUIREMENTS_YML), "collections: []\n"
        )
        self.assertEqual((), A.bibliotheques_epinglees(self.moteur))
        self.assertEqual((), A.collections_epinglees(self.moteur))


class TestLaPlageSeCompare(unittest.TestCase):
    def test_a_version_inside_and_one_outside(self):
        self.assertIs(True, A.dans_la_plage("2.18.19", PLAGE))
        self.assertIs(False, A.dans_la_plage("2.19.4", PLAGE))

    def test_an_unreadable_side_is_unknown_and_never_true(self):
        self.assertIsNone(A.dans_la_plage(None, PLAGE))
        self.assertIsNone(A.dans_la_plage("2.18.19", "pas une exigence"))

    def test_a_range_that_pins_nothing_is_refused(self):
        """Une plage sans borne laisserait passer n'importe quelle version."""
        self.assertIsNone(A.specifieur("ansible-core"))

    def test_extras_markers_and_urls_are_refused(self):
        for texte in (
            "ansible-core[extra]>=2.18,<2.19",
            "ansible-core>=2.18,<2.19; python_version>'3'",
            "ansible-core @ https://example.invalid/a.whl",
            "autre-paquet>=2.18,<2.19",
        ):
            with self.subTest(texte=texte):
                self.assertIsNone(A.specifieur(texte))


class TestLInterprete(unittest.TestCase):
    def test_an_interpreter_on_the_path_comes_first(self):
        """Le moindre ajout : ne rien poser quand le poste en a déjà un."""
        with mock.patch.object(
            A.shutil, "which", lambda nom: "/usr/bin/" + nom
        ):
            chemin, provenance = A.interprete("3.13")
        self.assertEqual(("/usr/bin/python3.13", "PATH"), (chemin, provenance))

    def test_without_one_on_the_path_the_version_manager_is_asked(self):
        with (
            mock.patch.object(
                A.shutil,
                "which",
                lambda nom: None if "python" in nom else "/m",
            ),
            mock.patch.object(A, "_mise_ou", lambda _m: "/pose/3.13"),
            mock.patch.object(A.os, "access", lambda *_a: True),
        ):
            chemin, provenance = A.interprete("3.13")
        self.assertEqual(
            (os.path.join("/pose/3.13", "bin", "python3.13"), "mise"),
            (chemin, provenance),
        )

    def test_nothing_anywhere_names_nothing(self):
        with mock.patch.object(A.shutil, "which", lambda _n: None):
            self.assertEqual((None, ""), A.interprete("3.13"))
            self.assertIsNone(A.geste_mise("3.13"))


class TestLesEtapes(CasDeBanc):
    def etapes(self, refaire=False):
        return A.etapes(
            self.racine, self.moteur, "/un/python3.13", PLAGE, refaire
        )

    def test_what_is_shown_is_what_is_run(self):
        """Un affichage écrit une seconde fois dérive de ce qui part. Il est
        DÉRIVÉ de l'argv, et cette épreuve tient la dérivation."""
        for etape in self.etapes():
            with self.subTest(etape=etape.argv[0]):
                self.assertEqual(shlex.join(etape.argv), A.montre(etape))

    def test_the_range_reaches_pip_exactly_as_the_engine_writes_it(self):
        """Reformulée, une plage se corrigerait en silence : un désacord
        entre ce que le moteur exige et ce qui est posé doit se VOIR."""
        argvs = [e.argv for e in self.etapes() if e.argv]
        self.assertTrue(any(PLAGE in a for a in argvs), argvs)

    def test_the_collections_land_under_the_engine(self):
        attendu = os.path.join(self.moteur, A.COLLECTIONS)
        argvs = [e.argv for e in self.etapes() if e.argv]
        self.assertTrue(any(attendu in a for a in argvs), argvs)

    def test_redoing_removes_before_it_builds(self):
        """L'ordre EST la garantie : supprimer après avoir créé effacerait
        ce qu'on vient de poser, et supprimer est la seule façon de changer
        l'INTERPRÉTEUR d'un venv déjà là."""
        pas = self.etapes(refaire=True)
        self.assertEqual(A.SUPPRIMER, pas[0].action)
        self.assertIsNone(pas[0].argv)
        self.assertIn("venv", pas[1].argv)

    def test_without_redoing_nothing_is_removed(self):
        self.assertEqual(
            [], [e for e in self.etapes() if e.action == A.SUPPRIMER]
        )


class TestLEnvironnementDuGeste(CasDeBanc):
    """La garde du moteur lance `python3` NU : c'est le PATH qui décide."""

    def test_the_venv_bin_is_the_first_entry_of_the_path(self):
        env = A.environnement(
            self.racine, self.moteur, {"PATH": "/usr/bin:/bin"}
        )
        self.assertEqual(
            os.path.join(self.venv, "bin"), env["PATH"].split(os.pathsep)[0]
        )

    def test_the_rest_of_the_path_survives(self):
        env = A.environnement(
            self.racine, self.moteur, {"PATH": "/usr/bin:/bin"}
        )
        self.assertEqual(["/usr/bin", "/bin"], env["PATH"].split(":")[1:])

    def test_the_collections_are_named_because_the_engine_config_does_not(
        self,
    ):
        env = A.environnement(self.racine, self.moteur, {"PATH": ""})
        self.assertEqual(
            os.path.join(self.moteur, A.COLLECTIONS),
            env["ANSIBLE_COLLECTIONS_PATH"],
        )

    def test_the_minor_is_read_through_that_path(self):
        """La sonde MESURE ce que verra la garde : le `python3` du venv."""
        self.poser_venv(python3="echo 3.13")
        self.assertEqual("3.13", A.mineur_du_path(self.racine, self.moteur))

    def test_a_venv_wiped_under_the_feet_reads_as_unknown(self):
        """Un chemin absolu vers `bin/python` répondrait encore ; le PATH,
        lui, ne trouve plus rien et c'est le verdict juste."""
        self.poser_venv(python3="echo 3.13")
        shutil.rmtree(self.venv)
        with mock.patch.dict(os.environ, {"PATH": "/nulle-part-fictif"}):
            self.assertIsNone(A.mineur_du_path(self.racine, self.moteur))


class TestLaSondeDeVersion(CasDeBanc):
    def test_the_root_is_not_on_the_probe_path(self):
        """`-c` met le dossier courant en tête de `sys.path` : la sonde
        tourne DANS le venv, jamais à la racine."""
        self.poser_venv(python="echo 1.2.3")
        ecrire(os.path.join(self.racine, "piege.txt"), "rien")
        self.assertEqual("1.2.3", A.version_posee(self.racine, "peu-importe"))

    def test_a_relative_root_reads_the_same_as_an_absolute_one(self):
        """Le chemin du venv est ABSOLU : relatif, il se résoudrait sous le
        `cwd` de la sonde — c'est-à-dire sous lui-même — et l'écran dirait
        « illisible » pendant qu'une vérification lirait la version."""
        self.poser_venv(python="echo 4.5.6")
        vrai = os.getcwd()
        os.chdir(self.racine)
        self.addCleanup(os.chdir, vrai)
        self.assertEqual("4.5.6", A.version_posee(".", "peu-importe"))

    def test_a_chatty_probe_is_unreadable(self):
        self.poser_venv(python="echo une; echo deux")
        self.assertIsNone(A.version_posee(self.racine, "peu-importe"))

    def test_a_failing_probe_is_unreadable(self):
        self.poser_venv(python="exit 3")
        self.assertIsNone(A.version_posee(self.racine, "peu-importe"))


class TestLeGardeDeSuppression(CasDeBanc):
    """Effacer est le seul geste irréversible de cette couche."""

    def test_a_real_venv_under_the_root_is_removed(self):
        self.poser_venv()
        self.assertEqual(0, A._supprimer_venv(self.racine))
        self.assertFalse(os.path.exists(self.venv))

    def test_a_link_is_never_followed(self):
        """Le suivre effacerait ce qu'il désigne, qui n'est pas ce que
        l'écran a nommé.

        LE REFUS TOMBE AVANT L'EFFACEMENT. Constater que le contenu survit
        ne prouverait que le garde de `shutil.rmtree`, qui refuse déjà un
        lien : le jour où l'on efface autrement — un `os.walk`, un
        `ignore_errors` — ce constat resterait vert et la cible partirait.
        """
        ailleurs = os.path.join(self.racine, "ailleurs-fictif")
        ecrire(os.path.join(ailleurs, "tresor.txt"), "à garder")
        os.symlink(ailleurs, self.venv)
        tentes = []
        with mock.patch.object(
            A.shutil, "rmtree", lambda *a, **k: tentes.append(a)
        ):
            code = A._supprimer_venv(self.racine)
        self.assertEqual(1, code)
        self.assertEqual([], tentes, "l'effacement a été tenté sur un lien")
        self.assertTrue(os.path.isfile(os.path.join(ailleurs, "tresor.txt")))

    def test_a_missing_venv_is_not_a_success(self):
        """Rendre 0 sur un venv absent ferait annoncer une suppression que
        personne n'a faite."""
        self.assertEqual(1, A._supprimer_venv(self.racine))

    def test_the_guard_would_notice_a_removal_that_always_fires(self):
        """Contrôle positif : un garde qui refuse toujours passerait les
        deux refus ci-dessus. Celui-ci prouve qu'il accepte le cas juste."""
        self.poser_venv()
        self.assertEqual(0, A._supprimer_venv(self.racine))


class TestLeLanceur(CasDeBanc):
    def test_a_command_that_cannot_run_is_a_failure_not_a_raise(self):
        """Une étape qui lève arrêterait le menu sur une trace ; elle rend
        un code, que l'appelant lit."""
        etape = A.Etape(argv=("/nulle-part-fictif/rien",))
        self.assertNotEqual(0, A.poser(etape, self.racine))

    def test_a_step_without_argv_and_without_action_fails(self):
        self.assertNotEqual(0, A.poser(A.Etape(argv=None), self.racine))

    def test_the_removal_step_goes_through_the_guard(self):
        self.poser_venv()
        etape = A.Etape(argv=None, libelle="rm", action=A.SUPPRIMER)
        self.assertEqual(0, A.poser(etape, self.racine))
        self.assertFalse(os.path.exists(self.venv))


if __name__ == "__main__":
    unittest.main()
