#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
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


class TestRedactSecretsFormes(unittest.TestCase):
    """Les formes de secret qui ne portent pas « password » dans un nom
    d'option ou de variable : une ligne de configuration, une URL, un jeton
    reconnaissable à son préfixe, une option courte propre à un outil, du
    JSON, une clé privée. Chaque cas vérifie que la valeur part ET que ce
    qui la précède reste lisible. Valeurs inventées.
    """

    def masque(self, texte, secret, reste):
        sortie = redact_secrets(texte)
        self.assertNotIn(secret, sortie)
        self.assertIn(reste, sortie)
        return sortie

    def test_ligne_de_configuration_odoo(self):
        self.masque(
            "admin_passwd = invente-adm1", "invente-adm1", "admin_passwd = "
        )
        self.masque(
            "db_password = invente-db2", "invente-db2", "db_password = "
        )

    def test_ligne_yaml(self):
        self.masque("  api_key: invente-yaml3", "invente-yaml3", "api_key: ")

    def test_variable_en_minuscules(self):
        self.masque(
            "export pgpassword=invente-pg4", "invente-pg4", "pgpassword="
        )

    def test_la_commande_apres_la_variable_reste(self):
        """« PGPASSWORD=x psql » : la règle de configuration ne doit pas
        avaler la commande qui suit la valeur."""
        self.masque(
            "PGPASSWORD=invente-pg5 psql -d essai",
            "invente-pg5",
            "psql -d essai",
        )

    def test_identifiants_dans_une_url(self):
        sortie = self.masque(
            "postgresql://odoo:invente-url6@db:5432/essai",
            "invente-url6",
            "postgresql://odoo:",
        )
        self.assertIn("@db:5432/essai", sortie)

    def test_jeton_github_seul_dans_une_url(self):
        jeton = "ghp_" + "A" * 36
        self.masque(
            f"origin  https://{jeton}@github.com/essai/depot.git (fetch)",
            jeton,
            "@github.com/essai/depot.git",
        )

    def test_jeton_gitlab(self):
        jeton = "glpat-" + "b" * 20
        self.masque(f"TOKEN est {jeton}", jeton, "TOKEN est")

    def test_json(self):
        self.masque(
            '{"login": "essai", "password": "invente-json7"}',
            "invente-json7",
            '"login": "essai"',
        )

    def test_option_w_d_odoo(self):
        self.masque(
            "./odoo-bin -r odoo -w invente-w8 -d essai",
            "invente-w8",
            "-d essai",
        )
        self.masque("odoo_bin.sh -w 'invente w9'", "invente w9", "-w ")

    def test_sshpass_et_mysql(self):
        self.masque(
            "sshpass -p invente-ssh10 ssh essai", "invente-ssh10", "ssh essai"
        )
        self.masque(
            "mysql -u root -pinvente-my11 base", "invente-my11", "base"
        )

    def test_curl_utilisateur_et_mot_de_passe(self):
        self.masque(
            "curl -u admin:invente-curl12 http://essai.invalid",
            "invente-curl12",
            "-u admin:",
        )

    def test_cle_privee_dans_un_meme_texte(self):
        texte = (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEinvente13\n"
            "-----END OPENSSH PRIVATE KEY-----\n"
        )
        sortie = self.masque(
            texte, "invente13", "-----END OPENSSH PRIVATE KEY-----"
        )
        self.assertIn("-----BEGIN OPENSSH PRIVATE KEY-----", sortie)

    def test_les_autres_options_courtes_restent(self):
        """« -w » et « -u » veulent dire autre chose hors de leur outil."""
        for commande in (
            "grep -w motif fichier.txt",
            "docker exec -u odoo:odoo essai-ERPLibre-1 bash",
            "curl -w '%{http_code}' http://essai.invalid",
            "ssh://git@github.com/essai/depot.git",
            "Password: ",
        ):
            self.assertEqual(redact_secrets(commande), commande)


if __name__ == "__main__":
    unittest.main()
