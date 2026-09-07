#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Assistant LLM du CLI TODO : quel serveur répond, et que lui dire.

Le paquet est découpé par responsabilité : `fingerprint` reconnaît QUI répond
sur un port, `capabilities` traduit cette reconnaissance en ce que le modèle
sait faire, `servers` garde les serveurs retenus, `backends` parle à l'un
d'eux, `chat` tient la conversation. Aucun de ces modules n'importe `todo.py` ;
c'est le mixin `script/todo/assistant_menu.py` qui les branche sur le CLI.

La frontière est tenue par un test — importer ce paquet ne doit jamais tirer
`script.todo.todo`, qui coûte près d'une seconde et imprime sur la sortie.

Deux règles gouvernent tout ce qui suit, et aucune n'est une précaution de
style.

**Une adresse ne devient jamais du texte de prompt.** Un alias SSH, un nom
d'hôte, une adresse IP, un nom de VM désignent des machines qui ne
s'annoncent nulle part ailleurs. Un serveur porte donc une POIGNÉE opaque —
`server-1` — et c'est elle qui circule ; l'adresse vit dans l'affichage du
menu et dans la configuration privée, jamais dans une invite, un argument de
commande ou un fichier que le dépôt suit. Le détecteur du dépôt reconnaît les
adresses, les courriels et les chemins de compte ; il ne reconnaît PAS les
noms, ce qui rend le filtrage insuffisant et la structure nécessaire.

**Le port dit où frapper, jamais qui répond.** Trois logiciels écoutent sur
8080, deux sur 5000, et l'un d'eux réémet l'API d'un autre à l'identique. La
reconnaissance se lit dans le CORPS d'une réponse, dans un ordre fixe dont
`fingerprint` porte la raison.
"""
