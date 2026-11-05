#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""QEMU/KVM › Deploy VM(s) : le catalogue, sous les règles des choix.

Les distributions se choisissent sous les règles d'un choix multiple, ou
par une action à lettre : [c] le catalogue complet, [p] la version
principale de chaque distro, [g] des versions précises dans la liste à
plat. Une réponse vide n'en prend aucune : le catalogue entier, qui
déploie des dizaines de VM, se demande par [c]. Chaque liste de
réponses finit par une réponse acceptée ou « 0 ».

Le catalogue est inventé ; les ressources, les noms et le plan sont
remplacés par des doubles, et rien n'est déployé.
"""

import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

# {distro: ({version: (code, os, ram, disque)}, version par défaut)}
MOD = types.SimpleNamespace(
    DISTROS={
        "forged_a": (
            {"1": ("c", "o", 1024, "10G"), "2": ("c", "o", 2048, "20G")},
            "2",
        ),
        "forged_b": ({"9": ("c", "o", 512, "5G")}, "9"),
    }
)


class TestLeCatalogue(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo._qemu_prompt_infra_arch = lambda: "amd64"
        self.todo._qemu_arch_distros = lambda arch: None
        self.todo._qemu_stat_avg = lambda *a: ""
        self.todo._host_free_ram_mb = lambda: 8192
        self.todo._qemu_prompt_resources = lambda sel, cpu, ram: (
            "x1",
            [row + (2,) for row in sel],
        )
        self.todo._qemu_customize_vms = lambda sel, cpu: (
            [f"forged_vm_{i}" for i in range(len(sel))],
            sel,
        )
        self.todo._qemu_make_vm = lambda d, v, a, *rest: f"{d} {v} {a}"
        self.todo._qemu_print_plan = lambda *a: None

    def collect(self, *answers):
        """Les VM du plan (« distro version arch »), ou None ; ce qui
        s'imprime va dans `self.shown`."""
        out = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=answers),
            redirect_stdout(out),
        ):
            got = self.todo._qemu_collect_vms_cli(MOD)
        self.shown = out.getvalue()
        return None if got is None else got[1]

    def test_an_empty_answer_zero_or_ctrl_d_deploys_nothing(self):
        # Une réponse vide ne déploie rien, pas même le catalogue entier, et
        # le dit ; [0] et Ctrl+D reviennent sans un mot, aux distributions,
        # aux versions d'une distribution et à la liste à plat de [g].
        for answers, said in (
            ([""], True),
            (["0"], False),
            ([EOFError], False),
            (["forged_a", EOFError], False),
            (["g", ""], True),
            (["g", "0"], False),
            (["g", EOFError], False),
        ):
            with self.subTest(answers=answers):
                self.assertIsNone(self.collect(*answers))
                self.assertEqual(t("Nothing selected.") in self.shown, said)

    def test_the_three_actions_follow_the_numbers(self):
        self.assertEqual(
            self.collect("c"),
            ["forged_a 1 amd64", "forged_a 2 amd64", "forged_b 9 amd64"],
        )
        self.assertEqual(
            self.collect("P"), ["forged_a 2 amd64", "forged_b 9 amd64"]
        )
        self.assertEqual(
            self.collect("g", "1 3"), ["forged_a 1 amd64", "forged_b 9 amd64"]
        )
        self.assertIsNone(self.collect("g", ""))
        self.assertIn("[c] ", self.shown)
        # [g] lit des numéros, des plages ou `tout`, pas seulement une
        # liste à virgules : son libellé dit la liste qu'il ouvre.
        self.assertIn(
            f"[g] {t('Pick exact versions (flat list)')}", self.shown
        )

    def test_distributions_then_their_versions(self):
        self.assertEqual(self.collect("forged_a", "2"), ["forged_a 2 amd64"])
        self.assertEqual(
            self.collect("tout", "1", "tout"),
            ["forged_a 1 amd64", "forged_b 9 amd64"],
        )
        # Une réponse vide aux versions d'une distro n'en prend aucune ; [0]
        # renonce au déploiement entier.
        self.assertEqual(self.collect("1 2", "", "1"), ["forged_b 9 amd64"])
        self.assertIsNone(self.collect("1 2", "0"))

    def test_an_invalid_answer_is_named_and_asked_again(self):
        # Les mots principal et granulaire, une action mêlée à un numéro, un
        # numéro hors de la liste ou écrit autrement qu'elle ne l'affiche
        # sont dits invalides.
        refused = ["principal", "granulaire", "1 p", "3", "all p", "01", "²"]
        self.assertIsNone(self.collect(*refused, "0"))
        for answer in refused:
            self.assertIn(f"{t('Invalid choice: ')}{answer}", self.shown)


if __name__ == "__main__":
    unittest.main()
