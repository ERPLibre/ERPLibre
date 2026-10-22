#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La fusion des manifests Google Repo : qui gagne, et qui entre.

Le script lit ses listes (conf/*.csv, private/default_git_manifest.csv) par
chemins relatifs au répertoire courant ; il est donc lancé comme en vrai, en
sous-processus, depuis une racine jetable.

Propriétés gardées :
- l'ordre des manifests est celui des listes : private/ est lu en dernier et
  l'emporte, quel que soit PYTHONHASHSEED (un ensemble le rendait aléatoire) ;
- le projet Dolibarr entre dans la fusion avec --with_dolibarr, ou d'office
  quand son checkout existe. Sorti de la fusion, il serait effacé par le
  prochain « repo sync », conf.php compris.

Et, dans une copie de conf/ et manifest/ sans mobile/ ni .repo/ :
- un .odoo-version terminé par un saut de ligne, comme l'écrit un éditeur,
  donne le même manifeste fusionné que sans, avec les modules de cette
  version d'Odoo et sans ligne d'erreur ;
- les jeux du Stream Deck n'entrent dans la fusion que si
  script/stream_deck/games existe, ou avec --with_streamdeck, comme le
  mobile.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script" / "git" / "git_merge_repo_manifest.py"
VERSION = "18.0"

# Commits inventés.
PIN_A = "a" * 40
PIN_B = "b" * 40


def manifest(revision, upstream="24.0"):
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="Dolibarr" fetch="https://github.com/Dolibarr/" />
    <project
        name="dolibarr.git"
        path="dolibarr/dolibarr"
        remote="Dolibarr"
        revision="{revision}"
        upstream="{upstream}"
        dest-branch="{upstream}"
        clone-depth="1"
        groups="dolibarr"
    />
</manifest>
"""


class Racine:
    """Une racine de dépôt jetable où lancer le script."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ("conf", "manifest", "private", ".repo/local_manifests"):
            (self.root / d).mkdir(parents=True)
        (self.root / "manifest/git_manifest_erplibre.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8" ?>\n<manifest />\n'
        )

    def ecrire(self, rel, texte):
        chemin = self.root / rel
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(texte)

    def liste(self, rel, *manifests):
        self.ecrire(rel, '"filepath"\n' + "".join(m + "\n" for m in manifests))

    def fusionner(self, *args, seed="0"):
        env = dict(os.environ, PYTHONPATH=str(RACINE), PYTHONHASHSEED=seed)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        sortie = self.root / "out.xml"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--output", str(sortie), *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        projets = ET.parse(sortie).getroot().findall("project")
        return {p.get("path"): p for p in projets}

    def close(self):
        self.tmp.cleanup()


class Banc(unittest.TestCase):
    def setUp(self):
        self.racine = Racine()
        self.addCleanup(self.racine.close)


class TestOrdreDeFusion(Banc):
    def test_the_last_listed_manifest_wins_whatever_the_hash_seed(self):
        r = self.racine
        r.ecrire("manifest/pin_a.xml", manifest(PIN_A))
        r.ecrire("manifest/pin_b.xml", manifest(PIN_B))
        r.liste(
            "private/default_git_manifest.csv",
            "manifest/pin_a.xml",
            "manifest/pin_b.xml",
        )
        for seed in ("0", "1", "2", "3", "4", "5"):
            with self.subTest(seed=seed):
                projets = r.fusionner(seed=seed)
                self.assertEqual(
                    projets["dolibarr/dolibarr"].get("revision"), PIN_B
                )


def chemins(manifeste):
    return sorted(
        p.get("path") for p in ET.parse(manifeste).getroot().iter("project")
    )


class LaVersionDOdoo(unittest.TestCase):
    def fusionner(self, contenu, jeux=False, options=()):
        with tempfile.TemporaryDirectory() as dossier:
            for nom in ("conf", "manifest"):
                shutil.copytree(RACINE / nom, Path(dossier, nom))
            if contenu is not None:
                Path(dossier, ".odoo-version").write_text(contenu)
            if jeux:
                Path(dossier, "script/stream_deck/games").mkdir(parents=True)
            sortie = os.path.join(dossier, "fusion.xml")
            fini = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", sortie, *options],
                cwd=dossier,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(0, fini.returncode, fini.stderr)
            return fini.stdout, chemins(sortie)

    def test_a_trailing_newline_changes_nothing(self):
        attendus = chemins(RACINE / f"manifest/git_manifest_odoo{VERSION}.xml")
        sans_saut, projets = self.fusionner(VERSION)
        avec_saut, projets_avec_saut = self.fusionner(VERSION + "\n")
        self.assertNotIn("ERROR", avec_saut)
        self.assertNotIn("ERROR", sans_saut)
        self.assertEqual(projets, projets_avec_saut)
        self.assertTrue(set(attendus) <= set(projets_avec_saut))


class LesJeuxDuStreamDeck(unittest.TestCase):
    JEUX = "script/stream_deck/games"
    fusionner = LaVersionDOdoo.fusionner

    def test_they_come_only_with_their_directory_or_the_option(self):
        for contenu, jeux, options, attendu in (
            (None, False, (), False),
            (VERSION, False, (), False),
            (None, True, (), True),
            (VERSION, True, (), True),
            (None, False, ("--with_streamdeck",), True),
        ):
            with self.subTest(odoo=contenu, jeux=jeux, options=options):
                _sortie, projets = self.fusionner(contenu, jeux, options)
                self.assertEqual(attendu, self.JEUX in projets)


if __name__ == "__main__":
    unittest.main()
