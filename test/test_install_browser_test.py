#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'il faut aux tests navigateur d'Odoo pour tourner au lieu de sauter.

Un tour, un test hoot, tout HttpCase qui pilote un navigateur lève SkipTest
dans deux cas : aucun Chrome ni Chromium dans le PATH, ou websocket-client
absent du venv. La passe reste verte dans les deux, d'où ces gardes :

- install_browser_test.sh choisit, par distribution, un paquet que les tests
  savent piloter. Sur Ubuntu, « chromium-browser » mène au snap, dont le /tmp
  privé cache à Odoo le port de débogage : le script prend le .deb de Google,
  et refuse là où il n'existe pas plutôt que de poser le snap. Linux Mint
  bloque snapd et publie son propre « chromium », que le script prend comme
  sur Debian ;
- il cherche le navigateur sous les noms et dans l'ordre d'Odoo, et ne
  réinstalle rien quand un nom répond, sauf un Chromium snap, qui ne compte
  pas comme présent ;
- il reste hors de « make install_os », que l'installation de production
  appelle aussi ;
- websocket-client est une dépendance PRINCIPALE du pyproject d'Odoo 18, et
  figure dans le requirements d'ERPLibre que relit poetry_update.py, faute de
  quoi la régénération suivante l'effacerait. Une table « [poetry.group...] »
  sans le préfixe « tool. » n'est lue par personne : Poetry l'ignore sans un
  mot.

Le script tourne en --dry-run, PATH réduit à un répertoire vide :
/etc/os-release et uname y sont remplacés par EL_OS_RELEASE, EL_UNAME_S et
EL_UNAME_M, et seules des commandes internes de bash s'exécutent.
"""

import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/install/install_browser_test.sh"
AIGUILLAGE = RACINE / "script/install/install_dev.sh"
MAKEFILE = RACINE / "conf/make.installation.Makefile"
ODOO18_COMMON = RACINE / "odoo18.0/odoo/odoo/tests/common.py"
PYPROJECT_18 = RACINE / "requirement/pyproject.odoo18.0_python3.12.10.toml"
REQUIREMENTS_18 = (
    RACINE / "requirement/requirements.odoo18.0_python3.12.10.txt"
)


def _lancer(
    os_release="",
    uname_s="Linux",
    uname_m="x86_64",
    binaires=(),
    snap=(),
    scripts=None,
):
    """Le script en --dry-run, dans un répertoire et un PATH neufs.

    :param os_release: contenu du faux /etc/os-release
    :param binaires: noms posés dans le PATH, comme s'ils étaient installés
    :param snap: noms posés dans un faux <tmp>/snap/bin, placé en tête du PATH
    :param scripts: {nom: contenu} de scripts posés dans le PATH
    :return: (code de retour, sortie standard et d'erreur réunies)
    """
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp, "bin")
        bin_dir.mkdir()
        snap_dir = Path(tmp, "snap", "bin")
        snap_dir.mkdir(parents=True)
        contenus = {Path(bin_dir, nom): "#!/bin/sh\n" for nom in binaires}
        contenus.update(
            {Path(snap_dir, nom): "#!/bin/sh\n" for nom in snap}
        )
        contenus.update(
            {Path(bin_dir, nom): texte for nom, texte in (scripts or {}).items()}
        )
        for chemin, texte in contenus.items():
            chemin.write_text(texte, encoding="utf-8")
            chemin.chmod(0o755)
        fichier = Path(tmp, "os-release")
        fichier.write_text(os_release, encoding="utf-8")
        env = {
            "PATH": f"{snap_dir}:{bin_dir}",
            "EL_OS_RELEASE": str(fichier),
            "EL_UNAME_S": uname_s,
            "EL_UNAME_M": uname_m,
        }
        res = subprocess.run(
            ["/bin/bash", str(SCRIPT), "--dry-run"],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    return res.returncode, res.stdout + res.stderr


class LeChoixParDistribution(unittest.TestCase):
    def assertInstalle(self, os_release, attendu):
        code, sortie = _lancer(os_release)
        self.assertEqual(code, 0, sortie)
        self.assertIn(attendu, sortie)

    def test_debian_and_mint_take_their_own_chromium(self):
        """Linux Mint bloque snapd : son « chromium » est un .deb."""
        for distro in ("debian", "linuxmint"):
            with self.subTest(distro=distro):
                code, sortie = _lancer(f"ID={distro}\n")
                self.assertEqual(code, 0, sortie)
                self.assertIn("install -y chromium", sortie)
                self.assertNotIn("google-chrome", sortie)
                self.assertNotIn("wget", sortie)

    def test_arch(self):
        self.assertInstalle(
            "ID=arch\n", "pacman -S --needed --noconfirm chromium"
        )

    def test_fedora(self):
        self.assertInstalle("ID=fedora\n", "dnf install -y chromium")

    def test_the_rhel_family_asks_for_epel_first(self):
        code, sortie = _lancer('ID=rocky\nID_LIKE="rhel centos fedora"\n')
        self.assertEqual(code, 0, sortie)
        self.assertLess(
            sortie.index("install -y epel-release"),
            sortie.index("install -y chromium"),
        )

    def test_opensuse(self):
        self.assertInstalle(
            'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n',
            "zypper --non-interactive install chromium",
        )

    def test_macos_takes_a_bundle_odoo_looks_for(self):
        code, sortie = _lancer(uname_s="Darwin", uname_m="arm64")
        self.assertEqual(code, 0, sortie)
        self.assertIn("brew install --cask google-chrome", sortie)


class Ubuntu(unittest.TestCase):
    """Le chromium d'apt y est un snap : jamais demandé."""

    def assertDebDeGoogle(self, sortie):
        self.assertIn("google-chrome-stable", sortie)
        self.assertIn("wget", sortie)
        self.assertIn("install -y", sortie)
        self.assertNotIn("install -y chromium", sortie)

    def test_amd64_installs_the_google_deb(self):
        code, sortie = _lancer("ID=ubuntu\n")
        self.assertEqual(code, 0, sortie)
        self.assertDebDeGoogle(sortie)
        self.assertNotIn("chromium-browser", sortie)

    def test_a_snap_chromium_does_not_count_as_installed(self):
        code, sortie = _lancer(
            "ID=ubuntu\n", snap=["chromium", "chromium-browser"]
        )
        self.assertEqual(code, 0, sortie)
        self.assertNotIn("deja present", sortie)
        self.assertIn("snap ecarte", sortie)
        self.assertDebDeGoogle(sortie)

    def test_a_wrapper_script_of_the_snap_does_not_count(self):
        """Le « chromium-browser » de transition d'Ubuntu est un script qui
        lance le snap."""
        wrapper = '#!/bin/sh\nexec /snap/bin/chromium "$@"\n'
        code, sortie = _lancer(
            "ID=ubuntu\n", scripts={"chromium-browser": wrapper}
        )
        self.assertEqual(code, 0, sortie)
        self.assertNotIn("deja present", sortie)
        self.assertDebDeGoogle(sortie)

    def test_a_browser_after_the_snap_is_kept(self):
        code, sortie = _lancer(
            "ID=ubuntu\n", binaires=["google-chrome-stable"], snap=["chromium"]
        )
        self.assertEqual(code, 0, sortie)
        self.assertIn("deja present", sortie)
        self.assertIn("google-chrome-stable", sortie)
        self.assertNotIn("wget", sortie)

    def test_without_a_deb_it_refuses_instead_of_the_snap(self):
        code, sortie = _lancer("ID=ubuntu\n", uname_m="aarch64")
        self.assertEqual(code, 1, sortie)
        self.assertNotIn("apt-get", sortie)
        self.assertNotIn("wget", sortie)


class CeQuiNePosePasDePaquet(unittest.TestCase):
    def test_nixos_is_left_to_its_declaration(self):
        code, sortie = _lancer("ID=nixos\n")
        self.assertEqual(code, 1, sortie)
        self.assertIn("environment.systemPackages", sortie)
        for commande in ("nix-env", "nix profile", "apt-get", "dnf"):
            self.assertNotIn(commande, sortie)

    def test_an_unknown_distribution_says_so(self):
        code, sortie = _lancer("ID=distro_inventee\n")
        self.assertEqual(code, 1, sortie)
        self.assertIn("distro_inventee", sortie)

    def test_an_unknown_option_is_refused(self):
        res = subprocess.run(
            ["/bin/bash", str(SCRIPT), "--option-inventee"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(res.returncode, 2)


class LaRechercheDuNavigateur(unittest.TestCase):
    def test_a_present_browser_installs_nothing(self):
        for nom in (
            "google-chrome",
            "chromium",
            "chromium-browser",
            "google-chrome-stable",
        ):
            with self.subTest(nom=nom):
                code, sortie = _lancer("ID=debian\n", binaires=[nom])
                self.assertEqual(code, 0, sortie)
                self.assertIn(nom, sortie)
                self.assertNotIn("apt-get", sortie)

    def test_names_and_order_are_odoo_s(self):
        """Un nom qu'Odoo ne cherche pas ferait croire à un navigateur
        présent ; un nom manquant ferait réinstaller pour rien."""
        if not ODOO18_COMMON.is_file():
            self.skipTest("odoo18.0 non cloné")
        odoo = re.search(
            r"for bin_ in (\[[^\]]+\])", ODOO18_COMMON.read_text("utf-8")
        )
        self.assertIsNotNone(odoo)
        attendu = re.findall(r"'([^']+)'", odoo.group(1))
        script = re.search(
            r"for bin_ in (google-chrome[^;]*);",
            SCRIPT.read_text("utf-8"),
        )
        self.assertIsNotNone(script)
        self.assertEqual(script.group(1).split(), attendu)


class HorsDeLInstallationDuSysteme(unittest.TestCase):
    def test_install_os_does_not_call_it(self):
        self.assertNotIn("install_browser_test", AIGUILLAGE.read_text("utf-8"))

    def test_its_make_target_exists(self):
        src = MAKEFILE.read_text("utf-8")
        self.assertIn(".PHONY: install_browser_test", src)
        self.assertIn("./script/install/install_browser_test.sh", src)


class WebsocketClientDOdoo18(unittest.TestCase):
    def setUp(self):
        with PYPROJECT_18.open("rb") as f:
            self.pyproject = tomllib.load(f)

    def test_it_is_a_main_dependency(self):
        deps = self.pyproject["tool"]["poetry"]["dependencies"]
        self.assertIn("websocket-client", deps)

    def test_the_requirements_poetry_update_reads_name_it(self):
        lignes = [
            ligne.split("#")[0].strip()
            for ligne in REQUIREMENTS_18.read_text("utf-8").splitlines()
        ]
        self.assertTrue(
            any(re.match(r"websocket[-_]client\b", x) for x in lignes)
        )

    def test_no_pyproject_has_a_table_poetry_ignores(self):
        for chemin in sorted(RACINE.glob("requirement/pyproject.*.toml")):
            with self.subTest(fichier=chemin.name):
                with chemin.open("rb") as f:
                    self.assertNotIn("poetry", tomllib.load(f))


if __name__ == "__main__":
    unittest.main()
