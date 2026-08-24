# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ausculter une instance : d'où vient la base, et que peut-on y lire.

Ce module ne réanalyse rien. Les analyses existent déjà — vues
personnalisées, champs x_, restant de migration — et chacune sait parler
à une base. Ce qui manquait, c'est le chemin d'AVANT : la base n'est pas
toujours ici. Elle est dans un zip, ou chez un client, ou vivante sur un
serveur auquel on n'a qu'un identifiant.

Trois provenances, deux destins
-------------------------------
Le zip et la sauvegarde distante finissent au même endroit : restaurés en
base locale. À partir de là, tout ce que le dépôt sait faire fonctionne,
sans une ligne de plus.

L'instance VIVANTE, non. Aucun outil d'ici ne parle autre chose que psql,
et on n'a pas la base — on a une session Odoo. Ce que RPC laisse lire est
un sous-ensemble : les tables `ir_*` oui, `pg_catalog` non. Une analyse
qui compte des index ne peut donc pas tourner là, et le dire est le
travail de ce module. Une analyse muette qu'on croit rassurante est pire
que pas d'analyse du tout.

Pourquoi la TUI ne fait que CHOISIR
-----------------------------------
`run_tui` des six écrans du dépôt refuse de s'ouvrir dans une boucle
asyncio déjà en cours, et une analyse lourde appelée depuis un
gestionnaire de touche gèle l'affichage sans rien dire. Un hub qui
CONTIENT les analyses se heurte aux deux. Celui-ci demande ce qu'on veut,
se referme, et laisse l'analyse s'ouvrir chez elle, en pleine possession
du terminal.
"""

from __future__ import annotations

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


REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

# Ce qu'une provenance donne à la fin. `database` couvre le zip restauré
# comme la sauvegarde téléchargée : une fois restaurés, ils ne se
# distinguent plus.
KIND_DATABASE = "database"
KIND_LIVE = "live"

ANALYSES = (
    {
        "key": "migration_residue",
        "title": "Migration leftovers",
        "why": "What a migration left behind, judged without needing the"
        " step-by-step databases.",
        "script": "script/analyse/check_migration_residue.py",
        "kinds": (KIND_DATABASE,),
        "needs_sql": "It reads pg_catalog — indexes and real tables — which"
        " no RPC session exposes.",
    },
    {
        "key": "instance_state",
        "title": "State of the instance",
        "why": "Neutralisation, scheduler, backups, queues and who is an"
        " administrator — read for the use you intend.",
        "script": "script/analyse/check_instance_state.py",
        "kinds": (KIND_DATABASE,),
        "needs_sql": "Several checks read tables no RPC session exposes,"
        " and the lateness of a job is computed in SQL.",
        # Le même chiffre veut dire deux choses opposées selon qu'on
        # ausculte une copie ou une production : l'attente ne se devine
        # pas, elle se demande.
        "asks_expect": True,
    },
    {
        "key": "cow_views",
        "title": "Customised views, website copies included",
        "why": "Every view someone changed, and every website copy that"
        " shadows a module view.",
        "script": "script/analyse/analyse_view_custom.py",
        "kinds": (KIND_DATABASE,),
        "needs_sql": "Comparing a copy with the module view it hides is a"
        " join on arch_db, done in SQL.",
    },
    {
        "key": "custom_fields",
        "title": "Studio and hand-made x_ fields",
        "why": "Fields and models added outside any module, and which of"
        " them have no column behind them.",
        "script": "script/analyse/analyse_custom_field.py",
        "kinds": (KIND_DATABASE,),
        "needs_sql": "Telling a declared field from a real column means"
        " reading pg_attribute.",
    },
)


def analysis_by_key(key):
    """L'analyse portant cette clé, ou None."""
    for analyse in ANALYSES:
        if analyse["key"] == key:
            return analyse
    return None


def available(kind):
    """Les analyses qui savent lire CETTE provenance.

    Rendre la liste complète et laisser l'appelant filtrer ferait afficher
    des choix qui échoueraient à l'ouverture ; c'est le genre de menu qui
    apprend à ne plus faire confiance au menu.
    """
    return tuple(a for a in ANALYSES if kind in a["kinds"])


def unavailable(kind):
    """Celles qui ne le savent pas, avec la raison — pour la DIRE."""
    return tuple(a for a in ANALYSES if kind not in a["kinds"])


def command_for(analyse, database, config_path=None, extra=None):
    """La ligne de commande qui lance l'analyse sur cette base."""
    cmd = [sys.executable, analyse["script"], "-d", database]
    if config_path:
        cmd += ["-c", config_path]
    if extra:
        cmd += list(extra)
    return cmd


def run_analysis(analyse, database, config_path=None, extra=None, env=None):
    """Lancer l'analyse et rendre son code de sortie.

    Sans capture : l'analyse écrit sur le terminal, et certaines ouvrent
    leur propre TUI. Les intercepter reviendrait à leur retirer l'écran.
    """
    cmd = command_for(analyse, database, config_path, extra)
    completed = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
    return completed.returncode


def describe_source(kind, target):
    """Une ligne qui dit sur QUOI l'on travaille, avant d'analyser.

    Après une restauration, le nom de la base n'est plus celui du fichier —
    l'annoncer évite d'analyser une base pour une autre.
    """
    if kind == KIND_LIVE:
        return f"🛰  {t('Live instance:')} {target}"
    return f"💾 {t('Database:')} {target}"


# ── La neutralisation a-t-elle vraiment eu lieu ? ────────────────────────
#
# Mesuré sur les sept bases d'une chaîne 12 → 18 dont le nom porte pourtant
# « neutralize » : `database.is_neutralized` ABSENT dans les sept, 16 à 35
# crons actifs, et `mail.catchall.domain` toujours au domaine du CLIENT.
# Demander « voulez-vous neutraliser ? », recevoir oui, et ne rien vérifier
# reproduit exactement cette illusion.
#
# On ne lit que des booléens de PRÉSENCE. Une clé de paiement vivante a été
# trouvée dans cette base de test ; un rapport finit dans un billet ou
# devant un agent, et n'a aucune raison de la porter.

NEUTRALIZE_SQL = {
    "flag": "SELECT count(*) FROM ir_config_parameter"
    " WHERE key='database.is_neutralized' AND value IN ('true','True','1')",
    "cron_active": "SELECT count(*) FROM ir_cron WHERE active",
    "mail_server": "SELECT count(*) FROM ir_mail_server",
    "payment_live": "SELECT count(*) FROM payment_provider"
    " WHERE state NOT IN ('disabled','test')",
}


def neutralize_state(database, config_path=None):
    """Ce que la base dit d'elle-même après une neutralisation.

    Un contrôle illisible rend None et n'est pas compté comme zéro : la
    table `payment_provider` n'existe pas si le module n'est pas installé,
    et cette absence n'est pas une bonne nouvelle à afficher.
    """
    from script.analyse import lib_analyse

    etat = {}
    for cle, sql in NEUTRALIZE_SQL.items():
        try:
            brut = lib_analyse.run_psql(
                database, sql, config_path=config_path
            ).strip()
            etat[cle] = int(brut.splitlines()[0])
        except Exception:  # noqa: BLE001 - absent n'est pas nul
            etat[cle] = None
    return etat


def neutralize_report(etat, colour=False):
    """Dire ce qui a pris et ce qui n'a pas pris, sans rien inventer.

    `ir_mail_server` à zéro n'est PAS une preuve de sûreté : Odoo retombe
    alors sur le `smtp_server` du fichier de configuration — c'est
    précisément pourquoi son propre `neutralize.sql` INSÈRE un serveur
    bouchon au lieu de tout supprimer.
    """
    lignes = []
    drapeau = etat.get("flag")
    if drapeau:
        lignes.append(f"✅ {t('database.is_neutralized is set.')}")
    else:
        lignes.append(
            f"❌ {t('database.is_neutralized is NOT set — Odoo does not')}"
            f" {t('consider this database neutralised.')}"
        )
    crons = etat.get("cron_active")
    if crons:
        lignes.append(f"⚠  {crons} {t('scheduled actions are still active.')}")
    elif crons == 0:
        lignes.append(f"✅ {t('No scheduled action is active.')}")
    serveurs = etat.get("mail_server")
    if serveurs == 0:
        lignes.append(
            f"⚠  {t('No mail server at all: Odoo falls back to smtp_server')}"
            f" {t('from the config file. A blocking one is safer than none.')}"
        )
    vivants = etat.get("payment_live")
    if vivants:
        lignes.append(
            f"❌ {vivants} {t('payment provider(s) are neither disabled nor')}"
            f" {t('in test mode.')}"
        )
    return "\n".join(paint_plain(lignes, colour))


def paint_plain(lignes, colour):
    """Teinter selon l'icône de tête — une seule règle, pas une par ligne."""
    if not colour:
        return lignes
    teinte = {"❌": "\033[31m", "⚠": "\033[33m", "✅": "\033[32m"}
    sorties = []
    for ligne in lignes:
        code = teinte.get(ligne[:1], "")
        sorties.append(f"{code}{ligne}\033[0m" if code else ligne)
    return sorties


# ── L'instance vivante ───────────────────────────────────────────────────
#
# Depuis Odoo 14, une CLÉ D'API se présente exactement comme un mot de
# passe à `authenticate` : même appel, même place. La différence n'est pas
# technique, elle est humaine — une clé se révoque sans changer le mot de
# passe de personne. On demande donc laquelle on donne, et l'on envoie la
# même chose.


def live_connect(base_url, database, login, secret, timeout=30):
    """Ouvrir une session XML-RPC. Rendre (uid, version), ou lever.

    C'est un vrai contrôle, pas une politesse : sans lui, une faute dans
    l'URL ou la clé ne se verrait qu'à la première analyse, et passerait
    pour un défaut de l'analyse.
    """
    import xmlrpc.client

    url = base_url.rstrip("/")
    common = xmlrpc.client.ServerProxy(
        f"{url}/xmlrpc/2/common", allow_none=True
    )
    import socket

    ancien = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        version = (common.version() or {}).get("server_serie", "?")
        uid = common.authenticate(database, login, secret, {})
    finally:
        socket.setdefaulttimeout(ancien)
    if not uid:
        raise PermissionError(t("The instance refused these credentials."))
    return uid, version


# Ce qu'une analyse a le droit d'appeler sur une instance vivante. La liste
# est appliquée ICI et non chez l'appelant : une production n'a pas à
# dépendre de la prudence de chaque analyse à venir. `write`, `create` et
# `unlink` ne peuvent pas s'y glisser par distraction.
RPC_READ_ONLY = (
    "search_read",
    "search_count",
    "read",
    "read_group",
    "fields_get",
)


def live_call(base_url, database, uid, secret, model, method, *args, **kw):
    """Un appel RPC en lecture. Tout le reste est refusé sans être tenté."""
    if method not in RPC_READ_ONLY:
        raise PermissionError(
            f"{t('Monitoring only reads; refused method:')} {method}"
        )
    import xmlrpc.client

    models = xmlrpc.client.ServerProxy(
        f"{base_url.rstrip('/')}/xmlrpc/2/object", allow_none=True
    )
    return models.execute_kw(
        database, uid, secret, model, method, list(args), kw
    )
