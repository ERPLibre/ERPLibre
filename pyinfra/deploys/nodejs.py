"""
ERPLibre - Node.js and npm packages installation.

Replaces: the Node.js section of install_debian_dependency.sh
"""

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from pyinfra.operations import apt, server

from deploys.env import get_env


def install_nodejs():
    """Install Node.js via NodeSource and global npm packages."""
    env = get_env()

    # NodeSource repository prerequisites
    apt.packages(
        name="Install NodeSource prerequisites",
        packages=["ca-certificates", "curl", "gnupg"],
    )

    # Add NodeSource repository (Node 20.x)
    server.shell(
        name="Add NodeSource GPG key and repository",
        commands=[
            "mkdir -p /etc/apt/keyrings",
            "curl -fsSL"
            " https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key"
            " | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg --yes",
            'echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg]'
            " https://deb.nodesource.com/node_20.x"
            ' nodistro main"'
            " > /etc/apt/sources.list.d/nodesource.list",
        ],
        _sudo=True,
    )

    # Install Node.js
    apt.packages(
        name="Install Node.js",
        packages=["nodejs"],
        update=True,
        latest=True,
    )

    # Global npm packages
    server.shell(
        name="Install global npm packages (rtlcss, less)",
        commands=[
            "npm install npm@latest -g",
            "npm install -g rtlcss",
            "npm install -g less",
        ],
        _sudo=True,
    )

    # Local npm packages (prettier + plugin-xml)
    server.shell(
        name="Install local npm packages (prettier)",
        commands=[
            f"cd {env['project_root']} && npm install",
        ],
    )

    # lessc symlink
    server.shell(
        name="Create lessc symlink",
        commands=[
            "ln -fs /usr/local/bin/lessc /usr/bin/lessc",
        ],
        _sudo=True,
    )


if __name__ == "__main__" or "pyinfra" in sys.modules:
    install_nodejs()
