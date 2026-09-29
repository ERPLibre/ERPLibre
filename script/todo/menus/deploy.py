#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille QEMU, ouverts depuis Execute : Deploy et son
sous-menu SSH, Network et Security.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place. Une entrée qui ouvre un sous-menu
nomme la méthode publique de celui-ci : son cadre porte le fil d'Ariane.
"""

from script.todo.ui.registry import Entry, Menu, Section

DEPLOY = Menu(
    "prompt_execute_deploy",
    "Deploy",
    [
        Section("Local"),
        Entry("Clone ERPLibre locally (git clone)", "_deploy_clone_erplibre"),
        Entry("Configure sshfs", "_configure_sshfs"),
        Entry(
            "SSH port forwarding (open Odoo in the browser)",
            "_deploy_port_forward",
        ),
        Entry("Configure a SOCKS proxy over SSH", "_deploy_socks_proxy"),
        Section("Remote & services"),
        Entry("SSH (remote host)...", "prompt_execute_deploy_ssh"),
        Entry(
            "QEMU/KVM - Deploy an Ubuntu VM (libvirt)", "prompt_execute_qemu"
        ),
        Entry(
            "Proxmox VE - Deploy a VM on a remote host",
            "prompt_execute_proxmox",
        ),
        Entry(
            "Deploy - Install NTFY notification server", "_deploy_ntfy_server"
        ),
        Entry(
            "QEMU cache - Download mirror for local VMs",
            "prompt_execute_qemu_cache",
        ),
        Section("VPN & tunnels"),
        Entry(
            "VPN - Tunnels (L2TP/IPsec, WireGuard, OpenVPN...)",
            "prompt_execute_vpn",
        ),
    ],
    intro="Deploy ERPLibre to a local directory!",
    render="once",
)

SSH = Menu(
    "prompt_execute_deploy_ssh",
    "SSH",
    [
        Entry("SSH - Check connection", "_deploy_ssh_check"),
        # « rsync --delete » efface, sur l'hôte distant, ce qui n'existe
        # pas ici.
        Entry("SSH - Sync files (rsync)", "_deploy_ssh_push", danger=True),
        Entry("SSH - Install ERPLibre", "_deploy_ssh_install"),
        Entry("SSH - Start Odoo", "_deploy_ssh_run"),
        Entry("SSH - Stop Odoo", "_deploy_ssh_stop"),
        Entry("SSH - Restart Odoo", "_deploy_ssh_restart"),
        Entry("SSH - Service status", "_deploy_ssh_status"),
        Entry("SSH - View logs", "_deploy_ssh_logs"),
        Entry("SSH - Run make target", "_deploy_ssh_make"),
        Entry("SSH - Install systemd service", "_deploy_ssh_install_systemd"),
        Entry("SSH - Configure nginx + SSL", "_deploy_ssh_install_nginx"),
    ],
    intro="Deploy ERPLibre to a remote host over SSH!",
    render="once",
)

NETWORK = Menu(
    "prompt_execute_network",
    "Network",
    [
        Entry("SSH port-forwarding", "generate_network_port_forwarding"),
        Entry(
            "Network performance request per second",
            "generate_network_performance_test",
        ),
        Entry(
            "VPN - Tunnels (L2TP/IPsec, WireGuard, OpenVPN...)",
            "prompt_execute_vpn",
        ),
        Entry(
            "Odoo reverse proxy (pages and websocket on one port)",
            "network_reverse_proxy",
        ),
        Entry(
            "Local TLS certificates for testing (HTTPS)",
            "network_local_certificates",
        ),
    ],
    intro="Network tools!",
    render="once",
)

SECURITY = Menu(
    "prompt_execute_security",
    "Security",
    [
        Entry(
            "pip-audit - Check vulnerabilities on Python environments",
            "execute_pip_audit",
        ),
    ],
    intro="Dependency security audit!",
    render="once",
)
