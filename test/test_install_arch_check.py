#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La garde d'architecture de make install_os et make install.

amd64, arm64 et s390x passent sans un mot. Une autre architecture est
nommée, puis une question o/N décide : Entrée seule vaut non. Sans terminal,
la réponse est non, sauf EL_ALLOW_UNSUPPORTED_ARCH=1, qui répond oui sans
question. uname est remplacé par un script qui rend l'architecture voulue.
"""

import os
import select
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = ". ./script/install/lib_arch_check.sh; el_arch_check"


class Base(unittest.TestCase):
    def env(self, arch, **extra):
        """Environnement où « uname -m » rend `arch`."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        faux = Path(tmp.name, "uname")
        faux.write_text(f"#!/bin/sh\necho {arch}\n", encoding="utf-8")
        faux.chmod(0o755)
        env = {
            k: v
            for k, v in os.environ.items()
            if k != "EL_ALLOW_UNSUPPORTED_ARCH"
        }
        env["PATH"] = f"{tmp.name}:{env['PATH']}"
        env.update(extra)
        return env

    def sans_terminal(self, arch, **extra):
        return subprocess.run(
            ["bash", "-c", SCRIPT],
            cwd=RACINE,
            env=self.env(arch, **extra),
            input="o\n",
            capture_output=True,
            text=True,
            check=False,
        )

    def au_terminal(self, arch, reponse):
        """Lance la garde sur un pseudo-terminal et y tape `reponse`."""
        maitre, esclave = os.openpty()
        proc = subprocess.Popen(
            ["bash", "-c", SCRIPT],
            cwd=RACINE,
            env=self.env(arch),
            stdin=esclave,
            stdout=esclave,
            stderr=esclave,
        )
        os.close(esclave)
        os.write(maitre, (reponse + "\n").encode())
        code = proc.wait(timeout=10)
        lu = b""
        while select.select([maitre], [], [], 0.2)[0]:
            try:
                morceau = os.read(maitre, 4096)
            except OSError:
                break
            if not morceau:
                break
            lu += morceau
        os.close(maitre)
        return code, lu.decode(errors="replace")


class TestArchitecturesSupportees(Base):
    def test_supported_architectures_pass_silently(self):
        for arch in ("x86_64", "amd64", "aarch64", "arm64", "s390x"):
            with self.subTest(arch=arch):
                proc = self.sans_terminal(arch)
                self.assertEqual(0, proc.returncode, proc.stdout)
                self.assertEqual("", proc.stdout)


class TestArchitectureNonSupportee(Base):
    def test_yes_in_french_or_english_goes_on(self):
        for reponse in ("o", "oui", "Y", "yes"):
            with self.subTest(reponse=reponse):
                code, lu = self.au_terminal("ppc64le", reponse)
                self.assertEqual(0, code, lu)
                self.assertIn("ppc64le non supportée", lu)
                self.assertIn("[o/N]", lu)

    def test_enter_or_no_stops_and_names_the_variable(self):
        for reponse in ("", "n", "non"):
            with self.subTest(reponse=reponse):
                code, lu = self.au_terminal("riscv64", reponse)
                self.assertEqual(1, code, lu)
                self.assertIn("EL_ALLOW_UNSUPPORTED_ARCH=1", lu)

    def test_without_terminal_it_stops_without_asking(self):
        proc = self.sans_terminal("ppc64le")
        self.assertEqual(1, proc.returncode)
        self.assertNotIn("[o/N]", proc.stdout)
        self.assertIn("EL_ALLOW_UNSUPPORTED_ARCH=1 make install", proc.stdout)

    def test_the_variable_answers_yes_without_asking(self):
        proc = self.sans_terminal("ppc64le", EL_ALLOW_UNSUPPORTED_ARCH="1")
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertNotIn("[o/N]", proc.stdout)
        self.assertIn("ppc64le non supportée", proc.stdout)


class TestAppelants(unittest.TestCase):
    """Les deux points d'entrée posent la garde, avant tout travail."""

    def test_install_dev_checks_before_the_distribution(self):
        source = (RACINE / "script/install/install_dev.sh").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            source.index("el_arch_check || exit 1"),
            source.index("source /etc/os-release"),
        )

    def test_install_erplibre_checks_before_the_venv(self):
        source = (RACINE / "script/install/install_erplibre.sh").read_text(
            encoding="utf-8"
        )
        garde = source.index("el_arch_check || exit 1")
        self.assertLess(
            garde, source.index(". ./script/install/S390x/build_check.sh")
        )
        self.assertLess(garde, source.index("install_venv.sh"))
        # build_check.sh ne se charge plus que sur s390x.
        self.assertIn('if [ "$(uname -m)" = "s390x" ]; then', source)


if __name__ == "__main__":
    unittest.main(verbosity=1)
