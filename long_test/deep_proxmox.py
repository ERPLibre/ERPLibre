#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Jusqu'à quel étage un Proxmox dans un Proxmox tient-il ?

Ce n'est pas un test unitaire : il crée de vraies machines et prend des
HEURES. Il vit donc hors de `test/`, que le lanceur unitaire balaie.

Ce qu'il établit, et pourquoi cela valait un script : la profondeur
d'imbrication praticable ne se déduit pas, elle se mesure. Mesuré ici, sur une
machine à 28 cœurs : trois étages coûtent 34 minutes, et le quatrième 4 h 20
d'amorçage plus 7 h 18 d'installation. Tout y est 15 à 30 fois plus lent — et
c'est là que les fabricants cessent de documenter l'imbrication.

La descente et ce qu'elle sait sont dans `descente.py`, partagés avec
`deep_qemu.py`. Ce fichier-ci n'a que les VERBES de Proxmox : « qm create »
chez le parent, install_proxmox.sh, le noyau -pve, pmxcfs debout, un stockage
capable d'accueillir l'étage suivant.

Il envoie NOTRE install_proxmox.sh par scp au lieu de laisser la VM cloner le
dépôt : c'est notre code qu'on veut éprouver, et le dépôt distant est souvent
en retard sur le checkout — un correctif absent du distant a fait « revenir »
le même défaut sur trois VM de suite.

  ./long_test/deep_proxmox.py                  # trois étages, ~34 minutes
  ./long_test/deep_proxmox.py --depth 5        # en demander plus, sciemment
  ./long_test/deep_proxmox.py --dry-run        # le plan, rien de créé
  ./long_test/deep_proxmox.py --detruire       # défaire ce qui a été posé
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
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from script.proxmox import nesting  # noqa: E402
from script.proxmox import proxmox_deploy as pve  # noqa: E402

import descente  # noqa: E402
from descente import (  # noqa: E402,F401
    DELAIS,
    _lance_une_descente,
    Famille,
    a_defaire,
    alias_etage as _alias_etage,
    autre_descente,
    capacite_hote,
    cle_publique,
    dernier_rapport,
    descente_vivante,
    detruire,
    detruire_etage1,
    dire,
    identite_de,
    module_qemu,
    nom_etage as _nom_etage,
    retirer_alias,
)

# L'image des étages imbriqués. Debian parce que install_proxmox.sh s'installe
# SUR une Debian — Proxmox ne publie pas d'image cloud.
DISTRO = "proxmox"
NOM_BASE = "deep-pve"
OUTIL = "deep_proxmox"


def nom_etage(niveau):
    return _nom_etage(niveau, NOM_BASE)


def alias_etage(niveau, parent_alias):
    return _alias_etage(niveau, parent_alias, NOM_BASE)


class Descente(descente.Descente):
    """Les verbes de Proxmox. Le reste est dans `descente.Descente`."""

    OUTIL = OUTIL
    NOM_BASE = NOM_BASE
    DISTRO = DISTRO

    def noyau_convient(self, noyau):
        """Le noyau Proxmox, et pas celui de Debian.

        Sans lui la machine reste sur le noyau cloud, dépouillé de tout
        netfilter : ni pont NAT, ni invité.
        """
        return "-pve" in noyau

    def installer(self, hote):
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
    def remettre_debout(self, hote):
        """Les unités PVE, puis le CONSTAT que /etc/pve est monté."""
        if self.dry_run:
            print("      unités PVE + montage de /etc/pve")
            return True
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

    def controler(self, hote):
        """Ce parent peut-il héberger l'étage suivant ?

        Sixième étape, et elle manquait : le contrôle du stockage était celui
        du DÉBUT de l'étage suivant, si bien qu'un étage marqué « terminé »
        pouvait n'avoir aucun stockage capable d'accueillir une image — et le
        compteur d'étages atteints mentait d'autant.
        """
        if self.dry_run:
            print("      pvesm status : un stockage pour les images")
            return True
        code, out = self.executer(
            hote,
            "pvesm status --content images",
            DELAIS["controle"],
            "pvesm",
        )
        if code:
            self.dire("      ✗ « pvesm status » a échoué : rien conclu")
            return False
        stockage = pve.pick_storage(pve.parse_storages(out))
        if not stockage:
            self.dire("      ✗ aucun stockage pour les images")
            return False
        self.dire(f"      stockage : {stockage}")
        return True


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


FAMILLE = Famille(OUTIL, NOM_BASE, detruire_une)


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
        return detruire(FAMILLE, journal, dry_run=args.dry_run)

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
