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
        self.assertEqual(
            self._lines(self.suite_log), ["odoo", "--workers", "2"]
        )

    def test_each_word_is_one_requirement(self):
        res = self._run(odoo="humanize  pyotp==2.9.0 phonenumbers>=8.13,<9")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIsNone(self._lines(self.erplibre_log))
        pip = self._lines(self.odoo_log)
        self.assertEqual(pip[:3], ["-m", "pip", "install"])
        self.assertEqual(
            pip[-3:], ["humanize", "pyotp==2.9.0", "phonenumbers>=8.13,<9"]
        )
        self.assertEqual(
            self._lines(self.suite_log), ["odoo", "--workers", "2"]
        )

    def test_a_yaml_block_spreads_over_lines(self):
        """Un bloc YAML « | » livre une exigence par ligne : toutes passent."""
        res = self._run(
            odoo="humanize\npyotp==2.9.0\n", erplibre="rich\n  pyyaml"
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            self._lines(self.odoo_log)[-2:], ["humanize", "pyotp==2.9.0"]
        )
        self.assertEqual(
            self._lines(self.erplibre_log)[-2:], ["rich", "pyyaml"]
        )

    def test_each_list_goes_to_its_venv(self):
        res = self._run(odoo="humanize", erplibre="rich==13.7.1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self._lines(self.odoo_log)[-1], "humanize")
        self.assertEqual(self._lines(self.erplibre_log)[-1], "rich==13.7.1")
        self.assertEqual(
            self._lines(self.suite_log), ["odoo", "--workers", "2"]
        )

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
    """APT_EXTRA_PACKAGES : id, dpkg-query, apt-get, apt-cache, apt-config et
    setpriv sont des faux placés en tête du PATH, qui notent leurs arguments
    dans un même journal, dans l'ordre des appels ; les capacités viennent
    d'un faux fichier d'état de processus. Le faux apt-get install marque
    installés les noms qu'il reçoit, sauf sous FAKE_APT_INSTALLE_AUTRE, où il
    réussit sans les installer, comme apt sur une expression régulière ; le
    faux apt-cache connaît les noms de FAKE_CONNUS."""

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
        self.dpkg = os.path.join(d, "dpkg.status")
        stub(
            os.path.join(faux, "dpkg-query"),
            'printf "%b" "${FAKE_INSTALLED:-}"\n'
            f"if [[ -f {self.dpkg} ]]; then cat {self.dpkg}; fi\n",
        )
        stub(
            os.path.join(faux, "apt-get"),
            f'echo "apt-get $*" >> {self.journal}\n'
            'if [[ "$1" == clean ]]; then exit "${FAKE_CLEAN_RC:-0}"; fi\n'
            'if [[ "$1" != install ]]; then exit 0; fi\n'
            'if [[ "${FAKE_APT_RC:-0}" != 0 || -n "${FAKE_APT_INSTALLE_AUTRE:-}" ]]; then\n'
            '  exit "${FAKE_APT_RC:-0}"\n'
            "fi\n"
            'for a in "$@"; do\n'
            f'  if [[ "$a" != -* && "$a" != install ]]; then echo "ii  $a " >> {self.dpkg}; fi\n'
            "done\n",
        )
        stub(
            os.path.join(faux, "apt-cache"),
            f'echo "apt-cache $*" >> {self.journal}\n'
            'printf "%b" "${FAKE_CONNUS-}"\n',
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
        self,
        paquets,
        uid="0",
        caps=CAPS_APT,
        installes="",
        rc="0",
        pip="",
        connus="libmagic1\\nfirefox-esr\\ncron\\nsl\\ng++\\n",
        **faux,
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
            FAKE_CONNUS=connus,
            **faux,
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
        appels = [a for a in self._appels() if not a.startswith("apt-cache ")]
        self.assertEqual(appels[0], "apt-get update -q")
        self.assertEqual(
            appels[1],
            "apt-get install -y -q --no-install-recommends libmagic1 firefox-esr",
        )
        self.assertEqual(appels[2], "apt-get clean")
        self.assertTrue(appels[3].startswith("pip "), appels)
        self.assertEqual(appels[-1], "odoo odoo")
        self.assertEqual(os.listdir(self.listes), [])

    def test_un_bloc_yaml_sur_plusieurs_lignes_installe_tout(self):
        res = self._run("libmagic1\nsl\n  firefox-esr\n")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(
            "apt-get install -y -q --no-install-recommends"
            " libmagic1 sl firefox-esr",
            self._appels(),
        )

    def test_le_nom_exact_est_cherche_dans_l_index_apres_update(self):
        res = self._run("g++")
        self.assertEqual(res.returncode, 0, res.stderr)
        appels = self._appels()
        self.assertEqual(appels[0], "apt-get update -q")
        self.assertEqual(appels[1], "apt-cache --all-names pkgnames g++")
        self.assertTrue(appels[2].startswith("apt-get install "), appels)

    def test_un_suffixe_d_action_d_apt_est_refuse_avant_apt(self):
        """« curl- » retirerait curl, « foo+ » est une action d'apt."""
        for mot in ("curl-", "foo+", "libmagic1.", "g+++-"):
            with self.subTest(mot=mot):
                res = self._run(mot)
                self.assertEqual(res.returncode, 1)
                self.assertIn("nom de paquet Debian", res.stderr)
                self.assertIn("Odoo ne démarre pas", res.stderr)
                self.assertEqual(self._appels(), [])

    def test_un_nom_inconnu_d_apt_est_refuse_avant_l_installation(self):
        """« libmagic1.64 » serait lu en expression régulière."""
        res = self._run("libmagic1 libmagic1.64")
        self.assertEqual(res.returncode, 1)
        self.assertIn("« libmagic1.64 »", res.stderr)
        self.assertIn("Odoo ne démarre pas", res.stderr)
        appels = self._appels()
        self.assertEqual(appels[0], "apt-get update -q")
        self.assertFalse(
            [a for a in appels if a.startswith("apt-get install")], appels
        )
        self.assertNotIn("odoo odoo", appels)
        self.assertIn("apt-get clean", appels)

    def test_un_nom_absent_apres_apt_arrete_avant_odoo(self):
        """apt réussit sans installer le nom : refusé, sinon chaque
        démarrage relancerait apt."""
        res = self._run("libmagic1", FAKE_APT_INSTALLE_AUTRE="1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("sans installer « libmagic1 »", res.stderr)
        self.assertIn("Odoo ne démarre pas", res.stderr)
        self.assertNotIn("odoo odoo", self._appels())

    def test_un_echec_du_menage_d_apt_avertit_sans_arreter(self):
        res = self._run("libmagic1", FAKE_CLEAN_RC="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Avertissement", res.stderr)
        self.assertEqual(self._appels()[-1], "odoo odoo")

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
        """Sans FSETID, apt réussit mais perd un bit setgid, sans erreur."""
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
