#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Copie une configuration Odoo en y ajoutant la connexion PostgreSQL.

    odoo_rc_db.py SOURCE DESTINATION

Les clés db_host, db_port, db_user et db_password absentes de SOURCE
prennent les valeurs des variables ERPLIBRE_DB_HOST, ERPLIBRE_DB_PORT,
ERPLIBRE_DB_USER et ERPLIBRE_DB_PASSWORD ; une clé présente garde sa valeur.
Les valeurs passent par l'environnement et non par les arguments : ceux d'un
processus se lisent avec ps par tout compte de l'hôte d'un conteneur, et ceux
d'Odoo pendant toute sa vie. DESTINATION est créée en 0600, le mot de passe
y étant écrit.
"""

import configparser
import os
import sys

CLES = {
    "db_host": "ERPLIBRE_DB_HOST",
    "db_port": "ERPLIBRE_DB_PORT",
    "db_user": "ERPLIBRE_DB_USER",
    "db_password": "ERPLIBRE_DB_PASSWORD",
}


def completer(source, destination, environ=None):
    """Écrit DESTINATION : SOURCE complétée des clés db_* absentes."""
    environ = os.environ if environ is None else environ
    # Sans interpolation : un « % » dans un mot de passe reste tel quel.
    config = configparser.RawConfigParser()
    config.read(source)
    if not config.has_section("options"):
        config.add_section("options")
    for cle, variable in CLES.items():
        if not config.has_option("options", cle) and variable in environ:
            config.set("options", cle, environ[variable])
    if os.path.exists(destination):
        os.remove(destination)
    descripteur = os.open(
        destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        config.write(fichier)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} SOURCE DESTINATION")
    completer(sys.argv[1], sys.argv[2])
