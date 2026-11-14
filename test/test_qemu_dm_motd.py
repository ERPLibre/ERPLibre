#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le guide de connexion reste hors de l'ouverture de session graphique.

Sur Arch, pam_motd est dans /etc/pam.d/system-login, que GDM et LightDM
incluent : le guide arrive au greeter en message PAM, et le greeter GNOME le
tient un temps proportionnel à sa longueur avant de lancer la session. Le
bloc pose, juste avant pam_motd, une règle qui le saute pour les seuls
services des gestionnaires d'affichage.

Le bloc est EXÉCUTÉ sur une copie du fichier, avec les vrais grep et sed :
c'est la forme exacte du fichier produit qui compte pour PAM.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo.todo import TODO  # noqa: E402

# La pile de session d'Arch (pambase), telle que livrée.
SYSTEM_LOGIN = """\
#%PAM-1.0

auth       required   pam_shells.so
auth       include    system-auth

session    optional   pam_loginuid.so
session    include    system-auth
session    optional   pam_lastlog2.so      silent
session    optional   pam_motd.so
session    optional   pam_mail.so          dir=/var/spool/mail standard quiet
session    required   pam_env.so
"""

PL = "/etc/pam.d/system-login"


def _todo():
    return TODO.__new__(TODO)


class _Fichier:
    """Joue le bloc sur un fichier temporaire au lieu du vrai, avec un sudo
    qui exécute simplement sa commande."""

    def __init__(self, contenu):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pl = self.dir / "system-login"
        if contenu is not None:
            self.pl.write_text(contenu)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "sudo").write_text('#!/bin/bash\nexec "$@"\n')
        (bin_dir / "sudo").chmod(0o755)
        self.path = f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"

    def joue(self):
        cmd = _todo()._qemu_dm_motd_skip_cmd().replace(PL, str(self.pl))
        res = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            env=dict(os.environ, PATH=self.path),
            timeout=30,
        )
        return res

    def lignes(self):
        return self.pl.read_text().splitlines()

    def close(self):
        self.tmp.cleanup()


class TestMotdSkippedForDisplayManagers(unittest.TestCase):
    def setUp(self):
        self.f = _Fichier(SYSTEM_LOGIN)

    def tearDown(self):
        self.f.close()

    def test_the_rule_sits_right_before_pam_motd(self):
        """« success=1 » saute UNE ligne : la règle doit précéder pam_motd
        immédiatement, sinon elle sauterait autre chose."""
        res = self.f.joue()
        self.assertEqual(res.returncode, 0, res.stderr)
        lignes = self.f.lignes()
        i = next(n for n, l in enumerate(lignes) if "pam_motd.so" in l)
        regle = lignes[i - 1]
        self.assertTrue(regle.startswith("session"), regle)
        self.assertIn("[success=1 default=ignore]", regle)
        self.assertIn("pam_succeed_if.so", regle)
        self.assertTrue(regle.rstrip().endswith("quiet"), regle)

    def test_only_display_manager_services_are_named(self):
        """ssh (sshd) et la console (login) gardent le guide."""
        self.f.joue()
        regle = next(l for l in self.f.lignes() if "pam_succeed_if" in l)
        services = re.search(r"service in (\S+)", regle).group(1).split(":")
        self.assertIn("gdm-password", services)
        self.assertIn("lightdm", services)
        for garde in ("sshd", "login", "su", "sudo", "systemd-user"):
            self.assertNotIn(garde, services)

    def test_the_rest_of_the_stack_is_untouched(self):
        self.f.joue()
        sans = [l for l in self.f.lignes() if "pam_succeed_if" not in l]
        self.assertEqual(sans, SYSTEM_LOGIN.splitlines())

    def test_a_second_run_adds_nothing(self):
        self.f.joue()
        une = self.f.lignes()
        res = self.f.joue()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.f.lignes(), une)
        self.assertEqual(res.stdout, "")

    def test_it_says_what_it_did(self):
        from script.todo.todo_i18n import t

        res = self.f.joue()
        self.assertIn(
            t("connection guide kept out of the graphical login"), res.stdout
        )


class TestNothingToDoElsewhere(unittest.TestCase):
    def test_no_file_no_change_no_error(self):
        f = _Fichier(None)
        try:
            res = f.joue()
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(res.stdout + res.stderr, "")
            self.assertFalse(f.pl.exists())
        finally:
            f.close()

    def test_a_stack_without_pam_motd_is_left_alone(self):
        sans_motd = "".join(
            l for l in SYSTEM_LOGIN.splitlines(True) if "pam_motd" not in l
        )
        f = _Fichier(sans_motd)
        try:
            res = f.joue()
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(f.pl.read_text(), sans_motd)
        finally:
            f.close()


class TestWiredIntoTheDesktop(unittest.TestCase):
    def test_every_flavour_carries_it_before_the_greeter_starts(self):
        todo = _todo()
        bloc = todo._qemu_dm_motd_skip_cmd()
        for flavour in ("gnome", "cinnamon"):
            cmd = todo._qemu_desktop_remote_cmd(flavour, "deb", distro="arch")
            self.assertIn(bloc, cmd, flavour)
            self.assertLess(
                cmd.index(bloc),
                cmd.index("systemctl start display-manager"),
                flavour,
            )


if __name__ == "__main__":
    unittest.main()
