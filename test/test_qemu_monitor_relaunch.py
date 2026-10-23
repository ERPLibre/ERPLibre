#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Relance, depuis le suivi, des installations en échec (touches r et R).

Ce que ces tests gardent :

- la session conserve, VM par VM, ce qu'il faut rejouer : la commande
  distante, l'identité ssh, le début propre à la VM ;
- la relance rejoue la MÊME commande, précédée d'une garde qui refuse de
  partir tant que l'installation précédente tourne dans la VM — reconnue à
  la marque que porte son shell distant, ou à un make ;
- l'ancien journal est mis de côté (<journal>.N) : écrire à la suite
  laisserait l'ancien marqueur d'échec visible, et la ligne repasserait
  aussitôt en ❌ ;
- l'état est relu sur le disque : une VM déjà relancée par un autre suivi
  ne l'est pas deux fois ;
- une session hors ligne ou antérieure à la relance est refusée, avec la
  raison ;
- une relance faite par un autre suivi n'est adoptée qu'une fois son
  entrée écrite dans le manifeste.

_launch_one est remplacé : aucun processus n'est détaché.
"""

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "test"))

from async_case import AsyncCase  # noqa: E402

from script.todo import qemu_install_monitor as mon  # noqa: E402

COMMANDE = "set -e; make install_os && make install_odoo_18"
# Les messages se comparent à leur traduction : la langue du poste décide.
ANTERIEURE = mon.t(
    "This session predates relaunch: its install command was not"
    " kept. Deploy the VM again."
)


class Lanceur:
    """Remplace _launch_one : retient chaque appel."""

    def __init__(self):
        self.appels = []

    def __call__(self, *args, **kw):
        self.appels.append((args, kw))


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.lanceur = Lanceur()
        patch = mock.patch.object(mon, "_launch_one", self.lanceur)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(mon, "local_uuid", lambda nom: "uuid-x")
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(mon, "session_dir", lambda: self.base)
        patch.start()
        self.addCleanup(patch.stop)

    def session(self, vms, **extra):
        """Session écrite par launch_installs, puis journaux posés à la main."""
        chemin = mon.launch_installs(vms, "develop", COMMANDE, **extra)
        self.lanceur.appels.clear()
        return chemin

    def finit(self, chemin, nom, code):
        manifeste = json.loads(Path(chemin).read_text())
        vm = next(v for v in manifeste["vms"] if v["name"] == nom)
        with open(vm["log"], "a") as fh:
            fh.write(f"une erreur\n{mon.EXIT_MARKER} {code}\n")
        return vm


class TestLaSessionGardeCeQuIlFautRejouer(Base):
    def test_commande_identite_et_debut_par_vm(self):
        avant = time.time()
        chemin = self.session(
            [
                {"name": "vm-a", "ip": "10.0.0.1", "arch": "amd64"},
                {
                    "name": "vm-b",
                    "ip": "10.0.0.2",
                    "arch": "amd64",
                    "remote_cmd": "set -e; propre à vm-b",
                },
            ],
            identity="/chemin/de/cle",
        )
        vms = json.loads(Path(chemin).read_text())["vms"]
        self.assertEqual(COMMANDE, vms[0]["remote_cmd"])
        self.assertEqual("set -e; propre à vm-b", vms[1]["remote_cmd"])
        self.assertEqual("/chemin/de/cle", vms[0]["identity"])
        self.assertGreaterEqual(vms[0]["started"], avant)

    def test_sans_identite_la_cle_est_absente(self):
        chemin = self.session([{"name": "vm-a", "ip": "10.0.0.1"}])
        self.assertNotIn(
            "identity", json.loads(Path(chemin).read_text())["vms"][0]
        )


class TestRelaunchInstall(Base):
    def test_rejoue_la_meme_commande_derriere_la_garde(self):
        chemin = self.session(
            [{"name": "vm-a", "ip": "10.0.0.1", "arch": "amd64"}],
            identity="/cle",
        )
        self.finit(chemin, "vm-a", 1)
        mon.relaunch_install(chemin, "vm-a")
        (args, kw) = self.lanceur.appels[-1]
        self.assertEqual("10.0.0.1", args[0])
        self.assertTrue(args[1].endswith(COMMANDE))
        garde = mon.RELAUNCH_GUARD.format(
            msg=mon.t("An install is already running in this VM.")
        )
        self.assertTrue(args[1].startswith(garde))
        self.assertEqual("/cle", kw["identity"])
        self.assertFalse(kw["pve"])
        self.assertTrue(kw["installs"])
        self.assertEqual("", kw["reboot"])

    def test_l_ancien_journal_est_mis_de_cote(self):
        chemin = self.session([{"name": "vm-a", "ip": "10.0.0.1"}])
        vm = self.finit(chemin, "vm-a", 1)
        mon.relaunch_install(chemin, "vm-a")
        ancien = Path(vm["log"] + ".1")
        self.assertIn(f"{mon.EXIT_MARKER} 1", ancien.read_text())
        neuf = Path(vm["log"]).read_text()
        self.assertNotIn(mon.EXIT_MARKER, neuf)
        self.assertIn(str(ancien), neuf)
        self.assertEqual(("running", None), mon.read_status(vm["log"]))
        entree = json.loads(Path(chemin).read_text())["vms"][0]
        self.assertEqual(1, entree["relaunches"])
        self.assertEqual([str(ancien)], entree["previous_logs"])

    def test_une_seconde_relance_prend_le_rang_suivant(self):
        chemin = self.session([{"name": "vm-a", "ip": "10.0.0.1"}])
        vm = self.finit(chemin, "vm-a", 1)
        mon.relaunch_install(chemin, "vm-a")
        self.finit(chemin, "vm-a", 2)
        mon.relaunch_install(chemin, "vm-a")
        self.assertTrue(Path(vm["log"] + ".2").exists())
        entree = json.loads(Path(chemin).read_text())["vms"][0]
        self.assertEqual(2, entree["relaunches"])

    def test_une_vm_deja_relancee_ne_l_est_pas_deux_fois(self):
        """Un autre suivi sur la même session a relancé : le journal neuf,
        sans marqueur, se lit « running » sur le disque."""
        chemin = self.session([{"name": "vm-a", "ip": "10.0.0.1"}])
        self.finit(chemin, "vm-a", 1)
        mon.relaunch_install(chemin, "vm-a")
        with self.assertRaises(mon.RelaunchRefused):
            mon.relaunch_install(chemin, "vm-a")
        self.assertEqual(1, len(self.lanceur.appels))

    def test_une_installation_reussie_n_est_pas_relancee(self):
        chemin = self.session([{"name": "vm-a", "ip": "10.0.0.1"}])
        vm = self.finit(chemin, "vm-a", 0)
        with self.assertRaises(mon.RelaunchRefused):
            mon.relaunch_install(chemin, "vm-a")
        self.assertFalse(Path(vm["log"] + ".1").exists())
        self.assertEqual([], self.lanceur.appels)

    def test_l_ip_du_suivi_remplace_celle_du_manifeste(self):
        chemin = self.session([{"name": "vm-a", "ip": "10.0.0.1"}])
        self.finit(chemin, "vm-a", 1)
        mon.relaunch_install(chemin, "vm-a", ip="10.0.0.7")
        self.assertEqual("10.0.0.7", self.lanceur.appels[-1][0][0])
        entree = json.loads(Path(chemin).read_text())["vms"][0]
        self.assertEqual("ssh erplibre@10.0.0.7", entree["ssh"])

    def test_une_vm_proxmox_garde_son_alias(self):
        chemin = self.session(
            [{"name": "vm-p", "ip": "alias-p", "pve": {"vmid": 101}}]
        )
        self.finit(chemin, "vm-p", 1)
        mon.relaunch_install(chemin, "vm-p", ip="10.0.0.7")
        (args, kw) = self.lanceur.appels[-1]
        self.assertEqual("alias-p", args[0])
        self.assertTrue(kw["pve"])

    def test_une_session_hors_ligne_est_refusee(self):
        chemin = self.session(
            [{"name": "vm-a", "ip": "10.0.0.1"}], hors_ligne=True
        )
        self.finit(chemin, "vm-a", 1)
        with self.assertRaises(mon.RelaunchRefused):
            mon.relaunch_install(chemin, "vm-a")

    def test_une_session_anterieure_est_refusee(self):
        chemin = self.session([{"name": "vm-a", "ip": "10.0.0.1"}])
        manifeste = json.loads(Path(chemin).read_text())
        del manifeste["vms"][0]["remote_cmd"]
        Path(chemin).write_text(json.dumps(manifeste))
        self.finit(chemin, "vm-a", 1)
        with self.assertRaises(mon.RelaunchRefused) as refus:
            mon.relaunch_install(chemin, "vm-a")
        self.assertEqual(ANTERIEURE, str(refus.exception))


class TestLaRelanceSeProtege(Base):
    def test_un_domaine_qui_n_est_plus_le_meme_est_refuse(self):
        """Nom repris par un déploiement plus récent, ou domaine effacé : le
        lanceur résout l'adresse par le nom, l'installation partirait
        ailleurs."""
        chemin = self.session([{"name": "vm-a", "ip": "10.0.0.1"}])
        vm = self.finit(chemin, "vm-a", 1)
        for autre in ("uuid-autre", ""):
            with self.subTest(autre=autre), mock.patch.object(
                mon, "local_uuid", lambda nom, a=autre: a
            ):
                with self.assertRaises(mon.RelaunchRefused):
                    mon.relaunch_install(chemin, "vm-a")
        self.assertFalse(Path(vm["log"] + ".1").exists())
        self.assertEqual([], self.lanceur.appels)

    def test_un_lancement_qui_echoue_remet_l_ancien_journal(self):
        """La VM reste en échec, donc relançable."""
        chemin = self.session([{"name": "vm-a", "ip": "10.0.0.1"}])
        vm = self.finit(chemin, "vm-a", 1)

        def refuse(*a, **k):
            raise OSError(11, "fork refusé")

        with mock.patch.object(mon, "_launch_one", refuse):
            with self.assertRaises(mon.RelaunchRefused):
                mon.relaunch_install(chemin, "vm-a")
        self.assertEqual(("failed", 1), mon.read_status(vm["log"]))
        self.assertFalse(Path(vm["log"] + ".1").exists())
        entree = json.loads(Path(chemin).read_text())["vms"][0]
        self.assertNotIn("relaunches", entree)
        mon.relaunch_install(chemin, "vm-a")
        self.assertEqual(1, len(self.lanceur.appels))

    def test_les_notes_de_l_hote_sont_redites(self):
        chemin = self.session(
            [{"name": "vm-a", "ip": "10.0.0.1", "notes": ["cache : bypass"]}]
        )
        vm = self.finit(chemin, "vm-a", 1)
        mon.relaunch_install(chemin, "vm-a")
        self.assertIn("cache : bypass", Path(vm["log"]).read_text())

    def test_un_journal_remplace_se_relit_depuis_le_debut(self):
        journal = self.base / "j.log"
        journal.write_text("neuf\n")
        texte, fin = mon._read_new(str(journal), 10_000)
        self.assertEqual("neuf\n", texte)
        self.assertEqual(5, fin)


class TestLaGardeDansLaVm(unittest.TestCase):
    """RELAUNCH_GUARD exécuté sous bash, pgrep remplacé."""

    def lance(self, make_tourne):
        with tempfile.TemporaryDirectory() as coin:
            faux = Path(coin, "pgrep")
            faux.write_text(f"#!/bin/sh\nexit {0 if make_tourne else 1}\n")
            faux.chmod(0o755)
            # Le PATH système porte le vrai sudo : la doublure passe devant.
            doublure = Path(coin, "sudo")
            doublure.write_text('#!/bin/sh\nexec "$@"\n')
            doublure.chmod(0o755)
            garde = mon.RELAUNCH_GUARD.format(msg="déjà en cours")
            return subprocess.run(
                ["bash", "-c", garde + "echo installe"],
                env={"PATH": f"{coin}:/usr/bin:/bin"},
                capture_output=True,
                text=True,
                check=False,
            )

    def test_un_make_qui_tourne_arrete_la_relance(self):
        res = self.lance(make_tourne=True)
        self.assertEqual(75, res.returncode)
        self.assertNotIn("installe", res.stdout)

    def test_sans_make_la_commande_part(self):
        res = self.lance(make_tourne=False)
        self.assertEqual(0, res.returncode)
        self.assertIn("installe", res.stdout)


class TestLaGardeReconnaitLInstallation(unittest.TestCase):
    """RELAUNCH_GUARD sous bash, avec le VRAI pgrep pour la marque.

    Le make est caché par une doublure : celui qui lance ces tests en est
    un, et la garde le prendrait pour une installation."""

    def setUp(self):
        vrai = shutil.which("pgrep")
        if not vrai:
            self.skipTest("pgrep absent")
        deja = subprocess.run(
            ["pgrep", "-u", str(os.getuid()), "-f", mon.INSTALL_TAG],
            capture_output=True,
        )
        if deja.returncode == 0:
            self.skipTest("une installation marquée tourne sur ce poste")
        coin = tempfile.TemporaryDirectory()
        self.addCleanup(coin.cleanup)
        faux = Path(coin.name, "pgrep")
        faux.write_text(
            "#!/bin/sh\n"
            'case " $* " in *" -x make "*) exit 1;; esac\n'
            f'exec {vrai} "$@"\n'
        )
        faux.chmod(0o755)
        self.path = f"{coin.name}:/usr/bin:/bin"

    def relance(self):
        """Le shell de la relance, marqué comme _launch_one le marque."""
        garde = mon.RELAUNCH_GUARD.format(msg="déjà en cours")
        return subprocess.run(
            ["bash", "-c", f": {mon.INSTALL_TAG}; {garde}echo installe"],
            env={"PATH": self.path},
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_une_installation_sans_make_arrete_la_relance(self):
        """La première installation attend cloud-init, ou installe ses
        paquets : aucun make ne tourne encore."""
        # Son groupe entier part au nettoyage : le sleep, orphelin, tiendrait
        # sinon la sortie du lanceur de tests ouverte.
        premiere = subprocess.Popen(
            ["bash", "-c", f": {mon.INSTALL_TAG}; sleep 30; true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.addCleanup(premiere.wait)
        self.addCleanup(os.killpg, premiere.pid, signal.SIGKILL)
        res = self.relance()
        self.assertEqual(75, res.returncode, res.stdout)
        self.assertIn("déjà en cours", res.stdout)
        self.assertNotIn("installe", res.stdout)

    def test_le_shell_de_la_relance_ne_se_compte_pas(self):
        res = self.relance()
        self.assertEqual(0, res.returncode, res.stdout)
        self.assertIn("installe", res.stdout)

    def test_une_installation_finie_ne_bloque_plus(self):
        premiere = subprocess.Popen(
            ["bash", "-c", f": {mon.INSTALL_TAG}; true; true"]
        )
        premiere.wait()
        self.assertEqual(0, self.relance().returncode)


class TestLeLanceurMarqueLInstallation(unittest.TestCase):
    def test_la_marque_ouvre_le_script_distant(self):
        """En tête : pgrep ne compare qu'un préfixe de la ligne de
        commande."""
        vus = {}

        class FauxPopen:
            def __init__(self, argv, *a, **k):
                vus["argv"] = argv

        with mock.patch.object(mon.subprocess, "Popen", FauxPopen):
            mon._launch_one("cible", "echo bonjour", "/dev/null", "vm-a")
        self.assertIn(
            shlex.quote(f": {mon.INSTALL_TAG}; echo bonjour"),
            vus["argv"][-1],
        )


class TestLeSuivi(AsyncCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.lanceur = Lanceur()
        for cible, valeur in (
            ("_launch_one", self.lanceur),
            ("read_domstats", lambda: ""),
            ("arm_balloon", lambda names: None),
            ("virsh_domstates", lambda: {}),
            ("_port_open", lambda ip, port=8069, timeout=0.5: False),
            ("record_duration", lambda *a, **k: None),
        ):
            patch = mock.patch.object(mon, cible, valeur)
            patch.start()
            self.addCleanup(patch.stop)

    def manifeste(self, codes, offline=None, avec_cmd=True, todo=None):
        vms = []
        for nom, code in codes.items():
            log = self.base / f"{nom}.log"
            fin = f"{mon.EXIT_MARKER} {code}\n" if code is not None else ""
            log.write_text(f"===> install\n{fin}")
            entree = {
                "name": nom,
                "ip": "127.0.0.9",
                "arch": "amd64",
                "log": str(log),
                "ssh": f"ssh erplibre@{nom}",
                "disk": str(self.base / f"{nom}.qcow2"),
            }
            if avec_cmd:
                entree["remote_cmd"] = COMMANDE
            vms.append(entree)
        manifeste = {"branch": "develop", "started": time.time() - 600}
        manifeste["vms"] = vms
        if offline is not None:
            manifeste["offline"] = offline
        chemin = self.base / "session.json"
        chemin.write_text(json.dumps(manifeste))
        self.chemin = str(chemin)
        return mon.run_monitor(str(chemin), run_app=False, todo=todo)

    async def ouvre(self, app, pilot):
        await pilot.pause()
        await app._tick_table()
        await pilot.pause()

    def etat(self, app, nom):
        from textual.widgets import DataTable

        return str(app.query_one("#vms", DataTable).get_cell(nom, "state"))

    async def test_r_relance_la_vm_en_echec_selectionnee(self):
        app = self.manifeste({"vm-a": 1, "vm-b": 0})
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            self.assertEqual("❌ (1)", self.etat(app, "vm-a"))
            await pilot.press("r")
            await pilot.pause()
            self.assertEqual("ConfirmScreen", type(app.screen).__name__)
            await pilot.click("#c_yes")
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(1, len(self.lanceur.appels))
            self.assertNotIn("vm-a", app._final)
            self.assertNotEqual("❌ (1)", self.etat(app, "vm-a"))
            self.assertEqual("✅", self.etat(app, "vm-b"))

    async def test_r_sur_une_reussite_ne_fait_rien(self):
        app = self.manifeste({"vm-b": 0, "vm-a": 1})
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            with mock.patch.object(app, "notify") as notify:
                await pilot.press("r")
                await pilot.pause()
            self.assertNotEqual("ConfirmScreen", type(app.screen).__name__)
            self.assertEqual(
                mon.t("Only a failed install can be relaunched."),
                notify.call_args[0][0],
            )

    async def test_maj_r_relance_tous_les_echecs(self):
        app = self.manifeste({"vm-a": 1, "vm-b": 0, "vm-c": 255})
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            await pilot.press("R")
            await pilot.pause()
            self.assertEqual("ConfirmScreen", type(app.screen).__name__)
            await pilot.click("#c_yes")
            await app.workers.wait_for_complete()
            await pilot.pause()
            lances = sorted(a[3] for a, _kw in self.lanceur.appels)
            self.assertEqual(["vm-a", "vm-c"], lances)

    async def test_annuler_ne_relance_rien(self):
        app = self.manifeste({"vm-a": 1})
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            await pilot.press("r")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual([], self.lanceur.appels)
            self.assertIn("vm-a", app._final)

    async def test_une_session_hors_ligne_est_refusee_avant_la_question(self):
        app = self.manifeste({"vm-a": 1}, offline=True)
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            with mock.patch.object(app, "notify") as notify:
                await pilot.press("r")
                await pilot.pause()
            self.assertNotEqual("ConfirmScreen", type(app.screen).__name__)
            self.assertEqual(
                mon.t("Relaunch is not available for an offline session."),
                notify.call_args[0][0],
            )

    async def test_une_session_anterieure_est_refusee_avant_la_question(self):
        app = self.manifeste({"vm-a": 1}, avec_cmd=False)
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            with mock.patch.object(app, "notify") as notify:
                await pilot.press("r")
                await pilot.pause()
            self.assertNotEqual("ConfirmScreen", type(app.screen).__name__)
            self.assertEqual(ANTERIEURE, notify.call_args[0][0])

    async def test_une_vm_effacee_n_est_pas_relancee(self):
        app = self.manifeste({"vm-a": 1})
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            app._domstate["vm-a"] = "gone"
            with mock.patch.object(app, "notify") as notify:
                await pilot.press("R")
                await pilot.pause()
            self.assertNotEqual("ConfirmScreen", type(app.screen).__name__)
            self.assertEqual(
                mon.t("No failed install to relaunch."),
                notify.call_args[0][0],
            )

    async def test_une_coupure_tenue_ailleurs_est_refusee(self):
        """Guet ou verrou d'un autre déploiement : la relance tournerait sans
        Internet."""

        class Todo:
            def _qemu_coupure_tenue_ailleurs(self):
                return True

        app = self.manifeste({"vm-a": 1}, todo=Todo())
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            await pilot.press("r")
            await pilot.pause()
            self.assertNotEqual("ConfirmScreen", type(app.screen).__name__)
            self.assertEqual([], self.lanceur.appels)

    async def test_une_relance_faite_ailleurs_est_adoptee(self):
        """Un autre suivi sur la même session a relancé : la ligne quitte
        son ❌ ici aussi."""
        app = self.manifeste({"vm-a": 1})
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            self.assertEqual("❌ (1)", self.etat(app, "vm-a"))
            with mock.patch.object(mon, "local_uuid", lambda nom: ""):
                mon.relaunch_install(self.chemin, "vm-a")
            await app._tick_table()
            await pilot.pause()
            self.assertNotIn("vm-a", app._final)
            self.assertNotEqual("❌ (1)", self.etat(app, "vm-a"))

    async def test_un_journal_neuf_attend_son_entree_avant_l_adoption(self):
        """Tick tombé entre la mise en place du journal et la réécriture du
        manifeste : l'ancienne entrée n'est pas adoptée, la neuve l'est au
        tick suivant, adresse comprise."""
        app = self.manifeste({"vm-a": 1})
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            self.assertEqual("❌ (1)", self.etat(app, "vm-a"))
            log = self.base / "vm-a.log"
            os.replace(log, str(log) + ".1")
            log.write_text("en-tête neuf\n")
            await app._tick_table()
            await pilot.pause()
            self.assertIn("vm-a", app._final)
            manifeste = json.loads(Path(self.chemin).read_text())
            entree = manifeste["vms"][0]
            entree.update(
                ip="127.0.0.42",
                started=time.time(),
                relaunches=1,
                previous_logs=[str(log) + ".1"],
            )
            Path(self.chemin).write_text(json.dumps(manifeste))
            await app._tick_table()
            await pilot.pause()
            self.assertNotIn("vm-a", app._final)
            self.assertEqual("127.0.0.42", app._vm_by_name("vm-a")["ip"])

    async def test_la_duree_globale_suit_l_horloge_de_la_session(self):
        """Une VM relancée tard ne ramène pas le total figé à sa seule
        durée."""
        app = self.manifeste({"vm-a": 1, "vm-b": 1})
        maintenant = time.time()
        app._vm_by_name("vm-b")["started"] = maintenant - 100
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            app._final = {
                "vm-a": ("failed", 1, 50.0),
                "vm-b": ("done", 0, 90.0),
            }
            total = app._total_elapsed(maintenant, maintenant - 600)
            self.assertAlmostEqual(590.0, total, delta=2)

    async def test_la_duree_part_du_debut_propre_a_la_vm(self):
        """Une VM relancée ou ajoutée ne compte pas le temps d'avant elle."""
        app = self.manifeste({"vm-a": 1})
        vm = app._vm_by_name("vm-a")
        vm["started"] = time.time() - 30
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            self.assertLess(app._final["vm-a"][2], 120)


if __name__ == "__main__":
    unittest.main()
