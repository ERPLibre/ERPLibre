#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les conteneurs reposent-ils tous sur la même base ?

La base est « python:<version>-slim-<nom de version Debian> » : le Python vient
de l'image officielle, jamais de Debian. Changer de nom de version ne change
donc pas l'interpréteur, et rien n'obligeait les vieux Odoo à rester sur
bullseye — dont le dépôt de sécurité est aujourd'hui démantelé.

Ce que ces tests gardent :

- une seule base, pour toutes les versions d'Odoo. L'aiguillage précédent
  portait une branche « buster » INATTEIGNABLE : sa condition était la
  négation de celle qui la précédait ;
- le build de wkhtmltopdf suit la version. Celui de bullseye réclame
  libssl1.1, absente de bookworm : un .deb mal apparié s'installe puis ne se
  lance pas, et l'impression PDF échoue à l'exécution, pas à la construction ;
- l'empreinte accompagne l'URL. Le Dockerfile la vérifie avant d'installer,
  et une URL changée sans son empreinte ferait échouer la construction.
"""

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = (RACINE / "script/docker/docker_build.sh").read_text(encoding="utf-8")
DOCKERFILE = (RACINE / "docker/Dockerfile.base").read_text(encoding="utf-8")


class TestUneSeuleBase(unittest.TestCase):
    def test_aucune_version_debian_anterieure(self):
        for ancienne in ("bullseye", "buster", "stretch"):
            with self.subTest(version=ancienne):
                self.assertNotIn(f"DEBIAN_NAME={ancienne}", SCRIPT)

    def test_la_base_est_bookworm(self):
        self.assertIn("--build-arg DEBIAN_NAME=bookworm", SCRIPT)

    def test_elle_est_posee_une_seule_fois(self):
        """Plusieurs branches redonneraient un aiguillage à entretenir."""
        self.assertEqual(1, SCRIPT.count("--build-arg DEBIAN_NAME="))

    def test_plus_aucun_drapeau_de_version(self):
        self.assertNotIn("IS_DEBIAN_", SCRIPT)


class TestWkhtmltopdf(unittest.TestCase):
    def test_le_build_suit_la_version_de_la_base(self):
        """Le .deb de bullseye réclame libssl1.1, absente de bookworm."""
        urls = re.findall(r"URL_WKHTMLTOX=(\S+)", SCRIPT)
        self.assertTrue(urls)
        for url in urls:
            with self.subTest(url=url):
                self.assertIn("bookworm", url)

    def test_l_empreinte_accompagne_l_url(self):
        self.assertEqual(
            SCRIPT.count("URL_WKHTMLTOX="),
            SCRIPT.count("SHA1SUM_WKTHMLTOX="),
        )

    def test_le_dockerfile_verifie_l_empreinte_avant_d_installer(self):
        """Sans ce contrôle, une page d'erreur HTML s'installerait comme
        un paquet."""
        verif = DOCKERFILE.index("sha1sum -c -")
        pose = DOCKERFILE.index(
            "apt-get install -y --no-install-recommends ./wkhtmltox.deb"
        )
        self.assertLess(verif, pose)

    def test_le_defaut_du_dockerfile_s_accorde_au_script(self):
        """Une construction lancée sans argument ne doit pas changer de base."""
        self.assertIn("ARG DEBIAN_NAME=bookworm", DOCKERFILE)
        attendue = re.search(r"URL_WKHTMLTOX=(\S+)", SCRIPT).group(1)
        self.assertIn(attendue, DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
