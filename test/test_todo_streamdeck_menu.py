#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les actions du menu Stream Deck de TODO.

Chaque action se joue sur un TODO sans __init__, sous un HOME temporaire :
le lanceur est un double qui retient les commandes, les sondes muettes
rendent ce qu'on leur fixe, les réponses au clavier viennent d'une liste.
Aucune commande ne part.

Ce que ces tests gardent :

- les quatre questions de l'installation Stream Deck deviennent des
  options, le programme et la relance toujours explicites, leurs défauts
  pris dans les réglages en place, la commande s'affiche une fois, par
  l'annonce du lanceur, et 0 n'installe rien ;
- une réponse hors liste est signalée et la question reposée ;
- service, autostart et programme disent quoi installer sans unité, et
  appellent systemctl --user sinon ; le programme change le réglage et ne
  redémarre l'unité que si elle tournait ;
- la désinstallation demande confirmation, et son échec se dit comme
  tel ;
- chaque commande lancée s'affiche une seule fois : par l'annonce du
  lanceur, ou par la question de confirmation de la désinstallation, et
  jamais une seconde fois sous « Executed » ;
- Ctrl-C quitte le journal en direct sans quitter le menu ;
- l'extension se recharge par make, ses préférences par gnome-extensions ;
- l'état et le diagnostic affichent ce que rend erplibre_home_status ;
- chaque libellé a ses deux langues, les valeurs passées aux commandes
  restant celles de systemctl et des réglages.
"""

import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.execute import execute  # noqa: E402
from script.execute.execute import Execute  # noqa: E402
from script.todo import streamdeck_menu  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

UNITE = "erplibre-home-streamdeck.service"
INSTALLATEUR = "./script/install/install_erplibre_home.sh"


class ExecuteFactice:
    """Retient chaque commande ; rend (code, []) quand on lui demande code
    et lignes, comme exec_command_live, et `code` sinon."""

    def __init__(self, code=0):
        self.commandes = []
        self.options = []
        self.code = code

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        self.options.append(kwargs)
        if kwargs.get("return_status_and_output"):
            return self.code, []
        return self.code


class ProcessusVide:
    """Un processus déjà fini, sans sortie, qui rend `code`."""

    def __init__(self, code):
        lecture, ecriture = os.pipe()
        os.close(ecriture)
        self.stdout = os.fdopen(lecture, "rb")
        self.returncode = code

    def wait(self):
        return self.returncode


class ExecuteBannieres(Execute):
    """Le vrai exec_command_live, bannières comprises, sur un Popen
    remplacé : la commande est retenue, aucun processus ne part. Compter
    la commande dans la sortie compte donc ce que le lanceur affiche
    réellement, en plus de ce que le menu affiche lui-même."""

    def __init__(self, code=0):
        with mock.patch("shutil.which", return_value=None):
            super().__init__()
        self.commandes = []
        self.code = code

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        processus = []

        def popen(_commande, **_kw):
            processus.append(ProcessusVide(self.code))
            return processus[-1]

        try:
            with mock.patch.object(execute.subprocess, "Popen", popen):
                return super().exec_command_live(cmd, **kwargs)
        finally:
            for p in processus:
                p.stdout.close()


class ExecuteInterrompu(ExecuteFactice):
    """Retient la commande puis lève KeyboardInterrupt, comme un Ctrl-C
    pendant une commande en direct."""

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        raise KeyboardInterrupt


class Menu(unittest.TestCase):
    def setUp(self):
        todo_i18n._current_lang = "en"
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.home = Path(dossier.name)
        environ = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.reglages = self.home / ".config/erplibre-home/streamdeck.conf"
        self.sondes = []
        self.reponses_sondes = {}

    def unite(self):
        fichier = self.home / ".config/systemd/user" / UNITE
        fichier.parent.mkdir(parents=True)
        fichier.write_text("[Unit]\n")

    def jouer(self, methode, reponses, execute=None):
        """Lance `methode` avec `reponses` au clavier et `execute` pour
        lanceur, un ExecuteFactice par défaut. Rend (commandes lancées,
        sortie, valeur rendue)."""
        todo = TODO.__new__(TODO)
        todo.execute = execute or ExecuteFactice()

        def sonde(argv):
            self.sondes.append(tuple(argv))
            return self.reponses_sondes.get(tuple(argv), (1, ""))

        todo._streamdeck_probe = sonde
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch("builtins.input", side_effect=list(reponses)),
        ):
            rendu = getattr(todo, methode)()
        return todo.execute.commandes, sortie.getvalue(), rendu


class LInstallationStreamDeck(Menu):
    def test_each_answer_becomes_an_option(self):
        cas = (
            (("", "", "", ""), " --deck-program=tiler --restart-after-game"),
            (
                ("2", "y", "n", "y"),
                " --deck-program=controller --autostart"
                " --no-restart-after-game --with-extras",
            ),
            (
                ("3", "", "", ""),
                " --deck-program=none --restart-after-game",
            ),
            (
                ("1", "o", "", ""),
                " --deck-program=tiler --autostart --restart-after-game",
            ),
        )
        for reponses, options in cas:
            with self.subTest(reponses=reponses):
                commandes, sortie, rendu = self.jouer(
                    "_erplibre_home_streamdeck_install_local",
                    reponses,
                    ExecuteBannieres(),
                )
                commande = f"{INSTALLATEUR} --stream-deck{options}"
                self.assertEqual([commande], commandes)
                self.assertEqual(1, sortie.count(commande), sortie)
                self.assertIs(rendu, False)

    def test_enter_keeps_the_settings_in_place(self):
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text(
            "DECK_PROGRAM=controller\nRESTART_AFTER_GAME=no\n"
        )
        cas = (
            (
                ("", "", "", ""),
                " --deck-program=controller --no-restart-after-game",
            ),
            (
                ("1", "", "y", ""),
                " --deck-program=tiler --restart-after-game",
            ),
        )
        for reponses, options in cas:
            with self.subTest(reponses=reponses):
                commandes, sortie, _ = self.jouer(
                    "_erplibre_home_streamdeck_install_local", reponses
                )
                self.assertEqual(
                    [f"{INSTALLATEUR} --stream-deck{options}"], commandes
                )
                self.assertIn("[2] Controller *", sortie)

    def test_zero_installs_nothing(self):
        commandes, _sortie, rendu = self.jouer(
            "_erplibre_home_streamdeck_install_local", ("0",)
        )
        self.assertEqual([], commandes)
        self.assertIs(rendu, False)


class LeChoix(Menu):
    def test_an_answer_out_of_the_list_is_asked_again(self):
        self.unite()
        commandes, sortie, _ = self.jouer(
            "_streamdeck_service", ("9", "x", "1")
        )
        self.assertEqual([f"systemctl --user start {UNITE}"], commandes)
        self.assertEqual(2, sortie.count("Invalid selection!"))


class LeService(Menu):
    def test_without_the_unit_it_names_the_install(self):
        for methode in (
            "_streamdeck_service",
            "_streamdeck_program",
            "_streamdeck_autostart",
        ):
            with self.subTest(methode=methode):
                commandes, sortie, _ = self.jouer(methode, ())
                self.assertEqual([], commandes)
                self.assertIn("make erplibre_home_streamdeck_install", sortie)

    def test_each_action_calls_systemctl_user(self):
        self.unite()
        attendus = {
            "1": f"systemctl --user start {UNITE}",
            "2": f"systemctl --user stop {UNITE}",
            "3": f"systemctl --user restart {UNITE}",
            "4": f"journalctl --user -u {UNITE} -f",
        }
        for reponse, commande in attendus.items():
            with self.subTest(reponse=reponse):
                commandes, _, _ = self.jouer("_streamdeck_service", (reponse,))
                self.assertEqual([commande], commandes)

    def test_systemctl_gets_the_user_bus_fallback(self):
        """Sous su ou sudo -u, systemctl --user reçoit les variables du bus
        que rend user_bus_env, comme l'installateur les pose."""
        self.unite()
        repli = {"XDG_RUNTIME_DIR": "/exemple/run"}
        execute = ExecuteFactice()
        with mock.patch.object(
            streamdeck_menu.service, "user_bus_env", return_value=repli
        ):
            commandes, _, _ = self.jouer(
                "_streamdeck_service", ("3",), execute
            )
        self.assertEqual([f"systemctl --user restart {UNITE}"], commandes)
        self.assertEqual(repli, execute.options[0].get("new_env"))

    def test_ctrl_c_leaves_the_live_log_only(self):
        self.unite()
        execute = ExecuteInterrompu()
        commandes, _, rendu = self.jouer(
            "_streamdeck_service", ("4",), execute
        )
        self.assertEqual([f"journalctl --user -u {UNITE} -f"], commandes)
        self.assertIsNone(rendu)

    def test_autostart_enables_or_disables(self):
        self.unite()
        self.reponses_sondes[("systemctl", "--user", "is-enabled", UNITE)] = (
            1,
            "disabled\n",
        )
        for reponse, verbe in (("1", "enable"), ("2", "disable")):
            with self.subTest(verbe=verbe):
                commandes, sortie, _ = self.jouer(
                    "_streamdeck_autostart", (reponse,)
                )
                self.assertEqual(
                    [f"systemctl --user {verbe} {UNITE}"], commandes
                )
                self.assertIn("Autostart: disabled", sortie)


class LeProgramme(Menu):
    def test_it_rewrites_the_setting_and_restarts_an_active_unit(self):
        self.unite()
        self.reponses_sondes[("systemctl", "--user", "is-active", UNITE)] = (
            0,
            "active\n",
        )
        commandes, _, _ = self.jouer("_streamdeck_program", ("2",))
        self.assertEqual(
            "DECK_PROGRAM=controller\n", self.reglages.read_text()
        )
        self.assertEqual([f"systemctl --user restart {UNITE}"], commandes)

    def test_a_stopped_unit_stays_stopped(self):
        self.unite()
        commandes, _, _ = self.jouer("_streamdeck_program", ("3",))
        self.assertEqual("DECK_PROGRAM=none\n", self.reglages.read_text())
        self.assertEqual([], commandes)

    def test_the_same_program_changes_nothing(self):
        self.unite()
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text("DECK_PROGRAM=tiler\n")
        commandes, sortie, _ = self.jouer("_streamdeck_program", ("",))
        self.assertEqual([], commandes)
        self.assertIn("Unchanged.", sortie)
        self.assertNotIn(
            ("systemctl", "--user", "is-active", UNITE), self.sondes
        )

    def test_a_settings_file_outside_utf8_is_read_and_kept(self):
        """Un fichier de réglages qui n'est pas en UTF-8 montre son
        programme, comme le service le lit, et ses autres octets restent
        tels quels quand le programme change."""
        self.unite()
        self.reglages.parent.mkdir(parents=True)
        commentaire = "# réglé à la main\n".encode("latin-1")
        self.reglages.write_bytes(commentaire + b"DECK_PROGRAM=none\n")
        commandes, sortie, _ = self.jouer("_streamdeck_program", ("1",))
        self.assertIn("Deck program: No program", sortie)
        self.assertIn("Deck program: Tiler", sortie)
        self.assertNotIn("Unchanged.", sortie)
        self.assertEqual(
            commentaire + b"DECK_PROGRAM=tiler\n", self.reglages.read_bytes()
        )
        self.assertEqual([], commandes)

    def test_the_default_creates_no_settings_file(self):
        """Sans réglages, Entrée garde le défaut, que l'installateur et le
        service prennent déjà : aucun fichier ne se crée pour le redire."""
        self.unite()
        commandes, sortie, _ = self.jouer("_streamdeck_program", ("",))
        self.assertFalse(self.reglages.exists())
        self.assertFalse(self.reglages.parent.exists())
        self.assertEqual([], commandes)
        self.assertIn("Unchanged.", sortie)

    def test_an_invalid_value_is_shown_and_needs_an_explicit_choice(self):
        """Une valeur hors PROGRAMS se dit invalide ; aucune option ne
        porte l'étoile, et Entrée repose la question au lieu de remplacer
        la valeur en silence."""
        self.unite()
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text("DECK_PROGRAM=exemple\n")
        _, sortie, _ = self.jouer("_streamdeck_program", ("", "0"))
        self.assertIn("Deck program: exemple (invalid)", sortie)
        self.assertNotIn("*", sortie)
        self.assertIn("Invalid selection!", sortie)
        self.assertEqual("DECK_PROGRAM=exemple\n", self.reglages.read_text())
        self.jouer("_streamdeck_program", ("", "2"))
        self.assertEqual(
            "DECK_PROGRAM=controller\n", self.reglages.read_text()
        )

    def test_an_invalid_value_needs_an_explicit_choice_to_install(self):
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text("DECK_PROGRAM=exemple\n")
        commandes, sortie, _ = self.jouer(
            "_erplibre_home_streamdeck_install_local", ("", "3", "", "", "")
        )
        self.assertIn("Deck program: exemple (invalid)", sortie)
        self.assertNotIn("*", sortie)
        self.assertEqual(1, sortie.count("Invalid selection!"))
        self.assertEqual(
            [
                f"{INSTALLATEUR} --stream-deck --deck-program=none"
                " --restart-after-game"
            ],
            commandes,
        )


class LaDesinstallation(Menu):
    def test_each_choice_runs_its_options_after_confirmation(self):
        for reponse, options in (
            ("1", "--uninstall --stream-deck"),
            ("2", "--uninstall"),
        ):
            with self.subTest(options=options):
                commandes, sortie, _ = self.jouer(
                    "_streamdeck_uninstall", (reponse, "y")
                )
                self.assertEqual([f"{INSTALLATEUR} {options}"], commandes)
                self.assertIn("ERPLibre Home uninstalled.", sortie)

    def test_a_failed_uninstall_says_uninstall(self):
        _, sortie, _ = self.jouer(
            "_streamdeck_uninstall", ("2", "y"), ExecuteFactice(code=1)
        )
        self.assertIn(
            "❌ ERPLibre Home uninstall failed, see the output above.", sortie
        )
        self.assertNotIn("installation failed", sortie)

    def test_the_command_shows_once_in_the_question(self):
        """La question de confirmation porte la commande ; le lanceur ne
        la répète ni avant ni après."""
        for reponse, options in (
            ("1", "--uninstall --stream-deck"),
            ("2", "--uninstall"),
        ):
            with self.subTest(options=options):
                commande = f"{INSTALLATEUR} {options}"
                commandes, sortie, _ = self.jouer(
                    "_streamdeck_uninstall",
                    (reponse, "y"),
                    ExecuteBannieres(),
                )
                self.assertEqual([commande], commandes)
                self.assertEqual(1, sortie.count(commande), sortie)
                self.assertIn(f"Will execute: {commande}\n", sortie)

    def test_no_confirmation_no_uninstall(self):
        commandes, _, _ = self.jouer("_streamdeck_uninstall", ("2", ""))
        self.assertEqual([], commandes)


class LExtension(Menu):
    def test_reload_and_preferences(self):
        for reponse, commande in (
            ("1", "make erplibre_home_reload"),
            ("2", "gnome-extensions prefs erplibre-home@technolibre.ca"),
        ):
            with self.subTest(commande=commande):
                commandes, _, _ = self.jouer(
                    "_streamdeck_extension", (reponse,)
                )
                self.assertEqual([commande], commandes)


class LAffichageUnique(Menu):
    """Chaque commande lancée par le menu s'affiche une fois, par
    l'annonce du lanceur, et non une seconde fois sous « Executed »."""

    def test_each_command_shows_once(self):
        self.unite()
        self.reponses_sondes[("systemctl", "--user", "is-active", UNITE)] = (
            0,
            "active\n",
        )
        systemctl = "systemctl --user"
        cas = (
            ("_streamdeck_service", ("1",), f"{systemctl} start {UNITE}"),
            (
                "_streamdeck_service",
                ("4",),
                f"journalctl --user -u {UNITE} -f",
            ),
            ("_streamdeck_autostart", ("1",), f"{systemctl} enable {UNITE}"),
            ("_streamdeck_program", ("2",), f"{systemctl} restart {UNITE}"),
            ("_streamdeck_extension", ("1",), "make erplibre_home_reload"),
            ("_erplibre_home_install_local", (), INSTALLATEUR),
        )
        for methode, reponses, commande in cas:
            with self.subTest(methode=methode, commande=commande):
                commandes, sortie, _ = self.jouer(
                    methode, reponses, ExecuteBannieres()
                )
                self.assertEqual([commande], commandes)
                self.assertEqual(1, sortie.count(commande + "\n"), sortie)
                self.assertNotIn("Executed", sortie)


class LeJeuLanceUneFois(Menu):
    """Le jeu choisi s'affiche une fois, comme les autres commandes."""

    def test_the_game_command_shows_once(self):
        jeu = {"name": "g", "path": "script/stream_deck/game_g.py"}
        todo_mod = sys.modules[TODO.__module__]
        with (
            mock.patch.object(todo_mod.os, "access", return_value=True),
            mock.patch.object(
                TODO, "_scan_streamdeck_games", return_value=[
                    dict(jeu, description="g")
                ]
            ),
            mock.patch.object(
                todo_mod.click, "prompt", side_effect=["1", "0"]
            ),
        ):
            commandes, sortie, _ = self.jouer(
                "prompt_execute_streamdeck_games", (), ExecuteBannieres()
            )
        (commande,) = commandes
        self.assertEqual(1, sortie.count(commande + "\n"), sortie)
        self.assertNotIn("Executed", sortie)


class LEtatEtLeDiagnostic(Menu):
    FAITS = {"exemple": True}

    def test_status_prints_the_status_lines(self):
        with (
            mock.patch.object(
                streamdeck_menu.statut, "collect", return_value=self.FAITS
            ) as collect,
            mock.patch.object(
                streamdeck_menu.statut,
                "status_lines",
                return_value=["Level: base", "Deck lock: free"],
            ),
        ):
            _, sortie, _ = self.jouer("_streamdeck_status", ())
        self.assertEqual("  Level: base\n  Deck lock: free\n", sortie)
        self.assertEqual(streamdeck_menu.RACINE, collect.call_args[0][1])

    def test_diagnosis_prints_each_fix_or_nothing_to_fix(self):
        with (
            mock.patch.object(
                streamdeck_menu.statut, "collect", return_value=self.FAITS
            ),
            mock.patch.object(
                streamdeck_menu.statut,
                "diagnosis_lines",
                return_value=[("No Stream Deck plugged in", "plug it in")],
            ),
        ):
            _, sortie, _ = self.jouer("_streamdeck_diagnosis", ())
        self.assertEqual(
            "❌ No Stream Deck plugged in\n   → plug it in\n", sortie
        )
        with (
            mock.patch.object(
                streamdeck_menu.statut, "collect", return_value=self.FAITS
            ),
            mock.patch.object(
                streamdeck_menu.statut, "diagnosis_lines", return_value=[]
            ),
        ):
            _, sortie, _ = self.jouer("_streamdeck_diagnosis", ())
        self.assertEqual("✅ Nothing to fix.\n", sortie)


class LesLibelles(Menu):
    def test_choices_show_translated_labels_and_pass_raw_values(self):
        todo_i18n._current_lang = "fr"
        self.unite()
        commandes, sortie, _ = self.jouer("_streamdeck_service", ("2",))
        self.assertEqual([f"systemctl --user stop {UNITE}"], commandes)
        self.assertIn("[1] 🟢 Démarrer", sortie)
        _, sortie, _ = self.jouer("_streamdeck_program", ("2",))
        self.assertIn("Programme du deck : Tiler", sortie)
        self.assertIn("[2] Contrôleur", sortie)
        self.assertIn("[3] Aucun programme", sortie)
        self.assertEqual(
            "DECK_PROGRAM=controller\n", self.reglages.read_text()
        )
        commandes, sortie, _ = self.jouer("_streamdeck_autostart", ("1",))
        self.assertEqual([f"systemctl --user enable {UNITE}"], commandes)
        self.assertIn("[2] Désactiver", sortie)


class LesTraductions(unittest.TestCase):
    def test_every_label_has_fr_and_en(self):
        source = Path(streamdeck_menu.__file__).read_text(encoding="utf-8")
        cles = set(re.findall(r'(?<![\w.])t\(\s*"([^"]+)"\s*\)', source))
        cles |= {
            "".join(morceaux)
            for morceaux in re.findall(
                r'(?<![\w.])t\(\s*\n\s*"([^"]+)"\s*\n\s*"([^"]+)"', source
            )
        }
        self.assertGreater(len(cles), 20)
        for cle in sorted(cles):
            with self.subTest(cle=cle):
                entree = todo_i18n.TRANSLATIONS.get(cle)
                self.assertIsNotNone(entree, cle)
                self.assertTrue(entree.get("fr") and entree.get("en"))


class LeReglageDesJeux(Menu):
    def test_it_writes_off_without_the_unit_and_restarts_nothing(self):
        commandes, _, _ = self.jouer("_streamdeck_games_setting", ("2",))
        self.assertEqual("GAMES=off\n", self.reglages.read_text())
        self.assertEqual([], commandes)
        self.assertEqual([], self.sondes)

    def test_keeping_the_current_value_writes_nothing(self):
        _, sortie, _ = self.jouer("_streamdeck_games_setting", ("",))
        self.assertFalse(self.reglages.exists())
        self.assertIn("Unchanged.", sortie)

    def test_an_invalid_value_needs_an_explicit_choice(self):
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text("GAMES=peut-etre\n")
        _, sortie, _ = self.jouer("_streamdeck_games_setting", ("", "1"))
        self.assertIn("invalid", sortie)
        self.assertEqual("GAMES=on\n", self.reglages.read_text())

    def test_the_submenu_offers_the_entry(self):
        todo = TODO.__new__(TODO)
        with (
            mock.patch.object(TODO, "_streamdeck_games_setting") as entree,
            mock.patch.object(
                streamdeck_menu.click, "prompt", side_effect=["11", "0"]
            ),
            mock.patch.object(TODO, "fill_help_info", return_value=""),
        ):
            todo.prompt_execute_streamdeck()
        entree.assert_called_once_with()


class LeReglageDesPlugins(Menu):
    def setUp(self):
        super().setUp()
        racine = self.home / "depot"
        plugins = racine / "script/stream_deck/erplibre_streamdeck/plugins"
        plugins.mkdir(parents=True)
        for nom in ("sound", "tiling"):
            (plugins / f"{nom}.py").write_text("")
        patch = mock.patch.object(streamdeck_menu, "RACINE", str(racine))
        patch.start()
        self.addCleanup(patch.stop)

    def test_it_lists_the_ids_with_their_state(self):
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text("DECK_PLUGINS_OFF=tiling\n")
        _, sortie, _ = self.jouer("_streamdeck_plugins_setting", ("0",))
        self.assertIn("[1] sound: on", sortie)
        self.assertIn("[2] tiling: off", sortie)

    def test_choosing_an_id_turns_it_off_and_writes_the_setting(self):
        commandes, sortie, _ = self.jouer(
            "_streamdeck_plugins_setting", ("2",)
        )
        self.assertEqual(
            "DECK_PLUGINS_OFF=tiling\n", self.reglages.read_text()
        )
        self.assertIn("tiling: off", sortie)
        self.assertEqual([], commandes)

    def test_choosing_an_off_id_turns_it_on_and_keeps_the_others(self):
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text(
            "GAMES=off\nDECK_PLUGINS_OFF=tiling,ghost,sound\n"
        )
        self.jouer("_streamdeck_plugins_setting", ("2",))
        self.assertEqual(
            "GAMES=off\nDECK_PLUGINS_OFF=ghost,sound\n",
            self.reglages.read_text(),
        )

    def test_back_writes_nothing(self):
        self.jouer("_streamdeck_plugins_setting", ("0",))
        self.assertFalse(self.reglages.exists())

    def test_an_active_unit_is_restarted(self):
        self.reponses_sondes[
            ("systemctl", "--user", "is-active", UNITE)
        ] = (0, "active\n")
        commandes, _, _ = self.jouer("_streamdeck_plugins_setting", ("1",))
        self.assertEqual([f"systemctl --user restart {UNITE}"], commandes)

    def test_a_stopped_unit_stays_stopped(self):
        commandes, _, _ = self.jouer("_streamdeck_plugins_setting", ("1",))
        self.assertEqual([], commandes)

    def test_without_plugins_it_says_so(self):
        with mock.patch.object(
            streamdeck_menu.service, "deck_plugin_ids", return_value=[]
        ):
            _, sortie, _ = self.jouer("_streamdeck_plugins_setting", ())
        self.assertIn("No deck plugins found.", sortie)

    def test_the_submenu_offers_the_entry(self):
        todo = TODO.__new__(TODO)
        with (
            mock.patch.object(TODO, "_streamdeck_plugins_setting") as entree,
            mock.patch.object(
                streamdeck_menu.click, "prompt", side_effect=["12", "0"]
            ),
            mock.patch.object(TODO, "fill_help_info", return_value=""),
        ):
            todo.prompt_execute_streamdeck()
        entree.assert_called_once_with()


class LeReglageDeLaPeriode(Menu):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def test_it_shows_the_value_and_accepts_a_valid_period(self):
        for langue in ("fr", "en"):
            with self.subTest(langue=langue):
                todo_i18n._current_lang = langue
                if self.reglages.exists():
                    self.reglages.unlink()
                commandes, sortie, _ = self.jouer(
                    "_streamdeck_session_refresh_setting", (" 2 ",)
                )
                self.assertIn(
                    "Rafraîchissement des sessions : 1 s"
                    if langue == "fr"
                    else "Session refresh: 1 s",
                    sortie,
                )
                self.assertEqual(
                    "DECK_SESSION_REFRESH_SEC=2\n",
                    self.reglages.read_text(),
                )
                self.assertEqual([], commandes)

    def test_a_decimal_comma_is_read_and_written_with_a_dot(self):
        todo_i18n._current_lang = "fr"
        self.jouer("_streamdeck_session_refresh_setting", ("0,5",))
        self.assertEqual(
            "DECK_SESSION_REFRESH_SEC=0.5\n", self.reglages.read_text()
        )

    def test_entry_refuses_out_of_range(self):
        for langue, bornes in (
            ("fr", "de 0.5 à 60 secondes"),
            ("en", "0.5 to 60 seconds"),
        ):
            for reponse in ("0.1", "abc", "61", "1e1"):
                with self.subTest(langue=langue, reponse=reponse):
                    todo_i18n._current_lang = langue
                    self.reglages.parent.mkdir(parents=True, exist_ok=True)
                    self.reglages.write_text(
                        "GAMES=off\nDECK_SESSION_REFRESH_SEC=3\n"
                    )
                    commandes, sortie, _ = self.jouer(
                        "_streamdeck_session_refresh_setting", (reponse,)
                    )
                    self.assertEqual(
                        "GAMES=off\nDECK_SESSION_REFRESH_SEC=3\n",
                        self.reglages.read_text(),
                    )
                    self.assertIn(bornes, sortie)
                    self.assertEqual([], commandes)
                    self.assertEqual([], self.sondes)

    def test_an_empty_answer_keeps_the_value(self):
        todo_i18n._current_lang = "en"
        _, sortie, _ = self.jouer(
            "_streamdeck_session_refresh_setting", ("",)
        )
        self.assertFalse(self.reglages.exists())
        self.assertIn("Unchanged.", sortie)

    def test_an_invalid_value_in_the_file_shows_as_invalid(self):
        todo_i18n._current_lang = "en"
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text("DECK_SESSION_REFRESH_SEC=abc\n")
        _, sortie, _ = self.jouer(
            "_streamdeck_session_refresh_setting", ("",)
        )
        self.assertIn("'abc' (invalid) s", sortie)

    def test_an_active_unit_is_restarted(self):
        self.reponses_sondes[
            ("systemctl", "--user", "is-active", UNITE)
        ] = (0, "active\n")
        commandes, _, _ = self.jouer(
            "_streamdeck_session_refresh_setting", ("0.5",)
        )
        self.assertEqual([f"systemctl --user restart {UNITE}"], commandes)

    def test_a_stopped_unit_stays_stopped(self):
        commandes, _, _ = self.jouer(
            "_streamdeck_session_refresh_setting", ("0.5",)
        )
        self.assertEqual([], commandes)
        self.assertEqual(
            "DECK_SESSION_REFRESH_SEC=0.5\n", self.reglages.read_text()
        )

    def test_the_submenu_offers_the_entry(self):
        todo = TODO.__new__(TODO)
        with (
            mock.patch.object(
                TODO, "_streamdeck_session_refresh_setting"
            ) as entree,
            mock.patch.object(
                streamdeck_menu.click, "prompt", side_effect=["13", "0"]
            ),
            mock.patch.object(TODO, "fill_help_info", return_value=""),
        ):
            todo.prompt_execute_streamdeck()
        entree.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
