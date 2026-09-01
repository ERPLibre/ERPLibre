#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Démonstration de bout en bout de la passerelle SMS.

La passerelle a deux moitiés — un module Odoo côté serveur, une application
Android côté téléphone — et c'est leur mise en relation qui pose problème à
qui découvre le produit : un secret partagé, un identifiant d'appareil, une
URL joignable, et rien ne fonctionne tant que les trois ne concordent pas.

Ce paquet automatise cette mise en relation sur une VM jetable, pour que la
démonstration soit reproductible et qu'un échec se diagnostique étape par
étape plutôt qu'en bloc.

Découpage par responsabilité, comme le paquet `mail` :

- `spec`  décrit la démonstration et retient son état entre deux sessions
- `steps` définit les étapes et leur enchaînement, sans savoir les exécuter
- `menu`  branche le tout sur le CLI

Aucun de ces modules n'importe `todo.py` ; c'est `todo.py` qui importe `menu`.
"""
