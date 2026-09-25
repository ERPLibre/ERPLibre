#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'entrée « mandataire inverse » du menu Network de TODO."""

import os
import tempfile
import unittest
from unittest.mock import patch

from script.todo.todo import TODO


class TestMenuNetwork(unittest.TestCase):
    def test_l_option_4_lance_le_mandataire(self):
        """Les choix du menu et ses branches sont tenus à la main : [4] doit
        afficher le mandataire ET appeler sa méthode."""
        todo = TODO()
        with (
            patch.object(TODO, "network_reverse_proxy") as mock_rp,
            patch("click.prompt", side_effect=["4", "0"]) as mock_prompt,
            patch("script.todo.todo_telemetry.record"),
        ):
            todo.prompt_execute_network()
        mock_rp.assert_called_once_with()
        self.assertIn("[4]", mock_prompt.call_args_list[0].args[0])


class TestLancement(unittest.TestCase):
    def config(self, contenu):
        f = tempfile.NamedTemporaryFile(
            "w", suffix=".conf", delete=False, encoding="utf-8"
        )
        f.write(contenu)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def lancer(self, reponse, contenu):
        todo = TODO()
        with (
            patch("builtins.input", return_value=reponse),
            patch.object(todo.execute, "exec_command_live") as mock_exec,
            patch("builtins.print") as mock_print,
        ):
            todo.network_reverse_proxy(config_path=self.config(contenu))
        imprime = " ".join(
            str(a) for c in mock_print.call_args_list for a in c.args
        )
        return mock_exec.call_args.args[0], imprime

    def test_local_par_defaut_avec_les_ports_du_config(self):
        cmd, _ = self.lancer(
            "",
            "[options]\nhttp_port = 9069\ngevent_port = 9072\n"
            "proxy_mode = True\nworkers = 2\n",
        )
        self.assertIn("./script/reverse_proxy/main.py", cmd)
        self.assertIn("--listen 127.0.0.1", cmd)
        self.assertIn("--web-port 9069", cmd)
        self.assertIn("--websocket-port 9072", cmd)

    def test_reseau_ecoute_sur_toutes_les_interfaces(self):
        cmd, _ = self.lancer(
            "2", "[options]\nproxy_mode = True\nworkers = 2\n"
        )
        self.assertIn("--listen 0.0.0.0", cmd)

    def test_les_reglages_manquants_sont_signales(self):
        # Sans proxy_mode Odoo ignore X-Forwarded-*, sans workers le bus
        # (8072) n'existe pas : le mandataire n'y changerait rien.
        _, imprime = self.lancer("1", "[options]\nworkers = 0\n")
        self.assertIn("proxy_mode", imprime)
        self.assertIn("workers", imprime)

    def test_rien_n_est_signale_quand_tout_est_regle(self):
        _, imprime = self.lancer(
            "1", "[options]\nproxy_mode = True\nworkers = 2\n"
        )
        self.assertNotIn("proxy_mode", imprime)


if __name__ == "__main__":
    unittest.main()
