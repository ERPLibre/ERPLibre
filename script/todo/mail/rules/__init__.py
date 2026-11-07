#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Règles du courrier entrant : décrire, filtrer, retenir, répondre.

`model`, `filter`, `regex_worker`, `guards`, `markup`, `report` et `svg`
sont des alias des modules du noyau (`erplibre_mail_core.rules`) : décrire
une règle et la (dé)sérialiser, évaluer l'arbre de conditions sur un
message, borner une expression régulière dans le temps, décider si une
réponse automatique part, rendre le corps de la réponse, calculer et rendre
le rapport de statistiques, contrôler une image SVG et la convertir en PNG
au moment de son ajout. Ce paquet garde ce qui touche au disque et au
cache : `storage` garde les règles, l'état et les images sur le disque, et
`lock` exclut deux passes concurrentes sur un même compte.

Ces modules sont purs au sens du réseau : aucun n'ouvre de connexion IMAP ni
SMTP, et seul `storage` touche au disque ; `svg` écrit la source dans un
dossier temporaire le temps de la convertir.
L'orchestration, qui les assemble avec le cache et les transports, vit dans
`engine` ; `release` relâche à la main les envois retenus. `run` est la
commande sans interface qui lance une passe de `engine` sur chaque compte,
pour le service systemd ou à la main :
`python -m script.todo.mail.rules.run`.
"""
