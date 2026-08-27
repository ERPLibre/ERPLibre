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

    def attendre_ssh(self, hote, delai):
        """Attend que la machine réponde. Rend les secondes, ou None.

        Des connexions COURTES successives : cloud-init régénère les clés
        d'hôte et redémarre sshd au premier démarrage, ce qui tuerait une
        session longue.
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
        while time.time() - debut < delai:
            code, _o = pve.run(sonde, "true", 60)
            if code == 0:
                return int(time.time() - debut)
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
        for unite in pve.PVE_UNITS:
            self.executer(
                hote, pve.pve_unit_cmd(unite, remonte=True), 300, unite
            )
        _c, out = self.executer(
            hote, pve.mount_wait_cmd(), self.delai("reparation"), "montage"
        )
        vu = pve.parse_mount_wait(out)
        self.dire(f"      /etc/pve : {vu['verdict']}")
        return vu["verdict"] == "MONTE"

    def preparer_parent(self, parent):
        """Stockage, pont et réseau interne du parent, ou None."""
        _c, out = self.executer(
            parent,
            "pvesm status --content images",
            DELAIS["controle"],
            "pvesm",
        )
        stockage = pve.pick_storage(pve.parse_storages(out))
        if not stockage and not self.dry_run:
            self.dire("      ✗ aucun stockage sur le parent")
            return None
        _c, out = self.executer(
            parent,
            "ip -o link show type bridge",
            self.delai("controle"),
            "ponts",
        )
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

    def creer_enfant(self, parent, niveau, res, prepare):
        """« qm create » sur le parent. Rend (vmid, adresse) ou (None, None)."""
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
                # Le domaine libvirt existe : le rapport doit exister aussi.
                self._sauver(etage)
            else:
                prepare = self.preparer_parent(parent)
                if not prepare:
                    etage["etape"] = "parent"
                    self.etages.append(etage)
                    self.interrompu = True
                    break
                vmid, adresse = self.creer_enfant(parent, niveau, res, prepare)
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
            attente = self.attendre_ssh(cible, self.delai("ssh"))
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
            with open(temporaire, "w", encoding="utf-8") as fh:
                json.dump(
                    self._etat(interrompu=True, en_cours=en_cours),
                    fh,
                    indent=2,
                )
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


def dernier_rapport():
    """Le rapport JSON le plus récent, ou {}.

    C'est le SEUL enregistrement de ce que la descente a créé : un couple
    (alias du parent, VMID) par étage. Détruire d'après lui, et non d'après
    les noms, est toute la différence entre défaire son propre travail et
    effacer une machine qui se trouve porter un nom voisin.
    """
    dossier = os.path.expanduser("~/.erplibre/longtest")
    try:
        fichiers = sorted(
            f for f in os.listdir(dossier) if f.endswith(".json")
        )
    except OSError:
        return {}
    for nom in reversed(fichiers):
        try:
            with open(os.path.join(dossier, nom), encoding="utf-8") as fh:
                rapport = json.load(fh)
        except (OSError, ValueError):
            continue
        if rapport.get("dry_run"):
            continue  # un plan n'a rien créé
        rapport["fichier"] = os.path.join(dossier, nom)
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
            nom_etage(int(e["niveau"])),
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


def detruire_etage1(journal, dry_run=False):
    """Le domaine libvirt du premier étage — le SEUL qui en soit un.

    La boucle d'avant tournait sur trente niveaux avec une condition morte, et
    sa branche « niveau == 1 » était vraie même quand la descente n'avait
    jamais rien créé : « virsh undefine --remove-all-storage » partait alors
    sur un domaine qui pouvait être n'importe quoi, sortie capturée, sans un
    mot.
    """
    nom = nom_etage(1)
    existe = subprocess.run(
        ["sudo", "-n", "virsh", "dominfo", nom],
        capture_output=True,
        text=True,
    )
    if existe.returncode:
        dire(f"    — {nom} : aucun domaine libvirt", journal)
        return True
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
    dire(f"    étage  1  {nom_etage(1)} (libvirt)", journal)
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
    if not detruire_etage1(journal):
        faits -= 1
    dire(
        f"\n  {faits} / {len(liste) + 1} défait(s)."
        + (
            ""
            if faits == len(liste) + 1
            else "  ⚠ il reste des machines : voir plus haut."
        ),
        journal,
    )
    return 0 if faits == len(liste) + 1 else 1


def principal(argv=None):
    parseur = argparse.ArgumentParser(
        description="Jusqu'à quel étage un Proxmox dans un Proxmox tient-il ?"
    )
    parseur.add_argument("--depth", type=int, default=10)
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
        print(
            f"\n  ⚠ demandée {plan['demandee']}, atteignable"
            f" {plan['atteignable']} — manque de {plan['arret']}"
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
