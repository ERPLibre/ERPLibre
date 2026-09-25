#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu des moteurs de conteneurs : Docker et Podman.

Trois sujets sous une même porte : l'état du moteur et son installation,
l'inventaire de ce qu'il détient, et les opérations propres aux images
ERPLibre de script/docker/.

Le moteur n'est pas choisi une fois pour toutes : la fiche est relue à chaque
écran, parce qu'un service peut démarrer, un groupe prendre effet et un
paquet s'installer PENDANT la session. Ce qui se retient d'un écran à l'autre
est le choix de l'opérateur quand les deux moteurs répondent, rien d'autre.

Les scripts de script/docker/ parlent la ligne de commande Docker et nomment
leurs conteneurs d'après le répertoire courant. Sous Podman seul, ils ne
trouvent rien : le menu le dit avant de lancer, plutôt que de laisser un
« command not found » le dire mal.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que celles
des autres fichiers, elles s'appellent donc par « self. » sans rien importer.
"""

import json
import os
import shlex
import shutil

import click

from script.todo import container_runtime
from script.todo.todo_i18n import t

# Le catalogue qui fait autorité sur les versions d'Odoo constructibles.
CATALOGUE = "conf/supported_version_erplibre.json"


class ContainerMenuMixin:
    """Menu des moteurs de conteneurs : Docker et Podman.

    Voir l'en-tête du fichier pour la frontière de ce mixin.
    """

    def prompt_execute_container(self):
        print(f"🤖 {t('Container engines!')}")
        choices = [
            {"section": t("Engine")},
            {
                "prompt_description": t(
                    "Diagnostic - engine, service, socket, access without sudo"
                )
            },
            {"prompt_description": t("Install Docker")},
            {"prompt_description": t("Install Podman")},
            {"section": t("Inventory")},
            {"prompt_description": t("Images")},
            {"prompt_description": t("Containers")},
            {"prompt_description": t("Networks")},
            {"section": t("ERPLibre images")},
            {"prompt_description": t("Build an image for an Odoo version")},
            {
                "prompt_description": t(
                    "Compose - start, stop, logs, processes"
                )
            },
            {
                "prompt_description": t(
                    "ERPLibre container - shell, databases, tests, status"
                )
            },
            {
                "prompt_description": t(
                    "Remove unused images, containers and volumes"
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
                self._container_diagnostic()
            elif status == "2":
                self._container_install("docker")
            elif status == "3":
                self._container_install("podman")
            elif status == "4":
                self._container_inventaire(["images"])
            elif status == "5":
                self._container_inventaire(["ps", "-a"])
            elif status == "6":
                self._container_reseaux()
            elif status == "7":
                self._container_build_odoo()
            elif status == "8":
                self._container_compose()
            elif status == "9":
                self._container_erplibre()
            elif status == "10":
                self._container_nettoyage()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------
    # Le moteur

    def _container_fiches(self):
        """Les fiches des deux moteurs, relues maintenant."""
        return container_runtime.etats()

    def _container_fiche(self):
        """Le moteur à employer, ou None si aucun ne répond.

        Quand les deux répondent, le choix de l'opérateur est retenu pour la
        durée de la session : reposer la question à chaque liste d'images
        rendrait le menu inutilisable.
        """
        fiches = self._container_fiches()
        prets = [f for f in fiches if container_runtime.utilisable(f)]
        if not prets:
            print(f"⚠ {t('No container engine answers here.')}")
            for fiche in fiches:
                if fiche["binaire"] and fiche["raison"]:
                    print(f"  {fiche['moteur']} : {fiche['raison']}")
            print(f"  {t('See [1] Diagnostic, then [2] or [3] to install.')}")
            return None
        if len(prets) == 1:
            return prets[0]
        choisi = getattr(self, "_container_choix", None)
        for fiche in prets:
            if fiche["moteur"] == choisi:
                return fiche
        noms = [f["moteur"] for f in prets]
        print(f"\n{t('Available engines:')} {', '.join(noms)}")
        reponse = click.prompt(t("Engine to use"), default=noms[0])
        for fiche in prets:
            if fiche["moteur"] == reponse.strip().lower():
                self._container_choix = fiche["moteur"]
                return fiche
        self._container_choix = prets[0]["moteur"]
        return prets[0]

    def _container_diagnostic(self):
        """L'état des deux moteurs, champ par champ.

        Rien n'est masqué quand un moteur est absent : savoir que Podman
        n'est pas là fait partie du diagnostic autant que l'état de Docker.
        """
        for fiche in self._container_fiches():
            print(f"\n{fiche['moteur']}")
            if not fiche["binaire"]:
                print(f"  {t('binary')}      : {t('absent')}")
                continue
            print(f"  {t('binary')}      : {fiche['binaire']}")
            print(f"  {t('version')}     : {fiche['version'] or '?'}")
            service = {True: t("active"), False: t("stopped")}.get(
                fiche["service"], t("unknown to systemd")
            )
            print(f"  {t('service')}     : {service}")
            if fiche["socket"]:
                print(f"  {t('socket')}      : {fiche['socket']}")
            if fiche["sans_sudo"]:
                print(f"  {t('without sudo')} : {t('yes')}")
                mode = {True: t("rootless"), False: t("as root")}.get(
                    fiche["rootless"], "?"
                )
                print(f"  {t('mode')}        : {mode}")
                compose = fiche["compose"]
                print(
                    f"  {t('compose')}     :"
                    f" {' '.join(compose) if compose else t('absent')}"
                )
            else:
                print(f"  {t('without sudo')} : {t('no')}")
                if fiche["raison"]:
                    print(f"  {t('reason')}      : {fiche['raison']}")
                avec = t("yes") if fiche["avec_sudo"] else t("no")
                print(f"  {t('with sudo')}   : {avec}")
        print()

    def _container_install(self, moteur):
        """Propose l'installation du moteur, après avoir montré la commande.

        Le groupe « docker » équivaut à root : le mode est demandé, jamais
        choisi à la place de l'opérateur.
        """
        cmd = ["sudo", "bash", "./script/install/install_container.sh", moteur]
        if moteur == "docker":
            print(f"\n{t('Docker runs a daemon owned by root.')}")
            print(
                f"  1) {t('group docker - equivalent to root on this host')}"
            )
            print(f"  2) {t('rootless - one daemon per account, no group')}")
            mode = click.prompt(t("Mode"), default="1").strip()
            if mode == "2":
                cmd.append("--rootless")
                print(f"\n⚠ {t('No Debian or Arch repository ships the')}")
                print(
                    f"  {t('rootless tool: --amont takes the vendor packages.')}"
                )
                if self._is_yes(
                    input(f"💬 {t('Use vendor packages? (Y/N): ')}")
                ):
                    cmd.append("--amont")
            else:
                cmd.append("--groupe")
        compte = os.environ.get("USER") or ""
        if compte:
            cmd += ["--compte", compte]
        print(f"\n  {t('Will execute:')} {shlex.join(cmd)}")
        if not self._is_yes(input(f"💬 {t('Continue? (Y/N): ')}")):
            print(t("Nothing to do."))
            return
        self.execute.exec_command_live(shlex.join(cmd), source_erplibre=False)

    # ------------------------------------------------------------------
    # L'inventaire

    def _container_inventaire(self, args):
        """Lance une sous-commande de listage sur le moteur retenu."""
        fiche = self._container_fiche()
        if not fiche:
            return
        cmd = container_runtime.commande(fiche, args)
        self.execute.exec_command_live(shlex.join(cmd), source_erplibre=False)

    def _container_reseaux(self):
        """Les réseaux, puis le détail de l'un d'eux sur demande.

        « network inspect » est la seule vue qui donne sous-réseaux,
        passerelle et conteneurs attachés, et les deux moteurs la rendent
        en JSON — d'où un détail proposé plutôt qu'une colonne de plus,
        dont les champs diffèrent d'un moteur à l'autre.
        """
        fiche = self._container_fiche()
        if not fiche:
            return
        cmd = container_runtime.commande(fiche, ["network", "ls"])
        self.execute.exec_command_live(shlex.join(cmd), source_erplibre=False)
        nom = click.prompt(t("Network to inspect (empty to skip)"), default="")
        nom = nom.strip()
        if not nom:
            return
        cmd = container_runtime.commande(fiche, ["network", "inspect", nom])
        self.execute.exec_command_live(shlex.join(cmd), source_erplibre=False)

    # ------------------------------------------------------------------
    # Les images ERPLibre

    def _container_versions_odoo(self):
        """Les versions d'Odoo du catalogue, de la plus récente à la plus
        ancienne. Vide si le catalogue est illisible."""
        try:
            with open(CATALOGUE, encoding="utf-8") as fh:
                catalogue = json.load(fh)
        except (OSError, ValueError):
            return []
        versions = []
        for cle in catalogue:
            odoo = cle.split("_")[0].removeprefix("odoo")
            if odoo not in versions:
                versions.append(odoo)
        return sorted(versions, key=lambda v: float(v), reverse=True)

    def _container_build_odoo(self):
        """Construit l'image d'une version d'Odoo par docker_build.sh."""
        if not self._container_exige_docker():
            return
        versions = self._container_versions_odoo()
        if not versions:
            print(f"⚠ {t('Unreadable version catalogue:')} {CATALOGUE}")
            return
        print(f"\n{t('Odoo version:')}")
        for i, version in enumerate(versions, 1):
            print(f"  [{i}] {version}")
        choix = click.prompt(t("Number"), default="1").strip()
        try:
            version = versions[int(choix) - 1]
        except (ValueError, IndexError):
            print(t("Command not found !"))
            return
        cmd = f"./script/docker/docker_build.sh --odoo_{version.split('.')[0]}"
        if self._is_yes(input(f"💬 {t('Rebuild without cache? (Y/N): ')}")):
            cmd += " --no-cache"
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _container_compose(self):
        """Démarrer, arrêter, suivre ou lister la composition ERPLibre."""
        fiche = self._container_fiche()
        if not fiche:
            return
        compose = fiche["compose"] or [fiche["moteur"], "compose"]
        choices = [
            {"prompt_description": t("Start in the background")},
            {"prompt_description": t("Stop")},
            {"prompt_description": t("Follow the logs")},
            {"prompt_description": t("Processes")},
        ]
        help_info = self.fill_help_info(choices)
        args = {
            "1": ["up", "-d"],
            "2": ["down"],
            "3": ["logs", "-f"],
            "4": ["ps"],
        }
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status not in args:
                print(t("Command not found !"))
                continue
            self.execute.exec_command_live(
                shlex.join(compose + args[status]), source_erplibre=False
            )

    def _container_erplibre(self):
        """Les gestes qui visent le conteneur ERPLibre déjà démarré.

        Tous passent par les scripts de script/docker/, qui retrouvent le
        conteneur d'après le nom du répertoire courant — les lancer depuis
        un autre répertoire ne trouve rien.
        """
        if not self._container_exige_docker():
            return
        choices = [
            {"prompt_description": t("Enter the ERPLibre container")},
            {"prompt_description": t("Databases of the ERPLibre container")},
            {"prompt_description": t("Regenerate odoo.conf (addons paths)")},
            {"prompt_description": t("Run the tests")},
            {"prompt_description": t("Status of the git repositories")},
            {"prompt_description": t("Copy a file into the container")},
        ]
        help_info = self.fill_help_info(choices)
        scripts = {
            "1": "./script/docker/docker_exec.sh",
            "2": "./script/docker/docker_list_database.sh",
            "3": "./script/docker/docker_gen_config.sh",
            "4": "./script/docker/docker_make_test.sh",
            "5": "./script/docker/docker_repo_show_status.sh",
        }
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status in scripts:
                self.execute.exec_command_live(
                    scripts[status], source_erplibre=False
                )
            elif status == "6":
                self._container_copier_fichier()
            else:
                print(t("Command not found !"))

    def _container_copier_fichier(self):
        """Copie un fichier de l'hôte vers le conteneur.

        Le script exige un fichier qui existe et refuse le reste : la source
        est donc vérifiée ici, où l'on peut redemander, plutôt qu'au retour
        d'un code d'erreur.
        """
        source = click.prompt(t("File to copy")).strip()
        if not source or not os.path.isfile(source):
            print(f"⚠ {t('No such file:')} {source}")
            return
        cible = click.prompt(
            t("Destination in the container (empty for the default)"),
            default="",
        ).strip()
        cmd = ["./script/docker/docker_copy_file.sh", source]
        if cible:
            cmd.append(cible)
        self.execute.exec_command_live(shlex.join(cmd), source_erplibre=False)

    def _container_exige_docker(self):
        """True si la ligne de commande Docker est là.

        Les scripts de script/docker/ l'appellent par son nom. Podman fournit
        la même interface, mais seulement si le paquet « podman-docker » pose
        le lien : sans lui, ces scripts échouent sur un binaire introuvable,
        et ce n'est pas ce que l'erreur laisse croire.
        """
        if shutil.which("docker"):
            return True
        print(f"⚠ {t('These scripts call the docker command by name.')}")
        if shutil.which("podman"):
            print(f"  {t('Install podman-docker to provide it.')}")
        return False

    def _container_nettoyage(self):
        """Efface ce qui n'est plus référencé, VOLUMES COMPRIS.

        Un volume effacé emporte la base de données du conteneur : la
        confirmation nomme ce qui part avant de le demander.
        """
        fiche = self._container_fiche()
        if not fiche:
            return
        print(f"\n⚠ {t('This REMOVES unused images, containers, networks')}")
        print(f"  {t('and VOLUMES - a volume holds the database.')}")
        cmd = container_runtime.commande(
            fiche, ["system", "prune", "-a", "--volumes"]
        )
        print(f"  {t('Will execute:')} {shlex.join(cmd)}")
        if not self._is_yes(input(f"💬 {t('Continue? (Y/N): ')}")):
            print(t("Nothing to do."))
            return
        self.execute.exec_command_live(shlex.join(cmd), source_erplibre=False)
