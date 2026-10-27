#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Repo sync d'arrière-plan de install_locally_dev.sh, et détection par
update_env_version.py des sources d'Odoo absentes.

Le script réel tourne dans un arbre temporaire où install_locally.sh,
update_manifest_local_dev.sh et npm sont des bouchons : le premier échoue
ou réussit selon la phase, le second lance un petit-enfant de longue durée
dont il écrit le PID dans un fichier.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from script.version.update_env_version import Update

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "script", "install", "install_locally_dev.sh")

STUB_INSTALL = """#!/usr/bin/env bash
if [ "$EL_PHASE" = "poetry" ]; then
    # Laisse au repo sync le temps de lancer son petit-enfant.
    for _ in $(seq 50); do [ -s child.pid ] && break; sleep 0.1; done
    exit "${STUB_POETRY_RC:-0}"
fi
exit 0
"""

STUB_SYNC = """#!/usr/bin/env bash
echo "stub sync started"
sleep 300 &
echo $! > child.pid
if [ -n "$STUB_SYNC_RC" ]; then
    kill $!
    echo "stub sync failure"
    exit "$STUB_SYNC_RC"
fi
wait
"""


def _alive(pid):
    """Vrai si le processus existe et n'est pas un zombie."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


class TestInstallRepoSyncBackground(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.makedirs(os.path.join(self.tmp, "script", "install"))
        os.makedirs(os.path.join(self.tmp, "script", "manifest"))
        os.makedirs(os.path.join(self.tmp, "bin"))
        shutil.copy(SCRIPT, os.path.join(self.tmp, "script", "install"))
        self._write("env_var.sh", "")
        self._write("script/install/install_locally.sh", STUB_INSTALL)
        self._write("script/manifest/update_manifest_local_dev.sh", STUB_SYNC)
        self._write("bin/npm", "#!/usr/bin/env bash\nexit 0\n")

    def _write(self, rel, content):
        path = os.path.join(self.tmp, rel)
        with open(path, "w") as f:
            f.write(content)
        os.chmod(path, 0o755)

    def _run(self, **env):
        full_env = dict(os.environ)
        full_env["PATH"] = (
            os.path.join(self.tmp, "bin") + os.pathsep + full_env["PATH"]
        )
        full_env["EL_PARALLEL_INSTALL"] = "1"
        full_env.update(env)
        # Inscrit AVANT le lancement : un script qui dépasse le délai lève
        # TimeoutExpired, et l'enfant du faux sync doit mourir quand même.
        pid_file = os.path.join(self.tmp, "child.pid")
        self.addCleanup(self._kill_from_file, pid_file)
        proc = subprocess.run(
            ["bash", "./script/install/install_locally_dev.sh"],
            cwd=self.tmp,
            env=full_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )
        log = re.search(r"(/tmp/el_repo_sync_\d+\.log)", proc.stdout)
        self.assertIsNotNone(log, proc.stdout)
        log_path = log.group(1)
        self.addCleanup(
            lambda: os.path.exists(log_path) and os.remove(log_path)
        )
        with open(pid_file) as f:
            child_pid = int(f.read())
        return proc, log_path, child_pid

    @classmethod
    def _kill_from_file(cls, pid_file):
        try:
            with open(pid_file) as f:
                cls._kill(int(f.read()))
        except (OSError, ValueError):
            pass

    @staticmethod
    def _kill(pid):
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass

    def _assert_dead(self, pid):
        # Le petit-enfant orphelin est réparenté puis récolté par init.
        for _ in range(20):
            if not _alive(pid):
                return
            time.sleep(0.1)
        self.fail(f"orphan process {pid} still running")

    def test_poetry_failure_kills_whole_sync_group_and_keeps_log(self):
        proc, log_path, child_pid = self._run(STUB_POETRY_RC="1")
        self.assertNotEqual(proc.returncode, 0)
        self._assert_dead(child_pid)
        self.assertTrue(os.path.isfile(log_path))
        with open(log_path) as f:
            self.assertIn("stub sync started", f.read())
        self.assertIn(f"log kept: {log_path}", proc.stdout)

    def test_sync_failure_reports_error_and_keeps_log(self):
        proc, log_path, _ = self._run(STUB_SYNC_RC="3")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("repo sync) failed", proc.stdout)
        self.assertTrue(os.path.isfile(log_path))
        with open(log_path) as f:
            self.assertIn("stub sync failure", f.read())

    def test_success_removes_log(self):
        proc, log_path, _ = self._run(STUB_SYNC_RC="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Repo sync completed successfully", proc.stdout)
        self.assertFalse(os.path.exists(log_path))


class TestValidateEnvironmentOdooSources(unittest.TestCase):
    """Un venv complet sans odoo<ver>/odoo/odoo-bin n'est pas installé."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)
        os.makedirs(os.path.join("odoo18.0", "addons"))
        os.makedirs(".venv.odoo18.0_python3.12.10")
        with patch("sys.argv", ["prog", "--install_dev"]):
            self.update = Update()
        self.update.expected_venv_name = ".venv.odoo18.0_python3.12.10"
        self.update.expected_addons_name = os.path.join("odoo18.0", "addons")
        self.update.expected_odoo_name = "odoo18.0"
        self.update.expected_pyproject_path = "unused"
        self.update.expected_poetry_lock_path = "unused"
        self.update.new_version_odoo = "18.0"
        p = patch.object(Update, "update_link_file", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        # Version enregistrée comme installée, sauf test contraire.
        self.installe = patch(
            "script.version.update_env_version.get_version_installed",
            return_value=True,
        )
        self.installe.start()
        self.addCleanup(self.installe.stop)

    def _odoo_bin(self):
        os.makedirs(os.path.join("odoo18.0", "odoo"))
        open(os.path.join("odoo18.0", "odoo", "odoo-bin"), "w").close()

    def test_missing_odoo_bin_requires_install(self):
        self.assertFalse(self.update.validate_environment())

    def test_present_odoo_bin_is_valid(self):
        self._odoo_bin()
        self.assertTrue(self.update.validate_environment())

    def test_failed_poetry_is_not_an_installation(self):
        """Venv et sources présents, mais aucune installation réussie
        enregistrée : poetry install a échoué, il faut reprendre."""
        self._odoo_bin()
        self.installe.stop()
        with patch(
            "script.version.update_env_version.get_version_installed",
            return_value=False,
        ):
            self.assertFalse(self.update.validate_environment())

    def test_a_switch_ignores_the_installation_record(self):
        """--switch n'installe rien : l'état ne le concerne pas."""
        self._odoo_bin()
        self.installe.stop()
        self.update.config.install_dev = False
        with patch(
            "script.version.update_env_version.get_version_installed",
            return_value=False,
        ):
            self.assertTrue(self.update.validate_environment())


def _manifeste_local(revision):
    """Écrit un manifeste local à un projet, sur `revision`."""
    os.makedirs(os.path.join(".repo", "local_manifests"), exist_ok=True)
    with open(
        os.path.join(".repo", "local_manifests", "erplibre_manifest.xml"), "w"
    ) as f:
        f.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n'
            f'  <project name="p" path="p" revision="{revision}"/>\n'
            "</manifest>\n"
        )


class TestValidateEnvironmentFreezeMode(unittest.TestCase):
    """Le mode demandé par TODO (EL_FREEZE) contre celui du manifeste local.

    Une version installée et complète sautait le repo sync : choisir la
    production laissait les dépôts sur leurs branches."""

    SHA = "1234567890abcdef1234567890abcdef12345678"

    def setUp(self):
        # Le même checkout que TestValidateEnvironmentOdooSources, complet :
        # son setUp sans hériter de ses tests.
        TestValidateEnvironmentOdooSources.setUp(self)
        TestValidateEnvironmentOdooSources._odoo_bin(self)

    def _valide(self, el_freeze):
        env = {} if el_freeze is None else {"EL_FREEZE": el_freeze}
        with patch.dict(os.environ, env, clear=False):
            if el_freeze is None:
                os.environ.pop("EL_FREEZE", None)
            return self.update.validate_environment()

    def test_production_on_branches_requires_the_sync(self):
        _manifeste_local("18.0")
        self.assertFalse(self._valide("1"))

    def test_development_on_frozen_commits_requires_the_sync(self):
        _manifeste_local(self.SHA)
        self.assertFalse(self._valide("0"))

    def test_the_mode_already_in_place_needs_nothing(self):
        _manifeste_local(self.SHA)
        self.assertTrue(self._valide("1"))
        _manifeste_local("18.0")
        self.assertTrue(self._valide("0"))

    def test_production_without_local_manifest_requires_the_sync(self):
        self.assertFalse(self._valide("1"))
        self.assertTrue(self._valide("0"))

    def test_no_choice_from_todo_changes_nothing(self):
        _manifeste_local("18.0")
        self.assertTrue(self._valide(None))

    def test_a_switch_is_not_concerned(self):
        _manifeste_local("18.0")
        self.update.config.install_dev = False
        self.assertTrue(self._valide("1"))


class TestLocalManifestFrozen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)

    def test_reads_the_mode(self):
        from script.version.update_env_version import local_manifest_frozen

        self.assertIsNone(local_manifest_frozen())
        _manifeste_local("18.0")
        self.assertFalse(local_manifest_frozen())
        _manifeste_local("1234567890abcdef1234567890abcdef12345678")
        self.assertTrue(local_manifest_frozen())
        with open(
            os.path.join(".repo", "local_manifests", "erplibre_manifest.xml"),
            "w",
        ) as f:
            f.write("<manifest>")
        self.assertIsNone(local_manifest_frozen())


if __name__ == "__main__":
    unittest.main()
