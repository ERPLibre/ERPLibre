#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les réponses de « ./todo.sh install » données d'avance.

Ces tests gardent script/todo/install_non_interactif.py et les points
d'entrée qui s'en servent :

- une option l'emporte sur sa variable, une valeur illisible ou une
  identité à moitié donnée est refusée, et une réponse délibérée absente
  est nommée avec l'option et la variable qui la donnent ;
- la réponse sur mise n'est exigée que si mise manque, et la cible « m »,
  qui fait choisir un appareil au clavier, est refusée en mode non
  interactif ;
- install.sh lit --non-interactive et vérifie les réponses AVANT de poser
  le venv d'outillage ; todo.py refuse d'ouvrir son menu dans ce mode ;
- make install_non_interactive passe par ce même chemin.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import install_non_interactif as ni  # noqa: E402


def environnement(**extra):
    """L'environnement du test, sans mode ni réponse hérités du shell."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k != ni.NON_INTERACTIF
        and k not in {var for _, var, _ in ni.QUESTIONS.values()}
    }
    env.update(extra)
    return env


class TestReponses(unittest.TestCase):
    def lire(self, argv, **env):
        return ni.lire_reponses(argv, environnement(**env))

    def test_options(self):
        reponses, mode = self.lire(
            [
                "--non-interactive",
                "--target",
                "18.0",
                "--env",
                "prod",
                "--type",
                "extra",
                "--system",
                "yes",
            ]
        )
        self.assertTrue(mode)
        self.assertEqual(
            (
                reponses["cible"],
                reponses["environnement"],
                reponses["type"],
                reponses["systeme"],
            ),
            ("18.0", "prod", "extra", True),
        )

    def test_variables(self):
        reponses, mode = self.lire(
            [],
            EL_NON_INTERACTIVE="1",
            EL_INSTALL_TARGET="Q",
            EL_FREEZE="0",
            EL_WITH_EXTRA="0",
            EL_INSTALL_SYSTEM="0",
        )
        self.assertTrue(mode)
        self.assertEqual(reponses["cible"], "q")
        self.assertEqual(reponses["environnement"], "dev")
        self.assertEqual(reponses["type"], "standard")
        self.assertIs(reponses["systeme"], False)

    def test_l_option_l_emporte_sur_la_variable(self):
        reponses, _ = self.lire(["--env", "dev"], EL_FREEZE="1")
        self.assertEqual(reponses["environnement"], "dev")

    def test_sans_mode_rien_n_est_impose(self):
        reponses, mode = self.lire([])
        self.assertFalse(mode)
        self.assertTrue(all(v is None for v in reponses.values()))

    def test_variable_illisible_refusee(self):
        with self.assertRaises(ni.ReponsesInvalides) as e:
            self.lire([], EL_FREEZE="2", EL_INSTALL_SYSTEM="oui")
        self.assertEqual(len(e.exception.messages), 2)
        self.assertIn("EL_FREEZE=2", e.exception.messages[0])

    def test_identite_a_moitie_refusee(self):
        with self.assertRaises(ni.ReponsesInvalides):
            self.lire(["--git-name", "Nom Fictif"])
        with self.assertRaises(ni.ReponsesInvalides):
            self.lire([], EL_GIT_EMAIL="fictif@example.invalid")

    def test_courriel_invalide_refuse(self):
        with self.assertRaises(ni.ReponsesInvalides):
            self.lire(["--git-name", "Nom", "--git-email", "sans-arobase"])

    def test_identite_complete_acceptee(self):
        reponses, _ = self.lire(
            [],
            EL_GIT_NAME="Nom Fictif",
            EL_GIT_EMAIL="fictif@example.invalid",
        )
        self.assertEqual(reponses["git_courriel"], "fictif@example.invalid")


class TestManquantes(unittest.TestCase):
    def test_une_version_demande_tout(self):
        self.assertEqual(
            ni.manquantes({"cible": "18.0"}),
            ["environnement", "type", "systeme"],
        )

    def test_rien_donne(self):
        self.assertEqual(
            ni.manquantes({}),
            ["cible", "environnement", "type", "systeme"],
        )

    def test_q_w_m_n_ont_ni_environnement_ni_type(self):
        for cible in ("q", "w", "m"):
            with self.subTest(cible=cible):
                self.assertEqual(ni.manquantes({"cible": cible}), ["systeme"])

    def test_mise_requise_seulement_quand_elle_manque(self):
        reponses = {"cible": "q", "systeme": True}
        self.assertEqual(ni.manquantes(reponses), [])
        self.assertEqual(ni.manquantes(reponses, mise_absent=True), ["mise"])
        reponses["mise"] = False
        self.assertEqual(ni.manquantes(reponses, mise_absent=True), [])

    def test_l_identite_n_est_jamais_requise(self):
        reponses = {
            "cible": "18.0",
            "environnement": "dev",
            "type": "standard",
            "systeme": False,
        }
        self.assertEqual(ni.manquantes(reponses), [])

    def test_le_message_nomme_option_et_variable(self):
        ligne = ni.message_manquante("environnement")
        for attendu in ("--env", "dev|prod", "EL_FREEZE=0|1", "FREEZE=0|1"):
            self.assertIn(attendu, ligne)
        self.assertIn("EL_INSTALL_TARGET", ni.message_manquante("cible"))


class TestPreparer(unittest.TestCase):
    def preparer(self, argv, mise=False, **env):
        with unittest.mock.patch.object(
            ni, "mise_requis", lambda environ: mise
        ):
            return ni.preparer(argv, environnement(**env))

    def test_hors_mode_aucune_erreur(self):
        self.assertEqual(self.preparer(["--target", "18.0"])[2], [])

    def test_cible_m_refusee_en_mode(self):
        _, mode, erreurs = self.preparer(
            ["--non-interactive", "--target", "m", "--system", "no"]
        )
        self.assertTrue(mode)
        self.assertEqual(len(erreurs), 1)

    def test_mise_absente_exige_sa_reponse(self):
        argv = ["--non-interactive", "--target", "q", "--system", "no"]
        erreurs = self.preparer(argv, mise=True)[2]
        self.assertTrue(any("--mise" in e for e in erreurs))
        self.assertEqual(
            self.preparer(argv + ["--mise", "no"], mise=True)[2], []
        )

    def test_verifier_rend_2_et_nomme_les_options(self):
        sortie = io.StringIO()
        with (
            unittest.mock.patch.object(ni, "mise_requis", lambda e: False),
            contextlib.redirect_stdout(sortie),
        ):
            code = ni.verifier(["--non-interactive"], environnement())
        self.assertEqual(code, 2)
        self.assertIn("--target", sortie.getvalue())


class TestMiseRequis(unittest.TestCase):
    def test_pyenv_impose_ne_demande_rien(self):
        self.assertFalse(
            ni.mise_requis(environnement(EL_PYTHON_PROVIDER="pyenv"))
        )

    def test_mise_introuvable(self):
        with tempfile.TemporaryDirectory() as home:
            # Un sudo qui refuse : le PATH système ne mène pas au vrai.
            sudo = Path(home, "sudo")
            sudo.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            sudo.chmod(0o755)
            env = environnement(HOME=home, PATH=f"{home}:/usr/bin:/bin")
            env.pop("MISE_INSTALL_PATH", None)
            env.pop("EL_PYTHON_PROVIDER", None)
            if Path("/usr/bin/mise").exists() or Path("/bin/mise").exists():
                self.skipTest("mise posé dans /usr/bin")
            self.assertTrue(ni.mise_requis(env))


class TestInstallSh(unittest.TestCase):
    """install.sh dans une copie réduite du dépôt : aucun venv, et une
    version requise que nul python ne porte, d'où l'amorçage. Le faux
    source_todo.sh note qu'il a été lancé, et avec quel mode."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        for fichier in (
            "install.sh",
            "script/install/lib_git_requis.sh",
            "script/install/lib_non_interactive.sh",
            "script/__init__.py",
            "script/todo/install_non_interactif.py",
            "script/todo/todo_i18n.py",
            "env_var.sh",
        ):
            cible = self.racine / fichier
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes((RACINE / fichier).read_bytes())
        (self.racine / "conf").mkdir()
        (self.racine / "conf/python-erplibre-venv").write_text(
            ".venv.absent\n"
        )
        (self.racine / "conf/python-erplibre-version").write_text("99.0.0\n")
        amorce = self.racine / "script/todo/source_todo.sh"
        amorce.write_text(
            '#!/bin/sh\necho "AMORCE mode=${EL_NON_INTERACTIVE:-}'
            ' mise=${EL_INSTALL_MISE:-}"\n',
            encoding="utf-8",
        )
        amorce.chmod(0o755)

    def lancer(self, *argv, **env):
        return subprocess.run(
            ["bash", str(self.racine / "install.sh"), *argv],
            env=environnement(EL_PYTHON_PROVIDER="pyenv", **env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_option_reponses_manquantes_rien_n_est_amorce(self):
        fait = self.lancer("install", "--non-interactive", "--target", "18.0")
        self.assertEqual(fait.returncode, 2)
        self.assertNotIn("AMORCE", fait.stdout)
        self.assertIn("--system", fait.stdout)

    def test_option_reponses_completes_amorce_en_mode(self):
        fait = self.lancer(
            "install",
            "--non-interactive",
            "--target",
            "q",
            "--system",
            "no",
        )
        self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
        self.assertIn("AMORCE mode=1", fait.stdout)

    def test_la_reponse_mise_atteint_l_amorcage(self):
        for forme in (["--mise", "yes"], ["--mise=yes"]):
            with self.subTest(forme=forme):
                fait = self.lancer(
                    "install",
                    "--non-interactive",
                    "--target",
                    "q",
                    "--system",
                    "no",
                    *forme,
                )
                self.assertIn("AMORCE mode=1 mise=1", fait.stdout)

    def test_sans_mode_sans_terminal_rien_n_est_amorce(self):
        fait = self.lancer("install", "--target", "q")
        self.assertEqual(fait.returncode, 1)
        self.assertNotIn("AMORCE", fait.stdout)


class TestPointsDEntreeTodo(unittest.TestCase):
    """todo.py lancé pour de vrai, par le python du venv d'outillage."""

    PYTHON = RACINE / ".venv.erplibre/bin/python"

    def lancer(self, *argv, **env):
        if not self.PYTHON.exists():
            self.skipTest("venv d'outillage absent")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return subprocess.run(
            [str(self.PYTHON), "script/todo/todo.py", *argv],
            cwd=RACINE,
            env=environnement(XDG_STATE_HOME=tmp.name, **env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_install_reponses_manquantes(self):
        fait = self.lancer("install", "--non-interactive")
        self.assertEqual(fait.returncode, 2)
        self.assertIn("--target", fait.stdout)

    def test_menu_refuse_en_mode_par_la_variable(self):
        fait = self.lancer(EL_NON_INTERACTIVE="1")
        self.assertEqual(fait.returncode, 2)
        self.assertIn("./todo.sh install --non-interactive", fait.stdout)

    def test_menu_refuse_avec_l_option_seule(self):
        fait = self.lancer("--non-interactive")
        self.assertEqual(fait.returncode, 2)


class TestCibleMake(unittest.TestCase):
    def test_cible_make(self):
        texte = (RACINE / "conf/make.installation.Makefile").read_text(
            encoding="utf-8"
        )
        self.assertIn("install_non_interactive:", texte)
        self.assertIn("./todo.sh install --non-interactive", texte)
        self.assertIn("env -u EL_FREEZE", texte)


if __name__ == "__main__":
    unittest.main()
