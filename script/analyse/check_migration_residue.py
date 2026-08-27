#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'une migration a laissé derrière elle, lu dans UNE seule base.

`check_migration_quality` répond à une autre question : il compare les
bases de PALIER qu'une migration locale a laissées, et il lui faut le
journal de progression. Devant la sauvegarde d'un client, ni l'une ni
l'autre n'existe. Il fallait donc un outil qui n'ait besoin que de la
base qu'on a sous la main.

Le piège, et pourquoi la moitié des contrôles évidents ont été écartés
--------------------------------------------------------------------
Un compteur absolu ne prouve rien. Mesuré sur une chaîne 12 → 18 réelle,
en comparant la base d'ORIGINE à la migrée :

    champs stockés sans colonne      25 → 72     ← 25 AVANT toute migration
    modèles sans table               90 → 158    ← 90 AVANT
    contraintes orphelines          155 → 530    ← 155 AVANT

Ces trois-là paraissent accablants et ne le sont pas : un modèle abstrait
n'a jamais de table, un champ hérité n'a jamais sa colonne à lui. Affichés
bruts, ils font peur pour rien — et un rapport qui fait peur pour rien
finit par être ignoré en entier.

Ne restent ici que les constats qui se jugent SANS point de comparaison,
parce qu'ils sont faux en eux-mêmes. Les mêmes bases, mêmes mesures :

    ir_model_relation sans table      0 → 68     la table m2m est nommée,
                                                 elle n'existe pas
    index doublés convention 17       0 → 414    Odoo 17 renomme, sans
                                                 supprimer l'ancien
    liste de prix par défaut absente  0 → 1      `product` installé, son
                                                 xmlid pas là

Zéro avant, non nul après : aucun de ceux-là ne peut s'expliquer
autrement que par la migration.

« Zéro avant, non nul après » ne suffit pourtant pas
----------------------------------------------------
Un quatrième contrôle a vécu ici et n'y est plus : `res_lang.active` à
NULL, 0 avant et 9 après. Le chiffre était juste, la conclusion fausse.

Mesuré palier par palier : 0, 1, 2, 3, 5, 8, 9 — les NULL arrivent avec
les langues que CHAQUE version ajoute au catalogue. Et c'est Odoo
lui-même qui les écrit : `active = fields.Boolean()` sans défaut
(res_lang.py:64) et un `res.lang.csv` sans colonne `active` — l'INSERT ne
porte pas la colonne, PostgreSQL y met NULL.

Aucune conséquence, vérifiée dans la source de la 18 : un domaine
`('active','=',False)` compile en `(IS NULL OR = FALSE)`
(models.py:3217-3222), l'action du menu Langues porte `active_test: False`
(res_lang_views.xml:136), le tri passe par `COALESCE(active, FALSE)`
(models.py:5692) et la lecture rend `bool(value)` (fields.py:1515). NULL
et FALSE sont indiscernables partout.

La leçon : la croissance mesurée doit AUSSI être inexplicable autrement.
Ici elle s'expliquait très bien.

Un quatrième a été RETIRÉ après vérification
--------------------------------------------
« ir_model_relation nomme une table absente » : 0 avant, 68 après, le
profil idéal. Et sans la moindre conséquence. Son unique consommateur,
`_module_data_uninstall` dans `base/models/ir_model.py`, teste
`sql.table_exists(...)` AVANT de supprimer : la ligne périmée est
ignorée, puis effacée. Les 68 appartiennent en outre à des modules
INSTALLÉS, que `database_cleanup` ne touche pas — la réparation que ce
fichier désignait n'en aurait réparé aucune.

Un constat sans conséquence et sans geste possible est du bruit, quelle
que soit la netteté du signal. Il est parti.

Chaque constat nomme l'outil qui le répare. Un rapport qui montre un
dégât sans dire quoi lancer oblige à chercher, et on ne cherche pas.

Lecture seule : `default_transaction_read_only=on`, imposé par le serveur.
"""

from __future__ import annotations

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


from script.analyse import check_migration_quality as quality  # noqa: E402
from script.analyse import lib_analyse  # noqa: E402
from script.todo import migration_status as status  # noqa: E402

COULEURS = {
    "broken": "\033[31m",
    "step": "\033[36m",
    "watch": "\033[33m",
    "ok": "\033[32m",
    "dim": "\033[90m",
}
RESET = "\033[0m"


def paint(texte, genre, colour):
    """Teinter, ou rendre le texte tel quel quand la couleur est coupée."""
    if not colour:
        return texte
    return f"{COULEURS.get(genre, '')}{texte}{RESET}"


# `sql` doit rendre UN nombre. `repair` nomme l'outil qui corrige, ou None
# quand il n'y en a pas encore — le dire vaut mieux que de laisser croire.
CONTROLES = (
    {
        "key": "stuck_modules",
        "title": "Modules stuck between two states",
        "why": "A migration that stopped mid-flight leaves them there;"
        " Odoo will retry the transition at every start.",
        "sql": "SELECT count(*) FROM ir_module_module"
        " WHERE state IN ('to install','to upgrade','to remove')",
        "gravity": "broken",
        "repair": "script/todo/todo_upgrade.py (uninstall_one_by_one)",
    },
    {
        "key": "duplicate_index",
        "title": "Indexes duplicated by the Odoo 17 renaming",
        "why": "Odoo 17 changed the naming convention without dropping the"
        " old index: both are maintained on every write. This count is a"
        " cheap signal — the repair tool compares columns and"
        " uniqueness, and is the one to trust.",
        "sql": "SELECT count(*) FROM pg_indexes a WHERE a.schemaname='public'"
        " AND a.indexname ~ '__[a-z0-9_]+_index$'"
        " AND EXISTS (SELECT 1 FROM pg_indexes b WHERE b.schemaname='public'"
        " AND b.tablename = a.tablename"
        " AND b.indexname = replace(a.indexname, '__', '_'))",
        "gravity": "watch",
        "repair": "script/odoo/migration/fix_duplicate_index.py --apply",
    },
    {
        "key": "missing_pricelist",
        "title": "Default pricelist missing while product is installed",
        "why": "product.list0 was declared up to Odoo 16 only; nothing"
        " recreates it, and a quotation has no price list to pick.",
        # On cherche une LISTE, pas son xmlid. Mesuré : la réparation
        # laisse Odoo créer « Par défaut » sans poser `product.list0` —
        # chercher l'xmlid signalait donc une base parfaitement saine, et
        # aurait signalé de même celle d'un client qui a créé la sienne à
        # la main.
        #
        # Et seulement si la FONCTIONNALITÉ est active, c'est-à-dire si
        # `base.group_user` implique `product.group_product_pricelist` —
        # la question exacte que pose la case des réglages. Sans elle,
        # l'absence de liste est normale ; signaler quand même menait à
        # créer une liste dans une base qui n'en veut pas, et Odoo
        # prévenait alors à chaque ouverture des réglages qu'il allait
        # l'archiver.
        "sql": "SELECT CASE WHEN EXISTS (SELECT 1 FROM ir_module_module"
        " WHERE name='product' AND state='installed')"
        " AND to_regclass('public.product_pricelist') IS NOT NULL"
        " AND EXISTS (SELECT 1 FROM res_groups_implied_rel r"
        " JOIN ir_model_data u ON u.model='res.groups' AND u.res_id=r.gid"
        " AND u.module='base' AND u.name='group_user'"
        " JOIN ir_model_data g ON g.model='res.groups' AND g.res_id=r.hid"
        " AND g.module='product' AND g.name='group_product_pricelist')"
        " AND NOT EXISTS (SELECT 1 FROM product_pricelist)"
        " THEN 1 ELSE 0 END",
        "gravity": "broken",
        "repair": "script/odoo/migration/restore_config_defaults.py --apply",
    },
    {
        "key": "view_model_gone",
        "title": "Views bound to a model that no longer exists",
        "why": "Opening one raises; the menu that leads to it is a dead end.",
        "sql": "SELECT count(*) FROM ir_ui_view v"
        " WHERE v.model IS NOT NULL AND v.model <> ''"
        " AND NOT EXISTS (SELECT 1 FROM ir_model m WHERE m.model = v.model)",
        "gravity": "broken",
        "repair": None,
    },
    {
        "key": "view_parent_gone",
        "title": "Views inheriting a view that is gone",
        "why": "The whole inheritance chain below them stops rendering.",
        "sql": "SELECT count(*) FROM ir_ui_view v WHERE v.inherit_id IS NOT"
        " NULL AND NOT EXISTS"
        " (SELECT 1 FROM ir_ui_view p WHERE p.id = v.inherit_id)",
        "gravity": "broken",
        "repair": "script/odoo/migration/fix_cow_render.py --apply",
    },
    {
        "key": "xmlid_model_gone",
        "title": "External ids pointing at a model that is gone",
        "why": "Every module update that resolves one of them fails.",
        "sql": "SELECT count(*) FROM ir_model_data d WHERE NOT EXISTS"
        " (SELECT 1 FROM ir_model m WHERE m.model = d.model)",
        "gravity": "broken",
        "repair": "script/odoo/migration/database_cleanup.py",
    },
    {
        "key": "attachment_field_gone",
        "title": "Attachments whose carrying field is gone",
        "why": "Odoo raises a KeyError merely checking them, and nothing"
        " will ever read them again.",
        "sql": "SELECT count(*) FROM ir_attachment a"
        " WHERE a.res_field IS NOT NULL AND a.res_field <> ''"
        " AND NOT EXISTS (SELECT 1 FROM ir_model_fields f"
        " WHERE f.model = a.res_model AND f.name = a.res_field)",
        "gravity": "watch",
        "repair": "script/analyse/check_filestore.py",
    },
)


def inspect(database, config_path=None):
    """Passer chaque contrôle, et rendre son nombre.

    Un contrôle qui ÉCHOUE n'est pas un contrôle qui rend zéro : une table
    absente parce que le module n'est pas installé n'est pas un dégât. On
    garde l'erreur telle quelle, et le rendu la distingue.
    """
    resultats = {}
    for controle in CONTROLES:
        try:
            brut = lib_analyse.run_psql(
                database, controle["sql"], config_path=config_path
            ).strip()
            resultats[controle["key"]] = int(brut.splitlines()[0])
        except Exception as exc:  # noqa: BLE001 - on rapporte, on ne meurt pas
            resultats[controle["key"]] = {
                "error": str(exc).splitlines()[0][:120]
            }
    return resultats


def judge(resultats):
    """Ne garder que ce qui compte, le plus grave d'abord.

    Un contrôle illisible remonte AVEC les autres : ne pas avoir pu
    regarder n'est pas la même chose que n'avoir rien trouvé, et taire la
    différence est exactement ce qui fait prendre un rapport pour une
    garantie.
    """
    trouve, illisibles = [], []
    for controle in CONTROLES:
        valeur = resultats.get(controle["key"])
        if isinstance(valeur, dict):
            illisibles.append((controle, valeur.get("error", "")))
        elif valeur:
            trouve.append((controle, valeur))
    trouve.sort(key=lambda pair: (pair[0]["gravity"] != "broken", -pair[1]))
    return trouve, illisibles


def famille(nom):
    """La base d'origine dont ce nom est un palier.

    « test_neutralize_upgrade_14 » et « …_upgrade_18 » sont deux paliers
    de la MÊME migration. Interroger la base 18 doit montrer l'échec du
    palier 14 : c'est le seul endroit où il subsiste.
    """
    return nom.rsplit("_upgrade_", 1)[0] if "_upgrade_" in nom else nom


def verdicts(database, path=None):
    """(tous, ratés) pour cette base — lus dans le FICHIER, pas en SQL.

    Un test de fumée qui échoue ne laisse aucune trace en base : rien
    n'est écrit, rien n'est cassé, la requête suivante répond. Les
    contrôles ci-dessus sont donc structurellement aveugles à ce type
    d'échec, et c'était la moitié de ce qu'une migration peut rater.
    """
    dct = quality.read_progression(path or quality.DEFAULT_PROGRESSION)
    lignee = famille(database)
    tous = [
        e
        for e in quality.read_events(dct)
        if famille(quality.event_database(e)) == lignee
    ]
    return tous, quality.failures(tous)


def extrait_du_journal(dct, event, colour=True, avant=6):
    """(lignes, la sortie de l'outil y est-elle) autour de ce verdict.

    La commande seule ne dit pas POURQUOI. Le journal, lui, garde ce
    qu'Odoo écrivait au moment du test — et c'est tout ce qu'on a : la
    sortie de l'outil n'y est pas, parce qu'elle passe par le terminal,
    qu'un tube ferait renoncer aux outils en plein écran. Le pilote le
    documente à l'endroit où il l'écrit.

    Silencieux quand il n'y a rien à montrer : une ligne « pas de
    journal » par verdict noierait les quatre qui comptent.
    """
    chemin = status.step_log_path(dct, event.get("step"))
    if not chemin or avant <= 0:
        return [], False
    try:
        with open(chemin, "r", encoding="utf-8", errors="replace") as handle:
            brut = handle.read().splitlines()
    except OSError:
        return [], False
    extrait, rang = quality.event_excerpt(brut, event, avant=avant)
    if not extrait:
        return [], False
    lignes = [paint(f"          {chemin}", "dim", colour)]
    for ligne in extrait:
        lignes.append(paint(f"            {ligne[:150]}", "dim", colour))
    debut = max(0, rang - avant) if rang is not None else 0
    avec_sortie = rang is not None and quality.excerpt_has_output(
        extrait, rang - debut
    )
    return lignes, avec_sortie


def verdicts_block(database, colour=True, path=None, lignes_avant=6):
    """La section « Verdicts », ou rien du tout s'il n'y en a pas.

    Silencieuse quand le fichier n'existe pas : devant la sauvegarde d'un
    client, il n'y a jamais eu de migration locale, et annoncer l'absence
    d'un fichier qu'on n'attendait pas ne renseigne personne.
    """
    chemin = path or quality.DEFAULT_PROGRESSION
    tous, ratés = verdicts(database, chemin)
    if not tous:
        return []
    lignes = [
        "",
        paint(f"🚦 {t('Verdicts the migration recorded')}", "step", colour),
    ]
    lignes.append(paint(f"   {t('recorded in')} {chemin}", "dim", colour))
    lignes.append("")
    if not ratés:
        lignes.append(
            paint(
                f"✅ {str(len(tous)).rjust(6)}  {t('checks, all passed')}",
                "ok",
                colour,
            )
        )
    dct = quality.read_progression(chemin)
    sortie_presente = False
    for event in ratés:
        version = quality.version_of(quality.event_database(event), dct)
        palier = str(version) if version else quality.event_step(event)
        lignes.append(
            paint(
                f"❌ {palier.rjust(6)}  {event['name']}",
                "broken",
                colour,
            )
        )
        lignes.append(
            paint(f"          {event['detail'][:120]}", "dim", colour)
        )
        bloc, avec_sortie = extrait_du_journal(
            dct, event, colour, lignes_avant
        )
        sortie_presente = sortie_presente or avec_sortie
        lignes.extend(bloc)
    lignes.append("")
    lignes.append(
        paint(
            f"   {t('These come from the file, not the database:')}"
            f" {t('the exit code ignores them.')}",
            "dim",
            colour,
        )
    )
    if ratés and lignes_avant > 0 and not sortie_presente:
        lignes.append(
            paint(
                f"   {t('the tool output is not in the step log: it goes')}"
                f" {t('to the terminal and dies with it.')}",
                "dim",
                colour,
            )
        )
    return lignes


def render(database, resultats, version=None, colour=True):
    """Le rapport lisible. Chaque constat dit quoi lancer pour le réparer."""
    trouve, illisibles = judge(resultats)
    lignes = [f"🚚 {t('Migration residue in')} {database}"]
    if version:
        lignes.append(f"   {t('base module version:')} {version}")
    lignes.append("")

    if not trouve and not illisibles:
        lignes.append(
            paint(
                f"✅ {t('None of the checks found anything.')}", "ok", colour
            )
        )
        lignes.append(
            paint(
                f"   {t('This reads one database on its own — it cannot see')}"
                f" {t('what an earlier step silently dropped.')}",
                "dim",
                colour,
            )
        )
        return "\n".join(lignes + verdicts_block(database, colour)).rstrip()

    for controle, combien in trouve:
        icone = "❌" if controle["gravity"] == "broken" else "⚠"
        lignes.append(
            paint(
                f"{icone} {str(combien).rjust(6)}  {t(controle['title'])}",
                controle["gravity"],
                colour,
            )
        )
        lignes.append(paint(f"          {t(controle['why'])}", "dim", colour))
        if controle["repair"]:
            lignes.append(f"          → {controle['repair']}")
        else:
            lignes.append(
                paint(f"          → {t('no repair tool yet')}", "dim", colour)
            )
        lignes.append("")

    for controle, erreur in illisibles:
        lignes.append(
            paint(
                f"❔        {t(controle['title'])} — {t('could not read')}",
                "watch",
                colour,
            )
        )
        lignes.append(paint(f"          {erreur}", "dim", colour))
    return "\n".join(lignes + verdicts_block(database, colour)).rstrip()


def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=t("What a migration left behind, read in one database."),
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", help="odoo config file")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    try:
        lib_analyse.require_odoo_database(
            args.database, config_path=args.config
        )
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    resultats = inspect(args.database, args.config)
    try:
        version = lib_analyse.database_version(
            args.database, config_path=args.config
        )
    except Exception:  # noqa: BLE001 - la version est un confort, pas le sujet
        version = None
    trouve, illisibles = judge(resultats)

    if args.json:
        tous_verdicts, verdicts_ratés = verdicts(args.database)
        print(
            json.dumps(
                {
                    "database": args.database,
                    "base_version": version,
                    "checks": resultats,
                    "found": [c["key"] for c, _ in trouve],
                    "unreadable": [c["key"] for c, _ in illisibles],
                    "verdicts": tous_verdicts,
                    "verdicts_failed": [
                        {"step": quality.event_step(e), "name": e["name"]}
                        for e in verdicts_ratés
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        colour = sys.stdout.isatty() and not args.no_color
        print(render(args.database, resultats, version, colour))
    return 1 if trouve else 0


if __name__ == "__main__":
    sys.exit(main())
