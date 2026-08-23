#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Montage sshfs : ne rien annoncer qui n'ait eu lieu, et dire pourquoi.

Le symptôme rapporté : « read: Connection reset by peer », « code : 1 », et
juste après « Monté sur /tmp/sshfs_… », la commande pour démonter et celle
pour ouvrir le répertoire dans un explorateur. Le montage n'avait pas eu lieu.

La cause, elle, est plus profonde : sshfs lit « a+b » comme un CHAÎNAGE
d'hôtes — « ssh a, puis ssh b depuis a » — et ne consulte donc jamais
~/.ssh/config pour l'alias entier. Or c'est todo.py qui nomme les VM
découvertes « rebond+domaine », et la seconde moitié de ce nom est un domaine
libvirt, pas un alias SSH du rebond. Ces alias-là, les plus utiles, étaient
les seuls que sshfs ne pouvait pas monter.

Ce que ces tests gardent :

- Aucune ligne de succès après un code non nul.
- Le point de montage inutilisé est retiré, pas laissé dans /tmp.
- Un alias à « + » est résolu par ssh lui-même (« ssh -G ») et rendu à sshfs
  sous une forme qu'il ne peut plus mal lire, options comprises — sans
  StrictHostKeyChecking, une VM à l'IP recyclée échouerait sur sa clé d'hôte.
- « Host a b » déclare DEUX alias : c'est ce que le générateur du dépôt écrit.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

# Entrée réelle écrite par todo.py pour une VM derrière un rebond.
CONFIG = """Host *
    ServerAliveInterval 60

Host novipro_private
    HostName 192.168.100.110
    User mathben

Host novipro_private+ERPLibre01
    HostName 192.168.122.50
    User mathben
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    IdentityFile /home/erplibre/.ssh/id_ed25519
    IdentitiesOnly yes
    ProxyJump novipro_private

Host erplibre-ubuntu-2604 erplibre-2604-bis
    HostName 192.168.123.165
    User erplibre

Host web-?
    User www
"""

# Sortie de « ssh -G » pour l'alias à « + », réduite à ce qui compte.
SSH_G = """host novipro_private+erplibre01
hostname 192.168.122.50
user mathben
port 22
proxyjump novipro_private
identityfile /home/erplibre/.ssh/id_ed25519
identityfile ~/.ssh/id_rsa
identitiesonly yes
stricthostkeychecking false
userknownhostsfile /dev/null
"""


def _config(texte=CONFIG):
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".config", delete=False, encoding="utf-8"
    )
    tmp.write(texte)
    tmp.close()
    return tmp.name


class TestLectureConfig(unittest.TestCase):
    def setUp(self):
        self.chemin = _config()
        self.addCleanup(os.unlink, self.chemin)

    def test_it_reads_hosts_in_file_order(self):
        hosts = TODO._ssh_config_entries(self.chemin)
        noms = [n for n, _i in hosts]
        self.assertEqual("novipro_private", noms[0])
        self.assertIn("novipro_private+ERPLibre01", noms)

    def test_a_host_line_with_two_patterns_gives_two_aliases(self):
        """C'est ce que le générateur du dépôt écrit (« Host {' '.join(names)} »).
        Les prendre pour un seul nom donnait l'alias « a b », que sshfs ne peut
        pas monter — et qui n'existe pour personne."""
        hosts = dict(TODO._ssh_config_entries(self.chemin))
        self.assertIn("erplibre-ubuntu-2604", hosts)
        self.assertIn("erplibre-2604-bis", hosts)
        self.assertEqual(
            "192.168.123.165", hosts["erplibre-ubuntu-2604"]["hostname"]
        )
        self.assertEqual(
            hosts["erplibre-ubuntu-2604"], hosts["erplibre-2604-bis"]
        )

    def test_wildcard_patterns_are_left_out(self):
        """« Host * » et « Host web-? » ne désignent aucune machine : les
        proposer dans un menu de montage n'a pas de sens."""
        noms = [n for n, _i in TODO._ssh_config_entries(self.chemin)]
        self.assertNotIn("*", noms)
        self.assertNotIn("web-?", noms)

    def test_the_plus_alias_stays_one_name(self):
        noms = [n for n, _i in TODO._ssh_config_entries(self.chemin)]
        self.assertNotIn("novipro_private", noms[1:2] and [])
        self.assertIn("novipro_private+ERPLibre01", noms)

    def test_hostname_and_user_are_kept(self):
        hosts = dict(TODO._ssh_config_entries(self.chemin))
        info = hosts["novipro_private+ERPLibre01"]
        self.assertEqual("192.168.122.50", info["hostname"])
        self.assertEqual("mathben", info["user"])

    def test_a_missing_file_is_not_a_crash(self):
        self.assertEqual([], TODO._ssh_config_entries("/nexistepas/config"))


class TestResolution(unittest.TestCase):
    def test_it_reads_ssh_dash_g(self):
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, SSH_G, ""),
        ):
            cfg = TODO._ssh_resolve("novipro_private+ERPLibre01")
        self.assertEqual("192.168.122.50", cfg["hostname"])
        self.assertEqual("novipro_private", cfg["proxyjump"])

    def test_the_first_identityfile_wins(self):
        """ssh -G les répète toutes ; la première est celle qu'il essaiera."""
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, SSH_G, ""),
        ):
            cfg = TODO._ssh_resolve("x")
        self.assertEqual("/home/erplibre/.ssh/id_ed25519", cfg["identityfile"])

    def test_a_failing_ssh_resolves_to_nothing(self):
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 255, "", "bad"),
        ):
            self.assertEqual({}, TODO._ssh_resolve("x"))
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertEqual({}, TODO._ssh_resolve("x"))


class TestCommandeSshfs(unittest.TestCase):
    def setUp(self):
        # Méthode d'instance : elle interroge self._ssh_resolve quand aucune
        # résolution ne lui est fournie.
        self.todo = TODO.__new__(TODO)
        self.todo._ssh_resolve = lambda alias: {}

    def test_an_alias_without_plus_is_handed_over_untouched(self):
        """Sans « + », c'est ssh qui lit la config, et rien ne vaut mieux."""
        cmd, contourne = self.todo._sshfs_command("vm-a", "/tmp/mnt")
        self.assertEqual("sshfs -o follow_symlinks vm-a:/ /tmp/mnt", cmd)
        self.assertFalse(contourne)

    def _resolue(self):
        return {
            "hostname": "192.168.122.50",
            "user": "mathben",
            "port": "22",
            "proxyjump": "novipro_private",
            "identityfile": "/home/erplibre/.ssh/id_ed25519",
            "identitiesonly": "yes",
            "stricthostkeychecking": "false",
            "userknownhostsfile": "/dev/null",
        }

    def test_a_plus_alias_becomes_a_resolved_target(self):
        cmd, contourne = self.todo._sshfs_command(
            "novipro_private+ERPLibre01", "/tmp/mnt", self._resolue()
        )
        self.assertTrue(contourne)
        self.assertIn("mathben@192.168.122.50:/", cmd)
        self.assertNotIn("+", cmd)

    def test_the_options_that_matter_travel_with_it(self):
        """Sans ProxyJump, la VM est injoignable ; sans StrictHostKeyChecking,
        une IP DHCP recyclée fait échouer le montage sur sa clé d'hôte."""
        cmd, _ = self.todo._sshfs_command("a+b", "/tmp/mnt", self._resolue())
        for attendu in (
            "-o ProxyJump=novipro_private",
            "-o Port=22",
            "-o IdentityFile=/home/erplibre/.ssh/id_ed25519",
            "-o IdentitiesOnly=yes",
            "-o StrictHostKeyChecking=false",
            "-o UserKnownHostsFile=/dev/null",
        ):
            self.assertIn(attendu, cmd)

    def test_options_ssh_reports_as_none_are_not_forwarded(self):
        """« ssh -G » écrit « proxyjump none » quand il n'y en a pas ; le
        transmettre ferait échouer ssh sur une valeur qu'il vient d'inventer.
        """
        cfg = dict(self._resolue(), proxyjump="none")
        cmd, _ = self.todo._sshfs_command("a+b", "/tmp/mnt", cfg)
        self.assertNotIn("ProxyJump", cmd)

    def test_an_unresolvable_alias_is_left_alone(self):
        """Mieux vaut la commande d'origine, qui échouera en le disant, qu'une
        cible inventée qui monterait la mauvaise machine."""
        cmd, contourne = self.todo._sshfs_command("a+b", "/tmp/mnt", {})
        self.assertEqual("sshfs -o follow_symlinks a+b:/ /tmp/mnt", cmd)
        self.assertFalse(contourne)

    def test_the_mount_point_stays_last(self):
        """La syntaxe de sshfs : cible puis point de montage. Une option glissée
        après monterait ailleurs."""
        cmd, _ = self.todo._sshfs_command("a+b", "/tmp/mnt", self._resolue())
        self.assertTrue(cmd.endswith(" /tmp/mnt"), cmd)


class TestDiagnostic(unittest.TestCase):
    def test_each_kind_of_failure_names_its_culprit(self):
        cas = (
            (
                "ssh: Could not resolve hostname zz: Name or service not known",
                "unknown host name: check HostName",
            ),
            (
                "ssh: connect to host x port 22: Connection timed out",
                "no answer: is the server up and reachable?",
            ),
            (
                "ssh: connect to host x port 22: No route to host",
                "no route: check the network or the ProxyJump",
            ),
            (
                "ssh: connect to host x port 22: Connection refused",
                "nothing listening on the SSH port",
            ),
            (
                "mathben@x: Permission denied (publickey).",
                "authentication refused: check User and key",
            ),
            (
                "Host key verification failed.",
                "host key changed for this address",
            ),
        )
        for stderr, attendu in cas:
            self.assertEqual(attendu, TODO._ssh_failure_hint(stderr), stderr)

    def test_an_unknown_error_is_not_guessed(self):
        """Rien à dire plutôt qu'un diagnostic inventé : la ligne brute de ssh
        sera affichée telle quelle."""
        self.assertEqual("", TODO._ssh_failure_hint("sshfs: fuse: bidule"))
        self.assertEqual("", TODO._ssh_failure_hint(""))


class TestFlux(unittest.TestCase):
    """Le parcours complet, exécuteur bouchonné."""

    def _todo(self, code, probe=(0, "")):
        todo = TODO.__new__(TODO)
        todo.lances = []
        exe = mock.Mock()

        def lance(cmd, **kw):
            todo.lances.append(cmd)
            return code

        exe.exec_command_live = lance
        todo.execute = exe
        todo._ssh_probe = lambda alias, timeout=8: probe
        todo._ssh_resolve = lambda alias: {
            "hostname": "192.168.122.50",
            "user": "mathben",
            "proxyjump": "novipro_private",
        }
        return todo

    def _joue(self, todo, config, selection="2"):
        chemin = _config(config)
        self.addCleanup(os.unlink, chemin)
        reponses = iter(["2", selection])
        crees = []
        vrai_makedirs = os.makedirs
        vrai_rmdir = os.rmdir

        def makedirs(path, **kw):
            crees.append(path)
            return vrai_makedirs(path, **kw)

        retires = []

        def rmdir(path):
            retires.append(path)
            return vrai_rmdir(path)

        out = io.StringIO()
        with mock.patch(
            "builtins.input", lambda *a: next(reponses, "")
        ), mock.patch(
            "os.path.expanduser",
            lambda p: chemin if p.endswith("config") else p,
        ), mock.patch(
            "os.makedirs", makedirs
        ), mock.patch(
            "os.rmdir", rmdir
        ):
            with contextlib.redirect_stdout(out):
                todo._configure_sshfs()
        return out.getvalue(), crees, retires

    def test_a_failed_mount_announces_nothing_mounted(self):
        """Le cœur du problème rapporté : « Monté sur … » après un code 1."""
        todo = self._todo(1)
        sortie, _crees, _retires = self._joue(todo, CONFIG, "2")
        self.assertNotIn(t("Mounted on: "), sortie)
        self.assertNotIn("fusermount", sortie)
        self.assertNotIn("nautilus", sortie)
        self.assertIn(t("sshfs mount failed."), sortie)

    def test_a_failed_mount_leaves_no_empty_directory(self):
        """Une tentative par jour pendant un mois laissait trente répertoires
        vides dans /tmp."""
        todo = self._todo(1)
        _s, crees, retires = self._joue(todo, CONFIG, "2")
        self.assertEqual(crees, retires)
        for chemin in retires:
            self.assertFalse(os.path.exists(chemin))

    def test_a_successful_mount_says_how_to_unmount(self):
        todo = self._todo(0)
        sortie, crees, retires = self._joue(todo, CONFIG, "2")
        self.assertIn(t("Mounted on: "), sortie)
        self.assertIn("fusermount -u", sortie)
        self.assertEqual([], retires)
        for chemin in crees:
            self.addCleanup(lambda p=chemin: os.path.isdir(p) and os.rmdir(p))

    def test_ssh_working_points_at_the_plus_not_at_the_network(self):
        """Quand ssh joint l'hôte, ce n'est pas le réseau : c'est sshfs qui a
        mal lu l'alias. Le message doit envoyer là, et donner la commande."""
        todo = self._todo(1, probe=(0, ""))
        # L'alias à « + » est le troisième de la config (après le rebond seul).
        sortie, _c, _r = self._joue(todo, CONFIG, "2")
        self.assertIn(
            t("SSH reaches this host: ~/.ssh/config is fine."), sortie
        )

    def test_ssh_failing_sends_to_the_config_or_the_server(self):
        todo = self._todo(
            1,
            probe=(
                255,
                "ssh: connect to host x port 22: Connection timed out",
            ),
        )
        sortie, _c, _r = self._joue(todo, CONFIG, "2")
        self.assertIn(t("no answer: is the server up and reachable?"), sortie)
        self.assertIn(
            t("Update ~/.ssh/config, or check the server is up."), sortie
        )

    def test_the_plus_alias_is_bypassed_before_being_run(self):
        """Le vrai correctif : la commande lancée ne contient plus le « + »."""
        todo = self._todo(0)
        # [1] novipro_private · [2] novipro_private+ERPLibre01 · [3] la VM
        _s, _c, _r = self._joue(todo, CONFIG, "2")
        lancee = todo.lances[0]
        self.assertIn("mathben@192.168.122.50:/", lancee)
        self.assertIn("-o ProxyJump=novipro_private", lancee)
        self.assertNotIn("+ERPLibre01", lancee)


if __name__ == "__main__":
    unittest.main(verbosity=1)
