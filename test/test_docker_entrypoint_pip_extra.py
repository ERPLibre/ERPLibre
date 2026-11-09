#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""docker/entrypoint_pip_extra.sh, sans Docker : un faux préfixe ERPLibre
dont le « python » de chaque venv, Odoo et ERPLibre, note ses arguments dans
son propre journal, et un faux entrypoint qui note les siens. Lancé sous un
compte ordinaire, le script garde ce compte."""

import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "docker", "entrypoint_pip_extra.sh")
VERSION = "odoo18.0_python3.12.16"


class PrefixeFaux(unittest.TestCase):
    """Le faux préfixe et ses journaux, sans test propre : chaque classe
    qui en hérite n'exécute que les siens."""

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

    def _run(self, odoo="", erplibre="", rc="0", **extra):
        env = dict(
            os.environ,
            ODOO_PREFIX=self.tmp.name,
            ERPLIBRE_ENTRYPOINT=self.suite,
            PIP_EXTRA_REQUIREMENTS_ODOO=odoo,
            PIP_EXTRA_REQUIREMENTS_ERPLIBRE=erplibre,
            FAKE_PIP_RC=rc,
        )
        env.update(extra)
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


class TestEntrypointPipExtra(PrefixeFaux):
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
        self.assertEqual(pip[:4], ["-I", "-m", "pip", "install"])
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


class TestVenvResolu(PrefixeFaux):
    """Le nom du venv d'Odoo vient de .erplibre-version, qu'Odoo peut
    réécrire : un nom hors format, ou un venv qu'un lien mène ailleurs,
    arrête le script avant tout python. Un « python » piégé attend à chaque
    cible détournée et note son lancement ; il ne doit jamais tourner."""

    def setUp(self):
        super().setUp()
        self.dehors = tempfile.TemporaryDirectory()
        self.addCleanup(self.dehors.cleanup)
        self.piege_log = os.path.join(self.dehors.name, "piege.log")
        piege = f'echo "$0" >> {self.piege_log}\n'
        for base in (self.dehors.name, os.path.join(self.tmp.name, "autre")):
            os.makedirs(os.path.join(base, "bin"))
            self._stub(os.path.join(base, "bin", "python"), piege)

    def _version(self, texte):
        with open(os.path.join(self.tmp.name, ".erplibre-version"), "w") as fh:
            fh.write(texte)

    def _refuse(self, res):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("Odoo ne démarre pas", res.stderr)
        self.assertIsNone(self._lines(self.piege_log))
        self.assertIsNone(self._lines(self.odoo_log))
        self.assertIsNone(self._lines(self.suite_log))

    def test_une_version_hors_format_est_refusee(self):
        """« erplibre/../autre » mènerait « .venv.<version>/bin/python »
        sur autre/bin/python, hors de tout venv ; les deux premières
        versions visent chacune un python piégé."""
        for texte in (
            "erplibre/../autre",
            "erplibre/../" + os.path.relpath(self.dehors.name, self.tmp.name),
            f"{VERSION}/../../autre",
            "odoo18.0_python3.12.16/",
            "odoo18_python3",
            "",
        ):
            with self.subTest(version=texte):
                self._version(texte + "\n")
                res = self._run(odoo="humanize")
                self._refuse(res)
                self.assertIn(".erplibre-version", res.stderr)

    def test_une_version_qui_n_est_pas_un_fichier_est_refusee(self):
        chemin = os.path.join(self.tmp.name, ".erplibre-version")
        os.remove(chemin)
        os.mkfifo(chemin)
        self._refuse(self._run(odoo="humanize"))

    def test_une_version_changee_en_tube_apres_le_test_est_refusee(self):
        """Un faux « head » substitue un tube nommé au fichier entre le test
        « -f » et la lecture : sans écrivain, l'ouverture bloquerait root
        sans fin ; le délai de lecture arrête le script avant tout python."""
        faux = os.path.join(self.dehors.name, "faux")
        os.makedirs(faux)
        self._stub(
            os.path.join(faux, "head"),
            'f="${@: -1}"; rm -f -- "$f"; mkfifo -- "$f"\n'
            f'exec {shutil.which("head")} "$@"\n',
        )
        debut = time.monotonic()
        res = self._run(
            odoo="humanize", PATH=faux + os.pathsep + os.environ["PATH"]
        )
        self.assertLess(time.monotonic() - debut, 20)
        self._refuse(res)
        self.assertIn(".erplibre-version", res.stderr)
        self.assertTrue(
            stat.S_ISFIFO(
                os.lstat(
                    os.path.join(self.tmp.name, ".erplibre-version")
                ).st_mode
            )
        )

    def test_un_venv_lie_hors_du_prefixe_est_refuse(self):
        for venv, variable in (
            (f".venv.{VERSION}", "PIP_EXTRA_REQUIREMENTS_ODOO"),
            (".venv.erplibre", "PIP_EXTRA_REQUIREMENTS_ERPLIBRE"),
        ):
            for cible in (
                self.dehors.name,
                os.path.join(self.tmp.name, "autre"),
            ):
                with self.subTest(venv=venv, cible=cible):
                    chemin = os.path.join(self.tmp.name, venv)
                    reel = chemin + ".reel"
                    os.rename(chemin, reel)
                    os.symlink(cible, chemin)
                    try:
                        res = self._run(
                            odoo="humanize" * (variable.endswith("ODOO")),
                            erplibre="rich" * (variable.endswith("LIBRE")),
                        )
                    finally:
                        os.remove(chemin)
                        os.rename(reel, chemin)
                    self._refuse(res)
                    self.assertIn(variable, res.stderr)
                    self.assertIsNone(self._lines(self.erplibre_log))

    def test_un_venv_lie_a_un_autre_venv_du_prefixe_est_refuse(self):
        chemin = os.path.join(self.tmp.name, f".venv.{VERSION}")
        shutil.rmtree(chemin)
        os.symlink(os.path.join(self.tmp.name, ".venv.erplibre"), chemin)
        res = self._run(odoo="humanize")
        self._refuse(res)
        self.assertIsNone(self._lines(self.erplibre_log))

    def test_un_prefixe_lie_reste_accepte(self):
        """Seul le venv doit être enfant direct du préfixe RÉSOLU."""
        lien = os.path.join(self.dehors.name, "prefixe")
        os.symlink(self.tmp.name, lien)
        res = self._run(odoo="humanize", ODOO_PREFIX=lien)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self._lines(self.odoo_log)[-1], "humanize")


class TestPipEnRoot(PrefixeFaux):
    """Le script se croit root : « id » répond 0, « setpriv » note ses
    arguments puis lance la commande, et « stat » rapporte root comme
    propriétaire des chemins de FAKE_STAT_ROOT, séparés par « : »."""

    def setUp(self):
        super().setUp()
        faux = os.path.join(self.tmp.name, "faux")
        os.makedirs(faux)
        self.setpriv_log = os.path.join(self.tmp.name, "setpriv.log")
        self._stub(os.path.join(faux, "id"), "echo 0\n")
        self._stub(
            os.path.join(faux, "setpriv"),
            f'printf "%s\\n" "$@" > {self.setpriv_log}\n'
            'while [[ "$1" != env ]]; do shift; done; shift\n'
            'while [[ "$1" == *=* ]]; do shift; done\nexec "$@"\n',
        )
        self._stub(
            os.path.join(faux, "stat"),
            f'sortie=$({shutil.which("stat")} "$@") || exit\n'
            'IFS=: read -r -a racines <<<"${FAKE_STAT_ROOT:-}"\n'
            'for r in "${racines[@]}"; do\n'
            '  if [[ "${@: -1}" == "$r" ]]; then\n'
            "    sortie=$(sed 's/^[0-9]*/0/' <<<\"${sortie}\")\n"
            "  fi\n"
            "done\n"
            'echo "${sortie}"\n',
        )
        self.path = faux + os.pathsep + os.environ["PATH"]

    def test_pip_tourne_sous_le_proprietaire_du_venv(self):
        res = self._run(
            odoo="humanize", PATH=self.path, ERPLIBRE_RUN_AS="root"
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"--reuid={os.getuid()}", self._lines(self.setpriv_log))
        self.assertEqual(self._lines(self.odoo_log)[-1], "humanize")

    def test_uid_et_gid_viennent_d_une_seule_lecture_du_venv(self):
        """Le faux stat répond le vrai propriétaire à la première lecture du
        venv, puis un autre uid et un autre gid, comme après le renommage
        d'un autre venv sur ce chemin : setpriv reçoit le couple de la
        première lecture, et le venv n'est lu qu'une fois."""
        venv = os.path.realpath(
            os.path.join(self.tmp.name, f".venv.{VERSION}")
        )
        compteur = os.path.join(self.tmp.name, "stat_venv.log")
        self._stub(
            os.path.join(self.tmp.name, "faux", "stat"),
            f'if [[ "${{@: -1}}" == "{venv}" ]]; then\n'
            f"  echo x >> {compteur}\n"
            f"  if (( $(wc -l < {compteur}) > 1 )); then\n"
            '    echo "54321 54322"; exit 0\n'
            "  fi\n"
            "fi\n"
            f'exec {shutil.which("stat")} "$@"\n',
        )
        res = self._run(
            odoo="humanize", PATH=self.path, ERPLIBRE_RUN_AS="root"
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        args = self._lines(self.setpriv_log)
        self.assertIn(f"--reuid={os.getuid()}", args)
        self.assertIn(f"--regid={os.getgid()}", args)
        self.assertEqual(1, len(self._lines(compteur)))

    def test_un_venv_de_root_dans_un_prefixe_d_un_autre_compte_est_refuse(
        self,
    ):
        """Le préfixe appartient à l'utilisateur des tests : il pourrait
        substituer le venv entre la vérification et le lancement."""
        venv = os.path.realpath(
            os.path.join(self.tmp.name, f".venv.{VERSION}")
        )
        res = self._run(
            odoo="humanize",
            PATH=self.path,
            ERPLIBRE_RUN_AS="root",
            FAKE_STAT_ROOT=venv,
        )
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("appartient à root", res.stderr)
        self.assertIn("PIP_EXTRA_REQUIREMENTS_ODOO", res.stderr)
        self.assertIsNone(self._lines(self.odoo_log))
        self.assertIsNone(self._lines(self.setpriv_log))
        self.assertIsNone(self._lines(self.suite_log))


class TestBaseDuVenvEnRoot(PrefixeFaux):
    """Un venv de root ne vaut que si l'interpréteur de base que nomme
    « home » dans pyvenv.cfg est sûr : Python y charge os.py, site.py et
    sitecustomize.py, même sous -I. Le compte des tests y joue root : le faux
    « stat » le rapporte comme uid 0, et rapporte « 0 755 » hors du dossier
    des tests ; le faux « find » lit « -user 0 » comme ce compte. Une
    écriture qu'un autre compte détiendrait se simule par le bit
    d'écriture du groupe, que le vrai find et le vrai stat voient."""

    def setUp(self):
        super().setUp()
        self.racine = os.path.realpath(self.tmp.name)
        uid = os.getuid()
        faux = os.path.join(self.racine, "faux")
        os.makedirs(faux)
        self.setpriv_log = os.path.join(self.racine, "setpriv.log")
        self._stub(os.path.join(faux, "id"), "echo 0\n")
        self._stub(
            os.path.join(faux, "setpriv"),
            f'printf "%s\\n" "$@" > {self.setpriv_log}\nexit 1\n',
        )
        self._stub(
            os.path.join(faux, "stat"),
            f'sortie=$({shutil.which("stat")} "$@") || exit\n'
            'c="${@: -1}"\n'
            f'if [[ "$c" == {self.racine} || "$c" == {self.racine}/* ]]; then\n'
            f'  sed -E "s/^{uid}( |$)/0\\1/" <<<"${{sortie}}"\n'
            "else\n"
            "  sed -E 's/^[0-9]+ [0-7]+$/0 755/; s/^[0-9]+$/0/' <<<\"${sortie}\"\n"
            "fi\n",
        )
        self._stub(
            os.path.join(faux, "find"),
            "args=() avant=\n"
            'for a in "$@"; do\n'
            f'  if [[ "$avant" == -user && "$a" == 0 ]]; then a={uid}; fi\n'
            '  args+=("$a"); avant="$a"\n'
            "done\n"
            f'exec {shutil.which("find")} "${{args[@]}}"\n',
        )
        self.path = faux + os.pathsep + os.environ["PATH"]
        self.base = os.path.join(self.racine, "base")
        self.stdlib = os.path.join(self.base, "lib", "python3.12")
        os.makedirs(os.path.join(self.base, "bin"))
        os.makedirs(os.path.join(self.stdlib, "lib-dynload"))
        for nom in ("os.py", "site.py"):
            open(os.path.join(self.stdlib, nom), "w").close()
        open(os.path.join(self.base, "lib", "libpython3.12.so"), "w").close()
        self.venv = os.path.join(self.racine, ".venv.erplibre")
        self._cfg(os.path.join(self.venv, "pyvenv.cfg"), self._home())
        for d in (self.base, self.venv):
            os.chmod(d, 0o755)
            for haut, dossiers, fichiers in os.walk(d):
                for n in dossiers:
                    os.chmod(os.path.join(haut, n), 0o755)
                for n in fichiers:
                    chemin = os.path.join(haut, n)
                    os.chmod(chemin, 0o755 if n == "python" else 0o644)

    def _home(self):
        return os.path.join(self.base, "bin")

    @staticmethod
    def _cfg(chemin, *homes):
        with open(chemin, "w") as fh:
            for home in homes:
                fh.write(f"home = {home}\n")
            fh.write("include-system-site-packages = false\n")
        os.chmod(chemin, 0o644)

    def _lancer(self):
        return self._run(
            erplibre="rich", PATH=self.path, ERPLIBRE_RUN_AS="root"
        )

    def _refuse(self, res):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("interpréteur de base", res.stderr)
        self.assertIsNone(self._lines(self.erplibre_log))
        self.assertIsNone(self._lines(self.setpriv_log))
        self.assertIsNone(self._lines(self.suite_log))

    def test_une_base_sure_est_acceptee_et_pip_tourne_en_root(self):
        res = self._lancer()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self._lines(self.erplibre_log)[-1], "rich")
        self.assertIsNone(self._lines(self.setpriv_log))

    def test_une_bibliotheque_standard_inscriptible_est_refusee(self):
        chemin = os.path.join(self.stdlib, "sitecustomize.py")
        open(chemin, "w").close()
        os.chmod(chemin, 0o664)
        self._refuse(self._lancer())

    def test_un_dossier_de_la_base_inscriptible_est_refuse(self):
        for dossier in (
            self._home(),
            self.base,
            os.path.join(self.base, "lib"),
            self.stdlib,
        ):
            with self.subTest(dossier=dossier):
                os.chmod(dossier, 0o775)
                try:
                    self._refuse(self._lancer())
                finally:
                    os.chmod(dossier, 0o755)

    def test_une_entree_directe_de_lib_inscriptible_est_refusee(self):
        """« lib » porte libpython et pythonXY.zip, que Python charge."""
        os.chmod(os.path.join(self.base, "lib", "libpython3.12.so"), 0o664)
        self._refuse(self._lancer())

    def test_un_lien_de_la_stdlib_vers_un_dossier_hors_arbre_est_refuse(self):
        """find ne suit pas le lien : le contenu de la cible échapperait."""
        dehors = os.path.join(self.racine, "dehors")
        os.makedirs(dehors, mode=0o755)
        os.chmod(dehors, 0o755)
        os.symlink(dehors, os.path.join(self.stdlib, "encodings"))
        self._refuse(self._lancer())

    def test_un_home_absent_non_resolu_ou_sans_stdlib_est_refuse(self):
        lien = os.path.join(self.racine, "lien")
        os.symlink(self.base, lien)
        vide = os.path.join(self.racine, "vide", "bin")
        os.makedirs(os.path.join(self.racine, "vide", "lib"))
        os.makedirs(vide)
        for homes in (
            (),
            (os.path.join(self.racine, "absent", "bin"),),
            (os.path.join(lien, "bin"),),
            (self._home() + "/",),
            ("base/bin",),
            (vide,),
        ):
            with self.subTest(homes=homes):
                self._cfg(os.path.join(self.venv, "pyvenv.cfg"), *homes)
                self._refuse(self._lancer())

    def _base_inscriptible(self):
        """Une seconde base, complète, dont os.py reste inscriptible : son
        « home » ne se refuse que par sa bibliothèque standard."""
        base = os.path.join(self.racine, "autre")
        stdlib = os.path.join(base, "lib", "python3.12")
        os.makedirs(os.path.join(base, "bin"))
        os.makedirs(os.path.join(stdlib, "lib-dynload"))
        open(os.path.join(stdlib, "os.py"), "w").close()
        for haut, dossiers, _ in os.walk(base):
            os.chmod(haut, 0o755)
        os.chmod(os.path.join(stdlib, "os.py"), 0o664)
        return os.path.join(base, "bin")

    def test_la_premiere_cle_home_fait_foi(self):
        autre = self._base_inscriptible()
        cfg = os.path.join(self.venv, "pyvenv.cfg")
        self._cfg(cfg, autre, self._home())
        self._refuse(self._lancer())
        self._cfg(cfg, self._home(), autre)
        res = self._lancer()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_un_lib_entre_home_et_le_prefixe_est_refuse(self):
        """Python s'arrêterait au premier lib/pythonX.Y/os.py : un « lib »
        sans stdlib entre les deux est un dossier que la recherche sonde."""
        os.makedirs(os.path.join(self._home(), "lib"), mode=0o755)
        self._refuse(self._lancer())

    def test_bin_pyvenv_cfg_passe_avant_celui_du_venv(self):
        """Python lit d'abord le pyvenv.cfg du dossier de l'exécutable."""
        autre = self._base_inscriptible()
        bin_cfg = os.path.join(self.venv, "bin", "pyvenv.cfg")
        self._cfg(bin_cfg, autre)
        self._refuse(self._lancer())
        self._cfg(bin_cfg, self._home())
        self._cfg(os.path.join(self.venv, "pyvenv.cfg"), autre)
        res = self._lancer()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


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
        stub = PrefixeFaux._stub
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
        # Les listes restent : le redémarrage suivant ne refait qu'un
        # apt-get update conditionnel.
        self.assertNotIn("apt-get clean", appels)
        self.assertIn("deb_InRelease", os.listdir(self.listes))

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
