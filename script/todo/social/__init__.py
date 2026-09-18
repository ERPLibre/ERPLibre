#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le client de réseaux sociaux : comptes, cache, fils et publication.

Séparé du client courriel parce qu'un fil n'est pas une boîte : il n'a ni
dossiers, ni UID croissants, ni protocole commun d'une plateforme à
l'autre. Ce qui se partage — le coffre à secrets, le scellement du cache —
est importé de `script.todo.mail`, qui le porte déjà.
"""
