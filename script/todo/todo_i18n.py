#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import re

ENV_VAR_FILE = "./env_var.sh"

_current_lang = None

TRANSLATIONS = {
    # Main menu
    "Importation success!": {
        "fr": "L'importation est un succès!",
        "en": "Importation success!",
    },
    "opening": {
        "fr": "Ouverture de TODO en cours ...",
        "en": "Opening TODO ...",
    },
    "enter_directives": {
        "fr": "=> Entre tes directives par son chiffre et fait Entrée!",
        "en": "=> Enter your choice by number and press Enter!",
    },
    "command": {
        "fr": "Commande :",
        "en": "Command:",
    },
    "menu_execute": {
        "fr": "Exécution",
        "en": "Execute",
    },
    "menu_install": {
        "fr": "Installation",
        "en": "Install",
    },
    "menu_question": {
        "fr": "Question",
        "en": "Question",
    },
    "menu_fork": {
        "fr": "Fork - Ouvre TODO dans une nouvelle tabulation",
        "en": "Fork - Open TODO in a new tab",
    },
    "menu_quit": {
        "fr": "Quitter",
        "en": "Quit",
    },
    "cmd_not_found": {
        "fr": "Commande non trouvée !",
        "en": "Command not found !",
    },
    "back": {
        "fr": "Retour",
        "en": "Back",
    },
    # Execute submenu
    "menu_run": {
        "fr": "Run - Exécuter et installer une instance",
        "en": "Run - Execute and install an instance",
    },
    "menu_automation": {
        "fr": "Automatisation - Demonstration des fonctions développées",
        "en": "Automation - Demonstration of developed features",
    },
    "menu_update": {
        "fr": "Mise à jour - Update all developed staging source code",
        "en": "Update - Update all developed staging source code",
    },
    "menu_code": {
        "fr": "Code - Outil pour développeur",
        "en": "Code - Developer tools",
    },
    "menu_doc": {
        "fr": "Doc - Recherche de documentation",
        "en": "Doc - Documentation search",
    },
    "menu_database": {
        "fr": "Database - Outils sur les bases de données",
        "en": "Database - Database tools",
    },
    "menu_process": {
        "fr": "Process - Outils sur les executions",
        "en": "Process - Execution tools",
    },
    "menu_config": {
        "fr": "Config - Traitement du fichier de configuration",
        "en": "Config - Configuration file management",
    },
    "menu_network": {
        "fr": "Réseau - Outil réseautique",
        "en": "Network - Network tools",
    },
    "menu_security": {
        "fr": "Sécurité - Audit de sécurité des dépendances",
        "en": "Security - Dependency security audit",
    },
    "menu_rtk": {
        "fr": "RTK - Proxy CLI pour réduire la consommation de tokens LLM",
        "en": "RTK - CLI proxy to reduce LLM token consumption",
    },
    "menu_lang": {
        "fr": "Langue - Changer la langue / Change language",
        "en": "Language - Change language / Changer la langue",
    },
    # RTK (Rust Token Killer)
    "rtk_manage": {
        "fr": "Gérer RTK (Rust Token Killer) pour optimiser les tokens!",
        "en": "Manage RTK (Rust Token Killer) for token optimization!",
    },
    "rtk_install": {
        "fr": "Installer RTK",
        "en": "Install RTK",
    },
    "rtk_version": {
        "fr": "Vérifier la version de RTK",
        "en": "Check RTK version",
    },
    "rtk_gain": {
        "fr": "Afficher les économies de tokens cumulées",
        "en": "Show cumulative token savings",
    },
    "rtk_discover": {
        "fr": "Identifier les opportunités d'optimisation",
        "en": "Discover optimization opportunities",
    },
    "rtk_init_global": {
        "fr": "Initialiser le hook auto-rewrite global",
        "en": "Initialize global auto-rewrite hook",
    },
    "rtk_status": {
        "fr": "Vérifier le statut de RTK",
        "en": "Check RTK status",
    },
    "rtk_not_installed": {
        "fr": "RTK n'est pas installé. Utilisez l'option 1 pour l'installer.",
        "en": "RTK is not installed. Use option 1 to install it.",
    },
    "rtk_installed_version": {
        "fr": "RTK est installé, version : ",
        "en": "RTK is installed, version: ",
    },
    "rtk_hook_active": {
        "fr": "Hook auto-rewrite global : actif",
        "en": "Global auto-rewrite hook: active",
    },
    "rtk_hook_inactive": {
        "fr": "Hook auto-rewrite global : inactif",
        "en": "Global auto-rewrite hook: inactive",
    },
    "rtk_install_method": {
        "fr": "Méthode d'installation :",
        "en": "Installation method:",
    },
    "rtk_install_curl": {
        "fr": "curl - Script d'installation automatique",
        "en": "curl - Automatic install script",
    },
    "rtk_install_brew": {
        "fr": "brew - Homebrew (macOS/Linux)",
        "en": "brew - Homebrew (macOS/Linux)",
    },
    "rtk_install_cargo": {
        "fr": "cargo - Compilation depuis les sources (Rust requis)",
        "en": "cargo - Build from source (Rust required)",
    },
    # Prompts and messages
    "enter_password": {
        "fr": "Entrez votre mot de passe : ",
        "en": "Enter your password: ",
    },
    "ia_prompt": {
        "fr": "Écrit moi ta question ",
        "en": "Write your question ",
    },
    "new_instance_confirm": {
        "fr": "Voulez-vous une nouvelle instance?",
        "en": "Do you want a new instance?",
    },
    "ssh_port_forwarding": {
        "fr": "SSH port-forwarding",
        "en": "SSH port-forwarding",
    },
    "network_performance_request_per_second": {
        "fr": "Performance réseau en requêtes par seconde",
        "en": "Network performance request per second",
    },
    "setup_queue_job_for_parallelism": {
        "fr": "Configurer la file d'attente pour l'exécution parallèle",
        "en": "Setup queue job for parallelism",
    },
    "choose_database": {
        "fr": "Choisir sa base de données",
        "en": "Choose your database",
    },
    "update_dev": {
        "fr": "Mise à jour du développement",
        "en": "Development update",
    },
    "code_need": {
        "fr": "Qu'avez-vous de besoin pour développer?",
        "en": "What do you need for development?",
    },
    "doc_search": {
        "fr": "Vous cherchez de la documentation?",
        "en": "Looking for documentation?",
    },
    "db_modify": {
        "fr": "Faites des modifications sur les bases de données!",
        "en": "Make changes to databases!",
    },
    "process_manage": {
        "fr": "Manipuler les processus d'exécution!",
        "en": "Manage execution processes!",
    },
    "config_manage": {
        "fr": "Manipuler la configuration ERPLibre et Odoo!",
        "en": "Manage ERPLibre and Odoo configuration!",
    },
    "network_tools": {
        "fr": "Outil réseautique!",
        "en": "Network tools!",
    },
    "security_audit": {
        "fr": "Audit de securite des dépendances!",
        "en": "Dependency security audit!",
    },
    "script_failed": {
        "fr": "Le script Bash a échoué avec le code de retour",
        "en": "The Bash script failed with return code",
    },
    "no_env_installed": {
        "fr": "Aucun environnement installe trouve. Installez d'abord une version d'Odoo.",
        "en": "No installed environment found. Install an Odoo version first.",
    },
    "choose_env_audit": {
        "fr": "Choisir un environnement pour l'audit :",
        "en": "Choose an environment for the audit:",
    },
    "selection": {
        "fr": "Sélection : ",
        "en": "Select: ",
    },
    "error_value": {
        "fr": "Erreur, impossible de comprendre la valeur",
        "en": "Error, cannot understand value",
    },
    "dep_file_not_found": {
        "fr": "Fichier de dépendances introuvable : ",
        "en": "Dependencies file not found: ",
    },
    "execution": {
        "fr": "Execution : ",
        "en": "Execution: ",
    },
    "current": {
        "fr": "Actuel",
        "en": "Current",
    },
    "default": {
        "fr": "Défaut",
        "en": "Default",
    },
    "reboot_todo": {
        "fr": "Reboot TODO ...",
        "en": "Reboot TODO ...",
    },
    "pip_audit_desc": {
        "fr": "pip-audit - Verifier les vulnérabilités sur les environnements Python",
        "en": "pip-audit - Check vulnerabilities on Python environments",
    },
    "will_execute": {
        "fr": "Va exécuter :",
        "en": "Will execute:",
    },
    "choose_version": {
        "fr": "Choisir une version :",
        "en": "Choose a version:",
    },
    "error_cannot_understand": {
        "fr": "Erreur, impossible de comprendre la valeur",
        "en": "Error, cannot understand value",
    },
    # todo.json translatable prompt_descriptions
    "json_instance_test": {
        "fr": "Test - Instance de base minimale",
        "en": "Test - Minimal base instance",
    },
    "json_robot_minimal": {
        "fr": "Ouvrir RobotLibre 🤖 minimal",
        "en": "Open RobotLibre 🤖 minimal",
    },
    "json_robot_search": {
        "fr": "Ouvrir RobotLibre 🤖 en activant la recherche",
        "en": "Open RobotLibre 🤖 with search enabled",
    },
    "json_open_erplibre_todo": {
        "fr": "Ouvrir ERPLibre avec TODO 🤖",
        "en": "Open ERPLibre with TODO 🤖",
    },
    "json_update_erplibre_base_test": {
        "fr": "Mise à jour de tous les erplibre_base sur la base de données test",
        "en": "Update all erplibre_base on database test",
    },
    "json_show_code_status": {
        "fr": "Afficher le statut du code",
        "en": "Show code status",
    },
    "json_stash_all_code": {
        "fr": "Remiser tout le code",
        "en": "Stash all code",
    },
    "json_format_modified_code": {
        "fr": "Formater le code modifié",
        "en": "Format modified code",
    },
    # todo.py hardcoded prompt_descriptions
    "mobile_compile_run": {
        "fr": "Mobile - Compiler et exécuter le logiciel",
        "en": "Mobile - Compile and run software",
    },
    "upgrade_odoo_migration": {
        "fr": "Mise à jour Odoo - Migration de base de données",
        "en": "Upgrade Odoo - Migration Database",
    },
    "upgrade_poetry_dependency": {
        "fr": "Mise à jour Poetry - Dépendances d'Odoo",
        "en": "Upgrade Poetry - Dependency of Odoo",
    },
    "open_shell": {
        "fr": "Ouvrir le SHELL",
        "en": "Open SHELL",
    },
    "upgrade_module": {
        "fr": "Mise à jour de module",
        "en": "Upgrade Module",
    },
    "debug": {
        "fr": "Débogage",
        "en": "Debug",
    },
    "migration_module_coverage": {
        "fr": "Couverture de migration des modules",
        "en": "Migration module coverage",
    },
    "what_change_between_version": {
        "fr": "Quels changements entre les versions",
        "en": "What change between version",
    },
    "oca_guidelines": {
        "fr": "Directives OCA",
        "en": "OCA guidelines",
    },
    "oca_migration_odoo_19": {
        "fr": "Migration OCA Odoo 19 - Jalons",
        "en": "OCA migration Odoo 19 milestone",
    },
    "download_db_backup": {
        "fr": "Télécharger une base de données pour créer une sauvegarde (.zip)",
        "en": "Download database to create backup (.zip)",
    },
    "restore_from_backup": {
        "fr": "Restaurer a partir d'une sauvegarde (.zip)",
        "en": "Restore from backup (.zip)",
    },
    "create_backup": {
        "fr": "Créer une sauvegarde (.zip)",
        "en": "Create backup (.zip)",
    },
    "kill_process_port": {
        "fr": "Terminer le processus Odoo du port actuel",
        "en": "Kill Odoo process from actual port",
    },
    "kill_git_daemon": {
        "fr": "Terminer le processus du serveur git daemon",
        "en": "Kill git daemon server process",
    },
    "kill_git_daemon_done": {
        "fr": "Processus git daemon terminé.",
        "en": "Git daemon process killed.",
    },
    "generate_all_config": {
        "fr": "Générer toute la configuration",
        "en": "Generate all configuration",
    },
    "generate_from_preconfig": {
        "fr": "Générer a partir de la pre-configuration",
        "en": "Generate from pre-configuration",
    },
    "generate_from_backup": {
        "fr": "Générer a partir d'un fichier de sauvegarde",
        "en": "Generate from backup file",
    },
    "generate_from_database": {
        "fr": "Générer a partir de la base de données",
        "en": "Generate from database",
    },
    "preconfig_base": {
        "fr": "base",
        "en": "base",
    },
    "preconfig_base_code_generator": {
        "fr": "base + code_generator",
        "en": "base + code_generator",
    },
    "preconfig_base_image_db": {
        "fr": "base + image_db",
        "en": "base + image_db",
    },
    "preconfig_all": {
        "fr": "tout",
        "en": "all",
    },
    "debug_todo_py": {
        "fr": "Débogage todo.py",
        "en": "Debug todo.py",
    },
    # Test section
    "menu_test": {
        "fr": "Test - Tester un module Odoo",
        "en": "Test - Test an Odoo module",
    },
    "test_description": {
        "fr": "Tester un module Odoo sur une base de données temporaire!",
        "en": "Test an Odoo module on a temporary database!",
    },
    "test_run_module": {
        "fr": "Tester un module",
        "en": "Test a module",
    },
    "test_run_module_coverage": {
        "fr": "Tester un module avec couverture de code",
        "en": "Test a module with code coverage",
    },
    "test_run_unit_tests": {
        "fr": "Tests unitaires ERPLibre",
        "en": "ERPLibre unit tests",
    },
    "test_unit_running": {
        "fr": "Exécution des tests unitaires",
        "en": "Running unit tests",
    },
    "test_unit_success": {
        "fr": "Tous les tests unitaires ont réussi",
        "en": "All unit tests passed",
    },
    "test_unit_failed": {
        "fr": "Des tests unitaires ont échoué, code de sortie",
        "en": "Some unit tests failed, exit code",
    },
    "test_enter_module_name": {
        "fr": "Nom du module à tester : ",
        "en": "Module name to test: ",
    },
    "test_db_name": {
        "fr": "Nom de la base de données temporaire (défaut: test_todo_tmp) : ",
        "en": "Temporary database name (default: test_todo_tmp): ",
    },
    "test_install_extra_modules": {
        "fr": "Modules supplémentaires à installer (séparés par des virgules, vide pour aucun) : ",
        "en": "Extra modules to install (comma-separated, empty for none): ",
    },
    "test_log_level": {
        "fr": "Niveau de log (défaut: test) : ",
        "en": "Log level (default: test): ",
    },
    "test_creating_db": {
        "fr": "Création de la base de données temporaire",
        "en": "Creating temporary database",
    },
    "test_installing_modules": {
        "fr": "Installation des modules",
        "en": "Installing modules",
    },
    "test_running": {
        "fr": "Exécution des tests",
        "en": "Running tests",
    },
    "test_cleaning_db": {
        "fr": "Suppression de la base de données temporaire",
        "en": "Cleaning up temporary database",
    },
    "test_keep_db": {
        "fr": "Conserver la base de données temporaire? (o/N) : ",
        "en": "Keep the temporary database? (y/N): ",
    },
    "test_db_kept": {
        "fr": "Base de données conservée",
        "en": "Database kept",
    },
    "test_success": {
        "fr": "Tests terminés avec succès!",
        "en": "Tests completed successfully!",
    },
    "test_failed": {
        "fr": "Les tests ont échoué avec le code de retour",
        "en": "Tests failed with return code",
    },
    "test_module_required": {
        "fr": "Le nom du module est requis!",
        "en": "Module name is required!",
    },
    # Git section
    "menu_git": {
        "fr": "Git - Outils Git",
        "en": "Git - Git tools",
    },
    "git_manage": {
        "fr": "Outils de gestion Git!",
        "en": "Git management tools!",
    },
    "git_local_server": {
        "fr": "Serveur git local",
        "en": "Local git server",
    },
    "git_repo_manage": {
        "fr": "Gérer le serveur de dépôts git local!",
        "en": "Manage local git repository server!",
    },
    "git_repo_deploy_local": {
        "fr": "Déployer un serveur git local (~/.git-server)",
        "en": "Deploy a local git server (~/.git-server)",
    },
    "git_repo_deploy_production": {
        "fr": "Déployer un serveur git production (/srv/git, root requis)",
        "en": "Deploy a production git server (/srv/git, root required)",
    },
    "git_repo_deploy_starting": {
        "fr": "Démarrage du déploiement du serveur git...",
        "en": "Starting git server deployment...",
    },
    "git_mode_local": {
        "fr": "Mode local (~/.git-server)",
        "en": "Local mode (~/.git-server)",
    },
    "git_mode_production": {
        "fr": "Mode production (/srv/git, root requis)",
        "en": "Production mode (/srv/git, root required)",
    },
    "git_action_all": {
        "fr": "Tout exécuter (init + remote + push + serve)",
        "en": "Run all (init + remote + push + serve)",
    },
    "git_action_init": {
        "fr": "Init - Créer les bare repos",
        "en": "Init - Create bare repos",
    },
    "git_action_remote": {
        "fr": "Remote - Ajouter les remotes locaux",
        "en": "Remote - Add local remotes",
    },
    "git_action_push": {
        "fr": "Push - Pousser vers le serveur local",
        "en": "Push - Push to local server",
    },
    "git_action_serve": {
        "fr": "Serve - Démarrer le daemon git",
        "en": "Serve - Start git daemon",
    },
    # Language selection
    "lang_prompt": {
        "fr": "Choisir la langue / Choose language",
        "en": "Choose language / Choisir la langue",
    },
    "lang_french": {
        "fr": "Francais",
        "en": "French",
    },
    "lang_english": {
        "fr": "Anglais",
        "en": "English",
    },
    "lang_changed": {
        "fr": "Langue changée pour : Francais",
        "en": "Language changed to: English",
    },
    "execution_time": {
        "fr": "Temps d'exécution TODO",
        "en": "TODO execution time",
    },
    "keyboard_interrupt": {
        "fr": "Interruption clavier",
        "en": "Keyboard interrupt",
    },
    # GPT code section
    "menu_gpt_code": {
        "fr": "GPT code - Outils d'assistant IA",
        "en": "GPT code - AI assistant tools",
    },
    "gpt_code_manage": {
        "fr": "Outils d'assistant IA pour le développement!",
        "en": "AI assistant tools for development!",
    },
    "gpt_code_claude_commit": {
        "fr": "Configurer le commit Claude Code",
        "en": "Configure Claude Code commit",
    },
    "gpt_code_enter_name": {
        "fr": "Entrez votre nom complet : ",
        "en": "Enter your full name: ",
    },
    "gpt_code_enter_email": {
        "fr": "Entrez votre courriel : ",
        "en": "Enter your email: ",
    },
    "gpt_code_commit_exists": {
        "fr": "Le fichier ~/.claude/commands/commit.md existe déjà. Aucune action effectuée.",
        "en": "File ~/.claude/commands/commit.md already exists. No action taken.",
    },
    "gpt_code_commit_created": {
        "fr": "Fichier ~/.claude/commands/commit.md créé avec succès!",
        "en": "File ~/.claude/commands/commit.md created successfully!",
    },
    "gpt_code_commit_error": {
        "fr": "Erreur lors de la création du fichier : ",
        "en": "Error creating file: ",
    },
}


def get_lang() -> str:
    global _current_lang
    if _current_lang is not None:
        return _current_lang

    # 1. Check env_var.sh file
    if os.path.exists(ENV_VAR_FILE):
        try:
            with open(ENV_VAR_FILE) as f:
                content = f.read()
            match = re.search(
                r'^EL_LANG=["\']?(\w+)["\']?', content, re.MULTILINE
            )
            if match:
                lang = match.group(1)
                if lang in ("fr", "en"):
                    _current_lang = lang
                    return _current_lang
        except OSError:
            pass

    # 2. Check env var
    env_lang = os.environ.get("EL_LANG")
    if env_lang in ("fr", "en"):
        _current_lang = env_lang
        return _current_lang

    # 3. Default
    _current_lang = "fr"
    return _current_lang


def set_lang(lang: str) -> None:
    global _current_lang
    _current_lang = lang

    # Persist to env_var.sh
    if os.path.exists(ENV_VAR_FILE):
        try:
            with open(ENV_VAR_FILE) as f:
                content = f.read()
        except OSError:
            return

        new_line = f'EL_LANG="{lang}"'
        if re.search(r"^EL_LANG=", content, re.MULTILINE):
            content = re.sub(
                r'^EL_LANG=["\']?\w*["\']?',
                new_line,
                content,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            content = content.rstrip("\n") + "\n" + new_line + "\n"

        with open(ENV_VAR_FILE, "w") as f:
            f.write(content)


def lang_is_configured() -> bool:
    """Check if a language has been explicitly set."""
    if os.path.exists(ENV_VAR_FILE):
        try:
            with open(ENV_VAR_FILE) as f:
                content = f.read()
            return bool(re.search(r"^EL_LANG=", content, re.MULTILINE))
        except OSError:
            pass
    return False


def t(key: str) -> str:
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return key
    lang = get_lang()
    return entry.get(lang, entry.get("fr", key))
