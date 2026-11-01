#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""docker/entrypoint_pip_extra.sh, sans Docker : un faux préfixe ERPLibre
dont le « python » de chaque venv, Odoo et ERPLibre, note ses arguments dans
son propre journal, et un faux entrypoint qui note les siens. Lancé sous un
compte ordinaire, le script garde ce compte."""

import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "docker", "entrypoint_pip_extra.sh")
VERSION = "odoo18.0_python3.12.16"


class TestEntrypointPipExtra(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        with open(os.path.join(d, ".erplibre-version"), "w") as fh:
            fh.write(VERSION + "\n")
        self.pip_log = {}
        for venv in (f".venv.{VERSION}", ".venv.erplibre"):
            bindir = os.path.join(d, venv, "bin")
            os.makedirs(bindir)
            self.pip_log[venv] = os.path.join(d, f"pip{venv}.log")
            self._stub(
                os.path.join(bindir, "python"),
                f'printf "%s\\n" "$@" > {self.pip_log[venv]}\n'
                'exit "${FAKE_PIP_RC:-0}"\n',
            )
        self.odoo_log = self.pip_log[f".venv.{VERSION}"]
        self.erplibre_log = self.pip_log[".venv.erplibre"]
        self.suite_log = os.path.join(d, "suite.log")
        self.suite = os.path.join(d, "entrypoint.sh")
        self._stub(self.suite, f'printf "%s\\n" "$@" > {self.suite_log}\n')

    @staticmethod
    def _stub(path, body):
        with open(path, "w") as fh:
            fh.write("#!/usr/bin/env bash\n" + body)
        os.chmod(path, 0o755)

    def _run(self, odoo="", erplibre="", rc="0"):
        env = dict(
            os.environ,
            ODOO_PREFIX=self.tmp.name,
            ERPLIBRE_ENTRYPOINT=self.suite,
            PIP_EXTRA_REQUIREMENTS_ODOO=odoo,
            PIP_EXTRA_REQUIREMENTS_ERPLIBRE=erplibre,
            FAKE_PIP_RC=rc,
        )
        return subprocess.run(
            ["bash", SCRIPT, "odoo", "--workers", "2"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _lines(self, path):
        if not os.path.exists(path):
            return None
        with open(path) as fh:
            return fh.read().splitlines()

    def test_empty_lists_install_nothing(self):
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIsNone(self._lines(self.odoo_log))
        self.assertIsNone(self._lines(self.erplibre_log))
        self.assertEqual(self._lines(self.suite_log), ["odoo", "--workers", "2"])

    def test_each_word_is_one_requirement(self):
        res = self._run(odoo="humanize  pyotp==2.9.0 phonenumbers>=8.13,<9")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIsNone(self._lines(self.erplibre_log))
        pip = self._lines(self.odoo_log)
        self.assertEqual(pip[:3], ["-m", "pip", "install"])
        self.assertEqual(
            pip[-3:], ["humanize", "pyotp==2.9.0", "phonenumbers>=8.13,<9"]
        )
        self.assertEqual(self._lines(self.suite_log), ["odoo", "--workers", "2"])

    def test_each_list_goes_to_its_venv(self):
        res = self._run(odoo="humanize", erplibre="rich==13.7.1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self._lines(self.odoo_log)[-1], "humanize")
        self.assertEqual(self._lines(self.erplibre_log)[-1], "rich==13.7.1")
        self.assertEqual(self._lines(self.suite_log), ["odoo", "--workers", "2"])

    def test_erplibre_list_alone_needs_no_odoo_venv(self):
        os.remove(os.path.join(self.tmp.name, ".erplibre-version"))
        res = self._run(erplibre="rich==13.7.1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self._lines(self.erplibre_log)[-1], "rich==13.7.1")

    def test_pip_failure_stops_before_odoo(self):
        for odoo, erplibre, variable in (
            ("pyotp==0.0.0", "", "PIP_EXTRA_REQUIREMENTS_ODOO"),
            ("", "rich==0.0.0", "PIP_EXTRA_REQUIREMENTS_ERPLIBRE"),
        ):
            with self.subTest(variable=variable):
                res = self._run(odoo=odoo, erplibre=erplibre, rc="1")
                self.assertEqual(res.returncode, 1)
                self.assertIn(variable, res.stderr)
                self.assertIsNone(self._lines(self.suite_log))


if __name__ == "__main__":
    unittest.main()
