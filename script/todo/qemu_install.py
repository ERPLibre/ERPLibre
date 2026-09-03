#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu QEMU/KVM : ce qui s'installe DANS la VM.\n\nCe fichier ne cr\u00e9e aucune VM : il fabrique les commandes distantes qu'on y\nex\u00e9cutera. Profils ERPLibre et service Odoo, bureau GNOME et ses saveurs,\nmagasins d'applications, fuseaux, miroirs de paquets, et les outils de\nd\u00e9veloppement (PyCharm, Android Studio, extensions GNOME, compilation mobile,\nAVD, Forgejo).\n\nFronti\u00e8re claire : ici on \u00e9crit du shell destin\u00e9 \u00e0 l'invit\u00e9 ; dans\nqemu_deploy.py on d\u00e9cide QUELLES VM le recevront."""

import re
import shlex

from script.todo import dev_tools
from script.todo.todo_i18n import t


class QemuInstallMixin:
    """Menu QEMU/KVM : ce qui s'installe DANS la VM.\n\nCe fichier ne cr\u00e9e aucune VM : il fabrique les commandes distantes qu'on y\nex\u00e9cutera. Profils ERPLibre et service Odoo, bureau GNOME et ses saveurs,\nmagasins d'applications, fuseaux, miroirs de paquets, et les outils de\nd\u00e9veloppement (PyCharm, Android Studio, extensions GNOME, compilation mobile,\nAVD, Forgejo).\n\nFronti\u00e8re claire : ici on \u00e9crit du shell destin\u00e9 \u00e0 l'invit\u00e9 ; dans\nqemu_deploy.py on d\u00e9cide QUELLES VM le recevront."""

    # Préparation hôte QEMU/libvirt du profil « ERPLibre Déploiement ».
    # Délègue à deploy_qemu.py --setup-host : les noms de paquets y sont déjà
    # définis pour apt/dnf/pacman/zypper/brew (TOOL_PACKAGES, DAEMON_PACKAGES),
    # et il fait ce que l'ancien one-liner ne faisait PAS — démarrer le démon,
    # ajouter l'utilisateur au groupe libvirt et activer le réseau « default ».
    # Sans le groupe, virt-install retombe sur qemu:///session où « default »
    # n'existe pas : la VM échoue alors que tous les paquets sont installés.
    # L'ancien one-liner finissait par « || true » et masquait ses erreurs.
    # Le redémarrage est consenti ICI et nulle part ailleurs : la VM vient
    # d'être créée, personne ne la regarde, et le noyau fraîchement installé
    # doit être chargé avant que libvirt puisse monter virbr0. Sur un poste de
    # travail, la question se pose — voir _qemu_ensure_tools.
    _QEMU_QEMU_PKGS = (
        "./script/qemu/deploy_qemu.py --setup-host --assume-yes"
        " --reboot-if-needed --assume-yes-reboot"
    )

    def _qemu_ask_prod(self):
        """Environnement cible : dev (défaut) ou prod. En PROD : ERPLibre est
        installé dans /opt/erplibre (au lieu de ~/git/erplibre) et le service
        systemd reste CONFINÉ par SELinux (pas d'unconfined)."""
        print(f"\n{t('Target environment?')}")
        print(f"  [1] {t('Development (~/git/erplibre, SELinux relaxed)')} *")
        print(f"  [2] {t('Production (/opt/erplibre, SELinux enforced)')}")
        sel = input(t("Choice (1-2, default 1): ")).strip()
        return sel == "2"

    def _qemu_install_profiles(self):
        """Profils installables : [(libellé, commande)]. Le premier est le
        défaut. Partagé par l'invite en ligne et le formulaire TUI."""
        profiles = [
            (
                f"ERPLibre + Odoo {v}",
                f"make install_os && make install_odoo_{v}",
            )
            for v in ("18", "17", "16", "15", "14", "13", "12")
        ]
        profiles += [
            (
                t("ERPLibre + all Odoo versions"),
                "make install_os && make install_odoo_all_version",
            ),
            (
                t("ERPLibre only (no Odoo)"),
                "make install_os && ./script/install/install_erplibre.sh",
            ),
            (
                t("ERPLibre mobile (home)"),
                "make install_os && ./mobile/install_and_run.sh",
            ),
            (
                t("ERPLibre Deployment (+ QEMU + dev)"),
                "make install_os && make install_dev && "
                + self._QEMU_QEMU_PKGS,
            ),
            (
                t("Proxmox VE hypervisor (no Odoo)"),
                "./script/proxmox/install_proxmox.sh",
            ),
        ]
        return profiles

    # Un système qui IMPOSE ce qu'on installe dessus. Choisir « Proxmox VE »
    # comme système, c'est demander qu'il soit installé : ni ERPLibre, ni
    # Odoo n'ont leur place sur un hyperviseur, et les y poser par défaut
    # était le contraire de ce que le choix exprimait.
    _QEMU_DISTRO_PROFILE = {"proxmox": "Proxmox VE hypervisor (no Odoo)"}

    def _qemu_distro_profile(self, distro):
        """(libellé, commande) du profil qu'un système impose, ou None.

        Une seule règle, lue par l'invite en ligne comme par le formulaire :
        chacun la redisait, et le formulaire l'avait justement oubliée."""
        voulu = self._QEMU_DISTRO_PROFILE.get(distro)
        if not voulu:
            return None
        cible = t(voulu)
        for entree in self._qemu_install_profiles():
            if entree[0] == cible:
                return entree
        return None

    def _qemu_no_erplibre_cmds(self):
        """Les commandes d'installation qui NE posent pas ERPLibre.

        Déduites de la table des systèmes imposés : le profil hyperviseur
        Proxmox n'installe ni ERPLibre ni Odoo. Rien n'est écrit en dur ici,
        pour qu'ajouter un système à la table suffise."""
        cmds = set()
        for distro in self._QEMU_DISTRO_PROFILE:
            impose = self._qemu_distro_profile(distro)
            if impose:
                cmds.add(impose[1])
        return cmds

    def _qemu_installs_erplibre(self, branch, install_cmd=""):
        """Cette VM va-t-elle VRAIMENT poser ERPLibre ?

        Décidé sur la COMMANDE, pas sur la case : elle seule sait si le dépôt
        sera cloné. C'est ce qui règle les cinq gigaoctets de marge et la
        section ERPLibre du guide affiché à la connexion. Sans commande
        connue, on répond oui : mieux vaut cinq gigaoctets de trop qu'une
        installation qui remplit le disque."""
        if not branch:
            return False
        if not install_cmd:
            return True
        return install_cmd.strip() not in self._qemu_no_erplibre_cmds()

    def _qemu_pick_install_profile(self, distro=""):
        """Choix de CE QU'ON installe sur la VM. Renvoie (label, commande
        finale exécutée dans ~/git/erplibre).

        Le profil qu'un système impose passe en tête, et devient donc le
        défaut de la réponse vide.
        """
        profiles = self._qemu_install_profiles()
        impose = self._qemu_distro_profile(distro)
        if impose:
            profiles.sort(key=lambda p: p[0] != impose[0])
        print(f"\n{t('What to install on the VM(s)?')}")
        for i, (label, _cmd) in enumerate(profiles, 1):
            print(f"  [{i}] {label}{' *' if i == 1 else ''}")
        sel = input(t("Choice (number, blank = Odoo 18): ")).strip()
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(profiles):
                return profiles[idx]
        except ValueError:
            pass
        return profiles[0]  # défaut : ERPLibre + Odoo 18

    @staticmethod
    def _qemu_install_dir(prod):
        """Répertoire d'installation ERPLibre dans la VM : /opt/erplibre en
        PROD (hors /home -> service SELinux confiné possible), sinon
        ~/git/erplibre (dev)."""
        return "/opt/erplibre" if prod else "$HOME/git/erplibre"

    @staticmethod
    def _qemu_guide_dir(prod):
        """Répertoire d'ERPLibre tel que le GUIDE de connexion l'annonce.

        « ~/git/erplibre » plutôt que « $HOME/git/erplibre » : ce chemin n'est
        pas exécuté par un script, il est lu par quelqu'un qui recopie la ligne
        dans son shell — où les deux marchent — et le tilde est la forme qu'il
        reconnaît. En production le chemin est absolu et la question ne se pose
        pas."""
        return "/opt/erplibre" if prod else "~/git/erplibre"

    @staticmethod
    def _qemu_make_target(install_cmd):
        """Cible make qui installe Odoo dans `install_cmd`, pour le guide.

        Les profils s'écrivent « make install_os && make install_odoo_18 » : la
        cible utile est la SECONDE, celle qui installe Odoo, et c'est aussi
        celle qu'on relance après un « git pull ». Les profils qui n'en ont pas
        (« ERPLibre seul », « mobile », « Déploiement ») rendent une chaîne
        vide : le guide s'arrête alors à « git pull » plutôt que d'annoncer une
        cible qui n'est pas celle de cette VM."""
        found = re.findall(r"make\s+(install_odoo\S*)", install_cmd or "")
        return found[-1] if found else ""

    def _qemu_odoo_service_cmd(self, prod=False):
        """Snippet shell (exécuté dans la VM) qui installe ERPLibre/Odoo comme
        service systemd puis l'active. N'est ajouté QUE pour les profils Odoo.

        DEV : ERPLibre sous ~/home. Un service système ne peut PAS exécuter
        du user_home_t sous SELinux, et « SELinuxContext=unconfined » ne suffit
        pas (transition init_t -> unconfined_t refusée -> toujours 203/EXEC).
        Sur une VM de dev jetable, on passe donc SELinux en PERMISSIF (relâché).
        PROD : ERPLibre sous /opt/erplibre (hors user_home_t) -> le service
        reste CONFINÉ par SELinux ; on restaure les contextes (restorecon)."""
        svc_dir = self._qemu_install_dir(prod)
        selinux_shell = (
            'SELINUX_LINE=""; '  # pas de SELinuxContext (inefficace)
        )
        if prod:
            pre = (
                "command -v restorecon >/dev/null 2>&1 && "
                "sudo restorecon -R /opt/erplibre >/dev/null 2>&1 || true; "
            )
        else:
            # DEV : SELinux permissif (persistant) si actif -> le service peut
            # exécuter run.sh/venv sous /home.
            pre = (
                "if command -v getenforce >/dev/null 2>&1 && "
                '[ "$(getenforce)" = "Enforcing" ]; then '
                "sudo setenforce 0 || true; "
                "sudo sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' "
                "/etc/selinux/config 2>/dev/null || true; fi; "
            )
        return (
            f'SVC_USER=$(whoami); SVC_GROUP=$(id -gn); SVC_DIR="{svc_dir}"; '
            + pre
            + selinux_shell
            + "sudo tee /etc/systemd/system/erplibre.service >/dev/null <<UNIT\n"
            "[Unit]\n"
            "Description=ERPLibre\n"
            "Requires=postgresql.service\n"
            "After=network.target network-online.target postgresql.service\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            "User=$SVC_USER\n"
            "Group=$SVC_GROUP\n"
            "Restart=always\n"
            "RestartSec=5\n"
            "ExecStart=/bin/bash $SVC_DIR/run.sh\n"
            "WorkingDirectory=$SVC_DIR\n"
            "StandardOutput=journal+console\n"
            "$SELINUX_LINE\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
            "UNIT\n"
            "sudo systemctl daemon-reload; "
            "sudo systemctl enable --now erplibre.service"
        )

    # Bureaux disponibles, par gestionnaire de paquets. Une seule source pour
    # la TUI et la CLI. Les noms ont été relevés distribution par
    # distribution, pas déduits : Arch n'a PAS xrdp dans ses dépôts officiels
    # (AUR seulement) et prend TigerVNC, avec un port et un client différents.
    #
    # Côté dnf on installe un ENVIRONNEMENT, pas un groupe : le groupe
    # « gnome-desktop » d'AlmaLinux apporte gdm et gnome-shell mais PAS
    # « base-x », donc aucun serveur X — vérifié dans son comps.xml. Les
    # environnements diffèrent selon la famille (RHEL / Fedora), d'où la
    # cascade : le premier qui existe gagne.
    _QEMU_DESKTOP = {
        "gnome": {
            "label": "GNOME",
            "apt": "gnome-core dbus-x11",
            "dnf_env": "graphical-server-environment "
            "workstation-product-environment gnome-desktop",
            "pacman": "gnome gdm",
            "zypper": "patterns-gnome-gnome_basic gdm",
            "service": "gdm",
            # Suffixe ajouté au nom de VM, donc au nom d'hôte. Une VM
            # graphique se reconnaît alors d'un « virsh list », et deux VM de
            # même distribution mais de types différents ne se marchent plus
            # dessus — le nom sert aussi de clé de collision.
            "suffix": "gnome",
        },
        "cinnamon": {
            "label": "Cinnamon (Linux Mint)",
            # Le bureau de Linux Mint, depuis les dépôts de la distribution :
            # Ubuntu 24.04 livre Cinnamon 6.0.4, la 25.10 la 6.4.12. Le dépôt
            # de Mint lui-même n'est pas utilisé — il est en HTTP nu et ne
            # publie que i386/amd64, ce qui exclurait arm64 et s390x.
            "apt": "cinnamon-desktop-environment dbus-x11",
            "dnf_env": "cinnamon-desktop",
            "pacman": "cinnamon lightdm lightdm-gtk-greeter",
            "zypper": "cinnamon lightdm",
            "service": "lightdm",
            # « mint » plutôt que « cinnamon » : c'est le nom retenu pour le
            # parc. Le paquet installé reste bien Cinnamon, depuis les dépôts
            # de la distribution et non ceux de Mint.
            "suffix": "mint",
        },
    }

    # Ubuntu remplace trois applications par des paquets de TRANSITION dont le
    # postinst lance « snap install ». Or snapd est coupé juste avant, pour
    # empêcher ses rafraîchissements pendant l'installation : le postinst ne
    # joint alors pas le store et RÉESSAIE UNE MINUTE DURANT TRENTE MINUTES.
    # L'installation paraît figée et rien dans le log ne dit pourquoi.
    #
    # La famille est CLOSE et relevée dans l'index du dépôt, pas devinée : trois
    # paquets sources portent une version « …snap1… », firefox, chromium-browser
    # et thunderbird — avec toutes leurs déclinaisons (firefox-locale-*,
    # chromium-codecs-*). Les corriger un à un a coûté deux VM figées : firefox
    # sous GNOME, puis thunderbird sous Cinnamon.
    #
    # Les trois ne sont que RECOMMANDÉS, et avec des solutions de rechange :
    #   Recommends: firefox-esr | firefox | chromium | epiphany-browser | …
    #   Recommends: thunderbird | evolution | geary | mail-reader
    # On les écarte donc, et on nomme deux vrais .deb pour satisfaire les
    # recommandations. Les nommer rend le résultat déterministe : laissé à apt,
    # le premier repli était « chromium-browser », un paquet de transition lui
    # aussi.
    #
    # Un épinglage apt sur « Pin: version *snap1* » aurait été plus général —
    # essayé en glob et en regex, il ne bloque rien. Mesuré sur une VM 26.04 :
    # avec cette liste, GNOME (844 paquets) et Cinnamon (1167) n'en tirent
    # AUCUN, sans erreur apt.
    _QEMU_APT_NO_SNAP = (
        "epiphany-browser evolution"
        " firefox- chromium- chromium-browser- thunderbird-"
    )

    # Magasin d'applications d'une VM graphique. Ubuntu livre snapd dans son
    # image cloud (vérifié : 2.75.2 en 26.04) et gnome-core RECOMMANDE
    # « firefox », qui n'y est plus qu'un paquet de transition lançant
    # « snap install ». Trois réponses possibles, et il faut choisir :
    #
    #   deb      rien que des .deb. snapd coupé, paquets-snap écartés,
    #            epiphany-browser comme navigateur. Le plus léger, et rien à
    #            télécharger en plus pendant un déploiement déjà long.
    #   flatpak  l'outillage Flatpak en plus, SANS dépôt Flathub ni
    #            installation : la machine est prête, l'administrateur ajoute
    #            les dépôts qu'il veut.
    #   snap     le comportement d'Ubuntu, snapd laissé actif et Firefox en
    #            snap. Lent sous émulation, mais c'est le défaut de la distro.
    #
    # La question n'a de sens que pour une VM Ubuntu GRAPHIQUE : sur un
    # serveur, rien ne tire de snap.
    QEMU_APP_STORES = (
        ("deb", "deb only (epiphany-browser)"),
        ("flatpak", "Flatpak tooling, no Flathub"),
        ("snap", "snap (Ubuntu default, Firefox)"),
    )

    QEMU_SNAP_DISTROS = ("ubuntu",)

    # Fuseaux proposés au déploiement. Des NOMS IANA, pas des décalages :
    # cloud-init écrit /etc/timezone et refuse « UTC-5 », qui ne dit d'ailleurs
    # rien de l'heure d'été. Un nom porte ses propres règles de bascule.
    #
    # Liste courte et ordonnée par usage réel plutôt qu'exhaustive : la base
    # IANA en compte près de six cents, illisibles dans une liste déroulante.
    # Le Québec d'abord, le reste du Canada ensuite, puis les places qu'on
    # rencontre en pratique. La saisie libre reste offerte pour le reste.
    QEMU_TIMEZONES = (
        "America/Montreal",
        "America/Toronto",
        "America/Halifax",
        "America/Winnipeg",
        "America/Edmonton",
        "America/Vancouver",
        "America/St_Johns",
        "UTC",
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Sao_Paulo",
        "Europe/London",
        "Europe/Paris",
        "Europe/Brussels",
        "Europe/Zurich",
        "Europe/Madrid",
        "Europe/Berlin",
        "Africa/Casablanca",
        "Asia/Dubai",
        "Asia/Kolkata",
        "Asia/Shanghai",
        "Asia/Tokyo",
        "Australia/Sydney",
    )

    @classmethod
    def _qemu_timezone_choices(cls, current=""):
        """Liste à proposer : le fuseau de l'hôte en tête, sans doublon.

        Le mettre en premier plutôt que de le supposer présent : une machine
        hors de cette liste doit quand même voir le sien en un coup d'œil."""
        out = [current] if current else []
        out += [z for z in cls.QEMU_TIMEZONES if z != current]
        return out

    @classmethod
    def _qemu_desktop_suffixes(cls):
        """{clé de saveur: suffixe de nom}. La TUI le reçoit par son contexte
        plutôt que de le redéfinir : un seul endroit décrit les saveurs."""
        return {k: v["suffix"] for k, v in cls._QEMU_DESKTOP.items()}

    @classmethod
    def _qemu_apt_store_pkgs(cls, app_store):
        """Paquets apt à ajouter au bureau selon le magasin retenu."""
        if app_store == "snap":
            # On ne retire rien : Firefox arrivera en snap, comme sur une
            # Ubuntu ordinaire, et snapd est resté actif pour le servir.
            return ""
        pkgs = cls._QEMU_APT_NO_SNAP
        if app_store == "flatpak":
            # Le greffon donne à GNOME Logiciels la gestion des Flatpak.
            # Aucun « remote-add » ici : le dépôt reste un choix explicite.
            pkgs += " flatpak gnome-software-plugin-flatpak"
        return pkgs

    # Accès distant, indépendant du bureau choisi.
    _QEMU_DESKTOP_REMOTE = {
        "apt": {"packages": "xrdp", "port": 3389, "client": "RDP"},
        "dnf": {"packages": "xrdp", "port": 3389, "client": "RDP"},
        "pacman": {"packages": "tigervnc", "port": 5901, "client": "VNC"},
        "zypper": {"packages": "xrdp", "port": 3389, "client": "RDP"},
    }

    # Place que prend un bureau complet, annoncée dans le plan : sur une image
    # cloud de 40 G, l'oublier remplit le disque en pleine installation.
    QEMU_DESKTOP_EXTRA_DISK_GB = 6

    @staticmethod
    def _qemu_cloud_init_wait():
        """Attend la fin de cloud-init, qui tient le verrou apt/dnf/pacman
        pendant sa phase « paquets ».

        L'attente dure jusqu'à 15 min et n'écrivait RIEN : sur une architecture
        émulée, le log restait muet un quart d'heure juste après avoir annoncé
        le début de l'installation, ce qui se lit comme un blocage. Deux lignes
        l'encadrent, et le « status » final dit si elle a abouti ou expiré."""
        return (
            "if command -v cloud-init >/dev/null 2>&1; then "
            'echo "== '
            + t("Waiting for cloud-init to finish (up to 15 min)")
            + ' =="; '
            "sudo timeout 900 cloud-init status --wait >/dev/null 2>&1 "
            "|| true; "
            + f'echo "   {t("cloud-init:")} $(cloud-init status 2>/dev/null '
            '| head -1)"; '
            "fi; "
        )

    @staticmethod
    def _qemu_vm_ready_report():
        """Relevé de mise en route, pour une VM où l'on n'installe RIEN.

        Sans lui, la commande distante valait « true » : le suivi affichait un
        ✅ instantané sur un journal vide, ce qui n'apprend rien de la machine
        qu'on vient de créer. Ici, il y a une fin claire (le marqueur de sortie
        que pose le lanceur) et de quoi juger qu'elle est prête : système,
        noyau, adresse, disque, mémoire, et le verdict de cloud-init.
        """
        return (
            f'echo "===> {t("VM start-up")}"; '
            ". /etc/os-release 2>/dev/null || true; "
            f'echo "   {t("system:")} ${{PRETTY_NAME:-?}}"; '
            f'echo "   {t("kernel:")} $(uname -r) ($(uname -m))"; '
            f'echo "   {t("address:")} '
            "$(hostname -I 2>/dev/null | awk '{print $1}')\"; "
            f'echo "   {t("disk:")} '
            '$(df -h / | awk \'NR==2 {print $3"/"$2" ("$5")"}\')"; '
            f'echo "   {t("memory:")} '
            '$(free -h 2>/dev/null | awk \'NR==2 {print $3"/"$2}\')"; '
            f'echo "   {t("uptime:")} $(uptime -p 2>/dev/null || true)"; '
            f'echo "<=== {t("VM start-up")}"; '
        )

    @staticmethod
    def _qemu_no_auto_upgrade(prod, app_store="deb"):
        """Coupe les mises à jour automatiques sur une VM de DÉVELOPPEMENT.

        Vécu sur erplibre-ubuntu-2404 : unattended-upgrades s'est déclenché en
        pleine migration Odoo 12->13 et a redémarré le cluster PostgreSQL
        (« received fast shutdown request » x3) -> OpenUpgrade a perdu sa
        connexion et la base intermédiaire est restée à moitié migrée. Effet
        secondaire bienvenu : les timers apt-daily ne tiennent plus le verrou
        apt pendant l'installation. En PROD on ne touche à rien : les
        correctifs de sécurité automatiques doivent rester actifs."""
        if prod:
            return ""
        return (
            "if command -v apt-get >/dev/null 2>&1; then "
            "sudo systemctl disable --now unattended-upgrades.service "
            "apt-daily.timer apt-daily-upgrade.timer "
            ">/dev/null 2>&1 || true; "
            'printf \'APT::Periodic::Update-Package-Lists "0";\\n'
            'APT::Periodic::Unattended-Upgrade "0";\\n\' '
            "| sudo tee /etc/apt/apt.conf.d/99-erplibre-no-auto-upgrade "
            ">/dev/null; "
            "fi; "
            "if command -v dnf >/dev/null 2>&1; then "
            "sudo systemctl disable --now dnf-automatic.timer "
            "dnf-automatic-install.timer >/dev/null 2>&1 || true; "
            "fi; "
            # snapd : 57 s sur le CHEMIN CRITIQUE du démarrage, mesurés par
            # « systemd-analyze critical-chain » sur une VM s390x —
            # multi-user.target attend snapd.seeded. C'est du temps payé pour
            # rien quand aucun snap n'est voulu. On désactive plutôt que
            # désinstaller, pour rester réversible d'un « systemctl enable ».
            #
            # Sauf si le magasin RETENU est snap : le couper puis laisser un
            # postinst appeler « snap install » est exactement ce qui figeait
            # une VM graphique trente minutes durant.
            + (
                ""
                if app_store == "snap"
                else "sudo systemctl disable --now snapd.seeded.service "
                "snapd.service snapd.socket snapd.apparmor.service "
                ">/dev/null 2>&1 || true; "
            )
        )

    # Miroirs openSUSE préférés, du plus proche au dernier recours. Le
    # redirecteur officiel n'est PAS géographique pour cette distribution :
    # mesuré depuis Montréal sur les métadonnées oss s390x (15 Mo),
    # download.opensuse.org met 23,8 s — il sert depuis l'Europe — contre
    # 2,7 s pour mirrors.rit.edu. Les trois familles dnf, elles, choisissent
    # déjà un miroir canadien toutes seules ; rien à faire de ce côté.
    #
    # Chaque miroir est SONDÉ sur le chemin de l'architecture ET du produit
    # courants, puis le premier qui répond gagne. C'est nécessaire : aucun ne
    # réplique tout. Relevé le 2026-08-12 —
    #   csclub    Leap oui, Tumbleweed non (404)
    #   rit.edu   zsystems oui ; injoignable ce jour-là (curl 7)
    #   leaseweb  Tumbleweed x86_64 et Leap oui, ports zsystems non
    # D'où plusieurs entrées plutôt qu'une : avec la seule rit.edu, sa panne
    # renvoyait tout le monde sur download.opensuse.org, servi d'Europe.
    # Ordonnées par proximité de Montréal. Aucun sondage concluant : on garde
    # les dépôts de l'image, donc le comportement d'avant.
    _QEMU_ZYPPER_MIRRORS = (
        "https://mirror.csclub.uwaterloo.ca/opensuse",
        "https://mirrors.rit.edu/opensuse",
        "https://mirror.us.leaseweb.net/opensuse",
    )

    # Miroirs Arch canadiens, du plus rapide au suivant. Mesuré depuis
    # Montréal sur extra.db : quantum5 2,0 s, xenyth 7,1 s, contre 8,0 s pour
    # geo.mirror.pkgbuild.com — le miroir « géographique » officiel n'est donc
    # pas le meilleur ici. Arch n'est proposé qu'en amd64 dans le catalogue,
    # et ces deux-là ne servent que x86_64 (Arch Linux ARM a ses propres
    # miroirs) : la garde d'architecture le dit quand même.
    _QEMU_PACMAN_MIRRORS = (
        "https://mirror.quantum5.ca/archlinux/$repo/os/$arch",
        "https://mirror.xenyth.net/archlinux/$repo/os/$arch",
    )

    def _qemu_pacman_mirror_cmd(self):
        """Place les miroirs canadiens EN TÊTE de la mirrorlist.

        reflector écrase le fichier avec « --save » : il faut donc écrire
        après lui, pas avant. Ses miroirs restent dessous, comme repli."""
        # « \\n » et non un vrai saut de ligne : la commande distante est UNE
        # chaîne, passée à bash -c après shlex.quote. Un retour littéral y
        # survivrait, mais rendrait la chaîne illisible et fragile à relire.
        # « $repo » et « $arch » restent littéraux : c'est pacman qui les
        # substitue, d'où les guillemets SIMPLES autour du format.
        lines = "".join(f"Server = {m}\\n" for m in self._QEMU_PACMAN_MIRRORS)
        first = self._QEMU_PACMAN_MIRRORS[0].split("/")[2]
        return (
            '[ "$(uname -m)" = x86_64 ] && { '
            # Idempotent : la préparation Arch passe deux fois quand une VM
            # est graphique (bureau puis ERPLibre), et empiler les mêmes
            # miroirs à chaque passage allongerait la liste sans rien gagner.
            f'grep -q "{first}" /etc/pacman.d/mirrorlist 2>/dev/null || {{ '
            f"printf '{lines}' | sudo tee /etc/pacman.d/mirrorlist.el "
            "> /dev/null; "
            "sudo sh -c 'cat /etc/pacman.d/mirrorlist "
            ">> /etc/pacman.d/mirrorlist.el "
            "&& mv /etc/pacman.d/mirrorlist.el /etc/pacman.d/mirrorlist'; "
            "}; }; "
        )

    def _qemu_pacman_prepare_cmd(self):
        """Préparation Arch : verrou, miroirs proches, mise à jour COMPLÈTE.

        Les trois sont indissociables, et il faut les faire AVANT la moindre
        installation. Une image cloud Arch est un instantané dont la base de
        paquets pointe des versions déjà retirées des miroirs : « pacman -S »
        s'y arrête sur « failed retrieving file … 404 » — vécu sur llvm-libs
        et perl. Arch ne supporte pas la mise à jour partielle.

        Ce bloc ne vivait QUE dans le chemin ERPLibre. Or le bureau s'installe
        AVANT lui : une VM graphique échouait donc toujours, sans jamais
        atteindre le code qui l'aurait sauvée."""
        return (
            "if command -v pacman >/dev/null 2>&1; then "
            # Verrou périmé (cloud-init interrompu) : le retirer SEULEMENT si
            # aucun pacman ne tourne, sinon on attend qu'il se libère.
            "pgrep -x pacman >/dev/null 2>&1 "
            "|| sudo rm -f /var/lib/pacman/db.lck; "
            # reflector d'abord, nos miroirs ensuite : « --save » écrase le
            # fichier, écrire avant lui ne servirait à rien.
            "sudo pacman -Sy --needed --noconfirm reflector || true; "
            "sudo reflector --latest 20 --protocol https --sort rate "
            "--save /etc/pacman.d/mirrorlist || true; "
            + self._qemu_pacman_mirror_cmd()
            + "sudo pacman -Syu --noconfirm || true; "
            "fi; "
        )

    @staticmethod
    def _qemu_yay_install_cmd():
        """Pose yay, l'assistant AUR, sur un invité Arch.

        « yay-bin » et non « yay » : le paquet source compile son propre Go,
        ce qui coûte plusieurs minutes et le compilateur avec ; le binaire
        précompilé donne le même outil.

        makepkg REFUSE de tourner en root et sort en erreur ; le clonage et la
        construction restent donc sous l'utilisateur de la VM, qui appelle
        sudo pour la seule installation finale. Le NOPASSWD posé par
        cloud-init rend ce sudo silencieux.

        yay est un bonus, pas une condition : le bloc se termine par « true »
        pour qu'un AUR injoignable ne fasse pas échouer, sous « set -e », une
        installation par ailleurs complète.
        """
        return (
            "command -v yay >/dev/null 2>&1 || { "
            "sudo pacman -S --needed --noconfirm base-devel git && "
            "yd=$(mktemp -d) && "
            "git clone --depth 1 https://aur.archlinux.org/yay-bin.git "
            '"$yd" && ( cd "$yd" && makepkg -si --noconfirm ); '
            # « rm -rf » sur une variable vide rend 0 en silence sous -f : le
            # nettoyage n'a donc pas besoin de savoir si le clonage a eu lieu.
            'rm -rf "$yd"; '
            # « || true » ferme le groupe ENTIER, et il porte. Le groupe est
            # le DERNIER membre de la liste « || », donc set -e s'y applique
            # et le premier sudo en échec emporterait toute l'installation.
            # Un membre de plus l'y suspend, et rend le bloc inoffensif.
            "} || true; "
            "command -v yay >/dev/null 2>&1 "
            '&& echo "   yay installé" || echo "   ⚠ yay non installé"; '
        )

    def _qemu_zypper_mirror_cmd(self):
        """Réécrit l'hôte des dépôts zypper vers un miroir plus proche."""
        mirrors = " ".join(self._QEMU_ZYPPER_MIRRORS)
        # Leap et Tumbleweed n'ont pas le même arbre de dépôts : la rolling
        # isole les architectures secondaires sous /ports/, Leap 16 unifie tout
        # et garde s390x dans l'arbre principal (les /ports/ y rendent 404).
        return (
            ". /etc/os-release; "
            'case "$ID" in *tumbleweed*) zp=tumbleweed; '
            '[ "$(uname -m)" = s390x ] && zp=ports/zsystems/tumbleweed;; '
            '*) zp="distribution/leap/$VERSION_ID";; esac; '
            f"for zm in {mirrors}; do "
            "if curl -fsS --max-time 20 -o /dev/null "
            '"$zm/$zp/repo/oss/repodata/repomd.xml"; then '
            "sudo sed -i "
            '"s|https\\?://download\\.opensuse\\.org|$zm|g" '
            "/etc/zypp/repos.d/*.repo 2>/dev/null || true; "
            f'echo "   {t("openSUSE mirror:")} $zm"; break; fi; done; '
        )

    @staticmethod
    def _qemu_tunnel_hint(port, kind):
        """Deux lignes imprimees DANS la VM : le tunnel a monter depuis le
        poste de travail, avec l'adresse deja remplie.

        Un port annonce sans chemin pour y arriver n'aide personne : le reseau
        libvirt n'est pas route depuis l'exterieur de son hote."""
        local = port + 1
        return (
            "ip=$(hostname -I 2>/dev/null | awk '{print $1}'); "
            f'echo "     {t("From your workstation:")} '
            f'ssh -L {local}:$ip:{port} <user>@<hote-libvirt>"; '
            f'echo "     {t("then point your client at")} '
            f'localhost:{local}  ({kind})"; '
        )

    def _qemu_desktop_remote_cmd(self, flavour="gnome", app_store="deb"):
        """Bloc shell installant le bureau choisi + son accès distant, quelle
        que soit la distribution. Même aiguillage que l'installation ERPLibre,
        et même traitement du verrou apt : cette étape passe par la commande
        distante et non par cloud-init, où ses 1 à 2 Go allongeraient un
        démarrage déjà long sans laisser la moindre trace dans le suivi."""
        de = self._QEMU_DESKTOP.get(flavour) or self._QEMU_DESKTOP["gnome"]
        rem = self._QEMU_DESKTOP_REMOTE
        label = de["label"]
        return (
            f'echo "== {t("Installing the desktop (long):")} {label} =="; '
            "if command -v apt-get >/dev/null 2>&1; then "
            "n=0; until sudo apt-get -o DPkg::Lock::Timeout=120 update -qq; do "
            "n=$((n+1)); [ $n -ge 30 ] && break; sleep 10; done; "
            "sudo DEBIAN_FRONTEND=noninteractive "
            "apt-get -o DPkg::Lock::Timeout=600 install -y "
            f"{de['apt']} {rem['apt']['packages']} "
            f"{self._qemu_apt_store_pkgs(app_store)}; "
            "elif command -v dnf >/dev/null 2>&1; then "
            # Cascade d'environnements : le premier qui existe gagne. Un
            # environnement absent fait rendre 1 à dnf sans rien installer,
            # d'où le « || » plutôt qu'une détection préalable.
            "de_ok=0; "
            f"for e in {de['dnf_env']}; do "
            'sudo dnf -y group install "$e" && { de_ok=1; break; }; done; '
            '[ "$de_ok" = 1 ] || echo "Aucun environnement graphique dnf '
            "trouve pour " + label + '"; '
            f"sudo dnf install -y {rem['dnf']['packages']}; "
            "elif command -v pacman >/dev/null 2>&1; then "
            "pgrep -x pacman >/dev/null 2>&1 "
            "|| sudo rm -f /var/lib/pacman/db.lck; "
            + self._qemu_pacman_prepare_cmd()
            + f"sudo pacman -S --needed --noconfirm {de['pacman']} "
            f"{rem['pacman']['packages']}; "
            "elif command -v zypper >/dev/null 2>&1; then "
            "sudo zypper --non-interactive refresh || true; "
            # « --auto-agree-with-licenses » appartient à la SOUS-COMMANDE
            # install, pas aux options globales : placé avant, zypper répond
            # « The flag --auto-agree-with-licenses is not known ».
            "sudo zypper --non-interactive install "
            f"--auto-agree-with-licenses {de['zypper']} "
            f"{rem['zypper']['packages']}; "
            "else echo 'Gestionnaire de paquets inconnu'; exit 1; fi; "
            # Le bureau ne sert à rien s'il ne démarre pas tout seul : les
            # images cloud démarrent en multi-user.target.
            "sudo systemctl set-default graphical.target || true; "
            f"sudo systemctl enable {de['service']} >/dev/null 2>&1 || true; "
            # Et il faut le DÉMARRER, pas seulement l'activer. Deux raisons,
            # toutes deux mesurées sur erplibre-ubuntu-2604-gnome :
            #
            #   - graphical.target était DÉJÀ atteinte quand le paquet est
            #     arrivé, et une cible active ne rattrape pas un service ajouté
            #     après coup : display-manager.service est resté inactif ;
            #   - sur Debian et Ubuntu, « systemctl enable gdm » rend 0 sans
            #     rien faire — l'unité n'a pas de « WantedBy », seulement
            #     « Alias=display-manager.service » que le paquet a déjà posé.
            #
            # Résultat : GNOME installé, gdm3 installé, cible graphique par
            # défaut… et la console de la VM restait en mode texte jusqu'au
            # premier redémarrage. L'écran, c'est justement ce qu'on est venu
            # chercher sur une VM graphique.
            "if sudo systemctl start display-manager.service 2>/dev/null || "
            f"sudo systemctl start {de['service']} 2>/dev/null; then "
            f'echo "   {t("graphical session started")}"; '
            f'else echo "   ⚠ {t("graphical session not started; reboot the VM")}"; '
            "fi; "
            # xrdp là où il existe ; sur Arch c'est TigerVNC, qui se configure
            # par utilisateur et n'a pas de service à activer d'office.
            "if command -v xrdp >/dev/null 2>&1; then "
            "sudo systemctl enable --now xrdp >/dev/null 2>&1 || true; "
            f'echo "   {t("Remote desktop:")} RDP 3389"; '
            # L'IP est sur le reseau PRIVE de libvirt : annoncer le port sans
            # dire comment l'atteindre ne sert a rien. La VM connait sa propre
            # adresse ; seul le nom de l'hote libvirt manque, et c'est le
            # lecteur qui l'a. La console SPICE, elle, est en « listen=none »
            # et suppose virt-viewer SUR l'hote — inutilisable quand cet hote
            # est lui-meme une VM sans interface graphique.
            + self._qemu_tunnel_hint(3389, "RDP")
            + "elif command -v vncserver >/dev/null 2>&1; then "
            f'echo "   {t("Remote desktop:")} VNC 5901 '
            '(vncpasswd puis vncserver :1)"; '
            + self._qemu_tunnel_hint(5901, "VNC")
            + "fi; "
        )

    # ------------------------------------------------------------------ #
    # Outils de développement d'une VM graphique
    # ------------------------------------------------------------------ #
    # Chacun est une case à cocher, indépendante des autres, et chacun pèse sur
    # le disque — le plan l'annonce AVANT de déployer, sinon l'installation se
    # termine sur un disque plein après une heure d'attente.
    #
    # « disk_gb » compte le PIC, pas l'installé : l'archive téléchargée vit sur
    # le disque le temps de l'extraction. PyCharm, c'est 1,2 Go d'archive et
    # ~3 Go déplié ; Android Studio 1,5 Go et 3,5 Go, plus la place du premier
    # SDK que l'utilisateur téléchargera.
    #
    # « arches » n'est pas une précaution : Google ne publie Android Studio
    # QU'EN x86_64 (vérifié — toutes les variantes aarch64 de l'URL rendent 404,
    # et le product-info.json de l'archive ne déclare qu'une cible
    # « Linux/amd64 »). JetBrains, lui, publie bien une archive aarch64.
    _QEMU_VM_TOOLS = {
        "pycharm": {
            "label": "PyCharm",
            "hint": "Python IDE, opens the ERPLibre checkout",
            "disk_gb": 5,
            "arches": ("amd64", "arm64"),
            "desktops": (),
            "needs_desktop": True,
            "families": (),
            "phase": "before",
        },
        "android": {
            "label": "Android Studio",
            "hint": "ERPLibre mobile development (x86_64 only)",
            "disk_gb": 8,
            "arches": ("amd64",),
            "desktops": (),
            "needs_desktop": True,
            "families": (),
            "phase": "before",
        },
        "gnome_ext": {
            "label": "GNOME extensions",
            "hint": "suggested extensions + extension manager",
            "disk_gb": 1,
            "arches": (),
            "desktops": ("gnome",),
            "needs_desktop": True,
            "families": (),
            "phase": "before",
        },
        # Le seul outil qui ne demande PAS de bureau : il compile, il n'affiche
        # rien. Une VM serveur le prend, une VM graphique aussi — et sur
        # celle-ci le SDK est partagé avec Android Studio plutôt que doublé.
        #
        # « families » le borne à apt, et ce n'est pas un choix : l'installateur
        # du dépôt mobile, install-android.sh, commence par
        # « sudo apt install openjdk-17-jdk ». Ailleurs il s'arrête là. Lever
        # cette limite se fait dans CE script-là, pas ici.
        #
        # Disque : ~1,5 Go de SDK et plateformes, ~2,5 Go de NDK, whisper.cpp
        # et sentencepiece clonés, node_modules, et les artefacts Gradle.
        "mobile": {
            "label": "ERPLibre mobile (build)",
            "hint": "APK debug + Vitest, validates the VM",
            "disk_gb": 12,
            "arches": ("amd64",),
            "desktops": (),
            "needs_desktop": False,
            "families": ("apt",),
            # APRÈS l'installation : le build a besoin du dépôt mobile, que le
            # manifeste ajoute, et du venv d'outils pour le synchroniser.
            "phase": "after",
        },
        # Forgejo est un SERVICE, pas un outil de bureau : une VM serveur le
        # prend aussi bien qu'une VM graphique. Son binaire est STATIQUE — le
        # même fichier sur apt, dnf, pacman et zypper — donc aucune famille de
        # paquets n'est exclue, et c'est ce qui le rend portable sur toutes les
        # plateformes ERPLibre sans une branche par distribution.
        #
        # Les architectures, elles, sont bornées par l'amont : Forgejo publie
        # amd64, arm64 et arm-6, et RIEN pour s390x. Sur celle-là il faudrait le
        # bâtir en Go ; la case se grise plutôt que de poser un binaire qui ne
        # s'exécute pas.
        #
        # Disque : ~115 Mo de binaire (34 Mo téléchargés en .xz), la base SQLite
        # et les dépôts que l'utilisateur y poussera.
        "forgejo": {
            "label": "Forgejo (git forge)",
            "hint": "self-hosted git forge on :3000, SQLite",
            "disk_gb": 2,
            "arches": ("amd64", "arm64"),
            "desktops": (),
            "needs_desktop": False,
            "families": (),
            # APRÈS l'installation : le script vit dans le dépôt, donc après le
            # clone. Rien d'autre ne l'y oblige — Forgejo ne dépend ni du venv
            # ni d'Odoo.
            "phase": "after",
        },
        # L'émulateur n'a pas besoin de bureau DANS la VM : il s'affiche sur
        # l'écran de qui s'y connecte, par « ssh -X ». Il a besoin, lui, de KVM
        # dans la VM — donc de virtualisation imbriquée sur l'hôte, ce que le
        # bloc vérifie et annonce plutôt que de laisser découvrir.
        #
        # Disque : ~1,5 Go d'image système, ~2 Go de données d'AVD, plus
        # l'émulateur lui-même.
        # Ni bureau ni famille de paquets : les quatre outils sont des
        # installateurs amont, aucun n'est dans les dépôts des distributions
        # supportées. Une VM serveur les prend donc aussi bien qu'une VM
        # graphique — c'est en SSH qu'on s'en sert.
        #
        # Disque : les binaires sont petits (rtk et starship sont statiques,
        # l'agent est un bundle node) ; la marge couvre leurs caches.
        "aidev": {
            "label": "AI coding tools",
            "hint": "rtk, starship, and one agent",
            "disk_gb": 2,
            "arches": (),
            "desktops": (),
            "needs_desktop": False,
            "families": (),
            # AVANT le clone : chaque outil s'y garde lui-même, et aucun ne
            # doit faire échouer l'installation d'ERPLibre pour un curl qui
            # ne répond pas.
            "phase": "before",
        },
        "avd": {
            "label": "Android emulator (Pixel)",
            "hint": "AVD viewable over ssh -X",
            "disk_gb": 6,
            "arches": ("amd64",),
            "desktops": (),
            "needs_desktop": False,
            "families": ("apt",),
            "phase": "after",
        },
    }

    # Famille de paquets de chaque distribution, pour borner un outil à ce qui
    # sait l'installer.
    _QEMU_DISTRO_FAMILY = {
        "ubuntu": "apt",
        "debian": "apt",
        "fedora": "dnf",
        "almalinux": "dnf",
        "rocky": "dnf",
        "opensuse": "zypper",
        "arch": "pacman",
    }

    def _qemu_guest_context(self):
        """Ce que les DEUX écrans de déploiement doivent savoir du système
        invité : type de VM, magasin d'applications, outils, fuseaux, Python.

        Une seule méthode et non deux blocs jumeaux dans les constructeurs de
        contexte : c'est en n'en remplissant qu'un que l'écran Proxmox avait
        perdu la moitié des réglages. Rien ici ne parle d'hyperviseur — c'est
        exactement ce qui rend le bloc commun."""
        outils = self._QEMU_VM_TOOLS
        return {
            "desktops": [
                (k, v["label"]) for k, v in self._QEMU_DESKTOP.items()
            ],
            "desktop_suffixes": self._qemu_desktop_suffixes(),
            "desktop_disk_gb": self.QEMU_DESKTOP_EXTRA_DISK_GB,
            "app_stores": [(k, t(lbl)) for k, lbl in self.QEMU_APP_STORES],
            "snap_distros": self.QEMU_SNAP_DISTROS,
            "timezone": self._qemu_host_timezone(),
            "timezones": self._qemu_timezone_choices(
                self._qemu_host_timezone()
            ),
            "mise_arches": self.QEMU_MISE_ARCHES,
            "vm_tools": self._qemu_vm_tool_choices(),
            "vm_tool_disk": {k: v["disk_gb"] for k, v in outils.items()},
            "vm_tool_arches": {k: v["arches"] for k, v in outils.items()},
            "vm_tool_desktops": {k: v["desktops"] for k, v in outils.items()},
            # « after » = l'outil vit DANS le dépôt ERPLibre (compilation
            # mobile, AVD, script Forgejo) : sans installation, il n'existe
            # pas, et la commande distante le saute en le nommant.
            "vm_tool_phases": {
                k: v.get("phase", "before") for k, v in outils.items()
            },
            "vm_tool_needs_desktop": {
                k: v["needs_desktop"] for k, v in outils.items()
            },
            "vm_tool_families": {k: v["families"] for k, v in outils.items()},
            "distro_family": dict(self._QEMU_DISTRO_FAMILY),
            "defaults": {
                "install": True,
                "add_ssh_config": True,
                "monitor": True,
                "prod": False,
                # L'identité git que la VM reçoit AUJOURD'HUI, celle de
                # l'hôte : les champs la montrent plutôt que de s'ouvrir
                # vides, ce qui la ferait croire absente. Les laisser vides
                # garde ce comportement, les modifier le remplace.
                "ai_agent": dev_tools.AGENT_DEFAUT,
                "git_name": self._qemu_host_git("user.name"),
                "git_email": self._qemu_host_git("user.email"),
            },
        }

    def _qemu_host_git(self, cle):
        """Valeur globale « git config » de l'hôte, ou ''.

        Passe par deploy_qemu, seule autorité sur cette lecture : git accepte
        DEUX emplacements pour sa configuration globale et le script sait
        lequel interroger. Sans module importable on ne devine pas — un champ
        vide reprend l'identité de l'hôte au déploiement, ce qui est déjà le
        comportement par défaut.
        """
        try:
            mod = self._qemu_import_module()
            return mod._git_global(cle, mod.invoking_home()) or ""
        except Exception:
            return ""

    @classmethod
    def _qemu_vm_tool_choices(cls):
        """[(clé, libellé, indice)] pour le formulaire et l'invite en ligne."""
        return [
            (key, t(spec["label"]), t(spec["hint"]))
            for key, spec in cls._QEMU_VM_TOOLS.items()
        ]

    @classmethod
    def _qemu_tools_for(cls, tools, arch, desktop, distro="", phase=""):
        """Outils RÉELLEMENT applicables à cette VM.

        Un outil demandé pour tout le parc ne convient pas forcément à chaque
        machine : Android Studio n'existe qu'en x86_64, les extensions GNOME
        n'ont pas de sens sous Cinnamon, et la compilation mobile ne sait
        s'installer que sur les distributions apt. Filtrer ici plutôt que dans
        la commande distante évite d'annoncer une installation qui ne se fera
        pas.

        `phase` restreint au moment d'exécution : « before » avant le clone,
        « after » après l'installation. Vide, les deux sont rendus."""
        out = []
        for key in tools or ():
            spec = cls._QEMU_VM_TOOLS.get(key)
            if not spec:
                continue
            if spec["needs_desktop"] and not desktop:
                continue
            if spec["arches"] and arch not in spec["arches"]:
                continue
            if spec["desktops"] and desktop not in spec["desktops"]:
                continue
            family = cls._QEMU_DISTRO_FAMILY.get(distro, "")
            if spec["families"] and distro and family not in spec["families"]:
                continue
            if phase and spec["phase"] != phase:
                continue
            out.append(key)
        return out

    @classmethod
    def _qemu_tools_disk_gb(cls, tools, arch, desktop, distro=""):
        """Go à ajouter au disque pour les outils applicables à cette VM."""
        return sum(
            cls._QEMU_VM_TOOLS[k]["disk_gb"]
            for k in cls._qemu_tools_for(tools, arch, desktop, distro)
        )

    # Archive officielle JetBrains, et non un paquet de distribution : aucun ne
    # couvre les quatre gestionnaires (Arch l'a dans extra, Debian et Ubuntu ne
    # l'ont qu'en snap — coupé ici —, Fedora et openSUSE pas du tout).
    #
    # La ligne COMMUNITY, et non le produit unifié. Mesuré dans une VM :
    # « code=PCC&latest » sert maintenant pycharm-2025.3, le build unifié, qui
    # s'arrête sur sa licence — son journal dit « NoValidIdeLicense » puis
    # « Get licenses: request requires authentication », et le projet ne
    # s'ouvre jamais. Aucune ouverture, donc aucun .idea, donc rien à
    # configurer ensuite. Community ne demande aucun compte, et elle est
    # toujours publiée et corrigée : 2025.2.6.2 date du 2026-07-29.
    #
    # Aucun numéro figé ici : on prend la plus récente archive
    # « pycharm-community- » du flux officiel des versions, pour
    # l'architecture de la VM.
    _QEMU_PYCHARM_FEED = (
        "https://data.services.jetbrains.com/products/releases"
        "?code=PCC&type=release"
    )

    # Repli quand le flux est injoignable : la redirection « dernière version ».
    # Elle sert le build unifié, donc on le DIT — l'utilisateur devra ouvrir un
    # compte JetBrains, et mieux vaut l'apprendre dans le journal qu'au premier
    # lancement.
    _QEMU_PYCHARM_URL = (
        "https://download.jetbrains.com/product?code=PCC&latest&distribution="
    )

    # Android Studio n'a PAS d'URL « latest » : le répertoire de version
    # (2026.1.3.8) et le nom de fichier (quail3-patch1) sont deux jetons
    # INDÉPENDANTS, l'un ne se déduit pas de l'autre, et le flux updates.xml de
    # Google ne publie ni l'un ni l'autre. On lit donc l'URL sur la page
    # officielle, qui la porte en clair, et on retombe sur celle-ci si la page
    # change de forme. Relevée et vérifiée (HTTP 200) le 2026-08-17.
    _QEMU_ANDROID_URL = (
        "https://dl.google.com/dl/android/studio/ide-zips/2026.1.3.8/"
        "android-studio-quail3-patch1-linux.tar.gz"
    )

    _QEMU_ANDROID_PAGE = "https://developer.android.com/studio"

    @staticmethod
    def _qemu_desktop_entry_cmd(name, label, exec_cmd, icon, categories):
        """Écrit un lanceur .desktop. Sans lui, un outil déplié dans /opt
        n'existe pas pour le bureau : il ne se lance qu'en tapant son chemin.
        """
        return (
            f"sudo tee /usr/share/applications/{name}.desktop >/dev/null <<DESK\n"
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Version=1.0\n"
            f"Name={label}\n"
            f"Exec={exec_cmd}\n"
            f"Icon={icon}\n"
            "Terminal=false\n"
            f"Categories={categories}\n"
            "StartupNotify=true\n"
            "DESK\n"
        )

    def _qemu_jetbrains_launcher_cmd(self, root, link, alias=""):
        """Lien vers le lanceur de l'archive, quel que soit son nom.

        JetBrains a renommé « bin/pycharm.sh » en « bin/pycharm » (et
        « studio.sh » en « studio ») : les deux existent selon la version, on
        prend celui qui est là.

        `alias` : un second nom pour la même commande. L'archive d'Android
        Studio n'installe que « studio », mais personne ne tape « studio » —
        on cherche « android-studio », on ne trouve rien, et on conclut que
        l'installation a échoué alors qu'elle est bien là. Vécu."""
        return (
            f"b=$(ls {root}/bin/{link}.sh {root}/bin/{link} 2>/dev/null "
            "| head -1); "
            f'[ -n "$b" ] && sudo ln -sf "$b" /usr/local/bin/{link}; '
            + (
                f'[ -n "$b" ] && sudo ln -sf "$b" /usr/local/bin/{alias}; '
                if alias
                else ""
            )
        )

    def _qemu_pycharm_remote_cmd(self, prod=False):
        """Installe PyCharm et lui donne le dépôt ERPLibre comme projet.

        « Configuré sur git/erplibre » veut dire deux choses, et les deux sont
        faites ici : le lanceur du bureau OUVRE ce dépôt, et
        pycharm_configuration.py y écrit le .idea/ du projet (interpréteur,
        configurations d'exécution, dossiers exclus) — la même chose que
        « make pycharm_configure », mais avec le python du venv d'outils, seul à
        disposer de xmltodict.

        Tout le bloc est gardé : un IDE qui ne s'installe pas ne doit pas faire
        échouer l'installation d'ERPLibre, qui elle a duré une heure."""
        el_dir = self._qemu_install_dir(prod)
        return (
            f'echo "== {t("Installing PyCharm (long)")} =="; '
            "{ "
            'case "$(uname -m)" in x86_64) jb=linux;; '
            'aarch64|arm64) jb=linuxARM64;; *) jb="";; esac; '
            # if/else et non « || { …; false; } » : dans un groupe, un échec
            # n'interrompt PAS la suite (set -e est suspendu à gauche d'un
            # « && »), et l'architecture non servie partait quand même
            # télécharger une URL sans valeur de distribution.
            'if [ -z "$jb" ]; then '
            f'echo "   {t("no JetBrains build for")} $(uname -m)"; false; '
            "else "
            # Déjà posé ? On ne retélécharge pas. Rejouer une
            # installation est le cas NORMAL — une qui est morte, un outil
            # ajouté après coup — et le téléchargement en est la partie
            # longue : mesuré, ~5 min pour Android Studio, autant pour
            # PyCharm. Le reste de l'étape (lanceur, alias, raccourci)
            # rejoue de toute façon, lui est idempotent et bon marché.
            "if [ -x /opt/pycharm/bin/pycharm.sh ]; then "
            f'echo "   {t("already there, download skipped")}"; '
            "else "
            # /var/tmp et non /tmp : sur Fedora et dérivés /tmp est un tmpfs, en
            # RAM — 1,2 Go d'archive y tueraient une VM de 3 Go.
            # Le flux dit quelle archive Community prendre pour cette
            # architecture. En python plutôt qu'en shell : il fait la requête,
            # lit le JSON et rend une ligne — sans jq, absent des images cloud.
            "url=$(python3 - \"$jb\" <<'ELPYJB'\n"
            "import json, sys, urllib.request\n"
            "key = sys.argv[1]\n"
            "try:\n"
            f'    with urllib.request.urlopen("{self._QEMU_PYCHARM_FEED}",\n'
            "                                 timeout=30) as fh:\n"
            "        data = json.load(fh)\n"
            "except Exception:\n"
            "    sys.exit(0)\n"
            'for rel in data.get("PCC", []):\n'
            '    link = (rel.get("downloads") or {}).get(key, {}).get("link", "")\n'
            '    if "pycharm-community-" in link:\n'
            "        print(link)\n"
            "        break\n"
            "ELPYJB\n"
            "); "
            'if [ -z "$url" ]; then '
            f'url="{self._QEMU_PYCHARM_URL}$jb"; '
            f'echo "   {t("release feed unreachable: unified build, it will ask for a JetBrains account")}"; '
            "fi; "
            "tmp=$(mktemp -p /var/tmp pycharm-XXXX.tar.gz) && "
            'curl -fsSL "$url" -o "$tmp" && '
            "sudo mkdir -p /opt/pycharm && "
            'sudo tar -xzf "$tmp" -C /opt/pycharm --strip-components=1; '
            'rc=$?; rm -f "$tmp"; [ $rc -eq 0 ]; fi; fi; } && { '
            + self._qemu_jetbrains_launcher_cmd("/opt/pycharm", "pycharm")
            + self._qemu_desktop_entry_cmd(
                "pycharm",
                "PyCharm (ERPLibre)",
                f"/usr/local/bin/pycharm {el_dir}",
                "/opt/pycharm/bin/pycharm.svg",
                "Development;IDE;",
            )
            # AUCUN appel à pycharm_configuration.py ici : l'installation
            # ERPLibre le fait déjà. update_env_version.pycharm_update() teste
            # « os.path.exists('.idea') » puis lance le script — une seule
            # autorité, et elle sait se taire quand le projet n'existe pas
            # encore. Doubler l'appel ne configurait rien de plus : ça écrivait
            # « Missing ./.idea path » dans le journal d'une VM neuve, où
            # PyCharm n'a évidemment jamais ouvert le dépôt.
            + f'echo "   {t("PyCharm installed:")} /opt/pycharm '
            f'({t("command")} pycharm, {t("project")} {el_dir})"; '
            f'echo "   {t("open the project once and close PyCharm; the .idea "
                          "it writes is what the install configures")}"; '
            f'}} || echo "   ⚠ {t("PyCharm not installed (see above)")}"; '
        )

    # Serveur X virtuel, par gestionnaire de paquets. Les noms ne se
    # ressemblent pas d'une famille à l'autre — relevés dans chaque dépôt, pas
    # devinés.
    _QEMU_XVFB_PKG = {
        "apt": "xvfb",
        "dnf": "xorg-x11-server-Xvfb",
        "zypper": "xorg-x11-server-Xvfb",
        "pacman": "xorg-server-xvfb",
    }

    # Attente maximale du .idea, en tours de 5 s — cinq minutes. Mesuré sur une
    # VM Ubuntu 26.04 à 16 Go : le projet est écrit en 195 s, indexation du
    # dépôt en cours. On n'attend donc PAS la fin de cette indexation, qui dure
    # bien plus et dont personne n'a besoin ici : pycharm_configuration.py ne
    # réclame que le .iml et misc.xml.
    _QEMU_PYCHARM_OPEN_TRIES = 60

    def _qemu_xvfb_install_cmd(self):
        """Pose Xvfb avec le gestionnaire de paquets présent, sans bruit."""
        x = self._QEMU_XVFB_PKG
        return (
            "if command -v apt-get >/dev/null 2>&1; then "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get "
            f"-o DPkg::Lock::Timeout=600 install -y {x['apt']} "
            ">/dev/null 2>&1 || true; "
            "elif command -v dnf >/dev/null 2>&1; then "
            f"sudo dnf install -y {x['dnf']} >/dev/null 2>&1 || true; "
            "elif command -v zypper >/dev/null 2>&1; then "
            "sudo zypper --non-interactive install --auto-agree-with-licenses "
            f"{x['zypper']} >/dev/null 2>&1 || true; "
            "elif command -v pacman >/dev/null 2>&1; then "
            f"sudo pacman -S --needed --noconfirm {x['pacman']} "
            ">/dev/null 2>&1 || true; fi; "
        )

    def _qemu_pycharm_project_cmd(self, prod=False):
        """Crée le .idea/ du dépôt en ouvrant PyCharm une fois, sans écran.

        C'est PyCharm, et lui seul, qui écrit ce répertoire : ni le dépôt ni
        pycharm_configuration.py ne savent le fabriquer — ce dernier exige un
        .iml puis un misc.xml, et s'arrête sinon. Sans cette ouverture, l'étape
        pycharm_update() de l'installation ne trouve rien à configurer.

        Xvfb parce que l'IDE réclame un affichage, même pour ouvrir un projet
        et s'arrêter. Il tourne DANS la VM : l'hôte qui orchestre n'a besoin
        d'aucune bibliothèque graphique, et rien ne transite par « ssh -X ».

        TROIS fenêtres bloqueraient une session où personne ne peut cliquer, et
        chacune a été rencontrée avant d'être écartée : politique de
        confidentialité, partage de données, et surtout « faites-vous confiance
        à ce projet ? ». C'est celle-là qui figeait tout — le journal s'arrêtait
        1,3 s après le démarrage, sans jamais ouvrir le projet, et il a fallu
        « idea.trust.all.projects » pour le débloquer. Le consentement, lui, est
        écrit REFUSÉ : aucune statistique ne part.

        Mesuré sur une VM Ubuntu 26.04 à 16 Go : .idea complet en 195 s, et
        pycharm_configuration.py écrit ensuite ses exclusions dans le .iml.

        Tout est gardé. Sans Xvfb, sans PyCharm, ou sans .idea au bout du
        délai, on le dit et l'installation continue : elle n'en dépend pas,
        elle en profite seulement.
        """
        el_dir = self._qemu_install_dir(prod)
        return (
            f'echo "== {t("Creating the PyCharm project (first open)")} =="; '
            "{ if ! command -v pycharm >/dev/null 2>&1; then "
            f'echo "   {t("PyCharm missing, step skipped")}"; false; '
            "else "
            "command -v xvfb-run >/dev/null 2>&1 || { "
            + self._qemu_xvfb_install_cmd()
            + "}; "
            "if ! command -v xvfb-run >/dev/null 2>&1; then "
            f'echo "   {t("no Xvfb here, open PyCharm by hand")}"; false; '
            "else "
            # Réponses aux fenêtres de première ouverture. En python plutôt
            # qu'en shell : l'horodatage en millisecondes et le « <!--…--> » de
            # la propriété se passeraient mal de guillemets imbriqués.
            "python3 - <<'ELPYC' || true\n"
            "import pathlib, time\n"
            "h = pathlib.Path.home()\n"
            'c = h / ".local/share/JetBrains/consentOptions"\n'
            "c.mkdir(parents=True, exist_ok=True)\n"
            '(c / "accepted").write_text(\n'
            '    "rsch.send.usage.stat:1.1:0:%d\\n" % (time.time() * 1000)\n'
            ")\n"
            '(h / ".pycharm-headless.vmoptions").write_text(\n'
            '    "-Djb.privacy.policy.text=<!--999.999-->\\n"\n'
            '    "-Djb.consents.confirmation.enabled=false\\n"\n'
            '    "-Didea.trust.all.projects=true\\n"\n'
            '    "-Didea.suppress.statistics.report=true\\n"\n'
            ")\n"
            "ELPYC\n"
            # « setsid » donne au tout son PROPRE groupe de processus, et
            # c'est le groupe qu'on tuera. Sans lui, « $!  » est le PID de
            # xvfb-run — un script — et le tuer n'atteint ni PyCharm, ni Xvfb,
            # ni les cef_server qu'il a lancés. Mesuré sur
            # erplibre-ubuntu-2604-gnome : PyCharm tournait encore 45 minutes
            # plus tard avec 1,9 Go, et la compilation de l'APK qui suivait
            # s'est fait tuer par le noyau, faute de mémoire.
            # Les watches inotify AVANT d'ouvrir : le dépôt mobile pose
            # 123 000 fichiers d'assets, et la limite par défaut est dépassée
            # dès l'analyse — « inotify_add_watch(...): No space left on
            # device », puis « watch root cannot be watched: -2 », puis aucun
            # .idea écrit. Mesuré sur erplibre-ubuntu-2604-gnome, deux fois.
            # 524288 est la valeur que JetBrains documente lui-même.
            "cur=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null "
            '|| echo 0); if [ "$cur" -lt 524288 ] 2>/dev/null; then '
            'echo "fs.inotify.max_user_watches=524288" '
            "| sudo tee /etc/sysctl.d/60-erplibre-inotify.conf >/dev/null && "
            "sudo sysctl -q -p /etc/sysctl.d/60-erplibre-inotify.conf "
            f'2>/dev/null; echo "   {t("inotify watches raised for the IDE")}"; '
            "fi; "
            # DEUX tentatives, et c'est mesuré : la première ouverture d'un
            # dépôt neuf indexe 212 000 fichiers, plante son configurateur
            # d'interpréteur (« PythonSdkConfigurator - homeDir is null ») et
            # n'écrit AUCUN .idea, même au bout de cinq minutes. La seconde, sur
            # les caches que la première a laissés, l'écrit en 25 secondes —
            # constaté sur deux VM différentes.
            ": > /tmp/pycharm-first-run.log; "
            "for attempt in 1 2; do "
            'PYCHARM_VM_OPTIONS="$HOME/.pycharm-headless.vmoptions" '
            f"setsid xvfb-run -a pycharm {el_dir} "
            ">> /tmp/pycharm-first-run.log 2>&1 & "
            "pid=$!; ok=0; "
            f"for i in $(seq 1 {self._QEMU_PYCHARM_OPEN_TRIES}); do "
            f"if ls {el_dir}/.idea/*.iml >/dev/null 2>&1 && "
            f"[ -f {el_dir}/.idea/misc.xml ]; then ok=1; break; fi; "
            "sleep 5; done; "
            # Cinq secondes de plus : les fichiers apparaissent PENDANT leur
            # écriture, et un TERM à l'instant où misc.xml naît le tronquerait.
            "sleep 5; kill -TERM -$pid 2>/dev/null || "
            "kill -TERM $pid 2>/dev/null; "
            "for i in $(seq 1 12); do kill -0 -$pid 2>/dev/null || break; "
            "sleep 5; done; kill -KILL -$pid 2>/dev/null; "
            # Filet, et il a sa raison d'être : ce qui survit ici mange la
            # mémoire de TOUTES les étapes suivantes.
            #
            # Par NOM de processus (« -x »), jamais par ligne de commande. Un
            # « pkill -f /opt/pycharm » attrape aussi le ssh QUI PORTE cette
            # installation — sa ligne de commande contient le script entier,
            # donc ce chemin. Vécu : une installation est morte en silence, sa
            # session ssh emportée, 48 minutes perdues. Mesuré ensuite : par
            # nom, 3 processus réels attrapés et 0 faux ; par ligne de commande,
            # 4 dont le ssh. Les noms sont ceux relevés dans la VM — pycharm,
            # Xvfb, fsnotifier, cef_server — et « -u » borne au compte courant.
            #
            # « pgrep -c » IMPRIME 0 et rend 1 quand il ne trouve rien : un
            # « || echo 0 » donnerait « 0\n0 », qui n'est pas « 0 ». « wc -l »
            # rend un seul nombre et un code 0.
            'left=$(pgrep -u "$(id -u)" -x '
            '"pycharm|cef_server|fsnotifier|Xvfb" 2>/dev/null | wc -l); '
            '[ "$left" = 0 ] || { '
            f'echo "   {t("closing what survived the first open:")} $left"; '
            'pkill -u "$(id -u)" -x '
            '"pycharm|cef_server|fsnotifier|Xvfb" 2>/dev/null; sleep 2; }; '
            '[ "$ok" = 1 ] && break; '
            f'echo "   {t("no project yet, second try on the warm caches")}"; '
            "done; "
            '[ "$ok" = 1 ]; fi; fi; } && '
            f'echo "   {t("project created, the install will configure it")}" '
            f'|| echo "   ⚠ {t("no .idea: open PyCharm once, then")} '
            'make pycharm_configure"; '
        )

    def _qemu_android_studio_remote_cmd(self):
        """Installe Android Studio, pour le développement mobile ERPLibre.

        L'émulateur, lui, exige KVM DANS la VM, donc la virtualisation
        imbriquée : on le dit plutôt que de laisser découvrir l'échec au premier
        lancement. Compiler et déployer sur un appareil réel par adb n'en
        dépendent pas."""
        return (
            f'echo "== {t("Installing Android Studio (long)")} =="; '
            "{ "
            'if [ "$(uname -m)" != x86_64 ]; then '
            f'echo "   {t("Android Studio: Google publishes x86_64 only")}"; '
            "false; "
            "else "
            # Déjà posé ? On ne retélécharge pas. Rejouer une
            # installation est le cas NORMAL — une qui est morte, un outil
            # ajouté après coup — et le téléchargement en est la partie
            # longue : mesuré, ~5 min pour Android Studio, autant pour
            # PyCharm. Le reste de l'étape (lanceur, alias, raccourci)
            # rejoue de toute façon, lui est idempotent et bon marché.
            "if [ -x /opt/android-studio/bin/studio ]; then "
            f'echo "   {t("already there, download skipped")}"; '
            "else "
            # La page officielle porte l'URL en clair ; le repli garde une
            # version connue qui répond, pour le jour où sa forme change.
            f"url=$(curl -fsSL --max-time 30 {self._QEMU_ANDROID_PAGE} "
            "| grep -oE 'https://[a-z0-9.-]*gvt1\\.com/[^\"]*linux\\.tar\\.gz' "
            "| head -1); "
            f'[ -n "$url" ] || url="{self._QEMU_ANDROID_URL}"; '
            "tmp=$(mktemp -p /var/tmp android-XXXX.tar.gz) && "
            'curl -fsSL "$url" -o "$tmp" && '
            "sudo mkdir -p /opt/android-studio && "
            'sudo tar -xzf "$tmp" -C /opt/android-studio '
            "--strip-components=1; "
            'rc=$?; rm -f "$tmp"; [ $rc -eq 0 ]; fi; fi; } && { '
            + self._qemu_jetbrains_launcher_cmd(
                "/opt/android-studio", "studio", alias="android-studio"
            )
            + self._qemu_desktop_entry_cmd(
                "android-studio",
                "Android Studio",
                "/usr/local/bin/studio",
                "/opt/android-studio/bin/studio.svg",
                "Development;IDE;",
            )
            +
            # Le SDK partagé, vu depuis la SESSION graphique. install-android.sh
            # écrit ses exports dans ~/.bashrc, que GNOME ne lit pas : Android
            # Studio lancé depuis le menu ne verrait donc pas le SDK et
            # proposerait d'en télécharger un second. environment.d est le
            # canal que la session utilisateur lit vraiment.
            "mkdir -p ~/.config/environment.d && "
            "printf 'ANDROID_HOME=%s/android\\nANDROID_SDK_ROOT=%s/android\\n'"
            ' "$HOME" "$HOME" '
            "> ~/.config/environment.d/10-erplibre-android.conf; "
            # repositories.cfg absent, et l'assistant de première ouverture
            # s'arrête sur une erreur au lieu de proposer quoi que ce soit.
            "mkdir -p ~/.android && touch ~/.android/repositories.cfg; "
            + f'echo "   {t("Android Studio installed:")} /opt/android-studio '
            f'({t("command")} studio / android-studio)"; '
            f'echo "   {t("SDK shared through ANDROID_HOME:")} $HOME/android"; '
            "grep -q vmx /proc/cpuinfo 2>/dev/null "
            "|| grep -q svm /proc/cpuinfo 2>/dev/null "
            f'|| echo "   {t("no nested KVM: the emulator will not run")}"; '
            f'}} || echo "   ⚠ {t("Android Studio not installed (see above)")}"; '
        )

    # Extensions GNOME suggérées, par gestionnaire de paquets. Les noms ne sont
    # pas les mêmes d'une famille à l'autre (« dashtodock » sur Debian,
    # « dash-to-dock » sur Fedora), et aucune liste n'existe en entier partout.
    #
    # D'où l'installation UNE PAR UNE : apt, dnf, zypper et pacman échouent tous
    # sur la commande ENTIÈRE dès qu'un seul nom est inconnu. Un paquet absent
    # est donc annoncé et sauté, au lieu de faire tomber les autres avec lui.
    _QEMU_GNOME_EXT_PKGS = {
        "apt": (
            "gnome-shell-extension-manager",
            "gnome-tweaks",
            "gnome-shell-extensions",
            "gnome-shell-extension-dashtodock",
            "gnome-shell-extension-appindicator",
            "gnome-shell-extension-caffeine",
        ),
        "dnf": (
            "gnome-extensions-app",
            "gnome-tweaks",
            "gnome-shell-extension-dash-to-dock",
            "gnome-shell-extension-appindicator",
            "gnome-shell-extension-caffeine",
            "gnome-shell-extension-user-theme",
        ),
        "zypper": (
            "gnome-shell-extensions",
            "gnome-tweaks",
            "gnome-shell-extension-dash-to-dock",
            "gnome-shell-extension-appindicator",
        ),
        "pacman": (
            "extension-manager",
            "gnome-tweaks",
            "gnome-shell-extensions",
        ),
    }

    # Extensions demandées nommément, par leur UUID sur extensions.gnome.org.
    # Aucune n'est empaquetée par une distribution : on passe donc par le site.
    #
    # L'archive dépend de la version de GNOME Shell, et ce n'est pas une
    # précaution de principe : mesuré le 2026-08-17, le même point d'entrée
    # sert gTile v59 pour GNOME 46, v62 pour GNOME 48 et v52 pour GNOME 3.38.
    # Une URL figée poserait donc, tôt ou tard, une archive faite pour une
    # autre version.
    #
    # Ce que le site fait d'une version qu'il ne connaît PAS : il sert la plus
    # récente (vérifié — « shell_version=99 » rend l'archive des GNOME 49/50),
    # il ne répond pas 404. Sans conséquence fâcheuse pour autant : GNOME Shell
    # refuse de CHARGER une extension dont metadata.json ne déclare pas la
    # version courante. Une archive mal appariée reste donc inerte et affichée
    # « obsolète » dans le gestionnaire — elle ne casse pas la session.
    _QEMU_GNOME_EXT_UUIDS = (
        "gTile@vibou",
        "freon@UshakovVasilii_Github.yahoo.com",
        "tracker@aliakseiz.github.com",
    )

    _QEMU_GNOME_EXT_SITE = "https://extensions.gnome.org/download-extension"

    def _qemu_gnome_ext_site_cmd(self):
        """Installe les extensions nommées depuis extensions.gnome.org.

        Celles-là, on les ACTIVE — à la différence des paquets de la
        distribution, dont on ne connaît pas l'UUID. Deux raisons, l'une et
        l'autre vérifiées : le site rend l'archive faite pour le GNOME Shell de
        cette VM, et une archive mal appariée n'est de toute façon jamais
        chargée par GNOME, qui compare metadata.json à sa propre version. Ce
        n'est donc pas l'activation qui peut casser une session.

        Le tout dans un groupe gardé : ni une panne de réseau ni une extension
        retirée du site ne doivent faire échouer une installation d'une heure.
        """
        uuids = " ".join(self._QEMU_GNOME_EXT_UUIDS)
        site = self._QEMU_GNOME_EXT_SITE
        return (
            "{ "
            # « gnome-shell --version » rend « GNOME Shell 48.2 » : le dernier
            # champ suffit, et évite une expression régulière à rallonge.
            "v=$(gnome-shell --version 2>/dev/null | awk '{print $NF}'); "
            'if [ -z "$v" ]; then '
            + f'echo "   {t("GNOME Shell not found, site extensions skipped")}"; '
            + "else "
            # Le site attend le numéro MAJEUR depuis GNOME 40 (« 48 ») et
            # « majeur.mineur » avant (« 3.38 ») : sans la bonne forme, il ne
            # renvoie aucune archive.
            "maj=${v%%.*}; "
            'if [ "$maj" -ge 40 ] 2>/dev/null; then sv="$maj"; '
            'else sv=$(echo "$v" | cut -d. -f1,2); fi; '
            # gnome-extensions écrit dans ~/.local/share, mais l'activation
            # passe par GSettings : sans bus de session — le cas d'un
            # « ssh hôte commande » — dconf ne peut rien écrire.
            # dbus-run-session en fournit un le temps de l'appel, et
            # l'écriture atterrit bien dans le dconf de l'utilisateur.
            'gx() { if [ -z "$DBUS_SESSION_BUS_ADDRESS" ] && '
            "command -v dbus-run-session >/dev/null 2>&1; then "
            'dbus-run-session -- gnome-extensions "$@"; '
            'else gnome-extensions "$@"; fi; }; ' + f"for u in {uuids}; do "
            # « || echo » DANS la substitution : un mktemp qui échoue rendrait
            # l'affectation non nulle, et « set -e » couperait toute la suite.
            + "z=$(mktemp -p /var/tmp gext-XXXX.zip || echo /var/tmp/gext.zip); "
            + 'if curl -fsSL --max-time 120 "'
            + site
            + '/$u.shell-extension.zip?shell_version=$sv" -o "$z" '
            + '&& gx install --force "$z" >/dev/null 2>&1; then '
            + 'gx enable "$u" >/dev/null 2>&1 || true; '
            + f'echo "   {t("installed and enabled:")} $u"; else '
            + f'echo "   {t("not available for this GNOME, skipped:")} '
            + '$u (GNOME $sv)"; fi; rm -f "$z"; done; '
            + f'echo "   {t("log out and back in to load them")}"; '
            + "fi; } || true; "
        )

    def _qemu_gnome_ext_remote_cmd(self):
        """Pose les extensions GNOME suggérées.

        Deux sources, et deux politiques, pour une raison :
          - les paquets de la DISTRIBUTION sont installés sans être activés. On
            ne connaît pas leur UUID de façon fiable, et activer à l'aveugle une
            extension incompatible avec la version de GNOME Shell laisse la
            session sur un écran noir — panne qu'on ne diagnostique pas depuis
            une console série. Le gestionnaire graphique est posé pour choisir ;
          - les extensions nommées par leur UUID sont, elles, ACTIVÉES : le site
            rend l'archive faite pour ce GNOME-là, et une archive mal appariée
            n'est jamais chargée par GNOME plutôt que de casser la session.
        """
        pkgs = self._QEMU_GNOME_EXT_PKGS
        return (
            f'echo "== {t("Suggested GNOME extensions")} =="; '
            "if command -v apt-get >/dev/null 2>&1; then "
            f"EXT='{' '.join(pkgs['apt'])}'; "
            "I='sudo DEBIAN_FRONTEND=noninteractive apt-get "
            "-o DPkg::Lock::Timeout=600 install -y'; "
            "elif command -v dnf >/dev/null 2>&1; then "
            f"EXT='{' '.join(pkgs['dnf'])}'; I='sudo dnf install -y'; "
            "elif command -v zypper >/dev/null 2>&1; then "
            f"EXT='{' '.join(pkgs['zypper'])}'; "
            "I='sudo zypper --non-interactive install "
            "--auto-agree-with-licenses'; "
            "elif command -v pacman >/dev/null 2>&1; then "
            f"EXT='{' '.join(pkgs['pacman'])}'; "
            "I='sudo pacman -S --needed --noconfirm'; "
            'else EXT=""; fi; '
            'for p in $EXT; do $I "$p" >/dev/null 2>&1 '
            f'|| echo "   {t("not in the repos, skipped:")} $p"; done; '
            f'echo "   {t("Enable them from Extension Manager, or:")} '
            'gnome-extensions enable <uuid>"; '
            + self._qemu_gnome_ext_site_cmd()
        )

    # Diagnostic de la compilation mobile : motif rencontré dans le journal
    # détaillé -> cause nommée. Du plus précis au plus général, le premier qui
    # correspond gagne.
    #
    # Cette liste est faite pour GRANDIR. Une compilation Android échoue de
    # cent façons, et le journal fait des dizaines de mégaoctets : sans cette
    # traduction, « la VM est rouge » n'apprend rien et il faut tout rouvrir.
    # Chaque panne rencontrée sur une VM mérite d'y laisser sa ligne.
    _QEMU_MOBILE_DIAG = (
        ("No space left on device", "disk full"),
        ("Failed to find target with hash string", "SDK platform missing"),
        ("SDK location not found", "SDK not found (ANDROID_HOME)"),
        ("have not been accepted", "SDK licences not accepted"),
        ("NDK not configured", "NDK missing"),
        # Vécu : Capacitor 8 réclame un JDK 21 quand l'installateur amont pose
        # un 17, et Gradle s'arrête là.
        (
            "Cannot find a Java installation",
            "JDK required by the project missing",
        ),
        # Vécu aussi : le JDK est là, mais Gradle TOURNE sur un plus ancien.
        ("invalid source release", "Gradle running on too old a JDK"),
        ("cannot overwrite", "SDK already there (upstream installer replays)"),
        # Vécu : sentencepiece bâtit protoc pour la CIBLE et l'exécute sur
        # l'hôte. Le message est cryptique ; la cause, non.
        ("Exec format error", "cross-compiled protoc run on the host"),
        ("Unsupported class file major version", "JDK/Gradle mismatch"),
        ("Could not determine java version", "JDK/Gradle mismatch"),
        (
            "Could not resolve all files for configuration",
            "Gradle dependency unreachable (network?)",
        ),
        ("npm ERR!", "npm dependencies"),
        ("Test Files", "Vitest tests failed"),
        # Vécu : le manifeste rend 0 sans avoir cloné, et l'étape suivante
        # tombe sur un cd impossible. Le motif nomme la vraie cause.
        #
        # SANS APOSTROPHE, et ce n'est pas cosmétique : ces motifs partent dans
        # un « grep -q '<motif>' », entre apostrophes. « can't cd to » fermait
        # la chaîne et rendait tout le bloc invalide — attrapé par bash -n.
        ("cd: can", "mobile repository missing"),
        # Vécu aussi : sans python3.12-venv, .venv.erplibre n'existe pas, et
        # rien de ce qui suit ne peut synchroniser le manifeste.
        ("virtual environment", "ERPLibre venv missing (incomplete install)"),
        ("No module named", "ERPLibre venv incomplete (no pip: python3-venv)"),
        # Vécu sur erplibre-ubuntu-2604-gnome : le noyau a tué le démon Gradle
        # (6,8 Go de RSS sur 12 Go, sans swap), et Gradle n'en sait rien — il
        # dit seulement que son démon « a disparu ». Le motif nomme la mémoire,
        # et le contexte l'établit au lieu de le supposer.
        # Vécu, et c'est en amont : « Too many zip entries 123678 (MAX=65535) ».
        # Un APK est un ZIP classique, borné à 65 535 entrées, et le dépôt
        # mobile embarque 122 684 fichiers sous assets/public/repos — des
        # dépôts Odoo entiers — pour 337 fichiers qui sont l'application. Rien
        # ici ne peut le corriger : c'est au projet mobile de ne pas les
        # empaqueter. On le NOMME, avec le chiffre, plutôt que de laisser lire
        # 5 000 lignes de Gradle.
        (
            "Too many zip entries",
            "too many asset files for one APK (ZIP limit: 65535 entries)",
        ),
        ("daemon disappeared", "Gradle daemon killed: out of memory", "mmem"),
        ("Cannot allocate memory", "out of memory", "mmem"),
        ("Java heap space", "Gradle heap too small", "mmem"),
        ("FAILED", "Gradle task failed"),
    )

    def _qemu_mobile_diag_cmd(self):
        """Fonction shell qui NOMME la cause d'un échec, à partir du journal.

        Un « la VM est rouge » n'apprend rien quand le journal fait des dizaines
        de mégaoctets. On cherche donc les motifs connus, et à défaut on montre
        les dernières lignes — c'est toujours mieux que rien.

        La recherche porte sur la FIN du journal, pas sur tout. Vécu : le
        diagnostic a annoncé « licences SDK non acceptées » quand la panne était
        un JDK manquant — le motif venait de la revue de licences d'une étape
        RÉUSSIE, trois étapes plus haut. Nommer la mauvaise cause coûte plus
        cher que se taire."""
        lines = ""
        for entry in self._QEMU_MOBILE_DIAG:
            pat, cause = entry[0], entry[1]
            extra = f"{entry[2]}; " if len(entry) > 2 else ""
            lines += (
                f"grep -q '{pat}' \"$d\" && {{ "
                f'echo "   {t("probable cause:")} {t(cause)}"; '
                f'{extra}rm -f "$d"; return 0; }}; '
            )
        return (
            # Le contexte mémoire, lu dans /proc et dans le journal du noyau :
            # une cause « mémoire » se PROUVE, l'affirmer sans le compte de
            # l'oom-killer serait une supposition de plus. Pas d'awk ni de sed
            # ici : leurs programmes demandent des guillemets, et tout ceci
            # voyage déjà dans un ssh entre apostrophes.
            "mmem() { m=$(grep MemTotal /proc/meminfo | tr -dc 0-9); "
            "w=$(grep SwapTotal /proc/meminfo | tr -dc 0-9); "
            "k=$(sudo dmesg 2>/dev/null | grep -c oom-kill); "
            f'echo "   {t("memory:")} $((m/1024)) {t("MB RAM,")} '
            f'$((w/1024)) {t("MB swap, kernel OOM kills:")} $k"; }}; '
            'mdiag() { d=$(mktemp); tail -400 "$1" > "$d"; '
            + lines
            + f'echo "   {t("no known pattern, last lines:")}"; '
            'tail -12 "$1" | sed "s/^/     /"; rm -f "$d"; }; '
        )

    def _qemu_android_prologue_cmd(self):
        """Ce que la compilation mobile et l'émulateur partagent : le journal
        détaillé, le coureur d'étapes, le diagnostic, et l'environnement du SDK.

        Écrit UNE fois même quand les deux options sont cochées — deux
        prologues, ce serait deux journaux et deux SDK."""
        return (
            self._qemu_mobile_diag_cmd() +
            # Le détail va dans un fichier À PART. Une compilation Gradle écrit
            # des dizaines de milliers de lignes, dont des centaines portant le
            # mot « error » sans qu'aucune ne soit une panne : les verser dans
            # le journal d'installation rendrait son compteur d'erreurs
            # inutilisable, et le diagnostic illisible.
            'M="$HOME/erplibre-mobile-build.log"; : > "$M"; '
            f'echo "   {t("detailed log in the VM:")} $M"; '
            'mstep() { lbl="$1"; shift; echo "   -> $lbl"; '
            'if sh -c "$*" >> "$M" 2>&1; then return 0; fi; '
            f'echo "   ⚠ {t("FAILED:")} $lbl"; mdiag "$M"; return 1; }}; '
            # Le SDK vit dans $HOME/android, l'emplacement qu'emploie
            # l'installateur du dépôt. Android Studio, s'il est là, le trouvera
            # par ANDROID_HOME : un seul SDK sur la machine, pas deux.
            'export ANDROID_HOME="$HOME/android"; '
            'export ANDROID_SDK_ROOT="$HOME/android"; '
            'export PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin'
            ':$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator"; '
            # ~/.bashrc n'est pas lu par un « ssh hôte commande » : ce que
            # l'installateur y écrit ne sert qu'aux sessions futures, pas à la
            # compilation qui suit immédiatement.
            #
            # Le JDK le PLUS RÉCENT installé, et non celui des alternatives.
            # Mesuré : avec JAVA_HOME sur le 17 que pose l'installateur amont,
            # Gradle tourne en 17 et s'arrête sur « invalid source release: 21 »
            # — les modules de Capacitor 8 compilent en 21. Le tri est
            # « sort -V », donc java-21 passe après java-17, pas avant.
            "export JAVA_HOME=$(ls -d /usr/lib/jvm/java-*-openjdk-* "
            "2>/dev/null | sort -V | tail -1); "
            '[ -n "$JAVA_HOME" ] || export JAVA_HOME=$(dirname $(dirname '
            "$(readlink -f $(command -v javac 2>/dev/null "
            "|| command -v java 2>/dev/null) 2>/dev/null) 2>/dev/null) "
            "2>/dev/null); "
            'export PATH="$JAVA_HOME/bin:$PATH"; '
        )

    def _qemu_android_sdk_steps(self, el_dir):
        """Les étapes qui posent le SDK : dépôt mobile, prérequis, installateur
        amont, plateforme réclamée par le projet. Communes aux deux options."""
        return (
            # Le « test -f » n'est pas une ceinture de plus : c'est la seule
            # vérité disponible. update_manifest_local_mobile.sh finit par
            # « kill $DAEMON_PID » et rend donc 0 même quand il n'a rien cloné —
            # vécu, faute de .venv.erplibre. L'étape passait, et c'est le « cd »
            # suivant qui échouait, deux étapes plus loin.
            # Le venv d'ERPLibre d'abord, et nommément : tout ce qui suit en
            # dépend — c'est lui qui porte « repo », qui synchronise le
            # manifeste. Vécu avec le profil « ERPLibre seul », dont le code
            # note lui-même « problem installing with q, the script depend on
            # odoo » : sans venv, le manifeste rendait 0 sans rien cloner et
            # l'échec ne se voyait que deux étapes plus loin.
            f'mstep "{t("ERPLibre venv (everything below needs it)")}" '
            # « activate », et non « bin/python » : sans python3-venv, le venv
            # naît INFIRME — bin/python existe (un lien), mais ni pip ni
            # activate ni site-packages. La sonde passait, et l'échec ne se
            # voyait que deux étapes plus loin, en « No module named git ».
            f"'test -f {el_dir}/.venv.erplibre/bin/activate' && "
            f'mstep "{t("mobile repository (additive manifest)")}" '
            f"'cd {el_dir} && ./script/manifest/update_manifest_local_mobile.sh; "
            "test -f mobile/erplibre_home_mobile/install-android.sh' && "
            f'mstep "{t("prerequisites of the upstream installer")}" '
            # libpulse0 : l'émulateur a DEUX binaires qemu, et seul le
            # « headless » se passe de PulseAudio. Celui qui ouvre une FENÊTRE —
            # le cas d'un « ssh -X » — lie libpulse.so.0, absente des images
            # cloud, et s'arrête sur « cannot open shared object file » même
            # avec « -no-audio ». Mesuré : c'est la SEULE bibliothèque qui
            # manque, tout le reste des dépendances Qt voyage dans le bundle.
            #
            # openjdk-21 EN PLUS du 17 que pose l'installateur amont : mesuré,
            # Gradle s'arrête sur « Cannot find a Java installation matching
            # {languageVersion=21} » — les modules de Capacitor 8 réclament 21.
            # Les deux JDK cohabitent, et Gradle choisit par sa chaîne d'outils.
            # unzip et xauth, eux, manquent des images cloud.
            "'sudo DEBIAN_FRONTEND=noninteractive apt-get "
            "-o DPkg::Lock::Timeout=600 install -y unzip wget xauth "
            "libpulse0 openjdk-21-jdk' && "
            # L'installateur amont n'est PAS idempotent : au second passage il
            # s'arrête sur « mv: cannot overwrite latest/cmdline-tools ». Mesuré.
            # On ne le rejoue donc que s'il reste quelque chose à poser — un
            # déploiement qui se répète ne doit pas échouer sur une réussite
            # précédente.
            f'mstep "{t("Android SDK, licences, NDK")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && "
            "{ [ -x $HOME/android/cmdline-tools/latest/bin/sdkmanager ] "
            "|| ./install-android.sh; }' && "
            f'mstep "{t("SDK platform required by the project")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && "
            'v=$(sed -n "s/.*compileSdkVersion *= *\\([0-9]*\\).*/\\1/p" '
            'android/variables.gradle) && [ -n "$v" ] && '
            'yes | sdkmanager "platforms;android-$v" '
            '"build-tools;$v.0.0"\' && '
        )

    def _qemu_mobile_build_steps(self, el_dir):
        """Étapes de compilation de l'application mobile, puis ses tests.

        C'est la seule étape qui peut faire échouer la VM, et c'est voulu : une
        machine dont l'application ne compile pas n'est pas une machine prête.
        Le code de sortie remonte donc jusqu'au tableau de bord.

        Le dépôt mobile porte son propre installateur Android — JDK, outils en
        ligne de commande, licences acceptées, plateformes, NDK, whisper.cpp et
        sentencepiece. On l'appelle plutôt que de le réécrire : une seconde
        implémentation dériverait de la première sans prévenir. Deux choses lui
        manquent pourtant, et on les ajoute ici :
          - unzip et wget, qu'il suppose présents et qu'aucune image cloud ne
            livre ;
          - la plateforme que le projet réclame VRAIMENT. Son installateur pose
            android-34 quand android/variables.gradle demande compileSdk 36 ;
            plutôt que de figer 36 ici, on lit le chiffre dans le fichier.

        L'étape est bornée à apt (voir _QEMU_VM_TOOLS) : cet installateur
        commence par « sudo apt install openjdk-17-jdk » et s'arrête là
        ailleurs. La lever se fait dans ce script-là, pas ici.
        """
        return (
            # Du swap AVANT de compiler, et ce n'est pas de la prudence : le
            # démon Gradle a atteint 6,8 Go de RSS hors tas — son -Xmx1536m ne
            # le borne pas — sur une VM de 12 Go SANS swap, et le noyau l'a tué
            # deux fois de suite. « --max-workers=2 » n'y a rien changé :
            # mesuré, le pic est passé de 10,3 à 11,2 Go. C'est donc de la marge
            # qu'il faut, pas moins de parallélisme.
            #
            # Jamais bloquant : une image sur btrfs refuse un fichier d'échange
            # ordinaire, et une compilation qui tient en mémoire n'en a pas
            # besoin. On le dit et on continue.
            "w=$(grep SwapTotal /proc/meminfo | tr -dc 0-9); "
            'if [ "$w" -lt 2000000 ]; then '
            "if sudo fallocate -l 4G /swapfile-erplibre 2>/dev/null && "
            "sudo chmod 600 /swapfile-erplibre && "
            "sudo mkswap -q /swapfile-erplibre >/dev/null 2>&1 && "
            "sudo swapon /swapfile-erplibre 2>/dev/null; then "
            "grep -q swapfile-erplibre /etc/fstab 2>/dev/null || "
            'echo "/swapfile-erplibre none swap sw 0 0" '
            "| sudo tee -a /etc/fstab >/dev/null; "
            f'echo "   {t("4 GB of swap added for the build")}"; '
            "else sudo rm -f /swapfile-erplibre 2>/dev/null; "
            f'echo "   {t("no swap could be added; build may run short")}"; '
            "fi; fi; "
            f'mstep "{t("npm dependencies")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && npm ci' && "
            f'mstep "{t("web bundle (vite build)")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && npm run build' && "
            # Le transfert des dépôts du manifeste DANS l'application est
            # vérifié, et son compte-rendu se lit dans le journal
            # d'installation — d'où l'appel HORS mstep, qui enverrait la sortie
            # dans le journal détaillé de la VM.
            #
            # Ces dépôts entrent en PACKS, et c'est ce qui rend la chose
            # possible : un APK est un ZIP borné à 65535 entrées, quand les
            # 139 dépôts pèsent plus de 116 000 fichiers. Un fichier par source
            # donnait « Too many zip entries 123678 (MAX=65535) » et rien du
            # tout ; regroupés, ils tiennent en 391 tranches — mesuré, avec
            # 3 002 entrées dans l'APK.
            #
            # Lié par « && » : un transfert vide fait échouer la VM, au même
            # titre qu'un APK manquant. Une application qui ne porte pas le code
            # qu'elle est censée montrer n'est pas l'application demandée.
            f'echo "   -> {t("repo transfer into the app")}" && '
            f"(cd {el_dir} && ./script/mobile/check_bundle_transfer.py"
            f" --workspace {el_dir}) && "
            f'mstep "{t("native sync (capacitor)")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && npx cap sync android' && "
            # UNE seule ABI, celle de la VM — qui est aussi celle de
            # l'émulateur. Deux raisons, la seconde décisive :
            #   - quatre ABI, c'est quatre fois la compilation de whisper.cpp
            #     et de sentencepiece, pour trois qui ne serviront jamais ici ;
            #   - sentencepiece bâtit son « protoc » POUR LA CIBLE puis tente de
            #     l'exécuter sur l'hôte. En arm64 cela donne « Exec format
            #     error » et la compilation s'arrête — mesuré. En x86_64 la
            #     cible et l'hôte coïncident, et le défaut ne se manifeste pas.
            #     Un APK arm64 demandera un correctif au projet mobile.
            f'mstep "{t("debug APK (gradle)")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile/android && "
            "./gradlew --no-daemon assembleDebug "
            "-Pandroid.injected.build.abi=x86_64' && "
            f'mstep "{t("Vitest tests")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && npm test' && "
            # L'APK est la preuve, pas le code de sortie de Gradle : une tâche
            # peut rendre 0 sans avoir rien produit.
            # DEUX emplacements, et il faut les deux. Avec une ABI injectée,
            # AGP écrit dans « intermediates/apk/debug » et non dans
            # « outputs/apk/debug » : mesuré, une compilation RÉUSSIE était
            # rapportée « aucun APK produit » parce que je ne regardais que le
            # second. Un contrôle qui cherche au mauvais endroit ne vaut pas
            # mieux que pas de contrôle.
            f"apk=$(ls {el_dir}/mobile/erplibre_home_mobile/android/app/build"
            "/outputs/apk/debug/*.apk "
            f"{el_dir}/mobile/erplibre_home_mobile/android/app/build"
            "/intermediates/apk/debug/*.apk 2>/dev/null | head -1); "
            'if [ -n "$apk" ]; then '
            f'echo "   ✅ {t("APK built:")} $apk"; '
            # Capacitor sert la même application dans un navigateur : sur une
            # VM graphique, c'est la voie de déverminage sans Android ni
            # émulateur. On la NOMME plutôt que d'imposer Chromium — sur
            # Ubuntu il n'existe qu'en snap, et snapd est justement coupé sur
            # ces VM. Le navigateur du bureau fait l'affaire.
            #
            # DANS la branche de succès, et c'est tout l'enjeu : placé après le
            # « fi », cet echo devenait la dernière commande du bloc et rendait
            # 0 — une VM sans APK repassait au vert.
            f'echo "   {t("browser debugging (no Android):")} '
            f"cd {el_dir}/mobile/erplibre_home_mobile "
            '&& npm start"; else '
            f'echo "   ⚠ {t("no APK produced")}"; false; fi'
        )

    def _qemu_avd_steps(self, el_dir):
        """Étapes créant un émulateur prêt à s'ouvrir depuis le poste de travail.

        Le modèle n'est pas figé : on demande au SDK la liste de ses profils et
        on retient le Pixel le plus récent au plus petit écran — ni Pro, ni XL,
        ni pliant, ni tablette. Sur un écran distant, chaque pixel traverse le
        réseau : le petit modèle n'est pas une coquetterie.

        L'image système suit la plateforme du projet, et redescend si elle n'est
        pas publiée — Google ne fournit pas d'image pour toutes les API.

        Le rendu est réglé en logiciel DANS la configuration de l'AVD plutôt
        qu'en option de lancement : par « ssh -X » il n'y a pas de GLX direct, et
        l'émulateur s'ouvrirait sur un écran noir. Ainsi « emulator -avd
        erplibre » suffit, sans rien à retenir.

        Le mode est « swangle » — ANGLE sur SwiftShader — et non
        « swiftshader_indirect », qui n'existe PLUS : l'émulateur 37.1 répond
        « Selected GPU option 'swiftshader_indirect' is not valid, switching to
        auto », puis « Your GPU drivers may have a bug », avant de retomber de
        lui-même sur swangle. Il fonctionnait, en affichant deux erreurs qui
        laissaient croire à une panne. Les modes valides sont exactement quatre,
        que « emulator -help-gpu » énumère : auto, host, swiftshader, swangle.
        """
        return (
            f'echo "   == {t("Android emulator (AVD)")} =="; '
            # KVM dans la VM : sans lui l'émulateur x86 refuse de démarrer. On
            # le dit ici, où c'est réparable (virtualisation imbriquée sur
            # l'hôte), plutôt qu'au premier lancement.
            "if [ ! -e /dev/kvm ]; then "
            f'echo "   ⚠ {t("no /dev/kvm: nested virtualisation is off on the host")}"; '
            "else "
            # /dev/kvm est en root:kvm 0660 : sans appartenir au groupe,
            # l'émulateur refuse de démarrer sur « ProbeKVM: This user doesn't
            # have permissions to use KVM ». Mesuré. L'appartenance ne prend
            # qu'à la prochaine session — ce qui tombe bien, la session utile
            # est justement celle du « ssh -X » qui viendra ensuite.
            "sudo usermod -aG kvm $(id -un) 2>/dev/null || true; "
            f'echo "   {t("user added to the kvm group (effective at next login)")}"; '
            "fi; "
            f'mstep "{t("emulator and system image")}" '
            '\'v=$(sed -n "s/.*compileSdkVersion *= *\\([0-9]*\\).*/\\1/p" '
            f"{el_dir}/mobile/erplibre_home_mobile/android/variables.gradle); "
            "for a in $v 36 35 34; do "
            'img="system-images;android-$a;google_apis;x86_64"; '
            'if yes | sdkmanager "emulator" "$img"; then '
            'echo "$img" > $HOME/.erplibre-avd-image; break; fi; done; '
            "test -s $HOME/.erplibre-avd-image' && "
            f'mstep "{t("Pixel profile, smallest screen")}" '
            # Le plus récent des Pixel simples : on trie sur le NUMÉRO, pas sur
            # l'ordre d'affichage, et on écarte les grands modèles.
            '\'avdmanager list device | grep -oE "pixel_[0-9]+a?" '
            '| grep -vE "pro|xl|fold|tablet" | sort -t_ -k2 -n | tail -1 '
            "> $HOME/.erplibre-avd-device; test -s $HOME/.erplibre-avd-device' && "
            f'mstep "{t("create the AVD")}" '
            "'img=$(cat $HOME/.erplibre-avd-image); "
            "dev=$(cat $HOME/.erplibre-avd-device); "
            'echo no | avdmanager create avd -n erplibre -k "$img" '
            '-d "$dev" --force && '
            # Rendu logiciel, écrit dans la config : par ssh -X il n'y a pas
            # de GLX direct, et « auto » donnerait un écran noir. Ces deux
            # clés-là SURVIVENT, elles ne viennent pas du profil du téléphone.
            #
            # L'écran, en revanche, ne s'écrit PAS ici : l'émulateur réécrit
            # config.ini depuis le profil Pixel au premier démarrage, et les
            # hw.lcd.* y étaient effacés — l'AVD repartait en 1080x2400
            # densité 420. C'est donc au LANCEMENT qu'il se règle, par
            # _QEMU_EMULATOR_FLAGS, et la commande affichée plus bas les porte.
            'printf "hw.gpu.enabled=yes\\nhw.gpu.mode=swangle\\n" '
            ">> $HOME/.android/avd/erplibre.avd/config.ini' && "
            f'echo "   ✅ {t("AVD ready:")} '
            "$(cat $HOME/.erplibre-avd-device) / "
            '$(cat $HOME/.erplibre-avd-image)"; '
            # La commande à copier, avec l'adresse déjà remplie : un émulateur
            # dont on ignore comment l'ouvrir ne sert à personne.
            "ip=$(hostname -I 2>/dev/null | awk '{print $1}'); "
            # Chemins ABSOLUS, et c'est le point : « ssh hôte 'commande' »
            # ne lit NI ~/.profile NI ~/.bashrc — Ubuntu place même un
            # « return » en tête du second pour les shells non interactifs.
            # Le PATH que l'installateur y écrit ne s'applique donc jamais
            # à ces commandes, et « emulator » y répond « command not
            # found ». Vécu, sur la ligne que ce message affichait lui-même.
            f'echo "   {t("open it from your workstation:")} '
            # « -XC » et non « -X » : la compression X11 change tout sur un
            # écran distant. Les autres drapeaux viennent de la même autorité
            # que le lancement du menu : écran réduit, densité qui va avec, et
            # pas d'instantané en attente si on tue l'émulateur.
            'ssh -XC erplibre@$ip \\"$HOME/android/emulator/emulator '
            f'-avd erplibre {self._QEMU_EMULATOR_FLAGS}\\""; '
            f'echo "   {t("then install the APK:")} '
            # « -t » : l'ABI injectée fait marquer l'APK « testOnly » par AGP,
            # et adb le refuse sans ce drapeau — « INSTALL_FAILED_TEST_ONLY ».
            # Mesuré sur l'émulateur.
            'ssh erplibre@$ip \\"$HOME/android/platform-tools/adb install -r -t '
            f"{el_dir}/mobile/erplibre_home_mobile/android/app/build"
            '/outputs/apk/debug/app-debug.apk\\""; '
            # La voie scrcpy, nommée ici parce que c'est la première
            # question qui vient après « ça se lance mais c'est lent » :
            # X11 transporte des pixels bruts, scrcpy un flux H.264 encodé
            # par l'appareil. Le détail du tunnel vit dans le menu
            # « Remote desktop tunnel », choix 4.
            + f'echo "   {t("smoother, without X11:")} TODO > Execute > Deploy > QEMU/KVM > tunnel > 4"'
        )

    def _qemu_forgejo_steps(self, el_dir):
        """Pose Forgejo dans la VM, par le script dédié du dépôt.

        Tout le travail est DANS le script — architecture, version, somme de
        contrôle, compte système, configuration, service, compte
        administrateur. Ce bloc ne fait que l'appeler : une seule autorité, et
        la même commande sert un déploiement de VM et une installation à la
        main sur une machine existante.

        Pas de garde, comme la compilation mobile : une VM dont la forge
        demandée n'existe pas n'est pas la VM demandée. Le script, lui, est
        rejouable — il ne retélécharge pas un binaire déjà en place et ne
        réécrit jamais une configuration existante.
        """
        return (
            f'echo "== {t("Forgejo (git forge)")} =="; '
            f"{el_dir}/script/forgejo/install_forgejo.sh"
        )

    def _qemu_after_remote_cmd(self, tools, prod=False):
        """Phase d'APRÈS l'installation : prologue commun, SDK commun, puis ce
        qui a été coché.

        Un seul prologue et un seul SDK même quand les deux options le sont :
        deux prologues, et le second tronquerait le journal détaillé du premier.

        Les groupes sont joints par « && » et non par « ; ». C'est ce qui fait
        qu'un APK manquant reste l'échec de la VM : collé par « ; », un
        émulateur créé avec succès effacerait le verdict de la compilation."""
        picked = [
            k
            for k in ("forgejo", "mobile", "avd")
            if k in (tools or ()) and k in self._QEMU_VM_TOOLS
        ]
        if not picked:
            return ""
        el_dir = self._qemu_install_dir(prod)
        parts = []
        # Forgejo d'abord : une minute, contre une heure pour le SDK et l'APK.
        # Un échec rapide se voit tôt plutôt qu'après le long.
        if "forgejo" in picked:
            parts.append(f"{{ {self._qemu_forgejo_steps(el_dir)}; }}")
        groups = []
        if "mobile" in picked:
            groups.append(self._qemu_mobile_build_steps(el_dir))
        if "avd" in picked:
            groups.append(self._qemu_avd_steps(el_dir))
        if groups:
            # UN seul prologue et un seul SDK même quand les deux options le
            # sont : deux prologues, et le second tronquerait le journal
            # détaillé du premier.
            parts.append(
                "{ "
                + f'echo "== {t("ERPLibre mobile, Android SDK (long)")} =="; '
                + self._qemu_android_prologue_cmd()
                + self._qemu_android_sdk_steps(el_dir)
                # Chaque groupe entre ACCOLADES. Sans elles, « && » ne lie que
                # la première commande du groupe suivant : mesuré, un APK
                # manquant laissait tourner l'émulateur puis rendait 0 — la VM
                # repassait au vert alors que rien n'avait compilé.
                + " && ".join(f"{{ {g}; }}" for g in groups)
                + "; }"
            )
        return " && ".join(parts) + "; "

    def _qemu_mobile_remote_cmd(self, prod=False):
        """Compilation mobile seule — la forme que testent les tests."""
        return self._qemu_after_remote_cmd(("mobile",), prod)

    def _qemu_avd_remote_cmd(self, prod=False):
        """Émulateur seul."""
        return self._qemu_after_remote_cmd(("avd",), prod)

    def _qemu_aidev_remote_cmd(self, agent=""):
        """rtk, starship et UN agent, posés dans la VM.

        Chaque pose est bornée dans le temps ET privée d'entrée standard. Le
        contrat de la phase « before » veut qu'un outil ne fasse échouer ni
        les autres ni l'installation d'ERPLibre : « || true » couvre l'échec,
        mais pas l'ATTENTE. Un installateur amont qui pose une question
        resterait pendu sur un SSH sans terminal, et le déploiement avec lui ;
        « </dev/null » la lui fait rater tout de suite, « timeout » borne le
        reste. C'est aussi pourquoi starship reçoit « -y ».

        L'accroche du prompt et la ligne de PATH sont posées UNE fois :
        sans le « grep » qui précède, chaque redéploiement d'une même VM
        rallonge son ~/.bashrc d'une ligne identique.

        Le répertoire est écrit en « $HOME » et non en « ~ » : entre
        guillemets, le tilde n'est pas étendu par le shell, et le PATH
        porterait alors un chemin qui n'existe pas.
        """
        commande, repertoire = dev_tools.AGENTS.get(
            agent or dev_tools.AGENT_DEFAUT,
            dev_tools.AGENTS[dev_tools.AGENT_DEFAUT],
        )
        repertoire = repertoire.replace("~/", "$HOME/", 1)
        prompt = dev_tools.STARSHIP_LINE["bash"]
        path_line = f'export PATH="{repertoire}:$PATH"'

        def pose(cmd, secondes):
            return (
                f"timeout {secondes} sh -c {shlex.quote(cmd)}"
                " </dev/null || true; "
            )

        def une_fois(ligne, motif):
            return (
                f"grep -qF {shlex.quote(motif)} ~/.bashrc 2>/dev/null"
                f" || echo {shlex.quote(ligne)} >> ~/.bashrc; "
            )

        return (
            f'echo "== {t("AI coding tools")} =="; '
            + pose(dev_tools.RTK_UPSTREAM, 300)
            + pose(dev_tools.STARSHIP_UPSTREAM_YES, 300)
            + une_fois(prompt, "starship init bash")
            + pose(commande, 600)
            + une_fois(path_line, repertoire)
        )

    def _qemu_tools_remote_cmd(
        self, tools, prod=False, phase="before", ai_agent=""
    ):
        """Bloc des outils cochés pour cette PHASE, du plus utile au plus lourd.

        « before » : posé avant le clone. Chaque outil s'y garde lui-même —
        aucun ne fait échouer les autres, ni l'installation d'ERPLibre.

        « after » : la compilation mobile, qui vient après l'installation dont
        elle dépend, et qui elle NE se garde PAS. C'est le contrat demandé : une
        VM dont l'application ne compile pas doit être rouge."""
        if phase == "after":
            # Un seul bloc pour les deux options : voir _qemu_after_remote_cmd.
            return self._qemu_after_remote_cmd(tools, prod)
        blocks = {
            # En tête : quelques secondes de curl, contre des minutes pour un
            # IDE. Ce qui échoue vite se voit tôt.
            "aidev": lambda: self._qemu_aidev_remote_cmd(ai_agent),
            "gnome_ext": self._qemu_gnome_ext_remote_cmd,
            "pycharm": lambda: self._qemu_pycharm_remote_cmd(prod),
            "android": self._qemu_android_studio_remote_cmd,
        }
        return "".join(fn() for k, fn in blocks.items() if k in (tools or ()))

    def _qemu_editor_pkg(self):
        """Paquet de l'éditeur de l'hôte, à installer dans la VM.

        L'éditeur atteint déjà la VM par deux chemins, tous deux posés par
        deploy_qemu.py : « core.editor » dans son ~/.gitconfig, et la ligne
        « éditer le serveur » du guide de connexion. Encore faut-il que le
        binaire y soit — les images cloud n'ont ni nano ni vim garantis, et
        certaines n'ont même pas vi. On l'ajoute donc aux outils d'amorçage, avec
        curl, git et make, là où les dépôts viennent d'être rafraîchis.

        La table des éditeurs vit dans deploy_qemu.py : une seule autorité décide
        du paquet installé, de la commande affichée et de core.editor. Sans
        module importable, on n'installe rien plutôt que de deviner un nom."""
        try:
            mod = self._qemu_import_module()
            return mod.vm_editor(mod.invoking_home())[0]
        except Exception:
            return ""

    def _qemu_editor_suffix(self):
        """« vim » -> « vim » précédé d'une espace, rien du tout sinon.

        La liste des outils d'amorçage est une chaîne shell entre apostrophes :
        y concaténer une chaîne vide sans précaution laisserait une espace en
        trop, inoffensive mais visible dans chaque log d'installation."""
        pkg = self._qemu_editor_pkg()
        return f" {pkg}" if pkg else ""

    # mise ne publie de binaire que pour ces architectures : 46 assets à la
    # v2026.8.4, aucun s390x — son propre script d'installation refuse cette
    # plateforme. Ailleurs, le choix « mise » est sans objet et on reste sur
    # pyenv, ce que le formulaire et l'invite disent avant de déployer.
    QEMU_MISE_ARCHES = ("amd64", "arm64")

    def _qemu_mise_remote_cmd(self, python_provider):
        """Pose mise DANS la VM et fixe EL_PYTHON_PROVIDER pour l'installation.

        mise s'installe par défaut dans ~/.local/bin, qui n'est PAS dans le
        PATH d'un « ssh hôte 'commande' » : ni ~/.profile ni ~/.bashrc n'y sont
        lus. On le pose donc dans /usr/local/bin, présent dans le PATH par
        défaut — même raison que pour cargo et rustc.

        Sans mise utilisable, rien n'est écrit : lib_python_provider.sh
        retombe alors sur pyenv toute seule."""
        if python_provider == "pyenv":
            # Explicite : même si mise se trouvait déjà dans l'image, on ne
            # l'utilise pas. Sans cela le mode « auto » du dépôt le prendrait.
            return "export EL_PYTHON_PROVIDER=pyenv; "
        if python_provider != "mise":
            return ""
        return (
            f'echo "== {t("Installing mise (precompiled Python)")} =="; '
            "if command -v mise >/dev/null 2>&1; then "
            'echo "   mise: $(mise --version)"; '
            "else "
            # La variable est passée À sudo, pas exportée avant : « sudo -E »
            # dépend de env_reset dans sudoers et n'est pas garanti.
            "curl -fsSL https://mise.run "
            "| sudo MISE_INSTALL_PATH=/usr/local/bin/mise sh "
            '|| echo "   mise indisponible ici : pyenv prendra le relais"; '
            "fi; "
            # « auto », et non « mise » : si l'installation ci-dessus a échoué,
            # lib_python_provider.sh doit pouvoir retomber sur pyenv.
            "export EL_PYTHON_PROVIDER=auto; "
        )
