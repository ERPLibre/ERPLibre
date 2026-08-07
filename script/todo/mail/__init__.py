#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Client courriel du CLI TODO.

Le paquet est découpé par responsabilité : `crypto` scelle, `secrets` garde
les mots de passe, `accounts` décrit les comptes, `store` cache localement,
`imap_sync` synchronise, `smtp_send` envoie, `tui` affiche, `menu` branche le
tout sur le CLI. Aucun de ces modules n'importe `todo.py` ; c'est `todo.py`
qui importe `menu`.
"""
