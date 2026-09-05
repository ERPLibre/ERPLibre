#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les verbes de VM : ce qu'ils composent, sans toucher une machine.

Un verbe rend une CHAÎNE ; il ne l'exécute pas. C'est ce qui permet de
l'éprouver entièrement depuis une station et de la MONTRER avant de la
lancer — ce que le tableau de bord fait déjà pour la suppression.

La suppression est le verbe le plus dangereux du lot : ces épreuves portent
surtout sur son garde d'identité, parce qu'un garde qu'on ne sait pas
éprouver s'OUVRE le jour où il casse, au lieu de se fermer.
"""

import os
import subprocess
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.vm import backend as B  # noqa: E402
from script.vm import verbs as V  # noqa: E402


def _sans_qm(garde):
    """Le garde, « qm » remplacé par « true » : la sonde ne répond rien, le
    refus se déclenche, et c'est son MESSAGE qu'on veut lire."""
    return garde.replace(
        "qm config 101 2>/dev/null | sed -n 's/^name: //p' | head -1", "true"
    )


LOCALE = B.handle_of({"name": "essai", "uuid": "abc-123"})
DISTANTE = B.handle_of(
    {
        "name": "essai",
        "pve": {"vmid": 101, "target": "hote.exemple", "sudo": "sudo "},
    }
)


class TestLeGardeDIdentite(unittest.TestCase):
    def test_the_remote_guard_checks_the_name_behind_the_vmid(self):
        """Un VMID libéré est RÉATTRIBUÉ."""
        garde = V.identity_guard(DISTANTE)
        self.assertIn("qm config 101", garde)
        self.assertIn("REFUS", garde)
        self.assertIn("exit 1", garde)

    def test_the_local_guard_checks_the_uuid_behind_the_name(self):
        """Un nom de domaine se réemploie ; l'UUID naît et meurt avec lui."""
        garde = V.identity_guard(LOCALE)
        self.assertIn("domuuid", garde)
        self.assertIn("abc-123", garde)
        self.assertIn("exit 1", garde)

    def test_an_unarmed_handle_produces_no_guard(self):
        """Désarmement ASSUMÉ : mieux vaut la prudence d'avant que refuser
        toute opération sur un poste où la preuve n'a pas pu être relevée."""
        self.assertEqual("", V.identity_guard(LOCALE._replace(proof="")))
        self.assertEqual("", V.identity_guard(None))

    def test_a_name_carrying_a_substitution_is_never_run(self):
        """Le nom était interpolé BRUT dans le message du garde, donc relu
        par le shell : une substitution s'y exécutait à l'endroit précis où
        le garde annonce qu'il n'a rien fait — et sur l'hôte, sous
        élévation. La valeur piégée est inventée."""
        piege = "essai$(id -u)"
        garde = V.identity_guard(DISTANTE._replace(proof=piege))
        joue = subprocess.run(
            ["sh", "-c", _sans_qm(garde) + " exit 0"],
            capture_output=True,
            text=True,
        )
        self.assertIn(piege, joue.stdout)

    def test_a_quote_in_the_name_cannot_close_the_message(self):
        piege = 'essai"; touch /tmp/rien-de-reel; echo "'
        garde = V.identity_guard(DISTANTE._replace(proof=piege))
        joue = subprocess.run(
            ["sh", "-c", _sans_qm(garde) + " exit 0"],
            capture_output=True,
            text=True,
        )
        self.assertIn(piege, joue.stdout)
        self.assertNotIn("touch", joue.stderr)

    def test_the_remote_guard_refuses_a_reused_key_and_passes_the_right_one(
        self,
    ):
        """Le contrôle qui compte : le garde doit s'ARRÊTER. Il traverse
        deux « shlex.quote » avant d'atteindre un shell, et chaque niveau
        est une occasion de le casser — un garde cassé s'ouvre."""
        garde = V.identity_guard(DISTANTE)
        for vu, attendu in (("essai", 0), ("autre", 1)):
            with self.subTest(vu=vu):
                joue = subprocess.run(
                    [
                        "sh",
                        "-c",
                        f"qm() {{ echo 'name: {vu}'; }}; {garde} exit 0",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(attendu, joue.returncode, joue.stdout)

    def test_the_local_guard_refuses_a_reused_name(self):
        garde = V.identity_guard(LOCALE)
        for vu, attendu in (("abc-123", 0), ("def-456", 1)):
            with self.subTest(vu=vu):
                joue = subprocess.run(
                    [
                        "sh",
                        "-c",
                        f"virsh() {{ echo '{vu}'; }}; {garde} exit 0",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(attendu, joue.returncode, joue.stdout)

    def test_an_unknown_backend_says_so_instead_of_guessing(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.identity_guard(LOCALE._replace(backend="lima"))


class TestLaSuppression(unittest.TestCase):
    def test_the_guard_leads_the_remote_command(self):
        """Placé après, il refuserait une machine déjà détruite."""
        cmd = V.delete_command(DISTANTE)
        self.assertLess(cmd.index("REFUS"), cmd.index("qm destroy"))

    def test_the_guard_leads_the_local_command_too(self):
        cmd = V.delete_command(LOCALE, sudo="", uri="qemu:///system")
        self.assertLess(cmd.index("REFUS"), cmd.index("undefine"))

    def test_a_remote_delete_never_speaks_to_local_libvirt(self):
        """« virsh undefine <nom> » aurait effacé le domaine LOCAL
        homonyme — le même piège, avec la pire conséquence."""
        cmd = V.delete_command(DISTANTE)
        self.assertNotIn("virsh", cmd)
        self.assertIn("qm destroy 101", cmd)

    def test_keeping_the_disks_is_possible_on_both(self):
        """Contrôle positif : l'effacement des disques n'est pas fatal."""
        self.assertNotIn("--purge", V.delete_command(DISTANTE, False))
        self.assertNotIn("rm -f", V.delete_command(LOCALE, False))
        self.assertIn("--purge", V.delete_command(DISTANTE, True))
        self.assertIn("rm -f", V.delete_command(LOCALE, True))

    def test_the_local_delete_uses_the_uri_it_is_given(self):
        """Le module ne sonde pas la station : elle entre en paramètre."""
        cmd = V.delete_command(LOCALE, uri="qemu:///session")
        self.assertIn("qemu:///session", cmd)
        self.assertNotIn("qemu:///system", cmd)

    def test_the_local_delete_uses_the_sudo_it_is_given(self):
        self.assertNotIn("sudo virsh", V.delete_command(LOCALE, sudo=""))
        self.assertIn("sudo virsh", V.delete_command(LOCALE, sudo="sudo "))

    def test_no_identity_is_refused_rather_than_guessed(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.delete_command(None)

    def test_an_unknown_backend_is_refused(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.delete_command(LOCALE._replace(backend="lima"))


class TestLaCommandeSurLHote(unittest.TestCase):
    def test_it_goes_through_the_host_and_not_the_vm(self):
        """L'hôte est la seule autorité pour une VM distante."""
        self.assertIn("hote.exemple", V.host_command(DISTANTE, "qm list"))

    def test_the_jump_travels_when_there_is_one(self):
        avec = DISTANTE._replace(
            host=dict(DISTANTE.host, jump="bastion.exemple")
        )
        self.assertIn("-J bastion.exemple", V.host_command(avec, "qm list"))
        self.assertNotIn("-J", V.host_command(DISTANTE, "qm list"))

    def test_the_elevation_wraps_the_whole_sequence(self):
        """« sudo a && b » n'élèverait que le premier mot."""
        cmd = V.host_command(DISTANTE, "a && b")
        self.assertIn("sudo sh -c", cmd)

    def test_without_elevation_the_command_is_untouched(self):
        nu = DISTANTE._replace(host={"target": "hote.exemple"})
        self.assertNotIn("sh -c", V.host_command(nu, "qm list"))

    def test_a_tty_is_asked_for_only_when_wanted(self):
        self.assertIn("ssh -t ", V.host_command(DISTANTE, "x", tty=True))
        self.assertNotIn("ssh -t ", V.host_command(DISTANTE, "x"))


class TestIlNeSondeRien(unittest.TestCase):
    """Ce qui dépend de la station entre en paramètre.

    C'est ce qui garde le module utilisable par un backend qui n'existe pas
    encore, et éprouvable sans machine.
    """

    def test_it_imports_only_the_standard_library_and_its_own_package(self):
        import ast

        chemin = os.path.join(RACINE, "script", "vm", "verbs.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        racines = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                racines.update(a.name.split(".")[0] for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                racines.add(noeud.module)
        externes = {
            r
            for r in racines
            if not r.startswith("script.vm")
            and r.split(".")[0] not in sys.stdlib_module_names
        }
        self.assertTrue(racines, "aucun import lu : rien n'est prouvé")
        self.assertEqual(set(), externes)

    def test_it_neither_runs_nor_prints(self):
        import ast

        chemin = os.path.join(RACINE, "script", "vm", "verbs.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        noms = [
            n.func.id
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        self.assertTrue(noms, "aucun appel lu : rien n'est prouvé")
        for interdit in ("print", "input", "run", "system", "which"):
            self.assertNotIn(interdit, noms)


if __name__ == "__main__":
    unittest.main()
