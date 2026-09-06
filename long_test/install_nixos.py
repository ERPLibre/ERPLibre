#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""ERPLibre s'installe-t-il sur NixOS, de bout en bout ?

Ni `deep_qemu.py` ni `deep_proxmox.py` : ceux-là mesurent une profondeur
d'imbrication, celui-ci n'a qu'UNE machine et une question binaire — le
chemin que le menu emprunte aboutit-il sur un système déclaratif.

Il est ici et non dans `test/` pour la raison qui vaut pour ses deux voisins :
il crée une VM, y installe un système entier et prend des heures.

CE QU'IL ENVOIE, ET POURQUOI CE N'EST PAS UN SCRIPT À LUI

L'installation est la commande distante que le menu compose,
`_qemu_erplibre_remote_cmd`, prise telle quelle. Un test qui installerait par
ses propres soins prouverait SON chemin, pas celui du produit — et c'est
justement là que se cachaient les pannes : l'amorçage sans branche nix, le
Makefile qui présumait /bin/bash, les chemins de compilation lus d'une
session plus vieille que le module qu'elle venait d'appliquer.

UNE SEULE SESSION SSH, ET C'EST LA CONDITION QUI COMPTE

Le bloc part en UN appel, comme le déploiement le fait. C'est ce qui expose
la panne du PREMIER passage : la session est ouverte avant que
« make install_os » n'applique le module, donc avant que pam_env ne pose
CPATH ; les paquets qui n'ont pas de roue amont s'y arrêtaient. Rejouer
l'installation dans une session neuve réussit et donne raison à tort.

LE VERDICT EST LA VÉRIFICATION, PAS UN CODE DE RETOUR

« nixos-rebuild switch » rend 4 quand une unité n'a pas redémarré alors que
le système EST activé, et chaque bloc d'outil du menu rend 0 par
construction. On juge donc sur l'état de la machine : les chemins que envfs
fabrique, le venv, les modules qui n'ont pas de roue et doivent se compiler,
puis Odoo qui répond.

  ./long_test/install_nixos.py                 # crée la VM, installe, juge
  ./long_test/install_nixos.py --dry-run       # le plan et les commandes
  ./long_test/install_nixos.py --hote nixos-1  # sur une machine qu'on a déjà
  ./long_test/install_nixos.py --detruire      # défaire ce qui a été posé
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from descente import (  # noqa: E402
    Famille,
    capacite_hote,
    cle_publique,
    detruire,
    dire,
)

DISTRO = "nixos"
NOM_BASE = "long-nixos"
OUTIL = "install_nixos"

# La RAM : le catalogue annonce 2048 Mo pour NixOS et le « nixos-rebuild » du
# module y tient — mesuré, une fois les manuels HTML écartés. La compilation
# de ce qui n'a pas de roue amont, elle, n'a été éprouvée qu'au-dessus : le
# défaut est donc plus large que le minimum, et « --memory » le règle pour qui
# veut mesurer la limite basse.
MEMOIRE_MO = 4096
VCPUS = 4
# Le disque VIRTUEL de la VM : 40 Go, le minimum que le catalogue annonce. Il
# garde la marge des générations du store Nix, que rien ne purge tout seul.
DISQUE_GO = 40

# Ce que l'installation ÉCRIT vraiment, mesuré à la fin d'une installation
# complète : 12 Go, dont 5,5 pour le store. C'est ce chiffre-là qu'il faut
# comparer à l'espace libre de l'hôte, et non les 40 Go ci-dessus : un qcow2
# n'est pas préalloué, il ne prend que ce qu'on y écrit. Les confondre faisait
# refuser le test sur une machine qui pouvait parfaitement le mener.
DISQUE_ECRIT_GO = 12

# Ce qu'il faut à la machine AVANT de commencer, en plus de la VM elle-même.
# Annoncer un plan qui ne tient pas coûte une heure pour rien.
MARGE_RAM_MO = 1024
MARGE_DISQUE_GO = 8

# Les modules qui n'ont PAS de roue amont et doivent donc se compiler dans la
# VM. Ce sont eux qui tombent quand les en-têtes manquent, et eux seuls : les
# roues manylinux s'installent sans compilateur.
MODULES_COMPILES = ("psycopg2", "ldap", "cups", "MySQLdb")

# Odoo sans base répond 303 vers son sélecteur. 200, 404 et 500 prouvent aussi
# qu'un serveur écoute et a chargé son registre ; 000 est l'absence de réponse.
CODES_VIVANTS = ("200", "303", "404", "500")

DELAI_SSH = 600
DELAI_INSTALL = 10800
DELAI_HTTP = 300


def journal_du_jour():
    chemin = os.path.expanduser(
        f"~/.erplibre/longtest/{NOM_BASE}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    )
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    return chemin


def commande_installation(branche):
    """Le bloc que le MENU envoie, pris tel quel.

    Importé plutôt que recopié : deux copies d'une chaîne d'installation
    divergent, et c'est la copie du test qui reste verte pendant que le
    produit casse.
    """
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    return TODO.__new__(TODO)._qemu_erplibre_remote_cmd(branche)


def ssh_base(cible, jump=""):
    opts = [
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
    ]
    if jump:
        opts += ["-J", jump]
    return ["ssh"] + opts + [cible]


def attendre_ssh(cible, journal, jump="", delai=DELAI_SSH):
    """Vrai dès que la machine répond. Le premier boot d'une image NixOS pose
    le compte par cloud-init : tant qu'il n'a pas fini, le port répond mais
    l'authentification échoue."""
    fin = time.time() + delai
    while time.time() < fin:
        fini = subprocess.run(
            ssh_base(cible, jump) + ["true"],
            capture_output=True,
            timeout=30,
        )
        if fini.returncode == 0:
            return True
        time.sleep(5)
    dire(f"      ✗ {cible} jamais joignable en {delai} s", journal)
    return False


def creer_vm(nom, journal, dry_run, memoire=MEMOIRE_MO):
    """La VM, par la CLI du dépôt — celle que le menu appelle aussi.

    Rend (nom, uuid) ou (None, ""). L'UUID est ce qui identifie la machine
    pour la destruction : un nom se réutilise, un UUID non.
    """
    argv = [
        os.path.join(RACINE, ".venv.erplibre/bin/python"),
        os.path.join(RACINE, "script/qemu/deploy_qemu.py"),
        "--distro",
        DISTRO,
        "--name",
        nom,
        "--vcpus",
        str(VCPUS),
        "--memory",
        str(memoire),
        "--disk-size",
        f"{DISQUE_GO}G",
    ]
    pub = cle_publique()
    if pub:
        argv += ["--ssh-key", pub]
    if dry_run:
        dire("      " + " ".join(shlex.quote(a) for a in argv), journal)
        return nom, ""
    fini = subprocess.run(argv, timeout=DELAI_SSH * 3)
    if fini.returncode:
        dire("      ✗ la création de la VM a échoué", journal)
        return None, ""
    uuid = subprocess.run(
        ["sudo", "-n", "virsh", "domuuid", nom],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return nom, ("" if uuid.returncode else uuid.stdout.strip())


def adresse_de(nom, journal):
    """L'adresse de la VM, et l'entrée ~/.ssh/config qui va avec.

    La CLI ne l'écrit pas : sans elle, « ssh long-nixos » rend « Name or
    service not known » et l'attente irait jusqu'à son plein délai sur une
    machine qui répond parfaitement à son adresse.
    """
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    todo = TODO.__new__(TODO)
    ip = todo._qemu_vm_ip_now(nom)
    if not ip:
        dire(f"      ✗ {nom} créée mais sans adresse", journal)
        return ""
    prive = cle_publique()[:-4] if cle_publique() else None
    todo._write_ssh_config_entry([nom], "erplibre", ip, identity_file=prive)
    dire(f"      {nom} : {ip}", journal)
    return ip


def installer(cible, branche, journal, jump="", dry_run=False):
    """Le bloc du menu, en UNE session — la condition qui expose la panne du
    premier passage. Rend (ok, secondes)."""
    bloc = commande_installation(branche)
    if dry_run:
        dire(f"      {len(bloc)} caractères de commande distante", journal)
        dire("      " + bloc[:200] + " …", journal)
        return True, 0
    debut = time.time()
    with open(journal, "a", encoding="utf-8") as fh:
        fini = subprocess.run(
            ssh_base(cible, jump) + ["bash -s"],
            input=bloc,
            text=True,
            stdout=fh,
            stderr=subprocess.STDOUT,
            timeout=DELAI_INSTALL,
        )
    secondes = int(time.time() - debut)
    # Le code de retour est NOTÉ, pas cru : la vérification tranche.
    dire(f"      installation : code={fini.returncode}, {secondes} s", journal)
    return fini.returncode == 0, secondes


def sonder(cible, commande, jump=""):
    """La sortie d'une commande distante, ou "" si elle échoue."""
    try:
        fini = subprocess.run(
            ssh_base(cible, jump) + [commande],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return fini.stdout.strip() if fini.returncode == 0 else ""


def verifier(cible, journal, jump=""):
    """L'état de la machine, contrôle par contrôle. Rend {nom: bool}.

    Ce sont des FAITS, pas des codes de retour : ce que envfs fabrique, le
    venv, les modules qui doivent se compiler, et un serveur qui répond.
    """
    resultats = {}

    chemins = sonder(
        cible,
        "for f in /bin/bash /usr/bin/env; do [ -e $f ] || exit 1; done;"
        " ls /usr/bin/python3.* >/dev/null 2>&1 || exit 1; echo ok",
        jump,
    )
    resultats["envfs"] = chemins == "ok"

    venv = sonder(
        cible,
        "cd git/erplibre 2>/dev/null && ls -d .venv.odoo*/bin/python"
        " 2>/dev/null | head -1",
        jump,
    )
    resultats["venv"] = bool(venv)

    if venv:
        # Les quatre en un seul import : ce qui manque est nommé par Python
        # lui-même dans le journal, et un seul aller-retour suffit.
        code = "import " + ", ".join(MODULES_COMPILES) + "; print('ok')"
        rendu = sonder(
            cible,
            f"cd git/erplibre && ./{venv} -c {shlex.quote(code)}"
            " 2>&1 | tail -1",
            jump,
        )
        resultats["modules_compiles"] = rendu == "ok"
    else:
        resultats["modules_compiles"] = False

    # Les manuels HTML : le module les écarte, et leur retour ferait revenir
    # une construction Sphinx de trois mille pages à chaque installation.
    doc = sonder(
        cible, "ls /run/current-system/sw/share/doc 2>/dev/null | wc -l", jump
    )
    resultats["sans_manuels_html"] = doc == "0"

    resultats["odoo_repond"] = odoo_repond(cible, journal, jump)

    for nom, ok in resultats.items():
        dire(f"      {'✓' if ok else '✗'} {nom}", journal)
    return resultats


def odoo_repond(cible, journal, jump=""):
    """Odoo démarré par le dépôt, et un code HTTP qui prouve un registre
    chargé. Le serveur est lancé ICI plutôt que supposé en service : une VM de
    développement n'en installe pas forcément un."""
    subprocess.run(
        ssh_base(cible, jump)
        + ["cd git/erplibre && nohup ./run.sh >/tmp/odoo-longtest.log 2>&1 &"],
        capture_output=True,
        timeout=60,
    )
    fin = time.time() + DELAI_HTTP
    while time.time() < fin:
        code = sonder(
            cible,
            "curl -s -o /dev/null -w '%{http_code}' -m 10"
            " http://127.0.0.1:8069/web/login",
            jump,
        )
        if code in CODES_VIVANTS:
            dire(f"      Odoo rend {code}", journal)
            return True
        time.sleep(10)
    dire("      ✗ Odoo n'a rien rendu", journal)
    return False


def plan_tient(journal, memoire=MEMOIRE_MO):
    """La machine peut-elle héberger la VM ? Le dire AVANT de la créer."""
    coeurs, ram, disque = capacite_hote()
    dire(
        f"  machine locale : {coeurs} cœurs, {ram} Mo disponibles,"
        f" {disque} Go de disque",
        journal,
    )
    manque = []
    if ram < memoire + MARGE_RAM_MO:
        manque.append(f"RAM (il en faut {memoire + MARGE_RAM_MO} Mo)")
    if disque < DISQUE_ECRIT_GO + MARGE_DISQUE_GO:
        manque.append(
            f"disque (il en faut {DISQUE_ECRIT_GO + MARGE_DISQUE_GO} Go"
            f" libres ; le disque virtuel fait {DISQUE_GO} Go, creux)"
        )
    if manque:
        dire(f"  ✗ pas assez de {' ni de '.join(manque)}", journal)
        return False
    return True


def mener(argv):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument("--detruire", action="store_true")
    parseur.add_argument(
        "--hote",
        default="",
        help="installer sur une machine NixOS existante (alias ssh ou"
        " user@adresse) au lieu de créer une VM",
    )
    parseur.add_argument("--jump", default="", help="rebond ssh pour --hote")
    parseur.add_argument("--branche", default="develop")
    parseur.add_argument("--memory", type=int, default=MEMOIRE_MO)
    args = parseur.parse_args(argv)

    journal = journal_du_jour()

    # `detruire_une` défait une VM IMBRIQUÉE chez son parent. Il n'y en a
    # aucune ici — une seule machine, au premier étage — donc le défaire
    # partagé ne l'appelle jamais. On le dit quand même plutôt que de poser
    # None : le jour où il serait appelé, le journal nommerait la raison au
    # lieu de s'arrêter sur « NoneType is not callable ».
    def pas_d_imbrique(parent_alias, identite, nom, log=None):
        dire(f"      ✗ {nom} : ce test ne crée pas de VM imbriquée", log)
        return False

    famille = Famille(OUTIL, NOM_BASE, pas_d_imbrique)
    if args.detruire:
        return detruire(famille, journal, dry_run=args.dry_run)

    dire(f"  journal : {journal}", journal)
    if args.dry_run:
        dire("  --dry-run : rien ne sera créé.", journal)

    # La forme du rapport n'est pas libre : c'est le CONTRAT du défaire
    # partagé (descente.py). « etages » vide fait écarter le rapport par
    # dernier_rapport — « rien créé » — et la VM survivrait au --detruire.
    # « pid » est ce qui empêche de détruire la machine d'une installation
    # EN COURS : sans lui, le rapport de la course en cours est le plus
    # récent, donc celui qu'on choisit.
    rapport = {
        "outil": OUTIL,
        "distro": DISTRO,
        "branche": args.branche,
        "dry_run": args.dry_run,
        "pid": os.getpid(),
        "etapes": {},
        "etages": [],
    }
    chemin = journal[:-4] + ("-dryrun.json" if args.dry_run else ".json")

    if args.hote:
        cible, uuid = args.hote, ""
        dire(f"  hôte fourni : {args.hote}", journal)
    else:
        if not args.dry_run and not plan_tient(journal, args.memory):
            return 1
        nom = f"{NOM_BASE}-{time.strftime('%H%M%S')}"
        dire(
            f"  création de {nom} ({args.memory} Mo, {DISQUE_GO} Go)", journal
        )
        nom, uuid = creer_vm(nom, journal, args.dry_run, args.memory)
        if not nom:
            return 1
        # Écrit AVANT la suite : une course qui meurt en cours
        # d'installation laisse quand même de quoi la défaire.
        rapport["etages"] = [
            {
                "niveau": 1,
                "nom": nom,
                "uuid": uuid,
                "alias": nom,
                "cree": True,
            }
        ]
        cible = nom
        if not args.dry_run:
            _ecrire(chemin, rapport, journal)
            if not adresse_de(nom, journal):
                return 1

    if args.dry_run:
        installer(cible, args.branche, journal, args.jump, dry_run=True)
        _ecrire(chemin, rapport, journal)
        return 0

    if not attendre_ssh(cible, journal, args.jump):
        _ecrire(chemin, rapport, journal)
        return 1
    rapport["etapes"]["joignable"] = True

    ok, secondes = installer(cible, args.branche, journal, args.jump)
    rapport["etapes"]["installation_code_zero"] = ok
    rapport["secondes_installation"] = secondes

    controles = verifier(cible, journal, args.jump)
    rapport["controles"] = controles
    _ecrire(chemin, rapport, journal)

    # Le verdict porte sur l'ÉTAT, pas sur le code de retour de l'installation.
    tout = all(controles.values())
    dire(f"  {'✅' if tout else '❌'} ERPLibre sur NixOS", journal)
    return 0 if tout else 1


def _ecrire(chemin, rapport, journal):
    with open(chemin, "w", encoding="utf-8") as fh:
        json.dump(rapport, fh, indent=2)
    dire(f"  rapport : {chemin}", journal)


if __name__ == "__main__":
    sys.exit(mener(sys.argv[1:]))
