"""
ERPLibre - System dependency installation.

Replaces: script/install/install_debian_dependency.sh
(PostgreSQL, build tools, pyenv deps, selenium deps sections)
"""

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from pyinfra.operations import apt, server

from deploys.env import get_env


def install_system_dependencies():
    """Install all Debian/Ubuntu system dependencies."""
    env = get_env()

    # PostgreSQL & PostGIS
    apt.packages(
        name="Install PostgreSQL and PostGIS",
        packages=["postgresql", "libpq-dev", "postgis"],
        update=True,
        cache_valid_time=3600,
    )

    # Create PostgreSQL user
    server.shell(
        name="Create PostgreSQL user",
        commands=[
            f"sudo -u postgres createuser -s {env['el_user']} 2>/dev/null"
            " || true",
        ],
    )

    # Build tools and development libraries
    apt.packages(
        name="Install build tools and dev libraries",
        packages=[
            "git",
            "build-essential",
            "wget",
            "libxslt-dev",
            "libzip-dev",
            "libldap2-dev",
            "libsasl2-dev",
            "gdebi-core",
            "libffi-dev",
            "libbz2-dev",
            "parallel",
            "pysassc",
            "swig",
            "cmake",
            "portaudio19-dev",
            "libcups2-dev",
            "shfmt",
            "xmlsec1",
        ],
    )

    # MariaDB and FreeTDS
    apt.packages(
        name="Install MariaDB and FreeTDS dev libraries",
        packages=["libmariadbd-dev", "freetds-dev"],
    )

    # pyenv dependencies (Python compilation)
    apt.packages(
        name="Install pyenv build dependencies",
        packages=[
            "make",
            "libssl-dev",
            "zlib1g-dev",
            "libreadline-dev",
            "libsqlite3-dev",
            "curl",
            "llvm",
            "libncurses5-dev",
            "libncursesw5-dev",
            "xz-utils",
            "tk-dev",
            "liblzma-dev",
        ],
    )

    # Selenium dependencies
    apt.packages(
        name="Install Selenium dependencies",
        packages=[
            "libcairo2-dev",
            "python3-dev",
            "pkg-config",
            "libxt-dev",
            "libgirepository1.0-dev",
        ],
    )


if __name__ == "__main__" or "pyinfra" in sys.modules:
    install_system_dependencies()
