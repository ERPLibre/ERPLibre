# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Règles du courrier entrant, sans stockage : `model` décrit une règle et
la (dé)sérialise, `filter` évalue l'arbre de conditions, `regex_worker`
borne une expression régulière dans le temps, `guards` décide si un envoi
automatique part, `markup` rend le corps de la réponse, `forward` construit
le message d'un transfert, `report` calcule et rend le rapport de
statistiques, `svg` refuse ou convertit en PNG une image SVG, et `media` lit
le type réel et les dimensions d'une image matricielle dans ses octets.
"""
