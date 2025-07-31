#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
import argparse
import logging
import os
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
        "--domain",
        required=True,
        help="Separate by ; for multiple domains. Main domain is first on the list.",
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
        site_available_path = f"/etc/nginx/sites-available/{main_domain}"
        site_enabled_path = f"/etc/nginx/sites-enabled/{main_domain}"
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
        with open(site_available_path, "w") as template:
            template.write(content)
        if not os.path.exists(site_enabled_path):
            cmd_syslink = f"ln -s {site_available_path} {site_enabled_path}"
            os.system(cmd_syslink)

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
        cmd_lst_domain = " -d " + " -d ".join(lst_domain)
        cmd_certbot = "sudo certbot --nginx%s" % cmd_lst_domain
        print(cmd_certbot)
        os.system(cmd_certbot)


if __name__ == "__main__":
    main()
