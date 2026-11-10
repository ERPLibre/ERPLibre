#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'extension GNOME ERPLibre Home est un dépôt à part, cloné dans
script/gnome-extension/erplibre_home/.

Ce que ces tests gardent :

- ERPLibre ne suit aucun fichier du clone, qu'il ignore, ni ce que la
  passation à repo sync et l'installateur posent à côté ; il suit le
  fichier de la version du contrat ;
- le manifeste de l'extension suit sa branche main, à son chemin, dans le
  groupe erplibre_home, sous le remote TechnoLibre du mobile ; seule
  conf/git_manifest_erplibre_home.csv le nomme, et l'init de repo qui
  nomme ses groupes garde erplibre_home, faute de quoi repo supprimerait
  l'extension de la session ;
- erplibre_home_contract porte une version MAJEUR.MINEUR, et un clone dont
  CONTRACT.md porte une autre version MAJEURE fait échouer la suite ;
- chaque méthode D-Bus qu'appelle le programme du deck figure au tableau
  du contrat avec autant d'arguments d'entrée que l'appel en passe, sur
  l'objet et l'interface que le client nomme ;
- les chemins d'ERPLibre que le contrat dit employés par l'extension
  désignent des fichiers d'ERPLibre, et la racine de checkout qu'il
  énonce est le chemin du manifeste ;
- chaque clé que le deck lit d'un enregistrement partagé figure au
  tableau des enregistrements du contrat ;
- make test_gnome_extension lance les commandes de test du contrat.

Ce qui lit le clone est sauté, avec sa raison, quand il manque
(SANS_EXTENSION), et n'en lit que CONTRACT.md. L'extension se teste
elle-même dans son dépôt : test/unit/contract.test.js y tient son code à
CONTRACT.md.
"""

import ast
import csv
import os
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from erplibre_home_extension import (  # noqa: E402
    CHEMIN,
    EXTENSION,
    SANS_EXTENSION,
    contrat,
    contrat_a_plat,
    enregistrements,
    methodes_promises,
    objet_et_interface,
)

ROOT = Path(__file__).resolve().parent.parent
MANIFESTE = "manifest/git_manifest_erplibre_home_gnome_extension.xml"
LISTE = "git_manifest_erplibre_home.csv"
CONTRAT = ROOT / "script/gnome-extension/erplibre_home_contract"
DECK = ROOT / "script/stream_deck"
LIGNE_DE_VERSION = re.compile(r"^\*\*Contract version: (\d+\.\d+)\*\*$", re.M)


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    )


def texte(chemin):
    return Path(chemin).read_text(encoding="utf-8")


class LaFrontiere(unittest.TestCase):
    def test_erplibre_tracks_nothing_under_the_extension(self):
        suivis = git("ls-files", CHEMIN)
        self.assertEqual(0, suivis.returncode, suivis.stderr)
        self.assertEqual("", suivis.stdout)

    def test_the_clone_and_what_is_set_aside_are_ignored(self):
        """Le clone, son .git que la passation met de côté et le clone en
        cours de l'installateur."""
        for chemin in (
            CHEMIN + "/metadata.json",
            CHEMIN + "/locale/fr/LC_MESSAGES/erplibre-home.mo",
            "script/gnome-extension/erplibre_home.plain-clone-git-x/HEAD",
            "script/gnome-extension/erplibre_home.ABC123/metadata.json",
        ):
            with self.subTest(chemin=chemin):
                self.assertEqual(
                    0, git("check-ignore", "-q", chemin).returncode
                )

    def test_the_contract_version_file_is_tracked(self):
        relatif = str(CONTRAT.relative_to(ROOT))
        self.assertEqual(1, git("check-ignore", "-q", relatif).returncode)
        self.assertEqual(relatif + "\n", git("ls-files", relatif).stdout)


class LeManifeste(unittest.TestCase):
    def setUp(self):
        self.racine = ET.parse(ROOT / MANIFESTE).getroot()
        (self.projet,) = [
            p for p in self.racine.iter("project") if p.get("path") == CHEMIN
        ]

    def test_it_follows_the_main_branch_of_the_extension(self):
        """Une version MAJEURE du contrat qui change sur main touche tout
        checkout à sa prochaine mise à jour : LeContrat le surveille."""
        remotes = {
            r.get("name"): r.get("fetch") for r in self.racine.iter("remote")
        }
        self.assertEqual(
            "erplibre-home-gnome-extension.git", self.projet.get("name")
        )
        self.assertEqual(
            "https://github.com/TechnoLibre/",
            remotes[self.projet.get("remote")],
        )
        self.assertEqual("main", self.projet.get("revision"))

    def test_it_belongs_to_the_erplibre_home_group(self):
        groupes = self.projet.get("groups", "").split(",")
        self.assertIn("erplibre_home", groupes)

    def test_its_remote_is_named_technolibre_like_the_mobile(self):
        self.assertEqual("TechnoLibre", self.projet.get("remote"))
        mobile = ET.parse(ROOT / "manifest/git_manifest_mobile_home.xml")
        remotes_du_mobile = {
            r.get("name"): r.get("fetch")
            for r in mobile.getroot().iter("remote")
        }
        (remote,) = [
            r
            for r in self.racine.iter("remote")
            if r.get("name") == "TechnoLibre"
        ]
        self.assertEqual(remotes_du_mobile["TechnoLibre"], remote.get("fetch"))

    def test_only_its_own_list_names_it(self):
        """Les listes générales entrent dans toute fusion, celle d'un
        serveur Odoo comprise ; celle du Stream Deck n'a pas à l'amener :
        la base d'ERPLibre Home s'installe sans le deck."""
        for liste, nomme in (
            (LISTE, True),
            ("git_manifest.csv", False),
            ("git_manifest_mobile.csv", False),
            ("git_manifest_odoo.csv", False),
            ("git_manifest_streamdeck.csv", False),
        ):
            with self.subTest(liste=liste):
                with open(ROOT / "conf" / liste, encoding="utf-8") as fh:
                    fichiers = [
                        ligne["filepath"] for ligne in csv.DictReader(fh)
                    ]
                self.assertEqual(nomme, MANIFESTE in fichiers)

    def test_the_code_generator_init_keeps_the_erplibre_home_group(self):
        """Un groupe absent de l'init fait supprimer par repo le répertoire
        du projet : l'extension que la session a chargée."""
        script = ROOT / (
            "script/manifest/update_manifest_local_dev_code_generator.sh"
        )
        (init,) = [
            ligne
            for ligne in texte(script).splitlines()
            if "bin/repo init" in ligne
        ]
        groupes = re.search(r"-g (\S+)", init).group(1).split(",")
        self.assertIn("erplibre_home", groupes)


class LeContrat(unittest.TestCase):
    def majeure(self, version):
        self.assertRegex(version, r"^\d+\.\d+$")
        return version.split(".")[0]

    def test_the_contract_file_holds_one_version(self):
        self.majeure(texte(CONTRAT).strip())

    @SANS_EXTENSION
    def test_the_clone_shares_its_major(self):
        """Une MAJEURE qui diffère : ERPLibre et l'extension ne s'entendent
        plus sur CONTRACT.md ; main de l'extension a changé de MAJEURE sans
        que erplibre_home_contract suive."""
        attendue = texte(CONTRAT).strip()
        (clonee,) = LIGNE_DE_VERSION.findall(texte(EXTENSION / "CONTRACT.md"))
        self.assertEqual(self.majeure(attendue), self.majeure(clonee))


@SANS_EXTENSION
class LesSuitesDeLExtension(unittest.TestCase):
    def test_make_runs_the_test_commands_the_contract_states(self):
        """make test_gnome_extension lance, depuis la racine d'ERPLibre,
        les commandes que l'article 2 du contrat énonce depuis celle du
        clone."""
        makefile = texte(ROOT / "conf/make.test.Makefile")
        a_plat = contrat_a_plat()
        for commande, dossier in (
            ("node --test %stest/unit/*.test.js", "test/unit"),
            ("python3 -m unittest discover -s %stest/python", "test/python"),
        ):
            with self.subTest(dossier=dossier):
                self.assertIn("`%s`" % (commande % ""), a_plat)
                self.assertIn(commande % (CHEMIN + "/"), makefile)


def appels_d_bus():
    """{méthode: {nombres d'arguments}} des appels dbus.call(...) du
    programme du deck dont la méthode est une chaîne littérale."""
    appels = {}
    for fichier in sorted((DECK / "erplibre_streamdeck").rglob("*.py")):
        for noeud in ast.walk(ast.parse(texte(fichier))):
            if not (
                isinstance(noeud, ast.Call)
                and isinstance(noeud.func, ast.Attribute)
                and noeud.func.attr == "call"
                and isinstance(noeud.func.value, ast.Name)
                and noeud.func.value.id == "dbus"
                and noeud.args
            ):
                continue
            methode = noeud.args[0]
            if isinstance(methode, ast.Constant):
                appels.setdefault(methode.value, set()).add(
                    len(noeud.args) - 1
                )
    return appels


@SANS_EXTENSION
class LInterfaceDBus(unittest.TestCase):
    """Le deck appelle l'extension par erplibre_streamdeck/dbus.py. Une
    méthode renommée ou un argument de plus ne se voit qu'à l'exécution,
    sur une session, par un bouton qui ne fait rien. Le tableau du
    contrat en fait foi ; contract.test.js, dans le dépôt de l'extension,
    y tient extension.js."""

    def setUp(self):
        self.promises = methodes_promises()

    def test_the_client_names_the_promised_object(self):
        client = ast.parse(texte(DECK / "erplibre_streamdeck/dbus.py"))
        valeurs = {
            cible.id: noeud.value.value
            for noeud in ast.walk(client)
            if isinstance(noeud, ast.Assign)
            and isinstance(noeud.value, ast.Constant)
            for cible in noeud.targets
            if isinstance(cible, ast.Name)
        }
        self.assertEqual("org.gnome.Shell", valeurs["DEST"])
        self.assertIn("`org.gnome.Shell`", contrat_a_plat())
        self.assertEqual(
            objet_et_interface(), (valeurs["PATH"], valeurs["IFACE"])
        )

    def test_every_call_is_promised_with_its_arguments(self):
        appels = appels_d_bus()
        self.assertIn("TileWindow", appels)
        for methode, arites in sorted(appels.items()):
            with self.subTest(methode=methode):
                self.assertIn(methode, self.promises)
                self.assertEqual({self.promises[methode]}, arites)

    def test_the_claude_session_methods_take_the_session_id(self):
        """claude_sessions.py passe le nom de la méthode en variable, avec
        un seul argument : l'identifiant de session."""
        source = texte(DECK / "erplibre_streamdeck/plugins/claude_sessions.py")
        nommees = [
            m
            for m in self.promises
            if m.endswith("ClaudeSession") or m == "SetClaudeSessionWindow"
        ]
        self.assertTrue(nommees)
        for methode in nommees:
            with self.subTest(methode=methode):
                self.assertIn('"%s"' % methode, source)
                self.assertEqual(1, self.promises[methode])


@SANS_EXTENSION
class LesChemins(unittest.TestCase):
    """Les chemins, relatifs au checkout, que l'extension lance ou cherche
    quand elle tourne dans ERPLibre, tels que les énonce la section « What
    the extension relies on » du contrat."""

    def setUp(self):
        (self.section,) = re.findall(
            r"^## What the extension relies on\n(.*?)^## ",
            contrat(),
            re.M | re.S,
        )

    def chemins(self):
        """Les chemins script/... que la section nomme, ./ ôté."""
        return set(
            re.findall(
                r"(?<![\w./-])(?:\./)?(script/[\w./-]+\.(?:py|sh|md))",
                self.section,
            )
        )

    def test_the_erplibre_files_it_runs_exist(self):
        jeux = self.galerie()
        chemins = self.chemins() - {jeux}
        for attendu in (
            "script/stream_deck/erplibre_controller.py",
            "script/install/erplibre_home_deck.sh",
            "script/todo/todo.py",
        ):
            self.assertIn(attendu, chemins)
        for relatif in sorted(chemins):
            with self.subTest(chemin=relatif):
                self.assertTrue((ROOT / relatif).is_file())

    def test_the_deck_python_is_the_venv_the_installer_creates(self):
        installateur = texte(ROOT / "script/install/install_erplibre_home.sh")
        (venv,) = re.findall(
            r'^VENV="\$\{RACINE\}/([^"]+)"$', installateur, re.M
        )
        self.assertIn("`%s/bin/python`" % venv, self.section)

    def galerie(self):
        (relatif,) = re.findall(
            r"`(script/[\w./-]+/gallery_server\.py)`", self.section
        )
        return relatif

    def test_the_gallery_is_the_one_of_the_games_clone(self):
        reglages = texte(ROOT / "script/install/erplibre_home_settings.sh")
        (jeux,) = re.findall(r'^DECK_GAMES_DIR="([^"]+)"$', reglages, re.M)
        self.assertEqual(jeux + "/gallery_server.py", self.galerie())

    def test_the_deck_unit_and_install_target_are_erplibre_s(self):
        (unite,) = re.findall(r"`([\w-]+\.service)`", self.section)
        self.assertIn(
            unite,
            texte(ROOT / "script/install/erplibre_home_settings.sh")
            + texte(ROOT / "script/install/install_erplibre_home.sh"),
        )
        (cible,) = re.findall(r"`make (\w+_install)`", self.section)
        makefiles = "".join(
            texte(f) for f in sorted((ROOT / "conf").glob("make.*.Makefile"))
        )
        self.assertRegex(makefiles, r"(?m)^%s:" % cible)

    def test_the_checkout_root_is_the_manifest_path(self):
        self.assertIn("`/%s`" % CHEMIN, self.section)


def cles_lues(fichier, variables):
    """Les clés littérales lues par `v.get("clé")` ou `v["clé"]` d'un
    fichier Python, pour v parmi `variables`."""
    cles = set()
    for noeud in ast.walk(ast.parse(texte(fichier))):
        if (
            isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
            and noeud.func.attr == "get"
            and isinstance(noeud.func.value, ast.Name)
            and noeud.func.value.id in variables
            and noeud.args
            and isinstance(noeud.args[0], ast.Constant)
        ):
            cles.add(noeud.args[0].value)
        elif (
            isinstance(noeud, ast.Subscript)
            and isinstance(noeud.value, ast.Name)
            and noeud.value.id in variables
            and isinstance(noeud.slice, ast.Constant)
        ):
            cles.add(noeud.slice.value)
    return cles


def cles_ecrites(fichier, temoin):
    """Les clés de chaque dict littéral d'un fichier Python qui porte la
    clé `temoin` : ce que le fichier écrit d'un enregistrement."""
    ecrits = []
    for noeud in ast.walk(ast.parse(texte(fichier))):
        if isinstance(noeud, ast.Dict):
            cles = {c.value for c in noeud.keys if isinstance(c, ast.Constant)}
            if temoin in cles:
                ecrits.append(cles)
    return ecrits


@SANS_EXTENSION
class LesEnregistrements(unittest.TestCase):
    """Le deck lit clé par clé les fichiers d'état que l'extension écrit.
    Une clé que le contrat ne nomme pas peut changer sur main sans que la
    version bouge : le deck montrerait alors un mauvais état, sans erreur.
    Les tests du deck, eux, lisent des fichiers fabriqués."""

    PLUGINS = DECK / "erplibre_streamdeck/plugins"

    def setUp(self):
        self.tableau = enregistrements()

    def test_the_contract_lists_the_three_records(self):
        self.assertEqual(
            {"claude/*.json", "mpv/*.json", "todo_terminals.json"},
            set(self.tableau),
        )

    def test_the_deck_reads_only_promised_claude_keys(self):
        lues = cles_lues(self.PLUGINS / "claude_sessions.py", {"d"})
        self.assertIn("ts_active", lues)
        self.assertLessEqual(lues, set(self.tableau["claude/*.json"]))

    def test_the_deck_reads_only_promised_mpv_keys(self):
        lues = cles_lues(self.PLUGINS / "mpv_sessions.py", {"d"})
        self.assertIn("started_at", lues)
        self.assertLessEqual(lues, set(self.tableau["mpv/*.json"]))

    def test_the_deck_reads_and_writes_promised_terminal_keys(self):
        """Le deck et l'extension ajoutent chacun leurs entrées au même
        fichier : le deck écrit toutes les clés du contrat."""
        fichier = self.PLUGINS / "todo_terminals.py"
        promises = set(self.tableau["todo_terminals.json"])
        lues = cles_lues(fichier, {"t", "term", "existing"})
        self.assertIn("window_id", lues)
        self.assertLessEqual(lues, promises)
        self.assertEqual([promises], cles_ecrites(fichier, "window_id"))


if __name__ == "__main__":
    unittest.main()
