#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installation des dépendances ERPLibre sur NixOS.

Les quatre autres scripts de distribution POSENT des paquets ; celui-ci n'en
pose aucun. Il dépose une déclaration et demande au système de s'y conformer,
parce que c'est la seule façon dont une dépendance dure là-bas : ce qui est
installé à la main vit hors de la configuration et disparaît à la
reconstruction suivante.

Ce que ces tests gardent :

- l'aiguillage reconnaît « nixos ». Sans cette branche, install_dev.sh tombe
  dans son « else », appelle le script Debian, et celui-ci sort en erreur dès
  la détection du système — avant même d'essayer un apt-get qui n'existe pas ;
- les DEUX options qui portent tout le reste sont déclarées. Sans envfs, /bin
  et /usr/bin restent vides : le Makefile force « SHELL := /bin/bash » et
  toute cible échoue avant sa première ligne, tandis que
  lib_python_provider.sh ne cherche l'interpréteur du système qu'en
  /usr/bin/pythonX.Y. Sans nix-ld, aucune roue manylinux ni aucun binaire
  téléchargé ne s'exécute ;
- la version de Python déclarée répond à celle que le dépôt demande ;
- le compte du rôle PostgreSQL est substitué, jamais écrit en dur.
"""

import re
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
MODULE = RACINE / "conf/nixos/erplibre.nix"
SCRIPT = RACINE / "script/install/install_nixos_dependency.sh"
AIGUILLAGE = RACINE / "script/install/install_dev.sh"


class LAiguillage(unittest.TestCase):
    def setUp(self):
        self.src = AIGUILLAGE.read_text(encoding="utf-8")

    def test_nixos_has_its_own_branch(self):
        self.assertIn('"${ID}" == "nixos"', self.src)
        self.assertIn("install_nixos_dependency.sh", self.src)

    def test_it_is_decided_before_the_debian_fallback(self):
        """Le « else » de fin appelle le script Debian : une branche placée
        après lui ne serait jamais atteinte."""
        self.assertLess(
            self.src.index('"${ID}" == "nixos"'),
            self.src.rindex("install_debian_dependency.sh"),
        )

    def test_the_supported_list_names_it(self):
        """Le message de repli énumère les systèmes supportés : en omettre un
        qu'on supporte fait douter de celui qu'on lit."""
        ligne = [x for x in self.src.splitlines() if "not supported" in x][-1]
        self.assertIn("NixOS", ligne)


class LeScript(unittest.TestCase):
    def setUp(self):
        self.src = SCRIPT.read_text(encoding="utf-8")

    def test_it_is_valid_shell(self):
        fini = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)

    def test_it_is_executable(self):
        """git saute silencieusement un script sans bit d'exécution, et
        install_dev.sh l'appelle directement."""
        import os

        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_it_refuses_another_system(self):
        """Déposer un module NixOS ailleurs ne ferait rien de bon, et le
        « nixos-rebuild » qui suit n'existerait pas."""
        self.assertIn("ID=nixos", self.src)

    def test_the_import_is_added_once(self):
        """Relancé, le script ne doit pas empiler les imports : la
        configuration ne compilerait plus."""
        self.assertIn('grep -q "erplibre.nix"', self.src)

    def test_it_says_when_there_is_no_imports_block(self):
        """Une configuration sans « imports = [ » laisserait le module mort :
        NixOS ne lit que ce que la configuration importe."""
        self.assertIn("imports = [", self.src)
        self.assertIn("exit 1", self.src)

    def test_the_python_version_comes_from_the_repository(self):
        """Une version écrite ici dériverait de .python-odoo-version au
        premier changement."""
        self.assertIn(".python-odoo-version", self.src)

    def test_it_verifies_what_the_module_promised(self):
        """Sans /bin/bash, la moindre cible make échoue avant sa première
        ligne : le dire ici plutôt qu'une heure plus tard, ailleurs."""
        for chemin in ("/bin/bash", "/usr/bin/env"):
            self.assertIn(chemin, self.src)


class LeModule(unittest.TestCase):
    def setUp(self):
        self.src = MODULE.read_text(encoding="utf-8")

    def test_the_two_hinges_are_declared(self):
        """envfs pour /bin et /usr/bin, nix-ld pour les binaires étrangers :
        sans l'une des deux, rien de ce dépôt ne fonctionne."""
        self.assertIn("services.envfs.enable = true;", self.src)
        self.assertIn("programs.nix-ld.enable = true;", self.src)

    def test_what_compiles_here_is_also_given_to_the_loader(self):
        """Un module compilé sur place n'a pas de RPATH : son « .so » ne
        retrouve sa bibliothèque à l'IMPORT que par LD_LIBRARY_PATH, donc par
        ce que nix-ld déclare. Déclarer l'en-tête sans la bibliothèque fait
        réussir la compilation et échouer l'import."""
        entetes = ("openldap", "cups", "libmysqlclient")
        loader = self.src.split("programs.nix-ld.libraries")[1].split("];")[0]
        for lib in entetes:
            with self.subTest(lib=lib):
                self.assertIn(lib, loader)

    def test_pg_config_is_its_own_derivation(self):
        """Il n'est ni dans postgresql ni dans sa sortie « .dev », et
        psycopg2 s'arrête sur « pg_config executable not found »."""
        self.assertIn("postgresql.pg_config", self.src)

    def test_the_dynamic_loader_gets_what_the_wheels_ask(self):
        """Une roue manylinux qui ne trouve pas sa bibliothèque échoue à
        l'IMPORT, pas à l'installation : bien plus tard, et sans rapport
        apparent avec pip."""
        for lib in ("libpq", "libxml2", "libxslt", "openssl", "zlib"):
            with self.subTest(lib=lib):
                self.assertIn(lib, self.src)

    def test_the_python_matches_what_the_repository_wants(self):
        voulu = (RACINE / ".python-odoo-version").read_text().strip()
        majeur, mineur = voulu.split(".")[:2]
        self.assertIn(f"python{majeur}{mineur}", self.src)

    def test_the_database_role_is_substituted(self):
        """Le nom du compte varie d'un déploiement à l'autre ; l'écrire en dur
        donnerait un rôle qui ne correspond à personne."""
        self.assertIn("@EL_USER@", self.src)
        self.assertIn("ensureClauses.superuser = true;", self.src)

    def test_the_placeholder_is_the_one_the_script_replaces(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marque in set(re.findall(r"@[A-Z_]+@", self.src)):
            with self.subTest(marque=marque):
                self.assertIn(marque, script)

    def test_what_npm_cannot_install_is_declared_instead(self):
        """Les quatre autres scripts posent lessc et rtlcss par « npm install
        -g ». Ici le préfixe npm EST le store, en lecture seule : le geste
        échoue. nixpkgs porte les deux, et une déclaration ne s'installe
        pas — elle tient."""
        self.assertIn("nodePackages.less", self.src)
        self.assertIn("nodePackages.rtlcss", self.src)
        self.assertNotIn("npm install -g", self.src)

    def test_the_pager_and_the_less_compiler_are_two_things(self):
        """« less » le paginateur et « less » le compilateur LESS portent le
        même nom et ne se remplacent pas : les deux sont déclarés."""
        lignes = [x.strip() for x in self.src.splitlines()]
        self.assertIn("less", lignes)
        self.assertIn("nodePackages.less", lignes)

    def test_postgis_is_a_server_plugin_not_a_package(self):
        """Déclarée hors du serveur, l'extension ne serait pas chargeable par
        « CREATE EXTENSION »."""
        self.assertIn("extensions = ps:", self.src)
        self.assertIn("postgis", self.src)

    def test_a_compiler_outside_a_nix_shell_finds_the_headers(self):
        """Sans ces variables, ce qui n'a pas de roue amont ne se compile pas :
        gcc ne cherche ni en-têtes ni bibliothèques dans le profil système."""
        for var in ("CPATH", "LIBRARY_PATH", "PKG_CONFIG_PATH"):
            with self.subTest(var=var):
                self.assertIn(var, self.src)

    def test_the_variables_reach_a_non_interactive_ssh(self):
        """« environment.variables » n'écrit que dans /etc/set-environment,
        que seul un shell de CONNEXION lit. Le déploiement, lui, installe par
        « ssh hôte 'commande' » : la variable y serait vide."""
        self.assertIn("environment.sessionVariables", self.src)
        self.assertNotIn("environment.variables", self.src)

    def test_the_html_manuals_are_left_out(self):
        """NixOS installe la sortie « doc » de CHAQUE paquet du système
        (extraOutputsToInstall vaut « man info doc »). Celle de CPython n'est
        pas dans le cache binaire : le premier rebuild la BÂTIT, un Sphinx de
        trois mille pages qui domine le temps d'installation et fait cesser de
        répondre une machine étroite.

        « documentation.doc » et non « documentation » : les pages de manuel
        et info restent, elles se lisent depuis un terminal."""
        self.assertIn("documentation.doc.enable = false;", self.src)
        self.assertNotIn("documentation.enable", self.src)

    def test_the_install_reads_the_paths_off_the_filesystem(self):
        """Une session reçoit les variables du module à son OUVERTURE, par
        pam_env. L'installation applique le module (« make install_os ») puis
        compile (« make install_odoo_18 ») dans la MÊME session : la sienne
        est plus vieille que ce qu'elle vient de déclarer.

        Les trois paquets du verrou qui n'ont pas de roue amont s'arrêtaient
        alors sur « lber.h », « cups/http.h » et « mysql.h » — au PREMIER
        passage seulement, ce qui est la pire des pannes : le second réussit
        et donne raison à tort. env_var.sh relit donc le profil courant du
        système, un lien sur le disque, plutôt qu'une variable héritée."""
        env = (RACINE / "env_var.sh").read_text(encoding="utf-8")
        self.assertIn("if [ -d /run/current-system/sw ]", env)
        for var in ("CPATH", "LIBRARY_PATH", "PKG_CONFIG_PATH"):
            with self.subTest(var=var):
                self.assertIn(f"export {var}=", env)
                self.assertIn("/run/current-system/sw", env)

    def test_nothing_is_exported_off_nixos(self):
        """Le garde est le répertoire lui-même : ailleurs, aucune de ces
        variables n'est touchée."""
        env = (RACINE / "env_var.sh").read_text(encoding="utf-8")
        bloc = env.split("if [ -d /run/current-system/sw ]")[1].split("fi")[0]
        self.assertNotIn("\nexport", bloc.replace("\n  export", ""))

    def test_the_headers_are_linked_into_the_profile(self):
        """Le profil ne porte pas « /include » par défaut : sans cette ligne,
        déclarer une sortie « .dev » ne met les en-têtes nulle part, et
        « fatal error: lber.h » reste entier."""
        self.assertIn("environment.pathsToLink", self.src)
        self.assertIn('"/include"', self.src)


if __name__ == "__main__":
    unittest.main()
