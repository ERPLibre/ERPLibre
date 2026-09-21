#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le coffre du dépôt : une seule voie d'accès aux secrets.

Nommé « vault » et non « secrets » : un paquet nommé `secrets` posé sur
`sys.path` MASQUE le module standard du même nom, et tout ce qui en attend
`token_hex` casse alors sans dire pourquoi. Mesuré, et gratuit à éviter.
"""
