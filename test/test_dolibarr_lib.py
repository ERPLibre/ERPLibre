#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cœur pur de script/dolibarr/ : épinglage, libellé, nom d'instance.

L'épinglage vit en deux endroits qui doivent se tenir : le manifest porte le
COMMIT, conf/supported_version_dolibarr.json porte la version affichée et la
branche. Un commit pris sur une autre branche que celle déclarée ferait
afficher une version fausse au menu d'installation ; read_pin le refuse au
lieu de le laisser passer.
"""

import json
import os
import sys
import tempfile
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.dolibarr import lib_dolibarr  # noqa: E402

# Valeurs inventées : un commit ne désigne personne, mais celui-ci n'existe
# dans aucun dépôt.
COMMIT = "0123456789abcdef0123456789abcdef01234567"

MANIFEST = """<?xml version="1.0" encoding="UTF-8" ?>
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

PIN = {
    "version": "24.0.1",
    "branch": "24.0",
    "docker_image": "dolibarr/dolibarr:24.0.0",
    "mariadb_image": "mariadb:11.4",
    "php_min": "7.2",
    "php_max": "8.5",
}


class _Racine:
    """Une racine de dépôt jetable avec conf/ et manifest/."""

    def __init__(
        self, pin=PIN, revision=COMMIT, upstream="24.0", manifest=MANIFEST
    ):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "conf"))
        os.makedirs(os.path.join(self.root, "manifest"))
        if pin is not None:
            with open(
                self.path("conf/supported_version_dolibarr.json"),
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(pin, f)
        if manifest is not None:
            with open(
                self.path("manifest/git_manifest_dolibarr.xml"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(manifest.format(revision=revision, upstream=upstream))

    def path(self, rel):
        return os.path.join(self.root, rel)

    def close(self):
        self.tmp.cleanup()


class TestReadPin(unittest.TestCase):
    def _root(self, **kw):
        r = _Racine(**kw)
        self.addCleanup(r.close)
        return r.root

    def test_commit_comes_from_the_manifest_and_version_from_the_json(self):
        pin = lib_dolibarr.read_pin(self._root())
        self.assertEqual(pin["commit"], COMMIT)
        self.assertEqual(pin["version"], "24.0.1")
        self.assertEqual(pin["branch"], "24.0")
        self.assertEqual(pin["path"], "dolibarr/dolibarr")
        self.assertEqual(pin["docker_image"], "dolibarr/dolibarr:24.0.0")

    def test_a_commit_pinned_on_another_branch_is_refused(self):
        # Le JSON annonce 24.0 ; le manifest suit 23.0 : le menu afficherait
        # « 24.0.1 » pour du code 23.
        root = self._root(upstream="23.0")
        with self.assertRaises(lib_dolibarr.PinError) as ctx:
            lib_dolibarr.read_pin(root)
        self.assertIn("23.0", str(ctx.exception))
        self.assertIn("24.0", str(ctx.exception))

    def test_a_branch_name_is_not_a_pin(self):
        # revision="24.0" suivrait la branche : ce n'est plus un épinglage.
        root = self._root(revision="24.0")
        with self.assertRaises(lib_dolibarr.PinError):
            lib_dolibarr.read_pin(root)

    def test_a_short_commit_is_not_a_pin(self):
        root = self._root(revision=COMMIT[:12])
        with self.assertRaises(lib_dolibarr.PinError):
            lib_dolibarr.read_pin(root)

    def test_missing_json_raises_pin_error_not_os_error(self):
        # Le menu ne rattrape qu'UNE exception pour dire pourquoi l'entrée
        # manque ; un FileNotFoundError ferait tomber tout l'écran.
        root = self._root(pin=None)
        with self.assertRaises(lib_dolibarr.PinError):
            lib_dolibarr.read_pin(root)

    def test_missing_manifest_raises_pin_error(self):
        root = self._root(manifest=None)
        with self.assertRaises(lib_dolibarr.PinError):
            lib_dolibarr.read_pin(root)

    def test_manifest_without_the_dolibarr_project_is_refused(self):
        root = self._root(
            manifest='<manifest><remote name="x" fetch="https://x/" />'
            "</manifest>"
        )
        with self.assertRaises(lib_dolibarr.PinError):
            lib_dolibarr.read_pin(root)

    def test_the_project_is_found_by_its_group_not_its_rank(self):
        # Un manifest fusionné porte d'autres projets avant Dolibarr : prendre
        # le premier venu épinglerait un autre dépôt.
        other = (
            '    <project name="erplibre.git" path="." remote="Dolibarr"'
            ' revision="fedcba9876543210fedcba9876543210fedcba98"'
            ' upstream="24.0" groups="base" />\n'
        )
        manifest = MANIFEST.replace("    <project\n", other + "    <project\n")
        pin = lib_dolibarr.read_pin(self._root(manifest=manifest))
        self.assertEqual(pin["commit"], COMMIT)
        self.assertEqual(pin["path"], "dolibarr/dolibarr")

    def test_json_missing_a_key_is_refused(self):
        pin = dict(PIN)
        del pin["version"]
        with self.assertRaises(lib_dolibarr.PinError) as ctx:
            lib_dolibarr.read_pin(self._root(pin=pin))
        self.assertIn("version", str(ctx.exception))


class TestLeVraiEpinglage(unittest.TestCase):
    """Les fichiers du dépôt eux-mêmes : lisibles, et d'accord entre eux."""

    def test_the_repository_pin_reads(self):
        pin = lib_dolibarr.read_pin(RACINE)
        self.assertRegex(pin["version"], r"^\d+\.\d+\.\d+$")
        # La version affichée appartient à la branche suivie : 24.0.x sur 24.0.
        self.assertTrue(pin["version"].startswith(pin["branch"] + "."), pin)
        self.assertEqual(pin["path"], "dolibarr/dolibarr")


class TestInstallLabel(unittest.TestCase):
    PIN = dict(PIN, commit=COMMIT, path="dolibarr/dolibarr")

    def test_label_shows_version_and_short_commit(self):
        self.assertEqual(
            lib_dolibarr.install_label("8", self.PIN, installed=False),
            "8: Dolibarr 24.0.1 (0123456)",
        )

    def test_label_says_installed(self):
        self.assertEqual(
            lib_dolibarr.install_label("9", self.PIN, installed=True),
            "9: Dolibarr 24.0.1 (0123456) - Installed",
        )


class TestInstanceName(unittest.TestCase):
    # Le nom devient nom de base, de pool php-fpm, d'unité systemd et de
    # répertoire : tout ce qui casse l'un de ces usages est refusé.
    ACCEPTES = ("dolibarr", "doli_2", "ab", "a" * 31)
    REFUSES = (
        "",
        "a",  # trop court pour se distinguer
        "a" * 32,
        "Dolibarr",  # majuscule
        "2dolibarr",  # commence par un chiffre
        "doli-barr",  # tiret : invalide en nom de base MariaDB sans quotes
        "doli barr",
        "../etc",
        "doli.barr",
    )

    def test_accepted_names(self):
        for name in self.ACCEPTES:
            with self.subTest(name=name):
                self.assertTrue(lib_dolibarr.valid_instance_name(name))

    def test_refused_names(self):
        for name in self.REFUSES:
            with self.subTest(name=name):
                self.assertFalse(lib_dolibarr.valid_instance_name(name))


class TestLogin(unittest.TestCase):
    # L'identifiant part dans argv et dans la base de Dolibarr : ni espace
    # ni métacaractère, et pas d'option déguisée en tête (« -x »).
    ACCEPTES = ("admin", "jean.dupont", "ops@example.org", "a", "x_1-2")
    REFUSES = ("", " admin", "adm in", "-x", "x;id", "a" * 51, "é")

    def test_accepted(self):
        for login in self.ACCEPTES:
            with self.subTest(login=login):
                self.assertTrue(lib_dolibarr.valid_login(login))

    def test_refused(self):
        for login in self.REFUSES:
            with self.subTest(login=login):
                self.assertFalse(lib_dolibarr.valid_login(login))


class TestParsePort(unittest.TestCase):
    CAS = (
        ("", 8080, 8080),  # vide : le défaut
        ("  9000 ", 8080, 9000),
        ("1024", 8080, 1024),
        ("65535", 8080, 65535),
        ("1023", 8080, None),  # privilégié : un utilisateur ne l'ouvre pas
        ("65536", 8080, None),
        ("80a", 8080, None),
        ("-1", 8080, None),
    )

    def test_cases(self):
        for texte, defaut, attendu in self.CAS:
            with self.subTest(texte=texte):
                self.assertEqual(
                    lib_dolibarr.parse_port(texte, defaut), attendu
                )


class TestNativeSupport(unittest.TestCase):
    # (système, famille, nixos, systemd, mode) -> (proposé, raison)
    CAS = (
        (("Linux", "apt-get", False, True, "dev"), (True, "")),
        (("Linux", "zypper", False, True, "prod"), (True, "")),
        (("Linux", "dnf", False, False, "dev"), (True, "")),
        (
            ("Linux", "pacman", False, False, "prod"),
            (False, "native production needs systemd"),
        ),
        (
            ("Linux", None, False, True, "dev"),
            (False, "unsupported system for a native install"),
        ),
        (
            ("Linux", None, True, True, "dev"),
            (
                False,
                "on NixOS, declare services.dolibarr in conf/nixos/erplibre.nix",
            ),
        ),
        (("Darwin", "brew", False, False, "dev"), (True, "")),
        (
            ("Darwin", "brew", False, False, "prod"),
            (False, "native production needs systemd"),
        ),
        (
            ("Darwin", None, False, False, "dev"),
            (False, "a native install on macOS needs Homebrew"),
        ),
        (
            ("Windows", None, False, False, "dev"),
            (False, "unsupported system for a native install"),
        ),
    )

    def test_matrix(self):
        for args, attendu in self.CAS:
            with self.subTest(args=args):
                self.assertEqual(lib_dolibarr.native_support(*args), attendu)


class TestContainerSupport(unittest.TestCase):
    # (système, famille, moteur utilisable) -> (proposé, raison)
    CAS = (
        # Un moteur qui répond suffit, où que l'on soit.
        (("Darwin", None, True), (True, "")),
        # Sans moteur : proposé là où install_container.sh sait l'installer.
        (("Linux", "apt-get", False), (True, "")),
        (("Linux", "pacman", False), (True, "")),
        (
            ("Linux", None, False),
            (False, "no container engine, and none can be installed here"),
        ),
        (
            ("Darwin", "brew", False),
            (
                False,
                "install Docker Desktop first",
            ),
        ),
        (
            ("Windows", None, False),
            (
                False,
                "install Docker Desktop first",
            ),
        ),
    )

    def test_matrix(self):
        for args, attendu in self.CAS:
            with self.subTest(args=args):
                self.assertEqual(
                    lib_dolibarr.container_support(*args), attendu
                )


class TestAvailable(unittest.TestCase):
    def test_development_native_is_delivered(self):
        self.assertIn(("dev", "native"), lib_dolibarr.AVAILABLE)

    def test_every_pair_is_a_known_mode_and_runtime(self):
        for mode, runtime in lib_dolibarr.AVAILABLE:
            with self.subTest(mode=mode, runtime=runtime):
                self.assertIn(mode, ("dev", "prod"))
                self.assertIn(runtime, lib_dolibarr.RUNTIMES)


class TestInstallArgv(unittest.TestCase):
    PYTHON = "./.venv.erplibre/bin/python"

    def test_native_development(self):
        argv, env = lib_dolibarr.install_argv(
            {
                "runtime": "native",
                "mode": "dev",
                "db": "mariadb",
                "instance": "dolibarr",
                "port": 8080,
                "admin_login": "admin",
                "admin_password": "",
            }
        )
        self.assertEqual(
            argv,
            [
                self.PYTHON,
                "-u",
                "script/dolibarr/install_native.py",
                "--mode",
                "dev",
                "--instance",
                "dolibarr",
                "--db",
                "mariadb",
                "--port",
                "8080",
                "--admin-login",
                "admin",
            ],
        )
        # Mot de passe vide : le script le génère ; rien à transmettre.
        self.assertEqual(env, {})

    def test_container_production_behind_a_domain(self):
        argv, env = lib_dolibarr.install_argv(
            {
                "runtime": "container",
                "mode": "prod",
                "db": "mariadb",
                "instance": "erp",
                "port": 8090,
                "domain": "erp.example.org",
                "tls": "certbot",
                "email": "ops@example.org",
                "admin_login": "gestion",
                "admin_password": "",
            }
        )
        self.assertEqual(
            argv,
            [
                self.PYTHON,
                "-u",
                "script/dolibarr/install_container.py",
                "--mode",
                "prod",
                "--instance",
                "erp",
                "--port",
                "8090",
                "--domain",
                "erp.example.org",
                "--tls",
                "certbot",
                "--email",
                "ops@example.org",
                "--admin-login",
                "gestion",
            ],
        )

    def test_the_container_runtime_takes_no_database_choice(self):
        # L'image officielle ne s'installe d'elle-même que sur MariaDB : un
        # --db passé au script conteneur serait trompeur.
        argv, _env = lib_dolibarr.install_argv(
            {
                "runtime": "container",
                "mode": "dev",
                "db": "postgresql",
                "instance": "dolibarr",
                "port": 8080,
                "admin_login": "admin",
                "admin_password": "",
            }
        )
        self.assertNotIn("--db", argv)

    def test_a_typed_password_travels_in_the_environment_only(self):
        secret = "Pa55-inventé-pour-le-test"
        argv, env = lib_dolibarr.install_argv(
            {
                "runtime": "native",
                "mode": "dev",
                "db": "postgresql",
                "instance": "dolibarr",
                "port": 8080,
                "admin_login": "admin",
                "admin_password": secret,
            }
        )
        self.assertFalse(any(secret in a for a in argv), argv)
        self.assertEqual(env, {"EL_DOLIBARR_ADMIN_PASSWORD": secret})

    def test_unknown_runtime_is_refused(self):
        with self.assertRaises(ValueError):
            lib_dolibarr.install_argv(
                {
                    "runtime": "native; rm -rf ~",
                    "mode": "dev",
                    "db": "mariadb",
                    "instance": "dolibarr",
                    "port": 8080,
                    "admin_login": "admin",
                    "admin_password": "",
                }
            )


class TestFreePort(unittest.TestCase):
    def test_first_free_port_from_the_start(self):
        occupes = {8080, 8081}
        self.assertEqual(
            lib_dolibarr.free_port(8080, lambda p: p not in occupes), 8082
        )

    def test_the_start_itself_when_free(self):
        self.assertEqual(lib_dolibarr.free_port(8080, lambda p: True), 8080)

    def test_none_when_every_port_is_taken(self):
        self.assertIsNone(
            lib_dolibarr.free_port(8080, lambda p: False, limit=5)
        )


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _ecrire(self, contenu):
        chemin = os.path.join(self.root, lib_dolibarr.REGISTRY)
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(contenu)

    def test_no_registry_means_no_instance(self):
        self.assertEqual(lib_dolibarr.load_registry(self.root), {})

    def test_instances_are_keyed_by_name(self):
        self._ecrire(json.dumps({"instances": {"dolibarr": {"mode": "dev"}}}))
        self.assertEqual(
            lib_dolibarr.load_registry(self.root),
            {"dolibarr": {"mode": "dev"}},
        )

    def test_an_unreadable_registry_is_an_error_not_an_empty_one(self):
        # Le lire vide ferait croire qu'aucune instance n'existe, et laisserait
        # installer par-dessus une instance vivante.
        self._ecrire("{ pas du json")
        with self.assertRaises(lib_dolibarr.RegistryError):
            lib_dolibarr.load_registry(self.root)


if __name__ == "__main__":
    unittest.main()
