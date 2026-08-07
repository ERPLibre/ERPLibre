#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Socle commun des outils d'analyse d'une base Odoo, en lecture seule.

Pourquoi psql en sous-processus plutôt que psycopg2
---------------------------------------------------
La raison est déjà écrite dans le dépôt, dans ``reset_stale_cow_views.py`` :
« Plain psql on purpose: this runs on databases whose Odoo registry does not
load, which is precisely when it is needed ». Une base 12.0 sur un checkout
18.0 ne charge pas son registre, et c'est exactement le moment où on veut
l'analyser. Accessoirement, psycopg2 n'est pas dans ``.venv.erplibre``, qui est
l'interpréteur de ces outils.

La lecture seule est une garantie, pas une promesse
--------------------------------------------------
``PGOPTIONS`` porte ``default_transaction_read_only=on`` : c'est **le serveur**
qui refuse toute écriture, pour toutes les transactions de la connexion. Un
``SET`` glissé dans le même ``-c`` ne suffirait pas — ``psql -c`` ouvre une
transaction implicite unique, et ``default_transaction_read_only`` ne vaut que
pour les transactions *suivantes*.

Ne jamais deviner la forme du schéma
------------------------------------
Douze versions d'Odoo se partagent ces tables. Les colonnes apparaissent,
changent de type (``text`` puis ``jsonb`` à partir de 16.0), ou n'existent que
si un module est installé. D'où ``existing_columns()`` et ``tr_col()`` : on
sonde avant d'écrire une requête, on ne date pas les colonnes de mémoire.

Les sondes lisent ``pg_attribute``, pas ``information_schema`` :
``information_schema`` est filtré par les droits. Avec un rôle non
propriétaire, elle renverrait un ensemble vide, et l'analyse concluerait
« aucune colonne website, donc aucune vue COW » sans le moindre avertissement.
"""

import configparser
import json
import os
import re
import subprocess
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


REPO_ROOT = new_path

# Une valeur littérale « False » dans config.conf veut dire « non défini » :
# c'est ainsi qu'Odoo écrit l'absence de valeur dans son fichier de config.
CONFIG_UNSET = ("false", "none", "")

# Un nom de base voyage jusqu'à une commande shell (`odoo_bin.sh shell -d …`,
# lancée avec shell=True par execute.py). On le valide au lieu de compter sur
# l'échappement : la liste de caractères qu'une base Odoo utilise réellement
# est courte, et tout le reste est soit une erreur de frappe, soit une
# injection.
RE_DATABASE_NAME = re.compile(r"[A-Za-z0-9_.-]+")

# Modèles dont la table N'EST PAS `_name.replace('.', '_')`.
#
# Dérivé des sources, pas écrit de mémoire : parcours AST de tous les `.py` de
# `odoo18.0/` et `addons/` (27 843 fichiers), en gardant les classes dont le
# `_table` diffère du défaut. Beaucoup de modules déclarent un `_table` égal au
# défaut — ce sont des déclarations sans effet, à ne pas confondre avec une
# surcharge.
#
# Sans cette table, `replace('.', '_')` échoue précisément sur les modèles les
# plus fréquents dans `ir_model_data` : `ir.actions.act_window` chercherait
# `ir_actions_act_window`, qui n'existe pas.
#
# La liste n'est pas la vérité, seulement ce qu'on sait : un modèle absent
# d'ici et dont la table est introuvable est classé « table inconnue » (un
# fait), jamais « table orpheline » (une anomalie). Pour la régénérer, refaire
# le parcours AST sur l'arbre courant.
MODEL_TABLE_OVERRIDE = {
    "ir.actions.act_multi": "ir_actions",
    "ir.actions.act_url": "ir_act_url",
    "ir.actions.act_window": "ir_act_window",
    "ir.actions.act_window.message": "ir_actions",
    "ir.actions.act_window.view": "ir_act_window_view",
    "ir.actions.act_window_close": "ir_actions",
    "ir.actions.actions": "ir_actions",
    "ir.actions.client": "ir_act_client",
    "ir.actions.report": "ir_act_report_xml",
    "ir.actions.server": "ir_act_server",
    "project.task.stage.personal": "project_task_user_rel",
    # `ir.actions.report.xml` est le nom d'avant 11.0 : les lignes
    # `ir_model_data` d'une base ancienne le portent encore.
    "ir.actions.report.xml": "ir_act_report_xml",
}


class AnalyseError(Exception):
    """Échec de l'outil, pas un constat d'analyse.

    Distinction qui porte le code de retour : 2 pour « je n'ai pas pu
    analyser », réservé à cette exception ; 1 pour « j'ai analysé et j'ai
    trouvé des constats ». Les confondre rendrait une analyse en échec
    indistinguable d'une base à problèmes.
    """


def valid_database_name(name):
    """Le nom est-il un nom de base plausible, sûr à mettre dans une commande ?"""
    return bool(name) and RE_DATABASE_NAME.fullmatch(name) is not None


def read_config(config_path=None):
    """Lire config.conf, en repliant sur /etc/odoo/odoo.conf comme run.sh.

    Renvoie un dict des options, vide si aucun fichier n'est trouvé — l'absence
    de config n'est pas une erreur : sur une installation native, psql se
    connecte très bien par le socket unix sans aucun paramètre.
    """
    lst_candidate = (
        [config_path]
        if config_path
        else [
            os.path.join(REPO_ROOT, "config.conf"),
            "/etc/odoo/odoo.conf",
        ]
    )
    for path in lst_candidate:
        if path and os.path.isfile(path):
            parser = configparser.RawConfigParser()
            try:
                parser.read(path)
            except configparser.Error:
                continue
            if parser.has_section("options"):
                return dict(parser.items("options"))
    return {}


def pg_env(config_path=None, timeout=120, overrides=None):
    """Variables d'environnement pour psql : connexion + lecture seule.

    Les paramètres viennent de config.conf, pas d'une hypothèse « socket unix
    et rôle = utilisateur système » : le dépôt lui-même livre
    ``db_user = erplibre`` et un docker-compose.yml avec un mot de passe.

    ``PGOPTIONS`` est ce qui rend l'analyse incapable d'écrire, et borne la
    durée d'une requête — un scan qui part en vrille ne bloque pas un menu.
    """
    config = read_config(config_path)
    my_env = os.environ.copy()

    dct_map = {
        "db_host": "PGHOST",
        "db_port": "PGPORT",
        "db_user": "PGUSER",
        "db_password": "PGPASSWORD",
        "db_sslmode": "PGSSLMODE",
    }
    for key, var in dct_map.items():
        value = str(config.get(key, "")).strip()
        if value.lower() not in CONFIG_UNSET:
            my_env[var] = value
    for var, value in (overrides or {}).items():
        if value:
            my_env[var] = str(value)

    my_env["PGOPTIONS"] = (
        f"-c default_transaction_read_only=on -c statement_timeout={timeout}s"
    )
    # Un ~/.psqlrc avec \timing ou \pset ajoute des lignes à la sortie et casse
    # le parsing. -X l'ignore, mais PSQLRC vide protège aussi les appels qui
    # oublieraient -X.
    my_env["PSQLRC"] = ""
    return my_env


def run_psql(database, sql, timeout=120, config_path=None, overrides=None):
    """Exécuter du SQL et rendre la sortie brute, une ligne par enregistrement.

    ``-X`` ignore ~/.psqlrc, ``-w`` interdit l'invite de mot de passe (sans
    lui, un mot de passe manquant bloque le menu TODO sans rien afficher),
    ``ON_ERROR_STOP=1`` fait échouer au premier problème plutôt que de rendre
    une sortie partielle qu'on prendrait pour un résultat.
    """
    if not valid_database_name(database):
        raise AnalyseError(f"{t('Invalid database name: ')}{database!r}")
    cmd = [
        "psql",
        "-X",
        "-w",
        "-v",
        "ON_ERROR_STOP=1",
        "-d",
        database,
        "-tAc",
        sql,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
            cwd=REPO_ROOT,
            env=pg_env(config_path, timeout=timeout, overrides=overrides),
        )
    except FileNotFoundError as exc:
        raise AnalyseError(
            f"{t('psql is not installed or not in PATH.')}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AnalyseError(
            f"{t('Query exceeded the timeout (s): ')}{timeout}"
        ) from exc
    if result.returncode:
        raise AnalyseError(
            f"{t('Cannot read from the database: ')}"
            f"{result.stderr.strip() or result.returncode}"
        )
    return result.stdout


def json_query(database, sql, **kwargs):
    """Rendre le résultat d'un SELECT comme une liste de dicts.

    Le SQL est enveloppé côté PostgreSQL plutôt que découpé côté Python : une
    arch de vue contient des retours de ligne et des « | », donc tout
    séparateur maison finirait par couper au mauvais endroit. C'est le même
    choix que ``snapshot_cow_views.py``.

    ``sql`` est un SELECT SANS point-virgule final : il devient une
    sous-requête.
    """
    inner = sql.strip().rstrip(";")
    wrapped = (
        "SELECT COALESCE(json_agg(row_to_json(t))::text, '[]')"
        f" FROM ({inner}) t;"
    )
    raw = run_psql(database, wrapped, **kwargs).strip()
    if not raw:
        return []
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise AnalyseError(f"{t('Unreadable JSON from psql: ')}{exc}") from exc


def scalar_query(database, sql, **kwargs):
    """Première valeur de la première ligne, ou None si aucune ligne."""
    raw = run_psql(database, sql, **kwargs).strip()
    if not raw:
        return None
    return raw.splitlines()[0].strip() or None


def require_odoo_database(database, **kwargs):
    """Refuser tout ce qui n'est pas une base Odoo, avant d'aller plus loin.

    Sans ce contrôle, ``-d postgres`` ou une base vide remonte un
    « relation "ir_ui_view" does not exist » brut, qui ressemble à un bogue de
    l'outil alors que c'est une erreur de saisie.
    """
    found = scalar_query(
        database, "SELECT to_regclass('public.ir_module_module');", **kwargs
    )
    if not found:
        raise AnalyseError(f"'{database}' {t('is not an Odoo database.')}")
    return True


def database_version(database, **kwargs):
    """Version Odoo de la BASE, qui n'est pas celle du checkout.

    Comparer les deux est ce qui évite d'ouvrir un shell Odoo pour rien : sur
    une base 13.0 avec un checkout 18.0, le registre ne chargera pas, et mieux
    vaut le dire tout de suite qu'après trente secondes de chargement.
    """
    return scalar_query(
        database,
        "SELECT latest_version FROM ir_module_module WHERE name = 'base';",
        **kwargs,
    )


def existing_columns(database, table, **kwargs):
    """Colonnes réellement présentes, via pg_attribute (pas information_schema).

    Renvoie un ensemble vide si la table n'existe pas — les deux cas se
    distinguent avec ``to_regclass`` si l'appelant en a besoin.
    """
    sql = (
        "SELECT a.attname FROM pg_attribute a"
        " JOIN pg_class c ON c.oid = a.attrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        f" WHERE n.nspname = 'public' AND c.relname = {quote_literal(table)}"
        " AND a.attnum > 0 AND NOT a.attisdropped;"
    )
    return {
        line.strip()
        for line in run_psql(database, sql, **kwargs).splitlines()
        if line.strip()
    }


def column_types(database, table, **kwargs):
    """{colonne: type PostgreSQL} — dit `jsonb` là où 15.0 disait `text`."""
    sql = (
        "SELECT a.attname, format_type(a.atttypid, a.atttypmod)"
        " FROM pg_attribute a"
        " JOIN pg_class c ON c.oid = a.attrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        f" WHERE n.nspname = 'public' AND c.relname = {quote_literal(table)}"
        " AND a.attnum > 0 AND NOT a.attisdropped;"
    )
    dct_type = {}
    for line in run_psql(database, sql, **kwargs).splitlines():
        if "|" in line:
            name, _, kind = line.partition("|")
            dct_type[name.strip()] = kind.strip()
    return dct_type


def tr_col(table, column, dct_type, lang="en_US"):
    """Fragment SQL lisant un champ traduit, quelle que soit la version.

    À partir de 16.0 un champ traduit est un ``jsonb`` ``{"en_US": "…"}`` ;
    jusqu'à 15.0 c'est du texte. Un seul endroit décide, et il décide sur le
    type réel de la colonne — pas sur un numéro de version, qu'il faudrait
    connaître et qui mentirait sur une base à moitié migrée.

    ``dct_type`` vient de ``column_types()``. Une colonne inconnue rend NULL
    plutôt que du SQL invalide : l'appelant verra un champ vide, pas une
    requête qui explose.
    """
    kind = (dct_type or {}).get(column)
    if kind is None:
        return "NULL::text"
    qualified = f'"{table}"."{column}"' if table else f'"{column}"'
    if kind == "jsonb":
        return f"{qualified}->>{quote_literal(lang)}"
    return f"{qualified}::text"


def quote_literal(value):
    """Littéral SQL sûr : les quotes simples sont doublées.

    Nécessaire parce que ces requêtes sont assemblées en texte pour psql, sans
    paramètres liés. Les seules valeurs concernées ici sont des noms de tables
    et de colonnes venant du catalogue, mais un nom de table hérité peut
    parfaitement porter une apostrophe.
    """
    return "'" + str(value).replace("'", "''") + "'"


def model_table(model, known_tables=None):
    """Table d'un modèle, ou None si elle est introuvable.

    None veut dire « je ne sais pas », jamais « il n'y en a pas » : c'est ce
    qui empêche de classer un modèle à `_table` surchargé comme une anomalie.
    ``known_tables`` est l'ensemble des tables réelles, quand l'appelant l'a.
    """
    table = MODEL_TABLE_OVERRIDE.get(model, model.replace(".", "_"))
    if known_tables is not None and table not in known_tables:
        return None
    return table


def public_tables(database, **kwargs):
    """Tables réelles du schéma public, vues par le catalogue.

    ``relkind IN ('r', 'p')`` : 'r' pour une table ordinaire, 'p' pour une
    table partitionnée. Odoo n'en partitionne pas, mais le jour où cela
    changera, le compte ne doit pas devenir faux en silence.
    """
    sql = (
        "SELECT c.relname FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p');"
    )
    return {
        line.strip()
        for line in run_psql(database, sql, **kwargs).splitlines()
        if line.strip()
    }


JSON_BEGIN = "ANALYSE_JSON_BEGIN"
JSON_END = "ANALYSE_JSON_END"


def odoo_config_path(config_path=None):
    """Chemin du fichier de configuration Odoo, comme run.sh le résout.

    Sans ``-c``, ``odoo_bin.sh`` ne passe AUCUNE configuration : ``addons_path``
    retombe sur le défaut d'Odoo, et le shell ne voit alors aucun des dépôts de
    ``addons/``. ``read_arch_from_file`` ne trouverait plus un seul fichier et
    rendrait une arch de référence vide pour toutes les vues — sans erreur.
    C'est la panne la plus coûteuse de cet outillage, parce qu'elle est
    silencieuse : le rapport dirait « aucun écart » sur une base pleine
    d'écarts.
    """
    for path in (
        config_path,
        os.path.join(REPO_ROOT, "config.conf"),
        "/etc/odoo/odoo.conf",
    ):
        if path and os.path.isfile(path):
            return path
    raise AnalyseError(t("No Odoo configuration file found."))


def odoo_shell_json(
    database, script_path, env=None, timeout=600, config_path=None
):
    """Pousser un script dans « odoo-bin shell » et récupérer son JSON.

    Pas de ``shell=True`` : la commande est une liste, le script arrive par
    l'entrée standard. Un nom de base n'a donc rien à échapper — il ne traverse
    aucun interpréteur de commandes.

    Les journaux d'Odoo se mêlent à la sortie, d'où les sentinelles : on ne
    lit que ce qui est entre elles. Leur absence est une erreur franche, pas
    une liste vide qu'on prendrait pour « rien à signaler ».
    """
    if not valid_database_name(database):
        raise AnalyseError(f"{t('Invalid database name: ')}{database!r}")
    with open(script_path, "r", encoding="utf-8") as handle:
        source = handle.read()

    my_env = os.environ.copy()
    my_env.update(env or {})
    cmd = [
        os.path.join(REPO_ROOT, "odoo_bin.sh"),
        "shell",
        "-c",
        odoo_config_path(config_path),
        "-d",
        database,
        "--no-http",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=source,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=REPO_ROOT,
            env=my_env,
        )
    except FileNotFoundError as exc:
        raise AnalyseError(t("odoo_bin.sh not found.")) from exc
    except subprocess.TimeoutExpired as exc:
        raise AnalyseError(
            f"{t('The Odoo shell exceeded the timeout (s): ')}{timeout}"
        ) from exc

    output = result.stdout or ""
    if JSON_BEGIN not in output or JSON_END not in output:
        detail = (result.stderr or output).strip().splitlines()[-3:]
        raise AnalyseError(
            f"{t('The Odoo shell returned no result: ')}{' / '.join(detail)}"
        )
    chunk = output.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0]
    try:
        return json.loads(chunk.strip())
    except ValueError as exc:
        raise AnalyseError(
            f"{t('Unreadable JSON from the Odoo shell: ')}{exc}"
        ) from exc


def normalise_arch(value):
    """L'arch en chaîne, quel que soit le type de la colonne.

    ``arch_db`` est du texte jusqu'à 15.0 et du jsonb à partir de 16.0, avec
    une entrée par langue. Reprise de ``reset_stale_cow_views.normalise_arch``,
    à l'identique : deux implémentations de cette conversion finiraient par
    diverger sur un cas limite, et c'est exactement le genre d'écart qui
    ferait conclure « la vue a changé » sur une base qui n'a rien changé.
    """
    if not isinstance(value, str):
        return "" if value is None else str(value)
    text = value.strip()
    if text.startswith("{") and '"' in text:
        try:
            data = json.loads(text)
        except ValueError:
            return value
        if isinstance(data, dict) and data:
            for lang in ("en_US", *sorted(data)):
                if lang in data and isinstance(data[lang], str):
                    return data[lang]
    return value


# Attributs dont la valeur est un chemin ou une expression : l'espace y sépare
# des jetons, il se normalise, mais il ne se supprime pas. « //div[1] /span »
# et « //div[1]/span » ne désignent pas la même chose.
SPACING_ATTRS = ("expr", "position", "groups", "t-call", "class")


def canonical(arch):
    """Forme canonique d'une arch, pour DÉCIDER s'il y a un écart.

    Sert à répondre « est-ce différent », jamais à afficher : ce qu'un humain
    relit, c'est l'arch brute.

    Pourquoi pas ``etree.canonicalize()`` en un appel, alors que lxml est là :
    son seul levier sur les espaces, ``strip_text``, s'applique à TOUS les
    nœuds texte, y compris le contenu d'un ``t-esc`` ou d'un CDATA — donc il
    masquerait des différences de contenu réelles. Et il n'offre aucun levier
    sur les espaces à l'intérieur d'une valeur d'attribut, alors que c'est
    précisément là que vit le bruit : un ``expr`` réindenté n'est pas une
    modification. D'où ce parcours, qui trie les attributs comme le ferait
    c14n, replie les espaces là où ils ne portent rien, et laisse le texte
    tranquille partout ailleurs.

    Renvoie None si l'arch n'est pas du XML analysable — un écart ne se
    conclut pas sur une comparaison qui n'a pas eu lieu.
    """
    from lxml import etree

    text = normalise_arch(arch)
    if not text.strip():
        return None
    try:
        parser = etree.XMLParser(remove_blank_text=True, remove_comments=True)
        root = etree.fromstring(text.encode("utf-8"), parser=parser)
    except etree.XMLSyntaxError:
        return None

    def render(node):
        lst_attr = []
        for key in sorted(node.attrib):
            value = node.attrib[key]
            if key in SPACING_ATTRS:
                value = " ".join(value.split())
            lst_attr.append(f"{key}={value!r}")
        head = node.tag + ("[" + ",".join(lst_attr) + "]" if lst_attr else "")
        # Le texte n'est replié que sur ses bords : l'indentation autour d'un
        # élément est de la mise en forme, l'espace À L'INTÉRIEUR d'un libellé
        # ou d'un t-esc est du contenu.
        own = (node.text or "").strip()
        parts = [head] + ([f"#{own}" for _ in (1,) if own])
        parts += [render(child) for child in node]
        tail = (node.tail or "").strip()
        if tail:
            parts.append(f"~{tail}")
        return "(" + " ".join(parts) + ")"

    return render(root)


def arch_differs(left, right):
    """(différent ?, comparable ?) entre deux arch.

    Deux réponses parce qu'il y a trois issues : identiques, différentes, et
    « je n'ai pas pu comparer ». Confondre la troisième avec la première
    ferait répondre « tout va bien » sur une vue au XML cassé, qui est
    justement celle qu'il faut regarder.
    """
    canon_left = canonical(left)
    canon_right = canonical(right)
    if canon_left is None or canon_right is None:
        return None, False
    return canon_left != canon_right, True


def side_by_side(left, right):
    """[(marque, gauche, droite)] alignés, pour l'affichage côte à côte.

    Marque : ' ' identiques, '≠' remplacées, '-' seulement à gauche, '+'
    seulement à droite. Consommé par le TUI ET par le rendu texte, pour que
    les deux racontent la même chose.
    """
    import difflib

    lst_left = normalise_arch(left).splitlines()
    lst_right = normalise_arch(right).splitlines()
    lst_row = []
    matcher = difflib.SequenceMatcher(None, lst_left, lst_right)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                lst_row.append(
                    (" ", lst_left[i1 + offset], lst_right[j1 + offset])
                )
        elif tag == "replace":
            for offset in range(max(i2 - i1, j2 - j1)):
                lst_row.append(
                    (
                        "≠",
                        lst_left[i1 + offset] if i1 + offset < i2 else None,
                        lst_right[j1 + offset] if j1 + offset < j2 else None,
                    )
                )
        elif tag == "delete":
            for offset in range(i1, i2):
                lst_row.append(("-", lst_left[offset], None))
        elif tag == "insert":
            for offset in range(j1, j2):
                lst_row.append(("+", None, lst_right[offset]))
    return lst_row


def diff_stats(lst_row):
    """{added, removed, changed} depuis les lignes de side_by_side()."""
    return {
        "added": sum(1 for mark, _, _ in lst_row if mark == "+"),
        "removed": sum(1 for mark, _, _ in lst_row if mark == "-"),
        "changed": sum(1 for mark, _, _ in lst_row if mark == "≠"),
    }


# --- Lire une sauvegarde .zip sans restaurer quoi que ce soit ----------------
#
# Une sauvegarde Odoo est un zip contenant `manifest.json`, un `filestore/` et
# un `dump.sql` — un pg_dump TEXTE, avec ses blocs `COPY … FROM stdin;` et ses
# `CREATE TABLE`. Tout se lit donc sans PostgreSQL et sans Odoo.
#
# Ce que ça débloque : analyser la sauvegarde d'une instance Enterprise depuis
# une installation Community. La restaurer y échoue — Odoo veut charger des
# modules qu'on n'a pas — alors que les champs Studio, eux, ne sont que des
# lignes de `ir_model_fields` qu'on peut lire telles quelles.
#
# La lecture est en FLOT, une seule passe : un dump de production pèse des
# gigaoctets, et on n'en veut que trois tables.

# Échappements de pg_dump dans un bloc COPY. `\N` (NULL) est traité à part :
# c'est une valeur, pas un caractère.
COPY_ESCAPE = {
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
}

# Lignes d'un CREATE TABLE qui ne déclarent pas une colonne.
NOT_A_COLUMN = (
    "CONSTRAINT",
    "PRIMARY",
    "UNIQUE",
    "CHECK",
    "FOREIGN",
    "EXCLUDE",
)


def unescape_copy(value):
    r"""Une valeur d'un bloc COPY, dés-échappée. « \N » devient None."""
    if value == "\\N":
        return None
    if "\\" not in value:
        return value
    out, index = [], 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            out.append(COPY_ESCAPE.get(value[index + 1], value[index + 1]))
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def backup_manifest(zip_path):
    """Le manifest.json d'une sauvegarde : version, modules, base d'origine."""
    import zipfile

    try:
        with zipfile.ZipFile(zip_path) as archive:
            with archive.open("manifest.json") as handle:
                return json.load(handle)
    except KeyError as exc:
        raise AnalyseError(
            f"{t('Not an Odoo backup (no manifest.json): ')}{zip_path}"
        ) from exc
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        raise AnalyseError(f"{t('Cannot read the backup: ')}{exc}") from exc


def read_backup(zip_path, tables=(), with_columns=()):
    """Lire un dump.sql en flot. -> (manifest, {table: [lignes]}, {table: colonnes}).

    Une seule passe, quelle que soit la taille du dump : on ne garde en mémoire
    que les tables demandées.
    """
    import io
    import zipfile

    manifest = backup_manifest(zip_path)
    set_want = set(tables)
    # True = toutes les tables. Le dump les déclare toutes de toute façon, et
    # on ne sait quelles tables comptent qu'APRÈS avoir lu les champs : les
    # garder toutes coûte quelques centaines de kilo-octets et évite une
    # seconde passe sur un fichier qui peut peser des gigaoctets.
    all_cols = with_columns is True
    set_cols = set() if all_cols else set(with_columns)
    dct_rows = {name: [] for name in set_want}
    dct_columns = {name: set() for name in set_cols}

    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise AnalyseError(f"{t('Cannot read the backup: ')}{exc}") from exc
    with archive:
        if "dump.sql" not in archive.namelist():
            raise AnalyseError(
                f"{t('This backup holds no dump.sql: ')}{zip_path}"
            )
        with archive.open("dump.sql") as raw:
            stream = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
            for line in stream:
                if line.startswith("COPY public."):
                    name = line[len("COPY public.") :].split(" ", 1)[0]
                    if name not in set_want:
                        continue
                    header = line[line.index("(") + 1 : line.rindex(")")]
                    lst_col = [c.strip() for c in header.split(",")]
                    for row in stream:
                        if row.startswith("\\."):
                            break
                        values = row.rstrip("\n").split("\t")
                        dct_rows[name].append(
                            dict(
                                zip(
                                    lst_col, [unescape_copy(v) for v in values]
                                )
                            )
                        )
                elif line.startswith("CREATE TABLE public."):
                    name = line[len("CREATE TABLE public.") :].split(" ", 1)[0]
                    for row in stream:
                        stripped = row.strip()
                        if stripped.startswith(");"):
                            break
                        if not all_cols and name not in set_cols:
                            continue
                        if stripped.upper().startswith(NOT_A_COLUMN):
                            continue
                        column = stripped.split(" ", 1)[0].strip('",')
                        if column:
                            dct_columns.setdefault(name, set()).add(column)
    return manifest, dct_rows, dct_columns


def _describe():
    """Dire ce qu'est ce fichier, et où sont les outils.

    Ce fichier porte un shebang et un nom qui ressemble à celui d'un outil ;
    le lancer ne produisait rien du tout, ce qui se lit comme une panne plutôt
    que comme « ce n'est pas un exécutable ». Il énumère donc ses voisins qui,
    eux, se lancent — la liste vient du disque, elle ne peut pas se périmer
    quand un outil s'ajoute.
    """
    here = os.path.dirname(os.path.abspath(__file__))

    def is_runnable(name):
        """Ce fichier se lance-t-il vraiment ?

        Le nom ne suffit pas : `analyse_diff_tui.py` commence pareil et n'a
        pas de point d'entrée. L'annoncer comme exécutable reproduirait le
        défaut même que cette fonction corrige — promettre une commande qui
        ne fait rien. On regarde donc s'il y a un bloc `__main__`.
        """
        if not (name.startswith("analyse_") and name.endswith(".py")):
            return False
        try:
            with open(os.path.join(here, name), encoding="utf-8") as handle:
                return '__name__ == "__main__"' in handle.read()
        except OSError:
            return False

    lst_tool = sorted(name for name in os.listdir(here) if is_runnable(name))
    print(
        f"📚 {os.path.basename(__file__)} — "
        f"{t('shared library, nothing to run here.')}"
    )
    print()
    if lst_tool:
        print(t("Runnable tools in this directory:"))
        for tool in lst_tool:
            print(f"    ./script/analyse/{tool} -d <database>")
    else:
        print(t("No analysis tool here yet."))
    print()
    print(f"{t('From the menu:')} make todo → Execute → Analyse")


if __name__ == "__main__":
    _describe()
