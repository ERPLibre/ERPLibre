#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le CLI script/qemu/usb_qemu.py, sur un faux sysfs et un faux virsh.

Ce que ces tests gardent :

- le CLI charge qemu_usb.py par CHEMIN : sa propre copie d'abord (la copie
  installée, lancée en « python3 -I »), le dépôt sinon ;
- attach / detach lisent l'état avant d'agir, exigent une persistance
  explicite, n'ajoutent sudo que pour qemu:///system quand virsh seul est
  refusé, et lisent domstate sous LC_ALL=C ;
- le service Stream Deck de l'hôte n'est arrêté qu'avec --yes ;
- reattach rend 0 quand il n'a rien à faire, détache l'adresse morte et
  attache en live à la nouvelle ;
- detach-unplugged ne détache que l'adresse du périphérique parti, sous le
  même verrou que reattach ;
- install-autoreattach pose les fichiers à l'identique une seule fois, et
  remove-autoreattach ne retire que les répertoires qu'elle a créés ;
- un retrait qui rend le deck à l'hôte exige --yes ou --no-restart quand
  le service deck y est arrêté.

Toutes les valeurs sont inventées : VM « vm-essai », hôte en .invalid.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.todo import todo_i18n

RACINE = Path(__file__).resolve().parents[1]
CLI = RACINE / "script/qemu/usb_qemu.py"


def _charger(path, name="usb_qemu_test"):
    """usb_qemu.py chargé comme module, par son chemin."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


UQ = _charger(CLI)
QU = UQ.QU

DOMAINE = "vm-essai"
DISTANT = "qemu+ssh://essai@hyperviseur.invalid:2222/system"

XML_VM = """<domain type='kvm'>
  <name>vm-essai</name>
  <os><type arch='x86_64'>hvm</type></os>
  <devices>
    <controller type='usb' model='qemu-xhci' ports='15'/>
{extra}  </devices>
</domain>
"""


def xml_vm(*hostdevs):
    return XML_VM.format(extra="".join(h + "\n" for h in hostdevs))


def hostdev(vid, pid, bus=None, dev=None, missing=False):
    addr = f"<address bus='{bus}' device='{dev}'/>" if bus is not None else ""
    miss = " missing='yes'" if missing else ""
    return (
        "    <hostdev mode='subsystem' type='usb' managed='yes'>"
        f"<source{miss}><vendor id='0x{vid}'/><product id='0x{pid}'/>"
        f"{addr}</source></hostdev>"
    )


def cp(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


class Hote:
    """Un hôte libvirt bouchonné : ce que virsh, systemctl et sudo rendent.

    Chaque appel est noté, et le XML que virsh reçoit est lu AU MOMENT de
    l'appel — le CLI efface son fichier temporaire juste après.
    """

    def __init__(
        self,
        etat="running",
        live="",
        config="",
        sonde=0,
        service=None,
        echecs=(),
        nodedevs=None,
    ):
        self.etat = etat
        self.live = live or xml_vm()
        self.config = config or xml_vm()
        self.sonde = sonde
        self.service = service  # None : unité absente ; sinon ActiveState
        self.echecs = set(echecs)
        self.nodedevs = nodedevs or {}
        self.appels = []
        self.envoyes = []
        self.envs = {}

    def __call__(self, argv, env=None, interactive=False, timeout=None):
        argv = list(argv)
        self.appels.append(argv)
        if "virsh" in argv:
            c = argv[argv.index("virsh") :]
            verbe = c[3]
            self.envs[verbe] = env
            if verbe in self.echecs:
                return cp(1, err=f"error: {verbe} refused")
            if verbe == "list":
                return cp(self.sonde)
            if verbe == "domstate":
                return cp(0, self.etat + "\n")
            if verbe == "dumpxml":
                return cp(0, self.config if "--inactive" in c else self.live)
            if verbe in ("attach-device", "detach-device"):
                with open(c[5], encoding="utf-8") as fh:
                    self.envoyes.append((verbe, c[-1], fh.read()))
                return cp(0)
            if verbe == "nodedev-list":
                return cp(0, "\n".join(self.nodedevs) + "\n")
            if verbe == "nodedev-dumpxml":
                return cp(0, self.nodedevs[c[4]])
            return cp(0)
        if "systemctl" in argv:
            if "show" in argv:
                if self.service is None:
                    return cp(0, "LoadState=not-found\nActiveState=inactive\n")
                return cp(0, f"LoadState=loaded\nActiveState={self.service}\n")
            if "stop" in argv:
                self.service = "inactive"
            if "start" in argv:
                self.service = "active"
            return cp(0)
        return cp(0)

    def verbes(self):
        out = []
        for a in self.appels:
            if "virsh" in a:
                out.append(a[a.index("virsh") + 3])
            elif "systemctl" in a and "show" not in a:
                out.append("systemctl " + a[-2])
        return out


class FauxSysfs:
    """Un /sys réduit à bus/usb/devices, dans un répertoire jetable."""

    def __init__(self, racine):
        self.racine = racine
        os.makedirs(os.path.join(racine, "bus/usb/devices"), exist_ok=True)

    def ajouter(self, nom, vid, pid, bus, dev, produit="", serie="", cls=""):
        d = os.path.join(self.racine, "bus/usb/devices", nom)
        os.makedirs(d, exist_ok=True)
        for fichier, valeur in (
            ("idVendor", vid),
            ("idProduct", pid),
            ("busnum", str(bus)),
            ("devnum", str(dev)),
            ("product", produit),
            ("serial", serie),
            ("bDeviceClass", cls),
        ):
            if valeur:
                with open(os.path.join(d, fichier), "w") as fh:
                    fh.write(valeur + "\n")

    def retirer(self, nom):
        shutil.rmtree(os.path.join(self.racine, "bus/usb/devices", nom))


class Base(unittest.TestCase):
    # UID effectif simulé : un utilisateur, sauf pour reattach (root).
    EUID = 1000

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="usb-cli-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sysfs = FauxSysfs(os.path.join(self.tmp, "sys"))
        self.sysfs.ajouter("usb3", "1d6b", "0003", 3, 1, cls="09")
        self.sysfs.ajouter("3-1", "046d", "c52b", 3, 2, "Souris")
        self.sysfs.ajouter(
            "3-2", "0fd9", "0080", 3, 5, "Stream Deck MK.2", "SERIE-A1"
        )
        euid = mock.patch.object(UQ.os, "geteuid", return_value=self.EUID)
        euid.start()
        self.addCleanup(euid.stop)
        tty = mock.patch.object(UQ, "_isatty", return_value=False)
        tty.start()
        self.addCleanup(tty.stop)
        # Les messages se comparent en anglais, quelle que soit la langue
        # choisie dans env_var.sh.
        langue = mock.patch.object(todo_i18n, "_current_lang", "en")
        langue.start()
        self.addCleanup(langue.stop)

    def lancer(self, hote, *argv):
        """(code, sortie, erreurs) de main() sur l'hôte bouchonné."""
        out, err = [], []
        code = UQ.main(
            [*argv, "--sysfs-root", self.sysfs.racine],
            run=hote,
            out=out.append,
            err=err.append,
        )
        return code, "\n".join(out), "\n".join(err)


class TestChargement(unittest.TestCase):
    def test_depuis_le_depot_qemu_usb_vient_de_todo(self):
        self.assertEqual(Path(UQ.LIB_PATH), RACINE / "script/todo/qemu_usb.py")

    def test_la_copie_installee_charge_son_voisin_en_mode_isole(self):
        """La copie de LIBEXEC_DIR tourne en « python3 -I », hors du dépôt :
        elle prend qemu_usb.py dans son propre répertoire."""
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(CLI, d)
            shutil.copy(RACINE / "script/todo/qemu_usb.py", d)
            sysfs = FauxSysfs(os.path.join(d, "sys"))
            sysfs.ajouter("1-4", "0fd9", "0084", 1, 7, "Stream Deck +")
            res = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    os.path.join(d, "usb_qemu.py"),
                    "list",
                    "--json",
                    "--sysfs-root",
                    sysfs.racine,
                ],
                capture_output=True,
                text=True,
                cwd=d,
                timeout=60,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            devs = json.loads(res.stdout)
            self.assertEqual(devs[0]["vid"], "0fd9")
            mod = _charger(os.path.join(d, "usb_qemu.py"), "usb_qemu_copie")
            self.assertEqual(mod.LIB_PATH, os.path.join(d, "qemu_usb.py"))

    def test_nom_du_service_deck_identique_a_todo(self):
        from script.todo import erplibre_home_service

        self.assertEqual(UQ.DECK_SERVICE, erplibre_home_service.UNIT_NAME)


class TestList(Base):
    def test_json_deck_en_tete_sans_concentrateur(self):
        code, out, _ = self.lancer(Hote(), "list", "--json")
        self.assertEqual(code, 0)
        devs = json.loads(out)
        self.assertEqual([d["sysname"] for d in devs], ["3-2", "3-1"])

    def test_texte_marque_le_deck(self):
        code, out, _ = self.lancer(Hote(), "list")
        self.assertEqual(code, 0)
        self.assertTrue(out.splitlines()[0].startswith("* 003.005"))

    def test_uri_distante_lit_nodedev_et_pas_le_sysfs_local(self):
        nodedev = (
            "<device><name>usb_1_4</name>"
            "<path>/sys/devices/pci0000:00/usb1/1-4</path>"
            "<capability type='usb_device'><bus>1</bus><device>9</device>"
            "<product id='0x0084'>Stream Deck +</product>"
            "<vendor id='0x0fd9'>Elgato</vendor></capability></device>"
        )
        racine = (
            "<device><name>usb_usb1</name><path>/sys/x/usb1</path>"
            "<capability type='usb_device'><bus>1</bus><device>1</device>"
            "<product id='0x0002'/><vendor id='0x1d6b'/></capability>"
            "</device>"
        )
        hote = Hote(nodedevs={"usb_1_4": nodedev, "usb_usb1": racine})
        code, out, _ = self.lancer(hote, "list", "--json", "--uri", DISTANT)
        self.assertEqual(code, 0)
        devs = json.loads(out)
        self.assertEqual(len(devs), 1)
        self.assertEqual(
            (devs[0]["sysname"], devs[0]["busnum"], devs[0]["devnum"]),
            ("1-4", 1, 9),
        )
        # Pas de sudo ni de sonde pour une URI distante.
        self.assertFalse(any(a[0] == "sudo" for a in hote.appels))
        self.assertNotIn("list", hote.verbes())


class TestAttach(Base):
    def test_persistance_exigee(self):
        code, _, err = self.lancer(Hote(), "attach", DOMAINE, "0fd9:0080")
        self.assertEqual(code, 2)
        self.assertIn("--live", err)

    def test_live_et_config(self):
        hote = Hote()
        code, _, err = self.lancer(
            hote, "attach", DOMAINE, "0fd9:0080", "--live", "--config"
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            [(v, f) for v, f, _x in hote.envoyes],
            [("attach-device", "--live"), ("attach-device", "--config")],
        )
        xml = hote.envoyes[0][2]
        self.assertIn("<vendor id='0x0fd9'/>", xml)
        self.assertIn("startupPolicy='optional'", xml)
        # Seul : VID:PID sans adresse, qui survit au rebranchement.
        self.assertNotIn("<address", xml)
        self.assertEqual(hote.envs["domstate"]["LC_ALL"], "C")

    def test_deja_attache_ne_relance_rien(self):
        hote = Hote(
            live=xml_vm(hostdev("0fd9", "0080", 3, 5)),
            config=xml_vm(hostdev("0fd9", "0080")),
        )
        code, out, _ = self.lancer(
            hote, "attach", DOMAINE, "3.5", "--live", "--config"
        )
        self.assertEqual(code, 0)
        self.assertEqual(hote.envoyes, [])
        self.assertIn("already attached", out)

    def test_vm_arretee_saute_live(self):
        hote = Hote(etat="shut off")
        code, out, _ = self.lancer(
            hote, "attach", DOMAINE, "0fd9:0080", "--live", "--config"
        )
        self.assertEqual(code, 0)
        self.assertEqual([f for _v, f, _x in hote.envoyes], ["--config"])
        self.assertIn("not running", out)
        # La vue live d'une VM arrêtée n'est pas lue.
        dumps = [a for a in hote.appels if "dumpxml" in a]
        self.assertTrue(all("--inactive" in a for a in dumps))

    def test_deux_decks_identiques(self):
        self.sysfs.ajouter(
            "3-3", "0fd9", "0080", 3, 6, "Stream Deck MK.2", "SERIE-B2"
        )
        code, _, err = self.lancer(
            Hote(), "attach", DOMAINE, "0fd9:0080", "--live"
        )
        self.assertEqual(code, 2)
        self.assertIn("003.006", err)
        hote = Hote()
        code, _, _ = self.lancer(hote, "attach", DOMAINE, "3.6", "--live")
        self.assertEqual(code, 0)
        self.assertIn("<address bus='3' device='6'/>", hote.envoyes[0][2])

    def test_absent_de_l_hote(self):
        code, _, err = self.lancer(
            Hote(), "attach", DOMAINE, "0fd9:0090", "--live"
        )
        self.assertEqual(code, 1)
        self.assertIn("--config", err)
        hote = Hote()
        code, _, _ = self.lancer(
            hote, "attach", DOMAINE, "0fd9:0090", "--config"
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(hote.envoyes), 1)

    def test_selecteur_illisible(self):
        code, _, _ = self.lancer(Hote(), "attach", DOMAINE, "3-2", "--live")
        self.assertEqual(code, 2)

    def test_emplacement_vide_detache_avant_l_attachement(self):
        # VM démarrée sans le deck : libvirt marque son <hostdev> missing.
        hote = Hote(live=xml_vm(hostdev("0fd9", "0080", missing=True)))
        code, _, err = self.lancer(
            hote, "attach", DOMAINE, "0fd9:0080", "--live"
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            ["detach-device", "attach-device"],
            [v for v, _f, _x in hote.envoyes],
        )
        self.assertNotIn("<address", hote.envoyes[0][2])

    def test_detach_bus_dev_trouve_un_hostdev_par_adresse_seule(self):
        adresse_seule = (
            "    <hostdev mode='subsystem' type='usb' managed='yes'>"
            "<source><address bus='3' device='5'/></source></hostdev>"
        )
        hote = Hote(live=xml_vm(adresse_seule))
        code, _, err = self.lancer(hote, "detach", DOMAINE, "3.5", "--live")
        self.assertEqual(code, 0, err)
        self.assertEqual(["detach-device"], [v for v, _f, _x in hote.envoyes])
        self.assertIn("<address bus='3' device='5'/>", hote.envoyes[0][2])

    def test_domaine_option_refuse(self):
        """Un domaine en « -x » serait lu par virsh comme une option."""
        err = []
        ctx = UQ.Ctx(run=Hote(), out=err.append, err=err.append)
        self.assertFalse(UQ._check_domain(ctx, "-x"))
        self.assertTrue(UQ._check_domain(ctx, DOMAINE))

    def test_echec_virsh_rend_1(self):
        hote = Hote(echecs={"attach-device"})
        code, _, err = self.lancer(
            hote, "attach", DOMAINE, "0fd9:0080", "--live"
        )
        self.assertEqual(code, 1)
        self.assertIn("refused", err)

    def test_fichier_xml_efface(self):
        hote = Hote()
        self.lancer(hote, "attach", DOMAINE, "0fd9:0080", "--live")
        chemin = [a for a in hote.appels if "attach-device" in a][0][5]
        self.assertFalse(os.path.exists(chemin))

    def test_dry_run_ne_lance_rien(self):
        hote = Hote()
        code, out, _ = self.lancer(
            hote, "attach", DOMAINE, "0fd9:0080", "--live", "--dry-run"
        )
        self.assertEqual(code, 0)
        self.assertEqual(hote.envoyes, [])
        self.assertIn(QU.XML_PLACEHOLDER, out)


class TestSudo(Base):
    def test_groupe_libvirt_sans_sudo(self):
        hote = Hote(sonde=0)
        self.lancer(hote, "attach", DOMAINE, "0fd9:0080", "--live")
        self.assertFalse(any(a[0] == "sudo" for a in hote.appels))

    def test_sonde_refusee_sudo_n(self):
        hote = Hote(sonde=1)
        self.lancer(hote, "attach", DOMAINE, "0fd9:0080", "--live")
        attache = [a for a in hote.appels if "attach-device" in a][0]
        self.assertEqual(attache[:3], ["sudo", "-n", "virsh"])
        # La sonde elle-même ne passe jamais par sudo.
        sonde = [a for a in hote.appels if "list" in a][0]
        self.assertEqual(sonde[0], "virsh")

    def test_root_ne_sonde_pas(self):
        with mock.patch.object(UQ.os, "geteuid", return_value=0):
            hote = Hote(sonde=1)
            self.lancer(hote, "attach", DOMAINE, "0fd9:0080", "--live")
        self.assertNotIn("list", hote.verbes())
        self.assertFalse(any(a[0] == "sudo" for a in hote.appels))

    def test_no_sudo(self):
        hote = Hote(sonde=1)
        self.lancer(
            hote, "attach", DOMAINE, "0fd9:0080", "--live", "--no-sudo"
        )
        self.assertFalse(any(a[0] == "sudo" for a in hote.appels))


class TestServiceDeck(Base):
    def test_service_actif_sans_yes_rend_3(self):
        hote = Hote(service="active")
        code, _, err = self.lancer(
            hote, "attach", DOMAINE, "0fd9:0080", "--live"
        )
        self.assertEqual(code, 3)
        self.assertIn("--yes", err)
        self.assertEqual(hote.envoyes, [])

    def test_yes_arrete_avant_d_attacher(self):
        hote = Hote(service="active")
        code, _, _ = self.lancer(
            hote, "attach", DOMAINE, "0fd9:0080", "--live", "--yes"
        )
        self.assertEqual(code, 0)
        v = hote.verbes()
        self.assertLess(v.index("systemctl stop"), v.index("attach-device"))

    def test_peripherique_autre_que_deck_ignore_le_service(self):
        hote = Hote(service="active")
        code, _, _ = self.lancer(
            hote, "attach", DOMAINE, "046d:c52b", "--live"
        )
        self.assertEqual(code, 0)
        self.assertFalse(any("systemctl" in a for a in hote.appels))

    def test_config_seule_ne_demande_rien(self):
        hote = Hote(service="active")
        code, out, _ = self.lancer(
            hote, "attach", DOMAINE, "0fd9:0080", "--config"
        )
        self.assertEqual(code, 0)
        self.assertNotIn("systemctl stop", hote.verbes())
        self.assertIn("next start", out)

    def test_detach_propose_puis_relance(self):
        live = xml_vm(hostdev("0fd9", "0080", 3, 5))
        hote = Hote(service="inactive", live=live)
        code, out, _ = self.lancer(
            hote, "detach", DOMAINE, "0fd9:0080", "--live"
        )
        self.assertEqual(code, 0)
        self.assertIn("systemctl --user start " + UQ.DECK_SERVICE, out)
        self.assertNotIn("systemctl start", hote.verbes())
        hote = Hote(service="inactive", live=live)
        self.lancer(hote, "detach", DOMAINE, "0fd9:0080", "--live", "--yes")
        self.assertIn("systemctl start", hote.verbes())
        self.assertEqual(hote.envoyes[0][0], "detach-device")
        self.assertIn("<address bus='3' device='5'/>", hote.envoyes[0][2])

    def test_argv_du_service(self):
        self.assertEqual(
            UQ.deck_service_argv(QU.DEFAULT_URI, "stop"),
            ["systemctl", "--user", "stop", UQ.DECK_SERVICE],
        )
        self.assertEqual(
            UQ.deck_service_argv(DISTANT, "stop"),
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-p",
                "2222",
                "essai@hyperviseur.invalid",
                "systemctl",
                "--user",
                "stop",
                UQ.DECK_SERVICE,
            ],
        )
        with mock.patch.object(UQ.os, "geteuid", return_value=0):
            with mock.patch.dict(os.environ, {"SUDO_USER": "essai"}):
                self.assertEqual(
                    UQ.deck_service_argv(QU.DEFAULT_URI, "stop")[:4],
                    ["systemctl", "--user", "--machine", "essai@.host"],
                )
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(UQ.deck_service_argv(QU.DEFAULT_URI, "stop"))
        self.assertIsNone(UQ.ssh_argv("qemu+ssh://-oProxyCommand=x/system"))


class TestReattach(Base):
    EUID = 0

    def setUp(self):
        super().setUp()
        self.mapping = os.path.join(self.tmp, "usb-passthrough.json")
        with open(self.mapping, "w") as fh:
            fh.write(
                QU.mapping_dumps(
                    [{"vid": "0fd9", "pid": "0080", "domain": DOMAINE}]
                )
            )

    def reattach(self, hote, nom="3-2"):
        return self.lancer(
            hote, "reattach", "--sysname", nom, "--mapping", self.mapping
        )

    def test_nom_invalide(self):
        code, _, _ = self.reattach(Hote(), "../../etc")
        self.assertEqual(code, 2)

    def test_peripherique_reparti(self):
        hote = Hote()
        code, out, _ = self.reattach(hote, "3-9")
        self.assertEqual(code, 0)
        self.assertEqual(hote.appels, [])
        self.assertIn("nothing to do", out)

    def test_sans_vm_associee(self):
        hote = Hote()
        code, _, _ = self.reattach(hote, "3-1")
        self.assertEqual(code, 0)
        self.assertEqual(hote.appels, [])

    def test_vm_arretee(self):
        hote = Hote(etat="shut off")
        code, _, _ = self.reattach(hote)
        self.assertEqual(code, 0)
        self.assertEqual(hote.envoyes, [])

    def test_detache_l_adresse_morte_puis_attache(self):
        hote = Hote(live=xml_vm(hostdev("0fd9", "0080", 3, 4)))
        code, _, err = self.reattach(hote)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            [(v, f) for v, f, _x in hote.envoyes],
            [("detach-device", "--live"), ("attach-device", "--live")],
        )
        self.assertIn("device='4'", hote.envoyes[0][2])
        self.assertIn("device='5'", hote.envoyes[1][2])
        self.assertNotIn("startupPolicy", hote.envoyes[1][2])
        # Root : ni sonde, ni sudo, et jamais --config.
        self.assertFalse(any(a[0] == "sudo" for a in hote.appels))
        self.assertFalse(any("--config" in a for a in hote.appels))

    def test_deja_rattache(self):
        hote = Hote(live=xml_vm(hostdev("0fd9", "0080", 3, 5)))
        code, out, _ = self.reattach(hote)
        self.assertEqual(code, 0)
        self.assertEqual(hote.envoyes, [])
        self.assertIn("already attached", out)

    def test_serie_choisit_la_vm(self):
        with open(self.mapping, "w") as fh:
            fh.write(
                QU.mapping_dumps(
                    [
                        {"vid": "0fd9", "pid": "0080", "domain": "vm-autre"},
                        {
                            "vid": "0fd9",
                            "pid": "0080",
                            "domain": DOMAINE,
                            "serial": "SERIE-A1",
                        },
                    ]
                )
            )
        hote = Hote()
        self.reattach(hote)
        attache = [a for a in hote.appels if "attach-device" in a][0]
        self.assertEqual(attache[4], DOMAINE)

    def test_virsh_en_echec(self):
        hote = Hote(echecs={"domstate"})
        code, _, _ = self.reattach(hote)
        self.assertEqual(code, 1)

    def test_correspondance_illisible(self):
        with open(self.mapping, "w") as fh:
            fh.write("{pas du json")
        code, _, _ = self.reattach(Hote())
        self.assertEqual(code, 1)


class TestDebranchement(Base):
    EUID = 0

    def setUp(self):
        super().setUp()
        self.mapping = os.path.join(self.tmp, "usb-passthrough.json")
        self.ecrire(
            [
                {"vid": "0fd9", "pid": "0080", "domain": DOMAINE},
                {"vid": "046d", "pid": "c52b", "domain": "vm-souris"},
            ]
        )
        verrou = mock.patch.object(
            UQ, "LOCK_PATH", os.path.join(self.tmp, "usb.lock")
        )
        verrou.start()
        self.addCleanup(verrou.stop)

    def ecrire(self, entrees):
        with open(self.mapping, "w") as fh:
            fh.write(QU.mapping_dumps(entrees))

    def debrancher(self, hote, instance="0fd9-003-004"):
        return self.lancer(
            hote,
            "detach-unplugged",
            "--instance",
            instance,
            "--mapping",
            self.mapping,
        )

    def test_instance_invalide(self):
        hote = Hote()
        for mauvaise in ("3-2", "0fd9-3-4", "0fd9-003-004;id"):
            code, _, _ = self.debrancher(hote, mauvaise)
            self.assertEqual(code, 2, mauvaise)
        self.assertEqual(hote.appels, [])

    def test_vendeur_sans_vm(self):
        hote = Hote()
        code, out, _ = self.debrancher(hote, "1234-003-004")
        self.assertEqual(code, 0)
        self.assertEqual(hote.appels, [])
        self.assertIn("mapped to no VM", out)

    def test_detache_l_adresse_partie_seulement(self):
        hote = Hote(
            live=xml_vm(
                hostdev("0fd9", "0080", 3, 4),
                hostdev("0fd9", "0080", 3, 5),
                hostdev("0fd9", "0080", missing=True),
            )
        )
        code, _, err = self.debrancher(hote)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            [(v, f) for v, f, _x in hote.envoyes],
            [("detach-device", "--live")],
        )
        self.assertIn("device='4'", hote.envoyes[0][2])
        self.assertFalse(any("--config" in a for a in hote.appels))
        self.assertFalse(any(a[0] == "sudo" for a in hote.appels))

    def test_deck_identique_encore_branche_garde(self):
        """3.5 porte encore le deck du faux sysfs : son <hostdev> reste."""
        hote = Hote(live=xml_vm(hostdev("0fd9", "0080", 3, 5)))
        code, out, _ = self.debrancher(hote, "0fd9-003-005")
        self.assertEqual(code, 0)
        self.assertEqual(hote.envoyes, [])
        self.assertIn("not attached", out)

    def test_vm_arretee(self):
        hote = Hote(
            etat="shut off", live=xml_vm(hostdev("0fd9", "0080", 3, 4))
        )
        code, _, _ = self.debrancher(hote)
        self.assertEqual(code, 0)
        self.assertEqual(hote.envoyes, [])
        self.assertNotIn("dumpxml", hote.verbes())

    def test_une_vm_illisible_n_arrete_pas_les_autres(self):
        self.ecrire(
            [
                {"vid": "0fd9", "pid": "0080", "domain": "vm-absente"},
                {
                    "vid": "0fd9",
                    "pid": "0080",
                    "domain": DOMAINE,
                    "serial": "S",
                },
            ]
        )

        class Partiel(Hote):
            def __call__(hote, argv, **kw):
                if "domstate" in argv and "vm-absente" in argv:
                    hote.appels.append(list(argv))
                    return cp(1, err="error: failed to get domain")
                return super().__call__(argv, **kw)

        hote = Partiel(live=xml_vm(hostdev("0fd9", "0080", 3, 4)))
        code, _, _ = self.debrancher(hote)
        self.assertEqual(code, 1)
        self.assertEqual(1, len(hote.envoyes))

    def test_correspondance_illisible(self):
        with open(self.mapping, "w") as fh:
            fh.write("{pas du json")
        code, _, _ = self.debrancher(Hote())
        self.assertEqual(code, 1)

    def test_verrou_tenu_pendant_les_appels(self):
        """reattach et detach-unplugged tiennent LOCK_PATH : un second
        verrou ne s'obtient pas pendant qu'ils parlent à virsh."""
        import fcntl

        tenus = []

        class Sonde(Hote):
            def __call__(hote, argv, **kw):
                with open(UQ.LOCK_PATH) as fh:
                    try:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        tenus.append(False)
                    except BlockingIOError:
                        tenus.append(True)
                return super().__call__(argv, **kw)

        self.debrancher(Sonde(live=xml_vm(hostdev("0fd9", "0080", 3, 4))))
        self.lancer(
            Sonde(), "reattach", "--sysname", "3-2", "--mapping", self.mapping
        )
        self.assertTrue(tenus)
        self.assertTrue(all(tenus))
        self.assertEqual(0o600, stat.S_IMODE(os.stat(UQ.LOCK_PATH).st_mode))

    def test_verrou_inaccessible_n_empeche_rien(self):
        with mock.patch.object(
            UQ, "LOCK_PATH", os.path.join(self.tmp, "absent", "usb.lock")
        ):
            hote = Hote(live=xml_vm(hostdev("0fd9", "0080", 3, 4)))
            code, _, _ = self.debrancher(hote)
        self.assertEqual(code, 0)
        self.assertEqual(1, len(hote.envoyes))


class TestInstallation(Base):
    def test_pose_puis_rien_a_refaire(self):
        prefix = os.path.join(self.tmp, "racine")
        hote = Hote()
        code, _, err = self.lancer(
            hote, "install-autoreattach", "--prefix", prefix
        )
        self.assertEqual(code, 0, err)
        p = UQ.system_paths(prefix)
        with open(p["rule"]) as fh:
            self.assertIn('ATTR{idVendor}=="0fd9"', fh.read())
        with open(p["unit"]) as fh:
            self.assertIn(
                f"-I -B {QU.LIBEXEC_CLI} reattach --sysname %i", fh.read()
            )
        with open(p["detach_unit"]) as fh:
            self.assertIn(
                f"-I -B {QU.LIBEXEC_CLI} detach-unplugged --instance %i",
                fh.read(),
            )
        with open(p["rule"]) as fh:
            self.assertIn("erplibre-usb-detach@0fd9-$env{BUSNUM}", fh.read())
        with open(p["cli"]) as fh, open(CLI) as src:
            self.assertEqual(fh.read(), src.read())
        with open(p["lib"]) as fh, open(UQ.LIB_PATH) as src:
            self.assertEqual(fh.read(), src.read())
        modeles = os.path.join(
            os.path.dirname(UQ.LIB_PATH), "streamdeck_models.py"
        )
        with open(p["models"]) as fh, open(modeles) as src:
            self.assertEqual(fh.read(), src.read())
        self.assertEqual(stat.S_IMODE(os.stat(p["cli"]).st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(p["rule"]).st_mode), 0o644)
        with open(p["mapping"]) as fh:
            self.assertEqual(QU.mapping_loads(fh.read()), [])
        # Une arborescence préparée n'est pas le système : aucun rechargement.
        self.assertEqual(hote.appels, [])
        code, out, _ = self.lancer(
            hote, "install-autoreattach", "--prefix", prefix
        )
        self.assertEqual(code, 0)
        self.assertNotIn("  + ", out)

    def test_rechargement_hors_prefix(self):
        hote = Hote()
        ctx = UQ.Ctx(run=hote, out=lambda _x: None)
        self.assertEqual(UQ.reload_system(ctx), 0)
        self.assertEqual(
            hote.appels,
            [
                ["systemctl", "daemon-reload"],
                ["udevadm", "control", "--reload-rules"],
            ],
        )

    def test_retrait_garde_la_correspondance(self):
        prefix = os.path.join(self.tmp, "racine")
        self.lancer(Hote(), "install-autoreattach", "--prefix", prefix)
        p = UQ.system_paths(prefix)
        # La copie installée, une fois lancée, laisse son __pycache__.
        cache = os.path.join(p["libexec"], "__pycache__")
        os.makedirs(cache)
        Path(cache, "qemu_usb.cpython-3.pyc").write_bytes(b"")
        code, _, _ = self.lancer(
            Hote(), "remove-autoreattach", "--prefix", prefix
        )
        self.assertEqual(code, 0)
        for cle in (
            "rule",
            "unit",
            "detach_unit",
            "cli",
            "lib",
            "models",
            "libexec",
        ):
            self.assertFalse(os.path.exists(p[cle]), cle)
        self.assertTrue(os.path.exists(p["mapping"]))
        # /usr/local/libexec, /usr/local et /usr n'existaient pas dans
        # l'arborescence : l'installation les a créés, le retrait les ôte.
        self.assertFalse(os.path.exists(os.path.join(prefix, "usr")))
        self.lancer(
            Hote(), "remove-autoreattach", "--prefix", prefix, "--purge"
        )
        self.assertFalse(os.path.exists(p["mapping"]))
        self.assertFalse(os.path.exists(os.path.dirname(p["mapping"])))

    def test_retrait_ote_le_verrou_des_unites(self):
        """Le premier rattachement crée LOCK_PATH ; le retrait ne le laisse
        pas derrière lui."""
        prefix = os.path.join(self.tmp, "racine")
        self.lancer(Hote(), "install-autoreattach", "--prefix", prefix)
        verrou = UQ.under(prefix, UQ.LOCK_PATH)
        os.makedirs(os.path.dirname(verrou))
        Path(verrou).write_bytes(b"")
        code, out, _ = self.lancer(
            Hote(), "remove-autoreattach", "--prefix", prefix
        )
        self.assertEqual(code, 0)
        self.assertFalse(os.path.lexists(verrou))
        self.assertIn("  - " + verrou, out)
        # Absent : rien à dire, rien d'échoué.
        code, out, _ = self.lancer(
            Hote(), "remove-autoreattach", "--prefix", prefix
        )
        self.assertEqual(code, 0)
        self.assertNotIn(verrou, out)

    def test_retrait_du_verrou_le_tient(self):
        """Sur le système, le verrou est pris avant d'être retiré : une
        unité encore en cours finit d'abord."""
        verrou = os.path.join(self.tmp, "usb.lock")
        Path(verrou).write_bytes(b"")
        vus = []

        @contextlib.contextmanager
        def tenu():
            vus.append(os.path.exists(verrou))
            yield

        sorties = []
        ctx = UQ.Ctx(run=Hote(), out=sorties.append)
        with (
            mock.patch.object(UQ, "LOCK_PATH", verrou),
            mock.patch.object(UQ, "serialized", tenu),
        ):
            self.assertTrue(UQ.remove_lock(ctx))
        self.assertEqual(vus, [True])
        self.assertFalse(os.path.exists(verrou))

    def test_un_libexec_preexistant_reste(self):
        prefix = os.path.join(self.tmp, "racine")
        avant = os.path.join(prefix, "usr/local/libexec")
        os.makedirs(avant)
        self.lancer(Hote(), "install-autoreattach", "--prefix", prefix)
        p = UQ.system_paths(prefix)
        self.assertFalse(os.path.exists(p["created"]))
        self.lancer(Hote(), "remove-autoreattach", "--prefix", prefix)
        self.assertFalse(os.path.exists(p["libexec"]))
        self.assertTrue(os.path.isdir(avant))

    def test_seuls_les_parents_crees_partent(self):
        prefix = os.path.join(self.tmp, "racine")
        os.makedirs(os.path.join(prefix, "usr/local"))
        self.lancer(Hote(), "install-autoreattach", "--prefix", prefix)
        p = UQ.system_paths(prefix)
        with open(p["created"]) as fh:
            self.assertEqual(["/usr/local/libexec"], json.load(fh))
        # Une seconde pose ne réécrit pas la liste : rien n'a été créé.
        self.lancer(Hote(), "install-autoreattach", "--prefix", prefix)
        with open(p["created"]) as fh:
            self.assertEqual(["/usr/local/libexec"], json.load(fh))
        self.lancer(Hote(), "remove-autoreattach", "--prefix", prefix)
        self.assertFalse(
            os.path.exists(os.path.join(prefix, "usr/local/libexec"))
        )
        self.assertTrue(os.path.isdir(os.path.join(prefix, "usr/local")))

    def test_un_fichier_etranger_garde_libexec_et_sa_liste(self):
        prefix = os.path.join(self.tmp, "racine")
        self.lancer(Hote(), "install-autoreattach", "--prefix", prefix)
        p = UQ.system_paths(prefix)
        Path(p["libexec"], "autre.txt").write_text("x")
        self.lancer(Hote(), "remove-autoreattach", "--prefix", prefix)
        self.assertTrue(os.path.exists(p["created"]))
        self.assertFalse(os.path.exists(p["cli"]))
        os.unlink(os.path.join(p["libexec"], "autre.txt"))
        self.lancer(Hote(), "remove-autoreattach", "--prefix", prefix)
        self.assertFalse(os.path.exists(os.path.join(prefix, "usr")))

    def test_une_liste_alteree_ne_designe_rien_d_autre(self):
        prefix = os.path.join(self.tmp, "racine")
        self.lancer(Hote(), "install-autoreattach", "--prefix", prefix)
        p = UQ.system_paths(prefix)
        etc_vide = os.path.join(prefix, "etc", "vide")
        os.makedirs(etc_vide)
        with open(p["created"], "w") as fh:
            json.dump(["/etc/vide", "/usr/local/libexec", "../.."], fh)
        self.lancer(Hote(), "remove-autoreattach", "--prefix", prefix)
        self.assertTrue(os.path.isdir(etc_vide))
        self.assertFalse(
            os.path.exists(os.path.join(prefix, "usr/local/libexec"))
        )
        self.assertTrue(os.path.isdir(os.path.join(prefix, "usr/local")))

    def test_non_root_se_relance_sous_sudo(self):
        hote = Hote()
        code, _, _ = self.lancer(hote, "install-autoreattach")
        self.assertEqual(code, 0)
        self.assertEqual(len(hote.appels), 1)
        argv = hote.appels[0]
        self.assertEqual(argv[:2], ["sudo", "-n"])
        self.assertEqual(argv[3:7], ["-I", "-S", "-B", str(CLI)])
        self.assertIn("install-autoreattach", argv)

    def test_la_relance_root_prend_le_python_du_systeme(self):
        """Le python d'un venv (sys.executable) n'est jamais relancé en
        root : son binaire et ses .pth appartiennent à l'utilisateur."""
        systeme = os.path.join(self.tmp, "python3")
        with open(systeme, "w") as fh:
            fh.write("")
        os.chmod(systeme, 0o755)
        hote = Hote()
        venv = mock.patch.object(UQ.sys, "executable", "/venv.invalid/python")
        with venv, mock.patch.object(UQ, "SYSTEM_PYTHON", systeme):
            self.lancer(hote, "install-autoreattach")
        self.assertEqual(systeme, hote.appels[0][2])
        absent = os.path.join(self.tmp, "absent", "python3")
        with venv, mock.patch.object(UQ, "SYSTEM_PYTHON", absent):
            self.assertEqual("/venv.invalid/python", UQ.root_python())


class TestServiceRendu(Base):
    """Un retrait qui rend le deck à l'hôte, service deck arrêté."""

    def setUp(self):
        super().setUp()
        self.prefix = os.path.join(self.tmp, "racine")
        self.chemin = UQ.system_paths(self.prefix)["mapping"]

    def ecrire(self, *entrees):
        os.makedirs(os.path.dirname(self.chemin), exist_ok=True)
        with open(self.chemin, "w") as fh:
            fh.write(QU.mapping_dumps(entrees))

    def lire(self):
        with open(self.chemin) as fh:
            return QU.mapping_loads(fh.read())

    def retirer(self, hote, *extra, selecteur="0fd9:0080"):
        return self.lancer(
            hote,
            "mapping",
            "remove",
            selecteur,
            "--prefix",
            self.prefix,
            *extra,
        )

    DECK = {"vid": "0fd9", "pid": "0080", "domain": DOMAINE}

    def test_derniere_entree_sans_accord_rend_3_sans_rien_changer(self):
        self.ecrire(self.DECK)
        hote = Hote(service="inactive")
        code, _, err = self.retirer(hote)
        self.assertEqual(code, 3)
        self.assertIn("--yes", err)
        self.assertIn("--no-restart", err)
        self.assertEqual([self.DECK], self.lire())
        self.assertEqual([], hote.verbes())

    def test_yes_retire_puis_relance(self):
        self.ecrire(self.DECK)
        hote = Hote(service="inactive")
        code, _, err = self.retirer(hote, "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual([], self.lire())
        self.assertEqual(["systemctl start"], hote.verbes())
        self.assertEqual("active", hote.service)

    def test_no_restart_retire_et_montre_la_commande(self):
        self.ecrire(self.DECK)
        hote = Hote(service="inactive")
        code, out, _ = self.retirer(hote, "--no-restart")
        self.assertEqual(code, 0)
        self.assertEqual([], self.lire())
        self.assertEqual([], hote.verbes())
        self.assertIn(f"systemctl --user start {UQ.DECK_SERVICE}", out)

    def test_yes_et_no_restart_s_excluent(self):
        with self.assertRaises(SystemExit):
            self.retirer(Hote(), "--yes", "--no-restart")

    def test_rien_a_demander(self):
        """Un autre deck reste, le service tourne ou manque, ou l'entrée
        n'est pas un deck : ni accord, ni relance."""
        souris = {"vid": "046d", "pid": "c52b", "domain": DOMAINE}
        autre = {"vid": "0fd9", "pid": "0084", "domain": "vm-autre"}
        for entrees, service, selecteur in (
            ((self.DECK, autre), "inactive", "0fd9:0080"),
            ((self.DECK,), "active", "0fd9:0080"),
            ((self.DECK,), None, "0fd9:0080"),
            ((souris,), "inactive", "046d:c52b"),
        ):
            self.ecrire(*entrees)
            hote = Hote(service=service)
            code, _, _ = self.retirer(hote, selecteur=selecteur)
            self.assertEqual(code, 0, (entrees, service))
            self.assertEqual([], hote.verbes())

    def test_remove_autoreattach_exige_l_accord(self):
        self.lancer(Hote(), "install-autoreattach", "--prefix", self.prefix)
        self.ecrire(self.DECK)
        p = UQ.system_paths(self.prefix)
        hote = Hote(service="inactive")
        code, _, _ = self.lancer(
            hote, "remove-autoreattach", "--prefix", self.prefix
        )
        self.assertEqual(code, 3)
        self.assertTrue(os.path.exists(p["rule"]))
        code, _, err = self.lancer(
            hote, "remove-autoreattach", "--prefix", self.prefix, "--yes"
        )
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(p["rule"]))
        self.assertEqual(["systemctl start"], hote.verbes())

    def test_remove_autoreattach_sans_deck_ni_pose(self):
        hote = Hote(service="inactive")
        self.ecrire(self.DECK)
        # Rien de posé : le retrait ne change rien au sort du deck.
        code, _, _ = self.lancer(
            hote, "remove-autoreattach", "--prefix", self.prefix
        )
        self.assertEqual(code, 0)
        self.lancer(Hote(), "install-autoreattach", "--prefix", self.prefix)
        self.ecrire({"vid": "046d", "pid": "c52b", "domain": DOMAINE})
        code, _, _ = self.lancer(
            hote, "remove-autoreattach", "--prefix", self.prefix
        )
        self.assertEqual(code, 0)
        self.assertEqual([], hote.verbes())


class TestCorrespondance(Base):
    def mapping(self, hote, *argv, prefix=None):
        extra = ["--prefix", prefix] if prefix else []
        return self.lancer(hote, "mapping", *argv, *extra)

    def test_ajout_liste_retrait(self):
        prefix = os.path.join(self.tmp, "racine")
        code, _, _ = self.mapping(
            Hote(), "add", DOMAINE, "0fd9:0080", prefix=prefix
        )
        self.assertEqual(code, 0)
        code, out, _ = self.mapping(Hote(), "list", "--json", prefix=prefix)
        self.assertEqual(
            json.loads(out),
            [{"domain": DOMAINE, "pid": "0080", "vid": "0fd9"}],
        )
        code, _, _ = self.mapping(Hote(), "remove", "0fd9:0080", prefix=prefix)
        self.assertEqual(code, 0)
        _c, out, _ = self.mapping(Hote(), "list", prefix=prefix)
        self.assertIn("No device", out)

    def test_ajout_met_la_regle_a_jour(self):
        prefix = os.path.join(self.tmp, "racine")
        self.lancer(Hote(), "install-autoreattach", "--prefix", prefix)
        self.mapping(Hote(), "add", DOMAINE, "046d:c52b", prefix=prefix)
        with open(UQ.system_paths(prefix)["rule"]) as fh:
            regle = fh.read()
        self.assertIn('ATTR{idVendor}=="046d"', regle)
        self.assertIn('ATTR{idVendor}=="0fd9"', regle)

    def test_bus_dev_retient_la_serie_entre_jumeaux(self):
        self.sysfs.ajouter(
            "3-3", "0fd9", "0080", 3, 6, "Stream Deck MK.2", "SERIE-B2"
        )
        prefix = os.path.join(self.tmp, "racine")
        code, _, _ = self.mapping(Hote(), "add", DOMAINE, "3.6", prefix=prefix)
        self.assertEqual(code, 0)
        with open(UQ.system_paths(prefix)["mapping"]) as fh:
            (entree,) = QU.mapping_loads(fh.read())
        self.assertEqual(entree["serial"], "SERIE-B2")

    def test_serie_vide_ne_retire_que_l_entree_sans_serie(self):
        chemin = os.path.join(self.tmp, "m.json")
        with open(chemin, "w") as fh:
            fh.write(
                QU.mapping_dumps(
                    [
                        {"vid": "0fd9", "pid": "0080", "domain": DOMAINE},
                        {
                            "vid": "0fd9",
                            "pid": "0080",
                            "domain": DOMAINE,
                            "serial": "SERIE-B2",
                        },
                    ]
                )
            )
        code, _, _ = self.mapping(
            Hote(),
            "remove",
            "0fd9:0080",
            "--domain",
            DOMAINE,
            "--serial",
            "",
            "--mapping",
            chemin,
        )
        self.assertEqual(code, 0)
        with open(chemin) as fh:
            (reste,) = QU.mapping_loads(fh.read())
        self.assertEqual("SERIE-B2", reste["serial"])

    def test_uri_distante_retenue(self):
        chemin = os.path.join(self.tmp, "m.json")
        self.mapping(
            Hote(),
            "add",
            DOMAINE,
            "0fd9:0080",
            "--uri",
            DISTANT,
            "--mapping",
            chemin,
        )
        with open(chemin) as fh:
            self.assertEqual(QU.mapping_loads(fh.read())[0]["uri"], DISTANT)


if __name__ == "__main__":
    unittest.main()
