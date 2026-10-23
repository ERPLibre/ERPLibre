#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La relecture d'adresse du lanceur détaché, et son avertissement.

Le lanceur relit l'adresse de la VM par virsh à chaque tour d'attente. Ce
que ces tests gardent :

- une VM pas encore démarrée fait échouer « domifaddr » sans que libvirt
  soit en cause : aucun avertissement ;
- une session ouverte avant l'ajout au groupe libvirt joint libvirt par
  « sg libvirt », sans tty ni mot de passe, et suit l'adresse ;
- seul un libvirt vraiment injoignable — virsh, sudo -n et sg refusés —
  écrit l'avertissement, une seule fois.

La commande est celle que _launch_one détacherait ; elle tourne sous bash
avec de faux ssh, virsh, sudo et sg.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_install_monitor as mon  # noqa: E402

FAUX_SSH = """#!/bin/sh
for dernier in "$@"; do :; done
case "$dernier" in
  *cloud-init*) echo "status: done" ;;
esac
exit 0
"""
# MODE : ok (tout répond), absent (la VM n'existe pas encore, libvirt
# répond), refus (libvirt injoignable sans le groupe). SG_ACTIF : le groupe
# a été pris par sg.
FAUX_VIRSH = """#!/bin/sh
echo "virsh $*" >> "$JOURNAL"
joint=1
[ "$MODE" = refus ] && [ -z "$SG_ACTIF" ] && joint=0
case "$*" in
  *" uri"*) [ $joint = 1 ] && echo qemu:///system && exit 0; exit 1 ;;
esac
[ $joint = 1 ] || exit 1
[ "$MODE" = absent ] && exit 1
case "$*" in
  *"--source lease"*) printf ' vnet0 52:54:00:aa:bb:cc ipv4 %s/24\\n' "$BAIL" ;;
  *"--source agent"*) [ -n "$AGENT" ] && printf ' eth0 - ipv4 %s/24\\n' "$AGENT" ;;
esac
exit 0
"""
FAUX_SG = """#!/bin/sh
echo "sg $*" >> "$JOURNAL"
[ "$SG_OK" = 1 ] || exit 1
SG_ACTIF=1 exec bash -c "$3"
"""
# Le newgrp d'util-linux, là où shadow ne fournit pas sg : il lit la commande
# sur son entrée.
FAUX_NEWGRP = """#!/bin/sh
echo "newgrp $*" >> "$JOURNAL"
[ "$NEWGRP_OK" = 1 ] || exit 1
SG_ACTIF=1 exec bash
"""


class TestRelectureDAdresse(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for nom, texte in (
            ("ssh", FAUX_SSH),
            ("virsh", FAUX_VIRSH),
            ("sg", FAUX_SG),
            ("newgrp", FAUX_NEWGRP),
        ):
            (self.bin / nom).write_text(texte)
            (self.bin / nom).chmod(0o755)

    def lance(
        self, mode, sg_ok=False, bail="10.0.0.5", agent="", newgrp_ok=False
    ):
        # Le faux sudo REFUSE, comme « sudo -n » sans tty : le PATH ci-dessous
        # perd la doublure du lanceur, la fonction pose la sienne.
        (self.bin / "sudo").write_text("#!/bin/sh\nexit 1\n")
        (self.bin / "sudo").chmod(0o755)
        log = self.base / "vm-a.log"
        log.write_text("")
        journal = self.base / "appels"
        journal.write_text("")
        with mock.patch.object(mon.subprocess, "Popen") as popen:
            mon._launch_one(
                "10.0.0.5", "true", str(log), name="vm-a", emulated=False
            )
        commande = popen.call_args[0][0][4]
        env = dict(
            os.environ,
            PATH=f"{self.bin}:/usr/bin:/bin",
            MODE=mode,
            SG_OK="1" if sg_ok else "",
            NEWGRP_OK="1" if newgrp_ok else "",
            BAIL=bail,
            AGENT=agent,
            JOURNAL=str(journal),
        )
        subprocess.run(
            ["bash", "-c", commande], env=env, timeout=60, check=False
        )
        return log.read_text(), journal.read_text()

    def avertit(self, texte):
        return "libvirt" in texte and mon.EXIT_MARKER in texte

    def test_a_reachable_libvirt_gives_no_warning(self):
        log, _ = self.lance("ok")
        self.assertNotIn("libvirt", log)
        self.assertIn("→ 10.0.0.5", log)

    def test_a_vm_not_started_yet_is_not_an_unreachable_libvirt(self):
        log, appels = self.lance("absent")
        self.assertNotIn("libvirt", log)
        # La question a bien été posée à libvirt, qui a répondu.
        self.assertIn("virsh --connect qemu:///system uri", appels)

    def test_a_session_without_the_group_goes_through_sg(self):
        log, appels = self.lance("refus", sg_ok=True, agent="10.0.0.9")
        self.assertNotIn("libvirt", log)
        self.assertIn("sg libvirt -c", appels)
        # L'adresse donnée par l'agent, joint par sg, est suivie.
        self.assertIn("→ 10.0.0.9", log)

    def test_without_sg_newgrp_reaches_libvirt(self):
        log, appels = self.lance("refus", newgrp_ok=True, agent="10.0.0.9")
        self.assertNotIn("libvirt", log)
        self.assertIn("newgrp libvirt", appels)
        self.assertIn("→ 10.0.0.9", log)

    def test_an_unreachable_libvirt_is_said_once(self):
        log, _ = self.lance("refus")
        lignes = [ligne for ligne in log.splitlines() if "libvirt" in ligne]
        self.assertEqual(1, len(lignes), log)
        self.assertIn(mon.EXIT_MARKER, log)


if __name__ == "__main__":
    unittest.main()
