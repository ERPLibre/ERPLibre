#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Registre des pilotes VPN.

Un pilote par technologie, et RIEN d'autre ici : le registre est la seule
chose que le menu, le CLI et les tests ont besoin de connaître pour lister
les technologies disponibles. Ajouter un pilote, c'est une ligne.
"""

from script.vpn.drivers.base import VpnDriver  # noqa: F401
from script.vpn.drivers.l2tp_ipsec import L2tpIpsecDriver
from script.vpn.drivers.openconnect import OpenconnectDriver
from script.vpn.drivers.openvpn import OpenvpnDriver
from script.vpn.drivers.sshuttle import SshuttleDriver
from script.vpn.drivers.wireguard import WireguardDriver

# Nom technique -> classe. Le nom se retrouve dans `driver` du profil et
# dans le paquet à installer : il ne change pas.
#
# L'ordre est celui du plus contraint au plus libre — c'est aussi celui dans
# lequel le menu les propose, et il aide à choisir : L2TP/IPsec quand le
# site l'impose, WireGuard quand on tient les deux bouts, sshuttle quand il
# n'y a qu'un accès SSH.
DRIVERS = {
    L2tpIpsecDriver.name: L2tpIpsecDriver,
    WireguardDriver.name: WireguardDriver,
    OpenvpnDriver.name: OpenvpnDriver,
    OpenconnectDriver.name: OpenconnectDriver,
    SshuttleDriver.name: SshuttleDriver,
}


def get_driver(name):
    """Classe du pilote `name`, ou None. Ne lève pas : un profil peut
    nommer un pilote retiré, et le CLI doit pouvoir le DIRE."""
    return DRIVERS.get(name)


def driver_names():
    """Les noms dans l'ordre du registre, pas dans l'ordre alphabétique :
    cet ordre est un conseil de choix, voir le commentaire de DRIVERS."""
    return list(DRIVERS)
