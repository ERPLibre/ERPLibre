#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La connexion d'Odoo, rendue à « psql » : le fichier de configuration
qu'Odoo lit, ses options, et l'environnement libpq qui en découle.

Un « psql » lancé sans cet environnement prend les valeurs par défaut de
libpq — socket Unix, rôle de l'utilisateur système — et joint un autre
serveur, ou un autre rôle, que celui d'Odoo. Toutes les lectures de la
base par les scripts passent donc par `environnement`, qui suit le même
fichier qu'Odoo.

Le module n'importe rien du dépôt : db_restore, lib_analyse et pg_state
s'en servent sans s'importer les uns les autres.
"""

import configparser
import os

# Les options de connexion d'Odoo et la variable libpq de chacune : la
# correspondance d'« exec_pg_environ » (odoo/tools/misc.py). PGSSLMODE
# compte : un serveur qui exige « verify-full » serait sinon joint sans
# contrôle de son certificat.
CORRESPONDANCE = (
    ("db_host", "PGHOST"),
    ("db_port", "PGPORT"),
    ("db_user", "PGUSER"),
    ("db_password", "PGPASSWORD"),
    ("db_sslmode", "PGSSLMODE"),
)

# Odoo écrit « False » pour une option laissée vide. L'exporter telle
# quelle ferait chercher un hôte nommé « False ».
VALEURS_VIDES = ("false", "none", "")

# Délais par défaut, en secondes : la connexion, puis chaque requête.
DELAI_CONNEXION = 10
DELAI_REQUETE = 60


def chemin_config(racine="."):
    """Le fichier de configuration qu'« odoo_bin.sh » fait lire à Odoo,
    ou None quand aucun n'existe.

    Même ordre que « odoo_rc_resolve » (script/lib_odoo_rc.sh) : un
    ODOO_RC posé l'emporte, puis `racine`/config.conf, puis
    /etc/odoo/odoo.conf. Le premier fichier présent est retenu, lisible ou
    non : c'est celui qu'Odoo lira.
    """
    if os.environ.get("ODOO_RC"):
        candidats = [os.environ["ODOO_RC"]]
    else:
        candidats = [
            os.path.join(racine, "config.conf"),
            "/etc/odoo/odoo.conf",
        ]
    for candidat in candidats:
        if os.path.isfile(candidat):
            return candidat
    return None


def options(chemin):
    """La section [options] de `chemin` en dict, vide quand le fichier
    manque, ne se lit pas ou n'a pas cette section. L'absence de
    configuration n'est pas une erreur : sur une installation native,
    psql joint le serveur par le socket Unix sans aucun paramètre."""
    if not chemin or not os.path.isfile(chemin):
        return {}
    lecteur = configparser.RawConfigParser()
    try:
        lecteur.read(chemin)
    except configparser.Error:
        return {}
    if not lecteur.has_section("options"):
        return {}
    return dict(lecteur.items("options"))


def environnement(
    chemin=None,
    racine=".",
    base=None,
    delai_requete=DELAI_REQUETE,
    delai_connexion=DELAI_CONNEXION,
    surcharges=None,
):
    """L'environnement qui connecte « psql » comme Odoo, en lecture seule.

    Part de os.environ ; les options de connexion de `chemin` (celui de
    `chemin_config(racine)` quand None) y deviennent les variables libpq quand
    elles portent une valeur. `surcharges`, un dict de variables libpq,
    l'emporte ensuite sur la configuration ; une valeur vide n'y compte
    pas.

    `base` passe par PGDATABASE et non par « -d » : libpq lit un « -d » qui
    contient « = » comme une chaîne de connexion entière, alors que
    PGDATABASE reste un nom.

    PGOPTIONS ouvre chaque transaction en lecture seule — c'est le serveur
    qui refuse l'écriture — et borne chaque requête à `delai_requete`
    secondes ; PGCONNECT_TIMEOUT borne la connexion, pour qu'un hôte
    injoignable rende la main avant le délai TCP du système. PSQLRC vide
    écarte un ~/.psqlrc dont la sortie (\\timing, \\pset) fausserait la
    réponse, même pour un appel qui oublie « -X ».
    """
    env = dict(os.environ)
    config = options(chemin_config(racine) if chemin is None else chemin)
    for option, variable in CORRESPONDANCE:
        valeur = str(config.get(option, "")).strip()
        if valeur.lower() not in VALEURS_VIDES:
            env[variable] = valeur
    for variable, valeur in (surcharges or {}).items():
        if valeur:
            env[variable] = str(valeur)
    if base:
        env["PGDATABASE"] = base
    env["PGCONNECT_TIMEOUT"] = str(delai_connexion)
    env["PGOPTIONS"] = (
        "-c default_transaction_read_only=on"
        f" -c statement_timeout={delai_requete}s"
    )
    env["PSQLRC"] = ""
    return env
