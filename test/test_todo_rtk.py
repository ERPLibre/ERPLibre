#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu RTK : dit-il ce qui s'est réellement passé ?

Deux modes de défaillance se ressemblent à l'écran et n'ont pas le même
remède. Le binaire peut être absent — l'installation a échoué. Il peut aussi
être posé sur le disque sans que le PATH du processus y mène : un processus
garde le PATH qu'il avait au démarrage, donc une installation faite pendant
que TODO tourne lui reste invisible jusqu'au redémarrage. Lancer « rtk » nu
rend alors 127, que rien ne distingue d'une absence.

Ce test vérifie que les deux cas sont annoncés séparément, et que les
commandes passent par le chemin absolu du binaire plutôt que par le PATH.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from script.todo.todo import TODO

FALLBACK = os.path.expanduser("~/.local/bin/rtk")
PATH_HINT = 'export PATH="$HOME/.local/bin:$PATH"'


class TestLeTemoinDuCrochetGlobal(unittest.TestCase):
    """Le témoin lisait le mauvais fichier.

    Il regardait « ~/.config/rtk/config.toml », qui est la configuration de
    rtk LUI-MÊME : elle apparaît dès qu'il tourne une fois. L'écran
    annonçait donc « actif » à qui n'avait jamais lancé
    « rtk init --global », et lui conseillait de ne rien faire.

    L'outil le dit dans son aide : « --global » ajoute au répertoire de
    configuration de l'ASSISTANT. C'est là que le crochet vit.
    """

    def ecrire(self, contenu):
        dossier = tempfile.mkdtemp()
        chemin = os.path.join(dossier, "settings.json")
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write(contenu)
        return chemin

    def test_the_hook_in_the_assistant_settings_reads_as_active(self):
        chemin = self.ecrire(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {"hooks": [{"command": "rtk hook claude"}]}
                        ]
                    }
                }
            )
        )
        self.assertTrue(TODO.rtk_global_hook_active(chemin))

    def test_settings_without_the_hook_read_as_inactive(self):
        chemin = self.ecrire(json.dumps({"hooks": {"PreToolUse": []}}))
        self.assertFalse(TODO.rtk_global_hook_active(chemin))

    def test_a_setting_that_merely_names_rtk_is_not_the_hook(self):
        """C'EST LE PIÈGE que le témoin précédent posait autrement :
        répondre oui à la simple présence du mot. Un chemin, un
        commentaire ou une variable le nomment sans l'appeler."""
        chemin = self.ecrire(
            json.dumps(
                {
                    "env": {"PATH": "/opt/rtk/bin:/usr/bin"},
                    "note": "installer rtk un jour",
                    # LE CAS QUI TRANCHE : la commande y est en toutes
                    # lettres, et pourtant elle n'est pas lancée. Sans un
                    # tel cas, chercher « rtk hook » n'importe où dans la
                    # chaîne passe l'épreuve sans tenir le contrat.
                    "statusLine": {
                        "command": "echo 'lancer rtk hook claude un jour'"
                    },
                    "doc": "ne PAS mettre rtk hook claude ici",
                }
            )
        )
        self.assertFalse(TODO.rtk_global_hook_active(chemin))

    def test_an_absent_or_broken_file_reads_as_inactive(self):
        """Un fichier illisible n'est pas un crochet posé : promettre
        l'inverse ferait croire l'écriture faite."""
        self.assertFalse(TODO.rtk_global_hook_active("/inexistant.json"))
        self.assertFalse(
            TODO.rtk_global_hook_active(self.ecrire("{ pas du json"))
        )

    def test_it_no_longer_looks_at_the_rtk_own_config(self):
        """Ce fichier existe dès le premier lancement de l'outil.

        Le contrôle porte sur le CODE et non sur la prose : le docstring
        nomme ce fichier pour dire qu'il ne s'en sert pas, et une
        recherche sur le texte entier ne distingue pas affirmer de citer.
        """
        import ast
        import inspect
        import textwrap

        arbre = ast.parse(
            textwrap.dedent(inspect.getsource(TODO.rtk_global_hook_active))
        )
        fonction = arbre.body[0]
        if ast.get_docstring(fonction):
            fonction.body = fonction.body[1:]
        code = ast.unparse(fonction)
        self.assertNotIn(".config/rtk", code)
        self.assertIn("settings.json", TODO.RTK_HOOK_SETTINGS)


class TestRtkLocate(unittest.TestCase):
    """rtk_locate distingue « dans le PATH », « posé ailleurs » et « absent »."""

    def test_found_in_path(self):
        with patch(
            "script.todo.todo.shutil.which", return_value="/usr/bin/rtk"
        ):
            self.assertEqual(TODO().rtk_locate(), ("/usr/bin/rtk", True))

    def test_found_outside_path(self):
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=True
        ):
            self.assertEqual(TODO().rtk_locate(), (FALLBACK, False))

    def test_absent(self):
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=False
        ):
            self.assertEqual(TODO().rtk_locate(), (None, False))


class TestRtkExec(unittest.TestCase):
    """rtk_exec appelle le binaire par son chemin absolu, jamais « rtk » nu."""

    def test_uses_absolute_path(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = 0
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=True
        ):
            todo.rtk_exec("gain")
        command = todo.execute.exec_command_live.call_args[0][0]
        self.assertTrue(command.startswith(FALLBACK), command)
        self.assertTrue(command.endswith(" gain"), command)

    def test_absent_runs_nothing(self):
        todo = TODO()
        todo.execute = MagicMock()
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=False
        ):
            with redirect_stdout(io.StringIO()):
                status = todo.rtk_exec("gain")
        self.assertEqual(status, 1)
        todo.execute.exec_command_live.assert_not_called()


class TestRtkReportInstall(unittest.TestCase):
    """Le compte rendu d'installation nomme le résultat, sans le supposer."""

    def report(self, todo, exit_code):
        out = io.StringIO()
        with redirect_stdout(out):
            todo.rtk_report_install(exit_code)
        return out.getvalue()

    def test_failure_is_not_announced_as_success(self):
        todo = TODO()
        todo.execute = MagicMock()
        output = self.report(todo, 1)
        self.assertIn("❌", output)
        self.assertNotIn("✅", output)
        todo.execute.exec_command_live.assert_not_called()

    def test_success_reports_version_and_path(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["rtk 0.47.0"])
        with patch(
            "script.todo.todo.shutil.which", return_value="/usr/bin/rtk"
        ):
            output = self.report(todo, 0)
        self.assertIn("✅", output)
        self.assertIn("rtk 0.47.0", output)
        self.assertIn("/usr/bin/rtk", output)
        self.assertNotIn(PATH_HINT, output)

    def test_success_outside_path_tells_how_to_reach_it(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["rtk 0.47.0"])
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=True
        ):
            output = self.report(todo, 0)
        self.assertIn("✅", output)
        self.assertIn(PATH_HINT, output)

    def test_success_without_binary_is_not_a_success(self):
        todo = TODO()
        todo.execute = MagicMock()
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=False
        ):
            output = self.report(todo, 0)
        self.assertIn("❌", output)
        self.assertNotIn("✅", output)


if __name__ == "__main__":
    unittest.main()
