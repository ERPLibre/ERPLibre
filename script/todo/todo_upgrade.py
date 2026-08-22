#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from uuid import uuid4


from script.todo import (
    auto_ask,
    migration_status,
    todo_file_browser,
)
from script.todo.version_manager import get_odoo_version

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - fallback when i18n is unavailable

    def t(key: str) -> str:
        return key


new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.execute import execute
from script.git.git_tool import GitTool

_logger = logging.getLogger(__name__)

PYTHON_BIN = ".venv.erplibre/bin/python3"
UPGRADE_DATABASE_CONFIG_LOG = ".venv.erplibre/odoo_database_migration_log.json"
# UPGRADE_MODULE_CONFIG_LOG = ".venv.erplibre/odoo_module_migration_log.json"
VENV_NAME_MODULE_MIGRATOR = ".venv"
LST_PATH_OCA_ODOO_MODULE_MIGRATOR = ["script", "OCA_odoo-module-migrator"]
PATH_OCA_ODOO_MODULE_MIGRATOR = "./" + "/".join(
    LST_PATH_OCA_ODOO_MODULE_MIGRATOR
)
PATH_VENV_MODULE_MIGRATOR = os.path.join(
    PATH_OCA_ODOO_MODULE_MIGRATOR, VENV_NAME_MODULE_MIGRATOR
)
PATH_SOURCE_VENV_MODULE_MIGRATOR = os.path.join(
    PATH_VENV_MODULE_MIGRATOR, "bin", "activate"
)
FILENAME_ODOO_VERSION = ".odoo-version"
LOCAL_MANIFEST = os.path.join(
    ".repo", "local_manifests", "erplibre_manifest.xml"
)
# Module lists for a version bump. The shared, versioned defaults live under
# script/; the per-database lists live under private/ (mirroring script/, like
# script/todo/todo.json -> private/todo/todo_override.json). Which modules must
# be dropped depends on the database, so that choice is never versioned.
PATH_MIGRATION_GLOBAL = os.path.join("script", "odoo", "migration")
PATH_MIGRATION_PRIVATE = os.path.join("private", "odoo", "migration")
# Le journal permanent des échecs et des verdicts, hors du fichier de
# progression : celui-ci est remis à zéro quand on recommence.
STEP_LOG_DIR = "step_log"
# Les deux premières étapes tournent avant qu'on ait choisi le nom de
# la base : leurs journaux attendent ici, puis rejoignent la migration.
UNNAMED_MIGRATION = "sans-nom"
EVENT_FILE = "events.jsonl"
# Steps of the migration, in order. What each one owns is declared just below,
# by GLOBAL_PROGRESSION_KEY and STEP_OWNED_KEY — not by the prefix alone, which
# lies on some keys and is missing on others. Rewinding to a step drops
# everything it and the later steps own, so the run really replays from there.
# Labels go through t(): the key IS the English string, as everywhere else.
MIGRATION_STEP = [
    (0, "Prepare the environment"),
    (1, "Restore and neutralize the database"),
    (2, "Update all addons"),
    (3, "Clean up before data migration"),
    (4, "Upgrade version by version (OpenUpgrade)"),
]


# Ce que le journal garde quoi qu'il arrive : des décisions et de la
# métadonnée, jamais du progrès. Rembobiner ne doit pas faire oublier QUELLE
# base on migre ni vers quelle version — on repartirait sur autre chose.
GLOBAL_PROGRESSION_KEY = frozenset(
    {
        "command_executed",
        # Le registre des échecs et des verdicts d'outils, comme le journal
        # des commandes : un retour en arrière ne doit PAS l'effacer. C'est
        # justement ce qu'on vient consulter après être revenu.
        "lst_event",
        "config_database_name",
        "config_migrate_repo",
        "date_create",
        "date_update",
        "migration_file",
        "target_odoo_version",
    }
)

# Clés que leur nom ne rattache à aucune étape, et l'étape qui les produit.
#
# Tout le reste s'auto-décrit : `state_<n>_` et `config_state_<n>_` nomment
# leur étape. Ces huit-là sont les sorties de la recherche de modules de
# l'étape 0 ; `dct_module_exist` est ensuite lu par l'étape 4.
#
# `state_1_update_all` est l'exception inverse : son nom dit 1, son travail
# est celui de l'étape 2 — c'est la mise à jour précoce, offerte avant la
# neutralisation quand la base vient d'une vieille version.
STEP_OWNED_KEY = {
    0: (
        "dct_module_exist",
        "dct_module_per_version",
        "len_dct_module_exist",
        "len_lst_module_duplicate",
        "len_lst_module_missing",
        "lst_module_duplicate",
        "lst_module_missing",
        "lst_module_per_version_origin",
    ),
    2: ("state_1_update_all",),
}

# Réponses de l'étape 4 indexées par bump de version, une entrée par palier —
# exactement comme les drapeaux `state_4_*_odoo_lst`. Leur nom ne le dit pas,
# d'où cette liste : rejouer un palier sans les vider réutilisait en silence
# les modules choisis au passage précédent.
STEP_4_PER_BUMP_KEY = (
    "config_state_4_install_module",
    "config_state_4_module_to_migrate_code",
    "config_state_4_uninstall_module",
)

STEP_PREFIX_RE = re.compile(r"^(?:config_)?state_(\d+)_")


def flag_step(key):
    """Étape dont relève une clé du journal, ou None si elle est globale.

    Le préfixe ne suffit pas : une clé peut le porter à tort
    (`state_1_update_all`) ou ne rien porter du tout (les listes de modules).
    La table tranche d'abord, le nom ensuite.
    """
    for step, lst_key in STEP_OWNED_KEY.items():
        if key in lst_key:
            return step
    match = STEP_PREFIX_RE.match(key)
    return int(match.group(1)) if match else None


class MigrationRewind(Exception):
    """L'utilisateur a demandé de revenir à une étape antérieure.

    Une exception, et non un code de retour : la demande peut venir de
    n'importe laquelle des invites, à n'importe quelle profondeur d'une
    méthode de mille lignes. La faire remonter par des valeurs de retour
    obligerait chaque appelant intermédiaire à la reconnaître et à la
    propager — autant d'endroits où l'oublier.
    """


class TodoUpgrade:
    def __init__(self, todo):
        self.file_path = None
        self.dir_path = None
        self.todo = todo
        self.dct_progression = {}
        self.lst_command_executed = []
        self.dct_module_per_version = {}
        self.dct_module_per_dct_version_path = {}
        self.execute = execute.Execute()

    def write_config(self):
        if "date_create" not in self.dct_progression.keys():
            self.dct_progression["date_create"] = str(datetime.datetime.now())
        self.dct_progression["date_update"] = str(datetime.datetime.now())
        # Always put command_executed at the end
        if "command_executed" in self.dct_progression.keys():
            value = self.dct_progression["command_executed"]
            del self.dct_progression["command_executed"]
            self.dct_progression["command_executed"] = value
        with open(UPGRADE_DATABASE_CONFIG_LOG, "w") as f:
            json.dump(self.dct_progression, f, indent=4)

    @staticmethod
    def read_progression():
        """Return the saved progression, or an empty dict if unreadable."""
        try:
            with open(UPGRADE_DATABASE_CONFIG_LOG, "r") as f:
                return json.load(f)
        except (json.decoder.JSONDecodeError, OSError):
            print(
                f"⚠️ {t('The progression file is invalid, ignoring it')}:"
                f" {UPGRADE_DATABASE_CONFIG_LOG}"
            )
            return {}

    @staticmethod
    def needs_update_all(dct_progression, already_done_early=False):
        """Faut-il encore mettre à jour tous les modules ?

        Trois façons de l'avoir déjà fait, et il faut les trois. Le drapeau de
        l'étape ; celui de la mise à jour précoce, posée avant la
        neutralisation quand la base vient d'une vieille version ; et la
        variable de la session en cours.

        Le second est ce qui manquait. Il n'est vrai que dans la session qui
        l'a posé, alors qu'à la reprise seule la trace écrite subsiste : sans
        le lire ici, reprendre une migration relançait `update_addons_all` sur
        une base déjà à jour — des heures, pour rien.
        """
        return not (
            dct_progression.get("state_2_update_all")
            or dct_progression.get("state_1_update_all")
            or already_done_early
        )

    @staticmethod
    def step_status(dct_progression, step):
        """Return (icon, detail) telling how far a migration step went.

        Steps 0 to 3 are plain booleans. Step 4 keeps one list per version, so
        its detail reports which version bumps are already migrated.
        """
        prefix = f"state_{step}_"
        dct_flag = {
            key: value
            for key, value in dct_progression.items()
            if key.startswith(prefix)
        }
        # Un journal écrit avant que l'étape 2 n'enregistre son propre drapeau
        # ne porte que state_1_update_all. Le travail a bien eu lieu ; le lire
        # ici évite de dire « non démarrée » d'une étape terminée.
        if (
            step == 2
            and not dct_flag
            and dct_progression.get("state_1_update_all")
        ):
            return "✅", t("done early, before the neutralization")
        if not dct_flag:
            return "⬜", t("not started")

        if step == 4:
            lst_done = dct_progression.get("state_4_upgrade_odoo_lst") or []
            # The data migration list only appears once a bump succeeds, so the
            # number of bumps comes from any per-version list (« *_odoo_lst »).
            total = max(
                [
                    len(value)
                    for key, value in dct_progression.items()
                    if key.startswith("state_4_")
                    and key.endswith("_odoo_lst")
                    and isinstance(value, list)
                ]
                or [0]
            )
            done = sum(1 for item in lst_done if item)
            detail = f"{done}/{total} " + t("version bumps migrated")
            # Name the versions when the target is known: the list ends on the
            # target, so the first bump is target - total + 1.
            try:
                last = int(float(dct_progression["target_odoo_version"]))
                detail += "  ·  " + " ".join(
                    f"{last - total + 1 + i}"
                    f"{'✓' if i < len(lst_done) and lst_done[i] else ''}"
                    for i in range(total)
                )
            except (KeyError, TypeError, ValueError):
                pass
            return ("✅" if total and done == total else "⏳"), detail

        if all(dct_flag.values()):
            if step == 2 and dct_progression.get("state_2_done_early"):
                # Le doute vient du moment, pas du résultat : le dire évite de
                # relancer une mise à jour qui a déjà eu lieu.
                return "✅", t("done early, before the neutralization")
            return "✅", t("done")
        return "⏳", t("partially done")

    def resume_context(self, old_dct_progression):
        """Everything the resume screen shows, as plain data.

        No I/O: the line-by-line prompt and the TUI both render THIS, so the
        two can never describe the migration differently.
        """
        migration_file = old_dct_progression.get("migration_file") or "?"
        steps = []
        for step, label in MIGRATION_STEP:
            icon, detail = self.step_status(old_dct_progression, step)
            steps.append(
                {
                    "step": step,
                    "icon": icon,
                    "label": t(label),
                    "detail": detail,
                }
            )
        lst_version = self.version_bumps(old_dct_progression)
        done = old_dct_progression.get("state_4_upgrade_odoo_lst") or []
        return {
            "file": os.path.basename(migration_file),
            "database": old_dct_progression.get("config_database_name") or "?",
            "target": old_dct_progression.get("target_odoo_version") or "?",
            "started": old_dct_progression.get("date_create") or "?",
            "steps": steps,
            "versions": [
                {
                    "version": version,
                    "done": bool(i < len(done) and done[i]),
                }
                for i, version in enumerate(lst_version)
            ],
        }

    @staticmethod
    def print_resume(ctx):
        """Render the resume screen on the terminal."""
        print()
        print(f"📍 {t('Migration in progress')}")
        # Pad in code, not in the translations: the labels differ in length
        # between languages and a hardcoded padding misaligns the colons.
        print(f"   {t('File'):<9}: {ctx['file']}")
        print(
            f"   {t('Database'):<9}: {ctx['database']}"
            f"   ·   {t('Target')} : {ctx['target']}"
        )
        print(f"   {t('Started'):<9}: {ctx['started']}")
        print()
        print(f"   {t('Steps')} :")
        for item in ctx["steps"]:
            print(
                f"     [{item['step']}] {item['icon']} "
                f"{item['label']:<44} {item['detail']}"
            )
        print()
        print(f"   [c] {t('Continue where it stopped')}")
        print(
            f"   [0-4] {t('Replay from that step')}"
            f" ({t('erases the progression of that step and the next ones')})"
        )
        if ctx["versions"]:
            versions = "/".join(str(v["version"]) for v in ctx["versions"])
            print(
                f"   [4.N] {t('Replay the upgrade from version N')}"
                f" ({versions}) —"
                f" {t('rebuilds the intermediate database')}"
            )
        print(f"   [n] {t('New migration, erase everything')}")
        print(f"   [r] {t('Keep the zip only, ask every question again')}")
        print(f"   [q] {t('Quit without doing anything')}")

    @staticmethod
    def archive_progression(old_dct_progression, reason):
        """Mettre le journal de côté avant qu'une nouvelle migration l'écrase.

        Le journal ne vit qu'à un seul endroit et la migration suivante écrit
        par-dessus : recommencer effaçait donc tout ce qu'on savait de la
        précédente — quels paliers étaient passés, quels modules manquaient,
        combien de temps chacun avait pris. Autant d'éléments qu'on ne cherche
        justement qu'APRÈS avoir dû recommencer.

        Le nom porte la base d'origine et l'horodatage de la copie, pour que
        deux tentatives sur la même base ne se recouvrent pas et qu'un fichier
        déplacé se décrive encore lui-même. Renvoie le chemin, ou None s'il n'y
        avait rien qui vaille d'être gardé.

        L'archive vit sous `private/`, pas dans le venv : une réinstallation
        efface `.venv.erplibre/`, et avec elle l'historique qu'on vient de
        sauver.
        """
        if not old_dct_progression:
            return None
        # Un journal qui ne porte aucun état n'apprend rien à personne.
        if not any(k.startswith("state_") for k in old_dct_progression):
            return None

        database_name = (
            old_dct_progression.get("config_database_name")
            or os.path.splitext(
                os.path.basename(
                    old_dct_progression.get("migration_file") or ""
                )
            )[0]
            or "unknown"
        )
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss")
        directory = os.path.join(
            PATH_MIGRATION_PRIVATE, database_name, "migration_log"
        )
        path = os.path.join(directory, f"{database_name}_{stamp}.json")
        # Deux copies dans la même seconde portent le même horodatage. Écraser
        # la première annulerait exactement la perte qu'on cherche à éviter,
        # et sans rien dire.
        suffix = 2
        while os.path.exists(path):
            path = os.path.join(
                directory, f"{database_name}_{stamp}_{suffix}.json"
            )
            suffix += 1
        payload = dict(old_dct_progression)
        payload["archived_at"] = str(datetime.datetime.now())
        payload["archived_reason"] = reason
        payload["archived_database"] = database_name
        try:
            os.makedirs(directory, exist_ok=True)
            with open(path, "w") as handle:
                json.dump(payload, handle, indent=4)
        except OSError as exc:
            # Ne jamais empêcher une migration de repartir pour une histoire
            # de copie : on le dit, et on continue.
            print(f"⚠️ {t('Could not archive the previous log')} : {exc}")
            return None
        print(f"📦 {t('Previous migration log kept in')} : {path}")
        return path

    def apply_resume_answer(self, old_dct_progression, answer, ctx):
        """Turn the answer into (progression, changed), or None to quit.

        THE decision point, shared by both interfaces: the TUI returns the
        same answer strings as the prompt, so this logic is written once.
        """
        answer = (answer or "").strip().lower()
        lst_version = [v["version"] for v in ctx["versions"]]

        if answer in ("", "c"):
            return old_dct_progression, False
        if answer == "q":
            return None
        # « n » et « r » repartent de zéro : dans les deux cas la progression
        # enregistrée disparaît, donc dans les deux cas on la garde d'abord.
        if answer == "n":
            self.archive_progression(old_dct_progression, "restart_from_zero")
            return {}, True
        if answer == "r":
            self.archive_progression(
                old_dct_progression, "restart_same_backup"
            )
            return {
                "migration_file": old_dct_progression.get("migration_file"),
                "date_create": old_dct_progression.get("date_create"),
            }, True
        if answer.startswith("4.") and lst_version:
            target = answer.split(".", 1)[1].strip()
            if target.isdigit() and int(target) in lst_version:
                return (
                    self.rewind_version_bump(
                        old_dct_progression, lst_version.index(int(target))
                    ),
                    True,
                )
            print(f"⚠️ {t('Unknown version')} : {target}")
            return old_dct_progression, False
        if answer.isdigit() and 0 <= int(answer) <= MIGRATION_STEP[-1][0]:
            return (
                self.rewind_progression(old_dct_progression, int(answer)),
                True,
            )

        print(f"⚠️ {t('Unknown choice, continuing where it stopped')}.")
        return old_dct_progression, False

    def prompt_resume(self, old_dct_progression, use_tui=False):
        """Show where the migration stands and ask what to do next.

        Returns (progression, changed), or None if the user quits. The old
        menu exposed internal key names (« Reuse database without state_4 »),
        which said nothing about what would happen; this shows the real state
        of every step and lets the user replay from any of them.
        """
        ctx = self.resume_context(old_dct_progression)
        answer = None
        if use_tui:
            answer = self.resume_tui(ctx)
        if answer is None:
            self.print_resume(ctx)
            answer = input(f"💬 {t('Your choice')} : ")
        return self.apply_resume_answer(old_dct_progression, answer, ctx)

    @staticmethod
    def ask_ui():
        """Interface of the migration: TUI, line-by-line prompts, or the
        read-only statistics screen. Returns None to leave the tool.

        The preference can settle it in advance (TODO > Configuration);
        « ask » asks. Same contract as the QEMU deployment — except for
        « stats », which is never a stored default: it does nothing, so
        landing there every time would only be in the way.
        """
        try:
            from script.todo import todo_prefs

            pref = todo_prefs.get("migration_ui")
        except Exception:
            pref = "ask"
        if pref in ("tui", "cli"):
            return pref
        print(f"\n{t('Interface:')}")
        print(f"  [1] {t('TUI form')} *")
        print(f"  [2] {t('Classic questions (line by line)')}")
        print(f"  [3] {t('Migration statistics (read-only)')}")
        print(f"  [0] {t('Cancel')}")
        print(f"  {t('(change the default in TODO > Configuration)')}")
        # `auto_ask` et non `input` : c'est la PREMIÈRE question posée
        # après l'activation de l'auto-exécution, et un input() nu y
        # arrêtait la migration avant même qu'elle ne commence. Méthode
        # statique, d'où l'appel direct plutôt que `self.ask`.
        answer = auto_ask.ask(t("Choice (0-3, default 1): ")).strip()
        return {"0": None, "2": "cli", "3": "stats"}.get(answer, "tui")

    @staticmethod
    def database_from_command(cmd):
        """Nom de base visé par une commande, ou "" si indécelable.

        Sert à proposer le bon outil au bon moment quand une commande échoue.
        On reconnaît les trois formes du dépôt : « -d <base> », « --database
        <base> », et l'argument positionnel des scripts addons
        (`update_addons_all.sh <base>`, `install_addons*.sh <base> <modules>`).
        """
        if not cmd:
            return ""
        match = re.search(r"(?:^|\s)(?:-d|--database)[=\s]+([\w.-]+)", cmd)
        if match:
            return match.group(1)
        match = re.search(
            r"\./script/addons/\w+\.sh\s+([\w.-]+)",
            cmd,
        )
        return match.group(1) if match else ""

    def check_stale_cow_views(self, database_name):
        """Lance le détecteur de copies COW en retard sur leur vue module.

        Purement consultatif : il n'écrit rien sans « --reset … --apply », que
        l'on propose seulement après avoir montré le diff — réinitialiser une
        copie peut effacer une personnalisation réelle."""
        script_path = os.path.join(
            PATH_MIGRATION_GLOBAL, "reset_stale_cow_views.py"
        )
        if not os.path.exists(script_path):
            print(f"⚠️ {t('Tool not found')}: {script_path}")
            return
        status, _cmd = self.todo_upgrade_execute(
            f"{PYTHON_BIN} ./{script_path} -d {database_name}",
            wait_at_error=False,
        )
        if status:
            # Sortie 1 = des écarts ont été trouvés (le script les a listés).
            warn = t("Read the diff first: a copy can hold a customisation.")
            print(f"\n💡 {t('To reset one of them onto its module view:')}")
            print(
                f"   {PYTHON_BIN} ./{script_path} -d {database_name}"
                f" --reset <key> --apply"
            )
            print(f"   {warn}")

    def show_stats(self):
        """Écran de statistiques, en lecture seule : rien n'est écrit, ni
        dans la base ni dans le journal de migration."""
        from script.todo import migration_stats as ms

        if not os.path.exists(UPGRADE_DATABASE_CONFIG_LOG):
            print(f"\nℹ️  {t('No migration in progress to resume.')}")
            return
        dct = self.read_progression()
        if not dct:
            print(f"\nℹ️  {t('No migration in progress to resume.')}")
            return
        ctx = self.resume_context(dct)
        database_name = dct.get("config_database_name") or ""
        stats = ms.compute(
            dct,
            ctx,
            database_name,
            self.read_uninstall_module_list,
            PATH_MIGRATION_PRIVATE,
            PATH_MIGRATION_GLOBAL,
        )

        while True:
            self.print_stats(ctx, stats)
            print(f"\n   [1] {t('Removed modules, with their reason')}")
            print(f"   [2] {t('Removed modules, comma-separated (copy)')}")
            print(f"   [3] {t('COW views: snapshots and differences')}")
            print(f"   [4] {t('Recorded decisions (journal)')}")
            print(f"   [5] {t('Executed commands (last 30)')}")
            print(f"   [t] {t('Migration state (full screen)')}")
            print(f"   [0] {t('Back')}")
            # `self.ask` : cet écran est atteint DEPUIS execute_odoo_upgrade,
            # donc après la question d'auto-exécution. Un input() nu y
            # arrêtait une migration automatique sans rien signaler.
            answer = self.ask(f"💬 {t('Your choice')} : ").strip().lower()
            if answer in ("", "0"):
                return
            if answer == "t":
                # La MÊME lettre que dans les invites : une lettre qui
                # change de sens d'un écran à l'autre ne s'apprend pas.
                self.show_migration_status()
                continue
            if answer == "1":
                for version, detail in sorted(stats["uninstall"].items()):
                    print(f"\n── {version - 1}.0 → {version}.0 ──")
                    self.print_uninstall_reason(detail)
            elif answer == "2":
                flat = ms.flat_module_list(stats["uninstall"])
                print(f"\n{len(flat)} {t('modules')} :\n")
                print(",".join(flat))
            elif answer == "3":
                self.stats_cow(stats, database_name)
            elif answer == "4":
                for line in stats["journal"]["comments"]:
                    print(f"   · {line}")
                if not stats["journal"]["comments"]:
                    print(f"   {t('nothing recorded')}")
            elif answer == "5":
                for line in stats["journal"]["commands"][-30:]:
                    print(f"   $ {line}")
            else:
                print(f"⚠️ {t('Unknown choice, continuing where it stopped')}.")

    @staticmethod
    def print_stats(ctx, stats):
        """Rend le tableau de bord de la migration."""
        print(f"\n📊 {t('Migration statistics')}")
        print(f"   {t('File'):<11}: {ctx['file']}")
        print(
            f"   {t('Database'):<11}: {ctx['database']}"
            f"   ·   {t('Target')} : {ctx['target']}"
        )
        print(
            f"   {t('Started'):<11}: {ctx['started']}"
            f"   ·   {t('elapsed')} {stats['delay']}"
        )

        print(f"\n── {t('Level reached')} ──")
        done = sum(1 for v in ctx["versions"] if v["done"])
        total = len(ctx["versions"]) or 1
        line = "   "
        for item in ctx["versions"]:
            mark = "✅" if item["done"] else "⬜"
            line += f"{item['version'] - 1}.0→{item['version']}.0 {mark}   "
        print(line)
        print(
            f"   {done}/{len(ctx['versions'])} "
            f"{t('version bumps migrated')}  ({done * 100 // total} %)"
        )
        print(
            "   "
            + "  ".join(f"[{s['step']}]{s['icon']}" for s in ctx["steps"])
        )

        print(f"\n── {t('Modules')} ──")
        if stats["origin_count"]:
            print(f"   {t('At the start'):<24}: {stats['origin_count']}")
        for version, count, delta in stats["evolution"]:
            change = "" if delta is None else f"   ({delta:+d})"
            print(f"   {f'{version}.0':<24}: {count}{change}")
        print(f"   {t('Removed in total'):<24}: {stats['removed_total']}")
        if stats["missing"]:
            print(f"   {t('Reported missing'):<24}: {len(stats['missing'])}")
        if stats["duplicate"]:
            print(f"   {t('Duplicated'):<24}: {len(stats['duplicate'])}")

        if stats["fixes"]:
            print(f"\n── {t('Migration fixes')} ──")
            for fix in stats["fixes"]:
                mark = "✅" if fix["applied"] else "⬜"
                print(f"   {mark} {fix['version']}.0   {fix['file']}")

        print(f"\n── {t('COW views')} ──")
        if stats["cow"]:
            for snap in stats["cow"]:
                print(
                    f"   {snap['label']:<18} {str(snap['count']):>4} "
                    f"{t('views')}   {snap['taken_at']}"
                )
        else:
            print(f"   {t('no snapshot')}")

        print(f"\n── {t('Journal')} ──")
        print(
            f"   {len(stats['journal']['commands'])} {t('commands')}, "
            f"{len(stats['journal']['comments'])} {t('recorded decisions')}"
        )

    def stats_cow(self, stats, database_name):
        """Instantanés COW, et différence entre deux d'entre eux."""
        snaps = stats["cow"]
        if len(snaps) < 2:
            print(f"   {t('Need two snapshots to diff.')}")
            return
        for index, snap in enumerate(snaps, 1):
            print(
                f"   [{index}] {snap['label']:<18} "
                f"{str(snap['count']):>4} {t('views')}   {snap['taken_at']}"
            )
        raw = input(
            f"💬 {t('Diff which two? (e.g. 1,2 — blank to skip)')} : "
        ).strip()
        parts = [p.strip() for p in raw.replace(",", " ").split()]
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            return
        first, second = (int(p) - 1 for p in parts)
        if not (0 <= first < len(snaps) and 0 <= second < len(snaps)):
            return
        self.diff_cow_views(
            database_name, snaps[first]["label"], snaps[second]["label"]
        )

    @staticmethod
    def resume_tui(ctx):
        """Resume screen as a TUI. Returns the SAME answer strings as the
        prompt, or None when textual is missing (fall back to the prompt)."""
        from script.todo import textual_setup

        if not textual_setup.ensure():
            return None
        try:
            from script.todo.migration_form import run_resume_tui

            return run_resume_tui(ctx)
        except ImportError:
            return None

    @staticmethod
    def version_bumps(dct_progression):
        """Odoo versions the step 4 loop walks through, e.g. [13, 14, ..., 18].

        The per-version lists all end on the target, so the first bump is
        « target - len + 1 ». Returns [] when step 4 has not started.
        """
        total = max(
            [
                len(value)
                for key, value in dct_progression.items()
                if key.startswith("state_4_")
                and key.endswith("_odoo_lst")
                and isinstance(value, list)
            ]
            or [0]
        )
        if not total:
            return []
        try:
            last = int(float(dct_progression["target_odoo_version"]))
        except (KeyError, TypeError, ValueError):
            return []
        return list(range(last - total + 1, last + 1))

    @staticmethod
    def rewind_version_bump(old_dct_progression, index):
        """Replay the step 4 loop from one version bump onwards.

        Only the per-version lists are trimmed from `index`: earlier bumps stay
        migrated and steps 0 to 3 are untouched. Resetting the clone entry is
        the point — the intermediate database of a failed bump is half
        migrated, so it must be dropped and rebuilt from the previous version
        rather than upgraded again.

        The answers given for a bump — STEP_4_PER_BUMP_KEY, indexed exactly
        like the flags — are trimmed too. They were not, so replaying a bump
        reused the modules chosen the previous time and asked nothing.
        """
        dct_kept = dict(old_dct_progression)
        for key, value in old_dct_progression.items():
            if not isinstance(value, list):
                continue
            per_bump = (
                key.startswith("state_4_")
                and key.endswith(("_odoo_lst", "_module"))
            ) or key in STEP_4_PER_BUMP_KEY
            if not per_bump:
                continue
            # Vider en gardant le type : `config_state_4_module_to_migrate_code`
            # porte des listes, sur lesquelles le code fait .append() sans les
            # avoir revues. Un False à leur place plante le palier rejoué.
            dct_kept[key] = [
                (
                    item
                    if i < index
                    else ([] if isinstance(item, list) else False)
                )
                for i, item in enumerate(value)
            ]
        return dct_kept

    AUTO_DELAY = 5
    MAX_ERROR_RETRY = 3
    MAX_ERROR_TURNS = 8

    def prompt_auto_execute(self):
        """Proposer que les invites prennent leur défaut après un délai.

        Une migration pose des dizaines de questions dont la réponse est
        presque toujours celle proposée. Les enchaîner à la main immobilise
        quelqu'un pendant des heures pour taper Entrée.

        Posée AVANT le choix de version, donc avant la première décision :
        activée, elle vaut pour toutes les suivantes, celle-là comprise.
        """
        # L'auto-exécution ne s'active JAMAIS d'elle-même : on efface le
        # drapeau avant de poser la question, sinon une variable héritée du
        # shell ferait répondre « oui » à la place de quelqu'un — et cette
        # réponse-là engage toutes les suivantes.
        auto_ask.export(False)
        answer = (
            auto_ask.ask(
                f"💬 {t('Auto-run: take the default answer after')}"
                f" {self.AUTO_DELAY} {t('seconds?')} (y/N) : ",
                default="n",
            )
            .strip()
            .lower()
        )
        self.auto_execute = answer == "y"
        # Dans l'ENVIRONNEMENT, car c'est le seul canal qu'un sous-processus
        # partage avec nous : la moitié des invites d'une migration sont
        # posées par des outils lancés à part — désinstalleur de thème,
        # détecteur de SCSS figé — et sans cela elles attendraient une
        # frappe qui ne vient jamais.
        auto_ask.export(self.auto_execute, self.AUTO_DELAY)
        if self.auto_execute:
            print(
                f"⏱ {t('Auto-run on: each prompt waits')}"
                f" {self.AUTO_DELAY} {t('seconds, then takes its default.')}"
            )

    def ask(self, prompt, default=""):
        """Lire une réponse ; rendre le défaut si rien n'arrive.

        Le compte à rebours vit dans `auto_ask`, pas ici : les outils lancés
        en sous-processus posent EUX AUSSI des questions, et une deuxième
        implémentation aurait dérivé de celle-ci sans que rien ne le dise.

        L'export à chaque appel n'est pas de la précaution : l'environnement
        est le SEUL canal qui traverse un `fork`. Sans lui, un outil lancé
        plus bas attendrait indéfiniment une frappe qui ne vient pas.
        """
        auto_ask.export(getattr(self, "auto_execute", False), self.AUTO_DELAY)
        return auto_ask.ask(prompt, default=default, seconds=self.AUTO_DELAY)

    def ask_gate(self, prompt, default=""):
        """Une invite d'attente, avec une porte de sortie vers l'arrière.

        Ces invites ne demandent qu'à continuer. Quand on s'aperçoit à ce
        moment-là qu'une étape précédente méritait un autre choix, la seule
        issue était Ctrl+C — qui laisse la progression telle quelle et oblige
        à retrouver l'écran de reprise. « b » fait le travail proprement :
        il rembobine l'état, l'écrit, et s'arrête en disant quoi relancer.
        """
        while True:
            answer = self.ask(prompt, default=default)
            reponse = (answer or "").strip().lower()
            if reponse == "t":
                # Regarder n'est pas répondre : on repose la MÊME question
                # après. Sans cela, ouvrir l'état vaudrait « continuer », ce
                # qui est exactement ce qu'on ne voulait pas faire.
                self.show_migration_status()
                continue
            if reponse != "b":
                return answer
            if self.rewind_to_chosen_step():
                raise MigrationRewind()
            # Renoncer au retour en arrière ne doit pas arrêter la migration :
            # on revient à la même invite, exactement là où l'on était.

    @staticmethod
    def backup_command(answer, template, default_cmd):
        """La commande de sauvegarde à lancer, ou « » pour ne rien faire.

        Trois réponses, trois sens, et le troisième est celui qui piège :
        « n » refuse, « y » ou Entrée prend le nom horodaté, et TOUT LE
        RESTE est un nom de fichier. Une réponse comme « non.zip » est donc
        un fichier, pas un refus — d'où la comparaison exacte plutôt qu'un
        début de mot.

        Entrée sauvegarde : au bout d'une migration de plusieurs heures,
        l'archive est ce qu'on voulait de toute façon. Mais refuser doit
        rester possible, et avoir un mot pour le dire.
        """
        reponse = (answer or "").strip()
        if reponse.lower() in ("", "n"):
            return ""
        if reponse.lower() == "y":
            return default_cmd
        return f"{template} {reponse}"

    def show_migration_status(self):
        """Ouvrir l'état de la migration, en plein écran.

        On ÉCRIT avant de lire : l'écran lit le fichier de progression, et
        ce qui vient de se passer n'y serait pas encore.

        Pas par `run_on_terminal` : celui-ci consigne ce qu'il lance dans
        le journal, et le journal est justement ce que cet écran montre.
        Regarder l'état polluerait alors l'état.
        """
        # Écrire seulement si l'on a quelque chose EN MÉMOIRE : l'écran
        # de statistiques est ouvert avant que la progression ne soit
        # chargée, et `write_config` y échouait sur un attribut absent.
        # Sans rien en mémoire, le fichier sur disque est déjà la vérité.
        if getattr(self, "dct_progression", None):
            self.write_config()
        subprocess.call(
            f"{PYTHON_BIN} ./script/todo/migration_status.py",
            shell=True,
            executable="/bin/bash",
        )

    def rewind_to_chosen_step(self):
        """Demander l'étape et rembobiner jusqu'à elle. Écrit la progression."""
        ctx = self.resume_context(self.dct_progression)
        print()
        print(f"📍 {t('Migration in progress')}")
        for item in ctx["steps"]:
            print(
                f"  [{item['step']}] {item['icon']}  {item['label']:<44}"
                f" {item['detail']}"
            )
        answer = input(
            f"💬 {t('Replay from which step? (empty to cancel)')} : "
        )
        answer = (answer or "").strip()
        if not answer.isdigit() or int(answer) > MIGRATION_STEP[-1][0]:
            print(f"⚠️ {t('Unknown choice, continuing where it stopped')}.")
            return False
        self.dct_progression = self.rewind_progression(
            self.dct_progression, int(answer)
        )
        self.write_config()
        return True

    @staticmethod
    def rewind_progression(old_dct_progression, step):
        """Drop everything `step` and the later steps own, not just their flags.

        Rewinding used to keep every key that was not « state_* ». The chosen
        step replayed, then the ones after it ran on the previous course's
        leftovers: the per-bump answers of step 4 — `config_state_4_*`, one
        entry per version bump — were still there, so the questions were not
        asked again and the work was taken for decided.

        So ownership is declared rather than guessed: GLOBAL_PROGRESSION_KEY
        survives everything, STEP_OWNED_KEY and the « state_<n>_ » prefixes
        say the rest. A key belonging to no one is progress by default and
        goes: a replay that keeps an unknown leftover is the very defect
        above, and `test_todo_upgrade_steps` fails on any unclassified key.
        """
        dct_kept = {}
        for key, value in old_dct_progression.items():
            if key in GLOBAL_PROGRESSION_KEY:
                dct_kept[key] = value
                continue
            index = flag_step(key)
            if index is not None and index < step:
                dct_kept[key] = value
        # The module search fills an in-memory dict the later steps rely on;
        # it must run again even when step 0 itself is kept.
        dct_kept["state_0_search_missing_module"] = False
        print(
            f"⏪ {t('Replaying from step')} {step} —"
            f" {t(dict(MIGRATION_STEP)[step])}"
        )
        return dct_kept

    def on_file_selected(self, file_path):
        self.file_path = file_path
        todo_file_browser.exit_program()

    def on_dir_selected(self, dir_path):
        self.dir_path = dir_path
        todo_file_browser.exit_program()

    def execute_module_upgrade(self):
        print("Welcome to Odoo module upgrade processus with ERPLibre 🤖")

        if os.path.exists(UPGRADE_DATABASE_CONFIG_LOG):
            with open(UPGRADE_DATABASE_CONFIG_LOG, "r") as f:
                try:
                    old_dct_progression = json.load(f)
                    self.dct_progression = old_dct_progression
                    self.lst_command_executed = old_dct_progression.get(
                        "command_executed"
                    )
                except json.decoder.JSONDecodeError:
                    print(
                        f'⚠️ The config file "{UPGRADE_DATABASE_CONFIG_LOG}" is invalid, ignore it.'
                    )

        print(
            "Migrate a directory repo to migrate all module, or select a directory module."
        )
        print("[m] Migrate one module")
        print("[r] Migrate one repo")
        print("[]  Directory browser")

        lst_dir_path = []
        from_version = 0
        to_version = 0

        status = input("💬 What do you choose : ").strip().lower()
        if status == "m":
            print("[p] Path (default)")
            print("[n] Name")

            status = input("💬 What do you choose : ").strip().lower()
            if status == "n":
                module_name = input("💬 Module name : ").strip().lower()
                from_version = int(
                    input("💬 From odoo version (12 to 18) : ").strip()
                )
                to_version = int(
                    input("💬 To odoo version (12 to 18) : ").strip()
                )
                self.switch_odoo(from_version)
                # TODO detect path
                (
                    lst_module_missing,
                    lst_module_duplicate,
                    lst_module_exist,
                    lst_module_error,
                ) = self.check_addons_exist([module_name], get_all_info=True)
                if (
                    lst_module_missing
                    or lst_module_duplicate
                    or lst_module_error
                ):
                    if lst_module_missing:
                        print(f"Missing list : {lst_module_missing}")
                    if lst_module_duplicate:
                        print(f"Duplicate list : {lst_module_duplicate}")
                    if lst_module_error:
                        print(f"Error list : {lst_module_error}")
                    return
                lst_dir_path.extend(lst_module_exist)
            else:
                self.dir_path = input("💬 Path : ").strip()
        elif status == "r":
            self.dir_path = input("💬 Path : ").strip()
        else:
            self.dir_path = None

        if not self.dir_path and not lst_dir_path:
            initial_dir = os.getcwd()

            file_browser = todo_file_browser.FileBrowser(
                initial_dir, self.on_dir_selected, open_dir=True
            )
            file_browser.run_main_frame()

        if not lst_dir_path and not os.path.exists(self.dir_path):
            _logger.error(f"Path '{self.dir_path}' not exists.")
            return

        if not from_version:
            from_version = int(
                input("💬 From odoo version (12 to 18) : ").strip()
            )
        if not to_version:
            to_version = int(input("💬 To odoo version (12 to 18) : ").strip())

        # TODO ask option direct migration

        lst_version_to_update = [
            (a, a + 1) for a in range(from_version, to_version)
        ]
        # lst_version_to_update = [(from_version, to_version)]
        # for actual_version in range(from_version, to_version):
        #     next_version = actual_version + 1
        for actual_version, next_version in lst_version_to_update:
            set_path_migrate_addons = set()

            if not lst_dir_path:
                if os.path.exists(
                    os.path.join(self.dir_path, "__manifest__.py")
                ):
                    lst_dir_path = [
                        [os.path.basename(self.dir_path), self.dir_path]
                    ]
                else:
                    lst_dir_path = [
                        [a, os.path.join(self.dir_path, a)]
                        for a in os.listdir(self.dir_path)
                        if os.path.exists(
                            os.path.join(self.dir_path, a, "__manifest__.py")
                        )
                    ]

            lst_path_git_clone_migrate = []
            lst_module_to_migrate_all = []
            for dir_path in lst_dir_path:
                source_manifest_path = os.path.join(
                    dir_path[1], "__manifest__.py"
                ).replace(f"odoo{from_version}.0", f"odoo{actual_version}.0")

                is_dir_module = os.path.exists(source_manifest_path)
                if not is_dir_module:
                    continue
                source_module_path = dir_path[1].replace(
                    f"odoo{from_version}.0", f"odoo{actual_version}.0"
                )
                source_addons_path = os.path.dirname(dir_path[1]).replace(
                    f"odoo{from_version}.0", f"odoo{actual_version}.0"
                )
                target_module_path = source_module_path.replace(
                    f"odoo{actual_version}.0", f"odoo{next_version}.0"
                )
                target_manifest_path = source_manifest_path.replace(
                    f"odoo{actual_version}.0", f"odoo{next_version}.0"
                )
                target_addons_path = source_addons_path.replace(
                    f"odoo{actual_version}.0", f"odoo{next_version}.0"
                )
                dct_module = {
                    "source_module_path": source_module_path,
                    "source_manifest_path": source_manifest_path,
                    "source_addons_path": source_addons_path,
                    "target_module_path": target_module_path,
                    "target_manifest_path": target_manifest_path,
                    "target_addons_path": target_addons_path,
                    "module_name": dir_path[0],
                    "source_version_odoo": actual_version,
                    "target_version_odoo": next_version,
                }
                lst_module_to_migrate_all.append(dct_module)
                set_path_migrate_addons.add(target_addons_path)
                # lst_path_git_clone_migrate.append(target_addons_path)
            # TODO auto detect version from
            # TODO if detect from directory, check from repo list
            # TODO detect from manifest version

            self.switch_odoo(next_version)
            self.install_OCA_odoo_module_migrator()

            self.internal_module_upgrade(
                next_version,
                lst_module_to_migrate_all,
                lst_path_git_clone_migrate,
            )

            for commit_path in set_path_migrate_addons:
                cmd = f"./script/code/git_commit_migration_addons_path.py --path {commit_path} --odoo_version {next_version}.0"
                self.todo_upgrade_execute(cmd)
            print(set_path_migrate_addons)
            status = self.ask(
                f"💬 {t('Please validate git commit on repos, press to')}"
                f" {t('continue')} : "
            ).strip()

    def internal_module_upgrade(
        self,
        next_version,
        lst_module_to_migrate_all,
        lst_path_git_clone_migrate,
    ):
        has_cmd = False
        cmd_parallel = "parallel :::"
        for dct_module in lst_module_to_migrate_all:
            target_addons_path = dct_module.get("target_addons_path")
            source_addons_path = dct_module.get("source_addons_path")
            module_name = dct_module.get("module_name")
            source_version_odoo = f'{dct_module.get("source_version_odoo")}.0'
            target_version_odoo = f'{dct_module.get("target_version_odoo")}.0'
            source_module_path_to_copy = dct_module.get("source_module_path")
            # Prepare git environment for target
            if target_addons_path not in lst_path_git_clone_migrate:
                lst_path_git_clone_migrate.append(target_addons_path)
                self.check_and_clone_source_to_target_migration_code(
                    next_version,
                    source_addons_path,
                    target_addons_path,
                )

            cmd_migration = (
                f"echo 'odoo_module_migrate {module_name}' && "
                f"cp -r {source_module_path_to_copy} {target_addons_path} && "
                f"cd {PATH_OCA_ODOO_MODULE_MIGRATOR} && "
                f"source {VENV_NAME_MODULE_MIGRATOR}/bin/activate && "
                f"python -m odoo_module_migrate --directory {target_addons_path} --modules {module_name} "
                f"--init-version-name {source_version_odoo} --target-version-name {target_version_odoo} "
                f"--no-commit && "
                f"cd ~- "
                # f"cp -r {source_module_path_to_copy} {target_module_path_to_copy} && "
                # f"cd {target_module_path_to_copy} && git commit -am '[MIG] {module_name}: Migration to {target_version_odoo}' && cd ~-"
            )
            cmd_parallel += f' "{cmd_migration}"'
            has_cmd = True

        if lst_module_to_migrate_all:
            if has_cmd:
                self.todo_upgrade_execute(cmd_parallel)
                print("List of path with migrate code :")
                print(lst_path_git_clone_migrate)
                print("ℹ To show repo status :\nmake repo_show_status")
                self.ask(
                    f"💬 {t('Check the migrated code, press to continue')} : "
                )

            # source_module_path = dct_module_result.get(
            #     "source_module_path"
            # )
            # if not source_module_path:
            #     _logger.error(
            #         f"Missing source module path '{source_module_path}'"
            #     )
            # else:
            #     if os.path.exists(
            #         os.path.join(source_module_path, ".git")
            #     ):
            #         self.todo_upgrade_execute(
            #             f"cd '{source_module_path}' && git stash && cd ~-",
            #         )
            #
            # target_module_path = dct_module_result.get(
            #     "target_module_path"
            # )
            # if not target_module_path:
            #     _logger.error(
            #         f"Missing target module path '{target_module_path}'"
            #     )
            # else:
            #     # TODO check if has file to commit
            #     self.todo_upgrade_execute(
            #         f"cd '{target_module_path}' && git commit -am '[MIG] {len(lst_module_to_migrate_all)} modules: Migration to {next_version}' && cd ~-",
            #     )

        # TODO copie to next odoo version
        #  do commit and continue
        #  continue migration to loop

        if next_version in [18]:
            # TODO need odoo 18, validate python version without switch
            status = self.ask(
                f"💬 {t('Please validate the repo is ready to run')}"
                f" views_migration_18, {t('press to continue')} : "
            ).strip()
            # Apply modification with views_migration_18
            has_cmd = False
            # cmd_serial = ""
            cmd_parallel = "parallel :::"
            for path_git_clone_migrate in lst_path_git_clone_migrate:
                cmd_migration = (
                    f"echo 'views_migration_18 {path_git_clone_migrate}' && "
                    f"./.venv.odoo18.0_python3.12.10/bin/python ./script/code/odoo_upgrade_code_with_dir_module.py --path {path_git_clone_migrate}"
                )
                cmd_parallel += f' "{cmd_migration}"'
                # cmd_serial += f"{cmd_migration};"
                has_cmd = True

            if has_cmd:
                # self.todo_upgrade_execute(
                #     cmd_serial
                # )
                self.todo_upgrade_execute(cmd_parallel)
                print("List of module with migration 18 :")
                print(lst_module_to_migrate_all)
                print("ℹ To show repo status :\nmake repo_show_status")
                self.ask(
                    f"💬 {t('Check the migrated code, press to continue')}"
                    " (18) : "
                )

        if next_version == 17:
            status = self.ask(
                f"💬 {t('Please validate the repo is ready to run')}"
                f" views_migration_17, {t('press to continue')} : "
            ).strip()
            # Apply modification with views_migration_17
            has_cmd = False
            cmd_serial = ""
            cmd_parallel = "parallel :::"
            for dct_module in lst_module_to_migrate_all:
                database_migration_17_name = (
                    f"migration_odoo_{next_version}_{str(uuid4())[:6]}"
                )
                module_name = dct_module.get("module_name")
                cmd_migration = (
                    f"echo 'views_migration_17 {module_name}' && "
                    f"./run.sh -d {database_migration_17_name} -i {module_name} --load=base,web,views_migration_17 --dev upgrade --no-http --stop-after-init"
                )
                cmd_parallel += f' "{cmd_migration}"'
                cmd_serial += f"{cmd_migration};"
                has_cmd = True

            if has_cmd:
                # self.todo_upgrade_execute(
                #     cmd_serial
                # )
                self.todo_upgrade_execute(cmd_parallel)
                print("List of module with migration 17 :")
                print(lst_module_to_migrate_all)
                print("ℹ To show repo status :\nmake repo_show_status")
                self.ask(
                    f"💬 {t('Check the migrated code, press to continue')}"
                    " (17) : "
                )

    def execute_odoo_upgrade(self):
        # TODO update dev environment for git project
        # TODO Redeploy new production after upgrade
        # 2 upgrades version = 5 environnement. 0-prod init, 1-dev init, 2-dev01, 3-dev02, 4-prod final
        print(t("Welcome to the Odoo database upgrade with ERPLibre") + " 🤖")
        self.prompt_auto_execute()
        self.lst_command_executed = []
        self.dct_module_per_version = {}
        self.dct_module_per_dct_version_path = {}
        default_database_name = "test"

        # L'écran de statistiques ne fait rien : on y revient autant de fois
        # qu'on veut, et on repose ensuite le choix d'interface.
        while True:
            ui = self.ask_ui()
            if ui is None:
                return
            if ui != "stats":
                break
            self.show_stats()
        use_tui = ui == "tui"

        if os.path.exists(UPGRADE_DATABASE_CONFIG_LOG):
            old_dct_progression = self.read_progression()
            if old_dct_progression:
                resumed = self.prompt_resume(old_dct_progression, use_tui)
                if resumed is None:
                    return
                self.dct_progression, changed = resumed
                if changed:
                    self.write_config()
            elif use_tui:
                print(f"ℹ️  {t('No migration in progress to resume.')}")
        elif use_tui:
            print(f"ℹ️  {t('No migration in progress to resume.')}")

        if "migration_file" in self.dct_progression:
            self.file_path = self.dct_progression["migration_file"]
        else:
            print("")
            print(t("Select the zip file of your database backup."))

            self.file_path = self.ask(
                f"💬 {t('Give the path of the file, or empty to use a file')}"
                f" {t('browser, or type')} 'remote'"
                f" {t('to download from production')} : "
            )
            if not self.file_path.strip():
                self.file_path = None
            if not self.file_path:
                initial_dir = os.path.join(os.getcwd(), "image_db")
                file_browser = todo_file_browser.FileBrowser(
                    initial_dir, self.on_file_selected
                )
                file_browser.run_main_frame()
            elif self.file_path == "remote":
                status, self.file_path, default_database_name = (
                    self.todo.db_manager.download_database_backup_cli()
                )
                if status:
                    _logger.error(
                        t(
                            "Cannot retrieve the database from remote, please"
                            " retry the migration."
                        )
                    )
                    return

            self.dct_progression["migration_file"] = self.file_path
            self.write_config()

        print(f"✅ {t('Open file')} {self.file_path}")
        with zipfile.ZipFile(self.file_path, "r") as zip_ref:
            manifest_file_1 = zip_ref.open("manifest.json")
        json_manifest_file_1 = json.load(manifest_file_1)
        odoo_actual_version = json_manifest_file_1.get("version")
        print(f"✅ {t('Detected Odoo CE version')} '{odoo_actual_version}'.")

        # print("What is your actual Odoo version?")
        lst_version, lst_version_installed, odoo_installed_version = (
            get_odoo_version()
        )

        lst_odoo_version = [
            {"prompt_description": a.get("odoo_version")}
            for a in lst_version
            if float(a.get("odoo_version")) > float(odoo_actual_version)
        ]
        help_info = self.todo.fill_help_info(lst_odoo_version)

        if "target_odoo_version" in self.dct_progression:
            odoo_target_version = self.dct_progression["target_odoo_version"]
        else:
            # Le défaut est le NUMÉRO de la version la plus haute, calculé
            # sur la liste réellement affichée : « 6 » n'est pas une
            # constante, c'est le rang de 18.0 aujourd'hui. Une version de
            # plus dans le catalogue le déplace, et l'écrire en dur ferait
            # choisir 18.0 quand l'écran propose 19.0.
            #
            # La plus haute se COMPARE, elle ne se lit pas au bout de la
            # liste : l'ordre d'affichage n'est pas une garantie, et « 9.0 »
            # se trie après « 18.0 » en chaînes.
            default_index = None
            default_version = None
            if lst_odoo_version:
                default_index = (
                    max(
                        range(len(lst_odoo_version)),
                        key=lambda i: float(
                            lst_odoo_version[i].get("prompt_description")
                        ),
                    )
                    + 1
                )
                default_version = lst_odoo_version[default_index - 1].get(
                    "prompt_description"
                )
            print(
                f"💬 {t('Which version do you want to upgrade to?')}"
                + (
                    f" ({t('Enter =')} {default_version})"
                    if default_version
                    else ""
                )
            )
            odoo_target_version = None
            cmd_no_found = True
            while cmd_no_found:
                # `self.ask` et non click.prompt : c'est lui qui porte le
                # mode auto, et click ne sait pas rendre la main après un
                # délai — l'auto se serait arrêté à la première question.
                # La marque « [6] » est donc posée à la main.
                marque = f" [{default_index}]" if default_index else ""
                status = self.ask(
                    f"{help_info}{marque}: ",
                    default=str(default_index) if default_index else "",
                )
                if not str(status).strip() and default_index:
                    status = str(default_index)
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(lst_odoo_version):
                        cmd_no_found = False
                        odoo_target_version = lst_odoo_version[
                            int_cmd - 1
                        ].get("prompt_description")
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("Command not found") + " 🤖!")

            self.dct_progression["target_odoo_version"] = odoo_target_version
            self.write_config()

        # Search nb diff to use range
        start_version = int(float(odoo_actual_version))
        end_version = int(float(odoo_target_version))
        range_version = range(start_version, end_version)
        lst_module = sorted(
            list(set(json_manifest_file_1.get("modules").keys()))
        )
        self.dct_module_per_version[start_version] = lst_module
        self.dct_progression["dct_module_per_version"] = (
            self.dct_module_per_version
        )
        self.dct_progression["lst_module_per_version_origin"] = lst_module
        # TODO need support minor version, example 18.2, the .2 (no need for OCE OCB)

        print(f"✨ {t('Documentation for this version')} :")
        # TODO Generate it locally and show it if asked

        for next_version in range_version:
            print(
                f"https://oca.github.io/OpenUpgrade/coverage_analysis/modules{next_version*10}-{(next_version+1)*10}.html"
            )

        # ⚠️ ℹ 💬 ❗ 🔷 ✨ 🟦 🔹 🔵 ⟳ ⧖ ⚙ ✔ ✅ ❌ ⏵ ⏸ ⏹ ◆ ◇ … ➤ ⚑ ★ ☆ ☰ ⬍ ⍟ ⊗ ⌘ ⏻ ⍰
        msg = "0 - Inspect zip"
        self.print_step(msg)
        self.add_comment_progression(msg)
        print(f"✅ -> {t('Search the Odoo version')}")
        print(f"✅ -> {t('Find the right environment, read the .zip file')}")

        is_state_4_reach_open_upgrade = self.dct_progression.get(
            "state_4_reach_open_upgrade"
        )

        if not is_state_4_reach_open_upgrade and not self.dct_progression.get(
            "state_0_install_odoo"
        ):
            lst_diff_version = sorted(
                list(
                    set([f"odoo{a}.0" for a in range_version]).difference(
                        set(lst_version_installed)
                    )
                )
            )
            for odoo_version_to_install in lst_diff_version:
                iter_range_version = odoo_version_to_install.replace(
                    "odoo", ""
                ).replace(".0", "")
                want_continue = self.ask(
                    f"💬 {t('Would you like to install')}"
                    f" '{odoo_version_to_install}' (y/Y) : "
                )
                if want_continue.strip().lower() != "y":
                    return
                self.todo_upgrade_execute(
                    f"make install_odoo_{iter_range_version}"
                )

                if not os.path.isfile(FILENAME_ODOO_VERSION):
                    print(
                        f"⚠️ {t('You need an installed system before')}"
                        f" {t('continuing, check your Odoo installation.')}"
                    )
                    return

        self.dct_progression["state_0_install_odoo"] = True
        self.write_config()
        # not self.dct_progression.get("state_0_switch_odoo")
        if not is_state_4_reach_open_upgrade:
            self.switch_odoo(odoo_actual_version)
        # self.dct_progression["state_0_switch_odoo"] = True
        # self.write_config()

        print(f"✅ -> {t('Install the environment if missing')}")

        if not self.dct_progression.get("state_0_search_missing_module"):
            self.switch_odoo(odoo_actual_version)
            dct_bd_modules = json_manifest_file_1.get("modules")
            lst_module_to_check = [a for a in dct_bd_modules.keys()]
            (
                lst_module_missing,
                lst_module_duplicate,
                lst_module_exist,
                lst_module_error,
            ) = self.check_addons_exist(lst_module_to_check, get_all_info=True)
            if not lst_module_missing:
                lst_module_missing = []
            dct_module_exist = {}
            if not lst_module_exist:
                lst_module_exist = []
            else:
                for item_lst_module_exist in lst_module_exist:
                    dct_module_exist[item_lst_module_exist[0]] = (
                        item_lst_module_exist[1].replace(os.getcwd(), ".")
                    )
            if not lst_module_duplicate:
                lst_module_duplicate = []

            lst_module_missing = sorted(list(set(lst_module_missing)))
            self.dct_progression["len_lst_module_missing"] = len(
                lst_module_missing
            )
            self.dct_progression["lst_module_missing"] = lst_module_missing
            self.dct_progression["len_dct_module_exist"] = len(
                lst_module_exist
            )
            self.dct_progression["dct_module_exist"] = dct_module_exist
            self.dct_progression["len_lst_module_duplicate"] = len(
                lst_module_duplicate
            )

            self.dct_progression["lst_module_duplicate"] = lst_module_duplicate
            self.write_config()
            if lst_module_missing or lst_module_duplicate:
                print(t("Cannot set up the environment to begin."))
                if lst_module_missing:
                    print(f"{t('Missing module')} :")
                    print(lst_module_missing)
                if lst_module_duplicate:
                    print(f"{t('Duplicate module')} :")
                    print(lst_module_duplicate)
                want_continue = self.ask(
                    f"💬 {t('Missing or duplicate module detected at init,')}"
                    f" {t('do you want to continue?')} (Y/N) : "
                )
                if want_continue.strip().lower() != "y":
                    return

            self.dct_progression["state_0_search_missing_module"] = True
            self.write_config()
        else:
            # TODO fill from config
            lst_module_missing = []

        print(f"✅ -> {t('Search missing modules')}")

        print(
            f"❌ -> {t('Install the missing modules, search for them or')}"
            f" {t('ask to uninstall them (can break data)')}"
        )

        msg = "1 - Import database from zip"
        self.print_step(msg)
        self.add_comment_progression(msg)

        database_name = self.dct_progression.get("config_database_name")
        if not database_name:
            database_name = (
                self.ask(
                    f"💬 {t('Which database name do you want to work with?')}"
                    f" {t('Default')} ({default_database_name}) : "
                ).strip()
                or default_database_name
            )
            self.dct_progression["config_database_name"] = database_name
            self.write_config()

        do_neutralize = False
        if not self.dct_progression.get("state_1_neutralize_database"):
            print(f"[1] {t('Ignore the database neutralization')}")
            wait_continue = (
                self.ask_gate(
                    "💬 "
                    + t("Neutralize database, press to continue")
                    + f" {t('(b = go back a step, t = show the migration state)')} : "
                )
                .strip()
                .lower()
            )
            if wait_continue != "1":
                do_neutralize = True
                database_name += "_neutralize"
                self.dct_progression["config_database_name"] = database_name
                self.write_config()

        print(f"★ {t('Working with database')} '{database_name}'")

        if not self.dct_progression.get("state_1_restore_database"):
            file_name = os.path.basename(self.file_path)
            image_db_file_path = os.path.join("image_db", file_name)
            str_will_copy = (
                f"🤖 {t('will copy')} '{self.file_path}'"
                f" {t('to')} '{image_db_file_path}'"
            )
            if not shutil._samefile(self.file_path, image_db_file_path):
                do_copy = False
                if os.path.exists(image_db_file_path):
                    status_overwrite_image_db = self.ask(
                        f"{str_will_copy}, "
                        f"{t('a file already exists, do you want to')}"
                        f" {t('continue?')} (y/Y) : "
                    ).strip()
                    if status_overwrite_image_db.lower() == "y":
                        do_copy = True
                        os.remove(image_db_file_path)
                else:
                    print(str_will_copy)
                    do_copy = True

                if do_copy:
                    shutil.copy(self.file_path, image_db_file_path)

            neutralize_arg = ""
            if start_version >= 16 and do_neutralize:
                neutralize_arg = " --neutralize"

            status, cmd_executed = self.todo_upgrade_execute(
                f"./script/database/db_restore.py --database {database_name} --image {file_name} --ignore_cache{neutralize_arg}",
                single_source_odoo=True,
            )
            if not status:
                self.dct_progression["state_1_restore_database"] = True
                self.write_config()

        print(f"✅ -> {t('Restore the database')}")
        already_update_state_1 = False

        if not self.dct_progression.get("state_1_update_all"):
            print(
                f"[1] {t('Update all addons before neutralizing (already')}"
                f" {t('neutralized by Odoo if supported)')}"
            )
            wait_continue = (
                self.ask(
                    f"💬 {t('Do you need to upgrade before neutralizing the')}"
                    f" {t('database? Press enter to ignore')} : "
                )
                .strip()
                .lower()
            )
            if wait_continue == "1":
                status, cmd_executed = self.todo_upgrade_execute(
                    f"./script/addons/update_addons_all.sh {database_name}",
                    single_source_odoo=True,
                )

                if not status:
                    already_update_state_1 = True
                    self.dct_progression["state_1_update_all"] = True
                    # La mise à jour de tous les modules EST l'étape 2, même
                    # faite plus tôt. Ne l'enregistrer que sous state_1 la
                    # laissait « non démarrée » à l'écran alors qu'elle venait
                    # de tourner, et faisait la refaire entièrement à la
                    # reprise suivante — sur une grosse base, des heures.
                    self.dct_progression["state_2_update_all"] = True
                    self.dct_progression["state_2_done_early"] = True
                    self.write_config()

            print(
                f"✅ -> {t('Update the database before neutralizing, by module')}"
            )

        print(f"✅ -> {t('Neutralize the database')}")
        if do_neutralize:
            status, cmd_executed = self.todo_upgrade_execute(
                f"./script/addons/update_prod_to_dev.sh {database_name}",
                single_source_odoo=True,
            )

            # TODO exécuter next line si status != 0 et log contient
            # psycopg2.errors.UndefinedTable: relation "discuss_channel" does not exist
            # LIGNE 1 : SELECT "discuss_channel"."id" FROM "discuss_channel" WHERE (...
            # source ./.venv.odoo18.0_python3.12.10/bin/activate && cat script/postgresql/migration/fix_migration_postgresql_17_to_postgresql_18_module_mail_nov_2025.py | ./odoo18.0/odoo/odoo-bin shell -d ripbylop_stage_prod_17_nov_2025
            # psycopg2.errors.ForeignKeyViolation: insert or update on table "discuss_channel_member" violates foreign key constraint "discuss_channel_member_channel_id_fkey"
            # DÉTAIL : Key (channel_id)=(20) is not present in table "discuss_channel".
            # ./script/database/migrate/process_backup_file.py --path_backup_zip image_db/db.zip --path_output_zip image_db/dbFIX.zip --word_to_delete discuss_channel_channel_type_not_null
            # Puis faire un retry de la commande, sinon rien

            # Only record the step when it actually succeeded. The previous
            # unconditional assignment made the test below dead code: a failed
            # neutralization was remembered as done and skipped on resume.
            if not status:
                self.dct_progression["state_1_neutralize_database"] = True
                self.write_config()
        else:
            self.dct_progression["state_1_neutralize_database"] = True
            self.write_config()

        if not self.dct_progression.get("state_1_theme_uninstalled"):
            self.prompt_uninstall_theme(database_name)
            self.dct_progression["state_1_theme_uninstalled"] = True
            self.write_config()

        config_state_1_uninstall_module = self.dct_progression.get(
            "config_state_1_uninstall_module"
        )
        config_state_1_install_module = self.dct_progression.get(
            "config_state_1_install_module"
        )

        if not is_state_4_reach_open_upgrade:
            lst_module_to_uninstall, lst_uninstall_reason = (
                self.read_uninstall_module_list(start_version, database_name)
            )
            if lst_uninstall_reason:
                print(f"✨ {t('Modules to uninstall before the migration')} :")
                self.print_uninstall_reason(lst_uninstall_reason)

            if config_state_1_uninstall_module:
                lst_module_to_uninstall = (
                    lst_module_to_uninstall + config_state_1_uninstall_module
                )

            if lst_module_to_uninstall:
                self.uninstall_from_database(
                    lst_module_to_uninstall, database_name, start_version
                )
                self.dct_progression["state_1_uninstall_module"] = True
                self.write_config()

        self.dct_progression["config_state_1_uninstall_module"] = (
            config_state_1_uninstall_module
        )

        self.write_config()

        print(f"✅ -> {t('Uninstall modules')}")

        print(f"✅ -> {t('Install modules')}")
        if not is_state_4_reach_open_upgrade:
            lst_module_to_install = []
            if config_state_1_install_module:
                lst_module_to_install = (
                    lst_module_to_install + config_state_1_install_module
                )
            if lst_module_to_install:
                self.install_from_database(
                    lst_module_to_install, database_name, start_version
                )
                self.dct_progression["state_1_install_module"] = True
                self.write_config()
        self.dct_progression["config_state_1_install_module"] = (
            config_state_1_install_module
        )
        self.write_config()

        msg = "2 - Succeed update all addons"
        self.print_step(msg)
        self.add_comment_progression(msg)

        if self.needs_update_all(self.dct_progression, already_update_state_1):
            status, cmd_executed = self.todo_upgrade_execute(
                f"./script/addons/update_addons_all.sh {database_name}",
                single_source_odoo=True,
            )
            if not status:
                self.dct_progression["state_2_update_all"] = True
                self.write_config()

        # Predict the website COW views that the NEXT version bump will break.
        # A copy-on-write view freezes the structure of the module view it was
        # copied from; when that module view changes mode between two versions,
        # the copy keeps an arch written for the old mode and the upgrade dies
        # on « Element ... cannot be located in parent view ». Reporting it here
        # -- before hours of migration -- leaves time to arbitrate.
        # Only the next bump can be predicted: the modes in database describe
        # the current version.
        # Sur le terminal, sans capturer : plus rien ne relit cette sortie —
        # la décision se prend sur le code de retour — et la capture faisait
        # annoncer « Command returned error code: 1 » sur un rapport qui va
        # bien. 1 veut dire « des copies casseront », pas « l'outil a raté ».
        status = self.run_on_terminal(
            f"{PYTHON_BIN} ./script/odoo/migration/check_cow_views.py"
            f" -d {database_name} -t odoo{start_version + 1}.0"
        )
        # L'avertissement annonçait un problème, invitait à arbitrer, et
        # aucune question ne suivait : dire « la question viendra au palier »
        # ne remplace pas la possibilité de regarder maintenant. Les copies
        # sont visibles ici, et les neutraliser ici vaut pour tous les paliers
        # — chaque base de palier est un clone de celle-ci.
        # Le code de sortie, pas le texte : 1 = des copies casseront.
        # Chercher une phrase anglaise dans la sortie rendait cette invite
        # muette dès que l'outil parlait français.
        if status == 1:
            self.prompt_cow_prediction(database_name, start_version + 1)

        # Même prédiction, autre matière : un SCSS personnalisé est lui aussi
        # une copie figée, et un palier renomme aussi des variables. Celle-ci
        # ne se voit qu'à l'écran d'une page — « Style error », sans dire quel
        # fichier ni depuis quand — et seulement une fois le palier passé.
        # Ici on PRÉDIT, on ne corrige pas : le checkout est encore sur la
        # version d'avant, et reset_asset n'existe qu'à partir de 13.0.
        # Appliquer depuis là lève « KeyError: 'web_editor.assets' » — c'est
        # arrivé sur une vraie migration, et l'échec est passé pour un
        # succès. La correction est proposée après le palier, plus bas.
        self.run_on_terminal(
            f"{PYTHON_BIN} ./script/odoo/migration/check_stale_scss.py"
            f" -d {database_name} -t odoo{start_version + 1}.0 --report-only"
        )

        # La mesure de DÉPART. Sans elle, une page qui rendait déjà 500 avant
        # la migration se lit comme un dégât de la migration, et l'on cherche
        # des heures du côté du palier. Mesuré : deux URL cassaient avant même
        # de commencer.
        # Le nettoyage AVANT la mesure : interroger les pages sur une base
        # encombrée fait chercher des pannes dans des restes, et le nettoyage
        # en répare une partie de lui-même.
        self.prompt_database_cleanup(database_name)
        self.prompt_smoke_public_url(database_name, baseline=True)

        msg = "3 - Clean up database before data migration"
        self.print_step(msg)
        self.add_comment_progression(msg)

        # Le nettoyage est fait à l'étape 2, par l'outil, et il pose lui-même
        # le module s'il manque. Redemander ici « avez-vous fini de nettoyer
        # dans l'interface ? » ferait faire à la main ce qui vient d'être
        # fait — et l'installation qui suivait arrivait APRÈS l'usage.
        if not self.dct_progression.get("state_3_clean_database"):
            self.dct_progression["state_3_install_clean_database"] = True
            self.dct_progression["state_3_clean_database"] = True
            self.write_config()

        self.install_OCA_odoo_module_migrator()

        msg = "4 - Upgrade version with OpenUpgrade"
        self.print_step(msg)
        self.add_comment_progression(msg)

        self.dct_progression["state_4_reach_open_upgrade"] = True
        self.write_config()
        lst_next_version = [
            a for a in range(start_version + 1, end_version + 1)
        ]
        lst_database_name_upgrade = [
            f"{database_name}_upgrade_{str(a)}" for a in lst_next_version
        ]
        # Setup lst_switch_odoo
        lst_clone_odoo = self.dct_progression.get(
            "state_4_clone_odoo_lst", [False] * len(lst_next_version)
        )
        lst_switch_odoo = self.dct_progression.get(
            "state_4_switch_odoo_lst", [False] * len(lst_next_version)
        )
        lst_module_migrate_odoo = self.dct_progression.get(
            "state_4_module_migrate_odoo_lst", [False] * len(lst_next_version)
        )
        lst_module_uninstall_module = self.dct_progression.get(
            "state_4_uninstall_module", [False] * len(lst_next_version)
        )
        lst_module_install_module = self.dct_progression.get(
            "state_4_install_module", [False] * len(lst_next_version)
        )
        lst_module_search_missing_module = self.dct_progression.get(
            "state_4_search_missing_module", [False] * len(lst_next_version)
        )

        nb_missing_value_switch_odoo = abs(
            len(lst_switch_odoo) - len(lst_next_version)
        )
        if nb_missing_value_switch_odoo:
            lst_switch_odoo += [False] * nb_missing_value_switch_odoo

        # Setup lst_upgrade_odoo
        lst_upgrade_odoo = self.dct_progression.get(
            "state_4_upgrade_odoo_lst", [[]] * len(lst_next_version)
        )
        lst_fix_migration_odoo = self.dct_progression.get(
            "state_4_fix_migration_odoo_lst", [[]] * len(lst_next_version)
        )
        nb_missing_value_upgrade_odoo = abs(
            len(lst_upgrade_odoo) - len(lst_next_version)
        )
        if nb_missing_value_upgrade_odoo:
            lst_upgrade_odoo += [[]] * nb_missing_value_upgrade_odoo

        database_name_upgrade = None
        lst_module_missing_next_version = []
        lst_module_to_delete = []
        lst_module_to_delete_last_version = []
        for index, next_version in enumerate(lst_next_version):
            # Reinit the list
            lst_module_missing_last_version = lst_module_missing_next_version[
                :
            ]
            lst_module_to_delete_last_version.extend(lst_module_to_delete)
            lst_module_to_delete = []

            msg = f"4.{index} - Ready to work with version {next_version}"
            self.add_comment_progression(msg)

            option_comment = 0
            msg = f"4.{index}.{chr(option_comment + 65)} - Search updated module list to next version"
            self.add_comment_progression(msg)

            if not database_name_upgrade:
                last_database_name = database_name
            else:
                last_database_name = database_name_upgrade
            database_name_upgrade = lst_database_name_upgrade[index]
            lst_module_to_uninstall = []
            lst_module_to_install = []
            lst_module_to_analyse = self.get_rename_module(
                self.dct_module_per_version[next_version - 1],
                next_version,
            )
            self.dct_module_per_version[next_version] = sorted(
                list(set(lst_module_to_analyse))
            )
            self.dct_progression["dct_module_per_version"] = (
                self.dct_module_per_version
            )

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Clone Odoo"
            self.add_comment_progression(msg)

            if not os.path.exists(f"odoo{next_version}.0/addons/addons"):
                os.makedirs(f"odoo{next_version}.0/addons/addons")

            if not lst_clone_odoo[index]:
                self.switch_odoo(next_version - 1)

                print(
                    f"⧖ -> {t('Cloning to Odoo')}{next_version},"
                    f" {t('from')} '{database_name}'"
                    f" {t('to')} '{database_name_upgrade}'."
                )
                # Delete if exist database
                self.todo_upgrade_execute(
                    f"./script/database/db_restore.py -d {database_name_upgrade} --only_drop",
                )

                # Duplicate database
                cmd_clone_database = f"./odoo_bin.sh db --clone --from_database {last_database_name} --database {database_name_upgrade}"
                status, cmd_executed = self.todo_upgrade_execute(
                    cmd_clone_database
                )

                # Everything downstream runs against this clone: if it failed,
                # do not mark it done (a rerun would skip the clone and migrate
                # a missing or truncated database).
                if status:
                    print(
                        f"❌ -> {t('Clone to Odoo')}{next_version}"
                        f" {t('FAILED (status')} {status})."
                        f" {t('Stopping:')} '{database_name_upgrade}'"
                        f" {t('is not usable.')}"
                    )
                    return

                lst_clone_odoo[index] = True
                self.dct_progression["state_4_clone_odoo_lst"] = lst_clone_odoo
                self.write_config()
                print(f"✅ -> {t('Clone done for Odoo')}{next_version}")
            else:
                print(
                    f"✅ -> {t('Clone already done for Odoo')}"
                    f"{next_version}"
                )

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Uninstall module"
            self.add_comment_progression(msg)

            config_state_4_uninstall_module = self.dct_progression.get(
                "config_state_4_uninstall_module",
                [False] * len(lst_next_version),
            )

            if not lst_module_uninstall_module[index]:
                lst_module_to_uninstall = (
                    config_state_4_uninstall_module[index] or []
                )
                # Same file convention as step 1, one file per version bump:
                # uninstall_module_list_odoo130_to_odoo140.txt is read HERE,
                # right before the 13 -> 14 data migration. Without this the
                # per-bump files existed in name only and were never read.
                lst_file, lst_detail = self.read_uninstall_module_list(
                    next_version - 1, database_name
                )
                if lst_detail:
                    print(
                        f"✨ {t('Modules to uninstall before Odoo')}"
                        f"{next_version} :"
                    )
                    self.print_uninstall_reason(lst_detail)
                lst_module_to_uninstall = list(
                    dict.fromkeys(list(lst_module_to_uninstall) + lst_file)
                )

                if lst_module_to_uninstall:
                    self.uninstall_from_database(
                        lst_module_to_uninstall,
                        database_name_upgrade,
                        next_version - 1,
                    )
                    lst_module_uninstall_module[index] = True
                    self.dct_progression["state_4_module_migrate_odoo_lst"] = (
                        lst_module_uninstall_module
                    )
                    self.write_config()

            self.dct_progression["config_state_4_uninstall_module"] = (
                config_state_4_uninstall_module
            )
            self.dct_progression["state_4_uninstall_module"] = (
                lst_module_uninstall_module
            )
            self.write_config()

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Install module"
            self.add_comment_progression(msg)

            config_state_4_install_module = self.dct_progression.get(
                "config_state_4_install_module",
                [False] * len(lst_next_version),
            )

            # Special case to install module to fix migration
            if (
                next_version == 13
                and "dms" in lst_module_to_analyse
                and "muk_dms"
                not in self.dct_progression.get("dct_module_exist", {}).keys()
            ):
                # Force install dms into odoo 12
                if not config_state_4_install_module[index]:
                    config_state_4_install_module[index] = ["dms"]
                elif "dms" not in config_state_4_install_module[index]:
                    config_state_4_install_module[index].append("dms")

            if not lst_module_install_module[index]:
                lst_module_to_install = config_state_4_install_module[index]
                if not lst_module_to_install:
                    lst_module_to_install = []

                if lst_module_to_install:
                    self.install_from_database(
                        lst_module_to_install,
                        database_name_upgrade,
                        next_version - 1,
                    )
                    lst_module_install_module[index] = True
                    self.dct_progression["state_4_module_migrate_odoo_lst"] = (
                        lst_module_install_module
                    )
                    self.write_config()

            self.dct_progression["config_state_4_install_module"] = (
                config_state_4_install_module
            )
            self.dct_progression["state_4_install_module"] = (
                lst_module_install_module
            )
            self.write_config()

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Switch Odoo"
            self.add_comment_progression(msg)

            if not lst_switch_odoo[index]:
                self.switch_odoo(next_version)
                lst_switch_odoo[index] = True
                self.dct_progression["state_4_switch_odoo_lst"] = (
                    lst_switch_odoo
                )
                self.write_config()
                print(
                    f"✅ -> {t('Switch done with update for Odoo')}"
                    f"{next_version}"
                )
            else:
                print(
                    f"✅ -> {t('Switch already done for Odoo')}"
                    f"{next_version}"
                )

            lst_state_4_module_migrate_code = self.dct_progression.get(
                "config_state_4_module_to_migrate_code",
                [[]] * len(lst_next_version),
            )
            if (
                "config_state_4_module_to_migrate_code"
                not in self.dct_progression.keys()
            ):
                self.dct_progression[
                    "config_state_4_module_to_migrate_code"
                ] = lst_state_4_module_migrate_code
            lst_module_to_migrate = lst_state_4_module_migrate_code[index]

            option_comment += 1
            msg = (
                f"4.{index}.{chr(option_comment + 65)} - Search missing module"
            )
            self.add_comment_progression(msg)

            if not lst_module_search_missing_module[index]:
                lst_module_to_analyse_updated = []
                for bd_module in lst_module_to_analyse:
                    if (
                        lst_module_to_uninstall
                        and bd_module in lst_module_to_uninstall
                    ):
                        # Ignore check if uninstall before
                        continue
                    lst_module_to_analyse_updated.append(bd_module)

                # TODO remove from list past module deleted
                lst_module_to_check = [
                    a
                    for a in lst_module_to_analyse_updated
                    if a not in lst_module_to_delete_last_version
                ]
                (
                    lst_module_missing_next_version,
                    lst_module_duplicate_next_version,
                ) = self.check_addons_exist(lst_module_to_check)

                lst_module_missing_next_version = sorted(
                    list(set(lst_module_missing_next_version))
                )

                self.dct_progression["state_4_len_lst_module_missing"] = len(
                    lst_module_missing_next_version
                )
                self.dct_progression["state_4_lst_module_missing"] = (
                    lst_module_missing_next_version
                )

                lst_module_duplicate = sorted(
                    list(set(lst_module_duplicate_next_version))
                )

                self.dct_progression["state_4_len_lst_module_duplicate"] = len(
                    lst_module_duplicate
                )
                self.dct_progression["state_4_lst_module_duplicate"] = (
                    lst_module_duplicate
                )

                if lst_module_duplicate:
                    print(f"{t('Duplicate module in Odoo')}{next_version} : ")
                    print(lst_module_duplicate)
                    self.ask(
                        f"💬 {t('Duplicate module error detected, handle it')}"
                        f" {t('manually then press enter to continue.')}"
                    )
                # if lst_module_missing_next_version and not lst_module_to_migrate:
                if lst_module_missing_next_version:
                    # TODO support when lst_module_to_migrate is fill
                    lst_module_to_migrate = []
                    print(
                        f"👹 {t('Missing module error detected, missing in')}"
                        f" Odoo{next_version} :"
                    )
                    for index_missing_module, module_missing in enumerate(
                        lst_module_missing_next_version
                    ):
                        old_path = self.dct_progression.get(
                            "dct_module_exist", {}
                        ).get(module_missing)
                        print(
                            f"[{index_missing_module}] {module_missing} - {old_path}"
                        )
                    print(f"[a] {t('All of the list above')}")
                    print(f"[e] {t('Add an extra custom one')}")

                    want_continue = (
                        self.ask(
                            f"💬 {t('List the missing modules to delete,')}"
                            f" {t('separated by commas. The others will be')}"
                            f" {t('migrated')}"
                            f" ({t('Enter = all, n = none')}) : ",
                            default="a",
                        )
                        .strip()
                        .lower()
                    )

                    is_delete_all = False

                    # « n » saute le bloc ENTIER, ajouts par version compris :
                    # Entrée valant « toutes », il faut un mot pour dire non,
                    # et il doit vraiment ne rien supprimer.
                    if want_continue == "n":
                        want_continue = ""
                    if want_continue:
                        lst_want_continue = [
                            a.strip() for a in want_continue.split(",")
                        ]
                        if "a" in lst_want_continue:
                            is_delete_all = True
                            lst_module_to_delete = [
                                lst_module_missing_next_version[a]
                                for a in range(
                                    len(lst_module_missing_next_version)
                                )
                            ]
                        else:
                            # TODO show error if the index is wrong
                            lst_want_continue_number = [
                                int(a)
                                for a in lst_want_continue
                                if a.isdigit()
                            ]
                            lst_module_to_delete = [
                                lst_module_missing_next_version[a]
                                for a in lst_want_continue_number
                                if 0
                                <= a
                                < len(lst_module_missing_next_version)
                            ]
                            if len(lst_module_to_delete) == len(
                                lst_module_missing_next_version
                            ):
                                is_delete_all = True

                        if next_version == 15:
                            lst_module_to_delete.append("users_default_groups")
                            lst_module_to_delete.append(
                                "web_editor_backend_context"
                            )
                            lst_module_to_delete.append(
                                "website_google_analytics_fixed"
                            )
                        elif next_version == 17:
                            lst_module_to_delete.append(
                                "export_delete_login_log"
                            )
                        elif next_version == 18:
                            lst_module_to_delete.append(
                                "base_attachment_object_storage"
                            )
                            lst_module_to_delete.append(
                                "user_password_strength"
                            )

                        if "e" in lst_want_continue:
                            want_continue = (
                                self.ask(
                                    f"💬 {t('List the module names to delete,')}"
                                    f" {t('separated by commas')} : "
                                )
                                .strip()
                                .lower()
                            )
                            lst_to_extend = [
                                a.strip() for a in want_continue.split(",")
                            ]
                            lst_module_to_delete.extend(lst_to_extend)

                    if lst_module_to_delete:
                        msg = f"4.{index}.{chr(option_comment + 65)}.option - Choose delete missing module"
                        self.add_comment_progression(msg)

                    self.switch_odoo(next_version - 1)

                    if lst_module_to_delete:
                        # Delete if exist database
                        self.todo_upgrade_execute(
                            f"./script/database/db_restore.py -d {database_name_upgrade} --only_drop",
                        )
                        # Duplicate database
                        cmd_clone_database = f"./odoo_bin.sh db --clone --from_database {last_database_name} --database {database_name_upgrade}"
                        self.todo_upgrade_execute(cmd_clone_database)
                        self.uninstall_from_database(
                            lst_module_to_delete,
                            database_name_upgrade,
                            next_version,
                        )
                        self.install_from_database(
                            lst_module_to_install,
                            database_name_upgrade,
                            next_version - 1,
                        )

                    if not is_delete_all:
                        msg = f"4.{index}.{chr(option_comment + 65)}.option - Choose auto-fix (not implemented yet)"
                        self.add_comment_progression(msg)

                        lst_module_to_migrate_code = set(
                            lst_module_missing_next_version
                        ) - set(lst_module_to_delete)
                        (
                            lst_module_missing_last,
                            lst_module_duplicate_last,
                            lst_module_exist_last,
                            lst_module_error_last,
                        ) = self.check_addons_exist(
                            lst_module_to_migrate_code, get_all_info=True
                        )

                        if lst_module_missing_last:
                            print(
                                f"{t('Missing module error')} :"
                                f" {lst_module_missing_last}"
                            )
                        if lst_module_duplicate_last:
                            print(
                                f"{t('Duplicate module error')} :"
                                f" {lst_module_duplicate_last}"
                            )
                        if lst_module_error_last:
                            print(
                                f"{t('Module error')} : {lst_module_error_last}"
                            )

                        if lst_module_exist_last:
                            odoo_name_last_version = (
                                f"odoo{next_version - 1}.0"
                            )
                            odoo_name_actual_version = f"odoo{next_version}.0"
                            for (
                                module_name,
                                module_path,
                            ) in lst_module_exist_last:
                                module_dir_path = os.path.dirname(module_path)
                                module_dir_path_new_version = (
                                    module_dir_path.replace(
                                        odoo_name_last_version,
                                        odoo_name_actual_version,
                                    )
                                )
                                module_dir_path_manifest = os.path.join(
                                    module_path, "__manifest__.py"
                                )
                                module_dir_new_version = os.path.join(
                                    module_dir_path_new_version, module_name
                                )
                                module_dir_new_version_manifest = os.path.join(
                                    module_dir_new_version, "__manifest__.py"
                                )
                                dct_module_to_migrate_module = {
                                    "source_module_path": module_path,
                                    "source_manifest_path": module_dir_path_manifest,
                                    "source_addons_path": module_dir_path,
                                    "target_module_path": module_dir_new_version,
                                    "target_manifest_path": module_dir_new_version_manifest,
                                    "target_addons_path": module_dir_path_new_version,
                                    "module_name": module_name,
                                    "source_version_odoo": next_version - 1,
                                    "target_version_odoo": next_version,
                                }
                                # TODO move this into config
                                lst_module_to_migrate.append(
                                    dct_module_to_migrate_module
                                )

                    self.dct_progression[
                        "config_state_4_module_to_migrate_code"
                    ][index] = lst_module_to_migrate
                    self.write_config()

                    self.switch_odoo(next_version)
                    # TODO auto-fix
                    # TODO try to migrate module, find in previous version, application la migration vers une nouvelle version
                    # TODO ajouté menu todo qui permet de faire une migration d'un module et migrer le générateur de code.
                    # TODO when check module, reminder provenance
                    # TODO implement asyncio instead of parallel
                    # TODO detect when duplicate path module ou module manquant, prendre décision qui ont efface si dupliqué
                    # TODO pourquoi web_ir_actions_act_multi est doublé dans odoo 13

                lst_module_search_missing_module[index] = True
                self.dct_progression["state_4_search_missing_module"] = (
                    lst_module_search_missing_module
                )
                self.write_config()
            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Migrate module"
            self.add_comment_progression(msg)
            lst_path_git_clone_migrate = []

            if not lst_module_migrate_odoo[index]:
                # TODO Searching module
                #  search addons/addons
                #  search read manifest and detect branch difference, manifest into private?
                #  Extract module name and run migration to another list
                #  Maybe check if already exist and show list or continue with overwrite
                #  Expliquer pourquoi on ne fait pas le oca-port, c'est

                config_migrate_repo = self.dct_progression.get(
                    "config_migrate_repo", False
                )
                self.dct_progression["config_migrate_repo"] = (
                    config_migrate_repo
                )

                if config_migrate_repo:
                    dct_module_result = self.search_module_to_move(
                        next_version - 1, next_version
                    )

                    # TODO code migration
                    #  git stash
                    #  call odoo-module-migrate, without commit

                    source_module_path = dct_module_result.get(
                        "source_module_path"
                    )
                    if not source_module_path:
                        _logger.error(
                            f"Missing source module path '{source_module_path}'"
                        )
                    else:
                        if os.path.exists(
                            os.path.join(source_module_path, ".git")
                        ):
                            self.todo_upgrade_execute(
                                f"cd '{source_module_path}' && git stash && cd ~-"
                            )

                    target_module_path = dct_module_result.get(
                        "target_module_path"
                    )
                    if not target_module_path:
                        _logger.error(
                            f"Missing target module path '{target_module_path}'"
                        )
                    else:
                        if os.path.exists(
                            os.path.join(target_module_path, ".git")
                        ):
                            self.todo_upgrade_execute(
                                f"cd '{target_module_path}' && git stash && cd ~-"
                            )

                    lst_module_to_migrate_all = dct_module_result.get(
                        "lst_module", []
                    )
                else:
                    lst_module_to_migrate_all = []

                # TODO remove duplicate au lieu d'extend
                lst_module_to_migrate_all.extend(lst_module_to_migrate)

                self.internal_module_upgrade(
                    next_version,
                    lst_module_to_migrate_all,
                    lst_path_git_clone_migrate,
                )

                lst_module_migrate_odoo[index] = True
                self.dct_progression["state_4_module_migrate_odoo_lst"] = (
                    lst_module_migrate_odoo
                )
                self.write_config()

                print(
                    f"✅ -> {t('Module upgrade done for Odoo')}"
                    f"{next_version}"
                )
            else:
                print(
                    f"✅ -> {t('Module upgrade already done for Odoo')}"
                    f"{next_version}"
                )

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Fix migrate code"
            self.add_comment_progression(msg)

            if not lst_fix_migration_odoo[index]:
                print("")
                stem = os.path.join(
                    PATH_MIGRATION_GLOBAL,
                    f"fix_migration_odoo{(next_version - 1) * 10}"
                    f"_to_odoo{next_version * 10}",
                )
                # Two flavours. « .sql » runs through psql: no Odoo registry,
                # so it works on a database not yet migrated -- exactly when
                # loading it with the TARGET version's code would fail. « .py »
                # is piped into the Odoo shell when the ORM is really needed.
                file_path_fix_migration = ""
                cmd_fix_migration = ""
                if os.path.exists(f"{stem}.sql"):
                    file_path_fix_migration = f"{stem}.sql"
                    cmd_fix_migration = (
                        f"psql -v ON_ERROR_STOP=1 -d {database_name_upgrade}"
                        f" -f ./{file_path_fix_migration}"
                    )
                elif os.path.exists(f"{stem}.py"):
                    file_path_fix_migration = f"{stem}.py"
                    cmd_fix_migration = (
                        f"cat ./{file_path_fix_migration} |"
                        f" ./odoo{next_version}.0/odoo/odoo-bin shell"
                        f" -d {database_name_upgrade}"
                    )
                if file_path_fix_migration:
                    status, cmd_executed = self.todo_upgrade_execute(
                        cmd_fix_migration,
                        single_source_odoo=True,
                    )

                    # A fix that did not run must not be recorded as applied,
                    # otherwise the rerun skips it and OpenUpgrade hits the very
                    # problem the fix exists to prevent.
                    if status:
                        print(
                            f"❌ -> {t('Migration fix for Odoo')}{next_version}"
                            f" {t('FAILED (status')} {status}) :"
                            f" {file_path_fix_migration}"
                        )
                        return

                    lst_fix_migration_odoo[index] = file_path_fix_migration
                    self.dct_progression["state_4_fix_migration_odoo_lst"] = (
                        lst_fix_migration_odoo
                    )
                    self.write_config()
                    print(
                        f"✅ -> {t('Migration fix done for Odoo')}"
                        f"{next_version}"
                    )
                else:
                    print(
                        f"✅ -> {t('No migration fix to run for Odoo')}"
                        f"{next_version}"
                    )
            else:
                print(
                    f"✅ -> {t('Migration fix already done for Odoo')}"
                    f"{next_version}"
                )

            for path_git_clone_migrate in lst_path_git_clone_migrate:
                cmd = f"./script/code/git_commit_migration_addons_path.py --path {path_git_clone_migrate} --odoo_version {next_version}.0"
                self.todo_upgrade_execute(cmd)

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Migrate database"
            self.add_comment_progression(msg)

            if not lst_upgrade_odoo[index]:
                path_addons_openupgrade = os.path.join(
                    os.getcwd(), f"odoo{next_version}.0", "OCA_OpenUpgrade"
                )

                # Update config with OCA_OpenUpgrade
                ignore_path = (
                    "--ignore-odoo-path " if next_version <= 13 else ""
                )
                extra_addons_path_extra = (
                    f",{path_addons_openupgrade}/addons,{path_addons_openupgrade}/odoo/addons"
                    if next_version <= 13
                    else ""
                )
                cmd_update_config = (
                    f"./script/git/git_repo_update_group.py {ignore_path}"
                    f"--extra-addons-path {path_addons_openupgrade}{extra_addons_path_extra} "
                    f"&& ./script/generate_config.sh"
                )
                self.todo_upgrade_execute(cmd_update_config)

                print(
                    f"🚸 {t('Please validate the commits after the code')}"
                    f" {t('migration.')}"
                )
                print(
                    f"ℹ {t('To show the repo status')} :"
                    "\nmake repo_show_status"
                )
                print(
                    f"🚸 {t('Please validate this path in config.conf')} :"
                    f" '{path_addons_openupgrade}'."
                )
                status = self.ask_gate(
                    f"💬 {t('Press to continue')} {msg}"
                    f" {t('(b = go back a step, t = show the migration state)')} : "
                ).strip()
                # The technique change at version 14
                if next_version <= 13:
                    erplibre_version = self.install_OCA_openupgrade(
                        next_version
                    )
                    cmd_upgrade = f".venv.{erplibre_version}/bin/python ./odoo{next_version}.0/OCA_OpenUpgrade/odoo-bin -c ./config.conf --update all --no-http --stop-after-init -d {database_name_upgrade}"
                else:
                    cmd_upgrade = f"./run.sh --upgrade-path=./odoo{next_version}.0/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all -c config.conf --stop-after-init --no-http --load=base,web,openupgrade_framework -d {database_name_upgrade}"
                lst_upgrade_odoo[index] = cmd_upgrade

                # Record the website COW views before the data migration. The
                # upgrade silently deletes and recreates copies (measured on
                # 12->13: 16 copies dropped, 13 created, children re-parented),
                # and rewrites the arch of many others. Without a before/after
                # record, "the site looks wrong" cannot be investigated.
                self.snapshot_cow_views(
                    database_name_upgrade, f"before_{next_version}"
                )

                # Take the copies that cannot survive this bump out of the way,
                # otherwise the data migration dies on them. Offered, not
                # forced: their arch is a real customization.
                self.neutralize_cow_views(database_name_upgrade, next_version)

                # wait_at_error=False on purpose: the generic « [1] to redo the
                # command » would replay OpenUpgrade on a database it has just
                # half migrated, which never recovers. The failure is handled
                # below by dropping the clone flag so the replay REBUILDS the
                # intermediate database from the previous version.
                status, cmd_executed = self.todo_upgrade_execute(
                    cmd_upgrade,
                    new_env={
                        "OPENUPGRADE_TARGET_VERSION": f"{next_version}.0"
                    },
                    wait_at_error=False,
                )

                # This is THE data migration. Recording it as done when it
                # failed used to send the loop to the next version on top of a
                # half-migrated database. Stop here instead: the state stays
                # unset, so a rerun replays this version.
                if status:
                    # The intermediate database is now half migrated and must
                    # not be reused: drop the clone flag so the rerun rebuilds
                    # it from the pristine source. Without this the replay
                    # would restart OpenUpgrade on top of the broken clone.
                    lst_clone_odoo[index] = False
                    self.dct_progression["state_4_clone_odoo_lst"] = (
                        lst_clone_odoo
                    )
                    self.write_config()
                    print(
                        f"\n❌ -> {t('Database migration to Odoo')}"
                        f"{next_version} {t('FAILED (status')} {status}).\n"
                        f"   '{database_name_upgrade}'"
                        f" {t('is now half migrated: replaying the command on')}"
                        f" {t('it would never recover, so it is NOT offered.')}"
                        f"\n   {t('The clone step has been reset. Fix the')}"
                        f" {t('cause, then relaunch the migration and answer')}"
                        f" [c] ({t('continue')}) :"
                        f" '{database_name_upgrade}'"
                        f" {t('will be dropped and rebuilt from the previous')}"
                        f" {t('version before retrying.')}"
                    )
                    return

                self.snapshot_cow_views(
                    database_name_upgrade, f"after_{next_version}"
                )
                self.diff_cow_views(
                    database_name_upgrade,
                    f"before_{next_version}",
                    f"after_{next_version}",
                )

                self.dct_progression["state_4_upgrade_odoo_lst"] = (
                    lst_upgrade_odoo
                )
                self.write_config()

                # ICI seulement la correction est possible : le checkout est
                # passé à la version cible, donc le shell sait faire
                # reset_asset. Et c'est le dernier moment utile — la mise à
                # jour des modules qui suit est ce qui compile les bundles,
                # donc ce qui échoue si un SCSS figé reste en place.
                self.run_on_terminal(
                    f"{PYTHON_BIN}"
                    " ./script/odoo/migration/check_stale_scss.py"
                    f" -d {database_name_upgrade} -t odoo{next_version}.0"
                )

                str_wait_next_version = (
                    " (or wait next version 🤖)"
                    if next_version != lst_next_version[-1]
                    else ""
                )

                status = (
                    self.ask(
                        f"💬 {t('Do you want to upgrade all')}"
                        f"{str_wait_next_version} ?"
                        f" (Y/n, {t('Enter upgrades all addons of the')}"
                        f" {t('database')}) : ",
                        default="y",
                    )
                    .strip()
                    .lower()
                )

                if status == "y":
                    self.todo_upgrade_execute(
                        f"./script/addons/update_addons_all.sh {database_name_upgrade}",
                    )

                # Au palier 13 SEULEMENT, et après la mise à jour des
                # modules : c'est là que MuK DMS devient OCA DMS, et donc
                # là que le modèle de sécurité change. OCA pose des règles
                # GLOBALES sur `permission_read`, accordé par une
                # `dms.access.group` — que la conversion ne crée pas,
                # puisque MuK n'en avait aucune. Les documents restent en
                # base, intacts, et plus personne ne les voit.
                #
                # L'outil ne fait rien s'il n'y a pas de DMS, et rien non
                # plus s'il a déjà réparé : le rejouer est sans effet.
                if next_version == 13:
                    self.run_on_terminal(
                        f"{PYTHON_BIN}"
                        " ./script/odoo/migration/dms_access_repair.py"
                        f" -d {database_name_upgrade} --apply"
                    )

                print(
                    f"✅ -> {t('Database upgrade done for Odoo')}"
                    f"{next_version}"
                )

                # Update config without OCA_OpenUpgrade
                cmd_update_config = f"./script/git/git_repo_update_group.py && ./script/generate_config.sh"
                self.todo_upgrade_execute(cmd_update_config)

                # Une migration peut charger tous ses modules et servir
                # quand même un 500 sur une page que personne n'ouvre. Mesuré
                # ici : /blog/<blog>/post/<billet> et /contactus, alors que
                # le journal de migration n'avait rien signalé.
                self.prompt_database_cleanup(database_name_upgrade)
                self.prompt_smoke_public_url(database_name_upgrade)

                # Le trou que ni les comptages ni le test de fumée ne
                # voient : des données PRÉSENTES qu'une règle globale
                # masque intégralement. Les comptages disent « tout est
                # là » — et c'est vrai. Les pages publiques répondent — et
                # c'est vrai aussi. Pourtant plus personne n'atteint les
                # données. Mesuré sur DMS au palier 13 : 69 fichiers et
                # 23 Mo intacts, zéro visible, pour tous les utilisateurs.
                self.run_on_terminal(
                    f"{PYTHON_BIN}"
                    " ./script/odoo/migration/check_hidden_models.py"
                    f" -d {database_name_upgrade}"
                )

                print(f"[y] {t('Open the server with Selenium')}")
                print(f"[a] {t('Open it at EVERY version bump, stop asking')}")
                # Une migration traverse jusqu'à six paliers. Répondre « y »
                # à chacun oblige à rester devant ; « a » est la réponse
                # qu'on donnait de toute façon six fois de suite, dite une
                # seule fois — et retenue, donc valable après une reprise.
                if self.dct_progression.get("state_4_selenium_every_bump"):
                    status = "y"
                    print(
                        f"ℹ -> {t('Testing every bump, as chosen earlier.')}"
                    )
                else:
                    status = (
                        self.ask(
                            f"💬 {t('Do you want to test this upgrade? Choose')}"
                            f" {t('or press enter to ignore it')} : "
                        )
                        .strip()
                        .lower()
                    )
                    if status == "a":
                        self.dct_progression["state_4_selenium_every_bump"] = (
                            True
                        )
                        self.write_config()
                        status = "y"
                "make repo_show_status"
                if status == "y":
                    self.todo.prompt_execute_selenium_and_run_db(
                        database_name_upgrade
                    )
                    status = self.ask(
                        f"💬 {t('Press enter to continue')} 4.{index} : "
                    ).strip()
            else:
                print(
                    f"✅ -> {t('Database upgrade already done for Odoo')}"
                    f"{next_version}"
                )

        #
        # waiting_input = self.ask("💬 Press any keyboard key to continue...")
        print("")

        msg = "5 - Cleaning up database after upgrade"
        self.print_step(msg)
        self.add_comment_progression(msg)

        print(
            f"✨ {t('Re-update i18n, purge the data and the tables')}"
            f" ({t('except mail_test and mail_test_full')})"
        )
        self.prompt_purge_dead_attachments(database_name_upgrade)
        # waiting_input = self.ask("💬print Press any keyboard key to continue...")
        msg = "6 - Migration finished"
        self.print_step(msg)
        self.add_comment_progression(msg)

        cmd_backup_template = f"./odoo_bin.sh db --backup --database {database_name_upgrade} --restore_image"
        cmd_backup = f"{cmd_backup_template} {database_name_upgrade}_finish_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        print(f"✨ {t('A backup can be created')} :\n{cmd_backup}")
        status = self.ask(
            f"💬 {t('Export a backup?')}"
            f" (Y/n, {t('or type filename.zip')}) : ",
            default="y",
        ).strip()
        cmd_backup = self.backup_command(
            status, cmd_backup_template, cmd_backup
        )
        if cmd_backup:
            self.todo_upgrade_execute(cmd_backup)

        status = self.ask(f"💬 {t('Test the migration, press y/Y')} : ")
        if status.lower().strip() == "y":
            self.todo.prompt_execute_selenium_and_run_db(database_name_upgrade)

    def _prompt_on_error(self, database_name, defaut, repare):
        """Le menu proposé quand une commande échoue. Rend (choix, réparé).

        Extrait de `todo_upgrade_execute` : à cinq entrées la méthode
        appelante passait le seuil de complexité, et une boucle d'invite
        se relit mieux seule que noyée dans l'exécution d'une commande.
        """
        # Une fois, avant la boucle : la détection lit un journal et
        # interroge la base, et la boucle peut tourner huit fois.
        themes = self.theme_blamed_by_the_error(database_name)
        tours = 0
        while True:
            # Une borne STRUCTURELLE, et non pas seulement la logique
            # ci-dessous qui bascule le défaut. Les deux protections
            # visent la même panne — une invite qui se repropose sans
            # fin — mais celle-ci tient même si l'autre est cassée un
            # jour par mégarde. Une boucle infinie dans une migration
            # lancée sans surveillance coûte une nuit.
            tours += 1
            if tours > self.MAX_ERROR_TURNS:
                print(f"🛑 {t('Too many turns on this prompt: moving on.')}")
                wait_status = ""
                break
            print(f"[1] {t('to redo the command')}")
            if database_name:
                print(
                    f"[2] {t('Check the COW views that drifted')}"
                    f" ({database_name})"
                )
                print(f"[3] {t('Reset one of them onto its module view')}")
                print(f"[4] {t('Browse the differences full screen')}")
                print(
                    f"[5] {t('Fix views whose type contradicts their')}"
                    f" {t('inheritance')}"
                )
                if themes:
                    print(
                        f"[6] {t('Uninstall the theme(s) the error names')}"
                        f" : {', '.join(themes)}"
                    )
            # `self.ask` : une migration automatique s'arrêtait ICI,
            # sur une invite qui ne demande qu'à continuer, et restait
            # bloquée sans que rien ne le signale.
            wait_status = (
                self.ask(
                    f"💬 {t('Error detected. Choose, or ctrl+c to')}"
                    f" {t('stop')}"
                    f" ({t('Enter')} = {defaut or t('continue')}) : ",
                    default=defaut,
                )
                .strip()
                .lower()
            )

            # psycopg2.errors.UndefinedTable: relation "discuss_channel" does not exist
            # LIGNE 1 : SELECT "discuss_channel"."id" FROM "discuss_channel" WHERE (...

            if wait_status == "2" and database_name:
                # Le motif d'échec le plus fréquent ici est « Element
                # <xpath …> cannot be located in parent view » : une copie
                # COW en retard sur sa vue module. On propose l'outil sur
                # place, puis on repose le choix pour rejouer.
                self.check_stale_cow_views(database_name)
                continue
            if wait_status == "3" and database_name:
                repare = self.prompt_reset_stale_cow_views(database_name)
                if repare:
                    # Quelque chose a changé : la commande mérite un
                    # nouvel essai, et c'est le seul cas où le rejeu
                    # est AUTOMATIQUE.
                    wait_status = "1"
                    break
                # Rien à réinitialiser. Reproposer « 3 » ferait tourner
                # en rond — mesuré : « Aucune copie COW n'a dérivé »,
                # encore et encore, sans fin.
                defaut = ""
                continue
            if wait_status == "6" and themes:
                # Le thème parti, la commande mérite un nouvel essai —
                # et `repare` autorise le rejeu automatique borné.
                for theme in themes:
                    self.run_on_terminal(
                        f"./script/addons/uninstall_addons_theme.sh"
                        f" {database_name} {theme}"
                    )
                wait_status = "1"
                repare = True
                break
            if wait_status == "5" and database_name:
                # Rien à voir avec les COW : ici la vue n'est PAS une
                # copie, c'est son `type` stocké qui ment. Odoo ne le
                # recalcule jamais — il le pose à la création — donc
                # aucune mise à jour ne le réparera, et le chargement
                # échoue avant d'y arriver.
                repare = self.prompt_fix_view_type(database_name)
                if repare:
                    wait_status = "1"
                    break
                defaut = ""
                continue
            if wait_status == "4" and database_name:
                # Sur le VRAI terminal : un plein écran refuse de
                # s'ouvrir sur un stdout capturé, et retomberait sur le
                # rapport texte sans que rien ne distingue les deux.
                self.run_on_terminal(
                    f"{PYTHON_BIN} ./"
                    + os.path.join(
                        PATH_MIGRATION_GLOBAL, "reset_stale_cow_views.py"
                    )
                    + f" -d {database_name} --tui"
                )
                continue
            break

        return wait_status, repare

    def prompt_fix_view_type(self, database):
        """Corriger les vues dont le `type` contredit leur héritage.

        Rend True si quelque chose a changé — c'est ce qui autorise le
        rejeu automatique de la commande.

        En SQL, sans l'ORM : le registre ne charge plus, et c'est
        précisément ce qu'on répare. Un outil qui aurait besoin d'Odoo
        pour réparer ce qui empêche Odoo de démarrer ne servirait à rien.
        """
        outil = os.path.join(PATH_MIGRATION_GLOBAL, "fix_view_type.py")
        # `wait_at_error=False` est OBLIGATOIRE : pour cet outil, 1 veut
        # dire « des trouvailles », pas « échec ». Sans ce drapeau,
        # `todo_upgrade_execute` y lit une panne et rouvre SON menu
        # d'erreur par-dessus le nôtre — mesuré : la question « Les
        # corriger ? » n'était jamais posée et le menu tournait en rond.
        status, _cmd = self.todo_upgrade_execute(
            f"{PYTHON_BIN} ./{outil} -d {database}",
            wait_at_error=False,
        )
        if status != 1:
            # 0 : rien à corriger. 2 : l'outil a échoué. Ni l'un ni
            # l'autre ne justifie de rejouer la commande.
            return False
        reponse = (
            self.ask(f"💬 {t('Correct them?')} (Y/n) : ", default="y")
            .strip()
            .lower()
        )
        if reponse not in ("y", "yes", "o"):
            return False
        status, _cmd = self.todo_upgrade_execute(
            f"{PYTHON_BIN} ./{outil} -d {database} --apply",
            wait_at_error=False,
        )
        return status == 0

    def prompt_purge_dead_attachments(self, database):
        """Effacer les pièces jointes dont le champ n'existe plus.

        ICI et pas entre les paliers. Mesuré : entre deux versions, deux
        à onze champs disparaissent puis REVIENNENT — `hr.employee.phone`,
        `account.move.statement_id`. « Le champ n'existe plus » est donc
        un état transitoire tant que la migration court, et purger
        dessus, c'est trancher sur ce qui va se rétablir.

        Le gain d'un nettoyage par palier serait nul de toute façon :
        mesuré, 1881 lignes apparaissent au palier 13 et le compte ne
        bouge plus ensuite. Une passe finale les prend toutes.

        Après la sauvegarde ? Non, AVANT : celle qui suit capturera
        l'état nettoyé, et qui veut garder l'état d'avant n'a qu'à
        refuser ici puis relancer l'outil depuis le menu Analyse.
        """
        from script.analyse import check_filestore as filestore

        try:
            rapport = filestore.audit(database)
        except Exception as exc:
            print(f"⚠ {t('Could not inspect the attachments: ')}{exc}")
            return
        if rapport.get("unavailable"):
            return
        sql = filestore.purge_dead_sql(rapport)
        combien = len(rapport.get("dead_ids") or [])
        if not sql:
            print(f"✅ {t('No attachment points at a field that is gone.')}")
            return
        poids = rapport.get("dead_kept_size", 0) // 1024
        print()
        print(
            f"🕳 {combien}"
            f" {t('attachment(s) point at a field that no longer exists')}"
            f" ({poids} ko)"
        )
        for texte in filestore.summarise(
            rapport["groups"]["dead_field"] + (rapport.get("dead_kept") or [])
        )[:6]:
            print(f"   {texte}")
        reponse = (
            self.ask(f"💬 {t('Delete them?')} (Y/n) : ", default="y")
            .strip()
            .lower()
        )
        if reponse not in ("y", "yes", "o"):
            print(f"ℹ️  {t('Nothing was deleted.')}")
            return
        status, _cmd, sortie = self.todo_upgrade_execute(
            f'psql -d {database} -c "{sql}"', get_output=True
        )
        if status:
            print(f"❌ {t('The purge failed.')}")
            return
        efface = filestore.rows_deleted(sortie)
        if efface is None:
            print(f"⚠ {t('The purge ran but said nothing.')}")
            return
        print(f"✅ {efface} {t('attachment row(s) deleted.')}")

    def get_rename_module(self, lst_module, next_version):
        path_search = f"odoo{next_version}.0/OCA_OpenUpgrade/"
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            f"find {path_search} -name apriori.py",
            get_output=True,
        )

        if not lst_output:
            _logger.error(
                f"Cannot find renamed module script apriori.py into path '{path_search}'"
            )
            return lst_module
        apriory_py = lst_output[0].strip()

        with open(apriory_py, "r") as f:
            file_content = f.read()

        data_vars = {}
        exec(file_content, data_vars)
        renamed_modules = data_vars.get("renamed_modules", {})
        merged_modules = data_vars.get("merged_modules", {})
        deleted_modules = data_vars.get("deleted_modules", [])

        lst_index_to_delete = []
        for index, module in enumerate(lst_module):
            renamed_module = renamed_modules.get(module)
            merged_module = merged_modules.get(module)
            if renamed_module:
                lst_module[index] = renamed_module
            if merged_module:
                lst_module[index] = merged_module
            if module in deleted_modules:
                lst_index_to_delete.append(index)
        for index_to_delete in lst_index_to_delete[::-1]:
            lst_module.pop(index_to_delete)
        return list(set(lst_module))

    def search_module_to_move(self, source_version_odoo, target_version_odoo):
        lst_module = []
        # lst_path_to_check = [
        #     os.path.join(f"odoo{actual_version_odoo}", "addons"),
        #     os.path.join(f"odoo{target_version_odoo}", "addons"),
        #     os.path.join(f"private", "addons"),
        # ]
        source_path_to_check = os.path.join(
            f"odoo{source_version_odoo}.0", "addons", "addons"
        )
        target_path_to_check = os.path.join(
            f"odoo{target_version_odoo}.0", "addons", "addons"
        )

        # Search
        is_moving_git = False
        if os.path.exists(source_path_to_check):
            if os.path.exists(os.path.join(source_path_to_check, ".git")):
                is_moving_git = True
            if not os.path.exists(target_path_to_check):
                shutil.copytree(source_path_to_check, target_path_to_check)
                # if not is_moving_git:
                #     os.mkdir(path_to_check_target)
                # else:
                #     # TODO clone
                #     pass

            if not is_moving_git:
                # TODO do something
                # Time to compare
                os.listdir(source_path_to_check)

        if os.path.exists(target_path_to_check):
            for dir_name in os.listdir(target_path_to_check):
                source_module_path = os.path.join(
                    source_path_to_check, dir_name
                )
                source_manifest_path = os.path.join(
                    source_module_path, "__manifest__.py"
                )

                target_module_path = os.path.join(
                    target_path_to_check, dir_name
                )
                target_manifest_path = os.path.join(
                    target_module_path, "__manifest__.py"
                )
                if os.path.exists(target_manifest_path):
                    # TODO remove from list when module already exist in version 15
                    dct_module = {
                        "source_module_path": source_module_path,
                        "source_manifest_path": source_manifest_path,
                        "source_addons_path": source_path_to_check,
                        "target_module_path": target_module_path,
                        "target_manifest_path": target_manifest_path,
                        "target_addons_path": target_path_to_check,
                        "module_name": dir_name,
                        "source_version_odoo": source_version_odoo,
                        "target_version_odoo": target_version_odoo,
                    }
                    lst_module.append(dct_module)

        dct_module = {
            "lst_module": lst_module,
            "source_module_path": source_path_to_check,
            "target_module_path": target_path_to_check,
        }
        return dct_module

    def snapshot_cow_views(self, database_name, label):
        """Record the website COW views of a database under private/.

        Never blocks the migration: a snapshot is forensic material, its
        absence must not stop an upgrade.
        """
        self.todo_upgrade_execute(
            f"{PYTHON_BIN} ./script/odoo/migration/snapshot_cow_views.py"
            f" -d {database_name} -l {label}",
            wait_at_error=False,
        )

    def print_step(self, msg):
        """Affiche un en-tête d'étape en traduisant son seul libellé.

        `msg` reste anglais : il part aussi dans le journal, que l'écran de
        reprise relit. Traduire ce qui est ÉCRIT rendrait un journal
        illisible pour l'autre langue, et l'étape 4 numérote ses en-têtes
        (« 4.2.C - Install module ») — seule la partie après le tiret est
        une phrase.
        """
        prefix, sep, label = msg.partition(" - ")
        # Retenu pour l'écran d'état : un événement sans étape oblige à
        # relire tout le journal pour savoir OÙ il s'est produit.
        self.current_step = msg
        self.open_step_log(msg)
        print(f"🔷 {prefix}{sep}{t(label)}" if sep else f"🔷 {t(msg)}")

    def installed_theme(self, database_name):
        """Thèmes installés, hors theme_default qui EST l'absence de thème."""
        status, _cmd, output = self.todo_upgrade_execute(
            f'psql -X -w -d {database_name} -tAc "SELECT name FROM'
            " ir_module_module WHERE name LIKE 'theme%' AND"
            " state = 'installed' AND name <> 'theme_default'"
            ' ORDER BY name;"',
            get_output=True,
            wait_at_error=False,
            quiet=True,
        )
        if status:
            return []
        return [line.strip() for line in (output or []) if line.strip()]

    def step_log_tail(self, octets=65536):
        """La fin du journal de l'étape en cours, ou "".

        Bornée, et lue depuis la FIN : une mise à jour de modules écrit
        des dizaines de milliers de lignes, et charger tout le fichier
        pour en regarder vingt coûterait plus que l'erreur qu'on cherche.
        """
        chemin = self.log_dir()
        etape = getattr(self, "current_step", "")
        if not chemin or not etape:
            return ""
        fichier = os.path.join(chemin, f"{self.step_slug(etape)}.log")
        try:
            with open(fichier, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                depart = max(0, handle.tell() - octets)
                handle.seek(depart)
                return handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def theme_blamed_by_the_error(self, database_name):
        """Les thèmes installés que la sortie récente MET EN CAUSE.

        Deux conditions, pas une. Un thème doit être installé — sinon il
        n'y a rien à retirer — ET son nom doit figurer dans ce que la
        commande vient d'écrire. Proposer la désinstallation à chaque
        échec reviendrait à offrir de casser le design du site pour une
        panne qui n'a rien à voir.
        """
        if not database_name:
            return []
        installes = self.installed_theme(database_name)
        if not installes:
            return []
        journal = self.step_log_tail()
        if not journal:
            return []
        return [nom for nom in installes if nom in journal]

    def prompt_uninstall_theme(self, database_name):
        """Proposer de retirer les thèmes AVANT de monter de version.

        Un thème installé traverse la migration : ses copies de vues et ses
        SCSS suivent chaque palier, et chaque palier peut renommer ce dont
        ils dépendent. Le retirer d'abord enlève d'un coup une famille
        entière de pannes, et se refait après.

        « non » par défaut : retirer un thème change l'apparence du site, et
        ce n'est pas à une migration de le décider à la place de quelqu'un.
        La question n'est posée que s'il y a un thème à retirer.
        """
        lst_theme = self.installed_theme(database_name)
        if not lst_theme:
            return
        print(
            f"\n✨ {t('Installed theme(s) on')} '{database_name}' :"
            f" {', '.join(lst_theme)}"
        )
        print(
            f"   {t('A theme carries view copies and SCSS through every')}"
            f" {t('version bump, and a bump can rename what they rely on.')}"
        )
        answer = (
            self.ask_gate(
                f"💬 {t('Uninstall them properly before migrating?')}"
                f" (Y/n, {t('(b = go back a step, t = show the migration state)')}) : ",
                default="y",
            )
            .strip()
            .lower()
        )
        if answer != "y":
            print(f"ℹ -> {t('Kept. Nothing was uninstalled.')}")
            return
        for theme in lst_theme:
            # Sur le VRAI terminal : ce script finit par theme_leftover.py,
            # qui pose une question. L'exécuteur capture la sortie par un
            # tube — Python la met alors en tampon par blocs — et l'invite
            # restait invisible pendant que le processus attendait une
            # réponse. On tape Entrée à l'aveugle, plusieurs fois, et les
            # frappes en trop vont à la question suivante.
            self.run_on_terminal(
                f"./script/addons/uninstall_addons_theme.sh"
                f" {database_name} {theme}"
            )

    def stale_cow_keys(self, database_name):
        """Les clés des copies COW en retard, sans décor."""
        script_path = os.path.join(
            PATH_MIGRATION_GLOBAL, "reset_stale_cow_views.py"
        )
        if not os.path.exists(script_path):
            return []
        status, _cmd, output = self.todo_upgrade_execute(
            f"{PYTHON_BIN} ./{script_path} -d {database_name} --list-keys",
            get_output=True,
            wait_at_error=False,
            quiet=True,
        )
        if status == 2:
            return []
        return [line.strip() for line in (output or []) if line.strip()]

    def prompt_reset_stale_cow_views(self, database_name):
        """Choisir quoi réinitialiser dans une LISTE, pas de mémoire.

        L'aide disait « --reset <key> --apply » et laissait retrouver la clé
        dans un diff de mille lignes. On la recopie, on se trompe d'un
        caractère, et la commande ne fait rien sans le dire — une clé qui ne
        correspond à rien n'est pas une erreur pour l'outil.

        Rend True si quelque chose a VRAIMENT été réinitialisé. C'est ce qui
        permet de rejouer la commande derrière : rejouer alors qu'on n'a
        rien changé donnerait le même échec, indéfiniment.
        """
        lst_key = self.stale_cow_keys(database_name)
        if not lst_key:
            print(
                f"✅ -> {t('No COW copy has drifted from its module view.')}"
            )
            return False
        print(f"\n✨ {t('Drifted COW copies')} :")
        for index, key in enumerate(lst_key, start=1):
            print(f"   [{index}] {key}")
        print(f"   [a] {t('All of the list above')}")
        answer = (
            self.ask_gate(
                f"💬 {t('Which one(s) to reset onto the module view?')}"
                f" ({t('numbers separated by commas, Enter = all, n =')}"
                f" {t('nothing')}) : ",
                default="a",
            )
            .strip()
            .lower()
        )
        # « n », et non plus le vide : Entrée vaut « toutes » maintenant, et
        # une sortie sans mot pour dire non serait une sortie sans issue.
        if not answer or answer == "n":
            print(f"ℹ -> {t('Kept. Nothing was reset.')}")
            return False
        if answer == "a":
            lst_chosen = ["all"]
        else:
            lst_chosen = []
            for part in answer.replace(" ", "").split(","):
                if part.isdigit() and 1 <= int(part) <= len(lst_key):
                    lst_chosen.append(lst_key[int(part) - 1])
            if not lst_chosen:
                print(f"⚠️ {t('Unknown choice, nothing was reset.')}")
                return False
        args = " ".join(f"--reset {key}" for key in lst_chosen)
        status = self.run_tool(
            "reset_stale_cow_views",
            f"{PYTHON_BIN} ./{os.path.join(PATH_MIGRATION_GLOBAL, 'reset_stale_cow_views.py')}"
            f" -d {database_name} {args} --apply",
        )
        return status == 0

    def prompt_database_cleanup(self, database_name):
        """Proposer le nettoyage OCA avant d'interroger les pages.

        Une migration laisse derrière elle des modèles, colonnes, tables,
        données et menus obsolètes. Les interroger ensuite fait chercher des
        pannes dans des restes qui n'auraient pas dû survivre — et le
        nettoyage lui-même en répare une partie.

        « non » par défaut : cela écrit en base, et c'est à vous d'en
        décider.
        """
        answer = (
            self.ask_gate(
                f"💬 {t('Clean the database before testing the pages?')}"
                f" (Y/n, {t('(b = go back a step, t = show the migration state)')}) : ",
                default="y",
            )
            .strip()
            .lower()
        )
        if answer != "y":
            return
        self.run_tool(
            "database_cleanup",
            f"{PYTHON_BIN}"
            " ./script/odoo/migration/database_cleanup.py"
            f" -d {database_name}",
        )

    def prompt_smoke_public_url(self, database_name, baseline=False):
        """Proposer d'interroger toutes les pages publiques de la base.

        La liste vient du sitemap — celle qu'Odoo publie pour les moteurs de
        recherche. Une page qui y figure et ne répond pas est une page que
        les visiteurs n'atteignent pas non plus.

        `baseline` marque la mesure d'AVANT le premier palier. Elle ne sert
        pas à réparer — elle sert à savoir ce qui cassait déjà. Sans ce point
        de départ, les mêmes 500 après le palier passent pour un dégât de la
        migration, et l'on cherche du mauvais côté.

        Le serveur ainsi démarré sert AUSSI au back-office : si la base a
        été neutralisée, l'outil se connecte avec l'utilisateur `test` que
        la neutralisation y a posé et ouvre la première page de chaque
        application. Un deuxième outil avec son propre serveur doublerait
        l'attente — le démarrage d'Odoo est ce qui coûte, pas les requêtes.
        """
        if baseline:
            print(
                f"\n✨ {t('Before starting: what already answers, and what')}"
                f" {t('does not. A page broken now will still be broken')}"
                f" {t('after — and that is not the migration.')}"
            )
        answer = (
            self.ask_gate(
                f"💬 {t('Request every public URL of this database now?')}"
                f" (Y/n, {t('(b = go back a step, t = show the migration state)')}) : ",
                default="y",
            )
            .strip()
            .lower()
        )
        if answer != "y":
            return
        # DIRE ce qui sera parcouru, et le dire AVANT. « si la base a été
        # neutralisée » laissait la question ouverte pendant tout le
        # parcours, et un saut annoncé en une ligne à la fin d'un long
        # rapport ne se voit pas : on croit alors le back-office testé.
        neutralise = "_neutralize" in database_name
        if neutralise:
            print(
                f"   {t('Public pages, then the back office and /my as the')}"
                f" {t('test user (neutralized database).')}"
            )
        else:
            print(
                f"   {t('Public pages only:')} '{database_name}'"
                f" {t('was not neutralized, so there is no test user to')}"
                f" {t('sign in with.')}"
            )
        self.run_tool(
            "smoke_public_url",
            f"{PYTHON_BIN}"
            " ./script/odoo/migration/smoke_public_url.py"
            f" -d {database_name}"
            + (" --internal-required" if neutralise else ""),
        )

    def show_cow_drift(self, database_name, next_version, mode="diff"):
        """Montre les copies COW à risque. Ne touche à rien.

        Un seul endroit construit la commande : les deux invites — celle de
        l'étape 2 et celle du palier — montraient sinon des choses qui
        pouvaient diverger sans que rien ne le signale.
        """
        cmd = (
            f"{PYTHON_BIN} ./script/odoo/migration/cow_drift.py"
            f" -d {database_name} -t odoo{next_version}.0"
        )
        if mode == "shape":
            cmd += " --shape"
        elif mode == "tui":
            cmd += " --tui"
        self.run_on_terminal(cmd)

    def run_on_terminal(self, cmd):
        """Lance une commande en lui laissant le VRAI terminal.

        `todo_upgrade_execute` capture la sortie par un tube. Un plein écran
        y voit un stdout qui n'est pas un terminal, renonce, et retombe sur
        son rapport texte : « w » réaffichait mot pour mot ce que « v »
        venait de montrer, sans rien signaler.

        Rien ne relit cette sortie — elle est REGARDÉE. Et le code de retour
        d'un afficheur ne veut pas dire « erreur » : 1 signifie « il y a des
        copies », ce qui est la raison même de l'avoir ouvert. L'annoncer
        comme un échec inquiétait pour rien.
        """
        self.lst_command_executed.append(cmd)
        self.dct_progression["command_executed"] = self.lst_command_executed
        self.write_config()
        print(f"\n🏠 ⬇ {t('Execute command')} :\n")
        print(cmd)
        self.note_step_log(f"$ {cmd}")
        status = subprocess.call(cmd, shell=True, executable="/bin/bash")
        self.note_step_log(f"  -> {status}")
        return status

    def prompt_cow_prediction(self, database_name, next_version):
        """Que faire des copies COW annoncées, dès l'étape 2.

        La neutralisation officielle a lieu au palier, sur la base de palier.
        Mais celle-ci en est la source : ce qu'on neutralise ici vaut pour
        tous les paliers, et la lecture n'écrit rien de toute façon. Attendre
        des dizaines de minutes pour seulement REGARDER n'avait pas de raison
        d'être.
        """
        neutralize = (
            f"{PYTHON_BIN} ./script/odoo/migration/neutralize_cow_views.py"
            f" -d {database_name} -t odoo{next_version}.0"
        )
        while True:
            # `self.ask`, pas `input` : cette invite boucle, et un `input`
            # nu ici arrêtait net une migration automatique — sans rien
            # afficher, puisque la question attendait déjà.
            answer = (
                self.ask(
                    f"💬 {t('What do you want to do with these COW copies?')}"
                    f" ({t('Enter = neutralize now, reversible')},"
                    f" v = {t('what each copy holds')},"
                    f" s = {t('why it breaks')},"
                    f" w = {t('full screen')},"
                    f" n = {t('decide at the version bump')}) : ",
                    default="a",
                )
                .strip()
                .lower()
            )
            if answer in ("v", "s", "w"):
                self.show_cow_drift(
                    database_name,
                    next_version,
                    {"v": "diff", "s": "shape", "w": "tui"}[answer],
                )
                continue
            if answer == "a":
                self.todo_upgrade_execute(
                    f"{neutralize} --apply", wait_at_error=False
                )
                print(
                    f"ℹ -> {t('Undo with')} :"
                    f" {neutralize.rsplit(' -t', 1)[0]} --restore"
                )
                return
            break
        print(
            f"ℹ -> {t('Nothing decided')} :"
            f" {t('the migration will ask again at the version bump.')}"
        )

    def neutralize_cow_views(self, database_name, next_version):
        """Offer to neutralize the COW views that would break this bump.

        Renaming their key unpairs them from the module view, so the upgrade
        stops choking on them. Nothing is deleted and the operation is
        reversible (neutralize_cow_views.py --restore), but the choice belongs
        to the user: those copies carry real customizations.
        """
        cmd = (
            f"{PYTHON_BIN} ./script/odoo/migration/neutralize_cow_views.py"
            f" -d {database_name} -t odoo{next_version}.0"
        )
        status, cmd_executed, output = self.todo_upgrade_execute(
            cmd, get_output=True, wait_at_error=False
        )
        # 0 = rien à neutraliser. Lire une phrase anglaise dans la sortie
        # faisait poser la question dès que l'outil parlait français.
        if status == 0:
            return

        # « v » et « w » avant de répondre : la question demande de renoncer à
        # une personnalisation sans avoir montré laquelle. Souvent trois lignes
        # — un id, une largeur de conteneur — mais parfois une page entière, et
        # rien dans l'avertissement ne permet de les distinguer.
        while True:
            answer = (
                self.ask(
                    "💬 Neutralize these copies so the upgrade can proceed?"
                    " Their arch is kept and the change is reversible."
                    " (Y/n, v = view the differences, w = full screen) : ",
                    default="y",
                )
                .strip()
                .lower()
            )
            if answer == "v":
                self.show_cow_drift(database_name, next_version, "diff")
                self.show_cow_drift(database_name, next_version, "shape")
                continue
            if answer == "w":
                self.show_cow_drift(database_name, next_version, "tui")
                continue
            break

        if answer == "n":
            print(
                "⚠️ -> Skipped. The data migration will very likely stop on"
                " these views."
            )
            return
        self.todo_upgrade_execute(f"{cmd} --apply", wait_at_error=False)
        print(
            "ℹ -> List them later with:"
            f" {PYTHON_BIN} ./script/odoo/migration/neutralize_cow_views.py"
            f" -d {database_name} --list"
        )

    def diff_cow_views(self, database_name, label_before, label_after):
        """Print what the version bump did to the website COW views."""
        directory = os.path.join(
            PATH_MIGRATION_PRIVATE, database_name, "cow_snapshots"
        )
        path_before = os.path.join(directory, f"{label_before}.json")
        path_after = os.path.join(directory, f"{label_after}.json")
        if not (os.path.exists(path_before) and os.path.exists(path_after)):
            return
        self.todo_upgrade_execute(
            f"{PYTHON_BIN} ./script/odoo/migration/snapshot_cow_views.py"
            f" --diff {path_before} {path_after}",
            wait_at_error=False,
        )

    @staticmethod
    def parse_module_list_file(file_path):
        """Read a module list file, return [(module, reason), ...].

        Accepted syntax, one module per line with an optional justification:

            queue_job          # blocks 12->13, trigger queue_job_notify
            mgmtsystem_hazard  # not ported to 13.0

        Commas and several names per line are also accepted, so a list copied
        from a command line works as-is. Blank lines and full-line comments are
        ignored.

        The previous parser was « f.readline().split() »: it kept only the FIRST
        line, so a multi-line list was silently truncated, and a comma-separated
        list collapsed into one bogus module name.
        """
        lst_module = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                content, _, reason = line.partition("#")
                for module_name in content.replace(",", " ").split():
                    lst_module.append((module_name, reason.strip()))
        return lst_module

    @staticmethod
    def print_uninstall_reason(lst_detail):
        """Show WHY each module goes away.

        Which modules must be dropped depends on the database, and a removal
        without a stated reason is a decision nobody can review later.
        """
        for name, reason, origin in lst_detail:
            print(
                f"   - {name}"
                + (f" — {reason}" if reason else " — ⚠️ no reason given")
                + f"  [{origin}]"
            )

    def read_uninstall_module_list(self, start_version, database_name):
        """Modules to uninstall before migrating start_version -> next.

        Reads the per-database private list first, then the shared versioned
        defaults; duplicates are dropped, keeping the first occurrence.

        Returns (lst_module, lst_detail) where lst_detail carries
        (module, reason, origin_file) so the caller can justify each removal.
        """
        file_name = (
            f"uninstall_module_list_odoo{start_version * 10}"
            f"_to_odoo{(start_version + 1) * 10}.txt"
        )
        lst_path = [
            os.path.join(PATH_MIGRATION_PRIVATE, database_name, file_name),
            os.path.join(PATH_MIGRATION_GLOBAL, file_name),
        ]

        lst_module = []
        lst_detail = []
        for file_path in lst_path:
            if not os.path.exists(file_path):
                continue
            for module_name, reason in self.parse_module_list_file(file_path):
                if module_name in lst_module:
                    continue
                lst_module.append(module_name)
                lst_detail.append((module_name, reason, file_path))
        return lst_module, lst_detail

    def split_present_missing(self, lst_module):
        """Split a module list into (present, missing) against the ACTIVE code.

        « Missing » means the addons path no longer holds the module — not
        that it is absent from the database. The distinction matters because
        check_addons_exist.py refuses the WHOLE uninstall for a single missing
        name, so the modules that ARE there never get uninstalled either.
        """
        lst_missing, _lst_duplicate = self.check_addons_exist(lst_module)
        set_missing = set(lst_missing or [])
        return (
            [name for name in lst_module if name not in set_missing],
            [name for name in lst_module if name in set_missing],
        )

    def prompt_uninstall_missing(self, lst_present, lst_missing):
        """Ask what to do when part of the list has no code left.
        Returns the list to actually uninstall (possibly empty)."""
        print()
        print(
            f"⚠️  {len(lst_missing)} "
            f"{t('modules of the list have no code in the active Odoo:')}"
        )
        for name in lst_missing:
            print(f"      {name}")
        print(f"    {t('Odoo cannot uninstall a module whose code is gone;')}")
        print(f"    {t('one of them fails the whole uninstall command.')}")
        print()
        if lst_present:
            print(
                f"    {len(lst_present)} "
                f"{t('are present and can be uninstalled:')}"
            )
            for name in lst_present:
                print(f"      {name}")
        else:
            print(f"    {t('No module of the list is present.')}")
        print()
        if lst_present:
            print(
                f"    [1] {t('Uninstall the present ones, skip the missing')}"
                " *"
            )
        print(f"    [2] {t('Try the whole list anyway (it will fail)')}")
        print(f"    [3] {t('Uninstall nothing, continue')}")
        answer = self.ask(
            f"💬 {t('Your choice')} ({t('Enter = 1')}) : ", default="1"
        ).strip()
        if answer == "2":
            return lst_present + lst_missing
        if answer == "3" or not lst_present:
            return []
        return lst_present

    def uninstall_from_database(
        self, lst_module_to_uninstall, database_name, actual_version
    ):
        if not lst_module_to_uninstall:
            return
        # Sort out what the active code still holds BEFORE calling the script:
        # it aborts on the first missing name and takes the rest down with it.
        lst_present, lst_missing = self.split_present_missing(
            lst_module_to_uninstall
        )
        if lst_missing:
            self.add_comment_progression(
                "uninstall - no code for: " + ", ".join(lst_missing)
            )
            lst_module_to_uninstall = self.prompt_uninstall_missing(
                lst_present, lst_missing
            )
            if not lst_module_to_uninstall:
                print(f"⏭  {t('Nothing uninstalled.')}")
                return
        uninstall_module = ",".join(lst_module_to_uninstall)
        self.todo_upgrade_execute(
            f"./script/addons/uninstall_addons.sh {database_name} {uninstall_module}",
            single_source_odoo=True,
        )

        # Update list installed module — only what was REALLY uninstalled, so
        # a module left in place stays counted as installed.
        self.dct_module_per_version[actual_version] = sorted(
            list(
                set(self.dct_module_per_version[actual_version])
                - set(lst_module_to_uninstall)
            )
        )
        self.dct_progression["dct_module_per_version"] = (
            self.dct_module_per_version
        )
        self.write_config()

    def install_from_database(
        self, lst_module_to_install, database_name, actual_version
    ):
        if not lst_module_to_install:
            return
        install_module = ",".join(lst_module_to_install)
        self.todo_upgrade_execute(
            f"./script/addons/install_addons.sh {database_name} {install_module}",
            single_source_odoo=True,
        )

        # Update list installed module
        self.dct_module_per_version[actual_version] = sorted(
            list(
                set(
                    self.dct_module_per_version[actual_version]
                    + lst_module_to_install
                )
            )
        )
        self.dct_progression["dct_module_per_version"] = (
            self.dct_module_per_version
        )
        self.write_config()

    def check_addons_exist(
        self, lst_module_to_check, ignore_error=True, get_all_info=False
    ):
        str_module_to_check = ",".join(sorted(lst_module_to_check))
        status, cmd_executed, dct_output = self.todo_upgrade_execute(
            f"{PYTHON_BIN} ./script/addons/check_addons_exist.py --format_json --output_json -m {str_module_to_check}",
            get_output=True,
            output_is_json=True,
            wait_at_error=not ignore_error,
        )

        lst_module_missing = dct_output.get("missing")
        lst_module_duplicate = dct_output.get("duplicate")
        if get_all_info:
            lst_module_error = dct_output.get("error")
            lst_module_exist = dct_output.get("exist")
            return (
                lst_module_missing,
                lst_module_duplicate,
                lst_module_exist,
                lst_module_error,
            )

        return lst_module_missing, lst_module_duplicate

    def switch_odoo(self, odoo_version):
        int_odoo_version = int(float(odoo_version))

        # Expect odoo_version like 12.0
        lst_version, lst_version_installed, odoo_installed_version = (
            get_odoo_version()
        )
        if odoo_installed_version != f"odoo{int_odoo_version}.0":
            print(
                f"⧖ -> Was '{odoo_installed_version}', Switch to odoo{int_odoo_version}.0"
            )
            self.todo_upgrade_execute(f"make switch_odoo_{int_odoo_version}")
            self.todo_upgrade_execute("make config_gen_all")

    def install_OCA_odoo_module_migrator(self):
        if not os.path.exists(PATH_VENV_MODULE_MIGRATOR):
            self.todo_upgrade_execute(
                f"cd {PATH_OCA_ODOO_MODULE_MIGRATOR} && python -m venv {VENV_NAME_MODULE_MIGRATOR} && source {VENV_NAME_MODULE_MIGRATOR}/bin/activate && pip3 install -r requirements.txt"
            )

    def install_OCA_openupgrade(self, next_version):
        # TODO install odoorpc==0.7.0
        # openupgradelib
        # openupgrade_path = f"odoo{next_version}.0/OCA_OpenUpgrade"
        # venv_oca_path = f"{openupgrade_path}/.venv"
        # if os.path.exists(venv_oca_path):
        #     return
        lst_version, lst_version_installed, odoo_installed_version = (
            get_odoo_version()
        )
        extract_version = f"{next_version}.0"
        dct_erplibre_info = [
            a for a in lst_version if a.get("odoo_version") == extract_version
        ]
        if not dct_erplibre_info:
            raise Exception(f"Cannot extract {extract_version}")
        dct_erplibre_info = dct_erplibre_info[0]
        erplibre_version = dct_erplibre_info.get("erplibre_version")
        # self.todo_upgrade_execute(
        #     f".venv.{erplibre_version}/bin/python -m venv {venv_oca_path} && {venv_oca_path}/bin/pip3 install -r {openupgrade_path}/requirements.txt"
        # )
        self.todo_upgrade_execute(
            f".venv.{erplibre_version}/bin/pip install odoorpc==0.7.0"
        )
        self.todo_upgrade_execute(
            f".venv.{erplibre_version}/bin/pip install openupgradelib"
        )
        return erplibre_version

    def todo_upgrade_execute(
        self,
        cmd,
        single_source_odoo=False,
        new_env=None,
        quiet=False,
        get_output=False,
        output_is_json=False,
        wait_at_error=True,
        attempt=1,
    ):
        if output_is_json and not get_output:
            get_output = True
        output = None
        if get_output:
            status, cmd_executed, output = self.execute.exec_command_live(
                cmd,
                source_erplibre=False,
                single_source_odoo=single_source_odoo,
                new_env=new_env,
                return_status_and_output_and_command=True,
                quiet=quiet,
            )
        else:
            status, cmd_executed = self.execute.exec_command_live(
                cmd,
                source_erplibre=False,
                single_source_odoo=single_source_odoo,
                new_env=new_env,
                return_status_and_command=True,
                quiet=quiet,
            )
        self.lst_command_executed.append(cmd_executed)
        self.dct_progression["command_executed"] = self.lst_command_executed
        self.write_config()
        # None means « the command never reported a status » -> treat it as a
        # failure, never as a success (defence in depth: exec_command_live now
        # always sets one, but a silent None must not skip this prompt).
        if (status is None or status) and wait_at_error:
            # AVANT l'invite : si l'on répond ctrl+c, l'échec doit tout de
            # même figurer dans l'état — c'est précisément celui qu'on
            # cherchera en revenant.
            self.record_event("command", cmd, status if status else 1)
            database_name = self.database_from_command(cmd)
            # « 3 » par défaut, car le motif d'échec le plus fréquent ici est
            # une copie COW en retard : la réparer est presque toujours ce
            # qu'on allait faire. Sans base nommée, les options 2 à 4
            # n'existent pas et le défaut redevient « continuer ».
            defaut = "3" if database_name else ""
            repare = False
            wait_status, repare = self._prompt_on_error(
                database_name, defaut, repare
            )

            if wait_status == "1":
                # Le rejeu AUTOMATIQUE est borné ; celui qu'on demande à la
                # main ne l'est pas. Sans cette borne, une réparation qui
                # n'y suffit pas relancerait la commande indéfiniment — et
                # une migration lancée en auto-exécution tournerait toute
                # la nuit sur le même échec.
                if repare and attempt >= self.MAX_ERROR_RETRY:
                    print(
                        f"🛑 {t('Still failing after')}"
                        f" {self.MAX_ERROR_RETRY}"
                        f" {t('attempts: this one needs a developer.')}"
                    )
                else:
                    return self.todo_upgrade_execute(
                        cmd,
                        single_source_odoo=single_source_odoo,
                        new_env=new_env,
                        quiet=quiet,
                        get_output=get_output,
                        output_is_json=output_is_json,
                        wait_at_error=wait_at_error,
                        attempt=attempt + 1,
                    )

        if get_output:
            if output_is_json:
                str_output = json.loads("".join(output))
                return status, cmd_executed, str_output
            return status, cmd_executed, output
        return status, cmd_executed

    def check_and_clone_source_to_target_migration_code(
        self, next_version, source_addons_path, target_addons_path
    ):
        if not os.path.exists(os.path.join(source_addons_path, ".git")):
            return
        if os.path.exists(os.path.join(target_addons_path, ".git")):
            return
        # if not os.path.exists(target_addons_path):
        #     cmd_mkdir = f"mkdir -p {target_addons_path}"
        #     status, cmd_executed, lst_output = self.todo_upgrade_execute(
        #         cmd_mkdir,
        #         get_output=True,
        #     )
        #     return
        source_dir_name = os.path.basename(source_addons_path)
        # Clone a project for next version
        # Get actual branch
        cmd_git_clone_migrate_source = (
            f"cd {source_addons_path} && "
            f"git branch --show-current && "
            f"cd ~-"
        )
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            cmd_git_clone_migrate_source,
            get_output=True,
        )
        branch_source = lst_output[0].strip() if len(lst_output) else ""
        if not branch_source:
            # Get branch from repo
            branch_source = self.get_branch_name_from_local_manifest(
                source_addons_path, f"{next_version}.0"
            )
        branch_target = branch_source.replace(
            str(next_version - 1), str(next_version)
        )
        # Get remote branch for actual version
        cmd_git_clone_migrate_source_same_target = (
            f"cd {source_addons_path} "
            f"&& git fetch --all "
            f'&& git branch -vv | grep "{branch_source}" '
            f"&& cd ~-"
        )
        cmd_git_clone_migrate_source_same_target_remote_only = (
            f"cd {source_addons_path} && git remote && cd ~-"
        )
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            cmd_git_clone_migrate_source_same_target,
            get_output=True,
            wait_at_error=False,
        )
        if status == 1:
            status, cmd_executed, lst_output = self.todo_upgrade_execute(
                cmd_git_clone_migrate_source_same_target_remote_only,
                get_output=True,
            )
            if lst_output:
                remote = lst_output[0].strip()
                # TODO write this modification into repo manifest
            else:
                remote = input(
                    "👹 BUG, you need to push last branch. Please write the remote/ :"
                )
        else:
            local_branch, remote, remote_branch = (
                self.get_local_branch_remote_actual_branch_git(
                    lst_output,
                )
            )
        # Get remote branch for next version
        remote_branch_target = f"{remote}/{branch_target}"
        cmd_git_clone_migrate_source_same_target = (
            f"cd {source_addons_path} "
            f"&& git fetch --all "
            f'&& git branch --remotes -vv | grep "{remote_branch_target} " '
            f"&& cd ~-"
        )
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            cmd_git_clone_migrate_source_same_target,
            get_output=True,
            wait_at_error=False,
        )
        has_existing_target_branch = any([a.strip() for a in lst_output])

        # TODO check config if path is added
        # Get remote branch address
        cmd_remote_address = (
            f"cd {source_addons_path} "
            f"&& git remote get-url {remote} "
            f"&& cd ~-"
        )
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            cmd_remote_address,
            get_output=True,
        )

        remote_address = lst_output[0].strip()

        # TODO some time, the clone has error, need to repeat
        branch_to_clone = (
            branch_target if has_existing_target_branch else branch_source
        )

        cmd_git_clone = (
            f"cd {os.path.dirname(target_addons_path)} "
            f"&& git clone {remote_address} {source_dir_name} -b {branch_to_clone} && cd ~-"
        )
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            cmd_git_clone,
            get_output=True,
        )
        if not has_existing_target_branch:
            cmd_git_clone = (
                f"cd {target_addons_path} "
                f"&& if git rev-parse --verify --quiet refs/heads/{branch_target}; then "
                f"git checkout {branch_target}; else git checkout -b {branch_target}; fi "
                f"&& cd ~-"
            )
            status, cmd_executed, lst_output = self.todo_upgrade_execute(
                cmd_git_clone,
                get_output=True,
            )

    def get_branch_name_from_local_manifest(self, addons_path, default_branch):
        relative_addons_path = addons_path.replace(os.getcwd() + "/", "")
        git_tool = GitTool()
        dct_remote, dct_project, default_remote = (
            git_tool.get_manifest_xml_info(filename=LOCAL_MANIFEST)
        )
        for dct_repo in dct_project.values():
            path = dct_repo.get("@path")
            if path == relative_addons_path:
                revision = dct_repo.get("@revision")
                return revision
        return default_branch

    def get_local_branch_remote_actual_branch_git(self, lst_output):
        for line in lst_output:
            # The current branch is marked with an asterisk (*) at the start of the line
            if not line.strip().startswith("*"):
                continue
            # Split the line to isolate the remote and remote branch name
            parts = line.split()
            if len(parts) >= 4:
                # The remote and remote branch are in the 4th part, e.g., '[origin/main]'
                remote_info = parts[3].strip("[]")
                # Split 'origin/main' into 'origin' and 'main'
                # remote, remote_branch = remote_info.split("/", 1)
                try:
                    remote, remote_branch = remote_info.split("/", 1)
                except ValueError as e:
                    # # TODO this means no remote, take default one? or last one?
                    # # TODO supporter la migration 17 vers 18
                    # print("👹 BUG, you need to push ")
                    # TODO search remote and associate branch
                    value = input(
                        "👹 BUG, you need to push last branch. Please write the remote/branch_name :"
                    )
                    remote, remote_branch = value.split("/", 1)
                return parts[1], remote, remote_branch
        return None, None, None

    MAX_EVENT = 200

    # Le nom de fichier d'une étape est calculé PAR L'ÉCRAN D'ÉTAT, et
    # importé ici. Deux formules dériveraient, et l'écran chercherait alors
    # un fichier que personne n'écrit — sans rien signaler, puisqu'un
    # fichier absent se lit comme une étape sans journal.
    step_slug = staticmethod(migration_status.step_slug)

    def log_dir(self):
        """Où vivent les journaux de CETTE migration. Créé à la demande.

        Sous le nom de la base, comme les archives et les instantanés COW :
        deux migrations menées de front ne doivent pas écrire dans le même
        fichier, et l'on veut pouvoir tout emporter d'un seul répertoire.
        """
        database = (getattr(self, "dct_progression", None) or {}).get(
            "config_database_name"
        ) or "sans-nom"
        chemin = os.path.join(PATH_MIGRATION_PRIVATE, database, STEP_LOG_DIR)
        try:
            os.makedirs(chemin, exist_ok=True)
        except OSError:
            return None
        if database != UNNAMED_MIGRATION:
            self.adopt_unnamed_logs(chemin)
        return chemin

    def adopt_unnamed_logs(self, chemin):
        """Rapatrier les journaux écrits AVANT que la base ne soit nommée.

        Les deux premières étapes — inspecter l'archive, la restaurer —
        tournent avant qu'on ait choisi le nom de la base. Leurs journaux
        atterrissaient donc sous « sans-nom », c'est-à-dire hors de la
        migration à laquelle ils appartiennent : mesuré, deux fichiers
        invisibles depuis l'écran d'état, et l'on cherchait des logs
        manquants qui étaient simplement à côté.

        En AJOUT si le fichier existe déjà : une reprise peut avoir écrit
        des deux côtés, et écraser perdrait le premier passage.
        """
        if getattr(self, "_unnamed_adopted", False):
            return
        self._unnamed_adopted = True
        source = os.path.join(
            PATH_MIGRATION_PRIVATE, UNNAMED_MIGRATION, STEP_LOG_DIR
        )
        if not os.path.isdir(source) or os.path.abspath(
            source
        ) == os.path.abspath(chemin):
            return
        for nom in sorted(os.listdir(source)):
            depart = os.path.join(source, nom)
            arrivee = os.path.join(chemin, nom)
            if not os.path.isfile(depart):
                continue
            try:
                with open(
                    depart, "r", encoding="utf-8", errors="replace"
                ) as f:
                    contenu = f.read()
                with open(arrivee, "a", encoding="utf-8") as f:
                    f.write(contenu)
                os.remove(depart)
            except OSError:
                continue
        try:
            os.rmdir(source)
        except OSError:
            pass

    def open_step_log(self, msg):
        """Rediriger la sortie des commandes vers le journal de cette étape.

        En AJOUT, jamais en écrasement : une étape rejouée après un retour
        en arrière doit s'ajouter à ce qu'on savait d'elle, pas l'effacer.
        C'est précisément l'historique qu'on vient relire.
        """
        self.close_step_log()
        chemin = self.log_dir()
        if not chemin:
            return
        fichier = os.path.join(chemin, f"{self.step_slug(msg)}.log")
        try:
            handle = open(fichier, "a", encoding="utf-8", buffering=1)
        except OSError:
            return
        handle.write(f"\n===== {datetime.datetime.now()} — {msg} =====\n")
        self.step_log = handle
        if getattr(self, "execute", None) is not None:
            self.execute.log_sink = handle

    def close_step_log(self):
        handle = getattr(self, "step_log", None)
        if handle:
            try:
                handle.close()
            except Exception:
                pass
        self.step_log = None
        if getattr(self, "execute", None) is not None:
            self.execute.log_sink = None

    def note_step_log(self, texte):
        """Écrire une ligne dans le journal de l'étape en cours.

        Ce qui passe par `run_on_terminal` n'a PAS de sortie capturable —
        un tube y ferait renoncer les pleins écrans, la leçon a été payée.
        On garde donc au moins la commande et son verdict.
        """
        handle = getattr(self, "step_log", None)
        if not handle:
            return
        try:
            handle.write(f"[{datetime.datetime.now()}] {texte}\n")
        except Exception:
            pass

    def record_event(self, kind, name, status, detail=""):
        """Garder ce qui s'est MAL passé, et ce que les outils ont conclu.

        Le journal existant (`command_executed`) dit ce qui a été LANCÉ,
        jamais ce que cela a donné. Après six paliers on lit deux cents
        lignes de commandes sans savoir laquelle a échoué, ni ce que le
        test de fumée a trouvé. C'est cette question-là que l'écran d'état
        doit pouvoir répondre.

        Borné : une migration lance des centaines de commandes, et un
        fichier de progression qui enfle sans limite finit par coûter plus
        cher à écrire qu'à lire.
        """
        lst = list(self.dct_progression.get("lst_event") or [])
        lst.append(
            {
                "at": str(datetime.datetime.now()),
                "step": getattr(self, "current_step", "") or "",
                "kind": kind,
                "name": name,
                "status": status,
                "detail": str(detail)[:500],
            }
        )
        self.dct_progression["lst_event"] = lst[-self.MAX_EVENT :]
        self.write_config()
        # ET sur disque, en AJOUT, hors du fichier de progression. Celui-ci
        # est archivé puis remis à zéro quand on recommence une migration :
        # tout ce qu'on y avait mis disparaissait alors de l'écran d'état,
        # au moment précis où l'on cherchait à comprendre pourquoi il avait
        # fallu recommencer.
        self.append_event_file(lst[-1])
        self.note_step_log(f"[{kind}] {name} -> {status}")

    def append_event_file(self, event):
        """Ajouter l'événement au journal permanent, une ligne de JSON.

        JSONL et non JSON : un fichier qu'on complète ligne à ligne
        survit à une interruption au milieu d'une écriture, là où un
        tableau JSON réécrit en entier ne laisserait qu'un fichier
        tronqué — donc illisible, donc perdu en totalité.
        """
        chemin = self.log_dir()
        if not chemin:
            return
        try:
            with open(
                os.path.join(chemin, EVENT_FILE), "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def run_tool(self, name, cmd):
        """Lancer un outil de migration et RETENIR sa conclusion.

        Les outils partagent une convention de code de sortie — 0 rien à
        signaler, 1 des trouvailles, 2 l'outil a échoué — et c'est
        exactement ce qu'on veut relire plus tard. Sans cela, « le test de
        fumée est-il passé ? » n'a pas de réponse une heure après.
        """
        status = self.run_on_terminal(cmd)
        self.record_event("test", name, status, cmd)
        return status

    def add_comment_progression(self, comment):
        """Marquer une étape dans le journal, et devenir CETTE étape.

        Vingt en-têtes d'étape passent par ici contre sept par
        `print_step` : toute la boucle des paliers n'utilise que celle-ci.
        Ne poser l'étape courante que dans l'autre laissait donc chaque
        verdict d'outil estampillé d'une étape périmée — et le résumé des
        tests semblait global alors qu'il aurait dû suivre les paliers.

        C'est le MÊME marqueur que `journal_by_step` découpe : une seule
        notion d'étape, posée à un seul endroit.
        """
        comment_to_add = f"# {comment}"
        self.lst_command_executed.append(comment_to_add)
        self.dct_progression["command_executed"] = self.lst_command_executed
        self.current_step = comment
        self.open_step_log(comment)
        self.write_config()
