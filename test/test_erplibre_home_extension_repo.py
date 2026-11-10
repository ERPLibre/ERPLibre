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
  du contrat, et extension.js la déclare avec autant d'arguments d'entrée
  que l'appel en passe, sur l'objet et l'interface que le client nomme ;
- les chemins qu'emploie l'extension dans un checkout désignent des
  fichiers d'ERPLibre, et son motif de racine reconnaît le chemin du
  manifeste.

Ce qui lit le clone est sauté, avec sa raison, quand il manque
(SANS_EXTENSION). L'extension se teste elle-même dans son dépôt :
test/unit/contract.test.js y confronte CONTRACT.md à ses propres fichiers.
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
                    fichiers = [l["filepath"] for l in csv.DictReader(fh)]
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
    sur une session, par un bouton qui ne fait rien."""

    def setUp(self):
        self.source = texte(EXTENSION / "extension.js")
        self.methodes = {
            nom: corps.count('direction="in"')
            for nom, corps in re.findall(
                r'<method name="(\w+)">(.*?)</method>', self.source, re.S
            )
        }
        self.methodes.update(
            {
                nom: 0
                for nom in re.findall(
                    r'<method name="(\w+)"\s*/>', self.source
                )
            }
        )
        contrat = texte(EXTENSION / "CONTRACT.md")
        self.promises = set(re.findall(r"^\s*\| `(\w+)` \|", contrat, re.M))

    def test_the_client_names_the_exported_object(self):
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
        self.assertIn("'%s'" % valeurs["PATH"], self.source)
        self.assertIn('<interface name="%s">' % valeurs["IFACE"], self.source)

    def test_every_call_is_promised_and_declared_with_its_arguments(self):
        appels = appels_d_bus()
        self.assertIn("TileWindow", appels)
        for methode, arites in sorted(appels.items()):
            with self.subTest(methode=methode):
                self.assertIn(methode, self.promises)
                self.assertIn(methode, self.methodes)
                self.assertEqual({self.methodes[methode]}, arites)

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
                self.assertEqual(1, self.methodes[methode])


@SANS_EXTENSION
class LesChemins(unittest.TestCase):
    """Les chemins, relatifs au checkout, que l'extension lance ou cherche
    quand elle tourne dans ERPLibre."""

    def constante(self, fichier, nom):
        (valeur,) = re.findall(
            r"^export const %s = '([^']+)';$" % nom,
            texte(EXTENSION / fichier),
            re.M,
        )
        return valeur

    def test_the_deck_files_it_runs_exist(self):
        for fichier, nom in (
            ("lib/deck-service.js", "CONTROLLER_REL"),
            ("lib/deck-service.js", "DECK_ENTRY_REL"),
        ):
            with self.subTest(nom=nom):
                self.assertTrue(
                    (ROOT / self.constante(fichier, nom)).is_file()
                )

    def test_the_deck_python_is_the_venv_the_installer_creates(self):
        relatif = self.constante(
            "lib/project-root.js", "STREAMDECK_PYTHON_REL"
        )
        installateur = texte(ROOT / "script/install/install_erplibre_home.sh")
        self.assertIn('VENV="${RACINE}/.venv.streamdeck"', installateur)
        self.assertEqual(".venv.streamdeck/bin/python", relatif)

    def test_the_gallery_is_the_one_of_the_games_clone(self):
        relatif = self.constante("lib/project-root.js", "GALLERY_SERVER_REL")
        reglages = texte(ROOT / "script/install/erplibre_home_settings.sh")
        (jeux,) = re.findall(r'^DECK_GAMES_DIR="([^"]+)"$', reglages, re.M)
        self.assertEqual(jeux + "/gallery_server.py", relatif)

    def test_the_checkout_root_is_found_from_the_manifest_path(self):
        (motif,) = re.findall(
            r"^const EXTENSION_SUFFIX_RE = /(.+)/;$",
            texte(EXTENSION / "lib/project-root.js"),
            re.M,
        )
        motif = re.compile(motif.replace("\\/", "/"))
        self.assertTrue(motif.search("/racine/" + CHEMIN))
        self.assertTrue(motif.search("/racine/" + CHEMIN + "/"))
        self.assertFalse(motif.search("/racine/" + CHEMIN + "_contract"))


if __name__ == "__main__":
    unittest.main()
