#!./.venv/bin/python
import argparse
import logging

import CloudFlare
import requests

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
        Can update all old_ip to new_ip.
        When auto_sync is enable:
        Check zone and name on cloudflare and compare with public ip, update all old ip with new ip if different.
        You need your profile in file ~/.cloudflare/cloudflare.cfg
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="The profile of CloudFlare, check ~/.cloudflare/cloudflare.cfg.",
    )
    parser.add_argument(
        "--old_ip", required=False, help="Ip to search to update."
    )
    parser.add_argument(
        "--new_ip", required=False, help="Ip to replace the old ip."
    )
    parser.add_argument(
        "--dns_name",
        required=False,
        help="DNS name to output his ip and sync.",
    )
    parser.add_argument(
        "--zone_name",
        required=False,
        help="The CloudFlare zone name to check.",
    )
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--raw", action="store_true")
    parser.add_argument(
        "--auto_sync",
        action="store_true",
        help=(
            "Need this to use DNS name and zone name to sync public ip to"
            " CloudFlare."
        ),
    )
    args = parser.parse_args()
    return args


class ManageCloudFlare:
    def __init__(self, profile, debug=False, raw=False):
        self.cf = CloudFlare.CloudFlare(profile=profile, debug=debug, raw=raw)
        self.raw = raw

    @staticmethod
    def get_public_ip():
        r = requests.get(r"https://api.ipify.org")
        ip = r.text
        return ip

    def get_ip_cloudflare(self, zone_name, name):
        """Return ip from a zone and domain"""
        zone = self.cf.zones.get(params={"name": zone_name})
        lst_zone = [a.get("id") for a in zone]
        for zone_id in lst_zone:
            lst_result_dns = self.cf.zones.dns_records.get(zone_id)
            for result_dns in lst_result_dns:
                if (
                    result_dns.get("type") == "A"
                    and result_dns.get("name") == name
                ):
                    return result_dns.get("content")

    def edit_cloudflare(self, old_ip, delete=False, new_ip=""):
        """Change ip of zone and name"""

        # TODO support smaller range
        params = {"per_page": 500}
        zones = self.cf.zones.get(params=params)
        result = zones.get("result") if self.raw else zones
        lst_zone = [a.get("id") for a in result]
        for zone_id in lst_zone:
            # dns_records = cf.zones.dns_records.export.get(zone_id)
            result_dns = self.cf.zones.dns_records.get(zone_id)
            dns_records = result_dns.get("result") if self.raw else result_dns
            for dns in dns_records:
                if dns.get("content") == old_ip:
                    if delete:
                        _logger.info(f"Delete {dns.get('name')}")
                        r = self.cf.zones.dns_records.delete(
                            zone_id, dns.get("id")
                        )
                    elif new_ip:
                        _logger.info(
                            f"Update {dns.get('name')} with ip {new_ip}, old"
                            f" ip was {old_ip}"
                        )
                        dns_record = {
                            "name": dns.get("name"),
                            "type": dns.get("type"),
                            "content": new_ip,
                        }
                        r = self.cf.zones.dns_records.post(
                            zone_id, data=dns_record
                        )
                        r = self.cf.zones.dns_records.delete(
                            zone_id, dns.get("id")
                        )


def main():
    config = get_config()
    cl = ManageCloudFlare(config.profile, debug=config.debug)
    if config.auto_sync:
        configured_ip = cl.get_ip_cloudflare(config.zone_name, config.dns_name)
        actual_ip = cl.get_public_ip()
        if configured_ip != actual_ip:
            cl.edit_cloudflare(configured_ip, new_ip=actual_ip)
        else:
            _logger.info(f"Nothing to do, same ip {actual_ip}")
    else:
        cl.edit_cloudflare(
            config.old_ip, delete=config.delete, new_ip=config.new_ip
        )


if __name__ == "__main__":
    main()
