#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Priver le cache de téléchargement de son amont, et l'y rebrancher.

Ce qu'on coupe n'est PAS le réseau de la VM. La VM en a besoin : le cache vit
sur l'orchestrateur, et c'est par son réseau qu'elle l'atteint. Lui couper la
patte ne prouverait rien — elle échouerait sans jamais interroger le cache.

Ce qu'on coupe est l'amont du SEUL service du cache. La VM garde son réseau
et parle au cache comme d'habitude ; le cache, lui, ne peut plus rien tirer de
l'internet. Tout ce qui arrive encore dans la VM vient donc du disque.

La coupure porte sur le COMPTE du service, jamais sur le port. Une règle
générale sur le 443 de l'orchestrateur emporterait la session ssh depuis
laquelle le déploiement est lancé, et la machine se couperait au milieu de la
commande qui la configure.

Le module REND le texte des règles et l'applique à part : un test vérifie
alors les règles au caractère près sans toucher au pare-feu de la machine qui
exécute les tests.
"""

import shlex

# Le compte sous lequel le service tourne. Le script d'installation porte la
# même valeur — il est en shell et ne peut pas la lire ici ; un test compare
# les deux, la dérive entre deux copies étant le seul risque de cette
# duplication.
SERVICE_USER = "elqcache"

# Une table à nous, effaçable d'un geste. Distincte de celle du détournement :
# la coupure est temporaire et la redirection ne l'est pas, les mêler ferait
# tomber le détournement de tout le pont en rebranchant l'amont.
TABLE = "erplibre_qemu_cache_offline"


def nft_rules(user: str = SERVICE_USER, table: str = TABLE) -> str:
    """Le jeu de règles à passer à « nft -f - ».

    « meta skuid » filtre sur l'UID du processus émetteur : seul ce que le
    service envoie tombe, le reste de la machine — session ssh, libvirt, les
    VM elles-mêmes — n'est pas touché.

    Les deux ports : le cache tire aussi en clair, et ne couper que le 443
    laisserait passer tout un miroir Debian.
    """
    return (
        f"table inet {table} {{\n"
        f"  chain sortie {{\n"
        f"    type filter hook output priority 0; policy accept;\n"
        f"    meta skuid {user} tcp dport {{ 80, 443 }} drop\n"
        f"  }}\n"
        f"}}\n"
    )


def cut_cmd(user: str = SERVICE_USER, table: str = TABLE) -> str:
    """La commande qui pose la coupure."""
    return f"printf %s {shlex.quote(nft_rules(user, table))} | sudo nft -f -"


def restore_cmd(table: str = TABLE) -> str:
    """La commande qui la retire, muette si elle n'était pas là.

    Toujours vraie : le rebranchement se fait dans un « finally », et une
    coupure déjà retirée ne doit pas y lever d'erreur qui masquerait celle
    d'origine.
    """
    return f"sudo nft delete table inet {table} 2>/dev/null || true"


# Là où le service écrit ses réglages. Le journal d'accès y est nommé : le
# chercher là plutôt que de recopier son chemin, qui est réglable.
CONF = "/etc/erplibre_go_qemu_cache/env"

# Les issues qui prouvent qu'un CORPS est en réserve. « fetched » n'en est
# pas : elle couvre aussi le « 304 » d'une revalidation, qui n'a pas de corps.
ISSUES_EN_RESERVE = ("stored", "hit", "stale")


def journal(conf: str = CONF) -> str:
    """Chemin du journal d'accès, ou "" s'il n'est pas lisible."""
    try:
        with open(conf, encoding="utf-8") as fh:
            for ligne in fh:
                if ligne.startswith("EL_ACCESS_LOG="):
                    return ligne.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def jeton_de_suite(distro: str, version: str) -> str:
    """Ce qui, dans une URL, identifie la SUITE de dépôt d'un système.

    Rend "" quand aucun jeton ne l'identifie de façon sûre : mieux vaut ne
    pas se prononcer que rassurer à tort. Un dépôt Fedora et un dépôt openSUSE
    se ressemblent dans l'URL — leur « /repodata/ » ne dit pas quelle version
    il sert — et un cache rempli pour une version passerait pour rempli pour
    toutes.

    Les familles apt, elles, portent le nom de code dans « /dists/<nom>/ »,
    et il est unique. Le nom vient du CATALOGUE du déploiement, jamais d'une
    table recopiée ici.
    """
    from script.qemu.deploy_qemu import DISTROS, cache_family

    if cache_family(distro) != "apt":
        return ""
    versions = (DISTROS.get(distro) or [{}])[0]
    entree = versions.get(version) or []
    return f"/dists/{entree[0]}/" if entree else ""


def detient_la_suite(distro: str, version: str, chemin: str = "") -> bool:
    """Le cache a-t-il un corps en réserve pour cette suite de dépôt ?

    Le journal d'accès EST la mesure : il porte l'URL et l'issue de chaque
    requête, et une issue de la liste ci-dessus prouve qu'un corps existe.

    Rend True dès qu'on ne sait pas juger — jeton inconnu, journal illisible :
    un avertissement qui se déclenche sans savoir apprend à passer outre, et
    c'est alors celui qui compte qu'on ne lit plus.
    """
    jeton = jeton_de_suite(distro, version)
    if not jeton:
        return True
    chemin = chemin or journal()
    if not chemin:
        return True
    import json
    import os

    if not os.path.exists(chemin):
        return True
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                if jeton not in ligne:
                    continue
                try:
                    d = json.loads(ligne)
                except ValueError:
                    continue
                if d.get("outcome") in ISSUES_EN_RESERVE and jeton in (
                    d.get("url") or ""
                ):
                    return True
    except OSError:
        return True
    return False


def suites_absentes(vms) -> list:
    """Les (système, version) dont le cache n'a rien, sans doublon.

    Ce qu'une VM hors ligne ne pourra pas lire : son apt échouera sur l'index
    de sa suite de base, et aucun paquet de cette suite ne sera trouvable.
    """
    vus, manquantes = set(), []
    for vm in vms or ():
        cle = (vm.get("distro") or "", vm.get("version") or "")
        if not cle[0] or cle in vus:
            continue
        vus.add(cle)
        if not detient_la_suite(*cle):
            manquantes.append(cle)
    return manquantes
