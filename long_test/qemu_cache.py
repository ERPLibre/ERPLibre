#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le cache de téléchargement sert-il vraiment la seconde VM ?

Deux machines sœurs, la même distribution, les mêmes paquets. La première
remplit le cache, la seconde doit être servie par lui. Ce script crée de
VRAIES VM et dure des dizaines de minutes : il vit dans « long_test/ » et non
dans « test/ », que le lanceur unitaire balaie en secondes.

## Ce qui est mesuré, et pourquoi pas ce qu'on croirait

« Zéro octet tiré de l'amont » est la manchette, pas le critère. Arch est une
publication continue : entre les deux déploiements, un miroir peut publier une
version neuve, que la seconde VM tirera légitimement — l'index n'est jamais
servi du cache tant que l'amont répond, donc elle la VERRA. Un critère fondé
sur le seul volume déclarerait alors le cache en panne alors qu'il fonctionne.

Le critère est donc : **aucune URL demandée par les DEUX VM n'est retirée de
l'amont une seconde fois.** Un paquet que la première a tiré et que la seconde
redemande doit venir du disque, sans exception. Ce que la seconde découvre
seule est compté, montré, et n'échoue pas.

## La contre-épreuve, qui fait la valeur du test

Un cache qui accélère ne prouve pas qu'il permet de travailler sans réseau.
« --hors-ligne » coupe l'accès de l'amont AU SEUL service du cache — par son
compte système, pas par une règle générale qui emporterait la session ssh de
l'opérateur — et déploie une troisième VM. Elle doit réussir sur l'index
stocké, et le journal doit dire sur quel instantané elle se bâtit.

```
./long_test/qemu_cache.py                 # deux VM
./long_test/qemu_cache.py --dry-run       # le plan, rien de créé
./long_test/qemu_cache.py --hors-ligne    # + la troisième VM, amont coupé
./long_test/qemu_cache.py --detruire      # défaire
```
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
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from descente import (  # noqa: E402
    Descente,
    cle_publique,
    detruire_etage1,
    dire,
)

OUTIL = "qemu_cache"
NOM_BASE = "el-cache-test"
DISTRO = "arch"
VERSION = "latest"

CLI = os.path.join(RACINE, "script/qemu/deploy_qemu.py")
CA = "/var/lib/erplibre_go_qemu_cache/ca.crt"
CACHE_BIN = "/usr/local/bin/erplibre_go_qemu_cache"
SERVICE = "erplibre-go-qemu-cache.service"
CONF = "/etc/erplibre_go_qemu_cache/env"
SERVICE_USER = "elqcache"
TABLE_BLOCAGE = "erplibre_qemu_cache_test"

# Un lot fixe et volumineux : la mesure exige que les DEUX VM demandent les
# MÊMES fichiers. Installer ERPLibre servirait aussi, mais coûterait des
# heures pour une comparaison que ce lot rend en minutes.
PAQUETS = "base-devel git python rust cmake"

DELAI_CREATION = 1800
DELAI_SSH = 600
DELAI_PAQUETS = 2400


def journal_neuf():
    chemin = os.path.expanduser(
        f"~/.erplibre/longtest/{OUTIL}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    )
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    return chemin


def chemin_rapport(horodatage=None):
    horodatage = horodatage or time.strftime("%Y%m%d-%H%M%S")
    return os.path.expanduser(
        f"~/.erplibre/longtest/{OUTIL}-{horodatage}.json"
    )


def machines_a_defaire(limite=20):
    """Tout ce que les rapports récents nomment, avec l'UUID quand il existe.

    Le rapport le plus récent ne suffit pas. Une exécution qui échoue à la
    création écrit un rapport qui NOMME une machine sans la connaître : le nom
    y est noté avant la création, justement pour qu'une création interrompue à
    mi-chemin laisse une trace. Ce rapport-là masquerait celui d'une exécution
    antérieure qui, elle, détient l'UUID — et la destruction retomberait sur
    le nom, ce que ce dépôt a appris à ne plus faire.

    Les rapports sont donc parcourus du plus ANCIEN au plus récent, l'UUID
    d'un rapport qui en a un l'emportant sur l'absence d'un autre. Rend
    {nom: uuid ou ""} et la liste des fichiers lus.
    """
    rep = os.path.expanduser("~/.erplibre/longtest")
    if not os.path.isdir(rep):
        return {}, []
    fichiers = sorted(
        (
            f
            for f in os.listdir(rep)
            if f.startswith(OUTIL) and f.endswith(".json")
        )
    )[-limite:]
    machines, lus = {}, []
    for nom in fichiers:
        chemin = os.path.join(rep, nom)
        try:
            with open(chemin, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not data.get("vms"):
            continue
        lus.append(chemin)
        uuids = data.get("uuids") or {}
        for vm in data["vms"]:
            # Un UUID connu ne se perd jamais au profit d'un rapport muet.
            if uuids.get(vm) or vm not in machines:
                machines[vm] = uuids.get(vm, machines.get(vm, ""))
    return machines, lus


def rapports_recents(limite=12):
    """Les rapports d'exécution, du plus récent au plus ancien."""
    rep = os.path.expanduser("~/.erplibre/longtest")
    if not os.path.isdir(rep):
        return []
    out = []
    for nom in sorted(
        (
            f
            for f in os.listdir(rep)
            if f.startswith(OUTIL) and f.endswith(".json")
        ),
        reverse=True,
    )[:limite]:
        try:
            with open(os.path.join(rep, nom), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if not mesure_reelle(d):
            continue
        d["_fichier"] = nom
        out.append(d)
    return out


def mesure_reelle(rapport):
    """Ce rapport porte-t-il une mesure, ou seulement un plan ?

    La marque « dry_run » tranche pour les rapports récents. Les plus anciens
    ne la portent pas : une durée nulle partout les trahit, car une
    installation de paquets qui prend zéro seconde n'a pas eu lieu.
    """
    if rapport.get("dry_run"):
        return False
    durees = rapport.get("durees") or {}
    return any(d > 0 for d in durees.values())


def rapport_comparatif():
    """Ce que le cache fait gagner, mesuré et non annoncé.

    Deux exécutions suffisent : une avec cache, une sans. Sans le témoin, un
    temps ne dit rien — une installation rapide peut l'être parce que le
    miroir est proche, pas parce qu'un cache a servi.
    """
    rapports = rapports_recents()
    if not rapports:
        print("\n  Aucune exécution mesurée. Lancer le test, puis le témoin :")
        print("    ./long_test/qemu_cache.py")
        print("    ./long_test/qemu_cache.py --sans-cache\n")
        return 1

    avec = [r for r in rapports if r.get("cache")]
    sans = [r for r in rapports if not r.get("cache")]

    print("\n  ── Rapport de performance ──\n")
    print(
        f"  {'exécution':<22}{'cache':<8}{'VM':<18}{'durée':>8}{'amont':>14}{'du cache':>14}"
    )
    print("  " + "─" * 82)
    for r in rapports[:6]:
        etiquette = r["debut"][:16].replace("T", " ")
        for nom, duree in (r.get("durees") or {}).items():
            o = (r.get("octets") or {}).get(nom, {})
            print(
                f"  {etiquette:<22}{'oui' if r.get('cache') else 'non':<8}"
                f"{nom:<18}{duree:>7.0f}s"
                f"{humain(o.get('amont', 0)):>14}{humain(o.get('cache', 0)):>14}"
            )
            etiquette = ""

    if avec and sans:
        da = moyenne_seconde_vm(avec)
        ds = moyenne_seconde_vm(sans)
        print()
        if da and ds:
            print(f"  seconde VM, avec cache : {da:.0f} s")
            print(f"  seconde VM, sans cache : {ds:.0f} s")
            if ds > da:
                print(
                    f"  gain : {ds - da:.0f} s, soit {100 * (ds - da) / ds:.0f} %"
                )
            else:
                # Un gain nul est un RÉSULTAT, pas une erreur : sur un lien
                # rapide, le temps est dominé par l'installation et non par
                # le téléchargement.
                print(
                    "  aucun gain de TEMPS : sur ce lien, le téléchargement ne"
                    " domine pas.\n  Le gain porte alors sur les octets, colonne"
                    " « amont »."
                )
    else:
        manque = "sans cache" if avec else "avec cache"
        print(f"\n  Il manque une exécution {manque} pour comparer :")
        print(
            "    ./long_test/qemu_cache.py" + (" --sans-cache" if avec else "")
        )
    print()
    return 0


def moyenne_seconde_vm(rapports):
    """La durée de la SECONDE VM, celle que le cache doit servir."""
    valeurs = []
    for r in rapports:
        for nom, d in (r.get("durees") or {}).items():
            if nom.endswith("-2"):
                valeurs.append(d)
    return sum(valeurs) / len(valeurs) if valeurs else 0


def humain(n):
    for unite in ("o", "Kio", "Mio", "Gio"):
        if n < 1024 or unite == "Gio":
            return f"{n:.0f} {unite}" if unite == "o" else f"{n:.1f} {unite}"
        n /= 1024
    return f"{n:.1f} Tio"


def executer(cmd, delai, journal=None, montrer=False):
    """Une commande locale. Rend (code, sortie)."""
    if journal:
        dire(f"  $ {cmd}", journal)
    try:
        p = subprocess.run(
            cmd,
            shell=True,
            capture_output=not montrer,
            text=True,
            timeout=delai,
        )
    except subprocess.TimeoutExpired:
        return 124, f"délai dépassé après {delai} s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# --------------------------------------------------------------------------
# Contrôles préalables
# --------------------------------------------------------------------------


def prealables(journal):
    """Ce qui doit être vrai AVANT de créer la moindre machine.

    Chaque manque est dit avec son remède : découvrir au bout de vingt minutes
    que le cache n'écoutait pas est le genre d'échec qui ne se pardonne pas.
    """
    manques = []
    if not os.path.isfile(CA):
        manques.append(
            f"autorité du cache absente ({CA}) — TODO › Déploiement › Cache QEMU"
        )
    code, _ = executer(f"systemctl is-active --quiet {SERVICE}", 15)
    if code:
        manques.append(
            f"le service {SERVICE} ne tourne pas — systemctl start {SERVICE}"
        )
    if not cle_publique():
        manques.append("aucune clé publique ssh dans ~/.ssh")
    code, _ = executer("virsh -c qemu:///system list --all", 30)
    if code:
        manques.append("libvirt injoignable — virsh -c qemu:///system list")
    if not os.path.isfile(CLI):
        manques.append(f"deploy_qemu.py absent ({CLI})")
    ecart = desaccord_de_reseau()
    if ecart:
        manques.append(ecart)
    restes = machines_vivantes()
    if restes:
        # Sans cette garde, la création bute sur le disque de la machine
        # restante et rend un « existe déjà » qui ne dit pas quoi faire.
        manques.append(
            f"machine(s) d'un essai précédent encore là : {', '.join(restes)}"
            f" — les défaire d'abord : {sys.argv[0]} --detruire"
        )
    for m in manques:
        dire(f"  ✗ {m}", journal)
    return not manques


def machines_vivantes():
    """Les machines de CE test qui existent encore, par leur nom."""
    code, sortie = executer("virsh -c qemu:///system list --all --name", 30)
    if code:
        return []
    return [
        l.strip()
        for l in (sortie or "").split("\n")
        if l.strip().startswith(NOM_BASE)
    ]


def desaccord_de_reseau():
    """Les règles visent-elles le sous-réseau que libvirt sert VRAIMENT ?

    Le réseau « default » ne sert pas toujours 192.168.122.0/24 : il est
    déplacé sur un /24 libre dès que ce préfixe entre en collision, ce qui est
    le cas de tout orchestrateur qui est lui-même une VM. Des règles posées
    sur l'autre préfixe existent, l'installation réussit, et aucune VM ne
    traverse le cache. Rend un message, ou "" si l'accord est fait.
    """
    code, xml = executer("virsh -c qemu:///system net-dumpxml default", 30)
    if code:
        return ""
    m = re.search(r"<ip address='([\d.]+)'", xml or "")
    if not m:
        return ""
    servi = m.group(1).rsplit(".", 1)[0] + ".0/24"
    code, regles = executer(
        "sudo -n nft list table ip erplibre_qemu_cache", 30
    )
    if code:
        return ""
    if servi not in (regles or ""):
        return (
            f"le détournement ne vise pas le réseau des VM : libvirt sert"
            f" {servi}, les règles disent autre chose — réinstaller le cache"
            " depuis TODO › Déploiement › Cache QEMU"
        )
    return ""


def journal_du_cache():
    """Chemin du journal d'accès, lu dans la configuration du service.

    Deviner « /var/log/... » marcherait aujourd'hui et mentirait le jour où
    quelqu'un change la valeur : c'est la configuration qui décide.
    """
    try:
        with open(CONF, encoding="utf-8") as fh:
            for ligne in fh:
                if ligne.startswith("EL_ACCESS_LOG="):
                    return ligne.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def lignes_depuis(chemin, decalage):
    """Les lignes du journal d'accès écrites après `decalage`, et le nouveau
    décalage. Les lignes illisibles sont sautées : une écriture en cours peut
    laisser une dernière ligne incomplète."""
    out = []
    try:
        taille = os.path.getsize(chemin)
    except OSError:
        return out, decalage
    if taille < decalage:
        # Le journal a été tourné : on repart de son début.
        decalage = 0
    with open(chemin, encoding="utf-8", errors="replace") as fh:
        fh.seek(decalage)
        for ligne in fh:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                out.append(json.loads(ligne))
            except ValueError:
                continue
        return out, fh.tell()


# --------------------------------------------------------------------------
# Les machines
# --------------------------------------------------------------------------


def deployer(nom, journal, dry_run=False, avec_cache=True):
    """Une VM Arch, branchée sur le cache ou non. Rend son adresse, ou ''.

    Sans le cache, la VM télécharge en direct : c'est le TÉMOIN, la mesure de
    ce que coûte une installation quand rien n'est gardé. Un gain ne veut rien
    dire sans lui.

    Omettre l'autorité NE SUFFIT PAS : l'interception est transparente et vaut
    pour tout le pont, si bien qu'une VM sans autorité est détournée quand
    même et échoue sur « self-signed certificate in certificate chain ». Le
    témoin demande donc « --cache-bypass », qui pose une exception par adresse
    MAC sur l'hôte avant la création. Elle ne vise QUE cette VM : le cache
    continue de servir les autres pendant la mesure, là où éteindre le service
    couperait tout le monde.
    """
    cmd = (
        f"sudo python3 {shlex.quote(CLI)} --distro {DISTRO}"
        f" --version {VERSION} --name {nom}"
        f" --vcpus 2 --memory 4096 --disk-size 20G"
        f" --ssh-key {shlex.quote(cle_publique())}"
        + (
            f" --cache-ca {shlex.quote(CA)}"
            if avec_cache
            else " --cache-bypass"
        )
        + f" --password erplibre --assume-yes"
    )
    if dry_run:
        dire(f"  [à blanc] {cmd}", journal)
        return "10.10.10.150"
    code, sortie = executer(cmd, DELAI_CREATION, journal, montrer=True)
    if code:
        dire(f"  ✗ {nom} : deploy_qemu rend {code}", journal)
        return ""
    return adresse_de(nom, journal)


def adresse_de(nom, journal):
    """L'adresse que le bail DHCP de libvirt donne à la VM."""
    for _essai in range(30):
        code, sortie = executer(
            f"virsh -c qemu:///system domifaddr {shlex.quote(nom)}"
            " --source lease",
            60,
        )
        if not code:
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)/", sortie)
            if m:
                return m.group(1)
        time.sleep(10)
    dire(f"  ✗ {nom} : aucune adresse au bail après cinq minutes", journal)
    return ""


def dans_la_vm(adresse, commande, delai, journal, montrer=False):
    ssh = (
        "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        f" -o ConnectTimeout=15 erplibre@{adresse} {shlex.quote(commande)}"
    )
    return executer(ssh, delai, journal, montrer=montrer)


def attendre_ssh(adresse, journal):
    for _essai in range(40):
        code, _ = dans_la_vm(adresse, "true", 30, None)
        if not code:
            return True
        time.sleep(15)
    dire(f"  ✗ {adresse} : ssh muet après dix minutes", journal)
    return False


def poser_les_paquets(adresse, journal, dry_run=False):
    """Le lot fixe, dans la VM. C'est CE trafic que la mesure regarde."""
    if dry_run:
        dire(f"  [à blanc] pacman -S {PAQUETS} sur {adresse}", journal)
        return True
    code, sortie = dans_la_vm(
        adresse,
        f"sudo pacman -Syu --noconfirm && sudo pacman -S --needed"
        f" --noconfirm {PAQUETS}",
        DELAI_PAQUETS,
        journal,
        montrer=True,
    )
    if code:
        dire(f"  ✗ pacman rend {code} sur {adresse}", journal)
        # La sortie est le seul indice quand le cache est en cause : un
        # certificat rejeté, un 504 du cache hors ligne.
        for ligne in (sortie or "").splitlines()[-15:]:
            dire(f"    | {ligne}", journal)
        return False
    return True


# --------------------------------------------------------------------------
# La mesure
# --------------------------------------------------------------------------


def paquets_seulement(lignes):
    """Les seules lignes qui portent un fichier de paquet.

    L'index et les pages sont écartés : ils ne sont JAMAIS servis du cache
    quand l'amont répond, et les compter ferait échouer un test qui mesure
    autre chose.
    """
    return [
        l
        for l in lignes
        if str(l.get("url", "")).endswith((".pkg.tar.zst", ".pkg.tar.xz"))
    ]


def verdict(premier, second, journal):
    """Le critère, puis la manchette. Rend True si le cache a servi."""
    p1 = paquets_seulement(premier)
    p2 = paquets_seulement(second)
    vues1 = {l["url"] for l in p1}

    # Le critère : ce que les DEUX ont demandé ne doit pas être ressorti.
    fautes = [l for l in p2 if l["url"] in vues1 and l.get("upstream")]
    # Ce que la seconde a découvert seule : légitime sur une publication
    # continue, montré pour que personne ne prenne un miroir qui bouge pour
    # une panne de cache.
    neufs = [l for l in p2 if l["url"] not in vues1]

    octets_amont = sum(l.get("bytes", 0) for l in p2 if l.get("upstream"))
    octets_cache = sum(l.get("bytes", 0) for l in p2 if not l.get("upstream"))

    dire("", journal)
    dire("  ── Mesure ──", journal)

    # Une mesure VIDE n'est pas un succès. Sans cette garde, un cache que
    # personne ne traverse rend « aucune faute » et le test sort en 0 : c'est
    # exactement ce qu'un détournement posé sur le mauvais sous-réseau
    # produit, l'installation ayant par ailleurs tout réussi.
    if not p1 and not p2:
        dire(
            "  ✗ ÉCHEC : aucun fichier de paquet n'a traversé le cache.",
            journal,
        )
        dire(
            "    Les VM ne passent pas par lui. Comparer le sous-réseau des",
            journal,
        )
        dire("    règles avec celui que libvirt sert vraiment :", journal)
        dire("      sudo nft list table ip erplibre_qemu_cache", journal)
        dire("      virsh -c qemu:///system net-dumpxml default", journal)
        return False
    if not p2:
        dire(
            "  ✗ ÉCHEC : la première VM a rempli le cache, la seconde ne lui"
            " a rien demandé.",
            journal,
        )
        return False
    dire(f"  1re VM : {len(p1)} fichiers de paquets demandés", journal)

    # Un cache déjà chaud sert AUSSI la première VM. Le critère reste tenu,
    # mais la démonstration change : ce n'est plus « la première remplit, la
    # seconde est servie », c'est « un cache chaud sert les deux ». Le dire,
    # sans quoi deux colonnes identiques passent pour une anomalie.
    amont1 = sum(l.get("bytes", 0) for l in p1 if l.get("upstream"))
    if p1 and not amont1:
        dire(
            "  ⚠ le cache était DÉJÀ chaud : la 1re VM n'a rien tiré de"
            " l'amont.",
            journal,
        )
        dire(
            "    Le critère tient, mais le remplissage n'est pas démontré"
            " ici.",
            journal,
        )
        dire(
            "    Pour l'exiger, vider le cache avant :"
            " /var/cache/erplibre_go_qemu_cache",
            journal,
        )
    dire(
        f"  2e VM  : {len(p2)} demandés, dont {len(neufs)} inconnus du cache",
        journal,
    )
    dire(f"  servis du disque : {octets_cache} octets", journal)
    dire(f"  tirés de l'amont : {octets_amont} octets", journal)
    if neufs:
        dire(
            f"  ({len(neufs)} fichiers neufs : le miroir a publié entre les"
            " deux déploiements, ce qui est normal sur Arch)",
            journal,
        )
        for l in neufs[:5]:
            dire(f"    + {l['url'].rsplit('/', 1)[-1]}", journal)
    if fautes:
        dire("", journal)
        dire(
            f"  ✗ ÉCHEC : {len(fautes)} fichier(s) déjà vus ont été retirés"
            " de l'amont",
            journal,
        )
        for l in fautes[:10]:
            dire(f"    ! {l['url']}", journal)
        return False
    dire("", journal)
    dire("  ✓ aucun fichier déjà vu n'est ressorti sur le réseau", journal)
    return True


# --------------------------------------------------------------------------
# La contre-épreuve
# --------------------------------------------------------------------------


def couper_lamont(journal, dry_run=False):
    """Prive le SEUL service du cache de son accès sortant.

    Par le compte du service — « meta skuid » — et non par une règle générale :
    couper tout le 443 de l'orchestrateur emporterait la session ssh depuis
    laquelle ce test se lance.
    """
    regles = (
        f"table inet {TABLE_BLOCAGE} {{\n"
        f"  chain sortie {{\n"
        f"    type filter hook output priority 0; policy accept;\n"
        f"    meta skuid {SERVICE_USER} tcp dport {{ 80, 443 }} drop\n"
        f"  }}\n"
        f"}}\n"
    )
    if dry_run:
        dire("  [à blanc] règles de coupure :", journal)
        for ligne in regles.splitlines():
            dire(f"    {ligne}", journal)
        return True
    code, sortie = executer(
        f"printf %s {shlex.quote(regles)} | sudo nft -f -", 60, journal
    )
    if code:
        dire(f"  ✗ coupure impossible : {sortie}", journal)
        return False
    return True


def rebrancher_lamont(journal, dry_run=False):
    if dry_run:
        dire(f"  [à blanc] nft delete table inet {TABLE_BLOCAGE}", journal)
        return
    executer(
        f"sudo nft delete table inet {TABLE_BLOCAGE} 2>/dev/null || true",
        60,
        journal,
    )


def contre_epreuve(journal, rapport, dry_run=False):
    """Une troisième VM, l'amont du cache coupé. Elle doit réussir.

    C'est ce qui distingue un cache d'une simple accélération : sans réseau,
    le déploiement tient encore sur l'index stocké.
    """
    dire("", journal)
    dire("  ── Contre-épreuve : amont coupé ──", journal)
    if not couper_lamont(journal, dry_run):
        return False
    try:
        nom = f"{NOM_BASE}-3"
        rapport["vms"].append(nom)
        ecrire_rapport(rapport)
        adresse = deployer(nom, journal, dry_run)
        if not adresse:
            return False
        noter_uuid(rapport, nom, dry_run)
        if not dry_run and not attendre_ssh(adresse, journal):
            return False
        ok = poser_les_paquets(adresse, journal, dry_run)
        if ok:
            dire(
                "  ✓ la troisième VM s'est bâtie sans que le cache joigne"
                " l'amont",
                journal,
            )
        return ok
    finally:
        # TOUJOURS : une coupure laissée en place priverait le cache de réseau
        # bien après la fin du test, et la panne se découvrirait ailleurs.
        rebrancher_lamont(journal, dry_run)
        dire("  amont rebranché", journal)


# --------------------------------------------------------------------------
# Rapport et destruction
# --------------------------------------------------------------------------


def noter_uuid(rapport, nom, dry_run=False):
    """L'UUID du domaine, tout de suite après sa création.

    C'est ce que « --detruire » vérifiera : sans lui, la destruction
    procéderait par le nom, et un nom se réutilise.
    """
    if dry_run:
        return
    uuid = Descente.uuid_libvirt(nom)
    if not uuid:
        dire(f"  ⚠ {nom} : UUID illisible, destruction par le nom", None)
        return
    rapport.setdefault("uuids", {})[nom] = uuid
    ecrire_rapport(rapport)


def ecrire_rapport(rapport):
    with open(rapport["_fichier"], "w", encoding="utf-8") as fh:
        json.dump(
            {k: v for k, v in rapport.items() if k != "_fichier"}, fh, indent=2
        )


def detruire(dry_run=False):
    """Défait ce que les rapports récents nomment, chacun une fois.

    À travers TOUS les rapports et non le dernier : une exécution qui échoue
    en écrit un neuf, et s'en tenir à celui-là laisserait vivantes les
    machines d'une exécution antérieure — celles-là mêmes qui font échouer la
    suivante en occupant leur disque.
    """
    journal = journal_neuf()
    machines, lus = machines_a_defaire()
    if not machines:
        dire("  rien à défaire : aucun rapport ne nomme de VM.", journal)
        return 0
    dire(
        f"  {len(lus)} rapport(s) lus, {len(machines)} machine(s) nommée(s)",
        journal,
    )
    for nom in sorted(machines):
        # L'UUID noté à la création, et non le nom : un nom se réutilise, et
        # « --remove-all-storage » efface un disque pour de bon. La fonction
        # du dépôt refuse d'agir quand l'UUID ne correspond pas.
        detruire_etage1(
            journal, nom, dry_run=dry_run, attendu=machines[nom] or None
        )
    # Une coupure oubliée par un test interrompu : la retirer fait partie du
    # ménage, et l'opération est sans effet si elle n'existe pas.
    rebrancher_lamont(journal, dry_run)
    defaire_les_exceptions(sorted(machines), journal, dry_run)
    return 0


def defaire_les_exceptions(noms, journal, dry_run=False):
    """Rend au cache les VM que le témoin en avait soustraites.

    Une adresse MAC libérée se réattribue : l'exception laissée derrière une
    VM détruite soustrairait au cache une machine neuve que personne n'a
    exceptée, et rien ne le dirait — la VM télécharge normalement, le journal
    du cache reste simplement muet à son sujet.
    """
    code, sortie = executer(f"sudo -n {CACHE_BIN} --bypass-list", 30, journal)
    if code:
        return
    for ligne in (sortie or "").split("\n"):
        champs = ligne.split(None, 1)
        if len(champs) < 2 or champs[1].strip() not in noms:
            continue
        mac = champs[0]
        if dry_run:
            dire(f"  [à blanc] exception retirée : {mac}", journal)
            continue
        executer(
            f"sudo -n {CACHE_BIN} --bypass-del {mac} | sudo -n nft -f -",
            30,
            journal,
        )
        dire(f"  exception retirée : {mac}", journal)


# --------------------------------------------------------------------------


def main(argv=None):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument("--detruire", action="store_true")
    parseur.add_argument(
        "--hors-ligne",
        action="store_true",
        help="ajoute une troisième VM, l'amont du cache coupé",
    )
    parseur.add_argument(
        "--sans-cache",
        action="store_true",
        help="le TÉMOIN : deux VM qui ne passent pas par le cache, pour"
        " mesurer ce que son absence coûte",
    )
    parseur.add_argument(
        "--rapport",
        action="store_true",
        help="comparer les dernières exécutions, avec et sans cache",
    )
    args = parseur.parse_args(argv)

    if args.rapport:
        return rapport_comparatif()
    if args.detruire:
        return detruire(args.dry_run)

    journal = journal_neuf()
    dire(f"  journal : {journal}", journal)
    if not args.dry_run and not prealables(journal):
        return 1

    acces = journal_du_cache()
    if not acces:
        dire(
            "  ✗ le service ne tient pas de journal d'accès : la mesure est"
            f" impossible. Poser EL_ACCESS_LOG dans {CONF}.",
            journal,
        )
        if not args.dry_run:
            return 1

    rapport = {
        "_fichier": chemin_rapport(),
        "outil": OUTIL,
        "debut": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "vms": [],
        "cache": not args.sans_cache,
        # Un plan à blanc ne crée rien et ne mesure rien. Il écrit pourtant un
        # rapport, et sans cette marque le comparatif compte ses durées de
        # zéro comme des mesures : il montre alors des exécutions qui n'ont
        # jamais eu lieu et tire la moyenne vers le bas.
        "dry_run": bool(args.dry_run),
        "journal": journal,
    }
    ecrire_rapport(rapport)

    decalage = 0
    if acces and os.path.exists(acces):
        decalage = os.path.getsize(acces)

    return _boucle(args, rapport, journal, acces, decalage)


def _boucle(args, rapport, journal, acces, decalage):
    """Les deux VM, la mesure, et ce qui suit. Séparé pour que le témoin
    puisse rallumer le service quoi qu'il arrive."""
    fenetres = []
    for rang in (1, 2):
        dire("", journal)
        dire(f"  ── VM {rang} ──", journal)
        nom = f"{NOM_BASE}-{rang}"
        # NOTÉ AVANT la création : une création échouée à mi-chemin laisserait
        # sinon une machine que le rapport ne nomme nulle part.
        rapport["vms"].append(nom)
        ecrire_rapport(rapport)
        adresse = deployer(
            nom, journal, args.dry_run, avec_cache=not args.sans_cache
        )
        if not adresse:
            return 1
        noter_uuid(rapport, nom, args.dry_run)
        if not args.dry_run and not attendre_ssh(adresse, journal):
            return 1
        debut = time.time()
        if not poser_les_paquets(adresse, journal, args.dry_run):
            return 1
        duree = time.time() - debut
        lignes, decalage = ([], decalage)
        if acces:
            lignes, decalage = lignes_depuis(acces, decalage)
        fenetres.append(lignes)
        # La durée est la seule matière d'une comparaison avec le témoin :
        # gardée dans le rapport, elle survit à la session.
        rapport.setdefault("durees", {})[nom] = round(duree, 1)
        rapport.setdefault("octets", {})[nom] = {
            "amont": sum(
                l.get("bytes", 0) for l in lignes if l.get("upstream")
            ),
            "cache": sum(
                l.get("bytes", 0) for l in lignes if not l.get("upstream")
            ),
        }
        ecrire_rapport(rapport)
        dire(f"  VM {rang} : paquets posés en {duree:.0f} s", journal)

    ok = True
    if args.dry_run:
        dire("", journal)
        dire("  [à blanc] la mesure comparerait les deux fenêtres.", journal)
    elif args.sans_cache:
        # Le témoin ne prouve rien sur le cache : il MESURE ce que coûte son
        # absence. Lui appliquer le critère n'aurait aucun sens.
        dire("", journal)
        dire("  ── Témoin : sans cache ──", journal)
        for nom, d in (rapport.get("durees") or {}).items():
            dire(f"  {nom} : {d:.0f} s", journal)
        dire("  Comparer avec « --rapport ».", journal)
    else:
        ok = verdict(fenetres[0], fenetres[1], journal)

    if args.hors_ligne:
        ok = contre_epreuve(journal, rapport, args.dry_run) and ok

    rapport["fin"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    rapport["cache"] = not args.sans_cache
    rapport["verdict"] = "ok" if ok else "échec"
    ecrire_rapport(rapport)
    dire("", journal)
    dire(f"  rapport : {rapport['_fichier']}", journal)
    dire(f"  défaire : {sys.argv[0]} --detruire", journal)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
