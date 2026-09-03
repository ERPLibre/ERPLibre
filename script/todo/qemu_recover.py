#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu QEMU/KVM : récupérer des fichiers dans le disque d'une VM.

Une VM qui ne démarre plus garde ses fichiers : le qcow2 est là, et libguestfs
sait le monter SANS la machine. Le chemin complet : poser les outils selon la
distribution de l'hôte, lister les systèmes de fichiers du disque, en choisir
un, parcourir un répertoire, puis extraire vers l'hôte.

Frontière claire : ici on LIT un disque, on n'y écrit jamais. Toute commande
porte « --ro » — c'est ce qui rend l'opération sûre même sur une VM allumée,
et c'est aussi pourquoi rien de ce fichier ne peut abîmer une machine.
"""

import os
import shlex
import shutil
import subprocess

from script.todo.todo_i18n import t

# Le paquet qui apporte guestfish, par gestionnaire de paquets. Il ne vit pas
# dans la table du déploiement : ces outils ne servent QU'À la récupération,
# et les poser sur chaque hôte qui déploie une VM serait du poids pour rien.
#
# Les noms diffèrent d'une distribution à l'autre et le nom Debian ne marche
# nulle part ailleurs : « libguestfs-tools » sur apt, « guestfs-tools » sur
# dnf et zypper depuis que le paquet a été scindé, « libguestfs » sur pacman.
GUESTFS_PACKAGES = {
    "apt": "libguestfs-tools",
    "dnf": "guestfs-tools",
    "pacman": "libguestfs",
    "zypper": "guestfs-tools",
}

# (gestionnaire, binaire à détecter, commande d'installation)
GUESTFS_INSTALL = (
    ("apt", "apt-get", "sudo apt-get install -y"),
    ("dnf", "dnf", "sudo dnf install -y"),
    ("pacman", "pacman", "sudo pacman -S --needed --noconfirm"),
    ("zypper", "zypper", "sudo zypper --non-interactive install"),
)

# guestfish suffit à tout faire ; les deux autres ne font que présenter mieux
# ce qu'il montre déjà. Les distinguer évite d'exiger un paquet complet là où
# l'essentiel est présent.
GUESTFS_BIN_ESSENTIEL = "guestfish"
GUESTFS_BIN_CONFORT = ("virt-filesystems", "virt-df")


def guestfs_install_cmd():
    """(commande d'installation, paquet) pour cet hôte, ou (None, None).

    Rend None sur un hôte dont le gestionnaire n'est pas connu — y compris
    macOS, où libguestfs ne tourne pas : proposer une commande qui échouera
    vaut moins que de dire qu'on ne sait pas.
    """
    for cle, binaire, install in GUESTFS_INSTALL:
        if shutil.which(binaire):
            return f"{install} {GUESTFS_PACKAGES[cle]}", GUESTFS_PACKAGES[cle]
    return None, None


class QemuRecoverMixin:
    """Menu QEMU/KVM : récupérer des fichiers dans le disque d'une VM.

    Une VM qui ne démarre plus garde ses fichiers : le qcow2 est là, et
    libguestfs sait le monter SANS la machine. Le chemin complet : poser les
    outils selon la distribution de l'hôte, lister les systèmes de fichiers du
    disque, en choisir un, parcourir un répertoire, puis extraire vers l'hôte.

    Frontière claire : ici on LIT un disque, on n'y écrit jamais.
    """

    def _qemu_guestfish_cmd(self, disk, *commandes):
        """Commande guestfish en LECTURE SEULE sur ce disque.

        « --ro » n'est pas une précaution parmi d'autres : sans lui, ouvrir le
        disque d'une VM allumée corrompt son système de fichiers. Avec lui, la
        lecture est sûre à tout moment — au pire elle voit un instantané
        incohérent, ce que le menu annonce.
        """
        parties = " : ".join(commandes)
        return (
            f"guestfish --ro -a {shlex.quote(str(disk))}"
            f"{' ' + parties if parties else ''}"
        )

    def _qemu_guestfish_lines(self, disk, *commandes, timeout=180):
        """Lignes rendues par guestfish, ou [] s'il échoue.

        L'appliance libguestfs démarre un noyau : compter en secondes, pas en
        dixièmes. Un timeout généreux vaut mieux qu'un échec sur une machine
        chargée.
        """
        cmd = self._qemu_guestfish_cmd(disk, *commandes)
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if res.returncode != 0:
            if res.stderr:
                print(f"  ⚠ {res.stderr.strip()[:300]}")
            return []
        return [ln for ln in (res.stdout or "").splitlines() if ln.strip()]

    def _qemu_recover_ensure_tools(self):
        """guestfish est-il là ? Sinon, proposer de l'installer. Rend un bool.

        L'installation est PROPOSÉE et la commande montrée avant : elle pose
        un paquet de plusieurs centaines de mégaoctets, avec une image noyau.
        """
        manque_essentiel = shutil.which(GUESTFS_BIN_ESSENTIEL) is None
        confort = [b for b in GUESTFS_BIN_CONFORT if shutil.which(b) is None]
        if not manque_essentiel and not confort:
            return True
        install, paquet = guestfs_install_cmd()
        if manque_essentiel:
            print(f"\n⚠  {t('guestfish is missing: libguestfs is not here.')}")
        else:
            print(f"\n⚠  {t('Some libguestfs helpers are missing:')}")
            print(f"   {' '.join(confort)}")
        if not install:
            print(f"   {t('Unknown package manager: install libguestfs.')}")
            return not manque_essentiel
        print(f"   {t('Will execute:')} {install}")
        if not self._is_yes_default_yes(
            input(t("Install libguestfs now? (Y/n): "))
        ):
            return not manque_essentiel
        self.execute.exec_command_live(install, source_erplibre=False)
        return shutil.which(GUESTFS_BIN_ESSENTIEL) is not None

    def _qemu_recover_ready(self, name):
        """La VM est-elle dans un état où la lecture a du sens ? Rend un bool.

        Une VM ALLUMÉE écrit pendant qu'on lit : la copie voit un instantané
        qui peut être incohérent — un fichier à moitié écrit, un journal non
        rejoué. Ce n'est pas dangereux en « --ro », mais il faut le dire, et
        proposer l'arrêt propre qui rend la lecture fidèle.
        """
        etat = self._qemu_domstate(name)
        if etat != "running":
            return True
        print(f"\n⚠  {t('This VM is running.')}")
        print(f"   {t('Reading a live disk sees a possibly torn state:')}")
        print(f"   {t('a half-written file, an unreplayed journal.')}")
        choix = self._qemu_pick(
            t("What do you want to do?"),
            ["read", "shutdown", "cancel"],
            "shutdown",
            [
                t("Read anyway (read-only, no risk for the VM)"),
                t("Shut the VM down cleanly, then read"),
                t("Cancel"),
            ],
        )
        if choix == "cancel":
            return False
        if choix == "read":
            return True
        return self._qemu_shutdown_wait(name)

    def _qemu_recover_pick_filesystem(self, disk):
        """Système de fichiers choisi dans le disque, ou "" si aucun.

        « list-filesystems » les rend tous, y compris ceux qu'on ne peut pas
        monter — swap, partitions vides. Les montrer quand même : leur absence
        de la liste inquiéterait plus qu'elle n'aiderait.
        """
        cmd = self._qemu_guestfish_cmd(disk, "run", "list-filesystems")
        print(f"\n{t('Will execute:')} {cmd}")
        lignes = self._qemu_guestfish_lines(disk, "run", "list-filesystems")
        if not lignes:
            print(f"  {t('No filesystem found on this disk.')}")
            return ""
        parts, labels = [], []
        for ligne in lignes:
            # « /dev/sda3: ext4 » — le nom, puis son type.
            dev, _, typ = ligne.partition(":")
            dev, typ = dev.strip(), typ.strip()
            if not dev:
                continue
            parts.append(dev)
            labels.append(f"{dev}  {typ}")
        if not parts:
            return ""
        # Le plus grand système de fichiers non-swap est presque toujours la
        # racine : le proposer par défaut épargne un choix à qui ne connaît
        # pas le partitionnement de sa VM.
        defaut = next(
            (p for p, lab in zip(parts, labels) if "swap" not in lab),
            parts[0],
        )
        return self._qemu_pick(t("Filesystem to mount"), parts, defaut, labels)

    def _qemu_recover_browse(self, disk, part, chemin):
        """Liste un répertoire du système de fichiers monté.

        Rend les entrées trouvées."""
        cmd = self._qemu_guestfish_cmd(
            disk, "run", f"mount {part} /", f"ls {shlex.quote(chemin)}"
        )
        print(f"\n{t('Will execute:')} {cmd}")
        entrees = self._qemu_guestfish_lines(
            disk, "run", f"mount {part} /", f"ls {shlex.quote(chemin)}"
        )
        if not entrees:
            print(f"  {t('Empty or unreadable directory.')}")
            return []
        for entree in entrees:
            print(f"    {entree}")
        print(f"  {t('Total:')} {len(entrees)}")
        return entrees

    def _qemu_recover_copy_out(self, disk, part, source, dest):
        """Extrait un chemin de la VM vers l'hôte. Rend un bool.

        « copy-out » écrit DANS le répertoire de destination : il faut donc
        qu'il existe, sinon guestfish s'arrête sur une erreur qui ne dit pas
        laquelle des deux extrémités manque.
        """
        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as exc:
            print(f"  ⚠ {t('Cannot create the destination: ')}{exc}")
            return False
        cmd = self._qemu_guestfish_cmd(
            disk,
            "run",
            f"mount {part} /",
            f"copy-out {shlex.quote(source)} {shlex.quote(dest)}",
        )
        print(f"\n{t('Will execute:')} {cmd}")
        code = self.execute.exec_command_live(cmd, source_erplibre=False)
        if code:
            print(f"  ⚠ {t('Extraction failed.')}")
            return False
        cible = os.path.join(dest, os.path.basename(source.rstrip("/")))
        print(f"\n✅ {t('Extracted to: ')}{cible}")
        return True

    def _qemu_recover_diagnostics(self, disk):
        """Commandes de diagnostic sur le disque, sans rien monter à la main.

        Chacune répond à une question précise qu'on se pose quand la lecture
        ne donne pas ce qu'on attend : les partitions existent-elles, restent-
        elles de la place, le système est-il reconnu, l'appliance
        démarre-t-elle.
        """
        q = shlex.quote(str(disk))
        sondes = [
            (
                t("Partitions and sizes"),
                f"virt-filesystems -a {q} --long -h --all",
            ),
            (t("Free space per filesystem"), f"virt-df -a {q} -h"),
            (
                t("Detected operating system"),
                self._qemu_guestfish_cmd(disk, "run", "inspect-os"),
            ),
            (
                t("Does the libguestfs appliance boot?"),
                "libguestfs-test-tool",
            ),
        ]
        for titre, cmd in sondes:
            print(f"\n── {titre} ──")
            print(f"{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_recover_files(self):
        """Récupère des fichiers dans le disque d'une VM, sans la démarrer."""
        print(f"\n💾 {t('Recover files from a VM disk (libguestfs)')}")
        if not self._qemu_recover_ensure_tools():
            return
        self._qemu_list_vms()
        print()
        name = input(t("VM name or ID: ")).strip()
        if not name:
            print(t("VM name is required!"))
            return
        name = self._qemu_domname(name)
        disk = self._qemu_main_disk(name)
        if not disk:
            print(f"  ⚠ {t('No disk found for this VM.')}")
            return
        print(f"  {t('Disk:')} {disk}")
        if not self._qemu_recover_ready(name):
            print(t("Cancelled."))
            return
        if self._is_yes(input(t("Run the diagnostics first? (y/N): "))):
            self._qemu_recover_diagnostics(disk)
        part = self._qemu_recover_pick_filesystem(disk)
        if not part:
            return
        chemin = input(t("Directory to list [/]: ")).strip() or "/"
        while True:
            self._qemu_recover_browse(disk, part, chemin)
            suite = input(
                t("Another directory, or Enter to extract: ")
            ).strip()
            if not suite:
                break
            chemin = suite
        source = input(f"{t('Path to extract')} [{chemin}] : ").strip()
        source = source or chemin
        defaut_dest = f"/tmp/{name}-backup"
        dest = input(f"{t('Destination on the host')} [{defaut_dest}] : ")
        dest = dest.strip() or defaut_dest
        self._qemu_recover_copy_out(disk, part, source, dest)
