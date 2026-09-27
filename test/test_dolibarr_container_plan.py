#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les commandes du moteur de conteneurs pour une instance Dolibarr.

Rendu pur : des listes d'arguments, sans le moteur en tête. Ce qui se garde :
- aucun secret sur argv : chaque secret passe par un fichier monté en
  lecture seule et sa variable *_FILE ;
- MariaDB range ses tables dans la collation que conf.php déclare ;
- le site n'écoute que sur 127.0.0.1 : nginx de l'hôte le sert en prod ;
- en dev, custom/ est un dossier de l'hôte, inscriptible par Apache ; en
  prod, tout est en volumes nommés, rien ne se perd à la recréation.
"""

import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import container_plan  # noqa: E402

PIN = {
    "docker_image": "docker.io/dolibarr/dolibarr:24.0.0",
    "mariadb_image": "docker.io/library/mariadb:11.4",
}
SECRETS = "/srv/essai/erp/secrets"
INIT = "/srv/essai/erp/init.d"
CUSTOM = "/srv/essai/erp/custom"
PODMAN = {"moteur": "podman", "rootless": True}
DOCKER = {"moteur": "docker", "rootless": False}


def paires(argv, option):
    """Les valeurs de chaque `option` de argv (« -e », « -v »…)."""
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == option]


class TestNoms(unittest.TestCase):
    def test_every_object_carries_the_instance(self):
        n = container_plan.names("erp")
        self.assertEqual(n["network"], "erplibre-dolibarr-erp")
        self.assertEqual(
            (n["db"], n["web"], n["cron"]),
            (
                "erplibre-dolibarr-erp-db",
                "erplibre-dolibarr-erp-web",
                "erplibre-dolibarr-erp-cron",
            ),
        )
        self.assertEqual(
            n["volumes"],
            {
                "dbdata": "erplibre-dolibarr-erp-dbdata",
                "documents": "erplibre-dolibarr-erp-documents",
                "custom": "erplibre-dolibarr-erp-custom",
            },
        )


class TestVersion(unittest.TestCase):
    def test_the_version_is_the_image_tag(self):
        for ref in (
            "docker.io/dolibarr/dolibarr:24.0.0",
            "docker.io/dolibarr/dolibarr:24.0.0@sha256:" + "1" * 64,
        ):
            with self.subTest(ref=ref):
                self.assertEqual(container_plan.image_version(ref), "24.0.0")


class TestReseauEtVolumes(unittest.TestCase):
    def test_one_network_and_the_named_volumes(self):
        self.assertEqual(
            container_plan.network_create("erp"),
            ["network", "create", "erplibre-dolibarr-erp"],
        )
        self.assertEqual(
            container_plan.volume_creates("erp", "prod"),
            [
                ["volume", "create", "erplibre-dolibarr-erp-dbdata"],
                ["volume", "create", "erplibre-dolibarr-erp-documents"],
                ["volume", "create", "erplibre-dolibarr-erp-custom"],
            ],
        )

    def test_development_keeps_custom_on_the_host(self):
        volumes = container_plan.volume_creates("erp", "dev")
        self.assertNotIn(
            ["volume", "create", "erplibre-dolibarr-erp-custom"], volumes
        )


class TestBase(unittest.TestCase):
    def setUp(self):
        self.argv = container_plan.run_db("erp", PIN, SECRETS, "prod", PODMAN)

    def test_passwords_come_from_read_only_files(self):
        env = paires(self.argv, "-e")
        self.assertIn("MARIADB_PASSWORD_FILE=/run/secrets/db_password", env)
        self.assertIn(
            "MARIADB_ROOT_PASSWORD_FILE=/run/secrets/db_root_password", env
        )
        self.assertIn(
            f"{SECRETS}/db_password:/run/secrets/db_password:ro",
            paires(self.argv, "-v"),
        )
        self.assertIn("MARIADB_DATABASE=dolibarr_erp", env)
        self.assertIn("MARIADB_USER=dolibarr_erp", env)

    def test_tables_take_the_collation_conf_php_declares(self):
        i = self.argv.index(PIN["mariadb_image"])
        self.assertEqual(
            self.argv[i + 1 :],
            [
                "--character-set-server=utf8mb4",
                "--collation-server=utf8mb4_unicode_ci",
            ],
        )

    def test_data_in_its_named_volume_and_no_port_published(self):
        self.assertIn(
            "erplibre-dolibarr-erp-dbdata:/var/lib/mysql",
            paires(self.argv, "-v"),
        )
        self.assertNotIn("-p", self.argv)
        self.assertEqual(
            paires(self.argv, "--network"), ["erplibre-dolibarr-erp"]
        )


class TestWeb(unittest.TestCase):
    def web(self, mode="dev", engine=PODMAN, **kw):
        options = dict(
            instance="erp",
            pin=PIN,
            secrets_dir=SECRETS,
            init_dir=INIT,
            mode=mode,
            engine=engine,
            port=8080,
            url="http://127.0.0.1:8080",
            admin_login="admin",
            custom_dir=CUSTOM,
            host_ids=(1000, 1000),
        )
        options.update(kw)
        return container_plan.run_web(**options)

    def test_it_listens_on_loopback_only(self):
        self.assertEqual(paires(self.web(), "-p"), ["127.0.0.1:8080:80"])

    def test_the_image_installs_itself_with_every_secret_as_a_file(self):
        env = paires(self.web(), "-e")
        for ligne in (
            "DOLI_INSTALL_AUTO=1",
            "DOLI_DB_TYPE=mysqli",
            "DOLI_DB_HOST=erplibre-dolibarr-erp-db",
            "DOLI_DB_NAME=dolibarr_erp",
            "DOLI_DB_USER=dolibarr_erp",
            "DOLI_DB_PASSWORD_FILE=/run/secrets/db_password",
            "DOLI_ADMIN_LOGIN=admin",
            "DOLI_ADMIN_PASSWORD_FILE=/run/secrets/admin_password",
            "DOLI_INSTANCE_UNIQUE_ID_FILE=/run/secrets/instance_id",
            "DOLI_URL_ROOT=http://127.0.0.1:8080",
            "DOLI_ENABLE_MODULES=Cron",
        ):
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, env)

    def test_the_erplibre_hook_runs_at_first_install(self):
        self.assertIn(
            f"{INIT}:/var/www/scripts/docker-init.d:ro",
            paires(self.web(), "-v"),
        )

    def test_the_hook_sets_the_cron_key_the_entrypoint_never_sees(self):
        # Donnée à l'entrée de l'image, la clé finirait dans ses journaux
        # (« Set cron key to … ») : seul le crochet la lit, dans son fichier.
        argv = self.web()
        self.assertIn(
            f"{SECRETS}/cron_key:/run/secrets/cron_key:ro", paires(argv, "-v")
        )
        self.assertFalse(
            [e for e in paires(argv, "-e") if e.startswith("DOLI_CRON_KEY")]
        )

    def test_production_comes_back_after_a_reboot(self):
        # Podman : podman-restart.service relance les « always » ; Docker :
        # son démon relance les « unless-stopped ».
        prod = dict(
            mode="prod", url="https://erp.example.org", custom_dir=None
        )
        self.assertEqual(paires(self.web(**prod), "--restart"), ["always"])
        self.assertEqual(
            paires(self.web(engine=DOCKER, **prod), "--restart"),
            ["unless-stopped"],
        )
        self.assertEqual(paires(self.web(), "--restart"), [])

    def test_development_binds_custom_and_maps_the_host_account(self):
        # Podman sans root : l'hôte devient www-data (33) dans le conteneur,
        # qui doit rester root pour lier le port 80.
        argv = self.web()
        self.assertIn(f"{CUSTOM}:/var/www/html/custom", paires(argv, "-v"))
        self.assertIn("--userns=keep-id:uid=33,gid=33", argv)
        self.assertEqual(paires(argv, "--user"), ["0:0"])
        self.assertIn("DOLI_PROD=0", paires(argv, "-e"))

    def test_docker_maps_www_data_onto_the_host_account(self):
        # keep-id n'existe que chez Podman : l'entrée de l'image renumérote
        # www-data.
        argv = self.web(engine=DOCKER)
        env = paires(argv, "-e")
        self.assertIn("WWW_USER_ID=1000", env)
        self.assertIn("WWW_GROUP_ID=1000", env)
        self.assertFalse([a for a in argv if a.startswith("--userns")])

    def test_rootful_podman_maps_like_docker(self):
        # keep-id ne sert qu'à Podman sans root ; sous sudo, l'entrée de
        # l'image renumérote www-data comme avec Docker.
        argv = self.web(engine={"moteur": "podman", "rootless": False})
        self.assertIn("WWW_USER_ID=1000", paires(argv, "-e"))
        self.assertFalse([a for a in argv if a.startswith("--userns")])

    def test_production_keeps_everything_in_named_volumes(self):
        argv = self.web(
            mode="prod", url="https://erp.example.org", custom_dir=None
        )
        volumes = paires(argv, "-v")
        self.assertIn(
            "erplibre-dolibarr-erp-custom:/var/www/html/custom", volumes
        )
        self.assertIn(
            "erplibre-dolibarr-erp-documents:/var/www/documents", volumes
        )
        env = paires(argv, "-e")
        self.assertIn("DOLI_PROD=1", env)
        self.assertIn("DOLI_URL_ROOT=https://erp.example.org", env)
        self.assertFalse([a for a in argv if a.startswith("--userns")])
        self.assertFalse([e for e in env if e.startswith("WWW_")])

    def test_the_image_comes_last(self):
        self.assertEqual(self.web()[-1], PIN["docker_image"])


class TestCron(unittest.TestCase):
    def setUp(self):
        self.argv = container_plan.run_cron(
            "erp", PIN, SECRETS, "prod", DOCKER, "admin", None
        )

    def test_it_runs_the_scheduled_jobs_with_the_key_from_a_file(self):
        env = paires(self.argv, "-e")
        self.assertIn("DOLI_CRON=1", env)
        self.assertIn("DOLI_CRON_KEY_FILE=/run/secrets/cron_key", env)
        self.assertIn("DOLI_CRON_USER=admin", env)
        self.assertIn(
            f"{SECRETS}/cron_key:/run/secrets/cron_key:ro",
            paires(self.argv, "-v"),
        )

    def test_it_publishes_no_port(self):
        self.assertNotIn("-p", self.argv)

    def test_it_stops_at_once(self):
        # L'image arrête par SIGWINCH, que bash en PID 1 ignore : 10 s
        # d'attente puis SIGKILL. Un init qui relaie SIGTERM arrête cron.
        self.assertIn("--init", self.argv)
        self.assertEqual(paires(self.argv, "--stop-signal"), ["SIGTERM"])

    def test_it_shares_the_instance_id_that_encrypts_the_key(self):
        # dolibarr_set_const chiffre CRON_KEY avec l'identifiant d'instance.
        self.assertIn(
            "DOLI_INSTANCE_UNIQUE_ID_FILE=/run/secrets/instance_id",
            paires(self.argv, "-e"),
        )

    def test_production_cron_and_database_restart_too(self):
        self.assertEqual(paires(self.argv, "--restart"), ["unless-stopped"])
        base = container_plan.run_db("erp", PIN, SECRETS, "prod", DOCKER)
        self.assertEqual(paires(base, "--restart"), ["unless-stopped"])

    def test_development_cron_writes_custom_like_the_site(self):
        # Les tâches des modules en développement vivent dans custom/.
        argv = container_plan.run_cron(
            "erp", PIN, SECRETS, "dev", DOCKER, "admin", CUSTOM, (1000, 1000)
        )
        self.assertIn(f"{CUSTOM}:/var/www/html/custom", paires(argv, "-v"))
        self.assertIn("WWW_USER_ID=1000", paires(argv, "-e"))


class TestAucunSecretSurArgv(unittest.TestCase):
    def test_no_secret_variable_is_passed_by_value(self):
        # Les noms de variables d'un secret ne paraissent qu'en *_FILE.
        sensibles = ("PASSWORD", "CRON_KEY", "UNIQUE_ID")
        for argv in (
            container_plan.run_db("erp", PIN, SECRETS, "prod", PODMAN),
            container_plan.run_web(
                "erp",
                PIN,
                SECRETS,
                INIT,
                "dev",
                PODMAN,
                8080,
                "http://127.0.0.1:8080",
                "admin",
                CUSTOM,
                (1000, 1000),
            ),
            container_plan.run_cron(
                "erp", PIN, SECRETS, "dev", PODMAN, "admin", CUSTOM
            ),
        ):
            for e in paires(argv, "-e"):
                nom = e.split("=", 1)[0]
                if any(s in nom for s in sensibles):
                    with self.subTest(e=e):
                        self.assertTrue(nom.endswith("_FILE"))


class TestRefus(unittest.TestCase):
    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            container_plan.volume_creates("erp", "staging")

    def test_development_needs_its_custom_directory(self):
        with self.assertRaises(ValueError):
            container_plan.run_web(
                "erp",
                PIN,
                SECRETS,
                INIT,
                "dev",
                PODMAN,
                8080,
                "http://127.0.0.1:8080",
                "admin",
                None,
                (1000, 1000),
            )


if __name__ == "__main__":
    unittest.main()
