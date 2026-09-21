#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les postures réseau : ce qu'une VM a le droit d'atteindre.

Un paquet, et non un module : le rendu des règles et les listes de
destinations viendront s'y ranger, et ils n'ont rien à faire dans le
registre.
"""

from script.posture.registry import (  # noqa: F401
    DEFAULT_POSTURE,
    DNS_KINDS,
    EGRESS_KINDS,
    HOST_KEY_POLICIES,
    NETWORK_KINDS,
    POSTURES,
    Posture,
    allows_real_data,
    get_posture,
    posture_names,
)
from script.posture.spec import (  # noqa: F401
    OK,
    POSTURE_KEY,
    REAL_DATA_KEY,
    REAL_DATA_UNCONFINED,
    SPEC_VERDICTS,
    UNKNOWN_POSTURE,
    check,
    posture_name,
    posture_of,
    real_data,
)
