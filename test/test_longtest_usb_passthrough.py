#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long du passage USB d'un deck simulé (long_test/usb_passthrough.py).

Lui charge des modules du noyau, écrit dans /etc et crée une Debian ;
ceux-ci tiennent ses parties pures en quelques millisecondes :

- les noms des domaines, le XML du domaine sans système ;
- le gadget configfs : ses écritures, et le script sh qui les fait, joué
  pour de vrai sous un dossier temporaire à la place de configfs ;
- les dépendances entre étapes, le verdict et le code de sortie ;
- les lectures de « info usb », du sysfs de l'invité, des unités ;
- la copie des modules que plugged_decks() charge dans l'invité, importée
  seule par un interpréteur isolé ;
- --dry-run et « --detruire --dry-run », menés sans rien lancer ;
- l'inscription au verrou des tests longs et au menu.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "long_test"))
sys.path.insert(0, str(RACINE))

import descente  # noqa: E402
import usb_passthrough as up  # noqa: E402

from script.todo import qemu_usb as qu  # noqa: E402

SCRIPT = RACINE / "long_test" / "usb_passthrough.py"

# Une sortie de « info usb » telle que QEMU l'écrit : un deck passé, une
# tablette, deux emplacements de redirection SPICE.
INFO_USB = """\
  Device 0.1, Port 1, Speed 480 Mb/s, Product QEMU USB Tablet, ID: input0
  Device 0.2, Port 2, Speed 12 Mb/s, Product Stream Deck MK.2, ID: hostdev0
  Device 0.0, Port 3, Speed 12 Mb/s, Product USB Redirection Device, ID: redir0
  Device 0.0, Port 4, Speed 12 Mb/s, Product USB Redirection Device, ID: redir1
"""


def _mener(*args, maison):
    """mener() dans ce processus, sur un HOME vide, sans verrou ni
    sous-processus réel. Rend (code, sortie, appels de subprocess.run)."""
    appels = []

    def faux_run(argv, *a, **k):
        appels.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, "", "")

    sortie = io.StringIO()
    with (
        mock.patch.dict(os.environ, {"HOME": maison}),
        mock.patch.object(up, "autre_descente", lambda: []),
        mock.patch.object(up.subprocess, "run", faux_run),
        contextlib.redirect_stdout(sortie),
    ):
        code = up.mener(list(args))
    return code, sortie.getvalue(), appels


class LesNoms(unittest.TestCase):
    def test_each_domain_names_the_run_and_its_role(self):
        noms = up.noms("20260101-000000")
        self.assertEqual(len(set(noms.values())), 3)
        for nom in noms.values():
            with self.subTest(nom=nom):
                self.assertTrue(nom.startswith(up.NOM_BASE + "-"))
                self.assertTrue(nom.endswith("-20260101-000000"))
                self.assertRegex(nom, r"^[a-z0-9-]+$")
        self.assertIn(f"{up.DISTRO}-{up.VERSION}", noms["invite"])

    def test_two_runs_never_share_a_name(self):
        a, b = up.noms("20260101-000000"), up.noms("20260101-000001")
        self.assertFalse(set(a.values()) & set(b.values()))


class LeDomaineSansSysteme(unittest.TestCase):
    def test_it_has_a_usb_controller_vnc_and_no_disk(self):
        xml = up.xml_domaine_nu("usb-pt-meca-x")
        racine = ET.fromstring(xml)
        self.assertEqual(racine.findtext("name"), "usb-pt-meca-x")
        self.assertIsNone(racine.find("./devices/disk"))
        self.assertIsNone(racine.find("./devices/interface"))
        etat = qu.usb_state(xml)
        self.assertTrue(qu.has_usb_controller(etat))
        self.assertEqual(etat["graphics"], ["vnc"])
        vnc = racine.find("./devices/graphics")
        self.assertEqual(vnc.get("listen"), "127.0.0.1")

    def test_spice_can_be_added_to_it(self):
        """L'étape 3 part de ce XML : le plan SPICE doit s'y appliquer."""
        plan = qu.spice_usbredir_plan(
            up.xml_domaine_nu("d"), "d", allow_vendors=(up.VID,)
        )
        self.assertEqual(len(plan), 1)
        etat = qu.usb_state(plan[0]["xml"])
        self.assertTrue(qu.spice_first(etat))
        self.assertTrue(qu.usbredir_ready(etat))

    def test_the_name_is_escaped(self):
        racine = ET.fromstring(up.xml_domaine_nu("a<b&c"))
        self.assertEqual(racine.findtext("name"), "a<b&c")


class LeGadget(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp(prefix="usb-pt-configfs-")
        self.addCleanup(shutil.rmtree, self.racine, True)

    def _jouer(self, script):
        return subprocess.run(
            ["sh", "-s"], input=script, capture_output=True, text=True
        )

    def test_plugging_is_the_last_write(self):
        ops = up.operations_gadget("dummy_udc.0")
        self.assertEqual(ops[-1][0], "ecrire")
        self.assertTrue(ops[-1][1].endswith("/UDC"))
        self.assertEqual(ops[-1][2], b"dummy_udc.0\n")

    def test_the_script_writes_every_byte(self):
        """Joué pour de vrai, sous un dossier temporaire : textes, série,
        descripteur binaire et lien de la fonction."""
        fini = self._jouer(
            up.script_sh(up.operations_gadget("dummy_udc.0", self.racine))
        )
        self.assertEqual(fini.returncode, 0, fini.stderr)
        g = Path(self.racine) / up.GADGET

        def lire(relatif):
            return (g / relatif).read_bytes()

        self.assertEqual(lire("idVendor"), b"0x0fd9\n")
        self.assertEqual(lire("idProduct"), b"0x0080\n")
        self.assertEqual(lire("strings/0x409/product"), b"Stream Deck MK.2\n")
        self.assertEqual(
            lire("strings/0x409/serialnumber"), (up.SERIE + "\n").encode()
        )
        self.assertEqual(
            lire("functions/hid.usb0/report_desc"), up.DESCRIPTEUR_HID
        )
        self.assertEqual(lire("UDC"), b"dummy_udc.0\n")
        lien = g / "configs/c.1/hid.usb0"
        self.assertTrue(lien.is_symlink())
        self.assertEqual(os.readlink(lien), str(g / "functions/hid.usb0"))

    def test_a_path_with_a_quote_stays_one_path(self):
        racine = os.path.join(self.racine, "l'autre $HOME")
        fini = self._jouer(
            up.script_sh(up.operations_gadget("dummy_udc.0", racine))
        )
        self.assertEqual(fini.returncode, 0, fini.stderr)
        self.assertTrue(os.path.isfile(os.path.join(racine, up.GADGET, "UDC")))

    def test_an_unexpected_udc_is_refused(self):
        for udc in ("", "dummy_udc.0; rm -rf /", "musb-hdrc.0", "../x"):
            with self.subTest(udc=udc):
                with self.assertRaises(ValueError):
                    up.operations_gadget(udc)
                with self.assertRaises(ValueError):
                    up.script_branchement(True, udc)

    def test_unplug_and_replug_write_the_udc_file(self):
        os.makedirs(os.path.join(self.racine, up.GADGET))
        udc = os.path.join(self.racine, up.GADGET, "UDC")
        for branche, attendu in ((True, b"dummy_udc.1\n"), (False, b"\n")):
            with self.subTest(branche=branche):
                fini = self._jouer(
                    up.script_branchement(branche, "dummy_udc.1", self.racine)
                )
                self.assertEqual(fini.returncode, 0, fini.stderr)
                self.assertEqual(Path(udc).read_bytes(), attendu)

    def test_removing_an_absent_gadget_succeeds(self):
        fini = self._jouer(up.script_retrait_gadget(self.racine))
        self.assertEqual(fini.returncode, 0, fini.stderr)

    def test_removal_unplugs_then_goes_deepest_first(self):
        script = up.script_retrait_gadget()
        self.assertLess(script.index("/UDC"), script.index("rm -f"))
        rmdir = script[script.index("rmdir") :]
        self.assertLess(
            rmdir.index("configs/c.1/strings/0x409"), rmdir.index("c.1 ")
        )
        self.assertTrue(rmdir.rstrip().endswith(f"/{up.GADGET}"))

    def test_unknown_operation_is_refused(self):
        with self.assertRaises(ValueError):
            up.script_sh([("chmod", "/x")])


class LesModules(unittest.TestCase):
    def test_only_what_the_run_loaded_and_in_order(self):
        self.assertEqual(
            up.modules_a_decharger(
                ["libcomposite"],
                ["udc_core", "libcomposite", "dummy_hcd", "usb_f_hid"],
            ),
            ["usb_f_hid", "dummy_hcd", "udc_core"],
        )

    def test_nothing_when_everything_was_there(self):
        tout = list(up.ORDRE_DECHARGEMENT)
        self.assertEqual(up.modules_a_decharger(tout, tout), [])

    def test_every_loaded_module_has_an_unload_rank(self):
        for module in up.MODULES:
            self.assertIn(module, up.ORDRE_DECHARGEMENT)


class LesEtapes(unittest.TestCase):
    def test_every_stage_has_its_function_and_dependencies(self):
        self.assertEqual(set(up.FONCTIONS), set(up.ETAPES))
        self.assertEqual(set(up.DEPENDANCES), set(up.ETAPES))
        self.assertEqual(set(up.DESCRIPTION), set(up.ETAPES))

    def test_a_stage_depends_only_on_earlier_ones(self):
        for rang, etape in enumerate(up.ETAPES):
            for dep in up.DEPENDANCES[etape]:
                with self.subTest(etape=etape, dep=dep):
                    self.assertLess(up.ETAPES.index(dep), rang)

    def test_a_failed_dependency_blocks(self):
        verdicts = {"emulated-deck": "FAILED(deck-gadget)", "spice": "PASSED"}
        self.assertEqual(
            up.bloquee_par("libvirt-mechanics", verdicts), ["emulated-deck"]
        )
        self.assertEqual(up.bloquee_par("spice", verdicts), [])
        self.assertEqual(
            up.bloquee_par("host-status", {"guest": "SKIPPED"}), ["guest"]
        )

    def test_spice_needs_no_deck(self):
        self.assertEqual(up.bloquee_par("spice", {}), [])

    def test_exit_code(self):
        ok = {"etape": "a", "verdict": "PASSED", "detail": ""}
        demande = {
            "etape": "b",
            "verdict": "SKIPPED",
            "detail": "--sans-invite",
        }
        garde = {
            "etape": "cleanup",
            "verdict": "SKIPPED",
            "detail": "--garder",
        }
        saute = {"etape": "c", "verdict": "SKIPPED", "detail": "after a"}
        tombe = {"etape": "d", "verdict": "FAILED", "detail": "unplug-udc"}
        self.assertEqual(up.code_sortie([ok, demande, garde]), 0)
        self.assertEqual(up.code_sortie([ok, saute]), 1)
        self.assertEqual(up.code_sortie([ok, tombe]), 1)

    def test_the_verdict_names_the_check(self):
        lignes = up.resume(
            [{"etape": "guest", "verdict": "FAILED", "detail": "guest-ssh",
              "duree_s": 12}]
        )  # fmt: skip
        self.assertIn("FAILED(guest-ssh)", lignes[1])
        self.assertIn("12.0s", lignes[1])

    def test_check_names_are_unique_in_the_source(self):
        """Un verdict nomme un contrôle : deux contrôles du même nom ne
        diraient plus lequel est tombé."""
        import re

        src = SCRIPT.read_text(encoding="utf-8")
        noms = re.findall(r'course\.controle\(\s*"([a-z-]+)"', src)
        doublons = {n for n in noms if noms.count(n) > 1}
        self.assertFalse(doublons, doublons)
        self.assertGreater(len(noms), 20)


class LesLectures(unittest.TestCase):
    def test_info_usb(self):
        vus = up.parse_info_usb(INFO_USB)
        self.assertIn(("Stream Deck MK.2", "hostdev0"), vus)
        self.assertEqual(
            [i for _p, i in vus if i.startswith("redir")], ["redir0", "redir1"]
        )
        self.assertEqual(up.parse_info_usb(""), [])
        self.assertEqual(up.parse_info_usb("unknown command"), [])

    def test_guest_sysfs_lines(self):
        texte = (
            "usb1|1d6b|0002||xHCI Host Controller\n"
            f"1-1|0FD9|0080|{up.SERIE}|Stream Deck MK.2\n"
            "ligne cassée\n"
        )
        vus = up.parse_usb_invite(texte)
        self.assertEqual(len(vus), 2)
        deck = up.deck_simule(vus)
        self.assertEqual(deck["sysname"], "1-1")
        self.assertEqual((deck["vid"], deck["pid"]), ("0fd9", "0080"))
        self.assertEqual(deck["product"], "Stream Deck MK.2")

    def test_a_product_with_a_bar_stays_whole(self):
        vus = up.parse_usb_invite(f"1-1|0fd9|0080|{up.SERIE}|A|B\n")
        self.assertEqual(vus[0]["product"], "A|B")

    def test_the_guest_command_runs_here(self):
        """CMD_USB_INVITE est du sh : joué sur cet hôte, chaque ligne se
        lit et porte un VID de quatre chiffres hexadécimaux."""
        fini = subprocess.run(
            ["sh", "-c", up.CMD_USB_INVITE], capture_output=True, text=True
        )
        self.assertEqual(fini.returncode, 0, fini.stderr)
        for p in up.parse_usb_invite(fini.stdout):
            self.assertRegex(p["vid"], r"^[0-9a-f]{4}$")

    def test_the_json_line_is_found_among_ssh_warnings(self):
        sortie = (
            "Warning: Permanently added '[x]' (ED25519) to known hosts.\n"
            '[{"serial": "S"}]\n'
            "Warning: Permanently added '[x]' (ED25519) to known hosts.\n"
        )
        self.assertEqual(up.liste_json(sortie), [{"serial": "S"}])
        self.assertEqual(up.liste_json("[pas du json\n"), [])
        self.assertEqual(up.liste_json(""), [])

    def test_no_deck_without_the_serial(self):
        self.assertIsNone(up.deck_simule([{"serial": "AUTRE"}]))
        self.assertIsNone(up.deck_simule(None))


class LesUnites(unittest.TestCase):
    def test_the_detach_unit_is_the_one_the_rule_starts(self):
        """La règle udev lance l'instance « VID-BUS-DEV » ; le test lit le
        journal de cette même instance."""
        nom = up.unite_detache(3, 2)
        self.assertEqual(nom, "erplibre-usb-detach@0fd9-003-002.service")
        instance = nom.split("@", 1)[1].rsplit(".", 1)[0]
        self.assertEqual(
            qu.parse_unplugged(instance), {"vid": "0fd9", "bus": 3, "dev": 2}
        )
        regle = qu.udev_rule_text((up.VID,))
        self.assertIn("erplibre-usb-detach@0fd9-$env{BUSNUM}", regle)

    def test_the_reattach_unit_is_named_by_sysname(self):
        self.assertEqual(
            up.unite_rattache("3-1"), "erplibre-usb-reattach@3-1.service"
        )


class LesCommandes(unittest.TestCase):
    def test_the_cli_runs_like_the_menu_runs_it(self):
        argv = up.argv_cli("list", "--json")
        self.assertEqual(argv[:3], [up.PYTHON_SYSTEME, "-I", "-B"])
        self.assertEqual(argv[3], up.CLI)
        root = up.argv_cli("install-autoreattach", root=True)
        self.assertEqual(root[:2], ["sudo", "-n"])

    def test_the_deploy_line_is_read_by_deploy_qemu(self):
        """Chaque option existe vraiment dans deploy_qemu.py."""
        from script.qemu import deploy_qemu

        argv = up.argv_deploiement("usb-pt-debian-13-x", "/k.pub", ["--x"])
        self.assertNotIn("sudo", argv)
        self.assertEqual(argv[-1], "--x")
        args = deploy_qemu.build_parser().parse_args(argv[2:-1])
        self.assertEqual((args.distro, args.version), ("debian", "13"))
        self.assertEqual(args.usb_hostdev, ["0fd9:0080"])
        self.assertTrue(deploy_qemu.wants_full_kernel(args))

    def test_what_install_lays_is_what_is_checked(self):
        chemins = up.chemins_autoreattach()
        for c in (qu.UDEV_RULE_PATH, qu.UNIT_PATH, qu.DETACH_UNIT_PATH):
            self.assertIn(c, chemins)

    def test_leftovers(self):
        rien = up.restes_autoreattach({}, existe=lambda c: False)
        self.assertEqual(rien, [])
        avant = {"libexec_avant": True, "etc_avant": True}
        self.assertEqual(
            up.restes_autoreattach(
                avant,
                existe=lambda c: c in (up.LIBEXEC_PARENT, up.DOSSIER_MAPPING),
            ),
            [],
        )
        restes = up.restes_autoreattach(
            {}, existe=lambda c: c in (qu.UNIT_PATH, up.LIBEXEC_PARENT)
        )
        self.assertEqual(restes, [qu.UNIT_PATH, up.LIBEXEC_PARENT])
        restes = up.restes_autoreattach(
            avant, existe=lambda c: c == up.DOSSIER_MAPPING
        )
        self.assertEqual(restes, [up.LIBEXEC_PARENT])
        restes = up.restes_autoreattach(
            avant,
            existe=lambda c: (
                c in (up.VERROU_UNITES, up.LIBEXEC_PARENT, up.DOSSIER_MAPPING)
            ),
        )
        self.assertEqual(restes, [up.VERROU_UNITES])

    def test_the_units_lock_is_the_cli_one(self):
        """VERROU_UNITES recopie usb_qemu.LOCK_PATH : les deux restent
        égaux, sans quoi le test chercherait un verrou que rien ne pose."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "usb_qemu_pour_le_test", up.CLI
        )
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        self.assertEqual(up.VERROU_UNITES, cli.LOCK_PATH)


class LaCopieDansLInvite(unittest.TestCase):
    def test_the_copy_imports_alone(self):
        """La copie de FICHIERS_STATUT suffit à plugged_decks() : extraite
        ailleurs et lancée par un interpréteur isolé, elle s'importe et
        rend une liste JSON."""
        dossier = tempfile.mkdtemp(prefix="usb-pt-invite-")
        self.addCleanup(shutil.rmtree, dossier, True)
        with tarfile.open(fileobj=io.BytesIO(up.archive_statut())) as tar:
            self.assertEqual(
                sorted(tar.getnames()), sorted(up.FICHIERS_STATUT)
            )
            tar.extractall(dossier, filter="data")
        fini = subprocess.run(
            ["sh", "-c", up.commande_decks_invite(dossier)],
            capture_output=True,
            text=True,
            cwd=dossier,
        )
        self.assertEqual(fini.returncode, 0, fini.stderr)
        self.assertIsInstance(json.loads(fini.stdout), list)


class LePlan(unittest.TestCase):
    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="usb-pt-maison-")
        self.addCleanup(shutil.rmtree, self.maison, True)

    def test_dry_run_creates_nothing(self):
        code, sortie, appels = _mener("--dry-run", maison=self.maison)
        self.assertEqual(code, 0)
        self.assertEqual(appels, [])
        for etape in up.ETAPES:
            self.assertIn(etape, sortie)
        self.assertIn("--usb-hostdev 0fd9:0080", sortie)
        self.assertIn("rien n'a été créé", sortie)
        rapports = list(Path(self.maison, ".erplibre/longtest").glob("*.json"))
        self.assertEqual(len(rapports), 1)
        self.assertTrue(rapports[0].name.endswith("-dryrun.json"))
        rapport = json.loads(rapports[0].read_text())
        self.assertTrue(rapport["dry_run"])
        self.assertEqual(rapport["outil"], up.OUTIL)

    def test_dry_run_marks_guest_stages_skipped_on_request(self):
        _code, sortie, _ = _mener(
            "--dry-run", "--sans-invite", maison=self.maison
        )
        self.assertEqual(sortie.count("(sautée : --sans-invite)"), 2)


class LeDefaire(unittest.TestCase):
    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="usb-pt-defaire-")
        self.addCleanup(shutil.rmtree, self.maison, True)
        self.dossier = Path(self.maison, ".erplibre/longtest")
        self.dossier.mkdir(parents=True)

    def _rapport(self, nom, **champs):
        rapport = {
            "outil": up.OUTIL,
            "dry_run": False,
            "pid": None,
            "etages": [],
            "hote": {
                "modules_charges": [],
                "gadget": "",
                "autoreattach": False,
            },
        }
        rapport.update(champs)
        (self.dossier / nom).write_text(json.dumps(rapport))
        return rapport

    def test_the_newest_report_with_something_left_is_chosen(self):
        self._rapport(
            "usb-pt-20260101-000000.json",
            etages=[{"nom": "usb-pt-meca-a", "uuid": "u-1"}],
        )
        self._rapport("usb-pt-20260102-000000.json")  # tout défait
        self._rapport(
            "usb-pt-20260103-000000-dryrun.json",
            dry_run=True,
            etages=[{"nom": "x", "uuid": "u"}],
        )
        self._rapport(
            "usb-pt-20260104-000000.json",
            outil="autre",
            etages=[{"nom": "y", "uuid": "u"}],
        )
        chemin, rapport = up.dernier_rapport_a_defaire(str(self.dossier))
        self.assertTrue(chemin.endswith("usb-pt-20260101-000000.json"))
        self.assertEqual(rapport["etages"][0]["nom"], "usb-pt-meca-a")

    def test_a_live_run_is_left_alone(self):
        self._rapport(
            "usb-pt-20260101-000000.json",
            pid=4242,
            hote={"gadget": "/g", "modules_charges": []},
        )
        with mock.patch.object(up, "descente_vivante", lambda pid: True):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    up.dernier_rapport_a_defaire(str(self.dossier)), ("", {})
                )

    def test_dry_run_lists_and_touches_nothing(self):
        self._rapport(
            "usb-pt-20260101-000000.json",
            etages=[{"nom": "usb-pt-debian-13-a", "uuid": "u-2"}],
            hote={
                "gadget": "/sys/kernel/config/usb_gadget/erplibre-usb-pt",
                "modules_charges": ["usb_f_hid", "dummy_hcd"],
                "autoreattach": True,
            },
        )
        code, sortie, appels = _mener(
            "--detruire", "--dry-run", maison=self.maison
        )
        self.assertEqual(code, 0)
        self.assertEqual(appels, [])
        self.assertIn("usb-pt-debian-13-a", sortie)
        self.assertIn("usb_f_hid, dummy_hcd", sortie)
        self.assertIn("rattachement automatique", sortie)
        self.assertIn("rien ne sera défait", sortie)

    def test_nothing_to_undo(self):
        with mock.patch.object(up, "gadget_vivant", lambda: False):
            code, sortie, _ = _mener("--detruire", maison=self.maison)
        self.assertEqual(code, 0)
        self.assertIn("rien à faire", sortie)

    def test_something_left(self):
        self.assertFalse(up.a_defaire({"hote": {}, "etages": []}))
        self.assertTrue(up.a_defaire({"hote": {"autoreattach": True}}))
        self.assertTrue(up.a_defaire({"hote": {"modules_charges": ["x"]}}))


class LInscription(unittest.TestCase):
    def test_it_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_the_lock_and_the_undo_know_it(self):
        from script.todo.longtest_menu import SCRIPTS_DEFAISABLES

        self.assertIn("usb_passthrough.py", descente.SCRIPTS)
        self.assertIn("usb_passthrough.py", SCRIPTS_DEFAISABLES)

    def test_the_menu_dispatches_plan_and_run(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vus = []
        todo.fill_help_info = lambda choix: ""
        todo._longtest_run = lambda nom, args="", demander=None: vus.append(
            (nom, args)
        )
        with mock.patch(
            "script.todo.longtest_menu.click.prompt",
            side_effect=["13", "14", "0"],
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                todo.prompt_execute_longtest()
        self.assertEqual(
            vus,
            [("usb_passthrough.py", "--dry-run"), ("usb_passthrough.py", "")],
        )

    def test_every_label_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for cle in (
            "USB passthrough, emulated deck: plan only (dry-run)",
            "USB passthrough, emulated deck: run it",
        ):
            with self.subTest(cle=cle):
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))

    def test_the_invented_serial_appears_nowhere_else(self):
        """La série est inventée : aucun autre fichier du dépôt ne la porte."""
        fini = subprocess.run(
            ["git", "-C", str(RACINE), "grep", "-l", up.SERIE],
            capture_output=True,
            text=True,
        )
        autres = [
            f
            for f in fini.stdout.split()
            if f
            not in (
                "long_test/usb_passthrough.py",
                "test/test_longtest_usb_passthrough.py",
            )
        ]
        self.assertEqual(autres, [])


if __name__ == "__main__":
    unittest.main()
