#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les paquets qui fournissent les outils de la réduction sûre.

La réduction d'un disque de VM refuse de partir sans huit binaires. Le nom du
binaire n'est presque jamais celui du paquet, et il change de famille en
famille : sgdisk vit dans « gdisk » chez Debian et Fedora, dans « gptfdisk »
chez Arch et openSUSE. Une table pareille se démode sans bruit — un trou n'y
fait rien planter, il fait juste proposer une installation qui n'installe pas
ce qui manque.

Ce qui se vérifie ici sans VM et sans toucher au système : que chaque outil a
un paquet dans les quatre familles, que la commande construite est celle du
gestionnaire présent, que les paquets ne sont pas demandés deux fois, et qu'un
refus comme un échec laissent l'appelant renoncer plutôt que continuer sans
ses outils.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo import todo_install  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

FAMILIES = ("apt-get", "dnf", "pacman", "zypper")


class _Exec:
    """Le lanceur de commandes, qui retient au lieu d'exécuter."""

    def __init__(self, status=0):
        self.ran = []
        self.status = status

    def exec_command_live(self, cmd, source_erplibre=False):
        self.ran.append(cmd)
        return self.status


class ShrinkToolsBase(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo.execute = _Exec()

    def _which(self, package_manager, missing, installed_after=()):
        """shutil.which vu depuis qemu_manage : un seul gestionnaire de
        paquets sur le PATH, et les outils manquants qui le restent tant que
        l'installation n'a pas tourné."""
        done = self.todo.execute

        def which(binaire):
            if binaire in FAMILIES:
                return (
                    f"/usr/bin/{binaire}"
                    if binaire == package_manager
                    else None
                )
            if binaire in missing:
                if done.ran and binaire in installed_after:
                    return f"/usr/bin/{binaire}"
                return None
            return f"/usr/bin/{binaire}"

        return which

    def _run(self, package_manager, missing, answer="y", installed_after=()):
        which = self._which(package_manager, missing, installed_after)
        buf = io.StringIO()

        # input() écrit son invite sur stdout comme le vrai : sans cela la
        # question n'apparaît nulle part et l'ORDRE des deux ne se voit pas.
        def demande(invite=""):
            print(invite, end="")
            return answer

        # `shutil` est UN seul objet module partagé : patcher son « which »
        # par n'importe quel importateur le patche pour todo_install aussi,
        # qui est le vrai lecteur du PATH depuis le refactor.
        with patch("script.todo.qemu_manage.shutil.which", which), patch(
            "builtins.input", demande
        ), redirect_stdout(buf):
            left = self.todo._qemu_install_shrink_tools(list(missing))
        return self.todo.execute.ran, left, buf.getvalue()


class TestPackageTable(ShrinkToolsBase):
    def test_every_tool_has_a_package_in_every_family(self):
        """Un trou ne plante pas : il propose une installation inutile."""
        for family in FAMILIES:
            per_family = TODO._SHRINK_PKG_FAMILY[family]
            for binaire in TODO._SHRINK_TOOLS:
                paquet = per_family.get(binaire) or TODO._SHRINK_PKG.get(
                    binaire
                )
                self.assertTrue(
                    paquet,
                    f"{family} : aucun paquet connu pour « {binaire} »",
                )

    def test_the_overrides_cover_exactly_the_known_families(self):
        """Une famille connue de todo_install sans surcharge ici proposerait
        « gdisk » à un Arch, qui ne l'a pas."""
        self.assertEqual(set(TODO._SHRINK_PKG_FAMILY), set(FAMILIES))
        self.assertEqual(set(todo_install.FAMILIES), set(FAMILIES))

    def test_sgdisk_is_the_one_that_changes_name(self):
        """Le cas qui a motivé la table, gardé explicitement."""
        noms = {f: TODO._SHRINK_PKG_FAMILY[f]["sgdisk"] for f in FAMILIES}
        self.assertEqual(noms["apt-get"], "gdisk")
        self.assertEqual(noms["dnf"], "gdisk")
        self.assertEqual(noms["pacman"], "gptfdisk")
        self.assertEqual(noms["zypper"], "gptfdisk")

    def test_no_family_override_repeats_the_common_table(self):
        """Un doublon entre les deux tables est une divergence en attente."""
        for family in FAMILIES:
            for binaire in TODO._SHRINK_PKG_FAMILY[family]:
                self.assertNotIn(
                    binaire,
                    TODO._SHRINK_PKG,
                    f"{family} : « {binaire} » est dans les deux tables",
                )


class TestInstallCommand(ShrinkToolsBase):
    def test_each_family_builds_its_own_command(self):
        attendu = {
            "apt-get": "sudo apt-get install -y gdisk",
            "dnf": "sudo dnf install -y gdisk",
            "pacman": "sudo pacman -S --needed --noconfirm gptfdisk",
            "zypper": "sudo zypper --non-interactive install gptfdisk",
        }
        for family, cmd in attendu.items():
            self.setUp()
            ran, left, _ = self._run(
                family, ["sgdisk"], installed_after=("sgdisk",)
            )
            self.assertEqual(ran, [cmd])
            self.assertEqual(left, [])

    def test_a_package_is_asked_for_once(self):
        """e2fsck, resize2fs et dumpe2fs sortent du même paquet."""
        ran, _, _ = self._run(
            "apt-get",
            ["e2fsck", "resize2fs", "dumpe2fs", "sgdisk"],
            installed_after=("e2fsck", "resize2fs", "dumpe2fs", "sgdisk"),
        )
        self.assertEqual(ran, ["sudo apt-get install -y e2fsprogs gdisk"])

    def test_the_command_is_shown_before_the_question(self):
        """On approuve ce qu'on a lu : la commande passe AVANT la question.

        L'ordre est le fond de l'affaire, pas la simple présence des deux :
        une question posée avant la commande fait approuver à l'aveugle.
        """
        ran, _, out = self._run("apt-get", ["sgdisk"], answer="n")
        commande = out.index("sudo apt-get install -y gdisk")
        question = out.index(t("Install them? (y/N): "))
        self.assertLess(commande, question)
        self.assertEqual(ran, [])


class TestGivingUp(ShrinkToolsBase):
    def test_a_refusal_installs_nothing_and_keeps_the_list(self):
        ran, left, _ = self._run("apt-get", ["sgdisk"], answer="n")
        self.assertEqual(ran, [])
        self.assertEqual(left, ["sgdisk"])

    def test_an_unknown_package_manager_gives_up(self):
        ran, left, _ = self._run("brew", ["sgdisk"])
        self.assertEqual(ran, [])
        self.assertEqual(left, ["sgdisk"])

    def test_the_list_is_re_read_from_disk_not_assumed(self):
        """Une installation qui ne pose rien doit rester un échec."""
        ran, left, _ = self._run("apt-get", ["sgdisk"], installed_after=())
        self.assertEqual(len(ran), 1)
        self.assertEqual(left, ["sgdisk"])

    def test_a_failing_install_is_reported_and_not_swallowed(self):
        """exec_command_live REND le code de sortie, il ne lève rien."""
        self.todo.execute = _Exec(status=100)
        ran, left, out = self._run("apt-get", ["sgdisk"])
        self.assertEqual(len(ran), 1)
        self.assertEqual(left, ["sgdisk"])
        self.assertIn("100", out)


if __name__ == "__main__":
    unittest.main()
