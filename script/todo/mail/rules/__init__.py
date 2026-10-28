#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Règles du courrier entrant : décrire, filtrer, retenir, répondre.

Le paquet est découpé par responsabilité : `model` décrit une règle et la
(dé)sérialise, `filter` évalue l'arbre de conditions sur un message,
`guards` décide si une réponse automatique part, `markup` rend le corps de la
réponse, `storage` garde les règles, l'état et les images sur le disque,
`svg` convertit en PNG une image SVG au moment de son ajout, et `lock`
exclut deux passes concurrentes sur un même compte.

Ces modules sont purs au sens du réseau : aucun n'ouvre de connexion IMAP ni
SMTP, et seuls `storage` et `svg`, qu'il appelle, touchent au disque.
L'orchestration, qui les assemble avec le cache et les transports, vit dans
`engine`.
"""
