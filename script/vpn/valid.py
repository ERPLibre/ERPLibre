#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que valide un profil VPN : le générique du dépôt, plus WireGuard.

Les contrôles n'avaient rien de propre aux tunnels — un nom, un chemin, un
port, une adresse — et une cible de déploiement en a besoin des mêmes. Ils
vivent désormais dans `script/lib_valid.py` et servent tout le dépôt ; ce
fichier les relaie pour les appelants qui les nomment ici, et garde ce qui
n'appartient qu'à WireGuard.

`ProfileError` est l'ANCIEN nom de `ValidationError`, et le même objet : un
`except ProfileError` écrit avant le partage attrape toujours ce que le
générique lève.

Un test qui doit REMPLACER une de ces fonctions la remplace à son domicile —
`script.lib_valid` — et non ici : le relais copie des noms, il ne les
interpose pas.
"""
from __future__ import annotations

import re

from script.lib_valid import (  # noqa: F401
    HOST_RE,
    NAME_RE,
    SERVER_RE,
    ValidationError,
    cidr_list,
    flag,
    integer,
    ip_address,
    ip_interface,
    path,
    port,
    text,
)

# L'ancien nom, et non une sous-classe : une sous-classe ferait passer à côté
# `except ProfileError` sur ce que lève le générique.
ProfileError = ValidationError

# Clé WireGuard : 32 octets en base64, donc 43 caractères + « = ».
WG_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$")


def wg_key(record, key, label, required=True):
    """Clé publique WireGuard : 32 octets en base64.

    Vérifiée ici parce que `wg-quick` refuse la configuration ENTIÈRE sur
    une clé mal formée, avec un message qui ne dit pas laquelle.
    """
    value = str(record.get(key) or "").strip()
    if not value:
        if required:
            raise ValidationError(f"{label} : clé obligatoire.")
        record[key] = ""
        return ""
    if not WG_KEY_RE.match(value):
        raise ValidationError(
            f"{label} : « {value[:12]}… » n'a pas la forme d'une clé"
            " WireGuard (32 octets en base64, 44 caractères finissant par"
            " « = »)."
        )
    record[key] = value
    return value
