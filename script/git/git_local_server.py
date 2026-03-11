#!/usr/bin/env python3
# © 2025-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import asyncio
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
DEFAULT_JOBS = 8
ERPLIBRE_REPO_NAME = "erplibre/erplibre"
ERPLIBRE_REPO_URL = "https://github.com/erplibre"


async def _run_git(*args, cwd=None, timeout=None):
    """Run a git command asynchronously.

    Returns (stdout, stderr, returncode).
    Raises asyncio.TimeoutError on timeout.
    """
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
        return (
            stdout.decode(),
            stderr.decode(),
            process.returncode,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise


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
        "--unshallow",
        action="store_true",
        help=(
            "Fetch full history for shallow repos before"
            " push (slow for large repos like odoo)."
            " Default: push shallow for performance"
        ),
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=DEFAULT_JOBS,
        help=(
            "Parallel jobs for init/remote/push"
            f" (default: {DEFAULT_JOBS})"
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


# --- Async workers for init ---


async def _init_single_bare_repo(git_path, project, semaphore):
    """Create a single bare repo (async worker)."""
    async with semaphore:
        repo_name = project["name"]
        if not repo_name.endswith(".git"):
            repo_name += ".git"
        bare_path = os.path.join(git_path, repo_name)

        if os.path.exists(bare_path):
            _logger.info(f"  Exists: {bare_path}")
            return "skipped"

        _logger.info(f"  Creating: {bare_path}")
        _, err, rc = await _run_git(
            "git", "init", "--bare", bare_path
        )
        if rc != 0:
            _logger.warning(
                f"  Init failed: {bare_path}: {err.strip()}"
            )
            return "error"

        # Enable git daemon export
        export_file = os.path.join(
            bare_path, "git-daemon-export-ok"
        )
        open(export_file, "w").close()

        # Allow pushing from shallow clones
        await _run_git(
            "git",
            "-C",
            bare_path,
            "config",
            "receive.shallowUpdate",
            "true",
        )

        return "created"


async def init_bare_repos(git_path, projects, jobs):
    """Create bare repos for all projects (async)."""
    os.makedirs(git_path, exist_ok=True)
    semaphore = asyncio.Semaphore(jobs)

    results = await asyncio.gather(
        *[
            _init_single_bare_repo(git_path, p, semaphore)
            for p in projects
        ]
    )

    created = results.count("created")
    skipped = results.count("skipped")
    errors = results.count("error")
    print(
        f"Bare repos: {created} created,"
        f" {skipped} skipped (already exist),"
        f" {errors} errors"
    )


# --- Async workers for remote ---


def build_remote_url(git_path, repo_name, port, remote_url_type):
    """Build the remote URL based on the type."""
    if remote_url_type == "daemon":
        if port != DEFAULT_PORT:
            return f"git://localhost:{port}/{repo_name}"
        return f"git://localhost/{repo_name}"
    # Default: file path
    return os.path.join(git_path, repo_name)


async def _add_single_remote(
    erplibre_root,
    git_path,
    project,
    remote_name,
    port,
    remote_url_type,
    semaphore,
):
    """Add or update remote for a single repo (async)."""
    async with semaphore:
        repo_path = os.path.join(
            erplibre_root, project["path"]
        )
        if not os.path.isdir(repo_path):
            _logger.warning(f"  Not found: {repo_path}")
            return "error"

        repo_name = project["name"]
        if not repo_name.endswith(".git"):
            repo_name += ".git"

        remote_url = build_remote_url(
            git_path, repo_name, port, remote_url_type
        )

        # Check if remote already exists
        stdout, _, _ = await _run_git(
            "git", "-C", repo_path, "remote"
        )
        existing_remotes = stdout.strip().split("\n")

        if remote_name in existing_remotes:
            _, err, rc = await _run_git(
                "git",
                "-C",
                repo_path,
                "remote",
                "set-url",
                remote_name,
                remote_url,
            )
            if rc != 0:
                _logger.warning(
                    f"  set-url failed for"
                    f" {project['path']}: {err.strip()}"
                )
                return "error"
            _logger.info(f"  Updated: {project['path']}")
            return "updated"
        else:
            _, err, rc = await _run_git(
                "git",
                "-C",
                repo_path,
                "remote",
                "add",
                remote_name,
                remote_url,
            )
            if rc != 0:
                _logger.warning(
                    f"  add failed for"
                    f" {project['path']}: {err.strip()}"
                )
                return "error"
            _logger.info(f"  Added: {project['path']}")
            return "added"


async def add_remotes(
    erplibre_root,
    git_path,
    projects,
    remote_name,
    port,
    remote_url_type,
    jobs,
):
    """Add local remote to each repo (async).

    remote_url_type='file': uses local path, push works
      without daemon running.
    remote_url_type='daemon': uses git://localhost URL,
      requires daemon for push.
    """
    semaphore = asyncio.Semaphore(jobs)

    results = await asyncio.gather(
        *[
            _add_single_remote(
                erplibre_root,
                git_path,
                p,
                remote_name,
                port,
                remote_url_type,
                semaphore,
            )
            for p in projects
        ]
    )

    added = results.count("added")
    updated = results.count("updated")
    errors = results.count("error")
    print(
        f"Remotes: {added} added, {updated} updated,"
        f" {errors} errors"
    )


# --- Async workers for push ---


async def _is_detached_head(repo_path):
    """Check if a repo is in detached HEAD state."""
    _, _, rc = await _run_git(
        "git", "-C", repo_path, "symbolic-ref", "HEAD"
    )
    return rc != 0


async def _checkout_manifest_branch(repo_path, revision):
    """Checkout the branch from the manifest revision.

    When Google Repo syncs, repos end up in detached HEAD
    on the exact commit. We create/checkout a local branch
    matching the manifest revision so git push works.
    """
    branch = (
        revision.split("/")[-1] if "/" in revision else revision
    )

    # Check if local branch already exists
    _, _, rc = await _run_git(
        "git",
        "-C",
        repo_path,
        "show-ref",
        "--verify",
        f"refs/heads/{branch}",
    )
    if rc == 0:
        await _run_git(
            "git", "-C", repo_path, "checkout", branch
        )
    else:
        await _run_git(
            "git",
            "-C",
            repo_path,
            "checkout",
            "-b",
            branch,
        )
    return branch


async def _update_bare_head(git_path, project):
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
    branch = (
        revision.split("/")[-1] if "/" in revision else revision
    )
    await _run_git(
        "git",
        "-C",
        bare_path,
        "symbolic-ref",
        "HEAD",
        f"refs/heads/{branch}",
    )


async def _try_unshallow(repo_path, project, remote_name):
    """Try to unshallow a repo by fetching full history."""
    shallow_file = os.path.join(
        repo_path, ".git", "shallow"
    )
    _logger.info(
        f"  Unshallowing {project['path']}..."
    )
    stdout, _, _ = await _run_git(
        "git", "-C", repo_path, "remote"
    )
    remotes = [
        r
        for r in stdout.strip().split("\n")
        if r and r != remote_name
    ]
    manifest_remote = project.get("remote", "")
    if manifest_remote in remotes:
        remotes.remove(manifest_remote)
        remotes.insert(0, manifest_remote)

    for try_remote in remotes:
        try:
            await _run_git(
                "git",
                "-C",
                repo_path,
                "fetch",
                "--unshallow",
                try_remote,
                timeout=300,
            )
        except asyncio.TimeoutError:
            continue
        if not os.path.exists(shallow_file):
            _logger.info(
                f"  Unshallowed via {try_remote}"
            )
            return
    if os.path.exists(shallow_file):
        _logger.warning(
            f"  Unshallow failed for"
            f" {project['path']},"
            " falling back to shallow push"
        )


async def _push_single_repo(
    erplibre_root,
    git_path,
    project,
    remote_name,
    push_all_branches,
    unshallow,
    semaphore,
):
    """Push a single repo to local remote (async)."""
    async with semaphore:
        repo_path = os.path.join(
            erplibre_root, project["path"]
        )
        if not os.path.isdir(repo_path):
            _logger.warning(f"  Not found: {repo_path}")
            return "error", False

        # Handle shallow repos
        shallow_file = os.path.join(
            repo_path, ".git", "shallow"
        )
        if os.path.exists(shallow_file):
            if unshallow:
                await _try_unshallow(
                    repo_path, project, remote_name
                )
            else:
                # Enable shallow push on bare repo
                repo_name = project["name"]
                if not repo_name.endswith(".git"):
                    repo_name += ".git"
                bare_path = os.path.join(
                    git_path, repo_name
                )
                if os.path.isdir(bare_path):
                    await _run_git(
                        "git",
                        "-C",
                        bare_path,
                        "config",
                        "receive.shallowUpdate",
                        "true",
                    )
                _logger.info(
                    f"  Shallow push for"
                    f" {project['path']}"
                )

        # Handle detached HEAD: checkout manifest branch
        did_checkout = False
        if await _is_detached_head(repo_path):
            revision = project.get("revision", "")
            if revision:
                branch = await _checkout_manifest_branch(
                    repo_path, revision
                )
                _logger.info(
                    f"  Checkout {branch} for"
                    f" {project['path']}"
                    " (was detached HEAD)"
                )
                did_checkout = True
            else:
                _logger.warning(
                    f"  Detached HEAD with no revision"
                    f" for {project['path']}, skipping"
                )
                return "error", False

        # Push
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
            _, err, rc = await _run_git(
                *cmd, timeout=120
            )
            if rc != 0:
                _logger.warning(
                    f"  Push failed for"
                    f" {project['path']}:"
                    f" {err.strip()}"
                )
                return "error", did_checkout
            else:
                await _update_bare_head(git_path, project)
                _logger.info(
                    f"  Pushed: {project['path']}"
                )
                return "pushed", did_checkout
        except asyncio.TimeoutError:
            _logger.warning(
                f"  Timeout pushing {project['path']}"
            )
            return "error", did_checkout


async def push_to_local(
    erplibre_root,
    git_path,
    projects,
    remote_name,
    push_all_branches,
    unshallow,
    jobs,
):
    """Push to local remote for each repo (async)."""
    semaphore = asyncio.Semaphore(jobs)

    results = await asyncio.gather(
        *[
            _push_single_repo(
                erplibre_root,
                git_path,
                p,
                remote_name,
                push_all_branches,
                unshallow,
                semaphore,
            )
            for p in projects
        ]
    )

    pushed = sum(1 for s, _ in results if s == "pushed")
    errors = sum(1 for s, _ in results if s == "error")
    checkouts = sum(1 for _, c in results if c)
    print(
        f"Push: {pushed} pushed, {checkouts} branch"
        f" checkouts, {errors} errors"
    )


# --- Serve (stays synchronous — long-running daemon) ---


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
            clone_path = project["path"]
            if clone_path == ".":
                clone_path = "erplibre"
            print(
                f"  git clone {base_url}/{repo_name}"
                f" {clone_path}"
            )
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


# --- Main ---


async def run_actions(config, erplibre_root, projects):
    """Run init/remote/push actions asynchronously."""
    action = config.action
    jobs = config.jobs

    if action in ("init", "all"):
        print("=== Creating bare repos ===")
        await init_bare_repos(config.path, projects, jobs)
        print()

    if action in ("remote", "all"):
        print("=== Adding remotes ===")
        await add_remotes(
            erplibre_root,
            config.path,
            projects,
            config.remote_name,
            config.port,
            config.remote_url_type,
            jobs,
        )
        print()

    if action in ("push", "all"):
        print("=== Pushing to local ===")
        await push_to_local(
            erplibre_root,
            config.path,
            projects,
            config.remote_name,
            config.push_all_branches,
            config.unshallow,
            jobs,
        )
        print()


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
    print(f"Parallel jobs: {config.jobs}")
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

    # Run async actions (init, remote, push)
    asyncio.run(run_actions(config, erplibre_root, projects))

    # Serve is synchronous (long-running daemon)
    if config.action in ("serve", "all"):
        print("=== Starting git daemon ===")
        serve_git_daemon(config.path, projects, config.port)


if __name__ == "__main__":
    main()
