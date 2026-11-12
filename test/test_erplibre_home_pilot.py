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
  même ; une clé libre, ou une valeur inchangée, ne dit rien. L'installation
  Stream Deck, qui change DECK_PROGRAM par --deck-program, fait de même ;
- le format de keymap.json que pose le contrat égale les constantes de
  keymap.py, --catalog rend la forme qu'il énonce, et le chargeur du deck
  donne à chaque fixture partagée de keymap.json le verdict qu'elle porte :
  il ne saute rien de ce que l'extension écrit, et pose telles qu'envoyées
  les entrées qu'il dit poser.

Ce qui lit le clone est sauté quand il manque (SANS_EXTENSION), ou quand
son contrat précède la version qui pose le tableau ou le format : une
MINEURE en retard reste compatible, repo sync l'amène.
"""

import contextlib
import dataclasses
import io
import json
import os
import re
import sys
import tempfile
import types
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "script/stream_deck"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = ["todo.py"]

from erplibre_home_extension import (  # noqa: E402
    SANS_EXTENSION,
    fixtures_de_dispositions,
    fixtures_de_reglages,
    reglages_du_contrat,
    valeur_du_contrat,
    version_du_contrat,
)
from erplibre_streamdeck import keymap, paths  # noqa: E402
from erplibre_streamdeck.plugin import Geometry  # noqa: E402
from erplibre_streamdeck.ui import icons  # noqa: E402

from script.todo import erplibre_home_service as service  # noqa: E402
from script.todo import streamdeck_menu  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

# La version du contrat qui pose le tableau des réglages pilotés.
CONTRAT_DU_PILOTE = (1, 3)
# La version du contrat qui pose keymap.json et --catalog.
CONTRAT_DES_DISPOSITIONS = (1, 4)
CONTRAT_INSCRIT = RACINE / "script/gnome-extension/erplibre_home_contract"
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


def forme_du_contrat(motif):
    """L'objet JSON que le contrat écrit avec des espaces réservés : la
    valeur que donne `motif` (groupe 1), chaque « <nom> » devenu la
    chaîne "nom", lue par json.loads. Ses clés et leur ordre sont ce que
    le contrat promet."""
    texte = valeur_du_contrat(motif)
    return json.loads(re.sub(r"<(\w+)>", r'"\1"', texte))


def plugins_nommes(disposition):
    """Les identifiants des actions « plugin:<id> » d'une disposition
    telle que le fichier la porte, quelle que soit sa forme."""
    cles = disposition.get("keys") if isinstance(disposition, dict) else None
    return {
        entree["action"][len("plugin:") :]
        for entree in (cles if isinstance(cles, list) else ())
        if isinstance(entree, dict)
        and isinstance(entree.get("action"), str)
        and entree["action"].startswith("plugin:")
    }


def verdict_du_chargeur(cas):
    """Ce que le chargeur du deck fait d'un keymap.json qui porte les
    `layouts` d'une fixture, comme l'article 11 du contrat le calcule :
    load, puis layout_for sur chaque modèle du catalogue, chargés avec un
    bouton d'accueil les plugins que la disposition nomme, sauf ceux que
    le catalogue n'offre pas ou que `plugins_off` éteint. Rend (verdict,
    lignes) : « problem » et les problèmes au premier problème ; sinon
    « altered » et les écarts quand une disposition posée diffère de ses
    entrées envoyées, lues en Entry(key, action, icon, label) (un champ
    inconnu ne compte pas) ; sinon « as_sent » quand une disposition au
    moins est posée, sinon « automatic ». « altered » n'est pas un verdict
    du contrat : aucune fixture ne le porte."""
    catalogue = cas["catalog"]
    with tempfile.TemporaryDirectory() as dossier:
        chemin = Path(dossier, "keymap.json")
        chemin.write_text(
            json.dumps(
                {"format": 1, "revision": 0, "layouts": cas["layouts"]}
            ),
            encoding="utf-8",
        )
        with contextlib.redirect_stderr(io.StringIO()):
            donnees = keymap.load(chemin)
    offerts = {
        action[len("plugin:") :]
        for action in catalogue["actions"]
        if action.startswith("plugin:")
    } - set(cas["plugins_off"])
    dispositions = donnees.get("layouts", {}) if donnees else {}
    problemes, ecarts, posee = [], [], False
    for modele, geo in sorted(catalogue["models"].items()):
        entrees, trouves = keymap.layout_for(
            donnees,
            modele,
            Geometry(geo["cols"], geo["rows"], geo["keys"]),
            offerts & plugins_nommes(dispositions.get(modele)),
            set(catalogue["icons"]),
        )
        problemes += trouves
        if entrees is None:
            continue
        posee = True
        if trouves:
            # Une entrée sautée peut n'avoir aucune forme : rien à comparer.
            continue
        envoyees = entrees_envoyees(dispositions[modele])
        if entrees != envoyees:
            ecarts.append(f"{modele}: {envoyees} posées en {entrees}")
    if problemes:
        return "problem", problemes
    if ecarts:
        return "altered", ecarts
    return ("as_sent" if posee else "automatic"), []


def entrees_envoyees(disposition):
    """Les entrées d'une disposition telles que le fichier les porte, en
    Entry : les quatre champs du format, les autres laissés de côté."""
    return [
        keymap.Entry(
            entree["key"],
            entree["action"],
            entree.get("icon"),
            entree.get("label"),
        )
        for entree in disposition["keys"]
    ]


ICONE = sorted(icons.ICONS)[0]
CAS_POSE = {
    "catalog": {
        "format": 1,
        "actions": ["plugin:timers", "tiles", "empty"],
        "icons": [ICONE],
        "models": {"0084": {"cols": 4, "rows": 2, "keys": 8}},
    },
    "plugins_off": [],
    "layouts": {
        "0084": {
            "keys": [
                {
                    "key": 0,
                    "action": "plugin:timers",
                    "icon": ICONE,
                    "label": "Minuteries",
                },
                {"key": 1, "action": "tiles"},
                {"key": 2, "action": "empty"},
            ]
        }
    },
}


class LeVerdictDuChargeur(unittest.TestCase):
    """verdict_du_chargeur ne dit « as_sent » que si le chargeur pose les
    entrées envoyées, et non une disposition seulement."""

    def test_the_loader_lays_out_the_entries_as_sent(self):
        self.assertEqual(("as_sent", []), verdict_du_chargeur(CAS_POSE))

    def test_a_loader_that_changes_an_entry_is_not_as_sent(self):
        reel = keymap.layout_for
        alterations = {
            "icon and label dropped": lambda entrees: [
                keymap.Entry(e.key, e.action) for e in entrees
            ],
            "tiles skipped": lambda entrees: [
                e for e in entrees if e.action != "tiles"
            ],
            "keys shifted": lambda entrees: [
                keymap.Entry((e.key + 1) % 8, e.action, e.icon, e.label)
                for e in entrees
            ],
        }
        for nom, alterer in alterations.items():

            def altere(*args, alterer=alterer):
                entrees, problemes = reel(*args)
                if entrees is not None:
                    entrees = alterer(entrees)
                return entrees, problemes

            with self.subTest(alteration=nom), mock.patch.object(
                keymap, "layout_for", altere
            ):
                verdict, ecarts = verdict_du_chargeur(CAS_POSE)
                self.assertNotEqual("as_sent", verdict)
                self.assertTrue(ecarts)


def un_par_categorie():
    """{catégorie Unicode: premier point de code de cette catégorie}, sur
    tout l'espace Unicode : chaque catégorie a son représentant."""
    exemples = {}
    for point in range(sys.maxunicode + 1):
        exemples.setdefault(unicodedata.category(chr(point)), chr(point))
    return exemples


class LaVersionInscrite(unittest.TestCase):
    def test_the_recorded_contract_covers_the_key_layouts(self):
        """keymap.py lit keymap.json et --catalog sort le catalogue que
        pose le contrat 1.4 : ERPLibre inscrit au moins cette version, et
        un clone plus ancien se dit en retard."""
        texte = CONTRAT_INSCRIT.read_text(encoding="utf-8").strip()
        self.assertRegex(texte, r"^\d+\.\d+$")
        inscrite = tuple(int(n) for n in texte.split("."))
        self.assertGreaterEqual(inscrite, CONTRAT_DES_DISPOSITIONS)


@SANS_EXTENSION
class LeContratDesDispositions(unittest.TestCase):
    def setUp(self):
        version = version_du_contrat()
        if version < CONTRAT_DES_DISPOSITIONS:
            self.skipTest(
                "contrat du clone %d.%d, keymap.json en %d.%d : repo sync"
                % (version + CONTRAT_DES_DISPOSITIONS)
            )

    def test_the_keymap_format_matches_the_loader_constants(self):
        fichier = forme_du_contrat(r'`(\{"format": \d+, "revision": [^`]*)`')
        self.assertEqual(keymap.FORMAT, fichier["format"])
        self.assertEqual(
            "~/" + str(paths.KEYMAP_FILE.relative_to(Path.home())),
            valeur_du_contrat(r"`(~/[^`]*keymap\.json)`"),
        )
        entree = forme_du_contrat(r'`(\{"key": [^`]*)`')
        self.assertEqual(
            [champ.name for champ in dataclasses.fields(keymap.Entry)],
            list(entree),
        )
        self.assertEqual(
            str(keymap.MAX_MODELS),
            valeur_du_contrat(r"4 lowercase hex digits, (\d+) models at most"),
        )
        self.assertEqual(
            str(keymap.LABEL_MAX),
            valeur_du_contrat(
                r"`label` at most (\d+) characters, counted by code point"
            ),
        )
        self.assertEqual(
            keymap.PLUGIN_ID,
            valeur_du_contrat(r"`<id>` of the pattern `([^`]+)`"),
        )
        self.assertEqual(
            set(keymap.FIXED_ACTIONS),
            {
                valeur_du_contrat(r"`(\w+)` \(a key of the dashboard\)"),
                valeur_du_contrat(r"`(\w+)` \(a black key\)"),
            },
        )

    def test_the_loader_refuses_no_label_the_contract_admits(self):
        """Un libellé que layout_for saute doit être un libellé que le
        contrat interdit : sinon le deck perdrait une touche que
        l'extension a écrite. Le chargeur peut être plus large."""
        interdites = set(
            re.findall(
                r"\b(C[a-z])\b",
                valeur_du_contrat(
                    r"none of the Unicode categories ([A-Za-z ,]+?)\. "
                ),
            )
        )
        self.assertIn("Cc", interdites)
        sautees = set()
        for categorie, caractere in un_par_categorie().items():
            donnees = {
                "format": 1,
                "layouts": {
                    "0084": {
                        "keys": [
                            {"key": 0, "action": "tiles", "label": caractere}
                        ]
                    }
                },
            }
            _entrees, problemes = keymap.layout_for(
                donnees, "0084", Geometry(4, 2, 8), set(), set()
            )
            if problemes:
                sautees.add(categorie)
        self.assertTrue(sautees)
        self.assertLessEqual(sautees, interdites)

    def test_the_catalog_has_the_shape_the_contract_states(self):
        forme = forme_du_contrat(
            r'deck lock: `(\{"format": \d+, "actions": [^`]*)`'
        )
        avec = types.SimpleNamespace(home_button=object())
        sans = types.SimpleNamespace(home_button=None)
        charges = [
            types.SimpleNamespace(id="timers", plugin=avec),
            types.SimpleNamespace(id="tiling", plugin=sans),
        ]
        modeles = {"0084": {"cols": 4, "rows": 2, "keys": 8}}
        with mock.patch.object(keymap, "models", return_value=modeles):
            catalogue = keymap.catalog(charges, off=("sound",))
        self.assertEqual(list(forme), list(catalogue))
        self.assertEqual(forme["format"], catalogue["format"])
        (modele,) = forme["models"].values()
        self.assertEqual(list(modele), list(catalogue["models"]["0084"]))
        fixes = valeur_du_contrat(
            r"that have a home key, then (`\w+` and `\w+`)"
        )
        self.assertEqual(
            re.findall(r"`(\w+)`", fixes), catalogue["actions"][-2:]
        )
        self.assertEqual(
            ["plugin:sound", "plugin:timers"], catalogue["actions"][:-2]
        )
        motif_icone = valeur_du_contrat(
            r"the icon names of the pattern `([^`]+)`"
        )
        self.assertEqual(sorted(icons.ICONS), catalogue["icons"])
        for nom in catalogue["icons"]:
            with self.subTest(icone=nom):
                self.assertRegex(nom, r"\A(?:%s)\Z" % motif_icone)

    def test_the_loader_gives_each_keymap_fixture_its_stated_verdict(self):
        fixtures = fixtures_de_dispositions()
        self.assertTrue(fixtures)
        for nom, cas in fixtures:
            with self.subTest(fixture=nom):
                verdict, problemes = verdict_du_chargeur(cas)
                self.assertEqual(cas["loader"], verdict, problemes)

    def test_the_deck_skips_nothing_the_extension_writes(self):
        """Revue 4 vue du deck : une disposition que l'extension écrit
        (valid) n'a aucune entrée sautée ni vidée par le chargeur."""
        valides = [
            (nom, cas)
            for nom, cas in fixtures_de_dispositions()
            if cas["valid"]
        ]
        self.assertTrue(valides)
        for nom, cas in valides:
            with self.subTest(fixture=nom):
                self.assertNotEqual("problem", cas["loader"])
                verdict, problemes = verdict_du_chargeur(cas)
                self.assertEqual([], problemes)
                self.assertIn(verdict, ("as_sent", "automatic"))


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
        """Une clé qu'aucune entrée de TODO n'écrit (key_layouts, dans
        keymap.json et non dans streamdeck.conf) ou que cet ERPLibre ne
        connaît pas (MINEURE plus récente) est ignorée ; un caractère de
        contrôle du libellé, qui piloterait le terminal où TODO l'affiche,
        devient « ? »."""
        with tempfile.TemporaryDirectory() as dossier:
            ecrire_pilote(
                dossier,
                {
                    "destination": "Odoo\x1b[2J\nde test",
                    "revision": 2,
                    "locked": ["key_layouts", "games", "games", "later"],
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

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        if kwargs.get("return_status_and_output"):
            return 0, []
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

    def installer(self, reponses):
        """L'installation Stream Deck de TODO sur un poste dont les
        réglages portent DECK_PROGRAM=tiler ; rend sa sortie et les
        commandes lancées."""
        self.reglages.parent.mkdir(parents=True, exist_ok=True)
        self.reglages.write_text("DECK_PROGRAM=tiler\n")
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch("builtins.input", side_effect=list(reponses)),
        ):
            todo._erplibre_home_streamdeck_install_local()
        return sortie.getvalue(), todo.execute.commandes

    def test_the_stream_deck_install_warns_on_a_locked_program(self):
        """L'installateur réécrit DECK_PROGRAM par --deck-program : un
        autre programme que celui en place, verrouillé, se dit avant de
        partir, et l'installation part quand même."""
        self.piloter(["deck_program"])
        sortie, commandes = self.installer(("2", "", "", ""))
        self.assertEqual(1, sortie.splitlines().count(AVERTISSEMENT))
        self.assertEqual(1, len(commandes))
        self.assertIn("--deck-program=controller", commandes[0])

    def test_the_stream_deck_install_keeping_the_program_does_not_warn(self):
        for verrouilles, reponses in (
            (["deck_program"], ("", "", "", "")),
            (["deck_program"], ("1", "", "", "")),
            (
                [k for k in service.CONFIG_LINES if k != "deck_program"],
                ("2", "", "", ""),
            ),
        ):
            with self.subTest(verrouilles=verrouilles, reponses=reponses):
                self.piloter(verrouilles)
                sortie, commandes = self.installer(reponses)
                self.assertNotIn("locked by Odoo", sortie)
                self.assertEqual(1, len(commandes))


if __name__ == "__main__":
    unittest.main()
