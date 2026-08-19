#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Où en est cette migration, et qu'est-ce qui a mal tourné.

Une migration traverse six paliers, lance des centaines de commandes et
dure des heures. Le journal existant dit ce qui a été LANCÉ ; il ne dit
jamais ce que cela a donné. Après trois heures on relit deux cents lignes
de commandes sans savoir laquelle a échoué, ni ce que le test de fumée a
conclu, ni à quelle étape on se trouve.

Ce module assemble la réponse à partir du fichier de progression — le
même que la migration écrit après chaque geste — et la rend en texte. Le
plein écran, lui, n'est qu'une autre vue de CES données : deux rendus
séparés dériveraient l'un de l'autre sans que rien ne le signale.

Rien n'est lu ailleurs que dans ce fichier : l'écran d'état ne doit jamais
toucher une base ni lancer un serveur. On l'ouvre en pleine migration.
"""

import json
import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


DEFAULT_PATH = ".venv.erplibre/odoo_database_migration_log.json"
PATH_MIGRATION_PRIVATE = os.path.join("private", "odoo", "migration")
STEP_LOG_DIR = "step_log"
EVENT_FILE = "events.jsonl"

# Les codes de sortie que TOUS les outils de migration partagent. Les
# traduire ici plutôt qu'à l'affichage évite qu'un « 1 » passe pour une
# panne alors qu'il annonce des trouvailles.
VERDICT = {
    0: ("✅", "nothing to report"),
    1: ("⚠️", "findings to look at"),
    2: ("❌", "the tool itself failed"),
}


def read(path=DEFAULT_PATH):
    """La progression, complétée par ce qui a été écrit SUR DISQUE.

    Le fichier de progression est archivé puis remis à zéro quand on
    recommence une migration : tout ce qu'il contenait disparaissait alors
    de cet écran. Le journal permanent, lui, ne fait que s'allonger — et
    c'est justement en revenant après une interruption qu'on a besoin de
    ce qui s'est passé avant.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            dct = json.load(handle)
    except (OSError, ValueError):
        return {}
    dct["lst_event"] = merge_events(dct)
    return dct


def log_dir(dct):
    """Le répertoire des journaux de cette migration, ou None."""
    database = (dct or {}).get("config_database_name")
    if not database:
        return None
    chemin = os.path.join(PATH_MIGRATION_PRIVATE, database, STEP_LOG_DIR)
    return chemin if os.path.isdir(chemin) else None


def read_event_file(dct):
    """Les événements du journal permanent, en ignorant les lignes cassées.

    Une écriture interrompue laisse une ligne tronquée ; la refuser en bloc
    perdrait tout le reste du fichier pour une seule ligne.
    """
    chemin = log_dir(dct)
    if not chemin:
        return []
    lst = []
    try:
        with open(
            os.path.join(chemin, EVENT_FILE), "r", encoding="utf-8"
        ) as handle:
            for ligne in handle:
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    lst.append(json.loads(ligne))
                except ValueError:
                    continue
    except OSError:
        return []
    return lst


def merge_events(dct):
    """Le disque d'abord, la mémoire ensuite, sans doublon.

    Les deux sources se recouvrent : ce qui vient d'être enregistré est aux
    deux endroits. On dédoublonne sur (horodatage, nom, type) — trois
    champs qu'un même événement porte à l'identique dans les deux.
    """
    vus = set()
    fusion = []
    for item in read_event_file(dct) + list(dct.get("lst_event") or []):
        cle = (item.get("at"), item.get("name"), item.get("kind"))
        if cle in vus:
            continue
        vus.add(cle)
        fusion.append(item)
    return fusion


def step_log_path(dct, step):
    """Le fichier de journal d'une étape, s'il existe."""
    chemin = log_dir(dct)
    if not chemin or not step:
        return None
    fichier = os.path.join(chemin, f"{step_slug(step)}.log")
    return fichier if os.path.isfile(fichier) else None


def step_slug(msg):
    """Le même nom que celui écrit par la migration. Un seul calcul.

    Deux formules séparées dériveraient, et l'écran chercherait alors un
    fichier que personne n'écrit — sans rien signaler, puisqu'un fichier
    absent se lit comme une étape sans journal.
    """
    import re

    prefix, sep, label = (msg or "").partition(" - ")
    propre = re.sub(r"[^A-Za-z0-9._-]+", "-", (label or prefix)).strip("-")
    tete = re.sub(r"[^A-Za-z0-9._-]+", "-", prefix).strip("-") if sep else ""
    nom = f"{tete}_{propre}" if tete else propre
    return (nom or "step")[:80].lower()


def step_log_tail(dct, step, lines=200):
    """Les dernières lignes du journal de cette étape."""
    chemin = step_log_path(dct, step)
    if not chemin:
        return []
    try:
        with open(chemin, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()[-lines:]
    except OSError:
        return []


def journal_by_step(dct):
    """Le journal découpé par étape, dans l'ordre.

    Les entrées commençant par « # » sont les en-têtes d'étape que la
    migration y dépose elle-même ; tout ce qui suit appartient à l'étape
    ouverte. On réutilise donc un marquage qui existe déjà plutôt que d'en
    inventer un second, qui divergerait.
    """
    lst_section = []
    courante = None
    for entry in dct.get("command_executed") or []:
        texte = str(entry)
        if texte.startswith("#"):
            courante = {"step": texte.lstrip("# ").strip(), "lst_cmd": []}
            lst_section.append(courante)
            continue
        if courante is None:
            courante = {"step": t("before the first step"), "lst_cmd": []}
            lst_section.append(courante)
        courante["lst_cmd"].append(texte)
    return lst_section


def events(dct, kind=None):
    """Ce qui a mal tourné, et ce que les outils ont conclu."""
    lst = [
        item
        for item in (dct.get("lst_event") or [])
        if kind is None or item.get("kind") == kind
    ]
    return lst


def verdict(status):
    """(icône, phrase) pour un code de sortie d'outil."""
    icone, phrase = VERDICT.get(status, ("❔", "unknown result"))
    return icone, t(phrase)


def tests_summary(dct):
    """Le DERNIER verdict de chaque outil, et le compte des passages.

    Un outil relancé après correction a deux verdicts contradictoires dans
    le journal, et c'est le dernier qui décrit la base telle qu'elle est.
    Afficher les deux sans les distinguer ferait lire une réparation comme
    un échec persistant.
    """
    dernier = {}
    for item in events(dct, kind="test"):
        nom = item.get("name") or "?"
        entree = dernier.setdefault(nom, {"name": nom, "runs": 0})
        entree["runs"] += 1
        entree["status"] = item.get("status")
        entree["at"] = item.get("at")
        entree["step"] = item.get("step")
    return [dernier[nom] for nom in sorted(dernier)]


def failures(dct):
    """Les commandes qui ont échoué, la plus récente d'abord."""
    return list(reversed(events(dct, kind="command")))


def overview(dct):
    """L'en-tête : de quelle migration parle-t-on."""
    return {
        "file": os.path.basename(dct.get("migration_file") or "?"),
        "database": dct.get("config_database_name") or "?",
        "target": dct.get("target_odoo_version") or "?",
        "started": dct.get("date_create") or "?",
        "updated": dct.get("date_update") or "?",
        "step": (
            (dct.get("lst_event") or [{}])[-1].get("step")
            or _last_step(dct)
            or "?"
        ),
    }


def _last_step(dct):
    lst = journal_by_step(dct)
    return lst[-1]["step"] if lst else None


def bumps(dct):
    """Les paliers, et lesquels sont faits."""
    done = dct.get("state_4_upgrade_odoo_lst") or []
    lst = dct.get("lst_version_bump") or []
    if not lst:
        # Le nom des bases de palier porte la version : c'est la seule
        # source disponible quand la liste n'a pas été écrite.
        lst = list(range(len(done)))
    return [
        {"version": version, "done": bool(i < len(done) and done[i])}
        for i, version in enumerate(lst)
    ]


def render_text(dct, limit_cmd=12):
    """Le rapport complet, en texte. C'est aussi le repli du plein écran."""
    if not dct:
        return f"ℹ️  {t('No migration in progress.')}"
    info = overview(dct)
    lignes = [
        f"📍 {t('Migration state')}",
        f"   {t('database')} : {info['database']}",
        f"   {t('image')} : {info['file']}",
        f"   {t('started')} : {info['started']}",
        f"   {t('last written')} : {info['updated']}",
        f"   {t('current step')} : {info['step']}",
    ]

    lst_test = tests_summary(dct)
    lignes.append(f"\n🧪 {t('Test results')}")
    if not lst_test:
        lignes.append(f"   {t('No tool has run yet.')}")
    for item in lst_test:
        icone, phrase = verdict(item.get("status"))
        rejeu = (
            f"  ({item['runs']} {t('runs')})"
            if item.get("runs", 1) > 1
            else ""
        )
        lignes.append(f"   {icone} {item['name']:<24} {phrase}{rejeu}")

    lst_failure = failures(dct)
    lignes.append(f"\n❌ {t('Commands that failed')} : {len(lst_failure)}")
    for item in lst_failure[:10]:
        lignes.append(f"   · [{item.get('step') or '?'}] {item.get('name')}")

    lignes.append(f"\n🔷 {t('What was done, step by step')}")
    for section in journal_by_step(dct):
        lst_cmd = section["lst_cmd"]
        journal = " 📄" if step_log_path(dct, section["step"]) else ""
        lignes.append(f"   {section['step']}  ({len(lst_cmd)}){journal}")
        for cmd in lst_cmd[:limit_cmd]:
            lignes.append(f"      {cmd[:120]}")
        if len(lst_cmd) > limit_cmd:
            reste = len(lst_cmd) - limit_cmd
            lignes.append(f"      … {reste} {t('more')}")
    return "\n".join(lignes)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description="Show what this migration has done, and what failed."
    )
    parser.add_argument("-f", "--file", default=DEFAULT_PATH)
    parser.add_argument(
        "--text",
        action="store_true",
        help="print the report instead of opening the full screen",
    )
    config = parser.parse_args(argv)
    dct = read(config.file)
    if not config.text:
        try:
            from script.todo.migration_status_tui import run_tui
        except Exception:
            run_tui = None
        if run_tui and run_tui(dct):
            return 0
    print(render_text(dct))
    return 0


if __name__ == "__main__":
    sys.exit(main())
