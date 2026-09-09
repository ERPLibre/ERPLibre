#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Lima : l'outil, les instances, et ce qui n'est pas éprouvé.

La frontière avec `script/vm/lima.py` est nette : ici on DEMANDE, on affiche
et on joue ; là-bas on compose du texte et on l'analyse. Ce fichier n'écrit
aucun argument de `limactl` en littéral — les rendus viennent du module, et
c'est ce qui fait que la confrontation de `long_test/` éprouve le code
livré plutôt que ses propres copies.

L'ÉCRAN DIT QUE LE BACKEND N'EST PAS ÉPROUVÉ. « Non éprouvé » ne veut pas
dire douteux : il veut dire NON CONFRONTÉ à un vrai « limactl ». Un écran
muet là-dessus laisse croire l'inverse, et c'est le seul backend du dépôt
dans cet état.

LA COMMANDE SE MONTRE AVANT DE SE JOUER. Deux raisons, et la seconde est la
vraie : une faute de frappe se voit, et surtout une opération qui détruit se
relit. `limactl delete -f` ne repose aucune question.
"""

import os
import subprocess

import click

from script.lib_valid import NAME_RE, ValidationError
from script.todo import host_os
from script.todo.todo_i18n import t
from script.vm import lima, lima_install
from script.todo.vm_backend_choice import UNPROVEN_NOTE
from script.vm.backend import LIMA, is_proven

# Où vivent les configurations d'instance. Sous le répertoire ERPLibre de
# l'utilisateur, et pas dans le dépôt : une instance appartient à la
# personne qui la lance, et un fichier dans le checkout se ferait emporter
# par un ratissage d'indexation.
LIMA_DIR = "~/.erplibre/lima"

# Ce qu'on écrit pour chaque route d'acquisition. La table est exhaustive :
# `tool_sentence` lève sur un verdict qu'elle ne connaît pas plutôt que de
# rendre une chaîne vide, qui s'afficherait comme un succès.
TOOL_SENTENCES = {
    lima_install.MANAGER: (
        "The package manager provides it. Its signature chain covers the"
        " whole index, which is stronger than a hand-copied checksum."
    ),
    lima_install.OK: (
        "A pinned release matches. Download it, then verify the checksum"
        " BEFORE running anything from the archive."
    ),
    lima_install.MANAGER_ABSENT: (
        "The package manager of this host is not installed. Install it, or"
        " read a checksum off a verified release and pin it in RELEASES."
    ),
    lima_install.NO_ROUTE: (
        "No package manager is known for this host, and no release is"
        " pinned. Both routes are shut: read a checksum off a verified"
        " release and pin it in RELEASES."
    ),
    lima_install.UNPINNED: (
        "The version asked for is not pinned. « latest » names a different"
        " thing on every call, so there is nothing to verify."
    ),
    lima_install.UNKNOWN_RELEASE: (
        "That version carries no checksum in RELEASES. A checksum is read"
        " off a release, it is never invented."
    ),
    lima_install.UNKNOWN_TARGET: (
        "No archive is published for this system and architecture."
    ),
    lima_install.CHECKSUM_MISMATCH: (
        "The checksum does NOT match. Run nothing from that archive: this"
        " is the last moment where nothing has been executed yet."
    ),
    lima_install.FILE_ABSENT: "The archive is not where it was expected.",
}


def tool_sentence(kind: str) -> str:
    """La phrase d'une route d'acquisition, traduite.

    Lève sur un verdict inconnu. Un `dict.get` rendant "" afficherait une
    ligne vide, qui se lit comme « tout va bien » — exactement le contraire
    de ce qu'un refus veut dire.
    """
    if kind not in TOOL_SENTENCES:
        raise KeyError(f"route sans phrase : {kind!r}")
    return t(TOOL_SENTENCES[kind])


def config_path(name: str, base: str = LIMA_DIR) -> str:
    """Le chemin du YAML de cette instance.

    Le nom est VALIDÉ par l'appelant avant d'arriver ici : il devient un
    nom de fichier, et un « ../ » écrirait ailleurs.
    """
    return os.path.join(os.path.expanduser(base), f"{name}.yaml")


def instance_line(instance) -> str:
    """Une ligne d'inventaire : ce qu'on voit sans déplier.

    L'état est dit en clair plutôt que par une couleur : la sortie d'un menu
    se colle dans un rapport, où la couleur ne survit pas.
    """
    marque = "▶" if lima.is_running(instance) else "■"
    detail = instance.arch or "?"
    if instance.ssh_port:
        detail += f", ssh {instance.ssh_port}"
    return f"{marque} {instance.name} [{instance.status or '?'}] ({detail})"


class LimaMenuMixin:
    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def prompt_execute_lima(self):
        print(f"🍋 {t('Lima: VMs on macOS and Linux, by name')}")
        if not is_proven(LIMA):
            # Dit à CHAQUE affichage, et non une fois : l'écran se rouvre,
            # et une note vue au premier passage ne tient pas au dixième.
            print(f"  * {t(UNPROVEN_NOTE)}")
        choices = [
            {"section": t("The tool")},
            {"prompt_description": t("Lima - How this host gets the tool")},
            {"section": t("Instances")},
            {"prompt_description": t("Lima - List the instances")},
            {"prompt_description": t("Lima - Create and start an instance")},
            {"prompt_description": t("Lima - Start an instance")},
            {"prompt_description": t("Lima - Stop an instance")},
            {"prompt_description": t("Lima - Delete an instance")},
            {"prompt_description": t("Lima - Open a shell in an instance")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._lima_tool()
            elif status == "2":
                self._lima_list()
            elif status == "3":
                self._lima_create()
            elif status == "4":
                self._lima_power("start")
            elif status == "5":
                self._lima_power("stop")
            elif status == "6":
                self._lima_delete()
            elif status == "7":
                self._lima_shell()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------
    # L'outil
    # ------------------------------------------------------------------
    def _lima_tool(self):
        """Par où cet hôte obtient l'outil, et s'il l'a déjà."""
        import shutil

        chemin = shutil.which(lima.LIMACTL)
        print(
            f"  {t('Host OS:')} {host_os.host_os()}"
            f"    {t('Architecture:')} {host_os.arch_token()}"
        )
        if chemin:
            print(f"  ✓ {lima.LIMACTL} : {chemin}")
        else:
            print(f"  ✗ {lima.LIMACTL} {t('is not installed.')}")
        route = lima_install.route(host_os.host_os(), host_os.arch_token())
        print(f"  {tool_sentence(route.kind)}")
        if route.command:
            print(f"  {t('Run:')} {route.command}")
        if route.release is not None:
            print(f"  {t('Archive:')} {route.release.url}")
            print(f"  {t('SHA-256:')} {route.release.sha256}")

    # ------------------------------------------------------------------
    # Lire l'inventaire
    # ------------------------------------------------------------------
    def _lima_instances(self):
        """Les instances, ou None si l'outil n'a pas répondu.

        None et non un tuple vide : « aucune instance » et « l'outil est
        absent » se corrigent de deux côtés opposés, et les confondre ferait
        proposer de créer une instance sur une machine sans outil.
        """
        argv = lima.list_argv()
        try:
            resultat = subprocess.run(
                argv, capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.SubprocessError) as panne:
            print(f"  ✗ {lima.display(argv)} : {panne}")
            return None
        if resultat.returncode:
            print(
                f"  ✗ {lima.display(argv)} :"
                f" {(resultat.stderr or '').strip()[:200]}"
            )
            return None
        return lima.parse_instances(resultat.stdout)

    def _lima_list(self):
        instances = self._lima_instances()
        if instances is None:
            return
        if not instances:
            print(f"  {t('No instance yet.')}")
            return
        for instance in instances:
            print(f"  {instance_line(instance)}")

    def _lima_select(self, running=None):
        """Le nom d'une instance, "" si l'utilisateur renonce.

        `running` filtre sur l'état : proposer d'arrêter une instance déjà
        éteinte fait jouer une commande qui échoue, et le refus de l'outil
        ne dit pas que le choix était le mauvais.
        """
        instances = self._lima_instances()
        if instances is None:
            return ""
        if running is not None:
            instances = tuple(
                i for i in instances if lima.is_running(i) is running
            )
        if not instances:
            print(f"  {t('No instance matches.')}")
            return ""
        for rang, instance in enumerate(instances, start=1):
            print(f"  [{rang}] {instance_line(instance)}")
        reponse = input(f"{t('Instance number (empty to cancel): ')}").strip()
        if not reponse.isdigit() or not 1 <= int(reponse) <= len(instances):
            return ""
        return instances[int(reponse) - 1].name

    # ------------------------------------------------------------------
    # Créer
    # ------------------------------------------------------------------
    def _lima_ask_name(self):
        """Un nom d'instance VALIDÉ, "" si l'utilisateur renonce.

        Validé ici parce qu'il devient à la fois un argument de commande et
        un nom de fichier : un « ../ » écrirait la configuration ailleurs, et
        une espace couperait la commande en deux.
        """
        brut = input(f"{t('Instance name: ')}").strip()
        if not brut:
            return ""
        fiche = {"name": brut}
        try:
            from script import lib_valid

            lib_valid.text(fiche, "name", t("Instance name"), pattern=NAME_RE)
        except ValidationError as refus:
            print(f"! {refus}")
            return ""
        return fiche["name"]

    def _lima_create(self):
        """Écrit la configuration, la montre, puis démarre l'instance.

        LA CONFIGURATION SE MONTRE ENTIÈRE. Elle décide de ce que l'invité
        monte de l'hôte et de ce qu'il expose ; la relire coûte dix secondes
        et c'est le seul moment où on le fera.
        """
        nom = self._lima_ask_name()
        if not nom:
            return
        arch = host_os.arch_token()
        macos = host_os.is_macos()
        image = self._lima_image(arch)
        texte = lima.render_config(image, arch=arch, macos=macos)
        chemin = config_path(nom)

        print(
            f"  {t('Host OS:')} {host_os.host_os()}"
            f"    {t('Architecture:')} {arch}"
        )
        print(f"  {t('Config file:')} {chemin}")
        print("  ---")
        for ligne in texte.splitlines():
            print(f"  {ligne}")
        print("  ---")
        # `host_limits` et non `unenforceable` : aucune posture n'est
        # choisie ici, et sans posture la seconde ne promet rien — donc elle
        # ne dirait RIEN, ce qui laisserait croire une instance joignable.
        for manque in lima.host_limits(macos):
            print(f"  ⚠ {t('Not held by this config:')} {manque}")
        argv = lima.start_argv(nom, chemin)
        print(f"  {t('Will execute:')} {lima.display(argv)}")
        if not self._is_yes(input(f"\n{t('Write and start? (o/N): ')}")):
            return

        # Le répertoire est créé en 0700 : une configuration d'instance dit
        # ce que la VM monte et expose, ce qui n'a pas à se lire de partout.
        os.makedirs(os.path.dirname(chemin), mode=0o700, exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write(texte)
        self.execute.exec_command_live(
            lima.display(argv), source_erplibre=False
        )

    def _lima_image(self, arch):
        """L'URL de l'image cloud pour cette architecture.

        Emprunte la convention DÉJÀ EN SERVICE du déploiement qemu plutôt
        que d'en écrire une seconde : un gabarit recopié diverge de sa copie
        au premier changement d'amont. L'import est tardif — le module est
        un CLI, et son import ne coûte rien mais n'a rien à faire au
        démarrage du menu.
        """
        import importlib.util

        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        chemin = os.path.join(racine, "script", "qemu", "deploy_qemu.py")
        spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.image_url("ubuntu", "noble", arch, "24.04")

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def _lima_power(self, action):
        """Démarre ou arrête. Refuse une action hors vocabulaire.

        Le filtre d'état vient de l'action : proposer d'arrêter ce qui est
        déjà éteint fait jouer une commande qui échoue pour rien.
        """
        if action not in lima.LIFECYCLE:
            print(t("Command not found !"))
            return
        nom = self._lima_select(running=(action == "stop"))
        if not nom:
            return
        argv = (
            lima.start_argv(nom) if action == "start" else lima.stop_argv(nom)
        )
        print(f"  {t('Will execute:')} {lima.display(argv)}")
        self.execute.exec_command_live(
            lima.display(argv), source_erplibre=False
        )

    def _lima_delete(self):
        """Détruit l'instance et son disque. Le nom se RETAPE.

        « -f » retire la dernière question de l'outil : sans la saisie ici,
        un choix mal tapé détruirait sans un mot. C'est la règle du dépôt
        pour ce qui détruit — recopier un nom oblige à regarder ce qu'on
        détruit, là où « o » se tape par réflexe.
        """
        nom = self._lima_select()
        if not nom:
            return
        chemin = config_path(nom)
        print(f"  {t('Will delete:')} {nom}")
        if os.path.exists(chemin):
            print(f"    {chemin}")
        argv = lima.delete_argv(nom)
        print(f"  {t('Will execute:')} {lima.display(argv)}")
        tape = input(
            f"{t('Type the instance name to confirm (empty to cancel): ')}"
        ).strip()
        if tape != nom:
            print(t("Cancelled."))
            return
        self.execute.exec_command_live(
            lima.display(argv), source_erplibre=False
        )
        # Le YAML part avec l'instance : le laisser ferait re-démarrer une
        # instance qu'on croyait détruite, sous une configuration qu'on ne
        # relirait pas.
        if os.path.exists(chemin):
            os.remove(chemin)
            print(f"  {t('Config removed:')} {chemin}")

    def _lima_shell(self):
        nom = self._lima_select(running=True)
        if not nom:
            return
        argv = lima.shell_argv(nom)
        print(f"  {t('Will execute:')} {lima.display(argv)}")
        self.execute.exec_command_live(
            lima.display(argv), source_erplibre=False
        )
