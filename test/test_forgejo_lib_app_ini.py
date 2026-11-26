#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""`ini_poser` de script/forgejo/lib_app_ini.sh, exécuté par bash.

Propriétés gardées : la clé se pose dans la section exacte, une valeur
déjà juste laisse le fichier identique octet pour octet, et toute autre
ligne — secrets compris — passe intacte. Les secrets sont inventés.
"""

import pathlib
import subprocess
import unittest

LIB = (
    pathlib.Path(__file__).resolve().parent.parent
    / "script/forgejo/lib_app_ini.sh"
)


def poser(texte, section, cle, valeur):
    res = subprocess.run(
        [
            "bash",
            "-c",
            '. "$0" && ini_poser "$1" "$2" "$3"',
            str(LIB),
            section,
            cle,
            valeur,
        ],
        input=texte,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if res.returncode:
        raise AssertionError(res.stderr)
    return res.stdout


class TestIniPoser(unittest.TestCase):
    def test_sourcing_has_no_side_effect(self):
        res = subprocess.run(
            ["bash", "-c", '. "$0"; echo fin', str(LIB)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual((res.returncode, res.stdout), (0, "fin\n"))

    def test_an_absent_section_is_appended(self):
        self.assertEqual(
            poser(
                "[server]\nHTTP_PORT = 3000\n", "actions", "ENABLED", "true"
            ),
            "[server]\nHTTP_PORT = 3000\n\n[actions]\nENABLED = true\n",
        )

    def test_a_section_without_the_key_gets_it_after_its_header(self):
        self.assertEqual(
            poser(
                "[repository]\nROOT = /r\n[log]\n",
                "repository",
                "DEFAULT_REPO_UNITS",
                "repo.code",
            ),
            "[repository]\nDEFAULT_REPO_UNITS = repo.code\nROOT = /r\n[log]\n",
        )

    def test_a_false_value_becomes_true(self):
        self.assertEqual(
            poser("[actions]\nENABLED=false\n", "actions", "ENABLED", "true"),
            "[actions]\nENABLED = true\n",
        )

    def test_a_right_value_leaves_the_file_byte_identical(self):
        for texte in (
            "[actions]\nENABLED = true\n",
            "[actions]\n  ENABLED   =   true  \n",
        ):
            self.assertEqual(
                poser(texte, "actions", "ENABLED", "true"), texte, texte
            )

    def test_other_sections_and_top_keys_are_untouched(self):
        texte = (
            "ENABLED = false\nRUN_USER = git\n"
            "[mailer]\nENABLED = false\n[actions]\n"
        )
        self.assertEqual(
            poser(texte, "actions", "ENABLED", "true"),
            "ENABLED = false\nRUN_USER = git\n"
            "[mailer]\nENABLED = false\n[actions]\nENABLED = true\n",
        )

    def test_a_dotted_section_is_another_section(self):
        texte = "[repository.pull-request]\nDEFAULT_REPO_UNITS = x\n"
        self.assertEqual(
            poser(texte, "repository", "DEFAULT_REPO_UNITS", "repo.code"),
            texte + "\n[repository]\nDEFAULT_REPO_UNITS = repo.code\n",
        )

    def test_secret_lines_are_byte_identical(self):
        secrets = (
            "[security]\n"
            "SECRET_KEY = s3cr3t-invente==\n"
            "INTERNAL_TOKEN=jeton.invente.abc=def\n"
            "[oauth2]\n"
            "JWT_SECRET =   jwt-invente  \n"
        )
        sortie = poser(secrets, "actions", "ENABLED", "true")
        self.assertTrue(sortie.startswith(secrets), sortie)


if __name__ == "__main__":
    unittest.main()
