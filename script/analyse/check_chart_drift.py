#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'une montée de version ajoute au référentiel comptable, sans le dire.

Le cas qui a fait écrire cet outil, mesuré sur une migration 12 → 18 :

    palier 17 :  96 comptes,  32 taxes, 14 positions,   0 groupe
    palier 18 : 427 comptes,  64 taxes, 28 positions, 168 groupes

Le script de migration de `l10n_ca` recharge le plan canadien `ca_2023`
par `try_loading(...)` SANS `force_create=False` — 31 des 33 scripts de
localisation du noyau le passent, trois l'oublient. Les codes du client
(sa propre numérotation) ne recouvrent celui du gabarit que sur 15 codes
sur 341 : les 326 autres ont été CRÉÉS.

Rien n'est détruit — les écritures ne bougent pas, les journaux gardent
leurs comptes. Mais trois écrans se remplissent de doublons, et surtout
les 168 groupes RECLASSENT les comptes du client : un compte fournisseurs
de 1067 écritures apparaît sous « Residential Mortgage Loans ».

Pourquoi une comparaison, et non un compte absolu
-------------------------------------------------
« 427 comptes » ne dit rien : un plan peut légitimement en compter mille.
Ce qui se juge, c'est l'ÉCART entre deux paliers de la même migration, et
la signature qui l'accompagne — des comptes ajoutés sans une écriture,
des noms qui deviennent homonymes, une grille de regroupement qui
apparaît là où il n'y en avait aucune.

L'outil ne répare rien. Il ne peut pas : la clé naturelle de suppression
attrape aussi des comptes du client réappariés par code, et douze des
comptes ajoutés sont accrochés en ON DELETE SET NULL. La bonne réponse
est de rejouer le palier avec le correctif, pas d'opérer la base livrée.
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

COULEURS = {
    "broken": "\033[31m",
    "watch": "\033[33m",
    "ok": "\033[32m",
    "step": "\033[36m",
    "dim": "\033[90m",
}
RESET = "\033[0m"


def paint(texte, genre, colour):
    """Teinter, ou rendre le texte tel quel quand la couleur est coupée."""
    if not colour:
        return texte
    return f"{COULEURS.get(genre, '')}{texte}{RESET}"


# Ce que le référentiel comptable porte, et ce qu'un gonflement y veut
# dire. `gravity` suit la règle du dépôt : `broken` pour ce qui est faux
# en soi, `watch` pour ce qui mérite un regard.
TABLES = (
    {
        "key": "account",
        "table": "account_account",
        "title": "Accounts in the chart",
        "why": "A reloaded chart template adds every account it could not"
        " match by code. They carry no entry, and they bury the"
        " customer's own chart.",
        "gravity": "broken",
    },
    {
        "key": "tax",
        "table": "account_tax",
        "title": "Taxes",
        "why": "Reloaded taxes are not renamed '[old]': the duplicates are"
        " indistinguishable in the interface.",
        "gravity": "broken",
    },
    {
        "key": "fiscal_position",
        "table": "account_fiscal_position",
        "title": "Fiscal positions",
        "why": "Each province then appears twice, under the same name.",
        "gravity": "broken",
    },
    {
        "key": "group",
        "table": "account_group",
        "title": "Account groups",
        "why": "Groups are matched to accounts by code PREFIX: a grid that"
        " appears reclassifies the customer's own accounts, and the trial"
        " balance in hierarchy mode follows.",
        "gravity": "broken",
    },
    {
        "key": "journal",
        "table": "account_journal",
        "title": "Journals",
        "why": "A journal added by a template reload competes with the"
        " customer's own.",
        "gravity": "watch",
    },
)


def compte(database, table, **kwargs):
    """Combien de lignes, ou None si la table n'existe pas."""
    existe = lib_analyse.scalar_query(
        database,
        f"SELECT (to_regclass('public.{table}') IS NOT NULL)::text;",
        **kwargs,
    )
    if (existe or "").strip().lower() != "true":
        return None
    brut = lib_analyse.scalar_query(
        database, f"SELECT count(*) FROM {table};", **kwargs
    )
    try:
        return int(brut)
    except (TypeError, ValueError):
        return None


def comptes_sans_ecriture(database, **kwargs):
    """(comptes, ceux qui ne portent aucune écriture).

    C'est la signature d'un gabarit rechargé : un plan vécu a des comptes
    vides, mais pas trois cents d'un coup.
    """
    lignes = lib_analyse.json_query(
        database,
        "SELECT count(*) AS total,"
        " count(*) FILTER (WHERE NOT EXISTS ("
        "   SELECT 1 FROM account_move_line l WHERE l.account_id = a.id"
        " )) AS sans_ecriture"
        " FROM account_account a",
        **kwargs,
    )
    if not lignes:
        return None, None
    return lignes[0].get("total"), lignes[0].get("sans_ecriture")


def homonymes(database, table, **kwargs):
    """Combien de noms portés par plus d'une ligne.

    Le rechargement ne renomme pas ce qu'il double : dans l'interface,
    deux lignes du même nom ne se distinguent pas.
    """
    brut = lib_analyse.scalar_query(
        database,
        "SELECT coalesce(sum(n - 1), 0) FROM ("
        f"  SELECT count(*) AS n FROM {table}"
        "   GROUP BY name->>'en_US' HAVING count(*) > 1) x;",
        **kwargs,
    )
    try:
        return int(brut)
    except (TypeError, ValueError):
        return None


def reclasses(database, **kwargs):
    """Combien de comptes tombent sous un groupe, par préfixe de code.

    Rejoue ce que fait `_compute_account_group` : le groupe dont le
    préfixe encadre le code, le plus spécifique d'abord.
    """
    brut = lib_analyse.scalar_query(
        database,
        "SELECT count(*) FROM ("
        "  SELECT a.id, a.code_store->>'1' AS code FROM account_account a"
        ") c JOIN LATERAL ("
        "  SELECT ag.id FROM account_group ag"
        "   WHERE ag.code_prefix_start <="
        "         left(c.code, char_length(ag.code_prefix_start))"
        "     AND ag.code_prefix_end >="
        "         left(c.code, char_length(ag.code_prefix_end))"
        "   ORDER BY char_length(ag.code_prefix_start) DESC, ag.id"
        "   LIMIT 1) g ON true;",
        **kwargs,
    )
    try:
        return int(brut)
    except (TypeError, ValueError):
        return None


def previous_database(database, dct=None):
    """Le palier qui précède celui-ci, lu dans la chaîne de la migration.

    On ne le devine pas depuis le nom : la base de DÉPART ne porte pas de
    suffixe, et retrancher 1 à « _upgrade_18 » donnerait « _upgrade_17 »
    même quand la chaîne n'est pas contiguë.
    """
    dct = quality.read_progression() if dct is None else dct
    chaine = quality.chain(dct)
    for rang, (_version, base) in enumerate(chaine):
        if base == database and rang:
            return chaine[rang - 1][1]
    return None


def inspect(after, before, **kwargs):
    """Ce que le dernier palier ajoute au référentiel du précédent."""
    rapport = {"before": before, "after": after, "tables": [], "signes": {}}
    for entree in TABLES:
        avant = compte(before, entree["table"], **kwargs)
        apres = compte(after, entree["table"], **kwargs)
        rapport["tables"].append(
            {
                "key": entree["key"],
                "table": entree["table"],
                "before": avant,
                "after": apres,
                "delta": (
                    None if avant is None or apres is None else apres - avant
                ),
            }
        )

    total, vides = comptes_sans_ecriture(after, **kwargs)
    rapport["signes"]["accounts"] = total
    rapport["signes"]["accounts_without_entry"] = vides
    for table, clef in (
        ("account_tax", "tax_homonyms"),
        ("account_fiscal_position", "fiscal_position_homonyms"),
    ):
        rapport["signes"][clef] = homonymes(after, table, **kwargs)
    if compte(after, "account_group", **kwargs):
        rapport["signes"]["accounts_regrouped"] = reclasses(after, **kwargs)
    return rapport


def judge(rapport):
    """[(entrée, écart)] pour ce qui a gonflé, du plus grave au moins."""
    par_clef = {e["key"]: e for e in TABLES}
    trouve = [
        (par_clef[ligne["key"]], ligne)
        for ligne in rapport["tables"]
        if ligne["delta"] and ligne["delta"] > 0
    ]
    ordre = {"broken": 0, "watch": 1}
    trouve.sort(
        key=lambda paire: (
            ordre.get(paire[0]["gravity"], 2),
            -paire[1]["delta"],
        )
    )
    return trouve


def render(rapport, colour=True):
    """Le rapport lisible. L'écart d'abord, ce qu'il signifie ensuite."""
    lignes = [
        f"📚 {t('Accounting reference data, one step to the next')}",
        paint(f"   {rapport['before']} → {rapport['after']}", "dim", colour),
        "",
    ]
    trouve = judge(rapport)
    if not trouve:
        lignes.append(
            paint(
                f"✅ {t('Nothing was added to the reference data.')}",
                "ok",
                colour,
            )
        )
        return "\n".join(lignes)

    for entree, ligne in trouve:
        icone = "❌" if entree["gravity"] == "broken" else "⚠"
        lignes.append(
            paint(
                f"{icone} {('+' + str(ligne['delta'])).rjust(6)}"
                f"  {t(entree['title'])}"
                f"  ({ligne['before']} → {ligne['after']})",
                entree["gravity"],
                colour,
            )
        )
        lignes.append(paint(f"          {t(entree['why'])}", "dim", colour))
        lignes.append("")

    signes = rapport["signes"]
    lignes.append(paint(f"   {t('What it looks like')}", "step", colour))
    vides = signes.get("accounts_without_entry")
    if vides:
        lignes.append(
            f"      {vides} / {signes.get('accounts')}"
            f" {t('accounts carry no entry at all')}"
        )
    for clef, phrase in (
        ("tax_homonyms", "taxes share a name with another"),
        (
            "fiscal_position_homonyms",
            "fiscal positions share a name with another",
        ),
    ):
        if signes.get(clef):
            lignes.append(f"      {signes[clef]} {t(phrase)}")
    if signes.get("accounts_regrouped"):
        lignes.append(
            f"      {signes['accounts_regrouped']}"
            f" {t('accounts fall under a group by code prefix')}"
        )
    lignes.append("")
    lignes.append(
        paint(
            f"   {t('Replay the step with the fix; do not operate the')}"
            f" {t('delivered database.')}",
            "dim",
            colour,
        )
    )
    return "\n".join(lignes).rstrip()


def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=t("What a version bump adds to the accounting data."),
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument(
        "--before",
        help=t("the step to compare against (default: the previous one)"),
    )
    parser.add_argument("-c", "--config", help="odoo config file")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    before = args.before or previous_database(args.database)
    if not before:
        print(
            f"❌ {t('No previous step found: name it with --before.')}",
            file=sys.stderr,
        )
        return 2
    for base in (before, args.database):
        try:
            lib_analyse.require_odoo_database(base, config_path=args.config)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {exc}", file=sys.stderr)
            return 2

    rapport = inspect(args.database, before, config_path=args.config)
    if args.json:
        print(json.dumps(rapport, indent=2, ensure_ascii=False))
    else:
        colour = sys.stdout.isatty() and not args.no_color
        print(render(rapport, colour))
    return 1 if judge(rapport) else 0


if __name__ == "__main__":
    sys.exit(main())
