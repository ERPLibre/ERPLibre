#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu QEMU/KVM : d\u00e9cider et lancer un d\u00e9ploiement.\n\nLe chemin complet d'une cr\u00e9ation : les ressources (pr\u00e9r\u00e9glages vCPU/RAM/disque\net saisie libre), le plan et son r\u00e9capitulatif, les v\u00e9rifications de l'h\u00f4te\n(groupe libvirt, KVM), le contexte du formulaire TUI, la collecte en ligne, et\nl'ex\u00e9cution d'une spec \u2014 la M\u00caME structure quelle que soit l'interface, ce qui\npermet aux invites et au formulaire de partager tout le reste.\n\nFronti\u00e8re claire : ici on d\u00e9cide ; dans qemu_install.py on \u00e9crit ce qui sera\nex\u00e9cut\u00e9 dans l'invit\u00e9."""

import contextlib
import fcntl
import getpass
import grp
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import NamedTuple

from script.lib_valid import ValidationError
from script.posture import destinations as posture_destinations
from script.posture import plan as posture_plan
from script.posture import rules as posture_rules
from script.posture import spec as posture_spec
from script.todo import (
    deploy_verify,
)
from script.todo import devstack_report as report
from script.todo import (
    egress_book,
    host_os,
    todo_prefs,
    vm_backend_choice,
    vm_profiles,
)
from script.todo.qemu_privilege import sudo_prefix, virsh_argv, virsh_cmd
from script.todo.todo_i18n import get_lang, t
from script.vm import backend as vm_backend

# Les options ssh de la relecture des règles. Une VM neuve n'a pas de clé
# d'hôte connue, et son adresse se réutilise d'un déploiement au suivant :
# la vérification refuserait une machine neuve à chaque fois. BatchMode
# interdit toute invite — une sonde qui attend une réponse bloque le
# déploiement sur une question que personne ne voit.
EGRESS_SSH_OPTS = (
    "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
    " -o ConnectTimeout=15 -o BatchMode=yes"
)


# Ce que l'aperçu met à la place d'un chemin de fichier. Il CALCULE les
# règles — c'est ainsi qu'une posture inhonorable se refuse avant qu'aucune
# machine n'existe — et il n'ÉCRIT rien : un fichier temporaire créé pour
# afficher son nom serait retiré avant que quiconque le lise. Les chevrons
# disent que ce n'est pas un chemin.
APERCU_REGLES = "<egress.nft>"
APERCU_UNITE = "<egress.service>"


class EgressFiles(NamedTuple):
    """Les deux fichiers rendus, ou deux chaînes vides.

    Deux et non un : les règles disent CE QUI passe, l'unité dit QUAND
    elles sont chargées. Poser les premières sans la seconde ne confine que
    jusqu'au premier redémarrage.
    """

    rules: str
    unit: str


class EgressOutcome(NamedTuple):
    """Ce que la relecture a conclu pour un parc.

    `code` agrège les couches, `unconfined` NOMME les machines : agréger
    seul perdrait ce qui sert, puisque la suite du déploiement se décide
    machine par machine et non pour le parc entier.
    """

    code: int
    unconfined: tuple


class _SansInternetImpossible(Exception):
    """La coupure demandée n'a pas pu être posée : rien n'est déployé.

    Une exception et non un code de retour : le déploiement est enveloppé
    d'un gestionnaire de contexte, et seule une exception l'empêche d'entrer
    dans le bloc.
    """


class QemuDeployMixin:
    """Menu QEMU/KVM : d\u00e9cider et lancer un d\u00e9ploiement.\n\nLe chemin complet d'une cr\u00e9ation : les ressources (pr\u00e9r\u00e9glages vCPU/RAM/disque\net saisie libre), le plan et son r\u00e9capitulatif, les v\u00e9rifications de l'h\u00f4te\n(groupe libvirt, KVM), le contexte du formulaire TUI, la collecte en ligne, et\nl'ex\u00e9cution d'une spec \u2014 la M\u00caME structure quelle que soit l'interface, ce qui\npermet aux invites et au formulaire de partager tout le reste.\n\nFronti\u00e8re claire : ici on d\u00e9cide ; dans qemu_install.py on \u00e9crit ce qui sera\nex\u00e9cut\u00e9 dans l'invit\u00e9."""

    def _qemu_erplibre_remote_cmd(
        self,
        branch,
        final_cmd=None,
        prod=False,
        desktop=False,
        python_provider="",
        app_store="deb",
        tools=(),
        ai_agent="",
    ):
        """Script exécuté DANS la VM. `branch` à None n'installe QUE le bureau
        — le choix graphique ne dépend pas d'ERPLibre, et une VM peut être
        voulue en bureau seul.

        `final_cmd` par défaut : install_os + install_odoo_18. `prod` :
        installe dans /opt/erplibre (au lieu de ~/git/erplibre) + service
        SELinux confiné. `desktop` : ajoute GNOME et son accès distant.
        `python_provider` : « mise » pour un CPython précompilé, sinon le
        comportement par défaut du dépôt (pyenv, qui compile). `tools` : outils
        de développement cochés (PyCharm, Android Studio, extensions GNOME),
        posés APRÈS ERPLibre — PyCharm a besoin du venv du dépôt pour écrire la
        configuration du projet."""
        if not branch:
            # Bureau seul : ni clone ni make, mais on garde le prologue —
            # attente de cloud-init et coupure des mises à jour automatiques,
            # sans quoi le verrou apt ferait échouer l'installation du bureau.
            if not desktop:
                # Rien à installer : le suivi n'a alors qu'à regarder la VM
                # ARRIVER. Un « true » rendait un journal vide et un ✅
                # instantané — et c'est pourquoi le suivi « ne marchait plus »
                # dès qu'on décochait ERPLibre.
                return (
                    "set -e; "
                    + self._qemu_cloud_init_wait()
                    + self._qemu_vm_ready_report()
                )
            # Les outils de la phase « after » vivent DANS le dépôt — la
            # compilation mobile, l'AVD, le script Forgejo. Sans clone, ils
            # n'existent pas ici. Les écarter en silence laissait croire qu'une
            # case cochée avait été honorée : on la NOMME.
            deferred = [
                k
                for k in (tools or ())
                if self._QEMU_VM_TOOLS.get(k, {}).get("phase") == "after"
            ]
            note = (
                f'echo "   ⚠ {t("needs the ERPLibre install, skipped:")}'
                f' {" ".join(deferred)}"; '
                if deferred
                else ""
            )
            # « aidev » n'est pas dans « deferred » : ses installations, elles,
            # ont bien lieu. C'est sa MOITIÉ de pré-configuration qui reste
            # dehors, les hooks et les gabarits vivant dans le dépôt.
            if "aidev" in (tools or ()):
                saute = t("no checkout: git hooks and Claude commands skipped")
                note += f'echo "   ⚠ {saute}"; '
            return (
                "set -e; "
                + self._qemu_cloud_init_wait()
                + self._qemu_no_auto_upgrade(prod, app_store)
                + self._qemu_desktop_remote_cmd(desktop, app_store)
                + self._qemu_tools_remote_cmd(tools, prod, ai_agent=ai_agent)
                + note
            )
        if not final_cmd:
            final_cmd = f"make install_os && make {self.ERPLIBRE_ODOO_TARGET}"
        # Profils AVEC Odoo (install_odoo*) uniquement : après l'install, on
        # enregistre Odoo comme service systemd (enable + start). Pas pour
        # « ERPLibre seul », « mobile » ni « Déploiement ».
        if vm_profiles.ODOO_MARK in final_cmd:
            # Le snippet de service est une SUITE d'instructions séparées par
            # « ; ». Collé tel quel après « && », l'opérateur ne lie que la
            # première : tout le reste s'exécute même quand le make a échoué, et
            # comme « systemctl enable » réussit, la commande distante rend 0 —
            # l'install était rapportée ✅ alors qu'elle avait échoué. « set -e »
            # ne rattrape pas : il n'interrompt pas sur un maillon d'une liste
            # « && ». Les accolades font porter le && sur le bloc entier.
            svc = self._qemu_odoo_service_cmd(prod).strip().rstrip(";")
            final_cmd = f"{final_cmd} && {{ {svc}; }}"
        # VM de DÉVELOPPEMENT uniquement : couper les mises à jour automatiques.
        # unattended-upgrades REDÉMARRE le cluster PostgreSQL sous lui-même —
        # « received fast shutdown request » — et une migration Odoo en cours y
        # perd sa connexion : OpenUpgrade s'arrête et la base intermédiaire
        # reste à moitié migrée. Effet secondaire bienvenu : les timers
        # apt-daily ne tiennent plus le verrou apt pendant l'installation. En
        # PROD on ne touche à rien : les correctifs de sécurité automatiques
        # doivent rester actifs.
        no_auto_upgrade = self._qemu_no_auto_upgrade(prod, app_store)
        tools_cmd = self._qemu_tools_remote_cmd(
            tools, prod, "before", ai_agent
        )
        # La compilation mobile vient APRÈS l'installation : elle a besoin du
        # dépôt, du venv d'outils qui synchronise le manifeste, et de node que
        # « make install_os » installe. Liée par « && » et NON gardée, pour que
        # son échec soit celui de la VM.
        after_cmd = self._qemu_tools_remote_cmd(tools, prod, "after")
        # APRÈS le make : sur un dépôt cloné mais pas installé,
        # PyCharm n'écrit AUCUN .idea — son configurateur d'interpréteur Python
        # échoue faute de venv, et il renonce. Le même appel sur un dépôt
        # installé l'écrit en cinq minutes : erplibre.iml, misc.xml,
        # modules.xml, vcs.xml.
        #
        # On ouvre donc quand l'interpréteur existe, puis on demande la
        # configuration explicitement : l'installation est déjà passée, et
        # pycharm_update() n'avait alors rien à configurer.
        open_step = (
            self._qemu_pycharm_project_cmd(prod)
            # Le venv du dépôt, comme le fait update_env_version.
            # pycharm_update() : le script importe xmltodict, absent du python
            # système : « make pycharm_configure » s'arrête sur
            # « No module named 'xmltodict' ».
            + "./.venv.erplibre/bin/python "
            "./script/ide/pycharm_configuration.py --init || true; "
            if "pycharm" in (tools or ())
            else ""
        )
        # Le groupe de PyCharm rend toujours 0 — un bonus, pas une condition —
        # là où la phase mobile porte le verdict de la VM.
        chain = [final_cmd]
        if open_step:
            chain.append(f"{{ {open_step} }}")
        if after_cmd:
            chain.append(f"{{ {after_cmd} }}")
        install_chain = " && ".join(chain)
        return (
            "set -e; "
            + self._qemu_cloud_init_wait()
            # Coupé AVANT les apt-get ci-dessous : sinon apt-daily peut reprendre
            # le verrou entre l'attente cloud-init et l'installation.
            + no_auto_upgrade
            # Le bureau d'abord : il repose sur les dépôts de la distribution,
            # là où l'installation ERPLibre compile longuement. Un échec ici se
            # voit donc tôt plutôt qu'après une heure.
            + (
                self._qemu_desktop_remote_cmd(desktop, app_store)
                if desktop
                else ""
            )
            +
            # Outils d'amorçage (absents des images cloud minimales) : curl,
            # git, make. Chaque branche RAFRAÎCHIT d'abord les dépôts pour que
            # la VM soit la plus rapide possible (miroirs à jour / les plus
            # rapides), puis installe. Supporte apt (Debian/Ubuntu), dnf/yum
            # (Fedora) et pacman (Arch).
            #
            # L'éditeur de l'hôte voyage avec eux : deploy_qemu.py a déjà écrit
            # « core.editor » dans le ~/.gitconfig de la VM et l'a nommé dans le
            # guide de connexion, mais aucune image cloud ne garantit vim ni
            # nano. Le poser ici plutôt que par cloud-init : les dépôts y sont
            # déjà rafraîchis, et une installation de paquet au premier boot
            # retarderait le démarrage sans laisser de trace dans le suivi.
            f"PKGS='curl git make{self._qemu_editor_suffix()}'; "
            "if command -v apt-get >/dev/null 2>&1; then "
            "fin=$(( $(date +%s) + 300 )); "
            "until sudo apt-get -o DPkg::Lock::Timeout=120 update -qq; do "
            '[ "$(date +%s)" -ge "$fin" ] && break; '
            'echo "apt indisponible, nouvel essai dans 10s..."; sleep 10; '
            "done; "
            "sudo apt-get -o DPkg::Lock::Timeout=600 install -y $PKGS; "
            "elif command -v dnf >/dev/null 2>&1; then "
            # makecache (dnf5 choisit les miroirs les plus rapides) puis
            # install --refresh ; retry avec « clean all » car les images
            # cloud fraîches ratent parfois la vérif GPG/checksum d'un miroir.
            "sudo dnf -q makecache || true; "
            "sudo dnf install -y --refresh $PKGS || "
            "{ sudo dnf clean all; sudo dnf install -y --refresh $PKGS; }; "
            "elif command -v pacman >/dev/null 2>&1; then "
            + self._qemu_pacman_prepare_cmd()
            # bash-completion n'est PAS dans une image cloud Arch, là où les
            # images Debian et Fedora l'embarquent : sans lui, la tabulation
            # ne complète que les noms de fichiers, pas les sous-commandes.
            + "sudo pacman -S --needed --noconfirm $PKGS bash-completion; "
            + self._qemu_yay_install_cmd()
            + "elif command -v zypper >/dev/null 2>&1; then "
            # openSUSE : « --non-interactive » vaut le -y des autres, et
            # « --auto-agree-with-licenses », qui va APRÈS « install »,
            # évite un blocage sur une licence à accepter.
            # Tumbleweed étant rolling, on rafraîchit avant d'installer.
            + self._qemu_zypper_mirror_cmd()
            + "sudo zypper --non-interactive refresh || true; "
            # Tumbleweed est ROLLING et ne supporte pas les mises à jour
            # partielles, exactement comme Arch. L'image cloud est un
            # instantané figé : ses dépôts ont avancé depuis, et un
            # « install » simple bute sur une incohérence — vécu, git 2.54
            # réclamait perl-Git bâti contre un perl-base plus ancien que
            # celui de l'image. zypper proposait alors trois solutions et
            # attendait un choix ; « --non-interactive » prend le défaut,
            # « c » = annuler, et l'installation s'arrêtait là.
            #
            # Sur Leap, « dup » sert à CHANGER de version : l'y appeler irait
            # contre la raison même de la choisir. « up » y suffit, l'image et
            # ses dépôts portant la même version.
            # $ID est déjà posé par le bloc miroir juste au-dessus ; on le
            # relit quand même, pour ne pas dépendre de l'ordre de deux
            # méthodes qui s'ignorent.
            ". /etc/os-release; "
            'case "$ID" in *tumbleweed*) '
            "sudo zypper --non-interactive dup --auto-agree-with-licenses "
            "--allow-vendor-change || true;; "
            "*) sudo zypper --non-interactive up "
            "--auto-agree-with-licenses || true;; esac; "
            "sudo zypper --non-interactive install "
            "--auto-agree-with-licenses $PKGS; "
            "elif command -v yum >/dev/null 2>&1; then "
            "sudo yum makecache -q || true; sudo yum install -y $PKGS; "
            # NixOS n'a aucun des cinq, et c'est là que l'installation
            # s'arrêtait : « Aucun gestionnaire de paquets », avant même le
            # clone. Le système est DÉCLARATIF, mais l'amorçage est le seul
            # moment où on ne peut pas l'être — le module qui déclare git et
            # make vit DANS le dépôt qu'il faut git pour cloner.
            #
            # Le profil de l'utilisateur tranche ce nœud : les outils y sont
            # posés pour la durée du clone, et « make install_os » les
            # redéclare ensuite pour le système entier. Rien n'est écrit dans
            # /etc/nixos avant que le dépôt ne soit là pour le faire.
            #
            # « <nixpkgs> » et non un canal : l'utilisateur n'en a aucun sur
            # cette image, là où NIX_PATH est posé pour tout le monde et
            # pointe les canaux de root.
            #
            # Les noms sont ceux de nixpkgs, où make s'appelle gnumake — $PKGS
            # porte les noms des quatre autres familles et ne vaut pas ici.
            #
            # python3 s'y ajoute, et seulement ici : les images des quatre
            # autres familles l'embarquent — cloud-init est écrit en Python et
            # le pose sur le PATH. Sur NixOS il vit dans le store, hors PATH,
            # et « make install_os » s'arrêtait sur « env: python3: No such
            # file or directory » à sa première recette. Sa version importe
            # peu : l'installation choisit ensuite le Python d'Odoo, que le
            # module déclare et que le profil du système porte, cherché avant
            # celui de l'utilisateur.
             + "elif command -v nix-env >/dev/null 2>&1; then "
            "nix-env -f '<nixpkgs>' -iA git gnumake curl python3"
            f"{self._qemu_editor_suffix()}; "
            # Le PATH de cette commande distante a été figé à l'ouverture du
            # shell SSH, avant que nix-env ne pose quoi que ce soit : sans
            # cette ligne, le contrôle juste en dessous déclare git manquant
            # sur une machine où il vient d'être installé.
            'export PATH="$HOME/.nix-profile/bin:$PATH"; '
            + "else echo 'Aucun gestionnaire de paquets "
            "(apt/dnf/pacman/zypper/yum/nix)'; exit 1; fi; "
            # Vérifie explicitement que tout est là : erreur nette plutôt
            # qu'un « command not found » cryptique plus loin.
            "for t in curl git make; do command -v $t >/dev/null 2>&1 || "
            '{ echo "Outil manquant apres installation: $t '
            '(reseau de la VM ?)"; exit 1; }; done; '
            + self._qemu_mise_remote_cmd(python_provider)
            # Les outils AVANT le clone et le make, et l'ordre compte : c'est
            # PyCharm qui écrit le .idea du dépôt, en l'ouvrant une fois, et
            # c'est l'installation qui, ensuite, y lance
            # pycharm_configuration.py. Posés après, ils arrivaient trop tard
            # pour cette étape-là.
            #
            # Le code de sortie de la commande distante reste celui de
            # l'installation : chaque bloc d'outil se garde lui-même et rend 0,
            # donc aucun ne peut faire passer un make échoué pour un succès.
            + tools_cmd
            # Clone : /opt/erplibre en PROD (racine, puis chown à l'utilisateur
            # pour que make/venv s'exécutent sans sudo), ~/git/erplibre en dev.
            # Un dépôt déjà là est gardé tel quel, et le journal le dit : la
            # branche choisie n'y est alors PAS rechargée.
            + (
                (
                    "sudo mkdir -p /opt; "
                    "if [ ! -d /opt/erplibre/.git ]; then "
                    f"sudo git clone --branch {shlex.quote(branch)} "
                    f"{self.ERPLIBRE_GIT_URL} /opt/erplibre; "
                    "sudo chown -R $(id -un):$(id -gn) /opt/erplibre; "
                    f"else {self._qemu_checkout_garde('/opt/erplibre')}; fi; "
                    + self._qemu_commit_line("/opt/erplibre")
                    + f"cd /opt/erplibre && {install_chain}"
                )
                if prod
                else (
                    "mkdir -p ~/git; "
                    "if [ ! -d ~/git/erplibre/.git ]; then "
                    f"git clone --branch {shlex.quote(branch)} "
                    f"{self.ERPLIBRE_GIT_URL} ~/git/erplibre; "
                    f"else {self._qemu_checkout_garde('~/git/erplibre')}; fi; "
                    + self._qemu_commit_line("~/git/erplibre")
                    + f"cd ~/git/erplibre && {install_chain}"
                )
            )
        )

    @staticmethod
    def _qemu_checkout_garde(depot):
        """Ligne du journal quand le clone est sauté : le dépôt existant est
        gardé, sans mise à jour."""
        note = f"   {t('Existing checkout kept, not updated:')} {depot}"
        return f"echo {shlex.quote(note)}"

    @staticmethod
    def _qemu_commit_line(depot):
        """Ligne du journal qui nomme le commit que la VM exécute vraiment.

        Lu DANS la VM, après le clone : c'est la seule source sûre. Hors
        ligne, le clone vient du miroir du cache, qui peut retarder sur le
        dépôt distant comme sur le checkout de l'hôte. `depot` n'est pas
        cité : « ~ » doit s'y développer. « || true » : sous « set -e », une
        ligne d'information ne doit jamais faire échouer l'installation.
        """
        fmt = shlex.quote("   Commit       : %h %s")
        return (
            f"git -C {depot} log -1 --abbrev=12 --format={fmt} "
            "2>/dev/null || true; "
        )

    def _qemu_install_erplibre_monitored(
        self,
        names,
        branch,
        ip_map=None,
        final_cmd=None,
        prod=False,
        desktop=False,
        python_provider="",
        app_store="deb",
        vm_tools=(),
        pve=None,
        meta=None,
        notes=None,
        ai_agent="",
        guet_hors_ligne=False,
        deploy_started=None,
        hors_ligne=None,
    ):
        """Lance l'install ERPLibre en parallèle DÉTACHÉE sur les VM et ouvre
        le dashboard Textual. Quitter le dashboard n'arrête pas les installs.
        `guet_hors_ligne` : l'amont du cache est coupé ; sa levée est confiée
        au guet entre le lancement et l'ouverture du tableau de bord.
        `deploy_started` : début du déploiement (epoch), recopié dans le
        manifeste ; None n'y écrit rien.
        `hors_ligne` : l'amont du cache était-il coupé pour ce déploiement ?
        Recopié dans le manifeste, où le bilan hors ligne le lit ; None, pour
        un appelant qui ne le sait pas, n'y écrit rien.
        `ip_map` : IP déjà résolues (sinon on résout ici, EN PARALLÈLE).
        `final_cmd` : commande d'install selon le profil choisi.
        `prod` : install /opt/erplibre + service SELinux confiné.
        `vm_tools` : outils cochés pour tout le parc, filtrés machine par
        machine (Android Studio n'existe qu'en x86_64, les extensions GNOME
        n'ont pas de sens sous Cinnamon).
        `notes` : {nom: [lignes]} — ce que l'hôte a décidé pour cette VM
        avant l'installation, recopié en tête de son journal.
        `meta` : {nom: (distro, version, arch)} quand l'appelant SAIT ce que
        sont ces VM. Sans elle, on le demande à virsh — juste ici, donc faux
        pour une VM qui vit sur un Proxmox distant."""
        from script.todo.qemu_install_monitor import (
            launch_installs,
            run_monitor,
        )

        # `desktop` accepte une SAVEUR unique (toutes les VM) ou un dict
        # {nom: saveur} depuis que le type se choisit machine par machine. La
        # commande distante en dépend, donc elle se construit par VM ; celle-ci
        # reste le défaut pour les noms absents du dict.
        desk_map = desktop if isinstance(desktop, dict) else {}
        # Même contrat que `desktop` : une chaîne pour tout le parc, ou
        # une carte {nom: branche} quand elles diffèrent d'une VM à l'autre.
        branch_map = branch if isinstance(branch, dict) else {}
        branch_def = "" if branch_map else branch
        # Idem pour le profil : « ERPLibre + Odoo 18 » peut differer d'une
        # machine a l'autre, on valide alors deux versions d'un coup.
        cmd_map = final_cmd if isinstance(final_cmd, dict) else {}
        cmd_def = None if cmd_map else final_cmd
        remote = self._qemu_erplibre_remote_cmd(
            branch_def,
            cmd_def,
            prod,
            "" if desk_map else desktop,
            python_provider,
            app_store,
            ai_agent=ai_agent,
        )
        try:
            mod = self._qemu_import_module()
        except Exception:
            mod = None
        if ip_map is None:
            ip_map = self._qemu_resolve_ips(names)
        vms = []
        for name in names:
            ip = ip_map.get(name)
            if ip:
                # Ce que l'appelant sait d'abord. Sinon virsh — mais virsh
                # ne connaît QUE les domaines d'ici : sur une VM posée sur un
                # Proxmox distant il ne répond rien, ou pire, il répond pour
                # un domaine local qui porte le même nom. L'architecture
                # décide des outils installés : une VM ARM prise pour x86_64
                # recevait Android Studio, qui n'existe pas pour elle.
                d, v, a = (meta or {}).get(name) or (
                    self._qemu_vm_meta(name, mod)
                    if mod
                    else (None, None, None)
                )
                entry = {
                    "name": name,
                    "ip": ip,
                    "distro": d,
                    "version": v,
                    "arch": a,
                }
                # {nom: {target, sudo, vmid}} quand la VM vit sur un hôte
                # Proxmox : le suivi lui demandera son état, virsh ne le
                # connaît pas.
                if (pve or {}).get(name):
                    entry["pve"] = pve[name]
                # Ce que l'hôte a décidé AVANT de lancer l'installation :
                # écrit en tête du journal, là où on le cherche quand ça a
                # échoué. La console qui l'a dit a défilé depuis.
                if (notes or {}).get(name):
                    entry["notes"] = list(notes[name])
                # Les outils imposent une commande PAR VM même quand tout le
                # reste est commun : ils dépendent de l'architecture de la
                # machine et de sa saveur de bureau, que seule cette boucle
                # connaît.
                if desk_map or branch_map or cmd_map or vm_tools:
                    # Le bureau de CETTE VM : sa saveur propre si la carte en
                    # donne une, sinon celle du parc. Prendre « rien » quand la
                    # carte est vide privait de bureau toute VM dont seule la
                    # branche ou le profil différait — la commande par défaut,
                    # elle, l'a toujours porté.
                    vm_desktop = desk_map.get(
                        name, "" if desk_map else desktop
                    )
                    entry["remote_cmd"] = self._qemu_erplibre_remote_cmd(
                        branch_map.get(name, branch_def),
                        cmd_map.get(name, cmd_def),
                        prod,
                        vm_desktop,
                        python_provider,
                        app_store,
                        self._qemu_tools_for(vm_tools, a, vm_desktop, d),
                        ai_agent,
                    )
                vms.append(entry)
            else:
                print(f"  {name}: {t('no IP, skipped.')}")
        if not vms:
            print(t("No VM to install."))
            return
        # Le mot-clé ne part que s'il porte une valeur : un lanceur de
        # remplacement à trois arguments reste alors appelable.
        debut = {}
        if deploy_started is not None:
            debut["deploy_started"] = deploy_started
        if hors_ligne is not None:
            debut["hors_ligne"] = bool(hors_ligne)
        manifest = launch_installs(
            vms,
            branch_def or next(iter(branch_map.values()), ""),
            remote,
            **debut,
        )
        if guet_hors_ligne:
            self._qemu_confier_la_levee(manifest)
        print(f"\n🖥  {t('Opening the interactive monitor...')}")
        # Affiche tous les chemins de log (pour les consulter/partager même si
        # on quitte le dashboard avant la fin).
        print(f"  {t('Log files:')}")
        with open(manifest, encoding="utf-8") as _fh:
            for entry in json.load(_fh)["vms"]:
                print(f"    {entry['log']}")
        try:
            run_monitor(manifest)
        except ImportError:
            # textual absent : les installs tournent déjà (détachées), on ne
            # plante donc pas — on propose de l'installer pour rouvrir.
            from script.todo import textual_setup

            if textual_setup.ensure():
                run_monitor(manifest)
        print(
            f"\n{t('Monitor closed. Installs keep running in the background.')}"
        )
        logdir = os.path.dirname(manifest)
        print(f"  {t('Logs:')} {logdir}")
        # Commande prête à copier pour relire/partager tous les logs.
        print(f"  {t('Read the logs:')} tail -n +1 {logdir}/*.log")

    def _qemu_install_erplibre_vm(
        self,
        name,
        ssh_key,
        branch,
        ip=None,
        final_cmd=None,
        prod=False,
        desktop=False,
        python_provider="",
        app_store="deb",
        vm_tools=(),
        ai_agent="",
    ):
        """Clone ERPLibre (branche donnée) dans la VM puis exécute la commande
        d'install du profil choisi (streamé). `ip` : IP déjà résolue ;
        `final_cmd` : commande d'install ; `prod` : /opt + SELinux confiné ;
        `vm_tools` : outils de développement cochés."""
        if ip is None:
            ip = self._qemu_vm_ip(name)
        if not ip:
            print(
                f"  {name}: {t('no IP obtained, ERPLibre install skipped.')}"
            )
            return
        # Attend que le SSH soit prêt (évite « Connection refused » quand
        # l'install démarre avant le sshd de la VM).
        print(f"  {name} ({ip}): {t('waiting for SSH...')}")
        if not self._qemu_wait_ssh(ip):
            print(
                f"  {name} ({ip}): "
                f"{t('SSH not reachable, ERPLibre install skipped.')}"
            )
            return
        # Distribution et architecture de CETTE VM : les outils s'y filtrent
        # (Android Studio n'existe qu'en x86_64, la compilation mobile qu'en
        # apt). Sans module lisible on ne filtre plus sur la distribution
        # plutôt que d'écarter à tort.
        try:
            mod = self._qemu_import_module()
            vm_distro, _v, vm_arch = self._qemu_vm_meta(name, mod)
        except Exception:
            vm_distro, vm_arch = "", self._qemu_vm_arch(name)
        remote = self._qemu_erplibre_remote_cmd(
            branch,
            final_cmd,
            prod,
            desktop,
            python_provider,
            app_store,
            self._qemu_tools_for(
                vm_tools, vm_arch or "amd64", desktop, vm_distro or ""
            ),
            ai_agent,
        )
        ssh_opts = (
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=15"
        )
        cmd = f"ssh {ssh_opts} erplibre@{ip} {shlex.quote(remote)}"
        print(f"\n  📦 {name} ({ip}): {t('installing ERPLibre')} ({branch})")
        print(f"  {t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    # Suggestions proposées aux invites de taille. Les lettres démarrent à « a »
    # pour ne JAMAIS entrer en conflit avec une valeur tapée directement : toute
    # saisie commençant par un chiffre est lue comme la valeur elle-même.
    _QEMU_DISK_PRESETS = (
        "20G",
        "30G",
        "40G",
        "50G",
        "60G",
        "80G",
        "100G",
        "120G",
        "160G",
        "200G",
        "400G",
        "600G",
        "800G",
        "1T",
        "1.5T",
        "2T",
    )

    # Jusqu'à 256 Go : les hôtes de virtualisation récents dépassent largement
    # 32 Go, et l'invite est en Mo — l'équivalent en Go est donc affiché.
    _QEMU_RAM_PRESETS = (
        1024,
        2048,
        3072,
        4096,
        5120,
        6144,
        7168,
        8192,
        9216,
        10240,
        11264,
        12288,
        13312,
        14336,
        15360,
        16384,
        32768,
        65536,
        131072,
        262144,
    )

    # KVM autorise plus de vCPU que de cœurs (surengagement) : on prévient
    # plutôt que d'écrêter, contrairement au multiplicateur x1..x4 qui, lui,
    # est un calcul automatique et se borne aux cœurs de l'hôte.
    _QEMU_CPU_PRESETS = (
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        24,
        32,
    )

    @staticmethod
    def _qemu_parse_disk(value):
        """Normalise une taille de disque en « <n>G », ou None si invalide.

        Accepte « 60 », « 60G », « 1T », « 1,5T ». Le suffixe T est converti
        (1 T = 1024 G) : tout le reste de la chaîne — nom de fichier qcow2,
        argument --disk-size — raisonne en gigaoctets.
        """
        txt = value.strip().upper().replace(",", ".")
        factor = 1
        if txt.endswith("T"):
            factor, txt = 1024, txt[:-1]
        elif txt.endswith("G"):
            txt = txt[:-1]
        try:
            gigs = int(float(txt) * factor)
        except ValueError:
            return None
        return f"{gigs}G" if gigs > 0 else None

    @staticmethod
    def _qemu_ram_label(mb):
        """« 65536 (64G) » : l'invite est en Mo, on raisonne en Go."""
        return f"{mb} ({mb // 1024}G)" if mb >= 1024 else str(mb)

    @staticmethod
    def _qemu_ask_value(label, current, presets, fmt=str):
        """Invite avec raccourcis lettrés. Renvoie '' pour « garder ».

        Une lettre choisit une suggestion, un chiffre reste une valeur
        littérale, vide garde la valeur actuelle. Les suggestions sont
        réparties sur plusieurs lignes pour rester lisibles.
        """
        lst_item = [
            f"[{chr(ord('a') + i)}] {fmt(p)}" for i, p in enumerate(presets)
        ]
        for start in range(0, len(lst_item), 5):
            print("    " + "  ".join(lst_item[start : start + 5]))
        answer = input(f"  {label} ({current}): ").strip()
        if not answer:
            return ""
        if len(answer) == 1 and answer.isalpha():
            index = ord(answer.lower()) - ord("a")
            if 0 <= index < len(presets):
                return str(presets[index])
            print(f"    ⚠ {t('Invalid size.')}")
            return ""
        return answer

    def _qemu_ask_disk(self, label, current):
        raw = self._qemu_ask_value(label, current, self._QEMU_DISK_PRESETS)
        if not raw:
            return None
        parsed = self._qemu_parse_disk(raw)
        if not parsed:
            print(f"    ⚠ {t('Invalid size.')}")
        return parsed

    def _qemu_ask_ram(self, label, current):
        raw = self._qemu_ask_value(
            label, current, self._QEMU_RAM_PRESETS, fmt=self._qemu_ram_label
        )
        if not raw:
            return None
        try:
            mb = int(raw)
        except ValueError:
            mb = 0
        if mb <= 0:
            print(f"    ⚠ {t('Invalid size.')}")
            return None
        return mb

    def _qemu_ask_cpu(self, label, current, host_cpu):
        raw = self._qemu_ask_value(label, current, self._QEMU_CPU_PRESETS)
        if not raw:
            return None
        try:
            n = int(raw)
        except ValueError:
            n = 0
        if n <= 0:
            print(f"    ⚠ {t('Invalid vCPU count.')}")
            return None
        if n > host_cpu:
            print(f"    ⚠ {t('More vCPU than host cores')} ({host_cpu}).")
        return n

    @staticmethod
    def _qemu_shared_value(values, fmt=str):
        """Valeur commune à toutes les VM, ou « varié » si elles diffèrent.
        Sert d'« actuel » aux invites globales, où une seule réponse couvre un
        parc qui n'est pas forcément homogène."""
        uniq = set(values)
        return fmt(uniq.pop()) if len(uniq) == 1 else t("varies")

    # vCPU de base (x1) par VM. Le multiplicateur monte de là.
    _QEMU_BASE_VCPUS = 2

    def _qemu_prompt_resources(self, selected, host_cpu, free_ram):
        """Ressources par VM : multiplicateur x1..x4, ou « Personnalisé ».

        x1..x4 multiplie la RAM (base = minimum de la version) et les vCPU
        (base _QEMU_BASE_VCPUS) en bornant ces derniers aux cœurs de l'hôte.
        « Personnalisé » pose les mêmes trois questions que la personnalisation
        par VM, mais une seule fois pour tout le parc.

        `selected` = liste de (d, v, ram_min, disk, arch). Renvoie
        (label, selected) où selected porte désormais les valeurs FINALES et
        un vCPU par VM : (d, v, ram, disk, arch, vcpus)."""
        base_ram = sum(s[2] for s in selected)  # RAM min totale (x1)
        base_vcpus = self._QEMU_BASE_VCPUS
        print(f"\n{t('Resources per VM (x1 = catalog minimum):')}")
        cpu_txt = f"{host_cpu} vCPU"
        ram_txt = (
            f"~{free_ram} Mo {t('free')}"
            if free_ram
            else t("free RAM unknown")
        )
        print(f"  {t('Host:')} {cpu_txt}, {ram_txt}")
        for n in (1, 2, 3, 4):
            vcpus = min(base_vcpus * n, host_cpu)
            total = base_ram * n
            star = " *" if n == 1 else ""
            warn = ""
            if free_ram and total > free_ram:
                warn = f"   ⚠ {t('> host free RAM')}"
            print(
                f"  [{n}] x{n}{star}  {vcpus} vCPU/VM, "
                f"{t('total RAM')} ~{total} Mo{warn}"
            )
        print(f"  [5] {t('Custom - set vCPU, RAM and disk')}")
        sel = input(f"{t('Choice (1-5, default 1):')} ").strip()
        try:
            mult = int(sel)
        except ValueError:
            mult = 1
        if not 1 <= mult <= 5:
            mult = 1

        if mult != 5:
            vcpus = min(base_vcpus * mult, host_cpu)
            return f"x{mult}", [
                (d, v, ram * mult, disk, a, vcpus)
                for (d, v, ram, disk, a) in selected
            ]

        # Personnalisé : une réponse vide garde la valeur du catalogue, qui
        # peut différer d'une VM à l'autre — d'où « varié » comme « actuel ».
        cpu = self._qemu_ask_cpu(
            t("vCPU per VM, blank = keep"), base_vcpus, host_cpu
        )
        ram = self._qemu_ask_ram(
            t("New RAM in MB, blank = keep"),
            self._qemu_shared_value([s[2] for s in selected]),
        )
        disk = self._qemu_ask_disk(
            t("New disk size in G, blank = keep"),
            self._qemu_shared_value([s[3] for s in selected]),
        )
        return t("custom"), [
            (
                d,
                v,
                ram or vram,
                disk or vdisk,
                a,
                cpu or base_vcpus,
            )
            for (d, v, vram, vdisk, a) in selected
        ]

    def _qemu_customize_vms(self, selected, host_cpu):
        """Personnalise chaque VM avant déploiement : NOM, DISQUE, RAM et vCPU.
        `selected` = liste de (d, v, ram, disk, a, vcpus) où les valeurs sont
        déjà FINALES (profil de ressources appliqué).
        Renvoie (names, selected_maj). Défaut : rien ne change."""
        names = [
            self._qemu_infra_name(d, v, a) for d, v, _r, _dk, a, _c in selected
        ]
        sel = [list(s) for s in selected]  # mutable

        def show():
            print(f"\n{t('VMs (default = no change):')}")
            for i, (nm, s) in enumerate(zip(names, sel), 1):
                d, v, ram, disk, a, vcpus = s
                print(
                    f"  [{i}] {nm}   ({d} {v} [{a}])  {vcpus} vCPU  "
                    f"RAM {ram}Mo  {t('disk')} {disk}"
                )

        show()
        raw = input(
            t("Modify which VMs? (numbers, comma-separated; blank = none): ")
        ).strip()
        for tok in re.split(r"[\s,]+", raw):
            if not tok:
                continue
            try:
                i = int(tok) - 1
            except ValueError:
                continue
            if not (0 <= i < len(sel)):
                continue
            # Pour la VM i : nom, disque, RAM, vCPU (vide = garder la valeur).
            new = input(
                f"  {names[i]} — {t('new name (blank = keep):')} "
            ).strip()
            if new:
                names[i] = new
            dk = self._qemu_ask_disk(
                t("New disk size in G, blank = keep"), sel[i][3]
            )
            if dk:
                sel[i][3] = dk
            rm = self._qemu_ask_ram(
                t("New RAM in MB, blank = keep"), sel[i][2]
            )
            if rm:
                sel[i][2] = rm
            cpu = self._qemu_ask_cpu(
                t("New vCPU count, blank = keep"), sel[i][5], host_cpu
            )
            if cpu:
                sel[i][5] = cpu
        if len(set(names)) != len(names):
            print(f"  ⚠ {t('Duplicate names detected; keeping as entered.')}")
        return names, [tuple(s) for s in sel]

    @staticmethod
    def _qemu_orphan_disks(names):
        """qcow2 présents sans VM définie, parmi `names` : [(nom, chemin)].

        Pur : ni sudo ni virsh — l'appelant fournit déjà les noms qui n'ont
        PAS de domaine. C'est ce qui permet au formulaire TUI de recalculer
        les collisions à chaque frappe sans déclencher d'invite de mot de
        passe."""
        orphans = []
        for name in names:
            path = f"/var/lib/libvirt/images/{name}.qcow2"
            if os.path.exists(path):
                orphans.append((name, path))
        return orphans

    def _qemu_offer_orphan_removal(self, names):
        """Propose d'effacer les qcow2 restés seuls. Rend False si on renonce.

        Un disque sans VM définie vient d'une création interrompue : la VM
        n'a jamais démarré, et le fichier ne porte donc rien. Il est tout de
        même PROPOSÉ et non effacé d'office — le même nom peut désigner le
        disque d'une VM retirée à la main, dont on voulait garder les données.

        Sans cet effacement, deploy_qemu refuse d'écraser et la création
        échoue, après avoir fait attendre.
        """
        orphans = self._qemu_orphan_disks(names)
        if not orphans:
            return True
        candidats = []
        for name, path in orphans:
            try:
                candidats.append((os.path.getsize(path), path, name))
            except OSError:
                candidats.append((0, path, name))
        # UN FICHIER RÉFÉRENCÉ N'EST JAMAIS ORPHELIN. La détection déduit le
        # chemin du nom, et elle a raison de le faire — le formulaire la
        # rappelle à chaque frappe, sans invite de mot de passe. Mais un
        # disque peut appartenir à un domaine portant un AUTRE nom : une VM
        # renommée garde le nom de fichier d'avant, si bien que déployer une
        # machine qui reprend l'ancien nom proposait d'effacer le disque
        # vivant de la voisine. Le contrôle vit donc ICI, où l'on efface, et
        # non là où l'on détecte.
        orphelins, proteges = self._qemu_split_orphans(candidats)
        if proteges:
            print(f"\n🛡  {t('Kept - these disks belong to something:')}")
            for _taille, chemin, porteur in proteges:
                print(f"   {chemin} — {porteur}")
        self._cleanup_delete_files(
            t("Orphan disks that would fail the deployment"),
            [(taille, chemin) for taille, chemin, _m in orphelins],
            t("Delete them and continue? (y/N): "),
        )
        restants = self._qemu_orphan_disks(names)
        if not restants:
            return True
        print(f"\n⚠  {t('Kept - the deployment of these VMs will FAIL:')}")
        for name, _path in restants:
            print(f"   {name}")
        return self._is_yes(input(t("Continue anyway? (y/N): ")))

    def _qemu_confirm_collisions(self, existing, pending_names):
        """Signale les noms qui heurtent l'existant, et demande confirmation.

        Deux cas, de gravité différente : une VM déjà définie est simplement
        ignorée — rien n'est écrasé — tandis qu'un qcow2 resté seul (VM
        supprimée sans son disque) fait échouer deploy_qemu, qui refuse
        d'écraser sans --force. Défaut NON : on ne poursuit que sur un « oui »
        explicite."""
        orphans = self._qemu_orphan_disks(pending_names)
        if not existing and not orphans:
            return True
        if existing:
            print(f"\n⚠  {t('Name collisions detected')} :")
            skipped = t("VM already defined - SKIPPED, nothing overwritten")
            for name in existing:
                print(f"   {name:<28.28} {skipped}")
        if orphans:
            return self._qemu_offer_orphan_removal(pending_names)
        return self._is_yes(
            input(f"{t('Continue despite these collisions? (y/N): ')}")
        )

    @staticmethod
    def _qemu_per_vm(carte, commun):
        """Faut-il une valeur PAR VM, ou le choix commun suffit-il ?

        « len(set) > 1 » ne suffisait pas : UNE seule VM qui porte sa propre
        valeur donne un ensemble d'un élément, et tout le parc retombait alors
        sur le choix commun. Déployée seule, une VM Proxmox recevait ainsi
        ERPLibre et Odoo 18 — le défaut qu'on venait de corriger dans le
        formulaire, réintroduit à l'exécution. Même piège pour la branche."""
        return bool(carte) and set(carte.values()) != {commun}

    def _qemu_print_recap(self, spec, existing):
        """État final soumis à approbation : tout ce qui va changer sur
        l'hôte, y compris ce qui ne changera PAS (VM existantes)."""
        install = spec.get("install")
        branch = install["branch"] if install else None
        print(f"\n── {t('Final review before deployment')} ──")
        print(f"  {t('VMs to create:')} {len(spec['vms'])}")
        for vm in spec["vms"]:
            # Le disque annoncé est celui qui sera réellement créé : ERPLibre
            # ajoute ERPLIBRE_EXTRA_DISK_GB à la demande initiale.
            gigs = self._parse_disk_gb(vm["disk"]) + (
                self.ERPLIBRE_EXTRA_DISK_GB
                if self._qemu_installs_erplibre(
                    branch,
                    vm.get("install_cmd") or (install or {}).get("cmd") or "",
                )
                else 0
            )
            # Ce qui S'ECARTE du choix commun se dit sur la ligne de la VM.
            # Sans cela le sommaire annoncait le profil general pour tout le
            # monde, y compris pour une VM figee sur un autre — on lisait
            # « Odoo 15 » avant de deployer une machine en Odoo 18.
            apart = []
            # Seul ce qui DIFFERE vaut d'etre signale : une VM figee sur la
            # meme branche que le global n'a rien de particulier a montrer,
            # et repeter la valeur commune sur chaque ligne la noierait.
            if install and vm.get("branch") and vm["branch"] != branch:
                apart.append(vm["branch"])
            if (
                vm.get("install_label")
                and install
                and vm.get("install_cmd") != install.get("cmd")
            ):
                apart.append(vm["install_label"])
            if vm.get("desktop") and vm["desktop"] != spec.get("desktop"):
                apart.append(
                    (self._QEMU_DESKTOP.get(vm["desktop"]) or {}).get(
                        "label", vm["desktop"]
                    )
                )
            print(
                f"     {vm['name']:<30} {vm['distro']} {vm['version']:<7} "
                f"[{vm['arch']:<5}] {vm['vcpus']} vCPU  RAM {vm['ram']}Mo  "
                f"{t('disk')} {gigs}G"
                + (f"  ⟵ {' · '.join(apart)}" if apart else "")
            )
        if existing:
            print(f"  {t('Existing, left untouched:')} {', '.join(existing)}")
        if install:
            env = (
                t("production (/opt, confined)")
                if install["prod"]
                else t("development (~/git)")
            )
            # « par defaut » : chaque VM peut s'en ecarter, et sa ligne le dit.
            # Ce qui sera REELLEMENT pose, pas le defaut du formulaire. Avec
            # une seule VM figee sur un autre profil, annoncer le defaut
            # revenait a nommer une version que rien n'installe — c'est
            # exactement ce qu'on relit ici pour eviter de se tromper.
            used_br = {vm.get("branch") or branch for vm in spec["vms"]}
            used_lb = {
                vm.get("install_label") or install["label"]
                for vm in spec["vms"]
            }
            varies = t("varies, see each line")
            # L'écart se mesure sur les branches RÉELLES : « varie » n'est
            # qu'un libellé, et le miroir n'a aucune branche de ce nom.
            ecart_de = sorted(used_br) if len(used_br) > 1 else None
            br_txt = used_br.pop() if len(used_br) == 1 else varies
            lb_txt = used_lb.pop() if len(used_lb) == 1 else varies
            print(
                f"  {t('Install:')} {t('branch')} {br_txt}, "
                f"{t('profile')} {lb_txt}, {env}"
            )
            # La VM ne reçoit pas CE checkout : elle CLONE la branche depuis
            # le dépôt distant, ou hors ligne depuis le miroir du cache. Un
            # correctif commité ici et non poussé n'y est donc pas, et le
            # défaut « revient » alors qu'il est corrigé.
            for ligne in self._qemu_branch_gap_lines(
                br_txt if ecart_de is None else ecart_de,
                hors_ligne=bool(spec.get("offline")),
            ):
                print(f"  {ligne}")
        else:
            print(f"  {t('Install:')} {t('no')}")
        flavour = spec.get("desktop")
        if flavour:
            label = (self._QEMU_DESKTOP.get(flavour) or {}).get(
                "label", flavour
            )
            print(
                f"  {t('VM type:')} {t('Graphical (server + desktop):')} {label}"
            )
        tools = spec.get("vm_tools") or ()
        if tools:
            # Les Go sont dits ici parce que c'est le dernier écran avant de
            # créer les disques : un IDE de plus, c'est un disque plus grand,
            # et cette page est celle qu'on relit pour s'en apercevoir.
            named = ", ".join(
                f"{t(self._QEMU_VM_TOOLS[k]['label'])} "
                f"(+{self._QEMU_VM_TOOLS[k]['disk_gb']} Go)"
                for k in tools
                if k in self._QEMU_VM_TOOLS
            )
            print(f"  {t('Development tools:')} {named}")
        prov = spec.get("python_provider")
        if prov:
            print(f"  {t('Python interpreter:')} {prov}")
        print(f"  {t('SSH key:')} {spec.get('ssh_key') or t('none')}")
        cfg = (
            t("one entry per VM") if spec["add_ssh_config"] else t("untouched")
        )
        print(f"  {t('~/.ssh/config:')} {cfg}")
        print(f"  {t('Parallelism:')} {spec['parallelism']} {t('at a time')}")
        # Avant la ligne du mot de passe : le système de base d'une VM se dit
        # AVANT de la créer, pas dans un journal d'installation.
        for rang, ligne in enumerate(self._qemu_image_lines(spec)):
            print(f"  {ligne}" if rang == 0 else f"     {ligne}")
        # DERNIÈRE ligne de la page, parce que l'invite de sudo tombe juste
        # après : elle n'explique rien d'elle-même, et un mot de passe tapé
        # sans savoir ce qu'il autorise est donné à l'aveugle.
        for rang, ligne in enumerate(self._qemu_sudo_lines()):
            print(f"  {ligne}" if rang == 0 else f"     {ligne}")

    def _qemu_image_lines(self, spec):
        """Ce qu'il faut savoir de l'image des VM retenues. Vide s'il n'y a
        rien de particulier à en dire.

        Les FAITS viennent de deploy_qemu, seule autorité sur l'image qu'il
        télécharge ; leur mise en phrase revient au menu, qui parle deux
        langues. Une distribution dont l'image vient d'un tiers se dit ici, et
        une distribution où l'installation ERPLibre échouera encore aussi :
        les deux se découvrent sinon après le déploiement.
        """
        distros = {vm.get("distro") for vm in spec.get("vms") or ()}
        try:
            mod = self._qemu_import_module()
        except Exception:
            return []
        lignes = []
        for distro in sorted(d for d in distros if d):
            note = mod.image_source_note(distro)
            if not note:
                continue
            url, tag = note
            lignes.append(
                t(
                    "%s: image rebuilt by a third party, not published by the"
                    " distribution"
                )
                % distro
            )
            lignes.append(url)
            lignes.append(
                t("release pinned to %s, sha256 fixed in the repository") % tag
            )
        return lignes

    def _qemu_sudo_lines(self):
        """Pourquoi le déploiement va demander le mot de passe. Vide s'il ne
        le demandera pas.

        Les FAITS viennent de deploy_qemu, seule autorité sur ce que le
        déploiement écrit et où ; leur mise en phrase revient au menu, qui
        parle deux langues. Root ne verra aucune invite : ne rien annoncer
        vaut mieux qu'annoncer une question qui ne viendra pas.
        """
        if os.geteuid() == 0:
            return []
        try:
            faits = self._qemu_import_module().sudo_facts()
        except Exception:
            return []
        ecritures = [valeurs for cle, valeurs in faits if cle == "ecriture"]
        lignes = [t("sudo password: asked when the deployment starts")]
        for chemin, proprio, mode in ecritures:
            lignes.append(
                t("write into %s — checked: %s %s, writing refused here")
                % (chemin, proprio, mode)
            )
        lignes.append(
            t(
                "the libvirt group opens the qemu:///system socket, not this"
                " directory"
            )
            if ecritures
            else t("the system steps of the script (service, group)")
        )
        if any(
            cle == "socket" and valeurs[0] == "non" for cle, valeurs in faits
        ):
            lignes.append(
                t(
                    "the libvirt socket does not answer without sudo either:"
                    " group absent from this session, or libvirt not started"
                )
            )
        return lignes

    def _qemu_build_deploy_parts(
        self,
        d,
        v,
        arch,
        name,
        eram,
        evcpus,
        disk,
        ssh_key,
        branch,
        dry_run,
        timezone=None,
        locale=None,
        desktop=False,
        prod=False,
        install_cmd="",
        vm_tools=(),
        gpu3d=False,
        git_name="",
        git_email="",
        cache_ca="",
        cache_bypass=False,
        offline=False,
    ):
        """Construit la commande deploy_qemu.py d'UNE VM (utilisée pour l'aperçu
        dry-run ET le déploiement réel)."""
        parts = [] if dry_run else ["sudo"]
        parts += [
            self._qemu_script_path(),
            "--distro",
            d,
            "--version",
            v,
            "--name",
            name,
            "--memory",
            str(eram),
            "--vcpus",
            str(evcpus),
            "--password",
            "erplibre",
        ]
        if not dry_run:
            # --no-wait-ip : ne bloque pas 90s/VM, l'IP est collectée après.
            parts.append("--no-wait-ip")
        if arch and arch != "amd64":
            parts += ["--arch", arch]
        if ssh_key:
            parts += ["--ssh-key", ssh_key]
        if timezone:
            # Toujours explicite, jamais implicite : la commande affichée en
            # dry-run doit produire la même VM si on la rejoue depuis une autre
            # machine, dont le fuseau serait différent.
            parts += ["--timezone", timezone]
        if locale:
            parts += ["--locale", locale]
        if desktop:
            parts.append("--desktop")
        if gpu3d:
            # « on » et non « auto » : auto s'abstient sur une VM sans écran,
            # or c'est précisément ce que la case permet de demander.
            parts += ["--gpu", "on"]
        if cache_bypass:
            # L'exception l'emporte sur l'autorité : la VM ne rencontrera
            # jamais le cache, lui faire approuver cette signature ne servirait
            # à rien. deploy_qemu.py pose l'exception AVANT de créer la VM.
            parts.append("--cache-bypass")
        elif cache_ca:
            # L'autorité du cache de téléchargement de l'hôte. La VM
            # l'approuve dès son premier démarrage, sans quoi le détournement
            # lui présente un certificat qu'elle rejette.
            parts += ["--cache-ca", cache_ca]
            if offline:
                # L'amont du cache sera coupé : ce qu'aucun cache ne rejoue,
                # l'audit de npm d'abord, est désactivé dans la VM.
                parts.append("--offline")
        # L'identité git de la VM. Sans ces options, deploy_qemu recopie celle
        # de l'HÔTE : le formulaire la montre et permet de la changer, il ne
        # la remplace pas par du vide.
        if git_name:
            parts += ["--git-name", git_name]
        if git_email:
            parts += ["--git-email", git_email]
        # Guide affiché à la connexion SSH de la VM : dans la langue du menu, et
        # avec la section ERPLibre seulement là où ERPLibre sera installé — une
        # VM déployée nue n'annonce pas un dépôt qui n'existe pas.
        parts += ["--lang", get_lang()]
        pose_erplibre = self._qemu_installs_erplibre(branch, install_cmd)
        if pose_erplibre:
            parts += ["--erplibre-dir", self._qemu_guide_dir(prod)]
            target = self._qemu_make_target(install_cmd)
            if target:
                parts += ["--erplibre-make", target]
        extra = 0
        if pose_erplibre:
            # ERPLibre dépasse le minimum : +5 Go de disque.
            extra += self.ERPLIBRE_EXTRA_DISK_GB
        if desktop:
            # GNOME et ses dépendances pèsent autant qu'ERPLibre : sans cette
            # marge, le disque se remplit en pleine installation du bureau.
            extra += self.QEMU_DESKTOP_EXTRA_DISK_GB
        # Les IDE pèsent plus lourd que tout le reste : PyCharm et Android
        # Studio, c'est l'archive téléchargée PUIS son contenu déplié. Compté
        # ici plutôt qu'au petit bonheur, sinon l'installation se termine sur un
        # disque plein après une heure.
        extra += self._qemu_tools_disk_gb(vm_tools, arch, desktop, d)
        # Ce que le guide de connexion annoncera. FILTRÉ par la machine, et
        # non la liste cochée pour le parc : Android Studio n'existe qu'en
        # x86_64 et les extensions GNOME n'ont pas de sens sans bureau —
        # annoncer un outil qui ne sera pas posé enverrait chercher une
        # commande absente. Rien n'est installé par deploy_qemu.py, qui ne
        # s'en sert que pour écrire /etc/motd.
        retenus = self._qemu_tools_for(vm_tools, arch, desktop, d)
        if retenus:
            parts += ["--vm-tools", ",".join(retenus)]
        # TOUJOURS, même sans supplément : sans le drapeau, deploy_qemu.py
        # reprend la taille par défaut du catalogue. Une VM réglée à 60 G mais
        # sans rien à installer repartait donc à 20 G, en silence.
        bigger = self._parse_disk_gb(disk) + extra
        if bigger:
            parts += ["--disk-size", f"{bigger}G"]
        parts.append("--dry-run" if dry_run else "-y")
        return parts

    # La clé sous laquelle le site nomme l'adresse de chaque rôle. Le
    # dépôt sait de QUOI une machine a besoin ; ceci dit OÙ, et c'est une
    # donnée de site.
    #
    # RELAYÉE et non recopiée : `egress_book` la porte, avec la lecture, le
    # refus du fichier suivi et l'écriture. Deux littéraux voisins cessent
    # de correspondre au premier renommage, et celui-là déciderait d'où une
    # liste blanche tire ses adresses.
    EGRESS_BOOK_KEY = egress_book.BOOK_KEY

    @staticmethod
    def _egress_probe_command(ip, user="erplibre"):
        """La ligne ssh qui relit les règles d'une VM. Rend une CHAÎNE.

        Elle n'exécute rien : c'est ce qui permet de l'éprouver depuis une
        station et de la MONTRER avant de la lancer.
        """
        sonde = posture_plan.probe_command()
        return f"ssh {EGRESS_SSH_OPTS} {user}@{ip} {shlex.quote(sonde)}"

    @staticmethod
    def _egress_read(commande):
        """Joue la sonde et rend sa sortie. Le SEUL geste impur d'ici.

        Ne lève pas : une panne de transport est un silence, que la lecture
        du verdict traite déjà — et un déploiement qui vient de réussir ne
        doit pas s'interrompre parce qu'une relecture n'a pas abouti.
        """
        try:
            fini = subprocess.run(
                commande,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return (fini.stdout or "") + (fini.stderr or "")

    @staticmethod
    def _egress_keep(deployed, unconfined):
        """Les machines sur lesquelles la suite a le droit de poser.

        Une liste À PART, et non `deployed` amputée : celle-ci compte ce
        qui a été déployé, et le sommaire final la lit. Les confondre
        ferait disparaître du décompte des machines bien réelles.
        """
        return [nom for nom in deployed if nom not in unconfined]

    def _qemu_station_facts(self, mod=None):
        """Les faits du réseau libvirt, lus une fois. ({} si illisible.)

        La lecture demande virsh et l'URI système ; elle vit donc ICI, où
        le module de déploiement est déjà chargé, et non chez le composeur
        qui ne sonde rien.
        """
        try:
            mod = mod or self._qemu_import_module()
        except Exception:
            return {}
        nom = mod.network_name(mod.DEFAULT_NETWORK)
        if not nom:
            return {}
        sudo = bool(sudo_prefix())
        try:
            actif, autostart = mod.network_state(nom, sudo)
            cidr = mod.network_cidr(nom, sudo)
            pont = mod.network_bridge(nom, sudo)
            collision = mod.network_collision(
                cidr, mod.host_networks(exclure_ponts=[pont])
            )
        except Exception:
            return {}
        return {
            "active": actif,
            "autostart": autostart,
            "cidr": cidr,
            "collision": collision,
        }

    def _qemu_lease_name(self, adresse, mod=None):
        """Le nom sous lequel `adresse` est servie, ou "".

        Sous LC_ALL=C : l'inventaire TRADUIT ses en-têtes, et l'analyseur
        reconnaît l'adresse par sa forme — mais lire la sortie d'un outil
        sous une locale inconnue est un piège que ce dépôt a déjà payé
        ailleurs, et qu'on ne rouvre pas ici.
        """
        if not adresse:
            return ""
        try:
            mod = mod or self._qemu_import_module()
        except Exception:
            # Le catalogue peut ne pas se charger sur une station nue ; ce
            # n'est pas une raison de faire tomber une lecture.
            return ""
        nom_reseau = mod.network_name(mod.DEFAULT_NETWORK)
        if not nom_reseau:
            return ""
        try:
            fini = subprocess.run(
                virsh_argv("net-dhcp-leases", nom_reseau),
                capture_output=True,
                text=True,
                timeout=20,
                env=self._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            # ÉTROIT, et non « Exception » : un filet large a déjà caché un
            # nom mal importé ici même, et la lecture rendait « aucun bail »
            # sans que rien ne le dise.
            return ""
        return vm_backend.lease_hostname(fini.stdout or "", adresse)

    def _qemu_verify_vm(self):
        """Une machine déployée, couche par couche, sans rien y changer.

        LE PENDANT DU VERBE DE STATION. Celui-là dit si l'on PEUT déployer ;
        celui-ci dit ce qu'une machine déjà là tient — son transport, son
        nom, et le confinement que sa posture promettait.

        Le nom est CHOISI dans la liste et jamais retapé : ce verbe ne
        détruit rien, et retaper un nom long pour une lecture serait un
        péage sans contrepartie.
        """
        domaines = self._qemu_list_domains_proved()
        noms = [d.name for d in domaines]
        if not noms:
            print(f"\n{t('No VM found.')}")
            return report.DS_SKIP
        print(f"\n{t('Available VMs:')}")
        for rang, nom in enumerate(noms, 1):
            print(f"  [{rang}] {nom}")
        choisis = self._parse_index_selection(
            input(t("Selection (numbers, or 'all'): ")).strip().lower(),
            noms,
        )
        if not choisis:
            print(t("Nothing selected."))
            return report.DS_SKIP
        ip_map = self._qemu_resolve_ips(choisis)
        pires = []
        for nom in choisis:
            adresse = ip_map.get(nom) or ""
            couches = list(
                deploy_verify.dns_layers(
                    nom,
                    lease=self._qemu_lease_name(adresse),
                    address=adresse,
                )
            )
            if adresse:
                lu = posture_plan.parse_probe(
                    self._egress_read(self._egress_probe_command(adresse))
                )
                couches.extend(deploy_verify.egress_layers(lu))
            couches.extend(deploy_verify.tls_layers())
            print()
            print(report.render_layers(couches, subject=nom))
            pires.append(report.aggregate_layers(couches))
        return report.worst_code(pires)

    def _qemu_verify_station(self):
        """Ce que la station sait faire, couche par couche, sans rien créer.

        AVANT de déployer, et non après : découvrir un groupe manquant ou un
        réseau en collision au bout de vingt minutes d'installation coûte
        bien plus cher qu'une lecture d'une seconde.

        Rend le pire code des couches, pour qu'un appelant puisse en
        dépendre. Ce qui n'a pas pu être lu n'est pas rendu VERT : le
        composeur le dit, et un bloc muet se lirait comme « tout va bien ».
        """
        print(f"\n🩺 {t('Verify the deploying station')}")
        couches = list(deploy_verify.host_layers())
        faits = self._qemu_station_facts()
        if faits:
            couches.extend(deploy_verify.network_layers(**faits))
        else:
            couches.append(
                report.layer_verdict(
                    "network",
                    report.DS_SKIP,
                    t("The libvirt network could not be read."),
                    t("Check virsh and the system URI."),
                )
            )
        print(report.render_layers(couches, subject=t("Station")))
        return report.aggregate_layers(couches)

    def _qemu_probe_egress(self, deployed, ip_map, lire=None):
        """Relit les règles de chaque VM déployée et écrit le verdict.

        Le chargement échoue DANS l'invité sans que l'hôte l'apprenne :
        l'attente de cloud-init lit son état pour cesser d'attendre, jamais
        pour le dire. Sans cette relecture, une machine dont l'image n'a pas
        l'analyseur se déploie en annonçant un confinement que rien ne tient.

        `lire` rend la lecture remplaçable, donc la décision vérifiable sans
        machine.

        SEULE UNE TABLE LUE COMPTE POUR UN CONFINEMENT. Une VM dont
        l'adresse n'a pas été résolue, ou qui n'a rien répondu, est nommée
        parmi les non confinées : ce qui n'a pas été lu vaut « non », et
        l'inverse ferait passer un silence pour une garantie.
        """
        lire = lire or self._egress_read
        verdicts = []
        sans_regles = []
        for nom in deployed:
            ip = ip_map.get(nom)
            lu = posture_plan.UNREAD
            if ip:
                lu = posture_plan.parse_probe(
                    lire(self._egress_probe_command(ip))
                )
            if lu != posture_plan.LOADED:
                sans_regles.append(nom)
            couches = deploy_verify.egress_layers(lu)
            print()
            print(report.render_layers(couches, subject=nom))
            verdicts.extend(couches)
        return EgressOutcome(
            report.aggregate_layers(verdicts), tuple(sans_regles)
        )

    def _qemu_egress_rules(self, spec):
        """Le texte des règles que cette spec demande, ou une chaîne vide.

        Vide n'est pas un échec : la sortie libre ne demande rien, et c'est
        la posture par défaut de la plupart des déploiements.

        Ce qui est refusé ici, c'est l'inverse — une posture qui EN attend
        et dont le site n'a pas nommé les adresses. La laisser passer
        déploierait une machine qui ne joint pas sa forge, et le manque se
        découvrirait sur la machine plutôt que devant l'écran.

        LA QUESTION POSÉE EST « CETTE POSTURE VEUT-ELLE DES RÈGLES ». Elle
        était « a-t-elle une liste bornée à résoudre », ce qui est une
        AUTRE question : une sortie coupée n'a aucune adresse à nommer et
        veut pourtant des règles. « local-only » se déployait donc avec la
        sortie entière — la posture qui promet le plus étant la seule à ne
        rien poser.
        """
        posture = posture_spec.posture_of(spec)
        if posture is None:
            raise vm_backend.VmBackendError(
                f"Déploiement : posture « {posture_spec.posture_name(spec)} »"
                " inconnue. Déployer en sortie libre une spec qui demandait"
                " du confinement serait le sens inverse de la demande."
            )
        if not posture_rules.wants_rules(posture):
            return ""
        # PAR LE MODULE DU CARNET, et non par une lecture directe : c'est
        # lui qui refuse le fichier SUIVI par git. Le carnet ne porte que
        # des adresses, et une adresse y devient publique — lire d'abord
        # donnerait un déploiement réussi derrière lequel la fuite ne se
        # verrait jamais.
        carnet = egress_book.read(self.config_file)
        try:
            cibles = posture_destinations.destinations_for(posture, carnet)
        except ValidationError as manque:
            # LE TYPE QUE LES APPELANTS GUETTENT. Le refus est légitime —
            # déployer sans ces adresses ferait découvrir le manque SUR la
            # machine — mais il traversait le programme entier jusqu'au
            # Makefile : le déploiement libvirt ne guette que les refus de
            # backend, et le menu Lima ne guettait rien.
            #
            # Et il dit OÙ réparer : nommer le rôle manquant sans dire où
            # le poser laisse chercher dans vingt-trois écrans.
            chemin = self.menu_path(
                "run",
                "prompt_execute",
                "prompt_execute_deploy",
                "prompt_execute_egress_book",
            )
            raise vm_backend.VmBackendError(
                f"{manque} {t('Set it in:')} {chemin}"
            ) from manque
        return posture_rules.render_egress(posture, cibles)

    @contextlib.contextmanager
    def _qemu_egress_file(self, spec):
        """Le chemin d'un fichier de règles, le temps du bloc.

        Chaîne vide quand la posture n'en attend pas : un déploiement qui ne
        confine rien ne doit pas payer un fichier.

        Le contenu nomme les adresses internes du site : il ne traîne pas
        après coup.
        """
        texte = self._qemu_egress_rules(spec)
        if not texte:
            yield EgressFiles("", "")
            return
        with contextlib.ExitStack() as pile:
            regles = pile.enter_context(self._fichier_ephemere(texte, ".nft"))
            unite = pile.enter_context(
                self._fichier_ephemere(posture_plan.unit_text(), ".service")
            )
            yield EgressFiles(regles, unite)

    @staticmethod
    @contextlib.contextmanager
    def _fichier_ephemere(texte, suffixe):
        """Un fichier écrit pour la durée du bloc, puis retiré.

        Écrit par mkstemp — un nom composé serait un chemin PRÉVISIBLE — et
        retiré dans tous les cas, y compris quand le déploiement s'arrête
        au milieu.
        """
        descripteur, chemin = tempfile.mkstemp(
            prefix="erplibre-egress-", suffix=suffixe
        )
        try:
            with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
                fichier.write(texte)
            yield chemin
        finally:
            with contextlib.suppress(OSError):
                os.unlink(chemin)

    def _qemu_deploy_parts_for(self, vm, spec, dry_run=False, egress=""):
        """Commande deploy_qemu.py d'une VM de la spec.

        POINT DE PASSAGE UNIQUE des deux interfaces : le formulaire TUI et les
        invites en ligne produisent la même spec, donc forcément la même
        commande. C'est ce qui rend leur divergence vérifiable par un test.

        C'est donc AUSSI l'endroit où un backend que ce chemin ne sait pas
        piloter doit s'arrêter. Ce chemin est libvirt de bout en bout — il
        vérifie /dev/kvm puis énumère les domaines par virsh — et laisser
        passer une autre description produirait un déploiement libvirt sous
        un faux nom, ou une exception au milieu du travail. Le refus nomme
        le backend.

        IL EST ATTEIGNABLE. La description porte le backend RÉSOLU depuis la
        préférence, et la préférence se règle à l'écran : « pve » ou « lima »
        y arrivent depuis n'importe quel hôte, et « automatique » suffit sur
        un poste Apple, où la résolution rend « lima ». L'écran de la
        préférence dit donc ce refus, faute de quoi il se lit comme une
        panne."""
        # LA RÈGLE D'OR, au seul endroit que les deux interfaces
        # traversent. Le refus arrive AVANT que la machine existe, ce qui
        # est le seul moment où il ne coûte rien. Une posture inconnue est
        # refusée elle aussi : replier sur la plus libre déploierait en
        # sortie libre un spec qui demandait du confinement.
        verdict = posture_spec.check(spec)
        if verdict != posture_spec.OK:
            raise vm_backend.VmBackendError(
                f"Déploiement refusé : {verdict}."
                f" Posture « {posture_spec.posture_name(spec)} »,"
                f" données réelles : {posture_spec.real_data(spec)}."
            )
        # AUCUN REFUS SUR LE COUPLE (profil, installation) ICI, et c'est
        # une décision. Un spec porte une POSTURE, pas le libellé sous
        # lequel on l'a choisie — et le registre sépare les deux exprès :
        # « les séparer est ce qui permet de servir autre chose sur la même
        # posture ». Déduire « on voulait une interface web » de « on a
        # choisi local-only » inverse cette séparation, et refuserait la
        # seule posture qui porte une donnée réelle. La question se pose là
        # où le LIBELLÉ existe : dans le formulaire.
        demande = spec.get("backend") or vm_backend.LIBVIRT
        if demande != vm_backend.LIBVIRT:
            raise vm_backend.VerbNotImplemented(
                f"Déploiement : ce chemin ne pilote que"
                f" « {vm_backend.LIBVIRT} », pas « {demande} »."
            )
        install = spec.get("install")
        parts = self._qemu_build_deploy_parts(
            vm["distro"],
            vm["version"],
            vm["arch"],
            vm["name"],
            vm["ram"],
            vm["vcpus"],
            vm["disk"],
            spec.get("ssh_key"),
            install["branch"] if install else None,
            dry_run=dry_run,
            timezone=spec.get("timezone"),
            locale=spec.get("locale"),
            # Le type suit la VM. Repli sur la valeur de spec pour la CLI,
            # qui ne pose la question qu'une fois pour tout le parc.
            #
            # La SAVEUR, et non un booléen : les extensions GNOME n'ont pas de
            # sens sous Cinnamon, et c'est ici que se calcule la place disque
            # des outils. « --desktop » ne regarde que la vérité de la valeur,
            # une chaîne non vide lui va aussi bien.
            desktop=vm.get("desktop", spec.get("desktop")) or "",
            # Les deux servent au guide de connexion : où ERPLibre sera posé, et
            # quelle cible make le remettra à jour.
            prod=bool(install and install.get("prod")),
            # La commande DE CETTE VM, pas seulement celle du formulaire :
            # elle décide de la marge disque et de ce que le guide annonce.
            # Une VM Proxmox recevait sinon les cinq gigaoctets d'ERPLibre et
            # une cible make qu'elle n'aurait jamais.
            install_cmd=(
                vm.get("install_cmd") or (install or {}).get("cmd") or ""
            ),
            vm_tools=spec.get("vm_tools") or (),
            gpu3d=bool(spec.get("gpu3d")),
            git_name=spec.get("git_name") or "",
            git_email=spec.get("git_email") or "",
            # L'autorité est posée dès que le service TOURNE, sans égard à
            # la case : l'interception est transparente et vaut pour tout le
            # pont, si bien qu'une VM privée de l'autorité est quand même
            # détournée et échoue sur « self-signed certificate in
            # certificate chain » à chaque téléchargement HTTPS. Le seul
            # contournement vrai est d'arrêter le service, qui emporte ses
            # règles avec lui.
            #
            # Le chemin est relu à chaque commande : désinstaller le cache
            # entre deux déploiements ne doit pas laisser une VM approuver une
            # autorité disparue.
            cache_ca=(
                self._qemu_cache_ca_path() if self._qemu_cache_active() else ""
            ),
            cache_bypass=bool(spec.get("cache_bypass")),
            offline=bool(spec.get("offline")),
        )
        # Le fichier de règles est POSÉ par le déploiement, pas rendu par
        # lui : il reçoit un chemin déjà écrit, et n'a rien à savoir des
        # postures. Absent, la commande est celle d'avant, mot pour mot.
        if egress and egress.rules:
            parts += ["--egress-file", egress.rules]
            parts += ["--egress-unit", egress.unit]
        return parts

    # Où l'installateur du cache pose son autorité. Un test compare cette
    # valeur au défaut du script d'installation : les deux séparées, la case
    # s'offrirait sans que la VM reçoive rien.
    QEMU_CACHE_CA = "/var/lib/erplibre_go_qemu_cache/ca.crt"
    QEMU_CACHE_SERVICE = "erplibre-go-qemu-cache.service"

    @classmethod
    def _qemu_cache_ca_path(cls):
        """Chemin de l'autorité du cache, ou '' si le cache n'est pas posé.

        L'existence du FICHIER suffit à décider : une autorité approuvée alors
        que le cache est arrêté ne coûte rien à la VM, qui télécharge en
        direct. C'est l'inverse qui casse — un détournement actif sans
        autorité dans l'invité.
        """
        return cls.QEMU_CACHE_CA if os.path.isfile(cls.QEMU_CACHE_CA) else ""

    @classmethod
    def _qemu_cache_active(cls):
        """Le service du cache tourne-t-il ? Sert au DÉFAUT de la case.

        Jamais à l'offrir : c'est le fichier d'autorité qui décide de son
        existence, et l'état d'un service change entre l'affichage du
        formulaire et le déploiement.
        """
        if not cls._qemu_cache_ca_path():
            return False
        try:
            return (
                subprocess.run(
                    [
                        "systemctl",
                        "is-active",
                        "--quiet",
                        cls.QEMU_CACHE_SERVICE,
                    ],
                    check=False,
                    timeout=5,
                ).returncode
                == 0
            )
        except (OSError, subprocess.SubprocessError):
            # Hôte sans systemd, ou systemctl injoignable : on ne prétend pas
            # savoir, et la case s'offre décochée.
            return False

    def _qemu_arches_for(self, distro, arch):
        """Architectures à déployer pour cette distro selon le choix global.
        « all » = uniquement celles que la distro publie réellement."""
        if arch != "all":
            return [arch]
        # Même source que _qemu_arch_distros : « all » ne doit jamais offrir
        # une combinaison que deploy_qemu.py refusera.
        out = ["amd64"]
        for a in ("arm64", "s390x"):
            supported = self._qemu_arch_distros(a)
            if supported and distro in supported:
                out.append(a)
        return out

    def _qemu_catalog_entries(self, mod, distros, arch):
        """Catalogue APLATI : une entrée par (distro, version, architecture).

        Fonction pure, sans I/O : c'est la source unique de ce qui est
        déployable, aussi bien pour la liste granulaire de la CLI que pour la
        liste à cocher du formulaire TUI."""
        flat = []
        # Une distro peut ne publier qu'une partie de ses versions sur une
        # architecture (Fedora ne construit que la courante en s390x). La
        # table vit dans deploy_qemu.py, qui refuse aussi ces combinaisons :
        # une seule source, donc aucun écran n'offre un choix rejeté ensuite.
        only = getattr(mod, "arch_versions", None)
        for d in distros:
            versions_map, default_v = mod.DISTROS[d]
            for v, (_c, _o, ram, disk) in versions_map.items():
                for a in self._qemu_arches_for(d, arch):
                    if only and v not in only(d, a, versions_map):
                        continue
                    flat.append(
                        {
                            "distro": d,
                            "version": v,
                            "arch": a,
                            "ram": ram,
                            "disk": disk,
                            "default": v == default_v,
                        }
                    )
        return flat

    @staticmethod
    def _qemu_make_vm(distro, version, arch, ram, disk, vcpus, name):
        """Une VM de la spec. Un seul endroit décrit sa forme."""
        return {
            "name": name,
            "distro": distro,
            "version": version,
            "arch": arch,
            "ram": ram,
            "disk": disk,
            "vcpus": vcpus,
        }

    def _qemu_split_existing(self, vms, domains):
        """Sépare les VM à créer de celles dont le domaine existe déjà.
        `domains` est la liste des noms libvirt, obtenue UNE fois (un seul
        sudo) et non par VM. Renvoie (à_créer, noms_existants)."""
        known = set(domains)
        pending = [vm for vm in vms if vm["name"] not in known]
        existing = [vm["name"] for vm in vms if vm["name"] in known]
        return pending, existing

    def _qemu_check_libvirt_group(self):
        """Prévient si virsh n'est pas joignable sans sudo, et propose de régler.

        Le suivi d'installation tourne DÉTACHÉ, sans tty : il ne peut pas
        répondre à une demande de mot de passe. « sudo -n » y échoue sur tout
        hôte exigeant une authentification interactive, et la VM devient alors
        introuvable dès que son bail DHCP change. Le groupe libvirt est la
        seule voie qui n'exige ni root ni tty.

        Vérifié AVANT de créer quoi que ce soit : découvrir le problème après
        vingt minutes d'installation coûte bien plus cher qu'une question ici.
        """
        probe = subprocess.run(
            ["virsh", "--connect", "qemu:///system", "list", "--name"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return  # joignable sans sudo : rien à signaler

        user = getpass.getuser()
        # Être dans /etc/group ne suffit pas : les groupes d'un processus sont
        # figés à l'ouverture de session. Distinguer les deux cas évite de
        # proposer un usermod déjà fait, et dit la vraie action attendue.
        try:
            declared = user in grp.getgrnam("libvirt").gr_mem
        except KeyError:
            declared = False
        try:
            active = grp.getgrnam("libvirt").gr_gid in os.getgroups()
        except KeyError:
            active = False

        print(f"\n⚠  {t('virsh cannot reach qemu:///system without sudo.')}")
        print(f"   {t('The install monitor runs detached and cannot type a')}")
        print(
            f"   {t('password: it would lose the VM when its lease moves.')}"
        )

        if declared and not active:
            print(
                f"\n   {t('You are in the libvirt group, but this session')}"
            )
            print(f"   {t('predates it. Log out and back in, or run:')}")
            print(f"     newgrp libvirt")
            return
        if active:
            # Groupe présent mais virsh échoue quand même : libvirtd arrêté,
            # socket absente… La cause n'est pas le groupe, ne pas la maquiller.
            print(f"\n   {t('Group is active, so the cause is elsewhere:')}")
            print(f"     {(probe.stderr or '').strip()[:200]}")
            return

        cmd = f"sudo usermod -aG libvirt {shlex.quote(user)}"
        print(f"\n   {t('Add your user to the libvirt group?')}")
        print(f"     {cmd}")
        if not self._is_yes_default_yes(input(t("Run it now? (Y/n): "))):
            return
        if os.system(cmd) != 0:
            print(f"   ⚠ {t('Command failed.')}")
            return
        print(f"\n✅ {t('Added. Log out and back in for it to take effect,')}")
        print(f"   {t('or start a new shell with: newgrp libvirt')}")

    def _qemu_check_kvm(self):
        """Prévient quand les VM seront ÉMULÉES faute de KVM.

        « Même architecture que l'hôte » ne veut pas dire accélérée : dans une
        VM sans virtualisation imbriquée, libvirt bascule en TCG sans le dire.
        Une VM s390x sur un hôte s390x lui-même invité KVM sort en
        « <domain type='qemu'> » et démarre en 7 min 30. Le savoir avant
        d'attendre vaut mieux que de chercher la cause après."""
        try:
            mod = self._qemu_import_module()
            if mod.kvm_available():
                return
        except Exception:
            return
        try:
            module = mod.nested_module()
        except Exception:
            module = "kvm"
        print(f"\n⚠  {t('KVM is unavailable: the VMs will be EMULATED.')}")
        print(f"   {t('A boot then takes 10-15 min, not under a minute.')}")
        print(
            f"   {t('Cause: /dev/kvm is missing. This host is itself a VM')}"
        )
        print(
            f"   {t('whose hypervisor does not expose nested virtualization.')}"
        )
        print(f"\n   {t('To fix it ON THE PARENT HYPERVISOR, not here:')}")
        print(
            f'     echo "options {module} nested=1"'
            f" | sudo tee /etc/modprobe.d/kvm-nested.conf"
        )
        print(f"     sudo modprobe -r {module} && sudo modprobe {module}")
        print(
            f"   {t('then set this VM to the host-passthrough CPU mode and')}"
        )
        print(
            f"   {t('stop it and start it again - a reboot is not enough.')}"
        )
        print(
            f"\n   {t('Without access to that hypervisor, nothing to do here.')}"
        )

    def _qemu_ask_ui(self):
        """Interface du déploiement : formulaire TUI ou invites en ligne.
        La préférence peut trancher d'avance (menu Configuration) ; « ask »
        pose la question."""
        pref = todo_prefs.get("qemu_deploy_ui")
        if pref in ("tui", "cli"):
            return pref
        print(f"\n{t('Interface:')}")
        print(f"  [1] {t('TUI form')} *")
        print(f"  [2] {t('Classic questions (line by line)')}")
        print(f"  {t('(change the default in TODO > Configuration)')}")
        sel = input(t("Choice (1-2, default 1): ")).strip()
        return "cli" if sel == "2" else "tui"

    def _qemu_form_context(self, mod):
        """Données préchargées pour le formulaire TUI.

        TOUT ce qui exige sudo (liste des domaines) ou le réseau (branches)
        est fait ICI, pendant que le terminal est encore à nous : une invite
        de mot de passe pendant que Textual affiche casserait l'écran.

        Le backend employé se résout ICI pour la même raison : la sonde du
        PATH est une lecture de la machine, et l'écran ne doit pas en faire
        au milieu de son affichage."""
        native = self._native_arch()
        arches = ["amd64", "arm64", "s390x"]
        if native not in arches:
            arches.insert(0, native)
        arches.append("all")

        catalog = {}
        for a in arches:
            distros = list(mod.DISTROS)
            if a != "all":
                allowed = self._qemu_arch_distros(a)
                if allowed is not None:
                    distros = [d for d in distros if d in allowed]
            entries = self._qemu_catalog_entries(mod, distros, a)
            for e in entries:
                # Le nom est calculé ici : le formulaire reste pure donnée.
                e["name"] = self._qemu_infra_name(
                    e["distro"], e["version"], e["arch"]
                )
            catalog[a] = entries

        print(f"\n{t('Loading (VM list, branches)...')}")
        disque_libre, disque_total = self._host_disk_gb()
        return {
            "catalog": catalog,
            "arches": arches,
            "native": native,
            "domains": self._qemu_list_domains(),
            "branches": self._qemu_branch_list() or ["master"],
            # La branche du dépôt : c'est elle qu'on déploie le plus souvent.
            "branch_current": self._qemu_repo_branch(),
            "install_profiles": self._qemu_install_profiles(),
            # Les systèmes qui IMPOSENT ce qu'on installe dessus. Sans cette
            # table, le formulaire posait ERPLibre + Odoo 18 sur une VM
            # Proxmox — l'invite en ligne, elle, savait déjà l'éviter.
            "distro_profiles": {
                d: self._qemu_distro_profile(d)
                for d in self._QEMU_DISTRO_PROFILE
                if self._qemu_distro_profile(d)
            },
            "ssh_key": self._qemu_default_ssh_key(),
            # Le cache de téléchargement de CET hôte. Lu ici, comme le reste
            # des mesures : l'écran ne doit rien interroger pendant qu'il
            # affiche. Absent, le formulaire n'offre pas la case.
            "cache_ca": self._qemu_cache_ca_path(),
            "cache_active": self._qemu_cache_active(),
            # La case « hors cache » ne s'offre que là où elle a un effet.
            # Sans service actif rien n'intercepte, et une case sans effet
            # est ce que ce menu a déjà eu, à tort.
            "cache_offert": self._qemu_cache_active(),
            # Le backend employé, résolu ici : l'écran l'AFFICHE et ne le
            # choisit pas. Un choix qu'on ne peut pas honorer — ce chemin ne
            # pilote que le local — vaut moins qu'un choix absent.
            "backend": vm_backend_choice.effective(
                todo_prefs.get("vm_backend"),
                host_os.host_os(),
                bool(shutil.which("limactl")),
            ),
            # LES TROIS CLÉS DE POSTURE, par le module qui les possède.
            # Recopiées d'un écran à l'autre, elles avaient déjà divergé :
            # la ligne composée à la main perdait la phrase du profil qui
            # promet une interface servie. Le défaut ici est PAR DÉFAUT :
            # ce chemin écrit les règles avant le premier démarrage.
            **vm_profiles.form_context(),
            "host_cpu": os.cpu_count() or 2,
            "free_ram": self._host_free_ram_mb(),
            # La place du système de fichiers qui portera les qcow2. Mesurée
            # ICI, comme le reste : une lecture disque pendant que Textual
            # affiche n'a pas sa place.
            "free_disk": disque_libre,
            "total_disk": disque_total,
            "base_vcpus": self._QEMU_BASE_VCPUS,
            "cpu_presets": self._QEMU_CPU_PRESETS,
            "ram_presets": self._QEMU_RAM_PRESETS,
            "disk_presets": self._QEMU_DISK_PRESETS,
            "extra_disk_gb": self.ERPLIBRE_EXTRA_DISK_GB,
            **self._qemu_guest_context(),
            # L'aperçu passe par le MÊME constructeur que le déploiement.
            "build_command": self._qemu_preview_command,
        }

    def _qemu_ssh_forwards(self, spec, vm_name):
        """Les redirections du bloc ssh d'UNE machine. Vide est la règle.

        LA MOITIÉ INSTALLATION du profil servi : la sortie coupée est tenue
        par les règles, et ce qui manquait est de rendre l'interface
        joignable depuis l'hôte, à une adresse stable qui ne dépend pas de
        l'IP du jour.

        La commande examinée est celle que CETTE machine subira — celle
        qu'elle a figée, sinon la commune. Une rangée qui installe autre
        chose ne doit pas hériter d'une promesse qu'elle ne tient pas.
        """
        commune = (spec.get("install") or {}).get("cmd", "") or ""
        propre = ""
        for vm in spec.get("vms") or []:
            if vm.get("name") == vm_name:
                propre = vm.get("install_cmd") or ""
                break
        return vm_profiles.web_forward(
            posture_spec.posture_name(spec), propre or commune
        )

    def _qemu_preview_command(self, vm, spec, dry):
        """La commande qu'un aperçu affiche, en UNE ligne.

        Le MÊME constructeur que le déploiement — c'est ce qui rend leur
        divergence vérifiable. Mais il porte la règle d'or, qui lève : un
        aperçu ne crée rien et n'a aucune raison de finir en pile, donc le
        refus s'affiche ici à la place de la commande, et l'écran reste.
        """
        try:
            parts = self._qemu_deploy_parts_for(vm, spec, dry_run=dry)
        except vm_backend.VmBackendError as refus:
            return f"✗ {t('Deployment refused:')} {refus}"
        return " ".join(shlex.quote(p) for p in parts)

    def _qemu_deploy(self, dry_run=False):
        """Déploiement d'un parc de VM, en trois temps : collecte des choix
        (formulaire TUI ou invites en ligne), aperçu ou exécution. Les deux
        interfaces produisent la MÊME spec."""
        print(f"🚀 {t('Deploy ERPLibre VM(s)!')}")
        try:
            mod = self._qemu_import_module()
        except Exception as exc:
            print(f"{t('Cannot load QEMU catalog: ')}{exc}")
            return
        # Rappel de la dernière installation enregistrée (si historique).
        last = self._qemu_last_run_line()
        if last:
            print(last)
        # Un aperçu ne crée rien : il n'a pas à interroger sur un run en cours.
        if not dry_run and self._qemu_active_install():
            return

        self._qemu_check_libvirt_group()
        self._qemu_check_kvm()

        try:
            self._qemu_deploy_decided(mod, dry_run)
        except vm_backend.VmBackendError as refus:
            # LE REFUS SE LIT, il ne se déroule pas. La garde du point de
            # passage unique lève, et rien ne la rattrapait : un couple
            # incohérent composé au formulaire sortait du menu en pile,
            # là où la voie Proxmox imprime son verdict et revient.
            print(f"\n  ✗ {t('Deployment refused:')} {refus}")

    def _qemu_deploy_decided(self, mod, dry_run):
        """Le choix d'interface, puis l'aperçu ou l'exécution.

        SÉPARÉE de son appelant pour que la garde du point de passage unique
        ait UN endroit où être rattrapée, quelle que soit l'interface qui a
        composé la spec.
        """
        if self._qemu_ask_ui() == "tui":
            spec = self._qemu_deploy_form(mod, dry_run)
            if spec is None:
                return
            if spec:  # None = annulé, {} = repli sur la CLI
                # Le formulaire signale les disques orphelins mais ne peut pas
                # les effacer : le faire demande root, et une invite de mot de
                # passe dans une application plein écran n'a nulle part où
                # s'afficher. La proposition vient donc ici, terminal rendu.
                if not self._qemu_offer_orphan_removal(
                    [vm["name"] for vm in spec.get("vms") or []]
                ):
                    print(t("Cancelled."))
                    return
                self._qemu_run_spec(spec)
                return

        got = self._qemu_collect_vms_cli(mod)
        if not got:
            return
        res_label, vms = got

        # Les options AVANT l'aperçu, et non l'inverse : posé plus haut, il
        # n'avait aucune spec à montrer et en fabriquait une réduite. La
        # collecte n'est pas la question qui engage — celle-là vient après
        # le plan, et l'aperçu ne la pose jamais puisqu'il ne fait rien.
        spec = self._qemu_collect_options_cli(vms, res_label)
        if not spec:
            return
        if dry_run:
            self._qemu_print_dry_run(spec)
            return
        self._qemu_run_spec(spec)

    def _qemu_deploy_form(self, mod, dry_run):
        """Ouvre le formulaire TUI. Renvoie la spec, None si annulé, ou {}
        pour retomber sur les invites en ligne (textual absent)."""
        from script.todo import textual_setup

        if not textual_setup.ensure():
            return {}
        try:
            from script.todo.qemu_deploy_form import run_deploy_form

            ctx = self._qemu_form_context(mod)
            spec = run_deploy_form(ctx)
        except ImportError:
            return {}
        if not spec:
            print(t("Cancelled."))
            return None
        if dry_run:
            # L'entrée « aperçu » du menu ne crée rien, même depuis la TUI.
            # La spec ENTIÈRE : elle est là, complète, et n'en transmettre
            # que les machines était une perte pure.
            self._qemu_print_dry_run(spec)
            return None
        self._qemu_print_recap(spec, spec.get("existing") or [])
        if not self._confirm_or_discard(t("Deploy these VMs now? (Y/n): ")):
            print(t("Cancelled."))
            return None
        return spec

    def _qemu_print_dry_run(self, spec):
        """Aperçu : les commandes deploy_qemu, sans rien créer.

        La SPEC ENTIÈRE, et non les seules machines. Le constructeur lit une
        douzaine de champs — fuseau, locale, bureau, outils, 3D, identité
        git, backend, commande d'installation — et une spec réduite les
        perdait tous : l'aperçu affirmait montrer ce qui serait lancé et
        montrait autre chose.

        Passe par le point de passage unique, donc l'écart avec le vrai
        déploiement est celui que borne test/test_qemu_dry_run_preview.py,
        et pas un de plus.
        """
        machines = spec.get("vms") or []
        # Les règles se CALCULENT, et rien ne s'écrit. Le refus d'une
        # posture que le site ne peut pas honorer arrive donc ici, avant
        # qu'aucune machine n'existe — ce qui est tout l'intérêt d'un
        # aperçu. Il ne s'interrompt pas pour autant : un essai à blanc
        # doit rester lançable, et le dire vaut mieux que se taire.
        regles = ""
        try:
            regles = self._qemu_egress_rules(spec)
        except Exception as souci:
            print(f"\n⛔ {t('Egress rules cannot be rendered:')} {souci}")
        egress = (
            EgressFiles(APERCU_REGLES, APERCU_UNITE)
            if regles
            else EgressFiles("", "")
        )
        print(f"\n{t('Preview (dry-run):')}")
        for vm in machines:
            parts = self._qemu_deploy_parts_for(
                vm, spec, dry_run=True, egress=egress
            )
            print("  " + " ".join(shlex.quote(p) for p in parts))
        if regles:
            # Le contenu, comme l'écriture atomique le montre à blanc
            # ailleurs : un nom de fichier n'apprend rien, les règles si.
            print(f"\n{t('Egress rules that would be posed:')}")
            for ligne in regles.rstrip("\n").splitlines():
                print(f"      │ {ligne}")

    def _qemu_collect_vms_cli(self, mod):
        """Invites en ligne : architecture, catalogue, ressources, noms.
        Renvoie (étiquette_de_profil, vms) ou None si rien à faire."""
        distros = list(mod.DISTROS)

        # 0) Architecture du parc (défaut : native ; [all] = TOUTES les archis
        # supportées). Pour une arch précise non-amd64, on restreint le
        # catalogue aux distros qui la publient ; pour [all], chaque distro
        # reçoit uniquement les archis QU'ELLE publie.
        arch = self._qemu_prompt_infra_arch()  # amd64/arm64/s390x/all
        if arch != "all":
            allowed = self._qemu_arch_distros(arch)
            if allowed is not None:
                keep = [d for d in distros if d in allowed]
                dropped = [d for d in distros if d not in keep]
                if dropped:
                    print(
                        f"  ⚠ {t('images for this arch only exist for:')} "
                        f"{', '.join(allowed)} "
                        f"({t('ignored:')} {', '.join(dropped)})"
                    )
                distros = keep
                if not distros:
                    print(t("Nothing selected."))
                    return None

        def arches_for(distro):
            return self._qemu_arches_for(distro, arch)

        # 1) Distributions : multi-sélection, catalogue complet, principal (la
        # version par défaut de chaque distro, marquée d'un *), ou granulaire
        # (liste à plat de TOUTES les versions × archis, choix par virgules).
        # Avec [all] archis, chaque version se décline en une VM par archi.
        print(f"\n{t('Distributions:')}")
        for i, d in enumerate(distros, 1):
            default_v = mod.DISTROS[d][1]
            vers = ", ".join(
                (v + " *" if v == default_v else v) for v in mod.DISTROS[d][0]
            )
            print(f"  [{i}] {d} ({vers}){self._qemu_stat_avg('distro', d)}")
        print(f"  [all] {t('Whole catalog (every version)')}")
        print(
            f"  [principal] {t('The main version of each distro (marked *)')}"
        )
        print(
            f"  [granulaire] {t('Pick exact versions (comma-separated list)')}"
        )
        raw = (
            input(
                t(
                    "Selection (numbers, 'all', 'principal' or 'granulaire',"
                    " default: all): "
                )
            )
            .strip()
            .lower()
        )
        catalog_all = raw in ("", "all", "*")
        principal = raw in ("principal", "each", "p")
        granular = raw in ("granulaire", "granular", "g")

        selected = []  # (distro, version, ram_mb, disk_str, arch)
        if granular:
            # Liste APLATIE distro + version + ARCHITECTURE : on choisit des
            # combinaisons précises par numéros séparés de virgules. La liste
            # vient du catalogue partagé avec le formulaire TUI.
            flat = self._qemu_catalog_entries(mod, distros, arch)
            print(f"\n{t('All versions:')}")
            for i, e in enumerate(flat, 1):
                star = " *" if e["default"] else ""
                print(
                    f"  [{i}] {e['distro']} {e['version']}{star} "
                    f"[{e['arch']}]  (RAM≥{e['ram']}Mo, {e['disk']})"
                )
            r = (
                input(t("Selection (comma-separated numbers): "))
                .strip()
                .lower()
            )
            for e in self._parse_index_selection(r, flat):
                selected.append(
                    (e["distro"], e["version"], e["ram"], e["disk"], e["arch"])
                )
        elif principal:
            # Une VM par distro (version par défaut) × chaque archi supportée.
            for d in distros:
                versions_map, default_v = mod.DISTROS[d]
                _c, _o, ram, disk = versions_map[default_v]
                for a in arches_for(d):
                    selected.append((d, default_v, ram, disk, a))
        else:
            sel_distros = (
                distros
                if catalog_all
                else self._parse_index_selection(raw, distros)
            )
            if not sel_distros:
                print(t("Nothing selected."))
                return None
            # 2) Versions par distro (multi-sélection) ; « all » si catalogue.
            for d in sel_distros:
                versions_map = mod.DISTROS[d][0]
                vlist = list(versions_map)
                if catalog_all:
                    chosen = vlist
                else:
                    print(f"\n{t('Versions for')} {d.capitalize()} :")
                    for i, v in enumerate(vlist, 1):
                        _c, _o, ram, disk = versions_map[v]
                        stat = self._qemu_stat_avg("version", v, d)
                        print(f"  [{i}] {v}  (RAM≥{ram}Mo, {disk}){stat}")
                    print(f"  [all] {t('select all')}")
                    r = input(
                        t("Selection (numbers, or 'all', default: all): ")
                    ).strip()
                    chosen = (
                        vlist
                        if r.lower() in ("", "all", "*")
                        else self._parse_index_selection(r.lower(), vlist)
                    )
                for v in chosen:
                    _c, _o, ram, disk = versions_map[v]
                    for a in arches_for(d):
                        selected.append((d, v, ram, disk, a))
        if not selected:
            print(t("Nothing selected."))
            return None

        # 2b) Ressources par VM : multiplicateur x1..x4 ou « Personnalisé ».
        # Le profil est CUIT dans `selected`, qui porte dès lors les valeurs
        # finales — RAM, disque et vCPU — pour chaque VM.
        host_cpu = os.cpu_count() or 2
        free_ram = self._host_free_ram_mb()
        res_label, selected = self._qemu_prompt_resources(
            selected, host_cpu, free_ram
        )

        # 2c) Personnalisation par VM : nom, disque, RAM, vCPU (à la demande).
        names, selected = self._qemu_customize_vms(selected, host_cpu)

        vms = [
            self._qemu_make_vm(d, v, a, ram, disk, vcpus, names[i])
            for i, (d, v, ram, disk, a, vcpus) in enumerate(selected)
        ]
        self._qemu_print_plan(vms, res_label, host_cpu, free_ram)
        return res_label, vms

    def _qemu_print_plan(self, vms, res_label, host_cpu, free_ram):
        """Plan + estimation des ressources de l'hôte."""
        total_ram = sum(vm["ram"] for vm in vms)
        total_disk = sum(self._parse_disk_gb(vm["disk"]) for vm in vms)
        total_cpu = sum(vm["vcpus"] for vm in vms)
        print(f"\n{t('Deployment plan')} ({len(vms)} VM, {res_label}) :")
        for vm in vms:
            print(
                f"  - {vm['name']:<30} {vm['distro']} {vm['version']:<7} "
                f"[{vm['arch']:<5}] {vm['vcpus']} vCPU  RAM {vm['ram']}Mo  "
                f"{t('disk')} {vm['disk']}"
            )
        cpu_warn = (
            f"   ⚠ {t('> host cores')} ({host_cpu})"
            if (total_cpu > host_cpu)
            else ""
        )
        print(f"\n  {t('Total vCPU (all running):')} {total_cpu}{cpu_warn}")
        print(f"  {t('Total RAM (all running):')} {total_ram} Mo")
        print(f"  {t('Total virtual disk (thin qcow2):')} ~{total_disk} G")
        if free_ram:
            print(f"  {t('Host RAM available:')} {free_ram} Mo")
            if total_ram > free_ram:
                warn = t(
                    "Total RAM exceeds host free RAM: not all VMs will run"
                    " at once."
                )
                print(f"  ⚠ {warn}")

    def _deploy_ask_posture(self, after_boot: bool = False) -> dict:
        """Les deux questions de la règle d'or, en ligne. Rend un FRAGMENT
        de spec.

        POSÉ PAR LES DEUX CHEMINS SANS FORMULAIRE — libvirt et Proxmox VE.
        Un fragment plutôt que deux clés recopiées chez chaque appelant :
        une clé écrite sous un autre nom d'un côté laisse la ligne vide,
        sans message et sans erreur.

        LES DONNÉES RÉELLES D'ABORD, parce que la réponse RETIRE des
        postures. Les offrir toutes puis refuser le couple à la garde fait
        répondre au reste du questionnaire avant de le dire. Ce qui est
        retiré s'affiche quand même, avec la raison que `screen_line`
        calcule déjà : une liste qui rétrécit en silence laisse croire que
        la posture n'existe pas.

        `after_boot` décrit le CHEMIN et non la posture : là où les règles
        n'arrivent qu'une fois la machine debout, les lignes portent
        l'écart de la fenêtre de démarrage.
        """
        real_data = self._is_yes(
            input(f"\n{t('This machine carries real data')} ? (y/N) : ")
        )
        offerts = vm_profiles.choices(real_data)
        ecrans = vm_profiles.form_context(after_boot)["posture_screen"]
        print(f"\n{t('Network posture')} :")
        for rang, (libelle, posture) in enumerate(offerts, 1):
            etoile = " *" if rang == 1 else ""
            print(f"  [{rang}] {libelle}{etoile}")
            print(f"      {ecrans[posture]}")
        retenus = vm_profiles.withheld(real_data)
        if retenus:
            print(f"\n  {t(vm_profiles.CANNOT_CARRY_REAL_DATA)}")
            for libelle, posture in retenus:
                print(f"  [-] {libelle}")
                print(f"      {ecrans[posture]}")
        # AUCUNE POSTURE OFFERTE : le fragment garde la réponse et ne nomme
        # personne. La garde lit alors la posture par défaut contre des
        # données réelles, et refuse — le seul repli qui ne promet rien.
        if not offerts:
            return {posture_spec.REAL_DATA_KEY: real_data}
        defaut = offerts[0]
        sel = input(
            f"{t('Choice (number or name, blank = the first):')} "
        ).strip()
        choisi = defaut
        if sel:
            choisi = None
            try:
                rang = int(sel) - 1
                if 0 <= rang < len(offerts):
                    choisi = offerts[rang]
            except ValueError:
                for offert in offerts:
                    if sel in offert:
                        choisi = offert
            if choisi is None:
                print(f"{t('Invalid selection, using')} {defaut[0]}")
                choisi = defaut
        return {
            posture_spec.POSTURE_KEY: choisi[1],
            posture_spec.REAL_DATA_KEY: real_data,
        }

    def _qemu_ask_desktop(self):
        """Serveur, ou serveur plus un bureau. Renvoie "" ou la saveur.

        Serveur par défaut : c'est ce que sert une image cloud, et le bureau
        ajoute une à deux heures d'installation sur une architecture émulée."""
        print(f"\n{t('VM type:')}")
        print(f"  [1] {t('Server (no graphical interface)')} *")
        flavours = list(self._QEMU_DESKTOP)
        for i, key in enumerate(flavours, 2):
            label = self._QEMU_DESKTOP[key]["label"]
            print(f"  [{i}] {t('Graphical (server + desktop):')} {label}")
        sel = input(t("Choice (number, blank = server): ")).strip()
        try:
            index = int(sel) - 2
        except ValueError:
            return ""
        return flavours[index] if 0 <= index < len(flavours) else ""

    @classmethod
    def _qemu_app_store_needed(cls, vms):
        """Vrai si au moins une VM du parc est à la fois graphique et d'une
        distribution qui livre snapd. Ailleurs la question n'a pas d'objet :
        un serveur ne tire aucun snap, et Debian ou Fedora n'en livrent pas."""
        return any(
            vm.get("desktop") and vm.get("distro") in cls.QEMU_SNAP_DISTROS
            for vm in vms
        )

    def _qemu_ask_app_store(self, vms):
        """Magasin d'applications des VM graphiques Ubuntu."""
        if not self._qemu_app_store_needed(vms):
            return "deb"
        print(f"\n{t('Application store (graphical Ubuntu VMs):')}")
        for i, (_key, label) in enumerate(self.QEMU_APP_STORES, 1):
            star = " *" if i == 1 else ""
            print(f"  [{i}] {t(label)}{star}")
        print(f"  ⚠ {t('snap needs the store; slow under emulation.')}")
        answer = input(f"{t('Choice')} [1]: ").strip() or "1"
        if answer.isdigit() and 1 <= int(answer) <= len(self.QEMU_APP_STORES):
            return self.QEMU_APP_STORES[int(answer) - 1][0]
        return "deb"

    def _qemu_ask_vm_tools(self, vms):
        """Outils de développement des VM graphiques : liste à cocher.

        Ne montre que ce qu'au moins une VM du parc peut recevoir : les IDE
        graphiques disparaissent d'un parc de serveurs, où ils n'auraient rien
        pour s'afficher, et la compilation mobile reste offerte — elle compile,
        elle n'affiche pas. La réponse vaut pour tout le parc et sera filtrée
        machine par machine.

        Saisie par numéros séparés par des espaces ou des virgules, « tous »
        pour tout cocher, vide pour rien : quatre questions oui/non de plus
        alourdiraient une séquence d'invites déjà longue."""
        choices = [
            c
            for c in self._qemu_vm_tool_choices()
            if any(
                self._qemu_tools_for(
                    (c[0],),
                    vm.get("arch", "amd64"),
                    vm.get("desktop", ""),
                    vm.get("distro", ""),
                )
                for vm in vms
            )
        ]
        if not choices:
            return ()
        print(f"\n{t('Development tools:')}")
        for i, (_key, label, hint) in enumerate(choices, 1):
            print(f"  [{i}] {label} — {hint}")
        gb = ", ".join(
            f"{label} +{self._QEMU_VM_TOOLS[key]['disk_gb']} Go"
            for key, label, _hint in choices
        )
        # Le mobile fait échouer la VM quand l'application ne compile pas :
        # c'est le but, mais il vaut mieux le savoir avant de cocher.
        if any(k == "mobile" for k, _l, _h in choices):
            print(f"  ⚠ {t('a failed mobile build marks the VM as failed')}")
        print(f"  {t('Disk needed:')} {gb}")
        answer = input(
            f"{t('Numbers separated by spaces, [all], blank = none:')} "
        ).strip()
        if not answer:
            return ()
        if answer.lower() in ("all", "tous", "toutes", "*"):
            return tuple(key for key, _l, _h in choices)
        picked = []
        for token in answer.replace(",", " ").split():
            if token.isdigit() and 1 <= int(token) <= len(choices):
                key = choices[int(token) - 1][0]
                if key not in picked:
                    picked.append(key)
        return tuple(picked)

    def _qemu_ask_ai_tools(self, vm_tools):
        """(agent, nom, courriel) — rien à poser si l'outil n'est pas coché.

        Le nom et le courriel sont proposés avec l'identité de l'HÔTE, qui
        est ce que la VM reçoit aujourd'hui : une réponse vide la garde. Sans
        ce défaut affiché, un champ vide se lirait comme une identité absente
        et inviterait à la ressaisir pour rien.
        """
        from script.todo import dev_tools

        if "aidev" not in (vm_tools or ()):
            return "", "", ""
        noms = list(dev_tools.AGENTS)
        print(f"  {t('AI coding tools')} :")
        for i, nom in enumerate(noms, 1):
            marque = " ←" if nom == dev_tools.AGENT_DEFAUT else ""
            print(f"    [{i}] {nom}{marque}")
        rep = input("    " + t("Choice: ")).strip()
        agent = (
            noms[int(rep) - 1]
            if rep.isdigit() and 1 <= int(rep) <= len(noms)
            else dev_tools.AGENT_DEFAUT
        )
        hote_nom = self._qemu_host_git("user.name")
        hote_mail = self._qemu_host_git("user.email")
        nom = input(f"    {t('Name for git')} [{hote_nom}] : ").strip()
        mail = input(f"    {t('Email for git')} [{hote_mail}] : ").strip()
        return agent, nom, mail

    def _qemu_ask_python_provider(self, arches):
        """mise (CPython précompilé) ou pyenv (compilation).

        `arches` : les architectures du parc à déployer. mise ne publie pas de
        binaire pour toutes — hors de QEMU_MISE_ARCHES la question n'a pas de
        sens et on ne la pose pas."""
        usable = [a for a in arches if a in self.QEMU_MISE_ARCHES]
        if not usable:
            # Rien, pas « pyenv » : le mode automatique doit rester libre de
            # préférer un Python de la distribution. Voir _python_provider()
            # dans le formulaire, même raisonnement.
            return ""
        print(f"\n{t('Python interpreter:')}")
        print(f"  [1] {t('mise (precompiled, faster)')} *")
        print(f"  [2] {t('pyenv (compiles from source)')}")
        skipped = [a for a in arches if a not in self.QEMU_MISE_ARCHES]
        if skipped:
            # Dit AVANT le déploiement plutôt que découvert dans un log.
            print(
                f"  ⚠ {t('mise has no binary for:')} "
                f"{', '.join(sorted(set(skipped)))} — "
                f"{t('those VMs use pyenv')}"
            )
        sel = input(t("Choice (number, blank = mise): ")).strip()
        return "pyenv" if sel == "2" else "mise"

    def _qemu_host_timezone(self):
        """Fuseau de l'hôte. Défini une seule fois, dans deploy_qemu.py, qui
        est aussi ce qui l'écrit dans le cloud-config : l'invite ne peut donc
        pas proposer un défaut différent de celui réellement appliqué."""
        try:
            mod = self._qemu_import_module()
            return mod.host_timezone()
        except Exception:
            return "UTC"

    def _qemu_ask_timezone(self):
        """Fuseau des VM à créer, celui de l'hôte par défaut.

        Une VM qui hérite du fuseau de son opérateur horodate ses journaux et
        ses bases comme lui ; en UTC l'écart ne se remarque qu'après coup."""
        default = self._qemu_host_timezone()
        answer = input(f"{t('Timezone for the VMs')} ({default}): ").strip()
        if not answer:
            return default
        # Un fuseau inconnu ne casse pas cloud-init : il l'ignore en silence et
        # la VM reste en UTC. Mieux vaut le refuser ici que le découvrir plus
        # tard sur des horodatages faux.
        if not os.path.exists(os.path.join("/usr/share/zoneinfo", answer)):
            print(f"⚠  {t('Unknown timezone, keeping')} {default}")
            return default
        return answer

    def _qemu_ask_locale(self):
        """Locale des VM. « C.UTF-8 » par défaut : les autres déclenchent un
        locale-gen dans l'invité, 36 s sur s390x — payé à chaque
        déploiement pour un confort dont une VM jetable n'a pas besoin."""
        default = "C.UTF-8"
        answer = input(f"{t('Locale for the VMs')} ({default}): ").strip()
        return answer or default

    def _qemu_collect_options_cli(self, vms, res_label):
        """Invites en ligne : clé SSH, installation ERPLibre, ~/.ssh/config,
        parallélisme, puis récapitulatif et confirmation.
        Renvoie la spec complète, ou None si l'utilisateur renonce."""
        # LA POSTURE EN TÊTE, comme le formulaire la pose juste sous la
        # machine : elle décrit le réseau de la VM et non ce qu'on installe
        # dedans. Sans elle, la spec de cette voie laissait la garde replier
        # sur « sortie libre » et « pas de données réelles ».
        posture = self._deploy_ask_posture()
        # Clé SSH (partagée par tout le parc). Sans clé, cloud-init n'en
        # injecte aucune : la VM démarre sans accès SSH, donc sans
        # installation ni vérification possibles. On propose donc d'en créer
        # une plutôt que de laisser passer un déploiement inutilisable.
        default_key = self._qemu_default_ssh_key()
        if not default_key:
            print(f"\n⚠  {t('No SSH public key found in ~/.ssh.')}")
            print(f"   {t('Without one the VMs start with no SSH access.')}")
            if self._is_yes_default_yes(input(t("Generate one now? (Y/n): "))):
                default_key = self._ssh_ensure_key()
        key_hint = default_key or t("none")
        ssh_key = input(f"{t('SSH public key path')} ({key_hint}): ").strip()
        if not ssh_key:
            ssh_key = default_key
        if ssh_key:
            ssh_key = os.path.expanduser(ssh_key)

        timezone = self._qemu_ask_timezone()
        locale = self._qemu_ask_locale()
        desktop = self._qemu_ask_desktop()
        # La CLI ne pose qu'un type pour tout le parc : on le recopie sur chaque
        # VM avant de décider du magasin, qui ne concerne que les graphiques.
        # Le nom suit le type, exactement comme dans le formulaire — c'est la
        # même fonction, pas une seconde implémentation.
        from script.todo.qemu_deploy_form import vm_name

        suffixes = self._qemu_desktop_suffixes()
        for _vm in vms:
            _vm.setdefault("desktop", desktop)
            _vm["name"] = vm_name(_vm["name"], _vm.get("desktop"), suffixes)
        app_store = self._qemu_ask_app_store(vms)
        vm_tools = self._qemu_ask_vm_tools(vms)
        python_provider = self._qemu_ask_python_provider(
            [vm["arch"] for vm in vms]
        )

        # 4) Option : installer ERPLibre dans ~/git/erplibre de chaque VM.
        install = None
        ans = input(
            t("Install ERPLibre into ~/git/erplibre on each VM? (Y/n): ")
        )
        if not self._is_yes_default_yes(ans) and any(
            v.get("distro") == "proxmox" for v in vms
        ):
            # C'est par cette étape que passe l'installation de Proxmox : sans
            # elle la VM reste une Debian nue, ce qui n'est pas ce qu'on a
            # demandé en choisissant « Proxmox VE » comme système.
            print(
                f"\n  ⚠ {t('Proxmox will NOT be installed: plain Debian VM.')}"
            )
            print(
                f"    {t('Later, in the VM:')}"
                " sudo ./script/proxmox/install_proxmox.sh"
            )
        if self._is_yes_default_yes(ans):
            branch = self._qemu_pick_branch()
            # dev (~/git, SELinux relâché) vs prod (/opt, confiné)
            prod = self._qemu_ask_prod()
            label, cmd = self._qemu_pick_install_profile(
                "proxmox"
                if any(v.get("distro") == "proxmox" for v in vms)
                else ""
            )
            monitor = self._is_yes_default_yes(
                input(t("Interactive monitoring dashboard? (y/N): "))
            )
            install = {
                "branch": branch,
                "prod": prod,
                "label": label,
                "cmd": cmd,
                "monitor": monitor,
            }
        else:
            # Rien à installer : le suivi garde tout son sens — il regarde les
            # VM arriver (cloud-init, puis relevé système) et porte le tableau
            # d'état, de débit d'écriture, de RAM et de disque. La question
            # était posée DANS la branche ERPLibre : refuser l'une emportait
            # l'autre sans qu'on l'ait demandé.
            monitor = self._is_yes_default_yes(
                input(f"{t('Watch the VMs start (no install)')} ? (O/n) : ")
            )

        # Posée même sans bureau : une VM sans console peut vouloir un
        # virtio-gpu accéléré, et c'est ce que « auto » n'accorde jamais.
        gpu3d = self._is_yes(
            input(
                t("3D acceleration (host GPU), even without a screen? (y/N): ")
            )
        )

        # Posée seulement quand un cache tourne : ailleurs, la réponse ne
        # changerait rien et la question ferait croire le contraire.
        cache_bypass = False
        if self._qemu_cache_active():
            cache_bypass = self._is_yes(
                input(t("Keep this VM out of the download cache? (y/N): "))
            )

        # Ces trois réponses n'ont d'objet que si l'outil est coché : les
        # poser toujours ferait trois questions de plus à qui n'en veut pas.
        ai_agent, git_name, git_email = self._qemu_ask_ai_tools(vm_tools)

        add_ssh_config = self._is_yes_default_yes(
            input(t("Add each VM to ~/.ssh/config? (Y/n): "))
        )

        # 5) Sépare les VM à CRÉER des déjà existantes AVANT de proposer le
        # parallélisme : on connaît alors le vrai nombre à déployer (affiché
        # dans le prompt) et on peut numéroter chaque tâche.
        pending, existing = self._qemu_split_existing(
            vms, self._qemu_list_domains()
        )
        n_jobs = len(pending)

        # Collisions de noms : une VM déjà définie est ignorée (rien n'est
        # écrasé), mais un qcow2 orphelin fera ÉCHOUER deploy_qemu, qui refuse
        # d'écraser sans --force. On le dit avant, pas après l'attente.
        if not self._qemu_confirm_collisions(
            existing, [vm["name"] for vm in pending]
        ):
            print(t("Cancelled."))
            return None
        if not pending:
            print(t("Nothing to create - every VM already exists."))
            return None

        # Nombre de déploiements en parallèle. Par défaut UNE EXÉCUTION PAR
        # INSTALLATION : le plafond du nombre de CPU ne s'applique pas, c'est
        # le nombre de VM qui fait foi. « n » retombe sur ce plafond, et un
        # chiffre vaut pour lui-même — même règle que les autres invites.
        default_par = n_jobs or 1
        cpu_par = min(n_jobs, os.cpu_count() or 4) or 1
        print(f"  [n] {t('limit to host cores')} ({cpu_par})")
        raw = (
            input(
                f"{t('Parallel deployments (default:')} {default_par}, "
                f"{n_jobs} {t('VMs')}): "
            )
            .strip()
            .lower()
        )
        if raw == "n":
            parallelism = cpu_par
        else:
            try:
                parallelism = max(1, int(raw)) if raw else default_par
            except ValueError:
                parallelism = default_par

        spec = {
            "res_label": res_label,
            "vms": pending,
            "existing": existing,
            "ssh_key": ssh_key,
            "timezone": timezone,
            "locale": locale,
            "desktop": desktop,
            "vm_tools": vm_tools,
            "python_provider": python_provider,
            "app_store": app_store,
            "install": install,
            # Au niveau du déploiement : le suivi survit à une installation
            # décochée (voir _qemu_run_spec).
            "monitor": monitor,
            "gpu3d": gpu3d,
            "cache_bypass": cache_bypass,
            "ai_agent": ai_agent,
            "git_name": git_name,
            "git_email": git_email,
            "add_ssh_config": add_ssh_config,
            "parallelism": parallelism,
            # Le FRAGMENT et non deux clés recopiées : il est indexé par les
            # constantes qui les nomment, donc il ne peut pas diverger de ce
            # que la garde relit.
            **posture,
        }

        # 6) Récapitulatif final, puis confirmation. Toutes les réponses
        # données jusqu'ici sont rassemblées ici : c'est le dernier point où
        # une erreur de saisie se rattrape sans avoir rien créé.
        self._qemu_print_recap(spec, existing)
        if not self._confirm_or_discard(t("Deploy these VMs now? (Y/n): ")):
            print(t("Cancelled."))
            return None
        return spec

    def _qemu_deploy_jobs_cli(self, jobs, workers):
        """Déploiement parallèle, sortie texte. Renvoie
        [(nom, rc, sortie, durée)] — même contrat que la vue TUI."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _run(job):
            jid, jname, jparts = job
            j0 = time.time()
            res = subprocess.run(jparts, capture_output=True, text=True)
            out = (res.stdout or "") + (res.stderr or "")
            return jid, jname, res.returncode, out, time.time() - j0

        outcome = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run, j) for j in jobs]
            # done = ordre de COMPLÉTION (les résultats reviennent dans le
            # désordre) ; jid = ordre de préparation (stable). Durée par VM.
            for done, fut in enumerate(as_completed(futures), 1):
                jid, jname, rc, out, secs = fut.result()
                mark = "✅" if rc == 0 else "❌"
                print(
                    f"\n[{done}/{len(jobs)}] {mark} [{jid}] {jname} "
                    f"(rc={rc}, {self._fmt_dur(secs)})"
                )
                lignes = [ln for ln in out.strip().splitlines() if ln]
                # Une VM qui réussit n'a rien à raconter ; une qui échoue a
                # UNE ligne qui compte, et elle est écrite par l'outil, pas
                # par nous. Quatre lignes ne suffisent pas à l'atteindre :
                # l'épilogue « Échec de la commande » et sa ligne de commande
                # les occupent, et le message de virt-install tombe juste
                # au-dessus de la fenêtre.
                for line in lignes[-4:] if rc == 0 else lignes[-30:]:
                    print(f"    {line}")
                if rc != 0:
                    chemin = self._qemu_save_failure_log(jname, out)
                    if chemin:
                        print(f"    {t('Full output:')} {chemin}")
                    # La 3D est décidée DANS deploy_qemu.py, pas dans l'argv :
                    # sa présence se lit sur la commande que le journal a
                    # rapportée. Le menu n'expose pas « --gpu off », donc la
                    # seule issue depuis ici est de la nommer.
                    if "accel3d=on" in out or "egl-headless" in out:
                        print(f"    {t('3D was on; retry without it:')}")
                        print("      ./script/qemu/deploy_qemu.py --gpu off …")
                outcome.append((jname, rc, out, secs))
        return outcome

    @staticmethod
    def _qemu_save_failure_log(name, out):
        """Écrit la sortie complète d'une création ratée. Rend le chemin.

        L'appelant jette `out` après la boucle : sans ce fichier, l'unique
        trace d'un échec est ce qui a défilé à l'écran. Rend None si l'écriture
        échoue — perdre le journal ne doit pas faire perdre le déploiement.
        """
        try:
            from script.todo.qemu_install_monitor import session_dir

            sur = "".join(
                c if c.isalnum() or c in "-_." else "_" for c in name
            )
            chemin = session_dir() / f"{sur}-create.log"
            chemin.write_text(out, encoding="utf-8", errors="replace")
            return chemin
        except Exception:
            return None

    def _qemu_deploy_jobs_tui(self, jobs, workers):
        """Même chose, en blocs repliables Textual. Renvoie None si textual
        manque, pour que l'appelant retombe sur la sortie texte."""
        from script.todo import textual_setup

        if not textual_setup.ensure():
            return None
        try:
            from script.todo.qemu_deploy_form import run_deploy_progress

            return run_deploy_progress(jobs, workers)
        except ImportError:
            return None

    @contextlib.contextmanager
    def _qemu_sans_internet(self, actif):
        """Coupe l'amont du cache le temps du bloc, et le rebranche toujours.

        Deux sorties tombent : celle du service du cache, et celle que l'hôte
        relaie pour les VM, et la résolution des noms par l'internet. Ce
        qu'une VM demande à l'hôte lui-même reste joignable : le cache, et
        les noms, auxquels l'hôte répond seul une adresse que le cache
        intercepte. Tout ce qui arrive encore dans une VM vient donc du
        disque du cache, et un pas qui prendrait un autre chemin échoue.

        La coupure vaut pour la spec ENTIÈRE, installation comprise : c'est
        l'installation qui télécharge, et une coupure levée avant elle ne
        mesurerait plus rien.

        Elle vaut aussi pour les AUTRES usagers du cache pendant ce temps —
        un déploiement mené en parallèle depuis un autre terminal se
        retrouvera hors ligne sans l'avoir demandé.

        La table est UNIQUE et partagée : deux coupures n'en font qu'une, et
        la première levée ôte les deux. D'où le refus quand un guet tourne
        encore — sa fin lèverait la coupure de ce déploiement-ci en cours de
        route — et la question quand une table est posée sans guet.

        Sur la voie suivie, la levée est confiée au guet dès le lancement des
        installations (`_qemu_confier_la_levee`) ; le « finally » ne la fait
        alors pas, il dit jusqu'à quand l'amont reste coupé. Ailleurs, il lève
        et VÉRIFIE : « rebranché » ne s'affiche que constaté.

        Hors ligne, un verrou de fichier tient le bloc ENTIER, relevés
        compris : deux déploiements lancés ensemble passeraient sinon tous
        deux les relevés avant que l'un ait posé son guet. Tant que la
        coupure est tenue, SIGHUP et SIGTERM déroulent le « finally » au lieu
        de tuer le processus sur place. La commande de coupure elle-même
        tourne DANS le « try » qui lève : un signal reçu pendant qu'elle
        s'exécute, la table déjà posée, trouve la levée sur son chemin. Seule
        une coupure qui rend un échec n'est pas levée — le sudo qui l'a
        refusée refuserait le retrait aussi, et redemanderait un mot de passe.

        En ligne, rien n'est coupé, mais une coupure tenue par un autre
        déploiement ferait tourner celui-ci hors ligne : on le dit et on
        demande (`_qemu_en_ligne_malgre_la_coupure`).
        """
        if not actif:
            if not self._qemu_en_ligne_malgre_la_coupure():
                raise _SansInternetImpossible()
            yield False
            return
        from script.qemu import cache_offline

        # Sans dnsmasq, la coupure des noms ne peut pas se poser, et
        # `cut_cmd` échouerait sans dire pourquoi : on le dit avant de rien
        # toucher.
        if not cache_offline.dnsmasq():
            print(f"\n  ✗ {t('dnsmasq is missing on the host: names cannot')}")
            print(
                f"    {t('be cut. Install the dnsmasq package, then F5.')} "
                f"{t('Nothing deployed.')}"
            )
            raise _SansInternetImpossible()
        with self._qemu_verrou_hors_ligne() as libre:
            if not libre:
                print(
                    f"\n  ✗ {t('Another offline deployment is starting or')}"
                )
                print(
                    f"    {t('running in another terminal.')} "
                    f"{t('Nothing deployed.')}"
                )
                raise _SansInternetImpossible()
            if not self._qemu_coupure_libre():
                raise _SansInternetImpossible()
            anciens = self._qemu_signaux_de_sortie()
            lever = True
            try:
                try:
                    if self._qemu_shell(cache_offline.cut_cmd()):
                        lever = False
                        # Refuser plutôt que déployer quand même : une VM
                        # bâtie avec l'amont debout se bâtit toujours, et son
                        # succès se lirait comme une preuve hors ligne qu'elle
                        # n'est pas.
                        print(
                            f"\n  ✗ {t('Upstream not cut: nothing deployed.')}"
                        )
                        faux = t(
                            "The result would look offline without being so."
                        )
                        print(f"    {faux}")
                        raise _SansInternetImpossible()
                    print(
                        f"\n  ✂ {t('Cache upstream cut for this deployment.')}"
                    )
                    yield True
                finally:
                    if lever:
                        self._qemu_rebrancher()
            finally:
                self._qemu_signaux_rendus(anciens)

    @staticmethod
    def _qemu_verrou_hors_ligne_chemin():
        """Fichier du verrou des déploiements hors ligne, dans le répertoire
        des sessions d'installation."""
        from script.todo.qemu_install_monitor import session_dir

        return session_dir() / ".coupure-hors-ligne.lock"

    @contextlib.contextmanager
    def _qemu_verrou_hors_ligne(self):
        """Tient le verrou exclusif des déploiements hors ligne le temps du
        bloc. Rend False s'il est déjà tenu ailleurs, True sinon.

        `flock` non bloquant : un second terminal est refusé sur-le-champ
        plutôt que mis en attente d'un déploiement qui dure des heures. Le
        verrou tombe avec le descripteur, donc aussi à la mort du processus,
        même par SIGKILL : aucun reste à nettoyer. Le descripteur n'est pas
        hérité (PEP 446) : les installations détachées ne le gardent pas.

        Un fichier impossible à ouvrir rend True : le verrou ne ferme que la
        course entre deux terminaux, les relevés qui suivent tiennent encore.
        """
        try:
            fd = os.open(
                self._qemu_verrou_hors_ligne_chemin(),
                os.O_RDWR | os.O_CREAT,
                0o600,
            )
        except OSError:
            yield True
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            libre = True
        except BlockingIOError:
            libre = False
        except OSError:
            # Système de fichiers sans flock : même règle qu'un fichier
            # impossible à ouvrir.
            libre = True
        try:
            yield libre
        finally:
            os.close(fd)

    def _qemu_verrou_tenu_ailleurs(self):
        """Un déploiement hors ligne tient-il le verrou ? Lecture seule.

        Le fichier n'est pas créé : absent, personne ne le tient. Le verrou
        n'est pris qu'un instant pour le sonder, puis rendu.
        """
        try:
            fd = os.open(self._qemu_verrou_hors_ligne_chemin(), os.O_RDWR)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        except OSError:
            return False
        finally:
            os.close(fd)
        return False

    def _qemu_en_ligne_malgre_la_coupure(self):
        """Un déploiement EN LIGNE peut-il partir ? True si oui.

        La table est partagée par tout le cache : tant qu'un autre
        déploiement la tient — son guet attend ses installations, ou il est
        encore en train de se lancer —, celui-ci tournerait hors ligne sans
        l'avoir demandé, et ses échecs de téléchargement se liraient comme
        des pannes. On le dit et on demande, « non » par défaut.

        Aucun sudo ici : `guet_actif_cmd` lit l'état d'une unité, et le
        verrou est un fichier de l'utilisateur. Sans guet ni verrou tenu,
        rien n'est demandé.
        """
        from script.qemu import cache_offline

        if self._qemu_shell(cache_offline.guet_actif_cmd()) == 0:
            heures = cache_offline.DUREE_MAX_GUET // 3600
            print(f"\n  ⚠ {t('An offline deployment is still installing.')}")
            print(f"    {t('The cache upstream stays cut until the last')}")
            print(f"    {t('installation ends, at most')} {heures} h.")
            print(f"    {t('This deployment would therefore run offline.')}")
            print(
                f"    {t('Lift it now with:')} "
                f"{cache_offline.lever_maintenant_cmd()}"
            )
        elif self._qemu_verrou_tenu_ailleurs():
            print(f"\n  ⚠ {t('An offline deployment is starting in another')}")
            print(
                f"    {t('terminal: the cache upstream is cut until it ends.')}"
            )
            print(f"    {t('This deployment would therefore run offline.')}")
        else:
            return True
        if not self._is_yes(
            input(f"  {t('Deploy anyway, offline? (y/N): ')}")
        ):
            print(f"  {t('Nothing deployed.')}")
            return False
        return True

    @staticmethod
    def _qemu_signaux_de_sortie():
        """Fait de SIGHUP et SIGTERM une sortie qui déroule les « finally ».

        Leur action par défaut tue le processus sur place : un terminal fermé
        ou une session ssh perdue laisse alors la coupure posée sans fin.
        Ici, le premier signal lève SystemExit(128 + signal) ; les suivants
        sont sans effet, pour qu'un second signal n'interrompe pas la levée en
        cours. Un signal déjà ignoré le reste : lancé sous « nohup », le
        déploiement doit survivre à son terminal.

        Rend {signal: ancien gestionnaire}, à passer à `_qemu_signaux_rendus`.
        Hors du fil principal, `signal.signal` lève ValueError : rien n'est
        posé et le dictionnaire est vide.
        """
        if threading.current_thread() is not threading.main_thread():
            return {}
        deja = []

        def sortir(signum, _frame):
            if deja:
                return
            deja.append(signum)
            raise SystemExit(128 + signum)

        anciens = {}
        for nom in ("SIGHUP", "SIGTERM"):
            num = getattr(signal, nom, None)
            if num is None or signal.getsignal(num) == signal.SIG_IGN:
                continue
            try:
                anciens[num] = signal.signal(num, sortir)
            except (ValueError, OSError):
                continue
        return anciens

    @staticmethod
    def _qemu_signaux_rendus(anciens):
        """Remet les gestionnaires que rend `_qemu_signaux_de_sortie`.

        Un ancien gestionnaire posé hors de Python se lit None : il redevient
        l'action par défaut, la seule qu'on sache rétablir.
        """
        for num, ancien in anciens.items():
            try:
                signal.signal(
                    num, signal.SIG_DFL if ancien is None else ancien
                )
            except (ValueError, OSError, TypeError):
                continue

    def _qemu_coupure_libre(self):
        """Peut-on poser une coupure ? True si oui, False si rien ne doit
        être déployé — l'appelant n'a plus rien à dire, tout est affiché.

        Un guet actif refuse d'office, que la table soit posée ou non : il la
        retirera à la fin des installations qu'il attend, et celle de ce
        déploiement avec. Une table posée sans guet est un reste — processus
        tué, installation synchrone menée depuis un autre terminal — que
        seul l'utilisateur peut juger : on demande, « non » par défaut.
        """
        from script.qemu import cache_offline

        if self._qemu_shell(cache_offline.guet_actif_cmd()) == 0:
            print(
                f"\n  ✗ {t('An offline deployment is still running: the cut')}"
            )
            print(
                f"    {t('is shared, and its end would lift yours.')} "
                f"{t('Nothing deployed.')}"
            )
            print(
                f"    {t('Lift it now with:')} "
                f"{cache_offline.lever_maintenant_cmd()}"
            )
            return False
        if self._qemu_shell(cache_offline.table_posee_cmd()) != 0:
            return True
        print(f"\n  ⚠ {t('The cache upstream is already cut, and nothing')}")
        print(f"    {t('will lift it: an interrupted deployment, or one')}")
        print(f"    {t('still installing without the monitor.')}")
        if not self._is_yes(input(f"  {t('Lift it and continue? (y/N): ')}")):
            print(f"  {t('Nothing deployed.')}")
            return False
        self._qemu_shell(cache_offline.restore_cmd())
        return True

    def _qemu_rebrancher(self):
        """Le « finally » de la coupure : lever, ou dire qui lèvera.

        Guet actif : les installations tournent encore, détachées, et c'est
        lui qui lèvera à la dernière. Lever ici les ferait finir en ligne.

        Sinon, TOUJOURS lever — une coupure laissée en place prive le cache de
        réseau bien après, et la panne se découvre ailleurs — puis constater :
        `restore_cmd` rend 0 même quand sudo refuse, et seul un relevé de la
        table dit si l'amont est revenu.
        """
        from script.qemu import cache_offline

        if self._qemu_shell(cache_offline.guet_actif_cmd()) == 0:
            heures = cache_offline.DUREE_MAX_GUET // 3600
            print(f"\n  ✂ {t('The cache upstream stays cut until the last')}")
            print(
                f"    {t('installation ends, at most')} {heures} h."
                f" {t('Lift it now with:')}"
            )
            print(f"    {cache_offline.lever_maintenant_cmd()}")
            return
        self._qemu_shell(cache_offline.restore_cmd())
        if self._qemu_shell(cache_offline.table_posee_cmd()) == 1:
            print(f"  {t('Cache upstream restored.')}")
            return
        print(f"\n  ✗ {t('The cache upstream may still be cut.')}")
        print(f"    {t('Lift it with:')} {cache_offline.restore_cmd()}")

    def _qemu_confier_la_levee(self, manifest):
        """Confie la levée de la coupure à root, le temps des installations.

        Appelée juste après leur lancement et AVANT le tableau de bord : le
        terminal est encore libre pour une invite de mot de passe. L'unité
        attend le marqueur de sortie de chaque journal du manifeste, puis
        lève ; elle survit à la fermeture du tableau de bord comme à la mort
        de ce processus, et le tableau de bord reste détachable.

        Rend True si le guet est posé. En cas d'échec, la coupure reste au
        « finally », c'est-à-dire à la fermeture du tableau de bord : le dire,
        puisque le fermer avant la fin fait finir les installations en ligne.
        """
        from script.qemu import cache_offline
        from script.todo.qemu_install_monitor import EXIT_MARKER

        try:
            with open(manifest, encoding="utf-8") as fh:
                journaux = [vm["log"] for vm in json.load(fh)["vms"]]
        except (OSError, ValueError, KeyError, TypeError):
            journaux = None
        heures = cache_offline.DUREE_MAX_GUET // 3600
        if (
            journaux
            and cache_offline.chemins_surs(journaux)
            and not self._qemu_shell(
                cache_offline.guet_cmd(journaux, EXIT_MARKER)
            )
        ):
            print(f"\n  ✂ {t('The cache upstream comes back when the last')}")
            print(
                f"    {t('installation ends, at most')} {heures} h,"
                f" {t('even if the monitor is closed.')}"
            )
            return True
        print(f"\n  ⚠ {t('Could not hand the lift over to systemd-run:')}")
        print(f"    {t('the cache upstream comes back when the monitor')}")
        print(
            f"    {t('closes; closing it early finishes the installs online.')}"
        )
        return False

    @staticmethod
    def _qemu_shell(cmd, timeout=60):
        """Code de retour d'une commande shell locale, 255 si elle n'a pas
        pu être lancée du tout."""
        try:
            return subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            ).returncode
        except (OSError, subprocess.SubprocessError):
            return 255

    def _qemu_run_spec(self, spec):
        """Enveloppe le déploiement de la coupure d'amont qu'il demande.

        Séparée du déploiement lui-même : la spec entière doit tenir dans le
        bloc, et un « with » autour de deux cents lignes déjà indentées se
        relit mal.
        """
        try:
            with self._qemu_sans_internet(bool(spec.get("offline"))) as coupee:
                return self._qemu_deploie_spec(spec, coupee=coupee)
        except _SansInternetImpossible:
            return

    def _qemu_deploie_spec(self, spec, coupee=False):
        """Exécute une spec de déploiement : création des VM en parallèle,
        résolution des IP, ~/.ssh/config, installation ERPLibre.

        Ne pose AUCUNE question — tous les choix sont dans la spec, d'où
        qu'elle vienne (invites en ligne ou formulaire TUI).

        `coupee` : l'amont du cache est coupé autour de cet appel. La voie
        suivie en confie alors la levée au guet, dès le lancement."""
        pending = spec["vms"]
        deployed = list(spec.get("existing") or [])
        install = spec.get("install")
        install_branch = install["branch"] if install else None
        # Le type de VM est choisi machine par machine dans la TUI ; la CLI n'en
        # pose qu'un pour tout le parc. On ramene les deux a la meme carte, et
        # `desktop` reste la reponse a « faut-il installer un bureau quelque
        # part ? », qui declenche la phase d'installation.
        desktop_default = spec.get("desktop") or ""
        desktop_map = {
            vm["name"]: (vm.get("desktop", desktop_default) or "")
            for vm in pending
        }
        for _name in deployed:
            desktop_map.setdefault(_name, desktop_default)
        desktop = next((d for d in desktop_map.values() if d), "")
        python_provider = spec.get("python_provider") or ""
        app_store = spec.get("app_store") or "deb"
        ai_agent = spec.get("ai_agent") or ""
        # Outils de développement : cochés une fois pour tout le parc, puis
        # filtrés machine par machine (architecture, saveur de bureau).
        vm_tools = tuple(spec.get("vm_tools") or ())
        # Branche par VM : « » sur une VM veut dire « celle du formulaire ».
        branch_map = {
            vm["name"]: (vm.get("branch") or install_branch or "")
            for vm in pending
        }
        for _n in deployed:
            branch_map.setdefault(_n, install_branch or "")
        branch_multi = self._qemu_per_vm(branch_map, install_branch or "")
        base_cmd = install["cmd"] if install else None
        cmd_map = {
            vm["name"]: (vm.get("install_cmd") or base_cmd) for vm in pending
        }
        for _n in deployed:
            cmd_map.setdefault(_n, base_cmd)
        cmd_multi = self._qemu_per_vm(cmd_map, base_cmd)
        ssh_key = spec.get("ssh_key")
        add_ssh_config = spec["add_ssh_config"]
        parallelism = spec["parallelism"]
        n_jobs = len(pending)

        # Le fichier de règles vit exactement le temps du déploiement :
        # il porte les adresses internes du site, et il est retiré même
        # si le parc s'arrête au milieu. Vide quand la posture n'attend
        # rien, ce qui est le cas de la plupart des déploiements.
        egress_pose = EgressFiles("", "")
        with self._qemu_egress_file(spec) as egress:
            egress_pose = egress
            # Jobs numérotés (k/N) : l'ID suit l'ORDRE de
            # préparation, stable même si les résultats reviennent
            # dans le désordre (exécution parallèle).
            jobs = []  # (id, name, parts)
            for k, vm in enumerate(pending, 1):
                parts = self._qemu_deploy_parts_for(
                    vm, spec, dry_run=False, egress=egress
                )
                jobs.append((f"{k}/{n_jobs}", vm["name"], parts))

            deploy_start = time.time()
            n_ok = 0
            if jobs:
                workers = min(parallelism, len(jobs))
                print(
                    f"\n{t('Deploying')} {len(jobs)} VM "
                    f"({t('parallel jobs:')} {workers})…"
                )
                if todo_prefs.get("qemu_deploy_progress") == "tui":
                    outcome = self._qemu_deploy_jobs_tui(jobs, workers)
                else:
                    outcome = None
                if outcome is None:
                    outcome = self._qemu_deploy_jobs_cli(jobs, workers)
                for name, rc, _out, _secs in outcome:
                    if rc == 0:
                        deployed.append(name)
                        n_ok += 1
                print(
                    f"\n{t('Deploy summary:')} {n_ok} OK, "
                    f"{len(jobs) - n_ok} {t('failed')}, "
                    f"{len(jobs)} {t('VMs')}, "
                    f"{self._fmt_dur(time.time() - deploy_start)}"
                )

        # 6) Résolution des IP EN PARALLÈLE (réutilisée pour ssh_config +
        # install) : une boucle EN SÉRIE bloquait plusieurs minutes par VM
        # émulée SANS sortie -> le dashboard « n'ouvrait jamais ».
        ip_map = {}
        # `desktop` compte aussi : sans IP résolue, l'installation du bureau
        # n'aurait aucune VM à joindre.
        # Les règles posées se RELISENT, donc l'adresse est nécessaire même
        # quand rien d'autre ne la demandait : sans elle, la relecture ne
        # joindrait aucune VM et rendrait un silence pour tout le parc.
        if deployed and (
            add_ssh_config or install_branch or desktop or egress_pose.rules
        ):
            labels = {
                nm: f"{k}/{len(deployed)}" for k, nm in enumerate(deployed, 1)
            }
            ip_map = self._qemu_resolve_ips(deployed, labels)

        if add_ssh_config:
            # La clé injectée par cloud-init est celle de la spec : c'est
            # elle que doit présenter ssh, pas la première venue de l'agent.
            identity = self._ssh_private_key(ssh_key)
            for name in deployed:
                ip = ip_map.get(name)
                if ip:
                    self._write_ssh_config_entry(
                        name,
                        "erplibre",
                        ip,
                        identity_file=identity,
                        forwards=self._qemu_ssh_forwards(spec, name),
                    )

        # Ce sur quoi la suite a le droit de poser, distinct de ce qui a
        # été déployé : le sommaire final compte le second, et une machine
        # écartée reste une machine déployée.
        a_installer = list(deployed)

        # 6 bis) Relecture des règles posées. Après la résolution des IP,
        # parce qu'elle en a besoin, et avant l'installation : une machine
        # qui n'a pas chargé ses règles doit se voir AVANT qu'on y pose
        # quoi que ce soit.
        if egress_pose.rules and deployed:
            releve = self._qemu_probe_egress(deployed, ip_map)
            if releve.unconfined:
                # RIEN ne se pose sur une machine qui devait être confinée
                # et ne l'est pas. Elle existe, elle est jointe, et c'est
                # justement pourquoi continuer l'installerait derrière une
                # promesse que la machine ne tient pas. Elle est écartée
                # une par une : les autres ont chargé leurs règles et n'ont
                # pas à payer pour elle.
                print(
                    f"\n⛔ {t('Withheld: egress rules did not hold on')}"
                    f" {', '.join(releve.unconfined)}"
                )
                print(f"   {t('Nothing is installed there.')}")
                a_installer = self._egress_keep(a_installer, releve.unconfined)

        # 7) Installation ERPLibre (clone + make) et/ou bureau GNOME. Le bureau
        # ne dépend PAS d'ERPLibre : une VM peut être voulue graphique et nue.
        # Il passe par la même commande distante, donc par le même suivi.
        #
        # Et quand il n'y a RIEN à installer, le suivi s'ouvre quand même : la
        # commande distante regarde alors la VM arriver (cloud-init puis relevé
        # système). Sans cela, décocher ERPLibre faisait disparaître le tableau
        # de bord — rapporté, et c'est ce qui donnait « le suivi ne fonctionne
        # plus ». Le choix vient du déploiement, pas de l'installation.
        monitor = install["monitor"] if install else spec.get("monitor", True)
        # Hors ligne, le suivi est d'office : seule sa voie confie la levée de
        # la coupure au guet, qui la tient jusqu'à la fin de la dernière
        # installation. Sans lui, la voie synchrone n'a aucun guet, et une spec
        # sans rien à installer lèverait la coupure dès les IP connues, avant
        # que cloud-init et l'agent invité aient fini de télécharger.
        if spec.get("offline"):
            monitor = True
        if install or desktop or monitor:
            if monitor:
                # Installs détachées en parallèle + dashboard Textual.
                self._qemu_install_erplibre_monitored(
                    a_installer,
                    branch_map if branch_multi else install_branch,
                    ip_map,
                    cmd_map if cmd_multi else base_cmd,
                    install["prod"] if install else False,
                    desktop=desktop_map,
                    python_provider=python_provider,
                    app_store=app_store,
                    vm_tools=vm_tools,
                    ai_agent=ai_agent,
                    guet_hors_ligne=coupee,
                    deploy_started=deploy_start,
                    # La coupure TENUE, et non la case de la spec : c'est
                    # elle qui fait qu'une réussite prouve le hors ligne.
                    hors_ligne=bool(coupee),
                )
            elif install:
                print(
                    f"\n{t('Installing ERPLibre on each VM')} "
                    f"({install_branch})…"
                )
                for name in a_installer:
                    self._qemu_install_erplibre_vm(
                        name,
                        ssh_key,
                        install_branch,
                        ip_map.get(name),
                        install["cmd"],
                        install["prod"],
                        desktop=desktop_map.get(name, ""),
                        python_provider=python_provider,
                        app_store=app_store,
                        vm_tools=vm_tools,
                        ai_agent=ai_agent,
                    )

        # Sommaire TOTAL (déploiement + résolution IP + ssh_config + install
        # synchrone ; l'install monitorée est détachée, non comptée ici).
        print(f"\n{'═' * 60}")
        print(f"  {t('TOTAL summary')}")
        print(
            f"  {t('VMs deployed:')} {n_ok}/{len(jobs) if jobs else 0}"
            f"  ({t('total incl. existing:')} {len(deployed)})"
        )
        print(
            f"  {t('Total time:')} {self._fmt_dur(time.time() - deploy_start)}"
        )
        print(f"{'═' * 60}")
        print(f"\n✅ {t('ERPLibre infra deployment done.')}")
        print(f"   {t('Default login:')} erplibre / erplibre")
        # PAR LE CONSTRUCTEUR : sans « --connect », un virsh non root vise
        # qemu:///session, où aucune VM du système n'existe. La commande
        # conseillée rendait donc une liste vide, sans erreur ni
        # avertissement, à qui venait d'en déployer plusieurs.
        print(f"   {t('Manage with:')} {virsh_cmd('list --all')}")
