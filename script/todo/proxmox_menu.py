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
        entrees = self._ssh_config_entries(
            os.path.expanduser("~/.ssh/config")
        )
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
            fh.write(res.stdout if res.stdout.endswith("\n") else res.stdout + "\n")
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
            print(f"  ✗ {t('Not a Proxmox host (or unreachable):')}")
            premiere = (out or "").strip().splitlines()
            print(f"    {premiere[0] if premiere else t('no answer')}")
            print(f"  → {t('Check the address, the SSH access and pveversion.')}")
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
                print(f"  ✗ {t('qm needs root: no root, and sudo asks for a password.')}")
                print(f"  → {t('Connect as root@, or allow NOPASSWD sudo.')}")
                return None
            prefixe = "sudo "
            print(f"  ✓ sudo")
        host = dict(host, version=version, sudo=prefixe)
        print(f"  ✓ Proxmox VE {version}")
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
            print(
                f"  [{i}] {vm['vmid']:<6} {vm['name']:<28} {vm['status']}"
            )
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
        taille = input(
            t("Size (+10G to add, 40G for a target): ")
        ).strip()
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
            with open(os.path.expanduser(chemin_local), encoding="utf-8") as fh:
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
            print(f"  ⚠ {t('This moves the host address: do it from a console.')}")
            return ""
        _c, sortie = self._pve_show(
            "ip -o -4 route show default", quiet=True
        )
        uplink = ""
        parts = (sortie or "").split()
        if "dev" in parts:
            uplink = parts[parts.index("dev") + 1]
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
        _c, cfg = self._pve_show("cat /etc/network/interfaces", quiet=True)
        infos = pve.parse_bridge_config(cfg)
        cpu, ram_libre = self._pve_capacity()

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
            "bridges": ponts,
            "bridge": pve.pick_bridge(ponts),
            "ipconfig": ipconfig,
            "build_command": build_command,
            "branches": self._qemu_branch_list() or ["master"],
            "install_profiles": self._qemu_install_profiles(),
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
            "disk": vm["disk"],
            "storage": spec["storage"],
            "bridge": spec["bridge"],
            "image": image,
            "user": spec.get("user") or "erplibre",
            "start": spec.get("start", True),
            "ipconfig": vm.get("ipconfig") or "ip=dhcp",
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

        if not dry_run and not self._pve_confirm_spec(host, spec):
            print(t("Cancelled."))
            return
        cle_locale = spec.get("ssh_key") or self._qemu_default_ssh_key()
        if cle_locale and not dry_run:
            if self._pve_push_key(cle_locale):
                spec["sshkey_path"] = "/root/.ssh/erplibre-deploy.pub"
            else:
                print(f"  ⚠ {t('SSH key not pushed: password login only.')}")
        travaux = []
        for vm in spec["vms"]:
            cmds = self._pve_vm_commands(mod, vm, spec)
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
        resultats = run_deploy_progress(travaux, spec.get("parallelism") or 1)
        reussies = [nom for nom, code, _o, _d in resultats if code == 0]
        for nom, code, sortie, _duree in resultats:
            if code:
                print(f"\n  ✗ {nom} : {t('exit code')} {code}")
                print("\n".join(sortie.rstrip().splitlines()[-12:]))
        if not reussies:
            return
        self._pve_after_create(host, spec, reussies, cle_locale)

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

        joignables = []
        for vm in spec["vms"]:
            if vm["name"] not in reussies:
                continue
            ip = pve.ip_from_ipconfig(vm.get("ipconfig") or "")
            if not ip:
                print(f"\n  {t('Waiting for the VM address…')} {vm['name']}")
                ip = self._pve_guest_ip(vm["vmid"])
            if not ip:
                print(f"  ⚠ {vm['name']} : {t('No address yet. Try [6] later.')}")
                continue
            print(f"  ✓ {vm['name']} : {ip}")
            if spec.get("add_ssh_config"):
                self._write_ssh_config_entry(
                    vm["name"],
                    spec.get("user") or "erplibre",
                    ip,
                    identity_file=self._ssh_private_key(cle_locale),
                    proxy_jump=host["target"],
                )
                print(f"  ✓ ~/.ssh/config : ssh {vm['name']}")
            joignables.append(vm)
        install = spec.get("install")
        if not install or not joignables:
            return
        noms = [vm["name"] for vm in joignables]
        print(f"  {install.get('label') or ''}")
        self._qemu_install_erplibre_monitored(
            noms,
            install.get("branch") or "master",
            {n: n for n in noms},
            install.get("cmd") or "",
        )

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
        nom = input(
            t("VM name (default: erplibre-<distro>): ")
        ).strip() or f"erplibre-{distro}"
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
        print(f"\n  {t('storage')} : {stockage}   ({len(stockages)} {t('offered')})")
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
        print(f"  ✓ {nom} : {ip}")
        # Entrée ~/.ssh/config avec l'hôte Proxmox en REBOND : c'est ce qui
        # rend la VM joignable d'ici, et c'est aussi ce qui permet au suivi
        # d'installation d'y entrer (il reçoit l'alias, pas l'IP).
        self._write_ssh_config_entry(
            nom,
            "erplibre",
            ip,
            identity_file=self._ssh_private_key(cle_locale),
            proxy_jump=host["target"],
        )
        print(f"  ✓ ~/.ssh/config : ssh {nom}")
        if self._is_yes_default_yes(
            input(f"\n{t('Install ERPLibre on it? (Y/n): ')}")
        ):
            branch = self._qemu_pick_branch()
            label, cmd = self._qemu_pick_install_profile(distro)
            print(f"  {label}")
            # L'ALIAS, pas l'IP : ssh y lit le ProxyJump de ~/.ssh/config.
            self._qemu_install_erplibre_monitored(
                [nom], branch, {nom: nom}, cmd
            )

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
        for vm in vms:
            ip = self._pve_guest_ip(vm["vmid"], attente=0)
            if not ip:
                print(f"  ⚠ {vm['name']} : {t('no address, skipped')}")
                continue
            self._write_ssh_config_entry(
                vm["name"],
                "erplibre",
                ip,
                identity_file=cle,
                proxy_jump=host["target"],
            )
            print(f"  ✓ ssh {vm['name']}   ({ip} {t('through')} {host['target']})")

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
            print(f"  → {t('Use [13] to add a ProxyJump entry, then a tunnel.')}")
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
        print(f"  {pve.image_fetch_cmd('https://…/debian-13.qcow2', spec['image'])}")
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
            {"prompt_description": t("Remote desktop tunnel (VNC/RDP over SSH)")},
            {"prompt_description": t("Android emulator (start, tunnel, scrcpy)")},
            {"section": t("Catalog")},
            {"prompt_description": t("List available images and their specs")},
            {"prompt_description": t("Proxmox - example sequence (dry-run)")},
            {"section": t("Host")},
            {"prompt_description": t("Change the Proxmox host")},
        ]
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
