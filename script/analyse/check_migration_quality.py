#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'une migration gagne et ce qu'elle perd, palier par palier.

La question qu'on se pose après six paliers n'est pas « a-t-elle fini » —
le journal le dit — mais « qu'est-ce qui a changé en chemin ». Un module
désinstallé en 15 pour débloquer la mise à jour, une table vidée sans que
personne ne le voie, deux cents vues apparues : rien de tout cela
n'apparaît dans un journal qu'on lit ligne à ligne.

Ce que l'outil compare
----------------------
Une migration laisse une base PAR PALIER — `x`, `x_upgrade_13`, … — et
elles existent toutes encore. On les interroge donc côte à côte, en
lecture seule, plutôt que de rejouer quoi que ce soit.

Pourquoi pas en démarrant Odoo
------------------------------
Six démarrages coûteraient une heure, écriraient dans les bases et
demanderaient de basculer le checkout à chaque palier. Mesuré : la même
inspection en SQL prend moins d'une demi-seconde par base, et ne touche à
rien. Ce qu'on y perd — les modèles abstraits, les champs calculés — ne
se compare pas d'une version à l'autre de toute façon.

Ce qui compte le plus
---------------------
Les LIGNES perdues. Un module en moins se voit ; une table qui passe de
quatre mille lignes à zéro ne se voit nulle part. Un renommage de table
entre deux versions s'y lit comme une perte suivie d'un gain : le rapport
les rapproche quand le compte correspond, plutôt que de crier au loup.

Codes de sortie : 0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué.
"""

import json
import os
import subprocess
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


DEFAULT_PROGRESSION = ".venv.erplibre/odoo_database_migration_log.json"
FILESTORE = os.path.join(
    os.path.expanduser("~"), ".local", "share", "Odoo", "filestore"
)
SEP = "\x1f"


def run_psql(database, sql):
    """Interroger la base en lecture seule, garantie par le SERVEUR.

    `default_transaction_read_only` n'est pas une promesse de l'outil :
    PostgreSQL refusera l'écriture même si le SQL en contenait une. On
    inspecte des bases de migration, parfois la seule copie qui reste.
    """
    env = os.environ.copy()
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    env["PSQLRC"] = ""
    done = subprocess.run(
        ["psql", "-X", "-w", "-d", database, "-tAF", SEP, "-c", sql],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        return None
    return [ligne.split(SEP) for ligne in done.stdout.splitlines() if ligne]


def read_progression(path=DEFAULT_PROGRESSION):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def chain(dct):
    """[(version, base)] du départ à l'arrivée, dans l'ordre du parcours.

    Le nom des bases de palier suit la convention du pilote —
    « <base>_upgrade_<version> » — et la liste des paliers se déduit de la
    cible et du nombre d'entrées `state_4_*_odoo_lst`. On ne devine donc
    rien : on relit ce que la migration a écrit.
    """
    base = dct.get("config_database_name")
    if not base:
        return []
    try:
        cible = int(float(dct.get("target_odoo_version") or 0))
    except (TypeError, ValueError):
        return []
    total = max(
        [
            len(valeur)
            for cle, valeur in dct.items()
            if cle.startswith("state_4_")
            and cle.endswith("_odoo_lst")
            and isinstance(valeur, list)
        ]
        or [0]
    )
    if not total or not cible:
        return [(None, base)]
    lst_version = list(range(cible - total + 1, cible + 1))
    depart = lst_version[0] - 1
    return [(depart, base)] + [
        (version, f"{base}_upgrade_{version}") for version in lst_version
    ]


META_SQL = """
SELECT 'odoo', latest_version FROM ir_module_module WHERE name = 'base'
UNION ALL SELECT 'view', count(*)::text FROM ir_ui_view
UNION ALL SELECT 'view_cow', count(*)::text FROM ir_ui_view
    WHERE website_id IS NOT NULL
UNION ALL SELECT 'menu', count(*)::text FROM ir_ui_menu
UNION ALL SELECT 'action', count(*)::text FROM ir_act_window
UNION ALL SELECT 'attachment', count(*)::text FROM ir_attachment
UNION ALL SELECT 'attachment_stored', count(*)::text FROM ir_attachment
    WHERE store_fname IS NOT NULL
UNION ALL SELECT 'language', count(*)::text FROM res_lang WHERE active
"""


def table_counts(database):
    """{table: lignes} pour toutes les tables. Une seule requête.

    Construite côté serveur puis exécutée d'un bloc : huit cents requêtes
    séparées coûteraient huit cents allers-retours, là où celle-ci prend
    quatre dixièmes de seconde — mesuré sur une base de 890 tables.
    """
    fabrique = run_psql(
        database,
        "SELECT string_agg("
        "format('SELECT %L t, count(*) n FROM %I', table_name, table_name),"
        " ' UNION ALL ') FROM information_schema.tables"
        " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'",
    )
    if not fabrique or not fabrique[0][0]:
        return {}
    lignes = run_psql(database, fabrique[0][0])
    if lignes is None:
        return {}
    return {
        nom: int(nombre)
        for nom, nombre in (ligne[:2] for ligne in lignes)
        if nombre.isdigit()
    }


def missing_files(database, lst_store_fname):
    """Les pièces jointes dont le FICHIER a disparu du filestore.

    Une base peut référencer des milliers de pièces jointes dont le
    contenu n'a pas suivi le clonage. Rien ne le signale : la page se
    charge, l'image est vide.
    """
    racine = os.path.join(FILESTORE, database)
    if not os.path.isdir(racine):
        return None
    return [
        nom
        for nom in lst_store_fname
        if nom and not os.path.isfile(os.path.join(racine, nom))
    ]


def inspect(database):
    """L'état d'une base, en lecture seule. `exists` False si absente."""
    etat = {"database": database, "exists": False}
    meta = run_psql(database, META_SQL)
    if meta is None:
        return etat
    etat["exists"] = True
    dct_meta = {ligne[0]: ligne[1] for ligne in meta if len(ligne) > 1}
    etat["odoo"] = (dct_meta.get("odoo") or "?").rsplit(".", 2)[0]
    for cle in (
        "view",
        "view_cow",
        "menu",
        "action",
        "attachment",
        "attachment_stored",
        "language",
    ):
        etat[cle] = int(dct_meta.get(cle) or 0)

    modules = run_psql(
        database, "SELECT name, state FROM ir_module_module ORDER BY name"
    )
    etat["module"] = {
        nom: statut for nom, statut in (m[:2] for m in modules or [])
    }
    etat["installed"] = sorted(
        nom for nom, statut in etat["module"].items() if statut == "installed"
    )
    modeles = run_psql(database, "SELECT model FROM ir_model ORDER BY model")
    etat["model"] = sorted(m[0] for m in modeles or [])
    etat["table"] = table_counts(database)
    # Les CHAMPS : un champ perdu est une colonne de données perdue, et
    # c'est plus fin qu'un modèle — un modèle qui survit peut avoir été
    # vidé de la moitié de ses champs sans que rien ne le dise.
    champs = run_psql(
        database,
        "SELECT model || '.' || name FROM ir_model_fields ORDER BY 1",
    )
    etat["field"] = sorted(ligne[0] for ligne in champs or [])
    # Les copies COW par leur CLÉ : c'est elle qu'on réinitialise, et
    # c'est par elle qu'on les retrouve d'une version à l'autre.
    copies = run_psql(
        database,
        "SELECT coalesce(key, 'id:' || id::text) FROM ir_ui_view"
        " WHERE website_id IS NOT NULL ORDER BY 1",
    )
    etat["cow"] = sorted(ligne[0] for ligne in copies or [])

    # Les modèles sans table : abstraits, mixins et vues SQL pour la
    # plupart — mais leur NOMBRE qui bouge d'un palier à l'autre dit
    # quelque chose, alors que la liste brute ne dit rien.
    tables = set(etat["table"])
    etat["model_without_table"] = [
        m for m in etat["model"] if m.replace(".", "_") not in tables
    ]

    stockees = run_psql(
        database,
        "SELECT DISTINCT store_fname FROM ir_attachment"
        " WHERE store_fname IS NOT NULL",
    )
    absents = missing_files(database, [ligne[0] for ligne in stockees or []])
    etat["attachment_missing"] = None if absents is None else len(absents)
    # Les NOMS, pas seulement le compte : sans eux, « 254 fichiers
    # absents » ne dit pas lesquels, et l'on ne peut ni juger de la
    # gravité ni retrouver ce qui a disparu. Bornés, car une base peut en
    # aligner des dizaines de milliers et l'écran n'en montrera jamais tant.
    etat["attachment_missing_list"] = (absents or [])[:MAX_MISSING]
    return etat


MAX_MISSING = 5000


def missing_detail(database, lst_store_fname, limit=400):
    """Les métadonnées des pièces jointes dont le fichier a disparu.

    À la DEMANDE, jamais pendant l'inspection : une requête de plus par
    base allongerait un parcours qui tient aujourd'hui en quatre secondes,
    pour une information qu'on ne regarde qu'en la demandant.

    `res_field` est le renseignement le plus utile du lot : il dit QUEL
    champ a perdu son image — l'`image_1920` d'un pays n'a pas le même
    poids qu'une pièce jointe de facture.
    """
    if not lst_store_fname:
        return []
    lst = list(lst_store_fname)[:limit]
    valeurs = ", ".join("'" + nom.replace("'", "''") + "'" for nom in lst)
    lignes = run_psql(
        database,
        "SELECT store_fname, coalesce(res_model, '-'),"
        " coalesce(res_field, '-'), coalesce(res_id::text, '-'),"
        " coalesce(mimetype, '-'), coalesce(file_size::text, '0'),"
        " coalesce(name, '-')"
        f" FROM ir_attachment WHERE store_fname IN ({valeurs})"
        " ORDER BY res_model, res_field, name",
    )
    return [
        {
            "store_fname": ligne[0],
            "model": ligne[1],
            "field": ligne[2],
            "res_id": ligne[3],
            "mimetype": ligne[4],
            "size": int(ligne[5]) if ligne[5].isdigit() else 0,
            "name": ligne[6],
        }
        for ligne in lignes or []
        if len(ligne) >= 7
    ]


DETAILS = ("modules", "models", "fields", "cow", "tables")


def render_detail(diff, categorie, colour=False):
    """La liste ENTIÈRE d'une catégorie, sans troncature.

    Le résumé coupe à huit entrées, et il a raison : personne ne lit
    trois cent soixante-quinze noms de modèles en passant. Mais quand on
    cherche si UN module précis a survécu, la liste tronquée ne répond
    pas — et c'est justement là qu'on a besoin d'elle.
    """
    from script.todo.migration_status import paint

    if diff is None or diff.get("unavailable"):
        return t("not comparable: a database is missing")
    if categorie == "tables":
        lignes = [f"── {t('table(s) lost rows')} ──"]
        vers = {a: b for a, b, _n in diff["renamed"]}
        for table, avant, apres, connu in diff["rows_lost"]:
            note = ""
            if connu and connu["into"]:
                note = f"   → {connu['into']}"
            elif connu:
                note = f"   {t('retired from the database')}"
            elif table in vers:
                note = f"   ↻ {vers[table]}"
            teinte = "dim" if connu else "fail"
            lignes.append(
                f"   {paint(f'{avant - apres:>8}', teinte, colour)}"
                f"  {table:<46} {avant} → {apres}{note}"
            )
        return "\n".join(lignes)

    perdus = diff.get(f"{categorie}_lost") or []
    gagnes = diff.get(f"{categorie}_gained") or []
    lignes = []
    # « − 28 copies COW » plutôt que « 28 copies COW perdus » : le signe
    # porte déjà le sens, et l'accord d'un participe avec une catégorie
    # dont le genre change d'une langue à l'autre ne se traduit pas.
    for lst, symbole, teinte in (
        (perdus, "−", "fail"),
        (gagnes, "+", "ok"),
    ):
        lignes.append(
            f"── {paint(symbole, teinte, colour)} {len(lst)}"
            f" {t(categorie)} ──"
        )
        lignes.extend(f"   {nom}" for nom in lst)
        lignes.append("")
    return "\n".join(lignes)


def render_missing(etat, colour=False, limit=60):
    """Ce qui manque, groupé d'abord, détaillé ensuite.

    Le groupement d'abord parce qu'il tranche : deux cent trente-trois
    drapeaux de pays et treize logos de fournisseurs de paiement sont des
    images livrées par les modules, qu'une mise à jour restaure. Huit
    pièces jointes éparses, non. La liste brute mettait les deux sur le
    même plan.
    """
    from script.todo.migration_status import paint

    absents = etat.get("attachment_missing") or 0
    if not absents:
        return f"✅ {t('every attachment file is present')}"
    lignes = [
        paint(
            f"❌ {absents}"
            f" {t('attachment files missing from the filestore')}",
            "fail",
            colour,
        ),
        f"   {etat['database']}",
        "",
    ]
    detail = missing_detail(
        etat["database"], etat.get("attachment_missing_list") or []
    )
    if not detail:
        lignes.append(t("Could not read their metadata."))
        return "\n".join(lignes)

    groupe = {}
    for item in detail:
        cle = (item["model"], item["field"], item["mimetype"])
        groupe[cle] = groupe.get(cle, 0) + 1
    lignes.append(f"── {t('by model and field')} ──")
    for (modele, champ, mime), nombre in sorted(
        groupe.items(), key=lambda x: -x[1]
    ):
        lignes.append(
            f"   {nombre:>5}  {paint(modele, 'step', colour):<34}"
            f" {champ:<22} {mime}"
        )
    lignes.append("")
    lignes.append(f"── {t('one by one')} ──")
    for item in detail[:limit]:
        lignes.append(
            f"   {item['model']}#{item['res_id']}"
            f"  {paint(item['field'], 'dim', colour)}"
            f"  {item['size']:>8} o  {item['name'][:44]}"
        )
        lignes.append(f"        {paint(item['store_fname'], 'cmd', colour)}")
    if len(detail) > limit:
        lignes.append(f"   … {len(detail) - limit} {t('more')}")
    return "\n".join(lignes)


# Ce qu'Odoo déplace ou retire de lui-même, d'une version à l'autre.
#
# Sans cette carte, l'outil annonçait « 81 tables ont perdu des lignes »
# et la plus grosse d'entre elles — ir_translation, 32 984 lignes — était
# une refonte voulue par l'éditeur. Les vraies questions se noyaient dans
# les fausses, ce qui est la façon la plus sûre de ne pas les voir.
#
# Chaque entrée a été VÉRIFIÉE sur une migration réelle 12 → 18, en
# comptant les deux côtés. Une carte écrite de mémoire vaudrait moins que
# pas de carte : elle expliquerait des pertes qui n'en sont pas.
SEMANTIC_MAP = (
    # Fusions : les enregistrements continuent, ailleurs et autrement.
    {
        "since": 13,
        "table": "account_invoice",
        "into": "account_move",
        "kind": "merged",
        "why": "invoices became journal entries",
    },
    {
        "since": 13,
        "table": "account_invoice_line",
        "into": "account_move_line",
        "kind": "merged",
        "why": "invoices became journal entries",
    },
    {
        "since": 13,
        "table": "account_invoice_tax",
        "into": "account_move_line",
        "kind": "merged",
        "why": "invoices became journal entries",
    },
    # Renommages : les mêmes enregistrements, sous un autre nom.
    {
        "since": 17,
        "table": "mail_channel",
        "into": "discuss_channel",
        "kind": "renamed",
        "why": "Discuss was renamed",
    },
    {
        "since": 17,
        "table": "mail_channel_partner",
        "into": "discuss_channel_member",
        "kind": "renamed",
        "why": "Discuss was renamed",
    },
    {
        "since": 13,
        "table": "website_redirect",
        "into": "website_rewrite",
        "kind": "renamed",
        "why": "redirections were reworked",
    },
    {
        "since": 13,
        "table": "crm_lead_tag",
        "into": "crm_tag",
        "kind": "renamed",
        "why": "tags became shared",
    },
    # Retraits : la fonction a quitté la base pour du code.
    {
        "since": 16,
        "table": "ir_translation",
        "into": None,
        "kind": "retired",
        "why": "translations moved into jsonb columns",
    },
    {
        "since": 17,
        "table": "account_tax_template",
        "into": None,
        "kind": "retired",
        "why": "chart templates left the database",
    },
    {
        "since": 17,
        "table": "account_account_template",
        "into": None,
        "kind": "retired",
        "why": "chart templates left the database",
    },
    {
        "since": 17,
        "table": "account_chart_template",
        "into": None,
        "kind": "retired",
        "why": "chart templates left the database",
    },
    {
        "since": 17,
        "table": "account_fiscal_position_template",
        "into": None,
        "kind": "retired",
        "why": "chart templates left the database",
    },
    {
        "since": 17,
        "table": "account_fiscal_position_tax_template",
        "into": None,
        "kind": "retired",
        "why": "chart templates left the database",
    },
    {
        "since": 17,
        "table": "account_fiscal_position_account_template",
        "into": None,
        "kind": "retired",
        "why": "chart templates left the database",
    },
    # Vérifié palier par palier : 1269 lignes en 12, 13 et 14, la table
    # disparaît en 15 et `mail_notification` en compte exactement 1269.
    # Pas une perdue.
    {
        "since": 15,
        "table": "mail_message_res_partner_needaction_rel",
        "into": "mail_notification",
        "kind": "merged",
        "why": "needaction became notifications",
    },
    {
        "since": 15,
        "table": "stock_inventory",
        "into": "stock_quant",
        "kind": "merged",
        "why": "inventory adjustments became quants",
    },
    {
        "since": 15,
        "table": "stock_inventory_line",
        "into": "stock_quant",
        "kind": "merged",
        "why": "inventory adjustments became quants",
    },
)


def as_version(etat):
    """« 18.0 » -> 18. None si l'on ne sait pas."""
    try:
        return int(float((etat or {}).get("odoo") or 0)) or None
    except (TypeError, ValueError):
        return None


def explain_loss(table, version):
    """Ce qu'Odoo a fait de cette table à cette version, ou None.

    `version` est celle d'ARRIVÉE : une refonte de la 17 n'explique rien
    d'un palier 13 → 14, et l'accepter ferait taire une vraie perte sous
    prétexte qu'elle porte le nom d'une table refondue plus tard.
    """
    if not version:
        return None
    for entree in SEMANTIC_MAP:
        if entree["table"] == table and entree["since"] <= version:
            return entree
    return None


def compare(avant, apres):
    """Ce qui a été gagné et ce qui a été perdu entre deux paliers."""
    if not avant.get("exists") or not apres.get("exists"):
        return {"unavailable": True}
    inst_avant, inst_apres = set(avant["installed"]), set(apres["installed"])
    mod_avant, mod_apres = set(avant["model"]), set(apres["model"])
    tbl_avant, tbl_apres = avant["table"], apres["table"]

    # TOUJOURS quatre éléments, le dernier étant l'explication ou None.
    # Un tuple de taille variable obligerait chaque lecteur à s'en méfier.
    lignes_perdues = []
    for table, nombre in sorted(tbl_avant.items()):
        reste = tbl_apres.get(table)
        if reste is None and nombre:
            lignes_perdues.append((table, nombre, 0, None))
        elif reste is not None and reste < nombre:
            lignes_perdues.append((table, nombre, reste, None))
    lignes_gagnees = [
        (table, tbl_avant.get(table, 0), nombre)
        for table, nombre in sorted(tbl_apres.items())
        if nombre > tbl_avant.get(table, 0)
    ]
    version = as_version(apres)
    for index, (table, debut, fin, _rien) in enumerate(lignes_perdues):
        connu = explain_loss(table, version)
        if not connu:
            continue
        # Une fusion qui n'a PAS grossi la table d'accueil n'explique
        # rien : on garde l'explication et on dit qu'elle ne tient pas.
        arrivee = connu["into"]
        recue = (
            apres["table"].get(arrivee, 0) - avant["table"].get(arrivee, 0)
            if arrivee
            else None
        )
        lignes_perdues[index] = (table, debut, fin, {**connu, "gained": recue})
    champ_avant = set(avant.get("field") or [])
    champ_apres = set(apres.get("field") or [])
    cow_avant = set(avant.get("cow") or [])
    cow_apres = set(apres.get("cow") or [])
    # Les plus grosses pertes EN TÊTE : on attaque une liste de
    # cinquante-sept par le haut, pas par ordre alphabétique.
    lignes_perdues.sort(key=lambda item: -(item[1] - item[2]))
    return {
        "fields_lost": sorted(champ_avant - champ_apres),
        "fields_gained": sorted(champ_apres - champ_avant),
        "cow_lost": sorted(cow_avant - cow_apres),
        "cow_gained": sorted(cow_apres - cow_avant),
        "modules_lost": sorted(inst_avant - inst_apres),
        "modules_gained": sorted(inst_apres - inst_avant),
        "models_lost": sorted(mod_avant - mod_apres),
        "models_gained": sorted(mod_apres - mod_avant),
        "rows_lost": lignes_perdues,
        "rows_gained": lignes_gagnees,
        "renamed": probable_renames(lignes_perdues, lignes_gagnees),
        "delta": {
            cle: apres.get(cle, 0) - avant.get(cle, 0)
            for cle in (
                "view",
                "view_cow",
                "menu",
                "action",
                "attachment",
                "language",
            )
        },
    }


def probable_renames(perdues, gagnees):
    """Rapprocher une table disparue d'une table apparue au même compte.

    Odoo renomme des tables entre versions — `mail_channel` est devenu
    `discuss_channel` en 17. Sans ce rapprochement, chaque renommage se
    lit comme une perte de données doublée d'une apparition, et l'on
    cherche un dégât là où il n'y en a pas.
    """
    disparues = {
        table: avant
        for table, avant, apres, _connu in perdues
        if apres == 0 and avant
    }
    apparues = {
        table: apres for table, avant, apres in gagnees if avant == 0 and apres
    }
    couples = []
    for table, nombre in sorted(disparues.items()):
        for autre, combien in sorted(apparues.items()):
            if combien == nombre and looks_renamed(table, autre):
                couples.append((table, autre, nombre))
                del apparues[autre]
                break
    return couples


RENAME_RATIO = 0.75


def looks_renamed(un, deux):
    """Les deux noms se ressemblent-ils assez pour être le même sujet ?

    Deux garde-fous ont été essayés et rejetés, mesurés sur une vraie
    migration. Le seul nombre de lignes accouplait
    `account_account_tag_account_tax_template_rel` à `dms_directory` : les
    deux comptaient sept lignes. Un mot commun d'au moins cinq lettres
    accouplait `cleanup_purge_wizard_menu` à
    `cleanup_create_indexes_line` — « cleanup » ne dit rien.

    La ressemblance d'ENSEMBLE tranche : `muk_dms_directory` et
    `dms_directory` se ressemblent à 87 %, `website_redirect` et
    `website_rewrite` à 83 %, tandis que les faux couples restent sous
    50 %.
    """
    import difflib

    return difflib.SequenceMatcher(None, un, deux).ratio() >= RENAME_RATIO


def survey(dct, echo=None):
    """Inspecter toute la chaîne, du départ à l'arrivée."""
    lst = []
    for version, database in chain(dct):
        if echo:
            echo(f"{database} …")
        etat = inspect(database)
        etat["version"] = version
        lst.append(etat)
    return lst


def overall(lst_snapshot):
    """La comparaison du PREMIER au DERNIER palier.

    Elle ne se déduit pas des comparaisons deux à deux : un module retiré
    en 15 puis remis en 17 n'a rien perdu du tout, et l'addition des
    étapes le compterait deux fois.
    """
    presents = [x for x in lst_snapshot if x.get("exists")]
    if len(presents) < 2:
        return {"unavailable": True}
    return compare(presents[0], presents[-1])


def render_text(lst_snapshot, colour=None, limit=8):
    """Le rapport complet. C'est aussi le repli du plein écran."""
    from script.todo.migration_status import paint, supports_colour

    if colour is None:
        colour = supports_colour()
    lignes = [f"📐 {t('Migration quality, step by step')}"]
    for etat in lst_snapshot:
        if not etat.get("exists"):
            lignes.append(
                f"   ⚠️  {etat['database']} : {t('database not found')}"
            )
            continue
        lignes.append(
            f"   {paint(f'{etat['odoo']:<6}', 'step', colour)}"
            f" {etat['database']:<34}"
            f" {len(etat['installed']):>4} {t('modules')}"
            f" · {len(etat['model']):>4} {t('models')}"
            f" · {etat['view']:>5} {t('views')}"
            f" · {etat['attachment']:>6} {t('attachments')}"
        )
        if etat.get("attachment_missing"):
            lignes.append(
                f"          {paint('❌', 'fail', colour)}"
                f" {etat['attachment_missing']}"
                f" {t('attachment files missing from the filestore')}"
            )

    presents = [x for x in lst_snapshot if x.get("exists")]
    for avant, apres in zip(presents, presents[1:]):
        lignes.append(f"\n🔀 {avant['odoo']} → {apres['odoo']}")
        lignes.extend(render_compare(compare(avant, apres), colour, limit))

    lignes.append(
        f"\n🏁 {t('From start to finish')} :"
        f" {presents[0]['odoo'] if presents else '?'}"
        f" → {presents[-1]['odoo'] if presents else '?'}"
    )
    lignes.extend(render_compare(overall(lst_snapshot), colour, limit))
    return "\n".join(lignes)


def render_compare(diff, colour, limit=8):
    """Les gains et les pertes d'un palier, en quelques lignes."""
    from script.todo.migration_status import paint

    if diff.get("unavailable"):
        return [f"   {t('not comparable: a database is missing')}"]
    lignes = []
    for cle, symbole, teinte in (
        ("modules_lost", "−", "fail"),
        ("modules_gained", "+", "ok"),
    ):
        lst = diff[cle]
        if lst:
            lignes.append(
                f"   {paint(symbole, teinte, colour)} {len(lst)}"
                f" {t('modules')} : {', '.join(lst[:limit])}"
                + (" …" if len(lst) > limit else "")
            )
    for cle, symbole, teinte in (
        ("models_lost", "−", "fail"),
        ("models_gained", "+", "ok"),
    ):
        lst = diff[cle]
        if lst:
            lignes.append(
                f"   {paint(symbole, teinte, colour)} {len(lst)}"
                f" {t('models')} : {', '.join(lst[:limit])}"
                + (" …" if len(lst) > limit else "")
            )
    if diff["renamed"]:
        lignes.append(
            f"   ↻ {len(diff['renamed'])} {t('probable table rename(s)')} :"
            f" {', '.join(f'{a} → {b}' for a, b, _n in diff['renamed'][:4])}"
        )
    perdues = diff["rows_lost"]
    if perdues:
        # LE signal qui compte : un module en moins se voit, une table qui
        # passe de quatre mille lignes à zéro ne se voit nulle part.
        #
        # Les pertes EXPLIQUÉES sont séparées des autres, jamais retirées.
        # Sans cette séparation on lisait « 81 tables ont perdu des lignes »
        # dont la plus grosse — ir_translation, 32 984 lignes — était une
        # refonte voulue par Odoo : les vraies questions se noyaient dans
        # les fausses, ce qui est la façon la plus sûre de ne pas les voir.
        vers = {a: b for a, b, _n in diff["renamed"]}
        ouvertes = [item for item in perdues if not item[3]]
        connues = [item for item in perdues if item[3]]
        if ouvertes:
            lignes.append(
                f"   {paint('▼', 'fail', colour)} {len(ouvertes)}"
                f" {t('table(s) lost rows, unexplained')} :"
            )
            for table, avant, apres, _rien in ouvertes[:limit]:
                note = (
                    f"   ↻ {t('probably renamed to')} {vers[table]}"
                    if table in vers
                    else ""
                )
                lignes.append(f"       {table:<40} {avant:>8} → {apres}{note}")
            if len(ouvertes) > limit:
                lignes.append(f"       … {len(ouvertes) - limit} {t('more')}")
        if connues:
            lignes.append(
                f"   {paint('▽', 'dim', colour)} {len(connues)}"
                f" {t('table(s) Odoo moved or retired')} :"
            )
            for table, avant, apres, connu in connues[:limit]:
                if connu["into"]:
                    recue = connu.get("gained")
                    # Une fusion dont la table d'accueil n'a PAS grossi
                    # n'explique rien : le dire, plutôt que de classer la
                    # perte comme attendue et passer à autre chose.
                    accueil = (
                        f"+{recue} {t('there')}"
                        if recue and recue > 0
                        else paint(t("but it gained nothing"), "fail", colour)
                    )
                    ou = f"→ {connu['into']}  ({accueil})"
                else:
                    ou = t("retired from the database")
                lignes.append(f"       {table:<40} {avant:>8} → {apres}  {ou}")
                lignes.append(f"           {connu['why']}")
            if len(connues) > limit:
                lignes.append(f"       … {len(connues) - limit} {t('more')}")
    delta = diff["delta"]
    lignes.append(
        "   "
        + "  ".join(
            f"{cle} {valeur:+d}" for cle, valeur in delta.items() if valeur
        )
        or "   ="
    )
    return lignes


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Compare every database a migration left behind, step by step,"
            " and report what was gained and what was lost."
        )
    )
    parser.add_argument(
        "-f",
        "--file",
        default=DEFAULT_PROGRESSION,
        help="migration progression file",
    )
    parser.add_argument(
        "--text",
        action="store_true",
        help="print the report instead of opening the full screen",
    )
    parser.add_argument("--limit", type=int, default=8)
    config = parser.parse_args(argv)

    dct = read_progression(config.file)
    if not chain(dct):
        print(f"ℹ️  {t('No migration in progress.')}")
        return 0
    lst = survey(dct, echo=lambda texte: print(f"⧖ {texte}", flush=True))
    if not config.text:
        try:
            from script.analyse.check_migration_quality_tui import run_tui
        except Exception:
            run_tui = None
        if run_tui and run_tui(lst):
            return 0
    print(render_text(lst, limit=config.limit))
    manque = [x for x in lst if not x.get("exists")]
    perdu = overall(lst)
    trouvailles = bool(manque) or bool(
        not perdu.get("unavailable")
        and (perdu["modules_lost"] or perdu["rows_lost"])
    )
    return 1 if trouvailles else 0


if __name__ == "__main__":
    sys.exit(main())
