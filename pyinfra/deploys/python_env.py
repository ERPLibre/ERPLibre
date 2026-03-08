"""
ERPLibre - Python environment setup.

Replaces: script/install/install_locally.sh
           script/install/install_venv.sh
           script/install/install_git_repo.sh
"""

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from pyinfra.operations import server, pip

from deploys.env import get_env


def install_python_env():
    """Install pyenv, create venvs, install dependencies."""
    env = get_env()

    _install_pyenv()
    _install_python_version(env["python_erplibre_version"])
    _install_python_version(env["python_odoo_version"])
    _create_venv_erplibre(env)
    _create_venv_odoo(env)
    _install_git_repo(env)
    _install_odoo_poetry(env)
    _link_odoo_source(env)


def _install_pyenv():
    """Install pyenv if not already present."""
    server.shell(
        name="Install pyenv",
        commands=[
            'test -d "$HOME/.pyenv" || '
            "curl -L"
            " https://raw.githubusercontent.com/pyenv/pyenv-installer"
            "/master/bin/pyenv-installer | bash",
        ],
    )


def _pyenv_prefix():
    """Return the shell prefix to activate pyenv."""
    return (
        'export PYENV_ROOT="$HOME/.pyenv" && '
        'export PATH="$PYENV_ROOT/bin:$PATH" && '
        'eval "$(pyenv init -)" && '
        'eval "$(pyenv virtualenv-init -)"'
    )


def _install_python_version(python_version):
    """Install a Python version via pyenv if not already present."""
    server.shell(
        name=f"Install Python {python_version} via pyenv",
        commands=[
            f"{_pyenv_prefix()} && "
            f"cd $HOME/.pyenv && git pull && cd - && "
            f"yes n | pyenv install -s {python_version}",
        ],
    )


def _create_venv_erplibre(env):
    """Create the ERPLibre venv and install its dependencies."""
    venv_path = env["venv_erplibre_path"]
    python_version = env["python_erplibre_version"]
    project_root = env["project_root"]
    pyenv_python = (
        f"$HOME/.pyenv/versions/{python_version}/bin/python"
    )

    # Create the venv
    server.shell(
        name=f"Create ERPLibre venv ({env['venv_erplibre_name']})",
        commands=[
            f"test -d {venv_path} || "
            f"{pyenv_python} -m venv {venv_path}",
        ],
    )

    # Install ERPLibre dependencies
    server.shell(
        name="Upgrade pip and install ERPLibre dependencies",
        commands=[
            f"source {venv_path}/bin/activate && "
            f"pip install --upgrade pip && "
            f"pip install -r"
            f" {project_root}/requirement/erplibre_require-ments.txt",
        ],
    )


def _create_venv_odoo(env):
    """Create the Odoo venv."""
    venv_path = env["venv_odoo_path"]
    python_version = env["python_odoo_version"]
    project_root = env["project_root"]
    pyenv_python = (
        f"$HOME/.pyenv/versions/{python_version}/bin/python"
    )

    # Create addons directory if missing
    addons_path = os.path.join(
        project_root,
        f"odoo{env['odoo_version']}",
        "addons",
        "addons",
    )
    server.shell(
        name="Create Odoo addons directory",
        commands=[f"mkdir -p {addons_path}"],
    )

    # Create the venv
    server.shell(
        name=f"Create Odoo venv ({env['venv_odoo_name']})",
        commands=[
            f"test -d {venv_path} || "
            f"{pyenv_python} -m venv {venv_path}",
        ],
    )

    # Upgrade pip
    server.shell(
        name="Upgrade pip in Odoo venv",
        commands=[
            f"source {venv_path}/bin/activate && "
            f"pip install --upgrade pip",
        ],
    )


def _install_git_repo(env):
    """Install the Google Repo tool into the ERPLibre venv."""
    venv_path = env["venv_erplibre_path"]
    repo_path = f"{venv_path}/bin/repo"
    python_hashbang = f"#!./{env['venv_erplibre_name']}/bin/python"

    server.shell(
        name="Install Google Repo tool",
        commands=[
            f"test -f {repo_path} && exit 0",
            f"curl -s"
            f" https://storage.googleapis.com/git-repo-downloads/repo"
            f" > {repo_path}",
            f"chmod +x {repo_path}",
            f"sed -i 1d {repo_path}",
            f'sed -i "1 i {python_hashbang}" {repo_path}',
        ],
    )


def _install_odoo_poetry(env):
    """Install Poetry and Odoo dependencies."""
    venv_path = env["venv_odoo_path"]
    poetry_version = env["poetry_version"]
    project_root = env["project_root"]

    server.shell(
        name=f"Install Poetry {poetry_version} and Odoo dependencies",
        commands=[
            f"source {venv_path}/bin/activate && "
            f"pip install poetry=={poetry_version} && "
            f"cd {project_root} && "
            f"export PYTHON_KEYRING_BACKEND="
            f"keyring.backends.null.Keyring && "
            f"poetry install --no-root -vvv",
        ],
    )

    # Remove artifacts created by pip
    server.shell(
        name="Clean pip artifacts",
        commands=[f"rm -rf {project_root}/artifacts"],
    )


def _link_odoo_source(env):
    """Link Odoo source into the venv site-packages."""
    venv_path = env["venv_odoo_path"]
    odoo_home = env["odoo_home"]
    python_major = env["python_version_major"]
    site_packages = (
        f"{venv_path}/lib/python{python_major}/site-packages"
    )
    project_root = env["project_root"]

    server.shell(
        name="Link Odoo source into venv site-packages",
        commands=[
            f"ln -fs {odoo_home}/odoo {site_packages}/",
        ],
    )

    # Record installed version
    server.shell(
        name="Record installed Odoo version",
        commands=[
            f"mkdir -p {project_root}/.repo",
            f'LINE="odoo{env["odoo_version"]}"',
            f'FILE="{project_root}/.repo/installed_odoo_version.txt"',
            f"touch $FILE",
            f'grep -qxF "$LINE" "$FILE" || echo "$LINE" >> "$FILE"',
        ],
    )


if __name__ == "__main__" or "pyinfra" in sys.modules:
    install_python_env()
