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
