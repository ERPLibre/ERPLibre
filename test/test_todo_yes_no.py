#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les questions oui/non de TODO : le défaut de chacune, lu dans le
code et épinglé dans CONFIRM_DEFAULTS.

Chaque appel `ui.confirm(` de `script/todo`, hors du port (`ui/`), donne
une clé (fichier, fonction, première clé `t("…")` de ses arguments, ou
`<dynamique>`) et la liste des défauts de ses appels, dans l'ordre du
fichier : un booléen littéral, `état` pour un nom (le défaut est l'état
qu'il porte), `typed` pour une confirmation tapée, sinon le texte de
l'expression. Les appels des enveloppes de WRAPPERS, qui posent leur
question par `ui.confirm`, entrent de même, leur défaut lu sur `default=`
au site appelant ; le `ui.confirm` d'une enveloppe n'a pas de ligne. Un
défaut qui change, une question qui naît ou part, change la table dans le
même commit. Le défaut est un booléen littéral, `typed` pour une
confirmation tapée, ou l'état pour les seules fonctions de
STATE_DEFAULTS.

Trois gardes ferment la porte aux règles écrites hors du port : aucun
texte ne porte d'indice oui/non hors de HINTED_TEXTS, aucune réponse lue
n'est comparée à un mot oui/non hors de YES_NO_COMPARES, et aucune aide
oui/non n'est définie ni lue hors de YES_NO_HELPERS. Chaque table ne
fait que baisser.
"""

import ast
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from script.todo import auto_ask
from script.todo.todo_i18n import TRANSLATIONS

REPO = Path(__file__).resolve().parent.parent
TODO = REPO / "script" / "todo"
PORT = TODO / "ui"

# Fonctions qui posent leur question par `ui.confirm`. Un nom nu reconnaît
# tout appel de ce nom ; « Classe.méthode », `self.méthode(` dans une
# méthode de cette classe.
WRAPPERS = {"show_and_ask", "ask_and_install", "TodoUpgrade.confirm"}

# Les fonctions dont le défaut est un état qu'elles reçoivent : celui de
# la VM, du profil VPN, ou du gel que propose l'appelant.
STATE_DEFAULTS = {
    "GitForkMenuMixin._git_question_gel",
    "QemuManageMixin._qemu_ask_bool",
    "VpnMenuMixin._vpn_ask_flag",
}

# (fichier, fonction, première clé t()) → défauts, dans l'ordre du fichier.
CONFIRM_DEFAULTS = {
    (
        "script/todo/assistant_menu.py",
        "AssistantMenuMixin._llm_keep",
        "Keep them all?",
    ): [False],
    (
        "script/todo/assistant_menu.py",
        "AssistantMenuMixin._llm_sweep_cidr",
        "<dynamique>",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_assure_emulation",
        "Install buildx and QEMU now?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_build_odoo",
        "Continue?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_build_odoo",
        "Rebuild without cache?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_install",
        "Continue?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_install",
        "Use vendor packages?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_nettoyage",
        "Continue?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_nettoyer_images",
        "Remove?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_nettoyer_projets",
        "Remove?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Continue anyway?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Continue?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Delete it?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Drop it and restore over it?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Is this database a copy? If unsure, yes.",
    ): [True],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Neutralize (mail servers, crons)?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Update every module after the restore (-u all)?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Keep a _cache_ copy, not neutralized, to speed up the next restore"
        " of this image?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Neutralize the database?",
    ): [True],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Update all addons after neutralizing?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Update all addons before neutralizing?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Update all addons?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager.duplicate_database",
        "Neutralize the copy?",
    ): [True],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_ajouter_depot",
        "Add it without checking the branch?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_ajouter_depot",
        "Fork it for an organisation now?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_ajouter_existant",
        "Set it aside (renamed, kept) and let repo clone it now?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_assistant_jeton",
        "Store it in the ERPLibre KeePass vault?",
    ): [True],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_client",
        "Continue anyway?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_creer_branche_plusieurs",
        "Push it to each project's remote?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_creer_pull_request",
        "Open it as a draft?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_creer_pull_request",
        "Open the pull request on",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_fork_organisation",
        "Add the upstream remote to the local clone now?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_fork_organisation",
        "Change the manifest to take this fork?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_fork_organisation",
        "Fork it?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_forks_orphelins",
        "Archive these repositories on GitHub",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_nettoyer_branches",
        "Also ask GitHub for branches merged by squash?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_nettoyer_branches",
        "Delete these local branches?",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_nettoyer_branches",
        "Fetch the remotes first, with prune?",
    ): [True],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_proposer_assistant",
        "<dynamique>",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_question_gel",
        "Freeze it on the head of the branch?",
    ): ["état"],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_retirer_depot",
        "Remove from the manifest",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_retirer_depot",
        "Remove the local clone too? repo keeps it if it holds uncommitted work.",
    ): [False],
    (
        "script/todo/git_fork_menu.py",
        "GitForkMenuMixin._git_statut_mes_pull_requests",
        "Only the repositories of the manifests?",
    ): [True],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_appliquer",
        "Apply the upgrade?",
    ): [False],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_approfondir",
        "Deepen the shallow clones (network)?",
    ): [False],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_geler",
        "Also freeze the upstream base of each fork (network)?",
    ): [False],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_geler",
        "Write these changes to the manifest files?",
    ): [False],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_publier",
        "Freeze the versions again now?",
    ): [True],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_publier_un",
        "Push to the fork?",
    ): [False],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_retenir",
        "Push",
    ): [False],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_tirer",
        "Clone the new repositories?",
    ): [False],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_tirer",
        "Deepen the shallow clones (network)?",
    ): [False],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_tirer",
        "Install the Python dependencies now (poetry install --no-root)?",
    ): [False],
    (
        "script/todo/git_repo_menu.py",
        "GitRepoMenuMixin._git_repo_tirer",
        "Pull the repositories?",
    ): [False],
    (
        "script/todo/healthcheck.py",
        "_installer_hooks",
        "Replace it?",
    ): [False],
    (
        "script/todo/healthcheck.py",
        "_regenerer_manifeste",
        "Switch to production: regenerate the local manifest and sync?",
    ): [False],
    (
        "script/todo/healthcheck.py",
        "_remplacer_venvs_obsoletes",
        "Delete the obsolete venv %s?",
    ): [False],
    (
        "script/todo/healthcheck.py",
        "_remplacer_venvs_obsoletes",
        "Install %s? It becomes the active version, and takes a while",
    ): [False],
    (
        "script/todo/install_update_menu.py",
        "InstallUpdateMenuMixin._update_choisir_deplacements",
        "Move it aside to %s?",
    ): [False],
    (
        "script/todo/install_update_menu.py",
        "InstallUpdateMenuMixin._update_choisir_deplacements",
        "Synchronize anyway?",
    ): [False],
    (
        "script/todo/install_update_menu.py",
        "InstallUpdateMenuMixin._update_reprendre",
        "Copy the local branches of %s into the new clone?",
    ): [True],
    (
        "script/todo/install_update_menu.py",
        "InstallUpdateMenuMixin._update_reprendre",
        "Delete the old clone %s?",
    ): [False],
    (
        "script/todo/longtest_menu.py",
        "LongTestMenuMixin._longtest_defaire",
        "Destroy all that?",
    ): [False],
    (
        "script/todo/longtest_menu.py",
        "LongTestMenuMixin._longtest_run",
        "<dynamique>",
    ): [False],
    (
        "script/todo/mail/menu.py",
        "_cache_size_and_purge",
        "mail_purge_confirm",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_appel_voip",
        "modem_call_confirm",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_appel_voip",
        "modem_continue",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_appel_voip",
        "voip_handset_ask",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_appel_voip",
        "voip_mic_ask",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_appeler",
        "modem_call_confirm",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_basculer_uac",
        "modem_uac_enable",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_diagnostic",
        "modem_continue",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_essai_combine",
        "modem_continue",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_essai_combine",
        "voip_mic_ask",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_regle_audio",
        "modem_audio_rule_ask_off",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_repondeur_messages_erplibre",
        "modem_ans_delete",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_repondeur_messages_recuperes",
        "modem_ans_delete",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_repondeur_recuperer",
        "modem_continue",
    ): [False, False, True],
    (
        "script/todo/modem/menu.py",
        "_sonder_audio",
        "modem_call_confirm",
    ): [False],
    (
        "script/todo/modem/menu.py",
        "_sonder_audio",
        "modem_probe_heard",
    ): [False],
    (
        "script/todo/module_menu.py",
        "ModuleMenuMixin._module_analysis_diff",
        "Include them?",
    ): [True],
    (
        "script/todo/module_menu.py",
        "ModuleMenuMixin._module_auto_install",
        "Commit the changed manifests in each repository (current branch)?",
    ): [False],
    (
        "script/todo/module_menu.py",
        "ModuleMenuMixin._module_auto_install",
        "Push each commit to its tracked branch?",
    ): [False],
    (
        "script/todo/module_menu.py",
        "ModuleMenuMixin._module_statistique",
        "Continue?",
    ): [False],
    (
        "script/todo/proxmox_menu.py",
        "ProxmoxMenuMixin._pve_add_hostkey",
        "Record it?",
    ): [False],
    (
        "script/todo/proxmox_menu.py",
        "ProxmoxMenuMixin._pve_change_state",
        "Confirm?",
    ): [False],
    (
        "script/todo/proxmox_menu.py",
        "ProxmoxMenuMixin._pve_cleanup",
        "Free them?",
    ): [False],
    (
        "script/todo/proxmox_menu.py",
        "ProxmoxMenuMixin._pve_confirm_spec",
        "Deploy this VM now?",
    ): [True],
    (
        "script/todo/proxmox_menu.py",
        "ProxmoxMenuMixin._pve_delete",
        "Apply: %s?",
    ): [False],
    (
        "script/todo/proxmox_menu.py",
        "ProxmoxMenuMixin._pve_delete",
        "Confirm for real?",
    ): [False],
    (
        "script/todo/proxmox_menu.py",
        "ProxmoxMenuMixin._pve_deploy_prompts",
        "Deploy this VM now?",
    ): [True],
    (
        "script/todo/proxmox_menu.py",
        "ProxmoxMenuMixin._pve_deploy_prompts",
        "Install ERPLibre on it?",
    ): [True],
    (
        "script/todo/python_menu.py",
        "PythonMenuMixin._poetry_drift_actif",
        "Update the venv to match the lock?",
    ): [False],
    (
        "script/todo/python_menu.py",
        "PythonMenuMixin._poetry_drift_autre",
        "Update the venv to match the lock?",
    ): [False],
    (
        "script/todo/python_menu.py",
        "PythonMenuMixin._venv_outillage_drift",
        "Install the missing requirements?",
    ): [False],
    (
        "script/todo/python_menu.py",
        "PythonMenuMixin.execute_python_versions",
        "Run them now?",
    ): [False],
    (
        "script/todo/qemu_access.py",
        "QemuAccessMixin._qemu_emulator_menu",
        "Close it now?",
    ): [False],
    (
        "script/todo/qemu_access.py",
        "QemuAccessMixin._qemu_scrcpy_tunnel",
        "Open the tunnel now?",
    ): [False],
    (
        "script/todo/qemu_access.py",
        "QemuAccessMixin._qemu_ssh_retry_with_key",
        "<dynamique>",
    ): [True],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_assistant",
        "Run these long tests?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_combler",
        "Replay these addresses through the cache now?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_combler_permis",
        "Replay anyway?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_miroir_remplir",
        "Fill the git mirrors now?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_miroir_retirer",
        "Remove this mirror?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_nettoyage_regler",
        "Write this setting?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_nettoyer_age",
        "Erase what is listed above?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_nettoyer_tout",
        "Erase the whole cache?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_oublier_url",
        "Remove this entry from the store?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_sans_sudo_la_bas",
        "Send it now, and print the command to finish there?",
    ): [False],
    (
        "script/todo/qemu_cache_menu.py",
        "QemuCacheMenuMixin._cache_transfert",
        "Copy now?",
    ): [False],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_ask_vm_account",
        "Keep the password in the VM?",
    ): [False],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_check_libvirt_group",
        "Run it now?",
    ): [True],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_collect_guest_cli",
        "Generate one now?",
    ): [True],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_collect_options_cli",
        "3D acceleration (host GPU), even without a screen?",
    ): [False],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_collect_options_cli",
        "Add each VM to ~/.ssh/config?",
    ): [True],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_collect_options_cli",
        "Install ERPLibre into ~/git/erplibre on each VM?",
    ): [True],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_collect_options_cli",
        "Interactive monitoring dashboard?",
    ): [True],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_collect_options_cli",
        "Keep this VM out of the download cache?",
    ): [False],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_collect_options_cli",
        "Watch the VMs start (no install)?",
    ): [True],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_confirm_collisions",
        "Continue despite these collisions?",
    ): [False],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_coupure_libre",
        "Lift it and continue?",
    ): [False],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_en_ligne_malgre_la_coupure",
        "Deploy anyway, offline?",
    ): [False],
    (
        "script/todo/qemu_deploy.py",
        "QemuDeployMixin._qemu_offer_orphan_removal",
        "Continue anyway?",
    ): [False],
    (
        "script/todo/qemu_install_monitor.py",
        "install_cli_browser",
        "Install now?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._cleanup_delete_files",
        "<dynamique>",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._cleanup_ghost_domains",
        "Undefine these ghost domains?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._cleanup_ssh_config",
        "Remove these ~/.ssh/config entries?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._cleanup_stale_leases",
        "Clear these stale leases?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_adjust_hardware",
        "Apply these changes?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_ask_backup",
        "Back up anyway, at the risk of filling the disk?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_ask_backup",
        "Back up the disk before shrinking?",
    ): [True],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_ask_bool",
        "<dynamique>",
    ): ["état"],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_change_state",
        "Adjust hardware before starting?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_change_state",
        "Apply: %s?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_change_state",
        "Confirm for real?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_cleanup",
        "Delete these orphan files?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_delete_vm",
        "Also delete disk images (qcow2 + seed ISO)?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_delete_vm",
        "Confirm deletion?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_diag_offer_tools",
        "Install them now?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_download_image",
        "Verify SHA256 after download?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_grow_via_console",
        "Open the serial console now?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_install_shrink_tools",
        "Install them?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_offer_start",
        "Start the VM now?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_resize_disk",
        "Delete this backup now?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_resize_disk",
        "Grow the guest filesystem now (over SSH)?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_resize_disk",
        "The VM must be off. Shut it down and retry?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_shrink_typed",
        "Type the VM name (%s) to confirm you understand the risk: ",
    ): ["typed"],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_shutdown_wait",
        "Graceful shutdown timed out. Force off (destroy)?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_start_failed",
        "Remove the 3D and start again?",
    ): [True],
    (
        "script/todo/qemu_menu.py",
        "QemuMenuMixin._qemu_ensure_tools",
        "Install the QEMU/libvirt tools now?",
    ): [True],
    (
        "script/todo/qemu_menu.py",
        "QemuMenuMixin._qemu_stats",
        "Erase %s recorded runs?",
    ): [False],
    (
        "script/todo/qemu_network.py",
        "QemuNetworkMixin._qemu_network_recreate",
        "Power off VMs that ignore the shutdown?",
    ): [False],
    (
        "script/todo/qemu_recover.py",
        "QemuRecoverMixin._qemu_recover_ensure_tools",
        "Install libguestfs now?",
    ): [True],
    (
        "script/todo/qemu_recover.py",
        "QemuRecoverMixin._qemu_recover_files",
        "Run the diagnostics first?",
    ): [False],
    (
        "script/todo/seal_menu.py",
        "SealMenuMixin._seal_ask_folder",
        "Replace it?",
    ): [False],
    (
        "script/todo/seal_menu.py",
        "SealMenuMixin.execute_seal_guide",
        "Are the sealed PDFs opened outside the organisation, in a reader nobody configures?",
    ): [False],
    (
        "script/todo/seal_menu.py",
        "SealMenuMixin.execute_seal_status",
        "Remove the %s folders without a seal from the registry?",
    ): [False],
    (
        "script/todo/sms/menu.py",
        "_appairer_par_usb",
        "sms_pair_confirm",
    ): [False],
    (
        "script/todo/sms/menu.py",
        "_place_test_call",
        "sms_call_confirm",
    ): [False],
    (
        "script/todo/sms/menu.py",
        "_reset",
        "sms_confirm_reset",
    ): [False],
    (
        "script/todo/sms/menu.py",
        "_step_mobile",
        "sms_confirm_mobile",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_caches_sudo",
        "Run these commands with sudo?",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_cpu_installer",
        "Install {name}?",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_diagnostic",
        "Save this report in private/diagnostic/?",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_espace",
        "Delete these items?",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_gpu_sudo",
        "Read them with sudo? The password is asked here.",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._analyse_offer_install",
        "<dynamique>",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._analyse_offer_install",
        "Go ahead?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._claude_install_preferred_plugins",
        "Install these plugins?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._claude_plugin_uninstall",
        "Uninstall this plugin?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._claude_reglages_ecrire",
        "Write it?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._confirm_or_discard",
        "<dynamique>",
    ): [True],
    (
        "script/todo/todo.py",
        "TODO._confirm_or_discard",
        "Keep your answers and ask again?",
    ): [True],
    (
        "script/todo/todo.py",
        "TODO._demander_systeme",
        "First system installation? Installs the system packages first",
    ): [True, False],
    (
        "script/todo/todo.py",
        "TODO._deploy_port_forward",
        "Continue anyway?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._deploy_port_forward",
        "Try anyway?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._deploy_qemu_cache",
        "Install the QEMU download cache?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._deploy_socks_proxy",
        "Try anyway?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._filestore_purge_dead",
        "<dynamique>",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._filestore_tidy_nested",
        "Go ahead?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._git_install_hooks",
        "Replace it?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._image_db_choose_version",
        "The images are generated with the active Odoo: switch to"
        " Odoo %s now (make switch_odoo_%s)?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._install_system_step",
        "Open PyCharm?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._list_claude_commands",
        "<dynamique>",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._list_claude_commands",
        "Show the differences?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._monitoring_anonymize_options",
        "Anonymise the logins too?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._monitoring_anonymize_options",
        "Keep the digit count?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._monitoring_image_name",
        "db_restore only reads image_db/. Link it there (%s)?",
    ): [True],
    (
        "script/todo/todo.py",
        "TODO._monitoring_restore",
        "Neutralize the database?",
    ): [True],
    (
        "script/todo/todo.py",
        "TODO._proposer_identite_git",
        "Configure it now?",
    ): [True],
    (
        "script/todo/todo.py",
        "TODO._proposer_identite_git",
        "Is this correct?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._run_instance",
        "Do you want a new instance?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._setup_claude_command",
        "Do you want to overwrite the file?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._shell_install_starship_binary",
        "Install starship?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._shell_install_starship_binary",
        "Run the upstream installer?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._todo_web_stop",
        "<dynamique>",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._virt_manager_offer",
        "Add the missing connections to virt-manager?",
    ): [True],
    (
        "script/todo/todo.py",
        "TODO.callback_make_mobile_home",
        "Android Studio is needed: change the menu picture?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO.callback_make_mobile_home",
        "Compile with debug information?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO.callback_make_mobile_home",
        "Do you want to personalize the mobile application?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO.callback_make_mobile_home",
        "mobile_lan_cleartext_ask",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO.execute_test_module",
        "Keep the temporary database?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO.upgrade_poetry",
        "Install the new dependencies in the Odoo venv now?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO.upgrade_poetry",
        "The update needs your git repositories: fetch them all first?",
    ): [False],
    (
        "script/todo/todo_install.py",
        "run_steps",
        "Upgrade the whole system first?",
    ): [False],
    (
        "script/todo/todo_telemetry.py",
        "install_sensors",
        "Install lm-sensors now?",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.confirm_rewind",
        "Confirm?",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.copy_to_image_db",
        "A file already exists, do you want to continue?",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.execute_odoo_upgrade",
        "Do you want to upgrade all addons of the database?",
    ): [True],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.execute_odoo_upgrade",
        "Missing or duplicate module detected at init, do you want to"
        " continue?",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.execute_odoo_upgrade",
        "Open the server with Selenium to test this upgrade?",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.execute_odoo_upgrade",
        "Test the migration?",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.execute_odoo_upgrade",
        "Would you like to install '%s'?",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.neutralize_cow_views",
        "Neutralize these copies so the upgrade can proceed? Their arch is"
        " kept and the change is reversible.",
    ): [True],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.prompt_auto_execute",
        "Auto-run: take the default answer after",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.prompt_database_cleanup",
        "Clean the database before testing the pages?",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.prompt_fix_view_type",
        "Correct them?",
    ): [True],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.prompt_purge_dead_attachments",
        "Delete them?",
    ): [False],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.prompt_smoke_public_url",
        "Request every public URL of this database now?",
    ): [True],
    (
        "script/todo/todo_upgrade.py",
        "TodoUpgrade.prompt_uninstall_theme",
        "Uninstall them properly before migrating?",
    ): [False],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_ask_hors_cellules",
        "Keep the VBA macros in the copy?",
    ): [False],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_ask_hors_cellules",
        "Keep the charts in the copy?",
    ): [False],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_ask_options",
        "Advanced options?",
    ): [False],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_ask_options",
        "Anonymise the header row too?",
    ): [False],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_ask_options",
        "Anonymise this file?",
    ): [False],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_ask_options",
        "Keep the digit count?",
    ): [False],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_ask_options",
        "Replace numbers?",
    ): [True],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_ask_options",
        "Replace text?",
    ): [True],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_copies",
        "Delete all copies in private/transform/?",
    ): [False],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_ecran",
        "Open the TUI for setup?",
    ): [True],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_install_env",
        "Create it now?",
    ): [True],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_preview",
        "Write?",
    ): [True],
    (
        "script/todo/vpn_menu.py",
        "VpnMenuMixin._vpn_ask_flag",
        "<dynamique>",
    ): ["état"],
    (
        "script/todo/vpn_menu.py",
        "VpnMenuMixin._vpn_connect",
        "Connect it again?",
    ): [False],
    (
        "script/todo/vpn_menu.py",
        "VpnMenuMixin._vpn_connect",
        "Run this plan?",
    ): [False],
    (
        "script/todo/vpn_menu.py",
        "VpnMenuMixin._vpn_delete_profile",
        "Delete profile « %s »?",
    ): [False],
    (
        "script/todo/vpn_menu.py",
        "VpnMenuMixin._vpn_edit_profile",
        "Advanced settings?",
    ): [False],
    (
        "script/todo/vpn_menu.py",
        "VpnMenuMixin._vpn_install",
        "Install it as well?",
    ): [False],
    (
        "script/todo/vpn_menu.py",
        "VpnMenuMixin._vpn_select_xml",
        "Browse it?",
    ): [True],
}

# Un indice oui/non : deux lettres de réponse séparées d'une barre, « y/N »
# ou « [O/n] », une lettre seule entre crochets ou parenthèses, « (Y) », ou
# un défaut nommé, « , default: N », « (défaut : non) ». « default: » suivi
# d'une valeur qui n'est pas un oui/non n'en est pas un.
HINT = re.compile(
    r"\b[yo]\s*/\s*[yno]\b"
    r"|[\[(][yo][\])]"
    r"|[(,]\s*(?:default|défaut)\s*:\s*(?:yes|no|oui|non|[yno])\b",
    re.IGNORECASE,
)

# Les textes qui portent un indice oui/non, clés de TRANSLATIONS ou
# littéraux d'une question, chacun avec ce qui le tient hors du port. La
# table ne fait que baisser : une question neuve passe par `ui.confirm`,
# dont le texte ne porte pas d'indice.
HINTED_TEXTS = {
    "[Y/n]: ": (
        "l'indice que le port ajoute à une confirmation, et que « Export a"
        " backup? » (execute_odoo_upgrade, question texte) reprend pour son"
        " propre indice"
    ),
    "[y/N]: ": "l'indice que le port ajoute à une confirmation",
    "Install it now? (Y/n): ": (
        "textual_setup.ensure, que des scripts lancés à part appellent"
        " avec leur propre `ask`"
    ),
    "Create it now? (Y/n): ": (
        "transform_setup.create et ensure, que des scripts lancés à part"
        " appellent avec leur propre `ask`"
    ),
    "Type 'oui' to confirm (default: no): ": (
        "_confirm_drop, une confirmation tapée en toutes lettres"
    ),
    "Run it now? [y/o/N] ": (
        "l'amorçage de todo.py, sous le Python du système, avant que `ui`"
        " puisse s'importer"
    ),
}

# Les appels qui rendent une réponse tapée, et ceux qui posent une
# question : les premiers, plus les confirmations.
ANSWER_ASKS = {
    "input",
    "ui.ask",
    "click.prompt",
    "self.ask",
    "self.ask_gate",
    "auto_ask.ask",
}
QUESTIONS = ANSWER_ASKS | {"ui.confirm", "click.confirm", "self.confirm"}
# Les mots d'un oui ou d'un non, que seul le port lit.
YES_NO_WORDS = {"y", "yes", "o", "oui", "n", "no", "non"}
# Les méthodes qui gardent une réponse lue telle qu'elle : la comparaison
# de `réponse.strip().lower()` porte toujours sur la réponse.
KEEPS_ANSWER = {"strip", "lstrip", "rstrip", "lower", "casefold"}
# Les opérateurs d'une comparaison ; `startswith` en est une aussi.
COMPARE_OPS = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)

# Les fonctions qui comparent une réponse lue à un mot oui/non, chacune
# avec la raison qui la tient hors du port. La table ne fait que baisser.
YES_NO_COMPARES = {
    ("script/todo/database_manager.py", "_confirm_drop"): (
        "une confirmation tapée : « oui » ou « yes » en toutes lettres"
    ),
    ("script/todo/qemu_deploy.py", "_qemu_collect_options_cli"): (
        "« n » y est une valeur, le plafond des cœurs de l'hôte"
    ),
    ("script/todo/todo.py", "_bootstrap"): (
        "l'amorçage, sous le Python du système, avant que `ui` puisse"
        " s'importer"
    ),
    ("script/todo/todo.py", "_telemetry_tui_loop"): (
        "une pause : « r » ou oui revient au suivi, Entrée quitte"
    ),
    ("script/todo/todo_upgrade.py", "execute_odoo_upgrade"): (
        "« n » = aucun, dans la liste des modules manquants à supprimer"
    ),
    ("script/todo/todo_upgrade.py", "prompt_reset_stale_cow_views"): (
        "« n » = aucune, dans la liste des vues à réinitialiser"
    ),
}

# Des fonctions qui comparent à un mot oui/non une valeur qui n'est pas
# une réponse lue : une sortie de commande, un champ, une unité (« o »,
# l'octet), une lettre de l'invite. La garde ne les voit pas.
NOT_ANSWERS = {
    ("script/todo/assistant_menu.py", "_llm_gpt_catalogue"),
    ("script/todo/container_runtime.py", "rootless"),
    ("script/todo/install_non_interactif.py", "lire_reponses"),
    ("script/todo/proxmox_deploy_form.py", "on_button_pressed"),
    ("script/todo/qemu_access.py", "_qemu_ssh_probe_remote"),
    ("script/todo/qemu_cache_menu.py", "_cache_humain"),
    ("script/todo/qemu_deploy.py", "_qemu_sudo_lines"),
    ("script/todo/qemu_hardware.py", "hw_state"),
    ("script/todo/system_menu.py", "octets"),
    ("script/todo/ui/legacy.py", "confirm_default"),
}

# Le nom d'une aide qui lit un oui ou un non hors du port.
HELPER_NAME = re.compile(
    r"_(?:is_(?:yes(?:_default_yes)?|no)|oui\w*|non|system_oui|python_oui)"
)

# Les aides oui/non de `script/todo` hors du port, (fichier, nom) → la
# raison qui les y tient. La table ne fait que baisser.
YES_NO_HELPERS = {
    ("script/todo/transform_setup.py", "_oui"): (
        "transform_setup.create et ensure, que des scripts lancés à part"
        " appellent avec leur propre `ask`"
    ),
}


def _key(call) -> str:
    """La première clé `t("…")` des arguments de `call`, hors `default=`,
    dans l'ordre du source ; `<dynamique>` sans elle."""
    values = [*call.args]
    values += [kw.value for kw in call.keywords if kw.arg != "default"]
    found = []
    for value in values:
        for node in ast.walk(value):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func, first = node.func, node.args[0]
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            literal = isinstance(first, ast.Constant)
            if name == "t" and literal and isinstance(first.value, str):
                found.append((node.lineno, node.col_offset, first.value))
    return min(found)[2] if found else "<dynamique>"


def _default(value):
    """Le défaut que lit la table pour l'expression `value` (None quand
    l'appel n'en passe pas)."""
    if value is None:
        return None
    if isinstance(value, ast.Constant) and isinstance(value.value, bool):
        return value.value
    if isinstance(value, ast.Name):
        return "état"
    return ast.unparse(value)


def _asks(call, wrappers, owner) -> str | None:
    """`ui` pour un appel `ui.confirm(`, `wrapper` pour l'appel d'une
    enveloppe de `wrappers` depuis la classe `owner`, None sinon."""
    func = call.func
    target = getattr(func, "value", None)
    if isinstance(func, ast.Attribute) and func.attr == "confirm":
        if isinstance(target, ast.Name) and target.id == "ui":
            return "ui"
    name = getattr(func, "id", None) or getattr(func, "attr", None)
    if name in wrappers:
        return "wrapper"
    is_self = isinstance(target, ast.Name) and target.id == "self"
    if is_self and f"{owner}.{name}" in wrappers:
        return "wrapper"
    return None


def survey_source(source, path, wrappers=WRAPPERS) -> dict:
    """Les lignes de la table que donne le module `source`, de chemin
    `path` ; `wrappers` : les enveloppes, comme WRAPPERS."""
    rows = {}

    def visit(node, scope, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, [*scope, child.name], child.name)
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, [*scope, child.name], owner)
                continue
            if isinstance(child, ast.Call):
                read(child, ".".join(scope) or "<module>", owner)
            visit(child, scope, owner)

    def read(call, where, owner):
        kind = _asks(call, wrappers, owner)
        if kind is None or where in wrappers:
            return
        given = {kw.arg: kw.value for kw in call.keywords}
        if kind == "ui" and "typed" in given:
            default = "typed"
        elif kind == "ui" and "default" not in given and len(call.args) > 1:
            default = _default(call.args[1])
        else:
            default = _default(given.get("default"))
        rows.setdefault((path, where, _key(call)), []).append(default)

    visit(ast.parse(source), [], None)
    return rows


def survey() -> dict:
    """Les lignes de la table que donne `script/todo`, hors du port."""
    rows = {}
    for path in sorted(TODO.rglob("*.py")):
        if path.is_relative_to(PORT):
            continue
        name = str(path.relative_to(REPO))
        rows.update(survey_source(path.read_text(encoding="utf-8"), name))
    return rows


def guarded_files() -> list:
    """Les fichiers dont les questions oui/non passent par le port :
    `script/todo` hors de `ui/port.py`, et l'analyse de migration, que
    TODO lance dans son propre processus."""
    paths = [p for p in sorted(TODO.rglob("*.py")) if p != PORT / "port.py"]
    analyse = REPO / "script" / "analyse" / "check_migration_quality_tui.py"
    return [*paths, analyse]


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def hinted_literals(source) -> set:
    """Les chaînes littérales à indice des arguments des questions
    (QUESTIONS) de `source` : clés `t("…")` et morceaux de f-string
    compris, une chaîne passée par un nom non."""
    found = set()
    for call in ast.walk(ast.parse(source)):
        if not (
            isinstance(call, ast.Call) and _dotted(call.func) in QUESTIONS
        ):
            continue
        for value in [*call.args, *(kw.value for kw in call.keywords)]:
            found |= {
                node.value
                for node in ast.walk(value)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and HINT.search(node.value)
            }
    return found


def hinted_texts() -> set:
    """Les clés de TRANSLATIONS dont la clé ou une traduction porte un
    indice, et les littéraux à indice des questions de guarded_files."""
    found = {
        key
        for key, texts in TRANSLATIONS.items()
        if any(HINT.search(text) for text in (key, *texts.values()))
    }
    for path in guarded_files():
        found |= hinted_literals(path.read_text(encoding="utf-8"))
    return found


def _own_nodes(scope):
    """Les nœuds de `scope`, une fonction ou un module, sans ceux des
    fonctions et classes qu'il définit : chacune a ses propres noms."""
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    stack = [n for n in scope.body if not isinstance(n, nested)]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(
            n for n in ast.iter_child_nodes(node) if not isinstance(n, nested)
        )


def _answer_of(node):
    """`node` sans ce qui garde la réponse telle qu'elle : les méthodes de
    KEEPS_ANSWER, l'indice `[0]`, la valeur d'un `:=`."""
    while True:
        func = getattr(node, "func", None)
        if isinstance(func, ast.Attribute) and func.attr in KEEPS_ANSWER:
            node = func.value
        elif isinstance(node, ast.Subscript) and (
            isinstance(node.slice, ast.Constant) and node.slice.value == 0
        ):
            node = node.value
        elif isinstance(node, ast.NamedExpr):
            node = node.value
        else:
            return node


def _reads_answer(node, names) -> bool:
    """Vrai quand `node` est une réponse lue : un appel d'ANSWER_ASKS, ou
    un nom de `names`, au travers de _answer_of. Un `or` ou un `and` en
    est une dès qu'une de ses valeurs l'est : `input() or "n"` rend la
    réponse quand elle n'est pas vide."""
    node = _answer_of(node)
    if isinstance(node, ast.BoolOp):
        return any(_reads_answer(value, names) for value in node.values)
    if isinstance(node, ast.Call):
        return _dotted(node.func) in ANSWER_ASKS
    return isinstance(node, ast.Name) and node.id in names


def _yes_no_word(node) -> bool:
    """Vrai pour une constante, ou un tuple, une liste, un ensemble de
    constantes, dont l'une est un mot de YES_NO_WORDS."""
    items = [node]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        items = node.elts
    if not items or not all(isinstance(i, ast.Constant) for i in items):
        return False
    return any(
        isinstance(i.value, str) and i.value.lower() in YES_NO_WORDS
        for i in items
    )


def _answer_names(nodes) -> set:
    """Les noms que `nodes` assignent depuis une réponse lue, de proche en
    proche : `a = input()`, puis `b = a.strip()`."""
    assigned = []
    for node in nodes:
        if isinstance(node, ast.Assign):
            assigned += [(target, node.value) for target in node.targets]
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value:
            assigned.append((node.target, node.value))
    names, grown = set(), True
    while grown:
        grown = False
        for target, value in assigned:
            if not isinstance(target, ast.Name) or target.id in names:
                continue
            if _reads_answer(value, names):
                names.add(target.id)
                grown = True
    return names


def _compared(node):
    """Les côtés que `node` compare : ceux de `==`, `!=`, `in`, `not in`,
    et `a.startswith(b)`, qui compare le début de `a` à `b` ; None pour
    tout autre nœud."""
    if isinstance(node, ast.Compare):
        if all(isinstance(op, COMPARE_OPS) for op in node.ops):
            return [node.left, *node.comparators]
        return None
    func = getattr(node, "func", None)
    if isinstance(func, ast.Attribute) and func.attr == "startswith":
        return [func.value, *node.args]
    return None


def yes_no_compares(source) -> dict:
    """(fonction, ligne) → vrai quand la comparaison porte sur une réponse
    lue, pour chaque comparaison de `source` (_compared) dont un côté est
    un mot oui/non (_yes_no_word). Une réponse lue : un appel
    d'ANSWER_ASKS, ou un nom que la MÊME fonction en assigne ; un
    paramètre n'en est pas une, il porte une valeur lue ailleurs. Le code
    hors de toute fonction compte sous `<module>`."""
    tree = ast.parse(source)
    scopes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    found = {}
    for scope in [tree, *scopes]:
        nodes = list(_own_nodes(scope))
        names = _answer_names(nodes)
        for node in nodes:
            sides = _compared(node) or []
            if any(_yes_no_word(side) for side in sides):
                where = getattr(scope, "name", "<module>")
                found[(where, node.lineno)] = any(
                    _reads_answer(side, names) for side in sides
                )
    return found


def yes_no_helpers(source) -> set:
    """Les noms d'aide oui/non (HELPER_NAME) que `source` définit, par
    `def` ou par une lambda affectée, ou qu'il lit, en nom nu ou en
    attribut : un appel comme une référence passée sans appel
    (`run(ask=_oui)`). Un nom affecté d'autre chose qu'une lambda n'en
    est pas un."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            name = node.id
        elif isinstance(node, ast.Attribute) and isinstance(
            node.ctx, ast.Load
        ):
            name = node.attr
        elif isinstance(node, ast.Assign) and isinstance(
            node.value, ast.Lambda
        ):
            found |= {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
                and HELPER_NAME.fullmatch(target.id)
            }
            continue
        else:
            continue
        if HELPER_NAME.fullmatch(name):
            found.add(name)
    return found


SAMPLE = """
def wipe(name, state):
    ui.confirm(t("Delete it?"), default=False)
    ui.confirm(t("Delete it?"), True)
    ui.confirm(f"{name}: " + t("Keep it?"), default=state)
    ui.confirm(text, default=False)
    ui.confirm(t("Type the name"), typed=name)
    ui.confirm(t("Unsaid?"))

class Upgrade:
    def confirm(self, text, default):
        return ui.confirm(text, default=default)

    def step(self):
        self.confirm(t("Go on?"), default=True)
        show_and_ask("make forged", t("Install it?"), default=self.flag)
        click.confirm(t("Untouched?"))

class Other:
    def step(self):
        self.confirm(t("Not a wrapper?"), default=True)

def show_and_ask(cmd, question, default=False):
    return ui.confirm(question, default=default)
"""


class TestConfirmDefaults(unittest.TestCase):
    def test_the_survey_reads_each_form(self):
        rows = survey_source(
            SAMPLE, "forged.py", {"show_and_ask", "Upgrade.confirm"}
        )
        self.assertEqual(
            rows,
            {
                ("forged.py", "wipe", "Delete it?"): [False, True],
                ("forged.py", "wipe", "Keep it?"): ["état"],
                ("forged.py", "wipe", "<dynamique>"): [False],
                ("forged.py", "wipe", "Type the name"): ["typed"],
                ("forged.py", "wipe", "Unsaid?"): [None],
                ("forged.py", "Upgrade.step", "Go on?"): [True],
                ("forged.py", "Upgrade.step", "Install it?"): ["self.flag"],
            },
        )

    def test_every_confirm_states_its_default(self):
        rows = survey()
        self.assertEqual(rows, CONFIRM_DEFAULTS)
        for (_path, where, key), defaults in rows.items():
            with self.subTest(where=where, key=key):
                self.assertIsNone(HINT.search(key), "the port writes it")
                if where in STATE_DEFAULTS:
                    self.assertEqual(set(defaults), {"état"})
                    continue
                self.assertTrue(
                    all(d == "typed" or type(d) is bool for d in defaults),
                    f"{defaults}: say True or False",
                )


HINTS = """
def ask(self, name):
    ui.confirm(t("Wipe it? (y/N): "), default=False)
    ui.ask(f"{name} " + t("Keep it, default: yes"))
    input("Go? [o/N] ")
    self.ask_gate(t("Purge? (Y/n, b, t)"), default="y")
    click.prompt(t("Depth (1 = these only, default:"))
    print(t("Shown, not asked (y/N)"))
    hint = "(y/N)"
    input(t("Asked through a name") + hint)
"""

# Le code où la garde des comparaisons lit chaque forme : `a`, réponse lue
# en clair, épluchée, par `:=`, avec un défaut par `or`, ou l'appel
# lui-même, comparée ou par `startswith` ; un paramètre, une valeur qui
# n'est pas lue, un autre mot et une fonction imbriquée non.
COMPARES = """
x = input("?")
x == "n"

def plain():
    a = input("?")
    a == "y"

def peeled(self):
    a = self.ask("?").strip().lower()
    b = a.strip()
    b in ("o", "oui")

def first(self):
    self.ask_gate("?")[0] != "n"

def walrus():
    if (a := click.prompt("?")) not in {"yes", "r"}:
        pass

def listed():
    a = ui.ask("?")
    a.lower() in ["non"]

def auto():
    auto_ask.ask("?", "y") == "yes"

def defaulted():
    a = (input("?") or "n").strip().lower()
    a in ("y", "o")

def prefixed(self):
    a = self.ask("?")
    a.lower().startswith(("y", "o"))

def parameter(answer):
    answer == "y"

def value(sortie):
    unite = sortie.split()[0]
    unite == "o"
    sortie.startswith("n")

def other_word():
    a = input("?")
    a == "a"

def nested():
    a = input("?")
    def inner():
        a == "y"
"""

HELPERS = """
def _oui(answer):
    return answer in ("", "o")

_oui_lambda = lambda answer: answer == "o"

class Menu:
    async def _non(self, answer):
        return self.forms._oui_forged(answer)

    def probe(self, run):
        return run(ask=self._oui_passed, other=_oui_bare)

def ask():
    _oui_kept = _is_none(input("?"))
    return _nom(input("?")) or _nonce()
"""


class TestYesNoGuards(unittest.TestCase):
    def test_the_hint_reads_each_form(self):
        hinted = [
            "Wipe it? (y/N): ",
            "Go? [O/n] : ",
            "Purge? (Y/n, b, t)",
            "Run it now? [y/o/N] ",
            "Install it (Y)",
            "Press y/Y to go on",
            "Keep it, default: N",
            "Type it (default: no): ",
            "Le garder (o/N, défaut : non) : ",
        ]
        for text in hinted:
            with self.subTest(text=text):
                self.assertIsNotNone(HINT.search(text))
        plain = [
            "Depth (1 = these machines only, default:",
            "Port (default: 8069): ",
            "TCP/IP",
            "Enter = all, n = none",
            "[n] limit to host cores",
            "Option (a)",
        ]
        for text in plain:
            with self.subTest(text=text):
                self.assertIsNone(HINT.search(text))

    def test_the_hint_is_read_in_what_a_question_is_given(self):
        self.assertEqual(
            hinted_literals(HINTS),
            {
                "Wipe it? (y/N): ",
                "Keep it, default: yes",
                "Go? [o/N] ",
                "Purge? (Y/n, b, t)",
            },
        )

    def test_no_text_carries_a_yes_no_hint(self):
        found, listed = hinted_texts(), set(HINTED_TEXTS)
        self.assertEqual(
            sorted(found - listed), [], "ask through ui.confirm, it hints"
        )
        self.assertEqual(
            sorted(listed - found), [], "remove these from HINTED_TEXTS"
        )

    def test_the_compare_guard_reads_each_form(self):
        by_scope = {}
        for (where, _line), reads in yes_no_compares(COMPARES).items():
            by_scope.setdefault(where, set()).add(reads)
        self.assertEqual(
            by_scope,
            {
                "<module>": {True},
                "plain": {True},
                "peeled": {True},
                "first": {True},
                "walrus": {True},
                "listed": {True},
                "auto": {True},
                "defaulted": {True},
                "prefixed": {True},
                "parameter": {False},
                "value": {False},
                "inner": {False},
            },
        )

    def test_no_answer_is_compared_to_yes_or_no(self):
        found = set()
        for path in guarded_files():
            rel = path.relative_to(REPO).as_posix()
            compares = yes_no_compares(path.read_text(encoding="utf-8"))
            found |= {
                (rel, where) for (where, _), read in compares.items() if read
            }
        listed = set(YES_NO_COMPARES)
        self.assertEqual(
            sorted(found - listed), [], "ask through ui.confirm instead"
        )
        self.assertEqual(
            sorted(listed - found), [], "remove these from YES_NO_COMPARES"
        )

    def test_values_that_are_not_answers_are_not_seen(self):
        for rel, function in sorted(NOT_ANSWERS):
            with self.subTest(rel=rel, function=function):
                source = (REPO / rel).read_text(encoding="utf-8")
                reads = {
                    read
                    for (where, _), read in yes_no_compares(source).items()
                    if where == function
                }
                self.assertEqual(reads, {False})

    def test_the_helper_guard_reads_each_form(self):
        self.assertEqual(
            yes_no_helpers(HELPERS),
            {
                "_oui",
                "_oui_lambda",
                "_non",
                "_oui_forged",
                "_oui_passed",
                "_oui_bare",
            },
        )

    def test_no_yes_no_helper_is_left(self):
        found = set()
        for path in sorted(TODO.rglob("*.py")):
            if path.is_relative_to(PORT):
                continue
            rel = path.relative_to(REPO).as_posix()
            source = path.read_text(encoding="utf-8")
            found |= {(rel, name) for name in yes_no_helpers(source)}
        listed = set(YES_NO_HELPERS)
        self.assertEqual(
            sorted(found - listed), [], "ask through ui.confirm instead"
        )
        self.assertEqual(
            sorted(listed - found), [], "remove these from YES_NO_HELPERS"
        )


class TestCountdownOnlyInAutoMode(unittest.TestCase):
    def test_seconds_is_the_delay_in_auto_mode_and_none_otherwise(self):
        names = (auto_ask.ENV_ENABLED, auto_ask.ENV_DELAY)
        with patch.dict(os.environ):
            for name in names:
                os.environ.pop(name, None)
            self.assertIsNone(auto_ask.seconds())
            os.environ[auto_ask.ENV_DELAY] = "7"
            self.assertIsNone(auto_ask.seconds())
            os.environ[auto_ask.ENV_ENABLED] = "1"
            self.assertEqual(auto_ask.seconds(), 7)
            os.environ[auto_ask.ENV_DELAY] = "-1"
            self.assertEqual(auto_ask.seconds(), auto_ask.DEFAULT_DELAY)


if __name__ == "__main__":
    unittest.main()
