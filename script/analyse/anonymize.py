#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Remplacer les données d'une copie par des données sans intérêt.

Aucune IA, aucun appel réseau : des mots pris dans une liste et des
nombres tirés au hasard, écrits par des UPDATE SQL. Ce qui rend la chose
délicate n'est pas le remplacement, c'est de savoir CE QU'ON N'A PAS LE
DROIT DE TOUCHER.

Quatre pièges, avec leur ampleur sur une base de production
-----------------------------------------------------------
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
   l'objet, clé par clé. Sans cela, une page rendue depuis ce champ se
   répare dans une langue et reste cassée dans les autres.
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

# PostgreSQL borne ses entiers par TAILLE, et garder la largeur peut viser
# plus haut que la colonne : une valeur à 10 chiffres tire dans
# 10⁹..9 999 999 999, quand `integer` s'arrête à 2 147 483 647 et
# `smallint` à 32 767. Le dépassement lève, et l'écriture tenant en une
# transaction unique, il emporte TOUTE l'anonymisation.
#
# La bande se RÉTRÉCIT donc au plafond, au lieu d'écraser les tirages
# dessus : borner le tirage par `least` mettrait, sur une colonne
# `integer` à 10 chiffres, près de huit valeurs sur dix exactement à
# 2 147 483 647.
PLAFOND_ENTIER = {
    "smallint": 32767,
    "integer": 2147483647,
    "bigint": 9223372036854775807,
}
# `atttypid::regtype::text` rend le nom canonique — `integer`, jamais
# `int4` — mais l'alias circule dans les dumps et les jeux d'essai.
ALIAS_ENTIER = {"int2": "smallint", "int4": "integer", "int8": "bigint"}


def type_entier(pg_type):
    """Le nom canonique du type entier de la colonne, ou None.

    Rend None pour tout ce qui n'est pas un entier borné — `numeric`,
    `double precision`, un texte — où aucun plafond ne s'applique.
    """
    canon = ALIAS_ENTIER.get(pg_type, pg_type)
    return canon if canon in PLAFOND_ENTIER else None


def type_de_coulee(champ):
    """Le type PostgreSQL vers lequel couler un tirage numérique.

    Un `integer` d'Odoo n'implique PAS une colonne entière : une base
    montée de version garde la colonne `numeric` qu'un champ `Float`
    avait créée, `ir_model_fields` disant désormais `integer`. Y couler
    en `integer` lève dès que la valeur dépasse 2 147 483 647 — et comme
    le plafond d'`integer` bornait alors le haut d'une bande dont le bas
    le dépassait déjà, la bande s'INVERSAIT et chaque ligne levait.

    `numeric` n'a pas de plafond : un entier y reste entier par `floor`.
    """
    canon = type_entier(champ.get("pg_type"))
    if champ["ttype"] == "integer":
        return canon or "numeric"
    return canon


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

# Des `char` d'Odoo qui portent une STRUCTURE, pas du texte. Odoo les
# reparse, et un mot y fait lever le serveur entier :
#   parent_path      → `int(id) for id in parent_path.split('/')`
#                      (base/models/res_company.py:117, models.py:203)
#   days_next_month  → `int(self.days_next_month)`
#                      (account/models/account_payment_term.py:321)
# `parent_path` existe sur tout modèle `_parent_store` — sept dans une
# base ordinaire. La sonde de contenu ci-dessous les retrouverait, mais
# les nommer coûte moins cher qu'une requête et ne dépend pas des données
# présentes le jour où l'on passe.
CHAMPS_STRUCTURES = frozenset({"parent_path", "days_next_month"})

# Un chemin d'identifiants : « 1/ », « 1/7/12/ ». Le motif exige les
# barres obliques — sans elles, un numéro de téléphone tout en chiffres
# serait pris pour une structure et échapperait à l'anonymisation, ce
# qui serait un défaut de confidentialité, pas de robustesse.
MOTIF_CHEMIN = r"^[0-9]+(/[0-9]+)*/$"

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

# Les codes de sortie sont un CONTRAT : le menu les lit pour décider s'il
# tire une sauvegarde derrière l'anonymisation. Ils doivent se distinguer
# d'une TRACE PYTHON, qui sort en 1 — lire « tout ce qui n'est ni 0 ni 2 »
# comme du travail annoncé faisait demander la confirmation destructrice
# après un plantage, puis « appliquer » sur un plan jamais calculé.
SORTIE_RIEN = 0  # rien à anonymiser, ou écriture faite
SORTIE_REFUS = 2  # refus, base illisible, écriture en erreur
SORTIE_A_FAIRE = 3  # marche à blanc : du travail est annoncé
SORTIE_SANS_EFFET = 4  # `--apply` n'avait rien à écrire


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
    return raison_du_refus(champ, inclure_connexion) is None


# Pourquoi une colonne n'est pas remplacée. Le rapport n'en NOMME qu'une —
# l'unicité numérique, la seule dont le silence laisserait partir une
# colonne identifiante — mais la raison se LIT ici et ne se redevine pas
# ailleurs : `id` est un entier unique, et c'est le plancher qui le
# refuse. Redevinée depuis le type et l'unicité, elle nommait `id` sur
# CHAQUE modèle, noyant les vrais avertissements ; et une colonne
# `xxx_id`, sous contrainte CHECK ou en jsonb numérique, se confondait de
# la même façon.
REFUS_PLANCHER = "plancher"
REFUS_CONNEXION = "connexion"
REFUS_RELATION = "relation"
REFUS_STRUCTURE = "structure"
REFUS_CONTRAINTE = "contrainte"
REFUS_JSONB_NOMBRE = "jsonb_nombre"
REFUS_NOMBRE_UNIQUE = "nombre_unique"
REFUS_TYPE = "type"


def raison_du_refus(champ, inclure_connexion=False):
    """Pourquoi ce champ n'est pas remplacé, ou None s'il l'est.

    L'ORDRE des contrôles fait la réponse, et c'est la raison d'être de
    cette fonction : plusieurs champs satisfont deux motifs à la fois, et
    seul le PREMIER rencontré est celui qui les écarte.
    """
    if champ["name"] in CHAMPS_INTERDITS:
        return REFUS_PLANCHER
    if champ["name"] in CHAMPS_CONNEXION and not inclure_connexion:
        return REFUS_CONNEXION
    if champ["name"].endswith("_id") or champ["name"].endswith("_ids"):
        # Une relation qui aurait échappé au filtre de ttype.
        return REFUS_RELATION
    if champ["name"] in CHAMPS_STRUCTURES:
        return REFUS_STRUCTURE
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
        return REFUS_CONTRAINTE
    if champ["ttype"] in TYPES_NOMBRE and champ.get("pg_type") == "jsonb":
        # Mesuré sur res_partner.credit_limit : un `float` d'Odoo peut
        # vivre dans un jsonb par société. Y écrire un nombre nu ferait
        # échouer l'UPDATE — et donc, transaction unique oblige, TOUTE
        # l'anonymisation. On s'abstient plutôt que de deviner sa forme.
        return REFUS_JSONB_NOMBRE
    if champ["ttype"] in TYPES_NOMBRE and champ.get("unique"):
        # Un TIRAGE ne garantit rien : `expression_texte` colle l'id sur
        # une colonne unique, un nombre n'a pas cette issue — y coller
        # l'id changerait sa grandeur. Deux lignes au même nombre font
        # échouer l'UPDATE, et transaction unique oblige, TOUTE
        # l'anonymisation avec. Même parade que pour les CHECK et les
        # jsonb numériques : on s'abstient, et le rapport le NOMME.
        return REFUS_NOMBRE_UNIQUE
    if champ["ttype"] in TYPES_TEXTE + TYPES_NOMBRE:
        return None
    return REFUS_TYPE


def abstention_a_nommer(champ, raison):
    """Cette colonne laissée en clair doit-elle être NOMMÉE au rapport ?

    « Laquelle toucher » et « laquelle nommer » sont deux questions.
    L'ordre des contrôles répond à la première : il rend UN motif, le
    premier rencontré. Le réutiliser comme prédicat du rapport taisait
    une colonne numérique unique dès qu'un autre motif la précédait —
    une contrainte CHECK, un jsonb, un nom en `_id` — alors que c'est
    exactement ce que la ligne ⚠ affirme, et exactement la situation pour
    laquelle elle existe.

    Le plancher, lui, reste muet : `id` est un entier unique sur CHAQUE
    modèle, et le nommer partout noyait les vrais avertissements.
    """
    if raison is None or raison == REFUS_PLANCHER:
        return False
    return champ["ttype"] in TYPES_NOMBRE and bool(champ.get("unique"))


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
    l'analyse syntaxique sur « syntax error at or near "user" » — donc,
    transaction unique oblige, TOUTE l'anonymisation. Les citer coûte
    deux caractères et ferme la question pour tous les noms à venir.
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


def expression_calibre(champ):
    """Le SQL qui remplace un nombre en gardant sa LARGEUR.

    8839 tire dans 1000..9999. La décade se lit sur la valeur de chaque
    LIGNE — `log(abs(col))` — et non sur la colonne : une colonne mêle des
    largeurs, et c'est la largeur de la valeur que l'opérateur veut voir
    survivre.

    Trois cas que la règle ne couvre pas, et qui retombent sur l'étendue
    mesurée :

    - `NULL` reste `NULL`, comme partout ;
    - `0` reste `0` : il n'a pas de largeur à garder, et un zéro devenu
      743 fabrique de la donnée là où il n'y en avait pas ;
    - `abs(col) < 1` n'a aucun chiffre avant la virgule. Appliquer la
      règle y tirerait un taux entre 1 et 9, ce que l'étendue mesurée
      existe précisément pour empêcher.

    La partie ENTIÈRE décide, pour un `float` comme pour un `monetary` :
    1234,56 garde ses quatre chiffres et ses deux décimales.

    La bande est rétrécie au plafond du type qui ACCUEILLE le tirage
    quand il en a un — voir `type_de_coulee` et `PLAFOND_ENTIER` : une
    valeur à 10 chiffres coulée en `integer` dépasserait 2 147 483 647, et
    l'écriture tenant en une transaction unique, elle emporterait tout.
    """
    nom = ident(champ["name"])
    entier = champ["ttype"] == "integer"
    # La mesure passe par `numeric` : `abs()` sur le plus petit entier
    # signé lève, sa valeur absolue ne tenant pas dans son propre type.
    mesure = f"abs({nom}::numeric)"
    # Le nombre de CHIFFRES, compté sur le texte de la partie entière.
    # `floor(log(...))` s'en approchait, mais travaille en flottant et
    # `log(999999999999999)` y vaut 15 tout rond : la décade gagnait un
    # rang, et la copie un chiffre. En `numeric`, le compte est exact
    # quelle que soit la grandeur.
    chiffres = f"length(trunc({mesure})::text)"
    decade = f"power(10::numeric, {chiffres} - 1)"
    haut = f"{decade} * 10 - 1"
    coulee = type_de_coulee(champ) or "numeric"
    # La bande doit tenir dans le type qui ACCUEILLE le tirage, et il
    # n'est pas toujours celui de la colonne — voir `type_de_coulee`.
    # `numeric` n'a pas de plafond, donc rien à rétrécir.
    if coulee in PLAFOND_ENTIER:
        haut = f"least({haut}, {PLAFOND_ENTIER[coulee]})"
    if entier:
        # Le `+ 1` rend le haut de la bande atteignable : sans lui, 8839
        # ne peut jamais sortir 9999. `random()::numeric` garde le calcul
        # exact là où le flottant perd des rangs au-delà de 2^53.
        tirage = (
            f"(sign({nom}) * floor({decade}"
            f" + random()::numeric * ({haut} - {decade} + 1)))::{coulee}"
        )
    else:
        # Pas de `+ 1` ici : `round(…, 2)` d'un tirage qui touche le haut
        # de la bande rendrait la décade SUIVANTE, soit un chiffre de plus.
        tirage = (
            f"round((sign({nom}) * ({decade}"
            f" + random()::numeric * ({haut} - {decade})))::numeric, 2)"
        )
    # Sous l'unité et sur zéro, l'étendue mesurée reprend la main : c'est
    # elle qui protège un taux, une heure ou une probabilité.
    repli = expression_nombre(champ)
    return (
        f"CASE WHEN {nom} IS NULL THEN NULL"
        f" WHEN {nom} = 0 THEN {nom}"
        f" WHEN {mesure} < 1 THEN ({repli})"
        f" ELSE {tirage} END"
    )


def expression_nombre(champ):
    """Le SQL qui remplace un nombre, DANS l'étendue de la colonne.

    0 à 1000 était l'intention, et c'est faux pour tout nombre qui porte
    un sens borné : `resource.calendar.attendance.hour_from` est un
    `float` qui vaut une heure de la journée, et un tirage à 957 y fait
    lever Odoo :

        time(int(integral), ...)  →  ValueError: hour must be in 0..23
            resource/models/utils.py:45

    Aucune contrainte PostgreSQL ne dit cela : la borne vit dans le code.
    La seule que les DONNÉES déclarent est leur propre étendue, et c'est
    celle qu'on respecte. Elle protège aussi les pourcentages, les taux et
    les quantités, sans qu'il faille les nommer un par un.

    Sans étendue connue — colonne vide, ou sonde impossible — on retombe
    sur 0 à 1000.
    """
    nom = ident(champ["name"])
    bas, haut = champ.get("borne_min"), champ.get("borne_max")
    entier = champ["ttype"] == "integer"
    # Même règle que pour le calibre : on coule vers le type qui accueille,
    # et un `integer` d'Odoo peut vivre dans une colonne `numeric` dont
    # l'étendue mesurée dépasse 2 147 483 647.
    coulee = type_de_coulee(champ) or "numeric"
    if bas is None or haut is None:
        tirage = (
            f"floor(random() * 1001)::{coulee}"
            if entier
            else "round((random() * 1000)::numeric, 2)"
        )
    elif entier:
        # +1 pour que la borne haute soit atteignable ; si bas == haut,
        # le tirage rend cette valeur, ce qui est sans risque : une
        # colonne constante ne porte aucune information à masquer.
        tirage = f"floor({bas} + random() * ({haut} - {bas} + 1))::{coulee}"
    else:
        tirage = f"round(({bas} + random() * ({haut} - {bas}))::numeric, 2)"
    return f"CASE WHEN {nom} IS NULL THEN NULL ELSE {tirage} END"


def sql_pour_table(table, champs, mots, calibre=False):
    """Un seul UPDATE par table : toutes ses colonnes d'un coup.

    `calibre` échange l'étendue mesurée contre la largeur de chaque
    valeur. Les deux ne tiennent pas ensemble, et c'est l'opérateur qui
    tranche : l'étendue protège les bornes que le CODE d'Odoo impose — une
    heure de la journée, une probabilité — la largeur sert un export relu
    à l'œil ou réimporté dans un champ borné.
    """
    morceaux = []
    for champ in champs:
        if champ["ttype"] in TYPES_TEXTE:
            valeur = expression_texte(champ, mots)
        elif calibre:
            valeur = expression_calibre(champ)
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
                # varchar(n) : n, sinon None. Une poignée de colonnes
                # sont bornées court — des codes à 1, 2 et 3 caractères.
                # Y écrire « jonquille » fait échouer tout l'UPDATE, et
                # donc toute l'anonymisation.
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
    calibre=False,
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
    # Ce qu'on ÉCARTE parce qu'aucune règle mécanique ne sait le
    # remplacer : le rapport le nomme, sans quoi une colonne identifiante
    # reste en clair sans que rien ne le dise.
    abstenus = {}
    for champ in champs:
        if champ["model"] not in retenus:
            continue
        raison = raison_du_refus(champ, inclure_connexion)
        if raison is not None:
            if abstention_a_nommer(champ, raison):
                abstenus.setdefault(champ["model"], []).append(champ["name"])
            continue
        par_modele.setdefault(champ["model"], []).append(champ)
    etapes = []
    for modele in modeles:
        laisses = sorted(abstenus.get(modele, ()))
        liste = par_modele.get(modele)
        sql = (
            sql_pour_table(table_de(modele), liste, mots, calibre)
            if liste
            else None
        )
        if sql:
            etapes.append(
                {
                    "model": modele,
                    "fields": liste,
                    "sql": sql,
                    "abstenus": laisses,
                }
            )
        elif laisses:
            # Une étape SANS travail, qui ne porte que l'avertissement.
            # Un modèle dont la seule colonne anonymisable EST la
            # numérique unique ne produit aucun UPDATE : l'écarter
            # emportait l'avertissement, et le rapport affirmait « rien à
            # anonymiser » sur la colonne même qu'il existe pour nommer.
            etapes.append(
                {
                    "model": modele,
                    "fields": [],
                    "sql": None,
                    "abstenus": laisses,
                }
            )
    return etapes


def sonder_colonnes(database, etapes, config_path=None):
    """Regarder ce que les colonnes CONTIENNENT. Rendre (écartées, bornes).

    Deux mesures, une seule requête par table — sur une liste noire de 410
    modèles, la différence est de 410 allers-retours au lieu de 1 300.

    ÉCARTÉES — les colonnes texte dont TOUT le contenu est un chemin
    d'identifiants. Le filet général, là où `CHAMPS_STRUCTURES` ne nomme
    que le connu : un module maison peut poser le sien sans lui donner ce
    nom. Une seule valeur non conforme suffit à garder la colonne — mieux
    vaut anonymiser une colonne douteuse que taire une donnée personnelle.

    BORNES — l'étendue réelle de chaque colonne numérique. C'est la seule
    borne que les données déclarent, et elle vaut pour toutes celles que
    le code d'Odoo impose sans que PostgreSQL en sache rien : heures de la
    journée, pourcentages, taux.
    """
    ecartees, bornes = {}, {}
    for etape in etapes:
        textes = [
            champ
            for champ in etape["fields"]
            if champ["ttype"] in TYPES_TEXTE and champ["pg_type"] != "jsonb"
        ]
        nombres = [
            champ
            for champ in etape["fields"]
            if champ["ttype"] in TYPES_NOMBRE and champ["pg_type"] != "jsonb"
        ]
        if not textes and not nombres:
            continue
        morceaux = []
        for champ in textes:
            nom = ident(champ["name"])
            morceaux.append(
                f"count(*) FILTER (WHERE {nom} IS NOT NULL AND {nom} <> '')"
                f" || ':' || count(*) FILTER (WHERE {nom} ~ {litteral(MOTIF_CHEMIN)})"
            )
        for champ in nombres:
            nom = ident(champ["name"])
            morceaux.append(
                f"coalesce(min({nom})::text, '') || ':'"
                f" || coalesce(max({nom})::text, '')"
            )
        sql = (
            "SELECT "
            + " || '\x1f' || ".join(morceaux)
            + f" FROM {ident(table_de(etape['model']))}"
        )
        try:
            brut = lib_analyse.run_psql(
                database, sql, config_path=config_path
            ).strip()
        except Exception:  # noqa: BLE001 - une table illisible ne bloque pas
            continue
        mesures = brut.split(SEP)
        if len(mesures) != len(textes) + len(nombres):
            continue
        for champ, mesure in zip(textes, mesures):
            try:
                remplies, chemins = (int(x) for x in mesure.split(":"))
            except ValueError:
                continue
            if remplies and remplies == chemins:
                ecartees.setdefault(etape["model"], []).append(champ["name"])
        for champ, mesure in zip(nombres, mesures[len(textes) :]):
            bas, _, haut = mesure.partition(":")
            if nombre_valide(bas) and nombre_valide(haut):
                bornes.setdefault(etape["model"], {})[champ["name"]] = (
                    bas,
                    haut,
                )
    return ecartees, bornes


def nombre_valide(texte):
    """Un littéral numérique, et rien d'autre.

    Ces valeurs viennent de la base mais retournent dans du SQL : on ne
    les recopie qu'après avoir vérifié qu'elles sont bien des nombres.
    """
    try:
        float(texte)
    except (TypeError, ValueError):
        return False
    return True


def appliquer_sondes(etapes, ecartees, bornes, mots, calibre=False):
    """Refaire le plan sans les écartées, et avec les bornes mesurées.

    `calibre` est repassé tel quel : refaire le SQL sans lui rendrait la
    marche à blanc et l'écriture différentes, ce qui est exactement ce que
    le rendu séparé existe pour empêcher.
    """
    propre = []
    for etape in etapes:
        exclues = set(ecartees.get(etape["model"], ()))
        mesures = bornes.get(etape["model"], {})
        gardes = []
        for champ in etape["fields"]:
            if champ["name"] in exclues:
                continue
            borne = mesures.get(champ["name"])
            gardes.append(
                {**champ, "borne_min": borne[0], "borne_max": borne[1]}
                if borne
                else champ
            )
        # Pas de garde sur une liste vide : `sql_pour_table` rend None, et
        # le `if sql` ci-dessous l'écarte. Deux vérifications pour la même
        # chose se contredisent un jour.
        sql = sql_pour_table(table_de(etape["model"]), gardes, mots, calibre)
        if sql:
            propre.append({**etape, "fields": gardes, "sql": sql})
        elif etape.get("abstenus"):
            # L'étape perd sa dernière colonne à la sonde, mais porte
            # encore l'avertissement : le garder, faute de quoi il
            # disparaît ici comme il disparaissait du plan.
            propre.append({**etape, "fields": [], "sql": None})
    return propre


def render(etapes, applique=False, verbeux=False):
    """Le rapport. Il dit ce qui est ÉCARTÉ autant que ce qui est pris."""
    if not etapes:
        return f"✅ {t('Nothing to anonymise with these lists.')}"
    # Une étape sans SQL ne porte QU'un avertissement : elle ne compte pas
    # pour du travail, et se dit quand même. C'est le seul cas où la
    # colonne nommée est aussi la seule qu'il y avait à traiter.
    travail = [e for e in etapes if e.get("sql")]
    total = sum(len(e["fields"]) for e in travail)
    tete = (
        (
            f"🎭 {len(travail)} {t('model(s)')}, {total} {t('column(s)')}"
            f" — {t('written') if applique else t('dry run, nothing written')}"
        )
        if travail
        else f"✅ {t('Nothing to anonymise with these lists.')}"
    )
    lignes = [tete, ""]
    for etape in etapes:
        if not etape.get("sql"):
            lignes.append(f"   {etape['model']}")
            lignes.append(
                f"        ⚠ {t('left in clear, numeric and unique:')}"
                f" {', '.join(etape.get('abstenus') or ())}"
            )
            continue
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
        abstenus = etape.get("abstenus") or []
        if abstenus:
            # Une colonne numérique UNIQUE reste en clair : aucun tirage
            # ne garantit son unicité, et y coller l'id changerait sa
            # grandeur. Le taire laisserait une colonne identifiante
            # partir sans que rien ne le dise.
            lignes.append(
                f"        ⚠ {t('left in clear, numeric and unique:')}"
                f" {', '.join(abstenus)}"
            )
        if verbeux:
            for champ in etape["fields"]:
                lignes.append(
                    f"        {champ['name']:<30} {champ['ttype']}"
                    f" / {champ['pg_type']}"
                )
    if travail and not applique:
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
    # Une étape sans SQL ne porte qu'un avertissement pour le rapport.
    sql = "\n".join(e["sql"] for e in etapes if e.get("sql"))

    # PAR FICHIER, jamais par `-c`. Linux plafonne un seul argument à
    # MAX_ARG_STRLEN — 32 pages, soit 131 072 octets. Le SQL de la liste
    # noire dépasse ce plafond dès quelques centaines de modèles, et `-c`
    # rend alors « OSError: [Errno 7] Argument list too long ». Le mode
    # qui couvre le plus est justement celui qui casse.
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
    parser.add_argument(
        "--keep-digits",
        action="store_true",
        help=t("draw a number of the same width; drops the extent"),
    )
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
        args.keep_digits,
    )
    # La sonde AVANT le rendu : la marche à blanc doit montrer ce que
    # `--apply` ferait, pas une approximation plus large.
    ecartees, bornes = sonder_colonnes(args.database, etapes, args.config)
    etapes = appliquer_sondes(etapes, ecartees, bornes, mots, args.keep_digits)
    if ecartees:
        combien = sum(len(v) for v in ecartees.values())
        print(
            f"🧭 {combien} {t('column(s) hold identifier paths and are left')}"
            f" {t('alone:')}"
        )
        for modele in sorted(ecartees):
            print(f"     {modele} : {', '.join(sorted(ecartees[modele]))}")
        print()

    # Une étape sans SQL ne porte qu'un avertissement : la compter pour du
    # travail ferait confirmer une écriture qui n'aurait pas lieu.
    travail = any(e.get("sql") for e in etapes)
    if not args.apply:
        print(render(etapes, applique=False, verbeux=args.verbose))
        return SORTIE_A_FAIRE if travail else SORTIE_RIEN

    if not travail:
        # Sans cette sortie, `ecrire` remettait un script VIDE à psql, qui
        # rend 0 : l'appelant lisait « écriture faite » et tirait une
        # sauvegarde de la base intacte en l'annonçant anonymisée.
        print(render(etapes, applique=False, verbeux=args.verbose))
        print(f"↩️  {t('Nothing was written:')} {t('nothing to do.')}")
        return SORTIE_SANS_EFFET

    erreur = ecrire(args.database, etapes, args.config)
    if erreur:
        print(f"❌ {t('Nothing was written:')} {erreur}", file=sys.stderr)
        return SORTIE_REFUS
    print(render(etapes, applique=True, verbeux=args.verbose))
    return SORTIE_RIEN


if __name__ == "__main__":
    sys.exit(main())
