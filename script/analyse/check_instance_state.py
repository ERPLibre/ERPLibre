#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Dans quel état est cette instance — et pour quel usage on la destine.

Le même chiffre veut dire deux choses opposées. Zéro cron actif est le
SUCCÈS attendu d'une copie de développement, et une panne totale sur une
production. Zéro serveur de courriel rassure sur l'une, condamne l'autre.
Un rapport qui ignore cette différence crie au loup sur ce que l'on vient
de demander, et l'on cesse alors de le lire — c'est la faute que ce dépôt
a déjà corrigée trois fois.

L'attente est donc DÉCLARÉE, `--expect copy` ou `--expect live`, et
chaque contrôle dit ce qu'il juge sous l'une et sous l'autre. Ce qui n'a
pas de sens sous l'attente courante n'est pas affiché en vert : il est
affiché comme non jugé, avec la raison.

Mesuré, et c'est ce qui a fixé la conception
--------------------------------------------
Sur la base 12 d'ORIGINE et sur sa migrée 18, jamais démarrées :

    crons en retard de plus d'un cycle    11  et   8
    lignes db_backup                       0  et   0

Le retard n'a rien à voir avec la migration : personne ne fait tourner le
cadenceur d'une base restaurée. Sous `--expect copy`, ces deux contrôles
ne sont donc pas jugés du tout. Les afficher en rouge aurait été du bruit
pur ; les afficher en vert, un mensonge.

Ce qui se juge SOUS LES DEUX
----------------------------
La neutralisation, elle, se mesure. Sur sept bases dont le nom portait
« neutralize », `database.is_neutralized` était absent des sept, avec
jusqu'à 35 crons actifs et le domaine de courriel du CLIENT en place.

On ne lit que des BOOLÉENS de présence pour tout ce qui touche à un
secret. Une clé de paiement vivante a été trouvée dans une base de test ;
un rapport finit dans un billet ou devant un agent, et n'a aucune raison
de la porter.

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


from script.analyse import lib_analyse  # noqa: E402

COPY = "copy"
LIVE = "live"
ATTENTES = (COPY, LIVE)

COULEURS = {
    "broken": "\033[31m",
    "watch": "\033[33m",
    "ok": "\033[32m",
    "dim": "\033[90m",
}
RESET = "\033[0m"


def paint(texte, genre, colour):
    if not colour:
        return texte
    return f"{COULEURS.get(genre, '')}{texte}{RESET}"


# Une politique dit COMMENT lire le nombre sous une attente donnée :
#   ("zero", gravité)    il doit valoir zéro
#   ("nonzero", gravité) il doit être non nul
#   ("info",)            on montre, on ne juge pas
#   ("skip", raison)     sans objet ici, et l'on DIT pourquoi
CONTROLES = (
    {
        "key": "neutralized",
        "section": "Neutralisation",
        "title": "database.is_neutralized",
        "sql": "SELECT count(*) FROM ir_config_parameter"
        " WHERE key='database.is_neutralized'"
        " AND value IN ('true','True','1')",
        "copy": ("nonzero", "broken"),
        "live": ("zero", "broken"),
        "why_copy": "Odoo does not consider this database neutralised;"
        " modules that neutralise themselves never ran.",
        "why_live": "A production marked as neutralised has had its"
        " scheduled actions and outgoing mail disabled.",
    },
    {
        "key": "mail_server_open",
        "section": "Neutralisation",
        "title": "Mail servers that could actually send",
        "sql": "SELECT count(*) FROM ir_mail_server WHERE active"
        " AND coalesce(smtp_host,'') NOT IN ('invalid','localhost.invalid')",
        "copy": ("zero", "broken"),
        "live": ("info",),
        "why_copy": "A copy that can send reaches the customer's real"
        " contacts.",
        "why_live": "",
    },
    {
        "key": "mail_server_total",
        "section": "Neutralisation",
        "title": "Mail servers declared at all",
        "sql": "SELECT count(*) FROM ir_mail_server",
        "copy": ("nonzero", "watch"),
        "live": ("nonzero", "watch"),
        "why_copy": "With NO server, Odoo falls back to smtp_server from"
        " the config file — which is why Odoo's own neutralize.sql"
        " INSERTS a blocking one instead of deleting them all.",
        "why_live": "With no server at all, Odoo silently uses the"
        " smtp_server from the config file.",
    },
    {
        "key": "payment_live",
        "section": "Neutralisation",
        "title": "Payment providers neither disabled nor in test",
        "sql": "SELECT count(*) FROM payment_provider"
        " WHERE state NOT IN ('disabled','test')",
        "copy": ("zero", "broken"),
        "live": ("info",),
        "why_copy": "A copy can charge real cards.",
        "why_live": "",
    },
    {
        "key": "url_mismatch",
        "section": "Neutralisation",
        "title": "Mail domain that does not match the base URL",
        "sql": "SELECT CASE WHEN EXISTS (SELECT 1 FROM ir_config_parameter c"
        " JOIN ir_config_parameter u ON u.key='web.base.url'"
        " WHERE c.key='mail.catchall.domain'"
        " AND position(c.value in u.value) = 0) THEN 1 ELSE 0 END",
        "copy": ("info",),
        "live": ("zero", "watch"),
        "why_copy": "",
        "why_live": "Portal links, invoice QR codes and reply addresses"
        " point somewhere else than the instance itself.",
    },
    {
        "key": "cron_active",
        "section": "Scheduler",
        "title": "Scheduled actions active",
        "sql": "SELECT count(*) FROM ir_cron WHERE active",
        "copy": ("zero", "watch"),
        "live": ("nonzero", "broken"),
        "why_copy": "A copy that still runs them sends mail and posts"
        " payments.",
        "why_live": "Nothing at all runs on a schedule.",
    },
    {
        "key": "cron_late",
        "section": "Scheduler",
        "title": "Scheduled actions late by more than one cycle",
        "sql": "SELECT count(*) FROM ir_cron c WHERE c.active"
        " AND c.nextcall <"
        " now() - (c.interval_number || ' ' || c.interval_type)::interval",
        "copy": (
            "skip",
            "Nobody runs the scheduler on a restored copy:"
            " measured 11 late on an untouched source database.",
        ),
        "live": ("zero", "broken"),
        "why_copy": "",
        "why_live": "A fixed threshold misses them — a ten-minute job one"
        " hour late matters, a monthly one does not.",
    },
    {
        "key": "backup_rows",
        "section": "Backups",
        "title": "Backup configurations recorded",
        "sql": "SELECT count(*) FROM db_backup",
        "copy": (
            "skip",
            "update_prod_to_dev deletes them on purpose;"
            " their absence here proves nothing.",
        ),
        "live": ("nonzero", "broken"),
        "why_copy": "",
        "why_live": "The backup scheduler runs and backs up nothing.",
    },
    {
        "key": "mail_stuck",
        "section": "Queues",
        "title": "Messages stuck in the outgoing queue",
        "sql": "SELECT count(*) FROM mail_mail"
        " WHERE state IN ('outgoing','exception')",
        "copy": ("info",),
        "live": ("zero", "watch"),
        "why_copy": "",
        "why_live": "Visible to the customer, invisible to the operator.",
    },
    {
        "key": "all_internal_are_admin",
        "section": "Users",
        "title": "Internal users who are ALL system administrators",
        "sql": "SELECT CASE WHEN (SELECT count(*) FROM res_users u"
        " WHERE u.active AND EXISTS (SELECT 1 FROM res_groups_users_rel r"
        " JOIN ir_model_data d ON d.model='res.groups' AND d.res_id=r.gid"
        " WHERE r.uid=u.id AND d.module='base' AND d.name='group_user'))"
        " = (SELECT count(*) FROM res_users u WHERE u.active"
        " AND EXISTS (SELECT 1 FROM res_groups_users_rel r"
        " JOIN ir_model_data d ON d.model='res.groups' AND d.res_id=r.gid"
        " WHERE r.uid=u.id AND d.module='base' AND d.name='group_system'))"
        " THEN 1 ELSE 0 END",
        "copy": ("zero", "watch"),
        "live": ("zero", "watch"),
        "why_copy": "No ordinary user exists to test visibility with — any"
        " access-rights check run here proves nothing.",
        "why_live": "Everyone can change everything, and no rule is ever"
        " exercised.",
    },
)

SECTIONS = ("Neutralisation", "Scheduler", "Backups", "Queues", "Users")


def inspect(database, config_path=None):
    """Passer chaque contrôle. Un contrôle illisible n'est PAS un zéro."""
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


def verdict(controle, valeur, attente):
    """(genre, gravité, raison) pour ce contrôle sous cette attente.

    `genre` vaut ok, bad, info, skip ou unreadable — jamais autre chose,
    et surtout jamais « ok » par défaut : un contrôle sans politique est un
    oubli, pas une bonne nouvelle.
    """
    if isinstance(valeur, dict):
        return "unreadable", "watch", valeur.get("error", "")
    politique = controle.get(attente)
    if not politique:
        return "skip", "dim", ""
    genre = politique[0]
    if genre == "skip":
        return "skip", "dim", t(politique[1])
    if genre == "info":
        return "info", "dim", ""
    raison = t(controle.get(f"why_{attente}", "") or "")
    if genre == "zero":
        return (
            ("ok", "ok", "") if not valeur else ("bad", politique[1], raison)
        )
    if genre == "nonzero":
        return ("ok", "ok", "") if valeur else ("bad", politique[1], raison)
    return "skip", "dim", ""


def findings(resultats, attente):
    """Ce qui ne va pas, et rien d'autre — pour le code de sortie."""
    mauvais = []
    for controle in CONTROLES:
        genre, gravite, raison = verdict(
            controle, resultats.get(controle["key"]), attente
        )
        if genre == "bad":
            mauvais.append((controle, gravite, raison))
    return mauvais


def render(database, resultats, attente, colour=True):
    """Le rapport, section par section, dans l'ordre déclaré."""
    entete = (
        t("a development copy") if attente == COPY else t("a live instance")
    )
    lignes = [
        f"🩺 {t('State of')} {database} — {t('read as')} {entete}",
        "",
    ]
    for section in SECTIONS:
        corps = []
        for controle in CONTROLES:
            if controle["section"] != section:
                continue
            valeur = resultats.get(controle["key"])
            genre, gravite, raison = verdict(controle, valeur, attente)
            nombre = "?" if isinstance(valeur, dict) else str(valeur)
            icone = {
                "ok": "✅",
                "bad": "❌" if gravite == "broken" else "⚠",
                "info": "ℹ️ ",
                "skip": "·",
                "unreadable": "❔",
            }[genre]
            corps.append(
                paint(
                    f"   {icone} {nombre.rjust(5)}  {t(controle['title'])}",
                    gravite if genre in ("bad", "ok") else "dim",
                    colour,
                )
            )
            if raison:
                corps.append(paint(f"            {raison}", "dim", colour))
        if corps:
            lignes.append(t(section))
            lignes.extend(corps)
            lignes.append("")
    return "\n".join(lignes).rstrip()


def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=t("What state an instance is in, for its intended use."),
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", help="odoo config file")
    parser.add_argument(
        "--expect",
        choices=ATTENTES,
        default=COPY,
        help="copy: a restored development copy. live: a running instance.",
    )
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
    mauvais = findings(resultats, args.expect)

    if args.json:
        print(
            json.dumps(
                {
                    "database": args.database,
                    "expect": args.expect,
                    "checks": resultats,
                    "bad": [c["key"] for c, _, _ in mauvais],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        colour = sys.stdout.isatty() and not args.no_color
        print(render(args.database, resultats, args.expect, colour))
    return 1 if mauvais else 0


if __name__ == "__main__":
    sys.exit(main())
