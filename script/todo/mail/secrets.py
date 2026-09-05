#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Relais vers le coffre du dépôt, qui a quitté le paquet « mail ».

Le mécanisme n'a jamais été propre au courrier : une référence
« <coffre>:<chemin> », deux magasins, une liste blanche des backends qui
chiffrent vraiment. Il vit désormais dans `script/vault/store.py` et sert
tout le dépôt. Ce fichier reste pour les appelants qui le nommaient ici.

Un test qui doit REMPLACER une de ces fonctions la remplace à son domicile —
`script.vault.store` — et non ici : le relais copie des noms, il ne les
interpose pas.
"""

from script.vault.store import (  # noqa: F401
    KEYRING_SERVICE,
    SAFE_BACKENDS,
    SecretError,
    SecretStore,
    create_kdbx,
    keyring_backend_name,
    keyring_is_safe,
)
