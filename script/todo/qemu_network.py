#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu QEMU/KVM : le sous-réseau où vivent les VM.

Deux entrées pour une seule question — quel /24 le réseau libvirt sert-il, et
que faire quand ce n'est plus celui que les VM attendent. Voir l'état ne
modifie rien ; le recréer arrête les VM attachées, redéfinit le réseau, puis
redémarre ces VM.

Le travail est fait par script/qemu/network_qemu.py, lancé comme un programme
et non importé : c'est lui qui porte l'ordre des trois gestes, et il reste
utilisable seul sur un hôte où le menu ne tourne pas — celui, justement, qui
vient de perdre son réseau.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que celles
des autres fichiers, elles s'appellent donc par « self. » sans rien importer.
"""

import os

from script.todo.qemu_privilege import needs_sudo
from script.todo.todo_i18n import t

# Le préfixe d'origine du « default » de libvirt, proposé par défaut. Il fait
# autorité dans network_qemu.py ; répété ici pour que l'invite ait une valeur à
# afficher sans charger le script.
PREFIXE_LIBVIRT = "192.168.122"


class QemuNetworkMixin:
    """Menu QEMU/KVM : le sous-réseau où vivent les VM."""

    def _qemu_network_script_path(self):
        """Chemin absolu vers script/qemu/network_qemu.py."""
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "qemu",
            "network_qemu.py",
        )
        return os.path.realpath(path)

    def _qemu_network_cmd(self, *args):
        """La commande du script, sudo laissé à qui en a besoin.

        « --no-sudo » quand le groupe libvirt suffit : préfixer sudo ne donne
        alors aucun droit de plus et réclame un mot de passe pour rien.
        """
        parts = [self._qemu_network_script_path(), *args]
        if not needs_sudo():
            parts.append("--no-sudo")
        return " ".join(parts)

    def _qemu_network_status(self):
        """Affiche le sous-réseau servi, les VM attachées et leurs baux."""
        cmd = self._qemu_network_cmd("--status")
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_network_recreate(self):
        """Recrée le sous-réseau : arrête les VM, redéfinit, redémarre.

        L'état est montré AVANT la question : le préfixe à viser se lit sur
        celui que le réseau sert aujourd'hui, et personne ne devrait avoir à
        deviner ce qu'il va changer.
        """
        self._qemu_network_status()
        print(f"\n{t('Recreating the subnet does three things:')}")
        print(f"  0. {t('shut down the VMs attached to the network')}")
        print(f"  1. {t('redefine the network on the wanted prefix')}")
        print(f"  2. {t('start those same VMs again')}")
        prefixe = input(
            f"\n{t('Target prefix')} [{PREFIXE_LIBVIRT}] : "
        ).strip()
        prefixe = prefixe or PREFIXE_LIBVIRT
        reseau = input(f"{t('libvirt network')} [default] : ").strip()
        reseau = reseau or "default"
        forcer = self._is_yes(
            input(t("Power off VMs that ignore the shutdown? (y/N): "))
        )
        args = ["--recreate", "--network", reseau, "--prefix", prefixe]
        if forcer:
            args.append("--force-off")
        cmd = self._qemu_network_cmd(*args)
        print(f"\n{t('Will execute:')} {cmd}")
        # La confirmation est posée par le script lui-même : il la pose sur
        # /dev/tty, donc elle fonctionne aussi quand il est lancé hors du menu.
        self.execute.exec_command_live(cmd, source_erplibre=False)
