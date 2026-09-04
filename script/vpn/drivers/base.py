#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un pilote VPN doit savoir faire, et tout ce qu'ils partagent.

Un pilote décrit UNE technologie : quels paquets, quels secrets, quels
fichiers, quelle séquence pour monter, laquelle pour descendre, et comment
savoir si c'est monté. Il n'exécute rien : il demande à un `Runner` (voir
`runner.py`), qui exécute ou se contente de montrer.

Ce fichier porte aussi tout ce qui est VRAI pour toutes les technologies : la
disposition des répertoires, l'état retenu entre deux processus, les routes,
le DNS de systemd-resolved, et les vérifications d'état. Un pilote nouveau
n'a donc à écrire que ce qui lui est propre — et quand une de ces mécaniques
se révèle fausse, elle se corrige à un seul endroit.

Où vivent les fichiers, pour tous les pilotes :

    /dev/shm/erplibre-vpn/<profil>/   0700 root — LES SECRETS. tmpfs : rien
                                     n'est écrit sur un disque persistant, et
                                     un redémarrage efface tout.
    /run/erplibre-vpn/<profil>.*      0755 — l'état NON secret (interface
                                     retenue, pid, route ajoutée). Lisible
                                     sans sudo : `status` en a besoin, et il
                                     tourne dans un autre processus que `up`.
"""
from __future__ import annotations

import ipaddress
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import time

# Les `secret_fields` d'un pilote portent des clés i18n : affichées brutes,
# elles mettaient de l'anglais au milieu d'une phrase française.
from script.todo.todo_i18n import t

# Un seul endroit nomme l'installateur : `vpn.py` l'importe d'ici.
INSTALL_SCRIPT = "./script/install/install_vpn.sh"

SECRET_DIR = "/dev/shm/erplibre-vpn"
STATE_DIR = "/run/erplibre-vpn"


# ----------------------------------------------------------------------
# Lecture de l'état de la machine — sans sudo, sans rien modifier
# ----------------------------------------------------------------------
def which(binary: str) -> str:
    """Chemin du binaire si NOUS pouvons l'exécuter, "" sinon.

    À réserver aux commandes lancées sous notre propre identité
    (systemctl is-active, resolvectl, sshuttle). Pour celles que root
    lance, voir `locate`.
    """
    return shutil.which(binary) or ""


def locate(binary: str) -> str:
    """Chemin du binaire s'il EXISTE dans le PATH, même si nous n'avons pas
    le droit de l'exécuter.

    C'est la bonne question pour un binaire que ROOT lance. `pppd` est en
    4750 root:dip sur Debian et Ubuntu : `which` le déclare absent à tout
    utilisateur hors du groupe dip, alors que xl2tpd — qui tourne en root —
    l'exécute très bien. Confondre les deux fait annoncer « pppd absent »
    sur une machine où le paquet ppp est installé, et envoie chercher au
    mauvais endroit.
    """
    return shutil.which(binary, mode=os.F_OK) or ""


# Famille netlink de l'IPsec du noyau. charon et `ip xfrm` n'ont pas
# d'autre porte : quand elle est fermée, aucune configuration ne rattrape.
NETLINK_XFRM = 6


def netlink_family_available(protocol: int) -> bool:
    """Le noyau expose-t-il cette famille netlink ?

    L'OUVERTURE suffit à répondre : le noyau charge à la demande le module
    qui sert la famille, et rend `EPROTONOSUPPORT` quand il ne le trouve
    pas. Aucune donnée n'est lue, aucun droit root n'est requis. C'est le
    premier geste de charon, et ce qui lui fait dire « unable to create
    netlink socket » avant d'abandonner sur `kernel-ipsec` manquant.
    """
    try:
        sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, protocol)
    except OSError:
        return False
    sock.close()
    return True


def stale_kernel() -> str:
    """Version du noyau en cours d'exécution quand ses modules ont disparu,
    "" quand ils sont là.

    Mettre à jour le paquet du noyau remplace `/lib/modules/<version>` par
    celle de la version neuve. Le noyau DÉJÀ démarré perd alors l'accès à
    tous ses modules : ceux qui étaient chargés continuent, aucun autre ne
    peut l'être. Une capacité que le noyau prend pourtant en charge devient
    donc indisponible jusqu'au redémarrage, et rien d'autre ne la rétablit.

    L'absence est jugée RELATIVEMENT aux autres arborescences : un noyau
    compilé sans modules n'en a aucune, et le déclarer périmé enverrait
    redémarrer pour rien.
    """
    release = platform.release()
    if os.path.isdir(f"/lib/modules/{release}"):
        return ""
    try:
        return release if os.listdir("/lib/modules") else ""
    except OSError:
        return ""


def resolve(host: str) -> str:
    """Première adresse IPv4 de `host`, ou "" — et `host` lui-même s'il EST
    déjà une adresse. Sans elle, impossible de préserver la route vers le
    serveur quand on remplace la route par défaut."""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
    except (socket.gaierror, UnicodeError):
        return ""
    return infos[0][4][0] if infos else ""


def _ip(args: list[str]) -> str:
    """Sortie de `ip …`, "" en cas d'échec. Lecture seule, sans sudo."""
    try:
        proc = subprocess.run(
            ["ip"] + args, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def interfaces(kind: str | None = None) -> set[str]:
    """Interfaces existantes, éventuellement d'un seul type (ppp, tun,
    wireguard).

    L'ensemble AVANT/APRÈS est ce qui permet de nommer l'interface qu'un
    tunnel vient de créer : pppd n'annonce pas « ppp3 » à qui l'a lancé, et
    supposer « ppp0 » est faux dès qu'un autre tunnel est déjà là.
    """
    args = ["-o", "link", "show"]
    if kind:
        args += ["type", kind]
    out = _ip(args)
    return set(re.findall(r"^\d+:\s+([^:@]+)", out, re.MULTILINE))


def ppp_interfaces() -> set[str]:
    return interfaces("ppp")


def wait_for_new_interface(before: set, kind: str, timeout=25, interval=0.5):
    """Nom de la première interface `kind` apparue depuis `before`, ou "".

    L'attente est nécessaire : entre la demande de session et l'interface
    configurée, il y a la négociation — quelques secondes, parfois vingt sur
    une liaison lente.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        new = interfaces(kind) - before
        if new:
            return sorted(new)[0]
        time.sleep(interval)
    return ""


def wait_for_interface_address(iface: str, timeout=25, interval=0.5):
    """Attend que `iface` porte une adresse IPv4. Rend la liste, ou [].

    Une interface PPP existe dès que pppd la crée, bien avant qu'IPCP ait
    négocié l'adresse. Lire trop tôt donne « sans adresse » sur un tunnel
    parfaitement sain, et fait chercher les DNS du pair avant que pppd les
    ait écrits.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        addresses = interface_addresses(iface)
        if addresses:
            return addresses
        time.sleep(interval)
    return []


def interface_addresses(iface: str) -> list[str]:
    out = _ip(["-brief", "addr", "show", "dev", iface])
    return re.findall(r"(\d+\.\d+\.\d+\.\d+)(?:/\d+)?", out)


def interface_exists(iface: str) -> bool:
    return bool(iface) and bool(_ip(["-o", "link", "show", "dev", iface]))


def route_to(target: str) -> dict:
    """{"via", "dev", "src"} de la route actuelle vers `target`, {} si
    indéterminée. Sert à garder joignable le serveur VPN lui-même."""
    out = _ip(["route", "get", target])
    if not out:
        return {}
    result = {}
    for key in ("via", "dev", "src"):
        found = re.search(rf"\b{key}\s+(\S+)", out)
        if found:
            result[key] = found.group(1)
    return result


def ssh_client_address() -> str:
    """Adresse du client SSH de la session courante, "" si on n'est pas
    dans une session SSH.

    `SSH_CONNECTION` vaut « <client> <port> <serveur> <port> ». Elle sert à
    ne PAS scier la branche sur laquelle on est assis : piloter un client
    VPN par SSH et lui faire capter tout le trafic coupe la session qui
    donne l'ordre — et le menu, et le tunnel avec.
    """
    connexion = os.environ.get("SSH_CONNECTION", "").split()
    if not connexion:
        return ""
    adresse = connexion[0]
    try:
        ipaddress.ip_address(adresse)
    except ValueError:
        return ""
    return adresse


def pppd_dns() -> list[str]:
    """Serveurs DNS poussés par le pair, lus dans /etc/ppp/resolv.conf.

    pppd écrit LÀ et nulle part ailleurs quand on lui demande `usepeerdns` ;
    c'est systemd-resolved qui ignore ce fichier, d'où l'étape `resolvectl`
    du pilote."""
    try:
        with open("/etc/ppp/resolv.conf") as fh:
            content = fh.read()
    except OSError:
        return []
    return re.findall(r"nameserver\s+(\S+)", content)


class VpnDriver:
    """Contrat d'un pilote, et les mécaniques communes."""

    # Nom technique : valeur du champ `driver` d'un profil, et argument de
    # `script/install/install_vpn.sh`.
    name = ""
    # Libellé montré à l'humain.
    label = ""
    # Binaires sans lesquels rien ne marche.
    binaries: tuple[str, ...] = ()
    # Ce que le NOYAU doit exposer : (libellé, sonde). La sonde lit l'état
    # de la machine, sans root et sans rien modifier. Vide quand tout se
    # joue en espace utilisateur — un tunnel TLS n'exige rien du noyau.
    # N'y mettre qu'une sonde dont le faux NÉGATIF est impossible : celle
    # qui répond « absent » sur une machine saine fait proposer un
    # redémarrage inutile, ce qui est pire que le diagnostic qu'elle rend.
    kernel_features: tuple = ()
    # Secrets attendus dans le coffre : (clé, libellé, obligatoire).
    # « password » et « username » désignent les champs NATIFS de
    # KeePassXC ; tout autre nom devient une propriété protégée.
    secret_fields: tuple[tuple[str, str, bool], ...] = ()
    # Champs de profil PROPRES à cette technologie : défauts, et le
    # formulaire que le menu déroule.
    defaults: dict = {}
    # (clé, libellé i18n, type, avancé) ; type ∈ text|int|flag|path.
    form_fields: tuple[tuple[str, str, str, bool], ...] = ()
    # Faux quand c'est le SERVEUR qui décide des routes : exiger une route
    # déclarée serait alors une fausse exigence.
    needs_routes = True
    # Type d'interface que la technologie crée, "" quand elle n'en crée pas
    # (sshuttle détourne par le pare-feu, sans interface).
    iface_kind = ""
    # Libellé i18n du champ « serveur » : une cible SSH ne se demande pas
    # comme l'adresse d'un concentrateur.
    server_label = "Server address (hostname or IP)"
    # Libellé i18n d'une ligne : QUAND choisir cette technologie. C'est la
    # seule décision où l'utilisateur a vraiment besoin d'un conseil.
    hint = ""
    # Vrai quand la technologie a été montée contre un vrai concentrateur.
    # Faux quand seuls les tests unitaires la couvrent : le menu marque
    # alors la ligne d'une étoile. Ce que l'utilisateur risque autrement,
    # c'est de lire cinq choix d'apparence égale et de partir en production
    # sur celui que personne n'a jamais vu aboutir.
    proven = False
    # Champ de profil qui porte l'identifiant, recopié dans le champ
    # `username` de l'entrée du coffre — pour que le coffre reste lisible
    # dans KeePassXC. Le profil reste la source de vérité.
    user_field = ""
    # Faux quand la technologie ne prend pas le MTU du profil — le demander
    # serait une question sans effet.
    uses_mtu = True

    def __init__(self, profile: dict, secrets: dict | None = None):
        self.profile = profile
        # `secrets` absent = mode « description » : on peut rendre les
        # fichiers non secrets, lister les étapes, vérifier l'état. Monter
        # le tunnel, non.
        self.secrets = secrets or {}
        self.name_tag = profile.get("name", "")

    # ------------------------------------------------------------------
    # À redéfinir
    # ------------------------------------------------------------------
    @classmethod
    def validate_profile(cls, profile: dict) -> None:
        """Valide et NORMALISE en place les champs propres au pilote.

        Lève `valid.ProfileError`. Les contrôles communs (nom, serveur,
        routes, MTU, témoin) sont déjà faits par `profiles.validate`.
        """

    def up(self, runner) -> bool:
        raise NotImplementedError

    def down(self, runner) -> bool:
        raise NotImplementedError

    def status(self, runner) -> list:
        """Liste de (libellé, verdict, détail). `None` en verdict veut dire
        « indéterminable » — pas « faux »."""
        raise NotImplementedError

    def log_commands(self) -> list:
        """(libellé, commande) à montrer dans le diagnostic."""
        return []

    # ------------------------------------------------------------------
    # Chemins et état
    # ------------------------------------------------------------------
    @property
    def secret_dir(self):
        return f"{SECRET_DIR}/{self.name_tag}"

    @property
    def pid_file(self):
        return self.state_file("pid")

    def state_file(self, key):
        return f"{STATE_DIR}/{self.name_tag}.{key}"

    def prepare_dirs(self, runner, secrets=True):
        """Le répertoire des secrets en 0700, celui de l'état en 0755.

        Deux modes différents parce que deux usages différents : un secret
        ne se lit que par root, l'état doit se lire par `status` lancé sans
        sudo.

        Pas de répertoire de secrets pour un pilote qui n'écrit pas de
        secret : sshuttle s'authentifie par clé SSH, et openconnect passe le
        mot de passe par l'entrée standard — aucun des deux n'a de fichier à
        y mettre. D'où `secrets=False`.
        """
        if secrets and self.secret_fields:
            runner.mkdir(self.secret_dir, "0700")
        runner.mkdir(STATE_DIR, "0755")

    def write_state(self, runner, key, value):
        runner.write(self.state_file(key), f"{value}\n", mode="0644")

    def read_state(self, key):
        """Valeur retenue au montage, "" sinon.

        Retenue dans un fichier et non devinée : `status` tourne dans un
        autre processus que `up`."""
        try:
            with open(self.state_file(key)) as fh:
                return fh.read().strip()
        except OSError:
            return ""

    def clear_state(self, runner, *keys):
        for key in keys:
            runner.remove(self.state_file(key))

    def recorded_iface(self):
        return self.read_state("iface")

    # ------------------------------------------------------------------
    # Prérequis
    # ------------------------------------------------------------------
    def missing_binaries(self) -> list:
        """Les binaires qui manquent VRAIMENT.

        `locate` et non `which` : ces binaires sont lancés par root, et
        « puis-je l'exécuter ? » est la mauvaise question — voir `locate`.
        """
        return [b for b in self.binaries if not locate(b)]

    def missing_secrets(self) -> list:
        return [
            label
            for key, label, required in self.secret_fields
            if required and not self.secrets.get(key)
        ]

    def secret_values(self) -> list:
        """Les valeurs à masquer dans tout affichage."""
        return [v for v in self.secrets.values() if v]

    def ensure_ready(self, runner) -> bool:
        """Noyau, binaires et secrets présents ?

        À blanc, un prérequis absent est un AVERTISSEMENT : montrer le plan
        sur une machine où le client n'est pas encore installé est justement
        à quoi sert le mode à blanc — c'est là qu'on relit une configuration
        avant de la poser.
        """
        report = runner.warn if runner.dry_run else runner.fail
        ready = True
        # Le noyau d'abord : quand c'est LUI qui manque, installer un paquet
        # n'y changerait rien, et l'annoncer en premier évite de chercher la
        # cause dans l'étage du dessus.
        for _, ok, detail in self.check_kernel():
            if ok is False:
                # Proposé avant d'être constaté, comme pour les paquets —
                # mais l'échec est constaté MÊME si le redémarrage est
                # accepté : la machine met quelques secondes à s'arrêter, et
                # monter un tunnel dans cet intervalle serait le monter sur
                # le noyau qu'on quitte.
                self.propose_reboot(runner)
                report(detail)
                ready = False
        missing = self.missing_binaries()
        if missing:
            # Proposé AVANT de constater l'échec : si le correctif passe, il
            # n'y a plus d'échec à annoncer. Constater puis réparer laisserait
            # un « montage incomplet » sur un montage qui a réussi.
            runner.info(f"      Binaires absents : {', '.join(missing)}")
            if runner.propose(
                f"paquets client de {self.name}",
                f"bash {INSTALL_SCRIPT} {self.name}",
                question="Installer les paquets client maintenant ?",
            ):
                missing = self.missing_binaries()
                if not missing:
                    runner.ok("Paquets installés.")
        if missing:
            report(
                f"Binaires absents : {', '.join(missing)}. Installer :"
                f" sudo bash {INSTALL_SCRIPT} {self.name}"
            )
            ready = False
        missing_secret = self.missing_secrets()
        if missing_secret:
            labels = ", ".join(t(label) for label in missing_secret)
            report(
                f"Secrets manquants dans le coffre : {labels}. Les déposer :"
                " TODO › Execute › Déploiement › VPN › « Déposer les"
                " secrets dans le coffre »."
            )
            ready = False
        return ready or runner.dry_run

    def needs_reboot(self) -> bool:
        """Un redémarrage est-il le SEUL remède à ce qui manque ?

        La conjonction qui le dit : une capacité du noyau manque ET les
        modules du noyau qui tourne ont disparu. Le module ne peut plus être
        chargé et aucune configuration n'y changera rien ; la version
        installée, elle, porte la capacité. Un noyau qui ne l'expose pas du
        tout ne gagnerait rien à redémarrer, et des modules périmés dont
        rien ne manque encore ne pressent pas : ni l'un ni l'autre ne rend
        vrai.
        """
        return bool(self.missing_kernel_features() and stale_kernel())

    def propose_reboot(self, runner) -> bool:
        """Propose le redémarrage quand `needs_reboot` le dit.

        Les garde-fous de `Runner.propose` valent ici : on demande, rien
        n'est appliqué à blanc ni sans terminal pour répondre.
        """
        if not self.needs_reboot():
            return False
        runner.info(
            "      Le noyau qui tourne n'a plus ses modules : le paquet du"
            " noyau a été mis à jour depuis le démarrage. Redémarrer les"
            " rétablit, et c'est le seul remède — toutes les sessions"
            " ouvertes seront coupées."
        )
        return runner.propose(
            "modules du noyau inaccessibles",
            "systemctl reboot",
            question="Redémarrer la machine maintenant ?",
        )

    # ------------------------------------------------------------------
    # Étapes communes
    # ------------------------------------------------------------------
    def add_routes(self, runner, iface):
        """Les routes déclarées, par l'interface du tunnel.

        `replace` et non `add` : une route déjà là ne doit pas faire
        échouer un remontage. Elles disparaissent avec l'interface, donc
        rien à défaire au « down »."""
        for route in self.profile.get("routes", []):
            runner.cmd(
                f"router {route} par {iface}",
                f"ip route replace {shlex.quote(route)}"
                f" dev {shlex.quote(iface)}",
                check=False,
            )

    def suggest_routes(self, runner, iface):
        """Quand rien n'est routé, proposer le réseau de l'adresse obtenue.

        Le site ne remet souvent qu'une passerelle et des identifiants, et
        personne ne sait quel réseau est derrière. Le premier montage, lui,
        le dit : le concentrateur nous place dans le réseau qu'on cherchait
        à joindre.

        Le /24 est une HYPOTHÈSE, annoncée comme telle — le préfixe réel ne
        se déduit pas d'une adresse. C'est le point de départ d'une
        question au site, pas une réponse.
        """
        if self.profile.get("routes") or self.profile.get("default_route"):
            return
        addresses = interface_addresses(iface)
        if not addresses:
            return
        try:
            network = ipaddress.ip_network(f"{addresses[0]}/24", strict=False)
        except ValueError:
            return
        runner.warn(
            "Aucun réseau routé : ce tunnel ne joint que l'hôte distant."
        )
        runner.info(
            f"      Adresse obtenue {addresses[0]}. Si le réseau du site"
            f" est un /24 — hypothèse, pas déduction — ajouter"
            f" « {network} » aux réseaux du profil."
        )

    def set_resolved_dns(self, runner, iface, servers, search=""):
        """Donne les serveurs DNS du tunnel à systemd-resolved.

        Sans cet appel, le tunnel est monté et aucun nom interne ne résout :
        resolved ne lit pas les fichiers que pppd ou vpnc-script écrivent.
        """
        if not servers:
            return
        if not which("resolvectl"):
            runner.warn(
                "resolvectl absent : les DNS du tunnel ne sont pas"
                " appliqués. Vérifier /etc/resolv.conf à la main."
            )
            return
        runner.cmd(
            f"DNS de {iface} : {' '.join(servers)}",
            f"resolvectl dns {shlex.quote(iface)} "
            + " ".join(shlex.quote(s) for s in servers),
            check=False,
        )
        if search:
            runner.cmd(
                f"domaine de recherche {search} sur {iface}",
                f"resolvectl domain {shlex.quote(iface)}"
                f" {shlex.quote('~' + search)}",
                check=False,
            )

    def kill_pidfile(self, runner, label="arrêter le démon", sudo=True):
        """Tue le processus dont le pid est dans le fichier de pid.

        `|| true` : au « down », le démon est souvent DÉJÀ tombé — c'est
        même la raison la plus fréquente d'un « down ». Ce n'est pas un
        échec.

        `sudo=False` pour un démon lancé SOUS l'utilisateur : sshuttle
        n'élève que la partie pare-feu, son processus principal est le
        nôtre, et root n'a pas à s'en mêler.
        """
        pid = shlex.quote(self.pid_file)
        runner.cmd(
            label,
            "sh -c {}".format(
                shlex.quote(f"[ -f {pid} ] && kill $(cat {pid}) || true")
            ),
            check=False,
            sudo=sudo,
        )

    def pid_alive(self):
        """Vrai/faux si le pid du fichier tourne, None si indéterminable.

        Pas de fichier de pid = FAUX, pas « on ne sait pas » : le démon
        écrit ce fichier au démarrage, son absence est une réponse. `None`
        est réservé au vrai doute — fichier illisible, pid corrompu.

        `os.kill(pid, 0)` ne tue rien : il demande au noyau si le processus
        existe. `PermissionError` veut dire qu'il existe mais ne nous
        appartient pas — donc vivant.
        """
        try:
            with open(self.pid_file) as fh:
                pid = int(fh.read().strip())
        except FileNotFoundError:
            return False
        except (OSError, ValueError):
            return None
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return None
        return True

    def add_host_route(self, runner, server_ip, raison="le serveur"):
        """Route /32 vers `server_ip` par la passerelle ACTUELLE.

        Posée avant de monter, retirée au « down ». Sans elle, dès que le
        tunnel capte la route par défaut, les paquets à destination de cette
        adresse entrent dans le tunnel — les paquets chiffrés vers le
        concentrateur, qui transportent le tunnel, et ceux de la session SSH
        qui donne l'ordre.

        Plusieurs adresses peuvent avoir besoin de cette protection : l'état
        garde donc une LISTE, une par ligne."""
        info = (
            runner.call(
                f"lire la route actuelle vers {server_ip}",
                lambda: route_to(server_ip),
                dry_safe=True,
            )
            or {}
        )
        via, dev = info.get("via"), info.get("dev")
        if not dev:
            runner.warn(
                f"Route actuelle vers {server_ip} indéterminée : la route de"
                f" survie de {raison} n'est pas posée. En mode « tout le"
                " trafic », le tunnel peut se couper lui-même."
            )
            return
        spec = f"{server_ip}/32"
        command = f"ip route replace {spec} dev {shlex.quote(dev)}"
        if via:
            command = (
                f"ip route replace {spec} via {shlex.quote(via)}"
                f" dev {shlex.quote(dev)}"
            )
        runner.cmd(
            f"poser la route de survie {spec} ({raison})",
            command,
            check=False,
        )
        gardees = [
            ligne
            for ligne in self.read_state("hostroute").splitlines()
            if ligne.strip() and ligne.strip() != spec
        ]
        gardees.append(spec)
        self.write_state(runner, "hostroute", "\n".join(gardees))

    def protect_the_ssh_session(self, runner):
        """Garde joignable le client SSH qui donne l'ordre.

        Piloter un client VPN par SSH et lui faire capter TOUT le trafic
        coupe la session qui vient de lancer la commande : le retour part
        dans le tunnel. On perd la machine, le menu, et le moyen de démonter
        ce qu'on vient de monter."""
        adresse = ssh_client_address()
        if not adresse:
            return
        runner.info(
            f"      Session SSH depuis {adresse} : on lui garde une route"
            " directe, sinon « tout le trafic » la couperait."
        )
        self.add_host_route(runner, adresse, raison="la session SSH")

    def del_host_route(self, runner):
        for spec in self.read_state("hostroute").splitlines():
            spec = spec.strip()
            if not spec:
                continue
            runner.cmd(
                f"retirer la route de survie {spec}",
                f"ip route del {shlex.quote(spec)}",
                check=False,
            )

    # ------------------------------------------------------------------
    # Vérifications d'état, communes
    # ------------------------------------------------------------------
    def missing_kernel_features(self) -> list:
        """Libellés des capacités du noyau que la machine n'expose pas."""
        return [label for label, probe in self.kernel_features if not probe()]

    def check_kernel(self) -> list:
        """L'étage le plus bas : ce que le noyau donne, et ce qui l'en
        empêche.

        Sans cette vérification, un module inaccessible se manifeste trois
        étages plus haut et sous un autre nom — charon démarre, abandonne à
        l'initialisation, et l'attente de la connexion accuse le bloc de
        `/etc/ipsec.conf`, qui est pourtant bien formé.

        Le verdict distingue deux causes que le même symptôme recouvre. Les
        modules du noyau qui tourne ont disparu : la capacité EXISTE dans ce
        noyau et un redémarrage la rend. Ce noyau ne l'expose pas : rien à
        redémarrer, c'est le noyau qu'il faut changer. Rend une liste vide
        quand le pilote n'exige rien du noyau et qu'il n'y a rien à signaler.
        """
        missing = self.missing_kernel_features()
        stale = stale_kernel()
        names = ", ".join(label for label, _ in self.kernel_features)
        if missing:
            absent = ", ".join(missing)
            if stale:
                return [
                    (
                        "noyau",
                        False,
                        f"{absent} : indisponible — les modules du noyau"
                        f" {stale} ont disparu, redémarrer",
                    )
                ]
            return [("noyau", False, f"{absent} : absent de ce noyau")]
        if stale:
            # Les capacités sondées répondent, mais elles sont les SEULES :
            # les modules qu'une négociation charge ensuite (ESP, AH, ppp)
            # ne peuvent plus l'être. Signalé, jamais compté en échec — un
            # tunnel déjà monté, lui, continue de fonctionner.
            detail = f"modules du noyau {stale} disparus — redémarrer"
            if not names:
                return [("noyau", None, detail)]
            return [("noyau", True, f"{names} présent, mais {detail}")]
        if not names:
            return []
        return [("noyau", True, f"{names} : présent")]

    def check_binaries(self):
        missing = self.missing_binaries()
        return (
            "paquets client",
            not missing,
            "présents" if not missing else f"absents : {', '.join(missing)}",
        )

    def check_mounted(self):
        iface = self.recorded_iface()
        return (
            "profil monté (état /run)",
            bool(iface),
            f"interface {iface}" if iface else "aucun état : non connecté",
        )

    def check_daemon(self, label="démon"):
        alive = self.pid_alive()
        if alive is None:
            detail = f"fichier de pid illisible : {self.pid_file}"
        elif alive:
            detail = f"vivant (pid dans {self.pid_file})"
        elif os.path.exists(self.pid_file):
            detail = "pid connu mais processus absent — démontage inachevé"
        else:
            detail = "aucun fichier de pid : non connecté"
        return (label, alive, detail)

    def check_iface(self, iface):
        exists = interface_exists(iface)
        addresses = interface_addresses(iface) if exists else []
        return (
            f"interface {iface}",
            exists and bool(addresses),
            ", ".join(addresses) if addresses else "absente ou sans adresse",
        )

    def check_routes(self, iface):
        checks = []
        for route in self.profile.get("routes", []):
            info = route_to(route.split("/")[0])
            ok = info.get("dev") == iface
            checks.append(
                (
                    f"route {route}",
                    ok,
                    f"via {info.get('dev', '?')}"
                    + (f" (attendu {iface})" if not ok else ""),
                )
            )
        if self.profile.get("default_route"):
            info = route_to("1.1.1.1")
            checks.append(
                (
                    "route par défaut",
                    info.get("dev") == iface,
                    f"via {info.get('dev', '?')}",
                )
            )
        return checks

    def check_probe(self, runner):
        """Le témoin : la seule vérification qui PROUVE que ça marche.

        Tout le reste dit que les tuyaux sont en place ; celle-ci dit qu'un
        paquet est allé au bout et revenu."""
        probe = self.profile.get("probe")
        if not probe:
            return []
        code, _ = runner.cmd(
            f"joindre {probe} à travers le tunnel",
            f"ping -c 2 -W 3 {shlex.quote(probe)}",
            sudo=False,
            check=False,
            capture=True,
        )
        return [
            (
                f"témoin {probe}",
                code == 0,
                "répond" if code == 0 else "ne répond pas",
            )
        ]

    def standard_status(self, runner, extra=()):
        """L'enchaînement habituel : noyau, paquets, état, interface,
        routes, témoin — du plus bas au plus haut, pour que la première
        ligne fausse soit la CAUSE et non une conséquence. Un pilote insère
        ses propres vérifications par `extra`, une liste de (libellé,
        verdict, détail)."""
        checks = self.check_kernel()
        checks.extend([self.check_binaries(), self.check_mounted()])
        checks.extend(extra)
        iface = self.recorded_iface()
        if iface:
            checks.append(self.check_iface(iface))
            checks.extend(self.check_routes(iface))
        checks.extend(self.check_probe(runner))
        return checks
