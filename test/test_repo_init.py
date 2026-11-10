#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""repo init lancé sans question, par script/manifest/repo_init.sh.

Sur un terminal, « repo init » demande la couleur tant que la config git de
l'utilisateur ne porte aucune clé color.ui, color.diff ou color.status, et
l'identité tant que ni le projet de manifeste ni cette config ne portent
user.name et user.email. Ces tests gardent :

- repo_color_default écrit color.ui = auto, la valeur de la réponse « y »,
  dans le fichier que lit repo : la config XDG quand elle existe,
  ~/.gitconfig sinon ; un choix déjà présent, même inclus, reste intact ;
- repo_identity_ready suit le test de repo, clé par clé entre les deux
  fichiers, et repo_identity_set écrit l'identité dans le fichier lu,
  jamais à moitié ;
- repo_init lance repo init l'entrée sur /dev/null quand l'identité manque,
  sur l'entrée héritée sinon ou quand --config-name la demande ;
- chaque script de script/manifest/ passe par repo_init.

Chaque test tourne dans un dossier temporaire qui sert de HOME et de racine :
la config de qui lance les tests n'est jamais lue ni écrite, et
.venv.erplibre/bin/repo y est un faux qui note son entrée standard.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
FRAGMENT = RACINE / "script/manifest/repo_init.sh"
SCRIPTS = sorted((RACINE / "script/manifest").glob("update_manifest_*.sh"))


class Banc(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"
        }
        self.env["HOME"] = str(self.home)
        self.gitconfig = self.home / ".gitconfig"
        self.xdg = self.home / ".config/git/config"
        self.manifeste = self.home / ".repo/manifests.git/config"

    def tearDown(self):
        self._tmp.cleanup()

    def _bash(self, code, *args, stdin=None):
        """(code de retour, stdout) de `code` après le fragment, lancé dans
        le dossier temporaire avec `args` en paramètres positionnels."""
        done = subprocess.run(
            ["bash", "-c", f'. "{FRAGMENT}" && {code}', "test", *args],
            cwd=self.home,
            env=self.env,
            stdin=stdin,
            capture_output=True,
            text=True,
        )
        return done.returncode, done.stdout

    def _lire(self, fichier, cle):
        done = subprocess.run(
            ["git", "config", "--file", str(fichier), "--get", cle],
            env=self.env,
            capture_output=True,
            text=True,
        )
        return done.stdout.strip() if done.returncode == 0 else None


class TestCouleur(Banc):
    def _lancer(self):
        self.assertEqual(self._bash("repo_color_default")[0], 0)

    def test_config_absente_cree_gitconfig(self):
        self._lancer()
        self.assertEqual(self._lire(self.gitconfig, "color.ui"), "auto")

    def test_choix_existant_respecte(self):
        self.gitconfig.write_text("[color]\n\tui = never\n")
        self._lancer()
        self.assertEqual(self._lire(self.gitconfig, "color.ui"), "never")

    def test_color_diff_suffit(self):
        self.gitconfig.write_text("[color]\n\tdiff = false\n")
        self._lancer()
        self.assertIsNone(self._lire(self.gitconfig, "color.ui"))

    def test_config_xdg_prioritaire(self):
        self.xdg.parent.mkdir(parents=True)
        self.xdg.write_text("[user]\n\tname = Test\n")
        self.gitconfig.write_text("[core]\n\tpager = less\n")
        self._lancer()
        self.assertEqual(self._lire(self.xdg, "color.ui"), "auto")
        self.assertIsNone(self._lire(self.gitconfig, "color.ui"))

    def test_xdg_config_home_respecte(self):
        ailleurs = self.home / "ailleurs"
        (ailleurs / "git").mkdir(parents=True)
        (ailleurs / "git/config").write_text("")
        self.env["XDG_CONFIG_HOME"] = str(ailleurs)
        self._lancer()
        self.assertEqual(
            self._lire(ailleurs / "git/config", "color.ui"), "auto"
        )
        self.assertFalse(self.gitconfig.exists())

    def test_xdg_config_home_vide_comme_repo(self):
        """Vide, il donne à repo le chemin relatif git/config, absent ici :
        repo lit ~/.gitconfig même si ~/.config/git/config existe."""
        self.xdg.parent.mkdir(parents=True)
        self.xdg.write_text("")
        self.env["XDG_CONFIG_HOME"] = ""
        self._lancer()
        self.assertEqual(self._lire(self.gitconfig, "color.ui"), "auto")
        self.assertIsNone(self._lire(self.xdg, "color.ui"))

    def test_inclusion_suivie(self):
        inclus = self.home / "inclus.conf"
        inclus.write_text("[color]\n\tstatus = false\n")
        self.gitconfig.write_text(f"[include]\n\tpath = {inclus}\n")
        self._lancer()
        self.assertIsNone(self._lire(self.gitconfig, "color.ui"))


class TestIdentite(Banc):
    IDENTITE = "[user]\n\tname = Fictif\n\temail = fictif@example.invalid\n"

    def _prete(self):
        return self._bash("repo_identity_ready")[0] == 0

    def test_aucune_config(self):
        self.assertFalse(self._prete())

    def test_config_utilisateur_complete(self):
        self.gitconfig.write_text(self.IDENTITE)
        self.assertTrue(self._prete())

    def test_nom_seul_ne_suffit_pas(self):
        self.gitconfig.write_text("[user]\n\tname = Fictif\n")
        self.assertFalse(self._prete())

    def test_projet_de_manifeste_suffit(self):
        self.manifeste.parent.mkdir(parents=True)
        self.manifeste.write_text(self.IDENTITE)
        self.assertTrue(self._prete())

    def test_cles_reparties_entre_les_deux_fichiers(self):
        self.manifeste.parent.mkdir(parents=True)
        self.manifeste.write_text("[user]\n\tname = Fictif\n")
        self.gitconfig.write_text("[user]\n\temail = fictif@example.invalid\n")
        self.assertTrue(self._prete())

    def test_config_xdg_lue(self):
        self.xdg.parent.mkdir(parents=True)
        self.xdg.write_text(self.IDENTITE)
        self.assertTrue(self._prete())

    def test_ecriture_puis_lecture(self):
        code, _ = self._bash(
            'repo_identity_set "$1" "$2"',
            "Nom Fictif",
            "fictif@example.invalid",
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._lire(self.gitconfig, "user.name"), "Nom Fictif")
        self.assertEqual(
            self._lire(self.gitconfig, "user.email"), "fictif@example.invalid"
        )
        self.assertTrue(self._prete())

    def test_ecriture_refuse_une_valeur_vide(self):
        code, _ = self._bash('repo_identity_set "$1" "$2"', "Nom Fictif", "")
        self.assertEqual(code, 1)
        self.assertFalse(self.gitconfig.exists())


@unittest.skipUnless(sys.platform.startswith("linux"), "lit /proc/self/fd/0")
class TestRepoInit(Banc):
    """Le faux repo note la cible de son entrée standard et ses arguments."""

    def setUp(self):
        super().setUp()
        faux = self.home / ".venv.erplibre/bin/repo"
        faux.parent.mkdir(parents=True)
        faux.write_text(
            "#!/bin/sh\n"
            'readlink /proc/self/fd/0 > "$HOME/entree"\n'
            'printf "%s\\n" "$@" > "$HOME/args"\n'
        )
        faux.chmod(0o755)

    def _lancer(self, *options):
        with subprocess.Popen(["sleep", "5"], stdout=subprocess.PIPE) as p:
            code, sortie = self._bash(
                'repo_init -u "$@"', "url fictive", *options, stdin=p.stdout
            )
            p.kill()
        self.assertEqual(code, 0)
        args = (self.home / "args").read_text().splitlines()
        self.assertEqual(args, ["init", "-u", "url fictive", *options])
        return (self.home / "entree").read_text().strip(), sortie

    def test_sans_identite_entree_sur_dev_null(self):
        entree, sortie = self._lancer()
        self.assertEqual(entree, "/dev/null")
        self.assertIn("aucune identité git", sortie)
        self.assertEqual(self._lire(self.gitconfig, "color.ui"), "auto")

    def test_config_name_garde_l_entree(self):
        entree, sortie = self._lancer("-b", "main", "--config-name")
        self.assertTrue(entree.startswith("pipe:"), entree)
        self.assertEqual(sortie, "")

    def test_avec_identite_entree_heritee(self):
        self.gitconfig.write_text(TestIdentite.IDENTITE)
        entree, sortie = self._lancer()
        self.assertTrue(entree.startswith("pipe:"), entree)
        self.assertEqual(sortie, "")


class TestScriptsDeManifeste(unittest.TestCase):
    def test_repo_init_passe_par_le_fragment(self):
        self.assertEqual(len(SCRIPTS), 6, [s.name for s in SCRIPTS])
        for script in SCRIPTS:
            texte = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                self.assertIsNone(
                    re.search(r"^[^#\n]*bin/repo init", texte, re.M)
                )
                appel = re.search(r"^[ \t]*repo_init ", texte, re.M)
                source = texte.find(". ./script/manifest/repo_init.sh")
                self.assertTrue(appel and source >= 0)
                self.assertLess(source, appel.start())


if __name__ == "__main__":
    unittest.main()
