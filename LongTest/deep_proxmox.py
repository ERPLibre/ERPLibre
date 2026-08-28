#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Jusqu'à quel étage un Proxmox dans un Proxmox tient-il ?

Ce n'est pas un test unitaire : il crée de vraies machines et prend des
HEURES. Il vit donc hors de `test/`, que le lanceur unitaire balaie.

Ce qu'il établit, et pourquoi cela valait un script : la profondeur
d'imbrication praticable ne se déduit pas, elle se mesure. Une mesure à la
main a montré, au quatrième étage, un invité 36 fois plus lent que le temps
réel — 583 secondes d'horloge pour 16 secondes de temps invité — puis un noyau
gelé au MÊME octet quelles que soient les ressources. Un chiffre obtenu une
fois, sur une machine, n'est pas un chiffre : ce script le refait à la demande
et dit exactement OÙ ça casse.

La descente est UNIFORME. Chaque étage, le premier compris, passe par les
mêmes six étapes : créer, attendre le ssh, installer Proxmox, redémarrer et
vérifier le noyau, remettre pmxcfs debout, contrôler le stockage. Seule la
création diffère — libvirt en local, « qm » ensuite.

Il envoie NOTRE install_proxmox.sh par scp au lieu de laisser la VM cloner le
dépôt : c'est notre code qu'on veut éprouver, et le dépôt distant est souvent
en retard sur le checkout — un correctif absent du distant a fait « revenir »
le même défaut sur trois VM de suite.

  ./LongTest/deep_proxmox.py --depth 10 --dry-run
  ./LongTest/deep_proxmox.py --depth 10
  ./LongTest/deep_proxmox.py --detruire        # défait ce que la descente a posé
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.proxmox import nesting  # noqa: E402
from script.proxmox import proxmox_deploy as pve  # noqa: E402

# L'image des étages imbriqués. Debian parce que install_proxmox.sh s'installe
# SUR une Debian — Proxmox ne publie pas d'image cloud.
DISTRO = "proxmox"
NOM_BASE = "deep-pve"

# Une étape bloquée ne doit pas bloquer le test : chaque appel est borné, et le
# journal dit lequel a expiré. Généreux, parce que chaque étage est plus lent
# que le précédent — c'est précisément ce qu'on mesure.
DELAIS = {
    "creation": 1200,
    "ssh": 2400,
    "install": 7200,
    "reboot": 2400,
    "reparation": 600,
    "controle": 180,
}


def dire(msg, journal=None):
    ligne = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(ligne, flush=True)
    if journal:
        with open(journal, "a", encoding="utf-8") as fh:
            fh.write(ligne + "\n")


def capacite_hote():
    """(cœurs, RAM disponible en Mo, disque libre en Go) de la machine réelle.

    « available » et non « free » : c'est ce que le noyau promet de rendre sans
    mettre la machine à genoux.
    """
    coeurs = os.cpu_count() or 2
    ram = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for ligne in fh:
                if ligne.startswith("MemAvailable:"):
                    ram = int(ligne.split()[1]) // 1024
                    break
    except OSError:
        pass
    disque = 0
    try:
        st = os.statvfs("/var/lib/libvirt/images")
        disque = (st.f_bavail * st.f_frsize) // (1024**3)
    except OSError:
        pass
    return coeurs, ram, disque


def module_qemu():
    """deploy_qemu.py chargé comme module : il porte le catalogue d'images."""
    import importlib.util

    chemin = os.path.join(RACINE, "script/qemu/deploy_qemu.py")
    spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cle_publique():
    for nom in ("id_ed25519.pub", "id_rsa.pub"):
        chemin = os.path.expanduser(f"~/.ssh/{nom}")
        if os.path.exists(chemin):
            return chemin
    return ""


def nom_etage(niveau):
    return f"{NOM_BASE}-{niveau}"


def alias_etage(niveau, parent_alias):
    """« parent+enfant », la convention du dépôt : elle dit où la machine vit
    et ne peut rien voler à un homonyme."""
    if not parent_alias:
        return nom_etage(niveau)
    court = re.sub(r"[^A-Za-z0-9._-]", "-", parent_alias)
    return f"{court}+{nom_etage(niveau)}"


class Descente:
    """Un étage après l'autre, et ce qu'on en sait."""

    def __init__(self, plan, journal, dry_run=False, chemin_json=None):
        self.plan = plan
        self.journal = journal
        self.chemin_json = chemin_json
        self.dry_run = dry_run
        self.etages = []
        self.interrompu = False
        self.niveau_courant = 1

    def dire(self, msg):
        dire(msg, self.journal)

    def delai(self, etape):
        """Le délai de cette étape, à l'étage courant.

        Constant, il contredisait la raison d'être du script : au quatrième
        étage un invité tournait 36 fois moins vite. Une installation de dix
        minutes au premier étage en demande des heures au quatrième, et le
        plafond fixe la déclarait échouée — en concluant à un mur
        d'imbrication là où il n'y avait qu'un délai trop court.

        Le facteur est CARRÉ et borné : chaque étage ajoute une couche
        d'hyperviseur à traverser, mais un facteur illimité rendrait un
        échec réel indiscernable d'une attente sans fin.
        """
        facteur = min(max(1, self.niveau_courant), 5) ** 2
        return DELAIS[etape] * facteur

    # ---------------------------------------------------------------- #
    # Parler aux machines
    # ---------------------------------------------------------------- #
    def executer(self, hote, remote, delai, etiquette, montrer=False):
        if self.dry_run:
            argv = pve.ssh_argv(
                hote, pve.wrap_privilege(remote, hote.get("sudo") or "")
            )
            print("      " + " ".join(shlex.quote(a) for a in argv)[:200])
            return 0, ""
        debut = time.time()
        code, sortie = pve.run(hote, remote, delai)
        if code or montrer:
            self.dire(
                f"      {etiquette} : code {code}"
                f" en {int(time.time() - debut)} s"
            )
        if code:
            for ligne in pve.strip_ssh_noise(sortie).strip().splitlines()[-5:]:
                self.dire(f"        {ligne}")
        return code, sortie

    def attendre_ssh(self, hote, delai, parent=None):
        """Attend que la machine réponde. Rend les secondes, ou None.

        Des connexions COURTES successives : cloud-init régénère les clés
        d'hôte et redémarre sshd au premier démarrage, ce qui tuerait une
        session longue.

        `parent` : si l'hôte qui HÉBERGE la machine attendue cesse de
        répondre, on abandonne tout de suite. Constaté : l'étage 1 a redémarré
        pendant l'installation de l'étage 4, ce qui a éteint les étages 2, 3 et
        4 d'un coup ; la descente a attendu son délai entier — quarante
        minutes — un ssh qui ne pouvait plus aboutir, puis a rendu « jamais
        joignable en ssh ». Le diagnostic était faux : la machine n'était pas
        lente, sa MAISON n'existait plus.
        """
        if self.dry_run:
            return 0
        debut = time.time()
        # SANS privilège : wrap_privilege transformerait « true » en
        # « sudo sh -c true », et un sudo qui réclame un mot de passe — le
        # temps que cloud-init écrive /etc/sudoers.d — se lisait « jamais
        # joignable en ssh ». Le transport marchait ; c'est le diagnostic qui
        # était faux.
        sonde = dict(hote, sudo="")
        sonde_parent = dict(parent, sudo="") if parent else None
        while time.time() - debut < delai:
            code, _o = pve.run(sonde, "true", 60)
            if code == 0:
                return int(time.time() - debut)
            if sonde_parent is not None:
                code_parent, _p = pve.run(sonde_parent, "true", 60)
                if code_parent != 0:
                    self.dire(
                        f"      ✗ l'hôte {sonde_parent['target']} ne répond"
                        " plus : l'attente n'aboutira pas"
                    )
                    return None
            time.sleep(15)
        return None

    def sudo_pret(self, hote):
        """sudo répond-il sans mot de passe ? Nommé à part de ssh."""
        if self.dry_run:
            return True
        code, _o = pve.run(hote, "true", 60)
        return code == 0

    # ---------------------------------------------------------------- #
    # Les six étapes, les mêmes à chaque étage
    # ---------------------------------------------------------------- #
    def installer_proxmox(self, hote):
        """Envoie NOTRE script et l'exécute. Rend True si Proxmox est posé."""
        local = os.path.join(RACINE, "script/proxmox/install_proxmox.sh")
        distant = "/tmp/install_proxmox.sh"
        if self.dry_run:
            print(f"      scp {local} <hôte>:{distant}")
            print(f"      bash {distant}")
            return True
        argv = pve.ssh_argv(hote, "")[:-1]  # les options, sans la commande
        cible = argv[-1]
        options = argv[1:-1]
        res = subprocess.run(
            ["scp", "-q"] + options + [local, f"{cible}:{distant}"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if res.returncode:
            self.dire(f"      ✗ scp : {res.stderr.strip()[:200]}")
            return False
        # « bash » et non « sh » : le script porte « set -euo pipefail » et un
        # shebang bash. Sur Debian /bin/sh est dash, qui répond « set: Illegal
        # option -o pipefail » et sort à la PREMIÈRE ligne — vérifié. Chaque
        # étage aurait échoué sur l'installation, à tous les coups.
        code, _o = self.executer(
            dict(hote, sudo=""),
            f"bash {distant}",
            self.delai("install"),
            "install_proxmox.sh",
            montrer=True,
        )
        return code == 0

    def redemarrer_et_verifier(self, hote):
        """Redémarre, attend le retour, exige le noyau Proxmox.

        Le script pose le noyau sans redémarrer — lancé par ssh, un reboot
        couperait sa session et ferait passer l'installation pour un échec.
        Sans ce redémarrage, la machine reste sur le noyau cloud de Debian,
        dépouillé de tout netfilter : ni pont NAT, ni invité.
        """
        if self.dry_run:
            print("      reboot, puis btime changé ET *-pve dans uname -r")
            return True
        # L'instant de démarrage AVANT : le noyau seul ne prouve rien. Rejoué
        # sur un étage déjà installé, le script est idempotent et ne redémarre
        # pas ; vingt secondes après l'ordre, sshd répond encore et la machine
        # tourne DÉJÀ sur -pve. On validait donc un redémarrage qui n'avait pas
        # eu lieu, et l'étape suivante tombait sur une machine en train de
        # s'éteindre — avec un diagnostic sans rapport. Même piège que celui
        # corrigé dans le suivi d'installation, refait ici.
        _c, out = pve.run(dict(hote, sudo=""), "stat -c %Y /proc/1", 60)
        avant = pve.strip_ssh_noise(out).strip()
        pve.run(hote, "systemctl reboot", 60)
        debut = time.time()
        while time.time() - debut < self.delai("reboot"):
            time.sleep(20)
            code, out = pve.run(
                dict(hote, sudo=""), "uname -r; stat -c %Y /proc/1", 60
            )
            lignes = pve.strip_ssh_noise(out).strip().splitlines()
            if code or len(lignes) < 2:
                continue
            noyau, apres = lignes[0].strip(), lignes[-1].strip()
            if "-pve" not in noyau:
                continue
            if avant and apres == avant:
                continue  # elle n'a pas encore redémarré
            self.dire(
                f"      noyau {noyau} après {int(time.time() - debut)} s"
            )
            return True
        self.dire("      ✗ pas revenue sur un noyau -pve")
        return False

    def reparer_pmxcfs(self, hote):
        """Gel de cloud-init, /etc/hosts, unités, constat du montage."""
        if self.dry_run:
            print("      gel cloud-init + /etc/hosts + unités + montage")
            return True
        _c, out = pve.run(
            dict(hote, sudo=""), 'printf %s "$SSH_CONNECTION"', 30
        )
        ip = pve.ssh_server_ip(out)
        if not ip:
            self.dire("      ✗ adresse d'accès inconnue")
            return False
        for cmd, etiquette in (
            (pve.cloud_hosts_freeze_cmd(), "gel cloud-init"),
            (pve.hosts_repair_cmd(ip), "/etc/hosts"),
        ):
            code, sortie = self.executer(
                hote, cmd, self.delai("reparation"), etiquette
            )
            if code or "-KO" in pve.strip_ssh_noise(sortie):
                self.dire(f"      ✗ {etiquette}")
                return False
        # « pve_unit_cmd » joint le journal de l'unité à un échec — « la seule
        # façon de dire la cause à quelqu'un dont le seul accès à l'hôte est
        # cet outil », dit son propre commentaire. On le JETAIT : quand le
        # montage échouait ensuite, il ne restait qu'un « /etc/pve : ABSENT »
        # sans cause, et il fallait retourner sur la machine pour la chercher.
        echecs = []
        for unite in pve.PVE_UNITS:
            code, sortie = self.executer(
                hote, pve.pve_unit_cmd(unite, remonte=True), 300, unite
            )
            propre = pve.strip_ssh_noise(sortie)
            if code or "-KO" in propre:
                echecs.append((unite, propre))
        _c, out = self.executer(
            hote, pve.mount_wait_cmd(), self.delai("reparation"), "montage"
        )
        vu = pve.parse_mount_wait(out)
        self.dire(f"      /etc/pve : {vu['verdict']}")
        if vu["verdict"] != "MONTE":
            for unite, propre in echecs:
                self.dire(f"      ↳ {unite} : {propre.strip()[-400:]}")
            if not echecs:
                # Toutes debout et le montage absent : le dire, plutôt que de
                # laisser croire qu'on n'a pas regardé.
                self.dire("      ↳ toutes les unités PVE sont debout")
        return vu["verdict"] == "MONTE"

    def preparer_parent(self, parent):
        """Stockage, pont et réseau interne du parent, ou None.

        Les codes de retour des LECTURES sont regardés, et c'est tout le
        sujet ici. Ailleurs dans ce dépôt un code de retour ne prouve rien —
        celui d'une commande distante composée est celui du dernier maillon.
        Mais pour une lecture, il est la SEULE chose qui distingue « j'ai lu,
        il n'y a rien » de « je n'ai pas pu lire ».

        La différence n'est pas académique : de l'absence de pont on
        RECONFIGURE le réseau du parent. Un « ip link show » qui échoue — un
        hoquet ssh, un sudo pas encore prêt — se lisait « pas de pont », et on
        posait un pont et un NAT sur une machine qui en avait déjà un.
        """
        code, out = self.executer(
            parent,
            "pvesm status --content images",
            DELAIS["controle"],
            "pvesm",
        )
        if code and not self.dry_run:
            self.dire("      ✗ « pvesm status » a échoué : rien conclu")
            return None
        stockage = pve.pick_storage(pve.parse_storages(out))
        if not stockage and not self.dry_run:
            self.dire("      ✗ aucun stockage sur le parent")
            return None
        code, out = self.executer(
            parent,
            "ip -o link show type bridge",
            self.delai("controle"),
            "ponts",
        )
        if code and not self.dry_run:
            self.dire(
                "      ✗ liste des ponts illisible : on ne touche PAS au"
                " réseau du parent"
            )
            return None
        ponts = pve.parse_bridges(out)
        if not ponts:
            _c, nets = self.executer(
                parent, pve.USED_NETS_CMD, self.delai("controle"), "réseaux"
            )
            cidr = pve.pick_internal_cidr(nets) or pve.INTERNAL_CIDR
            _c, rt = self.executer(
                parent,
                "ip -o -4 route show default",
                DELAIS["controle"],
                "uplink",
            )
            trouve = re.search(r"dev\s+(\S+)", rt or "")
            uplink = trouve.group(1) if trouve else ""
            self.dire(f"      pont {cidr}, NAT par {uplink or '—'}")
            for cmd in pve.bridge_setup_cmds(cidr=cidr, uplink=uplink):
                code, _o = self.executer(
                    parent, cmd, DELAIS["reparation"], "pont"
                )
                if code and not self.dry_run:
                    return None
            ponts = [pve.INTERNAL_BRIDGE]
        _c, cfg = self.executer(
            parent,
            "cat /etc/network/interfaces",
            DELAIS["controle"],
            "interfaces",
        )
        # Le DNS de l'hôte. « --ipconfig0 » ne le porte PAS : une VM en
        # adresse fixe route mais ne résout rien, et install_proxmox.sh meurt
        # sur « apt update » sans que rien ne l'explique. Le rapport imputerait
        # à l'installation ce qui est un défaut de résolveur.
        _c, resolv = self.executer(
            parent, pve.RESOLV_CMD, self.delai("controle"), "resolv"
        )
        return (
            stockage or "local",
            ponts[0],
            pve.parse_bridge_config(cfg).get(ponts[0], {}),
            pve.parse_nameservers(resolv),
        )

    def creer_etage1(self, res):
        """Une VM locale, par la CLI QEMU/KVM."""
        nom = nom_etage(1)
        argv = [
            os.path.join(RACINE, ".venv.erplibre/bin/python"),
            os.path.join(RACINE, "script/qemu/deploy_qemu.py"),
            "--distro",
            DISTRO,
            "--name",
            nom,
            "--vcpus",
            str(res["vcpu"]),
            "--memory",
            str(res["ram"]),
            "--disk-size",
            f"{res['disque']}G",
        ]
        pub = cle_publique()
        if pub:
            argv += ["--ssh-key", pub]
        if self.dry_run:
            print("      " + " ".join(shlex.quote(a) for a in argv))
            return nom
        res_proc = subprocess.run(argv, timeout=DELAIS["creation"] * 3)
        if res_proc.returncode:
            self.dire("      ✗ la CLI QEMU/KVM a échoué")
            return None
        # L'entrée ~/.ssh/config, que la CLI n'écrit PAS. Sans elle,
        # « ssh deep-pve-1 » rend « Name or service not known » et la descente
        # attendait son plein délai avant de conclure « jamais joignable » —
        # sur une VM qui répondait parfaitement à son adresse. Vécu au premier
        # lancement réel.
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        ip = todo._qemu_vm_ip_now(nom)
        if not ip:
            self.dire(f"      ✗ {nom} créée mais sans adresse")
            return None
        self.dire(f"      {nom} : {ip}")
        prive = cle_publique()[:-4] if cle_publique() else None
        todo._write_ssh_config_entry(
            [nom], "erplibre", ip, identity_file=prive
        )
        return nom

    @staticmethod
    def uuid_libvirt(nom):
        """L'UUID du domaine `nom`, ou "". C'est lui qui l'identifie.

        Un nom se réutilise ; un UUID non. Sans lui, « --detruire » effaçait
        « deep-pve-1 » quel qu'il soit — la VM d'une descente précédente qu'on
        voulait garder, ou une machine sans rapport qui porte ce nom.
        """
        try:
            res = subprocess.run(
                ["sudo", "-n", "virsh", "domuuid", nom],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return "" if res.returncode else res.stdout.strip()

    def creer_enfant(self, parent, niveau, res, prepare, noter=None):
        """« qm create » sur le parent. Rend (vmid, adresse) ou (None, None).

        `noter` reçoit le VMID AVANT la première commande qui peut créer la
        VM. Sans lui, le VMID ne remontait qu'au RETOUR : une création qui
        échouait à la quatrième de ses six commandes — « qm resize » sur un
        stockage plein, par exemple — laissait une VM allumée et un disque
        alloué que le rapport ne nommait nulle part, donc que « --detruire »
        ne pouvait pas défaire.
        """
        stockage, pont, info_pont, dns = prepare
        mod = module_qemu()
        version = mod.DISTROS[DISTRO][1]
        code_img = mod.DISTROS[DISTRO][0][version][0]
        url = mod.image_url(DISTRO, code_img, "amd64", version)
        image = mod.default_image_name(DISTRO, code_img, "amd64", version)
        _c, out = self.executer(
            parent, "qm list", self.delai("controle"), "qm list"
        )
        vmid = pve.next_vmid(pve.parse_qm_list(out))
        ipconfig = pve.ipconfig_for(info_pont, vmid)
        adresse = pve.ip_from_ipconfig(ipconfig)
        # AVANT de télécharger l'image et de démarrer quoi que ce soit : sur un
        # pont relié au LAN, ipconfig_for rend « ip=dhcp » et l'adresse est
        # vide. Le contrôle venait après la création : on laissait une VM
        # allumée, un disque alloué, et une machine que --detruire ne
        # connaissait pas.
        if not adresse and self.dry_run:
            # En essai à blanc on n'a rien lu du parent : conclure « pas de
            # pont interne » serait une affirmation tirée d'une mesure qui
            # n'a pas eu lieu. On prend une adresse plausible pour dérouler
            # le plan jusqu'au bout.
            adresse = "10.10.10.150"
            ipconfig = f"ip={adresse}/24,gw=10.10.10.1"
        if not adresse:
            self.dire("      ✗ pas d'adresse fixe : le parent n'a pas de")
            self.dire("        pont interne, et l'enfant serait injoignable")
            return None, None
        spec = {
            "name": nom_etage(niveau),
            "storage": stockage,
            "image": image,
            "memory": res["ram"],
            "vcpus": res["vcpu"],
            "bridge": pont,
            "disk": f"{res['disque']}G",
            "user": "erplibre",
            "ipconfig": ipconfig,
            "sshkey_path": "/root/.ssh/longtest.pub",
            "nameservers": dns,
            "start": True,
        }
        # La clé publique doit être un FICHIER sur le parent : « --sshkeys »
        # n'accepte pas la clé en ligne.
        pub = cle_publique()
        if pub and not self.dry_run:
            with open(pub, encoding="utf-8") as fh:
                contenu = fh.read().strip()
            self.executer(
                parent,
                f"mkdir -p /root/.ssh && printf '%s\\n'"
                f" {shlex.quote(contenu)} > /root/.ssh/longtest.pub",
                DELAIS["controle"],
                "clé",
            )
        # Le VMID est annoncé MAINTENANT. Un numéro noté pour une VM qui
        # n'existera jamais ne coûte rien — « --detruire » lit « qm list » et
        # la dit absente — alors qu'une VM créée et non notée reste sur le
        # parent, invisible.
        if noter:
            noter(vmid)
        for cmd in [pve.image_fetch_cmd(url, image)] + pve.create_cmds(
            vmid, spec
        ):
            code, _o = self.executer(
                parent, cmd, self.delai("creation"), "qm create"
            )
            if code and not self.dry_run:
                return None, None
        return vmid, adresse

    # ---------------------------------------------------------------- #
    # La descente
    # ---------------------------------------------------------------- #
    def parcourir(self):
        parent = None
        parent_alias = ""
        for res in self.plan["niveaux"]:
            niveau = res["niveau"]
            self.niveau_courant = niveau
            debut = time.time()
            etage = {
                "niveau": niveau,
                "ressources": res,
                "etape": "creation",
                "ok": False,
            }
            self.dire(
                f"  ── étage {niveau} : {res['vcpu']} vCPU,"
                f" {res['ram']} Mo, {res['disque']} Go"
            )
            if niveau == 1:
                nom = self.creer_etage1(res)
                if not nom:
                    self.etages.append(etage)
                    self.interrompu = True
                    break
                alias = nom
                etage["nom"] = nom
                # L'UUID, et non le nom : c'est de lui que « --detruire » se
                # servira. Un nom se réutilise, un UUID non.
                etage["uuid"] = self.uuid_libvirt(nom)
                # Le domaine libvirt existe : le rapport doit exister aussi.
                self._sauver(etage)
            else:
                prepare = self.preparer_parent(parent)
                if not prepare:
                    etage["etape"] = "parent"
                    self.etages.append(etage)
                    self.interrompu = True
                    break

                def noter(
                    numero,
                    etage=etage,
                    parent_alias=parent_alias,
                    niveau=niveau,
                ):
                    etage["vmid"] = numero
                    etage["parent_alias"] = parent_alias
                    # Le nom est ÉCRIT, non déduit du numéro d'étage à la
                    # relecture : si nom_etage change un jour, un rapport
                    # ancien désignerait des machines qui ne sont pas les
                    # siennes.
                    etage["nom"] = nom_etage(niveau)
                    self._sauver(etage)

                vmid, adresse = self.creer_enfant(
                    parent, niveau, res, prepare, noter
                )
                if vmid is None:
                    self.etages.append(etage)
                    self.interrompu = True
                    break
                etage["vmid"] = vmid
                # Le parent est noté AVANT tout autre contrôle : c'est le seul
                # enregistrement de ce qu'on vient de créer, et --detruire s'en
                # sert. Sans lui, une VM abandonnée juste après « qm create »
                # n'était nommée nulle part.
                etage["parent_alias"] = parent_alias
                self._sauver(etage)
                alias = alias_etage(niveau, parent_alias)
                if not self.dry_run:
                    self.ecrire_alias(alias, adresse, parent_alias)
            cible = {"target": alias, "sudo": "sudo ", "jump": ""}
            etage["alias"] = alias

            etage["etape"] = "ssh"
            attente = self.attendre_ssh(cible, self.delai("ssh"), parent)
            if attente is None:
                self.dire("      ✗ jamais joignable en ssh")
                self.etages.append(etage)
                self.interrompu = True
                break
            etage["ssh_secondes"] = attente
            self.dire(f"      ssh après {attente} s")

            for etape, action in (
                ("install", lambda: self.installer_proxmox(cible)),
                ("reboot", lambda: self.redemarrer_et_verifier(cible)),
                ("pmxcfs", lambda: self.reparer_pmxcfs(cible)),
            ):
                etage["etape"] = etape
                self._sauver(etage)
                if not action():
                    self.etages.append(etage)
                    return self.rapport(interrompu=True)

            # En dry-run, aucune étape n'a été mesurée : les marquer
            # « atteintes » produisait un rapport indiscernable d'une vraie
            # réussite, JSON compris, et un code de sortie 0.
            etage["etape"] = "plan" if self.dry_run else "termine"
            etage["ok"] = not self.dry_run
            etage["secondes"] = int(time.time() - debut)
            self.etages.append(etage)
            self._sauver()
            self.dire(f"      ✓ étage {niveau} en {etage['secondes']} s")
            parent, parent_alias = cible, alias
        return self.rapport(interrompu=self.interrompu)

    def ecrire_alias(self, alias, adresse, parent_alias):
        """Une entrée ~/.ssh/config pour joindre l'enfant à travers le parent."""
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        prive = cle_publique()[:-4] if cle_publique() else None
        todo._write_ssh_config_entry(
            [alias],
            "erplibre",
            adresse,
            proxy_jump=parent_alias or None,
            identity_file=prive,
        )

    def _etat(self, interrompu, en_cours=None):
        """Le rapport, à cet instant. `en_cours` : l'étage pas encore rangé."""
        etages = list(self.etages)
        if en_cours is not None and en_cours not in etages:
            etages.append(en_cours)
        return {
            "demandee": self.plan["demandee"],
            "atteignable": self.plan["atteignable"],
            "atteinte": sum(1 for e in etages if e.get("ok")),
            "interrompu": interrompu,
            # Sans ce champ, un rapport d'essai à blanc se lisait comme une
            # descente réussie — et « --detruire » s'en servait.
            "dry_run": self.dry_run,
            "etages": etages,
        }

    def _sauver(self, en_cours=None):
        """Écrit le rapport PARTIEL, dès qu'une VM existe.

        Il ne s'écrivait qu'à la fin. Une descente tuée au quatrième étage —
        c'est arrivé — laissait quatre machines réelles et « --detruire »
        répondait « aucun rapport : rien à défaire » : le seul enregistrement
        du couple (alias du parent, VMID) mourait avec le processus. Il fallait
        alors les retrouver et les détruire à la main, c'est-à-dire par leur
        nom, ce que tout le reste de ce fichier s'applique à ne pas faire.

        Marqué « interrompu » jusqu'au bout : un rapport partiel ne doit jamais
        se lire comme une descente terminée.
        """
        if self.dry_run or not self.chemin_json:
            return
        temporaire = self.chemin_json + ".tmp"
        try:
            etat = self._etat(interrompu=True, en_cours=en_cours)
            # Le PID de la descente qui écrit : c'est ce qui distingue un
            # rapport ABANDONNÉ d'un rapport en cours d'écriture. Le rapport
            # final, lui, n'en porte pas — la descente est finie.
            etat["pid"] = os.getpid()
            with open(temporaire, "w", encoding="utf-8") as fh:
                json.dump(etat, fh, indent=2)
            os.replace(temporaire, self.chemin_json)
        except OSError as err:
            self.dire(f"      ⚠ rapport non écrit : {err}")

    def rapport(self, interrompu=False):
        etat = self._etat(interrompu)
        atteint = etat["atteinte"]
        print("")
        if self.dry_run:
            self.dire(
                f"  plan annoncé sur {len(self.etages)} étage(s) —"
                " rien n'a été créé"
            )
        else:
            self.dire(
                f"  profondeur atteinte : {atteint}"
                f" / {self.plan['demandee']}"
            )
            # Deux causes très différentes rendaient le même « 5 / 10 » : la
            # machine trop petite pour dix, ou un étage tombé en route. La
            # première n'est pas un défaut du code, la seconde si.
            if atteint == self.plan["atteignable"] < self.plan["demandee"]:
                self.dire(
                    f"  (plan borné à {self.plan['atteignable']} par le"
                    f" {self.plan['arret']} : tout le plan a tenu)"
                )
            elif atteint < self.plan["atteignable"]:
                self.dire(
                    f"  (le plan annonçait {self.plan['atteignable']} :"
                    " un étage est tombé, voir plus haut)"
                )
        for e in self.etages:
            if self.dry_run:
                marque, detail = "·", "plan"
            else:
                marque = "✓" if e["ok"] else "✗"
                detail = (
                    f"{e.get('secondes', '—')} s" if e["ok"] else e["etape"]
                )
            self.dire(f"    {marque} étage {e['niveau']:2d}  {detail}")
        return etat


def _lance_ce_script(pid):
    """`pid` exécute-t-il CE script — et non pas seulement le nomme-t-il ?

    Par ARGUMENT, jamais par sous-chaîne. Constaté sur cette machine : un
    « pgrep -f deep_proxmox.py » posé dans une boucle de surveillance donne un
    shell dont la ligne de commande contient le motif, et le contrôle comptait
    ce shell comme une descente — deux faux positifs sur trois. Un argument
    qui SE TERMINE par le nom du fichier, lui, ne peut venir que d'un
    interpréteur qu'on a lancé dessus.
    """
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as fh:
            arguments = fh.read().split(b"\0")
    except (OSError, ValueError):
        return False
    return any(a.endswith(b"deep_proxmox.py") for a in arguments)


def descente_vivante(pid):
    """Le processus `pid` est-il une descente EN COURS ?

    Le PID seul ne suffirait pas : les numéros se réutilisent, et rien ne dit
    qu'un rapport vieux d'une semaine ne porte pas le PID d'un shell
    d'aujourd'hui. La ligne de commande est donc lue aussi.
    """
    return bool(pid) and _lance_ce_script(pid)


def autre_deep_proxmox():
    """Les PID des AUTRES deep_proxmox.py vivants. Le sien est exclu.

    Le garde-fou du rapport — un PID dans le fichier — ne protège que les
    descentes lancées APRÈS son écriture : celle qui tournait déjà avait
    chargé l'ancien module en mémoire et n'écrira jamais de PID. Constaté sur
    une descente réelle de dix étages, à l'étage 4. Ce contrôle-ci ne dépend
    d'aucun rapport : détruire pendant qu'une descente tourne n'est jamais
    juste, quel que soit le rapport choisi.

    /proc plutôt que pgrep : « pgrep -f deep_proxmox » attrape le shell qui
    l'invoque, et on croit alors voir survivre un processus qui n'existe pas.
    """
    moi = os.getpid()
    vivants = []
    try:
        entrees = os.listdir("/proc")
    except OSError:
        return vivants
    for entree in entrees:
        if not entree.isdigit() or int(entree) == moi:
            continue
        if _lance_ce_script(entree):
            vivants.append(int(entree))
    return vivants


def dernier_rapport():
    """Le rapport le plus récent qui NOMME quelque chose à défaire, ou {}.

    C'est le SEUL enregistrement de ce que la descente a créé : un couple
    (alias du parent, VMID) par étage. Détruire d'après lui, et non d'après
    les noms, est toute la différence entre défaire son propre travail et
    effacer une machine qui se trouve porter un nom voisin.

    Deux rapports sont ÉCARTÉS, et chacun l'est pour un accident précis :

    * celui d'une descente VIVANTE. Depuis que le rapport s'écrit VM par VM,
      la descente en cours en a un sur le disque, et c'est le plus récent :
      « --detruire » aurait détruit l'arbre sous le processus qui installait
      encore, emportant des heures de mesure. Avant, la descente en cours
      n'avait aucun rapport et la question ne se posait pas — le correctif a
      créé le danger.

    * celui qui n'a RIEN créé. Un second lancement qui meurt à l'étage 1 —
      « le disque existe déjà » — écrit un rapport vide sous un horodatage
      plus tardif. Il masquait le partiel qui nommait les VM réelles :
      « 0 VM imbriquée(s) », puis « virsh undefine --remove-all-storage » sur
      l'étage 1, dont le disque contient les étages 2 et suivants — jamais
      arrêtés, jamais nommés.
    """
    dossier = os.path.expanduser("~/.erplibre/longtest")
    try:
        fichiers = sorted(
            f for f in os.listdir(dossier) if f.endswith(".json")
        )
    except OSError:
        return {}
    for nom in reversed(fichiers):
        chemin = os.path.join(dossier, nom)
        try:
            with open(chemin, encoding="utf-8") as fh:
                rapport = json.load(fh)
        except (OSError, ValueError):
            continue
        if rapport.get("dry_run"):
            continue  # un plan n'a rien créé
        if descente_vivante(rapport.get("pid")):
            dire(f"  ⏳ descente EN COURS ({rapport['pid']}) : {nom} ignoré")
            continue
        if not (rapport.get("etages") or []):
            continue  # rien créé : ne pas masquer un rapport qui nomme des VM
        rapport["fichier"] = chemin
        return rapport
    return {}


def a_defaire(rapport):
    """[(niveau, parent_alias, vmid, nom)] du plus PROFOND au plus haut.

    Trié sur le niveau LU dans le rapport, pas déduit du nom. La version
    d'avant comptait les « + » de l'alias — or `alias_etage` remplace le « + »
    du parent par un « - », donc chaque alias en portait exactement UN et le
    tri ne triait rien. La destruction partait du plus HAUT : « qm destroy
    --purge » sur l'étage 2 emportait le disque contenant les étages 3 et
    suivants, sans les avoir arrêtés ni nommés.
    """
    etages = [
        e
        for e in (rapport.get("etages") or [])
        if e.get("vmid") and e.get("parent_alias")
    ]
    etages.sort(key=lambda e: -int(e["niveau"]))
    return [
        (
            int(e["niveau"]),
            e["parent_alias"],
            int(e["vmid"]),
            # Le nom ÉCRIT par la descente. Le déduire du numéro d'étage
            # supposait que nom_etage ne changera jamais — un rapport ancien
            # aurait alors nommé des machines qui ne sont pas les siennes.
            e.get("nom") or nom_etage(int(e["niveau"])),
        )
        for e in etages
    ]


def detruire_une(parent_alias, vmid, nom, journal):
    """Arrête puis détruit UNE VM, par son VMID. Rend True si elle a disparu.

    Par le VMID et par égalité stricte du nom : un filtre par sous-chaîne
    aurait pris une « deep-pve-lab » de production, et « --purge » emporte les
    disques ET les entrées de sauvegarde.

    L'arrêt est CONSTATÉ avant la destruction : « qm stop » rend la main dès
    que la tâche est lancée, et sur un hyperviseur imbriqué mesuré 36 fois
    plus lent, « qm destroy » arrivait alors que la VM tournait encore et
    refusait avec « VM is running ».
    """
    parent = {"target": parent_alias, "sudo": "sudo ", "jump": ""}
    code, out = pve.run(parent, "qm list", 180)
    if code:
        dire(f"    ✗ {parent_alias} injoignable : rien touché", journal)
        return False
    presentes = {
        int(v["vmid"]): (v.get("name") or "") for v in pve.parse_qm_list(out)
    }
    if vmid not in presentes:
        dire(f"    — {vmid} déjà absente de {parent_alias}", journal)
        return True
    if presentes[vmid] != nom:
        dire(
            f"    ✗ {vmid} sur {parent_alias} s'appelle"
            f" « {presentes[vmid]} », pas « {nom} » : rien touché",
            journal,
        )
        return False
    pve.run(parent, f"qm stop {vmid} --skiplock 1 || true", 300)
    for _ in range(20):
        _c, etat = pve.run(parent, f"qm status {vmid}", 120)
        if "stopped" in pve.strip_ssh_noise(etat):
            break
        time.sleep(6)
    code, out = pve.run(parent, f"qm destroy {vmid} --purge 1", 600)
    if code:
        dire(f"    ✗ qm destroy {vmid} : code {code}", journal)
        for ligne in pve.strip_ssh_noise(out).strip().splitlines()[-3:]:
            dire(f"      {ligne}", journal)
        return False
    dire(f"    ✓ {nom} ({vmid}) sur {parent_alias}", journal)
    return True


def detruire_etage1(journal, dry_run=False, attendu=None, nom=None):
    """Le domaine libvirt du premier étage — le SEUL qui en soit un.

    La boucle d'avant tournait sur trente niveaux avec une condition morte, et
    sa branche « niveau == 1 » était vraie même quand la descente n'avait
    jamais rien créé : « virsh undefine --remove-all-storage » partait alors
    sur un domaine qui pouvait être n'importe quoi, sortie capturée, sans un
    mot.

    `attendu` : l'UUID que le rapport a noté à la création. C'est LUI qui
    identifie la machine, pas son nom. Un nom se réutilise — la VM d'une
    descente précédente qu'on voulait garder, ou une machine sans rapport qui
    porte celui-là — et « --remove-all-storage » efface un disque pour de bon.
    Un rapport ancien n'a pas d'UUID : on procède alors comme avant, par le
    nom, faute de mieux, mais en le disant.
    """
    nom = nom or nom_etage(1)
    existe = subprocess.run(
        ["sudo", "-n", "virsh", "dominfo", nom],
        capture_output=True,
        text=True,
    )
    if existe.returncode:
        dire(f"    — {nom} : aucun domaine libvirt", journal)
        return True
    if attendu:
        vu = Descente.uuid_libvirt(nom)
        if vu != attendu:
            dire(
                f"    ✗ {nom} : UUID {vu or '—'} au lieu de {attendu} —"
                " ce n'est PAS notre machine, rien touché",
                journal,
            )
            return False
    else:
        dire(
            f"    ⚠ {nom} : rapport sans UUID, identifié par son NOM", journal
        )
    if dry_run:
        dire(
            f"    [à blanc] virsh undefine {nom} --remove-all-storage", journal
        )
        return True
    subprocess.run(
        ["sudo", "virsh", "destroy", nom], capture_output=True, text=True
    )
    res = subprocess.run(
        [
            "sudo",
            "virsh",
            "undefine",
            nom,
            "--nvram",
            "--remove-all-storage",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode:
        dire(
            f"    ✗ virsh undefine {nom} : {res.stderr.strip()[:160]}", journal
        )
        return False
    dire(f"    ✓ {nom} (libvirt)", journal)
    return True


def detruire(journal=None, dry_run=False):
    """Défait ce que le DERNIER rapport dit avoir créé, du plus profond.

    Rien d'autre. La version d'avant prenait toute entrée ~/.ssh/config dont
    le nom contenait « deep-pve », puis sur son rebond détruisait toute VM
    dont le nom contenait « deep-pve » — une machine de labo appelée
    « deep-pve-lab » sur un hyperviseur de production tombait dedans.
    """
    # Avant tout : refuser tant qu'une descente tourne. Elle installe encore
    # sur les machines qu'on s'apprête à détruire, et son rapport peut être
    # celui qu'on vient de choisir.
    autres = autre_deep_proxmox()
    if autres:
        dire(
            f"  ⛔ une descente tourne ({', '.join(map(str, autres))}) :"
            " rien ne sera détruit.",
            journal,
        )
        dire("  Attendre qu'elle finisse, ou l'arrêter d'abord.", journal)
        return 1
    rapport = dernier_rapport()
    if not rapport:
        dire("  aucun rapport de descente : rien à défaire.", journal)
        dire(
            "  (les entrées ~/.ssh/config orphelines : menu de nettoyage)",
            journal,
        )
        return 0
    liste = a_defaire(rapport)
    dire(f"  rapport : {rapport.get('fichier')}", journal)
    dire(f"  {len(liste)} VM imbriquée(s) + l'étage 1 :", journal)
    for niveau, parent_alias, vmid, nom in liste:
        dire(
            f"    étage {niveau:2d}  {nom} ({vmid}) sur {parent_alias}",
            journal,
        )
    etage1_nom = next(
        (
            e.get("nom")
            for e in (rapport.get("etages") or [])
            if int(e.get("niveau", 0)) == 1
        ),
        None,
    )
    dire(f"    étage  1  {etage1_nom or nom_etage(1)} (libvirt)", journal)
    if dry_run:
        dire("\n  --dry-run : rien ne sera détruit.", journal)
        return 0
    # Une confirmation, parce que « --purge » emporte les disques et que le
    # menu lançait cette option d'une seule touche.
    reponse = input("\n  Détruire tout cela ? (tapez OUI) : ").strip()
    if reponse != "OUI":
        dire("  annulé.", journal)
        return 1
    faits = sum(
        1
        for niveau, parent_alias, vmid, nom in liste
        if detruire_une(parent_alias, vmid, nom, journal)
    )
    # « if not … : faits -= 1 » : un succès de l'étage 1 n'ajoutait RIEN,
    # alors que le total est len(liste) + 1. Le décompte était décalé de un
    # dans TOUS les cas — une destruction complète annonçait « il reste des
    # machines » et sortait 1, si bien que le seul avertissement censé
    # prévenir qu'un disque de plusieurs dizaines de Go reste alloué
    # s'affichait toujours, et qu'on apprenait à ne plus le lire.
    etage1 = next(
        (
            e
            for e in (rapport.get("etages") or [])
            if int(e.get("niveau", 0)) == 1
        ),
        {},
    )
    racine = detruire_etage1(
        journal, attendu=etage1.get("uuid"), nom=etage1.get("nom")
    )
    if racine:
        faits += 1
    retirer_alias(rapport, journal)
    if racine:
        # L'étage 1 est un DISQUE, et tout le reste vit dedans. « virsh
        # undefine --remove-all-storage » l'a effacé : les étages injoignables
        # — leur parent était éteint — ont disparu avec, qu'on ait pu leur
        # parler ou non. Annoncer « il reste des machines » dans ce cas était
        # faux dans l'autre sens, et un avertissement faux ne se lit plus.
        reste = len(liste) + 1 - faits
        dire(
            f"\n  {len(liste) + 1} / {len(liste) + 1} défait(s)."
            + (
                f"  ({reste} injoignable(s), emporté(s) avec le disque de"
                " l'étage 1.)"
                if reste
                else ""
            ),
            journal,
        )
        return 0
    dire(
        f"\n  {faits} / {len(liste) + 1} défait(s)."
        "  ⚠ l'étage 1 est DEBOUT : ce qu'il contient vit encore.",
        journal,
    )
    return 1


def retirer_alias(rapport, journal=None):
    """Retire de ~/.ssh/config les entrées de la descente défaite.

    Sans cela, elles survivaient aux machines : des entrées mortes dont le
    ProxyJump désigne un hôte qui n'existe plus, et qu'on retrouve plus tard
    sans savoir à quoi elles servaient.
    """
    alias = []
    for etage in rapport.get("etages") or []:
        nom = etage.get("alias")
        if not nom:
            # L'étage abandonné avant l'écriture de son alias : le calculer,
            # il est déterminé par (niveau, alias du parent).
            parent = etage.get("parent_alias")
            if parent:
                nom = alias_etage(int(etage["niveau"]), parent)
        if nom and nom not in alias:
            alias.append(nom)
    if not alias:
        return
    try:
        from script.todo.todo import TODO

        TODO.__new__(TODO)._write_ssh_config_entry(
            [], "erplibre", "", also_drop=tuple(alias)
        )
    except Exception as err:  # noqa: BLE001 - jamais bloquer la destruction
        dire(f"  ⚠ entrées ~/.ssh/config non retirées : {err}", journal)


def principal(argv=None):
    parseur = argparse.ArgumentParser(
        description="Jusqu'à quel étage un Proxmox dans un Proxmox tient-il ?"
    )
    # Trois par défaut, et c'est une MESURE, pas une prudence : les trois
    # premiers étages coûtent 280, 495 et 1 064 secondes — une demi-heure en
    # tout. Le quatrième en a coûté 7 h 18 d'installation et 4 h 20 d'amorçage
    # sur la même machine. Un défaut à dix promettait ce qu'aucune machine ne
    # peut tenir ; la profondeur reste un paramètre, et c'est à qui la demande
    # de savoir ce qu'il demande.
    parseur.add_argument("--depth", type=int, default=3)
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument("--detruire", action="store_true")
    args = parseur.parse_args(argv)

    journal = os.path.expanduser(
        f"~/.erplibre/longtest/deep-pve-{time.strftime('%Y%m%d-%H%M%S')}.log"
    )
    os.makedirs(os.path.dirname(journal), exist_ok=True)
    if args.detruire:
        # « --dry-run » était ignoré ici : la prudence naturelle avant une
        # destruction détruisait pour de vrai.
        return detruire(journal, dry_run=args.dry_run)

    coeurs, ram, disque = capacite_hote()
    print(
        f"\n  machine : {coeurs} cœurs, {ram} Mo disponibles,"
        f" {disque} Go de disque"
    )
    plan = nesting.nesting_plan(args.depth, coeurs, ram, disque)
    print(f"\n  {'étage':>5}  {'vCPU':>4}  {'RAM':>9}  {'disque':>8}")
    for n in plan["niveaux"]:
        print(
            f"  {n['niveau']:>5}  {n['vcpu']:>4}  {n['ram']:>6} Mo"
            f"  {n['disque']:>5} Go"
        )
    if plan["arret"]:
        # Les TROIS plafonds, pas seulement celui qui borne : sans eux on
        # ajoute la ressource nommée sans savoir de combien, ni laquelle
        # bornera ensuite.
        plafonds = " · ".join(
            f"{nom} {valeur}" for nom, valeur in plan["plafonds"].items()
        )
        print(
            f"\n  ⚠ demandée {plan['demandee']}, atteignable"
            f" {plan['atteignable']} — c'est le {plan['arret']} qui borne"
            f"\n    profondeur permise par chaque ressource : {plafonds}"
        )
    if not plan["niveaux"]:
        if args.depth < 1:
            print(f"\n  profondeur demandée : {args.depth} — rien à faire.\n")
            return 0
        print("\n  ✗ pas même un étage ne tient sur cette machine.\n")
        return 1
    print(f"\n  journal : {journal}")
    if args.dry_run:
        print("  --dry-run : rien ne sera créé.\n")
    chemin = journal[:-4] + ("-dryrun.json" if args.dry_run else ".json")
    descente = Descente(plan, journal, args.dry_run, chemin)
    rapport = descente.parcourir()
    with open(chemin, "w", encoding="utf-8") as fh:
        json.dump(rapport, fh, indent=2)
    print(f"\n  rapport : {chemin}\n")
    # En essai à blanc, c'est le PLAN qui est complet ou non — aucune
    # profondeur n'a été atteinte. Hors essai, « non nul » ne suffisait pas :
    # une descente morte au deuxième étage sur dix rendait 0.
    if args.dry_run:
        return 0 if rapport["atteignable"] == rapport["demandee"] else 1
    return 0 if rapport["atteinte"] == rapport["demandee"] else 1


if __name__ == "__main__":
    sys.exit(principal())
