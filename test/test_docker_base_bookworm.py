#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les conteneurs reposent-ils sur la bonne base ?

La base est « python:<version>-slim-<nom de version Debian> » : le Python vient
de l'image officielle, jamais de Debian. Changer de nom de version ne change
donc pas l'interpréteur, et rien n'obligeait les vieux Odoo à rester sur
bullseye — dont le dépôt de sécurité est aujourd'hui démantelé.

Ce que ces tests gardent :

- bookworm pour tout Python 3, et buster pour Python 2 SEUL : c'est la seule
  version de Debian qui porte une image Python 2.7. L'aiguillage se fait sur
  la version de Python, jamais sur celle d'Odoo, et chaque branche pose sa
  base une seule fois. Un aiguillage précédent portait une branche « buster »
  INATTEIGNABLE : sa condition était la négation de celle qui la précédait ;
- le build de wkhtmltopdf suit la base de SA branche. Celui de bullseye
  réclame libssl1.1, absente de bookworm : un .deb mal apparié s'installe puis
  ne se lance pas, et l'impression PDF échoue à l'exécution, pas à la
  construction ;
- l'empreinte accompagne l'URL. Le Dockerfile la vérifie avant d'installer,
  et une URL changée sans son empreinte ferait échouer la construction.
"""

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = (RACINE / "script/docker/docker_build.sh").read_text(encoding="utf-8")
DOCKERFILE = (RACINE / "docker/Dockerfile.base").read_text(encoding="utf-8")


def _branches():
    """Les lignes qui posent une base, chacune avec sa base."""
    return re.findall(r"^\s*ARGS=.*--build-arg DEBIAN_NAME=(\w+).*$", SCRIPT, re.M)


class TestBaseParVersionDePython(unittest.TestCase):
    def test_aucune_autre_version_debian(self):
        for ancienne in ("bullseye", "stretch"):
            with self.subTest(version=ancienne):
                self.assertNotIn(f"DEBIAN_NAME={ancienne}", SCRIPT)

    def test_bookworm_et_buster_une_fois_chacune(self):
        """Plus de branches redonneraient un aiguillage à entretenir."""
        self.assertEqual(["buster", "bookworm"], _branches())

    def test_buster_est_reserve_a_python_2(self):
        """La branche buster est celle de la condition Python 2, et c'est la
        version de PYTHON qui aiguille : Odoo 10 n'est pas le critère."""
        condition = SCRIPT.index('if [[ "${PYTHON_VERSION}" == 2.* ]]; then')
        buster = SCRIPT.index("--build-arg DEBIAN_NAME=buster")
        sinon = SCRIPT.index("\nelse\n", condition)
        bookworm = SCRIPT.index("--build-arg DEBIAN_NAME=bookworm")
        self.assertLess(condition, buster)
        self.assertLess(buster, sinon)
        self.assertLess(sinon, bookworm)

    def test_plus_aucun_drapeau_de_version(self):
        self.assertNotIn("IS_DEBIAN_", SCRIPT)


class TestWkhtmltopdf(unittest.TestCase):
    def test_le_build_suit_la_base_de_sa_branche(self):
        """Le .deb de bullseye réclame libssl1.1, absente de bookworm."""
        lignes = re.findall(
            r"^\s*ARGS=.*DEBIAN_NAME=(\w+).*URL_WKHTMLTOX=(\S+)", SCRIPT, re.M
        )
        self.assertEqual(2, len(lignes))
        for base, url in lignes:
            with self.subTest(base=base):
                self.assertIn(f".{base}_amd64.deb", url)

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
        attendue = re.search(
            r"DEBIAN_NAME=bookworm --build-arg URL_WKHTMLTOX=(\S+)", SCRIPT
        ).group(1)
        self.assertIn(attendue, DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
