#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Proxmox : Proxmox VE, ouvert depuis Deploy.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place.

Une entrée qui efface, agit en root sur un hôte, pose des paquets, écrit
une configuration globale ou crée de vraies machines porte `danger` : ni
la TUI de télémétrie ni la page web ne la lancent, son menu seul.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu, Section

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
