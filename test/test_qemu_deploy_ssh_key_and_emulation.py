#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Clé SSH d'un déploiement QEMU, et avertissement d'émulation du journal.

Une spec qui crée des VM puis les suit par SSH exige une clé : le suivi
sonde en BatchMode, où le mot de passe n'est jamais proposé. Sans clé, la
clé de ~/.ssh est générée avant toute création ; une clé nommée mais
inutilisable fait refuser le déploiement.

Le journal d'installation n'annonce une attente « normale » que pour une
VM émulée : en natif, une attente longue signale un vrai blocage.
"""

import contextlib
import io
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import qemu_install_monitor as mon  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

# Telle qu'elle paraît dans le script : citée pour le shell.
MSG_SLOW = shlex.quote(
    "   " + t("(an emulated architecture can be slow; this is normal)")
)


def _todo():
    """TODO sans son __init__ : ses vraies méthodes de clé SSH, rien
    d'autre."""
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    return TODO.__new__(TODO)


class _FausseGeneration:
    """`ssh-keygen` remplacé : crée la paire demandée par « -f », dans le
    HOME de l'essai, et compte ses appels."""

    def __init__(self):
        self.appels = 0

    def __call__(self, argv, *a, **k):
        self.appels += 1
        priv = argv[argv.index("-f") + 1]
        Path(priv).write_text("privée\n")
        Path(f"{priv}.pub").write_text("ssh-ed25519 AAAA essai\n")
        return subprocess.CompletedProcess(argv, 0, "", "")


def _spec(**kw):
    spec = {
        "vms": [{"name": "vm-essai", "arch": "amd64"}],
        "existing": [],
        "ssh_key": "",
        "install": {"branch": "develop", "cmd": "make x", "prod": False},
        "monitor": True,
        "add_ssh_config": True,
        "parallelism": 1,
    }
    spec.update(kw)
    return spec


class TestSpecSshKey(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patch = mock.patch.dict(os.environ, {"HOME": tmp.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.keygen = _FausseGeneration()
        patch = mock.patch("subprocess.run", self.keygen)
        patch.start()
        self.addCleanup(patch.stop)
        self.menu = _todo()

    def _assure(self, spec):
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            ok = self.menu._qemu_ensure_spec_ssh_key(spec)
        return ok, sortie.getvalue()

    def test_sans_cle_elle_est_generee_avant_le_deploiement(self):
        spec = _spec()
        ok, _ = self._assure(spec)
        self.assertTrue(ok)
        self.assertEqual(1, self.keygen.appels)
        self.assertEqual(
            str(self.home / ".ssh" / "id_ed25519.pub"), spec["ssh_key"]
        )
        # La clé privée correspondante est celle que présentera le suivi.
        self.assertEqual(
            str(self.home / ".ssh" / "id_ed25519"),
            self.menu._ssh_private_key(spec["ssh_key"]),
        )

    def test_une_cle_existante_est_reprise_sans_generation(self):
        ssh = self.home / ".ssh"
        ssh.mkdir()
        (ssh / "id_rsa").write_text("privée\n")
        (ssh / "id_rsa.pub").write_text("ssh-rsa AAAA essai\n")
        spec = _spec()
        ok, _ = self._assure(spec)
        self.assertTrue(ok)
        self.assertEqual(0, self.keygen.appels)
        self.assertEqual(str(ssh / "id_rsa.pub"), spec["ssh_key"])

    def test_une_cle_nommee_introuvable_refuse_le_deploiement(self):
        spec = _spec(ssh_key="~/.ssh/cle_inventee.pub")
        deploie = mock.Mock()
        self.menu._qemu_deploie_spec = deploie
        with contextlib.redirect_stdout(io.StringIO()):
            self.menu._qemu_run_spec(spec)
        deploie.assert_not_called()
        self.assertEqual(0, self.keygen.appels)

    def test_une_cle_publique_sans_cle_privee_est_refusee(self):
        ssh = self.home / ".ssh"
        ssh.mkdir()
        (ssh / "seule.pub").write_text("ssh-ed25519 AAAA essai\n")
        ok, sortie = self._assure(_spec(ssh_key=str(ssh / "seule.pub")))
        self.assertFalse(ok)
        self.assertIn("seule.pub", sortie)

    def test_une_generation_ratee_refuse_le_deploiement(self):
        self.menu._ssh_ensure_key = lambda: ""
        ok, _ = self._assure(_spec())
        self.assertFalse(ok)

    def test_rien_a_suivre_par_ssh_ne_demande_aucune_cle(self):
        spec = _spec(install=None, monitor=False)
        ok, _ = self._assure(spec)
        self.assertTrue(ok)
        self.assertEqual("", spec["ssh_key"])
        self.assertEqual(0, self.keygen.appels)

    def test_sans_vm_a_creer_aucune_cle_nest_exigee(self):
        ok, _ = self._assure(_spec(vms=[], existing=["vm-essai"]))
        self.assertTrue(ok)
        self.assertEqual(0, self.keygen.appels)


class TestEmulation(unittest.TestCase):
    def test_meme_architecture_nest_pas_emulee(self):
        for vm, hote in (
            ("s390x", "s390x"),
            ("amd64", "x86_64"),
            ("arm64", "aarch64"),
        ):
            with self.subTest(vm=vm, hote=hote):
                self.assertFalse(mon.is_emulated(vm, hote))

    def test_autre_architecture_est_emulee(self):
        self.assertTrue(mon.is_emulated("s390x", "x86_64"))
        self.assertTrue(mon.is_emulated("arm64", "x86_64"))

    def test_architecture_inconnue_nest_pas_declaree_emulee(self):
        self.assertFalse(mon.is_emulated(None, "x86_64"))
        self.assertFalse(mon.is_emulated("", "x86_64"))


class TestWrapper(unittest.TestCase):
    """Le script du lanceur, capturé sans rien exécuter."""

    def _wrapper(self, **kw):
        vus = {}

        def faux_popen(argv, *a, **k):
            vus["argv"] = argv

        with mock.patch.object(mon.subprocess, "Popen", faux_popen):
            mon._launch_one("cible", "true", "/dev/null", "vm-essai", **kw)
        return vus["argv"][-1]

    def test_natif_sans_avertissement_de_lenteur(self):
        self.assertNotIn(MSG_SLOW, self._wrapper(emulated=False))

    def test_emule_avec_avertissement_de_lenteur(self):
        self.assertIn(MSG_SLOW, self._wrapper(emulated=True))

    def test_la_cle_privee_est_presentee_par_chaque_ssh(self):
        script = self._wrapper(identity="/srv/essai/cle privee")
        self.assertTrue(
            script.startswith(
                "ssh() { command ssh -i '/srv/essai/cle privee' \"$@\"; }; "
            )
        )

    def test_sans_cle_ssh_garde_son_choix(self):
        self.assertNotIn("ssh() {", self._wrapper())

    def test_le_lanceur_juge_l_emulation_par_vm(self):
        recus = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with (
            mock.patch.object(mon, "session_dir", lambda: Path(tmp.name)),
            mock.patch.object(mon.platform, "machine", lambda: "s390x"),
            mock.patch.object(
                mon, "_launch_one", lambda *a, **k: recus.append(k)
            ),
        ):
            mon.launch_installs(
                [
                    {"name": "a", "ip": "192.0.2.1", "arch": "s390x"},
                    {"name": "b", "ip": "192.0.2.2", "arch": "amd64"},
                ],
                "",
                "true",
                identity="/srv/essai/cle",
            )
        self.assertEqual([False, True], [k["emulated"] for k in recus])
        self.assertEqual({"/srv/essai/cle"}, {k["identity"] for k in recus})


if __name__ == "__main__":
    unittest.main()
