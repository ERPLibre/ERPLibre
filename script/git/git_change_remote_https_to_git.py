#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import sys

from colorama import Fore, Style
from git import Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git.git_tool import GitTool

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
        "-d",
        "--dir",
        dest="dir",
        default="./",
        help="Path of repo to change remote, including submodule.",
    )
    parser.add_argument(
        "-f",
        "--upstream",
        dest="upstream",
        help=(
            "Upstream name to change address https to git. "
            "When empty, all upstream is updated."
        ),
    )
    parser.add_argument(
        "--git_to_https",
        action="store_true",
        help="Replace all repo git to https.",
    )
    args = parser.parse_args()
    return args


def change_remote(git_tool, repo_path, upstream_name, git_to_https):
    """Réécrit les remotes de `repo_path`. Rend le nombre de remotes changés.

    Lève ce que GitPython lève : c'est l'appelant qui décide si un dépôt
    fautif arrête le lot ou seulement lui-même.
    """
    repo_sm = Repo(repo_path)
    if upstream_name:
        remotes = [a for a in repo_sm.remotes if upstream_name == a.name]
    else:
        remotes = list(repo_sm.remotes)
    for remote in remotes:
        url, url_https, url_git = git_tool.get_url(remote.url)
        new_url = url_https if git_to_https else url_git
        remote.set_url(new_url)
        print(f'Remote "{remote.name}" update for {new_url}')
    return len(remotes)


def change_all_remotes(
    git_tool, lst_repo, root_path, upstream_name="", git_to_https=False
):
    """Parcourt `lst_repo`. Rend (remotes changés, [(chemin, raison)]).

    Un dépôt fautif n'arrête PAS le lot : un répertoire vidé à la main, un
    clone interrompu ou un `.git` effacé sont des états courants d'un
    checkout de développement, et ils n'ont rien à voir avec les cent
    quarante autres dépôts qui, eux, attendent leur nouveau remote.

    Les ennuis sont RENDUS plutôt qu'affichés au fil de l'eau : noyés dans
    la trace d'un lot de cette taille, ils ne se voient plus.
    """
    skipped = []
    changed = 0
    total = len(lst_repo)
    for i, repo in enumerate(lst_repo, start=1):
        print(f"Nb element {i}/{total}")
        repo_name = repo.get("name")
        repo_path = os.path.join(root_path, repo_name)
        if not os.path.isdir(repo_path):
            print(f"Ignore repo {repo_path}")
            skipped.append((repo_path, "directory is missing"))
            continue
        try:
            changed += change_remote(
                git_tool, repo_path, upstream_name, git_to_https
            )
        except InvalidGitRepositoryError:
            reason = "directory exists but holds no git repository"
        except NoSuchPathError:
            reason = "path vanished while running"
        except Exception as err:
            reason = f"{type(err).__name__}: {err}"
        else:
            continue
        print(f"Ignore repo {repo_path}: {reason}")
        skipped.append((repo_path, reason))
    return changed, skipped


def print_report(total, changed, skipped):
    """Le bilan, en fin de course et en couleur.

    Une ligne d'avertissement au moment où elle survient est perdue : ce
    que l'humain lit d'un lot long, c'est sa fin.
    """
    print(f"\n{'=' * 72}")
    print(f"{total} repo, {changed} remote updated, {len(skipped)} skipped")
    if not skipped:
        return
    print(f"{Fore.YELLOW}Skipped{Style.RESET_ALL}:")
    for repo_path, reason in skipped:
        print(f"  · {repo_path} — {reason}")


def main():
    git_tool = GitTool()
    config = get_config()

    lst_repo = git_tool.get_repo_info(config.dir, add_root=True)
    changed, skipped = change_all_remotes(
        git_tool,
        lst_repo,
        new_path,
        upstream_name=config.upstream,
        git_to_https=config.git_to_https,
    )
    print_report(len(lst_repo), changed, skipped)
    # Sortie nulle même avec des dépôts ignorés : tout ce qui POUVAIT être
    # changé l'a été, et le bilan porte le reste. C'est déjà le contrat
    # tenu pour un répertoire absent, qui n'a jamais fait échouer le lot.
    return 0


if __name__ == "__main__":
    sys.exit(main())
