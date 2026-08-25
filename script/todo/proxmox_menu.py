#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu Proxmox VE : déployer et gérer des VM sur un hôte DISTANT.

Sorti de todo.py, qui passait 13 000 lignes. Toute la différence avec le menu
QEMU/KVM tient en une phrase : l'hyperviseur est ailleurs. On choisit donc
l'hôte, on le vérifie, et tout part par SSH — voir script/proxmox/README.md.

Mixin : ses méthodes vivent sur la classe TODO, elles peuvent donc appeler
librement les helpers généraux (self._is_yes, self.fill_help_info) et ceux du
menu QEMU (self._qemu_prompt_distro, self._qemu_install_erplibre_monitored),
qu'elles réutilisent volontairement plutôt que de les redire."""

import os
import re
import shlex
import subprocess
import time

import click

from script.todo import todo_prefs
from script.todo.todo_i18n import t


class ProxmoxMenuMixin:
    """Menu Proxmox VE : déployer et gérer des VM sur un hôte DISTANT."""

    # ------------------------------------------------------------------ #
    # QEMU / KVM (libvirt) VM deployment
    # ------------------------------------------------------------------ #
    # ----------------------------------------------------------------- #
    # Proxmox VE : l'hyperviseur est AILLEURS
    # ----------------------------------------------------------------- #
    # Toute la différence avec QEMU/KVM tient là : ici on n'exécute rien sur
    # la machine locale. Il faut donc d'abord SAVOIR OÙ, et le retenir — sans
    # quoi chacune des dix-sept commandes reposerait la question.
    _PVE_PREF_KEY = "proxmox_host"
    # Le script qui transforme une Debian en hyperviseur. Autonome : il se
    # laisse exécuter par un tube, sans être copié d'abord.
    PVE_INSTALL_SCRIPT = "script/proxmox/install_proxmox.sh"

    def _pve_host(self, ask=True):
        """Hôte Proxmox retenu, ou None. Demande au besoin.

        Mémorisé dans les préférences : le menu compte dix-sept entrées, et
        redemander l'hôte à chacune serait insupportable. Le choix reste
        affiché en tête du menu, et se change par son entrée dédiée.
        """
        cache = getattr(self, "_pve_host_cache", None)
        if cache:
            return cache
        garde = todo_prefs.get(self._PVE_PREF_KEY) or {}
        if garde.get("target"):
            self._pve_host_cache = garde
            return garde
        return self._pve_pick_host() if ask else None

    def _pve_forget_host(self):
        self._pve_host_cache = None
        todo_prefs.set(self._PVE_PREF_KEY, {})

    def _pve_remember_host(self, host):
        self._pve_host_cache = host
        todo_prefs.set(self._PVE_PREF_KEY, host)

    @staticmethod
    def _pve_label(host):
        """« root@10.0.0.5 (par rebond) », pour l'afficher en tête de menu."""
        if not host:
            return ""
        lab = host.get("target", "?")
        if host.get("jump"):
            lab += f" ({t('through')} {host['jump']})"
        if host.get("version"):
            lab += f" — PVE {host['version']}"
        return lab

    def _pve_pick_host(self):
        """Choisit l'hôte Proxmox : VM locale, adresse, ou ~/.ssh/config."""
        print(f"\n{t('Which Proxmox host?')}")
        print(f"  [1] {t('From the local QEMU VMs')}")
        print(f"  [2] {t('Type an address')}")
        print(f"  [3] {t('From ~/.ssh/config')}")
        actuel = todo_prefs.get(self._PVE_PREF_KEY) or {}
        if actuel.get("target"):
            print(f"  [4] {t('Keep')} : {self._pve_label(actuel)}")
        choix = input(t("Choice: ")).strip()
        if choix == "4" and actuel.get("target"):
            self._pve_host_cache = actuel
            return actuel
        if choix == "1":
            host = self._pve_host_from_qemu()
        elif choix == "3":
            host = self._pve_host_from_ssh_config()
        elif choix == "2":
            host = self._pve_host_manual()
        else:
            print(t("Cancelled."))
            return None
        if not host:
            return None
        return self._pve_confirm_host(host)

    def _pve_host_manual(self):
        """Saisie libre. « root@ » par défaut : « qm » exige les privilèges."""
        brut = input(t("Address (user@host, default user root): ")).strip()
        if not brut:
            print(t("Cancelled."))
            return None
        cible = brut if "@" in brut else f"root@{brut}"
        jump = input(t("SSH jump host (blank = none): ")).strip()
        return {"target": cible, "jump": jump}

    def _pve_host_from_qemu(self):
        """Une VM Proxmox déployée ICI, prise dans la liste libvirt.

        C'est le cas du parc : on déploie une VM « proxmox » avec le menu
        QEMU/KVM, puis on déploie DEDANS. L'IP est celle du bail DHCP, pas une
        adresse à retaper.
        """
        noms = self._qemu_list_domains()
        if not noms:
            print(f"\n{t('No VM found.')}")
            return None
        print(f"\n{t('Local VMs:')}")
        ips = {}
        for i, nom in enumerate(noms, 1):
            ip = self._qemu_vm_ip_now(nom) or ""
            ips[nom] = ip
            etat = self._qemu_domstate(nom)
            print(f"  [{i}] {nom:<32} {ip or '-':<16} {etat}")
        sel = input(t("Selection (number): ")).strip()
        if not sel.isdigit() or not 1 <= int(sel) <= len(noms):
            print(t("Invalid selection!"))
            return None
        nom = noms[int(sel) - 1]
        ip = ips.get(nom)
        if not ip:
            print(f"  ⚠ {t('No IP for this VM: is it running?')}")
            return None
        return {"target": f"root@{ip}", "jump": "", "vm": nom}

    def _pve_host_from_ssh_config(self):
        """Un alias de ~/.ssh/config : il porte déjà utilisateur, port et
        ProxyJump — rien à redemander, et le rebond traverse."""
        entrees = self._ssh_config_entries(os.path.expanduser("~/.ssh/config"))
        if not entrees:
            print(f"\n{t('No SSH hosts found in ~/.ssh/config')}")
            return None
        print()
        for i, (nom, info) in enumerate(entrees, 1):
            hn = info.get("hostname", nom)
            u = info.get("user", "")
            desc = nom + (f" ({hn})" if hn != nom else "")
            print(f"  [{i}] {desc}{f' [{u}]' if u else ''}")
        sel = input(t("Select SSH host number: ")).strip()
        if not sel.isdigit() or not 1 <= int(sel) <= len(entrees):
            print(t("Invalid selection!"))
            return None
        alias = entrees[int(sel) - 1][0]
        # L'alias SEUL : ssh y lira l'utilisateur, le port et le ProxyJump.
        return {"target": alias, "jump": ""}

    @staticmethod
    def _pve_hostkey_missing(sortie):
        """La sortie de ssh dénonce-t-elle une clé d'hôte inconnue ou changée ?"""
        bas = (sortie or "").lower()
        return (
            "host key verification failed" in bas
            or "authenticity of host" in bas
            or "no ed25519 host key is known" in bas
        )

    @staticmethod
    def _pve_clean_output(sortie):
        """Les lignes de la sortie qui APPRENNENT quelque chose.

        « Warning: Permanently added … to the list of known hosts » arrive sur
        stderr à chaque connexion d'un hôte en UserKnownHostsFile=/dev/null.
        Affichée comme preuve d'un échec, elle envoyait chercher du côté de la
        clé d'hôte un problème qui n'avait rien à voir — rapporté.
        """
        gardees = []
        for ligne in (sortie or "").splitlines():
            nue = ligne.strip()
            if not nue or nue.startswith("Warning: Permanently added"):
                continue
            gardees.append(nue)
        return gardees

    def _pve_ssh_alive(self, host):
        """(ssh passe-t-il ?, ce qu'il a dit) — sans rien exiger de la machine.

        C'est la question qu'il fallait poser AVANT de conclure : une machine
        qui répond mais n'a pas Proxmox n'est pas « injoignable », et les deux
        pannes ne se corrigent pas du même côté."""
        from script.proxmox import proxmox_deploy as pve

        code, out = pve.run(host, "true", timeout=20)
        lignes = self._pve_clean_output(out)
        return code == 0, (lignes[0] if lignes else t("no answer"))

    def _pve_install_hint(self, host):
        """La commande qui poserait Proxmox VE sur cette machine.

        Le script du dépôt, poussé par le tube : il est autonome, donc
        « bash -s » suffit et il n'y a rien à copier d'abord."""
        return (
            f"cat {self.PVE_INSTALL_SCRIPT} | "
            f"ssh {host['target']} sudo bash -s"
        )

    def _pve_add_hostkey(self, host):
        """Enregistre la clé d'hôte, après accord explicite.

        ssh-keyscan et non « StrictHostKeyChecking=no » : la clé est écrite
        UNE fois dans known_hosts, et toute substitution ultérieure sera
        détectée. Désactiver la vérification l'aurait masquée pour toujours.
        """
        cible = host["target"].split("@")[-1]
        # Un alias de ~/.ssh/config n'est pas un nom de machine : ssh seul sait
        # vers quoi il pointe.
        resolu = self._ssh_resolve(host["target"])
        nom = resolu.get("hostname") or cible
        port = resolu.get("port") or host.get("port") or "22"
        print(f"\n  ⚠ {t('SSH does not know this host key yet.')}")
        print(f"  {t('Would record:')} ssh-keyscan -p {port} {nom}")
        if not self._is_yes(input(f"  {t('Record it?')} (o/N) : ")):
            return False
        try:
            res = subprocess.run(
                ["ssh-keyscan", "-p", str(port), nom],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  ✗ ssh-keyscan : {exc}")
            return False
        if res.returncode != 0 or not res.stdout.strip():
            print(f"  ✗ {t('No host key obtained.')}")
            return False
        chemin = os.path.expanduser("~/.ssh/known_hosts")
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "a", encoding="utf-8") as fh:
            fh.write(
                res.stdout if res.stdout.endswith("\n") else res.stdout + "\n"
            )
        lignes = len(res.stdout.strip().splitlines())
        print(f"  ✓ {lignes} {t('key(s) recorded in ~/.ssh/known_hosts')}")
        return True

    def _pve_confirm_host(self, host):
        """Vérifie que c'en est un, et le retient. Sinon, dit ce qu'il a vu.

        « pveversion » est la preuve : une adresse saisie à la main peut être
        n'importe quelle machine, et sans ce contrôle la première commande
        « qm » échouerait sur un « command not found » qui n'explique rien.
        """
        from script.proxmox import proxmox_deploy as pve

        print(f"\n  {t('Checking')} {host['target']}…")
        code, out = pve.run(host, "pveversion", timeout=30)
        version = pve.parse_pveversion(out)
        if not version and self._pve_hostkey_missing(out):
            # Première connexion : ssh refuse un hôte dont il n'a pas la clé.
            # On ne DÉSACTIVE pas la vérification — un hyperviseur n'est pas
            # une VM jetable — on propose de l'enregistrer, une fois.
            if self._pve_add_hostkey(host):
                code, out = pve.run(host, "pveversion", timeout=30)
                version = pve.parse_pveversion(out)
        if not version:
            # Un seul message confondait deux pannes : « ou il est
            # injoignable » envoyait vérifier le réseau alors que la machine
            # répondait, et la seule ligne montrée était l'avertissement de
            # ssh sur la clé d'hôte. On demande donc à ssh s'il passe.
            joignable, detail = self._pve_ssh_alive(host)
            # Ce que « pveversion » a répondu, et non ce que la sonde a dit :
            # « command not found » est LA preuve utile.
            dit = self._pve_clean_output(out)
            if joignable:
                print(f"  ✗ {t('Reachable, but Proxmox VE is not there:')}")
                print(
                    f"    ssh {host['target']} : ok — pveversion : "
                    f"{dit[0] if dit else t('absent')}"
                )
                print(f"  → {t('Install it:')}")
                print(f"    {self._pve_install_hint(host)}")
                print(
                    f"  → {t('Or redeploy the VM with the hypervisor profile.')}"
                )
            else:
                print(f"  ✗ {t('SSH does not get through:')}")
                print(f"    {detail}")
                print(
                    f"  → {t('Check the address, the SSH access and pveversion.')}"
                )
            return None
        # « qm » exige les privilèges. La voie « VM QEMU locale » donne
        # l'accès d'erplibre, pas de root : il faut donc sudo, et il faut le
        # VÉRIFIER — un sudo qui réclame un mot de passe bloquerait chaque
        # commande du menu sur une invite que personne ne voit.
        prefixe = ""
        _c, qui = pve.run(host, "id -u", timeout=20)
        if qui.strip() != "0":
            code, _o = pve.run(host, "sudo -n true", timeout=20)
            if code:
                print(
                    f"  ✗ {t('qm needs root: no root, and sudo asks for a password.')}"
                )
                print(f"  → {t('Connect as root@, or allow NOPASSWD sudo.')}")
                return None
            prefixe = "sudo "
            print(f"  ✓ sudo")
        host = dict(host, version=version, sudo=prefixe)
        print(f"  ✓ Proxmox VE {version}")
        # Le noyau DÉCIDE de ce qui marche : sans le noyau Proxmox, ni module
        # bridge ni table NAT — donc aucun pont à créer et aucune VM à
        # démarrer. Vécu sur l'hôte d'essai, où ifupdown2 répondait
        # « Another instance of this program is already running » au lieu de
        # « Operation not supported ». On le dit ici, une fois, plutôt que de
        # laisser chercher.
        noyau = pve.parse_kernel(out)
        if noyau and "-pve" not in noyau:
            print(f"  ⚠ {t('Still on the distribution kernel:')} {noyau}")
            print(f"  → {t('Reboot the host: no bridge, no NAT until then.')}")
        self._pve_remember_host(host)
        return host

    # -- Exécution sur l'hôte ------------------------------------------ #
    def _pve_show(self, remote, timeout=120, quiet=False):
        """Exécute `remote` sur l'hôte Proxmox et montre ce qui a été lancé.

        La commande est AFFICHÉE avant sa sortie : c'est ce qui rend chaque
        étape rejouable à la main, et c'est ainsi que les pannes de ce module
        ont été diagnostiquées.
        """
        from script.proxmox import proxmox_deploy as pve

        host = self._pve_host()
        if not host:
            return 255, ""
        if not quiet:
            # La forme RÉELLEMENT envoyée, enrobage sudo compris : une
            # commande affichée doit pouvoir être recopiée telle quelle.
            reel = pve.wrap_privilege(remote, host.get("sudo") or "")
            print(f"\n{t('Will execute:')} ssh {host['target']} {reel}")
        code, out = pve.run(host, remote, timeout)
        if out.strip() and not quiet:
            print(out.rstrip())
        if code and not quiet:
            print(f"  ⚠ {t('exit code')} {code}")
        return code, out

    def _pve_vms(self):
        """[{vmid, name, status, …}] des VM de l'hôte, ou []."""
        from script.proxmox import proxmox_deploy as pve

        code, out = self._pve_show("qm list", quiet=True)
        return pve.parse_qm_list(out) if code == 0 else []

    def _pve_pick_vm(self, titre="", multiple=False):
        """Choisit une VM de l'hôte (numéro de la liste, jamais le VMID à
        retaper). Renvoie un dict, une liste si `multiple`, ou None."""
        vms = self._pve_vms()
        if not vms:
            print(f"\n{t('No VM on this Proxmox host.')}")
            return [] if multiple else None
        print(f"\n{titre or t('VMs on this host:')}")
        for i, vm in enumerate(vms, 1):
            print(f"  [{i}] {vm['vmid']:<6} {vm['name']:<28} {vm['status']}")
        if multiple:
            print(f"  [all] {t('select all')}")
        brut = input(t("Selection (number): ")).strip()
        if multiple:
            if brut.lower() in ("all", "*"):
                return vms
            choisis = []
            for jeton in re.split(r"[\s,]+", brut):
                if jeton.isdigit() and 1 <= int(jeton) <= len(vms):
                    choisis.append(vms[int(jeton) - 1])
            return choisis
        if brut.isdigit() and 1 <= int(brut) <= len(vms):
            return vms[int(brut) - 1]
        print(t("Invalid selection!"))
        return None

    # -- Les commandes du menu ----------------------------------------- #
    def _pve_list(self):
        """« qm list », mis en tableau avec le total."""
        vms = self._pve_vms()
        if not vms:
            print(f"\n{t('No VM on this Proxmox host.')}")
            return
        print(
            f"\n{'VMID':<7} {'Nom':<30} {'État':<10} {'RAM (Mo)':>9}"
            f" {'Disque':>10}"
        )
        print("─" * 70)
        for vm in vms:
            print(
                f"{vm['vmid']:<7} {vm['name'][:30]:<30} {vm['status']:<10}"
                f" {vm['mem']:>9} {vm['disk']:>10}"
            )
        actives = sum(1 for v in vms if v["status"] == "running")
        print(f"\n  {len(vms)} VM, {actives} {t('running')}")
        # Le pendant du sous-menu de QEMU/KVM : la liste est le bon endroit
        # pour agir sur ce qu'on vient de lire.
        print(f"\n  [1] {t('Change the state of one or more VMs')}")
        if input(t("Choice (blank = back): ")).strip() == "1":
            self._pve_change_state(vms)

    def _pve_change_state(self, vms=None):
        """Démarre ou éteint des VM de l'hôte, avec double validation.

        « shutdown » et non « stop » : on demande à l'invité de s'arrêter, ce
        qui laisse Odoo fermer ses connexions PostgreSQL. « stop » coupe le
        courant — il est offert en second, nommé pour ce qu'il est.
        """
        from script.proxmox import proxmox_deploy as pve

        vms = vms if vms is not None else self._pve_vms()
        if not vms:
            print(f"\n{t('No VM on this Proxmox host.')}")
            return
        print(f"\n{t('Available VMs:')}")
        for i, vm in enumerate(vms, 1):
            print(
                f"  [{i}] {vm['vmid']:<7} {vm['name'][:34]:<34} {vm['status']}"
            )
        print(f"  [all] {t('select all')}")
        brut = input(t("Selection (numbers, or 'all'): ")).strip().lower()
        if not brut:
            print(t("Nothing selected."))
            return
        if brut in ("all", "*"):
            choisies = list(vms)
        else:
            # Par RANG, jamais par nom : deux VM du même hôte peuvent
            # porter le même nom (seul le VMID est unique sur Proxmox), et
            # cocher l'une éteignait les deux.
            rangs = self._parse_index_selection(
                brut, [str(i) for i in range(1, len(vms) + 1)]
            )
            voulus = {int(r) for r in rangs if str(r).isdigit()}
            choisies = [vm for i, vm in enumerate(vms, 1) if i in voulus]
        if not choisies:
            print(t("Nothing selected."))
            return
        print(
            f"\n  [1] {t('start')}   [2] {t('shutdown (clean)')}"
            f"   [3] {t('stop (pulls the plug)')}"
        )
        geste = input(t("Choice: ")).strip()
        verbe = {"1": "start", "2": "shutdown", "3": "stop"}.get(geste)
        if not verbe:
            print(t("Cancelled."))
            return
        print(
            f"\n  {verbe} : "
            + ", ".join(f"{vm['name']} ({vm['vmid']})" for vm in choisies)
        )
        if not self._is_yes(input(t("Confirm? (y/N): "))):
            print(t("Cancelled."))
            return
        for vm in choisies:
            code, _o = self._pve_show(f"qm {verbe} {vm['vmid']}", timeout=300)
            marque = "✓" if code == 0 else "✗"
            print(f"  {marque} {vm['name']}")
        # L'état APRÈS : c'est la seule preuve que le geste a porté.
        _c, out = self._pve_show("qm list", quiet=True)
        for vm in pve.parse_qm_list(out):
            if any(vm["vmid"] == c["vmid"] for c in choisies):
                print(f"    {vm['name']:<34} {vm['status']}")

    def _pve_vm_ip(self):
        """Adresse d'une VM, par l'agent invité.

        Sans agent, Proxmox ne connaît PAS l'adresse de ses invités : il ne la
        distribue pas lui-même. Le dire vaut mieux qu'afficher « rien ».
        """
        vm = self._pve_pick_vm()
        if not vm:
            return
        # _pve_guest_ip et non l'agent seul : il enchaîne agent PUIS voisinage
        # de l'hôte. L'image cloud Debian n'embarque pas qemu-guest-agent, et
        # cette entrée du menu répondait « aucune adresse » alors que « ip
        # neigh » la connaissait — deux chemins pour la même question, dont un
        # seul savait répondre.
        ip = self._pve_guest_ip(vm["vmid"], attente=20)
        if ip:
            print(f"\n  {vm['name']} : {ip}")
            print(f"  ssh erplibre@{ip}")
            return
        print(f"\n  ⚠ {t('No address for this VM.')}")
        print(f"  → {t('Is qemu-guest-agent installed and the VM started?')}")
        print(f"  → {t('A static address is visible right after creation.')}")

    def _pve_console(self):
        """Console série d'une VM. Demande un terminal : on passe donc par
        l'exécuteur du dépôt, qui en a un."""
        from script.proxmox import proxmox_deploy as pve

        vm = self._pve_pick_vm()
        if not vm:
            return
        host = self._pve_host()
        if not host:
            return
        cmd = " ".join(
            shlex.quote(a)
            for a in pve.ssh_argv(
                host,
                pve.wrap_privilege(
                    pve.console_cmd(vm["vmid"]), host.get("sudo") or ""
                ),
                tty=True,
            )
        )
        print(f"\n  {t('Ctrl+O to quit the serial console.')}")
        print(f"\n{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _pve_resize(self):
        """Agrandit un disque. Proxmox REFUSE de rétrécir : on le dit avant."""
        from script.proxmox import proxmox_deploy as pve

        vm = self._pve_pick_vm()
        if not vm:
            return
        print(f"\n  ⚠ {t('Proxmox can only GROW a disk, never shrink it.')}")
        taille = input(t("Size (+10G to add, 40G for a target): ")).strip()
        if not re.match(r"^\+?\d+[MGT]$", taille):
            print(t("Invalid selection!"))
            return
        self._pve_show(pve.resize_cmd(vm["vmid"], taille))

    def _pve_delete(self):
        """Efface des VM, avec DOUBLE validation — « --purge » emporte les
        disques et les sauvegardes, il n'y a pas de retour."""
        from script.proxmox import proxmox_deploy as pve

        vms = self._pve_pick_vm(multiple=True)
        if not vms:
            return
        noms = ", ".join(f"{v['vmid']} ({v['name']})" for v in vms)
        print(f"\n  ⚠ {t('This also destroys their disks and backups.')}")
        if not self._is_yes(input(f"{t('Apply:')} {noms} ? (o/N) : ")):
            print(t("Cancelled."))
            return
        if not self._is_yes(input(t("Confirm for real? (y/N): "))):
            print(t("Cancelled."))
            return
        for vm in vms:
            for cmd in pve.destroy_cmds(vm["vmid"]):
                self._pve_show(cmd, timeout=300)

    def _pve_cleanup(self):
        """Volumes de disque qu'aucune VM ne réclame plus.

        Proxmox ne les efface pas de lui-même : une création interrompue ou un
        « destroy » sans « --purge » en laisse. On les liste et on demande.
        """
        from script.proxmox import proxmox_deploy as pve

        code, out = self._pve_show(pve.orphan_disks_cmd(), quiet=True)
        if code:
            print(f"\n  ⚠ {t('exit code')} {code}")
            return
        vmids = [v["vmid"] for v in self._pve_vms()]
        orphelins = pve.parse_orphans(out, vmids)
        if not orphelins:
            print(f"\n  ✓ {t('Nothing orphaned.')}")
            return
        total = sum(t2 for _v, t2 in orphelins)
        print(f"\n{t('Orphan disks:')}")
        for volid, taille in orphelins:
            print(f"  {volid:<48} {taille / (1 << 30):>8.1f} Go")
        print(f"  {t('Total:')} {total / (1 << 30):.1f} Go")
        if not self._is_yes(input(f"{t('Free them?')} (o/N) : ")):
            print(t("Cancelled."))
            return
        for volid, _taille in orphelins:
            self._pve_show(f"pvesm free {shlex.quote(volid)}", timeout=300)

    def _pve_guest_ip(self, vmid, attente=120):
        """Adresse d'une VM Proxmox : agent invité, sinon voisinage de l'hôte.

        Deux voies parce qu'aucune ne suffit seule. L'agent est le plus sûr,
        mais l'image cloud Debian ne l'embarque pas. Le voisinage (« ip neigh »
        sur l'hôte) marche dès que la VM a émis un paquet — un bail DHCP suffit
        — et ne demande RIEN à l'invité.
        """
        from script.proxmox import proxmox_deploy as pve

        fin = time.time() + attente
        mac = ""
        while True:
            code, out = self._pve_show(
                pve.guest_ip_cmd(vmid), timeout=30, quiet=True
            )
            ips = pve.parse_guest_ips(out) if code == 0 else []
            if ips:
                return ips[0]
            if not mac:
                _c, cfg = self._pve_show(
                    f"qm config {vmid}", timeout=30, quiet=True
                )
                mac = pve.mac_from_config(cfg)
            if mac:
                _c, neigh = self._pve_show(
                    "ip -4 neigh show", timeout=30, quiet=True
                )
                ip = pve.ip_from_neigh(neigh, mac)
                if ip:
                    return ip
            if time.time() >= fin:
                return ""
            time.sleep(5)

    def _pve_push_key(self, chemin_local):
        """Recopie la clé publique SUR l'hôte : « qm set --sshkeys » attend un
        FICHIER là-bas, pas une clé en ligne."""
        try:
            with open(
                os.path.expanduser(chemin_local), encoding="utf-8"
            ) as fh:
                cle = fh.read().strip()
        except OSError as exc:
            print(f"  ⚠ {t('SSH key unreadable:')} {exc}")
            return ""
        distant = "/root/.ssh/erplibre-deploy.pub"
        code, _out = self._pve_show(
            "mkdir -p /root/.ssh && printf '%s\\n' "
            f"{shlex.quote(cle)} > {distant}",
            quiet=True,
        )
        return distant if code == 0 else ""

    def _pve_uplink(self):
        """Interface qui porte la route par défaut, ou '' — la sortie du NAT.

        Sans elle, le pont interne existe mais ses VM ne voient pas Internet.
        """
        _c, sortie = self._pve_show("ip -o -4 route show default", quiet=True)
        parts = (sortie or "").split()
        return parts[parts.index("dev") + 1] if "dev" in parts else ""

    def _pve_make_internal_bridge(self):
        """Crée le pont INTERNE et le rend, ou ('', raison). SANS rien demander.

        Appelable depuis l'écran de déploiement, où Textual tient le terminal :
        aucune invite, aucune sortie imprimée, tout est capturé. C'est possible
        parce que ce pont ne touche AUCUNE interface physique — il n'y a donc
        rien à faire arbitrer. Un pont sur le LAN, lui, déplace l'adresse de
        l'hôte et coupe la session : il reste manuel, et l'écran le dit.
        """
        from script.proxmox import proxmox_deploy as pve

        host = self._pve_host(ask=False)
        if not host:
            return "", t("No Proxmox host.")
        uplink = self._pve_uplink()
        for cmd in pve.bridge_setup_cmds(uplink=uplink):
            code, sortie = pve.run(host, cmd, 180)
            if code:
                lignes = pve.strip_ssh_noise(sortie).strip().splitlines()
                return "", (lignes[-1] if lignes else t("Step failed"))
        _c, out = pve.run(host, "ip -o link show type bridge", 30)
        if pve.INTERNAL_BRIDGE not in pve.parse_bridges(out):
            return "", t("The bridge did not come up.")
        return pve.INTERNAL_BRIDGE, ""

    def _pve_offer_bridge(self):
        """Aucun pont sur l'hôte : en proposer un, sans risquer l'accès.

        Une Proxmox installée SUR Debian n'a pas de vmbr0 — l'ISO en crée un,
        pas la procédure sur Debian. Or « qm create » exige un pont.

        On ne propose donc PAS d'ajouter l'interface physique au pont : cela
        déplace l'adresse de la machine et coupe la session SSH en cours, sans
        retour possible à distance. Un pont INTERNE, lui, ne touche à rien —
        les VM s'y parlent, et le masquerading leur donne l'extérieur.
        """
        from script.proxmox import proxmox_deploy as pve

        print(f"\n  ⚠ {t('No network bridge on this host.')}")
        print(f"  {t('qm create needs one. Two ways:')}")
        print(
            f"  [1] {t('create an internal')} {pve.INTERNAL_BRIDGE}"
            f" ({pve.INTERNAL_CIDR}) + NAT — {t('touches no physical NIC')}"
        )
        print(f"  [2] {t('do it myself (bridge-ports <nic>, needs console)')}")
        if input(t("Choice: ")).strip() != "1":
            print(f"\n  {t('To bridge the LAN, on the host:')}")
            print("    auto vmbr0")
            print("    iface vmbr0 inet static")
            print("        address <ip-de-l-hôte>/24")
            print("        gateway <passerelle>")
            print("        bridge-ports <interface>")
            print(
                f"  ⚠ {t('This moves the host address: do it from a console.')}"
            )
            return ""
        uplink = self._pve_uplink()
        print(f"  {t('uplink for NAT')} : {uplink or t('none')}")
        for cmd in pve.bridge_setup_cmds(uplink=uplink):
            code, _o = self._pve_show(cmd, timeout=120)
            if code:
                print(f"  ✗ {t('Step failed, stopping here.')}")
                return ""
        _c, out = self._pve_show("ip -o link show type bridge", quiet=True)
        ponts = pve.parse_bridges(out)
        if pve.INTERNAL_BRIDGE not in ponts:
            print(f"  ✗ {t('The bridge did not come up.')}")
            return ""
        print(f"  ✓ {pve.INTERNAL_BRIDGE}")
        return pve.INTERNAL_BRIDGE

    def _pve_deploy(self, dry_run=False):
        """Déploie une ou plusieurs VM SUR l'hôte Proxmox choisi.

        L'écran d'abord, les invites en repli : c'est le même choix qu'en
        QEMU/KVM, et pour la même raison — un plan de plusieurs machines se
        vérifie d'un coup d'œil, pas en relisant vingt réponses déjà données.
        Sans terminal graphique (ou sur refus), on retombe sur les questions.
        """
        host = self._pve_host()
        if not host:
            return
        mod = self._qemu_import_module()
        try:
            from script.todo.proxmox_deploy_form import run_proxmox_form

            ctx = self._pve_form_context(mod, host)
            spec = run_proxmox_form(ctx)
        except ImportError as exc:
            print(f"  ⚠ {t('TUI unavailable')} : {exc}")
            spec = {}
        if spec is None:
            print(t("Cancelled."))
            return
        if spec:
            return self._pve_deploy_spec(host, spec, mod, dry_run)
        return self._pve_deploy_prompts(dry_run)

    def _pve_form_context(self, mod, host):
        """Tout ce que l'écran doit savoir, LU AVANT de l'ouvrir.

        Chaque lecture passe par ssh, et certaines par sudo : une invite de
        mot de passe pendant que Textual affiche casserait l'écran. On paie
        donc tout ici, une fois, terminal encore à nous.
        """
        from script.proxmox import proxmox_deploy as pve

        print(f"\n{t('Loading (host, storage, bridges, VMs)...')}")
        native = self._native_arch()
        arches = ["amd64", "arm64", "s390x"]
        if native not in arches:
            arches.insert(0, native)
        catalog = {}
        for a in arches:
            distros = list(mod.DISTROS)
            allowed = self._qemu_arch_distros(a)
            if allowed is not None:
                distros = [d for d in distros if d in allowed]
            entries = self._qemu_catalog_entries(mod, distros, a)
            for e in entries:
                e["name"] = self._qemu_infra_name(
                    e["distro"], e["version"], e["arch"]
                )
            catalog[a] = entries

        vms = self._pve_vms()
        _c, out = self._pve_show("pvesm status --content images", quiet=True)
        stockages = pve.parse_storages(out)
        _c, out = self._pve_show("ip -o link show type bridge", quiet=True)
        ponts = pve.parse_bridges(out)
        if not ponts:
            # Le terminal est encore à nous : c'est ICI qu'on peut poser la
            # question. L'écran sait aussi le faire, mais sans pouvoir
            # expliquer les deux voies ni montrer ce qu'il exécute.
            if self._pve_offer_bridge():
                _c, out = self._pve_show(
                    "ip -o link show type bridge", quiet=True
                )
                ponts = pve.parse_bridges(out)
        _c, cfg = self._pve_show("cat /etc/network/interfaces", quiet=True)
        infos = pve.parse_bridge_config(cfg)
        cpu, ram_libre = self._pve_capacity()
        # Le DNS de l'hôte, pour les VM en adresse fixe : sans lui elles
        # routent mais ne résolvent rien, et « apt update » échoue sans que
        # rien ne l'explique. Mesuré sur la VM d'essai.
        _c, resolv = self._pve_show(pve.RESOLV_CMD, quiet=True)
        serveurs_dns = pve.parse_nameservers(resolv)

        def ipconfig(pont, vmid):
            return pve.ipconfig_for(infos.get(pont, {}), vmid)

        def build_command(vm, spec):
            """Les commandes qui seraient lancées pour CETTE VM."""
            return self._pve_vm_commands(mod, vm, spec)

        return {
            "host": dict(host, label=self._pve_label(host)),
            "node": self._pve_node_name(),
            "catalog": catalog,
            "arches": arches,
            "native": native,
            "names": [v["name"] for v in vms if v.get("name")],
            "vmids": [v["vmid"] for v in vms],
            "next_vmid": pve.next_vmid(vms),
            "storages": [s["name"] for s in stockages if s.get("actif")],
            "storage": pve.pick_storage(stockages),
            # La place libre par stockage, en octets : « pvesm status » la
            # donne dans la même sortie, donc l'écran peut dire si le plan
            # rentre sans un aller-retour de plus vers l'hôte.
            "storage_avail": {
                s["name"]: s.get("avail") or 0 for s in stockages
            },
            "bridges": ponts,
            "bridge": pve.pick_bridge(ponts),
            "ipconfig": ipconfig,
            "nameservers": serveurs_dns,
            # De quoi créer le pont DEPUIS l'écran, sans invite : le pont
            # interne ne touche à aucune interface physique.
            "make_bridge": self._pve_make_internal_bridge,
            "internal_bridge": (pve.INTERNAL_BRIDGE, pve.INTERNAL_CIDR),
            "build_command": build_command,
            "branches": self._qemu_branch_list() or ["master"],
            # La branche du dépôt : c'est elle qu'on déploie le plus souvent.
            "branch_current": self._qemu_repo_branch(),
            "install_profiles": self._qemu_install_profiles(),
            # Type de VM, magasin d'applications, outils, fuseau,
            # interpréteur Python : les réglages du système INVITÉ, qui ne
            # regardent pas l'hyperviseur. Cet écran n'en portait que trois —
            # une VM créée ici naissait sans bureau, sans outils et en UTC.
            **self._qemu_guest_context(),
            # Même règle qu'en QEMU/KVM : un système peut IMPOSER ce qu'on
            # installe dessus. Un Proxmox imbriqué recevait sinon ERPLibre et
            # Odoo 18, comme l'écran d'à côté avant correction.
            "distro_profiles": {
                d: self._qemu_distro_profile(d)
                for d in self._QEMU_DISTRO_PROFILE
                if self._qemu_distro_profile(d)
            },
            "ssh_key": self._qemu_default_ssh_key(),
            "cpu_presets": self._QEMU_CPU_PRESETS,
            "ram_presets": self._QEMU_RAM_PRESETS,
            "disk_presets": self._QEMU_DISK_PRESETS,
            "base_vcpus": self._QEMU_BASE_VCPUS,
            # Les cœurs et la mémoire de L'HÔTE DISTANT : ceux d'ici ne
            # disent rien de ce qu'on peut y loger.
            "host_cpu": cpu,
            "free_ram": ram_libre,
            "extra_disk_gb": self.ERPLIBRE_EXTRA_DISK_GB,
        }

    def _pve_capacity(self):
        """(cœurs, Mo de RAM libre) de l'hôte, ou un repli prudent.

        Deux valeurs en une commande : le formulaire s'en sert pour borner les
        vCPU et pour prévenir quand le plan demande plus de mémoire que
        l'hôte n'en a de libre."""
        code, out = self._pve_show(
            "nproc; free -m | awk '/^Mem:/ {print $7}'", quiet=True
        )
        lignes = [x.strip() for x in (out or "").splitlines() if x.strip()]
        if code or len(lignes) < 2:
            return 2, 0
        cpu = int(lignes[0]) if lignes[0].isdigit() else 2
        libre = int(lignes[1]) if lignes[1].isdigit() else 0
        return cpu, libre

    def _pve_node_name(self):
        """Nom du nœud Proxmox, tel qu'il se nomme lui-même."""
        code, out = self._pve_show("hostname", quiet=True)
        return out.strip().splitlines()[0] if code == 0 and out.strip() else ""

    def _pve_disk_with_margin(self, vm, spec):
        """Taille du disque à créer : celle du plan, marge comprise.

        La même règle que la voie libvirt, qui ajoute ERPLIBRE_EXTRA_DISK_GB à
        la demande initiale quand ERPLibre s'installe. Ici la marge se perdait
        entre l'écran et « qm resize ».
        """
        from script.todo.deploy_form_extras import (
            extras_disk_gb,
            extras_tables,
        )

        demande = vm.get("disk") or ""
        gigs = self._parse_disk_gb(demande)
        if not gigs:
            return demande
        install = spec.get("install") or {}
        cmd = vm.get("install_cmd") or install.get("cmd") or ""
        marge = 0
        if self._qemu_installs_erplibre(install.get("branch"), cmd):
            marge += self.ERPLIBRE_EXTRA_DISK_GB
        # Le bureau et les outils pèsent aussi, et sur la VM QUI LES REÇOIT :
        # une VM ARM n'aura pas Android Studio, un serveur aucun des IDE. Le
        # plan les additionne déjà à l'écran ; sans eux ici, la VM naissait
        # avec le disque d'un serveur nu et GNOME le remplissait.
        marge += extras_disk_gb(
            dict(vm, desktop=vm.get("desktop") or spec.get("desktop") or ""),
            spec.get("vm_tools") or (),
            extras_tables(self._qemu_guest_context()),
        )
        return f"{gigs + marge}G" if marge else demande

    def _pve_vm_commands(self, mod, vm, spec):
        """Les commandes de création d'UNE VM, dans l'ordre : l'image puis
        « qm ». Sert à l'aperçu comme à l'exécution — un aperçu qui ne
        montrerait pas exactement ce qui va tourner ne servirait à rien."""
        from script.proxmox import proxmox_deploy as pve

        code, _v = mod.DISTROS[vm["distro"]][0][vm["version"]][:2]
        url = mod.image_url(vm["distro"], code, vm["arch"], vm["version"])
        image = mod.default_image_name(
            vm["distro"], code, vm["arch"], vm["version"]
        )
        detail = {
            "name": vm["name"],
            "memory": vm["ram"],
            "vcpus": vm["vcpus"],
            # La MARGE d'ERPLibre entre dans la taille réellement créée : le
            # plan l'annonçait (« 25G » pour un catalogue à 20 G) et « qm
            # resize » recevait 20 G. La VM naissait cinq gigaoctets trop
            # petite pour ce qu'on venait de lui promettre — trouvé par
            # l'audit, pas à l'usage.
            "disk": self._pve_disk_with_margin(vm, spec),
            "storage": spec["storage"],
            "bridge": spec["bridge"],
            "image": image,
            "user": spec.get("user") or "erplibre",
            "start": spec.get("start", True),
            "ipconfig": vm.get("ipconfig") or "ip=dhcp",
            # Le DNS de l'hôte : « --ipconfig0 » ne le porte pas, et une VM
            # en adresse fixe se retrouvait sans résolveur.
            "nameservers": spec.get("nameservers") or (),
        }
        if spec.get("sshkey_path"):
            detail["sshkey_path"] = spec["sshkey_path"]
        return [pve.image_fetch_cmd(url, image)] + pve.create_cmds(
            vm["vmid"], detail
        )

    def _pve_deploy_spec(self, host, spec, mod, dry_run=False):
        """Exécute la spec rendue par l'écran.

        Les images D'ABORD, une par une : deux téléchargements simultanés du
        même fichier se marcheraient dessus. Les VM ensuite, en parallèle si
        on l'a demandé — chacune est une suite « qm » indépendante.
        """
        from script.proxmox import proxmox_deploy as pve
        from script.todo.deploy_form_lib import run_deploy_progress

        # Le stockage et le pont AVANT tout : l'écran les vérifie déjà, mais
        # cette méthode s'appelle aussi d'ailleurs. Sans ce garde-fou, on
        # téléchargeait 350 Mio d'image pour finir sur « net0: invalid format
        # - missing key » — vécu sur l'hôte d'essai.
        for valeur, message in (
            (spec.get("storage"), t("No storage able to hold a VM disk.")),
            (spec.get("bridge"), t("No bridge on the host.")),
        ):
            if not valeur:
                print(f"\n  ✗ {message}")
                return
        if not dry_run and not self._pve_confirm_spec(host, spec):
            print(t("Cancelled."))
            return
        cle_locale = spec.get("ssh_key") or self._qemu_default_ssh_key()
        if cle_locale and not dry_run:
            if self._pve_push_key(cle_locale):
                spec["sshkey_path"] = "/root/.ssh/erplibre-deploy.pub"
            else:
                print(f"  ⚠ {t('SSH key not pushed: password login only.')}")
        travaux, commandes = [], {}
        for vm in spec["vms"]:
            cmds = self._pve_vm_commands(mod, vm, spec)
            commandes[vm["name"]] = cmds
            if dry_run:
                print(f"\n── {vm['name']} ({t('VMID')} {vm['vmid']}) ──")
                for cmd in cmds:
                    print(f"  {cmd}")
                continue
            # UNE seule commande distante par VM : l'enchaînement par « && »
            # s'arrête à la première étape qui cède, et le journal de la VM
            # porte toute sa création.
            remote = " && ".join(cmds)
            travaux.append(
                (
                    vm["name"],
                    vm["name"],
                    pve.ssh_argv(
                        host,
                        pve.wrap_privilege(remote, host.get("sudo") or ""),
                    ),
                )
            )
        if dry_run:
            return
        if spec["existing"]:
            print(f"  ⏭ {t('already there')} : {', '.join(spec['existing'])}")
        if not travaux:
            return
        # Le journal AVANT de lancer : la vue de progression se referme et
        # emporte tout ce qu'elle montrait. Rapporté — « il manque plein
        # d'informations qu'il y avait avant, où est le fichier de log ? ».
        # L'ancienne voie par questions imprimait chaque commande et sa
        # sortie ; celle-ci les écrit, ce qui vaut mieux qu'un défilement.
        session = self._pve_log_dir()
        print(f"\n  {t('Log:')} {session}")
        # Comment joindre chaque VM SANS dépendre de ~/.ssh/config, qui n'est
        # écrit qu'après : par le rebond de l'hôte, explicitement. C'est ce que
        # « s » utilise dans la vue de progression — sans quoi il partait sur
        # le nom de la VM, donc sur une locale homonyme (rapporté).
        cibles_ssh = {}
        for vm in spec["vms"]:
            ip = pve.ip_from_ipconfig(vm.get("ipconfig") or "")
            if ip:
                compte = (spec.get("user") or "erplibre") + "@" + ip
                cibles_ssh[vm["name"]] = (
                    f"ssh -J {shlex.quote(host['target'])} "
                    f"{shlex.quote(compte)}"
                )
        # Ce qui attend derrière cet écran : sans le dire, on reste devant
        # une fenêtre « terminée » sans savoir que l'installation d'ERPLibre
        # démarre en la quittant.
        suite = ""
        if spec.get("install"):
            suite = t("Quit (q) to start the ERPLibre install")
        elif spec.get("monitor", True):
            suite = t("Quit (q) to follow the VM starting up")
        resultats = run_deploy_progress(
            travaux,
            spec.get("parallelism") or 1,
            ssh_cmds=cibles_ssh,
            suite=suite,
        )
        reussies = [nom for nom, code, _o, _d in resultats if code == 0]
        for nom, code, sortie, duree in resultats:
            chemin = self._pve_write_log(
                session,
                nom,
                spec,
                commandes.get(nom) or [],
                code,
                sortie,
                duree,
            )
            marque = "✓" if code == 0 else "✗"
            print(f"  {marque} {nom} : {chemin}")
            if code:
                print(f"    {t('exit code')} {code}")
                # Les dernières lignes à l'écran, le reste dans le journal :
                # c'est l'échec qu'on veut lire tout de suite.
                propre = pve.collapse_progress(pve.strip_ssh_noise(sortie))
                for ligne in propre.rstrip().splitlines()[-12:]:
                    print(f"    {ligne}")
        if not reussies:
            return
        joignables = self._pve_after_create(host, spec, reussies, cle_locale)
        self._pve_print_summary(spec, joignables or [], session)

    @staticmethod
    def _pve_log_dir():
        """Répertoire de journaux de CE déploiement, créé au besoin.

        Même esprit que ~/.erplibre/qemu-install : une session par
        déploiement, un fichier par VM. La vue de progression se referme ; le
        journal reste, et c'est lui qu'on relit quand une étape a cédé."""
        session = os.path.join(
            os.path.expanduser("~/.erplibre/proxmox-deploy"),
            time.strftime("%Y%m%d-%H%M%S"),
        )
        os.makedirs(session, exist_ok=True)
        return session

    @staticmethod
    def _pve_write_log(session, nom, spec, cmds, code, sortie, duree):
        """Écrit le journal d'UNE VM et rend son chemin.

        Les commandes AVANT leur sortie : c'est ce qui rend l'étape rejouable
        à la main, et c'est ainsi que les pannes de ce module ont été
        diagnostiquées."""
        from script.proxmox import proxmox_deploy as pve

        chemin = os.path.join(session, f"{nom}.log")
        hote = (spec.get("host") or {}).get("target", "?")
        vm = next((v for v in spec.get("vms") or [] if v["name"] == nom), {})
        entete = [
            "=" * 64,
            "  ERPLibre — création d'une VM sur Proxmox VE",
            f"  Date      : {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  VM        : {nom}   VMID {vm.get('vmid', '?')}",
            f"  Hôte      : {hote}",
            f"  Stockage  : {spec.get('storage')}   "
            f"{t('bridge')} : {spec.get('bridge')}",
            f"  Adresse   : {(vm.get('ipconfig') or '').replace('ip=', '')}",
            f"  Ressources: {vm.get('vcpus', '?')} vCPU  "
            f"{vm.get('ram', '?')} Mo  {vm.get('disk', '?')}",
            "=" * 64,
            "",
            "---- commandes ----",
        ]
        entete += [f"  {c}" for c in cmds]
        propre = pve.collapse_progress(pve.strip_ssh_noise(sortie or ""))
        entete += ["", "---- sortie ----", propre.rstrip(), ""]
        entete += [
            (
                f"---- fin : code {code}, {duree:.0f} s ----"
                if isinstance(duree, (int, float))
                else f"---- fin : code {code} ----"
            )
        ]
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write("\n".join(entete) + "\n")
        return chemin

    def _pve_alias_names(self, nom, chaine, locaux=(), rebond=""):
        """UN seul nom pour l'entrée ~/.ssh/config : « hôte+vm ».

        Deux noms sur la même ligne « Host » — le chaîné et le court —
        étaient un doublon : ssh n'a besoin que d'un nom, et le second
        n'ajoutait qu'une façon de plus d'écrire la même adresse. Rapporté.

        Reste à choisir lequel, et c'est le chaîné. Prendre le nom court
        quand il se trouvait libre donnait un parc INCOHÉRENT : sur un même
        déploiement, deux VM recevaient « hôte+vm » — leurs noms étaient pris
        par des domaines locaux — et la troisième son nom court. Rapporté
        aussi. Une convention qui dépend de ce qui traîne dans le fichier
        n'est pas une convention.

        Le chaîné est donc systématique. Il dit où la machine vit, il ne peut
        rien voler à un domaine local, et deux VM du même nom sur deux hôtes
        Proxmox différents se distinguent d'elles-mêmes.

        Rend (noms, volé) — la seconde valeur reste pour l'appelant, qui
        signale au passage un nom qu'une VM locale porte aussi."""
        return [chaine], (t("a local VM") if nom in locaux else "")

    def _pve_set_timezone(self, cible, spec):
        """Pose le fuseau DANS la VM, par ssh.

        La voie libvirt le donne à cloud-init, qui écrit /etc/timezone au
        premier démarrage. « qm set » n'a pas d'équivalent : le cloud-init de
        Proxmox ne règle que l'utilisateur, la clé et le réseau. Une VM créée
        ici restait donc en UTC — et on ne s'en aperçoit qu'aux horodatages,
        parfois des jours plus tard.

        AVANT l'installation, pour que le journal porte déjà la bonne heure.
        Un nom IANA, jamais un décalage : « UTC-5 » ne dit rien de l'heure
        d'été, et timedatectl le refuse.
        """
        fuseau = (spec.get("timezone") or "").strip()
        if not fuseau:
            return False
        code, sortie = self._pve_ssh(
            cible, f"sudo timedatectl set-timezone {shlex.quote(fuseau)}"
        )
        if code:
            # Nommé et non tu : la VM reste en UTC, et c'est une surprise
            # qu'on veut avoir maintenant plutôt qu'au premier journal.
            print(f"  ⚠ {t('timezone not set')} : {fuseau} ({code})")
            return False
        print(f"  ✓ {t('Timezone')} : {fuseau}")
        return True

    def _pve_write_guide(self, cible, vm, spec, mod):
        """Pose le guide de connexion et l'identité git DANS la VM.

        La voie libvirt les livre par le « write_files » de cloud-init ;
        « qm set » n'offre pas cela, donc une VM Proxmox n'avait AUCUN guide —
        quelle que soit sa distribution. Rapporté sur Arch.

        Même contenu, livrée par ssh une fois la VM debout : `guide_files` est
        la source unique, comme sa docstring le promet. Un seul appel, tous les
        fichiers.
        """
        import types

        from script.todo.todo_i18n import get_lang

        install = spec.get("install") or {}
        cmd_install = vm.get("install_cmd") or install.get("cmd") or ""
        args = types.SimpleNamespace(
            distro=vm.get("distro") or "",
            version=vm.get("version") or "",
            arch=vm.get("arch") or "amd64",
            lang=get_lang(),
            # La section ERPLibre n'apparaît que si ERPLibre y sera : un guide
            # qui annonce un dépôt absent est un guide qui ment.
            erplibre_dir=(
                self._qemu_guide_dir(False)
                if self._qemu_installs_erplibre(
                    install.get("branch"), cmd_install
                )
                else ""
            ),
            erplibre_make=self._qemu_make_target(cmd_install),
            desktop=bool(vm.get("desktop")),
            no_git_identity=False,
            user=spec.get("user") or "erplibre",
        )
        try:
            fichiers = mod.guide_files(args)
        except Exception as exc:  # pragma: no cover - dépend du module
            print(f"  ⚠ {t('guide not written')} : {exc}")
            return False
        morceaux = []
        for chemin, mode, contenu, proprio in fichiers:
            q = shlex.quote(chemin)
            morceaux.append(
                f"printf '%s' {shlex.quote(contenu)} | sudo tee {q} "
                f">/dev/null && sudo chmod {mode} {q}"
            )
            if proprio:
                morceaux.append(f"sudo chown {shlex.quote(proprio)}: {q}")
        code, _o = self._pve_ssh(cible, " && ".join(morceaux))
        if code:
            print(f"  ⚠ {t('guide not written')} ({code})")
            return False
        print(f"  ✓ {t('connection guide written')}")
        return True

    @staticmethod
    def _pve_ssh(cible, remote, timeout=60):
        """(code, sortie) d'une commande exécutée DANS la VM, par son alias.

        Par l'alias et non par l'adresse : lui seul porte le rebond vers le
        réseau interne de l'hôte."""
        from script.proxmox import proxmox_deploy as pve

        argv = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            cible,
            remote,
        ]
        try:
            res = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 255, str(exc)
        return res.returncode, pve.strip_ssh_noise(
            (res.stdout or "") + (res.stderr or "")
        )

    def _pve_print_summary(self, spec, joignables, session):
        """Sommaire final : ce qui existe, où, et comment y entrer.

        Le pendant de celui de QEMU/KVM. Sans lui, l'écran se refermait sur la
        vue de progression et il ne restait rien à l'écran — ni l'adresse, ni
        la commande ssh, ni le chemin du journal."""
        print(f"\n{'═' * 60}")
        print(f"  {t('TOTAL summary')}")
        print(
            f"  {t('VMs deployed:')} {len(joignables)}/{len(spec['vms'])}"
            f"   {t('storage')} {spec.get('storage')}"
            f"   {t('bridge')} {spec.get('bridge')}"
        )
        for vm in joignables:
            print(
                f"    {vm['name']:<32} {t('VMID')} {vm.get('vmid', '?'):<6}"
                f" {vm.get('adresse', '?')}"
            )
            if vm.get("alias"):
                print(f"      ssh {vm['alias']}")
        if spec.get("install"):
            print(
                f"  {t('Install:')} {spec['install'].get('label') or ''}"
                f" ({spec['install'].get('branch')})"
            )
        print(f"  {t('Log:')} {session}")

    def _pve_confirm_spec(self, host, spec):
        """Récapitulatif puis confirmation, dans le TERMINAL.

        L'écran a montré le plan, mais c'est ici que ça devient réel — et sur
        une machine qui n'est pas la nôtre. La ligne dit donc où, quoi, et
        combien, avant le mot de passe sudo que l'hôte va demander."""
        print(f"\n  {t('Proxmox host')} : {self._pve_label(host)}")
        print(
            f"  {t('storage')} {spec['storage']}   "
            f"{t('bridge')} {spec['bridge']}   [{spec['res_label']}]"
        )
        for vm in spec["vms"]:
            print(
                f"    {vm['name']:32} {t('VMID')} {vm['vmid']}   "
                f"{vm['vcpus']} vCPU  {vm['ram']} Mo  {vm['disk']}   "
                f"{(vm.get('ipconfig') or '').replace('ip=', '')}"
            )
        if spec.get("install"):
            print(
                f"  ERPLibre : {spec['install'].get('label') or ''}"
                f"  ({spec['install'].get('branch')})"
            )
        return self._is_yes_default_yes(
            input(f"\n{t('Deploy this VM now? (Y/n): ')}")
        )

    def _pve_after_create(self, host, spec, reussies, cle_locale):
        """Ce qui suit la création : l'adresse, ~/.ssh/config, l'installation.

        L'alias et non l'IP dans les étapes suivantes : ssh y lit le rebond
        par l'hôte Proxmox, et le suivi d'installation en a besoin pour
        entrer dans une VM qui n'est pas sur notre réseau."""
        from script.proxmox import proxmox_deploy as pve

        # Les domaines LOCAUX : un nom partagé avec l'un d'eux fait dérailler
        # l'alias ssh et le suivi d'installation.
        locaux = set(self._qemu_list_domains())
        try:
            mod_qemu = self._qemu_import_module()
        except Exception:
            mod_qemu = None

        def alias_chaine(nom):
            """« hôte+vm », la convention déjà utilisée pour les VM
            imbriquées : elle dit où la machine vit, et n'entre en conflit
            avec rien."""
            hote = (host.get("target") or "").split("@")[-1]
            hote = re.sub(r"[^A-Za-z0-9._-]", "-", hote) or "pve"
            return f"{hote}+{nom}"

        # {nom de VM: alias à utiliser} — le suivi doit passer par l'alias
        # qu'on a RÉELLEMENT écrit, pas par le nom.
        alias = {}
        joignables = []
        for vm in spec["vms"]:
            if vm["name"] not in reussies:
                continue
            ip = pve.ip_from_ipconfig(vm.get("ipconfig") or "")
            if not ip:
                print(f"\n  {t('Waiting for the VM address…')} {vm['name']}")
                ip = self._pve_guest_ip(vm["vmid"])
            if not ip:
                print(
                    f"  ⚠ {vm['name']} : {t('No address yet. Try [6] later.')}"
                )
                continue
            print(f"  ✓ {vm['name']} : {ip}")
            # Un nom qui existe DÉJÀ comme domaine local est un piège : l'alias
            # ~/.ssh/config serait volé à la VM locale, et le suivi
            # d'installation — qui ré-résout par virsh — irait installer
            # ERPLibre sur ELLE. Vécu : « erplibre-ubuntu-2604 » déployée sur
            # Proxmox, installation partie sur la VM locale du même nom.
            noms_alias, vole = self._pve_alias_names(
                vm["name"],
                alias_chaine(vm["name"]),
                locaux,
                host["target"],
            )
            if vole:
                print(
                    f"  ⚠ {t('This name is already taken by')} {vole} :"
                    f" {t('the alias goes to')} {noms_alias[0]}"
                )
            # L'entrée ~/.ssh/config est le SEUL chemin vers cette VM : elle
            # est derrière l'hôte Proxmox (pont interne), donc son adresse
            # n'est pas routable d'ici et seul le rebond y mène. Décochée
            # alors qu'une installation est demandée, l'installation suivie ne
            # pouvait pas entrer — elle est donc écrite quand même, et on le
            # dit. Sans installation ni suivi, le choix est respecté.
            besoin = bool(spec.get("install")) or spec.get("monitor", True)
            if not spec.get("add_ssh_config") and besoin:
                print(f"  → {t('~/.ssh/config written anyway (install)')}")
            if spec.get("add_ssh_config") or besoin:
                self._write_ssh_config_entry(
                    noms_alias,
                    spec.get("user") or "erplibre",
                    ip,
                    identity_file=self._ssh_private_key(cle_locale),
                    proxy_jump=host["target"],
                )
                alias[vm["name"]] = noms_alias[0]
                print(f"  ✓ ~/.ssh/config : ssh {noms_alias[0]}")
            vm["adresse"] = ip
            vm["alias"] = alias.get(vm["name"], vm["name"])
            # Le guide AVANT l'installation : il doit être là même si rien ne
            # s'installe, et l'installation ne le touche pas.
            if vm["alias"] and mod_qemu:
                self._pve_write_guide(vm["alias"], vm, spec, mod_qemu)
            if vm["alias"]:
                self._pve_set_timezone(vm["alias"], spec)
            joignables.append(vm)
        install = spec.get("install")
        # Rendu à l'appelant pour son sommaire : lui seul sait ce qui a été
        # RÉELLEMENT joint.
        resultat = list(joignables)
        # Le suivi vient du DÉPLOIEMENT, pas de l'installation — même règle
        # qu'en QEMU/KVM. Sans elle, la case « Suivre l'installation » ne
        # commandait rien : décochée, le tableau de bord s'ouvrait quand
        # même ; cochée sans rien à installer, il ne s'ouvrait jamais.
        suivi = spec.get("monitor", True)
        if not joignables or not (install or suivi):
            return resultat
        noms = [vm["name"] for vm in joignables]
        if install:
            print(f"  {install.get('label') or ''}")
        # Une commande PAR VM dès qu'elles diffèrent : un Proxmox imbriqué
        # installe son hyperviseur, ses voisines ERPLibre. Une commande
        # unique en aurait imposé une aux deux.
        commun = (install or {}).get("cmd") or ""
        cartes = {
            vm["name"]: (vm.get("install_cmd") or commun) for vm in joignables
        }
        finale = cartes if self._qemu_per_vm(cartes, commun) else commun
        branche = (install or {}).get("branch") or ""
        # Même règle pour la branche et pour le type de VM : depuis que le
        # plan les porte PAR RANGÉE, lire la seule valeur commune revenait à
        # jeter le choix. Un parc mixte — un hyperviseur imbriqué à côté de VM
        # ERPLibre — est justement ce qu'on déploie ici le plus souvent.
        branches_vm = {
            vm["name"]: (vm.get("branch") or branche) for vm in joignables
        }
        if self._qemu_per_vm(branches_vm, branche):
            branche = branches_vm
        bureau = spec.get("desktop") or ""
        bureaux = {
            vm["name"]: (vm.get("desktop") or bureau) for vm in joignables
        }
        if self._qemu_per_vm(bureaux, bureau):
            bureau = bureaux
        if suivi:
            # Rien à installer ? La commande distante regarde alors la VM
            # ARRIVER (cloud-init, puis relevé système) : c'est ce que le
            # tableau de bord montre.
            #
            # La carte des hôtes suit : sans elle, les colonnes vivantes
            # (état, durée, écrit/s, RAM, disque) restaient VIDES pour une VM
            # posée sur un Proxmox distant — elles viennent de virsh, qui ne
            # connaît pas cet hôte.
            cartes_pve = {
                vm["name"]: {
                    "target": host["target"],
                    "sudo": host.get("sudo") or "",
                    "jump": host.get("jump") or "",
                    "vmid": vm.get("vmid"),
                    # L'adresse INTERNE : elle n'est pas routable d'ici, mais
                    # elle l'est depuis l'hôte. Avec le rebond, le tableau de
                    # bord entre dans la VM sans dépendre de ~/.ssh/config.
                    "addr": vm.get("adresse") or "",
                }
                for vm in joignables
                if vm.get("vmid")
            }
            self._qemu_install_erplibre_monitored(
                noms,
                branche,
                {n: alias.get(n, n) for n in noms},
                finale,
                # Les réglages du système invité, qui n'atteignaient pas la
                # commande distante : la VM naissait serveur nu, sans outils.
                prod=bool(spec.get("prod")),
                desktop=bureau,
                python_provider=spec.get("python_provider") or "",
                app_store=spec.get("app_store") or "deb",
                vm_tools=spec.get("vm_tools") or (),
                pve=cartes_pve,
                # Ce que sont ces VM, pris de la SPEC. Le suivi le demandait
                # à virsh, qui ne connaît que les domaines d'ici.
                meta={
                    vm["name"]: (
                        vm.get("distro"),
                        vm.get("version"),
                        vm.get("arch") or "amd64",
                    )
                    for vm in joignables
                },
            )
            return resultat
        # Sans suivi mais avec quelque chose à installer : en série, sortie à
        # l'écran. C'est le pendant exact de la voie QEMU/KVM.
        etiquette = branche if isinstance(branche, str) else t("per VM")
        print(f"\n{t('Installing ERPLibre on each VM')} ({etiquette})…")
        for vm in joignables:
            self._qemu_install_erplibre_vm(
                vm["name"],
                cle_locale,
                branches_vm.get(vm["name"], ""),
                alias.get(vm["name"], vm["name"]),
                vm.get("install_cmd") or commun,
                bool(spec.get("prod")),
                desktop=bureaux.get(vm["name"], ""),
                python_provider=spec.get("python_provider") or "",
                app_store=spec.get("app_store") or "deb",
                vm_tools=spec.get("vm_tools") or (),
            )
        return resultat

    def _pve_deploy_prompts(self, dry_run=False):
        """Déploie une VM SUR l'hôte Proxmox choisi, par questions.

        Le catalogue d'images est celui du dépôt (le même que QEMU/KVM) : c'est
        une connaissance locale, indépendante de l'hyperviseur. Tout le reste
        part sur l'hôte — téléchargement compris, puisque c'est là que le
        disque sera écrit.
        """
        from script.proxmox import proxmox_deploy as pve

        host = self._pve_host()
        if not host:
            return
        mod = self._qemu_import_module()
        distro = self._qemu_prompt_distro()
        version = self._qemu_prompt_version(distro)
        arch = "amd64"
        nom = (
            input(t("VM name (default: erplibre-<distro>): ")).strip()
            or f"erplibre-{distro}"
        )
        memoire = (
            self._qemu_ask_ram(t("RAM in MB, blank = 4096"), 4096) or 4096
        )
        vcpus = (
            self._qemu_ask_cpu(t("vCPU, blank = 2"), 2, os.cpu_count() or 2)
            or 2
        )
        disque = input(t("Disk size (default 32G): ")).strip() or "32G"

        code, _v = mod.DISTROS[distro][0][version][:2]
        url = mod.image_url(distro, code, arch, version)
        image = mod.default_image_name(distro, code, arch, version)

        # Stockage et pont : demandés à l'HÔTE, jamais devinés. « local-lvm »
        # n'existe pas partout, et un pont inventé fait échouer « qm create ».
        _c, out = self._pve_show("pvesm status --content images", quiet=True)
        stockages = pve.parse_storages(out)
        _c, out = self._pve_show("ip -o link show type bridge", quiet=True)
        ponts = pve.parse_bridges(out)
        _c, cfg_reseau = self._pve_show(
            "cat /etc/network/interfaces", quiet=True
        )
        infos_ponts = pve.parse_bridge_config(cfg_reseau)
        stockage = pve.pick_storage(stockages)
        pont = pve.pick_bridge(ponts)
        if not stockage:
            print(f"\n  ✗ {t('No storage able to hold a VM disk.')}")
            return
        if not pont and not dry_run:
            pont = self._pve_offer_bridge()
            if not pont:
                return
            _c, cfg_reseau = self._pve_show(
                "cat /etc/network/interfaces", quiet=True
            )
            infos_ponts = pve.parse_bridge_config(cfg_reseau)
        elif not pont:
            pont = pve.INTERNAL_BRIDGE
        # Le VMID D'ABORD : l'adresse d'un pont interne s'en déduit, et
        # l'afficher avant de l'avoir choisi ne pouvait pas marcher.
        vmid = pve.next_vmid(self._pve_vms())
        ipconfig = pve.ipconfig_for(infos_ponts.get(pont, {}), vmid)
        print(
            f"\n  {t('storage')} : {stockage}   ({len(stockages)} {t('offered')})"
        )
        print(f"  {t('bridge')}  : {pont}")
        print(f"  {t('address')} {ipconfig}")
        print(f"  VMID    : {vmid}")

        cle_locale = self._qemu_default_ssh_key()
        spec = {
            "name": nom,
            "memory": memoire,
            "vcpus": vcpus,
            "disk": disque,
            "storage": stockage,
            "bridge": pont,
            "image": image,
            "user": "erplibre",
            "sshkey_path": "/root/.ssh/erplibre-deploy.pub",
            "start": True,
            # DHCP sur un pont qui donne sur le LAN, adresse FIXE sur un pont
            # interne : là, aucun serveur DHCP ne répondrait et la VM
            # resterait muette.
            "ipconfig": ipconfig,
        }
        etapes = [pve.image_fetch_cmd(url, image)] + pve.create_cmds(
            vmid, spec
        )
        if dry_run:
            print(f"\n── {t('Would run on')} {host['target']} ──")
            print(f"  # {t('SSH key ->')} {spec['sshkey_path']}")
            for cmd in etapes:
                print(f"  {cmd}")
            return
        if not self._is_yes_default_yes(
            input(f"\n{t('Deploy this VM now? (Y/n): ')}")
        ):
            print(t("Cancelled."))
            return
        if cle_locale and not self._pve_push_key(cle_locale):
            print(f"  ⚠ {t('SSH key not pushed: password login only.')}")
            spec.pop("sshkey_path", None)
            etapes = [pve.image_fetch_cmd(url, image)] + pve.create_cmds(
                vmid, spec
            )
        for cmd in etapes:
            code, _out = self._pve_show(cmd, timeout=1800)
            if code:
                print(f"\n  ✗ {t('Step failed, stopping here.')}")
                return
        # Adresse fixe : c'est nous qui l'avons donnée, inutile de la
        # chercher. La découverte ne sert qu'au DHCP.
        ip = pve.ip_from_ipconfig(ipconfig)
        if ip:
            print(f"\n  {t('address given at creation:')} {ip}")
        else:
            print(f"\n  {t('Waiting for the VM address…')}")
            ip = self._pve_guest_ip(vmid)
        if not ip:
            print(f"  ⚠ {t('No address yet. Try [6] later.')}")
            return
        # ÉPILOGUE COMMUN avec l'écran, au lieu de le redire ici : cette voie
        # avait vieilli en silence — pas de protection de l'alias contre un
        # domaine local homonyme, pas de guide de connexion, pas de bloc
        # « pve » (donc aucune colonne vivante dans le suivi), pas de
        # sommaire. Trouvé par l'audit, jamais à l'usage.
        install = None
        if self._is_yes_default_yes(
            input(f"\n{t('Install ERPLibre on it? (Y/n): ')}")
        ):
            branch = self._qemu_pick_branch()
            label, cmd = self._qemu_pick_install_profile(distro)
            print(f"  {label}")
            install = {"branch": branch, "cmd": cmd, "label": label}
        spec_finale = {
            "host": host,
            "storage": stockage,
            "bridge": pont,
            "res_label": "",
            "vms": [
                {
                    "name": nom,
                    "vmid": vmid,
                    "distro": distro,
                    "version": version,
                    "arch": arch,
                    "ram": memoire,
                    "vcpus": vcpus,
                    "disk": disque,
                    "desktop": "",
                    "install_cmd": "",
                    "ipconfig": ipconfig,
                }
            ],
            "existing": [],
            "user": "erplibre",
            "ssh_key": cle_locale or "",
            "add_ssh_config": True,
            "install": install,
            "monitor": True,
            "python_provider": "",
            # La voie par questions ne demande pas le fuseau — l'écran le
            # fait. Sans ce défaut, elle laissait la VM en UTC, alors que la
            # voie libvirt reprend le fuseau de l'hôte depuis toujours.
            "timezone": self._qemu_host_timezone(),
        }
        joignables = self._pve_after_create(
            host, spec_finale, [nom], cle_locale
        )
        self._pve_print_summary(spec_finale, joignables or [], "")

    def _pve_ssh_config(self):
        """Écrit une entrée ~/.ssh/config par VM de l'hôte, avec l'hôte
        Proxmox en ProxyJump — sans quoi ces VM ne sont joignables d'ici que
        si leur réseau est routé jusqu'à nous."""
        host = self._pve_host()
        if not host:
            return
        vms = [v for v in self._pve_vms() if v["status"] == "running"]
        if not vms:
            print(f"\n{t('No running VM on this Proxmox host.')}")
            return
        cle = self._ssh_private_key(self._qemu_default_ssh_key())
        # Les domaines LOCAUX : un nom partagé avec l'un d'eux ne doit pas lui
        # voler son alias — même règle que le déploiement.
        locaux = set(self._qemu_list_domains())
        hote_court = (host.get("target") or "").split("@")[-1]
        hote_court = re.sub(r"[^A-Za-z0-9._-]", "-", hote_court) or "pve"
        for vm in vms:
            ip = self._pve_guest_ip(vm["vmid"], attente=0)
            if not ip:
                print(f"  ⚠ {vm['name']} : {t('no address, skipped')}")
                continue
            noms, vole = self._pve_alias_names(
                vm["name"],
                f"{hote_court}+{vm['name']}",
                locaux,
                host["target"],
            )
            if vole:
                print(
                    f"  ⚠ {t('This name is already taken by')} {vole} :"
                    f" {t('the alias goes to')} {noms[0]}"
                )
            self._write_ssh_config_entry(
                noms,
                "erplibre",
                ip,
                identity_file=cle,
                proxy_jump=host["target"],
            )
            print(
                f"  ✓ ssh {noms[0]}   ({ip} {t('through')} {host['target']})"
            )

    def _pve_test_vm(self):
        """Ouvre Odoo (:8069) d'une VM Proxmox dans un navigateur en ligne.

        Même chose que pour QEMU, à ceci près que l'adresse vient de l'hôte
        Proxmox et non de libvirt — et qu'elle n'est joignable d'ici que si son
        réseau l'est. On le dit plutôt que d'ouvrir une page vide.
        """
        vm = self._pve_pick_vm()
        if not vm:
            return
        ip = self._pve_guest_ip(vm["vmid"], attente=30)
        if not ip:
            print(f"\n  ⚠ {t('No address for this VM.')}")
            return
        if not self._qemu_ip_reachable(ip, port=8069, timeout=3):
            print(f"\n  ⚠ {ip}:8069 {t('unreachable from here.')}")
            print(
                f"  → {t('Use [13] to add a ProxyJump entry, then a tunnel.')}"
            )
            return
        navigateur = self._qemu_choose_cli_browser()
        if not navigateur:
            return
        url = f"http://{ip}:8069"
        print(f"→ {navigateur} {url}")
        os.system(f"{navigateur} {shlex.quote(url)}")

    def _pve_example(self):
        """Exemple de séquence, sans rien exécuter : de quoi voir ce que
        l'outil enverrait sur l'hôte."""
        from script.proxmox import proxmox_deploy as pve

        spec = {
            "name": "demo-vm",
            "memory": 4096,
            "vcpus": 2,
            "disk": "32G",
            "storage": "local-lvm",
            "bridge": "vmbr0",
            "image": "debian-13-genericcloud-amd64.qcow2",
            "sshkey_path": "/root/.ssh/erplibre-deploy.pub",
        }
        print(f"\n── {t('Example: demo-vm, Debian 13, on a Proxmox host')} ──")
        print(
            f"  {pve.image_fetch_cmd('https://…/debian-13.qcow2', spec['image'])}"
        )
        for cmd in pve.create_cmds(101, spec):
            print(f"  {cmd}")

    def _pve_stats(self):
        """État de l'hôte et de ses VM, en une page."""
        host = self._pve_host()
        if not host:
            return
        print(f"\n══ {t('Proxmox host:')} {self._pve_label(host)} ══")
        for titre, cmd in (
            (t("uptime"), "uptime"),
            (t("memory"), "free -h | head -2"),
            (t("storages"), "pvesm status"),
        ):
            code, out = self._pve_show(cmd, quiet=True)
            print(f"\n── {titre} ──")
            print((out or "").rstrip() if code == 0 else f"  ⚠ {out.strip()}")
        self._pve_list()

    def prompt_execute_proxmox(self):
        """Sous-menu Proxmox VE : l'équivalent du menu QEMU/KVM, mais sur un
        hôte DISTANT. La première question est donc « lequel ? » — et la
        réponse est retenue pour toute la session."""
        print(f"🤖 {t('Deploy a virtual machine on Proxmox VE!')}")
        if not self._pve_host():
            return False
        choices = [
            {"section": t("Deployment")},
            {"prompt_description": t("Deploy a VM on the Proxmox host")},
            {
                "prompt_description": t(
                    "Preview a deployment (dry-run, nothing sent)"
                )
            },
            {"prompt_description": t("Download a cloud image on the host")},
            {
                "prompt_description": t(
                    "Reopen install monitoring (last run / history)"
                )
            },
            {"section": t("Manage")},
            {"prompt_description": t("List VMs (qm list)")},
            {"prompt_description": t("Show a VM IP address")},
            {"prompt_description": t("Open the console on a VM")},
            {"prompt_description": t("Resize a VM disk")},
            {"prompt_description": t("Delete VM(s)")},
            {"prompt_description": t("Clean up (orphan disks)")},
            {
                "prompt_description": t(
                    "Test a VM (open Odoo in a CLI browser)"
                )
            },
            {"prompt_description": t("Statistics (host and VMs)")},
            {
                "prompt_description": t(
                    "SSH configuration (~/.ssh/config, ProxyJump)"
                )
            },
            {
                "prompt_description": t(
                    "Remote desktop tunnel (VNC/RDP over SSH)"
                )
            },
            {
                "prompt_description": t(
                    "Android emulator (start, tunnel, scrcpy)"
                )
            },
            {"section": t("Catalog")},
            {"prompt_description": t("List available images and their specs")},
            {"prompt_description": t("Proxmox - example sequence (dry-run)")},
            {"section": t("Host")},
            {"prompt_description": t("Change the Proxmox host")},
        ]
        # Même extension que le menu QEMU/KVM : ce que todo.json ajoute
        # s'affiche à la suite et se lance par son numéro.
        supplement = self.config_file.get_config("proxmox_from_makefile")
        if supplement:
            choices.extend(supplement)
        help_info = self.fill_help_info(choices)
        while True:
            hote = self._pve_host(ask=False)
            print(f"\n  {t('Proxmox host:')} {self._pve_label(hote) or '-'}")
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._pve_deploy()
            elif status == "2":
                self._pve_deploy(dry_run=True)
            elif status == "3":
                self._pve_fetch_image()
            elif status == "4":
                self._qemu_reopen_monitor()
            elif status == "5":
                self._pve_list()
            elif status == "6":
                self._pve_vm_ip()
            elif status == "7":
                self._pve_console()
            elif status == "8":
                self._pve_resize()
            elif status == "9":
                self._pve_delete()
            elif status == "10":
                self._pve_cleanup()
            elif status == "11":
                self._pve_test_vm()
            elif status == "12":
                self._pve_stats()
            elif status == "13":
                self._pve_ssh_config()
            elif status == "14":
                # Les VM Proxmox sont dans ~/.ssh/config (entrée 13) : le
                # tunnel du menu QEMU les y trouve, rebond compris.
                self._qemu_tunnel_menu()
            elif status == "15":
                self._qemu_emulator_menu()
            elif status == "16":
                self._qemu_list_images()
            elif status == "17":
                self._pve_example()
            elif status == "18":
                self._pve_forget_host()
                self._pve_pick_host()
            else:
                introuvable = True
                try:
                    numero = int(status)
                    # Les sections ne comptent pas dans la numérotation.
                    reelles = [c for c in choices if not c.get("section")]
                    if 0 < numero <= len(reelles):
                        introuvable = False
                        self.execute_from_configuration(reelles[numero - 1])
                except ValueError:
                    pass
                if introuvable:
                    print(t("Command not found !"))

    def _pve_fetch_image(self):
        """Télécharge une image cloud SUR l'hôte Proxmox.

        Là et pas ici : c'est sur l'hôte que le disque sera écrit, et faire
        descendre 325 Mio chez soi pour les renvoyer doublerait le transfert.
        """
        from script.proxmox import proxmox_deploy as pve

        mod = self._qemu_import_module()
        distro = self._qemu_prompt_distro()
        version = self._qemu_prompt_version(distro)
        code = mod.DISTROS[distro][0][version][0]
        url = mod.image_url(distro, code, "amd64", version)
        nom = mod.default_image_name(distro, code, "amd64", version)
        print(f"\n  {nom}\n  {url}")
        self._pve_show(pve.image_fetch_cmd(url, nom), timeout=1800)
