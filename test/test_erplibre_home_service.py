#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les réglages du service Stream Deck, vus de TODO.

TODO lit et réécrit le même fichier que l'installateur, le point d'entrée
du service et l'outil de passation : ces tests gardent les mêmes règles des
deux côtés, et comparent l'écriture de Python à celle de l'installateur sur
les mêmes entrées.
"""

import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import erplibre_home_service as service  # noqa: E402

INSTALLEUR = RACINE / "script/install/install_erplibre_home.sh"
BIBLIOTHEQUE = RACINE / "script/install/erplibre_home_settings.sh"


class LesChemins(unittest.TestCase):
    def test_under_dot_config_by_default(self):
        env = {"HOME": "/exemple/maison"}
        self.assertEqual(
            "/exemple/maison/.config/erplibre-home/streamdeck.conf",
            service.settings_path(env),
        )
        self.assertEqual(
            "/exemple/maison/.config/systemd/user/"
            "erplibre-home-streamdeck.service",
            service.unit_path(env),
        )

    def test_xdg_config_home_wins_and_empty_means_unset(self):
        env = {"HOME": "/exemple/maison", "XDG_CONFIG_HOME": "/exemple/cfg"}
        self.assertEqual(
            "/exemple/cfg/erplibre-home/streamdeck.conf",
            service.settings_path(env),
        )
        env["XDG_CONFIG_HOME"] = ""
        self.assertTrue(
            service.settings_path(env).startswith("/exemple/maison/.config/")
        )


class LaLecture(unittest.TestCase):
    def test_a_missing_file_gives_the_defaults(self):
        self.assertEqual(
            {
                "DECK_PROGRAM": "tiler",
                "RESTART_AFTER_GAME": "yes",
                "GAMES": "on",
            },
            service.read_settings("/exemple/absent.conf"),
        )

    def test_the_last_line_wins_and_comments_are_skipped(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier, "streamdeck.conf")
            chemin.write_text(
                "# DECK_PROGRAM=none\nDECK_PROGRAM=tiler\n"
                "sans egal\nDECK_PROGRAM=controller\n",
                encoding="utf-8",
            )
            reglages = service.read_settings(str(chemin))
        self.assertEqual("controller", reglages["DECK_PROGRAM"])
        self.assertEqual("yes", reglages["RESTART_AFTER_GAME"])

    def test_python_and_the_shell_library_read_the_same_value(self):
        """read_settings et deck_setting de la bibliothèque shell rendent
        la même valeur, y compris sur un « \\r », sans retour final, et
        sur un fichier qui n'est pas en UTF-8 : le shell lit des octets,
        un octet hors UTF-8 s'y compare remplacé par U+FFFD."""
        contenus = (
            "DECK_PROGRAM=none\n",
            "DECK_PROGRAM=a\nDECK_PROGRAM=controller",
            "# DECK_PROGRAM=none\nDECK_PROGRAM=\n",
            "DECK_PROGRAM=none\rRESTART_AFTER_GAME=no\n",
            "sans egal\nRESTART_AFTER_GAME=no\n",
            "# réglé à la main\nDECK_PROGRAM=none\n".encode("latin-1"),
            "DECK_PROGRAM=été\nRESTART_AFTER_GAME=no\n".encode("latin-1"),
        )
        for contenu in contenus:
            with self.subTest(contenu=contenu):
                with tempfile.TemporaryDirectory() as dossier:
                    chemin = Path(
                        dossier, ".config/erplibre-home/streamdeck.conf"
                    )
                    chemin.parent.mkdir(parents=True)
                    if isinstance(contenu, str):
                        contenu = contenu.encode("utf-8")
                    chemin.write_bytes(contenu)
                    env = {
                        k: v
                        for k, v in os.environ.items()
                        if k != "XDG_CONFIG_HOME"
                    }
                    env.update({"HOME": dossier, "BIB": str(BIBLIOTHEQUE)})
                    lu = {}
                    for cle, defaut in service.DEFAULTS.items():
                        fini = subprocess.run(
                            [
                                "bash",
                                "-c",
                                '. "$BIB"; deck_setting %s %s' % (cle, defaut),
                            ],
                            capture_output=True,
                            env=env,
                            timeout=30,
                        )
                        self.assertEqual(0, fini.returncode, fini.stderr)
                        lu[cle] = fini.stdout.decode(errors="replace").rstrip(
                            "\n"
                        )
                    self.assertEqual(
                        lu,
                        service.read_settings(str(chemin)),
                    )


class LesJeux(unittest.TestCase):
    """GAMES : on ou absent active les jeux, off les coupe, toute autre
    valeur les coupe aussi ; le shell et Python disent la même chose."""

    def shell(self, contenu, env=None):
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier)
            environ = {
                k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
            }
            environ.update({"HOME": dossier, "BIB": str(BIBLIOTHEQUE)})
            environ.update(env or {})
            conf = (
                Path(environ.get("XDG_CONFIG_HOME") or base / ".config")
                / "erplibre-home/streamdeck.conf"
            )
            if contenu is not None:
                conf.parent.mkdir(parents=True, exist_ok=True)
                conf.write_bytes(contenu.encode("utf-8"))
            fini = subprocess.run(
                [
                    "bash",
                    "-c",
                    '. "$BIB"; deck_games_enabled; echo "rc=$?";'
                    " deck_games_message",
                ],
                capture_output=True,
                text=True,
                env=environ,
                timeout=30,
            )
            lu = service.read_settings(str(conf))
        return fini.stdout, lu

    def test_on_off_missing_and_unknown(self):
        cas = (
            (None, "rc=0", True),
            ("GAMES=on\n", "rc=0", True),
            ("GAMES=off\n", "rc=1", False),
            ("GAMES=\n", "rc=2", False),
            ("GAMES=yes\n", "rc=2", False),
            ("GAMES=on\r\n", "rc=2", False),
        )
        for contenu, code, actif in cas:
            with self.subTest(contenu=contenu):
                sortie, lu = self.shell(contenu)
                self.assertIn(code, sortie)
                self.assertEqual(actif, service.games_enabled(lu))

    def test_the_message_names_the_setting_and_the_way_back(self):
        sortie, _ = self.shell("GAMES=off\n")
        self.assertIn("GAMES=off", sortie)
        self.assertIn("streamdeck.conf", sortie)
        self.assertIn("TODO › Stream Deck › Games on/off", sortie)

    def test_the_message_shows_a_carriage_return_instead_of_obeying_it(self):
        sortie, _ = self.shell("GAMES=on\r\n")
        message = sortie.split("rc=2", 1)[1]
        self.assertIn("GAMES=on\\r", message)
        self.assertNotIn("\r", message)

    def test_xdg_config_home_wins(self):
        with tempfile.TemporaryDirectory() as autre:
            sortie, _ = self.shell("GAMES=off\n", {"XDG_CONFIG_HOME": autre})
        self.assertIn("rc=1", sortie)
        self.assertIn(autre, sortie)


class LEcriture(unittest.TestCase):
    def test_a_key_is_replaced_in_place_and_others_stay(self):
        self.assertEqual(
            "# note\nDECK_PROGRAM=none\nEXEMPLE=1\nRESTART_AFTER_GAME=no\n",
            service.settings_text(
                "# note\nDECK_PROGRAM=tiler\nEXEMPLE=1\n",
                {"DECK_PROGRAM": "none", "RESTART_AFTER_GAME": "no"},
            ),
        )

    def test_write_creates_then_leaves_an_unchanged_file_alone(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier, "erplibre-home", "streamdeck.conf")
            self.assertTrue(
                service.write_settings(str(chemin), {"DECK_PROGRAM": "none"})
            )
            self.assertEqual("DECK_PROGRAM=none\n", chemin.read_text())
            avant = chemin.stat().st_mtime_ns
            self.assertFalse(
                service.write_settings(str(chemin), {"DECK_PROGRAM": "none"})
            )
            self.assertEqual(avant, chemin.stat().st_mtime_ns)

    def test_python_and_the_installer_write_the_same_text(self):
        """settings_text, write_settings et settings_content de
        l'installateur, sur les mêmes entrées, rendent le même texte. Le
        shell ne coupe les lignes que sur « \\n » : un « \\r », un
        « \\x0b », un « \\x1c » ou un « \\u2028 » reste dans sa ligne,
        des deux côtés."""
        entrees = (
            "",
            "DECK_PROGRAM=none\n",
            "# note\nEXEMPLE=1\nRESTART_AFTER_GAME=yes\nDECK_PROGRAM=tiler",
            "DECK_PROGRAM=none\r\nEXEMPLE=1\r\n",
            "DECK_PROGRAM=none\rRESTART_AFTER_GAME=yes\n",
            "EXEMPLE=a\x0bDECK_PROGRAM=none\n",
            "EXEMPLE=a\x1cRESTART_AFTER_GAME=yes\x1d\x1e\x85\n",
            "EXEMPLE=a\u2028DECK_PROGRAM=none\u2029\n",
            "\n\nEXEMPLE=1\n\n",
        )
        maj = {"DECK_PROGRAM": "controller", "RESTART_AFTER_GAME": "no"}
        for entree in entrees:
            with self.subTest(entree=entree):
                with tempfile.TemporaryDirectory() as dossier:
                    chemin = Path(dossier, "streamdeck.conf")
                    copie = Path(dossier, "copie.conf")
                    if entree:
                        chemin.write_bytes(entree.encode("utf-8"))
                        copie.write_bytes(entree.encode("utf-8"))
                    service.write_settings(str(copie), maj)
                    ecrit = copie.read_bytes().decode("utf-8")
                    env = {
                        k: v
                        for k, v in os.environ.items()
                        if k != "XDG_CONFIG_HOME"
                    }
                    env.update(
                        {
                            "HOME": dossier,
                            "INSTALLEUR": str(INSTALLEUR),
                            "FICHIER": str(chemin),
                        }
                    )
                    fini = subprocess.run(
                        [
                            "bash",
                            "-c",
                            'ERPLIBRE_HOME_SOURCE_ONLY=1 . "$INSTALLEUR"\n'
                            'settings_content "$FICHIER"'
                            " DECK_PROGRAM=controller RESTART_AFTER_GAME=no\n",
                        ],
                        capture_output=True,
                        env=env,
                        timeout=30,
                    )
                self.assertEqual(0, fini.returncode, fini.stderr)
                attendu = fini.stdout.decode("utf-8")
                self.assertEqual(attendu, service.settings_text(entree, maj))
                self.assertEqual(attendu, ecrit)

    def test_bytes_outside_utf8_survive_an_update(self):
        """Un fichier qui n'est pas en UTF-8 se met à jour sans erreur :
        ses octets restent tels quels hors des lignes des clés posées,
        comme le fait settings_content de l'installateur sur le même
        fichier. Une mise à jour qui ne change rien ne le réécrit pas."""
        commentaire = "# réglé à la main, ½\n".encode("latin-1")
        avant = commentaire + b"DECK_PROGRAM=tiler\nEXEMPLE=\xe9\n"
        maj = {"DECK_PROGRAM": "none", "RESTART_AFTER_GAME": "no"}
        attendu = (
            commentaire
            + b"DECK_PROGRAM=none\nEXEMPLE=\xe9\nRESTART_AFTER_GAME=no\n"
        )
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier, "streamdeck.conf")
            installe = Path(dossier, "installe.conf")
            chemin.write_bytes(avant)
            installe.write_bytes(avant)
            self.assertTrue(service.write_settings(str(chemin), maj))
            self.assertEqual(attendu, chemin.read_bytes())
            lu = service.read_settings(str(chemin))
            self.assertEqual("none", lu["DECK_PROGRAM"])
            self.assertEqual("no", lu["RESTART_AFTER_GAME"])
            mtime = chemin.stat().st_mtime_ns
            self.assertFalse(service.write_settings(str(chemin), maj))
            self.assertEqual(mtime, chemin.stat().st_mtime_ns)
            env = {
                k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
            }
            env.update(
                {
                    "HOME": dossier,
                    "INSTALLEUR": str(INSTALLEUR),
                    "FICHIER": str(installe),
                }
            )
            fini = subprocess.run(
                [
                    "bash",
                    "-c",
                    'ERPLIBRE_HOME_SOURCE_ONLY=1 . "$INSTALLEUR"\n'
                    'settings_content "$FICHIER"'
                    " DECK_PROGRAM=none RESTART_AFTER_GAME=no\n",
                ],
                capture_output=True,
                env=env,
                timeout=30,
            )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(attendu, fini.stdout)


class LaCommande(unittest.TestCase):
    def test_code_and_stdout(self):
        self.assertEqual(
            (3, "sortie\n"),
            service.run_command(["sh", "-c", "echo sortie; exit 3"]),
        )

    def test_a_missing_command_gives_none(self):
        self.assertEqual(
            (None, ""), service.run_command(["/exemple/commande-absente"])
        )

    def test_a_timeout_gives_none(self):
        self.assertEqual(
            (None, ""), service.run_command(["sleep", "5"], timeout=0.2)
        )

    def test_the_command_gets_the_user_bus_fallback(self):
        with (
            mock.patch.dict(os.environ, {}),
            mock.patch.object(
                service,
                "user_bus_env",
                return_value={"XDG_RUNTIME_DIR": "/exemple/run"},
            ),
        ):
            os.environ.pop("XDG_RUNTIME_DIR", None)
            self.assertEqual(
                (0, "/exemple/run\n"),
                service.run_command(["sh", "-c", 'echo "$XDG_RUNTIME_DIR"']),
            )


class LeBusUtilisateur(unittest.TestCase):
    """Sous su ou sudo -u, XDG_RUNTIME_DIR et DBUS_SESSION_BUS_ADDRESS
    manquent : user_bus_env les prend sous /run/user/<uid>, comme
    l'installateur, et seulement quand ils manquent et que le répertoire
    ou le socket existe. `runtime_root` remplace /run/user."""

    UID = 4242

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.racine = dossier.name
        self.runtime = os.path.join(self.racine, str(self.UID))

    def bus(self):
        os.makedirs(self.runtime, exist_ok=True)
        prise = socket.socket(socket.AF_UNIX)
        self.addCleanup(prise.close)
        prise.bind(os.path.join(self.runtime, "bus"))

    def env(self, environ):
        return service.user_bus_env(
            environ, runtime_root=self.racine, uid=self.UID
        )

    def test_both_missing_are_taken_from_the_runtime_dir(self):
        self.bus()
        self.assertEqual(
            {
                "XDG_RUNTIME_DIR": self.runtime,
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=%s/bus" % self.runtime,
            },
            self.env({"HOME": "/exemple/maison"}),
        )

    def test_variables_already_set_are_kept(self):
        self.bus()
        self.assertEqual(
            {},
            self.env(
                {
                    "XDG_RUNTIME_DIR": "/exemple/run",
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/exemple/bus",
                }
            ),
        )

    def test_without_the_socket_only_the_runtime_dir(self):
        os.makedirs(self.runtime)
        self.assertEqual({"XDG_RUNTIME_DIR": self.runtime}, self.env({}))

    def test_a_plain_file_named_bus_is_not_a_bus(self):
        os.makedirs(self.runtime)
        Path(self.runtime, "bus").write_text("")
        self.assertEqual({"XDG_RUNTIME_DIR": self.runtime}, self.env({}))

    def test_nothing_under_run_user_gives_nothing(self):
        self.assertEqual({}, self.env({"XDG_RUNTIME_DIR": ""}))


if __name__ == "__main__":
    unittest.main()
