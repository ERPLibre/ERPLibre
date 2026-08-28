#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur commun aux tests longs : descendre étage par étage.

Ce module ne sait rien de Proxmox ni de libvirt. Il sait ce qui est vrai de
TOUTE descente imbriquée, et qui a coûté cher à apprendre :

* un étage doit être inscrit au rapport à l'instant où sa machine existe, pas
  au retour de la fonction qui la crée ;
* le délai de chaque étape croît avec la profondeur, parce que c'est
  exactement ce qu'on mesure ;
* attendre un enfant dont le PARENT ne répond plus est une attente perdue ;
* on ne détruit jamais d'après un nom, et jamais ce qu'on n'a pas créé.

Chaque pile fournit ses VERBES en héritant de `Descente` : comment créer un
enfant, comment installer, ce que « le noyau convient » veut dire, comment
remettre les services debout, comment contrôler qu'un étage peut héberger le
suivant. Le reste est ici, écrit une fois.
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

# Les scripts qui lancent une descente. Le verrou les cherche TOUS : deux
# descentes de piles différentes se disputeraient la RAM, le disque et
# ~/.ssh/config aussi sûrement que deux de la même.
SCRIPTS = ("deep_proxmox.py", "deep_qemu.py")

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


CAPACITE_CMD = (
    "nproc | sed s/^/COEURS=/; "
    "grep MemAvailable /proc/meminfo | sed s/^/MEM=/; "
    "df --output=avail -BG /var/lib/libvirt/images 2>/dev/null"
    " | tail -1 | sed s/^/DISQUE=/"
)


def parse_capacite(texte):
    """(cœurs, RAM en Mo, disque en Go) lus chez l'hôte, ou (0, 0, 0).

    Zéro quand la ligne manque, jamais une valeur inventée : un plan
    dimensionné sur une capacité supposée annoncerait des étages qui ne
    tiennent pas.
    """
    propre = pve.strip_ssh_noise(texte or "")

    def lire(motif, diviseur=1):
        trouve = re.search(motif, propre, re.M)
        return int(trouve.group(1)) // diviseur if trouve else 0

    return (
        lire(r"^COEURS=\s*(\d+)"),
        # « MEM=MemAvailable:  7056288 kB » : le sed colle un « = », pas un
        # deux-points. L'expression attendait le second et rendait zéro — un
        # plan dimensionné sur zéro mébioctet n'annonce aucun étage.
        lire(r"^MEM=MemAvailable:\s*(\d+)", 1024),
        lire(r"^DISQUE=\s*(\d+)"),
    )


def capacite_distante(hote):
    """Ce dont dispose la RACINE quand la descente en emprunte une.

    `capacite_hote()` lit la machine LOCALE. Partir d'un hôte distant sans
    lire le sien dimensionnerait le plan d'après une machine qui n'héberge
    rien — on annoncerait dix étages sur un serveur qui n'en porte pas deux.
    """
    code, out = pve.run(dict(hote, sudo=""), CAPACITE_CMD, 120)
    if code:
        return 0, 0, 0
    return parse_capacite(out)


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


def nom_etage(niveau, base):
    return f"{base}-{niveau}"


def alias_etage(niveau, parent_alias, base):
    """L'alias ssh de l'étage : celui du parent, puis le sien.

    Chaîné, parce qu'un nom seul ne dit pas PAR OÙ passer : deux descentes
    peuvent avoir un « -2 », et OpenSSH doit savoir de quel parent il rebondit.
    """
    court = re.sub(r"[^A-Za-z0-9._-]", "-", parent_alias)
    return f"{court}+{nom_etage(niveau, base)}"


class Descente:
    """Un étage après l'autre, et ce qu'on en sait.

    Classe de BASE : elle mène la descente, tient le rapport et refuse de
    détruire ce qu'elle n'a pas créé. Ce qu'elle ne sait pas faire, elle le
    demande à la pile qui en hérite — les six crochets plus bas.
    """

    # Une descente sans racine part d'une VM qu'elle crée elle-même : c'est
    # le cas ordinaire, et ces défauts le disent au niveau de la CLASSE plutôt
    # que du constructeur, pour qu'une instance montée à la main les ait aussi.
    racine = None
    profondeur_racine = 0

    # Ce que chaque pile déclare.
    OUTIL = ""  # « deep_proxmox » : écrit au rapport, filtre --detruire
    NOM_BASE = ""  # « deep-pve » : préfixe des noms de machines
    DISTRO = ""  # la clé du catalogue d'images de deploy_qemu

    # ------------------------------------------------------------------ #
    # Les crochets. Chacun rend True quand l'étape a été CONSTATÉE.
    # ------------------------------------------------------------------ #
    def preparer_parent(self, parent):
        """Ce qu'il faut du parent pour créer chez lui, ou None."""
        raise NotImplementedError

    def creer_enfant(self, parent, niveau, res, prepare, noter=None):
        """Rend (identité, adresse), ou (None, None).

        `noter` reçoit l'identité AVANT la première commande qui peut créer
        la machine — sinon une création qui échoue à mi-chemin laisse une VM
        que le rapport ne nomme nulle part.
        """
        raise NotImplementedError

    def installer(self, hote):
        """Pose la pile sur l'étage."""
        raise NotImplementedError

    def noyau_convient(self, noyau):
        """`uname -r` annonce-t-il le noyau qu'on attend ?"""
        raise NotImplementedError

    def remettre_debout(self, hote):
        """Les services de la pile répondent-ils, une fois redémarrés ?"""
        raise NotImplementedError

    def controler(self, hote):
        """Cet étage peut-il HÉBERGER le suivant ?

        Sixième étape, et elle n'existait pas : le contrôle du stockage était
        celui du DÉBUT de l'étage suivant, si bien qu'un étage marqué
        « terminé » pouvait être incapable d'héberger quoi que ce soit — et le
        compteur d'étages atteints mentait d'autant.
        """
        raise NotImplementedError

    def nom_etage(self, niveau):
        return nom_etage(niveau, self.NOM_BASE)

    def alias_etage(self, niveau, parent_alias):
        return alias_etage(niveau, parent_alias, self.NOM_BASE)

    def __init__(
        self,
        plan,
        journal,
        dry_run=False,
        chemin_json=None,
        racine=None,
        profondeur_racine=0,
    ):
        # `racine` : un hôte qui EXISTE DÉJÀ, chez qui la descente s'installe
        # au lieu de créer sa propre machine de tête. Il n'est pas un étage —
        # il n'est pas compté, pas détruit, et son entrée ~/.ssh/config est
        # celle de l'utilisateur.
        self.racine = racine
        # Sa profondeur d'imbrication à LUI. Sans elle, le premier enfant
        # d'une racine déjà au troisième étage héritait des délais du premier :
        # quatre fois trop courts, exactement le défaut que `delai` raconte
        # avoir corrigé.
        self.profondeur_racine = profondeur_racine
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
        # La profondeur ABSOLUE : celle de la racine plus celle de l'étage.
        # Un enfant de niveau 1 posé dans une racine déjà au troisième étage
        # est en réalité au quatrième, et ses délais doivent le savoir.
        profondeur = self.profondeur_racine + max(1, self.niveau_courant)
        facteur = min(profondeur, 5) ** 2
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

    def redemarrer_et_verifier(self, hote):
        """Redémarre, attend le retour, exige le noyau voulu.

        L'installation pose le noyau sans redémarrer — lancée par ssh, un
        reboot couperait sa session et ferait passer l'installation pour un
        échec. Sans ce redémarrage, la machine reste sur le noyau cloud de
        Debian, dépouillé de tout netfilter : ni pont NAT, ni invité.

        Ce que « le bon noyau » veut dire appartient à la pile :
        `noyau_convient`.
        """
        if self.dry_run:
            print("      reboot, puis btime changé ET le noyau attendu")
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
            if not self.noyau_convient(noyau):
                continue
            if avant and apres == avant:
                continue  # elle n'a pas encore redémarré
            self.dire(
                f"      noyau {noyau} après {int(time.time() - debut)} s"
            )
            return True
        self.dire("      ✗ pas revenue sur le noyau attendu")
        return False

    def preparer_systeme(self, hote):
        """Gel de cloud-init et réparation de /etc/hosts. Vrai pour TOUTE pile.

        `manage_etc_hosts: True` fait réécrire /etc/hosts à chaque démarrage :
        le nom de la machine cesse de résoudre vers son adresse réelle, et les
        services qui s'y fient tombent sans dire pourquoi.
        """
        if self.dry_run:
            print("      gel cloud-init + /etc/hosts")
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
        # Ce « return True » manquait, et l'étape échouait donc SANS RIEN
        # DIRE : « ✗ étage 1 systeme » et pas une ligne de cause. Une fonction
        # qui rend None là où l'appelant attend un booléen ne ment pas à
        # moitié — elle dit « non ».
        return True

    def creer_etage1(self, res):
        """Une VM locale, par la CLI QEMU/KVM. Le seul étage sur du métal."""
        nom = self.nom_etage(1)
        argv = [
            os.path.join(RACINE, ".venv.erplibre/bin/python"),
            os.path.join(RACINE, "script/qemu/deploy_qemu.py"),
            "--distro",
            self.DISTRO,
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

    def parcourir(self):
        # Sans racine, le premier étage est une VM qu'on crée en local. Avec
        # une racine, TOUS les étages sont des enfants — le premier compris.
        parent = self.racine
        parent_alias = (self.racine or {}).get("target", "")
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
            if parent is None:
                nom = self.creer_etage1(res)
                if not nom:
                    self.etages.append(etage)
                    self.interrompu = True
                    break
                alias = nom
                etage["nom"] = nom
                # « cree » : NOUS l'avons faite. C'est de ce seul champ que
                # dépend le droit de la détruire. Avant lui, ce qui protégeait
                # une machine que nous n'avions pas créée était un effet de
                # bord — l'absence des clés qu'une descente écrit.
                etage["cree"] = True
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
                    # « identite » et non « vmid » : un VMID chez Proxmox,
                    # un UUID libvirt ailleurs. Le champ ancien est gardé pour
                    # les rapports écrits avant ce changement.
                    etage["identite"] = str(numero)
                    etage["vmid"] = numero
                    etage["parent_alias"] = parent_alias
                    etage["cree"] = True
                    # Le nom est ÉCRIT, non déduit du numéro d'étage à la
                    # relecture : si nom_etage change un jour, un rapport
                    # ancien désignerait des machines qui ne sont pas les
                    # siennes.
                    etage["nom"] = self.nom_etage(niveau)
                    self._sauver(etage)

                identite, adresse = self.creer_enfant(
                    parent, niveau, res, prepare, noter
                )
                if identite is None:
                    self.etages.append(etage)
                    self.interrompu = True
                    break
                etage["identite"] = str(identite)
                etage["vmid"] = identite
                etage["cree"] = True
                # Le parent est noté AVANT tout autre contrôle : c'est le seul
                # enregistrement de ce qu'on vient de créer, et --detruire s'en
                # sert. Sans lui, une VM abandonnée juste après « qm create »
                # n'était nommée nulle part.
                etage["parent_alias"] = parent_alias
                self._sauver(etage)
                alias = self.alias_etage(niveau, parent_alias)
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

            # Les quatre étapes qui suivent le ssh. « controle » est la
            # sixième et elle est NOUVELLE : sans elle, un étage était déclaré
            # terminé sans qu'on sache s'il pouvait héberger le suivant.
            for etape, action in (
                ("install", lambda: self.installer(cible)),
                ("reboot", lambda: self.redemarrer_et_verifier(cible)),
                ("systeme", lambda: self.preparer_systeme(cible)),
                ("services", lambda: self.remettre_debout(cible)),
                ("controle", lambda: self.controler(cible)),
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
            # La racine EMPRUNTÉE, si la descente en avait une. Hors de
            # « etages » : elle n'est pas un étage atteint, et l'y mettre
            # décalait de un le compte et le code de sortie.
            "racine": (
                {
                    "alias": self.racine.get("target"),
                    "profondeur": self.profondeur_racine,
                    "cree": False,
                }
                if self.racine
                else None
            ),
            # L'outil qui a écrit ce rapport. Sans lui, « deep_qemu
            # --detruire » prenait le rapport le plus récent — qui pouvait
            # être celui d'une descente Proxmox — et détruisait d'après lui.
            "outil": self.OUTIL,
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


def _lance_une_descente(pid):
    """`pid` exécute-t-il UN des scripts de descente — pas seulement le
    nomme-t-il ?

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
    # Les DEUX scripts : deux descentes de piles différentes se disputent la
    # RAM, le disque et ~/.ssh/config aussi sûrement que deux de la même.
    attendus = tuple(nom.encode() for nom in SCRIPTS)
    return any(a.endswith(attendus) for a in arguments)


def descente_vivante(pid):
    """Le processus `pid` est-il une descente EN COURS ?

    Le PID seul ne suffirait pas : les numéros se réutilisent, et rien ne dit
    qu'un rapport vieux d'une semaine ne porte pas le PID d'un shell
    d'aujourd'hui. La ligne de commande est donc lue aussi.
    """
    return bool(pid) and _lance_une_descente(pid)


def autre_descente():
    """Les PID des AUTRES descentes vivantes. Le sien est exclu.

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
        if _lance_une_descente(entree):
            vivants.append(int(entree))
    return vivants


def joindre_racine(cible, jump=""):
    """Le dict d'hôte d'une racine empruntée, ou None si elle ne répond pas.

    `sudo` est DÉDUIT, pas supposé : sur un hôte joint en root, préfixer les
    commandes de « sudo » échoue là où l'image n'en a pas, et sur un hôte
    joint en utilisateur, ne pas le mettre échoue partout.
    """
    hote = {"target": cible, "jump": jump or "", "sudo": ""}
    code, out = pve.run(hote, "id -u", 60)
    if code:
        dire(f"  ✗ {cible} : injoignable en ssh.")
        return None
    if pve.strip_ssh_noise(out).strip() != "0":
        hote["sudo"] = "sudo "
        code, _o = pve.run(hote, "true", 60)
        if code:
            dire(f"  ✗ {cible} : sudo demande un mot de passe.")
            return None
    return hote


def profondeur_de(cible):
    """La profondeur d'imbrication de `cible`, d'après sa chaîne de rebonds.

    C'est la seule mesure dont on dispose de l'extérieur, et elle est exacte
    pour les hôtes que nous avons déployés : c'est nous qui écrivons ces
    entrées, un ProxyJump par étage.
    """
    try:
        from script.todo.todo import TODO

        return nesting.depth_from_jumps(TODO._ssh_jump_depth(cible))
    except Exception:  # noqa: BLE001 - une profondeur inconnue vaut 1
        return 1


def mener(argv, description, famille, classe, couts=None):
    """La ligne de commande, le plan, la descente et le rapport.

    Identique d'une pile à l'autre à quatre choses près : ce qu'on annonce, la
    famille — qui nomme les fichiers et filtre les rapports —, la classe qui
    porte les verbes, et ce que coûte un étage.
    """
    parseur = argparse.ArgumentParser(description=description)
    # Trois par défaut, et c'est une MESURE, pas une prudence : les trois
    # premiers étages coûtent 280, 495 et 1 064 secondes — une demi-heure en
    # tout. Le quatrième en a coûté 7 h 18 d'installation et 4 h 20 d'amorçage
    # sur la même machine. Un défaut à dix promettait ce qu'aucune machine ne
    # peut tenir ; la profondeur reste un paramètre, et c'est à qui la demande
    # de savoir ce qu'il demande.
    parseur.add_argument("--depth", type=int, default=3)
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument("--detruire", action="store_true")
    # Partir d'un hôte qu'on POSSÈDE DÉJÀ. Créer une VM de tête pour héberger
    # un hyperviseur qu'on a sous la main coûte cinq minutes et un étage
    # d'imbrication — donc de la lenteur — pour rien.
    parseur.add_argument(
        "--hote",
        default="",
        help="partir d'un hôte existant (alias ssh ou user@adresse)"
        " au lieu de créer une VM de premier étage",
    )
    parseur.add_argument(
        "--jump", default="", help="rebond ssh pour joindre --hote"
    )
    args = parseur.parse_args(argv)

    journal = os.path.expanduser(
        f"~/.erplibre/longtest/{famille.nom_base}"
        f"-{time.strftime('%Y%m%d-%H%M%S')}.log"
    )
    os.makedirs(os.path.dirname(journal), exist_ok=True)
    if args.detruire:
        # « --dry-run » était ignoré ici : la prudence naturelle avant une
        # destruction détruisait pour de vrai.
        return detruire(famille, journal, dry_run=args.dry_run)

    racine, profondeur_racine = None, 0
    if args.hote:
        racine = joindre_racine(args.hote, args.jump)
        if racine is None:
            return 1
        profondeur_racine = profondeur_de(args.hote)
        # La capacité de la RACINE, pas celle d'ici. Dimensionner le plan sur
        # la machine locale quand les étages vivent ailleurs annoncerait des
        # étages qui ne tiennent pas.
        coeurs, ram, disque = capacite_distante(racine)
        if not coeurs:
            print(f"\n  ✗ {args.hote} : capacité illisible.\n")
            return 1
        print(f"\n  racine : {args.hote}, déjà au niveau {profondeur_racine}")
    else:
        coeurs, ram, disque = capacite_hote()
    ou = args.hote or "machine locale"
    print(
        f"\n  {ou} : {coeurs} cœurs, {ram} Mo disponibles,"
        f" {disque} Go de disque"
    )
    plan = nesting.nesting_plan(args.depth, coeurs, ram, disque, couts)
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
    descente = classe(
        plan, journal, args.dry_run, chemin, racine, profondeur_racine
    )
    # La racine est-elle en état d'héberger ? Le même contrôle que celui de
    # fin d'étage — un hôte emprunté n'a pas été préparé par nous, et rien ne
    # garantit que sa pile est debout.
    if racine and not args.dry_run and not descente.controler(racine):
        print(f"\n  ✗ {args.hote} ne peut pas héberger d'étage.\n")
        return 1
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


class Famille:
    """Ce qu'une pile doit dire d'elle aux fonctions qui détruisent.

    Trois choses, et pas une de plus : son nom d'outil — qui filtre les
    rapports —, le préfixe de ses machines, et comment on défait une machine
    imbriquée chez son parent.
    """

    def __init__(self, outil, nom_base, detruire_une):
        self.outil = outil
        self.nom_base = nom_base
        self.detruire_une = detruire_une


def dernier_rapport(outil="", prefixe=""):
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
        # Le rapport d'une AUTRE pile. Le dossier et le motif « *.json » sont
        # partagés : sans ce filtre, « deep_qemu --detruire » prenait le
        # rapport le plus récent — pouvant être celui d'une descente Proxmox —
        # et lançait « virsh undefine » d'après lui.
        #
        # Un rapport écrit AVANT que ce champ existe n'a pas d'outil. Le
        # refuser le rendrait indéfaisable, et laisser passer ramènerait le
        # danger : c'est le NOM DE FICHIER qui tranche, puisqu'il porte déjà
        # le préfixe de la pile — « deep-pve-20260828-…json ».
        if outil:
            declare = rapport.get("outil")
            if declare != outil and not (
                declare is None and prefixe and nom.startswith(prefixe)
            ):
                continue
        if descente_vivante(rapport.get("pid")):
            dire(f"  ⏳ descente EN COURS ({rapport['pid']}) : {nom} ignoré")
            continue
        if not (rapport.get("etages") or []):
            continue  # rien créé : ne pas masquer un rapport qui nomme des VM
        rapport["fichier"] = chemin
        return rapport
    return {}


def identite_de(etage):
    """L'identifiant de la machine SUR SON PARENT, ou "".

    Un VMID chez Proxmox, un UUID libvirt ailleurs — d'où une chaîne, et non
    un entier. « vmid » est l'ancien nom du champ : les rapports écrits avant
    ce changement le portent encore, et ils doivent rester défaisables.
    """
    valeur = etage.get("identite") or etage.get("vmid")
    return "" if valeur in (None, "") else str(valeur)


def a_defaire(rapport, nom_base=""):
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
        if identite_de(e) and e.get("parent_alias")
        # « cree » est le seul champ qui dise que la machine est à NOUS. Les
        # deux autres conditions ne protégeaient que par accident : elles
        # tenaient parce que rien ne décrivait un hôte emprunté. Depuis qu'une
        # descente peut PARTIR d'une machine existante, il faut le dire.
        and e.get("cree", True)
    ]
    etages.sort(key=lambda e: -int(e["niveau"]))
    return [
        (
            int(e["niveau"]),
            e["parent_alias"],
            identite_de(e),
            # Le nom ÉCRIT par la descente. Le déduire du numéro d'étage
            # supposait que nom_etage ne changera jamais — un rapport ancien
            # aurait alors nommé des machines qui ne sont pas les siennes.
            # Le nom ÉCRIT par la descente. Le déduire du numéro d'étage
            # supposait que nom_etage ne changera jamais — un rapport ancien
            # aurait alors nommé des machines qui ne sont pas les siennes.
            e.get("nom")
            or (nom_base and nom_etage(int(e["niveau"]), nom_base)),
        )
        for e in etages
    ]


def detruire_etage1(journal, nom, dry_run=False, attendu=None, cree=True):
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
    # `nom` est OBLIGATOIRE : une fonction qui lance
    # « virsh undefine --remove-all-storage » ne devine pas sa cible. Elle le
    # faisait — `nom_etage(1)` — et le repli désignait la machine numéro 1 de
    # la pile, quelle que soit celle dont parlait le rapport.
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
    elif cree:
        dire(
            f"    ⚠ {nom} : rapport sans UUID, identifié par son NOM", journal
        )
    else:
        # Ni UUID, ni preuve que la machine est à nous : on ne touche à rien.
        # Une descente PARTIE d'un hôte existant n'a jamais d'UUID libvirt
        # local ; le repli par le nom aurait effacé un homonyme, disques
        # compris, avec « --remove-all-storage ».
        dire(
            f"    — {nom} : pas créé par cette descente, rien touché", journal
        )
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


def detruire(famille, journal=None, dry_run=False):
    """Défait ce que le DERNIER rapport dit avoir créé, du plus profond.

    Rien d'autre. La version d'avant prenait toute entrée ~/.ssh/config dont
    le nom contenait « deep-pve », puis sur son rebond détruisait toute VM
    dont le nom contenait « deep-pve » — une machine de labo appelée
    « deep-pve-lab » sur un hyperviseur de production tombait dedans.
    """
    # Avant tout : refuser tant qu'une descente tourne. Elle installe encore
    # sur les machines qu'on s'apprête à détruire, et son rapport peut être
    # celui qu'on vient de choisir.
    autres = autre_descente()
    if autres:
        dire(
            f"  ⛔ une descente tourne ({', '.join(map(str, autres))}) :"
            " rien ne sera détruit.",
            journal,
        )
        dire("  Attendre qu'elle finisse, ou l'arrêter d'abord.", journal)
        return 1
    rapport = dernier_rapport(famille.outil, famille.nom_base)
    if not rapport:
        dire("  aucun rapport de descente : rien à défaire.", journal)
        dire(
            "  (les entrées ~/.ssh/config orphelines : menu de nettoyage)",
            journal,
        )
        return 0
    liste = a_defaire(rapport, famille.nom_base)
    dire(f"  rapport : {rapport.get('fichier')}", journal)
    dire(f"  {len(liste)} VM imbriquée(s) + l'étage 1 :", journal)
    for niveau, parent_alias, identite, nom in liste:
        dire(
            f"    étage {niveau:2d}  {nom} ({identite}) sur {parent_alias}",
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
    dire(
        f"    étage  1  {etage1_nom or nom_etage(1, famille.nom_base)}"
        " (libvirt)",
        journal,
    )
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
        for niveau, parent_alias, identite, nom in liste
        if famille.detruire_une(parent_alias, identite, nom, journal)
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
        journal,
        attendu=etage1.get("uuid"),
        nom=etage1.get("nom") or nom_etage(1, famille.nom_base),
        cree=bool(etage1.get("cree", True)),
    )
    if racine:
        faits += 1
    retirer_alias(rapport, journal, famille.nom_base)
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


def retirer_alias(rapport, journal=None, nom_base=""):
    """Retire de ~/.ssh/config les entrées de la descente défaite.

    Sans cela, elles survivaient aux machines : des entrées mortes dont le
    ProxyJump désigne un hôte qui n'existe plus, et qu'on retrouve plus tard
    sans savoir à quoi elles servaient.
    """
    alias = []
    for etage in rapport.get("etages") or []:
        # Seulement les nôtres. L'entrée ssh d'un hôte EMPRUNTÉ appartient à
        # l'utilisateur : il l'a écrite pour sa propre machine et elle lui sert
        # ailleurs.
        if not etage.get("cree", True):
            continue
        nom = etage.get("alias")
        if not nom:
            # L'étage abandonné avant l'écriture de son alias : le calculer,
            # il est déterminé par (niveau, alias du parent).
            parent = etage.get("parent_alias")
            if parent:
                nom = alias_etage(int(etage["niveau"]), parent, nom_base)
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
