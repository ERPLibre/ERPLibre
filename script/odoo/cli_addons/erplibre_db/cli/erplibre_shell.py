# -*- coding: utf-8 -*-
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""odoo-bin erplibre_shell : la commande « shell » d'Odoo 9, pour Odoo 8.

Odoo 8 n'a pas de commande shell, et l'outillage de migration lui passe ses
scripts sur l'entrée standard. odoo_bin.sh réécrit « shell » vers cette
commande quand l'Odoo actif n'en a pas.

Comme le shell d'Odoo 9 : l'entrée standard est exécutée avec « env »,
« self » (l'utilisateur) et le paquet d'Odoo, sous les noms « openerp » et
« odoo » ; le curseur est ouvert en gestionnaire de contexte, qui valide les
écritures en fin d'exécution réussie et les annule sur exception. Un terminal
ouvre une console interactive.

Le code tourne de Python 2.7 à 3.14 : ni f-string, ni argument nommé seul.
"""
from __future__ import print_function

import code
import os
import sys

try:
    from . import erplibre_db as commun
except ImportError:
    # Odoo 19 et 20 chargent ce seul fichier : voir erplibre_uninstall.
    import importlib.util

    _spec = importlib.util.spec_from_file_location(
        "odoo.cli.erplibre_db",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "erplibre_db.py"),
    )
    commun = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = commun
    _spec.loader.exec_module(commun)

odoo = commun.odoo


def executer(variables):
    """L'entrée standard dans variables, ou une console sur un terminal."""
    if os.isatty(sys.stdin.fileno()):
        code.interact(local=variables)
    else:
        variables["__name__"] = "__main__"
        exec(compile(sys.stdin.read(), "<stdin>", "exec"), variables)


class Erplibre_shell(commun.Command):
    """Exécute l'entrée standard avec env, comme le shell d'Odoo 9"""

    # Voir Erplibre_db : le nom de fichier pour Odoo 19 et 20, celui de la
    # classe pour Odoo 8 à 11.
    name = "erplibre_shell"

    def run(self, cmdargs):
        config = commun.config
        if "setup_logging" in commun._parametres(config.parse_config):
            config.parse_config(cmdargs, setup_logging=True)
        else:
            config.parse_config(cmdargs)
        variables = {"openerp": odoo, "odoo": odoo}
        base = config["db_name"]
        with commun.contexte_orm():
            if not base:
                executer(variables)
                return 0
            api = commun.module("api")
            with commun.ouvrir_registre(base).cursor() as cr:
                uid = odoo.SUPERUSER_ID
                contexte = api.Environment(cr, uid, {})["res.users"].context_get()
                env = api.Environment(cr, uid, contexte)
                variables["env"] = env
                variables["self"] = env.user
                executer(variables)
        return 0
