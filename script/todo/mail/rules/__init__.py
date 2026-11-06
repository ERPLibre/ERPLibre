#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Règles du courrier entrant : décrire, filtrer, retenir, répondre.

`model`, `filter`, `regex_worker`, `guards`, `markup` et `report` sont des
alias des modules du noyau (`erplibre_mail_core.rules`) : décrire une règle
et la (dé)sérialiser, évaluer l'arbre de conditions sur un message, borner
une expression régulière dans le temps, décider si une réponse automatique
part, rendre le corps de la réponse, calculer et rendre le rapport de
statistiques. Ce paquet garde ce qui touche au disque et au cache :
`storage` garde les règles, l'état et les images sur le disque, `svg`
convertit en PNG une image SVG au moment de son ajout, et `lock` exclut
deux passes concurrentes sur un même compte.

Ces modules sont purs au sens du réseau : aucun n'ouvre de connexion IMAP ni
SMTP, et seuls `storage` et `svg`, qu'il appelle, touchent au disque.
L'orchestration, qui les assemble avec le cache et les transports, vit dans
`engine` ; `release` relâche à la main les envois retenus. `run` est la
commande sans interface qui lance une passe de `engine` sur chaque compte,
pour le service systemd ou à la main :
`python -m script.todo.mail.rules.run`.
"""
