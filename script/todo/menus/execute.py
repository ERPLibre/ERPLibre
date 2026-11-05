#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Execute : Execute, qu'ouvre le menu principal, ses
sous-menus Code, Config, Process, Test, Uninstall et Image Odoo, Update et
Debug, qu'ouvre Code, et Generate from pre-configuration, qu'ouvre Config.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place. Une entrée qui ouvre un sous-menu
nomme la méthode publique de celui-ci, le `name` de son `Menu`.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu, Section

EXECUTE = Menu(
    "prompt_execute",
    "Execute",
    [
        Section("Development"),
        Entry("Code - Developer tools", "prompt_execute_code"),
        Entry(
            "Config - Configuration file management", "prompt_execute_config"
        ),
        Entry(
            "Run - Execute and install an instance", "prompt_execute_instance"
        ),
        Entry("Test - Test an Odoo module", "prompt_execute_test"),
        Entry("Process - Execution tools", "prompt_execute_process"),
        Entry(
            "Uninstall - Remove an Odoo version", "prompt_execute_uninstall"
        ),
        Entry(
            "Image Odoo - Database images for a quick installation",
            "prompt_execute_image_db",
        ),
        # Analyse module dessine son menu lui-même (`module_menu.py`) : son
        # segment de fil d'Ariane est celui de l'entrée.
        Entry(
            "Analyse module - Odoo modules of the checkout",
            "prompt_execute_module_analysis",
            crumb="Analyse module",
        ),
        Section("Data"),
        Entry("Database - Database tools", "prompt_execute_database"),
        Entry("Analyse - Odoo database analysis", "prompt_execute_analyse"),
        Entry(
            "Transform data - Transform your data", "prompt_execute_transform"
        ),
        Section("Sources & documentation"),
        Entry("Git - Git and shell tools", "prompt_execute_git"),
        Entry("Doc - Documentation search", "prompt_execute_doc"),
        Section("AI & automation"),
        Entry("GPT code - AI assistant tools", "prompt_execute_gpt_code"),
        Entry(
            "Automation - Demonstration of developed features",
            "prompt_execute_function",
        ),
        Section("Deployment, network & security"),
        Entry("Deploy - Deploy ERPLibre locally", "prompt_execute_deploy"),
        Entry("Network - Network tools", "prompt_execute_network"),
        Entry(
            "Security - Dependency security audit", "prompt_execute_security"
        ),
        Entry(
            "Docker / Podman - Container engines", "prompt_execute_container"
        ),
    ],
    back=None,
    render="once",
)

CODE = Menu(
    "prompt_execute_code",
    "Code",
    [
        FromConfig(
            "code_from_makefile", "execute_from_configuration", "instance"
        ),
        Entry("Open SHELL", "open_shell_on_database"),
        Entry("Upgrade Module", "upgrade_module"),
        Entry("Debug", "debug_ide"),
        Entry(
            "Update - Update all developed staging source code",
            "prompt_execute_update",
        ),
    ],
    intro="What do you need for development?",
    render="once",
)

CONFIG = Menu(
    "prompt_execute_config",
    "Config",
    [
        Section("Generate"),
        Entry("Generate all configuration", "generate_config"),
        Entry(
            "Generate from pre-configuration",
            "generate_config_from_preconfiguration",
        ),
        Entry("Generate from backup file", "generate_config_from_backup"),
        Entry("Generate from database", "generate_config_from_database"),
        Section("Advanced"),
        Entry("Setup queue job for parallelism", "generate_config_queue_job"),
    ],
    intro="Manage ERPLibre and Odoo configuration!",
    render="once",
)

DEBUG = Menu(
    "debug_ide",
    "Debug",
    [Entry("Debug todo.py", "_debug_todo_py")],
    render="once",
)

PRECONFIGURATION = Menu(
    "generate_config_from_preconfiguration",
    "Generate from pre-configuration",
    [
        Entry("base", "generate_config", kwargs={"add_arg": "--group base"}),
        Entry(
            "base + code_generator",
            "generate_config",
            kwargs={"add_arg": "--group base,code_generator"},
        ),
        Entry(
            "base + image_db",
            "generate_config",
            kwargs={"add_arg": "--group base,image_db"},
        ),
        Entry("all", "generate_config"),
    ],
    render="once",
)

PROCESS = Menu(
    "prompt_execute_process",
    "Process",
    [
        Entry("Kill Odoo process from actual port", "process_kill_from_port"),
        Entry("Kill git daemon server process", "process_kill_git_daemon"),
    ],
    intro="Manage execution processes!",
    render="once",
)

TEST = Menu(
    "prompt_execute_test",
    "Test",
    [
        Entry(
            "Test a module", "execute_test_module", kwargs={"coverage": False}
        ),
        Entry(
            "Test a module with code coverage",
            "execute_test_module",
            kwargs={"coverage": True},
        ),
        # TOUT test/test_*.py : les tests du courriel et de l'analyse en
        # font partie, et le tableau du lanceur les montre un à un.
        Entry("ERPLibre unit tests", "execute_unit_tests"),
        # Hors de la suite unitaire, et le libellé le dit : ceux-là créent
        # de vraies machines et durent des heures.
        Entry("Long tests - real VMs, hours", "prompt_execute_longtest"),
    ],
    intro="Test an Odoo module on a temporary database!",
    render="once",
)

# Le script de retrait affiche son plan et demande lui-même la
# confirmation ; ce qu'il retire ne revient pas : `danger`.
UNINSTALL = Menu(
    "prompt_execute_uninstall",
    "Uninstall",
    [
        Entry("Remove an Odoo version", "uninstall_odoo_version", danger=True),
        Entry(
            "Remove every Odoo version",
            "uninstall_odoo_version",
            kwargs={"tout": True},
            danger=True,
        ),
    ],
    intro="Remove what an Odoo version installed!",
    render="once",
)

IMAGE_DB = Menu(
    "prompt_execute_image_db",
    "Image Odoo",
    [
        Entry("List the images of an Odoo version", "image_db_list"),
        Entry(
            "Regenerate every image of an Odoo version",
            "image_db_regenerate",
            kwargs={"tout": True},
        ),
        Entry(
            "Regenerate one image",
            "image_db_regenerate",
            kwargs={"tout": False},
        ),
    ],
    intro="Database images for a quick installation!",
    render="once",
)

UPDATE = Menu(
    "prompt_execute_update",
    "Update",
    [
        FromConfig(
            "update_from_makefile", "execute_from_configuration", "instance"
        ),
        Entry("Upgrade Odoo - Migration Database", "_upgrade_odoo"),
        Entry("Upgrade Poetry - Dependency of Odoo", "upgrade_poetry"),
        # Repo dessine son menu lui-même (`git_repo_menu.py`).
        Entry("🔃 Update git repo", "prompt_execute_git_repo", crumb="Repo"),
    ],
    intro="Development update",
    render="once",
)
