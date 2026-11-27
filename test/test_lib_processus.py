#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""`script/lib_processus.py` sur de vrais processus et de vrais signaux.

Ce que ces tests gardent, sur les deux chemins d'attente (pidfd, et le
repli par waitid) :

- une commande lancée ouvre sa propre session et lit /dev/null ;
- tuer un groupe emporte ses descendants, et un chef sorti ne laisse pas
  d'orphelin derrière lui ;
- `communiquer` rend la main à la fin du chef, même quand un descendant
  tient le tube de sortie ;
- la grâce laisse SIGTERM sauver ce qu'il faut, puis SIGKILL finit le
  reste ;
- jamais de killpg sur un chef déjà récolté, dont le numéro pourrait
  désigner un autre programme ;
- un lot arrêté ne lance plus rien, et un lancement concurrent à l'arrêt
  est soit refusé, soit tué ;
- Ctrl+C pendant la grâce tue aussitôt ; SIGINT et SIGTERM venus de
  l'extérieur ne laissent aucun processus.
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "test"))

from processus_reels import (  # noqa: E402
    ATTENTE,
    lire,
    lire_pid,
    tous_morts,
    vivant,
)

from script import lib_processus as lp  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def parent_et_enfant(self, nom, fin_parent="wait", piege=""):
        """sh qui lance un `sleep 30` en arrière-plan, écrit son pid, puis
        `fin_parent`. Rend (cmd, fichier_du_pid_enfant)."""
        f = os.path.join(self.d, nom)
        cmd = [
            "sh",
            "-c",
            f"{piege} sleep 30 & echo $! > {f}.t; mv {f}.t {f}; {fin_parent}",
        ]
        return cmd, f

    def lire_pid(self, f):
        return lire_pid(f)


class TestGroupe(Base):
    def test_sa_propre_session_et_stdin_nul(self):
        g = lp.lancer(
            [
                sys.executable,
                "-c",
                "import os;print(os.getsid(0)==os.getpid(),os.readlink('/proc/self/fd/0'))",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        out, _ = g.communiquer(timeout=ATTENTE)
        self.assertEqual(out.split(), ["True", "/dev/null"])

    def test_refuse_les_arguments_de_session(self):
        for nom in ("start_new_session", "process_group", "preexec_fn"):
            with self.assertRaises(TypeError):
                lp.lancer(["true"], **{nom: None})

    def test_tuer_emporte_les_descendants(self):
        cmd, f = self.parent_et_enfant("a")
        g = lp.lancer(cmd)
        enfant = self.lire_pid(f)
        debut = time.monotonic()
        self.assertEqual(g.tuer(), -signal.SIGKILL)
        self.assertLess(time.monotonic() - debut, 1)
        self.assertEqual(tous_morts([g.pid, enfant]), [])

    def test_le_chef_sorti_ses_orphelins_partent(self):
        cmd, f = self.parent_et_enfant("b", fin_parent="exit 3")
        g = lp.lancer(cmd)
        self.assertEqual(g.attendre(ATTENTE), 3)
        self.assertEqual(tous_morts([self.lire_pid(f)]), [])

    def test_communiquer_ne_bloque_pas_sur_un_tube_tenu(self):
        """subprocess.run attendrait les 30 s du sleep qui tient stdout."""
        g = lp.lancer(
            ["sh", "-c", "sleep 30 & echo fin"],
            stdout=subprocess.PIPE,
            text=True,
        )
        debut = time.monotonic()
        out, err = g.communiquer(timeout=ATTENTE)
        self.assertEqual((out, err), ("fin\n", None))
        self.assertLess(time.monotonic() - debut, 2)

    def test_delai_leve_sans_tuer(self):
        g = lp.lancer(["sleep", "30"])
        with self.assertRaises(subprocess.TimeoutExpired):
            g.attendre(0.1)
        self.assertTrue(vivant(g.pid))
        self.assertIsNone(g.code)
        g.tuer()

    def test_grace_laisse_sigterm_sauver(self):
        marque = os.path.join(self.d, "sauve")
        prog = (
            "import signal,sys,time\n"
            "def h(*a):\n"
            f"  open({marque!r},'w').write('ok'); sys.exit(0)\n"
            "signal.signal(signal.SIGTERM,h)\n"
            "print('pret',flush=True)\n"
            "time.sleep(30)\n"
        )
        g = lp.lancer(
            [sys.executable, "-c", prog], stdout=subprocess.PIPE, text=True
        )
        self.addCleanup(g.processus.stdout.close)
        g.processus.stdout.readline()
        debut = time.monotonic()
        self.assertEqual(g.tuer(grace=5), 0)
        self.assertLess(time.monotonic() - debut, 2)
        self.assertTrue(os.path.exists(marque))

    def test_le_chef_sorti_laisse_la_grace_aux_descendants(self):
        """Le chef meurt au SIGTERM, son enfant sauve encore ses données :
        la sortie du chef n'abrège pas la grâce de l'enfant."""
        marque = os.path.join(self.d, "enfant_sauve")
        cmd = [
            "sh",
            "-c",
            f'sh -c \'trap "sleep 0.3; touch {marque}; exit 0" TERM;'
            " while :; do sleep 0.05; done' & echo pret; wait",
        ]
        g = lp.lancer(cmd, stdout=subprocess.PIPE, text=True)
        self.addCleanup(g.processus.stdout.close)
        g.processus.stdout.readline()
        time.sleep(0.1)
        g.tuer(grace=5)
        self.assertTrue(os.path.exists(marque))

    def test_grace_expiree_finit_au_sigkill(self):
        g = lp.lancer(
            [
                "sh",
                "-c",
                "trap '' TERM; echo pret; while :; do sleep 0.05; done",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(g.processus.stdout.close)
        g.processus.stdout.readline()
        debut = time.monotonic()
        self.assertEqual(g.tuer(grace=0.3), -signal.SIGKILL)
        self.assertGreaterEqual(time.monotonic() - debut, 0.3)

    def test_jamais_de_killpg_sur_un_chef_recolte(self):
        """Course entre un fil qui récolte et un autre qui signale : chaque
        killpg vise un numéro encore présent dans /proc (vivant ou zombie)."""
        vrai = os.killpg
        fautes = []

        def espion(pgid, sig):
            if not os.path.exists(f"/proc/{pgid}"):
                fautes.append(pgid)
            return vrai(pgid, sig)

        with mock.patch.object(lp.os, "killpg", espion):
            for _ in range(100):
                g = lp.lancer(["true"])
                stop = threading.Event()

                def marteler():
                    while not stop.is_set():
                        g.signaler(0)

                fil = threading.Thread(target=marteler)
                fil.start()
                g.attendre(ATTENTE)
                for _ in range(50):
                    self.assertFalse(g.signaler(signal.SIGKILL))
                stop.set()
                fil.join()
        self.assertEqual(fautes, [])


class TestGroupeSansPidfd(TestGroupe):
    """Les mêmes garanties par le repli, pour un noyau ou un système sans
    pidfd."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(lp, "_pidfd_open", None)
        p.start()
        self.addCleanup(p.stop)


class TestLot(Base):
    def test_arreter_tue_tout_et_refuse_la_suite(self):
        lot = lp.Lot()
        pids = []
        for n in "abc":
            cmd, f = self.parent_et_enfant(n)
            g = lot.lancer(cmd)
            pids += [g.pid, self.lire_pid(f)]
        lot.arreter()
        self.assertIsNone(lot.lancer(["true"]))
        self.assertEqual(tous_morts(pids), [])

    def test_lancement_concurrent_tue_ou_refuse(self):
        for _ in range(20):
            lot = lp.Lot()
            lances = []
            verrou = threading.Lock()

            def boucle():
                while True:
                    g = lot.lancer(["sleep", "30"])
                    if g is None:
                        return
                    with verrou:
                        lances.append(g)

            fils = [threading.Thread(target=boucle) for _ in range(6)]
            for f in fils:
                f.start()
            time.sleep(0.01)
            lot.arreter()
            for f in fils:
                f.join(ATTENTE)
            with verrou:
                pids = [g.pid for g in lances]
            self.assertEqual(tous_morts(pids), [])
            for g in lances:
                g.attendre(ATTENTE)
            self.assertEqual(lot.actifs(), [])

    def test_grace_mixte(self):
        marque = os.path.join(self.d, "sauve")
        lot = lp.Lot(grace=0.5)
        prog = (
            "import signal,sys,time\n"
            "signal.signal(signal.SIGTERM, lambda *a: (open(%r,'w').close(), sys.exit(0)))\n"
            "print('pret',flush=True)\ntime.sleep(30)\n" % marque
        )
        a = lot.lancer(
            [sys.executable, "-c", prog], stdout=subprocess.PIPE, text=True
        )
        b = lot.lancer(
            [
                "sh",
                "-c",
                "trap '' TERM; echo pret; while :; do sleep 0.05; done",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(a.processus.stdout.close)
        a.processus.stdout.readline()
        self.addCleanup(b.processus.stdout.close)
        b.processus.stdout.readline()
        debut = time.monotonic()
        lot.arreter()
        self.assertLess(time.monotonic() - debut, 1.5)
        self.assertEqual(
            (a.attendre(ATTENTE), b.attendre(ATTENTE)), (0, -signal.SIGKILL)
        )
        self.assertTrue(os.path.exists(marque))

    def test_ctrl_c_pendant_la_grace_tue_aussitot(self):
        ancien = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, ancien)
        lot = lp.Lot(grace=30)
        g = lot.lancer(
            [
                "sh",
                "-c",
                "trap '' TERM; echo pret; while :; do sleep 0.05; done",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(g.processus.stdout.close)
        g.processus.stdout.readline()
        principal = threading.get_ident()
        threading.Timer(
            0.2, signal.pthread_kill, (principal, signal.SIGINT)
        ).start()
        debut = time.monotonic()
        with self.assertRaises(KeyboardInterrupt):
            lot.arreter()
        self.assertLess(time.monotonic() - debut, 2)
        self.assertEqual(g.attendre(ATTENTE), -signal.SIGKILL)

    def test_pool_et_ctrl_c_comme_les_sondes(self):
        ancien = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, ancien)
        lot = lp.Lot()
        fichiers = []

        def sonde(n):
            cmd, f = self.parent_et_enfant(f"s{n}")
            fichiers.append(f)
            g = lot.lancer(cmd)
            if g is None:
                return None
            try:
                return g.communiquer(timeout=90)
            except BaseException:
                g.tuer()
                raise

        principal = threading.get_ident()

        def interrompre():
            fin = time.monotonic() + ATTENTE
            while (
                sum(os.path.exists(f) for f in fichiers) < 4
                and time.monotonic() < fin
            ):
                time.sleep(0.02)
            signal.pthread_kill(principal, signal.SIGINT)

        threading.Thread(target=interrompre, daemon=True).start()
        debut = time.monotonic()
        with self.assertRaises(KeyboardInterrupt):
            with ThreadPoolExecutor(4) as pool, lot:
                list(pool.map(sonde, range(10)))
        self.assertLess(time.monotonic() - debut, 3)
        pids = [self.lire_pid(f) for f in fichiers if os.path.exists(f)]
        self.assertEqual(tous_morts(pids), [])


class TestSignalReelDeLExterieur(Base):
    """Le lanceur est un vrai processus ; SIGINT et SIGTERM viennent de
    l'extérieur, comme d'un terminal ou de systemctl."""

    PILOTE = r"""
import os, signal, sys, time
sys.path.insert(0, %(racine)r)
from script import lib_processus as lp
signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt))
lot = lp.Lot()
try:
    with lot:
        for n in range(3):
            g = lot.lancer(["sh", "-c", "sleep 30 & echo $! >> %(pids)s; wait"])
            with open(%(pids)r, "a") as fh: fh.write(f"{g.pid}\n")
        print("pret", flush=True)
        time.sleep(30)
except KeyboardInterrupt:
    sys.exit(130)
"""

    def test_sigint_et_sigterm(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(sig=sig):
                pids = os.path.join(self.d, f"pids{sig}")
                code = self.PILOTE % {"racine": RACINE, "pids": pids}
                p = subprocess.Popen(
                    [sys.executable, "-c", code],
                    stdout=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                self.addCleanup(
                    lambda p=p: p.poll() is None and os.killpg(p.pid, 9)
                )
                self.assertEqual(p.stdout.readline().strip(), "pret")
                fin = time.monotonic() + ATTENTE
                while len(lire(pids).split()) < 6 and time.monotonic() < fin:
                    time.sleep(0.02)
                os.kill(p.pid, sig)
                self.assertEqual(p.wait(ATTENTE), 130)
                self.assertEqual(
                    tous_morts([int(x) for x in lire(pids).split()]), []
                )
                p.stdout.close()


class TestDetache(Base):
    """Un service qui survit à son lanceur, retrouvé par son fichier PID."""

    def detache(self, *args, env=None, cmd=None, ignore_term=False):
        """Un processus dans sa propre session, récolté dès sa sortie comme
        le ferait init pour un service dont le lanceur est parti."""
        code = "import time; time.sleep(30)"
        if ignore_term:
            code = "import signal, time; " + (
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
            )
        p = subprocess.Popen(
            cmd or [sys.executable, "-c", code, *args],
            start_new_session=True,
            env=env,
        )
        threading.Thread(target=p.wait, daemon=True).start()
        self.addCleanup(
            lambda: vivant(p.pid) and os.kill(p.pid, signal.SIGKILL)
        )
        return p.pid

    def test_l_empreinte_designe_le_processus(self):
        pid = self.detache()
        self.assertEqual(lp.retrouver(lp.empreinte(pid)), pid)

    def test_un_numero_reattribue_n_est_pas_le_processus(self):
        """Même numéro, autre instant de démarrage : ce n'est plus lui."""
        pid = self.detache()
        self.assertEqual(lp.retrouver(f"{pid}:1"), 0)
        self.assertIsNone(lp.signaler_detache(f"{pid}:1", signal.SIGTERM))
        self.assertTrue(vivant(pid))

    def test_un_numero_seul_exige_des_marqueurs_entiers(self):
        """Un fichier d'avant les empreintes : sans marqueur, ou avec un
        marqueur qui n'est qu'une partie d'un argument, il ne désigne
        rien. Les variables d'environnement comptent aussi."""
        pid = self.detache(
            "--http-port=18069", env=dict(os.environ, APPAREIL="demo-01")
        )
        self.assertEqual(lp.retrouver(str(pid)), 0)
        self.assertEqual(lp.retrouver(str(pid), "--http-port=1806"), 0)
        self.assertEqual(lp.retrouver(str(pid), "--http-port=18069"), pid)
        self.assertEqual(
            lp.retrouver(str(pid), ("--http-port=18069", "APPAREIL=demo-01")),
            pid,
        )
        self.assertEqual(lp.retrouver(str(pid), "APPAREIL=demo-0"), 0)

    def test_un_nom_de_programme_non_utf8(self):
        """Le nom recopié dans /proc/<pid>/stat n'est pas forcément de
        l'UTF-8 : l'empreinte se lit quand même."""
        lien = os.path.join(os.fsencode(self.d), b"\xff\xfe")
        os.symlink(shutil.which("sleep").encode(), lien)
        pid = self.detache(cmd=[lien, "30"])
        e = lp.empreinte(pid)
        self.assertIsNotNone(e)
        self.assertEqual(lp.retrouver(e), pid)
        self.assertEqual(lp.retrouver(f"{pid}:1"), 0)

    def test_un_processus_sorti_n_a_plus_d_empreinte(self):
        """Un zombie garde son instant de démarrage dans /proc : il ne
        tourne plus pour autant."""
        p = subprocess.Popen(["true"])
        self.addCleanup(p.wait)
        for _ in range(100):
            stat = lire(f"/proc/{p.pid}/stat")
            if stat.rsplit(")", 1)[-1].split()[0] == "Z":
                break
            time.sleep(0.02)
        self.assertIsNone(lp.empreinte(p.pid))

    def test_le_signal_atteint_tout_le_groupe_du_chef(self):
        cmd, f = self.parent_et_enfant("detache", "wait")
        chef = self.detache(cmd=cmd)
        enfant = self.lire_pid(f)
        cible = lp.signaler_detache(lp.empreinte(chef), signal.SIGTERM)
        self.assertEqual(cible, lp.empreinte(chef))
        self.assertEqual(tous_morts([chef, enfant]), [])

    def test_un_processus_qui_ne_mene_pas_son_groupe_est_seul_vise(self):
        """La branche os.kill : un membre du groupe, pas son chef. Le chef,
        et le reste du groupe, survivent."""
        cmd, f = self.parent_et_enfant("membre", "sleep 30")
        chef = self.detache(cmd=cmd)
        membre = self.lire_pid(f)
        self.assertTrue(
            lp.signaler_detache(lp.empreinte(membre), signal.SIGTERM)
        )
        self.assertEqual(tous_morts([membre]), [])
        self.assertTrue(vivant(chef))

    def test_arreter_passe_a_sigkill_apres_la_grace(self):
        pid = self.detache(ignore_term=True)
        time.sleep(0.2)  # le temps d'installer le gestionnaire de SIGTERM
        debut = time.monotonic()
        self.assertIs(lp.arreter_detache(lp.empreinte(pid), grace=0.5), True)
        self.assertGreaterEqual(time.monotonic() - debut, 0.5)
        self.assertFalse(vivant(pid))

    def test_arreter_un_etranger_ne_signale_rien(self):
        pid = self.detache()
        self.assertIsNone(lp.arreter_detache(str(pid), "--absent"))
        self.assertTrue(vivant(pid))

    def test_arreter_tue_les_membres_restes_apres_leur_chef(self):
        """Le chef sort sur SIGTERM, un membre de son groupe l'ignore :
        l'arrêt ne rend la main qu'une fois le membre tué par SIGKILL."""
        f = os.path.join(self.d, "membre")
        code = (
            "import signal, subprocess, sys, time; "
            "p = subprocess.Popen([sys.executable, '-c', "
            "'import signal, time; signal.signal(signal.SIGTERM, "
            "signal.SIG_IGN); time.sleep(30)']); "
            f"open({f!r}, 'w').write(str(p.pid)); time.sleep(30)"
        )
        chef = self.detache(cmd=[sys.executable, "-c", code])
        membre = self.lire_pid(f)
        time.sleep(0.3)  # le temps d'installer le gestionnaire de SIGTERM
        self.addCleanup(
            lambda: vivant(membre) and os.kill(membre, signal.SIGKILL)
        )
        self.assertIs(lp.arreter_detache(lp.empreinte(chef), grace=0.5), True)
        self.assertEqual(tous_morts([chef, membre]), [])

    def test_un_processus_d_un_autre_compte_n_est_pas_arrete(self):
        """Un processus qu'on ne peut signaler tourne toujours : l'arrêt
        rend False, pour que son fichier PID reste. Simulé : viser un vrai
        processus d'un autre compte pourrait, sous root, atteindre init."""
        pid = self.detache()
        with mock.patch.object(lp.os, "killpg", side_effect=PermissionError):
            self.assertIs(lp.arreter_detache(lp.empreinte(pid)), False)
        self.assertTrue(vivant(pid))

    def test_un_membre_au_nom_non_utf8_compte_dans_son_groupe(self):
        """Un membre illisible écourterait la grâce de son groupe."""
        f = os.path.join(self.d, "nonutf8")
        lien = os.path.join(os.fsencode(self.d), b"\xff\xfe")
        os.symlink(shutil.which("sleep").encode(), lien)
        script = lien + b" 30 & echo $! > " + os.fsencode(f) + b"; wait"
        chef = self.detache(cmd=[b"sh", b"-c", script])
        membre = self.lire_pid(f)
        self.assertIn(membre, lp.membres(chef))

    def test_texte_illisible(self):
        for texte in ("", "abc", ":12", "12:", None, "²", "١٢٣", "9" * 5000):
            with self.subTest(texte=texte):
                self.assertEqual(lp.retrouver(texte, "x"), 0)


class TestVivant(Base):
    def test_vivant_suit_le_groupe_sans_bloquer(self):
        g = lp.lancer(["sleep", "30"])
        debut = time.monotonic()
        self.assertTrue(g.vivant())
        self.assertLess(time.monotonic() - debut, 1)
        g.tuer()
        self.assertFalse(g.vivant())
        self.assertIsNotNone(g.code)

    def test_un_chef_sorti_seul_n_est_plus_vivant_ni_recolte(self):
        """vivant() ne récolte pas : le code reste None jusqu'à attendre(),
        qui balaie alors l'enfant laissé par le chef."""
        cmd, f = self.parent_et_enfant("seul", "exit 3")
        g = lp.lancer(cmd)
        enfant = self.lire_pid(f)
        for _ in range(200):
            if not g.vivant():
                break
            time.sleep(0.02)
        self.assertFalse(g.vivant())
        self.assertIsNone(g.code)
        self.assertTrue(vivant(enfant))
        self.assertEqual(g.attendre(), 3)
        self.assertEqual(tous_morts([enfant]), [])


if __name__ == "__main__":
    unittest.main()
