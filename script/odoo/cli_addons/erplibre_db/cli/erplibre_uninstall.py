# -*- coding: utf-8 -*-
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""odoo-bin erplibre_uninstall : l'option « --uninstall » du fork ERPLibre,
pour un Odoo amont.

Le fork désinstalle, au démarrage du serveur, les modules que nomme
« --uninstall a,b » et ceux qui en dépendent. odoo_bin.sh réécrit vers cette
commande tout appel qui porte l'option quand l'Odoo actif ne la connaît pas.
Les autres arguments sont ceux du serveur : -c, -d, --stop-after-init, etc.

Le code tourne de Python 2.7 à 3.14 : ni f-string, ni argument nommé seul.
"""
from __future__ import print_function

import sys

import odoo
from odoo.cli import Command
from odoo.modules.registry import Registry
from odoo.tools import config

try:
    from .erplibre_db import _parametres, contexte_orm, mourir
except ImportError:
    # Odoo 19 et 20 chargent ce seul fichier, sous le nom
    # odoo.cli.erplibre_uninstall : son voisin n'est pas importé, et se
    # charge alors par son chemin. Odoo 10 et 11 importent le paquet entier.
    import importlib.util
    import os

    _spec = importlib.util.spec_from_file_location(
        "odoo.cli.erplibre_db",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "erplibre_db.py"),
    )
    _voisin = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _voisin
    _spec.loader.exec_module(_voisin)
    _parametres = _voisin._parametres
    contexte_orm = _voisin.contexte_orm
    mourir = _voisin.mourir


def extraire_modules(cmdargs):
    """Sépare « --uninstall a,b » (ou « --uninstall=a,b ») du reste.

    Rend la liste des modules et les arguments restants, pour le serveur.
    """
    modules, reste = [], []
    args = iter(cmdargs)
    for arg in args:
        if arg == "--uninstall":
            valeur = next(args, "")
        elif arg.startswith("--uninstall="):
            valeur = arg.split("=", 1)[1]
        else:
            reste.append(arg)
            continue
        modules += [m.strip() for m in valeur.split(",") if m.strip()]
    return modules, reste


def desinstaller(env, noms):
    """Désinstalle les modules installés parmi noms, et leurs dépendants.

    Rend les noms effectivement désinstallés, vide si aucun n'était installé.
    """
    modules = env["ir.module.module"].search(
        [("name", "in", noms), ("state", "=", "installed")]
    )
    if not modules:
        return []
    modules |= modules.downstream_dependencies()
    retires = sorted(modules.mapped("name"))
    modules.button_immediate_uninstall()
    return retires


class Erplibre_uninstall(Command):
    """Désinstalle des modules et leurs dépendants (--uninstall du fork)"""

    # Voir Erplibre_db : le nom de fichier pour Odoo 19 et 20, celui de la
    # classe pour Odoo 10 et 11.
    name = "erplibre_uninstall"

    def run(self, cmdargs):
        noms, reste = extraire_modules(cmdargs)
        mourir(not noms, "Missing argument --uninstall.")
        if "setup_logging" in _parametres(config.parse_config):
            config.parse_config(reste, setup_logging=True)
        else:
            config.parse_config(reste)
        base = config["db_name"]
        mourir(not base or "," in base, "--uninstall requires one -d.")
        with contexte_orm():
            registre = Registry(base)
            with registre.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                retires = desinstaller(env, noms)
        if retires:
            print("Uninstalled modules (with dependents): %s" % ",".join(retires))
        else:
            print("Module(s) not installed: %s" % ",".join(noms), file=sys.stderr)
