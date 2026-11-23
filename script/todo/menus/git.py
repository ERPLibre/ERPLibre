#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Git : Git repository, qu'ouvre Execute, Repo,
qu'ouvre Git repository, et le menu d'un dépôt en conflit, qu'ouvre sa
file d'attente, dont les méthodes vivent dans `git_repo_menu.py` ; Git
local server et ses deux menus Actions, l'un du serveur local, l'autre du
serveur de production ; Shell, qu'ouvre Execute ; GPT code, qu'ouvre
Execute, Claude configs et ses Repository settings, Plugins, RTK et
Claude Code, dont la méthode vit dans `assistant_menu.py` ; Automation,
qu'ouvre Execute.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place. Une entrée qui ouvre un sous-menu
nomme la méthode de TODO qui l'ouvre, le `name` de son `Menu`.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu, Section

GIT = Menu(
    "prompt_execute_git",
    "Git repository",
    [
        # Les éléments de `git_from_makefile` vont dans Repositories,
        # Settings ou Tools selon leur « menu_group » : Tools prend aussi
        # ceux qui n'en portent pas, comme en écrit « Ajouter une
        # automatisation », ou au groupe inconnu. Un élément peut nommer la
        # méthode qui le lance. Aucune section ne passe cinq entrées.
        # Portent `danger` les entrées qui retirent un dépôt d'un manifeste,
        # suppriment des branches ou archivent des forks, même après leur
        # propre confirmation, et celles qui agissent sans rien demander
        # après le choix : synchroniser un clone par `repo sync`, geler un
        # dépôt dans un manifeste suivi, avancer des forks sur GitHub.
        Section("Repositories"),
        Entry("🔃 Update git repo", "prompt_execute_git_repo"),
        FromConfig(
            "git_from_makefile",
            "_git_from_configuration",
            "instance",
            only=["repositories"],
        ),
        Entry(
            "🔄 Synchronise one repository",
            "_git_synchroniser_depot",
            danger=True,
        ),
        Entry(
            "🧊 Freeze one repository on a commit",
            "_git_regeler_depot",
            danger=True,
        ),
        Section("Manifest"),
        Entry("➕ Add a repository to a manifest", "_git_ajouter_depot"),
        Entry(
            "📁 Add a repository from an existing directory",
            "_git_ajouter_existant",
        ),
        Entry(
            "➖ Remove a repository from a manifest",
            "_git_retirer_depot",
            danger=True,
        ),
        Section("Forks"),
        Entry(
            "🍴 Fork a repository for an organisation",
            "_git_fork_organisation",
        ),
        Entry(
            "🔭 Add the upstream remote of a repository", "_git_ajouter_amont"
        ),
        Entry(
            "⏩ Update forks from their upstream on GitHub",
            "_git_mettre_forks_a_jour",
            danger=True,
        ),
        Entry(
            "🪦 List the orphan forks of an organisation",
            "_git_forks_orphelins",
            danger=True,
        ),
        Entry(
            "🔑 Check the GitHub token (scopes, organisation)",
            "_git_verifier_jeton",
        ),
        Section("Branches"),
        Entry("🌿 Create a branch in a repository", "_git_creer_branche"),
        Entry(
            "🌳 Create the same branch in several repositories",
            "_git_creer_branche_plusieurs",
        ),
        Entry(
            "🧹 Clean the merged branches of a repository",
            "_git_nettoyer_branches",
            danger=True,
        ),
        Section("Pull requests"),
        Entry(
            "📋 List the pull requests of an organisation",
            "_git_lister_pull_requests",
        ),
        Entry(
            "📬 Open a pull request from the current branch",
            "_git_creer_pull_request",
        ),
        Entry(
            "🚦 Status of my pull requests (review, CI, merged)",
            "_git_statut_mes_pull_requests",
        ),
        Section("Settings"),
        Entry(
            "Install git hooks (commit-msg, pre-commit)", "_git_install_hooks"
        ),
        Entry(
            "Set merge.conflictStyle to zdiff3 (global)",
            "_git_set_conflict_style",
        ),
        FromConfig(
            "git_from_makefile",
            "_git_from_configuration",
            "instance",
            only=["configuration"],
        ),
        Section("Tools"),
        Entry("Add a remote to a local repository", "_git_add_remote"),
        FromConfig(
            "git_from_makefile",
            "_git_from_configuration",
            "instance",
            without=["repositories", "configuration"],
        ),
        Section("Server"),
        Entry("Local git server", "prompt_execute_git_local_server"),
        Entry("Kill git daemon server process", "process_kill_git_daemon"),
    ],
    intro="Git repositories and git tools!",
    render="once",
)

# Des outils de shell, pas de git. Chacun lance un installateur et écrit
# dans le fichier du shell : `danger`.
SHELL = Menu(
    "prompt_execute_shell",
    "Shell",
    [
        Section("Installation"),
        Entry(
            "Install Starship on Shell", "_shell_install_starship", danger=True
        ),
        Entry(
            "Install Claude Code", "_shell_install_claude_code", danger=True
        ),
        Entry("Install opencode", "_shell_install_opencode", danger=True),
    ],
    intro="Shell tools!",
    render="once",
)

# La mise à jour des dépôts, qui suit le manifeste, puis leur mise à
# niveau sur l'amont de chaque fork, qui réécrit leur historique. La ligne
# d'état dit la version d'Odoo active, le nombre de forks, le mode du
# manifeste local et le gel des fichiers de `manifest/`.
REPO = Menu(
    "prompt_execute_git_repo",
    "Repo",
    [
        # Synchroniser et reconfigurer lancent `repo sync` ou
        # `make repo_configure_all` sur le checkout sans rien demander : ni
        # la TUI ni la page web ne les lancent (`danger`).
        Section("Update"),
        Entry(
            "🔄 Synchronize the repositories", "_git_repo_sync", danger=True
        ),
        Entry(
            "🔁 Switch to development: each repository follows its branch",
            "_git_repo_reconfigurer",
            danger=True,
        ),
        Entry("⬇️ Pull the repositories", "_git_repo_tirer"),
        Section("Upgrade"),
        Entry("🌐 Add the upstream remotes", "_git_repo_ajouter_remotes"),
        Entry("🔍 Upgrade — dry run", "_git_repo_a_sec"),
        Entry("⬆️ Apply the upgrade", "_git_repo_appliquer"),
        Entry("🧩 Conflict queue", "_git_repo_file_conflits"),
        Entry("📤 Publish the updated forks", "_git_repo_publier"),
        Section("Observe"),
        Entry("📊 Report of the last pass", "_git_repo_rapport"),
        Entry("🖥️ Browse the upgrade on screen", "_git_repo_ecran"),
        Entry("🔗 Fork and upstream status", "_git_repo_etat_forks"),
        Section("Versions"),
        Entry("🧊 Freeze the versions", "_git_repo_geler"),
        Entry(
            "📌 Switch to production: each repository on its frozen commit",
            "_git_repo_reconfigurer",
            kwargs={"freeze": True},
            danger=True,
        ),
        Entry(
            "🫗 Unfreeze the versions",
            "_git_repo_geler",
            kwargs={"unfreeze": True},
        ),
        Entry("🔀 Compare two freezes", "_git_repo_comparer"),
    ],
    intro="Update and upgrade the git repositories",
    mark="🔃",
    state="_git_repo_etat",
    render="once",
)

# Les gestes sur un dépôt resté en conflit, celui que la file d'attente a
# choisi et que `_git_repo_resoudre` pose avec l'horodatage de sa passe :
# la ligne d'état liste ses fichiers en conflit, relue à chaque tour. Un
# geste qui quitte le rebase rend vrai et referme le menu.
CONFLICT = Menu(
    "_git_repo_gestes",
    "Conflict queue",
    [
        Entry(
            "🐚 Open a shell here",
            "_git_repo_geste",
            kwargs={"geste": "shell"},
        ),
        Entry(
            "👀 Show the conflicting diff",
            "_git_repo_geste",
            kwargs={"geste": "diff"},
        ),
        Entry("⬅️ Keep ours", "_git_repo_geste", kwargs={"geste": "notre"}),
        Entry("➡️ Take upstream", "_git_repo_geste", kwargs={"geste": "amont"}),
        Entry(
            "▶️ Continue the rebase",
            "_git_repo_geste",
            kwargs={"geste": "continuer"},
        ),
        Entry(
            "⏭️ Skip this commit",
            "_git_repo_geste",
            kwargs={"geste": "sauter"},
        ),
        Entry(
            "⏸️ Abort this rebase",
            "_git_repo_geste",
            kwargs={"geste": "abandonner"},
        ),
        Entry(
            "↩️ Return to the state managed by repo",
            "_git_repo_geste",
            kwargs={"geste": "revenir"},
        ),
    ],
    state="_git_repo_conflit_etat",
    closes_on_result=True,
    abort_closes=True,
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

# Les deux menus Actions ne diffèrent que par leur intro, par le
# `production_ready` que chaque entrée passe à `_deploy_git_server` et par
# `danger`. Les actions de production le portent toutes : elles tournent en
# root. En local, tout le porte sauf Init, qui n'écrit que sous
# ~/.git-server : Remote et Push ajoutent un remote à chaque dépôt du
# checkout ou y poussent, Serve ouvre les dépôts nus à la lecture et au
# push anonymes sur toutes les interfaces, chacun sans rien demander.
GIT_SERVER_LOCAL = Menu(
    "_prompt_git_server_local",
    "Actions",
    [
        Entry(
            "Run all (init + remote + push + serve)",
            "_deploy_git_server",
            kwargs={"production_ready": False, "action": "all"},
            danger=True,
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
            danger=True,
        ),
        Entry(
            "Push - Push to local server",
            "_deploy_git_server",
            kwargs={"production_ready": False, "action": "push"},
            danger=True,
        ),
        Entry(
            "Serve - Start git daemon",
            "_deploy_git_server",
            kwargs={"production_ready": False, "action": "serve"},
            danger=True,
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
            danger=True,
        ),
        Entry(
            "Init - Create bare repos",
            "_deploy_git_server",
            kwargs={"production_ready": True, "action": "init"},
            danger=True,
        ),
        Entry(
            "Remote - Add local remotes",
            "_deploy_git_server",
            kwargs={"production_ready": True, "action": "remote"},
            danger=True,
        ),
        Entry(
            "Push - Push to local server",
            "_deploy_git_server",
            kwargs={"production_ready": True, "action": "push"},
            danger=True,
        ),
        Entry(
            "Serve - Start git daemon",
            "_deploy_git_server",
            kwargs={"production_ready": True, "action": "serve"},
            danger=True,
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
        # Réécrit script/todo/todo.json, suivi par git, sans confirmation.
        Entry(
            "Add an automation with Claude in todo.py",
            "_claude_add_automation",
            danger=True,
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
        Entry(
            "⚙️ Repository settings: ultracode and session message",
            "_claude_reglages_depot",
        ),
    ],
    intro="Deploy Claude Code commands!",
    render="once",
)

# Les réglages de .claude/settings.json, le fichier versionné du dépôt. Un
# fichier qui n'est pas un objet JSON n'ouvre pas le menu : rien ne doit
# l'écraser. Chaque libellé est fixe et son état le suit, relu à chaque
# dessin. Aucune entrée ne porte `danger` : chaque bascule montre le
# fichier qu'elle écrirait et demande un oui avant de l'écrire, et
# l'aperçu n'écrit rien.
REPOSITORY_SETTINGS = Menu(
    "_claude_reglages_depot",
    "Repository settings",
    [
        Entry(
            "Ultracode by default",
            "_claude_basculer_ultracode",
            suffix="_claude_ultracode_etat",
        ),
        Entry(
            "Session message",
            "_claude_basculer_hook",
            suffix="_claude_hook_etat",
        ),
        Entry("Preview the session message", "_claude_apercu_hook"),
    ],
    state="_claude_reglages_etat",
    opens="_claude_reglages_ouvre",
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
        # Poser, mettre à jour ou retirer un plugin, ajouter un
        # marketplace change ce que chaque session de Claude Code charge :
        # `danger`. L'inventaire, la recherche et le détail lisent.
        Section("Install plugins"),
        Entry(
            "Install the ERPLibre preferred list",
            "_claude_install_preferred_plugins",
            danger=True,
        ),
        Entry(
            "Install a plugin by name",
            "_claude_plugin_install_by_name",
            danger=True,
        ),
        Entry("Add a marketplace", "_claude_marketplace_add", danger=True),
        Section("Maintenance"),
        Entry(
            "Update the marketplaces and the plugins",
            "_claude_plugin_update",
            danger=True,
        ),
        Entry("Uninstall a plugin", "_claude_plugin_uninstall", danger=True),
    ],
    intro="Manage Claude Code plugins and marketplaces!",
    render="once",
)

RTK = Menu(
    "prompt_execute_rtk",
    "RTK",
    [
        # L'installation lance un installateur et le crochet global
        # réécrit la configuration de Claude Code du compte : `danger`.
        Section("Setup"),
        Entry("Install RTK", "rtk_install", danger=True),
        Entry(
            "Initialize global auto-rewrite hook",
            "rtk_init_global",
            danger=True,
        ),
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

AUTOMATION = Menu(
    "prompt_execute_function",
    "Automation",
    [FromConfig("function", "execute_from_configuration", "instance")],
    render="once",
)
