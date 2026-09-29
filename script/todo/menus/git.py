#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Git : Git, qu'ouvre Execute, Git local server et
ses deux menus Actions, l'un du serveur local, l'autre du serveur de
production.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place. Une entrée qui ouvre un sous-menu
nomme la méthode de TODO qui l'ouvre : son cadre porte le fil d'Ariane.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu

GIT = Menu(
    "prompt_execute_git",
    "Git",
    [
        Entry("Local git server", "prompt_execute_git_local_server"),
        Entry("Add a remote to a local repository", "_git_add_remote"),
        Entry(
            "Install git hooks (commit-msg, pre-commit)", "_git_install_hooks"
        ),
        Entry(
            "Set merge.conflictStyle to zdiff3 (global)",
            "_git_set_conflict_style",
        ),
        # Un élément de todo.json peut nommer la méthode qui le lance.
        FromConfig("git_from_makefile", "_git_from_configuration", "instance"),
        # Des outils de shell, pas de git : ils ferment la liste.
        Entry("Install Starship on Shell", "_shell_install_starship"),
        Entry("Install Claude Code", "_shell_install_claude_code"),
        Entry("Install opencode", "_shell_install_opencode"),
    ],
    intro="Git and shell management tools!",
    render="once",
)

GIT_LOCAL_SERVER = Menu(
    "prompt_execute_git_local_server",
    "Git local server",
    [
        Entry(
            "Deploy a local git server (~/.git-server)",
            "_prompt_git_server_local",
        ),
        Entry(
            "Deploy a production git server (/srv/git, root required)",
            "_prompt_git_server_production",
        ),
    ],
    intro="Manage local git repository server!",
    render="once",
)

# Les deux menus Actions ne diffèrent que par leur intro et par le
# `production_ready` que chaque entrée passe à `_deploy_git_server`.
GIT_SERVER_LOCAL = Menu(
    "_prompt_git_server_local",
    "Actions",
    [
        Entry(
            "Run all (init + remote + push + serve)",
            "_deploy_git_server",
            kwargs={"production_ready": False, "action": "all"},
        ),
        Entry(
            "Init - Create bare repos",
            "_deploy_git_server",
            kwargs={"production_ready": False, "action": "init"},
        ),
        Entry(
            "Remote - Add local remotes",
            "_deploy_git_server",
            kwargs={"production_ready": False, "action": "remote"},
        ),
        Entry(
            "Push - Push to local server",
            "_deploy_git_server",
            kwargs={"production_ready": False, "action": "push"},
        ),
        Entry(
            "Serve - Start git daemon",
            "_deploy_git_server",
            kwargs={"production_ready": False, "action": "serve"},
        ),
    ],
    intro="Local mode (~/.git-server)",
    render="once",
)

GIT_SERVER_PRODUCTION = Menu(
    "_prompt_git_server_production",
    "Actions",
    [
        Entry(
            "Run all (init + remote + push + serve)",
            "_deploy_git_server",
            kwargs={"production_ready": True, "action": "all"},
        ),
        Entry(
            "Init - Create bare repos",
            "_deploy_git_server",
            kwargs={"production_ready": True, "action": "init"},
        ),
        Entry(
            "Remote - Add local remotes",
            "_deploy_git_server",
            kwargs={"production_ready": True, "action": "remote"},
        ),
        Entry(
            "Push - Push to local server",
            "_deploy_git_server",
            kwargs={"production_ready": True, "action": "push"},
        ),
        Entry(
            "Serve - Start git daemon",
            "_deploy_git_server",
            kwargs={"production_ready": True, "action": "serve"},
        ),
    ],
    intro="Production mode (/srv/git, root required)",
    render="once",
)
