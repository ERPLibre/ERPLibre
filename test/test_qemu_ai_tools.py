#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les outils d'assistance posés dans une VM au déploiement.

rtk, starship et UN agent — Claude Code ou opencode. Aucun n'est dans les
dépôts des distributions supportées : ce sont quatre installateurs amont,
donc quatre curl vers l'extérieur, lancés sur un SSH sans terminal.

Ce que ces tests gardent :

- une seule autorité pour les URL amont : l'hôte et la VM posent les mêmes
  outils, et deux copies dérivent dès que l'amont en change une ;
- aucune pose ne peut PENDRE : « || true » couvre l'échec, pas l'attente
  d'une réponse que personne ne donnera ;
- les lignes ajoutées au ~/.bashrc le sont UNE fois, sinon chaque
  redéploiement d'une même VM le rallonge ;
- l'identité git saisie prime sur celle de l'hôte, champ par champ.
"""

import importlib.util
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo import dev_tools  # noqa: E402
from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    chemin = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


class UneSeuleAutorite(unittest.TestCase):
    """Les mêmes outils se posent sur l'hôte et dans une VM."""

    def test_the_host_reads_the_shared_table(self):
        """Deux copies d'une URL dérivent dès que l'amont en change une, et
        la seconde est celle qu'on oublie."""
        self.assertIs(TODO._UPSTREAM_TOOLS, dev_tools.AGENTS)
        self.assertIs(TODO._STARSHIP_LINE, dev_tools.STARSHIP_LINE)
        self.assertEqual(TODO._STARSHIP_UPSTREAM, dev_tools.STARSHIP_UPSTREAM)

    def test_both_agents_are_offered(self):
        self.assertEqual(["claude", "opencode"], sorted(dev_tools.AGENTS))

    def test_the_default_agent_is_one_of_them(self):
        """Le premier de la table ferait dépendre le défaut de l'ordre
        d'écriture d'un dictionnaire."""
        self.assertIn(dev_tools.AGENT_DEFAUT, dev_tools.AGENTS)


class LeCatalogue(unittest.TestCase):
    def test_the_tool_exists_and_needs_no_desktop(self):
        """On s'en sert en SSH : une VM serveur le prend aussi."""
        spec = TODO._QEMU_VM_TOOLS["aidev"]
        self.assertFalse(spec["needs_desktop"])
        self.assertEqual((), spec["arches"])
        self.assertEqual((), spec["families"])

    def test_it_is_posed_before_the_clone(self):
        """« before » est la phase où chaque outil se garde lui-même. En
        « after », un curl sans réponse rendrait la VM rouge."""
        self.assertEqual("before", TODO._QEMU_VM_TOOLS["aidev"]["phase"])


class LaCommandeDistante(unittest.TestCase):
    def _cmd(self, agent=""):
        return TODO.__new__(TODO)._qemu_aidev_remote_cmd(agent)

    def test_it_poses_the_three_tools(self):
        cmd = self._cmd("claude")
        self.assertIn("rtk", cmd)
        self.assertIn("starship", cmd)
        self.assertIn("claude.ai", cmd)

    def test_the_chosen_agent_is_the_one_posed(self):
        """Un seul agent, celui qu'on a demandé : poser les deux
        installerait un outil que personne n'a coché."""
        claude = self._cmd("claude")
        opencode = self._cmd("opencode")
        self.assertIn("claude.ai", claude)
        self.assertNotIn("opencode.ai", claude)
        self.assertIn("opencode.ai", opencode)
        self.assertNotIn("claude.ai", opencode)

    def test_an_unknown_agent_falls_back(self):
        """Une valeur inattendue ne doit pas faire tomber un déploiement."""
        self.assertIn("claude.ai", self._cmd("gemini"))
        self.assertIn("claude.ai", self._cmd(""))

    def test_no_pose_can_hang(self):
        """« || true » couvre l'ÉCHEC, pas l'ATTENTE. Un installateur qui
        pose une question resterait pendu sur un SSH sans terminal, et le
        déploiement avec lui."""
        cmd = self._cmd("claude")
        self.assertEqual(3, cmd.count("</dev/null"))
        self.assertEqual(3, cmd.count("timeout "))
        self.assertEqual(3, cmd.count("|| true"))

    def test_starship_is_told_not_to_ask(self):
        """Sans « -y », son installateur attend une confirmation."""
        self.assertIn("-s -- -y", self._cmd("claude"))

    def test_the_rc_lines_are_written_once(self):
        """Sans le « grep » qui précède, chaque redéploiement d'une même VM
        rallonge son ~/.bashrc d'une ligne identique."""
        cmd = self._cmd("claude")
        self.assertEqual(2, cmd.count("grep -qF"))
        for morceau in cmd.split(";"):
            if ">> ~/.bashrc" in morceau:
                self.assertIn("||", morceau)

    def test_the_path_uses_home_not_a_tilde(self):
        """Entre guillemets, le tilde n'est pas étendu : le PATH porterait
        un répertoire nommé « ~ », qui n'existe pas."""
        cmd = self._cmd("opencode")
        self.assertIn('export PATH="$HOME/.opencode/bin:$PATH"', cmd)
        self.assertNotIn('PATH="~/', cmd)

    def test_it_is_valid_shell(self):
        """Une commande mal citée casse tout le bloc des outils, pas
        seulement le sien."""
        for agent in ("claude", "opencode", ""):
            with self.subTest(agent=agent):
                fini = subprocess.run(
                    ["bash", "-n"],
                    input=self._cmd(agent),
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)

    def test_nothing_is_posed_without_the_box(self):
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_erplibre_remote_cmd("develop", tools=())
        self.assertNotIn("starship", cmd)

    def test_the_agent_reaches_the_remote_command(self):
        """L'épreuve du bout en bout : le choix doit traverser toute la
        chaîne, sans quoi il reste un réglage sans effet."""
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_erplibre_remote_cmd(
            "develop", tools=("aidev",), ai_agent="opencode"
        )
        self.assertIn("opencode.ai", cmd)


class LIdentiteGit(unittest.TestCase):
    """Le formulaire montre l'identité de l'hôte et permet de la changer."""

    def _args(self, **kw):
        argv = ["--distro", "ubuntu", "--hostname", "vm"]
        for cle, valeur in kw.items():
            argv += [f"--{cle.replace('_', '-')}", valeur]
        return DQ.build_parser().parse_args(argv)

    def _identite(self, cc):
        lu = {}
        for ligne in cc.split("\n"):
            for champ in ("name", "email"):
                if ligne.strip().startswith(f"{champ} = "):
                    lu[champ] = ligne.split(" = ", 1)[1]
        return lu

    def test_what_was_typed_wins(self):
        cc = DQ.build_cloud_config(
            self._args(
                git_name="Une Personne", git_email="qui@exemple.invalid"
            ),
            None,
            [],
        )
        self.assertEqual(
            {"name": "Une Personne", "email": "qui@exemple.invalid"},
            self._identite(cc),
        )

    def test_each_field_stands_alone(self):
        """Remplir le seul courriel ne doit pas effacer le nom : les deux
        retombent sur l'hôte SÉPARÉMENT."""
        cc = DQ.build_cloud_config(
            self._args(git_email="qui@exemple.invalid"), None, []
        )
        lu = self._identite(cc)
        self.assertEqual("qui@exemple.invalid", lu.get("email"))
        self.assertNotEqual("", lu.get("name", ""))

    def test_the_option_reaches_the_command(self):
        """Le réglage doit atteindre deploy_qemu, sinon il n'existe pas."""
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_build_deploy_parts(
            "ubuntu",
            "24.04",
            "amd64",
            "vm",
            2048,
            2,
            "20G",
            "",
            "",
            True,
            git_name="Une Personne",
            git_email="qui@exemple.invalid",
        )
        self.assertIn("--git-name", cmd)
        self.assertIn("Une Personne", cmd)
        self.assertIn("--git-email", cmd)

    def test_an_empty_identity_says_nothing(self):
        """Vide, deploy_qemu recopie l'hôte : ajouter l'option avec une
        valeur vide écraserait cette identité par du rien."""
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_build_deploy_parts(
            "ubuntu", "24.04", "amd64", "vm", 2048, 2, "20G", "", "", True
        )
        self.assertNotIn("--git-name", cmd)
        self.assertNotIn("--git-email", cmd)


class LaSpec(unittest.TestCase):
    def test_the_three_settings_reach_the_spec(self):
        """Absents de l'assemblée, les réglages du formulaire n'atteignent
        jamais le déploiement — la case resterait décorative."""
        spec = build_spec(
            [],
            [],
            {
                "res_label": "x1",
                "ssh_key": "",
                "install": None,
                "add_ssh_config": False,
                "parallelism": 1,
                "ai_agent": "opencode",
                "git_name": "Une Personne",
                "git_email": "qui@exemple.invalid",
            },
        )
        self.assertEqual("opencode", spec["ai_agent"])
        self.assertEqual("Une Personne", spec["git_name"])
        self.assertEqual("qui@exemple.invalid", spec["git_email"])


if __name__ == "__main__":
    unittest.main()
