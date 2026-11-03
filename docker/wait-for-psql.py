#!/usr/bin/env python
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import configparser
import sys
import time

CLES = ("db_host", "db_port", "db_user", "db_password")


def lire_config(chemin):
    """Les clés db_* de la section [options] d'une configuration Odoo."""
    config = configparser.RawConfigParser()
    config.read(chemin)
    if not config.has_section("options"):
        return {}
    return {
        cle: config.get("options", cle)
        for cle in CLES
        if config.has_option("options", cle)
    }


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser()
    # --config plutôt que --db_password : les arguments d'un processus se
    # lisent avec ps par tout compte de l'hôte d'un conteneur. Une option
    # donnée sur la ligne l'emporte sur la configuration.
    arg_parser.add_argument("--config")
    arg_parser.add_argument("--db_host")
    arg_parser.add_argument("--db_port")
    arg_parser.add_argument("--db_user")
    arg_parser.add_argument("--db_password")
    arg_parser.add_argument("--db_name", required=False, default="postgres")
    arg_parser.add_argument("--timeout", type=int, default=10)

    args = arg_parser.parse_args()
    if args.config:
        for cle, valeur in lire_config(args.config).items():
            if getattr(args, cle) is None:
                setattr(args, cle, valeur)
    manquantes = [cle for cle in CLES if getattr(args, cle) is None]
    if manquantes:
        arg_parser.error(f"missing: {', '.join(manquantes)}")

    # Après les arguments : une connexion incomplète se refuse même là où
    # psycopg2 manque.
    import psycopg2

    start_time = time.time()
    print("Try connection to postgres...")

    connected = False
    error = ""
    while ((time.time() - start_time) < args.timeout) or connected is True:
        try:
            conn = psycopg2.connect(
                user=args.db_user,
                host=args.db_host,
                port=args.db_port,
                password=args.db_password,
                dbname=args.db_name,
            )
            break
        except psycopg2.OperationalError as e:
            error = e
            print(".")
            time.sleep(1)
        else:
            connected = True
            conn.close()
    if error:
        print("Database connection failure: %s" % error, file=sys.stderr)
        sys.exit(1)
