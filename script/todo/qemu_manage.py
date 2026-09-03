#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu QEMU/KVM : g\u00e9rer les VM existantes.\n\nLe cycle de vie apr\u00e8s la cr\u00e9ation : lister, allumer et \u00e9teindre, r\u00e9gler le\nmat\u00e9riel, redimensionner (et r\u00e9tr\u00e9cir, ce qui demande de traverser le syst\u00e8me\nde fichiers invit\u00e9 par nbd), effacer, nettoyer les restes, retrouver une\nadresse IP, rouvrir le suivi d'une installation.\n\nC'est le fichier qui appelle \u00ab virsh \u00bb le plus souvent : les helpers qui le\nfont (domstate, dumpxml, c_env) vivent donc ici."""

import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import time

from script.todo import todo_install
from script.todo.qemu_privilege import (
    LIBVIRT_URI as URI,
    sudo_prefix,
    system_path,
    virsh_argv,
)
from script.todo.todo_i18n import t


def parse_ssh_blocks(content) -> dict:
    """{nom: {"hostname": …, "proxyjump": …}} pour CHAQUE nom déclaré.

    Une ligne « Host » peut en porter plusieurs : ils partagent alors le même
    corps, donc la même entrée. Les motifs (« * », « ? ») sont écartés — ce
    sont des règles, pas des machines."""
    blocs, courant = {}, []
    for ligne in (content or "").splitlines():
        if re.match(r"^[ \t]*Host[ \t]+", ligne):
            corps = {}
            courant = [
                n for n in ligne.split()[1:] if "*" not in n and "?" not in n
            ]
            for nom in courant:
                blocs[nom] = corps
            continue
        if not courant:
            continue
        if ligne.strip() and not ligne[:1].isspace():
            courant = []
            continue
        mots = ligne.split()
        if len(mots) >= 2 and mots[0].lower() in ("hostname", "proxyjump"):
            blocs[courant[0]][mots[0].lower()] = mots[1]
    return blocs


def ssh_orphans(blocs, juge, prefixe="erplibre-"):
    """(gardées, orphelines) — chacune [(nom, raison)].

    Un ProxyJump ne vaut pas preuve de vie à lui seul : « écrite pour une VM
    imbriquée, que virsh ne connaîtra jamais » oublie que le rebond, lui, peut
    avoir disparu. Effacer la VM qui servait de rebond retire son entrée —
    correctement — et laisse celles qui rebondissaient par elle : des
    culs-de-sac présentés comme « mènent encore quelque part ».

    D'où le point fixe : retirer un parent peut orpheliner ses enfants, et
    ceux-ci peuvent en orpheliner d'autres. On tourne jusqu'à ce que plus
    rien ne bouge.

    `juge(nom)` ne rend que les preuves DIRECTES — un domaine vivant, une
    adresse qui mène à l'un d'eux, une VM de l'hôte Proxmox. Si le rebond
    comptait comme preuve directe, une chaîne de rebonds morts se soutiendrait
    toute seule."""
    noms = [n for n in blocs if n.startswith(prefixe)]
    raisons = {n: juge(n) for n in noms}

    def rebond_vivant(saut):
        if saut in blocs:
            # Une entrée qu'on ne gère PAS — hôte personnel — n'est jamais
            # notre affaire : on la suppose vivante plutôt que d'effacer sur
            # une supposition.
            return (
                bool(raisons.get(saut)) if saut.startswith(prefixe) else True
            )
        # Plus AUCUNE entrée de ce nom. Deux lectures, et il faut les
        # séparer : une adresse ou un nom DNS, ssh saura le joindre et ce
        # n'est pas notre affaire ; un nom de NOTRE nommage, en revanche,
        # n'existe que par son entrée — celle-ci partie, le rebond ne mène
        # nulle part. C'est l'état exact laissé par un nettoyage précédent,
        # qui avait retiré le parent et gardé les enfants.
        if not saut.startswith(prefixe):
            return True
        return bool(juge(saut))

    bouge = True
    while bouge:
        bouge = False
        for nom in noms:
            if raisons[nom]:
                continue
            saut = blocs[nom].get("proxyjump")
            if saut and rebond_vivant(saut):
                raisons[nom] = t("reached through a jump host")
                bouge = True
    gardes, orphelines = [], []
    for nom in noms:
        if raisons[nom]:
            gardes.append((nom, raisons[nom]))
        else:
            saut = blocs[nom].get("proxyjump")
            orphelines.append(
                (nom, f"{t('its jump host is gone:')} {saut}" if saut else "")
            )
    return gardes, orphelines


class QemuManageMixin:
    """Menu QEMU/KVM : g\u00e9rer les VM existantes.\n\nLe cycle de vie apr\u00e8s la cr\u00e9ation : lister, allumer et \u00e9teindre, r\u00e9gler le\nmat\u00e9riel, redimensionner (et r\u00e9tr\u00e9cir, ce qui demande de traverser le syst\u00e8me\nde fichiers invit\u00e9 par nbd), effacer, nettoyer les restes, retrouver une\nadresse IP, rouvrir le suivi d'une installation.\n\nC'est le fichier qui appelle \u00ab virsh \u00bb le plus souvent : les helpers qui le\nfont (domstate, dumpxml, c_env) vivent donc ici."""

    def _qemu_download_image(self):
        script_path = self._qemu_script_path()
        distro = self._qemu_prompt_distro()
        version = self._qemu_prompt_version(distro)
        ans = input(t("Verify SHA256 after download? (y/N): "))
        parts = [
            "sudo",
            script_path,
            "--download-only",
            "--distro",
            distro,
            "--version",
            version,
        ]
        if self._is_yes(ans):
            parts.append("--verify")
        cmd = " ".join(shlex.quote(p) for p in parts)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_list_vms(self, ask_advanced=False):
        cmd = f"{sudo_prefix()}virsh --connect {URI} list --all"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        if not ask_advanced:
            return
        # Menu contextuel : infos avancées, ou changer l'état de VM.
        print(f"\n{t('What do you want to do?')}")
        print(f"  [1] {t('Advanced info (vCPU, RAM, disk)')}")
        print(f"  [2] {t('Change the state of one or more VMs')}")
        print(f"  [{t('Enter')}] {t('Nothing')}")
        choice = input(t("Choice: ")).strip()
        if choice == "1":
            self._qemu_list_vms_advanced()
        elif choice == "2":
            self._qemu_change_state()

    def _qemu_change_state(self):
        """Démarre (« ouvrir ») ou éteint (« fermer ») une liste de VM saisie
        séparée par des virgules, avec DOUBLE validation."""
        names = self._qemu_list_domains()
        if not names:
            print(f"\n{t('No VM found.')}")
            return
        # Liste NUMÉROTÉE, comme l'écran de suppression : les noms de VM sont
        # longs et se ressemblent, les retaper invite à la faute de frappe sur
        # une commande qui change l'état d'une machine.
        print(f"\n{t('Available VMs:')}")
        for i, n in enumerate(names, 1):
            print(f"  [{i}] {n}")
        print(f"  [all] {t('select all')}")
        raw = input(t("Selection (numbers, or 'all'): ")).strip()
        if not raw:
            print(t("Nothing selected."))
            return
        if raw.lower() in ("all", "*"):
            resolved = list(names)
        else:
            resolved = self._parse_index_selection(raw.lower(), names)
            # Le parseur ignore en silence ce qu'il ne reconnaît pas. Sur une
            # sélection qui va démarrer ou éteindre des VM, un numéro hors
            # liste doit être dit, pas escamoté.
            unknown = [
                tok
                for tok in re.split(r"[\s,]+", raw.strip())
                if tok and tok not in names and not self._is_index(tok, names)
            ]
            if unknown:
                print(f"{t('Unknown VM(s):')} {', '.join(unknown)}")
                return
        if not resolved:
            print(t("Nothing selected."))
            return
        # Choix de l'état cible : ouvrir (démarrer) ou fermer (éteindre).
        print(f"\n{t('Target state:')}")
        print(f"  [1] {t('Open (start)')}")
        print(f"  [2] {t('Close (shut down)')}")
        print(f"  [3] {t('Adjust hardware only (vCPU, RAM, 3D)')}")
        st = input(t("Choice: ")).strip()
        if st == "1":
            action, verb = "start", t("start")
        elif st == "2":
            action, verb = "shutdown", t("shut down")
        elif st == "3":
            self._qemu_adjust_hardware(resolved)
            return
        else:
            print(t("Cancelled."))
            return
        # Le matériel d'une VM ne se règle QUE pendant qu'elle est éteinte :
        # démarrer est donc le dernier moment pour le faire, et le seul où la
        # question tombe juste.
        if action == "start" and self._is_yes(
            input(f"\n{t('Adjust hardware before starting? (y/N): ')}")
        ):
            self._qemu_adjust_hardware(resolved)
        # DOUBLE validation avant d'appliquer.
        summary = f"{verb} -> {', '.join(resolved)}"
        if not self._is_yes(input(f"{t('Apply:')} {summary} ? (o/N) : ")):
            print(t("Cancelled."))
            return
        if not self._is_yes(input(t("Confirm for real? (y/N): "))):
            print(t("Cancelled."))
            return
        for real in resolved:
            cmd = (
                f"{sudo_prefix()}virsh --connect {URI} "
                f"{action} {shlex.quote(real)}"
            )
            print(f"\n{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)

    @staticmethod
    def _qemu_dumpxml(name, inactive=True):
        """XML du domaine, ou '' — source de son état matériel.

        « --inactive » n'est pas décoratif : sur une VM allumée, « dumpxml »
        rend la vue VIVANTE, décorée de ce que libvirt a alloué au démarrage
        (portid du réseau, vnetN, alias). C'est la définition persistante que
        virt-xml modifie, et c'est donc elle qu'il faut lire — d'où le défaut.

        `inactive=False` demande justement la vue vivante : pour SAVOIR CE QUI
        EST OUVERT, c'est elle qui compte, un disque attaché à chaud n'existant
        que là.
        """
        argv = virsh_argv("dumpxml")
        if inactive:
            argv.append("--inactive")
        argv.append(name)
        try:
            res = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=20,
                env=QemuManageMixin._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return res.stdout if res.returncode == 0 else ""

    @staticmethod
    def _qemu_autostart(name):
        """Démarrage automatique activé ? (absent du XML : virsh seul le sait)"""
        try:
            res = subprocess.run(
                virsh_argv("dominfo", name),
                capture_output=True,
                text=True,
                timeout=15,
                env=QemuManageMixin._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        for line in res.stdout.splitlines():
            if line.startswith("Autostart:"):
                return line.split(":", 1)[1].strip() == "enable"
        return False

    def _qemu_ask_bool(self, prompt, default):
        """Question fermée dont le DÉFAUT est l'état actuel de la VM.

        Une réponse vide — ou incompréhensible — laisse la VM telle quelle :
        sur un formulaire de matériel, le silence ne doit rien modifier.
        """
        ans = input(prompt).strip()
        if self._is_yes(ans):
            return True
        if self._is_no(ans):
            return False
        return default

    def _qemu_host_gpu_node(self):
        """Nœud de rendu de l'hôte, vu par deploy_qemu (source unique), ou ''."""
        try:
            return self._qemu_import_module().host_gpu_node()
        except (OSError, AttributeError, ImportError):
            return ""

    def _qemu_net_choices(self):
        """Réseaux proposables : réseaux libvirt, puis ponts de l'hôte.

        Les ponts appartenant à un réseau libvirt (virbr0 pour « default »)
        sont écartés : les proposer offrirait DEUX fois le même chemin, dont
        un qui contourne la gestion du réseau par libvirt.
        """
        tokens = []
        nets = self._qemu_cmd_lines(virsh_argv("net-list", "--all", "--name"))
        owned = set()
        for net in nets:
            tokens.append(f"network:{net}")
            for line in self._qemu_cmd_lines(virsh_argv("net-info", net)):
                if line.startswith("Bridge:"):
                    owned.add(line.split(":", 1)[1].strip())
        for line in self._qemu_cmd_lines(
            ["ip", "-o", "link", "show", "type", "bridge"]
        ):
            # « 3: br0: <BROADCAST,...» -> br0
            parts = line.split(":")
            bridge = parts[1].strip() if len(parts) > 1 else ""
            if bridge and bridge not in owned:
                tokens.append(f"bridge:{bridge}")
        return tokens

    @staticmethod
    def _qemu_cmd_lines(cmd):
        """Lignes non vides d'une commande, ou [] si elle échoue."""
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                env=QemuManageMixin._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if res.returncode != 0:
            return []
        return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]

    def _qemu_adjust_hardware(self, names):
        """Règle vCPU, RAM, 3D et démarrage automatique de VM ÉTEINTES.

        Les VM allumées sont écartées, en le disant : virt-xml y écrirait une
        définition qui ne prendrait effet qu'au prochain démarrage — un
        réglage qui paraît appliqué et ne l'est pas.
        """
        from script.todo import qemu_hardware as hw

        off, busy = [], []
        for name in names:
            state = self._qemu_domstate(name)
            (off if state == "shut off" else busy).append(name)
        if busy:
            print(
                f"\n  ⚠ {t('Not shut off, hardware left untouched:')}"
                f" {', '.join(busy)}"
            )
        if not off:
            return
        node = self._qemu_host_gpu_node()
        gpu_txt = node or t("none (software rendering)")
        print(f"\n{t('Host GPU:')} {gpu_txt}")
        rows = [
            r
            for r in (
                hw.hw_state(self._qemu_dumpxml(n), self._qemu_autostart(n))
                for n in off
            )
            if r.get("name")
        ]
        if not rows:
            print(f"  ⚠ {t('Unreadable VM definition.')}")
            return
        for r in rows:
            print(f"  {r['name']:<30} {hw.hw_summary(r)}")
        nets = self._qemu_net_choices()
        want = self._qemu_hw_form(rows, node, nets)
        if want is None:
            print(t("Cancelled."))
            return
        if not want:
            want = self._qemu_hw_prompts(rows, node, nets)
        if not want:
            print(t("Cancelled."))
            return
        plan = []
        for r in rows:
            plan += hw.hw_plan(r, want.get(r["name"]) or {}, node)
        for entry in plan:
            if entry.get("skip"):
                print(f"  ⚠ {entry['what']} : {entry['skip']}")
        cmds = [e for e in plan if e.get("cmd")]
        if not cmds:
            print(f"\n{t('Nothing to change.')}")
            return
        print(f"\n{t('Changes:')}")
        for entry in cmds:
            print(f"  - {entry['what']}")
        if not self._is_yes(input(t("Apply these changes? (y/N): "))):
            print(t("Cancelled."))
            return
        for entry in cmds:
            cmd = sudo_prefix() + " ".join(
                shlex.quote(c) for c in entry["cmd"]
            )
            print(f"\n{t('Will execute:')} {cmd}")
            # virt-xml est un script Python du système : sans PATH assaini, il
            # s'amorce sur l'interpréteur du venv, où les modules de la
            # distribution n'existent pas.
            self.execute.exec_command_live(
                cmd,
                source_erplibre=False,
                new_env={"PATH": system_path()},
            )

    def _qemu_hw_form(self, rows, node, nets=None):
        """Formulaire TUI d'ajustement. Renvoie l'intention par VM, {} pour
        retomber sur les invites en ligne (textual absent), None si annulé."""
        from script.todo import textual_setup

        if not textual_setup.ensure():
            return {}
        try:
            from script.todo.qemu_hardware import run_hardware_form

            return run_hardware_form(rows, node, nets)
        except ImportError:
            return {}

    def _qemu_pick(self, title, values, current, labels=None):
        """Liste numérotée dont le DÉFAUT est la valeur actuelle.

        Rendre la valeur actuelle sur une réponse vide, et sur une réponse
        illisible : dans un formulaire de matériel, ne rien comprendre ne doit
        rien changer.
        """
        labels = labels or values
        print(f"{title} :")
        for i, (val, lab) in enumerate(zip(values, labels), 1):
            mark = " ←" if val == current else ""
            print(f"      [{i}] {lab}{mark}")
        ans = input("      " + t("Choice: ")).strip()
        if not ans.isdigit():
            return current
        idx = int(ans)
        return values[idx - 1] if 1 <= idx <= len(values) else current

    def _qemu_hw_prompts(self, rows, node, nets=None):
        """Même ajustement, en invites, quand Textual n'est pas disponible."""
        from script.todo import qemu_hardware as hw

        cpus = hw.cpu_choices(rows)
        reseaux = hw.net_choices(rows, nets)
        want = {}
        for r in rows:
            print(f"\n  {r['name']} — {hw.hw_summary(r)}")
            vcpus = input(f"    vCPU [{r.get('vcpus')}] : ")
            ram = input(f"    RAM [{hw.fmt_mib(r.get('mem_mib'))}] : ")
            reason = hw.gpu_allowed(r, node)
            if reason:
                print(f"    ⚠ {t('3D acceleration (host GPU)')} : {reason}")
                gpu = False
            else:
                gpu = self._qemu_ask_bool(
                    f"    {t('3D acceleration (host GPU)')} ? (o/N) : ",
                    bool(r.get("accel3d")),
                )
            auto = self._qemu_ask_bool(
                f"    {t('Autostart')} ? (o/N) : ", bool(r.get("autostart"))
            )
            cpu = self._qemu_pick(f"    {t('CPU mode')}", cpus, r.get("cpu"))
            heads = ""
            if r.get("video"):
                heads = input(f"    {t('Screens')} [{r.get('heads') or 1}] : ")
            net = r.get("net") or ""
            # Une seule possibilité : rien à demander. C'est le cas d'un hôte
            # sans pont, où le réseau libvirt est la seule voie.
            if len(reseaux) > 1:
                net = self._qemu_pick(
                    f"    {t('Network')}",
                    [tok for tok, _lab in reseaux],
                    net,
                    labels=[lab for _tok, lab in reseaux],
                )
            want[r["name"]] = hw.build_want(
                r, vcpus, ram, gpu, auto, cpu=cpu, heads=heads, net=net
            )
        return want

    @staticmethod
    def _qemu_dominfo(name):
        """(vcpus, max_mem_kib) via « virsh dominfo », ou (0, 0)."""
        try:
            res = subprocess.run(
                virsh_argv("dominfo", name),
                capture_output=True,
                text=True,
                timeout=15,
                env=QemuManageMixin._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return 0, 0
        vcpus, mem = 0, 0
        for line in res.stdout.splitlines():
            if line.startswith("CPU(s):"):
                try:
                    vcpus = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("Max memory:"):
                # « 4194304 KiB »
                try:
                    mem = int(line.split(":", 1)[1].split()[0])
                except (ValueError, IndexError):
                    pass
        return vcpus, mem

    @staticmethod
    def _qemu_disk_sizes(disk):
        """(taille virtuelle, taille réelle sur disque) en octets, via
        qemu-img info -U (lit même VM allumée). (0, 0) si échec."""
        try:
            res = subprocess.run(
                ["sudo", "qemu-img", "info", "-U", "--output=json", disk],
                capture_output=True,
                text=True,
                timeout=20,
            )
            data = json.loads(res.stdout)
            return (
                int(data.get("virtual-size", 0)),
                int(data.get("actual-size", 0)),
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0, 0

    @staticmethod
    def _qemu_domain_uptime(name):
        """Secondes depuis le démarrage du domaine, ou None.

        libvirt n'expose pas l'uptime d'un invité : ni dominfo, ni domstats, ni
        l'agent. Mais le processus QEMU du domaine est né avec lui, et son âge
        est donc exactement celui de la VM. « guest=<nom>, » est le motif que
        libvirt met dans sa ligne de commande — la virgule évite qu'un nom
        préfixe d'un autre matche à sa place."""
        try:
            res = subprocess.run(
                ["pgrep", "-f", f"guest={name},"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            pid = (res.stdout or "").split()[0]
            age = subprocess.run(
                ["ps", "-o", "etimes=", "-p", pid],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return int((age.stdout or "").strip())
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None

    @staticmethod
    def _qemu_dommemstat(name):
        """(utilisée, totale) en KiO vues par l'INVITÉ, ou (0, 0).

        « available » est ce que l'invité voit, « usable » ce qu'il peut encore
        rendre : leur différence est son « used », à quelques mégaoctets près —
        calibré contre le « free » de deux VM (1186 contre 1216, 4831 contre
        4838). « unused » ne convient pas : il ignore le cache, et donnait
        10,8 Go d'« utilisé » sur une VM qui en occupait 1,2.

        La période de collecte est posée d'abord, et c'est indispensable : sans
        elle le ballon ne rafraîchit rien, et une VM qui occupait 4,8 Go en
        annonçait 490 Mo — vécu. « --live » ne touche pas le XML : le réglage
        disparaît au prochain démarrage du domaine."""
        try:
            subprocess.run(
                virsh_argv("dommemstat", name, "--period", "5", "--live"),
                capture_output=True,
                text=True,
                timeout=15,
                env=QemuManageMixin._qemu_c_env(),
            )
            res = subprocess.run(
                virsh_argv("dommemstat", name),
                capture_output=True,
                text=True,
                timeout=15,
                env=QemuManageMixin._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return 0, 0
        stat = {}
        for line in (res.stdout or "").splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    stat[parts[0]] = int(parts[1])
                except ValueError:
                    continue
        total = stat.get("available", 0)
        usable = stat.get("usable", 0)
        if not total or not usable:
            return 0, total
        return max(0, total - usable), total

    def _qemu_list_vms_advanced(self):
        """Tableau détaillé par VM : état, vCPU, RAM allouée, disque (virtuel
        + réel), plus l'espace total disponible du stockage des images."""
        names = self._qemu_list_domains()
        if not names:
            print(f"\n{t('No VM found.')}")
            return
        g = 1 << 30
        # Largeurs serrées pour que la ligne tienne en 80 colonnes AVEC le nom
        # entier : c'est lui qui distingue les machines, et « erplibre-ubuntu-
        # 2604-gno » tronqué ne distingue plus rien.
        header = (
            f"\n{'VM':<26} {'État':<8} {'vCPU':>4} {'RAM':>10} "
            f"{'Disque':>7} {'Réel':>7} {'Uptime':>6}"
        )
        print(header)
        print("─" * len(header.strip()))
        disk_dirs = set()
        for name in names:
            state = self._qemu_domstate(name) or "?"
            vcpus, mem_kib = self._qemu_dominfo(name)
            disk = self._qemu_main_disk(name)
            virt, actual = self._qemu_disk_sizes(disk) if disk else (0, 0)
            if disk:
                disk_dirs.add(os.path.dirname(disk))
            ram_g = (mem_kib * 1024) / g if mem_kib else 0
            # « RAM » dit désormais l'USAGE et non la seule allocation : sur un
            # hyperviseur, savoir qu'une VM de 32 Go n'en occupe que 4,7 décide
            # s'il reste de la place pour la suivante. Deux nombres dans une
            # colonne plutôt que deux colonnes — le tableau tient encore sur
            # une ligne de terminal.
            used_kib, _total_kib = self._qemu_dommemstat(name)
            # Le total sans décimale quand il est entier — une allocation
            # vaut 8, 12 ou 32 Go, jamais 32,0.
            alloc = f"{ram_g:.0f}" if ram_g == int(ram_g) else f"{ram_g:.1f}"
            ram = (
                f"{used_kib * 1024 / g:.1f}G/{alloc}G"
                if used_kib
                else f"-/{alloc}G"
            )
            # L'uptime vient de l'âge du processus QEMU : libvirt ne l'expose
            # nulle part, et ce processus est né avec le domaine.
            up = self._qemu_domain_uptime(name)
            print(
                f"{name:<26.26} {state:<8.8} {vcpus:>4} "
                f"{ram:>10} {virt / g:>6.1f}G {actual / g:>6.1f}G "
                f"{self._fmt_uptime(up) if up else '-':>6}"
            )
        # Espace total disponible sur le(s) stockage(s) des disques.
        for d in sorted(disk_dirs) or ["/var/lib/libvirt/images"]:
            try:
                usage = shutil.disk_usage(d)
            except OSError:
                continue
            print(
                f"\n{t('Storage')} {d} : "
                f"{usage.free / g:.1f}G {t('free')} / "
                f"{usage.total / g:.1f}G {t('total')} "
                f"({usage.used / g:.1f}G {t('used')})"
            )

    def _qemu_show_ip(self):
        # Affiche d'abord les VM (avec leur ID) pour que l'utilisateur sache
        # quel nom/ID saisir, puis demande lequel (ou « all » pour toutes).
        self._qemu_list_vms()
        print()
        name = input(t("VM name or ID (or 'all'): ")).strip()
        if not name:
            print(t("VM name is required!"))
            return
        if name.lower() in ("all", "tous", "*"):
            targets = self._qemu_list_domains()
            if not targets:
                print(t("No VM found."))
                return
        else:
            targets = [name]
        for tgt in targets:
            cmd = (
                f"{sudo_prefix()}virsh --connect {URI} "
                f"domifaddr {shlex.quote(tgt)}"
                " --source lease"
            )
            print(f"\n{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_console(self):
        # Liste les VM, demande laquelle, rappelle comment quitter (Ctrl+])
        # puis ouvre la console série interactive.
        self._qemu_list_vms()
        print()
        name = input(t("VM name or ID: ")).strip()
        if not name:
            print(t("VM name is required!"))
            return
        print(f"\n💡 {t('To leave the console, press Ctrl+] (then Enter).')}")
        print(
            f"👤 {t('Default login (if set at deploy): erplibre / erplibre')}"
        )
        cmd = (
            f"{sudo_prefix()}virsh --connect {URI} console {shlex.quote(name)}"
        )
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_test_vm(self):
        """Teste une VM : résout son IP puis ouvre Odoo (:8069) dans un
        navigateur web EN LIGNE DE COMMANDE choisi par l'utilisateur."""
        self._qemu_list_vms()
        print()
        name = input(t("VM name or ID: ")).strip()
        if not name:
            print(t("VM name is required!"))
            return
        real = self._qemu_domname(name)
        if not self._qemu_domain_exists(real):
            print(f"{real}: {t('VM not found.')}")
            return
        print(f"\n{t('Resolving VM IP...')}")
        ip = self._qemu_vm_ip(real, timeout=120)
        if not ip:
            print(t("No IP found for this VM."))
            return
        browser = self._qemu_choose_cli_browser()
        if not browser:
            return
        url = f"http://{ip}:8069"
        print(f"→ {browser} {url}")
        # os.system (et NON exec_command_live) : un navigateur texte a besoin
        # du VRAI TTY interactif. exec_command_live redirige la sortie dans un
        # tube -> le navigateur ne fait qu'imprimer sans réagir au clavier.
        rc = os.system(f"{browser} {shlex.quote(url)}")
        if rc != 0:
            msg = t(
                "Page may not have loaded: Odoo not started on :8069, "
                "or network/firewall."
            )
            print(f"⚠  {msg}")

    def _qemu_reopen_monitor(self):
        """Rouvre le suivi d'installation (dashboard) sur un run PASSÉ : le
        dernier par défaut, ou un choix dans l'historique. Utile quand le
        dashboard s'est fermé et qu'on veut reprendre l'analyse."""
        from script.todo import qemu_install_monitor as mon

        runs = mon.list_install_runs()
        if not runs:
            print(t("No install run found in history."))
            return
        print(f"\n{t('Install runs (most recent first):')}")
        for i, r in enumerate(runs, 1):
            names = ", ".join(v.get("name", "?") for v in r["vms"])
            star = " *" if i == 1 else ""
            print(
                f"  [{i}] {r['label']} — {len(r['vms'])} VM{star}\n"
                f"        {names}"
            )
        sel = input(t("Choice (number, blank = last): ")).strip()
        run = runs[0]
        if sel:
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(runs):
                    run = runs[idx]
                else:
                    print(t("Invalid selection."))
                    return
            except ValueError:
                print(t("Invalid selection."))
                return
        self._qemu_open_monitor(run["manifest"])

    def _qemu_open_monitor(self, manifest):
        """Ouvre le dashboard sur un manifeste, en installant Textual au
        besoin. Deux entrées y mènent — l'historique et la reprise proposée
        avant un déploiement — d'où une seule définition."""
        from script.todo import qemu_install_monitor as mon

        try:
            mon.run_monitor(manifest)
        except ImportError:
            from script.todo import textual_setup

            if textual_setup.ensure():
                mon.run_monitor(manifest)
        except Exception as exc:
            print(f"{t('Command failed: ')}{exc}")

    def _qemu_active_install(self):
        """Propose de reprendre le suivi quand une installation tourne encore.

        Les installs partent détachées (`setsid -f`) : fermer le terminal ne
        les arrête pas, mais faisait perdre la seule vue dessus, et la seule
        issue connue était de tout effacer pour recommencer.

        True si l'on ne doit PAS enchaîner sur un déploiement."""
        try:
            from script.todo import qemu_install_monitor as mon

            run = mon.active_run()
        except Exception:
            return False
        if not run:
            return False
        names = ", ".join(v.get("name", "?") for v in run["vms"])
        print(
            f"\n⏳ {t('An install is still running:')} {run['label']} — "
            f"{run['active']}/{run['total']} {t('VM(s) in progress')}"
        )
        print(f"     {names}")
        if run.get("idle") is not None:
            # Un silence prolongé trahit un run mort dont le marqueur de sortie
            # ne viendra jamais : l'utilisateur tranche mieux que nous.
            print(
                f"     {t('Last activity:')} {mon._fmt_secs(int(run['idle']))}"
            )
        print(f"\n  [1] {t('Reopen that monitoring')} *")
        print(f"  [2] {t('Deploy anyway (new run)')}")
        print(f"  [0] {t('Back')}")
        sel = input(t("Choice (number, blank = reopen): ")).strip()
        if sel == "2":
            return False
        if sel != "0":
            self._qemu_open_monitor(run["manifest"])
        return True

    def _qemu_choose_cli_browser(self):
        """Offre la LISTE des navigateurs CLI installés, plus une option pour
        en INSTALLER un autre, et renvoie celui choisi, sinon None."""
        from script.todo.qemu_install_monitor import CLI_BROWSERS

        available = [b for b in CLI_BROWSERS if shutil.which(b)]
        if not available:
            return self._qemu_install_cli_browser()
        print(f"\n{t('Which browser to view the page?')}")
        for i, b in enumerate(available, 1):
            print(f"  [{i}] {b}{' *' if i == 1 else ''}")
        print(f"  [i] {t('Install another browser')}")
        sel = input(t("Choice (number, blank = first): ")).strip().lower()
        if sel == "i":
            return self._qemu_install_cli_browser()
        if not sel:
            return available[0]
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(available):
                return available[idx]
        except ValueError:
            pass
        return available[0]

    def _qemu_install_cli_browser(self):
        """Demande QUEL navigateur CLI installer, affiche la commande adaptée
        à l'OS, l'exécute après validation. Renvoie le binaire installé ou
        None."""
        from script.todo.qemu_install_monitor import (
            INSTALLABLE_BROWSERS,
            browser_install_command,
        )

        print(f"\n{t('Which browser to install?')}")
        for i, (b, desc) in enumerate(INSTALLABLE_BROWSERS, 1):
            print(f"  [{i}] {desc}{' *' if i == 1 else ''}")
        sel = input(t("Choice (number, blank = w3m): ")).strip()
        browser = INSTALLABLE_BROWSERS[0][0]
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(INSTALLABLE_BROWSERS):
                browser = INSTALLABLE_BROWSERS[idx][0]
        except ValueError:
            pass
        cmd = browser_install_command(browser)
        if not cmd:
            print(t("Unknown package manager; install it manually."))
            return None
        printable = " ".join(cmd)
        print(f"{t('Command:')} {printable}")
        if not self._is_yes(input(t("Install now? (y/N): "))):
            return None
        os.system(printable)
        return browser if shutil.which(browser) else None

    # ------------------------------------------------------------------ #
    # Redimensionnement du disque d'une VM
    # ------------------------------------------------------------------ #
    # « <source file='…'/> » couvre les disques, les cdrom ET les
    # « <backingStore> » d'une chaîne. Le nvram porte un attribut
    # « template » : l'attendre sans attribut le manquait, et c'est le
    # fichier le plus facile à perdre.
    _RE_SOURCE_FILE = re.compile(r"<source file='([^']+)'")
    _RE_NVRAM = re.compile(r"<nvram[^>]*>([^<]+)</nvram>")
    _RE_LIBVIRT_PATH = re.compile(r"""/var/lib/libvirt/[^,\0\s'"]+""")

    def _qemu_referenced_files(self, domains=None):
        """{chemin: domaine} — TOUT ce que les domaines référencent.

        L'autorité est libvirt, jamais le nom du fichier. Un domaine renommé
        garde le nom de fichier d'avant : juger sur le nom fait passer le
        disque d'une VM EN MARCHE pour un orphelin, et offre ses trois
        fichiers — disque, seed, nvram — au « rm -f ».

        Les deux vues, persistante et vivante, pour la raison dite dans
        `_qemu_dumpxml`.
        """
        refs = {}
        for nom in (
            domains if domains is not None else self._qemu_list_domains()
        ):
            for inactive in (True, False):
                xml = self._qemu_dumpxml(nom, inactive=inactive)
                if not xml:
                    continue
                trouves = self._RE_SOURCE_FILE.findall(
                    xml
                ) + self._RE_NVRAM.findall(xml)
                for chemin in trouves:
                    refs.setdefault(chemin.strip(), nom)
        return refs

    @classmethod
    def _qemu_files_in_use(cls):
        """Chemins de /var/lib/libvirt cités par un processus EN COURS.

        Contrôle INDÉPENDANT de libvirt : un qemu lancé à la main, ou une
        définition que libvirt aurait perdue, tient son disque ouvert quand
        même. Devant un « rm -f » de 63 Go, deux sources valent mieux qu'une.
        Sans privilège : /proc/<pid>/cmdline se lit, et le qemu d'une VM y
        porte ses disques, son seed et son nvram.
        """
        vus = set()
        for entree in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                with open(entree, "rb") as fh:
                    brut = fh.read().decode("utf-8", "replace")
            except OSError:
                continue
            for chemin in cls._RE_LIBVIRT_PATH.findall(brut):
                # Un chemin qui n'existe pas n'est pas un fichier tenu
                # ouvert : la ligne de commande d'un processus quelconque
                # peut contenir n'importe quoi (ce script lui-même y met son
                # motif). On ne protège que du réel.
                if os.path.exists(chemin):
                    vus.add(chemin)
        return vus

    def _qemu_vm_own_files(self, name):
        """Fichiers de CETTE VM, et d'elle seule : disques et seed.

        Demandés à libvirt, jamais déduits du nom. Une VM renommée garde le
        nom de fichier d'avant : « rm <nom>.qcow2 » ne trouvait alors rien et
        laissait 63 Go derrière lui — le même défaut que dans le nettoyage,
        pris par l'autre bout.

        Un fichier partagé avec un AUTRE domaine (image de fond d'une chaîne
        de qcow2) est écarté : l'effacer creverait la voisine. Le nvram aussi,
        parce que « virsh undefine --nvram » s'en charge déjà.
        """
        miens = set(self._qemu_referenced_files([name]))
        voisins = set(
            self._qemu_referenced_files(
                [d for d in self._qemu_list_domains() if d != name]
            )
        )
        return sorted(
            chemin
            for chemin in miens - voisins
            if chemin.startswith("/var/lib/libvirt/")
            and not chemin.endswith(".fd")
        )

    def _qemu_split_orphans(self, candidats):
        """(orphelins, protégés) — un fichier référencé n'est JAMAIS orphelin.

        `candidats` et le retour sont des (taille, chemin, motif). Les
        protégés portent, à la place du motif, ce qui les retient.
        """
        refs = self._qemu_referenced_files()
        ouverts = self._qemu_files_in_use()
        orphelins, proteges = [], []
        for taille, chemin, motif in candidats:
            porteur = refs.get(chemin)
            if not porteur and chemin in ouverts:
                porteur = t("a running process")
            if porteur:
                proteges.append((taille, chemin, porteur))
            else:
                orphelins.append((taille, chemin, motif))
        return orphelins, proteges

    @staticmethod
    def _qemu_c_env():
        """Environnement forçant LC_ALL=C : la sortie des outils (virsh,
        sgdisk, resize2fs, dumpe2fs…) reste en ANGLAIS quelle que soit la
        locale de l'hôte. Sinon « running » devient « en cours d'exécution »
        (fr) et les comparaisons/parsing d'état cassent."""
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        return env

    @staticmethod
    def _qemu_domstate(name):
        """État libvirt de la VM (« running », « shut off », …) ou ''."""
        try:
            res = subprocess.run(
                virsh_argv("domstate", name),
                capture_output=True,
                text=True,
                timeout=15,
                env=QemuManageMixin._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return res.stdout.strip() if res.returncode == 0 else ""

    @staticmethod
    def _qemu_domname(name):
        """Nom canonique de la VM (si on a fourni un ID numérique, le
        résout ; sinon renvoie tel quel). Utile car un ID disparaît une
        fois la VM éteinte."""
        if not str(name).isdigit():
            return name
        try:
            res = subprocess.run(
                virsh_argv("domname", str(name)),
                capture_output=True,
                text=True,
                timeout=15,
                env=QemuManageMixin._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return name
        out = res.stdout.strip()
        return out if res.returncode == 0 and out else name

    def _qemu_shutdown_wait(self, name, timeout=120):
        """Arrête la VM par SIGNAL (ACPI power-button, puis agent invité) et
        attend qu'elle soit « shut off » en affichant le temps restant du
        timeout. Si l'arrêt gracieux traîne, propose un arrêt forcé (destroy).
        Renvoie True si la VM est bien éteinte."""
        name = self._qemu_domname(name)
        if self._qemu_domstate(name) == "shut off":
            return True
        # --mode acpi,agent : envoie le SIGNAL d'extinction (bouton ACPI) puis
        # tente l'agent invité si présent — plus fiable qu'un arrêt brutal.
        cmd = (
            f"{sudo_prefix()}virsh --connect {URI} "
            f"shutdown {shlex.quote(name)}"
            " --mode acpi,agent"
        )
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        print(
            f"{t('Waiting for the VM to shut down...')} "
            f"({t('timeout')}: {timeout} s)"
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._qemu_domstate(name) == "shut off":
                # Efface la ligne de compte à rebours puis confirme.
                print(f"\r{' ' * 40}\r✅ {name}: {t('VM is off.')}")
                return True
            remaining = int(deadline - time.time())
            print(
                f"\r  ⏳ {t('shutting down')}… "
                f"{remaining:>3d} s {t('remaining')}",
                end="",
                flush=True,
            )
            time.sleep(2)
        print()  # newline après le compte à rebours
        # Arrêt gracieux trop long : proposer un arrêt forcé.
        if self._is_yes(
            input(
                t(
                    "Graceful shutdown timed out. Force off (destroy)? "
                    "(y/N): "
                )
            )
        ):
            cmd = (
                f"{sudo_prefix()}virsh --connect {URI} "
                f"destroy {shlex.quote(name)}"
            )
            print(f"{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)
            time.sleep(2)
            return self._qemu_domstate(name) == "shut off"
        return False

    @staticmethod
    def _qemu_main_disk(name):
        """Chemin du disque PRINCIPAL (qcow2) de la VM via domblklist. On
        ignore le seed cloud-init (…-seed.iso, en lecture seule)."""
        try:
            res = subprocess.run(
                virsh_argv("domblklist", name, "--details"),
                capture_output=True,
                text=True,
                timeout=15,
                env=QemuManageMixin._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        disks = []
        for line in res.stdout.splitlines():
            parts = line.split()
            # Colonnes : Type Device Target Source
            if len(parts) >= 4 and parts[1] == "disk" and parts[3] != "-":
                disks.append(parts[3])
        # Le disque de travail est le .qcow2 (le seed est un .iso).
        for d in disks:
            if d.endswith(".qcow2"):
                return d
        return disks[0] if disks else None

    @staticmethod
    def _qemu_disk_virtual_bytes(disk):
        """Taille VIRTUELLE (octets) du disque via « qemu-img info --json »."""
        try:
            # -U (--force-share) : lit même si la VM tourne (libvirt tient le
            # lock d'écriture). Sans ça : « Failed to get shared write lock ».
            res = subprocess.run(
                ["sudo", "qemu-img", "info", "-U", "--output=json", disk],
                capture_output=True,
                text=True,
                timeout=20,
            )
            data = json.loads(res.stdout)
            return int(data.get("virtual-size", 0))
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0

    def _qemu_resize_disk(self):
        """Redimensionne le disque d'une VM : affiche l'espace actuel, demande
        +NG / -NG / taille cible, applique (à chaud si possible pour agrandir),
        puis propose d'étendre le système de fichiers invité."""
        self._qemu_list_vms()
        print()
        name = input(t("VM name to resize: ")).strip()
        if not name:
            print(t("VM name is required!"))
            return
        if not self._qemu_domain_exists(name):
            print(f"{name}: {t('VM not found.')}")
            return
        # Résout tout de suite le NOM canonique (VM encore allumée -> l'ID est
        # résoluble). Après extinction, un ID numérique disparaît : « virsh
        # start 32 » échouerait. On travaille désormais avec le nom.
        name = self._qemu_domname(name)
        disk = self._qemu_main_disk(name)
        if not disk:
            print(t("Main disk not found for this VM."))
            return

        # 1) Espace actuel (virtuel + réel) + df invité si joignable.
        print(f"\n{t('Current disk:')} {disk}")
        # -U : lecture sûre même VM allumée (sinon « shared write lock »).
        self.execute.exec_command_live(
            f"{sudo_prefix()}qemu-img info -U {shlex.quote(disk)}",
            source_erplibre=False,
        )
        cur_bytes = self._qemu_disk_virtual_bytes(disk)
        cur_gb = cur_bytes / (1 << 30)
        state = self._qemu_domstate(name)
        if cur_bytes <= 0:
            print(t("Could not read current disk size; aborting."))
            print(f"{t('VM state:')} {state or '?'}")
            return
        print(f"{t('Current virtual size:')} {cur_gb:.1f} G")
        print(f"{t('VM state:')} {state or '?'}")

        # Espace HÔTE : le qcow2 est creux (sparse), donc on PEUT fixer une
        # taille virtuelle plus grande que l'espace réel — mais si la VM la
        # remplit, l'hôte tombe à court. Max « soutenable » ≈ taille réelle
        # actuelle + espace libre de l'hôte. On l'AFFICHE (avertissement, pas
        # de blocage) pour guider le choix.
        g = 1 << 30
        _virt, actual = self._qemu_disk_sizes(disk)
        try:
            free = shutil.disk_usage(os.path.dirname(disk)).free
        except OSError:
            free = 0
        max_safe_gb = (actual + free) / g if free else 0
        if max_safe_gb:
            print(
                f"{t('Host free space:')} {free / g:.1f} G  ·  "
                f"{t('max sustainable total (before host full):')} "
                f"~{max_safe_gb:.1f} G"
            )

        # 2) Nouvelle taille : +NG (agrandir), -NG (réduire) ou NG (cible).
        guide = t(
            "Enter +NG to grow, -NG to shrink, or NG for a target size "
            "(e.g. +20G, -10G, 60G)."
        )
        print(f"\n{guide}")
        raw = input(t("Resize: ")).strip().upper().replace("G", "")
        try:
            if raw.startswith("+"):
                new_gb = cur_gb + float(raw[1:])
            elif raw.startswith("-"):
                new_gb = cur_gb - float(raw[1:])
            else:
                new_gb = float(raw)
        except ValueError:
            print(t("Invalid size."))
            return
        if new_gb <= 0:
            print(t("Invalid size."))
            return
        new_gb = round(new_gb, 1)
        if abs(new_gb - cur_gb) < 0.05:
            print(t("No change."))
            return
        shrink = new_gb < cur_gb
        print(f"\n{t('New virtual size:')} {cur_gb:.1f} G -> {new_gb:.1f} G")
        # Avertissement (NON bloquant) : agrandir au-delà de ce que l'hôte
        # peut soutenir -> surallocation, l'hôte se remplira si la VM utilise
        # tout l'espace.
        if not shrink and max_safe_gb and new_gb > max_safe_gb:
            over = new_gb - max_safe_gb
            msg1 = t("Beyond host capacity by ~%.1f G — overcommit.") % over
            msg2 = (
                t(
                    "The qcow2 is thin: fine until the VM fills it, then the "
                    "host disk runs out. Max sustainable: ~%.1f G."
                )
                % max_safe_gb
            )
            print(f"⚠  {msg1}")
            print(f"   {msg2}")

        # 3) Application selon agrandir/réduire et l'état de la VM.
        was_shut_down = False  # la VM a-t-elle été éteinte pour l'occasion ?
        cmd = (
            None  # commande d'AGRANDISSEMENT (la réduction a son propre flux)
        )
        if shrink:
            # DANGER : qcow2 --shrink ne réduit PAS le FS invité -> perte de
            # données si le FS dépasse la cible. VM éteinte obligatoire.
            danger = t(
                "SHRINKING is DANGEROUS: the guest filesystem is NOT shrunk. "
                "Data beyond the new size is LOST. Shrink the guest FS FIRST, "
                "and only then shrink here."
            )
            print(f"⚠  {danger}")
            if state != "shut off":
                if not self._is_yes(
                    input(
                        t(
                            "The VM must be off. Shut it down and retry? "
                            "(y/N): "
                        )
                    )
                ):
                    print(t("Cancelled."))
                    return
                if not self._qemu_shutdown_wait(name):
                    print(t("VM is still not off; aborting."))
                    return
                state = "shut off"
                was_shut_down = True
            if not self._is_yes(
                input(t("Type y to confirm you understand the risk (y/N): "))
            ):
                print(t("Cancelled."))
                return
            # Réduction SÛRE (qemu-nbd : réduit FS + partition + GPT, avec
            # sauvegarde optionnelle restaurée en cas d'échec).
            if not self._qemu_safe_shrink(name, disk, new_gb):
                self._qemu_offer_start(name, was_shut_down)
                return
        elif state == "running":
            # Agrandissement À CHAUD : le disque virtuel grossit, le FS invité
            # devra être étendu ensuite.
            cmd = (
                f"{sudo_prefix()}virsh --connect {URI} "
                f"blockresize {shlex.quote(name)} "
                f"{shlex.quote(disk)} {new_gb:g}G"
            )
        else:
            cmd = (
                f"{sudo_prefix()}qemu-img resize"
                f" {shlex.quote(disk)} {new_gb:g}G"
            )

        # 4) Agrandissement : exécuter la commande + proposer d'étendre le FS.
        if cmd is not None:
            print(f"{t('Will execute:')} {cmd}")
            if self.execute.exec_command_live(cmd, source_erplibre=False) != 0:
                print(f"❌ {t('Resize failed (see error above).')}")
                return
            print(f"✅ {t('Virtual disk resized.')}")
            if self._is_yes(
                input(t("Grow the guest filesystem now (over SSH)? (y/N): "))
            ):
                self._qemu_grow_guest_fs(name)

        # 5) La VM a été éteinte pour l'opération : proposer de la redémarrer
        #    (l'utilisateur peut ainsi TESTER avant de décider du backup).
        self._qemu_offer_start(name, was_shut_down)

        # 6) Réduction réussie AVEC sauvegarde : proposer de l'effacer une fois
        #    la VM testée (défaut : NON -> on garde le backup par prudence).
        bak = getattr(self, "_shrink_backup", None)
        if shrink and bak and os.path.exists(bak):
            print(f"\n{t('A disk backup was kept:')} {bak}")
            if self._is_yes(input(t("Delete this backup now? (y/N): "))):
                subprocess.run(["sudo", "rm", "-f", bak], check=False)
                print(t("Backup deleted."))
            else:
                print(t("Backup kept (delete later via Clean up QEMU)."))
            self._shrink_backup = None

    def _qemu_offer_start(self, name, was_shut_down):
        """Si la VM a été éteinte pour l'opération, le noter et proposer de la
        redémarrer (sinon ne rien demander)."""
        if not was_shut_down:
            return
        print(f"\nℹ  {t('The VM was shut down for the resize.')}")
        if self._is_yes(input(t("Start the VM now? (y/N): "))):
            # `name` est déjà le nom canonique : « virsh start <id> »
            # échouerait car l'ID disparaît quand la VM est éteinte.
            cmd = (
                f"{sudo_prefix()}virsh --connect {URI} "
                f"start {shlex.quote(name)}"
            )
            print(f"{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)

    # Le nom du binaire n'est presque jamais celui du paquet. Ces cinq-là
    # portent le même nom dans les quatre familles.
    _SHRINK_PKG = {
        "e2fsck": "e2fsprogs",
        "resize2fs": "e2fsprogs",
        "dumpe2fs": "e2fsprogs",
        "partprobe": "parted",
        "lsblk": "util-linux",
        "blockdev": "util-linux",
    }
    # Les deux qui changent de famille en famille : sgdisk vit dans « gdisk »
    # chez Debian et Fedora, dans « gptfdisk » chez Arch et openSUSE, et
    # qemu-nbd porte quatre noms de paquet différents.
    _SHRINK_PKG_FAMILY = {
        "apt-get": {"sgdisk": "gdisk", "qemu-nbd": "qemu-utils"},
        "dnf": {"sgdisk": "gdisk", "qemu-nbd": "qemu-img"},
        "pacman": {"sgdisk": "gptfdisk", "qemu-nbd": "qemu-img"},
        "zypper": {"sgdisk": "gptfdisk", "qemu-nbd": "qemu-tools"},
    }

    def _qemu_install_shrink_tools(self, manquants):
        """Poser les paquets qui fournissent les outils manquants.

        Rend la liste de ce qui manque ENCORE, relue sur le disque : vide si
        tout est là. Un refus, un gestionnaire de paquets inconnu ou une
        installation en échec la rendent non vide, et l'appelant renonce.
        """
        paquets, inconnus = todo_install.resolve(
            manquants,
            commun=self._SHRINK_PKG,
            par_famille=self._SHRINK_PKG_FAMILY,
        )
        if inconnus:
            print(
                f"  ⚠ {t('No package known here for:')} {', '.join(inconnus)}"
            )
        status = todo_install.ask_and_install(
            self.execute,
            todo_install.install_command(paquets),
            t("Install them? (y/N): "),
            self._is_yes,
        )
        if status:
            print(f"  {t('Error installing the tools: ')}{status}")
        reste = [b for b in self._SHRINK_TOOLS if not shutil.which(b)]
        if not reste:
            # Sans cette ligne, la sortie du gestionnaire de paquets est
            # suivie directement de la question suivante, qui porte sur tout
            # autre chose : rien ne dit que l'installation a abouti ni qu'on
            # a changé d'étape.
            print(f"  ✅ {t('Tools installed; on with the shrink.')}")
        return reste

    @staticmethod
    def _qemu_backup_need_and_free(disk):
        """(besoin, libre) en octets pour la copie de sauvegarde du disque.

        Le besoin est la taille ALLOUÉE et non la taille apparente :
        « cp --sparse=always » ne recopie pas les trous d'un qcow2. C'est une
        borne haute — « --reflink=auto » rend la copie presque gratuite sur
        btrfs et XFS — mais rien ne garantit le reflink, et se tromper par
        excès est le bon sens ici : une copie qui manque de place s'arrête à
        mi-chemin et laisse un .bak tronqué.
        """
        besoin = os.stat(disk).st_blocks * 512
        libre = shutil.disk_usage(os.path.dirname(disk) or ".").free
        return besoin, libre

    def _qemu_ask_backup(self, disk):
        """Proposer la sauvegarde du disque, chiffres en main. True si oui.

        Les deux tailles passent AVANT la question : une copie qui ne tient
        pas s'arrête à mi-course et laisse un .bak tronqué sur un système de
        fichiers désormais plein. Quand la place manque, le défaut bascule à
        NON — une entrée distraite ne doit pas remplir le disque — sans pour
        autant décider à la place de l'opérateur, qui peut insister.
        """
        besoin, libre = self._qemu_backup_need_and_free(disk)
        print(
            f"\n{t('A backup doubles the space used:')}"
            f" {self._human_size(besoin)} — {t('free here:')}"
            f" {self._human_size(libre)}"
        )
        if libre > besoin * 1.05:
            return self._is_yes_default_yes(
                input(t("Back up the disk before shrinking? (Y/n): "))
            )
        print(f"⚠  {t('Not enough free space for a full backup.')}")
        return self._is_yes(
            input(
                t(
                    "Back up anyway, at the risk of filling the disk?"
                    " (y/N): "
                )
            )
        )

    def _qemu_safe_shrink(self, name, disk, new_gb):
        """Réduit le disque SANS casser l'OS, via qemu-nbd + resize2fs +
        sgdisk (sans libguestfs) : on réduit le FS (ext), puis la partition,
        puis le conteneur qcow2, puis on répare la GPT de secours. Une COPIE
        .bak est faite AVANT ; en cas d'échec on RESTAURE -> jamais de
        corruption. ext2/3/4 uniquement. Renvoie True si réduit."""
        import math

        missing = [b for b in self._SHRINK_TOOLS if not shutil.which(b)]
        if missing:
            print(
                f"{t('Missing tools for safe shrink:')} {', '.join(missing)}"
            )
            missing = self._qemu_install_shrink_tools(missing)
        if missing:
            print(
                f"{t('Still missing, safe shrink cancelled:')}"
                f" {', '.join(missing)}"
            )
            return False
        target = int(round(new_gb * (1 << 30)))
        # Sauvegarde OPTIONNELLE (défaut OUI) : permet de restaurer en cas
        # d'échec, et de tester la VM avant de la supprimer (proposé à la fin).
        self._shrink_backup = None
        bak = None
        if self._qemu_ask_backup(disk):
            bak = f"{disk}.bak"
            print(f"\n{t('Backing up the disk before shrinking…')}")
            if (
                subprocess.run(
                    [
                        "sudo",
                        "cp",
                        "--reflink=auto",
                        "--sparse=always",
                        disk,
                        bak,
                    ]
                ).returncode
                != 0
            ):
                print(t("Backup failed; aborting."))
                return False
        else:
            print(
                f"⚠  {t('No backup: a failure could leave the disk broken.')}"
            )
        subprocess.run(["sudo", "modprobe", "nbd", "max_part=16"], check=False)
        dev = None
        try:
            dev = self._qemu_nbd_connect(disk)
            if not dev:
                print(t("Could not attach the disk (nbd); aborting."))
                return self._qemu_shrink_revert(bak, disk, changed=False)
            part, start, fstype = self._qemu_root_part(dev)
            if not part:
                print(t("Could not detect the partition to shrink; aborting."))
                return self._qemu_shrink_revert(bak, disk, changed=False)
            if not fstype.startswith("ext"):
                print(
                    f"{t('Only ext2/3/4 can be shrunk safely; aborting.')}"
                    f" ({fstype})"
                )
                return self._qemu_shrink_revert(bak, disk, changed=False)
            n = self._qemu_part_number(dev, part)
            info = self._qemu_part_info(dev, n)
            # fsck AVANT toute opération.
            subprocess.run(["sudo", "e2fsck", "-f", "-y", part], check=False)
            bs = self._qemu_fs_blocksize(part)
            # Cibles (octets), en gardant 2 Mio pour la GPT de secours + marge.
            part_start_b = start * self._SECT
            max_fs_b = target - part_start_b - 4 * self._MiB
            if max_fs_b <= 0:
                print(t("Target size too small for this layout; aborting."))
                return self._qemu_shrink_revert(bak, disk, changed=False)
            min_blocks = self._qemu_fs_min_blocks(part)
            if min_blocks and min_blocks * bs > max_fs_b:
                print(t("Not enough used-space margin to shrink; aborting."))
                return self._qemu_shrink_revert(bak, disk, changed=False)
            fs_target_mib = max_fs_b // self._MiB
            print(
                f"\n{t('Shrinking guest ext filesystem')} {part} "
                f"-> {fs_target_mib} MiB…"
            )
            if (
                subprocess.run(
                    ["sudo", "resize2fs", part, f"{fs_target_mib}M"]
                ).returncode
                != 0
            ):
                print(t("resize2fs failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            # Fin de partition = début + taille RÉELLE du FS + 1 Mio, alignée.
            fs_bytes = self._qemu_fs_blocks(part) * bs
            new_end = start + int(
                math.ceil((fs_bytes + self._MiB) / self._SECT)
            )
            new_end = ((new_end + 2047) // 2048) * 2048 - 1  # align 2048
            if (new_end + 34) * self._SECT > target:
                print(t("Internal size check failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            # Réécrit la partition (mêmes type/UUID/nom -> PARTUUID préservé).
            print(f"{t('Shrinking the partition…')} ({part})")
            subprocess.run(["sudo", "sgdisk", "-d", n, dev], check=False)
            rc = subprocess.run(
                [
                    "sudo",
                    "sgdisk",
                    "-n",
                    f"{n}:{start}:{new_end}",
                    "-t",
                    f"{n}:{info['type']}",
                    "-u",
                    f"{n}:{info['uuid']}",
                    "-c",
                    f"{n}:{info['name']}",
                    dev,
                ]
            ).returncode
            if rc != 0:
                print(t("Partition rewrite failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            subprocess.run(
                ["sudo", "partprobe", dev], check=False, capture_output=True
            )
            # Détache puis tronque le conteneur qcow2.
            self._qemu_nbd_disconnect(dev)
            dev = None
            print(f"{t('Shrinking the qcow2 container…')} {new_gb:g}G")
            if (
                subprocess.run(
                    [
                        "sudo",
                        "qemu-img",
                        "resize",
                        "--shrink",
                        disk,
                        f"{new_gb:g}G",
                    ]
                ).returncode
                != 0
            ):
                print(t("Container shrink failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            # Répare la GPT de secours (fin du disque) + fsck final.
            dev = self._qemu_nbd_connect(disk)
            if dev:
                subprocess.run(["sudo", "sgdisk", "-e", dev], check=False)
                subprocess.run(
                    ["sudo", "partprobe", dev],
                    check=False,
                    capture_output=True,
                )
                p2 = self._qemu_root_part(dev)[0]
                if p2:
                    subprocess.run(
                        ["sudo", "e2fsck", "-f", "-y", p2], check=False
                    )
                self._qemu_nbd_disconnect(dev)
                dev = None
            self._shrink_backup = bak  # proposé à la suppression après le boot
            if bak:
                print(f"✅ {t('Disk safely shrunk. Backup kept at:')} {bak}")
            else:
                print(f"✅ {t('Disk safely shrunk.')}")
            return True
        finally:
            if dev:
                self._qemu_nbd_disconnect(dev)

    def _qemu_shrink_revert(self, bak, disk, changed):
        """Restaure le disque depuis la sauvegarde si on l'a modifié (changed)
        et qu'une sauvegarde existe ; sinon retire la sauvegarde inutile.
        Renvoie False (la réduction a échoué)."""
        if changed and bak:
            print(t("Restoring the original disk from backup…"))
            subprocess.run(["sudo", "mv", "-f", bak, disk], check=False)
        elif changed and not bak:
            print(
                f"⚠  {t('No backup to restore; run fsck on the disk before use.')}"
            )
        elif bak:
            subprocess.run(["sudo", "rm", "-f", bak], check=False)
        return False

    @staticmethod
    def _qemu_nbd_connect(disk):
        """Attache `disk` à un /dev/nbdN libre et renvoie le chemin, ou None.
        Attend que les sous-périphériques de partition (nbdNpM) APPARAISSENT
        (sinon lsblk/resize2fs ne voient rien juste après le connect)."""
        for i in range(16):
            dev = f"/dev/nbd{i}"
            # /sys/block/nbdN/pid absent => device libre.
            if os.path.exists(f"/sys/block/nbd{i}/pid"):
                continue
            rc = subprocess.run(
                ["sudo", "qemu-nbd", "-c", dev, disk],
                capture_output=True,
                text=True,
            ).returncode
            if rc != 0:
                continue
            base = f"nbd{i}"
            for _ in range(15):
                subprocess.run(
                    ["sudo", "partprobe", dev],
                    check=False,
                    capture_output=True,
                )
                time.sleep(1)
                if any(
                    os.path.exists(f"/sys/class/block/{base}p{n}")
                    for n in range(1, 32)
                ):
                    break
            return dev
        return None

    @staticmethod
    def _qemu_nbd_disconnect(dev):
        subprocess.run(["sudo", "qemu-nbd", "-d", dev], check=False)
        time.sleep(1)

    @staticmethod
    def _qemu_root_part(dev):
        """(partition la plus grosse, secteur de début, type FS) du disque nbd.
        (None, 0, '') si introuvable. Format lsblk -P (paires) : robuste aux
        colonnes VIDES — juste après le connect, FSTYPE peut être vide, et un
        parsing positionnel décalait/ignorait alors toutes les partitions."""
        import re

        try:
            res = subprocess.run(
                ["lsblk", "-Pbno", "NAME,SIZE,TYPE,FSTYPE", dev],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None, 0, ""
        best, best_sz, best_fs = None, -1, ""
        for line in res.stdout.splitlines():
            d = dict(re.findall(r'(\w+)="([^"]*)"', line))
            if d.get("TYPE") != "part":
                continue
            try:
                size = int(d.get("SIZE") or 0)
            except ValueError:
                size = 0
            if size > best_sz:
                best, best_sz, best_fs = (
                    d.get("NAME"),
                    size,
                    d.get("FSTYPE", ""),
                )
        if not best:
            return None, 0, ""
        part = f"/dev/{best}"
        try:
            start = int(open(f"/sys/class/block/{best}/start").read().strip())
        except OSError:
            start = 0
        if not best_fs:
            # FSTYPE pas encore en cache : sonder directement avec blkid.
            best_fs = subprocess.run(
                ["sudo", "blkid", "-o", "value", "-s", "TYPE", part],
                capture_output=True,
                text=True,
            ).stdout.strip()
        return part, start, best_fs

    @staticmethod
    def _qemu_part_number(dev, part):
        """Numéro de partition (ex. « 1 ») depuis /dev/nbd0p1."""
        return part[len(dev) :].lstrip("p")

    @staticmethod
    def _qemu_part_info(dev, n):
        """{type, uuid, name} d'une partition via « sgdisk -i »."""
        info = {"type": "", "uuid": "", "name": ""}
        res = subprocess.run(
            ["sudo", "sgdisk", "-i", n, dev],
            capture_output=True,
            text=True,
            env=QemuManageMixin._qemu_c_env(),
        )
        for line in res.stdout.splitlines():
            low = line.lower()
            if low.startswith("partition guid code"):
                info["type"] = line.split(":", 1)[1].split()[0]
            elif low.startswith("partition unique guid"):
                info["uuid"] = line.split(":", 1)[1].strip()
            elif low.startswith("partition name"):
                info["name"] = line.split(":", 1)[1].strip().strip("'")
        return info

    @staticmethod
    def _qemu_fs_blocksize(part):
        res = subprocess.run(
            ["sudo", "dumpe2fs", "-h", part],
            capture_output=True,
            text=True,
            env=QemuManageMixin._qemu_c_env(),
        )
        for line in res.stdout.splitlines():
            if line.startswith("Block size:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        return 4096

    @staticmethod
    def _qemu_fs_blocks(part):
        res = subprocess.run(
            ["sudo", "dumpe2fs", "-h", part],
            capture_output=True,
            text=True,
            env=QemuManageMixin._qemu_c_env(),
        )
        for line in res.stdout.splitlines():
            if line.startswith("Block count:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        return 0

    @staticmethod
    def _qemu_fs_min_blocks(part):
        """Taille minimale (blocs) du FS via « resize2fs -P »."""
        res = subprocess.run(
            ["sudo", "resize2fs", "-P", part],
            capture_output=True,
            text=True,
            env=QemuManageMixin._qemu_c_env(),
        )
        for tok in res.stdout.replace(":", " ").split():
            if tok.isdigit():
                return int(tok)
        return 0

    def _qemu_grow_guest_fs(self, name):
        """Étend la partition racine + le FS invité. Essaie SSH (IP résolue
        avec BATTEMENT, le boot émulé étant lent) ; en cas d'absence d'IP ou
        d'échec SSH, propose le repli par CONSOLE SÉRIE (commande à coller)."""
        remote = self._GROW_FS_REMOTE
        real = self._qemu_domname(name)
        # 1) SSH : IP résolue avec BATTEMENT (parallèle, boot émulé lent)
        # plutôt qu'un simple timeout court qui abandonnait trop tôt.
        ip = self._qemu_resolve_ips([real], timeout=300).get(real)
        if ip:
            opts = (
                "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                "-o ConnectTimeout=15"
            )
            cmd = f"ssh {opts} erplibre@{ip} {shlex.quote(remote)}"
            print(f"{t('Will execute:')} {cmd}")
            if self.execute.exec_command_live(cmd, source_erplibre=False) == 0:
                return
            print(f"⚠  {t('SSH grow failed; trying the guest agent.')}")
        else:
            print(t("No IP; trying the guest agent (no network)."))
        # 2) Agent invité (virtio, SANS réseau) — nécessite qemu-guest-agent
        # dans la VM (installé au déploiement) + guest-exec autorisé.
        res = self._qemu_guest_exec(real, remote)
        if res is not None:
            rc, out = res
            if out.strip():
                print(out.rstrip())
            if rc == 0:
                print(f"✅ {t('Guest filesystem grown via guest agent.')}")
                return
            print(
                f"⚠  {t('Guest agent grow failed; falling back to console.')}"
            )
        else:
            print(
                t("Guest agent unavailable; falling back to serial console.")
            )
        # 3) Console série (commande prête à coller, login interactif).
        self._qemu_grow_via_console(real, remote)

    def _qemu_guest_exec(self, name, script, wait=180):
        """Exécute `script` (sh -c) DANS la VM via l'AGENT INVITÉ (canal
        virtio, sans réseau). Renvoie (code_sortie, sortie) ou None si l'agent
        est indisponible / guest-exec refusé."""
        import base64

        def agent(payload):
            try:
                res = subprocess.run(
                    virsh_argv(
                        "qemu-agent-command", name, json.dumps(payload)
                    ),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            if res.returncode != 0:
                return None
            try:
                return json.loads(res.stdout).get("return")
            except ValueError:
                return None

        if agent({"execute": "guest-ping"}) is None:
            return None
        start = agent(
            {
                "execute": "guest-exec",
                "arguments": {
                    "path": "/bin/sh",
                    "arg": ["-c", script],
                    "capture-output": True,
                },
            }
        )
        if not start or "pid" not in start:
            return None
        pid = start["pid"]
        deadline = time.time() + wait
        print(t("Running via guest agent (no network)…"))
        while time.time() < deadline:
            st = agent(
                {"execute": "guest-exec-status", "arguments": {"pid": pid}}
            )
            if st and st.get("exited"):
                out = ""
                for k in ("out-data", "err-data"):
                    if st.get(k):
                        try:
                            out += base64.b64decode(st[k]).decode(
                                errors="replace"
                            )
                        except Exception:
                            pass
                return st.get("exitcode", 0), out
            time.sleep(2)
        return None

    def _qemu_grow_via_console(self, name, remote):
        """Repli console série : affiche la commande prête à coller puis ouvre
        la console (login interactif erplibre/erplibre — pas d'automatisation
        fiable de la saisie)."""
        print(f"\n{t('Serial console fallback. Log in, then paste:')}")
        print(f"\n  {remote}\n")
        print(f"💡 {t('To leave the console, press Ctrl+] (then Enter).')}")
        print(
            f"👤 {t('Default login (if set at deploy): erplibre / erplibre')}"
        )
        if not self._is_yes(input(t("Open the serial console now? (y/N): "))):
            return
        cmd = (
            f"{sudo_prefix()}virsh --connect {URI} console {shlex.quote(name)}"
        )
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_list_domains(self):
        """Noms des VM libvirt définies (via virsh)."""
        try:
            res = subprocess.run(
                virsh_argv("list", "--all", "--name"),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        return [n for n in res.stdout.split() if n.strip()]

    def _qemu_delete_vm(self):
        """Efface une ou plusieurs VM (arrêt + undefine), disques en option."""
        self._qemu_list_vms()
        print()
        names = self._qemu_list_domains()
        if not names:
            print(t("No VM found."))
            return
        print(f"\n{t('Select VMs to delete:')}")
        for i, n in enumerate(names, 1):
            print(f"  [{i}] {n}")
        print(f"  [all] {t('select all')}")
        raw = input(t("Selection (numbers, or 'all'): ")).strip()
        if not raw:
            print(t("Nothing selected."))
            return
        if raw.lower() in ("all", "*"):
            chosen = list(names)
        else:
            chosen = self._parse_index_selection(raw.lower(), names)
        if not chosen:
            print(t("Nothing selected."))
            return

        del_disks = self._is_yes(
            input(t("Also delete disk images (qcow2 + seed ISO)? (y/N): "))
        )

        print(f"\n{t('Will delete:')} {', '.join(chosen)}")
        if del_disks:
            print(f"  + {t('disk images and seed ISOs')}")
        else:
            print(f"  ({t('disks kept')})")
        if not self._is_yes(input(t("Confirm deletion? (y/N): "))):
            print(t("Cancelled."))
            return

        for name in chosen:
            q = shlex.quote(name)
            # Les fichiers AVANT l'undefine : après, plus de XML à lire.
            fichiers = self._qemu_vm_own_files(name) if del_disks else []
            # Éteindre si en cours, puis retirer la définition (+ nvram si
            # UEFI ; repli sans l'option pour les vieilles versions de virsh).
            cmd = (
                f"{sudo_prefix()}virsh --connect {URI} "
                f"destroy {q} 2>/dev/null; "
                f"{sudo_prefix()}virsh --connect {URI} "
                f"undefine {q} --nvram 2>/dev/null "
                f"|| {sudo_prefix()}virsh --connect {URI} undefine {q}"
            )
            if del_disks and fichiers:
                cmd += "; sudo rm -f " + " ".join(
                    shlex.quote(f) for f in fichiers
                )
            elif del_disks:
                # Rien à effacer : le dire, plutôt que de laisser croire que
                # la place a été rendue.
                print(f"  ⚠ {name} : {t('no disk file found for this VM')}")
            print(f"\n▶ {name}: {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)
        print(f"\n✅ {t('Deletion done.')}")

    @staticmethod
    def _qemu_find_files(directory, pattern):
        """(taille, chemin) des fichiers du répertoire (via sudo find)."""
        try:
            res = subprocess.run(
                [
                    "sudo",
                    "find",
                    directory,
                    "-maxdepth",
                    "1",
                    "-type",
                    "f",
                    "-name",
                    pattern,
                    "-printf",
                    "%s\t%p\n",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        out = []
        for line in res.stdout.splitlines():
            if "\t" in line:
                size, path = line.split("\t", 1)
                out.append((int(size), path))
        return out

    def _cleanup_delete_files(self, title, items, prompt):
        """items : [(taille, chemin)]. Liste, confirme, puis « sudo rm -f »."""
        if not items:
            return
        total = sum(s for s, _ in items)
        print(
            f"\n{title} — {self._human_size(total)}, "
            f"{len(items)} {t('files')} :"
        )
        for size, path in sorted(items, key=lambda o: -o[0]):
            print(f"  {self._human_size(size):>9}  {path}")
        if not self._is_yes(input(prompt)):
            print(t("Cancelled."))
            return
        paths = " ".join(shlex.quote(p) for _, p in items)
        cmd = f"sudo rm -f {paths}"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        print(f"✅ {t('Cleanup done.')}")

    def _qemu_domain_macs(self):
        """MACs de toutes les VM définies (pour repérer les baux périmés)."""
        macs = set()
        for name in self._qemu_list_domains():
            try:
                res = subprocess.run(
                    virsh_argv("domiflist", name),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            macs.update(
                m.lower()
                for m in re.findall(
                    r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", res.stdout
                )
            )
        return macs

    def _qemu_cleanup(self):
        """Repère les restes QEMU orphelins et propose de les effacer."""
        print(f"🧹 {t('Scanning for orphan QEMU files...')}")
        disk_dir = "/var/lib/libvirt/images"
        seed_dir = "/var/lib/libvirt/images/iso"
        nvram_dir = "/var/lib/libvirt/qemu/nvram"
        domains = set(self._qemu_list_domains())

        # 1) Fichiers orphelins : disques / seeds / .part / nvram.
        orphans = []  # (taille, chemin, motif)
        for size, path in self._qemu_find_files(disk_dir, "*.qcow2"):
            if os.path.basename(path)[: -len(".qcow2")] not in domains:
                orphans.append((size, path, t("orphan disk")))
        for size, path in self._qemu_find_files(seed_dir, "*-seed.iso"):
            if os.path.basename(path)[: -len("-seed.iso")] not in domains:
                orphans.append((size, path, t("orphan seed")))
        for size, path in self._qemu_find_files(seed_dir, "*.part"):
            orphans.append((size, path, t("partial download")))
        for size, path in self._qemu_find_files(nvram_dir, "*"):
            stem = re.sub(r"(_VARS)?\.fd$", "", os.path.basename(path))
            if stem not in domains:
                orphans.append((size, path, t("orphan UEFI nvram")))
        # Sauvegardes de disque laissées par un redimensionnement (.qcow2.bak).
        for size, path in self._qemu_find_files(disk_dir, "*.qcow2.bak"):
            orphans.append((size, path, t("disk backup (resize)")))
        # Le nom d'un fichier ne dit RIEN de son usage : c'est libvirt qui
        # sait. Une VM renommée garde le nom de fichier d'avant, et le
        # nettoyage offrait alors son disque de 63 Go au « rm -f » — rapporté.
        orphans, proteges = self._qemu_split_orphans(orphans)
        if proteges:
            print(f"\n{t('Kept (still attached to a VM):')}")
            for size, path, porteur in sorted(proteges, key=lambda o: -o[0]):
                print(
                    f"  {self._human_size(size):>9}  {path}" f"  ← {porteur}"
                )
        if orphans:
            total = sum(o[0] for o in orphans)
            print(f"\n{t('Orphan files:')}")
            for size, path, reason in sorted(orphans, key=lambda o: -o[0]):
                print(f"  {self._human_size(size):>9}  {path}  [{reason}]")
            print(
                f"\n  {t('Total:')} {self._human_size(total)} "
                f"({len(orphans)} {t('files')})"
            )
            if self._is_yes(input(t("Delete these orphan files? (y/N): "))):
                paths = " ".join(shlex.quote(o[1]) for o in orphans)
                cmd = f"sudo rm -f {paths}"
                print(f"{t('Will execute:')} {cmd}")
                self.execute.exec_command_live(cmd, source_erplibre=False)
                print(f"✅ {t('Cleanup done.')}")
            else:
                print(t("Cancelled."))
        else:
            print(f"✅ {t('No orphan files found.')}")

        # 2) Domaines fantômes (définis mais disque manquant).
        self._cleanup_ghost_domains()
        # 3) Doublons d'images nommées par codename (avant /releases/).
        dups = [
            (s, p)
            for s, p, _m in self._qemu_split_orphans(
                [
                    (s, p, "")
                    for s, p in self._qemu_find_files(
                        seed_dir, "*-server-cloudimg-*.img"
                    )
                    if not os.path.basename(p).startswith("ubuntu-")
                ]
            )[0]
        ]
        self._cleanup_delete_files(
            t("Stale codename-named Ubuntu images (duplicates):"),
            dups,
            t("Delete these duplicate images? (y/N): "),
        )
        # 4) Entrées ~/.ssh/config orphelines (erplibre-* sans VM).
        self._cleanup_ssh_config(domains)
        # 5) Baux DHCP périmés.
        self._cleanup_stale_leases()
        # 6) Tout le cache d'images de base (option lourde : re-téléchargement).
        # Une image de base peut servir de FOND à un disque (backingStore) :
        # elle est alors référencée, et l'effacer creverait la VM.
        cached = [
            (s, p)
            for s, p, _m in self._qemu_split_orphans(
                [
                    (s, p, "")
                    for s, p in self._qemu_find_files(seed_dir, "*")
                    if not p.endswith("-seed.iso") and not p.endswith(".part")
                ]
            )[0]
        ]
        self._cleanup_delete_files(
            t("All cached base images (reusable):"),
            cached,
            t("Delete ALL cached base images? (y/N): "),
        )

    def _cleanup_ghost_domains(self):
        """VM définies dont plus aucun disque n'existe -> propose undefine."""
        ghosts = []
        for name in self._qemu_list_domains():
            try:
                res = subprocess.run(
                    virsh_argv("domblklist", name, "--details"),
                    capture_output=True,
                    text=True,
                    timeout=15,
                    env=self._qemu_c_env(),
                )
            except (OSError, subprocess.SubprocessError):
                continue
            srcs = []
            for line in res.stdout.splitlines():
                p = line.split()
                if len(p) >= 4 and p[1] == "disk" and p[3] not in ("-", ""):
                    srcs.append(p[3])
            if srcs and all(
                subprocess.run(
                    ["sudo", "test", "-e", s], timeout=10
                ).returncode
                != 0
                for s in srcs
            ):
                ghosts.append(name)
        if not ghosts:
            return
        print(
            f"\n{t('Ghost domains (defined but disk missing):')} "
            f"{', '.join(ghosts)}"
        )
        if not self._is_yes(input(t("Undefine these ghost domains? (y/N): "))):
            print(t("Cancelled."))
            return
        for name in ghosts:
            q = shlex.quote(name)
            cmd = (
                f"{sudo_prefix()}virsh --connect {URI} "
                f"destroy {q} 2>/dev/null; "
                f"{sudo_prefix()}virsh --connect {URI} "
                f"undefine {q} --nvram 2>/dev/null "
                f"|| {sudo_prefix()}virsh --connect {URI} undefine {q}"
            )
            print(f"{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)
        print(f"✅ {t('Cleanup done.')}")

    def _ssh_entry_alive(self, content, nom, domains, adresses, distantes):
        """Cette entrée mène-t-elle encore quelque part ? (raison, ou '')

        Le NOM ne suffit pas à en juger — c'est le défaut qui a coûté cher :
        après un renommage de VM, l'alias garde l'ancien nom et se faisait
        effacer alors qu'il menait à une machine EN MARCHE. Trois autres
        preuves valent mieux :

        * son adresse est celle d'un domaine vivant ;
        * son nom est celui d'une VM de l'hôte Proxmox retenu.

        Le ProxyJump n'en fait PAS partie, et c'est le second défaut de cette
        fonction : il valait preuve à lui seul, sans qu'on regarde jamais si
        le rebond existait encore. Cette question-là se traite dans
        `ssh_orphans`, qui seule peut la poser — la réponse dépend des autres
        entrées, et de celles qu'on s'apprête à retirer.
        """
        if nom in domains:
            return nom
        bloc = re.search(
            rf"(?ms)^[ \t]*Host[ \t]+{re.escape(nom)}[ \t]*\n"
            r"((?:[ \t]+[^\n]*\n?)*)",
            content,
        )
        corps = bloc.group(1) if bloc else ""
        ip = re.search(r"(?mi)^[ \t]*HostName[ \t]+(\S+)", corps)
        if ip and ip.group(1) in adresses:
            return adresses[ip.group(1)]
        if nom in distantes:
            return t("a VM of the Proxmox host")
        return ""

    def _cleanup_ssh_config(self, domains):
        """Retire les blocs « Host erplibre-* » qui ne mènent plus à rien (on
        ne touche jamais aux autres hôtes SSH personnels)."""
        cfg = os.path.expanduser("~/.ssh/config")
        if not os.path.exists(cfg):
            return
        with open(cfg, encoding="utf-8") as fh:
            content = fh.read()
        # Les adresses des domaines vivants, et les VM de l'hôte Proxmox
        # retenu : deux preuves qu'une entrée sert encore, que le nom ignore.
        adresses = {}
        for nom in domains:
            ip = self._qemu_vm_ip_now(nom)
            if ip:
                adresses[ip] = nom
        distantes = set()
        try:
            hote = self._pve_host(ask=False)
            if hote:
                distantes = {
                    v["name"] for v in self._pve_vms() if v.get("name")
                }
        except Exception:
            pass
        gardes, orphelines = ssh_orphans(
            parse_ssh_blocks(content),
            lambda h: self._ssh_entry_alive(
                content, h, domains, adresses, distantes
            ),
        )
        if gardes:
            print(f"\n{t('Kept (still leads somewhere):')}")
            for h, raison in gardes:
                print(f"  {h}  ← {raison}")
        if not orphelines:
            return
        print(f"\n{t('Orphan ~/.ssh/config entries:')}")
        # Avec la RAISON : « son rebond n'existe plus » explique pourquoi une
        # entrée qu'on croyait bonne s'en va, et c'est la seule chose qui
        # permet de répondre non en connaissance de cause.
        for h, raison in orphelines:
            print(f"  {h}" + (f"  ← {raison}" if raison else ""))
        orphans = [h for h, _r in orphelines]
        if not self._is_yes(
            input(t("Remove these ~/.ssh/config entries? (y/N): "))
        ):
            print(t("Cancelled."))
            return
        for h in orphans:
            pat = re.compile(
                rf"(?m)^[ \t]*Host[ \t]+{re.escape(h)}[ \t]*\n"
                r"(?:[ \t]+[^\n]*\n?)*"
            )
            content = pat.sub("", content)
        content = content.strip("\n")
        content = content + "\n" if content else ""
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(cfg, 0o600)
        print(f"✅ {t('Cleanup done.')}")

    def _cleanup_stale_leases(self):
        """Baux DHCP libvirt dont la MAC n'appartient à aucune VM (best-effort :
        les baux expirent d'eux-mêmes)."""
        status = "/var/lib/libvirt/dnsmasq/virbr0.status"
        try:
            res = subprocess.run(
                ["sudo", "cat", status],
                capture_output=True,
                text=True,
                timeout=15,
            )
            leases = json.loads(res.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return
        if not isinstance(leases, list) or not leases:
            return
        macs = self._qemu_domain_macs()
        stale = [
            ln
            for ln in leases
            if str(ln.get("mac-address", "")).lower() not in macs
        ]
        if not stale:
            return
        print(f"\n{t('Stale DHCP leases (no matching VM):')}")
        for ln in stale:
            print(
                f"  {ln.get('ip-address', '?'):<16} "
                f"{ln.get('mac-address', '?')}  {ln.get('hostname', '')}"
            )
        if not self._is_yes(input(t("Clear these stale leases? (y/N): "))):
            print(t("Cancelled."))
            return
        kept = [ln for ln in leases if ln not in stale]
        tmp = os.path.join("/tmp", f"virbr0.status.{os.getpid()}.json")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(kept, fh)
        cmd = (
            f"sudo cp {shlex.quote(tmp)} {status} && "
            "sudo pkill -HUP -F /var/lib/libvirt/dnsmasq/virbr0.pid "
            "2>/dev/null || true"
        )
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        print(f"✅ {t('Cleanup done.')}")

    def _qemu_import_module(self):
        """Importe deploy_qemu.py comme module (source de vérité des specs).

        Mémorisé : le catalogue interroge cette source une fois par couple
        (distro, version), et réexécuter un fichier de 2 700 lignes à chaque
        passage se voyait à l'écran.
        """
        cached = getattr(self, "_qemu_mod_cache", None)
        if cached is not None:
            return cached
        import importlib.util

        path = self._qemu_script_path()
        spec = importlib.util.spec_from_file_location("deploy_qemu", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self._qemu_mod_cache = mod
        return mod

    @classmethod
    def _qemu_infra_name(cls, distro, version, arch=None):
        """Nom de VM stable pour le parc, ex. erplibre-ubuntu-2404. Ajoute un
        suffixe d'architecture quand elle diffère de la native de l'hôte (ex.
        erplibre-ubuntu-2604-s390x sur un hôte amd64) pour éviter les collisions
        de noms entre archis et rendre l'archi visible.

        La version « latest » ne figure pas dans le nom : une distribution en
        publication continue n'en a qu'une, si bien que le segment ne
        distingue aucune VM d'une autre. Une version nommée qui coexiste avec
        d'autres au catalogue reste dans le nom, tumbleweed comprise."""
        if version == "latest":
            base = f"erplibre-{distro}"
        else:
            base = f"erplibre-{distro}-{version.replace('.', '')}"
        if arch and arch != cls._native_arch():
            base += f"-{arch}"
        return base

    def _qemu_domain_exists(self, name):
        """Vrai si une VM libvirt de ce nom est déjà définie."""
        try:
            res = subprocess.run(
                virsh_argv("dominfo", name),
                capture_output=True,
                text=True,
                timeout=15,
            )
            return res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _qemu_host_addresses():
        """Adresses IPv4 de L'HÔTE, à écarter des candidates d'une VM.

        « virsh domifaddr --source arp » remonte la table ARP, où figurent les
        passerelles des ponts libvirt. Une VM n'a jamais l'adresse de son
        hôte : sans ce filtre, une VM RENOMMÉE — dont le bail porte encore
        l'ancien nom d'hôte, donc sans correspondance — se voit attribuer la
        passerelle.
        """
        try:
            res = subprocess.run(
                ["ip", "-4", "-o", "addr", "show"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return set()
        return set(re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", res.stdout))

    @staticmethod
    def _qemu_candidates_by_source(name):
        """{source: [ip]} — les candidates SANS mélanger les sources.

        Le bail dit ce que dnsmasq a donné, l'agent ce que la VM voit,
        l'ARP ce qui a parlé sur le réseau (passerelles comprises). Les
        garder séparées permet de choisir la plus sûre quand le nom d'hôte
        ne tranche pas.
        """
        siennes = QemuManageMixin._qemu_host_addresses()
        out = {}
        for source in ("lease", "agent", "arp"):
            try:
                res = subprocess.run(
                    virsh_argv("domifaddr", name, "--source", source),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            vues = []
            for ip in re.findall(r"(\d+\.\d+\.\d+\.\d+)", res.stdout):
                if ip != "127.0.0.1" and ip not in siennes and ip not in vues:
                    vues.append(ip)
            if vues:
                out[source] = vues
        return out

    @staticmethod
    def _qemu_lease_candidates(name):
        """Toutes les IPv4 candidates de la VM, agrégées de PLUSIEURS sources :
        - lease : base DHCP de dnsmasq (peut manquer sous forte charge, ou
          contenir plusieurs baux : bail précoce « ubuntu » périmé + bail
          définitif) ;
        - agent : qemu-guest-agent DANS la VM (voit l'IP réelle même quand le
          bail dnsmasq est absent) ;
        - arp : table ARP de l'hôte (VM active sur le réseau).
        On combine pour ne jamais rater une IP que le bail seul manquerait :
        sous forte charge, le bail dnsmasq reste vide alors que la VM a bien
        une adresse."""
        ips = []
        siennes = QemuManageMixin._qemu_host_addresses()
        for source in ("lease", "agent", "arp"):
            try:
                res = subprocess.run(
                    virsh_argv("domifaddr", name, "--source", source),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            for ip in re.findall(r"(\d+\.\d+\.\d+\.\d+)", res.stdout):
                # Ignore la loopback (remontée par --source agent) et les
                # adresses de l'HÔTE (passerelles des ponts, remontées par
                # --source arp) : une VM n'a jamais celles-là.
                if ip != "127.0.0.1" and ip not in ips and ip not in siennes:
                    ips.append(ip)
        return ips

    @staticmethod
    def _qemu_ip_reachable(ip, port=22, timeout=2):
        """Vrai si la VM répond sur cette IP (bail ACTIF, pas périmé). On teste
        le PING d'abord : il répond dès que le réseau de la VM est up, BIEN
        AVANT sshd — sinon on attendait le sshd (lent en émulation) et la
        résolution semblait « bloquée » alors que la VM a déjà son IP. Repli
        TCP:port si l'ICMP est filtré."""
        try:
            res = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout)), ip],
                capture_output=True,
                timeout=timeout + 1,
            )
            if res.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        import socket

        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except OSError:
            return False

    @staticmethod
    def _qemu_lease_ip_for_host(name, candidates):
        """Parmi `candidates`, l'IP dont le bail dnsmasq porte le hostname de la
        VM (le bail DÉFINITIF, pas le bail précoce « ubuntu »). None sinon."""
        try:
            res = subprocess.run(
                [
                    "sudo",
                    "sh",
                    "-c",
                    "cat /var/lib/libvirt/dnsmasq/*.status 2>/dev/null",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        # Plusieurs tableaux JSON concaténés : on parse chaque objet {...}.
        for obj in re.findall(r"\{[^{}]*\}", res.stdout or ""):
            if re.search(rf'"hostname":\s*"{re.escape(name)}"', obj):
                m = re.search(r'"ip-address":\s*"([\d.]+)"', obj)
                if m and m.group(1) in candidates:
                    return m.group(1)
        return None

    def _qemu_vm_ip_now(self, name):
        """IP de la VM d'après le bail DHCP, SANS attendre.

        `_qemu_vm_ip` patiente jusqu'à dix minutes par VM : c'est ce qu'il faut
        après un déploiement, et exactement ce qu'il ne faut pas pour AFFICHER
        une liste — trois VM figeaient le menu une demi-heure. Ici on lit le
        bail une fois, en préférant celui dont le hostname est le nom de la VM.
        """
        par_source = self._qemu_candidates_by_source(name)
        cands = [ip for ips in par_source.values() for ip in ips]
        if not cands:
            return None
        trouve = self._qemu_lease_ip_for_host(name, cands)
        if trouve:
            return trouve
        # Sans correspondance de nom d'hôte — le cas d'une VM RENOMMÉE, dont
        # le bail porte encore l'ancien nom — on prend la source la plus
        # sûre : le bail, puis l'agent, puis la table ARP. Celle-ci contient
        # les passerelles des ponts, où « la dernière candidate » tombe : la
        # VM se voit alors annoncée avec l'adresse de sa passerelle.
        for source in ("lease", "agent", "arp"):
            if par_source.get(source):
                return par_source[source][-1]
        return cands[-1]

    def _qemu_vm_ip(self, name, timeout=600):
        """IPv4 utilisable d'une VM. Gère le cas des baux multiples (hostname
        changé au boot) : renvoie en priorité le bail dont le hostname == nom
        de la VM, sinon une IP JOIGNABLE (sshd up), pour ne jamais retenir le
        bail précoce périmé. Attend jusqu'à `timeout` (boot émulé lent)."""
        deadline = time.time() + timeout
        cands = []
        while time.time() < deadline:
            cands = self._qemu_lease_candidates(name)
            if cands:
                # 1) bail définitif (hostname == nom de la VM)
                host_ip = self._qemu_lease_ip_for_host(name, cands)
                if host_ip:
                    return host_ip
                # 2) sinon, une IP déjà joignable (sshd up)
                for ip in cands:
                    if self._qemu_ip_reachable(ip):
                        return ip
            time.sleep(3)
        # Meilleur effort : le dernier bail (le plus récent) plutôt que le 1er.
        return cands[-1] if cands else None

    def _qemu_resolve_ips(self, names, labels=None, timeout=300):
        """Résout les IP de plusieurs VM EN PARALLÈLE (le boot émulé est lent),
        en affichant la progression au fur et à mesure. Renvoie {nom: ip|None}.
        `labels` : {nom: « k/N »} pour préfixer chaque ligne d'un ID de suivi.
        `timeout` : délai max PAR VM (borne l'attente d'une VM sans IP). Un
        BATTEMENT toutes les 30 s liste les VM encore en attente -> jamais de
        silence prolongé qui donne l'impression d'un blocage."""
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as _FTimeout
        from concurrent.futures import as_completed

        labels = labels or {}
        print(
            f"\n{t('Resolving VM IPs (parallel, emulated boot is slow)...')}"
        )
        result = {}
        t0 = time.time()
        starts = {}
        workers = min(len(names), (os.cpu_count() or 4)) or 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {}
            for n in names:
                starts[n] = time.time()
                futs[pool.submit(self._qemu_vm_ip, n, timeout)] = n
            pending = set(futs)
            done = 0
            while pending:
                try:
                    for fut in as_completed(list(pending), timeout=30):
                        pending.discard(fut)
                        n = futs[fut]
                        try:
                            ip = fut.result()
                        except Exception:
                            ip = None
                        result[n] = ip
                        done += 1
                        tag = f"[{labels[n]}] " if n in labels else ""
                        dur = self._fmt_dur(time.time() - starts[n])
                        print(
                            f"  [{done}/{len(names)}] {tag}{n}: "
                            f"{ip or t('no IP')} ({dur})"
                        )
                except _FTimeout:
                    # Battement : VM encore en attente (boot/DHCP lent).
                    waiting = [futs[f] for f in pending]
                    shown = ", ".join(waiting[:5])
                    if len(waiting) > 5:
                        shown += "…"
                    print(
                        f"  ⏳ {t('still waiting for')} {len(waiting)} VM "
                        f"({self._fmt_dur(time.time() - t0)}): {shown}"
                    )
        got = sum(1 for ip in result.values() if ip)
        print(
            f"  {t('IPs resolved:')} {got}/{len(names)} "
            f"({self._fmt_dur(time.time() - t0)})"
        )
        return result

    def _qemu_vm_arch(self, name):
        """Architecture d'une VM (jeton amd64/arm64/s390x) via virsh dumpxml."""
        try:
            res = subprocess.run(
                virsh_argv("dumpxml", name),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        m = re.search(r"<type[^>]*\barch='([^']+)'", res.stdout)
        if not m:
            return None
        return {
            "x86_64": "amd64",
            "aarch64": "arm64",
            "s390x": "s390x",
        }.get(m.group(1), m.group(1))

    def _qemu_vm_meta(self, name, mod):
        """(distro, version, arch) d'une VM déduits de son nom + son arch. Le
        nom suit _qemu_infra_name(distro, version, arch) : on retrouve donc
        (distro, version) en testant les combinaisons du catalogue."""
        arch = self._qemu_vm_arch(name) or "amd64"
        try:
            for d, (versions, _default) in mod.DISTROS.items():
                for v in versions:
                    if self._qemu_infra_name(d, v, arch) == name:
                        return d, v, arch
        except Exception:
            pass
        return None, None, arch

    @staticmethod
    def _qemu_repo_branch():
        """Branche du dépôt COURANT, ou '' — le défaut des formulaires.

        On déploie le plus souvent ce qu'on a sous les yeux ; le premier nom
        de la liste alphabétique, lui, n'a aucune raison d'être bon."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        nom = (res.stdout or "").strip()
        return "" if res.returncode or nom == "HEAD" else nom

    @staticmethod
    def _qemu_branch_gap(branche):
        """Combien de commits LOCAUX manquent à origin/<branche>, et lesquels.

        Rend (nombre, [sujets]) — (0, []) quand il n'y a rien à dire, ou quand
        la question ne se pose pas (pas de dépôt, pas de distant).

        Pourquoi le déploiement s'en soucie : la VM ne reçoit PAS le checkout
        d'ici, elle CLONE la branche depuis le dépôt distant. Tout ce qui
        tourne dans la VM — install_proxmox.sh, les scripts d'installation, le
        Makefile — vient donc de là.

        Un correctif commité ici mais pas poussé ne part donc pas : chaque VM
        déployée ensuite reçoit l'ancien script, et le défaut « revient »
        alors qu'il est corrigé. Rien ne le signale, d'où ce décompte.
        """
        if not branche:
            return 0, []
        try:
            res = subprocess.run(
                [
                    "git",
                    "log",
                    "--oneline",
                    "--no-decorate",
                    f"origin/{branche}..HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return 0, []
        # Une branche inconnue du distant, ou aucun distant : ce n'est pas un
        # écart à signaler, c'est une question qui ne se pose pas.
        if res.returncode:
            return 0, []
        sujets = [
            ligne.strip()
            for ligne in (res.stdout or "").splitlines()
            if ligne.strip()
        ]
        return len(sujets), sujets

    def _qemu_branch_gap_lines(self, branche, limite=3):
        """Les lignes à dire avant de déployer, ou []."""
        nombre, sujets = self._qemu_branch_gap(branche)
        if not nombre:
            return []
        lignes = [
            f"⚠ {t('The VM clones')} origin/{branche}, "
            f"{t('not this checkout.')}",
            f"  {nombre} {t('local commit(s) are missing there:')}",
        ]
        lignes += [f"    {s}" for s in sujets[:limite]]
        if nombre > limite:
            lignes.append(f"    … {nombre - limite} {t('more')}")
        lignes.append(f"  → git push {t('to deploy your own work.')}")
        return lignes

    def _qemu_branch_list(self):
        """Branches distantes d'ERPLibre, triées. Vide si le réseau manque.

        Séparé de l'invite : le formulaire TUI a besoin de la LISTE, et cet
        appel réseau (jusqu'à 30 s) doit être fait avant que Textual prenne
        le terminal."""
        branches = []
        try:
            res = subprocess.run(
                ["git", "ls-remote", "--heads", self.ERPLIBRE_GIT_URL],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in res.stdout.splitlines():
                ref = line.split("\t")[-1]
                if ref.startswith("refs/heads/"):
                    branches.append(ref[len("refs/heads/") :])
        except (OSError, subprocess.SubprocessError):
            pass
        branches.sort()
        return branches

    def _qemu_pick_branch(self):
        """Liste les branches distantes d'ERPLibre et en fait choisir une."""
        print(f"\n{t('Fetching ERPLibre branch list...')}")
        branches = self._qemu_branch_list()
        default = (
            "master"
            if "master" in branches
            else (branches[0] if branches else "master")
        )
        if not branches:
            return (
                input(f"{t('Branch (default:')} {default}): ").strip()
                or default
            )
        print(f"{t('Branches:')}")
        for i, b in enumerate(branches, 1):
            star = " *" if b == default else ""
            print(f"  [{i}] {b}{star}")
        sel = input(f"{t('Choice (number or name, default:')} {default}): ")
        sel = sel.strip()
        if not sel:
            return default
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(branches):
                return branches[idx]
        except ValueError:
            if sel in branches:
                return sel
        return default

    @staticmethod
    def _qemu_wait_ssh(ip, user="erplibre", timeout=1200):
        """Attend que sshd réponde ET que cloud-init soit TERMINÉ, via des
        connexions COURTES successives. Au 1er boot, cloud-init régénère les
        clés d'hôte et REDÉMARRE sshd : attendre la fin de cloud-init AVANT de
        lancer l'install évite qu'une session longue soit tuée (« Connection
        closed by remote host », exit 255 — cas Fedora). True si prête."""
        opts = (
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=8 -o BatchMode=yes"
        )
        # On imprime toujours l'état (|| true) pour matcher sur le TEXTE :
        # « status: running » n'a pas de code de sortie fiable selon la version.
        probe = (
            "if command -v cloud-init >/dev/null 2>&1; then "
            "cloud-init status 2>/dev/null || true; else echo nocloudinit; fi"
        )
        ready = ("done", "disabled", "error", "degraded", "nocloudinit")
        deadline = time.time() + timeout
        ssh_up = False
        while time.time() < deadline:
            try:
                res = subprocess.run(
                    f"ssh {opts} {user}@{ip} {shlex.quote(probe)}",
                    shell=True,
                    capture_output=True,
                    timeout=20,
                    text=True,
                )
                out = res.stdout or ""
            except (OSError, subprocess.SubprocessError):
                out = ""
            if out.strip():
                ssh_up = True  # sshd a répondu
            if any(k in out for k in ready):
                return True
            time.sleep(5)
        # cloud-init pas confirmé fini dans le délai : on tente quand même si
        # sshd répondait au moins (mieux qu'un abandon silencieux).
        return ssh_up
