#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Run the OCA « Database cleanup » purges, in order, until nothing moves.

Why a tool rather than the eight screens
----------------------------------------
A migration leaves obsolete models, columns, tables, data and menus behind.
The `database_cleanup` module offers one wizard per kind, and they are not
independent: purging a model frees the columns that referenced it, purging a
table frees the data rows pointing at it. One pass is never enough — the
order matters, and so does going round again.

Errors are expected, and are not a reason to stop
-------------------------------------------------
Some entries cannot be purged: a foreign key still holds, a record is
protected, a module refuses. Purging the whole list at once loses everything
to the first failure, so each entry is purged INSIDE ITS OWN SAVEPOINT: a
refusal rolls back that entry alone and the rest of the pass continues. What
one pass could not repair, the next may — once its neighbours are gone.

The loop stops when a full pass repairs nothing new. Whatever remains is
reported as a warning, not as a failure: a database can carry leftovers that
nothing can remove, and refusing to move on would help no one.

Exit codes: 0 nothing left, 1 leftovers remain, 2 the tool failed.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# L'ordre demandé, et il compte : purger un modèle libère les colonnes qui le
# référençaient, purger une table libère les données qui la visaient. Les
# index viennent après les purges — inutile d'indexer ce qu'on va retirer.
#
# `property` n'existe plus en 18.0 : Odoo y a remplacé ir.property par une
# colonne jsonb. On le garde dans la liste et on le saute quand il manque,
# plutôt que d'échouer sur une version où il n'a plus lieu d'être.
ORDER = [
    ("models", "cleanup.purge.wizard.model"),
    ("modules", "cleanup.purge.wizard.module"),
    ("columns", "cleanup.purge.wizard.column"),
    ("tables", "cleanup.purge.wizard.table"),
    ("data", "cleanup.purge.wizard.data"),
    ("menus", "cleanup.purge.wizard.menu"),
    ("indexes", "cleanup.create_indexes.wizard"),
    ("properties", "cleanup.purge.wizard.property"),
]

LABEL = {
    "models": "obsolete models",
    "modules": "obsolete modules",
    "columns": "obsolete columns",
    "tables": "obsolete tables",
    "data": "obsolete data entries",
    "menus": "obsolete menu entries",
    "indexes": "missing indexes",
    "properties": "obsolete properties",
}

STEP = "ERPLIBRE_CLEANUP_STEP"
START = "ERPLIBRE_CLEANUP_START"
END = "ERPLIBRE_CLEANUP_END"

SHELL_SCRIPT = """
import json

try:
    from odoo.exceptions import UserError
except Exception:
    class UserError(Exception):
        pass

ORDER = %(order)r
MAX_ROUND = %(max_round)d
DRY_RUN = %(dry_run)s

t_all = "%(all_label)s"
report = {"rounds": [], "missing": [], "failed": []}


def note(label, name, exc):
    report["failed"].append([label, name, str(exc)[:200]])


def step(label, name, index=0, total=0):
    # Dire ce qu'on fait PENDANT qu'on le fait. Sans cela l'outil se taisait
    # jusqu'au rapport final : mesuré, dix-sept minutes de silence complet
    # sur une base de 5984 modules, impossible à distinguer d'un blocage.
    detail = f" {index}/{total}" if total else ""
    print(f"%(step)s {label}{detail} {name}", flush=True)


def recover():
    # Rendre la transaction utilisable, quoi qu'il vienne de se passer.
    #
    # PAS de point de reprise ici, et c'est mesure : purge_modules.find()
    # purge lui-meme (purge_modules.py:91), et purge_columns appelle
    # cr.commit() (purge_columns.py:57). Or un COMMIT DETRUIT tous les
    # points de reprise : le notre disparaissait sous nos pieds, d'ou
    # « savepoint ... does not exist », puis tout ce qui suivait mourait
    # sur une transaction avortee. Un rollback franc remet les compteurs
    # a zero ; ce qu'on perd est borne, puisqu'on valide apres chaque
    # entree reussie.
    try:
        env.cr.rollback()
    except Exception:
        pass


try:
    for index in range(MAX_ROUND):
        this_round = []
        purged_this_round = 0
        step("pass", str(index + 1), index + 1, MAX_ROUND)
        for label, model in ORDER:
            if model not in env:
                if label not in report["missing"]:
                    report["missing"].append(label)
                continue
            ok = 0
            errors = []
            would = []
            try:
                wizard = env[model].create({})
                # Les noms sont matérialisés TOUT DE SUITE : les relire plus
                # tard relancerait une requête, et c'est là que le script
                # mourait quand la transaction avait été avortée entre-temps.
                todo = [
                    (line, line.name or str(line.id))
                    for line in wizard.purge_line_ids
                ]
            except UserError:
                # « No orphaned models found » : le module signale le VIDE
                # en levant. Le compter comme un échec faisait passer une
                # base saine pour cassée.
                recover()
                this_round.append({"kind": label, "purged": 0,
                                   "errors": [], "would": []})
                continue
            except Exception as exc:
                recover()
                note(label, "-", exc)
                continue
            # find() peut avoir purgé de lui-même : on garde ce qu'il a fait.
            if not DRY_RUN:
                try:
                    env.cr.commit()
                except Exception:
                    recover()
            if DRY_RUN:
                would = [name for _line, name in todo]
            elif todo:
                # LE LOT D'ABORD, et ce n'est pas une optimisation de
                # confort. `purge()` d'un module appelle
                # button_immediate_uninstall(), qui RECHARGE LE REGISTRE
                # ENTIER — 5984 modules à relire. En purgeant ligne par
                # ligne j'en faisais un rechargement PAR MODULE : mesuré,
                # dix secondes chacun, dix-sept minutes pour neuf modules.
                # Le module OCA purge le lot en un seul appel, donc un seul
                # rechargement.
                #
                # L'isolement ligne à ligne garde tout son sens — un refus
                # ne doit pas emporter la catégorie — mais il ne coûte que
                # lorsqu'il sert vraiment, c'est-à-dire après un échec.
                step(label, t_all, 0, len(todo))
                try:
                    wizard.purge_line_ids.purge()
                    env.cr.commit()
                    ok = len(todo)
                except Exception:
                    recover()
                    for index, (line, name) in enumerate(todo, start=1):
                        step(label, name, index, len(todo))
                        try:
                            line.purge()
                            # Valider ENTRÉE PAR ENTRÉE : un refus plus loin
                            # ne doit pas emporter ce qui vient d'être
                            # réparé.
                            env.cr.commit()
                            ok += 1
                        except Exception as exc:
                            recover()
                            errors.append([name, str(exc)[:160]])
            purged_this_round += ok
            this_round.append({"kind": label, "purged": ok,
                               "errors": errors, "would": would})
        report["rounds"].append(this_round)
        # On s'arrête quand une passe ENTIÈRE n'a plus rien réparé : ce qui
        # résistait au tour d'avant résistera encore. En simulation, une
        # seule passe suffit — rien ne change, donc rien ne se libère.
        if purged_this_round == 0 or DRY_RUN:
            break
except Exception as exc:
    # Le rapport de CE QUI A ÉTÉ FAIT vaut plus que la trace de ce qui a
    # cassé : sans lui, on ne sait même pas si la base a été touchée.
    note("*", "fatal", exc)

if DRY_RUN:
    # Une simulation qui écrit n'est pas une simulation. Et celle-ci
    # écrivait : purge_modules.find() purge de lui-meme, avant meme
    # qu'on ait rien decide. On defait tout ce que la lecture a
    # provoque — c'est possible ici, justement parce qu'on n'a valide
    # aucune entree.
    recover()

print("%(start)s")
print(json.dumps(report))
print("%(end)s")
"""


def build_script(max_round, dry_run):
    return SHELL_SCRIPT % {
        "order": ORDER,
        "max_round": max_round,
        "dry_run": "True" if dry_run else "False",
        "start": START,
        "end": END,
        "step": STEP,
        "all_label": "the whole batch",
    }


def checkout_version():
    """La version d'Odoo que le checkout servira, d'après .odoo-version."""
    try:
        with open(".odoo-version", "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def database_version(database):
    """La version que la BASE dit être la sienne, via le module `base`."""
    env = os.environ.copy()
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    env["PSQLRC"] = ""
    done = subprocess.run(
        [
            "psql",
            "-X",
            "-w",
            "-d",
            database,
            "-tAc",
            "SELECT latest_version FROM ir_module_module WHERE name='base';",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        return None
    parts = done.stdout.strip().split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else None


def require_matching_version(database):
    """Refuser d'ouvrir une base avec un Odoo d'une autre version.

    Un Odoo plus ancien qui charge une base plus récente ne se contente pas
    d'échouer : il ÉCRIT en chemin — mesuré, un shell en 14.0 lancé sur une
    base 17.0 est parti réécrire ir_model avant de mourir sur un jsonb qu'il
    ne connaissait pas. Le checkout suit la migration, et rien ne garantit
    qu'il soit resté sur la version de la base qu'on veut nettoyer.
    """
    checkout = checkout_version()
    database_side = database_version(database)
    if not checkout or not database_side:
        return None  # Rien pour trancher : ne pas bloquer sur une supposition.
    if checkout != database_side:
        return (
            f"{t('The checkout is on Odoo')} {checkout}"
            f" {t('and the database on')} {database_side}."
            f"\n   {t('Opening it with the wrong version writes to it before')}"
            f" {t('failing. Switch the checkout first.')}"
        )
    return None


def module_state(database, module="database_cleanup"):
    """L'état du module dans cette base, ou None si on ne peut pas lire."""
    env = os.environ.copy()
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    env["PSQLRC"] = ""
    done = subprocess.run(
        [
            "psql",
            "-X",
            "-w",
            "-d",
            database,
            "-tAc",
            f"SELECT state FROM ir_module_module WHERE name='{module}';",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        return None
    return done.stdout.strip() or None


def install_module(database, module="database_cleanup", timeout=1800):
    """Poser le module avant de s'en servir.

    Sans lui, aucun assistant n'existe et l'outil rend « rien à faire » sur
    une base qui en aurait eu besoin — un silence qu'on prend pour un
    succès. La migration l'installait plus tard, à l'étape 3 ; l'attendre
    revenait à nettoyer trop tard.
    """
    done = subprocess.run(
        ["./script/addons/install_addons.sh", database, module],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return done.returncode, done.stdout + done.stderr


def kill_group(process):
    """Tuer le GROUPE : « ./odoo_bin.sh » est un script bash.

    Un terminate() sur lui tue le script et laisse odoo-bin vivant, sur la
    base, avec ses verrous. La leçon a déjà été payée une fois par six
    serveurs orphelins.
    """
    try:
        group = os.getpgid(process.pid)
    except OSError:
        group = None
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        if group is None:
            break
        try:
            os.killpg(group, signal_number)
        except OSError:
            break
        try:
            process.wait(timeout=20)
            return
        except subprocess.TimeoutExpired:
            continue


def run_shell(database, config_path, script, timeout=3600, echo=None):
    """Pousser le script dans « odoo-bin shell » et rendre son rapport.

    On LIT au fil de l'eau plutôt que de tout capturer : ce nettoyage dure
    des minutes — dix-sept, mesurées, sur une base de 5984 modules — et la
    version précédente n'affichait rien avant la fin. Un travail qui avance
    et un blocage se ressemblent alors trait pour trait, et c'est ainsi
    qu'on interrompt une réparation à moitié faite.

    Les journaux d'Odoo se mêlent à la sortie, d'où les sentinelles : on ne
    lit comme rapport que ce qui est entre elles. Leur absence est une
    erreur franche, pas un rapport vide qu'on prendrait pour « rien à
    faire ».
    """
    process = subprocess.Popen(
        [
            "./odoo_bin.sh",
            "shell",
            "-c",
            config_path,
            "-d",
            database,
            "--log-level=warn",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    # Le délai ne peut pas vivre dans la boucle de lecture : celle-ci BLOQUE
    # tant qu'aucune ligne n'arrive, et c'est exactement le cas qu'il faut
    # couvrir. Un minuteur à part, donc.
    expire = {"fired": False}

    def couper():
        expire["fired"] = True
        kill_group(process)

    minuteur = threading.Timer(timeout, couper)
    minuteur.daemon = True
    minuteur.start()
    lst_line = []
    try:
        process.stdin.write(script)
        process.stdin.close()
        for line in process.stdout:
            lst_line.append(line)
            if echo and line.startswith(STEP):
                echo(line[len(STEP) :].strip())
        process.wait()
    finally:
        minuteur.cancel()
        if process.poll() is None:
            kill_group(process)
    output = "".join(lst_line)
    if expire["fired"]:
        raise RuntimeError(
            f"{t('The cleanup was still running after')} {timeout}"
            f" {t('seconds and was stopped.')}"
        )
    if START not in output or END not in output:
        raise RuntimeError(
            f"{t('The cleanup produced no report.')}\n{output.strip()[-1500:]}"
        )
    body = output.split(START, 1)[1].split(END, 1)[0].strip()
    try:
        return json.loads(body)
    except ValueError as exc:
        raise RuntimeError(f"{t('Unreadable report')} : {exc}")


def make_echo(depart):
    """Relayer la progression du script poussé, horodatée.

    Le temps écoulé n'est pas décoratif : c'est lui qui distingue « ça
    avance lentement » de « ça ne bouge plus », et c'est précisément la
    question qu'on se pose devant un écran muet.
    """

    def echo(ligne):
        morceaux = ligne.split(" ", 1)
        etiquette = morceaux[0]
        reste = morceaux[1] if len(morceaux) > 1 else ""
        secondes = int(time.monotonic() - depart)
        if etiquette == "pass":
            print(f"   [{secondes:>4}s] {t('pass')} {reste}")
        else:
            print(
                f"   [{secondes:>4}s] {t(LABEL.get(etiquette, etiquette))}"
                f" — {t(reste) if reste == 'the whole batch' else reste}"
            )

    return echo


def leftovers(report):
    """[(kind, name, message)] de ce que la DERNIÈRE passe n'a pas pu purger."""
    if not report.get("rounds"):
        return []
    lst = []
    for entry in report["rounds"][-1]:
        for name, message in entry.get("errors", []):
            lst.append((entry["kind"], name, message))
    for kind, name, message in report.get("failed", []):
        lst.append((kind, name, message))
    return lst


def render(report, database):
    lines = [f"🧹 {t('Database cleanup on')} '{database}'"]
    # La simulation ne répare rien : la présenter comme un échec ferait
    # croire à 585 refus là où il n'y a que 585 candidats.
    lst_would = [
        (entry["kind"], name)
        for this_round in report.get("rounds", [])
        for entry in this_round
        for name in entry.get("would", [])
    ]
    if lst_would:
        lines.append(
            f"ℹ {len(lst_would)} {t('entries would be purged')}"
            f" ({t('nothing was changed')}) :"
        )
        by_kind = {}
        for kind, _name in lst_would:
            by_kind[kind] = by_kind.get(kind, 0) + 1
        for kind, count in by_kind.items():
            lines.append(f"   - {t(LABEL.get(kind, kind))} : {count}")
        # Les échecs comptent AUSSI en simulation : une catégorie qui ne
        # s'ouvre même pas est une information, pas un silence.
        for kind, name, message in report.get("failed", []):
            lines.append(f"   ⚠ [{kind}] {name} : {message[:90]}")
        for kind in report.get("missing", []):
            lines.append(
                f"   ℹ {t(LABEL.get(kind, kind))} :"
                f" {t('no such wizard in this version, skipped.')}"
            )
        return "\n".join(lines) + "\n"
    total = 0
    for index, this_round in enumerate(report.get("rounds", []), start=1):
        purged = sum(entry["purged"] for entry in this_round)
        total += purged
        detail = ", ".join(
            f"{t(LABEL[entry['kind']])} {entry['purged']}"
            for entry in this_round
            if entry["purged"]
        )
        lines.append(
            f"   {t('pass')} {index} : {purged} {t('purged')}"
            + (f" — {detail}" if detail else "")
        )
    for kind in report.get("missing", []):
        lines.append(
            f"   ℹ {t(LABEL.get(kind, kind))} :"
            f" {t('no such wizard in this version, skipped.')}"
        )
    lst_left = leftovers(report)
    if not lst_left:
        lines.append(f"✅ -> {total} {t('entries purged, nothing left.')}")
        return "\n".join(lines) + "\n"
    lines.append(
        f"⚠️ {total} {t('purged;')} {len(lst_left)}"
        f" {t('could not be, and are left as they are')} :"
    )
    for kind, name, message in lst_left[:20]:
        lines.append(f"   - [{kind}] {name} : {message[:90]}")
    if len(lst_left) > 20:
        lines.append(f"   … {len(lst_left) - 20} {t('more')}")
    lines.append(
        f"   {t('A database can carry leftovers nothing can remove.')}"
        f" {t('This is a warning, not a failure.')}"
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the OCA database_cleanup purges in order, repeating until"
            " a full pass repairs nothing new."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", default="./config.conf")
    parser.add_argument(
        "--max-round",
        type=int,
        default=10,
        help="how many full passes at most (default 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be purged, purge nothing",
    )
    parser.add_argument("--timeout", type=int, default=3600)
    config = parser.parse_args(argv)

    mismatch = require_matching_version(config.database)
    if mismatch:
        print(f"⛔ {mismatch}")
        return 2

    state = module_state(config.database)
    if state != "installed":
        print(
            f"⧖ {t('database_cleanup is not installed on this base;')}"
            f" {t('installing it first.')}"
        )
        code, output = install_module(config.database)
        if code:
            print(output.strip()[-1500:])
            print(f"❌ {t('Could not install database_cleanup.')}")
            return 2

    print(f"⧖ {t('Cleaning')} '{config.database}'…")
    print(
        f"   {t('Purging modules reloads the whole registry: on a big')}"
        f" {t('addons path this takes minutes, not seconds.')}"
    )
    depart = time.monotonic()
    try:
        report = run_shell(
            config.database,
            config.config,
            build_script(config.max_round, config.dry_run),
            timeout=config.timeout,
            echo=make_echo(depart),
        )
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print(f"❌ {exc}")
        return 2
    print(render(report, config.database))
    print(f"⌛ {t('Took')} {int(time.monotonic() - depart)} {t('seconds.')}")
    return 1 if leftovers(report) else 0


if __name__ == "__main__":
    sys.exit(main())
