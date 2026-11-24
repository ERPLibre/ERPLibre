#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Odoo dans le registre des ERP installés en VM.

Odoo est l'ERP par défaut : ses profils, un par version, sont bâtis dans
_qemu_install_profiles et non reconnus par une commande unique ; il accepte
la production, tous les systèmes du catalogue, et le hors-ligne que le
cache de téléchargement gère ailleurs. Le suivi le sonde par une connexion
TCP sur 8069 et le relance par le service ERPLibre.
"""

from script.todo.qemu_erp import APP_ODOO, ErpApp


def web_hint(_ssh, _el_dir):
    """La ligne affichée quand le navigateur sort en erreur sur une VM
    Odoo."""
    return [
        "La page ne s'est peut-être pas affichée : Odoo n'est "
        "pas démarré sur :8069, ou réseau/pare-feu. Vérifie que "
        "le service Odoo tourne dans la VM (make run / systemd)."
    ]


APP = ErpApp(
    key=APP_ODOO,
    name="Odoo",
    port=8069,
    tunnel_port=18069,
    restart_button="Restart Odoo",
    restart_title="Restarting Odoo",
    web_hint=web_hint,
)
