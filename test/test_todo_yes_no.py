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
même commit.
"""

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from script.todo import auto_ask

REPO = Path(__file__).resolve().parent.parent
TODO = REPO / "script" / "todo"
PORT = TODO / "ui"

# Fonctions qui posent leur question par `ui.confirm`. Un nom nu reconnaît
# tout appel de ce nom ; « Classe.méthode », `self.méthode(` dans une
# méthode de cette classe.
WRAPPERS = {"show_and_ask", "ask_and_install", "TodoUpgrade.confirm"}

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
        self.assertEqual(survey(), CONFIRM_DEFAULTS)


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
