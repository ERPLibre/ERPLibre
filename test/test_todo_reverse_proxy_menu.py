#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'entrée « mandataire inverse » du menu Network de TODO."""

import os
import shutil
import subprocess
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


class TestMenuCertificats(unittest.TestCase):
    def test_l_option_5_genere_les_certificats(self):
        todo = TODO()
        with (
            patch.object(TODO, "network_local_certificates") as mock_cert,
            patch("click.prompt", side_effect=["5", "0"]) as mock_prompt,
            patch("script.todo.todo_telemetry.record"),
        ):
            todo.prompt_execute_network()
        mock_cert.assert_called_once_with()
        self.assertIn("[5]", mock_prompt.call_args_list[0].args[0])

    @unittest.skipUnless(shutil.which("openssl"), "openssl absent")
    def test_les_noms_saisis_s_ajoutent_aux_noms_par_defaut(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        dossier = os.path.join(d, "tls")
        with (
            patch("builtins.input", return_value="odoo.test, 10.0.0.9"),
            patch("builtins.print"),
        ):
            TODO().network_local_certificates(cert_dir=dossier)
        texte = subprocess.run(
            [
                "openssl",
                "x509",
                "-in",
                os.path.join(dossier, "server.crt"),
                "-noout",
                "-text",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for attendu in (
            "DNS:odoo.test",
            "IP Address:10.0.0.9",
            "DNS:localhost",
        ):
            self.assertIn(attendu, texte)


class TestLancement(unittest.TestCase):
    def config(self, contenu):
        f = tempfile.NamedTemporaryFile(
            "w", suffix=".conf", delete=False, encoding="utf-8"
        )
        f.write(contenu)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def lancer(self, reponse, contenu, protocole="1", cert_dir=None):
        todo = TODO()
        with (
            patch("builtins.input", side_effect=[reponse, protocole]),
            patch.object(todo.execute, "exec_command_live") as mock_exec,
            patch("builtins.print") as mock_print,
        ):
            todo.network_reverse_proxy(
                config_path=self.config(contenu),
                cert_dir=cert_dir or self.dossier_vide(),
            )
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

    def dossier_vide(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        return os.path.join(d, "tls")

    def test_http_par_defaut_sans_certificat(self):
        cmd, _ = self.lancer("", "[options]\nproxy_mode = True\nworkers = 2\n")
        self.assertNotIn("--tls-cert", cmd)

    @unittest.skipUnless(shutil.which("openssl"), "openssl absent")
    def test_https_genere_le_certificat_manquant_et_le_passe(self):
        dossier = self.dossier_vide()
        cmd, imprime = self.lancer(
            "",
            "[options]\nproxy_mode = True\nworkers = 2\n",
            protocole="2",
            cert_dir=dossier,
        )
        self.assertIn(f"--tls-cert {dossier}/server.crt", cmd)
        self.assertIn(f"--tls-key {dossier}/server.key", cmd)
        self.assertTrue(os.path.isfile(os.path.join(dossier, "ca.crt")))
        self.assertIn("ca.crt", imprime)

    def test_https_reprend_le_certificat_existant(self):
        dossier = self.dossier_vide()
        with patch(
            "script.reverse_proxy.local_cert.exists", return_value=True
        ), patch("script.reverse_proxy.local_cert.issue") as mock_issue:
            cmd, _ = self.lancer(
                "",
                "[options]\nproxy_mode = True\nworkers = 2\n",
                protocole="2",
                cert_dir=dossier,
            )
        mock_issue.assert_not_called()
        self.assertIn("--tls-cert", cmd)

    def test_rien_n_est_signale_quand_tout_est_regle(self):
        _, imprime = self.lancer(
            "1", "[options]\nproxy_mode = True\nworkers = 2\n"
        )
        self.assertNotIn("proxy_mode", imprime)


if __name__ == "__main__":
    unittest.main()
