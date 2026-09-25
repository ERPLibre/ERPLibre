#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'outillage que l'image installe couvre-t-il ce qu'elle lance ?

Le venv d'outillage de l'image prend le Python de l'IMAGE, qui est celui
d'Odoo — 3.7.17 pour Odoo 12, 3.8.20 pour Odoo 14. Le fichier de requis
complet vise le venv de l'hôte, en 3.14, et porte des bornes qu'aucun de ces
deux Python ne satisfait : « textual>=8,<9 » exige 3.9. Aucune image d'Odoo 12
à 15 ne pouvait donc se construire.

Ce que ces tests gardent :

- l'image installe SON fichier de requis, jamais celui de l'hôte ;
- tout point d'entrée Python que l'image lance est nommé dans le garde du
  Dockerfile. Un script ajouté sans l'y déclarer ne serait vu qu'au premier
  build, très loin, sur un ModuleNotFoundError ;
- ce que l'image installe est un sous-ensemble de ce que l'hôte installe. Un
  paquet qui n'existerait que pour l'image dériverait sans que rien ne le
  dise ;
- le garde ne compile plus tout script/. L'arbre entier alarmait sur des
  fichiers que l'image n'ouvre jamais, et concluait à tort qu'il fallait une
  version d'Odoo plus récente.
"""

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DOCKERFILE = (RACINE / "docker/Dockerfile.prod.pkg").read_text(
    encoding="utf-8"
)
MANIFEST_SH = (
    RACINE / "script/manifest/update_manifest_local_dev.sh"
).read_text(encoding="utf-8")
REQUIS_IMAGE = RACINE / "requirement/erplibre_require-ments-docker.txt"
REQUIS_HOTE = RACINE / "requirement/erplibre_require-ments.txt"


def _paquets(chemin):
    """Les noms de paquets d'un fichier de requis, en minuscules."""
    noms = set()
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.split("#")[0].strip()
        if not ligne or ligne.startswith("-") or ligne.startswith("git+"):
            continue
        noms.add(re.split(r"[<>=!;\[ ]", ligne)[0].strip().lower())
    return noms


def _modules_lances():
    """Les modules Python que l'image lance, en notation pointée.

    Deux sources : le Dockerfile lui-même, et le script de manifeste qu'il
    appelle — l'indirection par le shell est justement ce qu'un lecteur
    oublie.
    """
    modules = set()
    for texte in (DOCKERFILE, MANIFEST_SH):
        for chemin in re.findall(r"\.?/?(script/[\w/]+\.py)", texte):
            modules.add(chemin[: -len(".py")].replace("/", "."))
    return modules


class TestFichierDeRequis(unittest.TestCase):
    def test_l_image_installe_le_sien(self):
        self.assertTrue(REQUIS_IMAGE.exists())
        self.assertIn(
            "requirement/erplibre_require-ments-docker.txt", DOCKERFILE
        )

    def test_elle_n_installe_pas_celui_de_l_hote(self):
        """Il porte des bornes inatteignables sous 3.9."""
        self.assertNotIn(
            "pip3 install -r requirement/erplibre_require-ments.txt",
            DOCKERFILE,
        )

    def test_il_reste_un_sous_ensemble_de_celui_de_l_hote(self):
        manquants = _paquets(REQUIS_IMAGE) - _paquets(REQUIS_HOTE)
        self.assertEqual(set(), manquants)

    def test_il_reste_court(self):
        """C'est une fermeture d'imports, pas un second inventaire."""
        self.assertLessEqual(len(_paquets(REQUIS_IMAGE)), 12)


class TestGarde(unittest.TestCase):
    def test_il_nomme_tout_ce_que_l_image_lance(self):
        garde = re.search(r'python -c "import ([^"]+)"', DOCKERFILE)
        self.assertIsNotNone(garde, DOCKERFILE)
        nommes = {m.strip() for m in garde.group(1).split(",")}
        self.assertEqual(set(), _modules_lances() - nommes)

    def test_il_ne_compile_plus_tout_l_arbre(self):
        """« compileall script/ » alarmait sur des fichiers que l'image
        n'ouvre jamais — un « with » parenthésé, réservé à 3.9, dans un
        utilitaire de migration de bases."""
        self.assertNotIn("compileall -q script/", DOCKERFILE)

    def test_il_precede_ce_qui_en_depend(self):
        """Échouer ici coûte une couche ; échouer au repo sync en coûte
        beaucoup plus."""
        self.assertLess(
            DOCKERFILE.index('python -c "import script'),
            DOCKERFILE.index("update_manifest_local_dev.sh"),
        )


if __name__ == "__main__":
    unittest.main()
