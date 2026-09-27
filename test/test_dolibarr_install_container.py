#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur Dolibarr en conteneurs, sur un moteur simulé.

Le moteur (Docker ou Podman) garde en mémoire images, réseau, volumes et
conteneurs, et répond à inspect, pull, run et start comme les deux le font.
Ce qui se garde :
- chaque secret est un fichier 0600, écrit avant le premier conteneur, et
  aucune valeur ne paraît sur argv ;
- ce qui existe déjà est repris, jamais recréé : relancer reprend ;
- le site n'est déclaré prêt que lorsqu'il sert la page de connexion ;
- sans moteur utilisable, rien ne se lance.
"""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import install_container, install_native  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
IMAGE = "docker.io/dolibarr/dolibarr:24.0.0@sha256:" + "1" * 64
MARIADB = "docker.io/library/mariadb:11.4@sha256:" + "2" * 64
PAGE = "<title>Login @ 24.0.0</title>"


def fiche(moteur="podman", sans_sudo=True, avec_sudo=False, rootless=True):
    return {
        "moteur": moteur,
        "sans_sudo": sans_sudo,
        "avec_sudo": avec_sudo,
        "rootless": rootless if sans_sudo else None,
        "docker_host": None,
    }


class Moteur:
    """Un moteur de conteneurs en mémoire."""

    def __init__(self):
        self.images = set()
        self.reseaux = set()
        self.volumes = set()
        self.conteneurs = {}  # nom -> "running" | "exited"

    def repondre(self, argv):
        while argv and argv[0] in ("sudo",):
            argv = argv[1:]
        verbe = argv[1:]
        if verbe[:2] == ["image", "inspect"]:
            return (0, "[]") if verbe[2] in self.images else (125, "")
        if verbe[:1] == ["pull"]:
            self.images.add(verbe[1])
            return 0, ""
        for genre, ensemble in (
            ("network", self.reseaux),
            ("volume", self.volumes),
        ):
            if verbe[:2] == [genre, "inspect"]:
                return (0, "[]") if verbe[2] in ensemble else (125, "")
            if verbe[:2] == [genre, "create"]:
                ensemble.add(verbe[2])
                return 0, ""
        if verbe[:2] == ["container", "inspect"]:
            etat = self.conteneurs.get(verbe[-1])
            if etat is None:
                return 125, "no such container"
            return 0, "true" if etat == "running" else "false"
        if verbe[:1] == ["run"]:
            nom = verbe[verbe.index("--name") + 1]
            self.conteneurs[nom] = "running"
            return 0, "0123abcd"
        if verbe[:1] == ["start"]:
            self.conteneurs[verbe[1]] = "running"
            return 0, verbe[1]
        return None


class FauxRunner:
    def __init__(self, moteur, dry_run=False):
        self.moteur = moteur
        self.dry_run = dry_run
        self.evenements = []  # ("run", argv) | ("write", chemin)
        self.sortie = []

    def out(self, texte):
        self.sortie.append(texte)

    def run(self, argv, input=None, cwd=None, env=None):
        self.evenements.append(("run", list(argv)))
        if self.dry_run:
            return 0, ""
        return self.moteur.repondre(list(argv)) or (0, "")

    def probe(self, argv, cwd=None):
        return self.moteur.repondre(list(argv))

    def write(
        self, path, text, mode=0o600, sudo=False, owner=None, group=None
    ):
        if self.dry_run:
            return
        self.evenements.append(("write", path))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text)
        os.chmod(path, mode)

    def lances(self):
        return [a for genre, a in self.evenements if genre == "run"]


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name, "erplibre")
        (self.racine / "conf").mkdir(parents=True)
        (self.racine / "manifest").mkdir()
        (self.racine / "conf" / "supported_version_dolibarr.json").write_text(
            json.dumps(
                {
                    "version": "24.0.1",
                    "branch": "24.0",
                    "docker_image": IMAGE,
                    "mariadb_image": MARIADB,
                    "php_min": "7.2",
                    "php_max": "8.5",
                }
            )
        )
        (self.racine / "manifest" / "git_manifest_dolibarr.xml").write_text(
            '<manifest><project name="dolibarr.git" path="dolibarr/dolibarr"'
            f' remote="Dolibarr" revision="{COMMIT}" upstream="24.0"'
            ' groups="dolibarr" /></manifest>'
        )
        self.xdg = Path(tmp.name, "xdg")
        self.pages = [PAGE]
        patches = [
            mock.patch.object(install_native, "ROOT", str(self.racine)),
            mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.xdg)}),
            mock.patch.object(install_container, "http_get", self.http_get),
            mock.patch.object(install_container.time, "sleep"),
            mock.patch.object(
                install_container, "port_is_free", lambda port: True
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(install_native.lib_dolibarr.ENV_ADMIN_PASSWORD, None)
        self.moteur = Moteur()
        self.fiches = [fiche("docker", False, False), fiche()]
        self.etat = self.xdg / "ERPLibre" / "dolibarr" / "erp"

    def http_get(self, url, host):
        return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]

    def installer(self, *extra, dry_run=False):
        runner = FauxRunner(self.moteur, dry_run=dry_run)
        argv = ["--mode", "dev", "--instance", "erp", "--port", "8081", *extra]
        with (
            contextlib.redirect_stdout(io.StringIO()),
            mock.patch(
                "builtins.input", side_effect=AssertionError("input() appelé")
            ),
        ):
            code = install_container.main(
                argv, engines=self.fiches, runner=runner
            )
        return code, runner

    def secrets(self):
        dossier = self.etat / "secrets"
        return {f.name: f.read_text() for f in dossier.iterdir()}


class TestParcoursComplet(Banc):
    def test_a_development_install_runs_the_three_containers(self):
        code, runner = self.installer()
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        noms = [
            a[a.index("--name") + 1] for a in runner.lances() if "run" in a
        ]
        self.assertEqual(
            noms,
            [
                "erplibre-dolibarr-erp-db",
                "erplibre-dolibarr-erp-web",
                "erplibre-dolibarr-erp-cron",
            ],
        )
        self.assertIn(["podman", "pull", IMAGE], runner.lances())
        self.assertIn(["podman", "pull", MARIADB], runner.lances())
        self.assertIn(
            ["podman", "network", "create", "erplibre-dolibarr-erp"],
            runner.lances(),
        )

    def test_the_site_publishes_the_chosen_port_with_host_mapping(self):
        _code, runner = self.installer()
        web = [a for a in runner.lances() if "erplibre-dolibarr-erp-web" in a][
            0
        ]
        self.assertIn("127.0.0.1:8081:80", web)
        self.assertIn("--userns=keep-id:uid=33,gid=33", web)
        self.assertIn(f"{self.etat}/custom:/var/www/html/custom", web)

    def test_the_record_names_the_containers_and_the_secrets(self):
        self.installer()
        registre = json.loads(
            (
                self.racine / "private" / "dolibarr" / "instances.json"
            ).read_text()
        )
        fiche_ = registre["instances"]["erp"]
        self.assertEqual(fiche_["runtime"], "container")
        self.assertEqual(fiche_["engine"], "podman")
        self.assertEqual(fiche_["url"], "http://127.0.0.1:8081")
        self.assertEqual(fiche_["version"], "24.0.0")
        self.assertEqual(fiche_["secrets"], f"dir:{self.etat}/secrets")


class TestSecrets(Banc):
    def test_every_secret_is_a_private_file_before_any_container(self):
        _code, runner = self.installer()
        attendus = {
            "db_password",
            "db_root_password",
            "admin_password",
            "cron_key",
            "instance_id",
        }
        self.assertEqual(set(self.secrets()), attendus)
        dossier = self.etat / "secrets"
        self.assertEqual(stat.S_IMODE(dossier.stat().st_mode), 0o700)
        for f in dossier.iterdir():
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        premier_run = next(
            i
            for i, (g, a) in enumerate(runner.evenements)
            if g == "run" and "run" in a
        )
        ecrits = [
            i
            for i, (g, p) in enumerate(runner.evenements)
            if g == "write" and "/secrets/" in p
        ]
        self.assertTrue(ecrits)
        self.assertLess(max(ecrits), premier_run)

    def test_a_loose_secrets_directory_is_closed(self):
        dossier = self.etat / "secrets"
        dossier.mkdir(parents=True)
        os.chmod(dossier, 0o755)
        self.installer()
        self.assertEqual(stat.S_IMODE(dossier.stat().st_mode), 0o700)

    def test_no_secret_value_ever_reaches_argv(self):
        _code, runner = self.installer()
        valeurs = [v.strip() for v in self.secrets().values()]
        for argv in runner.lances():
            joint = " ".join(argv)
            for v in valeurs:
                self.assertNotIn(v, joint)

    def test_secrets_are_letters_and_digits(self):
        # L'entrée de l'image les relit par un echo non protégé.
        self.installer()
        for nom, valeur in self.secrets().items():
            with self.subTest(nom=nom):
                self.assertRegex(valeur.strip(), r"^[A-Za-z0-9]{20,}$")

    def test_a_rerun_keeps_the_secrets(self):
        self.installer()
        avant = self.secrets()
        (self.racine / "private" / "dolibarr" / "instances.json").unlink()
        self.installer()
        self.assertEqual(self.secrets(), avant)

    def test_a_typed_admin_password_is_used(self):
        with mock.patch.dict(
            os.environ,
            {install_native.lib_dolibarr.ENV_ADMIN_PASSWORD: "Saisi2Fois"},
        ):
            self.installer()
        self.assertEqual(
            self.secrets()["admin_password"].strip(), "Saisi2Fois"
        )


class TestCrochet(Banc):
    def test_the_hook_is_copied_into_the_instance(self):
        self.installer()
        copie = self.etat / "init.d" / "10-erplibre.php"
        source = (
            RACINE / "script" / "dolibarr" / "container" / "10-erplibre.php"
        )
        self.assertEqual(copie.read_text(), source.read_text())


class TestReprise(Banc):
    def test_existing_objects_are_reused_and_a_stopped_one_started(self):
        self.moteur.images = {IMAGE, MARIADB}
        self.moteur.reseaux = {"erplibre-dolibarr-erp"}
        self.moteur.volumes = {
            "erplibre-dolibarr-erp-dbdata",
            "erplibre-dolibarr-erp-documents",
        }
        self.moteur.conteneurs = {
            "erplibre-dolibarr-erp-db": "running",
            "erplibre-dolibarr-erp-web": "exited",
            "erplibre-dolibarr-erp-cron": "running",
        }
        code, runner = self.installer()
        self.assertEqual(code, 0)
        verbes = [a[1] for a in runner.lances()]
        self.assertNotIn("pull", verbes)
        self.assertNotIn("run", verbes)
        self.assertEqual(
            [a for a in runner.lances() if a[1] in ("create", "start")],
            [["podman", "start", "erplibre-dolibarr-erp-web"]],
        )
        self.assertFalse([a for a in runner.lances() if a[2:3] == ["create"]])


class TestAttente(Banc):
    def test_the_site_is_awaited_until_it_serves_the_login_page(self):
        self.pages = ["ERROR connection refused", "502", PAGE]
        code, runner = self.installer()
        self.assertEqual(code, 0)

    def test_a_site_that_never_serves_fails_and_starts_no_cron(self):
        self.pages = ["502"]
        code, runner = self.installer()
        self.assertEqual(code, 1)
        self.assertEqual(
            install_container.time.sleep.call_count,
            install_container.WAIT_TRIES - 1,
        )
        self.assertNotIn(
            "erplibre-dolibarr-erp-cron",
            [a for argv in runner.lances() for a in argv],
        )


class TestMoteur(Banc):
    def test_no_usable_engine_stops_before_anything(self):
        self.fiches = [
            fiche("docker", False, False),
            fiche("podman", False, False),
        ]
        code, runner = self.installer()
        self.assertEqual(code, 1)
        self.assertEqual(runner.lances(), [])
        self.assertFalse(self.etat.exists())

    def test_an_engine_reached_through_sudo_is_prefixed(self):
        self.fiches = [
            fiche("docker", False, True),
            fiche("podman", False, False),
        ]
        _code, runner = self.installer()
        self.assertEqual(runner.lances()[0][:2], ["sudo", "docker"])
        web = [a for a in runner.lances() if "erplibre-dolibarr-erp-web" in a][
            0
        ]
        self.assertIn(f"WWW_USER_ID={os.getuid()}", web)

    def test_podman_through_sudo_maps_like_docker(self):
        # Sous sudo, Podman tourne avec des privilèges : keep-id n'y sert pas.
        self.fiches = [
            fiche("docker", False, False),
            fiche("podman", False, True),
        ]
        _code, runner = self.installer()
        web = [a for a in runner.lances() if "erplibre-dolibarr-erp-web" in a][
            0
        ]
        self.assertEqual(web[:2], ["sudo", "podman"])
        self.assertIn(f"WWW_USER_ID={os.getuid()}", web)
        self.assertFalse([a for a in web if a.startswith("--userns")])

    def test_the_chosen_engine_wins(self):
        self.fiches = [fiche("docker"), fiche("podman")]
        _code, runner = self.installer("--engine", "podman")
        self.assertEqual(runner.lances()[0][0], "podman")


class TestRefus(Banc):
    def test_an_existing_instance_is_refused(self):
        self.installer()
        code, runner = self.installer()
        self.assertEqual(code, 1)
        self.assertEqual(runner.lances(), [])

    def test_a_busy_port_is_refused(self):
        with mock.patch.object(
            install_container, "port_is_free", lambda port: False
        ):
            code, runner = self.installer()
        self.assertEqual(code, 1)
        self.assertEqual(runner.lances(), [])

    def test_invalid_input_exits_2(self):
        for extra in (["--instance", "Bad-Name"], ["--port", "80"]):
            with self.subTest(extra=extra):
                code, _runner = self.installer(*extra)
                self.assertEqual(code, 2)


class TestBlanc(Banc):
    def test_a_dry_run_writes_and_creates_nothing(self):
        # Aucun conteneur ne tourne : le site ne répond pas, et l'essai à
        # blanc ne l'attend pas.
        self.pages = ["ERROR connection refused"]
        code, runner = self.installer(dry_run=True)
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        self.assertFalse(self.etat.exists())
        self.assertFalse(self.moteur.conteneurs)
        self.assertFalse(
            (self.racine / "private" / "dolibarr" / "instances.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
