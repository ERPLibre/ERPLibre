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
    return f"sudo {_retrait(table)}"


def _retrait(table: str = TABLE) -> str:
    """Le retrait nu, sans sudo : `restore_cmd` le préfixe, le guet le lance
    déjà en root."""
    return f"nft delete table inet {table} 2>/dev/null || true"


# Le guet : une unité systemd transitoire, posée par root au lancement des
# installations, qui attend que chaque journal porte son marqueur de sortie
# puis lève la coupure. Les installations tournent détachées et survivent au
# tableau de bord : lever la coupure à sa fermeture les ferait finir en ligne
# sans que rien ne le dise, et l'y garder la ferait durer tant que l'écran
# reste ouvert. Un processus Python ne tient pas ce rôle : SIGKILL, une
# session ssh perdue ou une panne l'emportent sans dérouler aucun « finally ».
UNITE_GUET = "erplibre-qemu-offline-lift"

# Durée maximale du guet, en secondes. Au-delà, systemd l'arrête et la levée
# (ExecStopPost) court quand même : une installation dont le marqueur ne vient
# jamais — session ssh pendue, VM supprimée — ne prive pas le cache d'amont
# indéfiniment.
DUREE_MAX_GUET = 12 * 3600

# Période de relecture des journaux. Le marqueur est la dernière ligne écrite ;
# elle borne le retard de la levée sur la fin réelle.
PAS_GUET = 10


# systemd réécrit « ${VAR} », un « $VAR » pris comme argument entier et
# « $$ » dans les arguments qu'il exécute, et les spécificateurs « % » dans
# les valeurs passées par « -p ». Un chemin de journal qui en porte serait
# réécrit : le guet ne le trouverait jamais, et la coupure tiendrait jusqu'à
# RuntimeMaxSec au lieu de tomber avec la dernière installation.
CARACTERES_REECRITS = ("$", "%")


def chemins_surs(journaux) -> bool:
    """Vrai si aucun chemin ne porte un caractère que systemd réécrirait.

    Refuser vaut mieux qu'échapper : « $$ » n'est juste que si systemd
    substitue réellement, ce qui dépend de sa version et de la voie par
    laquelle la commande lui arrive. Un refus ramène la levée au « finally »,
    dont le comportement est connu.
    """
    return all(
        not any(c in str(j) for c in CARACTERES_REECRITS) for j in journaux
    )


def script_attente(marqueur: str, pas: int = PAS_GUET) -> str:
    """Le script du guet : il rend 0 quand CHAQUE journal passé en argument
    porte `marqueur` dans ses derniers octets, et repasse toutes les `pas`
    secondes sinon.

    Un journal ABSENT compte pour non fini. Le guet part juste après le
    lancement des installations, et leurs journaux peuvent ne pas exister
    encore : les compter pour finis lèverait la coupure sur-le-champ, et
    l'installation se terminerait en ligne sans que rien ne le dise. Un
    journal qui ne viendra jamais — son répertoire effacé — tient donc la
    coupure jusqu'à RuntimeMaxSec, et la levée immédiate est affichée.

    Sans pipefail, « tail | grep » rend le statut de grep : un fichier absent
    ne livre rien, et le marqueur n'y est pas trouvé.
    """
    return (
        "while :; do fini=1; "
        'for f in "$@"; do '
        f'tail -c 4096 "$f" 2>/dev/null | grep -qF {shlex.quote(marqueur)}'
        " || fini=0; "
        'done; [ "$fini" = 1 ] && exit 0; '
        f"sleep {int(pas)}; done"
    )


def guet_cmd(
    journaux,
    marqueur: str,
    duree: int = DUREE_MAX_GUET,
    table: str = TABLE,
    unite: str = UNITE_GUET,
) -> str:
    """La commande qui confie la levée à root, par une unité transitoire.

    `journaux` : chemins des journaux d'installation, un par VM ; `marqueur` :
    ce que l'enveloppe détachée écrit en dernière ligne à la fin de chacune.
    Les chemins voyagent en ARGUMENTS du shell (« sh -c script sh j1 j2 … »)
    et non dans le script : un espace ou une apostrophe dans un chemin ne
    peut rien y casser.

    ExecStopPost court à la fin normale, au dépassement de RuntimeMaxSec et à
    un « systemctl stop » : la coupure tombe dans les trois cas. « --collect »
    efface l'unité même en échec, sans quoi son nom resterait pris.

    Le script d'attente vient de `script_attente` : un journal absent y
    compte pour NON fini.

    systemd remplace « ${VAR} » et « $$ » dans les arguments qu'il exécute : le
    script n'en contient aucun, seules les formes « $f » et « "$@" », qu'il
    laisse intactes, y figurent.
    """
    attente = script_attente(marqueur)
    parties = [
        "sudo",
        "systemd-run",
        f"--unit={unite}",
        "--collect",
        "--description=ERPLibre QEMU offline cut lift",
        "-p",
        f"RuntimeMaxSec={duree}",
        "-p",
        f'ExecStopPost=/bin/sh -c "{_retrait(table)}"',
        "/bin/sh",
        "-c",
        attente,
        "sh",
        *journaux,
    ]
    return " ".join(shlex.quote(p) for p in parties)


def guet_actif_cmd(unite: str = UNITE_GUET) -> str:
    """Rend 0 tant que le guet tourne. Sans sudo : lire l'état d'une unité
    est ouvert à tout compte."""
    return f"systemctl is-active --quiet {shlex.quote(unite)}"


def lever_maintenant_cmd(unite: str = UNITE_GUET) -> str:
    """La levée immédiate quand le guet tourne : l'arrêter fait courir son
    ExecStopPost, qui retire la table. Retirer la table seule laisserait le
    guet attendre pour rien."""
    return f"sudo systemctl stop {shlex.quote(unite)}"


def table_posee_cmd(table: str = TABLE) -> str:
    """Rend 0 si la coupure est posée, 1 si elle ne l'est pas, 2 si on ne
    peut pas le savoir.

    Le troisième cas est la raison d'être de la commande : « ! nft list
    table » conclurait à l'absence dès que sudo refuse ou que nft manque, et
    un rebranchement raté se lirait comme réussi. La table est cherchée
    ligne entière dans « nft list tables » : un nom qui la prolongerait ne
    compte pas.
    """
    ligne = shlex.quote(f"table inet {table}")
    return (
        "(l=$(sudo nft list tables) || exit 2; "
        f"printf '%s\\n' \"$l\" | grep -qxF {ligne} && exit 0; exit 1)"
    )


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
