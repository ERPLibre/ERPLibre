#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sur quelle Debian repose chaque image, et que lui demande-t-elle ?

La base est « python:<version>-slim-<nom de version Debian> » : le Python vient
de l'image officielle, jamais de Debian. Le nom de version ne change que les
paquets du système : trixie pour Odoo 16 à 18, bookworm pour 12 à 15, faute
d'image Python 3.7 ou 3.8 sur trixie.

Ce que ces tests gardent :

- chaque version d'Odoo interroge l'image Python de SA Debian. Le script est
  lancé pour de vrai, devant un faux « docker » qui note ce qu'on lui demande ;
- wkhtmltopdf au Qt patché sur amd64 et arm64, rien ailleurs. Debian trixie a
  retiré le paquet, et le build bookworm sert sur les deux bases ;
- l'empreinte d'un .deb est vérifiée avant qu'apt ne l'installe ;
- le client PostgreSQL de pgdg n'est demandé que là où pgdg publie, et sa
  clé ne vaut que pour son dépôt ;
- les paquets demandés existent sur les deux bases : trixie a retiré
  libncursesw5-dev et libxslt-dev, que libncurses-dev et libxslt1-dev
  remplacent aussi sur bookworm.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/docker/docker_build.sh"
TEXTE = SCRIPT.read_text(encoding="utf-8")
DOCKERFILE = (RACINE / "docker/Dockerfile.base").read_text(encoding="utf-8")
CATALOGUE = RACINE / "conf/supported_version_erplibre.json"

FAUX_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "${FAUX_DOCKER_JOURNAL}"
case "$1 $2" in
  "buildx imagetools")
    echo "Name: $4"
    for p in ${FAUX_PUBLIEES}; do echo "  Platform:    linux/${p}"; done ;;
  "buildx inspect") echo "Platforms:        ${FAUX_EMULEES}" ;;
  "version --format") echo "${FAUX_ARCH}" ;;
esac
"""


def lancer(*args, publiees="amd64 arm64/v8 s390x", emulees="", arch="amd64"):
    """Lance docker_build.sh devant un faux « docker ». Rend la sortie et les
    commandes reçues par docker, une par ligne."""
    with tempfile.TemporaryDirectory() as dossier:
        faux = Path(dossier) / "docker"
        faux.write_text(FAUX_DOCKER, encoding="utf-8")
        faux.chmod(0o755)
        journal = Path(dossier) / "journal"
        journal.touch()
        env = dict(
            os.environ,
            PATH=f"{dossier}:{os.environ['PATH']}",
            FAUX_DOCKER_JOURNAL=str(journal),
            FAUX_PUBLIEES=publiees,
            FAUX_EMULEES=emulees,
            FAUX_ARCH=arch,
        )
        sortie = subprocess.run(
            [str(SCRIPT), *args],
            cwd=RACINE,
            env=env,
            capture_output=True,
            text=True,
        )
        return sortie, journal.read_text(encoding="utf-8").splitlines()


def _python_de(odoo):
    with CATALOGUE.open(encoding="utf-8") as fh:
        for cle in json.load(fh):
            if cle.startswith(f"odoo{odoo}_python"):
                return cle.split("_python")[1]
    raise KeyError(odoo)


def _paquets_apt():
    """Les paquets de la première installation apt du Dockerfile."""
    debut = DOCKERFILE.index("apt-get install -y --no-install-recommends \\")
    fin = DOCKERFILE.index('&& arch="', debut)
    lignes = DOCKERFILE[debut:fin].splitlines()[1:]
    return [ligne.strip(" \\") for ligne in lignes if ligne.strip(" \\")]


class TestDebianParVersion(unittest.TestCase):
    def test_chaque_version_interroge_l_image_python_de_sa_debian(self):
        for odoo, debian in (
            ("18", "trixie"),
            ("17", "trixie"),
            ("16", "trixie"),
            ("15", "bookworm"),
            ("12", "bookworm"),
        ):
            with self.subTest(odoo=odoo):
                sortie, appels = lancer(f"--odoo_{odoo}", "--print-platforms")
                self.assertEqual(0, sortie.returncode, sortie.stderr)
                image = f"python:{_python_de(odoo + '.0')}-slim-{debian}"
                self.assertIn(f"buildx imagetools inspect {image}", appels)

    def test_les_architectures_publiees_sans_leur_variante(self):
        sortie, _ = lancer("--odoo_18", "--print-platforms")
        self.assertEqual("amd64 arm64 s390x", sortie.stdout.strip())

    def test_aucune_version_debian_anterieure(self):
        for ancienne in ("bullseye", "buster", "stretch"):
            with self.subTest(version=ancienne):
                self.assertNotIn(f"DEBIAN_NAME={ancienne}", TEXTE)
                self.assertNotIn(f"DEBIAN_NAME={ancienne}", DOCKERFILE)

    def test_le_defaut_du_dockerfile_est_celui_d_odoo_18(self):
        """Une construction lancée sans argument prend la base d'Odoo 18."""
        self.assertIn("ARG DEBIAN_NAME=trixie", DOCKERFILE)


class TestWkhtmltopdf(unittest.TestCase):
    def test_un_build_patche_pour_amd64_et_arm64_seulement(self):
        table = DOCKERFILE[
            DOCKERFILE.index('case "${arch}" in') : DOCKERFILE.index("esac")
        ]
        empreintes = dict(re.findall(r"(\w+)\) wk_sha1=([0-9a-f]{40})", table))
        self.assertEqual({"amd64", "arm64"}, set(empreintes))
        self.assertIn('*) wk_sha1="" ;;', table)

    def test_le_build_bookworm_sert_sur_les_deux_bases(self):
        """Ni trixie ni s390x n'ont de build : le nom du .deb ne suit pas
        DEBIAN_NAME."""
        self.assertIn(
            "wkhtmltox_${WKHTMLTOX_VERSION}.bookworm_${arch}.deb", DOCKERFILE
        )

    def test_sans_build_l_image_le_dit(self):
        self.assertIn("aucun build pour ${arch}", DOCKERFILE)

    def test_l_empreinte_est_verifiee_avant_d_installer(self):
        """Sans ce contrôle, une page d'erreur HTML s'installerait comme
        un paquet."""
        verif = DOCKERFILE.index("sha1sum -c -")
        pose = DOCKERFILE.index(
            "apt-get install -y --no-install-recommends ./wkhtmltox.deb"
        )
        self.assertLess(verif, pose)

    def test_l_architecture_ne_depend_pas_de_buildkit(self):
        """Sans BuildKit, TARGETARCH est vide : amd64 perdrait wkhtmltopdf
        sans un mot."""
        self.assertIn(
            'arch="${TARGETARCH:-$(dpkg --print-architecture)}"', DOCKERFILE
        )

    def test_le_script_ne_choisit_plus_le_deb(self):
        self.assertNotIn("URL_WKHTMLTOX", TEXTE)
        self.assertNotIn("SHA1SUM_WKTHMLTOX", TEXTE)


class TestPostgresql(unittest.TestCase):
    def setUp(self):
        debut = DOCKERFILE.index("# Le client PostgreSQL 18")
        self.bloc = DOCKERFILE[debut : DOCKERFILE.index("# Install npm")]

    def test_pgdg_seulement_la_ou_il_publie(self):
        self.assertIn("amd64|arm64)", self.bloc)
        self.assertIn("client=postgresql-client-18", self.bloc)
        self.assertIn("*) client=postgresql-client ;;", self.bloc)

    def test_la_cle_ne_vaut_que_pour_son_depot(self):
        self.assertIn("[signed-by=/usr/share/keyrings/pgdg.asc]", self.bloc)
        self.assertNotIn("trusted.gpg.d", self.bloc)

    def test_le_depot_suit_la_debian_de_la_base(self):
        """Un ARG d'avant FROM n'existe plus après lui sans être redéclaré :
        le dépôt deviendrait « -pgdg »."""
        self.assertIn("${DEBIAN_NAME}-pgdg main", self.bloc)
        redeclare = DOCKERFILE.index("\nARG DEBIAN_NAME\n")
        self.assertLess(DOCKERFILE.index("FROM "), redeclare)
        self.assertLess(redeclare, DOCKERFILE.index("# Le client PostgreSQL 18"))


class TestCompilationSansWheel(unittest.TestCase):
    """Hors amd64 et arm64, PyPI ne publie pas de wheel pour les dépendances
    natives du lock : Poetry les compile dans la construction."""

    def setUp(self):
        debut = DOCKERFILE.index("# PyPI publie des wheels amd64 et arm64")
        self.bloc = DOCKERFILE[debut : DOCKERFILE.index("# Install npm")]

    def test_les_outils_ne_vont_qu_aux_architectures_sans_wheel(self):
        self.assertIn("amd64|arm64) ;;", self.bloc)
        for paquet in ("gfortran", "libopenblas-dev", "libtbb-dev"):
            with self.subTest(paquet=paquet):
                self.assertIn(f"        {paquet} \\", self.bloc)

    def test_rust_vient_de_rustup_verifie(self):
        """Le rustc de Debian est trop ancien pour orjson."""
        self.assertNotIn("        rustc \\", self.bloc)
        verif = self.bloc.index("sha256sum -c -")
        self.assertLess(verif, self.bloc.index("/tmp/rustup-init -y"))
        self.assertRegex(self.bloc, r"s390x\) rustup_sha256=[0-9a-f]{64} ;;")

    def test_grpcio_compile_sur_l_openssl_du_systeme(self):
        """Le BoringSSL embarqué dans grpcio refuse s390x à la compilation."""
        self.assertIn("GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1", self.bloc)

    def test_pynacl_garde_sa_libsodium(self):
        """La libsodium de Debian trixie n'a pas les fonctions aegis que
        pynacl appelle : sa compilation échoue sur elle."""
        self.assertNotIn("SODIUM_INSTALL=system", DOCKERFILE)


class TestPaquets(unittest.TestCase):
    def test_aucun_paquet_retire_de_trixie(self):
        paquets = _paquets_apt()
        for retire in ("libncursesw5-dev", "libxslt-dev", "gdebi-core"):
            with self.subTest(paquet=retire):
                self.assertNotIn(retire, paquets)
        self.assertIn("libncurses-dev", paquets)
        self.assertIn("libxslt1-dev", paquets)

    def test_vim_n_y_est_pas(self):
        """Il dépend à la version près de vim-common, commun à toutes les
        architectures : un correctif publié avant le binaire d'une
        architecture arrête sa construction."""
        self.assertNotIn("vim", _paquets_apt())

    def test_aucun_doublon(self):
        paquets = _paquets_apt()
        self.assertEqual(len(paquets), len(set(paquets)), paquets)


if __name__ == "__main__":
    unittest.main()
