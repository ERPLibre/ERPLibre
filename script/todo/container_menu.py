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

import getpass
import json
import os
import shlex
import shutil
import subprocess
import sys
import textwrap

import click

from script.execute.execute import Execute
from script.todo import container_db, container_runtime, todo_journal, ui
from script.todo.menus import deploy as menus_deploy
from script.todo.todo_i18n import t
from script.todo.ui.navigator import navigate

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
        """Les moteurs de conteneurs : leur état et leur installation,
        l'inventaire de ce qu'ils détiennent, et les images ERPLibre
        (CONTAINER, `menus/deploy.py`), dessiné une fois, à l'entrée. Rend
        False sur [0]."""
        return navigate(self, menus_deploy.CONTAINER)

    # ------------------------------------------------------------------
    # Le moteur

    def _container_libelle_moteur(self, nom):
        """Le nom du moteur précédé de son icône, pour une liste.

        Le libellé est d'AFFICHAGE : le choix rend le nom nu, qui retrouve
        la fiche et se tape sans l'icône. Décorer ce qu'on affiche ne doit
        jamais décorer ce sur quoi on décide.
        """
        icone = ICONES_MOTEUR.get(nom)
        return f"{icone} {nom}" if icone else nom

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
        noms = [fiche["moteur"] for fiche in prets]
        choisi = ui.choose(
            t("Available engines:"),
            noms,
            default=noms[0],
            labels=[self._container_libelle_moteur(nom) for nom in noms],
            names=dict(zip(noms, noms)),
        )
        if choisi is None:
            return None
        self._container_choix = choisi
        return prets[noms.index(choisi)]

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
        choisi = ui.choose(
            t("Installed engines:"),
            poses,
            default=poses[0],
            labels=[self._container_libelle_moteur(nom) for nom in poses],
            names=dict(zip(poses, poses)),
        )
        return fiches.get(choisi)

    def _container_service(self):
        """Démarrer, arrêter ou activer le service d'un moteur, et LIRE son
        journal (CONTAINER_SERVICE, `menus/deploy.py`). Rend False sur [0],
        et None, le menu fermé, sans moteur installé ou choisi.

        Le journal est la moitié utile de cet écran : un démon qui refuse de
        naître ne dit rien à « docker info », qui ne rapporte que l'absence de
        socket. La cause — un module de noyau introuvable, une plage d'UID
        subordonnés manquante — n'est écrite que là.
        """
        return navigate(self, menus_deploy.CONTAINER_SERVICE)

    def _container_service_ouvre(self):
        """Ce qui ouvre le menu du service : le moteur choisi, ses unités et
        leur portée. Rend {"fiche", "par_compte"}, que reçoit chaque
        entrée, ou None sans moteur installé ou choisi."""
        fiche = self._container_choisir_moteur()
        if not fiche:
            return None
        moteur = fiche["moteur"]
        service, socket = UNITES[moteur]
        par_compte = self._container_par_compte(moteur, fiche)
        portee = t("account session") if par_compte else t("whole host")
        print(f"\n{moteur} — {service} / {socket} ({portee})")
        return {"fiche": fiche, "par_compte": par_compte}

    def _container_service_choisi(self, fiche=None, par_compte=None):
        """(fiche, par_compte) du moteur dont une entrée pilote le service :
        ceux que donne son menu, ou, sans fiche, comme depuis la TUI de
        télémétrie, le moteur choisi maintenant parmi ceux qui sont
        installés ; `par_compte` se déduit de la fiche quand il n'est pas
        donné. None sans moteur installé ou choisi."""
        if fiche is None:
            fiche = self._container_choisir_moteur()
            if not fiche:
                return None
        if par_compte is None:
            par_compte = self._container_par_compte(fiche["moteur"], fiche)
        return fiche, par_compte

    def _container_geste(self, geste, fiche=None, par_compte=None):
        """Le geste systemd `geste` sur le service du moteur (voir
        `_container_service_choisi`) : l'activation, enable ou disable,
        porte sur la SOCKET, qui fait naître le démon à la première
        connexion ; start, stop et restart portent sur le démon."""
        choisi = self._container_service_choisi(fiche, par_compte)
        if not choisi:
            return
        fiche, par_compte = choisi
        service, socket = UNITES[fiche["moteur"]]
        unite = socket if geste in ("enable", "disable") else service
        self._container_systemctl(geste, unite, par_compte)
        if geste == "enable" and par_compte:
            print(f"  {t('A per-account unit needs linger to start')}")
            print(f"  {t('without a login:')} loginctl enable-linger")

    def _container_etat_service(self, fiche=None, par_compte=None):
        """L'état du service du moteur, puis son journal (voir
        `_container_service_choisi`)."""
        choisi = self._container_service_choisi(fiche, par_compte)
        if not choisi:
            return
        fiche, par_compte = choisi
        self._container_journal(UNITES[fiche["moteur"]][0], par_compte)

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
            if Execute.interrupted:
                return

    def _container_install(self, moteur):
        """Propose l'installation du moteur, après avoir montré la commande.

        Le groupe « docker » équivaut à root : le mode est demandé, jamais
        choisi à la place de l'opérateur ; une réponse vide prend le mode
        sans privilège, et [0] n'installe rien.
        """
        cmd = ["sudo", "bash", "./script/install/install_container.sh", moteur]
        if moteur == "docker":
            print(f"\n{t('Docker runs a daemon owned by root.')}")
            modes = [
                (
                    t("docker group - ONE shared daemon, still root"),
                    t("Being in the group opens its socket, which"),
                    t("mounts any host path: it equals being root."),
                ),
                (
                    t("rootless - ONE daemon per account, no group"),
                    t("It runs inside your session, so nothing of it"),
                    t("is root. Ports under 1024 stay closed to it."),
                ),
            ]
            rang = ui.choose(
                t("Two ways to reach it without typing sudo:"),
                range(2),
                default=1,
                labels=["\n    ".join(mode) for mode in modes],
            )
            if rang is None:
                return
            if rang == 1:
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

    def _container_inventaire(self, sous_commande):
        """Lance sur le moteur retenu la sous-commande de listage
        `sous_commande`, ses mots séparés par des blancs (« images »,
        « ps -a »)."""
        fiche = self._container_fiche()
        if not fiche:
            return
        cmd = container_runtime.commande(fiche, sous_commande.split())
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
        """Construit l'image d'une ou de plusieurs versions d'Odoo, pour une
        ou plusieurs architectures.

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
        cibles = ui.choose(t("Odoo version:"), versions, multi=True)
        if not cibles:
            return
        if len(cibles) > 1:
            # Une image de production pèse une dizaine de gigaoctets : dès
            # deux, le dire AVANT, pendant qu'un disque plein est encore
            # évitable.
            print(f"\n⚠ {t('Several versions: hours of work, tens of GB.')}")
            if not self._is_yes(input(f"💬 {t('Continue? (Y/N): ')}")):
                print(t("Nothing to do."))
                return
        hote = self._container_arch_hote(prefixe)
        plan = self._container_choix_architectures(prefixe, cibles, hote)
        if not plan:
            return
        etrangeres = sorted(
            {a for archs in plan.values() for a in archs} - {hote}
        )
        if etrangeres and not self._container_assure_emulation(
            prefixe, etrangeres
        ):
            return
        sortie = ui.choose(
            t("Output:"),
            ["local", "push"],
            labels=[
                t("A local tag per architecture"),
                t(
                    "A multi-architecture manifest pushed to the registry"
                    " (docker login required)"
                ),
            ],
            default="local",
        )
        if sortie is None:
            return
        pousser = sortie == "push"
        # Le gel est la règle : l'image porte le code que nomme le manifeste.
        # Les branches donnent une image de développement, dont le code
        # change d'une construction à l'autre.
        code = ui.choose(
            t("Code:"),
            ["freeze", "branches"],
            labels=[
                t("The frozen commits of the manifest"),
                t("The head of each branch (development image)"),
            ],
            default="freeze",
        )
        if code is None:
            return
        sur_branches = " --branches" if code == "branches" else ""
        # Les modules extra par défaut, comme l'installation de production du
        # TODO qui les inclut ; l'installation standard s'en passe.
        type_install = ui.choose(
            t("Install type:"),
            ["standard", "extra"],
            labels=[
                t("Standard install (without extra modules)"),
                t("Install with extra modules (CybroOdoo - large, slow)"),
            ],
            default="extra",
        )
        if type_install is None:
            return
        sans_extra = " --without_extra" if type_install == "standard" else ""
        sans_cache = ""
        if self._is_yes(input(f"💬 {t('Rebuild without cache? (Y/N): ')}")):
            sans_cache = " --no-cache"

        echecs = []
        for version in cibles:
            court = version.split(".")[0]
            archs = plan[version]
            options = ""
            # La commande d'avant, telle quelle, pour l'architecture de l'hôte
            # en local : docker_build.sh n'a rien de plus à apprendre.
            if pousser or archs != [hote]:
                options += f" --platform={','.join(archs)}"
            if pousser:
                options += " --push"
            cmd = (
                f"{prefixe}./script/docker/docker_build.sh"
                f" --odoo_{court}{options}{sur_branches}{sans_extra}{sans_cache}"
            )
            if self.execute.exec_command_live(cmd, source_erplibre=False):
                echecs.append(version)
            if Execute.interrupted:
                return
        if len(cibles) > 1:
            passees = [v for v in cibles if v not in echecs]
            print(f"\n{t('Built:')} {', '.join(passees) or '-'}")
            if echecs:
                print(f"{t('Failed:')} {', '.join(echecs)}")

    def _container_sortie(self, prefixe, commande):
        """La sortie d'une commande lancée avec le préfixe d'environnement, ou
        None quand elle échoue."""
        try:
            fini = subprocess.run(
                ["bash", "-c", f"{prefixe}{commande}"],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return fini.stdout.strip() if fini.returncode == 0 else None

    def _container_arch_hote(self, prefixe):
        """L'architecture du démon Docker, au sens de Docker : amd64,
        arm64… — celle d'une construction sans --platform."""
        arch = self._container_sortie(
            prefixe, "docker version --format '{{.Server.Arch}}'"
        )
        return arch or "amd64"

    def _container_plateformes_publiees(self, prefixe, version):
        """Les architectures que publie l'image Python d'une version d'Odoo,
        lues par docker_build.sh, qui choisit cette image. Vide si le
        registre ne répond pas."""
        court = version.split(".")[0]
        sortie = self._container_sortie(
            prefixe,
            f"./script/docker/docker_build.sh --odoo_{court} --print-platforms",
        )
        return sortie.split() if sortie else []

    def _container_plateformes_emulees(self, prefixe):
        """Les plateformes que buildx sait construire, sans leur variante."""
        sortie = self._container_sortie(
            prefixe, "docker buildx inspect default"
        )
        emulees = set()
        for ligne in (sortie or "").splitlines():
            if ligne.startswith("Platforms:"):
                for plateforme in ligne.split(":", 1)[1].split(","):
                    morceaux = plateforme.strip().split("/")
                    if len(morceaux) >= 2:
                        emulees.add(morceaux[1])
        return emulees

    def _container_choix_architectures(self, prefixe, cibles, hote):
        """{version: [architectures]} à construire, ou {} pour revenir.

        Une seule question, même pour toutes les versions : un choix
        multiple (`ui.choose`) des architectures offertes, par numéro, plage,
        nom ou tout, all ou *, celle de l'hôte marquée comme la seule qui se
        construise sans émulation. Une réponse vide, [0] ou Ctrl+D n'en
        choisissent aucune. Chaque version ne garde que ce que sa base
        publie, et ce qu'elle perd est nommé.
        """
        publiees = {}
        for version in cibles:
            archs = self._container_plateformes_publiees(prefixe, version)
            if not archs:
                print(f"⚠ {t('Unreadable platforms for Odoo %s.') % version}")
                archs = [hote]
            publiees[version] = archs
        offertes = []
        for archs in publiees.values():
            offertes += [a for a in archs if a not in offertes]
        print()
        choisies = ui.choose(
            t("Architectures:"),
            offertes,
            multi=True,
            labels=[
                f"{arch} ({t('this machine')})" if arch == hote else arch
                for arch in offertes
            ],
            names=dict(zip(offertes, offertes)),
        )
        if not choisies:
            return {}
        plan = {}
        for version in cibles:
            gardees = [a for a in choisies if a in publiees[version]]
            for arch in choisies:
                if arch not in gardees:
                    print(
                        f"⚠ {t('%s is not published for Odoo %s: skipped.')}"
                        % (arch, version)
                    )
            if gardees:
                plan[version] = gardees
        return plan

    def _container_assure_emulation(self, prefixe, archs):
        """Vrai quand buildx émule chacune des architectures. Sinon, propose
        l'installation de buildx et de QEMU, commande montrée d'abord."""
        manquantes = [
            a
            for a in archs
            if a not in self._container_plateformes_emulees(prefixe)
        ]
        if not manquantes:
            return True
        commande = "sudo bash script/install/install_container.sh --multiarch"
        print(f"\n⚠ {t('No emulation for: %s') % ', '.join(manquantes)}")
        print(f"  {commande}")
        if not self._is_yes(
            input(f"💬 {t('Install buildx and QEMU now? (Y/N): ')}")
        ):
            return False
        self.execute.exec_command_live(commande, source_erplibre=False)
        emulees = self._container_plateformes_emulees(prefixe)
        encore = [a for a in manquantes if a not in emulees]
        if encore:
            print(f"⚠ {t('Still no emulation for: %s') % ', '.join(encore)}")
            return False
        return True

    def _container_compose(self):
        """Démarrer, arrêter, suivre ou lister la composition ERPLibre
        (CONTAINER_COMPOSE, `menus/deploy.py`). Rend False sur [0], et None,
        le menu fermé, sans moteur qui réponde."""
        return navigate(self, menus_deploy.CONTAINER_COMPOSE)

    def _container_compose_ouvre(self):
        """Ce qui ouvre le menu de la composition : la commande compose du
        moteur retenu. Rend {"compose"}, que reçoit chaque entrée, ou None
        sans moteur qui réponde."""
        fiche = self._container_fiche()
        if not fiche:
            return None
        return {"compose": fiche["compose"] or [fiche["moteur"], "compose"]}

    def _container_compose_geste(self, args, compose=None):
        """Lance la commande compose `compose`, suivie de `args`. Sans elle,
        comme lancée seule depuis la TUI de télémétrie, la commande est
        celle du moteur retenu maintenant, et rien ne part sans moteur qui
        réponde."""
        if compose is None:
            contexte = self._container_compose_ouvre()
            if contexte is None:
                return
            compose = contexte["compose"]
        self.execute.exec_command_live(
            shlex.join(compose + args), source_erplibre=False
        )

    def _container_erplibre(self):
        """Les gestes qui visent le conteneur ERPLibre déjà démarré
        (CONTAINER_ERPLIBRE, `menus/deploy.py`). Rend False sur [0], et None,
        le menu fermé, quand rien ne peut servir les scripts.

        Tous passent par les scripts de script/docker/, qui retrouvent le
        conteneur d'après le nom du répertoire courant — les lancer depuis
        un autre répertoire ne trouve rien.
        """
        return navigate(self, menus_deploy.CONTAINER_ERPLIBRE)

    def _container_erplibre_ouvre(self):
        """Ce qui ouvre le menu du conteneur ERPLibre : le préfixe de
        `_container_exige_docker`. Rend {"prefixe"}, que reçoit chaque
        entrée, ou None quand rien ne peut servir les scripts."""
        prefixe = self._container_exige_docker()
        if prefixe is None:
            return None
        return {"prefixe": prefixe}

    def _container_script(self, script, prefixe=None):
        """Lance le script `script` de script/docker/, précédé de `prefixe`.
        Sans lui, comme lancé seul depuis la TUI de télémétrie, le préfixe
        se demande à `_container_exige_docker`, et rien ne part quand rien
        ne peut servir le script."""
        if prefixe is None:
            prefixe = self._container_exige_docker()
            if prefixe is None:
                return
        self.execute.exec_command_live(prefixe + script, source_erplibre=False)

    def _container_copier_fichier(self, prefixe=None):
        """Copie un fichier de l'hôte vers le conteneur.

        Le script exige un fichier qui existe et refuse le reste : la source
        est donc vérifiée ici, où l'on peut redemander, plutôt qu'au retour
        d'un code d'erreur. `prefixe` est celui de `_container_exige_docker`,
        que demande la copie lancée sans lui, seule, depuis la TUI de
        télémétrie ; elle ne part pas quand rien ne peut la servir.
        """
        if prefixe is None:
            prefixe = self._container_exige_docker()
            if prefixe is None:
                return
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
        """Effacer des images choisies à la pièce : par leur rang, par leur
        référence telle que la liste l'écrit, ou toutes par « tout »,
        « all » ou « * ».

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
        refs = [container_runtime.reference_image(image) for image in images]
        libelles = []
        for ref, image in zip(refs, images):
            ligne = f"{ref}  {image['taille']}  ({image['age']})"
            tenants = usages.get(image["id"])
            if tenants:
                ligne += f"  ⛓ {', '.join(c['nom'] for c in tenants)}"
            libelles.append(ligne)
        choisies = ui.choose(
            t("Images to remove:"),
            refs,
            multi=True,
            labels=libelles,
            names=dict(zip(refs, refs)),
        )
        if not choisies:
            return

        plan = []
        for ref in choisies:
            image = images[refs.index(ref)]
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
                    if Execute.interrupted:
                        return
            args = ["rmi", "-f", ref] if action == "forcer" else ["rmi", ref]
            cmd = container_runtime.commande(fiche, args)
            if self.execute.exec_command_live(
                shlex.join(cmd), source_erplibre=False
            ):
                echecs.append(ref)
            if Execute.interrupted:
                return
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
        rang = ui.choose(
            t("Decision:"), range(len(options)), default=0, labels=options
        )
        return ("garder", "vider", "forcer")[rang or 0]

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
        libelles = []
        for nom in noms:
            projet = projets[nom]
            etats = ", ".join(
                sorted({c["etat"] for c in projet["conteneurs"]})
            )
            libelles.append(
                f"{nom}  —  {projet['dossier'] or '?'}\n"
                f"    {len(projet['conteneurs'])} {t('containers')} ({etats})"
            )
        choisis = ui.choose(
            t("Workspaces to remove:"),
            noms,
            multi=True,
            labels=libelles,
            names=dict(zip(noms, noms)),
        )
        if not choisis:
            return

        plan = []
        for nom in choisis:
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
            if Execute.interrupted:
                return
        self._container_bilan(
            len(etapes),
            echecs,
            t("An image another workspace still uses is kept."),
        )

    # ------------------------------------------------------------------
    # Les bases du conteneur ERPLibre

    def _container_mot_de_passe_maitre(self):
        """Le mot de passe maître d'Odoo, saisi sans écho ; "" s'il est vide.

        La commande « db » d'ERPLibre l'exige pour supprimer une base et pour
        restaurer par-dessus une base existante. Vide, elle essaie le
        défaut d'Odoo, « admin ». getpass n'écrit pas ce qu'on tape : il
        n'atteint ni l'écran ni le journal de session.
        """
        return getpass.getpass(f"🔑 {t('Odoo master password: ')}")

    def _container_dans(self, cmd, libelle, entree=None, secret=None):
        """Lance une commande « exec » et rend son code.

        Hors de exec_command_live : celui-ci recopie la commande à l'écran,
        et ces commandes portent un script shell entier. Le menu annonce
        lui-même ce qu'il lance, en une ligne ; le journal de session reçoit
        `libelle` à la place du script, puis la sortie et le code. Aucune
        de ces commandes ne demande de saisie : le tube de lancer_journalise
        ne leur retire rien.

        `secret`, quand il est donné, devient la première ligne de l'entrée
        standard, que le script lit (container_db._MOT_DE_PASSE_MAITRE) :
        ni la ligne de commande ni le journal ne le voient.
        """
        # Ce que le menu vient d'écrire doit précéder la sortie du conteneur,
        # même quand stdout n'est pas un terminal.
        sys.stdout.flush()
        if secret is None:
            return todo_journal.lancer_journalise(
                cmd, libelle=libelle, stdin=entree
            )
        lecture, ecriture = os.pipe()
        try:
            os.write(ecriture, (secret + "\n").encode())
        finally:
            os.close(ecriture)
        try:
            return todo_journal.lancer_journalise(
                cmd, libelle=libelle, stdin=lecture
            )
        finally:
            os.close(lecture)

    def _container_cible_erplibre(self, fiche):
        """Le conteneur ERPLibre en marche à viser, ou None.

        Celui de la composition du répertoire courant d'abord, comme les
        scripts de script/docker/ ; le seul en marche ensuite ; sinon la
        question (`ui.choose`), sans défaut : la restauration et la
        suppression qui le visent nomment leur conteneur, et une réponse
        vide, [0] ou Ctrl+D rendent None.
        """
        conteneurs = container_db.conteneurs_erplibre(fiche)
        if not conteneurs:
            print(f"⚠ {t('No ERPLibre container is running.')}")
            print(f"  {t('See [12] Compose to start it.')}")
            return None
        ici = container_db.du_dossier(conteneurs, os.getcwd())
        if ici:
            return ici
        if len(conteneurs) == 1:
            return conteneurs[0]
        rang = ui.choose(
            t("Running ERPLibre containers:"),
            range(len(conteneurs)),
            labels=[
                f"{c['nom']}  —  {c['dossier'] or '?'}" for c in conteneurs
            ],
        )
        return conteneurs[rang] if rang is not None else None

    def _container_sonder(self, fiche, conteneur):
        """Le répertoire de données d'Odoo et l'espace libre du conteneur."""
        cmd = container_db.executer(fiche, conteneur, container_db.SONDE)
        _code, sortie = container_runtime.lancer(cmd, timeout=30)
        return container_db.lire_sonde(sortie)

    def _container_lister_bases(self, fiche, conteneur):
        """[(base, vide)] du PostgreSQL du conteneur, ou None s'il se tait."""
        cmd = container_db.executer(fiche, conteneur, container_db.LISTE)
        code, sortie = container_runtime.lancer(cmd, timeout=120)
        if code != 0:
            return None
        return container_db.lire_liste(sortie)

    def _container_afficher_sonde(self, sonde):
        lisible = container_db.lisible
        print(f"  {t('Odoo data directory:')} {sonde['data_dir'] or '?'}")
        print(
            f"    {t('free:')} {lisible(sonde['libre_data'])}"
            f"  ({sonde['montage_data'] or '?'})"
        )
        print(
            f"  /tmp  {t('free:')} {lisible(sonde['libre_tmp'])}"
            f"  ({sonde['montage_tmp'] or '?'})"
        )
        if not sonde["ecriture"]:
            print(f"  ⚠ {t('Odoo account cannot write there: no restore.')}")

    def _container_espace_disque(self):
        """L'espace qui décide d'une restauration, du moteur au conteneur.

        Trois niveaux, parce que chacun peut manquer seul : le disque qui
        porte le moteur (images, couches, volumes), ce que le moteur peut
        rendre, et, dans chaque conteneur ERPLibre, /tmp et le répertoire de
        données d'Odoo.
        """
        fiche = self._container_fiche()
        if not fiche:
            return
        lisible = container_db.lisible
        moteur = fiche["moteur"]
        cmd = container_runtime.commande(
            fiche, ["info", "-f", container_db.FORMAT_RACINE[moteur]]
        )
        code, sortie = container_runtime.lancer(cmd, timeout=30)
        lignes = [x for x in sortie.splitlines() if x.startswith("/")]
        racine = lignes[-1].strip() if code == 0 and lignes else ""
        print(f"💽 {t('Engine storage:')} {racine or '?'}")
        if racine:
            try:
                usage = shutil.disk_usage(racine)
                print(
                    f"  {t('free:')} {lisible(usage.free)}"
                    f" / {lisible(usage.total)}"
                )
            except OSError as err:
                print(f"  ⚠ {err}")
        print(f"\n{t('Reclaimable by the engine:')}", flush=True)
        cmd = container_runtime.commande(fiche, ["system", "df"])
        self.execute.exec_command_live(shlex.join(cmd), source_erplibre=False)
        for conteneur in container_db.conteneurs_erplibre(fiche):
            print(f"\n📦 {conteneur['nom']}")
            self._container_afficher_sonde(
                self._container_sonder(fiche, conteneur)
            )
        print(f"\n{t('A web restore writes to /tmp twice the .zip,')}")
        print(f"{t('then its uncompressed content: see [15] instead.')}")

    def _container_restaurer_base(self):
        """Restaurer une sauvegarde .zip dans le conteneur ERPLibre.

        Le zip voyage par l'entrée standard jusqu'au répertoire de données
        d'Odoo, et « odoo-bin db load » s'y extrait (voir container_db). La
        place se vérifie AVANT de copier quoi que ce soit, sur la taille
        décompressée que donne l'index du zip, et le dossier de travail
        s'efface quoi qu'il arrive.
        """
        fiche = self._container_fiche()
        if not fiche:
            return
        conteneur = self._container_cible_erplibre(fiche)
        if not conteneur:
            return
        depart = os.path.join(os.getcwd(), "image_db")
        if not os.path.isdir(depart):
            depart = os.getcwd()
        chemin = self.db_manager.select_backup_path(depart)
        if not chemin:
            print(t("Nothing to do."))
            return
        tailles = container_db.tailles_sauvegarde(chemin)
        if not tailles:
            print(
                f"❌ {t('Not an Odoo backup (.zip with dump.sql):')} {chemin}"
            )
            return
        lisible = container_db.lisible
        print(f"\n📦 {conteneur['nom']}")
        print(
            f"  {t('Backup:')} {lisible(tailles['zip'])}"
            f" — dump.sql {lisible(tailles['dump'])},"
            f" filestore {lisible(tailles['filestore'])}"
            f" ({tailles['fichiers']} {t('files')})"
        )
        sonde = self._container_sonder(fiche, conteneur)
        self._container_afficher_sonde(sonde)
        if not sonde["ecriture"]:
            return
        besoin = container_db.besoin(tailles)
        print(f"  {t('Needed (estimate):')} {lisible(besoin)}")
        libre = sonde["libre_data"]
        if libre is not None and besoin > libre:
            print(f"⚠ {t('Not enough free space for this restore.')}")
            if not self._is_yes(input(f"💬 {t('Continue anyway? (Y/N): ')}")):
                print(t("Nothing to do."))
                return

        bases = self._container_lister_bases(fiche, conteneur)
        if bases is None:
            print(f"⚠ {t('PostgreSQL did not list the databases.')}")
            bases = []
        vides = dict(bases)
        nom = click.prompt(
            t("Database name"),
            default=container_db.nom_par_defaut(chemin) or None,
        ).strip()
        if not container_db.RE_NOM_BASE.match(nom):
            print(f"❌ {t('Invalid database name:')} {nom}")
            return
        options = []
        secret_restauration = ""
        if nom in vides:
            etat = t("empty") if vides[nom] else t("with data")
            print(f"⚠ {t('The database already exists:')} {nom} ({etat})")
            if not self._is_yes(
                input(f"💬 {t('Drop it and restore over it? (Y/N): ')}")
            ):
                print(t("Nothing to do."))
                return
            options.append("-f")
            secret_restauration = self._container_mot_de_passe_maitre()
        if self._is_yes(
            input(f"💬 {t('Neutralize (mail servers, crons)? (Y/N): ')}")
        ):
            options.append("-n")
        # Le défaut du gestionnaire web d'Odoo : une copie reçoit un nouvel
        # UUID, et deux bases ne se disputent pas les services qui les
        # identifient par lui. « Déplacée » garde celui d'origine.
        print(f"  {t('This database is a copy: it gets a new UUID.')}")
        print(f"  {t('This database was moved: it keeps its original UUID.')}")
        if not self._is_yes_default_yes(
            input(
                f"💬 {t('Is this database a copy? If unsure, yes. (Y/n): ')}"
            )
        ):
            options.append("--move")
        # Une sauvegarde d'une version précédente du code ne se charge pas
        # sans mise à jour de ses modules : la question se pose avant
        # l'exécution, la réponse choisit le script.
        print(f"  {t('A backup from an earlier ERPLibre needs its modules')}")
        print(f"  {t('updated: without it, Odoo refuses to load the base.')}")
        question = t("Update every module after the restore (-u all)? (y/N): ")
        mise_a_jour = self._is_yes(input(f"💬 {question}"))
        script = (
            container_db.RESTAURER_MAJ
            if mise_a_jour
            else container_db.RESTAURER
        )
        action = (
            f"psql + filestore, odoo-bin -u all {' '.join(options + [nom])}"
            if mise_a_jour
            else f"odoo-bin db load {' '.join(options + [nom])}"
        )
        print(
            f"\n{t('Will execute:')} {action}"
            f" {sonde['data_dir']}/{container_db.TRAVAIL}/{container_db.ZIP}"
        )
        if not self._is_yes(input(f"💬 {t('Continue? (Y/N): ')}")):
            print(t("Nothing to do."))
            return

        try:
            print(f"📤 {t('Copying the backup into the container...')}")
            with open(chemin, "rb") as entree:
                code = self._container_dans(
                    container_db.executer(
                        fiche,
                        conteneur,
                        container_db.RECEVOIR,
                        interactif=True,
                    ),
                    container_db.libelle(
                        conteneur,
                        f"cat > {sonde['data_dir']}/{container_db.TRAVAIL}"
                        f"/{container_db.ZIP}",
                    ),
                    entree=entree,
                )
            if code == 0:
                print(f"📥 {t('Restoring...')}")
                code = self._container_dans(
                    container_db.executer(
                        fiche,
                        conteneur,
                        script,
                        [nom, *options],
                        interactif=True,
                    ),
                    container_db.libelle(conteneur, action),
                    secret=secret_restauration,
                )
        finally:
            self._container_dans(
                container_db.executer(fiche, conteneur, container_db.NETTOYER),
                container_db.libelle(
                    conteneur,
                    f"rm -rf {sonde['data_dir']}/{container_db.TRAVAIL}",
                ),
            )
        if code == 0:
            print(f"✅ {t('Database restored:')} {nom}")
            return
        if code == 3:
            print(
                f"❌ {t('This Odoo has no db command: use the web manager.')}"
            )
            return
        print(f"❌ {t('The restore failed, code')} {code}.")
        if not mise_a_jour:
            # « column … does not exist » au chargement : la sauvegarde vient
            # d'une version précédente du code.
            for phrase in (
                "A missing column means an earlier ERPLibre backup:",
                "restore again with the module update (-u all).",
            ):
                print(f"  {t(phrase)}")
        restes = dict(self._container_lister_bases(fiche, conteneur) or [])
        if restes.get(nom):
            print(f"⚠ {t('The failed restore left an empty database:')} {nom}")
            if self._is_yes(input(f"💬 {t('Delete it? (Y/N): ')}")):
                self._container_dans(
                    container_db.executer(
                        fiche,
                        conteneur,
                        container_db.SUPPRIMER,
                        [nom],
                        interactif=True,
                    ),
                    container_db.libelle(conteneur, f"odoo-bin db drop {nom}"),
                    secret=self._container_mot_de_passe_maitre(),
                )

    def _container_supprimer_base(self):
        """Supprimer une base du conteneur, filestore compris.

        Le nom se RETAPE : recopier un nom long oblige à regarder ce qu'on
        détruit, là où un numéro se tape par réflexe. Une base vide — ce que
        laisse une restauration interrompue — est signalée comme telle.
        """
        fiche = self._container_fiche()
        if not fiche:
            return
        conteneur = self._container_cible_erplibre(fiche)
        if not conteneur:
            return
        bases = self._container_lister_bases(fiche, conteneur)
        if bases is None:
            print(f"⚠ {t('PostgreSQL did not list the databases.')}")
            return
        if not bases:
            print(t("No database in this container."))
            return
        # Sans défaut : une réponse vide revient, elle ne vise aucune base.
        rang = ui.choose(
            t("Databases:"),
            range(len(bases)),
            labels=[
                f"{nom}  ({t('empty')})" if vide else nom
                for nom, vide in bases
            ],
        )
        if rang is None:
            return
        nom = bases[rang][0]
        print(f"\n⚠ {t('This deletes the database and its filestore:')} {nom}")
        if input(f"💬 {t('Type its name to confirm: ')}").strip() != nom:
            print(t("Nothing to do."))
            return
        secret = self._container_mot_de_passe_maitre()
        code = self._container_dans(
            container_db.executer(
                fiche,
                conteneur,
                container_db.SUPPRIMER,
                [nom],
                interactif=True,
            ),
            container_db.libelle(conteneur, f"odoo-bin db drop {nom}"),
            secret=secret,
        )
        if code == 0:
            print(f"✅ {t('Database deleted:')} {nom}")
        elif code == 3:
            print(
                f"❌ {t('This Odoo has no db command: use the web manager.')}"
            )
        else:
            print(f"❌ {t('The deletion failed, code')} {code}.")
