#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
from datetime import datetime

import requests
import tldextract
from cloudflare import Cloudflare

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
        You need to setup your environment key CLOUDFLARE_API_TOKEN
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--ip", required=False, help="Ip to replace the old ip."
    )
    parser.add_argument(
        "--domain",
        required=False,
        help="DNS name to output his ip and sync.",
    )
    parser.add_argument(
        "--zone_name",
        required=False,
        help="The CloudFlare zone name to check.",
    )
    args = parser.parse_args()
    return args


class ManageCloudFlare:
    @staticmethod
    def get_public_ip():
        r = requests.get(r"https://api.ipify.org")
        ip = r.text
        return ip

    def set_ip_to_domain(self, parser):
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
        if not api_token:
            raise Exception(
                "Missing environment variable CLOUDFLARE_API_TOKEN"
            )
        public_ip = parser.ip
        website_domain = parser.domain
        cf = Cloudflare(api_token=api_token)
        url_extract = tldextract.extract(website_domain)
        url_domain_only = url_extract.top_domain_under_public_suffix
        domain_to_create = url_extract.fqdn
        zones = [a for a in cf.zones.list() if a.name == url_domain_only]
        if not zones:
            raise Exception(
                "Cannot found domain %s on your cloudflare account."
                % url_domain_only
            )
        zone = zones[0]
        # id_zone = zone.account.id
        id_zone = zone.id

        # Comment is limited to 100 char
        records_dns = cf.dns.records.list(
            zone_id=id_zone, name=domain_to_create
        )
        lst_dns = [a for a in records_dns]
        if lst_dns:
            for dns in lst_dns:
                # update comment
                comment = dns.comment
                new_comment = "Updated from ERPLibre at %s" % (datetime.now(),)
                # if comment:
                #     comment += "\n" + new_comment
                # else:
                #     comment = new_comment
                comment = new_comment
                try:
                    record_response = cf.dns.records.edit(
                        zone_id=id_zone,
                        content=public_ip,
                        dns_record_id=dns.id,
                        name=domain_to_create,
                        type="A",
                        comment=comment,
                    )
                except Exception as e:
                    _logger.error(e)
        else:
            try:
                record_response = cf.dns.records.create(
                    zone_id=id_zone,
                    name=domain_to_create,
                    type="A",
                    content=public_ip,
                    comment="Generated with ERPLibre",
                )
            except Exception as e:
                _logger.error(e)


def main():
    config = get_config()
    cl = ManageCloudFlare()
    cl.set_ip_to_domain(config)


if __name__ == "__main__":
    main()
