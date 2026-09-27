#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Installer Dolibarr en natif : nginx + PHP-FPM + MariaDB ou PostgreSQL.

    ./script/dolibarr/install_native.py --mode dev --db mariadb \\
        --instance dolibarr [--port 8080] [--admin-login admin] \\
        [--lang fr_FR] [--yes] [--dry-run]

Le mot de passe de l'administrateur vient de EL_DOLIBARR_ADMIN_PASSWORD ;
absent, il est généré. Les secrets passent par stdin ou par des fichiers
0600, jamais par argv : /proc/<pid>/cmdline est lisible par tout compte.

Les étapes sont numérotées et chacune constate avant d'agir : relancer
reprend là où une installation s'est arrêtée. La première qui échoue
arrête tout et dit pourquoi ; rien n'est défait.

Développement : le code est le checkout épinglé dolibarr/dolibarr, les
données et la configuration web vivent sous
~/.local/share/ERPLibre/dolibarr/<instance>/, et nginx comme PHP-FPM
tourneront sous le compte du développeur (script/dolibarr/run.py). Un
checkout ne sert qu'une instance : conf/conf.php est à chemin fixe.
"""

import argparse
import json
import os
import platform
import secrets
import shlex
import string
import subprocess
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import (  # noqa: E402
    install_files,
    lib_dolibarr,
    packages,
    web_config,
)
from script.todo import todo_install  # noqa: E402

ROOT = new_path

# Extensions sans lesquelles Dolibarr ne fonctionne pas, ou fonctionne mal
# en silence : sans openssl, dolEncrypt range les valeurs en clair.
REQUIRED_EXTENSIONS = (
    "gd",
    "curl",
    "intl",
    "simplexml",
    "dom",
    "zip",
    "mbstring",
    "calendar",
    "json",
    "openssl",
)

# Alphabet des secrets générés : ni « \\ » ni « " », que l'installeur de
# Dolibarr réécrit dans conf.php, ni rien qu'un shell ou du SQL interprète.
_SECRET_ALPHABET = string.ascii_letters + string.digits


def t(key):
    """Traduction si l'outillage TODO est là ; la clé sinon."""
    try:
        from script.todo.todo_i18n import t as _t
    except Exception:
        return key
    return _t(key)


class StepError(Exception):
    """Une étape a échoué ; `detail` porte la sortie utile, déjà filtrée."""

    def __init__(self, message, detail=""):
        super().__init__(message)
        self.detail = detail


class Runner:
    """Seul point qui exécute. En essai à blanc, il affiche et rend (0, "").

    Les sondes en lecture (probe) tournent aussi à blanc tant qu'elles ne
    demandent pas sudo : elles rendent le plan fidèle sans rien changer.
    """

    def __init__(self, dry_run=False, out=print):
        self.dry_run = dry_run
        self.out = out

    def run(self, argv, input=None, cwd=None, env=None):
        shown = shlex.join(argv)
        if input is not None:
            shown += "  < stdin"
        if self.dry_run:
            self.out(f"      [dry-run] $ {shown}")
            return 0, ""
        return self._exec(argv, input, cwd, env)

    def probe(self, argv, cwd=None):
        """Commande en lecture seule. None si à blanc et qu'elle veut sudo."""
        if self.dry_run and argv and argv[0] == "sudo":
            return None
        return self._exec(argv, None, cwd, None)

    def write(
        self, path, text, mode=0o600, sudo=False, owner=None, group=None
    ):
        """Écrit `text` dans `path` ; le contenu passe par stdin sous sudo.

        Sous sudo, `owner` et `group` fixent le propriétaire du fichier.
        """
        if self.dry_run:
            self.out(f"      [dry-run] write {path} ({oct(mode)})")
            return
        if sudo:
            argv = ["sudo", "install", "-m", f"{mode:o}"]
            if owner:
                argv += ["-o", owner]
            if group:
                argv += ["-g", group]
            code, out = self._exec(
                argv + ["/dev/stdin", path],
                text,
                None,
                None,
            )
            if code:
                raise StepError(t("Cannot write %s") % path, out)
            return
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, mode)

    def _exec(self, argv, input, cwd, env):
        full_env = None
        if env:
            full_env = dict(os.environ, **env)
        try:
            r = subprocess.run(
                argv,
                input=input,
                cwd=cwd,
                env=full_env,
                capture_output=True,
                text=True,
            )
        except OSError as e:
            return 127, str(e)
        return r.returncode, (r.stdout or "") + (r.stderr or "")


def generate_secret(length=32):
    return "".join(secrets.choice(_SECRET_ALPHABET) for _ in range(length))


def state_dir(instance):
    """~/.local/share/ERPLibre/dolibarr/<instance>, XDG_DATA_HOME respecté."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(base, "ERPLibre", "dolibarr", instance)


def default_lang():
    try:
        from script.todo.todo_i18n import get_lang

        return "fr_FR" if get_lang() == "fr" else "en_US"
    except Exception:
        return "en_US"


def tail(text, lines=20):
    return "\n".join((text or "").strip().splitlines()[-lines:])


# ---------------------------------------------------------------------------
# Contexte
# ---------------------------------------------------------------------------


class Context:
    """Ce que les étapes partagent. Rien ici n'est affiché tel quel."""

    def __init__(self, args, facts, pin):
        self.args = args
        self.facts = facts
        self.pin = pin
        self.family = facts["family"]
        self.instance = args.instance
        self.db = args.db
        self.state = state_dir(args.instance)
        self.data_root = os.path.join(self.state, "documents")
        self.run_dir = os.path.join(self.state, "run")
        self.secrets_file = os.path.join(self.state, "secrets.env")
        self.checkout = os.path.join(ROOT, pin["path"])
        self.htdocs = os.path.join(self.checkout, "htdocs")
        self.url = f"http://127.0.0.1:{args.port}"
        self.db_name = f"dolibarr_{args.instance}"
        self.db_user = f"dolibarr_{args.instance}"
        self.db_host = "localhost" if args.db == "mariadb" else "127.0.0.1"
        self.db_port = 3306 if args.db == "mariadb" else 5432
        self.db_type = "mysqli" if args.db == "mariadb" else "pgsql"
        self.php_version = None
        self.secrets = {}
        self.prod = args.mode == "prod"
        if self.prod:
            # Production : code exporté et en lecture seule dans /opt,
            # données sous /var/lib, secrets et TLS sous /etc (root, 0700).
            self.user = f"dolibarr_{args.instance}"
            self.code_root = f"/opt/erplibre-dolibarr/{args.instance}"
            self.htdocs = f"{self.code_root}/htdocs"
            self.state = f"/var/lib/erplibre-dolibarr/{args.instance}"
            self.data_root = f"{self.state}/documents"
            self.etc = f"/etc/erplibre-dolibarr/{args.instance}"
            self.secrets_file = f"{self.etc}/secrets.env"
            self.socket = f"/run/erplibre-dolibarr-{args.instance}.sock"
            scheme = "http" if args.tls == "none" else "https"
            self.url = f"{scheme}://{args.domain}"


def parse_secrets(text):
    """{NOM: valeur} du texte d'un fichier secrets.env."""
    out = {}
    for line in (text or "").splitlines():
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            out[name.strip()] = value
    return out


def read_secrets(path):
    """{NOM: valeur} d'un fichier secrets.env, {} s'il n'existe pas."""
    try:
        with open(path, encoding="utf-8") as f:
            return parse_secrets(f.read())
    except FileNotFoundError:
        return {}


# ---------------------------------------------------------------------------
# Étapes
# ---------------------------------------------------------------------------


def step_preflight(ctx, runner):
    ok, why = lib_dolibarr.native_support(
        ctx.facts["system"],
        ctx.family,
        ctx.facts["is_nixos"],
        ctx.facts["has_systemd"],
        ctx.args.mode,
    )
    if not ok:
        raise StepError(t("Native is not offered here: %s") % t(why))
    if ctx.facts["system"] != "Linux":
        raise StepError(t("This installer handles Linux for now."))
    try:
        known = lib_dolibarr.load_registry(ROOT)
    except lib_dolibarr.RegistryError as e:
        raise StepError(t("Dolibarr registry unreadable: %s") % e)
    if ctx.instance in known:
        raise StepError(t("This instance already exists: %s") % ctx.instance)
    return t("ok")


def installed_packages(runner, family, names):
    """Les paquets de `names` déjà installés (sondes sans sudo)."""
    found = []
    for name in names:
        if family == "apt-get":
            res = runner.probe(["dpkg-query", "-W", "-f=${Status}", name])
            ok = res and res[0] == 0 and "install ok installed" in res[1]
        elif family == "pacman":
            res = runner.probe(["pacman", "-Q", name])
            ok = res and res[0] == 0
        else:
            res = runner.probe(["rpm", "-q", "--whatprovides", name])
            ok = res and res[0] == 0
        if ok:
            found.append(name)
    return found


def install_missing(ctx, runner, groups):
    """Installe ce qui manque de chaque groupe de paquets ; True si installé.

    Une commande par groupe, dans l'ordre : un groupe peut ouvrir le dépôt
    où le suivant se trouve. Les commandes sont montrées puis confirmées en
    une fois, sauf --yes ; un refus ou un échec lève StepError.
    """
    commands = []
    for group in groups:
        present = installed_packages(runner, ctx.family, group)
        missing = [p for p in group if p not in present]
        if missing:
            commands.append(todo_install.install_command(missing, ctx.family))
    if not commands:
        return False
    refresh = todo_install.refresh_command(ctx.family)
    if refresh:
        commands.insert(0, refresh)
    for cmd in commands:
        runner.out(f"      {t('Will execute:')} {shlex.join(cmd)}")
    if not ctx.args.yes and not runner.dry_run:
        answer = input(f"      {t('Install these packages? (y/N): ')}")
        if answer.strip().lower() not in ("y", "yes", "o", "oui"):
            raise StepError(t("Packages refused, nothing installed."))
    for cmd in commands:
        code, out = runner.run(cmd)
        if code:
            raise StepError(t("Package installation failed."), tail(out))
    return True


def step_packages(ctx, runner):
    changed = install_missing(
        ctx, runner, [packages.packages_for(ctx.family, ctx.db)]
    )
    ini = packages.extensions_ini(ctx.family, ctx.db)
    if ini:
        path, text = ini
        current = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                current = f.read()
        if current != text:
            runner.write(path, text, mode=0o644, sudo=True)
            changed = True
    return t("ok") if changed else t("already done")


def php_version(runner):
    res = runner.probe(
        ["php", "-r", 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;']
    )
    if not res or res[0]:
        return None
    return res[1].strip()


def _version_tuple(text):
    return tuple(int(x) for x in text.split(".")[:2])


def step_php(ctx, runner):
    version = php_version(runner)
    if version is None:
        if runner.dry_run:
            return t("checked after the packages")
        raise StepError(t("php does not answer."))
    ctx.php_version = version
    low, high = ctx.pin["php_min"], ctx.pin["php_max"]
    if not (
        _version_tuple(low) <= _version_tuple(version) <= _version_tuple(high)
    ):
        raise StepError(
            t("PHP %s is outside what Dolibarr supports (%s to %s).")
            % (version, low, high)
        )
    res = runner.probe(["php", "-m"])
    loaded = {
        line.strip().lower() for line in (res[1] if res else "").splitlines()
    }
    driver = "mysqli" if ctx.db == "mariadb" else "pgsql"
    missing = [e for e in (driver,) + REQUIRED_EXTENSIONS if e not in loaded]
    if missing:
        raise StepError(t("PHP extensions missing: %s") % ", ".join(missing))
    return f"PHP {version}"



def _service_active(runner, unit):
    res = runner.probe(["systemctl", "is-active", "--quiet", unit])
    return bool(res) and res[0] == 0


def _root_path_exists(runner, path):
    res = runner.probe(["sudo", "test", "-e", path])
    return None if res is None else res[0] == 0


def db_init_commands(family, db, runner):
    """Commandes d'initialisation du serveur de base, avant de le démarrer.

    Debian/Ubuntu initialisent au postinst ; Fedora/EL et openSUSE au
    premier démarrage de MariaDB ; Arch jamais. PostgreSQL : initdb sur
    Fedora/EL et Arch, automatique ailleurs.
    """
    if family == "pacman" and db == "mariadb":
        if _root_path_exists(runner, "/var/lib/mysql/mysql") is False:
            return [
                [
                    "sudo",
                    "mariadb-install-db",
                    "--user=mysql",
                    "--basedir=/usr",
                    "--datadir=/var/lib/mysql",
                ]
            ]
    if family == "pacman" and db == "postgresql":
        if (
            _root_path_exists(runner, "/var/lib/postgres/data/PG_VERSION")
            is False
        ):
            return [
                [
                    "sudo",
                    "-u",
                    "postgres",
                    "initdb",
                    "--locale=C.UTF-8",
                    "--encoding=UTF8",
                    "--auth-local=peer",
                    "--auth-host=scram-sha-256",
                    "-D",
                    "/var/lib/postgres/data",
                ]
            ]
    if family == "dnf" and db == "postgresql":
        if (
            _root_path_exists(runner, "/var/lib/pgsql/data/PG_VERSION")
            is False
        ):
            return [["sudo", "postgresql-setup", "--initdb"]]
    return []


def db_unit(db):
    return "mariadb" if db == "mariadb" else "postgresql"


def step_db_service(ctx, runner):
    unit = db_unit(ctx.db)
    if _service_active(runner, unit):
        return t("already done")
    for cmd in db_init_commands(ctx.family, ctx.db, runner) + [
        ["sudo", "systemctl", "enable", "--now", unit]
    ]:
        code, out = runner.run(cmd)
        if code:
            raise StepError(t("Database server does not start."), tail(out))
    return t("ok")


def mariadb_sql(db_name, user, password):
    """SQL de création idempotent. Le compte est « @'localhost' » : le
    compte anonyme que posent certaines distributions refuserait un
    « @'%' » en local. Jeu de caractères explicite : celui que
    l'installeur de Dolibarr déclare dans conf.php."""
    return (
        f"CREATE DATABASE IF NOT EXISTS `{db_name}`"
        " CHARACTER SET utf8 COLLATE utf8_unicode_ci;\n"
        f"CREATE USER IF NOT EXISTS '{user}'@'localhost'"
        f" IDENTIFIED BY '{password}';\n"
        f"ALTER USER '{user}'@'localhost' IDENTIFIED BY '{password}';\n"
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{user}'@'localhost';\n"
        "FLUSH PRIVILEGES;\n"
    )


def postgresql_role_sql(user, password):
    """Rôle idempotent : créé, ou son mot de passe remis."""
    return (
        "DO $$ BEGIN\n"
        f"  IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN\n"
        f"    ALTER ROLE {user} LOGIN PASSWORD '{password}';\n"
        "  ELSE\n"
        f"    CREATE ROLE {user} LOGIN PASSWORD '{password}';\n"
        "  END IF;\n"
        "END $$;\n"
    )


def _psql(sql_args):
    return [
        "sudo",
        "-u",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
    ] + sql_args


def pg_hba_needs_password_line(family):
    """Fedora/EL et openSUSE initialisent avec « ident » pour 127.0.0.1 :
    un mot de passe par TCP y échoue tant qu'une ligne scram-sha-256 ne
    précède pas les lignes ident."""
    return family in ("dnf", "zypper")


def pg_hba_lines(db_name, user):
    return (
        f"host {db_name} {user} 127.0.0.1/32 scram-sha-256\n"
        f"host {db_name} {user} ::1/128 scram-sha-256\n"
    )


# Longueur de chaque secret d'une instance ; la clé cron n'existe qu'en
# production, où une minuterie systemd lance les tâches.
SECRET_LENGTHS = {"DB_PASSWORD": 32, "ADMIN_PASSWORD": 20}
PROD_SECRET_LENGTHS = {"CRON_KEY": 32}


def ensure_secrets(ctx, runner):
    """Complète ctx.secrets et les écrit, avant qu'une étape n'en use un.

    Relancée après un échec, l'installation reprend les MÊMES valeurs :
    step_database réaligne le compte de la base sur le mot de passe du
    fichier, et conf.php garde celui qu'il a reçu. Tous naissent ici,
    ensemble, et sont écrits avant que la base soit touchée.
    """
    wanted = dict(SECRET_LENGTHS)
    if ctx.prod:
        wanted.update(PROD_SECRET_LENGTHS)
    for name, length in wanted.items():
        if not ctx.secrets.get(name):
            ctx.secrets[name] = generate_secret(length)
    save_secrets(ctx, runner)


def save_secrets(ctx, runner):
    """Écrit ctx.secrets dans secrets.env (0600).

    En production le fichier est sous /etc, écrit par sudo ; son dossier
    est créé ici.
    """
    lines = "".join(f"{k}={v}\n" for k, v in sorted(ctx.secrets.items()))
    if ctx.prod:
        code, out = runner.run(["sudo", "install", "-d", "-m", "700", ctx.etc])
        if code:
            raise StepError(t("Cannot create %s.") % ctx.etc, tail(out))
        runner.write(ctx.secrets_file, lines, mode=0o600, sudo=True)
        return
    if not runner.dry_run:
        os.makedirs(ctx.state, mode=0o700, exist_ok=True)
    runner.write(ctx.secrets_file, lines, mode=0o600)


def step_database(ctx, runner):
    ensure_secrets(ctx, runner)
    password = ctx.secrets["DB_PASSWORD"]
    if ctx.db == "mariadb":
        code, out = runner.run(
            ["sudo", "mariadb"],
            input=mariadb_sql(ctx.db_name, ctx.db_user, password),
        )
        if code:
            raise StepError(t("Cannot create the database."), tail(out))
        return t("ok")
    code, out = runner.run(
        _psql(["-q"]), input=postgresql_role_sql(ctx.db_user, password)
    )
    if code:
        raise StepError(t("Cannot create the database."), tail(out))
    res = runner.probe(
        _psql(
            [
                "-Atc",
                f"SELECT 1 FROM pg_database WHERE datname = '{ctx.db_name}'",
            ]
        )
    )
    if not (res and res[0] == 0 and res[1].strip() == "1"):
        code, out = runner.run(
            _psql(["-q"]),
            input=(
                f"CREATE DATABASE {ctx.db_name} OWNER {ctx.db_user}"
                " ENCODING 'UTF8' TEMPLATE template0;\n"
            ),
        )
        if code:
            raise StepError(t("Cannot create the database."), tail(out))
    if pg_hba_needs_password_line(ctx.family):
        res = runner.probe(_psql(["-Atc", "SHOW hba_file"]))
        hba = res[1].strip() if res and res[0] == 0 else None
        if hba or not runner.dry_run:
            if not hba:
                raise StepError(t("Cannot find pg_hba.conf."))
            _add_hba_lines(ctx, runner, hba)
    return t("ok")


def _add_hba_lines(ctx, runner, hba):
    lines = pg_hba_lines(ctx.db_name, ctx.db_user)
    res = runner.probe(["sudo", "cat", hba])
    current = res[1] if res and res[0] == 0 else ""
    if lines.splitlines()[0] in current:
        return
    runner.write(hba, lines + current, mode=0o600, sudo=True)
    runner.run(["sudo", "chown", "postgres:postgres", hba])
    code, out = runner.run(["sudo", "systemctl", "reload", "postgresql"])
    if code:
        raise StepError(t("PostgreSQL does not reload."), tail(out))


def step_source(ctx, runner):
    head = os.path.join(ctx.htdocs, "version.inc.php")
    if not os.path.exists(head):
        code, out = runner.run(
            ["./script/manifest/update_manifest_local_dolibarr.sh"], cwd=ROOT
        )
        if code:
            raise StepError(t("Cannot fetch the Dolibarr source."), tail(out))
        if runner.dry_run:
            return t("ok")
    res = runner.probe(["git", "-C", ctx.checkout, "rev-parse", "HEAD"])
    commit = res[1].strip() if res and res[0] == 0 else ""
    if commit == ctx.pin["commit"]:
        return f"{ctx.pin['version']} ({commit[:7]})"
    return t("checkout at %s, pin %s") % (
        commit[:7] or "?",
        ctx.pin["commit"][:7],
    )


def step_dirs(ctx, runner):
    for path, mode in (
        (ctx.state, 0o700),
        (ctx.data_root, 0o750),
    ):
        if runner.dry_run:
            runner.out(f"      [dry-run] mkdir {path} ({oct(mode)})")
            continue
        os.makedirs(path, mode=mode, exist_ok=True)
        os.chmod(path, mode)
    return t("ok")


def installed_version(ctx, runner):
    """MAIN_VERSION_LAST_INSTALL de la base, ou None si pas installée."""
    query = (
        "SELECT value FROM llx_const"
        " WHERE name = 'MAIN_VERSION_LAST_INSTALL' AND entity = 0"
    )
    if ctx.db == "mariadb":
        res = runner.probe(
            ["sudo", "mariadb", "-N", "-D", ctx.db_name, "-e", query]
        )
    else:
        res = runner.probe(_psql(["-d", ctx.db_name, "-Atc", query]))
    if not res or res[0]:
        return None
    return res[1].strip() or None


def step_install(ctx, runner):
    if installed_version(ctx, runner):
        return t("already done")
    conf = os.path.join(ctx.htdocs, "conf", "conf.php")
    if os.path.exists(conf) and os.path.getsize(conf) > 0:
        raise StepError(
            t(
                "%s already configures another instance;"
                " one checkout serves one instance."
            )
            % conf
        )
    forced = os.path.join(ctx.htdocs, "install", "install.forced.php")
    admin_password = ctx.secrets["ADMIN_PASSWORD"]
    values = {
        "db_type": ctx.db_type,
        "db_host": ctx.db_host,
        "db_port": ctx.db_port,
        "db_name": ctx.db_name,
        "db_user": ctx.db_user,
        "db_pass": ctx.secrets["DB_PASSWORD"],
        "data_root": ctx.data_root,
        "admin_login": ctx.args.admin_login,
        "admin_pass": admin_password,
    }
    install_dir = os.path.join(ctx.htdocs, "install")
    lang = ctx.args.lang
    try:
        runner.write(conf, "", mode=0o600)
        runner.write(forced, install_files.render_install_forced(values))
        # Les codes de sortie des étapes ne disent rien : chacune se juge à
        # ce qu'elle a écrit, puis l'installation au contenu de la base.
        steps = (
            ["php", "step1.php", "set", lang, ctx.htdocs, "", ctx.url],
            ["php", "step2.php", "set", lang],
            ["php", "step5.php", "", "", lang, "set"],
        )
        outputs = []
        for argv in steps:
            code, out = runner.run(argv, cwd=install_dir)
            outputs.append(out)
            if code:
                raise StepError(t("%s failed.") % argv[1], tail(out))
        if runner.dry_run:
            return t("ok")
        with open(conf, encoding="utf-8") as f:
            written = f.read()
        if f"$dolibarr_main_db_type='{ctx.db_type}';" not in written:
            raise StepError(
                t("step1.php did not write conf.php."), tail(outputs[0])
            )
        if not installed_version(ctx, runner):
            raise StepError(
                t("The database holds no installed version."),
                tail(outputs[-1]),
            )
        if not os.path.exists(os.path.join(ctx.data_root, "install.lock")):
            raise StepError(
                t("step5.php did not lock the install."), tail(outputs[-1])
            )
    finally:
        # Il porte les mots de passe : il ne survit jamais à l'installation.
        if not runner.dry_run and os.path.exists(forced):
            os.remove(forced)
        _remove_install_log(runner)
    return t("ok")


def _remove_install_log(runner):
    """L'installeur écrit /tmp/dolibarr_install.log, lisible par tous."""
    path = "/tmp/dolibarr_install.log"
    if runner.dry_run:
        return
    try:
        if os.stat(path).st_uid == os.getuid():
            os.remove(path)
    except OSError:
        pass


def step_lock(ctx, runner):
    """htdocs/install.lock, et une copie de conf.php hors du checkout.

    step1.php ignore le verrou du dossier de données : sans celui de
    htdocs, il réécrirait conf.php après l'installation, clé d'instance
    comprise. Non suivi par git, ce fichier empêche aussi « repo sync »
    d'effacer le checkout en silence. La copie de conf.php garde la clé
    qui chiffre des valeurs en base.
    """
    lock = os.path.join(ctx.htdocs, "install.lock")
    if not os.path.exists(lock):
        runner.write(
            lock, "Locked by ERPLibre after the install.\n", mode=0o444
        )
    conf = os.path.join(ctx.htdocs, "conf", "conf.php")
    if not runner.dry_run:
        with open(conf, encoding="utf-8") as f:
            text = f.read()
        runner.write(os.path.join(ctx.state, "conf.php"), text, mode=0o600)
    return t("ok")


def step_web(ctx, runner):
    for path in web_config.run_dirs(ctx.run_dir):
        if runner.dry_run:
            runner.out(f"      [dry-run] mkdir {path}")
            continue
        os.makedirs(path, mode=0o700, exist_ok=True)
    runner.write(
        os.path.join(ctx.run_dir, "php-fpm.conf"),
        web_config.render_dev_fpm(ctx.run_dir),
        mode=0o600,
    )
    runner.write(
        os.path.join(ctx.run_dir, "nginx.conf"),
        web_config.render_dev_nginx(ctx.run_dir, ctx.htdocs, ctx.args.port),
        mode=0o600,
    )
    return t("ok")


CHECK_PHP = (
    'require "master.inc.php";'
    ' $r = $db->query("SELECT value FROM ".MAIN_DB_PREFIX."const'
    " WHERE name = 'MAIN_VERSION_LAST_INSTALL'\");"
    " $o = $db->fetch_object($r);"
    ' echo "ERPLIBRE_CHECK ", DOL_VERSION, " ", $o ? $o->value : "-", "\\n";'
)


def step_check(ctx, runner):
    """master.inc.php inclus depuis htdocs : code, conf.php et base à la
    fois. Le code de sortie ne suffit pas ; la ligne témoin, si."""
    code, out = runner.run(["php", "-r", CHECK_PHP], cwd=ctx.htdocs)
    if runner.dry_run:
        return t("ok")
    marker = [x for x in out.splitlines() if x.startswith("ERPLIBRE_CHECK ")]
    if code or not marker:
        raise StepError(t("Dolibarr does not answer from PHP."), tail(out))
    _, version, installed = marker[0].split(" ", 2)
    if installed == "-":
        raise StepError(t("Dolibarr answers, but reads no installed version."))
    return f"Dolibarr {version}"


def step_record(ctx, runner):
    entry = {
        "mode": ctx.args.mode,
        "runtime": "native",
        "db": ctx.db,
        "db_name": ctx.db_name,
        "host": "local",
        "url": ctx.url,
        "port": ctx.args.port,
        "code_root": ctx.checkout,
        "data_root": ctx.data_root,
        "state_dir": ctx.state,
        "commit": ctx.pin["commit"],
        "version": ctx.pin["version"],
        "admin_login": ctx.args.admin_login,
        "secrets": f"file:{ctx.secrets_file}",
    }
    return record_entry(ctx, runner, entry)


def record_entry(ctx, runner, entry):
    """Inscrit `entry` au registre des instances, sous private/."""
    registry = os.path.join(ROOT, lib_dolibarr.REGISTRY)
    if runner.dry_run:
        runner.out(f"      [dry-run] record {ctx.instance} in {registry}")
        return t("ok")
    try:
        data = {"instances": lib_dolibarr.load_registry(ROOT)}
    except lib_dolibarr.RegistryError as e:
        raise StepError(t("Dolibarr registry unreadable: %s") % e)
    data["instances"][ctx.instance] = entry
    os.makedirs(os.path.dirname(registry), mode=0o700, exist_ok=True)
    runner.write(registry, json.dumps(data, indent=4, sort_keys=True) + "\n")
    return t("ok")


STEPS = (
    ("Checks", step_preflight),
    ("System packages", step_packages),
    ("PHP and its extensions", step_php),
    ("Database server", step_db_service),
    ("Database and account", step_database),
    ("Dolibarr source", step_source),
    ("Data directories", step_dirs),
    ("Headless install", step_install),
    ("Install lock", step_lock),
    ("Web configuration", step_web),
    ("Check from PHP", step_check),
    ("Instance record", step_record),
)


def host_facts():
    system = platform.system()
    family = todo_install.family() if system == "Linux" else None
    return {
        "system": system,
        "family": family,
        "is_nixos": todo_install.os_id() == "nixos",
        "has_systemd": os.path.isdir("/run/systemd/system"),
    }


def run_steps(ctx, runner, steps=STEPS):
    """Joue les étapes ; rend 0, ou 1 à la première qui échoue."""
    total = len(steps)
    for i, (label, step) in enumerate(steps, start=1):
        try:
            result = step(ctx, runner)
        except StepError as e:
            runner.out(f"[{i}/{total}] {t(label)}: {t('FAILED')} — {e}")
            if e.detail:
                runner.out(e.detail)
            runner.out(t("Step failed, stopping here."))
            runner.out(
                t("Nothing was undone: running again resumes at this step.")
            )
            return 1
        runner.out(f"[{i}/{total}] {t(label)}: {result}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument("--mode", choices=("dev", "prod"), required=True)
    parser.add_argument("--db", choices=packages.DATABASES, required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--lang", default=None)
    parser.add_argument("--domain")
    parser.add_argument(
        "--tls", choices=("certbot", "local", "none"), default="none"
    )
    parser.add_argument("--email")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv=None, facts=None, runner=None):
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
    if args.mode == "prod" and not web_config.valid_domain(args.domain):
        print(t("Production needs a valid domain name (--domain)."))
        return 2
    args.lang = args.lang or default_lang()
    try:
        pin = lib_dolibarr.read_pin(ROOT)
    except lib_dolibarr.PinError as e:
        print(t("Dolibarr pin unreadable: %s") % e)
        return 2
    runner = runner or Runner(dry_run=args.dry_run)
    ctx = Context(args, facts or host_facts(), pin)
    steps = STEPS
    if ctx.prod:
        from script.dolibarr import native_prod

        steps = native_prod.STEPS
        res = runner.probe(["sudo", "cat", ctx.secrets_file])
        ctx.secrets = parse_secrets(res[1]) if res and res[0] == 0 else {}
    else:
        ctx.secrets = read_secrets(ctx.secrets_file)
    typed = os.environ.get(lib_dolibarr.ENV_ADMIN_PASSWORD)
    if typed:
        ctx.secrets["ADMIN_PASSWORD"] = typed
    status = run_steps(ctx, runner, steps)
    if status == 0 and not args.dry_run:
        print()
        print(t("Dolibarr %s installed: %s") % (pin["version"], ctx.url))
        print(
            t("Login: %s — password in %s")
            % (args.admin_login, ctx.secrets_file)
        )
    return status


if __name__ == "__main__":
    # Lancé comme script, ce fichier est __main__ : native_prod importe
    # script.dolibarr.install_native, un second module dont StepError est
    # une autre classe, que run_steps d'ici laisserait passer. Tout passe
    # donc par le module du paquet.
    from script.dolibarr import install_native as _package

    sys.exit(_package.main())
