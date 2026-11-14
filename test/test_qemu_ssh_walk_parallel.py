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
import subprocess
import sys
import threading
import unittest
from unittest import mock

sys.argv = ["todo.py"]
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

        def sonde(alias):
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

        def sonde(alias):
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

        def sonde(alias):
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

    def test_probe_detaches_stdin(self):
        """Une sonde en arrière-plan ne lit pas le clavier pendant qu'une
        question attend sa réponse."""
        todo = _todo()
        fini = subprocess.CompletedProcess([], 0, "LIBVIRT\tno\n", "")
        with mock.patch("subprocess.run", return_value=fini) as run:
            self.assertEqual(
                todo._qemu_ssh_probe_remote("hote-a"), ("nolibvirt", [])
            )
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_probe_has_no_terminal_to_prompt_on(self):
        """Le ssh d'un ProxyJump ne reçoit pas BatchMode et questionne
        /dev/tty : la sonde tourne sans terminal de contrôle ni ssh-askpass,
        pour qu'aucune invite ne s'ouvre pendant que d'autres sondes
        tournent."""
        todo = _todo()
        fini = subprocess.CompletedProcess([], 0, "LIBVIRT\tno\n", "")
        with mock.patch("subprocess.run", return_value=fini) as run:
            todo._qemu_ssh_probe_remote("hote-a")
        kwargs = run.call_args.kwargs
        self.assertIs(kwargs.get("start_new_session"), True)
        self.assertEqual(kwargs["env"].get("SSH_ASKPASS_REQUIRE"), "never")


if __name__ == "__main__":
    unittest.main()
