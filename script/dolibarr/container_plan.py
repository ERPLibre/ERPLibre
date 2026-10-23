#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Commandes du moteur de conteneurs pour une instance Dolibarr.

Rendu pur : des listes d'arguments sans le moteur en tête, que
container_runtime.commande() préfixe (sudo, DOCKER_HOST) et que
l'installateur lance. Aucun outil compose : network, volume et run simples,
que Docker et Podman acceptent tous deux.

Une instance <i> : un réseau, trois conteneurs sur ce réseau (MariaDB, le
site, les tâches planifiées) et des volumes nommés. Chaque secret est un
fichier 0600 de `secrets_dir`, monté en lecture seule et nommé par sa
variable *_FILE : aucune valeur ne passe sur argv, où `ps` et `inspect` la
montreraient. Le site n'écoute que sur 127.0.0.1 ; en production, le nginx
de l'hôte le sert sous son domaine.
"""

MODES = ("dev", "prod")

SECRET_MOUNT = "/run/secrets"

# MariaDB range sinon ses tables en utf8mb4_uca1400_ai_ci, alors que le
# conf.php de l'image déclare utf8mb4_unicode_ci.
MARIADB_FLAGS = [
    "--character-set-server=utf8mb4",
    "--collation-server=utf8mb4_unicode_ci",
]


def names(instance):
    """Réseau, conteneurs et volumes de l'instance, par rôle."""
    base = f"erplibre-dolibarr-{instance}"
    return {
        "network": base,
        "db": f"{base}-db",
        "web": f"{base}-web",
        "cron": f"{base}-cron",
        "volumes": {
            "dbdata": f"{base}-dbdata",
            "documents": f"{base}-documents",
            "custom": f"{base}-custom",
        },
    }


def image_version(ref):
    """L'étiquette d'une référence d'image (« 24.0.0 »), empreinte ôtée."""
    return ref.partition("@")[0].rpartition(":")[2]


def _check_mode(mode):
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")


def network_create(instance):
    return ["network", "create", names(instance)["network"]]


def volume_creates(instance, mode):
    """Une commande par volume nommé ; en dev, custom/ est sur l'hôte."""
    _check_mode(mode)
    volumes = names(instance)["volumes"]
    roles = ["dbdata", "documents"] + (["custom"] if mode == "prod" else [])
    return [["volume", "create", volumes[role]] for role in roles]


def _secrets(secrets_dir, *files):
    argv = []
    for name in files:
        argv += ["-v", f"{secrets_dir}/{name}:{SECRET_MOUNT}/{name}:ro"]
    return argv


def _db_env(instance):
    db = f"dolibarr_{instance}"
    return [
        "-e",
        "DOLI_DB_TYPE=mysqli",
        "-e",
        f"DOLI_DB_HOST={names(instance)['db']}",
        "-e",
        f"DOLI_DB_NAME={db}",
        "-e",
        f"DOLI_DB_USER={db}",
        "-e",
        f"DOLI_DB_PASSWORD_FILE={SECRET_MOUNT}/db_password",
    ]


def _restart(mode, engine):
    """En production, le conteneur revient au démarrage de la machine.

    Podman n'a pas de démon : podman-restart.service relance au boot les
    conteneurs « always ». Le démon Docker relance les « unless-stopped »,
    qui respecte un arrêt voulu.
    """
    if mode != "prod":
        return []
    policy = "always" if engine["moteur"] == "podman" else "unless-stopped"
    return ["--restart", policy]


def run_db(instance, pin, secrets_dir, mode, engine):
    """MariaDB de l'instance : base et compte dolibarr_<i>, aucun port."""
    _check_mode(mode)
    n = names(instance)
    db = f"dolibarr_{instance}"
    return (
        ["run", "-d", "--name", n["db"], "--network", n["network"]]
        + _restart(mode, engine)
        + ["-e", f"MARIADB_DATABASE={db}", "-e", f"MARIADB_USER={db}"]
        + ["-e", f"MARIADB_PASSWORD_FILE={SECRET_MOUNT}/db_password"]
        + [
            "-e",
            f"MARIADB_ROOT_PASSWORD_FILE={SECRET_MOUNT}/db_root_password",
        ]
        + _secrets(secrets_dir, "db_password", "db_root_password")
        + ["-v", f"{n['volumes']['dbdata']}:/var/lib/mysql"]
        + [pin["mariadb_image"]]
        + MARIADB_FLAGS
    )


def _account_mapping(mode, engine, host_ids):
    """En dev, www-data doit écrire dans le custom/ de l'hôte.

    Podman sans root : l'hôte devient 33 (www-data) dans le conteneur, qui
    reste root pour lier le port 80. Ailleurs, l'entrée de l'image
    renumérote www-data sur le compte de l'hôte.
    """
    if mode != "dev":
        return []
    if engine["moteur"] == "podman" and engine.get("rootless"):
        return ["--userns=keep-id:uid=33,gid=33", "--user", "0:0"]
    uid, gid = host_ids
    return ["-e", f"WWW_USER_ID={uid}", "-e", f"WWW_GROUP_ID={gid}"]


def _custom_mount(instance, mode, custom_dir):
    if mode == "prod":
        return [
            "-v",
            f"{names(instance)['volumes']['custom']}:/var/www/html/custom",
        ]
    if not custom_dir:
        raise ValueError("development binds custom/ to a host directory")
    return ["-v", f"{custom_dir}:/var/www/html/custom"]


def run_web(
    instance,
    pin,
    secrets_dir,
    init_dir,
    mode,
    engine,
    port,
    url,
    admin_login,
    custom_dir,
    host_ids,
):
    """Le site : l'image s'installe elle-même au premier démarrage.

    `init_dir` porte les crochets d'ERPLibre (docker-init.d), joués une fois
    à la première installation. `url` est l'adresse publique de l'instance.
    La clé cron n'est montée que pour le crochet : donnée à l'entrée de
    l'image (DOLI_CRON_KEY), elle finirait dans ses journaux.
    """
    _check_mode(mode)
    n = names(instance)
    return (
        ["run", "-d", "--name", n["web"], "--network", n["network"]]
        + _restart(mode, engine)
        + ["-p", f"127.0.0.1:{port}:80"]
        + _account_mapping(mode, engine, host_ids)
        + ["-e", "DOLI_INSTALL_AUTO=1"]
        + _db_env(instance)
        + ["-e", f"DOLI_ADMIN_LOGIN={admin_login}"]
        + ["-e", f"DOLI_ADMIN_PASSWORD_FILE={SECRET_MOUNT}/admin_password"]
        + [
            "-e",
            f"DOLI_INSTANCE_UNIQUE_ID_FILE={SECRET_MOUNT}/instance_id",
        ]
        + ["-e", f"DOLI_URL_ROOT={url}"]
        + ["-e", f"DOLI_PROD={1 if mode == 'prod' else 0}"]
        + ["-e", "DOLI_ENABLE_MODULES=Cron"]
        + _secrets(
            secrets_dir,
            "db_password",
            "admin_password",
            "instance_id",
            "cron_key",
        )
        + ["-v", f"{init_dir}:/var/www/scripts/docker-init.d:ro"]
        + ["-v", f"{n['volumes']['documents']}:/var/www/documents"]
        + _custom_mount(instance, mode, custom_dir)
        + [pin["docker_image"]]
    )


def run_cron(
    instance,
    pin,
    secrets_dir,
    mode,
    engine,
    admin_login,
    custom_dir,
    host_ids=None,
):
    """Les tâches planifiées : la même image, cron toutes les 5 minutes.

    Elles lisent custom/ comme le site : les tâches des modules y vivent.
    CRON_KEY est chiffrée en base avec l'identifiant d'instance : le même
    fichier que le site. L'image s'arrête par SIGWINCH, que bash en PID 1
    ignore ; un init qui relaie SIGTERM arrête cron sans attendre SIGKILL.
    """
    _check_mode(mode)
    n = names(instance)
    return (
        ["run", "-d", "--name", n["cron"], "--network", n["network"]]
        + _restart(mode, engine)
        + ["--init", "--stop-signal", "SIGTERM"]
        + _account_mapping(mode, engine, host_ids)
        + ["-e", "DOLI_CRON=1"]
        + _db_env(instance)
        + ["-e", f"DOLI_CRON_KEY_FILE={SECRET_MOUNT}/cron_key"]
        + ["-e", f"DOLI_CRON_USER={admin_login}"]
        + [
            "-e",
            f"DOLI_INSTANCE_UNIQUE_ID_FILE={SECRET_MOUNT}/instance_id",
        ]
        + _secrets(secrets_dir, "db_password", "cron_key", "instance_id")
        + ["-v", f"{n['volumes']['documents']}:/var/www/documents"]
        + _custom_mount(instance, mode, custom_dir)
        + [pin["docker_image"]]
    )
