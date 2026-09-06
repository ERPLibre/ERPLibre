#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les backends de VM : identité d'abord, verbes ensuite.

Un paquet, et non un module : les adaptateurs libvirt et Proxmox viendront
s'y ranger, puis un troisième pour macOS.
"""

from script.vm.backend import (  # noqa: F401
    BACKENDS,
    LIBVIRT,
    PVE,
    VerbNotImplemented,
    VmBackendError,
    VmHandle,
    addresses_by_name,
    handle_of,
    libvirt_handle,
    pve_handle,
    resolves_locally,
    is_armed,
    same_machine,
)
