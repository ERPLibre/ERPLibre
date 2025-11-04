#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

UNIT_TEMPLATE = """[Unit]
Description=ERPLibre for {user}
Requires=postgresql.service
After=network.target network-online.target postgresql.service

[Service]
Type=simple
SyslogIdentifier={user}
PermissionsStartOnly=true
User={user}
Group={user}
Restart=always
RestartSec=5
PIDFile={home_erplibre}/.venv.erplibre/service.pid
ExecStart={home_erplibre}/run.sh{EXEC_PARAM}
WorkingDirectory={home_erplibre}
StandardOutput=journal+console

[Install]
WantedBy=multi-user.target
"""


def ensure_root():
    if os.geteuid() != 0:
        sys.exit("❌ This script must be run as root (use sudo or root).")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def w_cmd(param: str, arg: str = None) -> str:
    if not arg:
        if type(arg) is str:
            return ""
        return param
    return f"{param} {arg}"


def main():
    parser = argparse.ArgumentParser(
        description="Create and enable a SystemD service for ERPLibre (Python equivalent of the bash script)."
    )

    # Exposed variables as configurable parameters
    parser.add_argument(
        "--user",
        required=True,
        help="Linux user running the service (e.g. erplibre)",
    )
    parser.add_argument(
        "--home-erplibre",
        help="Path to erplibre directory, workspace root path.",
    )
    parser.add_argument("--port", help="Application port (for information).")
    parser.add_argument(
        "--database",
        help="Database name to run only with it (for information).",
    )
    parser.add_argument(
        "--config-name",
        help="Service name (and systemd file name without .service). Default: user",
    )

    # Utility flags
    parser.add_argument(
        "--no-enable",
        action="store_true",
        help="Do not enable service on boot.",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Do not restart the service after setup.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without changing the system.",
    )
    args = parser.parse_args()

    ensure_root()

    # Default paths and fallback values (same logic as in the bash script)
    el_user = args.user
    el_home_erplibre = args.home_erplibre or os.getcwd()
    el_config_name = args.config_name or f"erplibre_{el_user}_{os.path.basename(os.getcwd())}"
    exec_param = (
        " "
        + f" {w_cmd("-d", args.database or "")} {w_cmd("-p", args.port or "")}".strip()
    )

    # Render the systemd service file content
    unit_content = UNIT_TEMPLATE.format(
        user=el_user,
        home_erplibre=el_home_erplibre,
        EXEC_PARAM=exec_param,
    )

    unit_dest_path = Path(f"/etc/systemd/system/{el_config_name}.service")

    print("* Final systemd file location:", unit_dest_path)

    if args.dry_run:
        print("\n--- GENERATED CONTENT ---\n")
        print(unit_content)
        print("\n--- END ---")
        print("\n(dry-run) No files written, no systemctl commands executed.")
        return

    # Write temporary unit file
    unit_dest_path.write_text(unit_content, encoding="utf-8")

    # chmod 755
    print("* Setting permissions to 755")
    unit_dest_path.chmod(
        stat.S_IRUSR
        | stat.S_IWUSR
        | stat.S_IXUSR
        | stat.S_IRGRP
        | stat.S_IXGRP
        | stat.S_IROTH
        | stat.S_IXOTH
    )

    # chown root:root
    print("* Changing owner to root:root")
    os.chown(unit_dest_path, 0, 0)

    # Sanity checks
    if not Path(el_home_erplibre).exists():
        print(f"⚠️  Warning: {el_home_erplibre} does not exist.")
    if not Path(el_home_erplibre, "run.sh").exists():
        print(f"⚠️  Warning: {el_home_erplibre}/run.sh does not exist.")

    # Reload systemd and enable service
    print("* Reloading systemd daemon")
    run(["systemctl", "daemon-reload"])

    if not args.no_enable:
        print(f"* Enabling service at boot: {el_config_name}.service")
        run(["systemctl", "enable", f"{el_config_name}.service"])
    else:
        print("* (skip) enable step")

    if not args.no_restart:
        print(f"* Restarting service: {el_config_name}.service")
        run(["systemctl", "restart", f"{el_config_name}.service"])
    else:
        print("* (skip) restart step")

    # Summary (equivalent of bash echo block)
    print("\n-----------------------------------------------------------")
    print("Done! ERPLibre service created and started. Details:")
    print(f"Port: {args.port}")
    print(f"Service user: {el_user}")
    print(f"Systemd file: {unit_dest_path}")
    print(f"Start:   systemctl start {el_config_name}")
    print(f"Stop:    systemctl stop {el_config_name}")
    print(f"Restart: systemctl restart {el_config_name}")
    print(f"Status:  systemctl status {el_config_name}")
    print(f"Logs:    journalctl -feu {el_config_name}")
    print("-----------------------------------------------------------")


if __name__ == "__main__":
    main()
