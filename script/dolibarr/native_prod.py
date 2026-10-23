#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les étapes de l'installation native de PRODUCTION de Dolibarr.

install_native.py les joue quand --mode prod ; les étapes communes
(paquets, PHP, serveur et compte de base) sont les siennes.

Disposition d'une instance <i> :
- code : /opt/erplibre-dolibarr/<i>, exporté du commit épinglé, root et en
  lecture seule ;
- données : /var/lib/erplibre-dolibarr/<i>/documents et sessions, au
  compte système dolibarr_<i> ;
- secrets, clé cron, copie de conf.php, TLS : /etc/erplibre-dolibarr/<i>,
  root, 0700 ;
- PHP-FPM : un pool sous dolibarr_<i>, socket lisible du seul nginx ;
- nginx : un hôte virtuel à l'emplacement de la famille ;
- tâches planifiées : un service oneshot et une minuterie systemd.

L'installation (step1, step2, step5) et l'activation du module Cron
tournent sous dolibarr_<i> ; conf.php finit en 0440 root:dolibarr_<i>, avec
prod à 1. SELinux en mode enforcing est refusé tant que ses contextes ne
sont pas éprouvés sur une machine.
"""

import os
import shlex
import ssl
import time
import urllib.request

from script.dolibarr import (
    install_files,
    install_native,
    packages,
    units,
    web_config,
)
from script.dolibarr.install_native import StepError, t, tail

# Activation du module Cron et pose de CRON_KEY, sous le compte de
# l'instance ; la clé arrive par stdin, jamais par argv.
CRON_PHP = (
    'require "master.inc.php";'
    ' require_once DOL_DOCUMENT_ROOT."/core/lib/admin.lib.php";'
    " $k = trim(fgets(STDIN));"
    ' $r = activateModule("modCron");'
    ' if (!empty($r["errors"])) {'
    ' echo "ERPLIBRE_CRON_FAIL ", implode("; ", $r["errors"]), "\\n"; exit(1); }'
    ' dolibarr_set_const($db, "CRON_KEY", $k, "chaine", 0, "", 0);'
    ' echo "ERPLIBRE_CRON_OK\\n";'
)

INCLUDE_CONF_D = "    include conf.d/*.conf;\n"

# Le contrôle HTTP suit un rechargement de nginx, dont les ouvriers
# sortants ferment les connexions en cours, et un pool PHP-FPM tout juste
# redémarré : la page est redemandée, une seconde d'écart, avant d'échouer.
CHECK_TRIES = 15
CHECK_PAUSE = 1.0


def nologin():
    """Le shell de refus de la distribution."""
    for path in ("/usr/sbin/nologin", "/usr/bin/nologin", "/sbin/nologin"):
        if os.path.exists(path):
            return path
    return "/bin/false"


def http_get(url, host):
    """Corps de la page `url`, demandée avec l'en-tête Host `host`.

    Le certificat n'est pas vérifié : la page d'une autorité locale ou
    d'un certificat pas encore publié doit pouvoir se lire.
    """
    req = urllib.request.Request(url, headers={"Host": host})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            return resp.read(65536).decode("utf-8", "replace")
    except OSError as e:
        return f"ERROR {e}"


def issue_local_cert(directory, names):
    """(certificat, clé, autorité) émis par l'autorité locale d'ERPLibre.

    L'autorité est celle du mandataire inverse : importée une fois dans le
    navigateur, elle vaut pour toutes les instances. Le certificat serveur
    reste dans `directory`, propre à l'instance.
    """
    from script.reverse_proxy import local_cert

    files = local_cert.issue(directory, names, ca_dir=local_cert.DEFAULT_DIR)
    return files["server_crt"], files["server_key"], files["ca_crt"]


def ensure_conf_d_include(text):
    """nginx.conf avec « include conf.d/*.conf; » dans http{}, une fois.

    Arch livre un nginx.conf qui n'inclut aucun dossier de sites. La ligne
    va à la FIN de http{}, avant son accolade fermante en colonne 0 : nginx
    prend pour serveur par défaut le premier déclaré sur un port, et celui
    de la distribution doit le rester. Lève ValueError sans bloc http{}.
    """
    if "include conf.d/*.conf;" in text:
        return text
    debut = text.index("http {")
    fin = text.find("\n}", debut)
    if fin < 0:
        raise ValueError("no closing brace for the http block")
    return text[: fin + 1] + INCLUDE_CONF_D + text[fin + 1 :]


def _sudo_file(runner, path):
    res = runner.probe(["sudo", "cat", path])
    return res[1] if res and res[0] == 0 else None


def _sudo_exists(runner, path):
    res = runner.probe(["sudo", "test", "-e", path])
    return bool(res) and res[0] == 0


def _run(runner, argv, message, **kw):
    code, out = runner.run(argv, **kw)
    if code:
        raise StepError(message, tail(out))
    return out


# ---------------------------------------------------------------------------
# Étapes
# ---------------------------------------------------------------------------


def step_prod_checks(ctx, runner):
    res = runner.probe(["getenforce"])
    if res and res[0] == 0 and res[1].strip() == "Enforcing":
        raise StepError(
            t(
                "SELinux is enforcing: native production is not validated there yet."
            )
        )
    return t("ok")


def _enterprise_linux(runner):
    """Vrai sur EL (Alma, Rocky, RHEL) : %{?rhel} y vaut la version
    majeure, et rien sur Fedora."""
    res = runner.probe(["rpm", "-E", "%{?rhel}"])
    return bool(res and res[0] == 0 and res[1].strip())


def step_certbot(ctx, runner):
    """certbot et son greffon nginx, en mode TLS certbot seulement.

    EL 9/10 ne les ont que dans EPEL : epel-release s'installe avant eux.
    """
    if ctx.args.tls != "certbot":
        return t("not needed")
    groups = [packages.certbot_packages(ctx.family)]
    if ctx.family == "dnf" and _enterprise_linux(runner):
        groups.insert(0, ["epel-release"])
    changed = install_native.install_missing(ctx, runner, groups)
    return t("ok") if changed else t("already done")


def step_source(ctx, runner):
    """Le checkout porte le commit épinglé : il en sera exporté."""
    if not os.path.exists(
        os.path.join(ctx.checkout, "htdocs", "version.inc.php")
    ):
        _run(
            runner,
            ["./script/manifest/update_manifest_local_dolibarr.sh"],
            t("Cannot fetch the Dolibarr source."),
            cwd=install_native.ROOT,
        )
    commit = ctx.pin["commit"]
    res = runner.probe(
        ["git", "-C", ctx.checkout, "cat-file", "-e", f"{commit}^{{commit}}"]
    )
    if not (res and res[0] == 0) and not runner.dry_run:
        raise StepError(
            t("The checkout lacks the pinned commit %s.") % commit[:7]
        )
    return f"{ctx.pin['version']} ({commit[:7]})"


def step_user(ctx, runner):
    res = runner.probe(["id", "-u", ctx.user])
    if res and res[0] == 0:
        return t("already done")
    _run(
        runner,
        [
            "sudo",
            "useradd",
            "--system",
            "--user-group",
            "--no-create-home",
            "--home-dir",
            ctx.state,
            "--shell",
            nologin(),
            ctx.user,
        ],
        t("Cannot create the system account."),
    )
    return ctx.user


def step_code(ctx, runner):
    if _sudo_exists(runner, f"{ctx.htdocs}/version.inc.php"):
        return t("already done")
    _run(
        runner,
        ["sudo", "mkdir", "-p", ctx.code_root],
        t("Cannot create %s.") % ctx.code_root,
    )
    pipeline = (
        "set -o pipefail; "
        f"git -C {shlex.quote(ctx.checkout)} archive --format=tar"
        f" {ctx.pin['commit']} | sudo tar -x -C {shlex.quote(ctx.code_root)}"
    )
    _run(runner, ["bash", "-c", pipeline], t("Cannot export the pinned code."))
    for argv in (
        ["sudo", "chown", "-R", "root:root", ctx.code_root],
        ["sudo", "chmod", "-R", "go-w", ctx.code_root],
    ):
        _run(runner, argv, t("Cannot secure %s.") % ctx.code_root)
    return ctx.code_root


def step_dirs(ctx, runner):
    for argv in (
        [
            "sudo",
            "install",
            "-d",
            "-o",
            "root",
            "-g",
            ctx.user,
            "-m",
            "750",
            ctx.state,
        ],
        [
            "sudo",
            "install",
            "-d",
            "-o",
            ctx.user,
            "-g",
            ctx.user,
            "-m",
            "750",
            ctx.data_root,
        ],
        [
            "sudo",
            "install",
            "-d",
            "-o",
            ctx.user,
            "-g",
            ctx.user,
            "-m",
            "700",
            f"{ctx.state}/sessions",
        ],
        ["sudo", "install", "-d", "-m", "700", ctx.etc],
    ):
        _run(runner, argv, t("Cannot create %s.") % argv[-1])
    return t("ok")


def step_install(ctx, runner):
    if install_native.installed_version(ctx, runner):
        return t("already done")
    conf = f"{ctx.htdocs}/conf/conf.php"
    current = _sudo_file(runner, conf)
    if current and current.strip():
        raise StepError(
            t(
                "%s already configures another instance;"
                " one checkout serves one instance."
            )
            % conf
        )
    forced = f"{ctx.htdocs}/install/install.forced.php"
    admin = ctx.secrets["ADMIN_PASSWORD"]
    values = {
        "db_type": ctx.db_type,
        "db_host": ctx.db_host,
        "db_port": ctx.db_port,
        "db_name": ctx.db_name,
        "db_user": ctx.db_user,
        "db_pass": ctx.secrets["DB_PASSWORD"],
        "data_root": ctx.data_root,
        "admin_login": ctx.args.admin_login,
        "admin_pass": admin,
    }
    lang = ctx.args.lang
    install_dir = f"{ctx.htdocs}/install"
    as_user = ["sudo", "-u", ctx.user, "php"]
    try:
        _run(
            runner,
            [
                "sudo",
                "install",
                "-o",
                ctx.user,
                "-g",
                ctx.user,
                "-m",
                "600",
                "/dev/null",
                conf,
            ],
            t("Cannot write %s") % conf,
        )
        runner.write(
            forced,
            install_files.render_install_forced(values),
            mode=0o600,
            sudo=True,
            owner=ctx.user,
            group=ctx.user,
        )
        outputs = []
        for step in (
            ["step1.php", "set", lang, ctx.htdocs, "", ctx.url],
            ["step2.php", "set", lang],
            ["step5.php", "", "", lang, "set"],
        ):
            code, out = runner.run(as_user + step, cwd=install_dir)
            outputs.append(out)
            if code:
                raise StepError(t("%s failed.") % step[0], tail(out))
        if runner.dry_run:
            return t("ok")
        written = _sudo_file(runner, conf) or ""
        if f"$dolibarr_main_db_type='{ctx.db_type}';" not in written:
            raise StepError(
                t("step1.php did not write conf.php."), tail(outputs[0])
            )
        if not install_native.installed_version(ctx, runner):
            raise StepError(
                t("The database holds no installed version."),
                tail(outputs[-1]),
            )
        if not _sudo_exists(runner, f"{ctx.data_root}/install.lock"):
            raise StepError(
                t("step5.php did not lock the install."), tail(outputs[-1])
            )
    finally:
        # Il porte les mots de passe : il ne survit jamais à l'installation.
        runner.run(["sudo", "rm", "-f", forced])
        runner.run(
            [
                "sudo",
                "find",
                "/tmp",
                "-maxdepth",
                "1",
                "-name",
                "dolibarr_install.log",
                "-user",
                ctx.user,
                "-delete",
            ]
        )
    return t("ok")


def step_harden(ctx, runner):
    """prod à 1, HTTPS forcé derrière TLS, conf.php en lecture seule.

    step1.php ignore le verrou du dossier de données : htdocs/install.lock
    le ferme. La copie de conf.php garde la clé qui chiffre des valeurs.
    """
    conf = f"{ctx.htdocs}/conf/conf.php"
    text = _sudo_file(runner, conf)
    if text is None and not runner.dry_run:
        raise StepError(t("Cannot read %s.") % conf)
    https = "0" if ctx.args.tls == "none" else "1"
    new = install_files.set_conf_values(
        text or "", {"prod": "1", "force_https": https}
    )
    runner.write(
        conf, new, mode=0o440, sudo=True, owner="root", group=ctx.user
    )
    runner.write(
        f"{ctx.htdocs}/install.lock",
        "Locked by ERPLibre after the install.\n",
        mode=0o444,
        sudo=True,
    )
    runner.write(f"{ctx.etc}/conf.php.bak", new, mode=0o400, sudo=True)
    return t("ok")


def step_cron(ctx, runner):
    key = ctx.secrets["CRON_KEY"]
    code, out = runner.run(
        ["sudo", "-u", ctx.user, "php", "-r", CRON_PHP],
        input=key + "\n",
        cwd=ctx.htdocs,
    )
    if not runner.dry_run and (code or "ERPLIBRE_CRON_OK" not in out):
        raise StepError(t("Cannot enable the Cron module."), tail(out))
    service, timer = units.cron_unit_names(ctx.instance)
    env_file = f"{ctx.etc}/cron.env"
    runner.write(env_file, units.render_cron_env(key), mode=0o600, sudo=True)
    runner.write(
        f"/etc/systemd/system/{service}",
        units.render_cron_service(
            ctx.instance, ctx.user, ctx.code_root, ctx.state, env_file
        ),
        mode=0o644,
        sudo=True,
    )
    runner.write(
        f"/etc/systemd/system/{timer}",
        units.render_cron_timer(ctx.instance),
        mode=0o644,
        sudo=True,
    )
    for argv in (
        ["sudo", "systemctl", "daemon-reload"],
        ["sudo", "systemctl", "enable", "--now", timer],
    ):
        _run(runner, argv, t("Cannot enable the scheduled jobs."))
    return timer


def step_pool(ctx, runner):
    layout = packages.fpm_layout(ctx.family, ctx.php_version or "")
    pool = f"{layout['pool_dir']}/erplibre-dolibarr-{ctx.instance}.conf"
    runner.write(
        pool,
        web_config.render_prod_fpm(
            ctx.instance,
            ctx.user,
            layout["web_user"],
            ctx.socket,
            ctx.code_root,
            ctx.state,
        ),
        mode=0o644,
        sudo=True,
    )
    _run(
        runner,
        ["sudo", layout["binary"], "-t"],
        t("PHP-FPM rejects the pool."),
    )
    for argv in (
        ["sudo", "systemctl", "enable", "--now", layout["unit"]],
        ["sudo", "systemctl", "reload-or-restart", layout["unit"]],
    ):
        _run(runner, argv, t("PHP-FPM does not start."))
    return pool


def _local_tls(ctx, runner):
    """Certificat de l'autorité locale, copié sous /etc (clé en 0600).

    Rend les chemins sous /etc. À blanc, rien n'est émis : ces chemins
    suffisent au rendu du site.
    """
    target = f"{ctx.etc}/tls"
    crt, key = f"{target}/server.crt", f"{target}/server.key"
    if runner.dry_run:
        runner.out(f"      [dry-run] local certificate for {ctx.args.domain}")
        return crt, key
    work = os.path.join(
        os.path.expanduser("~"), ".erplibre", "dolibarr_tls", ctx.instance
    )
    src_crt, src_key, ca = issue_local_cert(work, [ctx.args.domain])
    _run(
        runner,
        ["sudo", "install", "-d", "-m", "700", target],
        t("Cannot create %s.") % target,
    )
    with open(src_crt, encoding="utf-8") as f:
        runner.write(crt, f.read(), mode=0o644, sudo=True)
    with open(src_key, encoding="utf-8") as f:
        runner.write(key, f.read(), mode=0o600, sudo=True)
    runner.out(f"      {t('Authority to import in the browser:')} {ca}")
    return crt, key


def step_vhost(ctx, runner):
    site, link = packages.nginx_site(ctx.family, ctx.instance)
    if packages.nginx_needs_include(ctx.family):
        _run(
            runner,
            ["sudo", "mkdir", "-p", "/etc/nginx/conf.d"],
            t("Cannot create %s.") % "/etc/nginx/conf.d",
        )
        main = _sudo_file(runner, "/etc/nginx/nginx.conf")
        if main is not None:
            new = ensure_conf_d_include(main)
            if new != main:
                runner.write(
                    "/etc/nginx/nginx.conf", new, mode=0o644, sudo=True
                )
    cert = key = None
    if ctx.args.tls == "local":
        cert, key = _local_tls(ctx, runner)
    runner.write(
        site,
        web_config.render_prod_nginx(
            ctx.instance,
            ctx.htdocs,
            ctx.args.domain,
            ctx.socket,
            ctx.args.tls,
            cert=cert,
            key=key,
        ),
        mode=0o644,
        sudo=True,
    )
    if link:
        _run(
            runner,
            ["sudo", "ln", "-sf", site, link],
            t("Cannot enable the site."),
        )
    _run(
        runner, ["sudo", "nginx", "-t"], t("nginx rejects the configuration.")
    )
    for argv in (
        ["sudo", "systemctl", "enable", "--now", "nginx"],
        ["sudo", "systemctl", "reload", "nginx"],
    ):
        _run(runner, argv, t("nginx does not start."))
    if ctx.args.tls == "certbot":
        argv = [
            "sudo",
            "certbot",
            "--nginx",
            "-d",
            ctx.args.domain,
            "--non-interactive",
            "--agree-tos",
            "--redirect",
        ]
        argv += (
            ["-m", ctx.args.email]
            if ctx.args.email
            else ["--register-unsafely-without-email"]
        )
        _run(runner, argv, t("certbot could not obtain the certificate."))
    return site


def step_check(ctx, runner):
    """La base et le code répondent depuis PHP, puis nginx sert la page."""
    code, out = runner.run(
        ["sudo", "-u", ctx.user, "php", "-r", install_native.CHECK_PHP],
        cwd=ctx.htdocs,
    )
    if runner.dry_run:
        return t("ok")
    if code or "ERPLIBRE_CHECK " not in out:
        raise StepError(t("Dolibarr does not answer from PHP."), tail(out))
    scheme = "http" if ctx.args.tls == "none" else "https"
    from script.dolibarr.run import served_version

    page = ""
    for attempt in range(CHECK_TRIES):
        if attempt:
            time.sleep(CHECK_PAUSE)
        page = http_get(f"{scheme}://127.0.0.1/", ctx.args.domain)
        version = served_version(page)
        if version:
            return f"Dolibarr {version} — {ctx.url}"
    raise StepError(t("nginx does not serve the login page."), tail(page))


def step_record(ctx, runner):
    service, timer = units.cron_unit_names(ctx.instance)
    entry = {
        "mode": "prod",
        "runtime": "native",
        "db": ctx.db,
        "db_name": ctx.db_name,
        "host": "local",
        "url": ctx.url,
        "domain": ctx.args.domain,
        "tls": ctx.args.tls,
        "code_root": ctx.code_root,
        "data_root": ctx.data_root,
        "state_dir": ctx.state,
        "user": ctx.user,
        "commit": ctx.pin["commit"],
        "version": ctx.pin["version"],
        "admin_login": ctx.args.admin_login,
        "cron_timer": timer,
        "secrets": f"file:{ctx.secrets_file}",
    }
    return install_native.record_entry(ctx, runner, entry)


STEPS = (
    ("Checks", install_native.step_preflight),
    ("Production checks", step_prod_checks),
    ("System packages", install_native.step_packages),
    ("certbot", step_certbot),
    ("PHP and its extensions", install_native.step_php),
    ("Database server", install_native.step_db_service),
    ("Database and account", install_native.step_database),
    ("Dolibarr source", step_source),
    ("System account", step_user),
    ("Code in /opt", step_code),
    ("Data directories", step_dirs),
    ("Headless install", step_install),
    ("Hardening", step_harden),
    ("Scheduled jobs", step_cron),
    ("PHP-FPM pool", step_pool),
    ("nginx site", step_vhost),
    ("Check from PHP and HTTP", step_check),
    ("Instance record", step_record),
)
