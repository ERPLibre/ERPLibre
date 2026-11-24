#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Accès aux VM QEMU et cache de téléchargement : les questions oui/non,
sous les règles de `ui.confirm`.

Chaque question du cache est non par défaut : Entrée, une faute puis
Ctrl+D et Ctrl+D n'effacent, n'envoient, n'écrivent ni ne lancent rien ;
o, oui, y et yes agissent. La clé proposée sur une identité SSH refusée
est oui par défaut : Entrée la déploie, non et Ctrl+D la laissent.

ssh, sudo, du et les tests longs ne partent jamais : `execute` note chaque
commande, `subprocess.run` et `_longtest_run` sont des doubles qui notent.
Un `ScriptedPort` répond aux questions du port ; `click.prompt` ne lit que
les valeurs tapées.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_access, todo_i18n, ui  # noqa: E402
from script.todo import qemu_cache_menu as menu  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.todo.ui.port import ScriptedPort  # noqa: E402

VM = "forged-yesno-vm"
HOST = "forged-yesno-host"
# Une réponse vide, une faute puis Ctrl+D, Ctrl+D : chacune vaut non.
REFUS = ([""], ["peut-être", EOFError()], [EOFError()])
OUI = (["o"], ["oui"], ["y"], ["YES"])


class _Execute:
    """Note chaque commande, sans rien lancer."""

    def __init__(self):
        self.cmds = []

    def exec_command_live(self, cmd, **_opts):
        self.cmds.append(cmd)
        return 0


class _Base(unittest.TestCase):
    def setUp(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")
        self.todo = TODO.__new__(TODO)
        self.todo.execute = _Execute()

    def play(self, call, answers, typed=()):
        """Ce que rend `call()` quand `answers` répondent, dans l'ordre, par
        un `ScriptedPort` (`self.port`) ; `typed` répond aux valeurs lues
        par `click.prompt`, qu'aucune autre question ne lit."""
        with (
            mock.patch(
                "click.prompt",
                side_effect=list(typed) if typed else AssertionError,
            ),
            mock.patch("builtins.input", side_effect=AssertionError),
            mock.patch("builtins.print"),
            ui.bind(ScriptedPort(list(answers))) as self.port,
        ):
            return call()

    def asked(self):
        """(texte sans indice, défaut « y » ou « n ») de chaque question
        oui/non posée, une fois de plus après chaque faute."""
        return [
            (event["prompt"], event["default"])
            for event in self.port.events
            if event.get("kind") == "confirm"
        ]

    def check(self, call, key, acted, typed=(), default=False):
        """La seule question oui/non de `call` est `key`, de défaut
        `default` : chaque refus laisse `acted()` faux, chaque oui le rend
        vrai, et chaque réponse est lue ; une faute est dite, puis la
        question revient."""
        refus = list(REFUS)
        oui = list(OUI)
        if default:
            refus = [["n"], ["non"], ["peut-être", EOFError()], [EOFError()]]
            oui = [[""], *OUI]
        cases = [(r, False) for r in refus] + [(o, True) for o in oui]
        for answers, expected in cases:
            with self.subTest(answers=answers):
                self.todo.execute.cmds.clear()
                self.play(call, answers, typed)
                posee = (t(key), "y" if default else "n")
                fois = 2 if "peut-être" in answers else 1
                self.assertEqual(self.asked(), [posee] * fois)
                self.assertEqual(self.port.answers, [])
                self.assertIs(acted(), expected)
                if "peut-être" in answers:
                    notices = [
                        e["text"]
                        for e in self.port.events
                        if e.get("t") == "notice"
                    ]
                    self.assertIn(
                        f"{t('Answer yes or no: ')}peut-être", notices
                    )

    def ran(self, fragment):
        return any(fragment in cmd for cmd in self.todo.execute.cmds)


class TestLeNettoyageDuCache(_Base):
    """Age and cleanup : l'aperçu à blanc part toujours, l'effacement sur
    un oui seulement."""

    def test_erasing_what_has_not_served_waits_for_a_yes(self):
        def purged():
            self.assertTrue(self.ran("--dry-run"), "l'aperçu manque")
            return any(
                "--purge-older-than" in c and "--dry-run" not in c
                for c in self.todo.execute.cmds
            )

        self.check(
            self.todo._cache_nettoyer_age,
            "Erase what is listed above?",
            purged,
            typed=["30j"],
        )

    def test_erasing_the_whole_cache_waits_for_a_yes(self):
        def purged():
            self.assertTrue(self.ran("--purge --dry-run"), "l'aperçu manque")
            return any(
                " --purge " in c and "--dry-run" not in c
                for c in self.todo.execute.cmds
            )

        self.check(
            self.todo._cache_nettoyer_tout, "Erase the whole cache?", purged
        )

    def test_forgetting_a_url_waits_for_a_yes(self):
        def forgotten():
            self.assertTrue(self.ran("--detient"), "l'aperçu manque")
            return self.ran("--oublie")

        self.check(
            self.todo._cache_oublier_url,
            "Remove this entry from the store?",
            forgotten,
            typed=[f"https://{HOST}.example/objet"],
        )

    def test_a_cleanup_setting_is_written_only_on_a_yes(self):
        self.check(
            lambda: self.todo._cache_nettoyage_regler("EL_PURGE_AGE"),
            "Write this setting?",
            lambda: self.ran("EL_PURGE_AGE=90j"),
            typed=["90j"],
        )


class TestLesMiroirs(_Base):
    def test_removing_a_mirror_waits_for_a_yes(self):
        self.check(
            self.todo._cache_miroir_retirer,
            "Remove this mirror?",
            lambda: self.ran("--git-mirror-remove"),
            typed=[VM],
        )

    def test_filling_the_mirrors_waits_for_a_yes(self):
        maison = self.enterContext(tempfile.TemporaryDirectory())
        vraie = os.path.expanduser
        self.enterContext(
            mock.patch(
                "os.path.expanduser",
                lambda p: maison + p[1:] if p.startswith("~") else vraie(p),
            )
        )
        self.enterContext(
            mock.patch.object(menu, "environnement_de_l_unite", list)
        )
        self.check(
            lambda: self.todo._cache_miroir_remplir(
                [f"https://{HOST}.example/depot.git"]
            ),
            "Fill the git mirrors now?",
            lambda: self.ran("--git-mirror-prefetch"),
        )


class TestLeTransfert(_Base):
    """Copy it to another machine : rien ne voyage sans un oui."""

    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(menu, "CACHE_BIN", __file__))
        self.enterContext(
            mock.patch.object(
                menu.cache_offline, "reglage", return_value="/var/cache/x"
            )
        )
        self.todo._cache_poids = lambda chemin: "1G"
        self.todo._cache_octets = lambda chemin: 0

    def test_copying_waits_for_a_yes(self):
        self.todo._cache_ssh = lambda cible, commande, timeout=30: (
            0,
            "binaire\ncompte\nsudo\nFIN\n",
        )
        self.check(
            self.todo._cache_transfert,
            "Copy now?",
            lambda: self.ran("tar -C /var/cache/x"),
            typed=[f"op@{HOST}"],
        )

    def test_sending_without_sudo_there_waits_for_a_yes(self):
        self.check(
            lambda: self.todo._cache_sans_sudo_la_bas(
                f"op@{HOST}", "/var/cache/x", "compte_ssh=op\nFIN\n"
            ),
            "Send it now, and print the command to finish there?",
            lambda: bool(self.todo.execute.cmds),
        )


class TestLeRejeuSousUneCoupureIllisible(_Base):
    """Fill what offline runs lacked : une coupure que sudo empêche de
    lire n'est pas une absence ; le rejeu n'est permis que sur un oui."""

    def test_replaying_anyway_waits_for_a_yes(self):
        self.enterContext(mock.patch.object(menu, "CACHE_BIN", __file__))
        self.todo._cache_actif = lambda: True
        self.todo._cache_guet_actif = lambda: False
        self.todo._cache_amont_coupe = lambda: None
        permis = []
        self.check(
            lambda: permis.append(self.todo._cache_combler_permis()),
            "Replay anyway?",
            lambda: permis.pop(),
        )


class TestLAssistantDesTests(_Base):
    """Test - Choose and run : les essais créent de vraies VM ; aucun ne
    part sans un oui au lot."""

    def test_the_long_tests_run_only_on_a_yes(self):
        lances = []
        self.todo._longtest_run = lambda *a, **k: lances.append((a, k))
        self.todo._cache_systemes = lambda: [("debian", "🐧 Debian")]
        self.todo._cache_nom_des_machines = lambda *a: VM

        def run():
            lances.clear()
            return self.todo._cache_assistant()

        original = self.play

        def play(call, answers, typed=()):
            return original(call, ["1", "1", "1", *answers], typed)

        self.play = play
        self.check(run, "Run these long tests?", lambda: bool(lances))


class TestLEmulateurAndroid(_Base):
    """Android emulator : un émulateur déjà lancé sur l'AVD ne se ferme
    que sur un oui, et le tunnel adb ne s'ouvre que sur un oui."""

    def setUp(self):
        super().setUp()
        self.runs = []

        def run(cmd, *a, **k):
            self.runs.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        self.enterContext(
            mock.patch.object(qemu_access.subprocess, "run", side_effect=run)
        )
        self.todo._qemu_resolve_ips = lambda names, labels=None: {
            VM: "192.0.2.81"
        }
        self.todo._qemu_self_address = staticmethod(
            lambda: ("192.0.2.82", True)
        )

    def test_closing_the_running_emulator_waits_for_a_yes(self):
        self.todo._ssh_config_hosts = lambda: []
        self.todo._qemu_list_domains = lambda: [VM]
        self.todo._qemu_pick_target = lambda targets: (VM, "virsh")
        self.todo._qemu_emulator_running = lambda target, src: 1
        self.todo._qemu_emulator_ready = lambda target, src: (False, VM)

        def closed():
            return any("pkill" in " ".join(c) for c in self.runs)

        def call():
            self.runs.clear()
            self.todo._qemu_emulator_menu()

        self.check(call, "Close it now?", closed)

    def test_the_tunnel_opens_only_on_a_yes(self):
        self.enterContext(
            mock.patch.object(
                TODO, "_port_in_use", staticmethod(lambda p: False)
            )
        )

        def call():
            self.runs.clear()
            self.todo._qemu_scrcpy_tunnel(VM, "virsh")

        self.check(call, "Open the tunnel now?", lambda: bool(self.runs))


class TestLaCleSurUneIdentiteRefusee(_Base):
    """SSH configuration : une identité refusée propose la clé, oui par
    défaut ; non et Ctrl+D ne créent ni ne déploient rien."""

    def setUp(self):
        super().setUp()
        self.gestes = []
        self.todo._ssh_ensure_key = lambda: self.gestes.append("key") or True
        self.todo._ssh_deploy_keys = lambda aliases: self.gestes.append(
            aliases
        )
        self.todo._qemu_ssh_probe_remote = lambda alias: ("ok", [])

    def _retry(self):
        self.gestes.clear()
        return self.todo._qemu_ssh_retry_with_key(HOST, "refused")

    def test_an_existing_key_is_deployed_on_enter(self):
        self.todo._qemu_default_ssh_key = lambda: f"/{VM}/id.pub"
        self.check(
            self._retry,
            "Deploy it on this host (ssh-copy-id)?",
            lambda: [HOST] in self.gestes,
            default=True,
        )

    def test_a_missing_key_is_created_on_enter(self):
        self.todo._qemu_default_ssh_key = lambda: ""
        self.check(
            self._retry,
            "Create one and deploy it?",
            lambda: self.gestes == ["key", [HOST]],
            default=True,
        )

    def test_a_refusal_keeps_the_access_refused(self):
        self.todo._qemu_default_ssh_key = lambda: ""
        self.assertEqual(
            self.play(self._retry, [EOFError()]), ("auth", "refused")
        )


if __name__ == "__main__":
    unittest.main()
