#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Git : Git, qu'ouvre Execute, Git local server et
ses deux menus Actions, l'un du serveur local, l'autre du serveur de
production ; GPT code, qu'ouvre Execute, Claude configs, Plugins, RTK et
Claude Code, dont la méthode vit dans `assistant_menu.py`.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place. Une entrée qui ouvre un sous-menu
nomme la méthode de TODO qui l'ouvre : son cadre porte le fil d'Ariane.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu, Section

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

GPT_CODE = Menu(
    "prompt_execute_gpt_code",
    "GPT code",
    [
        Entry(
            "Configure Claude Code configurations", "_prompt_claude_configs"
        ),
        Entry(
            "Add an automation with Claude in todo.py",
            "_claude_add_automation",
        ),
        Entry(
            "RTK - CLI proxy to reduce LLM token consumption",
            "prompt_execute_rtk",
        ),
        Entry("Show the context given to Claude", "_show_claude_context"),
        Entry(
            "Claude Code plugins - marketplaces and ERPLibre list",
            "prompt_execute_claude_plugins",
        ),
        Entry("Claude Code - local sessions", "prompt_claude_sessions"),
    ],
    intro="AI assistant tools for development!",
    render="once",
)

CLAUDE_CONFIGS = Menu(
    "_prompt_claude_configs",
    "Claude configs",
    [
        Entry(
            "Commit - OCA/Odoo commit command",
            "_setup_claude_command",
            kwargs={
                "command_name": "commit",
                "template_filename": "template_claude_commands_commit.md",
                "personalize": True,
            },
        ),
        Entry(
            "Git prepare merge - Git merge preparation command",
            "_setup_claude_command",
            kwargs={
                "command_name": "git_prepare_merge",
                "template_filename": (
                    "template_claude_commands_git_prepare_merge.md"
                ),
            },
        ),
        # Deux commandes, qui vont ensemble.
        Entry(
            "Todo Add Command + Plan Max - Plan and add a todo.py command",
            "_setup_claude_todo_commands",
        ),
        Entry(
            "Todo Generate Code - Code by the OCA rules at high effort",
            "_setup_claude_command",
            kwargs={
                "command_name": "todo_generate_code",
                "template_filename": (
                    "template_claude_commands_todo_generate_code.md"
                ),
            },
        ),
        Entry("Show installed custom commands", "_list_claude_commands"),
    ],
    intro="Deploy Claude Code commands!",
    render="once",
)

PLUGINS = Menu(
    "prompt_execute_claude_plugins",
    "Plugins",
    [
        Section("Inventory"),
        Entry(
            "List installed plugins",
            "_claude_plugin_exec",
            kwargs={"args": "list"},
        ),
        Entry(
            "List configured marketplaces",
            "_claude_plugin_exec",
            kwargs={"args": "marketplace list"},
        ),
        Entry("Search a plugin in the marketplaces", "_claude_plugin_search"),
        Entry(
            "Show a plugin detail and its token cost", "_claude_plugin_details"
        ),
        Section("Install plugins"),
        Entry(
            "Install the ERPLibre preferred list",
            "_claude_install_preferred_plugins",
        ),
        Entry("Install a plugin by name", "_claude_plugin_install_by_name"),
        Entry("Add a marketplace", "_claude_marketplace_add"),
        Section("Maintenance"),
        Entry(
            "Update the marketplaces and the plugins", "_claude_plugin_update"
        ),
        Entry("Uninstall a plugin", "_claude_plugin_uninstall"),
    ],
    intro="Manage Claude Code plugins and marketplaces!",
    render="once",
)

RTK = Menu(
    "prompt_execute_rtk",
    "RTK",
    [
        Section("Setup"),
        Entry("Install RTK", "rtk_install"),
        Entry("Initialize global auto-rewrite hook", "rtk_init_global"),
        Section("Status"),
        Entry("Check RTK version", "rtk_check_version"),
        Entry("Check RTK status", "rtk_check_status"),
        Entry("Show cumulative token savings", "rtk_show_gain"),
        Section("Optimize"),
        Entry("Discover optimization opportunities", "rtk_discover"),
    ],
    intro="Manage RTK (Rust Token Killer) for token optimization!",
    render="once",
)

# Redessiné à chaque tour : le compte des sessions se relit. Ctrl+C à sa
# question ramène à GPT code au lieu de terminer TODO.
CLAUDE_CODE = Menu(
    "prompt_claude_sessions",
    "Claude Code",
    [
        Entry(
            "List local sessions",
            "_claude_lister",
            suffix="_claude_sessions_count",
        ),
        Entry("Ask a question to a session", "_claude_questionner"),
        Entry("Resume a session in a new terminal", "_claude_reprendre"),
    ],
    intro="Local Claude Code sessions",
    back=None,
    abort_closes=True,
)
