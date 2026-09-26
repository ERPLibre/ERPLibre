#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import time
import unittest
from unittest.mock import patch

from script.execute.execute import Execute, redact_secrets


class TestExecuteInit(unittest.TestCase):
    """Test Execute class initialization."""

    @patch("shutil.which")
    def test_init_with_gnome_terminal(self, mock_which):
        mock_which.side_effect = lambda x: (
            "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None
        )
        exe = Execute()
        self.assertIn("gnome-terminal", exe.cmd_source_erplibre)
        self.assertIn(".venv.erplibre", exe.cmd_source_erplibre)
        self.assertIn("gnome-terminal", exe.cmd_source_default)

    @patch("shutil.which")
    def test_init_with_osascript(self, mock_which):
        mock_which.side_effect = lambda x: (
            "/usr/bin/osascript" if x == "osascript" else None
        )
        exe = Execute()
        self.assertIn("osascript", exe.cmd_source_erplibre)

    @patch("shutil.which", return_value=None)
    def test_init_fallback_source(self, mock_which):
        exe = Execute()
        self.assertIn(".venv.erplibre/bin/activate", exe.cmd_source_erplibre)
        self.assertEqual(exe.cmd_source_default, "")


class TestExecCommandLive(unittest.TestCase):
    """Test exec_command_live method."""

    def setUp(self):
        with patch("shutil.which", return_value=None):
            self.exe = Execute()

    def test_simple_command_returns_zero(self):
        result = self.exe.exec_command_live(
            "echo hello",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(result, 0)

    def test_failing_command_returns_nonzero(self):
        result = self.exe.exec_command_live(
            "exit 42",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(result, 42)

    def test_return_status_and_output(self):
        status, output = self.exe.exec_command_live(
            "echo hello",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["hello"])

    def test_return_status_and_output_multiline(self):
        status, output = self.exe.exec_command_live(
            "echo -e 'line1\nline2\nline3'",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["line1", "line2", "line3"])

    def test_return_status_and_command(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(cmd, "echo test")

    def test_return_status_and_output_and_command(self):
        status, cmd, output = self.exe.exec_command_live(
            "echo result",
            source_erplibre=False,
            quiet=True,
            return_status_and_output_and_command=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(cmd, "echo result")
        self.assertEqual(output, ["result"])

    def test_source_erplibre_prepends_activate(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=True,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.erplibre/bin/activate", cmd)

    def test_single_source_erplibre(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            single_source_erplibre=True,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.erplibre/bin/activate", cmd)
        self.assertIn("echo test", cmd)

    def test_single_source_odoo_no_version_returns_error(self):
        with patch("os.path.exists", return_value=False):
            result = self.exe.exec_command_live(
                "echo test",
                source_erplibre=False,
                single_source_odoo=True,
                source_odoo="",
                quiet=True,
            )
        # `1`, pas `-1` : e24b185 a rendu à ce chemin la FORME que
        # l'appelant demande (un tuple s'il en attend un) et en a profité
        # pour donner un vrai code de sortie. Aucun appelant ne compare à
        # -1, qui n'est d'ailleurs pas un code de sortie valide.
        self.assertEqual(result, 1)

    def test_single_source_odoo_with_version(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            single_source_odoo=True,
            source_odoo="odoo18",
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.odoo18/bin/activate", cmd)

    def test_new_env_passed_to_subprocess(self):
        status, output = self.exe.exec_command_live(
            "echo $MY_TEST_VAR",
            source_erplibre=False,
            quiet=True,
            new_env={"MY_TEST_VAR": "test_value_123"},
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["test_value_123"])

    def test_empty_output_command(self):
        status, output = self.exe.exec_command_live(
            "true",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, [])


class TestRedactSecrets(unittest.TestCase):
    """Ce qui doit disparaître d'une commande affichée, et ce qui doit rester.

    Le caviardage est le DERNIER rempart et non le premier : un secret sur
    argv est déjà lisible par tout compte de la machine dans
    /proc/<pid>/cmdline, où aucun filtre n'atteint. Ces tests défendent donc
    la trace — terminal, journal, sortie CI — et rien d'autre.

    Trois familles portent un secret, et elles ne se ressemblent pas. Une
    option se reconnaît par son nom, une variable d'environnement par le
    sien, et un jeton d'en-tête n'a NI l'un NI l'autre : il suit le mot
    « Bearer ». Un filtre bâti sur les deux premières laisse passer la
    troisième, qui est exactement celle qu'une API de modèle emploie.

    Les valeurs sont inventées, comme l'exige la règle du dépôt pour tout
    exemple qui illustre un interdit.
    """

    def test_env_api_key_is_redacted(self):
        sortie = redact_secrets("OPENAI_API_KEY=sk-inventeXYZ python x.py")
        self.assertNotIn("sk-inventeXYZ", sortie)
        self.assertIn("OPENAI_API_KEY='***'", sortie)

    def test_env_apikey_without_separator(self):
        sortie = redact_secrets("MISTRAL_APIKEY=abc123 ./run")
        self.assertNotIn("abc123", sortie)

    def test_bearer_header_is_redacted(self):
        sortie = redact_secrets(
            "curl -H 'Authorization: Bearer sk-inventeABC' http://h/v1/models"
        )
        self.assertNotIn("sk-inventeABC", sortie)
        self.assertIn("Authorization: Bearer '***'", sortie)

    def test_basic_header_is_redacted(self):
        sortie = redact_secrets("Authorization: Basic dXNlcjpmYXV4")
        self.assertNotIn("dXNlcjpmYXV4", sortie)

    def test_header_case_is_ignored(self):
        sortie = redact_secrets("authorization: bearer sk-inventeDEF")
        self.assertNotIn("sk-inventeDEF", sortie)

    def test_option_password_still_redacted(self):
        sortie = redact_secrets("odoo --db_password 'inventeGHI'")
        self.assertNotIn("inventeGHI", sortie)

    def test_option_name_survives(self):
        """Le nom de l'option reste : la commande doit rester reproductible."""
        sortie = redact_secrets("odoo --db_password 'inventeJKL'")
        self.assertIn("--db_password", sortie)

    def test_a_path_is_not_a_secret(self):
        """Rien ne disparaît d'une commande qui ne porte aucun secret."""
        commande = "make test_unit_file F=test/test_execute.py"
        self.assertEqual(redact_secrets(commande), commande)

    def test_empty_text_survives(self):
        self.assertEqual(redact_secrets(""), "")
        self.assertIsNone(redact_secrets(None))


class TestRedactUrlCredentials(unittest.TestCase):
    """Identifiants portés par une URL (userinfo, RFC 3986 §3.2.1).

    Ni nom d'option ni nom de variable : le secret suit « user: » ou tient
    lieu de nom d'utilisateur. Schéma, hôte, chemin et nom d'utilisateur
    ordinaire restent, pour que la commande reste lisible. Valeurs inventées.
    """

    def test_password_in_userinfo_is_masked(self):
        sortie = redact_secrets(
            "psql postgresql://odoo:inventeMNO@db.example/base"
        )
        self.assertNotIn("inventeMNO", sortie)
        self.assertIn("postgresql://odoo:***@db.example/base", sortie)

    def test_token_as_password_is_masked(self):
        sortie = redact_secrets(
            "git clone https://x-access-token:inventePQR@forge.example/o/r.git"
        )
        self.assertNotIn("inventePQR", sortie)
        self.assertIn("https://x-access-token:***@forge.example", sortie)

    def test_prefixed_token_as_user_is_masked(self):
        sortie = redact_secrets(
            "git clone https://ghp_inventeSTU@forge.example/o/r.git"
        )
        self.assertNotIn("ghp_inventeSTU", sortie)
        self.assertIn("https://***@forge.example/o/r.git", sortie)

    def test_long_opaque_user_is_masked(self):
        jeton = "invente" + "x" * 30
        sortie = redact_secrets(f"curl https://{jeton}@forge.example/api")
        self.assertNotIn(jeton, sortie)

    def test_token_followed_by_a_password_is_masked(self):
        """Forme GitHub : le jeton tient lieu de nom d'utilisateur ET porte
        un mot de passe (« x-oauth-basic »). La règle du mot de passe masque
        d'abord ce second segment ; celle du jeton doit encore reconnaître
        l'@ à travers le « :*** » qui reste, sans quoi le jeton passe seul en
        clair."""
        jeton = "invente" + "T" * 33
        sortie = redact_secrets(
            f"git clone https://{jeton}:x-oauth-basic@forge.example/o/r.git"
        )
        self.assertNotIn(jeton, sortie)
        self.assertNotIn("x-oauth-basic", sortie)
        self.assertIn("https://***:***@forge.example/o/r.git", sortie)

    def test_password_with_unencoded_at_sign_is_masked_in_full(self):
        """Un « @ » non encodé dans le mot de passe (RFC 3986 l'interdit,
        ça arrive) ne doit pas fuir sa moitié : le masquage s'étend, glouton,
        jusqu'au DERNIER @ avant l'hôte."""
        sortie = redact_secrets(
            "psql postgresql://odoo:inventeP@ss@db.example/base"
        )
        self.assertNotIn("inventeP@ss", sortie)
        self.assertIn("postgresql://odoo:***@db.example/base", sortie)

    def test_ordinary_user_survives(self):
        for commande in (
            "git clone ssh://git@forge.example/o/r.git",
            "curl https://alice@forge.example/x",
        ):
            self.assertEqual(redact_secrets(commande), commande)

    def test_port_and_path_colon_survive(self):
        for commande in (
            "curl http://localhost:8069/web/login",
            "curl https://forge.example/a:b@c",
        ):
            self.assertEqual(redact_secrets(commande), commande)

    def test_url_in_the_middle_of_a_printed_line_is_masked(self):
        ligne = "Cloning from https://u:inventeVWX@forge.example/o/r.git\n"
        self.assertNotIn("inventeVWX", redact_secrets(ligne))

    def test_long_line_without_a_scheme_is_fast(self):
        """Le schéma des deux motifs est borné (32 caractères) : une ligne
        sans « :// » ne doit jamais coûter un temps proportionnel au CARRÉ de
        sa longueur (chaque motif balayait auparavant tout le préfixe
        `[a-z0-9+.-]*` avant d'abandonner à chaque position)."""
        ligne = "a." * 10000
        debut = time.monotonic()
        redact_secrets(ligne)
        self.assertLess(time.monotonic() - debut, 1.0)


if __name__ == "__main__":
    unittest.main()
