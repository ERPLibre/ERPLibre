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

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

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

    def test_no_handle_at_all_is_a_refusal_and_not_a_disarming(self):
        """Les deux se ressemblent et ne sont pas la même chose. « Sa preuve
        manque » se constate sur une machine qu'on désigne ; « aucune
        machine désignée » est une faute de l'appelant, et la lui rendre
        comme un désarmement la lui cacherait."""
        with self.assertRaises(B.VerbNotImplemented):
            V.identity_guard(None)

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
            V.identity_guard(LOCALE._replace(backend="jamais-un-backend"))


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
            V.delete_command(LOCALE._replace(backend="jamais-un-backend"))


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
            V.console(LOCALE._replace(backend="jamais-un-backend"))


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

    def test_the_backend_without_ssh_is_told_where_to_go(self):
        """Le refus général dirait « backend inconnu », ce qui serait FAUX :
        il est parfaitement connu, il ne s'atteint simplement pas ainsi. Un
        refus qui se trompe de raison envoie chercher au mauvais endroit —
        c'est tout le sujet de ce dépôt."""
        with self.assertRaises(B.VerbNotImplemented) as pris:
            V.ssh_prefix(B.lima_handle("essai"))
        message = str(pris.exception)
        self.assertIn("exec_prefix", message)
        self.assertNotIn("inconnu", message)


class TestLAlimentation(unittest.TestCase):
    """La pause est le pire endroit pour se tromper de machine : rien ne
    casse, rien n'alerte, et la VM figée est celle qu'on n'a pas regardée."""

    def test_a_remote_vm_is_paused_on_its_own_host(self):
        cmd = V.power_command(DISTANTE, "suspend")
        self.assertIn("hote.exemple", cmd)
        self.assertIn("qm suspend 101", cmd)
        self.assertNotIn("virsh", cmd)

    def test_a_local_vm_is_paused_by_libvirt(self):
        """Contrôle positif : la pause locale existe toujours."""
        cmd = V.power_command(LOCALE, "suspend", uri="qemu:///system")
        self.assertIn("virsh --connect qemu:///system suspend", cmd)
        self.assertIn("essai", cmd)

    def test_both_actions_reach_both_backends(self):
        for action in V.POWER_ACTIONS:
            for handle in (DISTANTE, LOCALE):
                with self.subTest(action=action, backend=handle.backend):
                    self.assertIn(action, V.power_command(handle, action))

    def test_an_unknown_action_names_the_known_ones(self):
        """Composer « qm eteindre 101 » ferait échouer la VM en silence, au
        milieu d'un lot, sans dire laquelle."""
        with self.assertRaises(B.VerbNotImplemented) as pris:
            V.power_command(LOCALE, "eteindre")
        self.assertIn("suspend", str(pris.exception))

    def test_both_backends_answer_with_a_string(self):
        """Deux formes — argv ici, chaîne là-bas — obligeaient l'appelant à
        savoir laquelle il tenait, donc à connaître le backend."""
        for handle in (DISTANTE, LOCALE):
            with self.subTest(backend=handle.backend):
                self.assertIsInstance(V.power_command(handle, "suspend"), str)

    def test_a_name_that_would_split_the_command_cannot(self):
        """La chaîne part dans un shell : c'est son DÉCOUPAGE qui décide, et
        non la présence du texte. Relire la chaîne ne prouve rien — un nom
        cité contient le piège sans l'exécuter."""
        piege = B.libvirt_handle("vm; touch /tmp/rien-de-reel")
        cmd = V.power_command(piege, "suspend")
        mots = subprocess.run(
            ["bash", "-c", cmd.replace("virsh ", "printf '%s\\n' ", 1)],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.splitlines()
        self.assertIn("vm; touch /tmp/rien-de-reel", mots)
        self.assertEqual(4, len(mots), mots)

    def test_no_identity_is_refused_rather_than_guessed(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.power_command(None, "suspend")

    def test_an_unknown_backend_is_refused(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.power_command(
                LOCALE._replace(backend="jamais-un-backend"), "suspend"
            )


class TestArmerLaPreuve(unittest.TestCase):
    """Le seul instant où l'on sait que ce nom désigne cette machine."""

    def test_a_local_vm_gets_its_uuid_from_the_probe(self):
        vus = []
        arme = V.arm(
            B.libvirt_handle("essai"),
            probe=lambda nom: vus.append(nom) or "abc-123",
        )
        self.assertEqual(["essai"], vus)
        self.assertEqual("abc-123", arme.proof)
        self.assertTrue(B.is_armed(arme))

    def test_a_remote_vm_needs_no_probe_at_all(self):
        """Sa preuve est son nom : elle est déjà là."""

        def refus(nom):
            raise AssertionError("la sonde ne doit pas être appelée")

        arme = V.arm(DISTANTE, probe=refus)
        self.assertEqual(DISTANTE, arme)

    def test_an_existing_proof_is_not_probed_again(self):
        def refus(nom):
            raise AssertionError("la sonde ne doit pas être appelée")

        self.assertEqual(LOCALE, V.arm(LOCALE, probe=refus))

    def test_a_silent_probe_leaves_it_disarmed_rather_than_failing(self):
        """Mieux vaut la protection d'avant que refuser de créer la
        machine."""
        arme = V.arm(B.libvirt_handle("essai"), probe=lambda nom: "")
        self.assertEqual("", arme.proof)
        self.assertFalse(B.is_armed(arme))

    def test_a_nameless_remote_vm_is_not_probed_locally_either(self):
        """Sa preuve manque, mais la sonde locale répondrait sur le VMID —
        et un « 101 » n'est pas un UUID de domaine d'ici."""

        def refus(cle):
            raise AssertionError(f"sonde locale appelée sur « {cle} »")

        nu = B.pve_handle({"vmid": 101, "target": "hote.exemple"})
        self.assertFalse(B.is_armed(nu))
        self.assertEqual(nu, V.arm(nu, probe=refus))

    def test_without_a_probe_nothing_is_invented(self):
        nu = B.libvirt_handle("essai")
        self.assertEqual(nu, V.arm(nu))

    def test_no_identity_is_refused_rather_than_guessed(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.arm(None)


class TestEcrireEtRelireLaMemeIdentite(unittest.TestCase):
    """`identity_fields` écrit ce que `handle_of` lit. Les deux se font
    face : écrite d'une façon et relue d'une autre, une identité désigne
    tranquillement autre chose."""

    def entree(self, handle):
        """L'entrée de manifeste minimale, telle que l'écrivain la compose."""
        entree = {
            "name": handle.name,
            "ip": handle.alias or handle.address,
        }
        entree.update(V.identity_fields(handle))
        return entree

    def test_a_remote_identity_survives_the_round_trip(self):
        handle = B.pve_handle(
            {"vmid": 101, "target": "hote.exemple", "addr": "198.51.100.7"},
            "essai",
            alias="hote+essai",
        )
        self.assertEqual(handle, B.handle_of(self.entree(handle)))

    def test_a_local_identity_survives_the_round_trip(self):
        handle = B.libvirt_handle("essai", uuid="abc-123", ip="192.0.2.10")
        self.assertEqual(handle, B.handle_of(self.entree(handle)))

    def test_a_disarmed_identity_survives_too(self):
        """Un manifeste écrit sans preuve doit se relire tel quel, et non
        se retrouver armé par accident."""
        handle = B.libvirt_handle("essai", ip="192.0.2.10")
        relu = B.handle_of(self.entree(handle))
        self.assertEqual(handle, relu)
        self.assertFalse(B.is_armed(relu))

    def test_the_written_fields_are_the_ones_the_reader_looks_for(self):
        self.assertIn("uuid", V.identity_fields(LOCALE))
        self.assertIn("pve", V.identity_fields(DISTANTE))

    def test_an_unknown_backend_writes_nothing_and_says_so(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.identity_fields(LOCALE._replace(backend="jamais-un-backend"))


class TestLeCanalDExecution(unittest.TestCase):
    """Par où le script détaché entre dans la VM pour y travailler."""

    DISTANTE_COMPLETE = B.handle_of(
        {
            "name": "vm-a",
            "ip": "pve1+vm-a",
            "pve": {"vmid": 101, "target": "pve1", "addr": "10.10.10.151"},
        }
    )

    def test_a_local_vm_is_entered_by_its_address(self):
        handle = B.libvirt_handle("vm-a", ip="192.0.2.10")
        self.assertEqual("192.0.2.10", V.exec_address(handle))

    def test_a_remote_vm_is_entered_by_its_alias(self):
        """Son adresse interne n'est routable que depuis l'hôte : l'attendre
        d'ici, c'est attendre vingt minutes pour rien."""
        self.assertEqual("pve1+vm-a", V.exec_address(self.DISTANTE_COMPLETE))

    def test_the_entry_address_is_not_the_service_address(self):
        """Les deux vivent dans la même fiche, à un champ près."""
        self.assertNotEqual(
            V.exec_address(self.DISTANTE_COMPLETE),
            self.DISTANTE_COMPLETE.address,
        )

    def test_a_remote_vm_without_an_alias_falls_back_on_its_address(self):
        """Mieux vaut essayer que ne rien tenter du tout."""
        handle = B.pve_handle(
            {"vmid": 101, "target": "pve1", "addr": "10.10.10.151"}, "vm-a"
        )
        self.assertEqual("10.10.10.151", V.exec_address(handle))

    def test_the_prefix_carries_the_account(self):
        """Sans lui, ssh se connecte sous le compte local de la station."""
        self.assertIn("erplibre@", V.exec_prefix(LOCALE))
        self.assertIn("root@", V.exec_prefix(LOCALE, user="root"))

    def test_the_address_stays_a_shell_variable(self):
        """Figée ici, elle ne se ré-résout plus : le script détaché suit un
        bail qui bouge, et une adresse morte ferait attendre en vain."""
        handle = B.libvirt_handle("vm-a", ip="192.0.2.10")
        prefixe = V.exec_prefix(handle)
        self.assertIn("$ip", prefixe)
        self.assertNotIn("192.0.2.10", prefixe)

    def test_the_options_land_before_the_target(self):
        prefixe = V.exec_prefix(LOCALE, options="-o BatchMode=yes")
        self.assertTrue(prefixe.startswith("ssh -o BatchMode=yes "), prefixe)

    def test_no_identity_is_refused_rather_than_guessed(self):
        for verbe in (V.exec_address, V.exec_prefix):
            with self.subTest(verbe=verbe.__name__):
                with self.assertRaises(B.VerbNotImplemented):
                    verbe(None)

    def test_an_unknown_backend_has_no_channel_yet(self):
        """Un backend qui n'a pas déclaré comment on entre chez lui doit le
        DIRE : composer un « ssh » au hasard le ferait joindre autre chose."""
        with self.assertRaises(B.VerbNotImplemented):
            V.exec_prefix(LOCALE._replace(backend="jamais-un-backend"))


class TestLesVieuxManifestesSOuvrentEncore(unittest.TestCase):
    """Le suivi se rouvre sur un manifeste qui peut avoir des semaines.

    Il a été écrit avant que rien de tout ceci n'existe : ni UUID, ni
    adresse interne, ni alias distinct. Refuser de le lire, ou le lire de
    travers, perdrait le suivi d'une installation en cours.
    """

    ANCIENS = (
        ("locale nue", {"name": "vm-a", "ip": "192.0.2.10"}),
        (
            "locale armée",
            {"name": "vm-b", "ip": "192.0.2.11", "uuid": "abc-123"},
        ),
        (
            "distante sans adresse interne",
            {
                "name": "vm-c",
                "ip": "pve1+vm-c",
                "pve": {"target": "pve1", "vmid": 7},
            },
        ),
    )

    def test_every_old_shape_still_yields_a_usable_channel(self):
        self.assertEqual(3, len(self.ANCIENS))
        for nom, entree in self.ANCIENS:
            with self.subTest(forme=nom):
                handle = B.handle_of(entree)
                self.assertIsNotNone(handle)
                self.assertEqual(entree["ip"], V.exec_address(handle))
                self.assertIn("$ip", V.exec_prefix(handle))

    def test_an_old_local_entry_is_refreshed_and_a_remote_one_is_not(self):
        """C'est ce qui décide de ré-résoudre par virsh, et se tromper y
        fait installer sur le domaine local homonyme."""
        self.assertTrue(B.resolves_locally(B.handle_of(self.ANCIENS[0][1])))
        self.assertFalse(B.resolves_locally(B.handle_of(self.ANCIENS[2][1])))


class TestLeBackendSansAdresse(unittest.TestCase):
    """Joindre une VM par son NOM, sans bail à relire.

    C'est le seul apport de ce backend sur un hôte qui a déjà libvirt, et
    c'est celui qui compte là où il n'y a aucun réseau d'hyperviseur à
    interroger.

    RIEN ICI N'A TOURNÉ contre un vrai « limactl » : ces épreuves tiennent ce
    qu'on COMPOSE, pas ce que l'outil en fait. La confrontation est dans
    `long_test/`.
    """

    LIMA = B.lima_handle("essai")

    def test_it_is_entered_by_its_name(self):
        self.assertEqual("essai", V.exec_address(self.LIMA))

    def test_its_channel_names_no_address_at_all(self):
        prefixe = V.exec_prefix(self.LIMA)
        self.assertNotIn("$ip", prefixe)
        self.assertNotIn("ssh", prefixe)
        self.assertIn("essai", prefixe)

    def test_the_composed_line_splits_into_the_expected_words(self):
        """« limactl shell » exécute des ARGUMENTS : sans « bash -c », une
        suite arriverait comme une liste de mots. On fait découper la ligne
        par un vrai shell plutôt que de relire la chaîne."""
        suite = "a && b || c"
        ligne = f"{V.exec_prefix(self.LIMA)} {shlex.quote(suite)}"
        mots = subprocess.run(
            ["bash", "-c", ligne.replace("limactl ", "printf '%s\\n' ", 1)],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.splitlines()
        self.assertEqual(["shell", "essai", "--", "bash", "-c", suite], mots)

    def test_a_name_that_would_split_the_line_cannot(self):
        piege = B.lima_handle("essai; touch /tmp/rien-de-reel")
        self.assertNotIn(
            "; touch /tmp/rien-de-reel bash", V.exec_prefix(piege)
        )
        mots = subprocess.run(
            [
                "bash",
                "-c",
                V.exec_prefix(piege).replace("limactl ", "printf '%s\\n' ", 1),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.splitlines()
        self.assertIn("essai; touch /tmp/rien-de-reel", mots)

    def test_its_identity_survives_the_round_trip(self):
        entree = {"name": "essai", "ip": ""}
        entree.update(V.identity_fields(self.LIMA))
        self.assertEqual(self.LIMA, B.handle_of(entree))

    def test_it_is_disarmed_and_says_so(self):
        """Un nom d'instance se réutilise. Fabriquer une preuve serait pire
        que de dire qu'il n'y en a pas : la suppression retombe alors sur la
        confirmation à deux mains, ce qui est la protection d'avant."""
        self.assertFalse(B.is_armed(self.LIMA))
        self.assertEqual("", V.identity_guard(self.LIMA))

    def test_the_verbs_it_cannot_do_yet_say_so(self):
        """« pas encore » se distingue d'une panne : l'écran peut retirer
        l'entrée proprement au lieu d'envoyer chercher ce qui ne va pas."""
        for verbe, args in (
            (V.delete_command, ()),
            (V.console, ()),
            (V.power_command, ("suspend",)),
            (V.host_command, ("echo",)),
        ):
            with self.subTest(verbe=verbe.__name__):
                with self.assertRaises(B.VerbNotImplemented):
                    verbe(self.LIMA, *args)


class TestCeQuiATourneContreUneVraieMachine(unittest.TestCase):
    """« Non éprouvé » ne veut pas dire douteux : il veut dire NON
    CONFRONTÉ. Un écran qui ne le dit pas laisse croire l'inverse."""

    def test_the_two_hypervisors_are_proven(self):
        self.assertTrue(B.is_proven(B.LIBVIRT))
        self.assertTrue(B.is_proven(B.PVE))

    def test_the_new_backend_is_not(self):
        self.assertFalse(B.is_proven(B.LIMA))

    def test_an_unknown_backend_is_not_proven_by_default(self):
        """Le doute penche du côté qui ne promet rien."""
        self.assertFalse(B.is_proven("jamais-un-backend"))

    def test_every_backend_of_the_vocabulary_has_an_answer(self):
        for nom in B.BACKENDS:
            with self.subTest(backend=nom):
                self.assertIn(nom, B.PROVEN)


class TestLaLigneQuUnHumainRecopie(unittest.TestCase):
    """La TROISIÈME forme, que `ssh_prefix` nommait déjà en creux.

    Son propre message le dit : « la forme diffère selon qu'on veut une
    session ou une commande ». `exec_prefix` rend la commande — il finit par
    « bash -c » — et le recopier ouvrirait un shell qui attend une commande
    qui ne vient jamais. Il manquait le verbe de la SESSION, et le tableau
    de bord composait donc « ssh compte@… » à la main pour toute machine, y
    compris celles qui ne s'atteignent pas par ssh.
    """

    LIMA = B.lima_handle("essai")
    LIBVIRT = B.libvirt_handle("vm-locale", uuid="u-u-i-d", ip="192.0.2.10")

    def test_an_instance_is_entered_by_its_own_tool(self):
        self.assertEqual("limactl shell essai", V.connect_command(self.LIMA))

    def test_a_local_vm_is_entered_by_ssh(self):
        """Le CONTRASTE : sans lui, une épreuve qui cherche « limactl »
        passerait aussi sur un verbe devenu constant."""
        ligne = V.connect_command(self.LIBVIRT)
        self.assertIn("ssh ", ligne)
        self.assertIn("192.0.2.10", ligne)
        self.assertNotIn("limactl", ligne)

    def test_the_session_form_carries_nothing_a_human_cannot_use(self):
        """LES DEUX FORMES DIFFÈRENT AUTREMENT SELON LE BACKEND, et c'est
        pourquoi un seul verbe ne pouvait pas les rendre.

        Sur l'instance, la commande finit par « bash -c » : recopiée, elle
        ouvre un shell qui attend une commande qui ne vient jamais. Sur une
        VM locale, elle porte « $ip » — une VARIABLE de shell que
        l'enveloppe détachée définit, et qui ne vaut rien dans le terminal
        de qui recopie.
        """
        self.assertNotIn("bash -c", V.connect_command(self.LIMA))
        self.assertIn("bash -c", V.exec_prefix(self.LIMA))
        self.assertNotIn("$ip", V.connect_command(self.LIBVIRT))
        self.assertIn("$ip", V.exec_prefix(self.LIBVIRT))

    def test_the_session_form_names_a_real_target(self):
        """C'est la seule chose qu'un tableau de bord peut afficher pour
        qu'on la recopie."""
        self.assertIn("192.0.2.10", V.connect_command(self.LIBVIRT))
        self.assertIn("essai", V.connect_command(self.LIMA))

    def test_it_answers_where_ssh_prefix_refuses(self):
        """C'est tout l'objet du verbe : le backend sans adresse a bien une
        façon d'entrer, et il n'y a rien à refuser."""
        with self.assertRaises(B.VerbNotImplemented):
            V.ssh_prefix(self.LIMA)
        self.assertTrue(V.connect_command(self.LIMA))

    def test_no_identity_is_no_line(self):
        with self.assertRaises(B.VerbNotImplemented):
            V.connect_command(None)

    def test_an_unknown_backend_is_refused_and_not_guessed(self):
        """Composer une ligne ssh pour un quatrième nom donnerait une
        commande visant une machine dont personne n'a dit qu'elle en
        acceptait une."""
        inconnu = self.LIBVIRT._replace(backend="jamais-vu")
        with self.assertRaises(B.VerbNotImplemented):
            V.connect_command(inconnu)

    def test_the_tool_name_is_written_in_one_place(self):
        """Ce fichier le nommait en dur DEUX fois — la session et la
        commande — et deux littéraux voisins cessent de correspondre au
        premier ajustement. Le module de l'outil le nomme, lui."""
        import os

        from code_literals import literals_in_file

        chemin = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "script",
            "vm",
            "verbs.py",
        )
        litteraux = literals_in_file(chemin, "limactl")
        self.assertEqual([], litteraux, litteraux)

    def test_both_forms_agree_on_which_instance(self):
        """Une session ouverte sur une instance et une commande jouée sur
        une autre serait le pire des deux mondes."""
        session = V.connect_command(self.LIMA)
        commande = V.exec_prefix(self.LIMA)
        self.assertTrue(commande.startswith(session), (session, commande))


if __name__ == "__main__":
    unittest.main()
