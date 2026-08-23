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
import re
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


# Les couleurs ANSI, et le droit de s'en passer. `NO_COLOR` est une
# convention respectée par la plupart des outils : la contredire oblige à
# nettoyer une sortie à la main, ce qui est exactement ce qu'on cherchait à
# éviter en la coloriant.
ANSI = {
    "cmd": "\033[36m",  # cyan : ce qui a été LANCÉ
    "step": "\033[1;34m",  # bleu gras : les étapes
    "ok": "\033[32m",
    "warn": "\033[33m",
    "fail": "\033[31m",
    "dim": "\033[2m",
}
RESET = "\033[0m"


def supports_colour(stream=None):
    """Peut-on colorier CETTE sortie ?

    Trois refus, et chacun a coûté à quelqu'un : un fichier de journal
    truffé de codes d'échappement, un `grep` qui ne trouve plus rien, un
    terminal qui les affiche en clair. Un tube n'est pas un écran.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "") in ("", "dumb"):
        return False
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def paint(texte, couleur, actif=True):
    """Colorier, ou rendre le texte tel quel. Jamais d'à-peu-près."""
    if not actif or couleur not in ANSI:
        return texte
    return f"{ANSI[couleur]}{texte}{RESET}"


VERDICT_COLOUR = {0: "ok", 1: "warn", 2: "fail"}


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


# Le format d'une ligne de journal Odoo :
#   2026-08-19 09:21:07,074 132948 ERROR <base> odoo.tools.translate: message
# Le nom de la base en fait partie, et c'est ce qui permet de séparer six
# paliers écrits dans un même fichier — ce qui était le cas avant qu'une
# étape n'ouvre son propre journal.
RE_LOG_LINE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \d+ (\w+) (\S+) ([\w.]+): (.*)$"
)
GRAVE = ("ERROR", "CRITICAL")

_CACHE = {}


def scan_log(chemin):
    """Compter les sévérités et relever les erreurs DISTINCTES d'un journal.

    Mis en cache sur (taille, date) : l'écran se redessine à chaque touche,
    et un journal d'étape atteint treize mégaoctets — mesuré. Le relire à
    chaque frappe rendrait l'écran inutilisable.

    Les erreurs sont dédoublonnées avec leur nombre : quarante-huit fois
    « Model X has no table » est UN problème vu quarante-huit fois, pas
    quarante-huit problèmes, et la liste brute noie tout le reste.
    """
    try:
        stat = os.stat(chemin)
    except OSError:
        return {"count": {}, "errors": []}
    cle = (chemin, stat.st_size, int(stat.st_mtime))
    if cle in _CACHE:
        return _CACHE[cle]
    compte = {}
    distinct = {}
    try:
        with open(chemin, "r", encoding="utf-8", errors="replace") as handle:
            for ligne in handle:
                trouve = RE_LOG_LINE.match(ligne)
                if not trouve:
                    if ligne.startswith("Traceback"):
                        compte["TRACEBACK"] = compte.get("TRACEBACK", 0) + 1
                    continue
                niveau, base, logger, message = trouve.groups()
                compte[niveau] = compte.get(niveau, 0) + 1
                if niveau in GRAVE:
                    signature = (base, logger, message.strip()[:120])
                    distinct[signature] = distinct.get(signature, 0) + 1
    except OSError:
        return {"count": {}, "errors": []}
    resultat = {
        "count": compte,
        "errors": [
            {
                "database": base,
                "logger": logger,
                "message": message,
                "times": nombre,
            }
            for (base, logger, message), nombre in sorted(
                distinct.items(), key=lambda item: -item[1]
            )
        ],
    }
    # Un seul journal en cache : ils pèsent des mégaoctets, et l'écran ne
    # regarde qu'une étape à la fois.
    _CACHE.clear()
    _CACHE[cle] = resultat
    return resultat


def step_log_scan(dct, step):
    """Ce que le journal de cette étape contient de grave."""
    chemin = step_log_path(dct, step)
    return scan_log(chemin) if chemin else {"count": {}, "errors": []}


def severe_count(scan):
    """Combien d'ERROR et de CRITICAL, en un seul nombre."""
    return sum(scan["count"].get(niveau, 0) for niveau in GRAVE)


def step_log_tail(dct, step, lines=400):
    """Les dernières lignes du journal de cette étape, et le compte total.

    Rend (lignes, total). Le total n'est pas décoratif : une mise à jour de
    modules écrit des dizaines de milliers de lignes, et montrer les
    dernières SANS dire qu'on en cache se lit comme « il manque des logs ».
    """
    chemin = step_log_path(dct, step)
    if not chemin:
        return [], 0
    try:
        with open(chemin, "r", encoding="utf-8", errors="replace") as handle:
            lst = handle.read().splitlines()
    except OSError:
        return [], 0
    return lst[-lines:], len(lst)


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
    """Le dernier verdict de chaque outil, PAR ÉTAPE, et son nombre de passages.

    Par étape, car c'est la question qu'on pose. Une migration lance le
    test de fumée à CHAQUE palier ; regrouper sur le seul nom d'outil n'en
    laissait qu'une ligne, et l'on lisait « smoke_public_url ✅ » sans voir
    que le palier 14 était passé et le 17 tombé.

    Dans une étape, le DERNIER verdict l'emporte : un outil relancé après
    correction a deux verdicts contradictoires, et c'est le second qui
    décrit la base telle qu'elle est. Les afficher tous deux sans les
    distinguer ferait lire une réparation comme un échec persistant.

    L'ordre est celui du journal, donc celui de la migration. Trier les
    étapes par leur nom mettrait « 4.10 » avant « 4.2 ».
    """
    dernier = {}
    for item in events(dct, kind="test"):
        cle = (item.get("step") or "", item.get("name") or "?")
        entree = dernier.setdefault(
            cle, {"name": cle[1], "step": cle[0], "runs": 0}
        )
        entree["runs"] += 1
        entree["status"] = item.get("status")
        entree["at"] = item.get("at")
    return list(dernier.values())


def tests_by_step(dct):
    """Les verdicts groupés sous leur étape, dans l'ordre de la migration."""
    par_etape = {}
    for item in tests_summary(dct):
        par_etape.setdefault(item["step"], []).append(item)
    return list(par_etape.items())


def failures(dct):
    """Les commandes qui ont échoué, la plus récente d'abord."""
    return list(reversed(events(dct, kind="command")))


def elapsed(dct):
    """Combien de temps la migration a duré, ou dure encore.

    Du premier écrit à la DERNIÈRE écriture du journal : la progression est
    réécrite après chaque geste, donc sa date de mise à jour EST la fin —
    ou l'instant présent si la migration tourne toujours.

    On délègue à `migration_stats.fmt_delay`, qui porte déjà ce calcul pour
    l'écran de statistiques. Deux formules donneraient deux durées pour la
    même migration selon l'écran qu'on ouvre.
    """
    try:
        from script.todo.migration_stats import fmt_delay
    except Exception:
        return "?"
    return fmt_delay(dct.get("date_create"), dct.get("date_update"))


def overview(dct):
    """L'en-tête : de quelle migration parle-t-on."""
    return {
        "elapsed": elapsed(dct),
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


def render_text(dct, limit_cmd=12, colour=None):
    """Le rapport complet, en texte. C'est aussi le repli du plein écran.

    `colour` à None laisse la sortie décider : un écran est colorié, un
    tube ne l'est pas. Le forcer sert aux tests, qui doivent pouvoir
    vérifier les deux sans dépendre de l'endroit où ils tournent.
    """
    if colour is None:
        colour = supports_colour()
    if not dct:
        return f"ℹ️  {t('No migration in progress.')}"
    info = overview(dct)
    lignes = [
        f"📍 {t('Migration state')}",
        f"   {t('database')} : {info['database']}",
        f"   {t('image')} : {info['file']}",
        f"   {t('started')} : {info['started']}",
        f"   {t('finished')} : {info['updated']}",
        f"   {t('duration')} : {info['elapsed']}",
        f"   {t('current step')} : {info['step']}",
    ]

    lst_test = tests_summary(dct)
    lignes.append(f"\n🧪 {t('Test results')}")
    if not lst_test:
        lignes.append(f"   {t('No tool has run yet.')}")
    for etape, lst_item in tests_by_step(dct):
        lignes.append(
            f"   {paint(etape or t('before the first step'), 'step', colour)}"
        )
        for item in lst_item:
            icone, phrase = verdict(item.get("status"))
            rejeu = (
                f"  ({item['runs']} {t('runs')})"
                if item.get("runs", 1) > 1
                else ""
            )
            teinte = VERDICT_COLOUR.get(item.get("status"), "dim")
            nom = f"{item['name']:<24}"
            lignes.append(
                f"      {icone} {paint(nom, teinte, colour)} {phrase}{rejeu}"
            )

    lst_failure = failures(dct)
    lignes.append(f"\n❌ {t('Commands that failed')} : {len(lst_failure)}")
    for item in lst_failure[:10]:
        lignes.append(
            f"   · [{item.get('step') or '?'}]"
            f" {paint(item.get('name') or '', 'fail', colour)}"
        )

    lignes.append(f"\n🔷 {t('What was done, step by step')}")
    for section in journal_by_step(dct):
        lst_cmd = section["lst_cmd"]
        journal = " 📄" if step_log_path(dct, section["step"]) else ""
        scan = step_log_scan(dct, section["step"])
        graves = severe_count(scan)
        # Le nombre d'ERROR à côté de l'étape : c'est la seule façon de
        # voir d'un coup d'œil OÙ la migration a souffert, sans ouvrir
        # treize mégaoctets de journal.
        alerte = f"  {paint(f'❌ {graves}', 'fail', colour)}" if graves else ""
        lignes.append(
            f"   {paint(section['step'], 'step', colour)}"
            f"  ({len(lst_cmd)}){journal}{alerte}"
        )
        for item in scan["errors"][:3]:
            lignes.append(
                f"      ×{item['times']:<3}"
                f" {paint(item['message'][:100], 'warn', colour)}"
            )
        for cmd in lst_cmd[:limit_cmd]:
            # LA demande : distinguer d'un coup d'œil ce qui a été lancé
            # du reste du rapport. Une liste de commandes en texte plat se
            # confond avec ses titres dès qu'elle dépasse l'écran.
            lignes.append(f"      {paint(cmd[:120], 'cmd', colour)}")
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
        if run_tui and run_tui(dct, path=config.file):
            return 0
    print(render_text(dct))
    return 0


if __name__ == "__main__":
    sys.exit(main())
