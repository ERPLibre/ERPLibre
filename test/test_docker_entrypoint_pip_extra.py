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


# CapEff avec CHOWN, DAC_OVERRIDE, FOWNER, FSETID, SETGID et SETUID ; puis
# avec SETGID et SETUID seuls, ce que donne le compose par défaut.
CAPS_APT = format(
    (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4) | (1 << 6) | (1 << 7), "016x"
)
CAPS_SETPRIV = format((1 << 6) | (1 << 7), "016x")


class TestAptExtra(unittest.TestCase):
    """APT_EXTRA_PACKAGES : id, dpkg-query, apt-get, apt-config et setpriv
    sont des faux placés en tête du PATH, qui notent leurs arguments dans un
    même journal, dans l'ordre des appels ; les capacités viennent d'un faux
    fichier d'état de processus."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.journal = os.path.join(d, "appels.log")
        self.listes = os.path.join(d, "lists")
        os.makedirs(os.path.join(self.listes, "partial"))
        open(os.path.join(self.listes, "deb_InRelease"), "w").close()
        with open(os.path.join(d, ".erplibre-version"), "w") as fh:
            fh.write(VERSION + "\n")
        bindir = os.path.join(d, ".venv.erplibre", "bin")
        os.makedirs(bindir)
        stub = TestEntrypointPipExtra._stub
        stub(
            os.path.join(bindir, "python"),
            f'echo "pip $*" >> {self.journal}\n',
        )
        faux = os.path.join(d, "faux")
        os.makedirs(faux)
        self.path = faux + os.pathsep + os.environ["PATH"]
        stub(os.path.join(faux, "id"), 'echo "${FAKE_UID:-1000}"\n')
        stub(
            os.path.join(faux, "dpkg-query"),
            'printf "%b" "${FAKE_INSTALLED:-}"\n',
        )
        stub(
            os.path.join(faux, "apt-get"),
            f'echo "apt-get $*" >> {self.journal}\n'
            'if [[ "$1" == install ]]; then exit "${FAKE_APT_RC:-0}"; fi\n',
        )
        stub(
            os.path.join(faux, "apt-config"),
            f"echo \"listes='{self.listes}/'\"\n",
        )
        stub(
            os.path.join(faux, "setpriv"),
            'while [[ "$1" != env ]]; do shift; done; shift\n'
            'while [[ "$1" == *=* ]]; do shift; done\nexec "$@"\n',
        )
        self.etat = os.path.join(d, "status")
        self.suite = os.path.join(d, "entrypoint.sh")
        stub(self.suite, f'echo "odoo $*" >> {self.journal}\n')

    def _run(
        self, paquets, uid="0", caps=CAPS_APT, installes="", rc="0", pip=""
    ):
        with open(self.etat, "w") as fh:
            fh.write(f"Name:\tbash\nCapEff:\t{caps}\n")
        env = dict(
            os.environ,
            PATH=self.path,
            ODOO_PREFIX=self.tmp.name,
            ERPLIBRE_ENTRYPOINT=self.suite,
            ERPLIBRE_RUN_AS="root",
            ERPLIBRE_PROC_STATUS=self.etat,
            APT_EXTRA_PACKAGES=paquets,
            PIP_EXTRA_REQUIREMENTS_ERPLIBRE=pip,
            PIP_EXTRA_REQUIREMENTS_ODOO="",
            FAKE_UID=uid,
            FAKE_INSTALLED=installes,
            FAKE_APT_RC=rc,
        )
        return subprocess.run(
            ["bash", SCRIPT, "odoo"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _appels(self):
        if not os.path.exists(self.journal):
            return []
        with open(self.journal) as fh:
            return fh.read().splitlines()

    def test_vide_n_appelle_pas_apt(self):
        res = self._run("", uid="1000", caps="0" * 16)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self._appels(), ["odoo odoo"])

    def test_installe_avant_pip_puis_vide_les_listes(self):
        res = self._run("libmagic1  firefox-esr", pip="python-magic")
        self.assertEqual(res.returncode, 0, res.stderr)
        appels = self._appels()
        self.assertEqual(appels[0], "apt-get update -q")
        self.assertEqual(
            appels[1],
            "apt-get install -y -q --no-install-recommends libmagic1 firefox-esr",
        )
        self.assertEqual(appels[2], "apt-get clean")
        self.assertTrue(appels[3].startswith("pip "), appels)
        self.assertEqual(appels[-1], "odoo odoo")
        self.assertEqual(os.listdir(self.listes), [])

    def test_deja_installe_ou_fourni_ne_demande_rien(self):
        """Ni apt, ni root, ni capacité : un redémarrage reste hors réseau."""
        installes = (
            "ii  libmagic1t64 libmagic1 (= 1:5.46-5)\\n"
            "ii  firefox-esr \\n"
            "rc  cron \\n"
        )
        res = self._run(
            "libmagic1 firefox-esr",
            uid="1000",
            caps="0" * 16,
            installes=installes,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self._appels(), ["odoo odoo"])
        self.assertIn("déjà installés", res.stdout)

    def test_paquet_retire_n_est_pas_installe(self):
        """« rc » : retiré, sa configuration restée ; il est réinstallé."""
        res = self._run("cron", installes="rc  cron \\n")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(
            "apt-get install -y -q --no-install-recommends cron",
            self._appels(),
        )

    def test_un_nom_invalide_est_refuse(self):
        for mot in ("-o", "Firefox", "pkg=1.0", "../x", "a"):
            with self.subTest(mot=mot):
                res = self._run(f"libmagic1 {mot}")
                self.assertEqual(res.returncode, 1)
                self.assertIn("nom de paquet Debian", res.stderr)
                self.assertEqual(self._appels(), [])

    def test_sans_root_refuse(self):
        res = self._run("libmagic1", uid="1000")
        self.assertEqual(res.returncode, 1)
        self.assertIn("root", res.stderr)
        self.assertEqual(self._appels(), [])

    def test_sans_les_capacites_d_apt_refuse_avant_apt(self):
        """Il installerait mal sans erreur : un setgid perdu sans FSETID."""
        sans_fsetid = format(int(CAPS_APT, 16) & ~(1 << 4), "016x")
        for caps in (CAPS_SETPRIV, sans_fsetid):
            with self.subTest(caps=caps):
                res = self._run("libmagic1", caps=caps)
                self.assertEqual(res.returncode, 1)
                self.assertIn("FSETID", res.stderr)
                self.assertEqual(self._appels(), [])

    def test_un_refus_d_apt_arrete_avant_odoo(self):
        res = self._run("libmagic1", rc="100")
        self.assertEqual(res.returncode, 1)
        self.assertIn("APT_EXTRA_PACKAGES", res.stderr)
        self.assertNotIn("odoo odoo", self._appels())


if __name__ == "__main__":
    unittest.main()
