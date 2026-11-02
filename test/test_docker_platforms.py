#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les architectures d'une construction : « docker_build.sh --platform ».

Une architecture étrangère se construit sous émulation QEMU. Sans elle, la
première commande RUN meurt sur « exec format error », loin de sa cause ; et
une architecture que l'image Python ne publie pas meurt au FROM. Le script
refuse les deux avant de rien réécrire ni construire.

Ce que ces tests gardent :

- une architecture inconnue, non publiée ou non émulée est refusée, et le
  refus nomme la commande qui installe l'émulation. Le script est lancé pour
  de vrai devant un faux « docker » ; les refus précèdent la réécriture de
  docker-compose.yml, que le test vérifie intacte ;
- l'architecture de l'hôte garde l'étiquette sans suffixe, celle que lance
  docker-compose.yml ; pousser suffixe chaque architecture puis réunit les
  étiquettes dans un manifeste ;
- docker compose n'est relancé que si l'architecture de l'hôte a été bâtie.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_docker_base_debian import RACINE, TEXTE, lancer  # noqa: E402

COMPOSE = RACINE / "docker-compose.yml"
EMULEES = "linux/amd64, linux/amd64/v2, linux/arm64, linux/s390x"


class TestRefus(unittest.TestCase):
    def setUp(self):
        self.compose = COMPOSE.read_bytes()

    def tearDown(self):
        self.assertEqual(self.compose, COMPOSE.read_bytes())

    def test_architecture_inconnue(self):
        sortie, _ = lancer("--odoo_18", "--platform=riscv64", emulees=EMULEES)
        self.assertNotEqual(0, sortie.returncode)
        self.assertIn("architecture inconnue : riscv64", sortie.stdout)

    def test_architecture_que_l_image_python_ne_publie_pas(self):
        sortie, _ = lancer(
            "--odoo_18",
            "--platform=s390x",
            publiees="amd64 arm64/v8",
            emulees=EMULEES,
        )
        self.assertNotEqual(0, sortie.returncode)
        self.assertIn("ne publie pas s390x", sortie.stdout)

    def test_architecture_sans_emulation(self):
        sortie, _ = lancer(
            "--odoo_18", "--platform=amd64,arm64", emulees="linux/amd64"
        )
        self.assertNotEqual(0, sortie.returncode)
        self.assertIn("aucune émulation de linux/arm64", sortie.stdout)
        self.assertIn("install_container.sh --multiarch", sortie.stdout)

    def test_une_variante_ne_vaut_pas_l_architecture(self):
        """« linux/arm/v7 » n'émule pas arm64 : la comparaison est exacte."""
        sortie, _ = lancer(
            "--odoo_18", "--platform=arm64", emulees="linux/amd64, linux/arm/v7"
        )
        self.assertNotEqual(0, sortie.returncode)
        self.assertIn("aucune émulation de linux/arm64", sortie.stdout)

    def test_les_refus_precedent_toute_ecriture(self):
        self.assertLess(
            TEXTE.index("aucune émulation de linux/"),
            TEXTE.index("docker_update_version.py --version"),
        )


class TestEtiquettes(unittest.TestCase):
    def test_l_hote_garde_l_etiquette_sans_suffixe(self):
        boucle = TEXTE[TEXTE.index("for arch in ${PLATEFORMES}; do\n  suffixe") :]
        self.assertIn('suffixe="-${arch}"', boucle)
        self.assertIn(
            'if [ "${POUSSER}" == false ] && [ "${arch}" == "${ARCH_HOTE}" ]; then',
            boucle,
        )

    def test_la_prod_part_de_la_base_de_la_meme_architecture(self):
        self.assertIn(
            '--build-arg ERPLIBRE_IMAGE_NAME="${ERPLIBRE_VERSION}${suffixe}"',
            TEXTE,
        )

    def test_pousser_reunit_les_architectures_dans_un_manifeste(self):
        self.assertIn(
            'docker buildx imagetools create -t "${ERPLIBRE_DOCKER_PROD_VERSION}"'
            ' "${poussees_prod[@]}"',
            TEXTE,
        )

    def test_compose_seulement_si_l_hote_est_bati(self):
        fin = TEXTE[TEXTE.rindex("cd -") :]
        self.assertIn('if [ "${hote_bati}" == true ]; then', fin)
        self.assertLess(fin.index("hote_bati"), fin.index("docker compose up -d"))


if __name__ == "__main__":
    unittest.main()
