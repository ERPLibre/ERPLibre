#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les réglages qu'Odoo ne recrée qu'à des moments qu'une migration évite.

Certains enregistrements de configuration ont cessé d'être LIVRÉS en
données et sont devenus le produit d'un geste : créer une société,
changer de devise, cocher une case, charger un plan comptable. Une
migration ne fait aucun de ces gestes. L'enregistrement part avec le
nettoyage des orphelins et rien ne le remet.

Deux cas mesurés sur une chaîne 12 → 18 réelle :

  liste de prix          `product.list0` est déclaré jusqu'en 16 et plus
                         après. Odoo 18 crée les listes par défaut dans
                         `_activate_or_create_pricelists()`, appelée à la
                         création d'une société, au changement de devise
                         et au basculement du réglage. Résultat : 1 liste
                         en 16, 0 en 17 et en 18, alors que le groupe
                         `product.group_product_pricelist` compte six
                         membres. Toute commande s'ouvre alors sans liste
                         de prix — elle ne casse rien, elle facture faux.

  rapprochement bancaire `account.reconciliation_model_default_rule` est
                         déclaré en 12 et plus dès la 13 : la 18 le crée
                         depuis le PLAN COMPTABLE
                         (`_get_account_reconcile_model`), qu'une montée
                         de version ne recharge jamais. Résultat : 1 en
                         12, 0 partout ensuite, et plus aucun lettrage
                         automatique sur les journaux de trésorerie.

On n'invente rien : on appelle les méthodes d'Odoo, celles-là mêmes que
le geste manquant aurait appelées. `_load_data` est rejoué avec
`ignore_duplicates`, donc l'outil se relance sans risque.

Lecture seule par défaut. `--apply` écrit, puis RELIT pour vérifier.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

import database_cleanup  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# Les sentinelles de `run_shell`, pas les nôtres : il les impose, et en
# poser d'autres ferait lire un rapport vide.
DEBUT = database_cleanup.START
FIN = database_cleanup.END

SCRIPT = """
import json
DRY = {dry}
rapport = {{"dry_run": DRY}}
try:
    Societe = env["res.company"].sudo()
    societes = Societe.search([])
    rapport["companies"] = len(societes)

    # ── Listes de prix ──────────────────────────────────────────────
    if "product.pricelist" in env:
        Liste = env["product.pricelist"].sudo().with_context(active_test=False)
        rapport["pricelist_before"] = Liste.search_count([])
        # Ce qui décide, c'est la FONCTIONNALITÉ, pas l'appartenance de
        # celui qui exécute. `has_group` était vrai ici parce que six
        # utilisateurs sont membres directs du groupe — hérité d'un
        # palier de migration — alors que la case de configuration était
        # décochée. On créait donc une liste de prix dans une base dont
        # la fonctionnalité est éteinte, et Odoo prévenait à chaque
        # ouverture des réglages qu'il allait l'archiver.
        #
        # `res.config.settings` lit ce que `base.group_user` IMPLIQUE
        # (res_config.py : « which groups are implied by the group
        # Employee ») : c'est la même question qu'on pose ici.
        fonction = env.ref("product.group_product_pricelist", False)
        employe = env.ref("base.group_user", False)
        rapport["pricelist_group"] = bool(
            fonction and employe and fonction in employe.implied_ids
        )
        if not DRY and rapport["pricelist_group"]:
            Societe._activate_or_create_pricelists()
            env.cr.commit()
        rapport["pricelist_after"] = Liste.search_count([])
    else:
        rapport["pricelist_absent"] = True

    # ── Modèles de rapprochement bancaire ───────────────────────────
    if "account.reconcile.model" in env:
        Modele = env["account.reconcile.model"].sudo()
        rapport["reconcile_before"] = Modele.search_count([])
        # Sans journal de trésorerie il n'y a rien à rapprocher : créer
        # des modèles là serait du bruit dans un menu qu'on n'ouvre pas.
        rapport["cash_journals"] = env["account.journal"].sudo().search_count(
            [("type", "in", ("bank", "cash"))]
        )
        rapport["charts"] = sorted(
            {{s.chart_template for s in societes if s.chart_template}}
        )
        if not DRY and rapport["cash_journals"] and rapport["charts"]:
            Gabarit = env["account.chart.template"].sudo()
            for societe in societes:
                if not societe.chart_template:
                    continue
                donnees = Gabarit._get_account_reconcile_model(
                    societe.chart_template
                )
                if not donnees:
                    continue
                # `_load_data` est le chemin d'Odoo : il pose les xmlid
                # préfixés par la société, donc un rechargement futur du
                # plan comptable ne fera pas de doublon.
                Gabarit.with_company(societe)._load_data(
                    {{"account.reconcile.model": donnees}},
                    ignore_duplicates=True,
                )
            env.cr.commit()
        rapport["reconcile_after"] = Modele.search_count([])
    else:
        rapport["reconcile_absent"] = True
except Exception as exc:
    rapport["error"] = "%s: %s" % (type(exc).__name__, exc)
print({debut!r})
print(json.dumps(rapport))
print({fin!r})
"""


def build_script(dry_run):
    return SCRIPT.format(
        dry="True" if dry_run else "False", debut=DEBUT, fin=FIN
    )


def pricelist_missing(rapport, apres=False):
    """Une liste manque-t-elle vraiment ?

    Pas de liste ET le groupe actif : la fonctionnalité est offerte aux
    utilisateurs et ne répond rien. Groupe éteint, l'absence est normale.

    `apres` regarde le compte D'APRÈS la réparation. Sans ce choix, un
    `--apply` réussi se conclurait toujours par « il en manque encore » :
    le compte d'avant, lui, reste à zéro pour l'éternité.
    """
    if rapport.get("pricelist_absent"):
        return False
    if not rapport.get("pricelist_group"):
        return False
    cle = "pricelist_after" if apres else "pricelist_before"
    return not rapport.get(cle)


def reconcile_missing(rapport, apres=False):
    """Aucun modèle alors qu'il y a de quoi rapprocher."""
    if rapport.get("reconcile_absent"):
        return False
    if not rapport.get("cash_journals"):
        return False
    cle = "reconcile_after" if apres else "reconcile_before"
    return not rapport.get(cle)


def findings(rapport, apres=False):
    lst = []
    if pricelist_missing(rapport, apres):
        lst.append("pricelist")
    if reconcile_missing(rapport, apres):
        lst.append("reconcile")
    return lst


def render(rapport, dry_run):
    lignes = []
    if not findings(rapport):
        return [f"✅ {t('Every default configuration record is there.')}"]
    lignes.append(
        f"🧾 {t('Configuration records a migration never recreates')}"
    )
    lignes.append("")
    if pricelist_missing(rapport):
        lignes.append(
            f"   💲 {t('No pricelist, and the pricelist feature is on.')}"
        )
        lignes.append(
            f"      {t('Every quotation opens without one: raw price, no rule.')}"
        )
    if reconcile_missing(rapport):
        lignes.append(
            f"   🏦 {t('No bank reconciliation model, for')}"
            f" {rapport.get('cash_journals', 0)} {t('cash/bank journal(s).')}"
        )
        lignes.append(f"      {t('Every statement line is matched by hand.')}")
    lignes.append("")
    if dry_run:
        lignes.append(f"   {t('Use --apply to let Odoo recreate them.')}")
    else:
        lignes.append(
            f"   {t('pricelists:')} {rapport.get('pricelist_before', 0)}"
            f" → {rapport.get('pricelist_after', 0)}"
            f"   ·   {t('reconcile models:')}"
            f" {rapport.get('reconcile_before', 0)}"
            f" → {rapport.get('reconcile_after', 0)}"
        )
    return lignes


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Report the default configuration records a version bump drops"
            " and no event recreates, and optionally let Odoo recreate them."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", default="config.conf")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually recreate them (default: report only)",
    )
    config = parser.parse_args(argv)

    # Le même garde-fou que partout : un Odoo d'une autre version ÉCRIT
    # dans la base avant d'échouer.
    souci = database_cleanup.require_matching_version(config.database)
    if souci:
        print(f"❌ {souci}")
        return 2

    try:
        rapport = database_cleanup.run_shell(
            config.database,
            config.config,
            build_script(not config.apply),
            echo=lambda texte: print(f"⧖ {texte}", flush=True),
        )
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    if rapport.get("error"):
        print(f"❌ {rapport['error']}")
        return 2

    print("\n".join(render(rapport, not config.apply)))
    if not findings(rapport):
        return 0
    if not config.apply:
        return 1
    # Juger sur le compte D'APRÈS : le script a recompté dans la même
    # session. Annoncer « recréé » sans regarder ferait découvrir
    # l'absence au premier devis.
    reste = findings(rapport, apres=True)
    if reste:
        print(f"⚠️  {t('Still missing after the repair.')} {', '.join(reste)}")
        return 1
    print(f"✅ {t('Odoo recreated them.')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
