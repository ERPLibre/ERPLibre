#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Remplacer les données d'une copie par des données sans intérêt.

Aucune IA, aucun appel réseau : des mots pris dans une liste et des
nombres tirés au hasard, écrits par des UPDATE SQL. Ce qui rend la chose
délicate n'est pas le remplacement, c'est de savoir CE QU'ON N'A PAS LE
DROIT DE TOUCHER.

Quatre pièges, tous mesurés sur une base réelle
-----------------------------------------------
1. « Tous les champs string » n'existe pas. 505 champs `selection` sont
   stockés en varchar : `res.partner.lang`, `sale.order.invoice_status`.
   Y écrire un mot au hasard casse l'ORM, pas la confidentialité. On ne
   se fie donc jamais au type PostgreSQL seul, mais au `ttype` que
   `ir_model_fields` déclare.
2. 2693 champs `many2one` sont des ENTIERS. Les tirer au hasard
   mélangerait toutes les relations de la base. Les nombres qu'on touche
   sont ceux qu'Odoo appelle integer, float ou monetary — jamais une
   relation.
3. 194 champs texte sont en `jsonb` depuis Odoo 17, un objet par langue.
   Écrire une chaîne par-dessus détruit la colonne ; on reconstruit
   l'objet, clé par clé. C'est le piège qui a déjà coûté un /contact
   réparé en anglais et resté cassé en français.
4. 301 contraintes d'unicité. Deux lignes qui reçoivent le même mot font
   échouer tout l'UPDATE. Sur une colonne unique, l'identifiant est
   collé au mot.

Ce qu'on ne touche jamais
-------------------------
Les modèles `ir.*` — vues, champs, xmlid : la base ne s'ouvrirait plus.
Les langues, devises et pays : ce ne sont pas des données personnelles,
et les casser casse les adresses et les montants. Cette liste est un
PLANCHER : aucune liste blanche ne la lève.

`res.users.login` et le mot de passe restent en place par défaut. On
anonymise pour POUVOIR partager une copie utilisable ; personne ne
pourrait plus s'y connecter. `--include-logins` pour l'autre choix.

Rien n'est écrit sans `--apply` ET `--confirm <nom de la base>`.
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


from script.analyse import lib_analyse  # noqa: E402

TYPES_TEXTE = ("char", "text", "html")
TYPES_NOMBRE = ("integer", "float", "monetary")

# Le plancher : aucune liste blanche ne le lève.
PREFIXES_INTERDITS = ("ir.",)
MODELES_INTERDITS = frozenset(
    {
        "res.groups",
        "res.lang",
        "res.currency",
        "res.currency.rate",
        "res.country",
        "res.country.state",
        "res.country.group",
        "res.config.settings",
        "base.language.install",
        "decimal.precision",
        "uom.uom",
        "uom.category",
    }
)
CHAMPS_INTERDITS = frozenset(
    {
        "id",
        "create_uid",
        "write_uid",
        "create_date",
        "write_date",
        "sequence",
        "active",
        "display_name",
        "__last_update",
        "arch_db",
        "arch_fs",
        "key",
        "model",
        "res_model",
        "res_field",
        "state",
        "color",
        "company_id",
    }
)
CHAMPS_CONNEXION = frozenset({"login", "password"})

# Le point de départ du mode hybride : ce qui porte des données
# personnelles dans une base Odoo ordinaire.
MODELES_PAR_DEFAUT = (
    "res.partner",
    "res.users",
    "res.company",
    "res.bank",
    "res.partner.bank",
    "crm.lead",
    "hr.employee",
    "mail.message",
    "mail.tracking.value",
    "account.move",
    "sale.order",
    "purchase.order",
    "project.task",
    "calendar.event",
    "survey.user_input",
)

MOTS_PAR_DEFAUT = (
    "alouette",
    "bruyere",
    "cascade",
    "dolmen",
    "erable",
    "fougere",
    "givre",
    "hameau",
    "iris",
    "jonquille",
    "lichen",
    "marais",
    "nenuphar",
    "orme",
    "pinson",
    "roseau",
    "sureau",
    "tourbe",
    "varech",
    "zephyr",
)

MODES = ("whitelist", "blacklist", "hybrid")


def modele_interdit(modele):
    """Le plancher, en une question."""
    if any(modele.startswith(p) for p in PREFIXES_INTERDITS):
        return True
    return modele in MODELES_INTERDITS


def choisir_modeles(tous, mode, whitelist=(), blacklist=(), defauts=None):
    """Quels modèles anonymiser, selon le mode.

    whitelist : ceux-là et rien d'autre.
    blacklist : tous SAUF ceux-là.
    hybrid    : la liste par défaut, plus la blanche, moins la noire —
                c'est le mode utile en pratique : on part de ce qui porte
                des données personnelles et on ajuste aux marges.

    Le plancher s'applique aux trois : un modèle `ir.*` ne passe par
    aucun chemin, même nommé explicitement.
    """
    tous = set(tous)
    blanche, noire = set(whitelist), set(blacklist)
    if mode == "whitelist":
        choisis = blanche & tous
    elif mode == "blacklist":
        choisis = tous - noire
    elif mode == "hybrid":
        base = set(MODELES_PAR_DEFAUT if defauts is None else defauts)
        choisis = ((base | blanche) - noire) & tous
    else:
        raise ValueError(f"{t('Unknown mode:')} {mode}")
    return sorted(m for m in choisis if not modele_interdit(m))


def champ_retenu(champ, inclure_connexion=False):
    """Ce champ-là se remplace-t-il ?

    `champ` : dict avec model, name, ttype, pg_type, unique.
    """
    if champ["name"] in CHAMPS_INTERDITS:
        return False
    if champ["name"] in CHAMPS_CONNEXION and not inclure_connexion:
        return False
    if champ["name"].endswith("_id") or champ["name"].endswith("_ids"):
        # Une relation qui aurait échappé au filtre de ttype.
        return False
    if champ.get("checked"):
        # Une contrainte CHECK hors de portée. Mesuré, et la distinction
        # compte : sur un NOMBRE toute contrainte borne la valeur —
        # crm_lead.probability entre 0 et 100, credit * debit = 0 — et un
        # tirage à 1000 fait échouer l'UPDATE, donc toute l'anonymisation.
        # Sur du TEXTE, presque toutes ne garantissent que la non-nullité :
        # `res_partner.name` n'exige d'être non nul que pour un contact, ce
        # qu'un mot satisfait. Les écarter TOUTES laissait le champ le plus
        # important de la base intact — une anonymisation qui n'anonymisait
        # pas les noms. La requête ne lève donc ce drapeau, pour du texte,
        # que sur les contraintes de FORME.
        return False
    if champ["ttype"] in TYPES_NOMBRE and champ.get("pg_type") == "jsonb":
        # Mesuré sur res_partner.credit_limit : un `float` d'Odoo peut
        # vivre dans un jsonb par société. Y écrire un nombre nu ferait
        # échouer l'UPDATE — et donc, transaction unique oblige, TOUTE
        # l'anonymisation. On s'abstient plutôt que de deviner sa forme.
        return False
    return champ["ttype"] in TYPES_TEXTE + TYPES_NOMBRE


def mots_pour(nom_champ, mots):
    """La liste de mots à utiliser pour ce champ.

    `mots` peut être une simple liste — la même partout — ou un
    dictionnaire par nom de champ avec une entrée `*` en repli. Le
    dictionnaire permet de garder des courriels qui ressemblent à des
    courriels, ce qu'une liste unique ne sait pas faire.
    """
    if isinstance(mots, dict):
        choix = mots.get(nom_champ) or mots.get("*") or MOTS_PAR_DEFAUT
    else:
        choix = mots or MOTS_PAR_DEFAUT
    return tuple(str(m) for m in choix) or MOTS_PAR_DEFAUT


def litteral(texte):
    """Un littéral SQL. Le seul endroit où du texte entre dans la requête."""
    return "'" + str(texte).replace("'", "''") + "'"


def ident(nom):
    """Un identifiant SQL, cité.

    Odoo laisse nommer un champ `user`, `order` ou `group` : ce sont des
    mots réservés de PostgreSQL, et un identifiant nu fait échouer
    l'analyse syntaxique — donc, transaction unique oblige, TOUTE
    l'anonymisation. Mesuré en liste noire sur une base réelle :
    « syntax error at or near "user" ». Les citer coûte deux caractères
    et ferme la question pour tous les noms à venir.
    """
    return '"' + str(nom).replace('"', '""') + '"'


def expression_texte(champ, mots):
    """Le SQL qui remplace un champ texte, en préservant les NULL.

    Un NULL qui deviendrait un mot créerait de la donnée là où il n'y en
    avait pas : la copie mentirait dans l'autre sens.
    """
    nom = ident(champ["name"])
    liste = mots_pour(champ["name"], mots)
    # Les parenthèses ne sont pas décoratives : PostgreSQL refuse
    # d'indexer un constructeur ARRAY[...] directement.
    tableau = "(ARRAY[" + ",".join(litteral(m) for m in liste) + "])"
    tirage = f'{tableau}[("id" % {len(liste)}) + 1]'
    borne = champ.get("max_len")
    if champ.get("unique"):
        # Deux lignes qui reçoivent le même mot feraient échouer TOUT
        # l'UPDATE sur une colonne unique. L'identifiant vient EN TÊTE
        # quand la colonne est bornée : c'est lui qui porte l'unicité, et
        # une troncature par la droite doit le laisser intact.
        if borne:
            tirage = f"\"id\"::text || '-' || {tirage}"
        else:
            tirage = f"{tirage} || '-' || \"id\"::text"
    if borne:
        # varchar(n) : mesuré, 13 colonnes sont bornées sur une base
        # réelle, dont des codes à 1, 2 et 3 caractères. « jonquille »
        # dans un varchar(3) fait échouer l'UPDATE entier.
        tirage = f"left({tirage}, {borne})"
    if champ.get("pg_type") == "jsonb":
        # Un objet par langue depuis Odoo 17 : on le reconstruit clé à
        # clé. Écrire une chaîne par-dessus détruirait la colonne.
        return (
            f"CASE WHEN {nom} IS NULL THEN NULL ELSE"
            f" (SELECT jsonb_object_agg(kv.key, {tirage})"
            f" FROM jsonb_each_text({nom}) AS kv) END"
        )
    return f"CASE WHEN {nom} IS NULL THEN NULL ELSE {tirage} END"


def expression_nombre(champ):
    """Le SQL qui remplace un nombre : au hasard, entre 0 et 1000."""
    nom = ident(champ["name"])
    if champ["ttype"] == "integer":
        tirage = "floor(random() * 1001)::integer"
    else:
        tirage = "round((random() * 1000)::numeric, 2)"
    return f"CASE WHEN {nom} IS NULL THEN NULL ELSE {tirage} END"


def sql_pour_table(table, champs, mots):
    """Un seul UPDATE par table : toutes ses colonnes d'un coup."""
    morceaux = []
    for champ in champs:
        if champ["ttype"] in TYPES_TEXTE:
            valeur = expression_texte(champ, mots)
        else:
            valeur = expression_nombre(champ)
        morceaux.append(f"{ident(champ['name'])} = {valeur}")
    if not morceaux:
        return None
    return f"UPDATE {ident(table)} SET " + ", ".join(morceaux) + ";"


def table_de(modele):
    """Le nom de table qu'Odoo donne à ce modèle."""
    return modele.replace(".", "_")


SEP = "\x1f"

# On croise TROIS sources, et c'est la raison d'être de cette requête :
# `ir_model_fields` dit ce qu'Odoo croit (le ttype, seul capable de
# distinguer un `selection` d'un vrai texte), `pg_attribute` dit ce que
# PostgreSQL a vraiment (jsonb ou varchar), et `pg_constraint` dit ce qui
# doit rester unique. Aucune des trois ne suffit seule.
REQUETE_CHAMPS = """
SELECT f.model || '\x1f' || f.name || '\x1f' || f.ttype || '\x1f'
       || a.atttypid::regtype::text || '\x1f'
       || CASE WHEN EXISTS (
              SELECT 1 FROM pg_constraint k
               WHERE k.conrelid = c.oid
                 AND k.contype IN ('u', 'p')
                 AND a.attnum = ANY(k.conkey)
          ) THEN '1' ELSE '0' END || '\x1f'
       || CASE WHEN EXISTS (
              SELECT 1 FROM pg_constraint k
               WHERE k.conrelid = c.oid
                 AND k.contype = 'c'
                 AND a.attnum = ANY(k.conkey)
                 AND (
                     -- Sur un NOMBRE, toute contrainte borne la valeur :
                     -- `credit * debit = 0`, `amount >= 0`. On s'abstient.
                     f.ttype IN ('integer','float','monetary')
                     -- Sur du TEXTE, presque toutes ne garantissent que la
                     -- non-nullité, ce qu'un mot satisfait. Seules celles
                     -- qui contraignent la FORME sont hors de portée.
                     OR pg_get_constraintdef(k.oid) ~
                        'char_length|~~|jsonb_typeof|similar to'
                 )
          ) THEN '1' ELSE '0' END || '\x1f'
       || CASE WHEN a.atttypmod > 4
               THEN (a.atttypmod - 4)::text ELSE '' END
  FROM ir_model_fields f
  JOIN pg_class c ON c.relname = replace(f.model, '.', '_')
                 AND c.relkind = 'r'
  JOIN pg_attribute a ON a.attrelid = c.oid
                     AND a.attname = f.name
                     AND a.attnum > 0
                     AND NOT a.attisdropped
 WHERE f.store
   AND f.ttype IN ('char','text','html','integer','float','monetary')
 ORDER BY f.model, f.name
"""


def inspect(database, config_path=None):
    """Tous les champs remplaçables de la base, avec leurs trois vérités."""
    brut = lib_analyse.run_psql(
        database, REQUETE_CHAMPS, config_path=config_path
    )
    champs = []
    for ligne in brut.splitlines():
        parts = ligne.split(SEP)
        if len(parts) != 7:
            continue
        champs.append(
            {
                "model": parts[0],
                "name": parts[1],
                "ttype": parts[2],
                "pg_type": parts[3],
                "unique": parts[4] == "1",
                "checked": parts[5] == "1",
                # varchar(n) : n, sinon None. Mesuré sur une base réelle,
                # 13 colonnes sont bornées — dont des codes à 1, 2 et 3
                # caractères. Y écrire « jonquille » fait échouer tout
                # l'UPDATE, et donc toute l'anonymisation.
                "max_len": int(parts[6]) if parts[6].isdigit() else None,
            }
        )
    return champs


def plan(
    champs,
    mode,
    whitelist=(),
    blacklist=(),
    inclure_connexion=False,
    mots=None,
):
    """Ce qui sera écrit, table par table — avant d'écrire quoi que ce soit.

    Rendu séparément de l'exécution pour que le mode « à blanc » montre
    EXACTEMENT ce que `--apply` ferait, et non une approximation.
    """
    modeles = choisir_modeles(
        {c["model"] for c in champs}, mode, whitelist, blacklist
    )
    retenus = set(modeles)
    par_modele = {}
    for champ in champs:
        if champ["model"] not in retenus:
            continue
        if not champ_retenu(champ, inclure_connexion):
            continue
        par_modele.setdefault(champ["model"], []).append(champ)
    etapes = []
    for modele in modeles:
        liste = par_modele.get(modele)
        if not liste:
            continue
        sql = sql_pour_table(table_de(modele), liste, mots)
        if sql:
            etapes.append({"model": modele, "fields": liste, "sql": sql})
    return etapes


def render(etapes, applique=False, verbeux=False):
    """Le rapport. Il dit ce qui est ÉCARTÉ autant que ce qui est pris."""
    if not etapes:
        return f"✅ {t('Nothing to anonymise with these lists.')}"
    total = sum(len(e["fields"]) for e in etapes)
    tete = (
        f"🎭 {len(etapes)} {t('model(s)')}, {total} {t('column(s)')}"
        f" — {t('written') if applique else t('dry run, nothing written')}"
    )
    lignes = [tete, ""]
    for etape in etapes:
        textes = [f for f in etape["fields"] if f["ttype"] in TYPES_TEXTE]
        nombres = [f for f in etape["fields"] if f["ttype"] in TYPES_NOMBRE]
        traduits = [f for f in textes if f["pg_type"] == "jsonb"]
        uniques = [f for f in etape["fields"] if f["unique"]]
        detail = f"{len(textes)} {t('text')}, {len(nombres)} {t('numeric')}"
        if traduits:
            detail += f", {len(traduits)} {t('translated (jsonb)')}"
        if uniques:
            detail += f", {len(uniques)} {t('unique')}"
        lignes.append(f"   {etape['model']:<34} {detail}")
        if verbeux:
            for champ in etape["fields"]:
                lignes.append(
                    f"        {champ['name']:<30} {champ['ttype']}"
                    f" / {champ['pg_type']}"
                )
    if not applique:
        lignes.append("")
        lignes.append(f"   {t('Use --apply --confirm <database> to write.')}")
    return "\n".join(lignes)


def charger_mots(chemin):
    """Lire un fichier Python qui déclare MOTS.

    Une liste — les mêmes mots partout — ou un dictionnaire par nom de
    champ avec un repli `*`. Aucun réseau, aucun modèle : des mots.
    """
    if not chemin:
        return None
    espace = {}
    with open(chemin, "r", encoding="utf-8") as handle:
        exec(compile(handle.read(), chemin, "exec"), espace)  # noqa: S102
    mots = espace.get("MOTS")
    if not mots:
        raise ValueError(f"{t('This file declares no MOTS:')} {chemin}")
    return mots


def ecrire(database, etapes, config_path=None, timeout=900):
    """Écrire les UPDATE — TOUS, ou AUCUN. None si tout a réussi.

    Une seule transaction (`-1`) et `ON_ERROR_STOP=1`. Sans cela, une
    collision d'unicité au dixième modèle laisserait une base à moitié
    anonymisée — c'est-à-dire une base dont plus personne ne peut dire ce
    qui est vrai, et que rien ne rattrape sinon une restauration.

    On reprend `pg_env` pour la connexion — hôte, port, mot de passe lus
    dans config.conf — et l'on ne lève QUE la lecture seule. La
    redéclarer ici, ce serait accepter qu'elle diverge un jour.
    """
    import subprocess
    import tempfile

    env = lib_analyse.pg_env(config_path, timeout=timeout)
    env["PGOPTIONS"] = f"-c statement_timeout={timeout}s"
    sql = "\n".join(etape["sql"] for etape in etapes)

    # PAR FICHIER, jamais par `-c`. Linux plafonne un seul argument à
    # MAX_ARG_STRLEN — 32 pages, soit 131 072 octets. Mesuré sur une base
    # réelle : le mode hybride tient dans 58 Ko et passait, la liste noire
    # produit 342 Ko sur 410 modèles et rendait « OSError: [Errno 7]
    # Argument list too long ». Le mode qui couvre le plus est justement
    # celui qui cassait.
    #
    # `-f` plutôt que l'entrée standard : `--single-transaction` n'est
    # documenté qu'avec `-c` ou `-f`, et c'est lui qui garantit le tout
    # ou rien. Le perdre en silence serait pire que le message d'erreur.
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".sql",
        prefix="el_anonymize_",
        encoding="utf-8",
        delete=False,
    )
    try:
        handle.write(sql)
        handle.close()
        done = subprocess.run(
            [
                "psql",
                "-X",
                "-w",
                "-1",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                database,
                "-tA",
                "-f",
                handle.name,
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout + 60,
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    if done.returncode:
        detail = (done.stderr or "").strip().splitlines()
        return detail[0][:200] if detail else "psql"
    return None


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description=t("Replace the data of a COPY with meaningless data."),
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", help="odoo config file")
    parser.add_argument("--mode", choices=MODES, default="hybrid")
    parser.add_argument(
        "--models", default="", help=t("comma separated, adds to the mode")
    )
    parser.add_argument(
        "--exclude", default="", help=t("comma separated, removed from it")
    )
    parser.add_argument("--words", help=t("python file declaring MOTS"))
    parser.add_argument("--include-logins", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm",
        default="",
        help=t("repeat the database name; --apply refuses without it"),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    # Le garde-fou, AVANT toute lecture : personne ne doit découvrir en
    # route qu'il a lancé cela sur la mauvaise base.
    if args.apply and args.confirm != args.database:
        print(
            f"❌ {t('Refusing to write: --confirm must repeat')}"
            f" '{args.database}'.",
            file=sys.stderr,
        )
        return 2

    try:
        lib_analyse.require_odoo_database(
            args.database, config_path=args.config
        )
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    try:
        mots = charger_mots(args.words)
        champs = inspect(args.database, args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    etapes = plan(
        champs,
        args.mode,
        [m.strip() for m in args.models.split(",") if m.strip()],
        [m.strip() for m in args.exclude.split(",") if m.strip()],
        args.include_logins,
        mots,
    )
    if not args.apply:
        print(render(etapes, applique=False, verbeux=args.verbose))
        return 1 if etapes else 0

    erreur = ecrire(args.database, etapes, args.config)
    if erreur:
        print(f"❌ {t('Nothing was written:')} {erreur}", file=sys.stderr)
        return 2
    print(render(etapes, applique=True, verbeux=args.verbose))
    return 0


if __name__ == "__main__":
    sys.exit(main())
