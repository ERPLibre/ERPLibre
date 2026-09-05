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
import shlex
import shutil
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


class TestLaConsole(unittest.TestCase):
    """Le seul recours quand SSH ne répond pas — donc le pire endroit pour
    se tromper de machine."""

    def test_a_remote_console_goes_through_the_host(self):
        """« virsh console <nom> » ouvrait celle du domaine LOCAL homonyme,
        la mauvaise machine, sans le dire."""
        ouverture = V.console(DISTANTE)
        self.assertIn("hote.exemple", ouverture.command)
        self.assertIn("qm terminal 101", ouverture.command)
        self.assertNotIn("virsh", ouverture.command)

    def test_a_local_console_speaks_to_libvirt(self):
        """Contrôle positif : la console locale existe toujours."""
        ouverture = V.console(LOCALE, sudo="", uri="qemu:///system")
        self.assertIn(
            "virsh --connect qemu:///system console", ouverture.command
        )
        self.assertIn("essai", ouverture.command)

    def test_a_remote_console_asks_for_a_tty(self):
        """Sans lui, la console n'a pas de clavier."""
        self.assertIn("ssh -t ", V.console(DISTANTE).command)

    def test_the_escape_sequence_is_not_the_same_on_both(self):
        """La donner fausse laisse l'utilisateur enfermé dans une console
        dont il ne sait plus sortir. C'est l'outil qui attache qui décide,
        pas l'écran."""
        self.assertNotEqual(
            V.console(DISTANTE).escape, V.console(LOCALE).escape
        )
        for handle in (DISTANTE, LOCALE):
            with self.subTest(backend=handle.backend):
                self.assertTrue(V.console(handle).escape)

    def test_the_label_names_the_machine_it_opens(self):
        """L'écran l'affiche avant d'attacher : c'est la dernière occasion
        de voir qu'on vise la mauvaise."""
        self.assertIn("hote.exemple", V.console(DISTANTE).label)
        self.assertIn("101", V.console(DISTANTE).label)
        self.assertIn("essai", V.console(LOCALE).label)

    def test_the_local_console_uses_the_uri_it_is_given(self):
        self.assertIn(
            "qemu:///session", V.console(LOCALE, uri="qemu:///session").command
        )

    def test_no_identity_is_refused_rather_than_guessed(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.console(None)

    def test_an_unknown_backend_is_refused(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.console(LOCALE._replace(backend="lima"))


class TestLAccesWeb(unittest.TestCase):
    """Une VM sur pont interne n'est pas routable d'ici."""

    AVEC_ADRESSE = B.pve_handle(
        {"vmid": 101, "target": "hote.exemple", "addr": "198.51.100.7"},
        "essai",
    )

    def test_a_reachable_address_needs_no_tunnel(self):
        acces = V.web_access(B.libvirt_handle("essai", ip="192.0.2.10"))
        self.assertEqual("http://192.0.2.10:8069", acces.url)
        self.assertEqual((), acces.tunnel)

    def test_an_internal_address_is_reached_through_a_tunnel(self):
        """Sans lui le navigateur ouvrait une page morte, et rien ne disait
        pourquoi."""
        acces = V.web_access(self.AVEC_ADRESSE)
        self.assertEqual("http://127.0.0.1:18069", acces.url)
        self.assertIn("-L", acces.tunnel)
        self.assertIn("18069:198.51.100.7:8069", acces.tunnel)
        self.assertIn("hote.exemple", acces.tunnel)

    def test_the_url_and_the_tunnel_always_agree(self):
        """Décidés séparément, ils pouvaient se contredire : une page en
        127.0.0.1 sans tunnel, ou l'inverse."""
        cas = (
            self.AVEC_ADRESSE,
            B.libvirt_handle("essai", ip="192.0.2.10"),
            B.pve_handle({"vmid": 101, "target": "hote.exemple"}, "essai"),
        )
        for handle in cas:
            with self.subTest(backend=handle.backend):
                acces = V.web_access(handle)
                boucle = acces.url.startswith("http://127.0.0.1")
                self.assertEqual(boucle, bool(acces.tunnel))

    def test_the_jump_travels_into_the_tunnel(self):
        avec = B.pve_handle(
            {
                "vmid": 101,
                "target": "hote.exemple",
                "addr": "198.51.100.7",
                "jump": "bastion.exemple",
            },
            "essai",
        )
        self.assertIn("-J", V.web_access(avec).tunnel)
        self.assertIn("bastion.exemple", V.web_access(avec).tunnel)

    def test_an_unknown_address_is_said_and_not_composed(self):
        """« http://None:8069 » est une page morte annoncée comme vivante."""
        acces = V.web_access(
            B.pve_handle({"vmid": 101, "target": "hote.exemple"}, "essai")
        )
        self.assertEqual("", acces.url)
        self.assertEqual((), acces.tunnel)

    def test_the_ports_are_the_ones_given(self):
        acces = V.web_access(self.AVEC_ADRESSE, port=19000, service=8070)
        self.assertEqual("http://127.0.0.1:19000", acces.url)
        self.assertIn("19000:198.51.100.7:8070", acces.tunnel)

    def test_the_tunnel_fails_loudly_rather_than_silently(self):
        """Sans ExitOnForwardFailure, ssh reste ouvert sur un port déjà
        pris, et la page s'ouvre sur le service de quelqu'un d'autre."""
        self.assertIn(
            "ExitOnForwardFailure=yes", V.web_access(self.AVEC_ADRESSE).tunnel
        )

    def test_no_identity_is_refused_rather_than_guessed(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.web_access(None)


class TestLaLigneSshVersLaVm(unittest.TestCase):
    """« s » ouvrait la mauvaise machine : un domaine LOCAL homonyme."""

    DISTANTE_AVEC_REBOND = B.pve_handle(
        {
            "target": "pve1.exemple",
            "jump": "bastion.exemple",
            "vmid": 101,
            "addr": "10.10.10.151",
        },
        "vm-a",
        alias="pve1+vm-a",
    )

    def test_a_local_vm_is_reached_directly(self):
        handle = B.libvirt_handle("vm-a", ip="198.51.100.118")
        ligne = V.ssh_prefix(handle)
        self.assertIn("erplibre@198.51.100.118", ligne)
        self.assertNotIn("-J", ligne)

    def test_a_remote_vm_goes_through_its_host(self):
        """Son adresse n'est routable que de là."""
        handle = B.pve_handle(
            {"target": "pve1.exemple", "vmid": 101, "addr": "10.10.10.151"},
            "vm-a",
        )
        ligne = V.ssh_prefix(handle)
        self.assertIn("-J pve1.exemple", ligne)
        self.assertIn("erplibre@10.10.10.151", ligne)

    def test_two_hops_are_separated_by_a_comma(self):
        """Répéter « -J » ne les accumule pas."""
        ligne = V.ssh_prefix(self.DISTANTE_AVEC_REBOND)
        self.assertIn("-J bastion.exemple,pve1.exemple", ligne)
        self.assertEqual(1, ligne.count("-J"))

    def test_ssh_itself_accepts_the_line_and_keeps_both_hops(self):
        """L'épreuve qui manquait. Le texte se relisait très bien ; ssh, lui,
        refusait la ligne entière — « Only a single -J option is permitted »,
        code 255 — et toute VM derrière un rebond était injoignable."""
        if not shutil.which("ssh"):
            raise unittest.SkipTest("ssh absent")
        ligne = V.ssh_prefix(self.DISTANTE_AVEC_REBOND)
        vu = subprocess.run(
            shlex.split(ligne.replace("ssh ", "ssh -G ", 1)),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, vu.returncode, vu.stderr)
        self.assertIn(
            "proxyjump bastion.exemple,pve1.exemple", vu.stdout.lower()
        )

    def test_without_a_routable_address_it_falls_back_to_the_alias(self):
        """Un hôte connu dont l'adresse interne reste inconnue : l'alias de
        ~/.ssh/config porte alors le chemin complet."""
        handle = B.pve_handle(
            {"target": "pve1.exemple"}, "vm-a", alias="pve1+vm-a"
        )
        self.assertIn("erplibre@pve1+vm-a", V.ssh_prefix(handle))
        self.assertNotIn("-J", V.ssh_prefix(handle))

    def test_the_user_is_the_one_given(self):
        handle = B.libvirt_handle("vm-a", ip="198.51.100.118")
        self.assertIn("root@198.51.100.118", V.ssh_prefix(handle, "root"))

    def test_the_options_lead_the_line(self):
        handle = B.libvirt_handle("vm-a", ip="198.51.100.118")
        ligne = V.ssh_prefix(handle, options="-o ConnectTimeout=8")
        self.assertTrue(ligne.startswith("ssh -o ConnectTimeout=8 "), ligne)

    def test_no_identity_is_refused_rather_than_guessed(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.ssh_prefix(None)


if __name__ == "__main__":
    unittest.main()
