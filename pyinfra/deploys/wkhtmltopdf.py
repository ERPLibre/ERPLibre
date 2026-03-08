"""
ERPLibre - wkhtmltopdf installation.

Replaces: the wkhtmltopdf section of install_debian_dependency.sh
Automatically detects Ubuntu/Debian version to choose the correct .deb.
"""

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from pyinfra import host
from pyinfra.operations import server
from pyinfra.facts.server import LinuxDistribution


# wkhtmltopdf URLs per distribution
WKHTMLTOPDF_URLS = {
    # Ubuntu 22.04+
    "jammy": "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb",
    # Ubuntu 20.04
    "focal": "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.focal_amd64.deb",
    # Ubuntu 18.04
    "bionic": "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.bionic_amd64.deb",
    # Debian bookworm
    "bookworm": "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb",
    # Debian bullseye (fallback)
    "bullseye": "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bullseye_amd64.deb",
}


def _get_wkhtmltopdf_url():
    """Determine the wkhtmltopdf URL based on the distribution."""
    dist_info = host.get_fact(LinuxDistribution)
    release = dist_info.get("release_meta", {}).get(
        "DISTRIB_CODENAME", ""
    )

    if release in WKHTMLTOPDF_URLS:
        return WKHTMLTOPDF_URLS[release]

    # Fallback: recent Ubuntu -> jammy, otherwise bullseye
    name = dist_info.get("name", "").lower()
    if "ubuntu" in name or "mint" in name:
        return WKHTMLTOPDF_URLS["jammy"]
    return WKHTMLTOPDF_URLS["bullseye"]


def install_wkhtmltopdf():
    """Install wkhtmltopdf if requested."""
    if not host.data.get("install_wkhtmltopdf", True):
        return

    url = _get_wkhtmltopdf_url()
    filename = url.rsplit("/", 1)[-1]

    server.shell(
        name="Install wkhtmltopdf",
        commands=[
            # Skip if already installed
            "dpkg -s wkhtmltox > /dev/null 2>&1 && exit 0",
            f"cd /tmp && wget -q -nc {url}",
            f"gdebi --n /tmp/{filename}",
            "ln -fs /usr/local/bin/wkhtmltopdf /usr/bin/wkhtmltopdf",
            "ln -fs /usr/local/bin/wkhtmltoimage /usr/bin/wkhtmltoimage",
        ],
        _sudo=True,
    )


if __name__ == "__main__" or "pyinfra" in sys.modules:
    install_wkhtmltopdf()
