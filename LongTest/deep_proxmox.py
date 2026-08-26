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

    def __init__(self, plan, journal, dry_run=False):
        self.plan = plan
        self.journal = journal
        self.dry_run = dry_run
        self.etages = []

    def dire(self, msg):
        dire(msg, self.journal)

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
        while time.time() - debut < delai:
            code, _o = pve.run(hote, "true", 30)
            if code == 0:
                return int(time.time() - debut)
            time.sleep(15)
        return None

    # ---------------------------------------------------------------- #
    # Les six étapes, les mêmes à chaque étage
    # ---------------------------------------------------------------- #
    def installer_proxmox(self, hote):
        """Envoie NOTRE script et l'exécute. Rend True si Proxmox est posé."""
        local = os.path.join(RACINE, "script/proxmox/install_proxmox.sh")
        distant = "/tmp/install_proxmox.sh"
        if self.dry_run:
            print(f"      scp {local} <hôte>:{distant}")
            print(f"      sh {distant}")
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
        code, _o = self.executer(
            dict(hote, sudo=""),
            f"sh {distant}",
            DELAIS["install"],
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
            print("      reboot puis attente de *-pve dans uname -r")
            return True
        pve.run(hote, "systemctl reboot", 60)
        debut = time.time()
        while time.time() - debut < DELAIS["reboot"]:
            time.sleep(20)
            code, out = pve.run(dict(hote, sudo=""), "uname -r", 30)
            noyau = pve.strip_ssh_noise(out).strip()
            if code == 0 and "-pve" in noyau:
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
                hote, cmd, DELAIS["reparation"], etiquette
            )
            if code or "-KO" in pve.strip_ssh_noise(sortie):
                self.dire(f"      ✗ {etiquette}")
                return False
        for unite in pve.PVE_UNITS:
            self.executer(
                hote, pve.pve_unit_cmd(unite, remonte=True), 300, unite
            )
        _c, out = self.executer(
            hote, pve.mount_wait_cmd(), DELAIS["reparation"], "montage"
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
            parent, "ip -o link show type bridge", DELAIS["controle"], "ponts"
        )
        ponts = pve.parse_bridges(out)
        if not ponts:
            _c, nets = self.executer(
                parent, pve.USED_NETS_CMD, DELAIS["controle"], "réseaux"
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
        return (
            stockage or "local",
            ponts[0],
            pve.parse_bridge_config(cfg).get(ponts[0], {}),
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
        return nom

    def creer_enfant(self, parent, niveau, res, prepare):
        """« qm create » sur le parent. Rend (vmid, adresse) ou (None, None)."""
        stockage, pont, info_pont = prepare
        mod = module_qemu()
        version = mod.DISTROS[DISTRO][1]
        code_img = mod.DISTROS[DISTRO][0][version][0]
        url = mod.image_url(DISTRO, code_img, "amd64", version)
        image = mod.default_image_name(DISTRO, code_img, "amd64", version)
        _c, out = self.executer(
            parent, "qm list", DELAIS["controle"], "qm list"
        )
        vmid = pve.next_vmid(pve.parse_qm_list(out))
        ipconfig = pve.ipconfig_for(info_pont, vmid)
        adresse = pve.ip_from_ipconfig(ipconfig)
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
                parent, cmd, DELAIS["creation"], "qm create"
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
                    break
                alias = nom
            else:
                prepare = self.preparer_parent(parent)
                if not prepare:
                    etage["etape"] = "parent"
                    self.etages.append(etage)
                    break
                vmid, adresse = self.creer_enfant(parent, niveau, res, prepare)
                if vmid is None:
                    self.etages.append(etage)
                    break
                etage["vmid"] = vmid
                alias = alias_etage(niveau, parent_alias)
                if not self.dry_run:
                    if not adresse:
                        # Sur un pont interne l'adresse est FIXE et dérivée du
                        # VMID. Vide, c'est que le parent n'a pas de pont
                        # interne — écrire un alias sans HostName donnerait
                        # une entrée qui ne mène nulle part.
                        self.dire("      ✗ pas d'adresse fixe pour l'enfant")
                        etage["etape"] = "adresse"
                        self.etages.append(etage)
                        break
                    self.ecrire_alias(alias, adresse, parent_alias)
            cible = {"target": alias, "sudo": "sudo ", "jump": ""}
            etage["alias"] = alias

            etage["etape"] = "ssh"
            attente = self.attendre_ssh(cible, DELAIS["ssh"])
            if attente is None:
                self.dire("      ✗ jamais joignable en ssh")
                self.etages.append(etage)
                break
            etage["ssh_secondes"] = attente
            self.dire(f"      ssh après {attente} s")

            for etape, action in (
                ("install", lambda: self.installer_proxmox(cible)),
                ("reboot", lambda: self.redemarrer_et_verifier(cible)),
                ("pmxcfs", lambda: self.reparer_pmxcfs(cible)),
            ):
                etage["etape"] = etape
                if not action():
                    self.etages.append(etage)
                    return self.rapport(interrompu=True)

            etage["etape"] = "termine"
            etage["ok"] = True
            etage["secondes"] = int(time.time() - debut)
            self.etages.append(etage)
            self.dire(f"      ✓ étage {niveau} en {etage['secondes']} s")
            parent, parent_alias = cible, alias
        return self.rapport()

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

    def rapport(self, interrompu=False):
        atteint = sum(1 for e in self.etages if e["ok"])
        print("")
        self.dire(
            f"  profondeur atteinte : {atteint} / {self.plan['demandee']}"
        )
        for e in self.etages:
            marque = "✓" if e["ok"] else "✗"
            detail = f"{e.get('secondes', '—')} s" if e["ok"] else e["etape"]
            self.dire(f"    {marque} étage {e['niveau']:2d}  {detail}")
        return {
            "demandee": self.plan["demandee"],
            "atteignable": self.plan["atteignable"],
            "atteinte": atteint,
            "interrompu": interrompu,
            "etages": self.etages,
        }


def detruire(journal=None):
    """Défait ce que la descente a posé, du plus profond au plus haut.

    Du plus profond : détruire un parent d'abord emporterait ses enfants sans
    qu'on ait pu les nommer, et laisserait des entrées ssh vers rien.
    """
    from script.todo.todo import TODO

    hosts = [h for h in TODO._ssh_config_hosts() if NOM_BASE in h]
    hosts.sort(key=lambda h: -h.count("+"))
    dire(f"  {len(hosts)} entrée(s) ssh à défaire", journal)
    for alias in hosts:
        bloc = TODO._ssh_config_block(alias)
        saut = (bloc or {}).get("proxyjump")
        if saut:
            parent = {"target": saut, "sudo": "sudo ", "jump": ""}
            _c, out = pve.run(parent, "qm list", 120)
            for vm in pve.parse_qm_list(out):
                if NOM_BASE in (vm.get("name") or ""):
                    dire(f"    qm destroy {vm['vmid']} sur {saut}", journal)
                    pve.run(
                        parent,
                        f"qm stop {vm['vmid']} --skiplock 1 || true;"
                        f" qm destroy {vm['vmid']} --purge 1",
                        300,
                    )
    for niveau in range(1, 30):
        nom = nom_etage(niveau)
        if nom in hosts or niveau == 1:
            subprocess.run(
                ["sudo", "virsh", "destroy", nom],
                capture_output=True,
            )
            subprocess.run(
                [
                    "sudo",
                    "virsh",
                    "undefine",
                    nom,
                    "--nvram",
                    "--remove-all-storage",
                ],
                capture_output=True,
            )
    dire(
        "  ✓ défait. Les entrées ssh orphelines : menu de nettoyage.", journal
    )


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
        detruire(journal)
        return 0

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
        print("\n  ✗ pas même un étage ne tient sur cette machine.\n")
        return 1
    print(f"\n  journal : {journal}")
    if args.dry_run:
        print("  --dry-run : rien ne sera créé.\n")
    descente = Descente(plan, journal, args.dry_run)
    rapport = descente.parcourir()
    chemin = journal[:-4] + ".json"
    with open(chemin, "w", encoding="utf-8") as fh:
        json.dump(rapport, fh, indent=2)
    print(f"\n  rapport : {chemin}\n")
    return 0 if rapport["atteinte"] else 1


if __name__ == "__main__":
    sys.exit(principal())
