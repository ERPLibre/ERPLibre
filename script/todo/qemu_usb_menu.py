#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu QEMU/KVM : passer un périphérique USB à une VM, Stream Deck d'abord.

Deux voies, selon l'endroit où le périphérique est branché :

- sur l'HÔTE LIBVIRT : un <hostdev> attaché par virsh, en live, en config
  ou les deux, la persistance étant choisie à chaque fois. L'hôte est ce
  poste (qemu:///system) ou le ProxyJump d'un hôte de ~/.ssh/config
  (qemu+ssh://<saut>/system) ;
- sur le POSTE qui ouvre virt-viewer : la redirection USB de SPICE, qui
  exige un affichage SPICE placé avant le VNC et des emplacements
  <redirdev type='spicevmc'> dans la VM.

Les plans viennent de qemu_usb.py, qui ne lance rien. Ce fichier lit l'état
par virsh, montre chaque commande, demande, puis l'exécute : le XML passe
par un fichier temporaire, sudo ne précède virsh que pour un qemu:///system
local que le groupe libvirt n'ouvre pas, jamais pour qemu+ssh.

Le service deck d'ERPLibre Home (unité --user) tient le deck sur l'hôte qui
le fait tourner ; QEMU comme spice-gtk le lui retirent. Il est donc arrêté
pendant le passage, après confirmation, et le détachement propose de le
relancer.

Le rattachement au rebranchement est l'affaire de script/qemu/usb_qemu.py,
lancé en root par une règle udev et une unité systemd posées sur l'hôte
libvirt, localement par sudo ou à distance par ssh.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que celles
des autres fichiers, elles s'appellent donc par « self. » sans rien importer.
"""

import json
import os
import shlex
import subprocess
import tempfile
import time

import click

from script.todo import erplibre_home_service as service
from script.todo import qemu_usb as qu
from script.todo.qemu_privilege import sudo_prefix
from script.todo.todo_i18n import t

# Le CLI autonome et le module qu'il charge, dans le dépôt. Copiés tels quels
# sur un hyperviseur distant pour l'installation du rattachement.
RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
CLI = os.path.join(RACINE, "script", "qemu", "usb_qemu.py")
LIB = os.path.join(RACINE, "script", "todo", "qemu_usb.py")

# Options des sondes ssh : jamais d'invite de mot de passe dans une sonde
# muette, et un hôte injoignable rend la main en quelques secondes.
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]

# Attente de l'arrêt propre d'une VM, et pas entre deux lectures d'état.
SHUTDOWN_TIMEOUT = 120
SHUTDOWN_POLL = 2

# États systemd où l'unité tient déjà, ou va tenir, le deck.
_ACTIVE_STATES = ("active", "activating", "reloading")


class QemuUsbMixin:
    """Menu QEMU/KVM : périphériques USB des VM (passage et redirection)."""

    def _qemu_usb_menu(self):
        choices = [
            {"section": t("Device on the libvirt host")},
            {"prompt_description": t("List the USB devices of this machine")},
            {"prompt_description": t("Attach a USB device to a VM")},
            {"prompt_description": t("Detach a USB device from a VM")},
            {"prompt_description": t("Show the USB devices of a VM")},
            {"section": t("Device on this workstation (SPICE)")},
            {"prompt_description": t("Open virt-viewer with USB redirection")},
            {"prompt_description": t("Enable SPICE USB redirection on a VM")},
            {"section": t("Replug")},
            {
                "prompt_description": t(
                    "Auto-reattach on replug (udev rule, device mapping)"
                )
            },
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._qemu_usb_list()
            elif status == "2":
                self._qemu_usb_attach()
            elif status == "3":
                self._qemu_usb_detach()
            elif status == "4":
                self._qemu_usb_show()
            elif status == "5":
                self._qemu_usb_viewer()
            elif status == "6":
                self._qemu_usb_enable_spice()
            elif status == "7":
                self._qemu_usb_autoreattach()
            else:
                print(t("Command not found !"))

    # -------------------------------------------------------------- #
    # Sondes : les seules méthodes qui lancent un processus muet.

    @staticmethod
    def _qemu_usb_capture(argv, stdin_text=None, timeout=30):
        """(code, sortie standard) de `argv`, sous LC_ALL=C pour que virsh
        réponde « running » quelle que soit la locale. (None, "") quand la
        commande ne se lance pas ou dépasse `timeout`. stderr passe au
        terminal : une invite de sudo ou de ssh reste visible."""
        env = dict(os.environ, LC_ALL="C", LANG="C")
        try:
            res = subprocess.run(
                list(argv),
                input=stdin_text,
                stdout=subprocess.PIPE,
                text=True,
                timeout=timeout,
                env=env,
            )
        except (OSError, subprocess.SubprocessError):
            return None, ""
        return res.returncode, res.stdout

    @staticmethod
    def _qemu_usb_prefix(target):
        """sudo devant virsh pour qemu:///system local quand le groupe
        libvirt ne suffit pas ; rien pour qemu+ssh, dont les droits sont
        ceux du compte distant."""
        if target["jump"]:
            return []
        return sudo_prefix().split()

    def _qemu_usb_virsh(self, target, argv):
        """Sortie d'un virsh muet sur la cible, "" en cas d'échec."""
        code, out = self._qemu_usb_capture(
            self._qemu_usb_prefix(target) + list(argv)
        )
        return out if code == 0 else ""

    def _qemu_usb_host_devices(self, jump=""):
        """Périphériques passables de l'hôte libvirt, decks en tête.

        Ce poste : lecture directe de sysfs. Un hyperviseur distant : le
        source de qemu_usb.py est envoyé à « python3 -I - » par ssh, suivi
        d'un appel qui imprime host_usb_devices() en JSON. Le module ne
        demande que la bibliothèque standard, et rien n'est écrit sur
        l'hyperviseur. Rend None quand la lecture distante échoue."""
        if not jump:
            return qu.host_usb_devices()
        try:
            with open(LIB, encoding="utf-8") as fh:
                source = fh.read()
        except OSError:
            return None
        source += (
            "\nimport json as _json\nprint(_json.dumps(host_usb_devices()))\n"
        )
        code, out = self._qemu_usb_capture(
            ["ssh", *SSH_OPTS, jump, "python3", "-I", "-"],
            stdin_text=source,
        )
        try:
            devs = json.loads(out) if code == 0 else None
        except ValueError:
            devs = None
        if not isinstance(devs, list):
            message = t("Cannot read the USB devices of {host}.")
            print(f"  ⚠ {message.format(host=jump)}")
            return None
        return devs

    @staticmethod
    def _qemu_usb_parse_service(text):
        """{"installed", "active"} lus dans la sortie de « systemctl show
        -p LoadState -p ActiveState » : installée quand LoadState vaut
        loaded, active quand ActiveState est l'un de _ACTIVE_STATES."""
        champs = {}
        for ligne in (text or "").splitlines():
            cle, _, valeur = ligne.partition("=")
            champs[cle.strip()] = valeur.strip()
        return {
            "installed": champs.get("LoadState") == "loaded",
            "active": champs.get("ActiveState") in _ACTIVE_STATES,
        }

    def _qemu_usb_service_state(self, jump=""):
        """État du service deck ERPLibre Home de l'hôte : ce poste par le
        bus utilisateur (service.run_command le complète sous su ou sudo),
        un hyperviseur par ssh, pour le compte qui s'y connecte. Une sonde
        qui échoue rend « absent »."""
        argv = [
            "systemctl",
            "--user",
            "show",
            "-p",
            "LoadState",
            "-p",
            "ActiveState",
            service.UNIT_NAME,
        ]
        if jump:
            code, out = self._qemu_usb_capture(
                ["ssh", *SSH_OPTS, jump, shlex.join(argv)]
            )
        else:
            code, out = service.run_command(argv)
        return self._qemu_usb_parse_service(out if code == 0 else "")

    # -------------------------------------------------------------- #
    # Cible, choix, plan

    def _qemu_usb_pick_target(self):
        """La VM visée, et l'hôte libvirt qui la fait tourner.

        Les domaines libvirt locaux d'abord, puis les hôtes de
        ~/.ssh/config ; pour ceux-ci, le domaine est le nom après le
        dernier « + » et l'hyperviseur est le ProxyJump que ssh calcule.
        Rend {"name", "src", "domain", "uri", "jump"}, src valant « virsh »
        ou « ssh_config » comme dans le menu des tunnels, ou None.

        Un hyperviseur Proxmox VE n'a pas de libvirt : il est refusé ici,
        son menu attribue l'USB par qm, toujours de façon persistante."""
        targets = [(n, "virsh") for n in self._qemu_list_domains()]
        targets += [(h, "ssh_config") for h in self._ssh_config_hosts()]
        if not targets:
            print(f"  {t('No host in ~/.ssh/config and no local VM.')}")
            return None
        print(f"{t('Which VM?')}")
        for i, (name, src) in enumerate(targets, 1):
            mark = f"  ({t('local VM')})" if src == "virsh" else ""
            print(f"  [{i}] {name}{mark}")
        answer = input(f"{t('Choice')} [1]: ").strip() or "1"
        if not answer.isdigit() or not 1 <= int(answer) <= len(targets):
            print(t("Cancelled."))
            return None
        name, src = targets[int(answer) - 1]
        if src == "virsh":
            return {
                "name": name,
                "src": src,
                "domain": name,
                "uri": qu.DEFAULT_URI,
                "jump": "",
            }
        jump = self._ssh_proxyjump(name)
        if not jump:
            print(f"\n  ⚠ {t('No ProxyJump for this host in ~/.ssh/config.')}")
            print(f"  {t('Cannot tell which machine runs its QEMU.')}")
            return None
        if self._hypervisor_is_proxmox(jump):
            message = t("{host} is a Proxmox VE host: no libvirt there.")
            print(f"\n  ⚠ {message.format(host=jump)}")
            print(
                f"  {t('Use the Proxmox VE menu; a Proxmox USB assignment')}"
            )
            print(f"  {t('is always persistent (no live or config choice).')}")
            return None
        return {
            "name": name,
            "src": src,
            "domain": name.rsplit("+", 1)[-1],
            "uri": f"qemu+ssh://{jump}/system",
            "jump": jump,
        }

    def _qemu_usb_read(self, target):
        """L'état USB de la VM dans ses deux vues.

        Rend {"domstate", "running", "config_xml", "config", "live"} :
        config est usb_state() de la définition (dumpxml --inactive), live
        celui de la VM en marche, None quand elle ne tourne pas. Rend None,
        en le disant, quand libvirt ne répond pas."""
        uri, domain = target["uri"], target["domain"]
        etat = self._qemu_usb_virsh(
            target, qu.domstate_argv(uri, domain)
        ).strip()
        cfg_xml = (
            self._qemu_usb_virsh(
                target, qu.dumpxml_argv(uri, domain, inactive=True)
            )
            if etat
            else ""
        )
        if not etat or not cfg_xml.strip():
            print(
                f"  ⚠ {t('Cannot read this VM through libvirt:')}"
                f" {uri} {domain}"
            )
            return None
        running = etat == "running"
        live_xml = (
            self._qemu_usb_virsh(target, qu.dumpxml_argv(uri, domain))
            if running
            else ""
        )
        print(f"\n  {domain} — {etat}")
        return {
            "domstate": etat,
            "running": running,
            "config_xml": cfg_xml,
            "config": qu.usb_state(cfg_xml),
            "live": qu.usb_state(live_xml) if running else None,
        }

    @staticmethod
    def _qemu_usb_print_devices(devs):
        for i, dev in enumerate(devs, 1):
            mark = f"  ★ {t('Stream Deck')}" if dev.get("is_deck") else ""
            print(f"  [{i}] {qu.device_line(dev)}{mark}")

    def _qemu_usb_pick_device(self, devs):
        """Un périphérique de `devs`, le premier par défaut — un deck quand
        il y en a un, host_usb_devices() les mettant en tête."""
        if not devs:
            print(f"  {t('No USB device to pass on this host.')}")
            return None
        self._qemu_usb_print_devices(devs)
        answer = input(f"{t('Which device?')} [1]: ").strip() or "1"
        if not answer.isdigit() or not 1 <= int(answer) <= len(devs):
            print(t("Cancelled."))
            return None
        return devs[int(answer) - 1]

    def _qemu_usb_ask_views(self, running):
        """(live, config) choisis pour cet attachement, ou None.

        Posée à chaque fois : un essai se fait en live seul, un usage
        durable en config. Live sur une VM arrêtée reste proposé ; le plan
        le saute alors en disant pourquoi."""
        arret = "" if running else f"  ({t('the VM is not running')})"
        print(f"\n{t('Persistence:')}")
        print(f"  [1] {t('live and config: now and at every start')} *")
        print(f"  [2] {t('live only: until the VM stops')}{arret}")
        print(f"  [3] {t('config only: from the next start')}")
        answer = input(f"{t('Choice')} [1]: ").strip() or "1"
        views = {"1": (True, True), "2": (True, False), "3": (False, True)}
        if answer not in views:
            print(t("Cancelled."))
            return None
        return views[answer]

    def _qemu_usb_show_plan(self, target, steps):
        """Affiche chaque étape, sautée avec sa raison ou lancée avec sa
        commande, sudo compris ; rend les étapes à lancer."""
        runnable = []
        for step in steps:
            if "skip" in step:
                print(f"  ⏭  {step['what']} — {step['skip']}")
                continue
            runnable.append(step)
            argv = self._qemu_usb_prefix(target) + step["argv"]
            print(f"  ▶ {step['what']}")
            print(f"      {shlex.join(argv)}")
        return runnable

    def _qemu_usb_exec(self, cmd):
        """Lance une commande shell en direct ; vrai quand elle réussit."""
        status = self.execute.exec_command_live(cmd, source_erplibre=False)
        return not status

    def _qemu_usb_run_steps(self, target, steps):
        """Lance les étapes dans l'ordre et s'arrête à la première qui
        échoue. Le XML de chacune passe par un fichier temporaire, effacé
        ensuite ; virsh le lit sur ce poste, même pour qemu+ssh."""
        for step in steps:
            fd, path = tempfile.mkstemp(prefix="erplibre-usb-", suffix=".xml")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(step.get("xml", ""))
                argv = self._qemu_usb_prefix(target) + qu.bind_xml(
                    step["argv"], path
                )
                ok = self._qemu_usb_exec(shlex.join(argv))
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            if not ok:
                print(f"  ⚠ {t('Command failed: ')}{step['what']}")
                return False
        return True

    # -------------------------------------------------------------- #
    # Service deck de l'hôte

    def _qemu_usb_service_cmd(self, verb, jump=""):
        argv = ["systemctl", "--user", verb, service.UNIT_NAME]
        return shlex.join(["ssh", jump, *argv] if jump else argv)

    def _qemu_usb_deck_conflict(self, jump=""):
        """Le service deck tourne-t-il sur la machine qui tient le deck ?

        Rend False quand il ne tourne pas, True quand l'utilisateur accepte
        de l'arrêter (l'appelant l'arrête après sa propre confirmation),
        None quand il refuse : le passage est alors annulé, le service et
        la VM se disputeraient le deck."""
        if not self._qemu_usb_service_state(jump)["active"]:
            return False
        host = jump or t("this machine")
        message = t("The ERPLibre Home deck service runs on {host}.")
        print(f"\n⚠  {message.format(host=host)}")
        print(f"   {t('It holds the deck, and loses it to the VM.')}")
        print(f"   {self._qemu_usb_service_cmd('stop', jump)}")
        if not self._is_yes(
            input(t("Stop that service during the passthrough? (y/N): "))
        ):
            print(t("Cancelled."))
            return None
        return True

    def _qemu_usb_offer_restart(self, jump=""):
        """Le deck rendu à l'hôte : propose d'y relancer le service deck
        s'il est installé et arrêté."""
        etat = self._qemu_usb_service_state(jump)
        if not etat["installed"] or etat["active"]:
            return
        host = jump or t("this machine")
        question = t(
            "Restart the ERPLibre Home deck service on {host}? (y/N): "
        )
        if self._is_yes(input(question.format(host=host))):
            self._qemu_usb_exec(self._qemu_usb_service_cmd("start", jump))

    # -------------------------------------------------------------- #
    # [1] à [4] : périphérique sur l'hôte libvirt

    def _qemu_usb_list(self):
        devs = self._qemu_usb_host_devices()
        print(f"🔌 {t('USB devices of this machine (hubs left out)')}")
        if not devs:
            print(f"  {t('No USB device to pass on this host.')}")
            return
        self._qemu_usb_print_devices(devs)
        if not any(d.get("is_deck") for d in devs):
            print(f"\n  {t('No Stream Deck plugged in here.')}")

    def _qemu_usb_attach(self):
        """Attache un périphérique de l'hôte libvirt à une VM.

        Le choix vient de l'hôte qui fait tourner la VM, lu dans sysfs.
        want_for() garde le VID:PID seul, qui survit au rebranchement, et
        n'épingle l'adresse que pour deux périphériques identiques. Le plan
        est montré, le service deck de l'hôte arrêté sur accord, puis les
        commandes sont lancées sur confirmation."""
        target = self._qemu_usb_pick_target()
        if not target:
            return
        devs = self._qemu_usb_host_devices(target["jump"])
        if devs is None:
            return
        host = target["jump"] or t("this machine")
        print(f"\n🔌 {t('USB devices of the libvirt host')} ({host})")
        dev = self._qemu_usb_pick_device(devs)
        if not dev:
            return
        want = dict(qu.want_for(dev, devs), action="attach")
        if want["bus"] is not None:
            print(f"  ⚠ {t('Two identical devices: this one is pinned by')}")
            print(
                f"    {t('its address, which changes when it is replugged.')}"
            )
        info = self._qemu_usb_read(target)
        if not info:
            return
        views = self._qemu_usb_ask_views(info["running"])
        if not views:
            return
        steps = qu.usb_plan(
            info["live"],
            info["config"],
            want,
            views[0],
            views[1],
            info["running"],
            target["domain"],
            target["uri"],
        )
        print(f"\n{t('Will execute:')}")
        runnable = self._qemu_usb_show_plan(target, steps)
        if not runnable:
            print(f"  {t('Nothing to do.')}")
            return
        # Seule une étape live prend le deck maintenant : config seule, ou
        # VM arrêtée, laisse le service de l'hôte tranquille.
        stop = False
        if dev.get("is_deck") and any(
            s.get("view") == "live" for s in runnable
        ):
            stop = self._qemu_usb_deck_conflict(target["jump"])
            if stop is None:
                return
        if not self._is_yes(input(t("Run these commands? (y/N): "))):
            print(t("Cancelled."))
            return
        if stop:
            self._qemu_usb_exec(
                self._qemu_usb_service_cmd("stop", target["jump"])
            )
        if not self._qemu_usb_run_steps(target, runnable):
            # Le service arrêté pour rien : le deck est resté à l'hôte.
            if stop:
                self._qemu_usb_offer_restart(target["jump"])
            return
        print(
            f"✅ {qu.device_id(dev['vid'], dev['pid'])} → {target['domain']}"
        )
        if dev.get("is_deck"):
            print(f"  {t('In the VM, ERPLibre Home takes the deck when its')}")
            print(f"  {t('service autostarts (ERPLibre Home > Autostart).')}")
        if views[0] and not views[1]:
            print(f"  {t('Live only: the VM loses it at its next stop.')}")

    @staticmethod
    def _qemu_usb_attached(info):
        """Les <hostdev> USB des deux vues, réunis par périphérique.

        Deux lignes désignent le même périphérique quand leurs VID:PID sont
        égaux et que leurs adresses le sont aussi, ou que l'une n'en a pas :
        libvirt complète l'adresse dans la vue live d'une définition écrite
        par VID:PID seul. Chaque ligne porte ses vues et garde l'adresse
        connue. Un <hostdev> live « missing » compte : c'est un usb-host
        vide dans QEMU, que usb_plan() sait détacher."""
        rows = []
        for view in ("live", "config"):
            state = info.get(view)
            for h in (state or {}).get("hostdevs", []):
                for row in rows:
                    meme_id = h["vid"] and (h["vid"], h["pid"]) == (
                        row["vid"],
                        row["pid"],
                    )
                    adresses = (row["bus"], row["dev"]), (h["bus"], h["dev"])
                    if meme_id and (
                        None in adresses[0]
                        or None in adresses[1]
                        or adresses[0] == adresses[1]
                    ):
                        row["views"].append(view)
                        if row["bus"] is None:
                            row["bus"], row["dev"] = h["bus"], h["dev"]
                        break
                else:
                    rows.append(
                        {
                            "vid": h["vid"],
                            "pid": h["pid"],
                            "bus": h["bus"],
                            "dev": h["dev"],
                            "views": [view],
                        }
                    )
        return rows

    def _qemu_usb_detach(self):
        """Détache un <hostdev> USB, vue par vue. Un deck rendu à l'hôte
        en live fait proposer la relance de son service deck."""
        target = self._qemu_usb_pick_target()
        if not target:
            return
        info = self._qemu_usb_read(target)
        if not info:
            return
        rows = self._qemu_usb_attached(info)
        if not rows:
            print(f"  {t('No USB device is attached to this VM.')}")
            return
        for i, row in enumerate(rows, 1):
            ident = qu.device_id(
                row["vid"], row["pid"], row["bus"], row["dev"]
            )
            print(f"  [{i}] {ident}  ({', '.join(row['views'])})")
        answer = input(f"{t('Which device?')} [1]: ").strip() or "1"
        if not answer.isdigit() or not 1 <= int(answer) <= len(rows):
            print(t("Cancelled."))
            return
        row = rows[int(answer) - 1]
        views = self._qemu_usb_ask_views(info["running"])
        if not views:
            return
        want = {k: row[k] for k in ("vid", "pid", "bus", "dev")}
        want["action"] = "detach"
        steps = qu.usb_plan(
            info["live"],
            info["config"],
            want,
            views[0],
            views[1],
            info["running"],
            target["domain"],
            target["uri"],
        )
        print(f"\n{t('Will execute:')}")
        runnable = self._qemu_usb_show_plan(target, steps)
        if not runnable:
            print(f"  {t('Nothing to do.')}")
            return
        if not self._is_yes(input(t("Run these commands? (y/N): "))):
            print(t("Cancelled."))
            return
        if not self._qemu_usb_run_steps(target, runnable):
            return
        print(f"✅ {t('Detached.')}")
        live_ran = any(s.get("view") == "live" for s in runnable)
        if row["vid"] == qu.DECK_VENDOR and live_ran:
            self._qemu_usb_offer_restart(target["jump"])

    def _qemu_usb_show(self):
        """Ce que la VM porte en USB : <hostdev> par vue, contrôleurs,
        emplacements de redirection SPICE, ordre des affichages."""
        target = self._qemu_usb_pick_target()
        if not target:
            return
        info = self._qemu_usb_read(target)
        if not info:
            return
        titres = (
            ("live", t("Running VM (live)")),
            ("config", t("Definition (config)")),
        )
        for view, titre in titres:
            state = info[view]
            print(f"\n── {titre} ──")
            if state is None:
                print(f"  {t('the VM is not running')}")
                continue
            for h in state["hostdevs"]:
                ident = qu.device_id(h["vid"], h["pid"], h["bus"], h["dev"])
                deck = (
                    f"  ★ {t('Stream Deck')}"
                    if h["vid"] == qu.DECK_VENDOR
                    else ""
                )
                absent = f"  ({t('absent at start')})" if h["missing"] else ""
                print(f"  hostdev {ident}{deck}{absent}")
            if not state["hostdevs"]:
                print(f"  {t('No USB device is attached to this VM.')}")
            controleurs = ", ".join(m or "?" for m in state["usb_controllers"])
            print(f"  {t('USB controller:')} {controleurs or t('none')}")
        cfg = info["live"] or info["config"]
        print(f"\n── {t('SPICE USB redirection')} ──")
        ordre = " → ".join(cfg["graphics"]) or t("none")
        print(f"  {t('Displays, in order:')} {ordre}")
        print(
            f"  {t('Redirection slots:')} {cfg['redirdevs'].count('spicevmc')}"
        )
        if qu.usbredir_ready(cfg) and qu.spice_first(cfg):
            print(f"  ✅ {t('Ready: virt-viewer offers USB redirection.')}")
        else:
            print(f"  {t('Not ready: entry 6 enables it (VM shut off).')}")
        allowed = [r["vendor"] for r in cfg["redirfilter"] if r["allow"]]
        if allowed:
            print(f"  {t('Allowed vendors:')} {', '.join(allowed)}")

    # -------------------------------------------------------------- #
    # [5] et [6] : périphérique sur ce poste, redirection SPICE

    def _qemu_usb_viewer(self):
        """Ouvre virt-viewer en redirigeant d'office les decks de ce poste.

        La VM doit déjà offrir la redirection dans la vue qui compte : la
        vue live quand elle tourne, la définition sinon. Une définition prête
        sous une VM en marche qui ne l'est pas demande un redémarrage. Le
        service deck de CE poste perd le deck redirigé : il est arrêté sur
        accord quand un deck est branché ici."""
        target = self._qemu_usb_pick_target()
        if not target:
            return
        info = self._qemu_usb_read(target)
        if not info:
            return
        state = info["live"] if info["running"] else info["config"]
        if not qu.usbredir_ready(state):
            if info["running"] and qu.usbredir_ready(info["config"]):
                print(f"  {t('Restart the VM: its definition has SPICE')}")
                print(f"  {t('redirection, the running VM not yet.')}")
            else:
                print(f"  {t('This VM has no SPICE USB redirection yet:')}")
                print(f"  {t('entry 6 enables it.')}")
            return
        if not qu.spice_first(state):
            print(
                f"  ⚠ {t('virt-viewer opens the first display, not SPICE:')}"
            )
            print(f"    {t('entry 6 puts SPICE first.')}")
        display = os.environ.get("DISPLAY") or os.environ.get(
            "WAYLAND_DISPLAY"
        )
        decks = [d for d in self._qemu_usb_host_devices() if d.get("is_deck")]
        if display and decks:
            stop = self._qemu_usb_deck_conflict()
            if stop is None:
                return
            if stop:
                self._qemu_usb_exec(self._qemu_usb_service_cmd("stop"))
        self._qemu_virt_viewer(target["name"], target["src"], usbredir=True)
        print(f"  {t('Other devices: File > USB device selection.')}")

    def _qemu_usb_shutdown(self, target):
        """Arrêt propre (virsh shutdown), puis attente de « shut off »
        pendant SHUTDOWN_TIMEOUT secondes. Vrai quand la VM est éteinte."""
        argv = self._qemu_usb_prefix(target) + qu.virsh_uri_argv(
            target["uri"], "shutdown", target["domain"]
        )
        if not self._qemu_usb_exec(shlex.join(argv)):
            return False
        fin = time.monotonic() + SHUTDOWN_TIMEOUT
        while True:
            etat = self._qemu_usb_virsh(
                target, qu.domstate_argv(target["uri"], target["domain"])
            ).strip()
            if etat == "shut off":
                return True
            if time.monotonic() >= fin:
                print(f"  ⚠ {t('The VM is still running.')}")
                return False
            time.sleep(SHUTDOWN_POLL)

    def _qemu_usb_enable_spice(self):
        """Ajoute à la définition ce que la redirection USB SPICE exige.

        spice_usbredir_plan() lit la définition et n'ajoute que ce qui
        manque : affichage SPICE avant le VNC, contrôleur USB, emplacements
        spicevmc, canal de l'agent, filtre de vendeurs sur demande. Le
        changement d'affichage ne vaut qu'au démarrage suivant : une VM en
        marche est arrêtée sur accord, puis relancée."""
        target = self._qemu_usb_pick_target()
        if not target:
            return
        info = self._qemu_usb_read(target)
        if not info:
            return
        question = t(
            "Redirect only Stream Decks (vendor {vendor})? (y/N): "
        ).format(vendor=qu.DECK_VENDOR)
        vendors = (qu.DECK_VENDOR,) if self._is_yes(input(question)) else None
        try:
            steps = qu.spice_usbredir_plan(
                info["config_xml"],
                target["domain"],
                target["uri"],
                allow_vendors=vendors,
            )
        except ValueError as exc:
            print(f"  ⚠ {exc}")
            return
        if not steps:
            print(f"  ✅ {t('SPICE USB redirection is already set up.')}")
            return
        for change in steps[0]["changes"]:
            print(f"  + {change}")
        was_running = info["domstate"] != "shut off"
        if was_running:
            print(f"\n  {t('The VM must be shut off: a display change')}")
            print(f"  {t('applies at the next start.')}")
            if not self._is_yes(
                input(t("Shut it down now, and start it again after? (y/N): "))
            ):
                print(t("Cancelled."))
                return
            if not self._qemu_usb_shutdown(target):
                return
            # Relue après l'arrêt : le plan porte sur la définition que
            # libvirt tient à cet instant.
            info = self._qemu_usb_read(target)
            if not info:
                return
            steps = qu.spice_usbredir_plan(
                info["config_xml"],
                target["domain"],
                target["uri"],
                allow_vendors=vendors,
            )
        print(f"\n{t('Will execute:')}")
        runnable = self._qemu_usb_show_plan(target, steps)
        if runnable and not self._is_yes(
            input(t("Run these commands? (y/N): "))
        ):
            print(t("Cancelled."))
            runnable = []
        ok = self._qemu_usb_run_steps(target, runnable) if runnable else False
        if ok:
            print(f"✅ {t('SPICE USB redirection enabled.')}")
        if was_running:
            argv = self._qemu_usb_prefix(target) + qu.virsh_uri_argv(
                target["uri"], "start", target["domain"]
            )
            self._qemu_usb_exec(shlex.join(argv))

    # -------------------------------------------------------------- #
    # [7] Rattachement au rebranchement

    @staticmethod
    def _qemu_usb_host_cli(jump=""):
        """Le CLI qui gère le rattachement de l'hôte : celui du dépôt sur ce
        poste, sa copie de LIBEXEC_DIR sur un hyperviseur."""
        return qu.LIBEXEC_CLI if jump else CLI

    def _qemu_usb_root_cmd(self, jump, cli, *args):
        """Le CLI lancé en root sur l'hôte libvirt : « sudo » localement
        (rien quand TODO tourne déjà en root), « ssh -t <saut> sudo » à
        distance, -t pour que sudo puisse demander son mot de passe.

        -B : root n'écrit aucun __pycache__ à côté du CLI, ni dans le
        checkout ni dans le répertoire temporaire de l'hyperviseur, que le
        compte ssh ne pourrait plus effacer. ssh recolle ses arguments par
        des espaces et le shell distant les relit : la commande distante
        est donc citée une seconde fois, en UN argument, pour qu'un numéro
        de série ou un nom de VM arrive entier et inerte."""
        argv = ["python3", "-I", "-B", cli, *args]
        if jump:
            return shlex.join(["ssh", "-t", jump, shlex.join(["sudo", *argv])])
        prefixe = [] if os.geteuid() == 0 else ["sudo"]
        return shlex.join([*prefixe, *argv])

    def _qemu_usb_read_mapping(self, jump=""):
        """Les entrées de correspondance de l'hôte (MAPPING), [] quand le
        fichier manque ou ne se lit pas."""
        if jump:
            code, text = self._qemu_usb_capture(
                ["ssh", *SSH_OPTS, jump, "cat", qu.MAPPING]
            )
            text = text if code == 0 else ""
        else:
            try:
                with open(qu.MAPPING, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                text = ""
        try:
            return qu.mapping_loads(text)
        except ValueError:
            print(f"  ⚠ {t('Unreadable mapping file:')} {qu.MAPPING}")
            return []

    def _qemu_usb_cli_installed(self, jump=""):
        """Le CLI est-il posé dans LIBEXEC_DIR de l'hôte ?"""
        if not jump:
            return os.path.isfile(qu.LIBEXEC_CLI)
        code, _out = self._qemu_usb_capture(
            ["ssh", *SSH_OPTS, jump, "test", "-f", qu.LIBEXEC_CLI]
        )
        return code == 0

    def _qemu_usb_autoreattach(self):
        """Rattachement automatique d'un périphérique rebranché.

        Le rebranchement donne un nouveau numéro de périphérique, et QEMU
        perd le sien. Sur l'hôte libvirt, une règle udev lance une unité
        systemd root qui relit la correspondance périphérique → VM et
        rattache en live. Tout se pose sur l'hôte qui fait tourner la VM :
        ce poste par sudo, ou l'hyperviseur par ssh."""
        target = self._qemu_usb_pick_target()
        if not target:
            return
        jump = target["jump"]
        host = jump or t("this machine")
        print(f"\n🔁 {t('Auto-reattach on replug')} — {host}")
        choix = self._streamdeck_choice(
            t("Action:"),
            (
                ("install", t("Install the udev rule and the unit")),
                ("map", t("Reattach a device to this VM on replug")),
                ("unmap", t("Stop reattaching a device to this VM")),
                ("show", t("Show the mappings of this host")),
                ("remove", t("Remove the udev rule and the unit")),
            ),
        )
        if choix is None:
            return
        if choix == "install":
            self._qemu_usb_reattach_install(jump)
        elif choix == "remove":
            self._qemu_usb_reattach_remove(jump)
        elif choix == "map":
            self._qemu_usb_map(target)
        elif choix == "unmap":
            self._qemu_usb_unmap(target)
        else:
            self._qemu_usb_show_mapping(target)

    def _qemu_usb_confirm_run(self, cmds):
        """Montre les commandes, demande, puis les lance dans l'ordre en
        s'arrêtant à la première qui échoue. Vrai quand toutes réussissent."""
        print(f"\n{t('Will execute:')}")
        for cmd in cmds:
            print(f"  {cmd}")
        if not self._is_yes(input(t("Run these commands? (y/N): "))):
            print(t("Cancelled."))
            return False
        for cmd in cmds:
            if not self._qemu_usb_exec(cmd):
                print(f"  ⚠ {t('Command failed: ')}{cmd}")
                return False
        return True

    def _qemu_usb_reattach_install(self, jump):
        """Pose la règle udev, l'unité et la copie du CLI sur l'hôte.

        Ce poste : le CLI du dépôt, lancé par sudo, se copie lui-même dans
        LIBEXEC_DIR. Un hyperviseur : le CLI et qemu_usb.py vont par scp dans
        un répertoire temporaire créé là-bas, d'où le même install part sous
        sudo ; le répertoire est effacé ensuite, réussite ou non."""
        if not jump:
            if self._qemu_usb_confirm_run(
                [self._qemu_usb_root_cmd("", CLI, "install-autoreattach")]
            ):
                print(f"✅ {t('Auto-reattach installed.')}")
            return
        code, out = self._qemu_usb_capture(
            [
                "ssh",
                *SSH_OPTS,
                jump,
                "mktemp",
                "-d",
                "/tmp/erplibre-usb.XXXXXX",
            ]
        )
        tmp = out.strip() if code == 0 else ""
        if not tmp.startswith("/tmp/erplibre-usb."):
            message = t("Cannot create a temporary directory on {host}.")
            print(f"  ⚠ {message.format(host=jump)}")
            return
        cli = f"{tmp}/{os.path.basename(CLI)}"
        cmds = [
            shlex.join(["scp", CLI, LIB, f"{jump}:{tmp}/"]),
            self._qemu_usb_root_cmd(jump, cli, "install-autoreattach"),
        ]
        try:
            if self._qemu_usb_confirm_run(cmds):
                print(f"✅ {t('Auto-reattach installed.')}")
        finally:
            self._qemu_usb_capture(["ssh", *SSH_OPTS, jump, "rm", "-rf", tmp])

    def _qemu_usb_reattach_remove(self, jump):
        if jump and not self._qemu_usb_cli_installed(jump):
            print(f"  {t('Auto-reattach is not installed on this host.')}")
            return
        cmd = self._qemu_usb_root_cmd(
            jump, self._qemu_usb_host_cli(jump), "remove-autoreattach"
        )
        if self._qemu_usb_confirm_run([cmd]):
            print(f"✅ {t('Auto-reattach removed.')}")

    def _qemu_usb_map(self, target):
        """Ajoute « ce périphérique → cette VM » à la correspondance de
        l'hôte, par « mapping add DOMAINE VID:PID » du CLI. Le numéro de
        série n'y entre que pour départager deux périphériques identiques :
        sans lui, l'entrée suit n'importe quel exemplaire du modèle.

        Sur ce poste, le CLI du dépôt écrit la correspondance même avant
        l'installation, qui reprend ensuite ses vendeurs dans la règle.
        Un hyperviseur n'a que la copie posée par l'installation."""
        jump = target["jump"]
        if jump and not self._qemu_usb_cli_installed(jump):
            print(f"  {t('Auto-reattach is not installed on this host:')}")
            print(f"  {t('install the udev rule and the unit first.')}")
            return
        devs = self._qemu_usb_host_devices(jump)
        if devs is None:
            return
        dev = self._qemu_usb_pick_device(devs)
        if not dev:
            return
        selecteur = f"{dev['vid']}:{dev['pid']}"
        args = ["mapping", "add", target["domain"], selecteur]
        if dev.get("serial") and qu.ambiguous(devs, dev["vid"], dev["pid"]):
            args += ["--serial", dev["serial"]]
        if self._qemu_usb_confirm_run(
            [
                self._qemu_usb_root_cmd(
                    jump, self._qemu_usb_host_cli(jump), *args
                )
            ]
        ):
            ident = qu.device_id(dev["vid"], dev["pid"])
            print(f"✅ {ident} → {target['domain']}")
        if (
            dev.get("is_deck")
            and self._qemu_usb_service_state(jump)["installed"]
        ):
            print(
                f"  ⚠ {t('The ERPLibre Home deck service of this host also')}"
            )
            print(f"    {t('starts on replug: disable its autostart there.')}")

    def _qemu_usb_unmap(self, target):
        jump = target["jump"]
        entries = [
            e
            for e in self._qemu_usb_read_mapping(jump)
            if e["domain"] == target["domain"]
        ]
        if not entries:
            print(f"  {t('No mapping for this VM.')}")
            return
        for i, e in enumerate(entries, 1):
            serial = f"  [{e['serial']}]" if e.get("serial") else ""
            print(f"  [{i}] {qu.device_id(e['vid'], e['pid'])}{serial}")
        answer = input(f"{t('Which device?')} [1]: ").strip() or "1"
        if not answer.isdigit() or not 1 <= int(answer) <= len(entries):
            print(t("Cancelled."))
            return
        e = entries[int(answer) - 1]
        selecteur = f"{e['vid']}:{e['pid']}"
        # --serial "" désigne l'entrée SANS série : sans l'option, le CLI
        # retirerait aussi les entrées de ce modèle qui en portent une.
        args = ["mapping", "remove", selecteur, "--domain", e["domain"]]
        args += ["--serial", e.get("serial") or ""]
        if self._qemu_usb_confirm_run(
            [
                self._qemu_usb_root_cmd(
                    jump, self._qemu_usb_host_cli(jump), *args
                )
            ]
        ):
            print(f"✅ {t('Mapping removed.')}")

    def _qemu_usb_show_mapping(self, target):
        entries = self._qemu_usb_read_mapping(target["jump"])
        if not entries:
            print(f"  {t('No mapping on this host.')}")
            return
        for e in entries:
            serial = f"  [{e['serial']}]" if e.get("serial") else ""
            mark = "  ←" if e["domain"] == target["domain"] else ""
            print(
                f"  {qu.device_id(e['vid'], e['pid'])}{serial}"
                f"  → {e['domain']}{mark}"
            )
