#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les choix des écrans de todo.py suivent les règles des sélecteurs.

Un numéro tel que la liste l'écrit, ou le nom exact qu'elle affiche ;
[0] Retour ; une réponse vide qui prend le défaut marqué, ou revient sans
lui ; une réponse invalide dite, puis la question reposée ; Ctrl+D qui
revient. Chaque réponse vient d'un double d'`input`, qui finit par une
réponse acceptée ou par « 0 » ; rien n'écrit dans env_var.sh ni dans les
préférences, et ce qu'un choix lancerait est un double qui note son appel.
"""

import contextlib
import io
import unittest
from unittest.mock import patch

from script.todo import todo as todo_module
from script.todo.todo import TODO
from script.todo.todo_i18n import t


def joue(action, *reponses):
    """(ce que rend `action()`, ce qu'elle imprime), chaque `input`
    répondu par `reponses`, dans l'ordre ; une réponse qui est une
    exception est levée à sa place, EOFError pour Ctrl+D."""
    with (
        patch("builtins.input", side_effect=reponses),
        contextlib.redirect_stdout(io.StringIO()) as sortie,
    ):
        rendu = action()
    return rendu, sortie.getvalue()


class TestLaLangue(unittest.TestCase):
    """La langue du premier lancement, puis Configuration › Language /
    Langue ; `set_lang`, qui écrit env_var.sh, est un double."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        patcher = patch.object(todo_module, "set_lang")
        self.set_lang = patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_first_launch_takes_a_number_or_a_shown_name(self):
        cas = (
            (["1"], "fr"),
            (["English"], "en"),
            (["01", "2"], "en"),
            (["français", "Français"], "fr"),
        )
        with patch.object(
            todo_module, "lang_is_configured", return_value=False
        ):
            for reponses, langue in cas:
                with self.subTest(reponses=reponses):
                    self.set_lang.reset_mock()
                    _, sortie = joue(self.todo._ask_language, *reponses)
                    self.set_lang.assert_called_once_with(langue)
                    fautes = sortie.count(t("Invalid choice: "))
                    self.assertEqual(fautes, len(reponses) - 1)

    def test_the_first_launch_left_open_keeps_no_language(self):
        # [0], une réponse vide ou Ctrl+D : rien n'est gardé, et TODO
        # redemande au lancement suivant.
        with patch.object(
            todo_module, "lang_is_configured", return_value=False
        ):
            for reponse in ("0", "", EOFError()):
                with self.subTest(reponse=reponse):
                    _, sortie = joue(self.todo._ask_language, reponse)
                    self.assertIn("[0] ", sortie)
        self.set_lang.assert_not_called()

    def test_a_configured_language_asks_nothing(self):
        with patch.object(
            todo_module, "lang_is_configured", return_value=True
        ):
            _, sortie = joue(self.todo._ask_language)
        self.assertEqual(sortie, "")
        self.set_lang.assert_not_called()

    def test_the_language_changes_by_number_or_shown_name(self):
        for reponses, langue in (
            (["2"], "en"),
            ([t("French")], "fr"),
            (["x", "+1", "1"], "fr"),
        ):
            with self.subTest(reponses=reponses):
                self.set_lang.reset_mock()
                rendu, sortie = joue(self.todo._change_language, *reponses)
                self.set_lang.assert_called_once_with(langue)
                self.assertIsNone(rendu)
                fautes = sortie.count(t("Invalid choice: "))
                self.assertEqual(fautes, len(reponses) - 1)

    def test_back_or_an_empty_answer_changes_nothing(self):
        for reponse in ("0", "", EOFError()):
            with self.subTest(reponse=reponse):
                rendu, _ = joue(self.todo._change_language, reponse)
                self.assertIs(rendu, False)
        self.set_lang.assert_not_called()


class TestLesPreferences(unittest.TestCase):
    """Configuration › QEMU deployment interface : la valeur courante est
    le défaut marqué ; les préférences sont un dict."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.prefs = {"qemu_deploy_ui": "tui"}
        prefs = todo_module.todo_prefs
        for patcher in (
            patch.object(prefs, "get", side_effect=self.prefs.get),
            patch.object(prefs, "set", side_effect=self.prefs.__setitem__),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def edit(self, *reponses):
        return joue(lambda: self.todo._pref_edit("qemu_deploy_ui"), *reponses)

    def test_a_value_by_its_number_as_shown(self):
        _, sortie = self.edit("03", "+3", "3")
        self.assertEqual(self.prefs["qemu_deploy_ui"], "cli")
        self.assertEqual(sortie.count(t("Invalid choice: ")), 2)
        self.assertIn(f"✅ {t('QEMU deployment interface')} :", sortie)

    def test_the_current_value_is_the_default_an_empty_answer_keeps(self):
        _, sortie = self.edit("")
        self.assertIn(f"[2] {t('TUI form')} {t('(default)')}\n", sortie)
        self.assertEqual(self.prefs["qemu_deploy_ui"], "tui")

    def test_back_writes_nothing(self):
        for reponse in ("0", EOFError()):
            with self.subTest(reponse=reponse):
                with patch.object(todo_module.todo_prefs, "set") as ecrit:
                    _, sortie = self.edit(reponse)
                ecrit.assert_not_called()
                self.assertNotIn("✅", sortie)


class Execute:
    """Le double d'`Execute` : note chaque commande, n'en lance aucune."""

    def __init__(self):
        self.commandes = []

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        return 0


ENTREES = [
    ("forged-a", {"hostname": "192.0.2.10", "user": "forged"}),
    ("forged-b", {}),
]


class TestLaCibleSSH(unittest.TestCase):
    """La saisie à la main ou un hôte de ~/.ssh/config, puis l'hôte, que
    lisent le proxy SOCKS et le montage sshfs ; ~/.ssh/config est un
    double."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        patcher = patch.object(
            TODO, "_ssh_config_entries", return_value=ENTREES
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def cible(self, *reponses):
        return joue(self.todo._ask_ssh_target, *reponses)

    def test_a_host_by_its_number_or_its_alias(self):
        for reponses, attendu in (
            (["2", "1"], ("forged-a", "forged", "192.0.2.10", "forged-a")),
            (["2", "forged-b"], ("forged-b",) * 4),
        ):
            with self.subTest(reponses=reponses):
                rendu, sortie = self.cible(*reponses)
                self.assertEqual(rendu[0], attendu[0])
                self.assertEqual(rendu[2:4], attendu[2:4])
                self.assertIs(rendu[4], True)
                self.assertIn("[1] forged-a (192.0.2.10) [forged]\n", sortie)

    def test_an_empty_answer_types_the_address_by_hand(self):
        rendu, sortie = self.cible("", "forged@198.51.100.7")
        self.assertEqual(
            rendu,
            (
                "forged@198.51.100.7",
                "forged",
                "198.51.100.7",
                "198.51.100.7",
                False,
            ),
        )
        self.assertIn(f"[1] {t('Manual entry')} {t('(default)')}", sortie)

    def test_back_at_either_list_gives_up(self):
        for reponses in (
            ["0"],
            [EOFError()],
            ["2", "0"],
            ["2", ""],
            ["2", EOFError()],
        ):
            with self.subTest(reponses=reponses):
                rendu, _ = self.cible(*reponses)
                self.assertIsNone(rendu)

    def test_a_typo_asks_again(self):
        rendu, sortie = self.cible("3", "x", "2", "forged-A", "01", "1")
        self.assertEqual(rendu[0], "forged-a")
        self.assertEqual(sortie.count(t("Invalid choice: ")), 4)

    def test_neither_tunnel_nor_mount_without_a_target(self):
        # Les deux appelants reviennent sur [0] avant de rien lancer ni
        # créer : ni ssh, ni répertoire de montage.
        self.todo.execute = Execute()
        with patch("os.makedirs") as cree:
            for appelant in ("_deploy_socks_proxy", "_configure_sshfs"):
                with self.subTest(appelant=appelant):
                    joue(getattr(self.todo, appelant), "0")
        self.assertEqual(self.todo.execute.commandes, [])
        cree.assert_not_called()


class TestLaRedirectionDePort(unittest.TestCase):
    """Deploy › SSH port forwarding : un hôte de ~/.ssh/config ou une
    adresse tapée ; la sonde du port distant et le tunnel sont des
    doubles."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo.execute = Execute()
        self.hotes = ["forged-a", "forged-b"]
        for nom, valeur in (
            ("_ssh_config_hosts", lambda: self.hotes),
            ("_remote_port_open", lambda host, port: True),
            ("_port_is_free", lambda port: True),
        ):
            patcher = patch.object(self.todo, nom, valeur)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tunnel(self, *reponses):
        _, sortie = joue(self.todo._deploy_port_forward, *reponses)
        return self.todo.execute.commandes, sortie

    def test_a_host_by_its_number_or_its_name(self):
        for reponses, hote in (
            (["2"], "forged-b"),
            (["forged-a"], "forged-a"),
        ):
            with self.subTest(reponses=reponses):
                self.todo.execute.commandes.clear()
                commandes, _ = self.tunnel(*reponses, "", "")
                self.assertEqual(
                    commandes, [f"ssh -N -L 8069:localhost:8069 {hote}"]
                )

    def test_another_host_is_typed_after_the_list(self):
        commandes, sortie = self.tunnel("3", "forged@192.0.2.9", "", "")
        self.assertIn(f"[3] {t('Type an address')}\n", sortie)
        self.assertEqual(
            commandes, ["ssh -N -L 8069:localhost:8069 forged@192.0.2.9"]
        )

    def test_without_a_declared_host_the_address_is_asked(self):
        self.hotes = []
        commandes, sortie = self.tunnel("forged-c", "", "")
        self.assertNotIn("[0]", sortie)
        self.assertEqual(commandes, ["ssh -N -L 8069:localhost:8069 forged-c"])

    def test_back_or_no_address_opens_nothing(self):
        for reponses in (
            ["0"],
            [""],
            [EOFError()],
            ["3", ""],
            ["3", EOFError()],
        ):
            with self.subTest(reponses=reponses):
                commandes, _ = self.tunnel(*reponses)
                self.assertEqual(commandes, [])
        self.hotes = []
        commandes, sortie = self.tunnel("")
        self.assertEqual(commandes, [])
        self.assertIn(t("Cancelled."), sortie)
        commandes, _ = self.tunnel(EOFError())
        self.assertEqual(commandes, [])

    def test_a_typo_asks_again(self):
        commandes, sortie = self.tunnel("forged-B", "01", "1", "", "")
        self.assertEqual(sortie.count(t("Invalid choice: ")), 2)
        self.assertEqual(commandes, ["ssh -N -L 8069:localhost:8069 forged-a"])


class TestLAnalyse(unittest.TestCase):
    """Execute › Analyse : la source d'une analyse, puis « aller plus
    loin » ; la base, la sauvegarde et ce qu'une entrée lance sont des
    doubles."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.demandes = []
        self.todo._analyse_select_database = lambda: (
            self.demandes.append("base") or "forged_db"
        )
        self.todo.db_manager = type(
            "Bases",
            (),
            {
                "select_backup_path": lambda _s: (
                    self.demandes.append("zip") or "/forged/copie.zip"
                )
            },
        )()

    def test_a_source_by_its_number(self):
        for reponses, attendu in (
            (["1"], (False, "forged_db")),
            (["2"], (True, "/forged/copie.zip")),
            (["3", "01", "1"], (False, "forged_db")),
        ):
            with self.subTest(reponses=reponses):
                rendu, sortie = joue(
                    self.todo._analyse_select_source, *reponses
                )
                self.assertEqual(rendu, attendu)
                fautes = sortie.count(t("Invalid choice: "))
                self.assertEqual(fautes, len(reponses) - 1)

    def test_back_asks_for_no_database_and_no_backup(self):
        for reponse in ("0", "", EOFError()):
            with self.subTest(reponse=reponse):
                rendu, sortie = joue(self.todo._analyse_select_source, reponse)
                self.assertIsNone(rendu)
                self.assertIn(f"[0] {t('Back')}", sortie)
        self.assertEqual(self.demandes, [])

    def suite(self, *reponses, rend=None):
        """Les rangs que reçoit le `handler` d'« aller plus loin », qui
        rend `rend`, et ce qui s'imprime."""
        rangs = []
        choix = [
            {"prompt_description": t("Show every entry")},
            {"prompt_description": t("Export as JSON")},
        ]
        _, sortie = joue(
            lambda: self.todo._analyse_follow_up(
                choix, lambda rang: rangs.append(rang) or rend
            ),
            *reponses,
        )
        return rangs, sortie

    def test_going_further_asks_again_until_back(self):
        rangs, sortie = self.suite("2", "1", "0")
        self.assertEqual(rangs, [2, 1])
        self.assertIn(f"[2] {t('Export as JSON')}\n", sortie)
        self.assertEqual(sortie.count(t("Go further")), 3)

    def test_going_further_a_typo_asks_again_and_empty_goes_back(self):
        rangs, sortie = self.suite("x", "01", "2", "")
        self.assertEqual(rangs, [2])
        self.assertEqual(sortie.count(t("Invalid choice: ")), 2)

    def test_going_further_closes_on_ctrl_d(self):
        rangs, _ = self.suite("2", EOFError())
        self.assertEqual(rangs, [2])

    def test_a_handler_that_returns_false_closes_the_list(self):
        rangs, _ = self.suite("1", rend=False)
        self.assertEqual(rangs, [1])


if __name__ == "__main__":
    unittest.main()
