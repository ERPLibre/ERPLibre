#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Installer Dolibarr en conteneurs : l'image officielle et MariaDB.

    ./script/dolibarr/install_container.py --mode dev --instance erp \\
        --port 8081 [--engine podman] [--yes] [--dry-run]

Docker OU Podman, choisi par container_runtime (celui qui répond sans sudo
d'abord, --engine pour trancher). Aucun outil compose : réseau, volumes et
conteneurs par des commandes simples (container_plan). L'image s'installe
elle-même au premier démarrage ; le crochet d'ERPLibre (10-erplibre.php)
ferme ce qu'elle laisse ouvert.

Tout ce que l'instance garde sur l'hôte vit dans
~/.local/share/ERPLibre/dolibarr/<instance> : secrets/ (un fichier 0600
par secret, dossier 0700), init.d/ (le crochet), custom/ (dév). Les
secrets sont écrits AVANT le premier conteneur et relus à chaque relance :
une installation interrompue reprend avec les mêmes. Ce qui existe déjà
(image, réseau, volume, conteneur) est repris, jamais recréé.

Le mot de passe de l'administrateur vient de EL_DOLIBARR_ADMIN_PASSWORD,
ou il est généré ; jamais d'un argument.
"""

import argparse
import os
import sys
import time

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import (  # noqa: E402
    container_plan,
    install_native,
    lib_dolibarr,
    native_prod,
)
from script.dolibarr.install_native import StepError, t, tail  # noqa: E402
from script.dolibarr.run import port_is_free, served_version  # noqa: E402

HOOK = os.path.join(os.path.dirname(__file__), "container", "10-erplibre.php")

# Chaque secret, par nom de fichier, et sa longueur ; lettres et chiffres
# seulement : l'entrée de l'image les relit par un echo non protégé et les
# range entre apostrophes dans conf.php.
SECRETS = {
    "db_password": 32,
    "db_root_password": 32,
    "admin_password": 20,
    "cron_key": 32,
    "instance_id": 32,
}

# La première installation de l'image prend 70 à 100 s ; une relance, moins
# d'une seconde.
WAIT_TRIES = 150
WAIT_PAUSE = 2.0

http_get = native_prod.http_get


class Context:
    """Ce que les étapes partagent. Rien ici n'est affiché tel quel."""

    def __init__(self, args, pin, fiche):
        self.args = args
        self.pin = pin
        self.fiche = fiche
        self.engine = {
            "moteur": fiche["moteur"],
            "rootless": bool(fiche["sans_sudo"] and fiche.get("rootless")),
        }
        self.instance = args.instance
        self.mode = args.mode
        self.state = install_native.state_dir(args.instance)
        self.secrets_dir = os.path.join(self.state, "secrets")
        self.init_dir = os.path.join(self.state, "init.d")
        self.custom_dir = (
            os.path.join(self.state, "custom") if args.mode == "dev" else None
        )
        self.url = f"http://127.0.0.1:{args.port}"
        self.names = container_plan.names(args.instance)
        self.version = container_plan.image_version(pin["docker_image"])


def engine(ctx, runner, args, message):
    """Lance `args` sur le moteur ; StepError avec `message` s'il refuse."""
    code, out = runner.run(container_plan_command(ctx, args))
    if code:
        raise StepError(message, tail(out))
    return out


def container_plan_command(ctx, args):
    from script.todo import container_runtime

    return container_runtime.commande(ctx.fiche, args)


def exists(ctx, runner, args):
    res = runner.probe(container_plan_command(ctx, args))
    return bool(res) and res[0] == 0


# ---------------------------------------------------------------------------
# Étapes
# ---------------------------------------------------------------------------


def step_preflight(ctx, runner):
    try:
        known = lib_dolibarr.load_registry(install_native.ROOT)
    except lib_dolibarr.RegistryError as e:
        raise StepError(t("Dolibarr registry unreadable: %s") % e)
    if ctx.instance in known:
        raise StepError(t("This instance already exists: %s") % ctx.instance)
    running = exists(
        ctx,
        runner,
        [
            "container",
            "inspect",
            "--format",
            "{{.State.Running}}",
            ctx.names["web"],
        ],
    )
    if not running and not port_is_free(ctx.args.port):
        raise StepError(t("Port %s is already in use.") % ctx.args.port)
    return ctx.fiche["moteur"]


def step_images(ctx, runner):
    pulled = []
    for ref in (ctx.pin["mariadb_image"], ctx.pin["docker_image"]):
        if not exists(ctx, runner, ["image", "inspect", ref]):
            engine(ctx, runner, ["pull", ref], t("Cannot pull %s.") % ref)
            pulled.append(ref)
    return t("ok") if pulled else t("already done")


def ensure_container_secrets(ctx, runner):
    """Relit les secrets de l'instance, crée ceux qui manquent (0600).

    Le mot de passe saisi (EL_DOLIBARR_ADMIN_PASSWORD) l'emporte sur celui
    du fichier : il ne sert qu'à la première installation.
    """
    typed = os.environ.get(lib_dolibarr.ENV_ADMIN_PASSWORD)
    if not runner.dry_run:
        os.makedirs(ctx.secrets_dir, mode=0o700, exist_ok=True)
        os.chmod(ctx.secrets_dir, 0o700)
    for name, length in SECRETS.items():
        path = os.path.join(ctx.secrets_dir, name)
        current = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                current = f.read().strip()
        value = current or install_native.generate_secret(length)
        if name == "admin_password" and typed:
            value = typed
        if value != current:
            runner.write(path, value + "\n", mode=0o600)
    return t("ok")


def step_files(ctx, runner):
    ensure_container_secrets(ctx, runner)
    with open(HOOK, encoding="utf-8") as f:
        hook = f.read()
    if not runner.dry_run:
        os.makedirs(ctx.init_dir, mode=0o755, exist_ok=True)
        if ctx.custom_dir:
            os.makedirs(ctx.custom_dir, mode=0o755, exist_ok=True)
    runner.write(
        os.path.join(ctx.init_dir, os.path.basename(HOOK)), hook, mode=0o644
    )
    return ctx.state


def step_network(ctx, runner):
    made = []
    net = ctx.names["network"]
    if not exists(ctx, runner, ["network", "inspect", net]):
        engine(
            ctx,
            runner,
            container_plan.network_create(ctx.instance),
            t("Cannot create %s.") % net,
        )
        made.append(net)
    for argv in container_plan.volume_creates(ctx.instance, ctx.mode):
        if not exists(ctx, runner, ["volume", "inspect", argv[-1]]):
            engine(ctx, runner, argv, t("Cannot create %s.") % argv[-1])
            made.append(argv[-1])
    return t("ok") if made else t("already done")


def _container(ctx, runner, name, run_argv):
    """Lance le conteneur `name`, ou le démarre s'il existe arrêté."""
    res = runner.probe(
        container_plan_command(
            ctx,
            ["container", "inspect", "--format", "{{.State.Running}}", name],
        )
    )
    if res and res[0] == 0:
        if res[1].strip() == "true":
            return t("already done")
        engine(ctx, runner, ["start", name], t("Cannot start %s.") % name)
        return t("container started")
    engine(ctx, runner, run_argv, t("Cannot start %s.") % name)
    return name


def step_db(ctx, runner):
    return _container(
        ctx,
        runner,
        ctx.names["db"],
        container_plan.run_db(
            ctx.instance, ctx.pin, ctx.secrets_dir, ctx.mode, ctx.engine
        ),
    )


def step_web(ctx, runner):
    return _container(
        ctx,
        runner,
        ctx.names["web"],
        container_plan.run_web(
            ctx.instance,
            ctx.pin,
            ctx.secrets_dir,
            ctx.init_dir,
            ctx.mode,
            ctx.engine,
            ctx.args.port,
            ctx.url,
            ctx.args.admin_login,
            ctx.custom_dir,
            (os.getuid(), os.getgid()),
        ),
    )


def step_wait(ctx, runner):
    """Le site sert-il sa page de connexion ? La première fois, l'image
    crée sa base avant d'ouvrir Apache."""
    if runner.dry_run:
        return t("ok")
    page = ""
    for attempt in range(WAIT_TRIES):
        if attempt:
            time.sleep(WAIT_PAUSE)
        page = http_get(f"{ctx.url}/", "127.0.0.1")
        version = served_version(page)
        if version:
            return f"Dolibarr {version} — {ctx.url}"
    raise StepError(t("The site does not serve the login page."), tail(page))


def step_cron(ctx, runner):
    return _container(
        ctx,
        runner,
        ctx.names["cron"],
        container_plan.run_cron(
            ctx.instance,
            ctx.pin,
            ctx.secrets_dir,
            ctx.mode,
            ctx.engine,
            ctx.args.admin_login,
            ctx.custom_dir,
            (os.getuid(), os.getgid()),
        ),
    )


def step_record(ctx, runner):
    entry = {
        "mode": ctx.mode,
        "runtime": "container",
        "engine": ctx.fiche["moteur"],
        "db": "mariadb",
        "host": "local",
        "url": ctx.url,
        "port": ctx.args.port,
        "version": ctx.version,
        "image": ctx.pin["docker_image"],
        "containers": [ctx.names[r] for r in ("db", "web", "cron")],
        "state_dir": ctx.state,
        "admin_login": ctx.args.admin_login,
        "secrets": f"dir:{ctx.secrets_dir}",
    }
    if ctx.custom_dir:
        entry["custom_dir"] = ctx.custom_dir
    return install_native.record_entry(ctx, runner, entry)


STEPS = (
    ("Checks", step_preflight),
    ("Container images", step_images),
    ("Instance files", step_files),
    ("Network and volumes", step_network),
    ("Database container", step_db),
    ("Site container", step_web),
    ("First start", step_wait),
    ("Scheduled jobs container", step_cron),
    ("Instance record", step_record),
)


def choose_engine(fiches, wanted=None):
    """La fiche du moteur à piloter, ou None si aucun ne répond."""
    from script.todo import container_runtime

    usable = [f for f in fiches if container_runtime.utilisable(f)]
    if wanted:
        usable = [f for f in usable if f["moteur"] == wanted]
    name = container_runtime.moteur_par_defaut(usable)
    return next((f for f in usable if f["moteur"] == name), None)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("dev",), required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--engine", choices=("docker", "podman"))
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv=None, engines=None, runner=None):
    args = build_parser().parse_args(argv)
    if not lib_dolibarr.valid_instance_name(args.instance):
        print(
            t(
                "Invalid name: lowercase letters, digits and _,"
                " starting with a letter."
            )
        )
        return 2
    if not lib_dolibarr.valid_login(args.admin_login):
        print(
            t(
                "Invalid login: letters, digits and . _ @ -,"
                " starting with a letter or a digit."
            )
        )
        return 2
    if lib_dolibarr.parse_port(str(args.port), None) is None:
        print(t("Invalid port: a number from 1024 to 65535."))
        return 2
    try:
        pin = lib_dolibarr.read_pin(install_native.ROOT)
    except lib_dolibarr.PinError as e:
        print(t("Dolibarr pin unreadable: %s") % e)
        return 2
    if engines is None:
        from script.todo import container_runtime

        engines = container_runtime.etats()
    fiche = choose_engine(engines, args.engine)
    if fiche is None:
        print(
            t("Docker / Podman is not offered here: %s")
            % t(lib_dolibarr.NO_ENGINE)
        )
        return 1
    runner = runner or install_native.Runner(dry_run=args.dry_run)
    ctx = Context(args, pin, fiche)
    status = install_native.run_steps(ctx, runner, STEPS)
    if status == 0 and not args.dry_run:
        print()
        print(t("Dolibarr %s installed: %s") % (ctx.version, ctx.url))
        print(
            t("Login: %s — password in %s")
            % (
                args.admin_login,
                os.path.join(ctx.secrets_dir, "admin_password"),
            )
        )
    return status


if __name__ == "__main__":
    # Comme install_native : tout passe par le module du paquet, dont
    # StepError est la classe que run_steps attrape.
    from script.dolibarr import install_container as _package

    sys.exit(_package.main())
