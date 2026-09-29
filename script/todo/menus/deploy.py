#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille QEMU, ouverts depuis Execute : Deploy, ses
sous-menus SSH et QEMU/KVM, Network et Security.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place. Une entrée qui ouvre un sous-menu
nomme la méthode publique de celui-ci : son cadre porte le fil d'Ariane.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu, Section

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

QEMU = Menu(
    "prompt_execute_qemu",
    "QEMU/KVM",
    [
        Section("Deployment"),
        Entry(
            "Deploy VM(s) (one or many)",
            "_qemu_deploy",
            kwargs={"dry_run": False},
        ),
        Entry(
            "Preview a deployment (dry-run, no sudo)",
            "_qemu_deploy",
            kwargs={"dry_run": True},
        ),
        Entry("Download a cloud image only", "_qemu_download_image"),
        Entry(
            "Reopen install monitoring (last run / history)",
            "_qemu_reopen_monitor",
        ),
        # Quatre intentions séparent les entrées de gestion : vivre avec ses
        # VM, y entrer, régler le réseau qui les porte, réparer quand ça va
        # mal. Une VM effacée, un disque rétréci, un réseau redéfini, des
        # fichiers orphelins effacés ne se rattrapent pas : `danger`.
        Section("Manage"),
        Entry(
            "List VMs (virsh list --all)",
            "_qemu_list_vms",
            kwargs={"ask_advanced": True},
        ),
        Entry("Show a VM IP address", "_qemu_show_ip"),
        Entry("Open the console on a VM", "_qemu_console"),
        Entry("Resize a VM disk", "_qemu_resize_disk", danger=True),
        Entry("Delete VM(s)", "_qemu_delete_vm", danger=True),
        Section("VM access"),
        Entry(
            "SSH configuration (~/.ssh/config, ProxyJump)",
            "_qemu_ssh_config_menu",
        ),
        Entry(
            "Remote desktop tunnel (VNC/RDP through SSH)",
            "_qemu_tunnel_menu",
        ),
        Entry(
            "Android emulator (start, tunnel, scrcpy)", "_qemu_emulator_menu"
        ),
        Section("VM network"),
        Entry("Show the libvirt network state", "_qemu_network_status"),
        Entry(
            "Recreate the VM subnet (stop, redefine, restart)",
            "_qemu_network_recreate",
            danger=True,
        ),
        Section("Troubleshoot"),
        Entry("Clean up QEMU (orphan files)", "_qemu_cleanup", danger=True),
        Entry(
            "Recover files from a VM disk (libguestfs)", "_qemu_recover_files"
        ),
        Entry("Test a VM (open Odoo in a CLI browser)", "_qemu_test_vm"),
        Entry("Diagnostics (report to share)", "_qemu_diagnostics"),
        Entry("Statistics (installs, durations, VMs)", "_qemu_stats"),
        Section("Catalog"),
        Entry("List available images and specs", "_qemu_list_images"),
        FromConfig(
            "qemu_from_makefile", "execute_from_configuration", "instance"
        ),
    ],
    intro="Deploy a QEMU/KVM virtual machine (libvirt)!",
    opens="_qemu_ouvre",
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
