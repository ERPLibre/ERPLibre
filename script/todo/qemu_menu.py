#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu QEMU/KVM : l'entr\u00e9e, le catalogue et les statistiques.\n\nC'est la porte du menu (\u00ab prompt_execute_qemu \u00bb) et ce qui sert \u00e0 TOUT le\nreste : le catalogue des distributions, le choix d'une version et d'une\narchitecture, la v\u00e9rification des outils de l'h\u00f4te. Les quatre autres fichiers\ndu menu QEMU s'appuient sur celui-ci.\n\nMixin de la classe TODO : ses m\u00e9thodes vivent sur la m\u00eame instance que celles\ndes autres fichiers, elles s'appellent donc par \u00ab self. \u00bb sans rien importer."""

import os
import shutil
from datetime import datetime

import click

from script.todo.todo_i18n import t


class QemuMenuMixin:
    """Menu QEMU/KVM : l'entr\u00e9e, le catalogue et les statistiques.\n\nC'est la porte du menu (\u00ab prompt_execute_qemu \u00bb) et ce qui sert \u00e0 TOUT le\nreste : le catalogue des distributions, le choix d'une version et d'une\narchitecture, la v\u00e9rification des outils de l'h\u00f4te. Les quatre autres fichiers\ndu menu QEMU s'appuient sur celui-ci.\n\nMixin de la classe TODO : ses m\u00e9thodes vivent sur la m\u00eame instance que celles\ndes autres fichiers, elles s'appellent donc par \u00ab self. \u00bb sans rien importer."""

    def _qemu_script_path(self):
        """Chemin absolu vers script/qemu/deploy_qemu.py."""
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "qemu",
            "deploy_qemu.py",
        )
        return os.path.realpath(path)

    def _qemu_default_ssh_key(self):
        """Première clé publique SSH trouvée dans ~/.ssh, sinon ''."""
        for name in ("id_ed25519.pub", "id_rsa.pub"):
            path = os.path.expanduser(f"~/.ssh/{name}")
            if os.path.exists(path):
                return path
        return ""

    # distro -> (versions affichées, version par défaut). Source de vérité =
    # deploy_qemu.py ; ceci ne sert qu'au sélecteur interactif.
    _QEMU_DISTROS = {
        "ubuntu": (["24.04", "25.10", "26.04"], "24.04"),
        "debian": (["11", "12", "13"], "12"),
        "fedora": (["41", "42", "43", "44"], "42"),
        "almalinux": (["9", "10"], "9"),
        "rocky": (["9", "10"], "10"),
        # Leap 16.0 par défaut : numérotée et stable. Tumbleweed reste offerte,
        # comme banc d'essai des ruptures à venir. Voir OPENSUSE_VERSIONS dans
        # deploy_qemu.py, qui fait autorité sur le catalogue.
        "opensuse": (["16.0", "tumbleweed"], "16.0"),
        "arch": (["latest"], "latest"),
        # Proxmox VE : le numéro est celui de PVE, pas de Debian (9 = trixie).
        # Une seule version au catalogue, la seule qui couvre amd64 ET arm64 —
        # voir PROXMOX_VERSIONS dans deploy_qemu.py, qui fait autorité.
        "proxmox": (["9"], "9"),
    }

    def _qemu_prompt_distro(self):
        """Demande la distribution (défaut : ubuntu)."""
        distros = list(self._QEMU_DISTROS)
        print(f"\n{t('Distribution:')}")
        for i, d in enumerate(distros, 1):
            print(f"  [{i}] {d}")
        sel = input(t("Choice (number or name, default: ubuntu): ")).strip()
        if not sel:
            return "ubuntu"
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(distros):
                return distros[idx]
        except ValueError:
            if sel in distros:
                return sel
        print(t("Invalid selection, using ubuntu"))
        return "ubuntu"

    def _qemu_prompt_version(self, distro):
        """Demande la version pour la distro (défaut = version par défaut)."""
        versions, default = self._QEMU_DISTROS.get(distro, ([], ""))
        print(f"\n{t('Version for')} {distro.capitalize()} :")
        for i, v in enumerate(versions, 1):
            suffix = " *" if v == default else ""
            stat = self._qemu_stat_avg("version", v, distro)
            print(f"  [{i}] {v}{suffix}{stat}")
        sel = input(
            f"{t('Choice (number or version, blank = default):')} "
        ).strip()
        if not sel:
            return default
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(versions):
                return versions[idx]
        except ValueError:
            if sel in versions:
                return sel
        print(f"{t('Invalid selection, using')} {default}")
        return default

    # Repli SEULEMENT : la table qui fait autorité est ARCH_DISTRO_SUPPORT de
    # deploy_qemu.py, lue par _qemu_arch_distros. Ces tuples ont longtemps été
    # une copie à la main, avec le commentaire « cohérent avec deploy_qemu » en
    # guise de garantie — et la cohérence a rompu à la première évolution :
    # Debian a gagné s390x là-bas sans l'obtenir ici, donc l'écran ne le
    # proposait pas. On ne les garde que pour le cas où l'import échoue.
    _QEMU_S390X_DISTROS = (
        "ubuntu",
        "almalinux",
        "rocky",
        "fedora",
        "opensuse",
        "debian",
    )

    _QEMU_ARM64_DISTROS = (
        "ubuntu",
        "debian",
        "fedora",
        "almalinux",
        "rocky",
        "opensuse",
    )

    # Alias distro pour l'affichage (jeton générique -> nom courant).
    _QEMU_ARCH_ALIAS = {"amd64": "x86_64", "arm64": "aarch64"}

    def _qemu_arch_distros(self, arch):
        """Distros supportant `arch` (None = toutes, cas amd64).

        Lu dans deploy_qemu.py, qui refuse aussi les combinaisons qu'il
        n'annonce pas : une seule table, donc aucun écran ne peut proposer un
        choix rejeté ensuite. « amd64 » n'y figure pas et rend None, ce qui
        veut bien dire « toutes » — c'est le contrat attendu ici.
        """
        try:
            table = getattr(self._qemu_import_module(), "ARCH_DISTRO_SUPPORT")
        except Exception:
            # Repli sur les copies locales : mieux vaut un catalogue figé
            # qu'un écran vide si deploy_qemu.py est absent ou cassé.
            if arch == "s390x":
                return self._QEMU_S390X_DISTROS
            if arch == "arm64":
                return self._QEMU_ARM64_DISTROS
            return None
        return table.get(arch)

    def _qemu_last_run_line(self):
        """Ligne « dernière install » (distro version [arch] en durée), depuis
        l'historique (.venv.erplibre) ; '' si aucune donnée."""
        try:
            from script.todo import qemu_install_monitor as mon

            r = mon.last_run()
            if r:
                return (
                    f"  ℹ {t('Last install:')} {r.get('distro')} "
                    f"{r.get('version')} [{r.get('arch')}] — "
                    f"{mon._fmt_secs(r.get('seconds', 0))}"
                )
        except Exception:
            pass
        return ""

    def _qemu_stat_avg(self, field, value, distro=None):
        """Suffixe « · ~5m moy (3) » : durée d'install MOYENNE historique pour
        cette archi/distro/version (fichier .venv.erplibre), ou '' si aucune
        donnée. Pour field='version', `distro` est requis."""
        try:
            from script.todo import qemu_install_monitor as mon

            if field == "arch":
                secs, n = mon.avg_by_arch(value)
            elif field == "version":
                secs, n = mon.avg_by_version(distro, value)
            else:
                secs, n = mon.avg_by_distro(value)
            if secs:
                return f"  · ~{mon._fmt_secs(secs)} {t('avg')} ({n})"
        except Exception:
            pass
        return ""

    def _qemu_ask_arch(self, opts, native, allow_all=False):
        """Affiche les architectures `opts` (natif marqué d'un *) et renvoie le
        choix. Si `allow_all`, propose aussi [all] = toutes les archis (renvoie
        « all »). Toute arch non native est ÉMULÉE (TCG, lente)."""
        print(f"\n{t('Architecture:')}")
        for i, a in enumerate(opts, 1):
            alias = self._QEMU_ARCH_ALIAS.get(a)
            label = f"{a} ({alias})" if alias else a
            if a == native:
                label += f" — {t('native')} *"
            elif a == "s390x":
                label += f"  ({t('IBM Z — emulated, slow; Ubuntu only')})"
            elif a == "arm64":
                label += f"  ({t('ARM 64-bit — emulated, slow')})"
            else:
                label += f"  ({t('emulated, slow')})"
            print(f"  [{i}] {label}{self._qemu_stat_avg('arch', a)}")
        if allow_all:
            print(f"  [all] {t('All supported architectures')}")
        sel = (
            input(f"{t('Choice (number or name, blank = native):')} ")
            .strip()
            .lower()
        )
        if not sel:
            return native
        if allow_all and sel in ("all", "*"):
            note = t("(includes emulated architectures — some VMs are slow)")
            print(f"⚠  {note}")
            return "all"
        chosen = None
        for i, a in enumerate(opts, 1):
            if sel in (str(i), a, self._QEMU_ARCH_ALIAS.get(a)):
                chosen = a
                break
        if chosen is None:
            print(f"{t('Invalid selection, using')} {native}")
            return native
        if chosen != native:
            warn = t(
                "This architecture is emulated (TCG): boot and install are"
                " much slower than the native one."
            )
            print(f"⚠  {warn}")
        return chosen

    def _qemu_prompt_infra_arch(self):
        """Architecture du parc (défaut : native de l'hôte, marquée d'un *).
        Toute arch non native est émulée ; le catalogue est ensuite restreint
        aux distros publiant cette arch."""
        native = self._native_arch()
        opts = ["amd64", "arm64", "s390x"]
        if native not in opts:  # hôte exotique : garder le natif en tête
            opts.insert(0, native)
        return self._qemu_ask_arch(opts, native, allow_all=True)

    def _qemu_list_images(self):
        """Affiche la liste des distros/versions et leurs specs."""
        cmd = f"{self._qemu_script_path()} --list-images"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_ensure_tools(self):
        """virsh absent : proposer l'installation plutôt que de laisser
        chaque commande échouer sur « sudo: virsh: command not found ».

        deploy_qemu.py --setup-host connaît les paquets de chaque
        distribution ; on ne devine donc rien ici, on le délègue."""
        if shutil.which("virsh"):
            return True
        print(f"\n⚠  {t('virsh is missing: libvirt is not installed here.')}")
        print(f"   {t('Every VM command will fail until it is.')}")
        if not self._is_yes_default_yes(
            input(t("Install the QEMU/libvirt tools now? (Y/n): "))
        ):
            return False
        # Sans --assume-yes-reboot : accepter d'installer des paquets n'est
        # pas accepter de perdre ce qui tourne sur la machine. Quand le noyau
        # a été remplacé depuis le démarrage, deploy_qemu.py pose la question
        # sur /dev/tty, et un refus laisse l'hôte avec ses paquets posés.
        cmd = (
            "sudo ./script/qemu/deploy_qemu.py --setup-host --assume-yes"
            " --reboot-if-needed"
        )
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        if shutil.which("virsh"):
            print(f"✅ {t('libvirt is available.')}")
            return True
        # Sur une distribution à noyau roulant, --setup-host peut demander un
        # redémarrage avant que les modules soient chargeables.
        print(f"⚠  {t('virsh still missing; a reboot may be required.')}")
        return False

    def prompt_execute_qemu(self):
        print(f"🤖 {t('Deploy a QEMU/KVM virtual machine (libvirt)!')}")
        script_path = self._qemu_script_path()
        if not os.path.isfile(script_path):
            print(f"{t('QEMU deploy script not found: ')}{script_path}")
            return False
        self._qemu_ensure_tools()
        choices = [
            {"section": t("Deployment")},
            {"prompt_description": t("Deploy VM(s) (one or many)")},
            {
                "prompt_description": t(
                    "Preview a deployment (dry-run, no sudo)"
                )
            },
            {"prompt_description": t("Download a cloud image only")},
            {
                "prompt_description": t(
                    "Reopen install monitoring (last run / history)"
                )
            },
            {"section": t("Manage")},
            {"prompt_description": t("List VMs (virsh list --all)")},
            {"prompt_description": t("Show a VM IP address")},
            {"prompt_description": t("Open the console on a VM")},
            {"prompt_description": t("Resize a VM disk")},
            {"prompt_description": t("Delete VM(s)")},
            {"prompt_description": t("Clean up QEMU (orphan files)")},
            {
                "prompt_description": t(
                    "Test a VM (open Odoo in a CLI browser)"
                )
            },
            {"prompt_description": t("Statistics (installs, durations, VMs)")},
            {
                "prompt_description": t(
                    "SSH configuration (~/.ssh/config, ProxyJump)"
                )
            },
            {
                "prompt_description": t(
                    "Remote desktop tunnel (VNC/RDP through SSH)"
                )
            },
            {
                "prompt_description": t(
                    "Android emulator (start, tunnel, scrcpy)"
                )
            },
            {"section": t("Catalog")},
            {"prompt_description": t("List available images and specs")},
        ]
        config_entries = self.config_file.get_config("qemu_from_makefile")
        if config_entries:
            choices.extend(config_entries)
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._qemu_deploy(dry_run=False)
            elif status == "2":
                self._qemu_deploy(dry_run=True)
            elif status == "3":
                self._qemu_download_image()
            elif status == "4":
                self._qemu_reopen_monitor()
            elif status == "5":
                self._qemu_list_vms(ask_advanced=True)
            elif status == "6":
                self._qemu_show_ip()
            elif status == "7":
                self._qemu_console()
            elif status == "8":
                self._qemu_resize_disk()
            elif status == "9":
                self._qemu_delete_vm()
            elif status == "10":
                self._qemu_cleanup()
            elif status == "11":
                self._qemu_test_vm()
            elif status == "12":
                self._qemu_stats()
            elif status == "13":
                self._qemu_ssh_config_menu()
            elif status == "14":
                self._qemu_tunnel_menu()
            elif status == "15":
                self._qemu_emulator_menu()
            elif status == "16":
                self._qemu_list_images()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    # Ignore les entrées de section pour mapper le numéro
                    # affiché sur la bonne commande (config incluse).
                    real = [c for c in choices if not c.get("section")]
                    if 0 < int_cmd <= len(real):
                        cmd_no_found = False
                        self.execute_from_configuration(real[int_cmd - 1])
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("Command not found !"))

    def _qemu_stats(self):
        """Statistiques d'utilisation de QEMU, et remise à zéro.

        Tout vient de l'historique tenu par le moniteur d'installation
        (.venv.erplibre/qemu_install_stats.json) et de l'état libvirt courant.
        """
        # Cet écran ne lit que des fichiers : il n'a pas besoin de Textual,
        # contrairement au dashboard du même module. Un échec d'import est
        # donc un vrai problème de module, pas une dépendance manquante.
        try:
            from script.todo import qemu_install_monitor as mon
        except ImportError as exc:
            print(f"{t('Command failed: ')}{exc}")
            return

        while True:
            summary = mon.stats_summary()
            print(f"\n📊 {t('QEMU statistics')}")
            if not summary:
                print(f"   {t('No installation recorded yet.')}")
            else:
                rate = 100 * summary["ok"] // max(summary["total"], 1)
                print(f"\n── {t('Installations')} ──")
                print(
                    f"   {t('Total'):<18}: {summary['total']}"
                    f"  ({summary['ok']} {t('succeeded')},"
                    f" {summary['failed']} {t('failed')} — {rate} %)"
                )
                if summary["first_ts"]:
                    days = max(
                        1,
                        (summary["last_ts"] - summary["first_ts"]) // 86400,
                    )
                    print(
                        f"   {t('Period'):<18}:"
                        f" {self._qemu_stamp(summary['first_ts'])}"
                        f" → {self._qemu_stamp(summary['last_ts'])}"
                        f"  ({days} {t('days')})"
                    )
                print(
                    f"   {t('Median duration'):<18}:"
                    f" {mon._fmt_secs(summary['median'])}"
                    f"   ({t('min')} {mon._fmt_secs(summary['min'])} ·"
                    f" {t('max')} {mon._fmt_secs(summary['max'])})"
                )
                print(
                    f"   {t('Cumulated time'):<18}:"
                    f" {mon._fmt_secs(summary['total_secs'])}"
                )
                for field, title in (
                    ("distro", t("By distribution")),
                    ("version", t("By version")),
                    ("arch", t("By architecture")),
                ):
                    rows = mon.stats_by(field)
                    if not rows:
                        continue
                    print(f"\n── {title} ──")
                    for key, count, avg, failed in rows[:8]:
                        # Un groupe sans aucun succès n'a pas de moyenne : « — »
                        # plutôt qu'un « ~0s » trompeur.
                        moy = f"~{mon._fmt_secs(avg)}" if count else "—"
                        fail = (
                            f"   ⚠ {failed} {self._plural(t('failure'), failed)}"
                            if failed
                            else ""
                        )
                        print(f"   {key:<22} {count:>3} ×   {moy:<8}{fail}")

            self._qemu_stats_vms(mon)
            print(f"\n   [r] {t('Reset the statistics')}")
            print(f"   [0] {t('Back')}")
            answer = input(f"💬 {t('Your choice')} : ").strip().lower()
            if answer in ("", "0"):
                return
            if answer == "r":
                if not summary:
                    print(f"   {t('Nothing to reset.')}")
                    continue
                confirm = input(
                    f"   {t('Erase')} {summary['total']}"
                    f" {t('recorded runs')}? (y/N): "
                ).strip()
                if self._is_yes(confirm):
                    count = mon.reset_stats()
                    print(f"   ✅ {count} {t('runs erased')}.")
                else:
                    print(f"   {t('Cancelled.')}")

    @staticmethod
    def _qemu_stamp(ts):
        """Horodatage court « 2026-08-01 »."""
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            return "?"

    def _qemu_stats_vms(self, mon):
        """Machines virtuelles actuelles : nombre, états, place disque."""
        try:
            states = mon.virsh_domstates()
        except Exception:
            return
        if not states:
            return
        running = sum(1 for s in states.values() if s == "running")
        total_bytes = 0
        counted = 0
        for name in states:
            try:
                # vm_disk_path attend un dict ; le chemin par défaut de libvirt
                # se déduit du seul nom.
                size = mon.disk_actual_size(mon.vm_disk_path({"name": name}))
            except Exception:
                size = None
            if size:
                total_bytes += size
                counted += 1
        print(f"\n── {t('Virtual machines')} ──")
        print(
            f"   {t('Defined'):<18}: {len(states)}"
            f"  ({running} {t('running')},"
            f" {len(states) - running} {t('stopped')})"
        )
        if counted:
            print(
                f"   {t('Disk used'):<18}:"
                f" {mon._fmt_size(total_bytes)}"
                f"  ({counted} {self._plural(t('image'), counted)})"
            )
