#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import sys
from collections import defaultdict

from colorama import Fore, Style
from git import Repo
from git.exc import GitCommandError, NoSuchPathError

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git.git_tool import GitTool
from script.git.manifest_freeze import is_sha, manifest_branch

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Compare actual code with a manifest.""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-m",
        "--manifest",
        default=".repo/local_manifests/erplibre_manifest.xml",
        help="The manifest to compare with actual code.",
    )
    args = parser.parse_args()
    return args


COLORS = {"PASS": Fore.GREEN, "WARNING": Fore.YELLOW, "ERROR": Fore.RED}

PASS_DETACHED = "Not on specified branch, no divergence"
PASS_OTHER_BRANCH = "Not same branch, no divergence"


def _rev_parse(git_repo, ref):
    """Le commit de `ref`, ou None si la référence n'existe pas."""
    try:
        return git_repo.git.rev_parse(ref)
    except GitCommandError:
        return None


def _compare_branch(git_repo, branch_name, organization):
    """Compare un dépôt à la branche que nomme « revision »."""
    value = git_repo.git.branch("--show-current")
    if not value:
        # TODO maybe need to check divergence with local branch and not remote branch
        commit_head = git_repo.git.rev_parse("HEAD")
        commit_branch = _rev_parse(git_repo, f"{organization}/{branch_name}")
        if commit_branch is None:
            # Cannot get information
            if branch_name == commit_head:
                return "PASS", PASS_DETACHED
            return (
                "ERROR",
                f"manifest revision is {branch_name} and commit"
                f" {commit_head}.",
            )
        if commit_branch != commit_head:
            return "WARNING", "Not on specified branch, got a divergence."
        return "PASS", PASS_DETACHED
    if branch_name == value:
        return "PASS", ""
    value_hash = git_repo.git.rev_parse(value)
    if _rev_parse(git_repo, branch_name) == value_hash:
        return "PASS", PASS_OTHER_BRANCH
    # Check if the new branch is pushed
    if _rev_parse(git_repo, f"{organization}/{value}") == value_hash:
        return (
            "WARNING",
            f"New branch '{value}', divergence, but it's push on remote.",
        )
    return (
        "ERROR",
        f"manifest revision is {branch_name} and actual revision is"
        f" {value}.",
    )


def _short(branch):
    """Nom court d'une branche : « refs/heads/18.0 » devient « 18.0 »."""
    prefix = "refs/heads/"
    return branch[len(prefix) :] if branch.startswith(prefix) else branch


def _compare_frozen(git_repo, sha, branch_name, organization):
    """Compare un dépôt au commit gelé que porte « revision ».

    Le commit fait foi : HEAD doit être ce commit, détaché ou non. La
    branche du manifeste, quand elle est connue, ne choisit que le libellé
    du succès. Une branche locale avancée au-delà du gel, mais poussée,
    reste un avertissement plutôt qu'une erreur.
    """
    commit_head = git_repo.git.rev_parse("HEAD")
    value = git_repo.git.branch("--show-current")
    if commit_head == sha:
        if not value:
            return "PASS", PASS_DETACHED
        if branch_name and _short(branch_name) == value:
            return "PASS", ""
        return "PASS", PASS_OTHER_BRANCH
    if value and _rev_parse(git_repo, f"{organization}/{value}") == (
        commit_head
    ):
        return (
            "WARNING",
            f"Branch '{value}' diverges from frozen revision {sha}, but"
            " it's push on remote.",
        )
    return (
        "ERROR",
        f"manifest revision is {sha} and commit {commit_head}.",
    )


def compare_project(git_repo, project, organization):
    """Compare un dépôt à son projet du manifeste. Rend (niveau, message).

    `project` est au format de xmltodict (« @revision »…). Le niveau est
    PASS, WARNING ou ERROR ; le message peut être vide. Un manifeste
    fusionné avec --freeze porte un commit dans « revision » et la
    branche dans « dest-branch » ou « upstream ».
    """
    revision = project.get("@revision")
    if is_sha(revision):
        branch_name = manifest_branch(
            revision, project.get("@upstream"), project.get("@dest-branch")
        )
        return _compare_frozen(git_repo, revision, branch_name, organization)
    return _compare_branch(git_repo, revision, organization)


def format_result(level, message):
    """La ligne affichée pour un dépôt : le niveau en couleur, puis le
    message s'il y en a un."""
    line = f"{COLORS[level]}{level}{Style.RESET_ALL}"
    return f"{line} {message}" if message else line


def main():
    config = get_config()
    git_tool = GitTool()

    dct_remote, dct_project, default_remote = git_tool.get_manifest_xml_info(
        filename=config.manifest, add_root=True
    )
    dct_result = defaultdict(int)
    i = 0
    total = len(dct_project)
    for name, project in dct_project.items():
        i += 1
        path = project.get("@path")
        print(f"{i}/{total} - {path}")
        organization = project.get("@remote", git_tool.default_project_name)

        try:
            git_repo = Repo(path)
        except NoSuchPathError:
            print(
                f"{Fore.YELLOW}Warning{Style.RESET_ALL} missing project"
                f" {path}."
            )
            dct_result["WARNING"] += 1
            continue

        level, message = compare_project(git_repo, project, organization)
        print(format_result(level, message))
        dct_result[level] += 1

    str_result = ""
    if dct_result["PASS"]:
        str_result += (
            f"{Fore.GREEN}PASS: {dct_result['PASS']}{Style.RESET_ALL}"
        )
    if dct_result["WARNING"]:
        if str_result:
            str_result += " "
        str_result += (
            f"{Fore.YELLOW}WARNING: {dct_result['WARNING']}{Style.RESET_ALL}"
        )
    if dct_result["ERROR"]:
        if str_result:
            str_result += " "
        str_result += (
            f"{Fore.RED}ERROR: {dct_result['ERROR']}{Style.RESET_ALL}"
        )
    print(str_result)


if __name__ == "__main__":
    main()
