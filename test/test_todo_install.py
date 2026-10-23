#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La composante d'installation partagée : familles, noms, ordre de décision.

Trois écritures séparées faisaient ce travail avant, chacune couvrant un
sous-ensemble différent : on pouvait installer virt-viewer sous openSUSE, mais
ni navigateur CLI ni lm-sensors. Ce qui se garde ici est donc surtout de la
COUVERTURE — qu'aucune famille ne retombe dans le trou — plus les deux règles
que la composante tient à la place des appelants : l'ID de la distribution
décide avant le PATH, et la commande s'affiche avant la question.

Rien n'est installé : le PATH et /etc/os-release sont simulés.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import mock_open, patch

sys.argv = ["todo.py"]
from script.todo import todo_install  # noqa: E402


def _only(*present):
    """shutil.which qui ne trouve que `present`."""
    return lambda b: f"/usr/bin/{b}" if b in present else None


class TestFamilyDetection(unittest.TestCase):
    def test_every_family_has_a_non_interactive_command(self):
        """Un menu qui rend la main à un prompt apt reste bloqué."""
        for famille in todo_install.FAMILIES:
            cmd = todo_install.install_command(["p"], famille=famille)
            self.assertEqual(cmd[0], "sudo")
            self.assertEqual(cmd[-1], "p")
            self.assertTrue(
                {"-y", "--noconfirm", "--non-interactive"} & set(cmd),
                f"{famille} : commande interactive {cmd}",
            )

    def test_the_distribution_id_decides_before_the_path(self):
        """Une machine peut porter deux gestionnaires ; l'ID dit lequel
        possède le système."""
        with (
            patch("builtins.open", mock_open(read_data='ID="debian"\n')),
            patch(
                "script.todo.todo_install.shutil.which",
                _only("apt-get", "dnf"),
            ),
        ):
            self.assertEqual(todo_install.family(), "apt-get")

    def test_the_path_decides_when_the_id_is_unknown(self):
        with (
            patch("builtins.open", mock_open(read_data='ID="nonesuch"\n')),
            patch("script.todo.todo_install.shutil.which", _only("zypper")),
        ):
            self.assertEqual(todo_install.family(), "zypper")

    def test_an_id_whose_manager_is_absent_falls_back(self):
        """Un conteneur Debian minimal sans apt-get ne doit pas mener à une
        commande apt-get qui n'existe pas."""
        with (
            patch("builtins.open", mock_open(read_data='ID="debian"\n')),
            patch("script.todo.todo_install.shutil.which", _only("dnf")),
        ):
            self.assertEqual(todo_install.family(), "dnf")

    def test_no_manager_is_none_not_a_guess(self):
        with (
            patch("builtins.open", mock_open(read_data="")),
            patch("script.todo.todo_install.shutil.which", _only()),
        ):
            self.assertIsNone(todo_install.family())
            self.assertIsNone(todo_install.install_command(["p"]))

    def test_the_four_supported_families_are_all_mapped(self):
        """Les plateformes annoncées par le dépôt doivent toutes tomber sur
        une famille, sans quoi l'installation leur est fermée."""
        for os_id, attendu in (
            ("ubuntu", "apt-get"),
            ("linuxmint", "apt-get"),
            ("debian", "apt-get"),
            ("almalinux", "dnf"),
            ("rocky", "dnf"),
            ("opensuse-leap", "zypper"),
            ("opensuse-tumbleweed", "zypper"),
            ("arch", "pacman"),
        ):
            with (
                patch("builtins.open", mock_open(read_data=f'ID="{os_id}"\n')),
                patch(
                    "script.todo.todo_install.shutil.which",
                    _only(*todo_install.FAMILIES),
                ),
            ):
                self.assertEqual(todo_install.family(), attendu, os_id)


class TestPackageNames(unittest.TestCase):
    def test_a_dict_picks_the_name_of_the_current_family(self):
        """lm-sensors chez Debian, lm_sensors ailleurs."""
        noms = {
            "apt-get": ["lm-sensors"],
            "dnf": ["lm_sensors"],
            "pacman": ["lm_sensors"],
            "zypper": ["sensors"],
        }
        for famille, attendu in (
            ("apt-get", "lm-sensors"),
            ("dnf", "lm_sensors"),
            ("zypper", "sensors"),
        ):
            cmd = todo_install.install_command(noms, famille=famille)
            self.assertEqual(cmd[-1], attendu)

    def test_a_family_absent_from_the_dict_installs_nothing(self):
        """Mieux vaut rien proposer qu'un paquet qui n'existe pas ici."""
        self.assertIsNone(
            todo_install.install_command({"apt-get": ["p"]}, famille="pacman")
        )

    def test_resolve_maps_binaries_and_deduplicates(self):
        paquets, inconnus = todo_install.resolve(
            ["e2fsck", "resize2fs", "sgdisk"],
            commun={"e2fsck": "e2fsprogs", "resize2fs": "e2fsprogs"},
            par_famille={"pacman": {"sgdisk": "gptfdisk"}},
            famille="pacman",
        )
        self.assertEqual(paquets, ["e2fsprogs", "gptfdisk"])
        self.assertEqual(inconnus, [])

    def test_resolve_says_what_it_cannot_map(self):
        """À dire, jamais à deviner : un nom inventé installerait au hasard."""
        paquets, inconnus = todo_install.resolve(
            ["sgdisk"], commun={}, par_famille={}, famille="apt-get"
        )
        self.assertEqual(paquets, [])
        self.assertEqual(inconnus, ["sgdisk"])


class TestAskAndInstall(unittest.TestCase):
    class _Exec:
        def __init__(self, status=0):
            self.ran, self.status = [], status

        def exec_command_live(self, cmd, source_erplibre=False):
            self.ran.append(cmd)
            return self.status

    def _play(self, cmd, answer, status=0):
        ex = self._Exec(status)
        buf = io.StringIO()

        def demande(invite=""):
            print(invite, end="")
            return answer

        with patch("builtins.input", demande), redirect_stdout(buf):
            got = todo_install.ask_and_install(
                ex, cmd, "Installer? (y/N): ", lambda a: a.strip() == "y"
            )
        return ex.ran, got, buf.getvalue()

    def test_the_command_is_printed_before_the_question(self):
        """Centralisé ici pour qu'aucun appelant ne puisse l'inverser."""
        ran, got, out = self._play(
            ["sudo", "apt-get", "install", "-y", "p"], "n"
        )
        self.assertLess(
            out.index("sudo apt-get install -y p"),
            out.index("Installer? (y/N): "),
        )
        self.assertEqual(ran, [])
        self.assertIsNone(got)

    def test_accepting_runs_it_and_gives_the_exit_code_back(self):
        """exec_command_live REND le code, il ne lève rien : l'appelant doit
        pouvoir le tester."""
        ran, got, _ = self._play(["sudo", "dnf", "install", "-y", "p"], "y")
        self.assertEqual(ran, ["sudo dnf install -y p"])
        self.assertEqual(got, 0)
        ran, got, _ = self._play(
            ["sudo", "dnf", "install", "-y", "p"], "y", status=127
        )
        self.assertEqual(got, 127)

    def test_no_command_is_said_not_silently_skipped(self):
        ran, got, out = self._play(None, "y")
        self.assertEqual(ran, [])
        self.assertIsNone(got)
        self.assertTrue(out.strip())

    def test_a_name_with_a_space_survives_the_display(self):
        """shlex.join, pour que la commande affichée soit celle qui tourne."""
        ran, _, out = self._play(
            ["sudo", "apt-get", "install", "-y", "a b"], "y"
        )
        self.assertIn("'a b'", out)
        self.assertIn("'a b'", ran[0])


class TestRefresh(unittest.TestCase):
    """Rafraîchir les index AVANT d'installer : un apt-get install sur un
    système neuf échoue sur des index vides, et Arch ne supporte pas la mise
    à jour partielle, d'où -Syu et jamais -Sy seul."""

    def test_each_family_refreshes_without_asking(self):
        self.assertEqual(
            todo_install.refresh_command("apt-get"),
            ["sudo", "apt-get", "update"],
        )
        self.assertEqual(
            todo_install.refresh_command("pacman"),
            ["sudo", "pacman", "-Syu", "--noconfirm"],
        )
        self.assertEqual(
            todo_install.refresh_command("zypper"),
            ["sudo", "zypper", "--non-interactive", "refresh"],
        )

    def test_dnf_refreshes_its_metadata_itself(self):
        self.assertIsNone(todo_install.refresh_command("dnf"))

    def test_no_family_no_command(self):
        with patch("script.todo.todo_install.family", return_value=None):
            self.assertIsNone(todo_install.refresh_command())


class _Exec:
    """Le lanceur du CLI, qui retient au lieu d'exécuter. `echecs` donne le
    code rendu par une commande qui commence par l'une de ses clés."""

    def __init__(self, echecs=None):
        self.ran, self.echecs = [], echecs or {}

    def exec_command_live(self, cmd, **kwargs):
        self.ran.append(cmd)
        for debut, code in self.echecs.items():
            if cmd.startswith(debut):
                return code
        return 0


def _yes(reponse):
    return reponse.strip().lower() in ("y", "o")


def _answers(*reponses):
    """input() qui écrit l'invite comme le vrai et répond dans l'ordre ;
    les invites posées s'accumulent dans `.posees`."""
    suite = iter(reponses)

    def demande(invite=""):
        demande.posees.append(invite)
        print(invite, end="")
        try:
            return next(suite)
        except StopIteration:
            raise AssertionError(f"question imprévue : {invite!r}") from None

    demande.posees = []
    return demande


class TestInstallSteps(unittest.TestCase):
    """Le rafraîchissement passe AVANT l'installation, dans une seule liste
    que tous les appelants lancent."""

    def test_the_refresh_comes_first(self):
        self.assertEqual(
            todo_install.install_steps(["p"], famille="apt-get"),
            [
                ["sudo", "apt-get", "update"],
                ["sudo", "apt-get", "install", "-y", "p"],
            ],
        )
        self.assertEqual(
            todo_install.install_steps(["p"], famille="zypper")[0],
            ["sudo", "zypper", "--non-interactive", "refresh"],
        )

    def test_dnf_has_only_the_install(self):
        self.assertEqual(
            todo_install.install_steps(["p"], famille="dnf"),
            [["sudo", "dnf", "install", "-y", "p"]],
        )

    def test_nothing_to_install_is_no_step_not_a_lone_refresh(self):
        self.assertEqual(
            todo_install.install_steps({"dnf": ["p"]}, famille="apt-get"), []
        )
        with patch("script.todo.todo_install.family", return_value=None):
            self.assertEqual(todo_install.install_steps(["p"]), [])

    def test_only_the_arch_refresh_is_a_full_upgrade(self):
        for famille in todo_install.FAMILIES:
            rafraichir = todo_install.refresh_command(famille)
            if rafraichir:
                self.assertTrue(todo_install.is_refresh(rafraichir))
                self.assertEqual(
                    todo_install.is_full_upgrade(rafraichir),
                    famille == "pacman",
                    famille,
                )
        installation = todo_install.install_command(["p"], famille="pacman")
        self.assertFalse(todo_install.is_refresh(installation))
        self.assertFalse(todo_install.is_full_upgrade(installation))


class TestRunSteps(unittest.TestCase):
    def _ask(self, famille, *reponses, echecs=None):
        ex = _Exec(echecs)
        demande = _answers(*reponses)
        buf = io.StringIO()
        with patch("builtins.input", demande), redirect_stdout(buf):
            got = todo_install.ask_and_install(
                ex,
                todo_install.install_steps(["p"], famille=famille),
                "Installer? (y/N): ",
                _yes,
            )
        return ex.ran, got, buf.getvalue(), demande.posees

    def test_one_question_runs_the_refresh_then_the_install(self):
        ran, got, out, posees = self._ask("apt-get", "y")
        self.assertEqual(
            ran, ["sudo apt-get update", "sudo apt-get install -y p"]
        )
        self.assertEqual(got, 0)
        self.assertEqual(len(posees), 1)
        # Les deux commandes sont lues avant d'être approuvées.
        self.assertLess(
            out.index("sudo apt-get install -y p"), out.index("Installer?")
        )

    def test_a_failed_refresh_stops_and_says_so(self):
        ran, got, out, _ = self._ask(
            "apt-get", "y", echecs={"sudo apt-get update": 100}
        )
        self.assertEqual(ran, ["sudo apt-get update"])
        self.assertEqual(got, 100)
        self.assertIn("❌", out)

    def test_an_empty_answer_never_upgrades_arch_even_for_default_yes(self):
        # Un appelant dont la règle accepte une réponse vide : l'installation
        # passe sur Entrée, la mise à jour complète du système non.
        ex = _Exec(None)
        demande = _answers("", "")
        with patch("builtins.input", demande), redirect_stdout(io.StringIO()):
            todo_install.ask_and_install(
                ex,
                todo_install.install_steps(["p"], famille="pacman"),
                "Installer? (Y/n): ",
                lambda r: r.strip().lower() in ("", "o", "oui", "y", "yes"),
            )
        self.assertNotIn("sudo pacman -Syu --noconfirm", ex.ran)
        self.assertEqual(len(ex.ran), 1)

    def test_the_arch_full_upgrade_is_announced_and_confirmed(self):
        ran, _, out, posees = self._ask("pacman", "y", "y")
        self.assertEqual(len(posees), 2)
        self.assertLess(
            out.index("sudo pacman -Syu --noconfirm"),
            out.index("Installer?"),
        )
        self.assertIn("⚠", out.split("Installer?")[0])
        self.assertEqual(
            ran,
            [
                "sudo pacman -Syu --noconfirm",
                "sudo pacman -S --needed --noconfirm p",
            ],
        )

    def test_the_full_upgrade_defaults_to_no(self):
        """Une entrée distraite ne met pas tout le système à jour : la
        mise à jour est sautée, l'installation part des index présents."""
        ran, got, _, posees = self._ask("pacman", "y", "")
        self.assertEqual(len(posees), 2)
        self.assertEqual(ran, ["sudo pacman -S --needed --noconfirm p"])
        self.assertEqual(got, 0)

    def test_refusing_the_install_asks_nothing_more(self):
        ran, got, _, posees = self._ask("pacman", "n")
        self.assertEqual(ran, [])
        self.assertIsNone(got)
        self.assertEqual(len(posees), 1)

    def test_a_single_command_still_works(self):
        """Le recours amont de starship reste une commande seule, en chaîne."""
        ex = _Exec()
        with (
            patch("builtins.input", _answers("y")),
            redirect_stdout(io.StringIO()),
        ):
            got = todo_install.ask_and_install(
                ex, "curl -sS x | sh", "Q? ", _yes
            )
        self.assertEqual(ex.ran, ["curl -sS x | sh"])
        self.assertEqual(got, 0)


class TestCallersRefreshFirst(unittest.TestCase):
    """Chaque appelant qui installe passe par install_steps : le
    rafraîchissement tourne avant le paquet, sans question de plus hors
    Arch."""

    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)
        self.todo.execute = _Exec()

    def _which(self, gestionnaire, installe_apres=()):
        ex = self.todo.execute

        def which(binaire):
            if binaire in todo_install.FAMILIES:
                return (
                    f"/usr/bin/{binaire}" if binaire == gestionnaire else None
                )
            if binaire in installe_apres and any(
                "install" in c or " -S " in c for c in ex.ran
            ):
                return f"/usr/bin/{binaire}"
            return None

        return which

    def _play(self, appel, gestionnaire, *reponses, installe_apres=()):
        with (
            patch("builtins.open", mock_open(read_data="")),
            patch("shutil.which", self._which(gestionnaire, installe_apres)),
            patch("builtins.input", _answers(*reponses)),
            redirect_stdout(io.StringIO()),
        ):
            got = appel()
        return self.todo.execute.ran, got

    def test_virt_viewer(self):
        ran, got = self._play(
            self.todo._qemu_ensure_virt_viewer,
            "apt-get",
            installe_apres=("virt-viewer",),
        )
        self.assertEqual(
            ran, ["sudo apt-get update", "sudo apt-get install -y virt-viewer"]
        )
        self.assertTrue(got)

    def test_virt_viewer_does_not_install_after_a_failed_refresh(self):
        self.todo.execute = _Exec({"sudo apt-get update": 100})
        ran, got = self._play(self.todo._qemu_ensure_virt_viewer, "apt-get")
        self.assertEqual(ran, ["sudo apt-get update"])
        self.assertFalse(got)

    def test_virt_viewer_asks_before_an_arch_full_upgrade(self):
        """Seule installation du CLI posée sans question : la mise à jour
        complète du système, elle, se demande, défaut Non."""
        ran, _ = self._play(
            self.todo._qemu_ensure_virt_viewer,
            "pacman",
            "",
            installe_apres=("virt-viewer",),
        )
        self.assertEqual(
            ran, ["sudo pacman -S --needed --noconfirm virt-viewer"]
        )

    def test_shrink_tools(self):
        ran, _ = self._play(
            lambda: self.todo._qemu_install_shrink_tools(["sgdisk"]),
            "zypper",
            "y",
        )
        self.assertEqual(
            ran,
            [
                "sudo zypper --non-interactive refresh",
                "sudo zypper --non-interactive install gptfdisk",
            ],
        )

    def test_starship(self):
        ran, _ = self._play(
            self.todo._shell_install_starship_binary,
            "apt-get",
            "y",
            installe_apres=("starship",),
        )
        self.assertEqual(
            ran, ["sudo apt-get update", "sudo apt-get install -y starship"]
        )

    def test_cli_browser(self):
        ran, got = self._play(
            self.todo._qemu_install_cli_browser,
            "apt-get",
            "",
            "y",
            installe_apres=("w3m",),
        )
        self.assertEqual(
            ran, ["sudo apt-get update", "sudo apt-get install -y w3m"]
        )
        self.assertEqual(got, "w3m")

    def test_the_monitor_browser_steps_refresh_first(self):
        from script.todo.qemu_install_monitor import browser_install_command

        with (
            patch("builtins.open", mock_open(read_data="")),
            patch("shutil.which", self._which("apt-get")),
        ):
            etapes = browser_install_command("lynx")
        self.assertEqual(
            etapes,
            [
                ["sudo", "apt-get", "update"],
                ["sudo", "apt-get", "install", "-y", "lynx"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
