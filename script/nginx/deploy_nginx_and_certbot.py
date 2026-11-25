#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
import argparse
import logging
import os
import shlex
import subprocess
import sys
import time

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)
_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """

    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Specify argument to create nginx services and run certbot.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--generate_nginx",
        action="store_true",
        help="Will configure odoo reverse-proxy with domain on nginx.",
    )
    parser.add_argument(
        "--run_certbot",
        action="store_true",
        help="Will run certbot with domain on nginx.",
    )
    parser.add_argument(
        "--ssl_exist",
        action="store_true",
        help="The certificate is already created, not supported with --run_certbot.",
    )
    parser.add_argument(
        "--force_ssl_dir",
        help="Change the dir of certificate for this dir. Will contain fullchain.pem and privkey.pem.",
    )
    parser.add_argument(
        "--nginx_conf",
        help="Path of the nginx file to write, instead of"
        " /etc/nginx/sites-available/<main domain>. A file under a"
        " sites-available directory is linked from its sites-enabled.",
    )
    parser.add_argument(
        "--default_server",
        action="store_true",
        help="Mark the listen directives default_server: the site answers"
        " any host name, the VM address or a tunnel included.",
    )
    parser.add_argument(
        "--no_certbot_options",
        action="store_true",
        help="Drop the certbot include and ssl_dhparam lines of the ssl"
        " template, for a certificate given by --force_ssl_dir on a host"
        " without certbot.",
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Separate by ; for multiple domains. Main domain is first on the list.",
    )
    parser.add_argument(
        "--admin_email",
        help="Will configure certbot with admin email to receive information about the certificate.",
    )
    parser.add_argument(
        "--odoo_version",
        default="18.0",
        help="Specify only one version, 12.0 to 18.0",
    )
    parser.add_argument(
        "--default_port_http",
        default=8069,
        help="The default port for http",
    )
    parser.add_argument(
        "--default_port_websocket",
        default=8072,
        help="The default port for websocket (or longpolling)",
    )

    args = parser.parse_args()
    return args


def enabled_link(site_path):
    """Le lien sites-enabled du fichier `site_path`, ou None.

    Seul un fichier rangé dans un répertoire « sites-available » (Debian,
    Ubuntu) a un lien à poser, dans le « sites-enabled » voisin. Ailleurs,
    conf.d par exemple, nginx lit le fichier lui-même."""
    dossier, nom = os.path.split(os.path.normpath(site_path))
    if os.path.basename(dossier) != "sites-available":
        return None
    return os.path.join(os.path.dirname(dossier), "sites-enabled", nom)


def adapt_template(content, default_server=False, no_certbot_options=False):
    """Le gabarit `content` déjà rempli, ajusté par deux options.

    `default_server` ajoute « default_server » aux directives « listen 80 »
    et « listen 443 ssl » : le site répond alors à tout nom d'hôte.
    `no_certbot_options` retire les lignes qui lisent les fichiers de
    certbot (options-ssl-nginx.conf, ssl-dhparams.pem), absents d'un hôte
    où certbot n'est pas installé : nginx -t échouerait sur elles."""
    if default_server:
        content = content.replace(
            "listen 80;", "listen 80 default_server;"
        ).replace("listen 443 ssl;", "listen 443 ssl default_server;")
    if no_certbot_options:
        content = "".join(
            ligne
            for ligne in content.splitlines(keepends=True)
            if "/etc/letsencrypt/options-ssl-nginx.conf" not in ligne
            and "/etc/letsencrypt/ssl-dhparams.pem" not in ligne
        )
    return content


def main():
    config = get_config()

    if " " in config.domain:
        raise ValueError("Cannot support space into domains.")

    lst_domain = config.domain.split(";")
    main_domain = lst_domain[0]
    main_domain_name = main_domain.replace(".", "_")

    # TODO support git, create a commit if exist .git

    if config.ssl_exist:
        template_name = (
            f"./script/nginx/template_nginx_ssl_odoo_{config.odoo_version}.txt"
        )
    else:
        template_name = (
            f"./script/nginx/template_nginx_odoo_{config.odoo_version}.txt"
        )
    if not os.path.exists(template_name):
        raise ValueError(f"Cannot find template path '{template_name}'")

    if config.generate_nginx:
        # TODO check if exist, overwrite it
        site_available_path = (
            config.nginx_conf or f"/etc/nginx/sites-available/{main_domain}"
        )
        site_enabled_path = enabled_link(site_available_path)
        print(f"Create file {site_available_path}")

        with open(template_name, "r") as template:
            content = template.read()
        cmd_lst_domain = " ".join(lst_domain)
        if config.force_ssl_dir:
            content = content.replace(
                "/etc/letsencrypt/live/DOMAIN",
                os.path.normpath(config.force_ssl_dir),
            )
        content = (
            content.replace("DOMAIN", cmd_lst_domain)
            .replace("SERVER_NAME", main_domain_name)
            .replace("8069", str(config.default_port_http))
            .replace("8072", str(config.default_port_websocket))
        )
        content = adapt_template(
            content, config.default_server, config.no_certbot_options
        )
        with open(site_available_path, "w") as template:
            template.write(content)
        if site_enabled_path and not os.path.exists(site_enabled_path):
            os.symlink(site_available_path, site_enabled_path)

    # TODO support both ssl_exist and run_certbot
    if config.ssl_exist and config.run_certbot:
        _logger.error(
            "Cannot run certbot with domain on nginx with feature ssl_exist. Please implement it."
        )
    if config.ssl_exist:
        pass
    elif config.run_certbot:
        if config.generate_nginx:
            time.sleep(10)
        cmd_certbot = certbot_argv(lst_domain, config.admin_email)
        print(shlex.join(cmd_certbot))
        return subprocess.run(cmd_certbot).returncode
    return 0


def certbot_argv(lst_domain, admin_email=None):
    """L'argv de « sudo certbot --nginx » pour les domaines `lst_domain`.

    Passé tel quel à subprocess, sans shell : un domaine ou un courriel n'y
    est jamais interprété. `admin_email` ajoute --email et le mode non
    interactif."""
    argv = ["sudo", "certbot"]
    if admin_email:
        argv += ["--email", admin_email, "--non-interactive", "--agree-tos"]
    argv.append("--nginx")
    for domain in lst_domain:
        argv += ["-d", domain]
    return argv


if __name__ == "__main__":
    sys.exit(main())
