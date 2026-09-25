# -*- coding: utf-8 -*-
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
# Odoo 10 et 11 importent le module pour découvrir ses commandes : c'est cet
# import qui enregistre la classe. Odoo 19 et 20 chargent cli/erplibre_db.py
# seul, sans passer par ce fichier.
from . import cli
