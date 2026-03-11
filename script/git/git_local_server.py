#!/usr/bin/env python3
# © 2025-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.execute.execute import Execute

_logger = logging.getLogger(__name__)

DEFAULT_ERPLIBRE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
DEFAULT_GIT_PATH = os.path.join(os.path.expanduser("~"), ".git-server")
PRODUCTION_GIT_PATH = "/srv/git"
DEFAULT_MANIFEST = ".repo/local_manifests/erplibre_manifest.xml"
DEFAULT_REMOTE_NAME = "local"
DEFAULT_PORT = 9418
ERPLIBRE_REPO_NAME = "erplibre/erplibre"
ERPLIBRE_REPO_URL = "https://github.com/erplibre"


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
Deploy a local git server using git daemon and configure
all repos from the ERPLibre manifest.

Actions (in order):
  1. init   - Create bare repos in the git server path
  2. remote - Add 'local' remote to each repo
  3. push   - Push all branches to the local remote
  4. serve  - Start git daemon

By default, all actions are executed sequentially.
The default path is ~/.git-server (user-level, no root needed).
Use --production-ready for /srv/git (requires root).
""",
    )
    parser.add_argument(
        "-p",
        "--path",
        default=None,
        help=(
            "Path for git server bare repos" f" (default: {DEFAULT_GIT_PATH})"
        ),
    )
    parser.add_argument(
        "--production-ready",
        action="store_true",
        help=(
            f"Use {PRODUCTION_GIT_PATH} as git server path"
            " (requires root privileges)"
        ),
    )
    parser.add_argument(
        "-m",
        "--manifest",
        default=DEFAULT_MANIFEST,
        help="Manifest XML file" f" (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--remote-name",
        default=DEFAULT_REMOTE_NAME,
        help="Remote name to add" f" (default: {DEFAULT_REMOTE_NAME})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Git daemon port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--action",
        choices=["init", "remote", "push", "serve", "all"],
        default="all",
        help="Action to perform (default: all)",
    )
    parser.add_argument(
        "--erplibre-root",
        default=None,
        help="ERPLibre root directory (default: auto-detect)",
    )
    parser.add_argument(
        "--push-all-branches",
        action="store_true",
        help="Push all local branches, not just the current one",
    )
    parser.add_argument(
        "--remote-url-type",
        choices=["file", "daemon"],
        default="file",
        help=(
            "Remote URL type: 'file' uses local path"
            " (push works without daemon), 'daemon'"
            " uses git:// protocol (default: file)"
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    args = parser.parse_args()

    # Resolve git server path
    if args.path and args.production_ready:
        parser.error("--path and --production-ready are mutually exclusive")
    if args.production_ready:
        args.path = PRODUCTION_GIT_PATH
    elif args.path is None:
        args.path = DEFAULT_GIT_PATH

    return args


def check_path_permissions(path):
    """Check if we have write permissions on the target
    path. Try the path itself first, then its closest
    existing parent directory."""
    check = path
    while check and not os.path.exists(check):
        check = os.path.dirname(check)
    if not check:
        check = "/"
    if os.access(check, os.W_OK):
        return True
    return False


def require_permissions_or_exit(path):
    """Exit with instructions if we cannot write to path."""
    print(f"Error: No write permission on {path}")
    print(
        "Please run this script with appropriate"
        " privileges:"
        f"\n  sudo {sys.executable}"
        f" {' '.join(sys.argv)}"
    )
    sys.exit(1)


def parse_manifest(manifest_path):
    """Parse the manifest XML and return list of projects."""
    tree = ET.parse(manifest_path)
    root = tree.getroot()

    remotes = {}
    for remote in root.findall("remote"):
        remotes[remote.get("name")] = remote.get("fetch")

    projects = []
    for project in root.findall("project"):
        name = project.get("name")
        path = project.get("path")
        remote = project.get("remote")
        revision = project.get("revision")
        projects.append(
            {
                "name": name,
                "path": path,
                "remote": remote,
                "revision": revision,
                "fetch_url": remotes.get(remote, ""),
            }
        )

    return projects


def get_erplibre_root_project(erplibre_root):
    """Build a project entry for the ERPLibre root repo.

    The root repo is not in the manifest (it is managed
    by git directly, not Google Repo) but needs to be
    included in the local git server.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            erplibre_root,
            "rev-parse",
            "--abbrev-ref",
            "HEAD",
        ],
        capture_output=True,
        text=True,
    )
    revision = (
        result.stdout.strip()
        if result.returncode == 0
        else "master"
    )

    return {
        "name": ERPLIBRE_REPO_NAME,
        "path": ".",
        "remote": "origin",
        "revision": revision,
        "fetch_url": ERPLIBRE_REPO_URL,
    }


def init_bare_repos(git_path, projects):
    """Create bare repos for all projects in the manifest."""
    os.makedirs(git_path, exist_ok=True)

    created = 0
    skipped = 0
    for project in projects:
        repo_name = project["name"]
        if not repo_name.endswith(".git"):
            repo_name += ".git"
        bare_path = os.path.join(git_path, repo_name)

        if os.path.exists(bare_path):
            _logger.info(f"  Exists: {bare_path}")
            skipped += 1
            continue

        _logger.info(f"  Creating: {bare_path}")
        subprocess.run(
            ["git", "init", "--bare", bare_path],
            check=True,
            capture_output=True,
        )

        # Enable git daemon export
        export_file = os.path.join(bare_path, "git-daemon-export-ok")
        open(export_file, "w").close()

        created += 1

    print(f"Bare repos: {created} created, {skipped} skipped (already exist)")


def build_remote_url(git_path, repo_name, port, remote_url_type):
    """Build the remote URL based on the type."""
    if remote_url_type == "daemon":
        if port != DEFAULT_PORT:
            return f"git://localhost:{port}/{repo_name}"
        return f"git://localhost/{repo_name}"
    # Default: file path
    return os.path.join(git_path, repo_name)


def add_remotes(
    erplibre_root,
    git_path,
    projects,
    remote_name,
    port,
    remote_url_type,
):
    """Add local remote to each repo.

    remote_url_type='file': uses local path, push works
      without daemon running.
    remote_url_type='daemon': uses git://localhost URL,
      requires daemon for push.
    """
    added = 0
    skipped = 0
    errors = 0
    for project in projects:
        repo_path = os.path.join(erplibre_root, project["path"])
        if not os.path.isdir(repo_path):
            _logger.warning(f"  Not found: {repo_path}")
            errors += 1
            continue

        repo_name = project["name"]
        if not repo_name.endswith(".git"):
            repo_name += ".git"

        remote_url = build_remote_url(
            git_path, repo_name, port, remote_url_type
        )

        # Check if remote already exists
        result = subprocess.run(
            ["git", "-C", repo_path, "remote"],
            capture_output=True,
            text=True,
        )
        existing_remotes = result.stdout.strip().split("\n")

        if remote_name in existing_remotes:
            # Update URL if remote exists
            subprocess.run(
                [
                    "git",
                    "-C",
                    repo_path,
                    "remote",
                    "set-url",
                    remote_name,
                    remote_url,
                ],
                check=True,
                capture_output=True,
            )
            _logger.info(f"  Updated: {project['path']}")
            skipped += 1
        else:
            subprocess.run(
                [
                    "git",
                    "-C",
                    repo_path,
                    "remote",
                    "add",
                    remote_name,
                    remote_url,
                ],
                check=True,
                capture_output=True,
            )
            _logger.info(f"  Added: {project['path']}")
            added += 1

    print(f"Remotes: {added} added, {skipped} updated," f" {errors} errors")


def is_detached_head(repo_path):
    """Check if a repo is in detached HEAD state."""
    result = subprocess.run(
        ["git", "-C", repo_path, "symbolic-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.returncode != 0


def checkout_manifest_branch(repo_path, revision):
    """Checkout the branch from the manifest revision.

    When Google Repo syncs, repos end up in detached HEAD
    on the exact commit. We create/checkout a local branch
    matching the manifest revision so git push works.
    """
    # Extract branch name — revision can be
    # "18.0", "18.0_dev", "ERPLibre/18.0", "main", etc.
    branch = revision.split("/")[-1] if "/" in revision else revision

    # Check if local branch already exists
    result = subprocess.run(
        [
            "git",
            "-C",
            repo_path,
            "show-ref",
            "--verify",
            f"refs/heads/{branch}",
        ],
        capture_output=True,
    )
    if result.returncode == 0:
        # Branch exists, checkout it
        subprocess.run(
            ["git", "-C", repo_path, "checkout", branch],
            capture_output=True,
        )
    else:
        # Create branch from current HEAD
        subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "checkout",
                "-b",
                branch,
            ],
            capture_output=True,
        )
    return branch


def update_bare_head(git_path, project):
    """Update the HEAD of the bare repo to point to the
    manifest branch, so git clone checks out the right
    branch by default."""
    repo_name = project["name"]
    if not repo_name.endswith(".git"):
        repo_name += ".git"
    bare_path = os.path.join(git_path, repo_name)
    if not os.path.isdir(bare_path):
        return

    revision = project.get("revision", "")
    if not revision:
        return
    branch = revision.split("/")[-1] if "/" in revision else revision
    subprocess.run(
        [
            "git",
            "-C",
            bare_path,
            "symbolic-ref",
            "HEAD",
            f"refs/heads/{branch}",
        ],
        capture_output=True,
    )


def push_to_local(
    erplibre_root,
    git_path,
    projects,
    remote_name,
    push_all_branches,
):
    """Push to local remote for each repo."""
    pushed = 0
    errors = 0
    checkouts = 0
    for project in projects:
        repo_path = os.path.join(erplibre_root, project["path"])
        if not os.path.isdir(repo_path):
            _logger.warning(f"  Not found: {repo_path}")
            errors += 1
            continue

        # Unshallow if needed (clone-depth in manifest)
        shallow_file = os.path.join(repo_path, ".git", "shallow")
        if os.path.exists(shallow_file):
            _logger.info(f"  Unshallowing {project['path']}...")
            # Try each remote until unshallow succeeds
            result = subprocess.run(
                ["git", "-C", repo_path, "remote"],
                capture_output=True,
                text=True,
            )
            remotes = [
                r
                for r in result.stdout.strip().split("\n")
                if r and r != remote_name
            ]
            # Try the manifest remote first
            manifest_remote = project.get("remote", "")
            if manifest_remote in remotes:
                remotes.remove(manifest_remote)
                remotes.insert(0, manifest_remote)

            for try_remote in remotes:
                result = subprocess.run(
                    [
                        "git",
                        "-C",
                        repo_path,
                        "fetch",
                        "--unshallow",
                        try_remote,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if not os.path.exists(shallow_file):
                    _logger.info(f"  Unshallowed via" f" {try_remote}")
                    break
            else:
                if os.path.exists(shallow_file):
                    _logger.warning(
                        f"  Unshallow failed for"
                        f" {project['path']},"
                        " push may fail"
                    )

        # Handle detached HEAD: checkout manifest branch
        if is_detached_head(repo_path):
            revision = project.get("revision", "")
            if revision:
                branch = checkout_manifest_branch(repo_path, revision)
                _logger.info(
                    f"  Checkout {branch} for"
                    f" {project['path']}"
                    " (was detached HEAD)"
                )
                checkouts += 1
            else:
                _logger.warning(
                    f"  Detached HEAD with no revision"
                    f" for {project['path']}, skipping"
                )
                errors += 1
                continue

        try:
            if push_all_branches:
                cmd = [
                    "git",
                    "-C",
                    repo_path,
                    "push",
                    remote_name,
                    "--all",
                ]
            else:
                cmd = [
                    "git",
                    "-C",
                    repo_path,
                    "push",
                    remote_name,
                ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                _logger.warning(
                    f"  Push failed for"
                    f" {project['path']}:"
                    f" {result.stderr.strip()}"
                )
                errors += 1
            else:
                update_bare_head(git_path, project)
                _logger.info(f"  Pushed: {project['path']}")
                pushed += 1
        except subprocess.TimeoutExpired:
            _logger.warning(f"  Timeout pushing {project['path']}")
            errors += 1

    print(
        f"Push: {pushed} pushed, {checkouts} branch"
        f" checkouts, {errors} errors"
    )


def print_clone_commands(git_path, projects, port):
    """Print git clone commands for all available repos."""
    print("=== Available repos to clone ===")
    base_url = (
        f"git://localhost:{port}"
        if port != DEFAULT_PORT
        else "git://localhost"
    )
    count = 0
    for project in projects:
        repo_name = project["name"]
        if not repo_name.endswith(".git"):
            repo_name += ".git"
        bare_path = os.path.join(git_path, repo_name)
        if os.path.isdir(bare_path):
            print(f"  git clone {base_url}/{repo_name}" f" {project['path']}")
            count += 1
    print(f"\nTotal: {count} repos available")
    print()


def serve_git_daemon(git_path, projects, port):
    """Start git daemon to serve repos."""
    print_clone_commands(git_path, projects, port)

    cmd = (
        f"git daemon --reuseaddr"
        f" --base-path={git_path}"
        f" --port={port}"
        f" --export-all"
        f" --enable=receive-pack"
        f" {git_path}"
    )
    print(f"Starting git daemon on port {port}...")
    print(f"  Base path: {git_path}")
    print(f"  URL: git://localhost:{port}/")
    print("  Press Ctrl+C to stop")

    execute = Execute()
    execute.exec_command_live(cmd, source_erplibre=False)


def main():
    config = get_config()

    log_level = logging.DEBUG if config.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s",
    )

    # Check write permissions on target path
    if not check_path_permissions(config.path):
        require_permissions_or_exit(config.path)

    # Detect ERPLibre root
    if config.erplibre_root:
        erplibre_root = os.path.abspath(config.erplibre_root)
    else:
        erplibre_root = DEFAULT_ERPLIBRE_PATH

    manifest_path = os.path.join(erplibre_root, config.manifest)
    if not os.path.exists(manifest_path):
        print(f"Error: Manifest not found: {manifest_path}")
        sys.exit(1)

    print(f"ERPLibre root: {erplibre_root}")
    print(f"Manifest: {manifest_path}")
    print(f"Git server path: {config.path}")
    print(f"Remote name: {config.remote_name}")
    if config.production_ready:
        print("Mode: production (/srv/git)")
    else:
        print("Mode: development (~/.git-server)")
    print(f"Remote URL type: {config.remote_url_type}")
    print()

    projects = parse_manifest(manifest_path)
    erplibre_project = get_erplibre_root_project(erplibre_root)
    projects.append(erplibre_project)
    print(
        f"Found {len(projects)} projects"
        f" ({len(projects) - 1} from manifest"
        f" + erplibre root)"
    )
    print()

    action = config.action

    if action in ("init", "all"):
        print("=== Creating bare repos ===")
        init_bare_repos(config.path, projects)
        print()

    if action in ("remote", "all"):
        print("=== Adding remotes ===")
        add_remotes(
            erplibre_root,
            config.path,
            projects,
            config.remote_name,
            config.port,
            config.remote_url_type,
        )
        print()

    if action in ("push", "all"):
        print("=== Pushing to local ===")
        push_to_local(
            erplibre_root,
            config.path,
            projects,
            config.remote_name,
            config.push_all_branches,
        )
        print()

    if action in ("serve", "all"):
        print("=== Starting git daemon ===")
        serve_git_daemon(config.path, projects, config.port)


if __name__ == "__main__":
    main()
