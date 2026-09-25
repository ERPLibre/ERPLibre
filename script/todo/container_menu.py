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
import textwrap

import click

from script.todo import container_runtime
from script.todo.todo_i18n import t

# Le catalogue qui fait autorité sur les versions d'Odoo constructibles.
CATALOGUE = "conf/supported_version_erplibre.json"

# Les codes que rend container_runtime, et la phrase à montrer. La phrase vit
# ICI et non dans le module : lui rend des faits, et une phrase choisit une
# langue.
RAISONS = {
    "groupe_hors_session": (
        "in the docker group, but not in this session: log in again"
    ),
    "groupe_absent": "not in the docker group - sudo, or install it again",
    "droits_socket": "not enough rights on the engine socket",
    "noyau_perime": (
        "the running kernel lost its module tree: reboot to load any module"
    ),
    "service_arrete": "the service is stopped - see [2] Service",
    "systemd_ignore": "no answer, and systemd does not know this unit",
    "socket_muette": "the unit runs but the socket does not answer",
    "delai": "the engine did not answer within the delay",
}

# Les unités systemd de chaque moteur : celle du démon, puis celle de la
# socket. L'activation au démarrage porte sur la SOCKET — c'est elle qui fait
# naître le démon à la première connexion — là où démarrer et arrêter portent
# sur le démon lui-même.
UNITES = {
    "docker": ("docker.service", "docker.socket"),
    "podman": ("podman.service", "podman.socket"),
}

# L'icône de chaque moteur. Hors de todo_i18n : un nom de produit ne se
# traduit pas, et son icône pas davantage — les deux langues y mettraient la
# même chose. Les mêmes que les entrées d'installation du menu, pour qu'une
# liste et son action se reconnaissent d'un coup d'œil.
ICONES_MOTEUR = {"docker": "🐳", "podman": "🦭"}


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
            {
                "prompt_description": t(
                    "Service - start, stop, enable at boot, journal"
                )
            },
            {"prompt_description": t("Install Docker")},
            {"prompt_description": t("Install Podman")},
            {"section": t("Inventory")},
            {"prompt_description": t("Images")},
            {"prompt_description": t("Containers")},
            {"prompt_description": t("Networks")},
            {"section": t("Cleanup")},
            {
                "prompt_description": t(
                    "Remove unused images, containers and volumes"
                )
            },
            {
                "prompt_description": t(
                    "By workspace - a compose project and what it holds"
                )
            },
            {"prompt_description": t("Images one by one")},
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
                self._container_service()
            elif status == "3":
                self._container_install("docker")
            elif status == "4":
                self._container_install("podman")
            elif status == "5":
                self._container_inventaire(["images"])
            elif status == "6":
                self._container_inventaire(["ps", "-a"])
            elif status == "7":
                self._container_reseaux()
            elif status == "8":
                self._container_nettoyage()
            elif status == "9":
                self._container_nettoyer_projets()
            elif status == "10":
                self._container_nettoyer_images()
            elif status == "11":
                self._container_build_odoo()
            elif status == "12":
                self._container_compose()
            elif status == "13":
                self._container_erplibre()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------
    # Le moteur

    def _container_libelle_moteur(self, nom):
        """Le nom du moteur précédé de son icône, pour une liste.

        Le libellé est d'AFFICHAGE : le choix rend un rang, et les appelants
        gardent leur liste de noms nus pour retrouver la fiche. Décorer ce
        qu'on affiche ne doit jamais décorer ce sur quoi on décide.
        """
        icone = ICONES_MOTEUR.get(nom)
        return f"{icone} {nom}" if icone else nom

    def _container_choix_numerote(self, titre, options, defaut="1"):
        """Le RANG choisi parmi des options numérotées, ou None.

        Le numéro plutôt que le nom : taper « docker » ou « podman » en entier
        pour deux entrées coûte plus qu'il ne rapporte, et une faute de frappe
        retombait en silence sur la première.

        Les rangs hors liste sont refusés explicitement : en Python
        options[-1] existe, et un « 0 » saisi rendrait la DERNIÈRE entrée —
        un choix que personne n'a fait, sur un écran qui en efface parfois.

        « 0 » vaut retour, comme dans tout le reste de TODO, et sort sans se
        plaindre : c'est un geste, pas une faute de frappe.
        """
        print(f"\n{titre}")
        for rang, option in enumerate(options, 1):
            print(f"  [{rang}] {option}")
        print(f"  [0] {t('Back')}")
        reponse = click.prompt(t("Number"), default=defaut).strip()
        try:
            rang = int(reponse)
        except ValueError:
            rang = -1
        if rang == 0:
            return None
        if not 1 <= rang <= len(options):
            print(t("Command not found !"))
            return None
        return rang - 1

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
            print(f"  {t('See [1] Diagnostic, then [3] or [4] to install.')}")
            return None
        if len(prets) == 1:
            return prets[0]
        choisi = getattr(self, "_container_choix", None)
        for fiche in prets:
            if fiche["moteur"] == choisi:
                return fiche
        rang = self._container_choix_numerote(
            t("Available engines:"),
            [self._container_libelle_moteur(f["moteur"]) for f in prets],
        )
        if rang is None:
            return None
        self._container_choix = prets[rang]["moteur"]
        return prets[rang]

    # Les libellés du diagnostic, dans l'ordre d'affichage. La largeur de la
    # colonne se CALCULE sur eux, traduits : un gabarit fixe est juste dans la
    # langue où il a été écrit et bancal dans l'autre.
    _CHAMPS = (
        "binary",
        "version",
        "service",
        "socket",
        "without sudo",
        "with sudo",
        "reason",
        "mode",
        "compose",
    )

    def _container_diagnostic(self):
        """L'état des deux moteurs, champ par champ.

        Rien n'est masqué quand un moteur est absent : savoir que Podman n'est
        pas là fait partie du diagnostic autant que l'état de Docker.
        """
        largeur = max(len(t(champ)) for champ in self._CHAMPS)

        def ligne(champ, valeur):
            print(f"  {t(champ):<{largeur}} : {valeur}")

        for fiche in self._container_fiches():
            print(f"\n{fiche['moteur']}")
            if not fiche["binaire"]:
                ligne("binary", t("absent"))
                continue
            ligne("binary", fiche["binaire"])
            ligne("version", fiche["version"] or "?")
            # « Service is stopped » plutôt que « stopped » : le second existe
            # déjà, traduit au féminin pluriel pour des machines.
            ligne(
                "service",
                {True: t("active"), False: t("Service is stopped")}.get(
                    fiche["service"], t("unknown to systemd")
                ),
            )
            if fiche["socket"]:
                ligne("socket", fiche["socket"])
            if fiche["sans_sudo"]:
                ligne("without sudo", t("yes"))
                ligne(
                    "mode",
                    {True: t("rootless"), False: t("as root")}.get(
                        fiche["rootless"], "?"
                    ),
                )
                compose = fiche["compose"]
                ligne(
                    "compose",
                    " ".join(compose) if compose else t("absent"),
                )
            else:
                ligne("without sudo", t("no"))
                raison = RAISONS.get(fiche["raison"])
                if raison:
                    # La raison est une phrase, pas un mot : on la replie sous
                    # sa colonne plutôt que de laisser le terminal la couper
                    # n'importe où.
                    replie = textwrap.wrap(t(raison), 78 - largeur - 5)
                    ligne("reason", replie[0] if replie else "")
                    for suite in replie[1:]:
                        print(f"  {'':<{largeur}}   {suite}")
                ligne("with sudo", t("yes") if fiche["avec_sudo"] else t("no"))
            # La socket d'un démon par compte n'est pas celle du défaut : sans
            # cette ligne dans l'environnement, le client s'adresse à celle de
            # root et tout paraît mort.
            if fiche["docker_host"]:
                print(f"  {t('Add to the account environment:')}")
                print(f"    export DOCKER_HOST={fiche['docker_host']}")
        print()

    def _container_par_compte(self, moteur, fiche=None):
        """Les unités de ce moteur sont-elles des unités « utilisateur » ?

        Un moteur sans privilège vit dans la session du compte : ses unités
        sont à lui, root ne les voit pas, et « sudo systemctl » se plaindrait
        d'une unité introuvable. Un démon partagé est l'inverse. Le mode que
        le moteur ANNONCE tranche d'abord ; à défaut, ce qui est sur le disque.
        """
        service, socket = UNITES[moteur]
        if fiche and (fiche.get("docker_host") or fiche.get("rootless")):
            return True
        # Une socket dans le répertoire de session prouve un démon par compte,
        # même muet : les deux jeux d'unités coexistent souvent — le paquet de
        # la distribution pose celles de l'hôte, celui du mode sans privilège
        # celles du compte — et l'unité de l'hôte existerait sans rien dire du
        # moteur que ce compte emploie.
        if moteur == "docker" and container_runtime.socket_rootless():
            return True
        if os.path.exists(f"/usr/lib/systemd/system/{service}"):
            return False
        return os.path.exists(f"/usr/lib/systemd/user/{socket}")

    def _container_choisir_moteur(self):
        """Le moteur dont on veut piloter le service, ou None.

        La question porte sur les moteurs INSTALLÉS et non sur ceux qui
        répondent : piloter un service est précisément ce qu'on fait quand il
        ne répond pas.
        """
        fiches = {f["moteur"]: f for f in self._container_fiches()}
        poses = [nom for nom, f in fiches.items() if f["binaire"]]
        if not poses:
            print(f"⚠ {t('No container engine is installed here.')}")
            return None
        if len(poses) == 1:
            return fiches[poses[0]]
        rang = self._container_choix_numerote(
            t("Installed engines:"),
            [self._container_libelle_moteur(nom) for nom in poses],
        )
        return fiches[poses[rang]] if rang is not None else None

    def _container_service(self):
        """Démarrer, arrêter ou activer le service d'un moteur, et LIRE son
        journal.

        Le journal est la moitié utile de cet écran : un démon qui refuse de
        naître ne dit rien à « docker info », qui ne rapporte que l'absence de
        socket. La cause — un module de noyau introuvable, une plage d'UID
        subordonnés manquante — n'est écrite que là.
        """
        fiche = self._container_choisir_moteur()
        if not fiche:
            return
        moteur = fiche["moteur"]
        service, socket = UNITES[moteur]
        par_compte = self._container_par_compte(moteur, fiche)
        portee = t("account session") if par_compte else t("whole host")
        print(f"\n{moteur} — {service} / {socket} ({portee})")

        choices = [
            {"prompt_description": t("Start")},
            {"prompt_description": t("Stop")},
            {"prompt_description": t("Restart")},
            {"prompt_description": t("Enable at boot")},
            {"prompt_description": t("Disable at boot")},
            {"prompt_description": t("Status and journal")},
        ]
        help_info = self.fill_help_info(choices)
        # L'activation porte sur la SOCKET, qui fait naître le démon à la
        # première connexion ; le reste porte sur le démon.
        actions = {
            "1": ("start", service),
            "2": ("stop", service),
            "3": ("restart", service),
            "4": ("enable", socket),
            "5": ("disable", socket),
        }
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status in actions:
                action, unite = actions[status]
                self._container_systemctl(action, unite, par_compte)
                if action == "enable" and par_compte:
                    print(f"  {t('A per-account unit needs linger to start')}")
                    print(f"  {t('without a login:')} loginctl enable-linger")
            elif status == "6":
                self._container_journal(service, par_compte)
            else:
                print(t("Command not found !"))

    def _container_systemctl(self, action, unite, par_compte):
        """Lance systemctl sur l'unité, dans la bonne portée.

        Un échec enchaîne l'état et le journal SANS qu'on les redemande.
        systemd ne rend qu'un « failed because the control process exited with
        error code » et renvoie à deux commandes à taper ; la cause — un
        module de noyau introuvable, une plage d'UID subordonnés manquante —
        n'est écrite que dans le journal, et c'est tout ce qu'on cherchait.
        """
        cmd = ["systemctl"]
        if par_compte:
            cmd.append("--user")
        else:
            cmd.insert(0, "sudo")
        code = self.execute.exec_command_live(
            shlex.join(cmd + [action, unite]), source_erplibre=False
        )
        if code:
            print(f"\n⚠ {t('The unit refused. Its state, then its journal:')}")
            self._container_journal(unite, par_compte)

    def _container_journal(self, unite, par_compte):
        """L'état de l'unité, puis son journal — la cause est dans le second.

        « status » montre le code de sortie et s'arrête là ; les lignes que le
        démon a écrites avant de mourir ne sont que dans le journal.
        """
        for cmd in (
            ["systemctl", "status", unite, "--no-pager"],
            ["journalctl", "-u", unite, "--no-pager", "-n", "40"],
        ):
            if par_compte:
                cmd.insert(1, "--user")
            else:
                cmd = ["sudo"] + cmd
            self.execute.exec_command_live(
                shlex.join(cmd), source_erplibre=False
            )

    def _container_install(self, moteur):
        """Propose l'installation du moteur, après avoir montré la commande.

        Le groupe « docker » équivaut à root : le mode est demandé, jamais
        choisi à la place de l'opérateur.
        """
        cmd = ["sudo", "bash", "./script/install/install_container.sh", moteur]
        if moteur == "docker":
            print(f"\n{t('Docker runs a daemon owned by root.')}")
            print(f"  {t('Two ways to reach it without typing sudo:')}")
            print(
                f"\n  1) {t('docker group - ONE shared daemon, still root')}"
            )
            print(f"     {t('Being in the group opens its socket, which')}")
            print(f"     {t('mounts any host path: it equals being root.')}")
            print(f"\n  2) {t('rootless - ONE daemon per account, no group')}")
            print(f"     {t('It runs inside your session, so nothing of it')}")
            print(f"     {t('is root. Ports under 1024 stay closed to it.')}")
            mode = click.prompt(t("Mode"), default="2").strip()
            if mode == "2":
                cmd.append("--rootless")
                print(f"\n  {t('Where Docker Inc. packages, rootless mode')}")
                print(f"  {t('needs ITS packages; elsewhere the installer')}")
                print(f"  {t('takes the route its distribution offers.')}")
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
        """Construit l'image d'une ou de TOUTES les versions d'Odoo.

        Le balayage ne s'arrête pas au premier échec : une version qui casse
        n'apprend rien sur les suivantes, et les relancer une à une coûte des
        heures. Le compte rendu final nomme ce qui est passé et ce qui est
        tombé — sans lui, seule la dernière sortie reste à l'écran.
        """
        prefixe = self._container_exige_docker()
        if prefixe is None:
            return
        versions = self._container_versions_odoo()
        if not versions:
            print(f"⚠ {t('Unreadable version catalogue:')} {CATALOGUE}")
            return
        rang = self._container_choix_numerote(
            t("Odoo version:"), versions + [t("All versions")]
        )
        if rang is None:
            return
        toutes = rang == len(versions)
        if toutes:
            # Une image de production pèse une dizaine de gigaoctets : le dire
            # AVANT, pendant qu'un disque plein est encore évitable.
            print(f"\n⚠ {t('Every version: hours of work, tens of GB.')}")
            if not self._is_yes(input(f"💬 {t('Continue? (Y/N): ')}")):
                print(t("Nothing to do."))
                return
        cibles = versions if toutes else [versions[rang]]
        sans_cache = ""
        if self._is_yes(input(f"💬 {t('Rebuild without cache? (Y/N): ')}")):
            sans_cache = " --no-cache"

        echecs = []
        for version in cibles:
            court = version.split(".")[0]
            cmd = (
                f"{prefixe}./script/docker/docker_build.sh"
                f" --odoo_{court}{sans_cache}"
            )
            if self.execute.exec_command_live(cmd, source_erplibre=False):
                echecs.append(version)
        if len(cibles) > 1:
            passees = [v for v in cibles if v not in echecs]
            print(f"\n{t('Built:')} {', '.join(passees) or '-'}")
            if echecs:
                print(f"{t('Failed:')} {', '.join(echecs)}")

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
        prefixe = self._container_exige_docker()
        if prefixe is None:
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
                    prefixe + scripts[status], source_erplibre=False
                )
            elif status == "6":
                self._container_copier_fichier(prefixe)
            else:
                print(t("Command not found !"))

    def _container_copier_fichier(self, prefixe=""):
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
        self.execute.exec_command_live(
            prefixe + shlex.join(cmd), source_erplibre=False
        )

    def _container_exige_docker(self):
        """Le préfixe d'environnement pour les scripts de script/docker/, ou
        None quand rien ne peut les servir.

        Deux choses leur manquent tour à tour. Le BINAIRE d'abord : ils
        appellent « docker » par son nom, et Podman ne fournit la même
        interface que si le paquet « podman-docker » pose le lien. La SOCKET
        ensuite : ils s'adressent à celle du défaut, où un démon par compte
        n'est pas — le script s'arrête alors sur « /var/run/docker.sock: no
        such file or directory », qui accuse le script et non le moteur.

        Rend une chaîne à préfixer, vide quand il n'y a rien à poser : le
        préfixe voyage avec la commande, là où une variable posée dans ce
        processus ne survivrait pas au shell qui la lance.
        """
        if not shutil.which("docker"):
            print(f"⚠ {t('These scripts call the docker command by name.')}")
            if shutil.which("podman"):
                print(f"  {t('Install podman-docker to provide it.')}")
            return None
        fiche = None
        for candidate in self._container_fiches():
            if candidate["moteur"] == "docker":
                fiche = candidate
        if not fiche or not container_runtime.utilisable(fiche):
            print(f"⚠ {t('The docker engine does not answer here.')}")
            print(f"  {t('See [1] Diagnostic, then [2] Service.')}")
            return None
        if fiche["docker_host"]:
            return f"DOCKER_HOST={fiche['docker_host']} "
        return ""

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
        # « Tout » s'arrête à ce qui tourne : prune ne touche ni un conteneur
        # en marche ni ce qu'il emploie. Pour effacer un projet VIVANT, c'est
        # l'entrée par espace de travail.
        print(f"  {t('Running containers, and what they use, are kept.')}")
        cmd = container_runtime.commande(
            fiche, ["system", "prune", "-a", "--volumes"]
        )
        print(f"  {t('Will execute:')} {shlex.join(cmd)}")
        if not self._is_yes(input(f"💬 {t('Continue? (Y/N): ')}")):
            print(t("Nothing to do."))
            return
        self.execute.exec_command_live(shlex.join(cmd), source_erplibre=False)

    def _container_lire_selection(self, total):
        """Les rangs saisis, ou None.

        Une saisie vide annule sans rien dire. Une saisie fautive le DIT, et
        n'efface rien : lire_selection refuse la saisie entière dès qu'une
        partie en est fausse.
        """
        texte = click.prompt(
            t("Numbers (1 3, 2-5, * for all, empty to cancel)"),
            default="",
            show_default=False,
        )
        if not texte.strip():
            print(t("Nothing to do."))
            return None
        rangs = container_runtime.lire_selection(texte, total)
        if rangs is None:
            print(f"⚠ {t('Invalid selection: nothing removed.')}")
        return rangs

    def _container_bilan(self, total, echecs, raison):
        """Ce qui est parti et ce qui a été refusé, avec la raison probable.

        Sans ce compte rendu, seule la dernière sortie du moteur reste à
        l'écran, et un refus au milieu passe pour une réussite.
        """
        print(f"\n{t('Removed:')} {total - len(echecs)}/{total}")
        if echecs:
            print(f"{t('Refused:')} {', '.join(echecs)}")
            print(f"  {raison}")

    def _container_nettoyer_images(self):
        """Effacer des images choisies à la pièce, par leur rang.

        Une image qu'un conteneur tient — même arrêté — est refusée par
        « rmi ». Le conflit se décide AVANT d'effacer quoi que ce soit : le
        découvrir en route laisse un effacement à moitié fait, et prive la
        décision de ce qu'elle doit savoir — quels conteneurs, dans quel
        état, de quel projet.

        Trois issues à un conflit, qui ne libèrent pas la même chose :
        effacer les conteneurs puis l'image rend l'espace ; forcer ne retire
        que le NOM, l'image restant sur le disque avec toute sa taille tant
        qu'un conteneur la tient ; et le moteur refuse de forcer quand l'un
        d'eux tourne. Garder est le défaut : dans le doute, rien ne part.
        """
        fiche = self._container_fiche()
        if not fiche:
            return
        images = container_runtime.lister_images(fiche)
        if not images:
            print(t("No image."))
            return
        usages = container_runtime.conteneurs_par_image(fiche, images)
        print()
        for rang, image in enumerate(images, 1):
            nom = container_runtime.reference_image(image)
            ligne = f"  [{rang:>2}] {nom}  {image['taille']}  ({image['age']})"
            tenants = usages.get(image["id"])
            if tenants:
                noms = ", ".join(c["nom"] for c in tenants)
                ligne += f"  ⛓ {noms}"
            print(ligne)
        rangs = self._container_lire_selection(len(images))
        if not rangs:
            return

        plan = []
        for rang in rangs:
            image = images[rang]
            tenants = usages.get(image["id"], [])
            action = "effacer"
            if tenants:
                action = self._container_decider_conflit(image, tenants)
            if action != "garder":
                plan.append((image, action, tenants))
        if not plan:
            print(t("Nothing to do."))
            return

        print(f"\n⚠ {t('Will remove:')}")
        for image, action, tenants in plan:
            ligne = f"    {container_runtime.reference_image(image)}"
            if action == "vider":
                noms = ", ".join(c["nom"] for c in tenants)
                ligne += f"  ← {t('after its containers:')} {noms}"
            elif action == "forcer":
                ligne += f"  ← {t('forced: the name only, the space stays')}"
            print(ligne)
        if not self._is_yes(input(f"💬 {t('Remove? (Y/N): ')}")):
            print(t("Nothing to do."))
            return

        echecs = []
        for image, action, tenants in plan:
            ref = container_runtime.reference_image(image)
            if action == "vider":
                # Les conteneurs d'abord : tant qu'un seul tient l'image,
                # « rmi » la refuse.
                for conteneur in tenants:
                    cmd = container_runtime.commande(
                        fiche, ["rm", "-f", conteneur["nom"]]
                    )
                    self.execute.exec_command_live(
                        shlex.join(cmd), source_erplibre=False
                    )
            args = ["rmi", "-f", ref] if action == "forcer" else ["rmi", ref]
            cmd = container_runtime.commande(fiche, args)
            if self.execute.exec_command_live(
                shlex.join(cmd), source_erplibre=False
            ):
                echecs.append(ref)
        self._container_bilan(
            len(plan), echecs, t("A container still uses a refused image.")
        )

    def _container_decider_conflit(self, image, tenants):
        """Ce qu'on fait d'une image que des conteneurs tiennent.

        Rend « garder », « vider » ou « forcer ». La question montre CE QUI
        tient l'image — nom, état, projet compose — parce que c'est cela qui
        décide : un conteneur arrêté d'un projet se recrée au prochain
        « compose up », un conteneur isolé en marche est peut-être du travail
        en cours.

        Forcer n'est proposé que si aucun conteneur ne tourne : le moteur le
        refuserait, et offrir un choix voué à l'échec n'aide personne.
        """
        print(f"\n⚠ {container_runtime.reference_image(image)}")
        print(f"  {t('is held by these containers:')}")
        for conteneur in tenants:
            projet = ""
            if conteneur["projet"]:
                projet = f"  — {t('project')} {conteneur['projet']}"
            print(f"    {conteneur['nom']}  ({conteneur['etat']}){projet}")
        options = [
            t("Keep the image"),
            t("Remove these containers, then the image - frees the space"),
        ]
        if any(c["etat"] == "running" for c in tenants):
            print(f"  {t('A container runs: the engine refuses to force.')}")
        else:
            options.append(t("Force - removes the name only; the space stays"))
        rang = self._container_choix_numerote(t("Decision:"), options)
        return {1: "vider", 2: "forcer"}.get(rang, "garder")

    def _container_nettoyer_projets(self):
        """Effacer un espace de travail : un projet compose et tout ce qu'il
        tient — conteneurs, réseaux, volumes, images.

        Les volumes portent les bases de données et ne reviennent pas : ils
        sont nommés à part, avant la question, et non noyés dans la liste.

        L'ordre compte : les conteneurs d'abord, sans quoi le moteur refuse
        d'effacer les réseaux, les volumes et les images qu'ils tiennent
        encore. Les images viennent en dernier et sans --force : une image
        qu'un AUTRE projet emploie est refusée, et doit l'être.
        """
        fiche = self._container_fiche()
        if not fiche:
            return
        projets = container_runtime.lister_projets(fiche)
        if not projets:
            print(t("No workspace (compose project) here."))
            return
        noms = sorted(projets)
        print()
        for rang, nom in enumerate(noms, 1):
            projet = projets[nom]
            etats = ", ".join(
                sorted({c["etat"] for c in projet["conteneurs"]})
            )
            print(f"  [{rang:>2}] {nom}  —  {projet['dossier'] or '?'}")
            print(
                f"       {len(projet['conteneurs'])} {t('containers')}"
                f" ({etats})"
            )
        rangs = self._container_lire_selection(len(noms))
        if not rangs:
            return

        plan = []
        for rang in rangs:
            nom = noms[rang]
            ressources = container_runtime.ressources_projet(fiche, nom)
            plan.append((nom, projets[nom], ressources))
        print(f"\n⚠ {t('Will remove:')}")
        volumes = []
        for nom, projet, ressources in plan:
            print(f"  {nom}")
            for etiquette, valeurs in (
                ("containers", [c["nom"] for c in projet["conteneurs"]]),
                ("networks", ressources["network"]),
                ("volumes", ressources["volume"]),
                ("images", projet["images"]),
            ):
                print(f"    {t(etiquette)} : {', '.join(valeurs) or '-'}")
            volumes += ressources["volume"]
        if volumes:
            print(
                f"\n⚠ {t('Volumes hold the databases: they do not come back.')}"
            )
        if not self._is_yes(input(f"💬 {t('Remove? (Y/N): ')}")):
            print(t("Nothing to do."))
            return

        etapes = []
        for _nom, projet, ressources in plan:
            etapes += [["rm", "-f", c["nom"]] for c in projet["conteneurs"]]
            etapes += [["network", "rm", r] for r in ressources["network"]]
            etapes += [["volume", "rm", v] for v in ressources["volume"]]
            etapes += [["rmi", i] for i in projet["images"]]
        echecs = []
        for args in etapes:
            cmd = container_runtime.commande(fiche, args)
            if self.execute.exec_command_live(
                shlex.join(cmd), source_erplibre=False
            ):
                echecs.append(" ".join(args))
        self._container_bilan(
            len(etapes),
            echecs,
            t("An image another workspace still uses is kept."),
        )
