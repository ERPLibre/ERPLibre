#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les réglages du Stream Deck que pilote un Odoo, vus d'ERPLibre.

L'extension GNOME applique à streamdeck.conf la configuration que l'Odoo
pilote lui envoie, et TODO écrit le même fichier par son menu Stream Deck.
Ce que ces tests gardent :

- le tableau des réglages pilotés du CONTRACT.md de l'extension égale les
  constantes d'erplibre_home_service : clé du fil et ligne du fichier,
  programmes, valeurs de GAMES, bornes de la période, motif d'identifiant
  de plugin ;
- sur les fixtures partagées du clone, settings_text et write_settings
  rendent, octet pour octet, ce que l'extension écrit : les deux écrivains
  du même fichier n'en perdent pas des lignes différentes ;
- deck_plugin_ids ne rend que des identifiants que le fil accepte ;
- pilot.json, écrit par l'extension, se lit sans jamais faire échouer
  TODO : absent, illisible ou hors forme, il ne compte pas ;
- avant d'écrire une clé que l'Odoo pilote verrouille, chaque entrée du
  menu le dit en une ligne qui nomme la destination, puis écrit quand
  même ; une clé libre, ou une valeur inchangée, ne dit rien.

Ce qui lit le clone est sauté quand il manque (SANS_EXTENSION), ou quand
son contrat précède la version qui pose le tableau : une MINEURE en
retard reste compatible, repo sync l'amène.
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = ["todo.py"]

from erplibre_home_extension import (  # noqa: E402
    SANS_EXTENSION,
    fixtures_de_reglages,
    reglages_du_contrat,
    version_du_contrat,
)

from script.todo import erplibre_home_service as service  # noqa: E402
from script.todo import streamdeck_menu  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

# La version du contrat qui pose le tableau des réglages pilotés.
CONTRAT_DU_PILOTE = (1, 3)
UNITE = "erplibre-home-streamdeck.service"
DESTINATION = "Odoo de test"
AVERTISSEMENT = (
    "Setting locked by Odoo (%s): it will be offered again." % DESTINATION
)


def ligne_du_fil(valeur):
    """La valeur d'une ligne de streamdeck.conf pour une valeur du fil :
    une liste jointe par des virgules, un nombre entier sans « .0 », comme
    String() de JavaScript, un texte tel quel."""
    if isinstance(valeur, list):
        return ",".join(valeur)
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return str(valeur)


def en_ticks(cellule):
    """Les morceaux entre accents graves d'une cellule du contrat."""
    return re.findall(r"`([^`]+)`", cellule)


@SANS_EXTENSION
class LeContratDuPilote(unittest.TestCase):
    def setUp(self):
        version = version_du_contrat()
        if version < CONTRAT_DU_PILOTE:
            self.skipTest(
                "contrat du clone %d.%d, tableau des réglages en %d.%d :"
                " repo sync" % (version + CONTRAT_DU_PILOTE)
            )

    def test_the_contract_table_matches_the_service_constants(self):
        tableau = reglages_du_contrat()
        self.assertEqual(
            service.CONFIG_LINES,
            {cle: ligne for cle, (ligne, _valeurs) in tableau.items()},
        )
        self.assertEqual(
            service.PROGRAMS, tuple(en_ticks(tableau["deck_program"][1]))
        )
        self.assertEqual(
            service.GAMES_VALUES, tuple(en_ticks(tableau["games"][1]))
        )
        bornes = re.findall(
            r"\d+(?:\.\d+)?", tableau["session_refresh_sec"][1]
        )
        self.assertEqual(
            service.SESSION_REFRESH_RANGE,
            tuple(float(borne) for borne in bornes),
        )
        self.assertEqual(
            [service.PLUGIN_ID_PATTERN],
            [m for m in en_ticks(tableau["plugins_off"][1]) if "[" in m],
        )

    def test_the_shared_fixtures_cover_what_the_writers_must_keep(self):
        """Commentaire, clé inconnue, clé en double, fins CRLF, dernière
        ligne sans saut, octets hors UTF-8 : chaque cas a sa fixture."""
        entrees = [fixture[1] for fixture in fixtures_de_reglages()]

        def doublon(octets):
            cles = [
                ligne.split(b"=", 1)[0]
                for ligne in octets.split(b"\n")
                if b"=" in ligne
            ]
            return any(
                cles.count(ligne.encode()) > 1
                for ligne in service.CONFIG_LINES.values()
            )

        def hors_utf8(octets):
            try:
                octets.decode("utf-8")
            except UnicodeDecodeError:
                return True
            return False

        cas = {
            "commentaire": lambda o: b"\n#" in b"\n" + o,
            "clé inconnue": lambda o: re.search(
                rb"(?m)^(?!(%s)=)[A-Z_]+="
                % b"|".join(v.encode() for v in service.CONFIG_LINES.values()),
                o,
            ),
            "clé en double": doublon,
            "CRLF": lambda o: b"\r\n" in o,
            "sans saut final": lambda o: o and not o.endswith(b"\n"),
            "hors UTF-8": hors_utf8,
        }
        for nom, present in cas.items():
            with self.subTest(cas=nom):
                self.assertTrue(any(present(o) for o in entrees), nom)

    def test_write_settings_and_the_extension_rewrite_agree_on_the_fixtures(
        self,
    ):
        """Les lignes de chaque fixture viennent de ses valeurs du fil par
        le tableau, et les deux écrivains en tirent les mêmes octets."""
        fixtures = fixtures_de_reglages()
        self.assertTrue(fixtures)
        for nom, octets, reglages, maj, attendu in fixtures:
            avant = octets.decode("utf-8", "surrogateescape")
            with self.subTest(fixture=nom):
                self.assertEqual(
                    {
                        service.CONFIG_LINES[cle]: ligne_du_fil(valeur)
                        for cle, valeur in reglages.items()
                    },
                    maj,
                )
                self.assertEqual(
                    attendu,
                    service.settings_text(avant, maj).encode(
                        "utf-8", "surrogateescape"
                    ),
                )
                with tempfile.TemporaryDirectory() as dossier:
                    chemin = Path(dossier, "streamdeck.conf")
                    chemin.write_bytes(octets)
                    service.write_settings(str(chemin), maj)
                    self.assertEqual(attendu, chemin.read_bytes())


class LesIdentifiantsDePlugin(unittest.TestCase):
    def test_deck_plugin_ids_keeps_only_ids_the_wire_accepts(self):
        """Un fichier que le motif du fil refuse n'est pas proposé : Odoo
        le refuserait dans DECK_PLUGINS_OFF, et le deck ne le charge pas."""
        motif = re.compile(service.PLUGIN_ID_PATTERN)
        with tempfile.TemporaryDirectory() as dossier:
            plugins = Path(
                dossier, "script/stream_deck/erplibre_streamdeck/plugins"
            )
            plugins.mkdir(parents=True)
            noms = ("sound", "a" * 64, "a" * 65, "Bad-Name", "9lives", "é")
            for nom in noms:
                (plugins / ("%s.py" % nom)).write_text("")
            ids = service.deck_plugin_ids(
                dossier, {"XDG_CONFIG_HOME": str(Path(dossier, "cfg"))}
            )
        self.assertEqual(sorted(["sound", "a" * 64]), ids)
        self.assertTrue(all(motif.fullmatch(i) for i in ids))


def ecrire_pilote(dossier, contenu):
    """Pose `contenu` (texte, octets, ou objet sérialisé en JSON) dans
    <dossier>/erplibre-home/pilot.json ; rend son chemin."""
    chemin = Path(dossier, "erplibre-home", "pilot.json")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contenu, bytes):
        chemin.write_bytes(contenu)
    elif isinstance(contenu, str):
        chemin.write_text(contenu, encoding="utf-8")
    else:
        chemin.write_text(json.dumps(contenu), encoding="utf-8")
    return chemin


PILOTE = {"destination": DESTINATION, "revision": 4, "locked": ["games"]}

MAUVAIS_PILOTES = (
    "",
    "{",
    "[]",
    "null",
    b"\xff\xfe{}",
    "[" * 50000,
    {"revision": 4, "locked": []},
    {"destination": 3, "revision": 4, "locked": []},
    {"destination": DESTINATION, "revision": "4", "locked": []},
    {"destination": DESTINATION, "revision": True, "locked": []},
    {"destination": DESTINATION, "revision": 4, "locked": "games"},
    {"destination": DESTINATION, "revision": 4, "locked": [1]},
    {"destination": DESTINATION, "revision": 4},
    {"destination": "x" * 70000, "revision": 4, "locked": []},
    json.dumps(PILOTE) + " " * 70000,
)


class LeFichierPilote(unittest.TestCase):
    def test_read_pilot_reads_the_state_file(self):
        with tempfile.TemporaryDirectory() as dossier:
            ecrire_pilote(Path(dossier, "state"), PILOTE)
            ecrire_pilote(Path(dossier, "home/.local/state"), PILOTE)
            par_xdg = service.read_pilot(
                {"XDG_STATE_HOME": str(Path(dossier, "state"))}
            )
            par_home = service.read_pilot(
                {"HOME": str(Path(dossier, "home")), "XDG_STATE_HOME": ""}
            )
        self.assertEqual(PILOTE, par_xdg)
        self.assertEqual(PILOTE, par_home)

    def test_a_missing_or_bad_pilot_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as dossier:
            environ = {"XDG_STATE_HOME": dossier}
            self.assertIsNone(service.read_pilot(environ))
            for contenu in MAUVAIS_PILOTES:
                with self.subTest(contenu=repr(contenu)[:60]):
                    ecrire_pilote(dossier, contenu)
                    self.assertIsNone(service.read_pilot(environ))
            chemin = ecrire_pilote(dossier, PILOTE)
            chemin.chmod(0)
            if not os.access(chemin, os.R_OK):
                self.assertIsNone(service.read_pilot(environ))

    def test_unknown_keys_drop_and_the_label_cannot_steer_the_terminal(self):
        """Une clé que cet ERPLibre ne connaît pas (MINEURE plus récente)
        est ignorée ; un caractère de contrôle du libellé, qui piloterait
        le terminal où TODO l'affiche, devient « ? »."""
        with tempfile.TemporaryDirectory() as dossier:
            ecrire_pilote(
                dossier,
                {
                    "destination": "Odoo\x1b[2J\nde test",
                    "revision": 2,
                    "locked": ["key_layouts", "games", "games"],
                    "extra": True,
                },
            )
            pilote = service.read_pilot({"XDG_STATE_HOME": dossier})
        self.assertEqual(
            {
                "destination": "Odoo?[2J?de test",
                "revision": 2,
                "locked": ["games"],
            },
            pilote,
        )


class ExecuteFactice:
    """Retient chaque commande lancée en direct ; aucune ne part."""

    def __init__(self):
        self.commandes = []

    def exec_command_live(self, cmd, **_kwargs):
        self.commandes.append(cmd)
        return 0


# Chaque entrée du menu qui écrit une clé pilotée : la clé du fil, la
# méthode, les réponses au clavier, la ligne qu'elle écrit dans un
# fichier vide.
ENTREES = (
    ("deck_program", "_streamdeck_program", ("2",), "DECK_PROGRAM=controller"),
    ("games", "_streamdeck_games_setting", ("2",), "GAMES=off"),
    (
        "plugins_off",
        "_streamdeck_plugins_setting",
        ("1",),
        "DECK_PLUGINS_OFF=sound",
    ),
    (
        "session_refresh_sec",
        "_streamdeck_session_refresh_setting",
        ("2",),
        "DECK_SESSION_REFRESH_SEC=2",
    ),
)


class LAvertissementDuMenu(unittest.TestCase):
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
        os.environ.pop("XDG_STATE_HOME", None)
        self.reglages = self.home / ".config/erplibre-home/streamdeck.conf"
        unite = self.home / ".config/systemd/user" / UNITE
        unite.parent.mkdir(parents=True)
        unite.write_text("[Unit]\n")
        depot = self.home / "depot"
        plugins = depot / "script/stream_deck/erplibre_streamdeck/plugins"
        plugins.mkdir(parents=True)
        (plugins / "sound.py").write_text("")
        patch = mock.patch.object(streamdeck_menu, "RACINE", str(depot))
        patch.start()
        self.addCleanup(patch.stop)

    def piloter(self, verrouilles):
        ecrire_pilote(
            self.home / ".local/state",
            {
                "destination": DESTINATION,
                "revision": 3,
                "locked": list(verrouilles),
            },
        )

    def jouer(self, methode, reponses):
        """Lance `methode` avec `reponses` au clavier ; rend sa sortie."""
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()
        todo._streamdeck_probe = lambda argv: (1, "")
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch("builtins.input", side_effect=list(reponses)),
        ):
            getattr(todo, methode)()
        return sortie.getvalue()

    def test_a_locked_key_warns_and_still_writes(self):
        for cle, methode, reponses, ligne in ENTREES:
            with self.subTest(cle=cle):
                if self.reglages.exists():
                    self.reglages.unlink()
                self.piloter([cle])
                sortie = self.jouer(methode, reponses)
                self.assertEqual(1, sortie.splitlines().count(AVERTISSEMENT))
                self.assertEqual(ligne + "\n", self.reglages.read_text())

    def test_the_warning_is_translated(self):
        todo_i18n._current_lang = "fr"
        self.piloter(["games"])
        sortie = self.jouer("_streamdeck_games_setting", ("2",))
        self.assertIn(
            "Réglage verrouillé par Odoo (%s) : il sera reproposé."
            % DESTINATION,
            sortie,
        )

    def test_a_free_key_does_not_warn(self):
        for cle, methode, reponses, ligne in ENTREES:
            with self.subTest(cle=cle):
                if self.reglages.exists():
                    self.reglages.unlink()
                self.piloter(k for k in service.CONFIG_LINES if k != cle)
                sortie = self.jouer(methode, reponses)
                self.assertNotIn("locked by Odoo", sortie)
                self.assertEqual(ligne + "\n", self.reglages.read_text())

    def test_an_unchanged_value_does_not_warn(self):
        """La période retapée telle quelle n'écrit rien : rien à
        reproposer, donc rien à dire."""
        self.piloter(["session_refresh_sec"])
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text("DECK_SESSION_REFRESH_SEC=2\n")
        sortie = self.jouer("_streamdeck_session_refresh_setting", ("2",))
        self.assertNotIn("locked by Odoo", sortie)
        self.assertIn("Unchanged.", sortie)

    def test_a_missing_or_bad_pilot_file_is_ignored(self):
        for contenu in (None,) + MAUVAIS_PILOTES:
            with self.subTest(contenu=repr(contenu)[:60]):
                chemin = self.home / ".local/state/erplibre-home/pilot.json"
                if chemin.exists():
                    chemin.unlink()
                if contenu is not None:
                    ecrire_pilote(self.home / ".local/state", contenu)
                if self.reglages.exists():
                    self.reglages.unlink()
                sortie = self.jouer("_streamdeck_games_setting", ("2",))
                self.assertNotIn("locked by Odoo", sortie)
                self.assertEqual("GAMES=off\n", self.reglages.read_text())


if __name__ == "__main__":
    unittest.main()
