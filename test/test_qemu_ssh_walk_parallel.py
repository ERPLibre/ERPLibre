#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Exploration SSH du parc : les sondes d'un niveau partent ensemble.

Le chevauchement se prouve par une barrière que seules des sondes
simultanées franchissent. L'ordre se prouve en faisant aboutir les sondes à
rebours : la sortie et les entrées écrites suivent quand même l'ordre du
niveau, et le repli sur la clé, qui pose une question, reste dans le fil
principal.
"""

import contextlib
import io
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.argv = ["todo.py"]
sys.path.insert(0, "test")
from processus_reels import vivant  # noqa: E402

from script import lib_processus  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

ATTENTE = 5  # secondes avant qu'une barrière non franchie échoue


def _todo():
    todo = TODO.__new__(TODO)
    todo._ssh_private_key = mock.Mock(return_value=None)
    todo._qemu_default_ssh_key = mock.Mock(return_value=None)
    todo._write_ssh_config_entry = mock.Mock()
    todo._virt_manager_offer = mock.Mock()
    todo._qemu_ssh_retry_with_key = mock.Mock()
    return todo


def _faux_ssh(dossier, corps):
    """Un `ssh` exécutable dans `dossier`, en tête du PATH le temps du test :
    il tourne comme la vraie sonde, et `corps` y écrit ce qu'il observe."""
    chemin = os.path.join(dossier, "ssh")
    with open(chemin, "w") as fh:
        fh.write("#!/bin/sh\n" + corps)
    os.chmod(chemin, 0o755)
    return mock.patch.dict(
        os.environ,
        {"PATH": f"{dossier}{os.pathsep}{os.environ.get('PATH', '')}"},
    )


def _walk(todo, aliases):
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        todo._qemu_ssh_walk([{"alias": a} for a in aliases], 2)
    return sortie.getvalue()


class TestQemuSshWalkParallel(unittest.TestCase):
    def test_probes_overlap_and_output_follows_level_order(self):
        """Trois sondes franchissent ensemble une barrière à trois, puis
        aboutissent dans l'ordre inverse : la sortie reste dans l'ordre."""
        aliases = ["hote-a", "hote-b", "hote-c"]
        barriere = threading.Barrier(len(aliases), timeout=ATTENTE)
        # c aboutit d'abord, puis libère b, qui libère a.
        libere = {a: threading.Event() for a in aliases}
        libere["hote-c"].set()
        suivant = {"hote-c": "hote-b", "hote-b": "hote-a"}
        reponses = {
            "hote-a": ("net", "exit 255"),
            "hote-b": ("ok", [("vm1", "10.0.0.1")]),
            "hote-c": ("nolibvirt", []),
        }

        def sonde(alias, sondes=None):
            barriere.wait()
            self.assertTrue(libere[alias].wait(ATTENTE))
            if alias in suivant:
                libere[suivant[alias]].set()
            return reponses[alias]

        todo = _todo()
        todo._qemu_ssh_probe_remote = sonde
        texte = _walk(todo, aliases)

        positions = [texte.index(f"{a}:") for a in ("hote-a", "hote-c")]
        self.assertEqual(positions, sorted(positions))
        todo._write_ssh_config_entry.assert_called_once()
        self.assertEqual(
            todo._write_ssh_config_entry.call_args.args[0], "hote-b+vm1"
        )

    def test_key_fallback_runs_in_main_thread_and_in_order(self):
        """Le repli « auth » pose une question : il tourne dans le fil
        principal, une fois par hôte refusé, dans l'ordre du niveau."""
        aliases = ["hote-a", "hote-b", "hote-c"]
        barriere = threading.Barrier(len(aliases), timeout=ATTENTE)

        def sonde(alias, sondes=None):
            barriere.wait()
            return "auth", "Permission denied"

        fils = []

        def repli(alias, message):
            fils.append(threading.current_thread())
            return "ok", [("vm", "10.0.0.9")]

        todo = _todo()
        todo._qemu_ssh_probe_remote = sonde
        todo._qemu_ssh_retry_with_key = mock.Mock(side_effect=repli)
        _walk(todo, aliases)

        self.assertEqual(
            [c.args[0] for c in todo._qemu_ssh_retry_with_key.call_args_list],
            aliases,
        )
        self.assertTrue(all(f is threading.main_thread() for f in fils))
        self.assertEqual(
            [c.args[0] for c in todo._write_ssh_config_entry.call_args_list],
            [f"{a}+vm" for a in aliases],
        )

    def test_concurrency_never_exceeds_the_cap(self):
        """Plus d'hôtes que le plafond : jamais plus de sondes à la fois."""
        aliases = [f"hote-{i}" for i in range(6)]
        verrou = threading.Lock()
        en_cours = [0]
        pic = [0]
        barriere = threading.Barrier(2, timeout=ATTENTE)

        def sonde(alias, sondes=None):
            with verrou:
                en_cours[0] += 1
                pic[0] = max(pic[0], en_cours[0])
            barriere.wait()
            with verrou:
                en_cours[0] -= 1
            return "nolibvirt", []

        todo = _todo()
        todo._qemu_ssh_probe_remote = sonde
        with mock.patch.object(TODO, "_QEMU_SSH_PARALLEL", 2):
            _walk(todo, aliases)
        self.assertEqual(pic[0], 2)

    def _sonder_avec_faux_ssh(self):
        """Lance une vraie sonde sur un faux `ssh` qui note son stdin, sa
        session et SSH_ASKPASS_REQUIRE, puis répond « pas de QEMU »."""
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        vu = os.path.join(dossier, "vu")
        patch = _faux_ssh(
            dossier,
            f'readlink /proc/self/fd/0 > "{vu}"\n'
            f'ps -o sid= -p $$ | tr -d " " >> "{vu}"\n'
            f'echo $$ >> "{vu}"\n'
            f'echo "$SSH_ASKPASS_REQUIRE" >> "{vu}"\n'
            'printf "LIBVIRT\\tno\\n"\n',
        )
        with patch:
            resultat = _todo()._qemu_ssh_probe_remote("hote-a")
        with open(vu) as fh:
            stdin, sid, pid, askpass = fh.read().split("\n")[:4]
        return resultat, stdin, sid, pid, askpass

    def test_probe_detaches_stdin(self):
        """Une sonde en arrière-plan ne lit pas le clavier pendant qu'une
        question attend sa réponse."""
        resultat, stdin, _sid, _pid, _askpass = self._sonder_avec_faux_ssh()
        self.assertEqual(resultat, ("nolibvirt", []))
        self.assertEqual(stdin, "/dev/null")

    def test_probe_has_no_terminal_to_prompt_on(self):
        """Le ssh d'un ProxyJump ne reçoit pas BatchMode et questionne
        /dev/tty : la sonde tourne dans sa propre session, sans terminal de
        contrôle ni ssh-askpass, pour qu'aucune invite ne s'ouvre pendant
        que d'autres sondes tournent."""
        _resultat, _stdin, sid, pid, askpass = self._sonder_avec_faux_ssh()
        self.assertEqual(sid, pid)
        self.assertEqual(askpass, "never")


class TestQemuSshProbeInterrupt(unittest.TestCase):
    """Ctrl+C pendant un niveau : les sondes tournent hors du groupe du
    terminal, que le signal n'atteint pas. Un faux `ssh` lance un enfant,
    comme le ssh d'un ProxyJump, puis attend ; l'arrêt doit les tuer tous
    deux sans attendre leur fin."""

    DUREE_SONDE = 30  # ce que coûterait d'attendre une sonde vivante

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        faux_ssh = os.path.join(self.dossier, "ssh")
        with open(faux_ssh, "w") as fh:
            fh.write(
                "#!/bin/sh\n"
                f"sleep {self.DUREE_SONDE} &\n"
                'echo "$!" > "$SONDES_PIDS/$$.tmp"\n'
                'mv "$SONDES_PIDS/$$.tmp" "$SONDES_PIDS/$$"\n'
                "wait\n"
            )
        os.chmod(faux_ssh, 0o755)
        chemin = f"{self.dossier}{os.pathsep}{os.environ.get('PATH', '')}"
        patch = mock.patch.dict(
            os.environ, {"PATH": chemin, "SONDES_PIDS": self.dossier}
        )
        patch.start()
        self.addCleanup(patch.stop)
        # Un lanceur qui ignore SIGINT le transmet ignoré : le test pose
        # le gestionnaire de Python lui-même.
        ancien = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, ancien)

    def _pids(self):
        """{chef: enfant} des faux ssh lancés."""
        pids = {}
        for nom in os.listdir(self.dossier):
            if nom.isdigit():
                with open(os.path.join(self.dossier, nom)) as fh:
                    pids[int(nom)] = int(fh.read())
        return pids

    def test_ctrl_c_kills_running_probes_and_their_children(self):
        aliases = ["hote-a", "hote-b"]
        principal = threading.get_ident()

        def interrompre():
            fin = time.monotonic() + 10
            while len(self._pids()) < len(aliases):
                if time.monotonic() > fin:
                    return
                time.sleep(0.05)
            signal.pthread_kill(principal, signal.SIGINT)

        threading.Thread(target=interrompre, daemon=True).start()
        debut = time.monotonic()
        with self.assertRaises(KeyboardInterrupt):
            with contextlib.closing(
                _todo()._qemu_ssh_probe_level(aliases)
            ) as probes:
                list(probes)
        self.assertLess(time.monotonic() - debut, self.DUREE_SONDE / 3)

        pids = self._pids()
        self.assertEqual(len(pids), len(aliases))
        fin = time.monotonic() + 3
        restants = [p for paire in pids.items() for p in paire]
        while restants and time.monotonic() < fin:
            restants = [p for p in restants if vivant(p)]
            time.sleep(0.05)
        self.assertEqual(restants, [])

    def test_no_probe_starts_after_the_stop(self):
        """Un niveau arrêté ne lance plus rien : la sonde rend « net »."""
        sondes = lib_processus.Lot()
        sondes.arreter()
        statut, _ = _todo()._qemu_ssh_probe_remote("hote-a", sondes)
        self.assertEqual(statut, "net")
        self.assertEqual(self._pids(), {})


if __name__ == "__main__":
    unittest.main()
