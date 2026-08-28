#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Jusqu'à quel étage une QEMU dans une QEMU tient-elle ?

Le pendant de `deep_proxmox.py`, et sa raison d'être : le ralentissement du
quatrième étage vient du PROCESSEUR — de ce que coûte une sortie de VM sous
pagination imbriquée — mais le coût par étage, lui, vient de ce qu'on installe.
Un nœud Proxmox pose un noyau, corosync, ceph et une interface web ; un hôte
libvirt nu pose libvirtd et qemu-kvm. Les deux mesures ensemble séparent ce qui
tient au matériel de ce qui tient à la pile, deux choses que la seule mesure
Proxmox confond.

CE QUE CE TEST DOIT PROUVER AVANT DE MESURER

`deploy_qemu.py` ne passe jamais « --cpu host-passthrough » : il s'en remet au
défaut de virt-install. Et quand /dev/kvm manque, il n'échoue pas — il pose
« --virt-type qemu », avertit sur une ligne, et crée une VM ENTIÈREMENT ÉMULÉE.
Un étage émulé démarre en sept minutes et demie au lieu de quelques secondes,
et rien dans le code de retour ne le dit.

Sans garde, ce script mesurerait donc de la TCG empilée en croyant mesurer de
la virtualisation imbriquée — et rendrait un chiffre plus flatteur, et faux.
D'où le contrôle de chaque étage : /dev/kvm lisible, « nested » à Y, et le
domaine de l'enfant en type='kvm' avec un CPU host-passthrough. Un étage qui
échoue à cela arrête la descente au lieu de la prolonger dans le vide.

  ./long_test/deep_qemu.py                  # trois étages
  ./long_test/deep_qemu.py --depth 5        # en demander plus, sciemment
  ./long_test/deep_qemu.py --dry-run        # le plan, rien de créé
  ./long_test/deep_qemu.py --detruire       # défaire ce qui a été posé
"""

import os
import re
import shlex
import subprocess
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from script.proxmox import nesting  # noqa: E402
from script.proxmox import proxmox_deploy as pve  # noqa: E402

import descente  # noqa: E402
from descente import (  # noqa: E402,F401
    DELAIS,
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
    mener,
    module_qemu,
    nom_etage as _nom_etage,
    retirer_alias,
)

# Une Debian nue : c'est elle qui recevra libvirt et qemu-kvm.
DISTRO = "debian"
NOM_BASE = "deep-qemu"
OUTIL = "deep_qemu"

# Le script est envoyé par scp, comme install_proxmox.sh l'est pour Proxmox :
# c'est NOTRE code qu'on veut éprouver, et il n'importe que la bibliothèque
# standard, donc il tourne dans un invité nu sans rien d'autre.
LOCAL_CLI = "script/qemu/deploy_qemu.py"
DISTANT_CLI = "/tmp/deploy_qemu.py"
CLE_DISTANTE = "/root/.ssh/longtest.pub"

# Trois faits, trois lignes, et l'ABSENCE d'une ligne vaut « non ». Écrit pour
# dash : /bin/sh sur Debian n'est pas bash.
CONTROLE_CMD = (
    "if [ -r /dev/kvm ]; then echo KVM=oui; else echo KVM=non; fi; "
    "cat /sys/module/kvm_amd/parameters/nested 2>/dev/null"
    " | sed s/^/NESTED=/; "
    "cat /sys/module/kvm_intel/parameters/nested 2>/dev/null"
    " | sed s/^/NESTED=/; "
    "df --output=avail -BG /var/lib/libvirt/images 2>/dev/null"
    " | tail -1 | sed s/^/DISQUE=/"
)

RESEAU_CMD = (
    "virsh -c qemu:///system net-info default 2>&1 | sed s/^/NET:/; "
    "systemctl is-active libvirtd 2>/dev/null | sed s/^/UNITE:/"
)


def nom_etage(niveau):
    return _nom_etage(niveau, NOM_BASE)


def alias_etage(niveau, parent_alias):
    return _alias_etage(niveau, parent_alias, NOM_BASE)


def parse_controle(texte):
    """Ce que le contrôle a VU. Ce qui n'a pas été lu vaut « non ».

    L'absence d'une ligne n'est jamais un oui : si
    /sys/module/kvm_amd/parameters/nested n'existe pas, c'est que le module
    n'est pas chargé, et l'étage suivant serait émulé.
    """
    propre = pve.strip_ssh_noise(texte or "")
    nested = re.search(r"^NESTED=(\S+)", propre, re.M)
    disque = re.search(r"^DISQUE=\s*(\d+)", propre, re.M)
    return {
        "kvm": bool(re.search(r"^KVM=oui\s*$", propre, re.M)),
        # « Y » ou « 1 » selon les versions du module.
        "nested": bool(nested and nested.group(1).strip() in ("Y", "1")),
        "disque_go": int(disque.group(1)) if disque else 0,
    }


def parse_reseau(texte):
    """Le réseau libvirt « default » est-il actif, et libvirtd debout ?"""
    propre = pve.strip_ssh_noise(texte or "")
    actif = re.search(r"^NET:\s*Active:\s*(\S+)", propre, re.M | re.I)
    unite = re.search(r"^UNITE:(\S+)", propre, re.M)
    return {
        "reseau": bool(actif and actif.group(1).lower() == "yes"),
        "libvirtd": bool(unite and unite.group(1).strip() == "active"),
    }


def parse_domifaddr(texte):
    """La première adresse IPv4 d'un domaine, sans son masque, ou "".

    virsh écrit un tableau ; on ne prend que les lignes qui annoncent « ipv4 »,
    et jamais la ligne d'en-tête ni les tirets.
    """
    for ligne in pve.strip_ssh_noise(texte or "").splitlines():
        champs = ligne.split()
        if len(champs) >= 4 and champs[2].lower() == "ipv4":
            return champs[3].split("/")[0]
    return ""


def parse_domaine(xml):
    """Le domaine tourne-t-il sous KVM, et son CPU passe-t-il l'hôte ?

    Les deux comptent, et pour la même raison : un domaine type='qemu' est
    ÉMULÉ, et un CPU qui ne passe pas les drapeaux de l'hôte ne porte pas la
    virtualisation — l'étage suivant serait émulé à son tour, sept minutes et
    demie de démarrage, sans qu'aucun code de retour ne le dise.
    """
    propre = pve.strip_ssh_noise(xml or "")
    domaine = re.search(r"<domain[^>]*\btype=['\"](\w+)['\"]", propre)
    cpu = re.search(r"<cpu[^>]*\bmode=['\"]([\w-]+)['\"]", propre)
    return {
        "type": domaine.group(1) if domaine else "",
        "cpu": cpu.group(1) if cpu else "",
    }


class Descente(descente.Descente):
    """Les verbes de QEMU/KVM. Le reste est dans `descente.Descente`."""

    OUTIL = OUTIL
    NOM_BASE = NOM_BASE
    DISTRO = DISTRO

    # ------------------------------------------------------------------ #
    def _envoyer_cli(self, hote):
        """Pose NOTRE deploy_qemu.py sur l'hôte. Rend True s'il y est.

        Refait à chaque besoin plutôt qu'une fois : /tmp est vidé au
        démarrage sur bien des systèmes, et l'installation redémarre.
        """
        local = os.path.join(RACINE, LOCAL_CLI)
        if self.dry_run:
            print(f"      scp {local} <hôte>:{DISTANT_CLI}")
            return True
        argv = pve.ssh_argv(hote, "")[:-1]  # les options, sans la commande
        cible = argv[-1]
        options = argv[1:-1]
        res = subprocess.run(
            ["scp", "-q"] + options + [local, f"{cible}:{DISTANT_CLI}"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if res.returncode:
            self.dire(f"      ✗ scp : {res.stderr.strip()[:200]}")
            return False
        return True

    def installer(self, hote):
        """libvirt et qemu-kvm, par « --setup-host ».

        Le code de retour ne prouve RIEN ici : « --setup-host » rend 0 même
        quand il s'est contenté de PROGRAMMER un redémarrage. C'est l'étape
        suivante — redémarrer et constater que la machine est revenue — qui
        prouve quelque chose, et le contrôle de fin d'étage qui prouve que KVM
        est là.
        """
        if self.dry_run:
            print(f"      {DISTANT_CLI} --setup-host")
            return True
        if not self._envoyer_cli(hote):
            return False
        code, _o = self.executer(
            hote,
            f"python3 {DISTANT_CLI} --setup-host --assume-yes",
            self.delai("install"),
            "deploy_qemu --setup-host",
            montrer=True,
        )
        return code == 0

    def noyau_convient(self, noyau):
        """Tout noyau convient : c'est le REDÉMARRAGE qui compte, pas ce
        qu'on redémarre.

        Il charge les modules KVM et applique l'appartenance au groupe
        libvirt, qui ne prend effet qu'à la SESSION SUIVANTE — sans lui,
        virt-install retombe sur qemu:///session, où le réseau « default »
        n'existe pas. Le moteur prouve déjà que la machine a vraiment
        redémarré en comparant l'instant de démarrage.
        """
        return bool(noyau)

    def remettre_debout(self, hote):
        """libvirtd actif et le réseau « default » démarré."""
        if self.dry_run:
            print("      libvirtd + réseau default")
            return True
        # Idempotent : sur un hôte déjà en ordre, les deux commandes ne font
        # rien et rendent 0.
        self.executer(
            hote,
            "systemctl enable --now libvirtd 2>/dev/null;"
            " virsh -c qemu:///system net-start default 2>/dev/null;"
            " virsh -c qemu:///system net-autostart default 2>/dev/null; true",
            self.delai("reparation"),
            "libvirtd",
        )
        _c, out = self.executer(
            hote, RESEAU_CMD, self.delai("controle"), "réseau"
        )
        vu = parse_reseau(out)
        self.dire(
            f"      libvirtd {'actif' if vu['libvirtd'] else 'ABSENT'},"
            f" réseau default {'actif' if vu['reseau'] else 'ABSENT'}"
        )
        return vu["libvirtd"] and vu["reseau"]

    def controler(self, hote):
        """CET étage peut-il héberger le suivant SANS l'émuler ?

        Le contrôle qui donne son sens à la mesure. Sans lui, un étage sans
        KVM ne casse pas : il bascule en émulation et continue. La descente
        irait plus « profond » en mesurant tout autre chose — de la TCG
        empilée, pas de la virtualisation imbriquée.
        """
        if self.dry_run:
            print("      /dev/kvm + nested=Y + place disque")
            return True
        code, out = self.executer(
            hote, CONTROLE_CMD, self.delai("controle"), "kvm"
        )
        if code:
            self.dire("      ✗ contrôle KVM illisible : rien conclu")
            return False
        vu = parse_controle(out)
        self.dire(
            f"      /dev/kvm {'oui' if vu['kvm'] else 'NON'},"
            f" nested {'oui' if vu['nested'] else 'NON'},"
            f" {vu['disque_go']} Go libres"
        )
        if not vu["kvm"]:
            self.dire("      ✗ pas de /dev/kvm : l'étage suivant serait ÉMULÉ")
            return False
        if not vu["nested"]:
            self.dire(
                "      ✗ virtualisation imbriquée absente :"
                " l'étage suivant serait ÉMULÉ"
            )
            return False
        return True

    def preparer_parent(self, parent):
        """Ce qu'il faut du parent : son réseau. C'est tout.

        Rien à construire, contrairement à Proxmox, où il faut poser un pont
        et un NAT dans /etc/network/interfaces : libvirt fournit déjà
        « default », avec NAT, bail DHCP ET résolveur dnsmasq. Le défaut qui a
        coûté cher là-bas — une VM en adresse fixe qui route mais ne résout
        rien, et une installation qui meurt sur « apt update » sans que rien
        ne l'explique — ne peut pas se produire ici.
        """
        if self.dry_run:
            print("      réseau default du parent")
            return ("default",)
        code, out = self.executer(
            parent, RESEAU_CMD, self.delai("controle"), "réseau"
        )
        if code:
            self.dire("      ✗ état du réseau illisible : rien conclu")
            return None
        vu = parse_reseau(out)
        if not vu["reseau"]:
            self.dire(
                "      ✗ le réseau « default » du parent n'est pas actif"
            )
            return None
        return ("default",)

    def creer_enfant(self, parent, niveau, res, prepare, noter=None):
        """Une VM dans le parent, par NOTRE deploy_qemu.py.

        L'ordre compte, et il n'est pas celui de Proxmox. Là-bas l'adresse est
        exigée AVANT la création (« --ipconfig0 ») ; ici libvirt ne la donne
        qu'APRÈS le démarrage. On note donc l'identité — le nom du domaine,
        qui est déterminé — avant la première commande qui peut créer quoi que
        ce soit, faute de quoi une création échouée à mi-chemin laisserait une
        machine que le rapport ne nomme nulle part.
        """
        (reseau,) = prepare
        nom = self.nom_etage(niveau)
        if noter:
            noter(nom)
        if not self._envoyer_cli(parent):
            return None, None
        pub = cle_publique()
        if pub and not self.dry_run:
            with open(pub, encoding="utf-8") as fh:
                contenu = fh.read().strip()
            self.executer(
                parent,
                f"mkdir -p /root/.ssh && printf '%s\\n'"
                f" {shlex.quote(contenu)} > {CLE_DISTANTE}",
                DELAIS["controle"],
                "clé",
            )
        creation = (
            f"python3 {DISTANT_CLI} --distro {DISTRO} --name {nom}"
            f" --vcpus {res['vcpu']} --memory {res['ram']}"
            f" --disk-size {res['disque']}G --network network={reseau}"
            f" --ssh-key {CLE_DISTANTE} --assume-yes"
        )
        code, _o = self.executer(
            parent,
            creation,
            self.delai("creation"),
            "deploy_qemu",
            montrer=True,
        )
        if code and not self.dry_run:
            return None, None
        if self.dry_run:
            return nom, "10.10.10.150"
        # Le domaine est-il vraiment accéléré ? « deploy_qemu » n'échoue PAS
        # quand KVM manque : il pose --virt-type qemu et continue. Un étage
        # émulé fausserait toute la mesure sans rien dire.
        _c, xml = self.executer(
            parent,
            f"virsh -c qemu:///system dumpxml {nom}",
            self.delai("controle"),
            "dumpxml",
        )
        vu = parse_domaine(xml)
        if vu["type"] != "kvm":
            self.dire(
                f"      ✗ domaine type='{vu['type'] or '?'}' : cette VM est"
                " ÉMULÉE, la mesure ne voudrait rien dire"
            )
            return None, None
        self.dire(f"      domaine kvm, cpu {vu['cpu'] or '?'}")
        _c, sortie = self.executer(
            parent,
            f"virsh -c qemu:///system domifaddr {nom} --source lease",
            self.delai("ssh"),
            "domifaddr",
        )
        adresse = parse_domifaddr(sortie)
        if not adresse:
            self.dire("      ✗ créée, mais sans adresse : rien à joindre")
            return None, None
        self.dire(f"      {nom} : {adresse}")
        return nom, adresse


def detruire_une(parent_alias, identite, nom, journal):
    """Arrête puis détruit UNE VM chez son parent, par son NOM et son UUID.

    Par égalité STRICTE du nom : un filtre par sous-chaîne aurait pris une
    « deep-qemu-lab » de production, et « --remove-all-storage » efface un
    disque pour de bon.
    """
    parent = {"target": parent_alias, "sudo": "sudo ", "jump": ""}
    code, out = pve.run(
        parent, "virsh -c qemu:///system list --all --name", 180
    )
    if code:
        dire(f"    ✗ {parent_alias} injoignable : rien touché", journal)
        return False
    presents = [
        ligne.strip()
        for ligne in pve.strip_ssh_noise(out).splitlines()
        if ligne.strip()
    ]
    if nom not in presents:
        dire(f"    — {nom} : absent de {parent_alias}", journal)
        return True
    pve.run(parent, f"virsh -c qemu:///system destroy {nom}", 300)
    code, _o = pve.run(
        parent,
        f"virsh -c qemu:///system undefine {nom} --nvram --remove-all-storage",
        600,
    )
    if code:
        dire(f"    ✗ {nom} sur {parent_alias} : undefine a échoué", journal)
        return False
    dire(f"    ✓ {nom} ({identite}) sur {parent_alias}", journal)
    return True


FAMILLE = Famille(OUTIL, NOM_BASE, detruire_une)


def principal(argv=None):
    return mener(
        argv,
        "Jusqu'à quel étage une QEMU dans une QEMU tient-elle ?",
        FAMILLE,
        Descente,
        nesting.COUTS_QEMU,
    )


if __name__ == "__main__":
    sys.exit(principal())
