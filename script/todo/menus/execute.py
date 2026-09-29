#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Execute : Execute, qu'ouvre le menu principal, ses
sous-menus Code, Config, Process et Test, et Update, qu'ouvre Code.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place. Une entrée qui ouvre un sous-menu
nomme la méthode publique de celui-ci : son cadre porte le fil d'Ariane.
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
        Entry("ERPLibre unit tests", "execute_unit_tests"),
        Entry(
            "Mail unit tests",
            "execute_unit_tests",
            kwargs={"pattern": "test_mail*.py"},
        ),
        Entry(
            "Analyse unit tests",
            "execute_unit_tests",
            kwargs={"pattern": "test_analyse*.py"},
        ),
        # Hors de la suite unitaire, et le libellé le dit : ceux-là créent
        # de vraies machines et durent des heures.
        Entry("Long tests - real VMs, hours", "prompt_execute_longtest"),
    ],
    intro="Test an Odoo module on a temporary database!",
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
    ],
    intro="Development update",
    render="once",
)
