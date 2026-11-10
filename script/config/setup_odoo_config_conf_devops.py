#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import configparser
import logging
import os

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

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
DESCRIPTION
    Force config.conf file to has workers 0 and support queue; --channel
    declares extra job channels: queue_job ones, or OCA connector ones on
    Odoo 8 and 9.

SUGGESTION
    ./script/config/setup_odoo_config_conf_devops.py
    ./script/config/setup_odoo_config_conf_devops.py --channel root.ms_graph:1
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--channel",
        action="append",
        default=[],
        metavar="NAME:CAPACITY",
        help="job channel to declare, e.g. root.ms_graph:1; "
        "repeatable. A channel already declared keeps its capacity.",
    )
    args = parser.parse_args()
    for channel in args.channel:
        name, _sep, capacity = channel.partition(":")
        if not name or not capacity.isdigit():
            parser.error(f"--channel expects NAME:CAPACITY, got {channel!r}")
    return args


def channel_name(item):
    """Return the full name queue_job gives the channel declared by
    ``item`` (``name[:capacity[:option...]]``): spaces around the name
    stripped and ``root.`` prefixed to a short name, since queue_job reads
    ``sub`` as ``root.sub``."""
    name = item.partition(":")[0].strip()
    if name != "root" and not name.startswith("root."):
        name = f"root.{name}"
    return name


def add_channels(channels, wanted):
    """Return ``channels`` (queue_job syntax, entries separated by commas
    or line breaks) with each ``wanted`` channel appended unless queue_job
    would read it as a channel already declared. A duplicate is never
    written: queue_job applies the last declaration of a channel, which
    would override the capacity and options of the first.

    The existing text is kept as is; new entries follow it on their own
    line when the value is written one channel per line, else after a
    comma."""
    names = {
        channel_name(item)
        for item in channels.replace("\n", ",").split(",")
        if item.strip()
    }
    added = []
    for channel in wanted:
        name = channel_name(channel)
        if name not in names:
            added.append(channel)
            names.add(name)
    if not added:
        return channels
    existing = channels.rstrip().rstrip(",")
    separator = "\n" if "\n" in existing.strip() else ","
    return separator.join(([existing] if existing.strip() else []) + added)


def odoo_major_version(path=".odoo-version"):
    """Return the major Odoo version that ``path`` names (``18`` for
    ``18.0``), or ``None`` when the file is missing or unreadable."""
    try:
        with open(path) as handle:
            return int(handle.read().strip().split(".")[0])
    except (OSError, ValueError):
        return None


def default_server_wide_modules(major):
    """Return the server-wide modules Odoo ``major`` loads when the config
    names none, as its ``tools/config.py`` defines them. Writing the key
    replaces that default, so it is kept rather than shortened: Odoo 19
    serves /xmlrpc and /jsonrpc without a database only through ``rpc``,
    and Odoo 8 to 10 load ``web_kanban`` there. An unknown version gets
    ``base,web``."""
    if major is None:
        return "base,web"
    if major <= 10:
        return "web,web_kanban"
    if major == 11:
        return "web"
    if major <= 18:
        return "base,web"
    return "base,rpc,web"


def job_runner(major):
    """Return ``(module, section)``: the server-wide module that runs the
    job channels on Odoo ``major`` and the config section it reads them
    from. Odoo 8 and 9 have no queue_job; OCA connector runs the jobs
    there, with the same channel syntax under ``[options-connector]``."""
    if major is not None and major <= 9:
        return "connector", "options-connector"
    return "queue_job", "queue_job"


def main():
    config = get_config()

    # Edit ./config.conf, else /etc/odoo/odoo.conf, else nothing
    has_config_file = True
    config_path = "./config.conf"
    if not os.path.isfile(config_path):
        config_path = "/etc/odoo/odoo.conf"
        if not os.path.isfile(config_path):
            has_config_file = False
    if has_config_file:
        config_parser = configparser.ConfigParser()
        config_parser.read(config_path)

        # Force workers to zero for local running
        if config_parser.has_option("options", "workers"):
            workers = config_parser.get("options", "workers")
            if workers != "0":
                config_parser.set("options", "workers", "0")
        else:
            config_parser.set("options", "workers", "0")

        major = odoo_major_version()
        runner_module, runner_section = job_runner(major)

        # Load the job runner
        if config_parser.has_option("options", "server_wide_modules"):
            server_wide_modules = config_parser.get(
                "options", "server_wide_modules"
            )
            if runner_module not in server_wide_modules:
                config_parser.set(
                    "options",
                    "server_wide_modules",
                    f"{server_wide_modules},{runner_module}",
                )
        else:
            config_parser.set(
                "options",
                "server_wide_modules",
                f"{default_server_wide_modules(major)},{runner_module}",
            )

        # Support job runner size channels
        job_channels = ""
        if config_parser.has_section(runner_section):
            if config_parser.has_option(runner_section, "channels"):
                job_channels = config_parser.get(runner_section, "channels")
        else:
            config_parser.add_section(runner_section)

        if not job_channels:
            job_channels = f"root:{os.cpu_count()}"
        config_parser.set(
            runner_section,
            "channels",
            add_channels(job_channels, config.channel),
        )

        with open(config_path, "w") as configfile:
            config_parser.write(configfile)


if __name__ == "__main__":
    main()
