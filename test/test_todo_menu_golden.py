#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Des menus de TODO rendent leurs rendus de référence : l'entrée [4]
(Navigation telemetry), Configuration, la famille Execute : Execute,
Code et Debug, Config et Generate from pre-configuration, Process, Test
et Update, la famille Run : Run, Database et son menu d'effacement,
Analyse, Transform data et Doc, la famille Git : Git, Git local server et
ses deux menus Actions, GPT code, Claude configs, Plugins, Claude Code,
RTK et Automation, la famille QEMU : Deploy, SSH, QEMU/KVM, QEMU cache et
ses sept menus, Network, Security, Docker / Podman et ses trois menus, la
famille Proxmox : Proxmox VE, VPN, Long test et Install, la famille
Assistant : Assistant, LLM, Servers, Search et les trois menus du
courriel, et le menu principal.

test/todo_menu_golden.json fige, pour chacun, les octets du terminal en
français et en anglais, ce que rend [0], les clés de télémétrie, les
sondes du hub web, et les messages `menu` d'une session web ;
test/todo_menu_golden.py dit comment ils se capturent (configuration,
préférences, hub arrêté, HOME temporaire) et les réécrit. La session web
se compare par ses messages `menu`, le fil d'Ariane de chaque menu
traversé et les clés de télémétrie, le vrai TODO tournant à part sous la
capture, comme dans le worker.

`TestCapture` tient les garde-fous de la capture sur un menu factice mis
à la place de [4] : une question au terminal lève au lieu de bloquer,
une étape de WALK absente de son menu est nommée, et ce que les familles
QEMU, Proxmox et Assistant lisent du système vient des doubles.
"""

import getpass
import io
import json
import shutil
import sys
import unittest
from unittest.mock import patch

import click
import todo_menu_golden as golden


class TestGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = golden.GOLDEN.read_text(encoding="utf-8")
        cls.reference = json.loads(text)

    def test_the_reference_covers_each_menu_in_both_languages(self):
        # Une session passe par Execute et Code plus d'une fois : chaque
        # menu de CRUMBS y a au moins un message.
        for lang in golden.LANGS:
            terminal = self.reference["terminal"][lang]
            self.assertEqual(sorted(terminal), sorted(golden.MENUS))
            session = self.reference["session"][lang]
            crumbs = {menu["crumbs"][-1] for menu in session["menus"]}
            self.assertEqual(crumbs, set(golden.CRUMBS))

    def test_the_terminal_shows_the_same_bytes(self):
        for lang in golden.LANGS:
            for method in golden.MENUS:
                with self.subTest(lang=lang, menu=method):
                    self.assertEqual(
                        golden.terminal(method, lang),
                        self.reference["terminal"][lang][method],
                    )

    def test_a_session_sees_the_same_menus_and_keys(self):
        for lang in golden.LANGS:
            with self.subTest(lang=lang):
                self.assertEqual(
                    golden.session(lang), self.reference["session"][lang]
                )


class TestCapture(unittest.TestCase):
    def captured(self, menu) -> dict:
        """Ce que `golden.terminal` rend quand `menu(todo)` tient la place
        de l'entrée [4]."""
        from script.todo.todo import TODO

        with patch.object(TODO, "prompt_telemetry", menu):
            return golden.terminal("prompt_telemetry", "en")

    def test_a_question_on_the_terminal_raises_instead_of_blocking(self):
        for name, menu in (
            ("input", lambda todo: input("Forged: ")),
            (
                "hidden_prompt",
                lambda todo: click.prompt("Forged", hide_input=True),
            ),
            ("getpass", lambda todo: getpass.getpass("Forged: ")),
        ):
            with (
                self.subTest(name),
                self.assertRaisesRegex(AssertionError, name),
            ):
                self.captured(menu)

    def test_the_standard_input_is_empty_during_the_capture(self):
        seen, stdin = [], sys.stdin
        self.captured(lambda todo: seen.append(sys.stdin))
        [during] = seen
        self.assertIsInstance(during, io.StringIO)
        self.assertEqual(during.read(), "")
        self.assertIs(sys.stdin, stdin)

    def test_the_qemu_family_reads_the_system_through_doubles(self):
        # virsh, le binaire du cache et les fiches des moteurs de
        # conteneurs qu'un menu lit en se dessinant sont ceux des doubles,
        # jamais ceux de l'hôte.
        seen = {}

        def menu(todo):
            from script.todo import container_runtime, qemu_cache_menu

            seen["virsh"] = shutil.which("virsh")
            seen["cache"] = qemu_cache_menu.CACHE_BIN
            seen["engines"] = container_runtime.etats()

        self.captured(menu)
        self.assertTrue(seen["virsh"].endswith("/system/stubs/virsh"))
        self.assertTrue(
            seen["cache"].endswith("/system/erplibre_go_qemu_cache")
        )
        self.assertEqual(
            [fiche["moteur"] for fiche in seen["engines"]],
            ["docker", "podman"],
        )

    def test_the_proxmox_family_reads_the_system_through_doubles(self):
        # L'hôte Proxmox retenu, les versions d'Odoo qu'Install propose et
        # les outils que lancent les feuilles de la famille sont ceux des
        # doubles, jamais ceux de l'hôte.
        seen = {}

        def menu(todo):
            from script.todo.version_manager import get_odoo_version

            seen["host"] = todo._pve_host(ask=False)
            seen["versions"] = get_odoo_version()
            seen["tools"] = [shutil.which(name) for name in ("qm", "which")]

        self.captured(menu)
        self.assertEqual(seen["host"], golden.HOST)
        versions, installed, active = seen["versions"]
        self.assertEqual(
            [version["odoo_version"] for version in versions],
            ["16.0", "17.0", "18.0"],
        )
        self.assertEqual(
            (installed, active), (["odoo17.0", "odoo18.0"], "odoo18.0")
        )
        qm, which = seen["tools"]
        self.assertTrue(qm.endswith("/system/stubs/qm"))
        self.assertTrue(which.endswith("/system/stubs/which"))

    def test_the_assistant_family_reads_the_system_through_doubles(self):
        # Les réseaux que Search propose, les serveurs de modèles connus et
        # ce qu'un serveur répond à une sonde sont ceux des doubles et de
        # CONFIG, jamais ceux de l'hôte : aucune sonde ne part.
        seen = {}

        def menu(todo):
            from script.todo.assistant import discover, fingerprint, servers

            seen["networks"] = [n.cidr for n in discover.local_networks()]
            seen["answers"] = fingerprint.collect("127.0.0.1", 11434)
            known = servers.load(get_config=todo._llm_get_config)
            seen["servers"] = [server.label for server in known]

        self.captured(menu)
        self.assertEqual(seen["networks"], ["192.0.2.0/24", "198.51.100.0/24"])
        self.assertEqual(seen["answers"], {})
        self.assertEqual(seen["servers"], ["Forged one", "Forged two"])

    def test_a_step_absent_from_its_menu_is_named(self):
        # Le menu principal n'a aucune entrée de ce libellé : la session
        # s'arrête là, sans répondre à rien.
        walk = (["Forged absent step"], "0")
        with patch.object(golden, "WALK", walk):
            with self.assertRaisesRegex(EOFError, "Forged absent step"):
                golden.session("en")


if __name__ == "__main__":
    unittest.main()
