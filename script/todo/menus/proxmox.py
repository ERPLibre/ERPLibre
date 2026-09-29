#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Proxmox : Proxmox VE, ouvert depuis Deploy, VPN,
ouvert depuis Deploy et depuis Network, Long test, ouvert depuis Test, et
Install, ouvert par le menu principal.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place.

Une entrée qui efface, agit en root sur un hôte, pose des paquets, écrit
une configuration globale ou crée de vraies machines porte `danger` : ni
la TUI de télémétrie ni la page web ne la lancent, son menu seul.
"""

from script.todo.ui.registry import (
    Entry,
    FromConfig,
    FromMethod,
    Menu,
    Section,
)

PROXMOX = Menu(
    "prompt_execute_proxmox",
    "Proxmox VE",
    [
        # Déployer crée une VM en root sur l'hôte, et une image téléchargée
        # s'écrit dans son stockage : `danger`. L'aperçu n'envoie rien.
        Section("Deployment"),
        Entry("Deploy a VM on the Proxmox host", "_pve_deploy", danger=True),
        Entry(
            "Preview a deployment (dry-run, nothing sent)",
            "_pve_deploy",
            kwargs={"dry_run": True},
        ),
        Entry(
            "Download a cloud image on the host",
            "_pve_fetch_image",
            danger=True,
        ),
        Entry(
            "Reopen install monitoring (last run / history)",
            "_qemu_reopen_monitor",
        ),
        # Un disque agrandi ne se rétrécit plus, une VM effacée avec ses
        # disques et ses sauvegardes, des volumes orphelins libérés ne se
        # rattrapent pas, et la configuration SSH réécrit ~/.ssh/config :
        # `danger`.
        Section("Manage"),
        Entry("List VMs (qm list)", "_pve_list"),
        Entry("Show a VM IP address", "_pve_vm_ip"),
        Entry("Open the console on a VM", "_pve_console"),
        Entry("Resize a VM disk", "_pve_resize", danger=True),
        Entry("Delete VM(s)", "_pve_delete", danger=True),
        Entry("Clean up (orphan disks)", "_pve_cleanup", danger=True),
        Entry("Test a VM (open Odoo in a CLI browser)", "_pve_test_vm"),
        Entry("Statistics (host and VMs)", "_pve_stats"),
        Entry(
            "SSH configuration (~/.ssh/config, ProxyJump)",
            "_pve_ssh_config",
            danger=True,
        ),
        Entry("Remote desktop tunnel (VNC/RDP over SSH)", "_qemu_tunnel_menu"),
        Entry(
            "Android emulator (start, tunnel, scrcpy)", "_qemu_emulator_menu"
        ),
        Section("Catalog"),
        Entry("List available images and their specs", "_qemu_list_images"),
        Entry("Proxmox - example sequence (dry-run)", "_pve_example"),
        Section("Host"),
        Entry("Change the Proxmox host", "_pve_change_host"),
        FromConfig(
            "proxmox_from_makefile", "execute_from_configuration", "instance"
        ),
    ],
    intro="Deploy a virtual machine on Proxmox VE!",
    render="once",
    opens="_pve_ouvre",
    before="_pve_hote_montre",
)

VPN = Menu(
    "prompt_execute_vpn",
    "VPN",
    [
        # Monter ou descendre un tunnel agit en root, par sudo, sur la
        # configuration réseau du système et sa table de routage : `danger`.
        Section("Connection"),
        Entry("VPN - Connect a profile", "_vpn_connect", danger=True),
        Entry("VPN - Disconnect a profile", "_vpn_disconnect", danger=True),
        Entry("VPN - Status and diagnosis", "_vpn_diagnose"),
        Section("Profiles & secrets"),
        Entry("VPN - Create a profile from a site preset", "_vpn_from_preset"),
        Entry(
            "VPN - Import an AnyConnect profile (.xml)",
            "_vpn_import_anyconnect",
        ),
        Entry("VPN - Add or edit a profile", "_vpn_edit_profile"),
        Entry("VPN - Store secrets in the vault", "_vpn_store_secrets"),
        Entry(
            "VPN - Show the rendered configuration (dry-run)",
            "_vpn_show_config",
        ),
        # Un profil effacé ne se rattrape pas : `danger`.
        Entry("VPN - Delete a profile", "_vpn_delete_profile", danger=True),
        # Installer le client pose des paquets, par sudo : `danger`.
        Section("Host"),
        Entry(
            "VPN - Install the client packages", "_vpn_install", danger=True
        ),
        Entry("VPN - What can this machine do?", "_vpn_check"),
    ],
    intro="VPN tunnels: connect, profiles, vault secrets",
    mark="🔐",
    render="once",
)

LONGTEST = Menu(
    "prompt_execute_longtest",
    "Long test",
    [
        # Un test lancé pour de vrai crée des machines pour des heures, et
        # Défaire les détruit avec leurs disques : `danger`. Un plan à
        # blanc ne crée rien.
        Entry(
            "Nested Proxmox depth: plan only (dry-run)",
            "_longtest_descente",
            kwargs={"script": "deep_proxmox.py", "dry_run": True},
        ),
        Entry(
            "Nested Proxmox depth: run it",
            "_longtest_descente",
            kwargs={"script": "deep_proxmox.py"},
            danger=True,
        ),
        Entry(
            "Nested QEMU depth: plan only (dry-run)",
            "_longtest_descente",
            kwargs={"script": "deep_qemu.py", "dry_run": True},
        ),
        Entry(
            "Nested QEMU depth: run it",
            "_longtest_descente",
            kwargs={"script": "deep_qemu.py"},
            danger=True,
        ),
        Entry(
            "Download cache: plan only (dry-run)",
            "_longtest_run",
            kwargs={"nom": "qemu_cache.py", "args": "--dry-run"},
        ),
        Entry(
            "Download cache: two VMs, measure",
            "_longtest_run",
            kwargs={"nom": "qemu_cache.py", "args": ""},
            danger=True,
        ),
        Entry(
            "Download cache: measure, then cut the upstream",
            "_longtest_run",
            kwargs={"nom": "qemu_cache.py", "args": "--hors-ligne"},
            danger=True,
        ),
        Entry(
            "ERPLibre on NixOS: plan only (dry-run)",
            "_longtest_nixos",
            kwargs={"dry_run": True},
        ),
        Entry("ERPLibre on NixOS: run it", "_longtest_nixos", danger=True),
        Entry(
            "Undo what the descent created", "_longtest_defaire", danger=True
        ),
    ],
    intro="Long tests: real VMs, hours. Not the unit suite.",
    mark="⏳",
    render="once",
)

# Install pose sa propre question (`asks`) : une touche par installation,
# [0], puis un numéro par version d'Odoo. Il se referme après une
# installation. Chaque installation pose des paquets : `danger`.
INSTALL = Menu(
    "prompt_install",
    "Install",
    [
        Entry(
            "ERPLibre only without Odoo, with the required Python",
            "_install_run",
            kwargs={"cmd": "./script/install/install_erplibre.sh"},
            hotkey="q",
            danger=True,
        ),
        Entry(
            "Install all Odoo version with ERPLibre",
            "_install_run",
            kwargs={"cmd": "make install_odoo_all_version"},
            hotkey="w",
            danger=True,
        ),
        Entry(
            "ERPLibre with mobile home",
            "_install_run",
            kwargs={"cmd": "./mobile/install_and_run.sh"},
            hotkey="m",
            danger=True,
        ),
        FromMethod("_install_versions", "_install_version", "version"),
    ],
    back=None,
    closes=True,
    opens="_install_prepare",
    asks="_install_ask",
)
