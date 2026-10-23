#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Modifier le cœur de Dolibarr : branche de travail, contrôle, patchs.

    ./script/dolibarr/core.py status
    ./script/dolibarr/core.py start --topic fix-invoice-total [--deepen 100]
    ./script/dolibarr/core.py check
    ./script/dolibarr/core.py patches [--out DIR]

Tout se passe dans le checkout épinglé et sur cette machine : rien n'est
poussé, aucune PR n'est ouverte ; pousser reste le geste du développeur.

start crée la branche de travail au commit épinglé (repo start quand le
checkout vient de Google Repo) et approfondit l'historique du checkout, à
profondeur 1 sinon, pour qu'un rebase et une série de patchs aient leur
contexte. Il refuse sans identité git : repo sync remet à zéro, sans rien
dire, une branche dont aucun commit ne porte le courriel configuré ; status
le signale pour une branche existante.

check applique aux commits depuis l'épinglé les règles de
.github/CONTRIBUTING.md de Dolibarr : Signed-off-by de l'auteur (DCO),
mot-clé du titre (FIX, CLOSE, NEW, PERF, DOC, QUAL, SEC, en capitales pour
le ChangeLog), ChangeLog et langues autres qu'en_US intouchables, une seule
correction par PR sur une branche stable, structure de base et
bibliothèques dans une PR à part. Un correctif vise la plus vieille version
touchée (N-2 conseillé), le reste develop.

patches exporte la série (git format-patch) sous private/dolibarr/patches/.
status dit aussi si le fork ERPLibre/dolibarr répond : son manifest de
développement vient une fois le fork créé.
"""

import argparse
import datetime
import os
import re
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import backup, lib_dolibarr  # noqa: E402

ROOT = new_path
t = backup.t

FORK = "https://github.com/ERPLibre/dolibarr.git"
REMOTE = "Dolibarr"
REPO = os.path.join(".venv.erplibre", "bin", "repo")
PATCHES = os.path.join("private", "dolibarr", "patches")
KEYWORDS = ("FIX", "CLOSE", "NEW", "PERF", "DOC", "QUAL", "SEC")
OK, FAIL, WARN = "✓", "✗", "!"
_TOPIC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_TITLE = re.compile(r"^(?P<kw>[A-Za-z]+)(?::|\s)\s*(?P<rest>.*)$")
_ISSUE = re.compile(r"^(#\w+)\s+(.*)$")
_OTHER_LANG = re.compile(r"^htdocs/langs/(?!en_US/)[^/]+/.+\.lang$")
_STRUCTURE = re.compile(r"^htdocs/install/mysql/(tables|migration)/")
_SEP, _END = "\x1f", "\x1e"


def parse_title(subject):
    """(mot-clé ou None, ticket ou None, description)."""
    m = _TITLE.match(subject)
    if not m or m.group("kw").upper() not in KEYWORDS:
        return None, None, subject
    rest = m.group("rest")
    issue = _ISSUE.match(rest)
    if issue:
        return m.group("kw"), issue.group(1), issue.group(2)
    return m.group("kw"), None, rest


def review(commits, files, branch):
    """[(niveau, message)] des règles de CONTRIBUTING.md sur `commits`
    ({sha, author, email, subject, body}) et les fichiers qu'ils touchent,
    pour une PR vers `branch`."""
    results = []
    unsigned = [
        c["sha"][:7]
        for c in commits
        if not re.search(
            rf"^Signed-off-by: .* <{re.escape(c['email'])}>\s*$",
            c["body"],
            re.M,
        )
    ]
    results.append(
        (
            FAIL,
            t("Without the author's Signed-off-by (DCO): %s")
            % ", ".join(unsigned),
        )
        if unsigned
        else (OK, t("Every commit signed off by its author (DCO)"))
    )
    keywords = []
    for c in commits:
        kw, issue, desc = parse_title(c["subject"])
        keywords.append((kw or "").upper())
        sha = c["sha"][:7]
        if kw is None:
            results.append(
                (
                    WARN,
                    t("%s: no keyword (FIX, CLOSE, NEW, PERF, DOC, QUAL, SEC)")
                    % sha,
                )
            )
        elif not kw.isupper():
            results.append(
                (
                    WARN,
                    t("%s: %s reaches the ChangeLog only in capitals")
                    % (sha, kw),
                )
            )
        if kw and kw.upper() == "CLOSE" and not issue:
            results.append(
                (WARN, t("%s: CLOSE names the issue it closes (#123)") % sha)
            )
        if len(desc) > 50:
            results.append(
                (
                    WARN,
                    t("%s: description of %d characters, 50 at most advised")
                    % (sha, len(desc)),
                )
            )
    forbidden = [f for f in files if f == "ChangeLog" or _OTHER_LANG.match(f)]
    results.append(
        (
            FAIL,
            t("Files left to the release process or to Transifex: %s")
            % ", ".join(forbidden),
        )
        if forbidden
        else (OK, t("Neither ChangeLog nor a language other than en_US"))
    )
    if branch != "develop":
        if len(commits) > 1:
            results.append(
                (
                    WARN,
                    t("Branch %s is stable: one fix per PR, here %d commits")
                    % (branch, len(commits)),
                )
            )
        if any(kw not in ("FIX", "SEC") for kw in keywords):
            results.append(
                (
                    WARN,
                    t(
                        "Branch %s is stable: anything but a fix goes to develop"
                    )
                    % branch,
                )
            )
    for path in files:
        if _STRUCTURE.match(path):
            results.append(
                (
                    WARN,
                    t("%s: structure changes go first in a PR of their own")
                    % path,
                )
            )
        elif path.startswith("htdocs/includes/"):
            results.append(
                (
                    WARN,
                    t("%s: a new library needs the project's approval first")
                    % path,
                )
            )
    return results


class Checkout:
    """Le checkout épinglé, lu et modifié par git."""

    def __init__(self, root, system):
        self.root, self.system = root, system
        try:
            self.pin = lib_dolibarr.read_pin(root)
        except lib_dolibarr.PinError as e:
            raise CoreError(t("Dolibarr pin unreadable: %s") % e)
        self.path = os.path.join(root, self.pin["path"])
        if not os.path.isdir(self.path):
            raise CoreError(
                t(
                    "No Dolibarr checkout at %s: sync it with"
                    " script/manifest/update_manifest_local_dolibarr.sh"
                )
                % self.path
            )

    def git(self, args, env=None):
        return self.system.run(["git", "-C", self.path] + args, env)

    def out(self, args):
        code, out = self.git(args)
        return out.strip() if code == 0 else ""

    def email(self):
        return self.out(["config", "user.email"])

    def commits(self):
        # Pas de strip() sur la sortie : \x1e et \x1f comptent pour des
        # blancs, et un dernier commit sans corps perdrait ses champs.
        code, raw = self.git(
            ["log", f"--format=%H{_SEP}%an{_SEP}%ae{_SEP}%s{_SEP}%b{_END}"]
            + [f"{self.pin['commit']}..HEAD"]
        )
        if code:
            return []
        commits = []
        for record in raw.split(_END):
            fields = record.strip("\n").split(_SEP)
            if len(fields) == 5:
                keys = ("sha", "author", "email", "subject", "body")
                commits.append(dict(zip(keys, fields)))
        return commits

    def files(self):
        return self.out(
            ["diff", "--name-only", f"{self.pin['commit']}..HEAD"]
        ).splitlines()


class CoreError(Exception):
    """Refus : sortie 2."""


def start(co, topic, depth):
    if not _TOPIC.match(topic):
        raise CoreError(t("Invalid branch name: %s") % topic)
    if not co.email():
        raise CoreError(
            t(
                "No git identity (user.email): repo sync would reset the branch."
                " Set it with: git config --global user.email ..."
            )
        )
    repo = os.path.join(co.root, REPO)
    if os.path.isdir(os.path.join(co.root, ".repo")) and os.path.exists(repo):
        code, out = co.system.run(
            [
                "sh",
                "-c",
                f"cd '{co.root}' && exec {REPO} start {topic} {co.pin['path']}",
            ]
        )
    else:
        code, out = co.git(["checkout", "-q", "-b", topic, co.pin["commit"]])
    if code:
        print(out.strip()[-500:])
        return 1
    code, out = co.git(
        [
            "fetch",
            "-q",
            f"--deepen={depth}",
            REMOTE,
            f"refs/heads/{co.pin['branch']}",
        ]
    )
    if code:
        print(
            t("Branch %s created; the history could not be deepened:") % topic
        )
        print(out.strip()[-500:])
        return 1
    print(
        t("Branch %s at the pinned commit %s, history deepened by %d.")
        % (topic, co.pin["commit"][:7], depth)
    )
    return 0


def status(co):
    branch = co.out(["rev-parse", "--abbrev-ref", "HEAD"])
    head = co.out(["rev-parse", "HEAD"])
    where = t("detached") if branch == "HEAD" else branch
    print(
        t("Pinned commit: %s (%s, branch %s)")
        % (co.pin["commit"][:7], co.pin["version"], co.pin["branch"])
    )
    print(t("Checkout: %s at %s") % (where, head[:7]))
    commits = co.commits()
    dirty = [x for x in co.out(["status", "--porcelain"]).splitlines() if x]
    print(
        t("Work since the pin: %d commit(s), %d uncommitted file(s)")
        % (len(commits), len(dirty))
    )
    shallow = co.out(["rev-parse", "--is-shallow-repository"]) == "true"
    depth = co.out(["rev-list", "--count", "HEAD"])
    print(
        (
            t("History: shallow, %s commit(s)")
            if shallow
            else t("History: full, %s commit(s)")
        )
        % depth
    )
    email = co.email()
    risk = bool(commits) and not any(c["email"] == email for c in commits)
    if risk:
        print(
            f"  {FAIL} "
            + t("No commit carries %s: the next repo sync resets this branch.")
            % (email or "user.email")
        )
    code, _out = co.system.run(
        ["git", "ls-remote", "--heads", FORK], {"GIT_TERMINAL_PROMPT": "0"}
    )
    print(
        t(
            "Fork ERPLibre/dolibarr: answers; its development manifest comes next."
        )
        if code == 0
        else t(
            "Fork ERPLibre/dolibarr: not found; work stays on a local branch."
        )
    )
    return 1 if risk else 0


def check(co):
    commits = co.commits()
    if not commits:
        print(t("No work commit since the pinned commit."))
        return 0
    results = review(commits, co.files(), co.pin["branch"])
    for level, message in results:
        print(f"  {level} {message}")
    print(
        t(
            "A fix targets the oldest affected version (N-2 advised),"
            " anything else develop."
        )
    )
    return 1 if any(level == FAIL for level, _m in results) else 0


def patches(co, out, now):
    commits = co.commits()
    if not commits:
        print(t("No work commit since the pinned commit."))
        return 0
    branch = co.out(["rev-parse", "--abbrev-ref", "HEAD"])
    name = f"{branch if branch != 'HEAD' else 'detached'}-{now:%Y%m%d-%H%M%S}"
    dest = out or os.path.join(co.root, PATCHES, name)
    code, listing = co.git(
        ["format-patch", "-q", "-o", dest, f"{co.pin['commit']}..HEAD"]
    )
    if code:
        print(listing.strip()[-500:])
        return 1
    print(t("%d patch(es) in %s") % (len(commits), dest))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    p = sub.add_parser("start")
    p.add_argument("--topic", required=True)
    p.add_argument("--deepen", type=int, default=100)
    sub.add_parser("check")
    p = sub.add_parser("patches")
    p.add_argument("--out")
    return parser


def main(argv=None, root=None, system=None, now=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    system = system or backup.System()
    try:
        co = Checkout(root, system)
        if args.action == "start":
            return start(co, args.topic, args.deepen)
        if args.action == "status":
            return status(co)
        if args.action == "check":
            return check(co)
        return patches(co, args.out, now or datetime.datetime.now())
    except CoreError as e:
        print(e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
