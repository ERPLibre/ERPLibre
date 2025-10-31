#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import subprocess

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

""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Path addons to commit each module for migration",
    )
    parser.add_argument(
        "--odoo_version",
        required=True,
        help="The version name to update for commit, example 12.0",
    )
    args = parser.parse_args()

    return args


def run_git_command(command, ignore_error=False):
    """Exécute une commande Git et gère les erreurs."""
    result = subprocess.run(
        command, capture_output=True, text=True, shell=True
    )
    if result.returncode != 0 and not ignore_error:
        print(f"Error executing command: {' '.join(command)}")
        print(result.stderr)
    return result


def commit_by_directory():
    """Crée un commit pour chaque répertoire contenant des fichiers modifiés."""

    config = get_config()

    # Exécuter 'git status --porcelain' pour obtenir les fichiers modifiés
    status_result = run_git_command(
        f'cd "{config.path}" && git status --porcelain'
    )
    if status_result.returncode != 0:
        return

    # Stocker les répertoires uniques
    modified_dirs = set()
    for line in status_result.stdout.splitlines():
        # Extrait le chemin du fichier
        file_path = line[3:].strip()
        # Récupère le nom du répertoire et l'ajoute au set
        dir_name = os.path.dirname(file_path)
        if dir_name:  # Assure que ce n'est pas le répertoire racine
            modified_dirs.add(dir_name.split("/")[0])

    # Parcourir les répertoires uniques et commiter
    for directory in modified_dirs:
        print(f"Processing directory: {directory}")

        # Ajoute tous les fichiers du répertoire
        if os.path.exists(os.path.join(config.path, directory)):
            mig_prefix_msg = "MIG"
            run_git_command(f'cd "{config.path}" && git add {directory}')

            # Vérifie si le répertoire a des changements staged
            commit_result_git_diff = run_git_command(
                f'cd "{config.path}" && git diff --cached --quiet {directory}',
                ignore_error=True,
            )
            if commit_result_git_diff.returncode == 0:
                print(f"No changes to commit in {directory}.")
                continue
        else:
            mig_prefix_msg = "DEL"
            run_git_command(f'cd "{config.path}" && git rm -r {directory}')

        # Crée le commit
        commit_message = (
            f"[{mig_prefix_msg}] {directory}: Migration to {config.odoo_version}"
        )
        commit_result = run_git_command(
            f'cd "{config.path}" && git commit -m "{commit_message}"'
        )

        if commit_result.returncode == 0:
            print(f"Commit successful for {directory}.")

    print("\nAll directories with changes have been processed.")


if __name__ == "__main__":
    commit_by_directory()
