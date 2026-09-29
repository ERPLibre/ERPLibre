#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille QEMU, ouverts depuis Execute : Deploy, ses
sous-menus SSH, QEMU/KVM et QEMU cache, avec ses sept menus, Network,
Security, et Docker / Podman avec son Service.

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

QEMU_CACHE = Menu(
    "prompt_execute_qemu_cache",
    "QEMU cache",
    [
        Entry("Cache - Install or reinstall", "_deploy_qemu_cache"),
        Entry("Cache - Diagnose: does it serve?", "_cache_diagnostic"),
        Entry("Cache - Service state", "_cache_service"),
        Entry("Cache - VMs kept out of the cache", "_cache_exceptions"),
        Entry("Cache - Git mirrors: fill them ahead", "_cache_miroir_git"),
        Entry("Cache - Age and cleanup", "_cache_age"),
        Entry("Cache - Guide: how it works", "_cache_guide"),
        Entry("Cache - Tests and performance report", "_cache_tests"),
        Entry("Cache - Fill what offline runs lacked", "_cache_combler"),
        Entry("Cache - Logs", "_cache_journaux"),
        Entry("Cache - Copy it to another machine", "_cache_transfert"),
        Entry("Cache - Automatic cleanup", "_cache_nettoyage_auto"),
    ],
    intro="QEMU download cache for local VMs",
    mark="📦",
    render="once",
)

# Arrêter le service retire ses règles : plus aucune VM n'est détournée,
# et le démarrer les repose.
CACHE_SERVICE = Menu(
    "_cache_service",
    "Service",
    [
        Entry(
            "Service - Start (start)",
            "_cache_systemctl",
            kwargs={"verbe": "start"},
        ),
        Entry(
            "Service - Start at boot (enable)",
            "_cache_systemctl",
            kwargs={"verbe": "enable"},
        ),
        Entry(
            "Service - Do not start at boot (disable)",
            "_cache_systemctl",
            kwargs={"verbe": "disable"},
        ),
        Entry(
            "Service - Stop (stop)",
            "_cache_systemctl",
            kwargs={"verbe": "stop"},
        ),
        Entry(
            "Service - Detailed state (status)",
            "_cache_systemctl",
            kwargs={"verbe": "status --no-pager", "montrer": False},
        ),
        Entry("Service - Logs (log)", "_cache_journal_service"),
    ],
    opens="_cache_service_ouvre",
    render="once",
)

CACHE_EXCEPTIONS = Menu(
    "_cache_exceptions",
    "Exceptions",
    [
        Entry(
            "Exceptions - Remove the stale ones",
            "_cache_retirer_orphelines",
            danger=True,
        ),
        Entry(
            "Exceptions - Remove one by its MAC",
            "_cache_retirer_par_mac",
            danger=True,
        ),
    ],
    opens="_cache_exceptions_ouvre",
    render="once",
    closes_on_result=True,
)

CACHE_GIT_MIRRORS = Menu(
    "_cache_miroir_git",
    "Git mirrors",
    [
        Entry(
            "Mirrors - Fill the base of the active Odoo version",
            "_cache_miroir_remplir_version",
        ),
        Entry(
            "Mirrors - Fill the extra of the active Odoo version",
            "_cache_miroir_remplir_version",
            kwargs={"extra": True},
        ),
        Entry(
            "Mirrors - Fill every manifest, all versions",
            "_cache_miroir_remplir_tout",
        ),
        Entry("Mirrors - List them, heaviest first", "_cache_miroir_lister"),
        Entry("Mirrors - Remove one", "_cache_miroir_retirer", danger=True),
    ],
    opens="_cache_miroir_git_ouvre",
    render="once",
)

CACHE_AGE = Menu(
    "_cache_age",
    "Age and cleanup",
    [
        Entry(
            "Age - By day",
            "_cache_lancer",
            kwargs={"options": "--age-report --age-par jour", "sudo": False},
        ),
        Entry(
            "Age - By week",
            "_cache_lancer",
            kwargs={
                "options": "--age-report --age-par semaine",
                "sudo": False,
            },
        ),
        Entry(
            "Age - By month",
            "_cache_lancer",
            kwargs={"options": "--age-report --age-par mois", "sudo": False},
        ),
        Entry(
            "Clean - What has not served for a while",
            "_cache_nettoyer_age",
            danger=True,
        ),
        Entry("Clean - Everything", "_cache_nettoyer_tout", danger=True),
        Entry("Clean - Forget one URL", "_cache_oublier_url", danger=True),
    ],
    opens="_cache_age_ouvre",
    render="once",
)

CACHE_TESTS = Menu(
    "_cache_tests",
    "Tests",
    [
        Entry("Test - Choose and run", "_cache_assistant"),
        Entry(
            "Test - The plan only (dry-run)",
            "_longtest_run",
            kwargs={"nom": "qemu_cache.py", "args": "--dry-run"},
        ),
        Entry(
            "Test - Performance report",
            "_longtest_run",
            kwargs={"nom": "qemu_cache.py", "args": "--rapport"},
        ),
        Entry(
            "Test - Undo the machines created",
            "_longtest_run",
            kwargs={"nom": "qemu_cache.py", "args": "--detruire"},
            danger=True,
        ),
    ],
    opens="_cache_tests_ouvre",
    render="once",
)

CACHE_LOGS = Menu(
    "_cache_journaux",
    "Logs",
    [
        Entry("Logs - Requests, live", "_cache_voir_acces"),
        Entry(
            "Logs - Only requests that went to the internet, live",
            "_cache_voir_acces",
            kwargs={"amont": True},
        ),
        Entry(
            "Logs - Last 40 requests",
            "_cache_voir_acces",
            kwargs={"suivre": False},
        ),
        Entry("Logs - Service journal, live", "_cache_journal_direct"),
    ],
    opens="_cache_journaux_ouvre",
    render="once",
)

# L'état des deux réglages et du minuteur se relit avant chaque question.
CACHE_CLEANUP = Menu(
    "_cache_nettoyage_auto",
    "Automatic cleanup",
    [
        Entry(
            "Cleanup - Set the age limit",
            "_cache_nettoyage_regler",
            kwargs={"cle": "EL_PURGE_AGE"},
        ),
        Entry(
            "Cleanup - Set the size ceiling",
            "_cache_nettoyage_regler",
            kwargs={"cle": "EL_MAX_SIZE"},
        ),
        Entry(
            "Cleanup - Preview now (dry run)",
            "_cache_nettoyage_lancer",
            kwargs={"a_blanc": True},
        ),
        Entry(
            "Cleanup - Run now",
            "_cache_nettoyage_lancer",
            kwargs={"a_blanc": False},
            danger=True,
        ),
    ],
    intro="Automatic cleanup of the cache",
    mark="\n🧹",
    before="_cache_nettoyage_etat",
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

CONTAINER = Menu(
    "prompt_execute_container",
    "Docker / Podman",
    [
        Section("Engine"),
        Entry(
            "Diagnostic - engine, service, socket, access without sudo",
            "_container_diagnostic",
        ),
        Entry(
            "Service - start, stop, enable at boot, journal",
            "_container_service",
        ),
        Entry(
            "Install Docker", "_container_install", kwargs={"moteur": "docker"}
        ),
        Entry(
            "Install Podman", "_container_install", kwargs={"moteur": "podman"}
        ),
        Section("Inventory"),
        Entry(
            "Images",
            "_container_inventaire",
            kwargs={"sous_commande": "images"},
        ),
        Entry(
            "Containers",
            "_container_inventaire",
            kwargs={"sous_commande": "ps -a"},
        ),
        Entry("Networks", "_container_reseaux"),
        # Chaque nettoyage efface pour de bon : un volume emporte la base de
        # données de son conteneur.
        Section("Cleanup"),
        Entry(
            "Remove unused images, containers and volumes",
            "_container_nettoyage",
            danger=True,
        ),
        Entry(
            "By workspace - a compose project and what it holds",
            "_container_nettoyer_projets",
            danger=True,
        ),
        Entry("Images one by one", "_container_nettoyer_images", danger=True),
        Section("ERPLibre images"),
        Entry("Build an image for an Odoo version", "_container_build_odoo"),
        Entry("Compose - start, stop, logs, processes", "_container_compose"),
        Entry(
            "ERPLibre container - shell, databases, tests, status",
            "_container_erplibre",
        ),
    ],
    intro="Container engines!",
    render="once",
)

# Chaque entrée reçoit la fiche du moteur choisi à l'ouverture et la portée
# de ses unités.
CONTAINER_SERVICE = Menu(
    "_container_service",
    "Service",
    [
        Entry("Start", "_container_geste", kwargs={"geste": "start"}),
        Entry("Stop", "_container_geste", kwargs={"geste": "stop"}),
        Entry("Restart", "_container_geste", kwargs={"geste": "restart"}),
        Entry(
            "Enable at boot", "_container_geste", kwargs={"geste": "enable"}
        ),
        Entry(
            "Disable at boot", "_container_geste", kwargs={"geste": "disable"}
        ),
        Entry("Status and journal", "_container_etat_service"),
    ],
    opens="_container_service_ouvre",
    render="once",
)
