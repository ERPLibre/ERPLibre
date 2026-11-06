#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Client courriel du CLI TODO.

Le paquet est découpé par responsabilité : `crypto` scelle, `secrets` garde
les mots de passe, `accounts` décrit les comptes, `store` cache localement,
`cache_convert` recopie un cache dans l'autre mode, `imap_sync`
synchronise, `smtp_send` envoie, `tui` affiche, `menu` branche le tout sur
le CLI. `tls_trust` épingle un certificat refusé, sur un geste humain. Le sous-paquet `rules` applique les règles du courrier
entrant (filtre, garde-fous, réponse automatique) après chaque
synchronisation ; `tui` (touche `e`) et `menu` (entrée [6]) les éditent.
Aucun de ces modules n'importe `todo.py` ; c'est `todo.py` qui importe
`menu`.

Le noyau des règles — modèle, filtres, garde-fous, rendu, rapport,
constructeurs SMTP, lecteurs IMAP, revendication — vit dans
`script/lib/erplibre_mail_core`, partagé avec un module Odoo ; les anciens
modules de ce paquet en sont des alias. `_core_path` le rend importable.
"""

from script.todo.mail import _core_path  # noqa: F401
