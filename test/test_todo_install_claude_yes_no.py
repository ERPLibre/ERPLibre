#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installation, l'identité git, les tunnels SSH, le cache QEMU, les
hooks git et les réglages de Claude Code : les questions oui/non de
todo.py, sous les règles de `ui.confirm`.

Chaque question est non par défaut, sauf trois qui sont oui : la première
installation du système quand un paquet manque, configurer l'identité git
maintenant, ajouter les connexions manquantes à virt-manager. Un refus —
Entrée là où le défaut est non, n, non, une faute puis Ctrl+D, Ctrl+D —
n'installe, n'écrit, ne lance ni ne redéploie rien ; o, oui, y et yes
agissent.

Les questions de l'installation (système, PyCharm, identité git) prennent
`back` : Ctrl+D y rend la main sans rien installer.

Rien ne part : `exec_command_live`, l'écriture des réglages, la pose des
hooks, le redéploiement et les plugins sont des doubles qui notent ; ce
qui s'écrit vraiment vit dans un dossier temporaire. Un `ScriptedPort`
répond aux questions du port ; `input` ne lit que les valeurs tapées.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import todo as todo_module  # noqa: E402
from script.todo import todo_i18n, ui  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.todo.ui.port import ScriptedPort  # noqa: E402

HOST = "forged-yesno-host"
NAME, EMAIL = "Forged Yesno", "forged@yesno.invalid"
# Défaut non : une réponse vide, une faute puis Ctrl+D, Ctrl+D refusent.
REFUS = ([""], ["n"], ["peut-être", EOFError()], [EOFError()])
OUI = (["o"], ["oui"], ["y"], ["YES"])
# Défaut oui : n, non, une faute puis Ctrl+D, Ctrl+D refusent.
REFUS_OUI = (["n"], ["non"], ["peut-être", EOFError()], [EOFError()])
OUI_OUI = ([""], *OUI)


class _Execute:
    """Note chaque commande, sans rien lancer."""

    def __init__(self):
        self.cmds = []

    def exec_command_live(self, cmd, **_opts):
        self.cmds.append(cmd)
        return 0


def _todo():
    todo = TODO.__new__(TODO)
    todo.execute = _Execute()
    return todo


class _Base(unittest.TestCase):
    def setUp(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")

    def play(self, call, answers, typed=()):
        """Ce que rend `call()` quand `answers` répondent, dans l'ordre, par
        un `ScriptedPort` (`self.port`) ; `typed` répond aux valeurs lues
        par `input`, qu'aucune autre question ne lit. `self.out` garde ce
        qui s'imprime."""
        with (
            mock.patch(
                "builtins.input",
                side_effect=list(typed) if typed else AssertionError,
            ),
            mock.patch("builtins.print") as self.out,
            ui.bind(ScriptedPort(list(answers))) as self.port,
        ):
            return call()

    def shown(self):
        return [
            " ".join(str(a) for a in c.args) for c in self.out.call_args_list
        ]

    def asked(self, prompt):
        """Chaque question oui/non `prompt` posée, (texte, défaut « y » ou
        « n », `back`), une fois de plus après chaque faute."""
        return [
            (e["prompt"], e["default"], e.get("back", False))
            for e in self.port.events
            if e.get("kind") == "confirm" and e["prompt"] == prompt
        ]

    def notices(self):
        return [e["text"] for e in self.port.events if e.get("t") == "notice"]

    def check(
        self,
        make,
        prompt,
        default=False,
        back=False,
        pre=(),
        post=(),
        after=(),
        typed=(),
    ):
        """`make()` rend (`call`, `acted`), neufs pour chaque cas ; la
        question oui/non `prompt`, de défaut `default`, suit les réponses
        `pre` du port et les valeurs tapées `typed` ; `post` suit un oui,
        `after` toute réponse. Chaque refus laisse `acted()` faux, chaque
        oui le rend vrai, chaque réponse est lue ; une faute est dite, puis
        la question revient ; le message porte `back` quand il est dit."""
        refus, oui = (REFUS_OUI, OUI_OUI) if default else (REFUS, OUI)
        cases = [(r, False) for r in refus] + [(o, True) for o in oui]
        for answers, expected in cases:
            with self.subTest(answers=answers):
                call, acted = make()
                tail = [*post] if expected else []
                self.play(call, [*pre, *answers, *tail, *after], typed)
                fois = 2 if "peut-être" in answers else 1
                posee = (prompt, "y" if default else "n", back)
                self.assertEqual(self.asked(prompt), [posee] * fois)
                self.assertEqual(self.port.answers, [])
                self.assertIs(acted(), expected)
                if "peut-être" in answers:
                    self.assertIn(
                        f"{t('Answer yes or no: ')}peut-être", self.notices()
                    )


SYSTEME = "First system installation? Installs the system packages first"


class TestInstallation(_Base):
    """La première installation du système, PyCharm et l'identité git :
    Ctrl+D rend la main à l'installation, qui ne lance rien."""

    def systeme(self, manque):
        todo = _todo()
        patcher = mock.patch.object(
            TODO, "_systeme_manquant", staticmethod(lambda: manque)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return todo

    def test_the_system_step_defaults_to_what_is_missing(self):
        for manque, default in ((["psql"], True), ([], False)):
            with self.subTest(manque=manque):
                todo = self.systeme(manque)
                rendu = []

                def make():
                    rendu.clear()

                    def call():
                        rendu.append(todo._demander_systeme())

                    return call, lambda: rendu[0] is True

                self.check(make, t(SYSTEME), default=default, back=True)

    def test_ctrl_d_at_the_system_step_goes_back(self):
        todo = self.systeme(["psql"])
        for answers in ([EOFError()], ["peut-être", EOFError()]):
            with self.subTest(answers=answers):
                self.assertIsNone(self.play(todo._demander_systeme, answers))
        todo = self.systeme([])
        self.assertIsNone(self.play(todo._install_system_step, []))
        self.assertEqual(todo.execute.cmds, [])

    def pycharm(self):
        """(`call`, `acted`) d'une étape sans installation système où
        PyCharm est présent et le projet sans `.idea` ; `self.rendu` garde
        ce que l'étape rend."""
        todo = _todo()
        self.rendu = []
        exists = os.path.exists

        def run(cmd, *_args, **_kwargs):
            return subprocess.CompletedProcess(cmd, 0, "", "")

        def call():
            with (
                mock.patch.object(todo_module.subprocess, "run", run),
                mock.patch.object(
                    todo_module.os.path,
                    "exists",
                    lambda p: False if p == ".idea" else exists(p),
                ),
                mock.patch.object(
                    TODO, "_wait_pycharm_closed", return_value=True
                ),
            ):
                self.rendu.append(todo._install_system_step(systeme=False))

        return call, lambda: any("pycharm" in c for c in todo.execute.cmds)

    def test_pycharm_opens_on_a_yes_only(self):
        self.check(self.pycharm, t("Open PyCharm?"), back=True)

    def test_ctrl_d_at_open_pycharm_goes_back(self):
        for answers in ([EOFError()], ["peut-être", EOFError()]):
            with self.subTest(answers=answers):
                call, acted = self.pycharm()
                self.play(call, answers)
                self.assertEqual(self.rendu, [None])
                self.assertFalse(acted())
        call, _ = self.pycharm()
        self.play(call, ["n"])
        self.assertEqual(self.rendu, [0])

    def identite(self):
        """(`call`, `acted`) de l'identité git, absente ; `self.rendu`
        garde ce que l'offre rend, `self.ecrits` chaque écriture."""
        todo = _todo()
        self.rendu, self.ecrits = [], []

        def fragment(fonction, *args):
            if fonction != "repo_identity_ready":
                self.ecrits.append((fonction, *args))
            code = 1 if fonction == "repo_identity_ready" else 0
            return subprocess.CompletedProcess(fonction, code, "", "")

        def call():
            with mock.patch.object(
                TODO, "_fragment_repo_init", staticmethod(fragment)
            ):
                self.rendu.append(todo._proposer_identite_git())

        return call, lambda: bool(self.ecrits)

    def test_the_git_identity_is_offered_yes_by_default(self):
        self.check(
            self.identite,
            t("Configure it now?"),
            default=True,
            back=True,
            post=[NAME, EMAIL, "o"],
        )

    def test_the_git_identity_is_written_once_confirmed(self):
        self.check(
            self.identite,
            t("Is this correct?"),
            back=True,
            pre=["o", NAME, EMAIL],
        )
        self.assertEqual(self.ecrits, [("repo_identity_set", NAME, EMAIL)])

    def test_ctrl_d_at_either_identity_question_installs_nothing(self):
        # Ctrl+D rend False : l'appelant revient sans installer ; un non à
        # la première question laisse l'installation suivre, sans écrire.
        for answers, rendu in (
            ([], False),
            (["peut-être", EOFError()], False),
            (["n"], True),
            (["o", NAME, EMAIL, EOFError()], False),
            (["", NAME, EMAIL, "n", EOFError()], False),
        ):
            with self.subTest(answers=answers):
                call, acted = self.identite()
                self.play(call, answers)
                self.assertEqual(self.rendu, [rendu])
                self.assertFalse(acted())
                self.assertEqual(self.port.answers, [])


class TestRun(_Base):
    """Run : la cible make d'une instance ne tourne que sur un oui."""

    def test_a_new_instance_is_made_on_a_yes_only(self):
        def make():
            todo = _todo()
            todo.execute_from_configuration = mock.Mock()

            def acted():
                appel = todo.execute_from_configuration.call_args
                return not appel.kwargs["ignore_makefile"]

            def call():
                todo._run_instance({"makefile_cmd": "forged_yesno"})

            return call, acted

        self.check(make, t("Do you want a new instance?"))


class TestDeploy(_Base):
    """virt-manager, le cache QEMU et les tunnels SSH : rien ne part sans
    oui, sauf l'ajout à virt-manager, oui par défaut."""

    def test_virt_manager_connections_are_added_yes_by_default(self):
        def make():
            todo = _todo()
            todo._virt_manager_uris = lambda: []
            todo._virt_manager_set_label = lambda uri, label: None
            todo._virt_manager_add = mock.Mock(return_value=0)

            def call():
                todo._virt_manager_offer([(HOST, "forged")])

            return call, lambda: todo._virt_manager_add.called

        self.check(
            make,
            t("Add the missing connections to virt-manager?"),
            default=True,
        )

    def test_the_qemu_cache_installs_on_a_yes_only(self):
        def make():
            todo = _todo()
            call = todo._deploy_qemu_cache
            return call, lambda: bool(todo.execute.cmds)

        self.check(
            make,
            t("Install the QEMU download cache?"),
            typed=["", "", ""],
        )

    def tunnel(self, ouvert, libre):
        """(`call`, `acted`) d'une redirection de port vers HOST, dont le
        port distant répond `ouvert` et le port local est `libre`."""
        todo = _todo()
        todo._ssh_config_hosts = lambda: [HOST]
        todo._remote_port_open = lambda host, port: ouvert
        todo._port_is_free = lambda port: libre
        return todo._deploy_port_forward, lambda: bool(todo.execute.cmds)

    def test_a_closed_remote_port_opens_on_a_yes_only(self):
        self.check(
            lambda: self.tunnel(False, True),
            t("Continue anyway?"),
            pre=["1", "", ""],
        )

    def test_a_busy_local_port_opens_on_a_yes_only(self):
        self.check(
            lambda: self.tunnel(True, False),
            t("Try anyway?"),
            pre=["1", "", ""],
        )

    def test_a_busy_socks_port_opens_on_a_yes_only(self):
        def make():
            todo = _todo()
            todo._ask_ssh_target = lambda: (HOST,)
            todo._first_free_port = lambda debut, essais=20: (
                debut if debut == 1080 else None
            )
            todo._port_is_free = lambda port: False
            call = todo._deploy_socks_proxy
            return call, lambda: bool(todo.execute.cmds)

        self.check(make, t("Try anyway?"), pre=[""])


class TestGitEtClaude(_Base):
    """Les hooks git, les réglages du dépôt, les commandes et les plugins
    de Claude Code : rien ne s'écrit, ne se redéploie ni ne s'installe
    sans oui."""

    def racine(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def test_another_hooks_path_is_replaced_on_a_yes_only(self):
        racine = self.racine()
        os.makedirs(os.path.join(racine, TODO._GIT_HOOKS_PATH))

        def make():
            todo = _todo()
            todo._claude_context_root = lambda: racine
            todo._git_hooks_path = lambda _racine: "/forged/hooks"
            pose = mock.Mock(return_value=(False, []))

            def call():
                with mock.patch.object(
                    todo_module.todo_etat, "installer_hooks_git", pose
                ):
                    todo._git_install_hooks()

            return call, lambda: pose.called

        self.check(make, t("Replace it?"))

    def test_the_repository_settings_are_written_on_a_yes_only(self):
        racine = self.racine()

        def make():
            todo = _todo()
            todo._claude_context_root = lambda: racine
            ecrit = mock.Mock()

            def call():
                with mock.patch.object(
                    todo_module.claude_reglages, "ecrire", ecrit
                ):
                    todo._claude_reglages_ecrire({})

            return call, lambda: ecrit.called

        self.check(make, t("Write it?"))

    def commandes(self):
        """Un TODO dont la seule commande, /forged_yesno, est périmée."""
        dossier = self.racine()
        gabarit = os.path.join(dossier, "gabarit.md")
        with open(gabarit, "w", encoding="utf-8") as flux:
            flux.write("neuf\n")
        with open(os.path.join(dossier, "forged_yesno.md"), "w") as flux:
            flux.write("ancien\n")
        todo = _todo()
        todo._CLAUDE_COMMANDS_DIR = dossier
        todo._CLAUDE_COMMAND_TEMPLATES = {"forged_yesno": "gabarit.md"}
        todo._claude_template_path = lambda _nom: gabarit
        todo._redeploy_claude_command = mock.Mock()
        return todo

    def test_the_differences_show_on_a_yes_only(self):
        def make():
            todo = self.commandes()

            def acted():
                return "-ancien" in self.shown()

            return todo._list_claude_commands, acted

        self.check(make, t("Show the differences?"), after=["n"])

    def test_outdated_commands_are_redeployed_on_a_yes_only(self):
        def make():
            todo = self.commandes()
            redeploy = todo._redeploy_claude_command
            return todo._list_claude_commands, lambda: redeploy.called

        question = t("Redeploy the %s outdated command(s)?") % 1
        self.check(make, question, pre=["n"])

    def test_an_existing_command_is_overwritten_on_a_yes_only(self):
        home = self.racine()
        dest = os.path.join(home, ".claude", "commands", "forged_yesno.md")
        gabarit = "template_claude_commands_git_prepare_merge.md"

        def make():
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as flux:
                flux.write("ancien\n")
            todo = _todo()

            def call():
                with mock.patch.dict(os.environ, {"HOME": home}):
                    todo._setup_claude_command("forged_yesno", gabarit)

            def acted():
                with open(dest, encoding="utf-8") as flux:
                    return flux.read() != "ancien\n"

            return call, acted

        self.check(make, t("Do you want to overwrite the file?"))

    def test_the_preferred_plugins_install_on_a_yes_only(self):
        def make():
            todo = _todo()
            todo._claude_plugin_exec = mock.Mock()
            todo._claude_plugin_is_installed = lambda name: False
            call = todo._claude_install_preferred_plugins
            return call, lambda: todo._claude_plugin_exec.called

        self.check(make, t("Install these plugins?"))

    def test_a_plugin_is_uninstalled_on_a_yes_only(self):
        def make():
            todo = _todo()
            todo._claude_plugin_exec = mock.Mock()
            call = todo._claude_plugin_uninstall
            return call, lambda: todo._claude_plugin_exec.called

        self.check(
            make, t("Uninstall this plugin?"), typed=["forged-yesno-plugin"]
        )


if __name__ == "__main__":
    unittest.main()
