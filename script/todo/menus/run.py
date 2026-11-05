#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Run, qu'ouvre Execute : Run, Database et son menu
d'effacement, Analyse, Transform data et Doc.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu, Section

RUN = Menu(
    "prompt_execute_instance",
    "Run",
    [
        Entry("Choose your database", "callback_execute_custom_database"),
        FromConfig("instance", "_run_instance", "instance"),
        Entry(
            "Mobile - Compile and run software",
            "callback_make_mobile_home",
            when="_mobile_exists",
        ),
    ],
    render="once",
)

# Chaque action passe la main à la méthode de même nom de `db_manager`.
DATABASE = Menu(
    "prompt_execute_database",
    "Database",
    [
        Section("Backup"),
        Entry("Create backup (.zip)", "create_backup_from_database"),
        Entry(
            "Download database to create backup (.zip)",
            "download_database_backup_cli",
        ),
        Section("Restore"),
        Entry("Restore from backup (.zip)", "restore_from_database"),
        Section("Duplicate"),
        Entry("Duplicate a database", "duplicate_database"),
        Section("Danger zone"),
        Entry("Erase a database", "drop_database", danger=True),
    ],
    intro="Make changes to databases!",
    render="once",
)

# Ouvert par `DatabaseManager.drop_database`, dont il nomme les méthodes.
ERASE = Menu(
    "drop_database",
    None,
    [
        Entry(
            "Erase ALL databases (make db_drop_all)",
            "_drop_all_databases",
            danger=True,
        ),
        Entry("Erase a single database", "_drop_single_database", danger=True),
    ],
    intro="Erase a database — irreversible operation!",
    mark="⚠️ ",
    back=None,
    render="once",
    closes=True,
)

ANALYSE = Menu(
    "prompt_execute_analyse",
    "Analyse",
    [
        Section("Structure"),
        Entry("Tables and database size", "execute_analyse_schema_size"),
        Section("Customisation"),
        Entry(
            "Customised views, website copies included",
            "execute_analyse_view_custom",
        ),
        Entry(
            "Studio and hand-made x_ fields", "execute_analyse_custom_field"
        ),
        Section("Migration"),
        Entry(
            "Quality of a migration, step by step",
            "execute_analyse_migration_quality",
        ),
        Section("Modules"),
        Entry(
            "Modules missing from the default package",
            "execute_analyse_module_package",
        ),
        Entry(
            "Dependencies between modules", "execute_analyse_module_dependency"
        ),
        Section("Files"),
        Entry(
            "Attachment files missing from the filestore",
            "execute_analyse_filestore",
        ),
        Section("Instance"),
        Entry(
            "Monitoring - a backup, a remote copy or a live instance",
            "execute_analyse_monitoring",
        ),
    ],
    intro="Analyse a database. Reading never writes.",
    render="once",
)

TRANSFORM = Menu(
    "prompt_execute_transform",
    "Transform data",
    [
        # « Source » et non « Source file » : l'entrée couvre un fichier et
        # une base Odoo, et un libellé qui dit « fichier » ferait chercher
        # ailleurs l'anonymiseur de base.
        Section("Source"),
        Entry("Open a file and read its report", "_transform_open_and_report"),
        Entry(
            "Anonymise an Odoo database or a backup",
            "_transform_anonymise_base",
        ),
        Section("Environment"),
        Entry("Install the reading environment", "_transform_install_env"),
        Entry("What can this machine read?", "_transform_capabilities"),
        Entry("Copies produced", "_transform_copies"),
        Entry("Databases produced", "_transform_bases_produites"),
    ],
    intro="Transform your data: read, describe, then copy.",
    mark="🪄",
    render="once",
)

DOC = Menu(
    "prompt_execute_doc",
    "Doc",
    [
        Entry("Migration module coverage", "_doc_migration_coverage"),
        Entry("What change between version", "_doc_version_changes"),
        Entry(
            "OCA guidelines",
            "_doc_link",
            kwargs={
                "url": "https://github.com/OCA/odoo-community.org/blob/master"
                "/website/Contribution/CONTRIBUTING.rst"
            },
        ),
        Entry(
            "OCA migration Odoo 19 milestone",
            "_doc_link",
            kwargs={
                "url": "https://github.com/OCA/maintainer-tools/issues/658"
            },
        ),
    ],
    intro="Looking for documentation?",
    render="once",
)
