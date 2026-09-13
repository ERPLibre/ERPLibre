#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Couper l'internet d'un déploiement hors ligne, et le rendre.

La coupure ferme trois sorties et laisse l'hôte joignable :
- l'amont du SEUL service du cache, qui ne peut plus rien tirer de
  l'internet : ce qu'il sert encore vient de son disque ;
- la sortie DIRECTE des VM, celle que l'hôte relaie : ping, autres ports,
  UDP, IPv6. Un pas d'installation qui prendrait un autre chemin que le
  cache — un clone par ssh, un dépôt sur un port à lui, du QUIC — échoue
  donc, au lieu de réussir en ligne sans que rien ne le montre ;
- la résolution des noms par l'internet : un résolveur à part, sur l'hôte,
  répond à TOUT nom une adresse fictive. Le détournement du cache vise un
  PORT et non une adresse, et le cache reconnaît le site à son nom (SNI,
  en-tête Host) : la VM joint donc encore ce que le cache détient, et rien
  d'autre. Aucune requête DNS d'une VM ne quitte l'hôte.

Reste ce qu'une VM demande à l'HÔTE lui-même : son 80 et son 443, détournés
vers le cache avant tout routage ; les noms, auxquels l'hôte répond seul ;
la session ssh de l'opérateur ; le trafic entre VM du même pont.

La coupure du cache porte sur son COMPTE, jamais sur le port. Une règle
générale sur le 443 de l'orchestrateur emporterait la session ssh depuis
laquelle le déploiement est lancé, et la machine se couperait au milieu de la
commande qui la configure.

Le module REND le texte des règles et l'applique à part : un test vérifie
alors les règles au caractère près sans toucher au pare-feu de la machine qui
exécute les tests.
"""

import re
import shlex
import shutil

# Le compte sous lequel le service tourne. Le script d'installation porte la
# même valeur — il est en shell et ne peut pas la lire ici ; un test compare
# les deux, la dérive entre deux copies étant le seul risque de cette
# duplication.
SERVICE_USER = "elqcache"

# Une table à nous, effaçable d'un geste. Distincte de celle du détournement :
# la coupure est temporaire et la redirection ne l'est pas, les mêler ferait
# tomber le détournement de tout le pont en rebranchant l'amont.
TABLE = "erplibre_qemu_cache_offline"

# Le pont des VM quand le service n'en nomme aucun : celui que libvirt donne
# à son réseau par défaut.
PONT_PAR_DEFAUT = "virbr0"

# Un nom d'interface tel que le noyau les accepte. Il entre tel quel dans les
# règles : une apostrophe ou un guillemet y casserait le jeu entier, et un nom
# faux donnerait une règle qui ne viserait rien — des VM restées en ligne
# sous une coupure annoncée.
_NOM_DE_PONT = re.compile(r"[A-Za-z0-9_.:-]{1,15}")

# Le résolveur fictif. Toute question reçoit la même adresse, que le
# détournement conduit au cache quelle qu'elle soit : 192.0.2.1 est réservée à
# la documentation (RFC 5737) et jamais routée. L'AAAA répond 100::1, du
# préfixe réservé au rejet (RFC 6666) : sans réponse, dnsmasq REFUSE la
# question, et un résolveur qui reçoit un refus peut écarter le serveur. Sans
# route IPv6, le client repasse aussitôt en IPv4 ; avec une route, la chaîne
# « transit » jette ce trafic.
ADRESSE_FICTIVE_V4 = "192.0.2.1"
ADRESSE_FICTIVE_V6 = "100::1"

# Hors des ports que tiennent déjà le résolveur de libvirt (53) et le mDNS
# de l'hôte (5353).
PORT_DNS = 10053

UNITE_DNS = "erplibre-qemu-offline-dns"


def nft_rules(
    user: str = SERVICE_USER,
    table: str = TABLE,
    pont: str = PONT_PAR_DEFAUT,
    refus: bool = True,
) -> str:
    """Le jeu de règles à passer à « nft -f - ».

    Chaîne « sortie » : « meta skuid » filtre sur l'UID du processus
    émetteur, si bien que seul ce que le service du cache envoie tombe ; la
    session ssh et le reste de l'hôte ne sont pas touchés. Les deux ports : le
    cache tire aussi en clair, et ne couper que le 443 laisserait passer tout
    un miroir Debian.

    Les deux chaînes de filtrage REFUSENT au lieu de jeter. Un paquet jeté
    fait pendre l'établissement jusqu'au délai de celui qui compose : le
    cache paierait ce délai à chaque adresse qu'il ne détient pas, et un
    « apt-get update » en enchaîne des centaines. Refusé, l'établissement
    échoue sur-le-champ, et le cache rend son 504 — ou sa copie — aussitôt.
    « refus=False » rend la variante qui jette : un noyau mis à jour sans
    redémarrage n'a plus ses modules sur le disque, et ne peut pas charger
    celui du refus. `cut_cmd` la pose alors en repli.

    Chaîne « transit » : elle refuse ce que le pont relaie vers une AUTRE
    interface, c'est-à-dire la sortie directe des VM. Ce qui vise l'hôte — le
    80 et le 443 détournés vers le cache avant le routage, le résolveur, la
    session ssh — passe par « input » et n'est pas touché ; le trafic entre
    VM ne quitte pas le pont. Une chaîne à soi suffit : un « accept » de
    libvirt dans SA table n'empêche pas ce refus de jouer, un paquet
    traversant toutes les chaînes de base de son point d'accroche.

    Chaîne « noms » : le DNS des VM — UDP et TCP 53, quelle que soit la
    destination, un résolveur public compris — est détourné vers le
    résolveur fictif de `dns_cmd`. Elle ne touche ni le 80 ni le 443, que la
    table du cache détourne de son côté.

    Lève ValueError sur un nom de pont qu'une interface ne peut pas porter.
    """
    if not _NOM_DE_PONT.fullmatch(pont or ""):
        raise ValueError(f"nom de pont refusé : {pont!r}")
    sortie, transit = (
        ("reject with tcp reset", "reject") if refus else ("drop", "drop")
    )
    return (
        f"table inet {table} {{\n"
        f"  chain sortie {{\n"
        f"    type filter hook output priority 0; policy accept;\n"
        f"    meta skuid {user} tcp dport {{ 80, 443 }} {sortie}\n"
        f"  }}\n"
        f"  chain noms {{\n"
        f"    type nat hook prerouting priority dstnat; policy accept;\n"
        f'    iifname "{pont}" udp dport 53 redirect to :{PORT_DNS}\n'
        f'    iifname "{pont}" tcp dport 53 redirect to :{PORT_DNS}\n'
        f"  }}\n"
        f"  chain transit {{\n"
        f"    type filter hook forward priority 0; policy accept;\n"
        f'    iifname "{pont}" oifname != "{pont}" {transit}\n'
        f"  }}\n"
        f"}}\n"
    )


def pont_des_vm() -> str:
    """Le pont que le service du cache détourne, lu dans ses réglages."""
    return reglage("EL_BRIDGE") or PONT_PAR_DEFAUT


def cut_cmd(
    user: str = SERVICE_USER, table: str = TABLE, pont: str = "", dns: str = ""
) -> str:
    """La commande qui pose la coupure : la table, PUIS le résolveur fictif.

    Tout ou rien. Si le résolveur ne part pas, la table est retirée aussitôt
    et la commande échoue : sans lui, le port 53 des VM mènerait à un port
    muet, et l'installation échouerait sur la résolution des noms — une
    raison qui n'est pas celle qu'on mesure. Sans dnsmasq sur l'hôte, la
    commande échoue d'emblée, pour la même raison.

    Le jeu qui refuse est tenté d'abord, celui qui jette en repli, dans le
    même sudo : nft pose un jeu entier ou rien, si bien qu'un refus que le
    noyau ne sait pas charger ne laisse aucune demi-coupure derrière lui.
    """
    pont = pont or pont_des_vm()
    regles = nft_rules(user, table, pont)
    repli = nft_rules(user, table, pont, refus=False)
    dns = dns or dns_cmd(pont)
    if not dns:
        return "false"
    pose = "sudo sh -c " + shlex.quote(
        f"printf %s {shlex.quote(regles)} | nft -f - 2>/dev/null"
        f" || printf %s {shlex.quote(repli)} | nft -f -"
    )
    return f"{pose} && {{ {dns} || {{ {restore_cmd(table)}; false; }}; }}"


def dnsmasq() -> str:
    """Le chemin de dnsmasq sur l'hôte, ou "" : la coupure des noms en
    dépend, et le déploiement le vérifie avant de rien poser."""
    return shutil.which("dnsmasq") or ""


def dns_cmd(
    pont: str = PONT_PAR_DEFAUT,
    binaire: str = "",
    duree: int = 0,
    unite: str = UNITE_DNS,
) -> str:
    """La commande qui fait répondre l'hôte à tout nom, le temps de la coupure.

    Un dnsmasq à part, et non celui de libvirt, auquel on ne touche pas : il
    reprend son rôle dès que la redirection du port 53 tombe avec la table.
    Le nôtre écoute le seul pont, sur PORT_DNS, sans fichier de réglages,
    sans amont (« --no-resolv »), sans /etc/hosts, avec un TTL nul : aucune
    réponse fictive ne survit dans une VM à la levée. Il tourne en unité
    transitoire bornée par RuntimeMaxSec, au-delà de celle du guet.

    Rend "" quand dnsmasq est introuvable.
    """
    binaire = binaire or dnsmasq()
    if not binaire:
        return ""
    if not _NOM_DE_PONT.fullmatch(pont or ""):
        raise ValueError(f"nom de pont refusé : {pont!r}")
    parties = [
        "sudo",
        "systemd-run",
        f"--unit={unite}",
        "--collect",
        "--description=ERPLibre QEMU offline DNS",
        "-p",
        f"RuntimeMaxSec={duree or DUREE_MAX_GUET + 3600}",
        binaire,
        "--keep-in-foreground",
        "--conf-file=/dev/null",
        "--no-resolv",
        "--no-hosts",
        "--no-poll",
        f"--interface={pont}",
        # dnsmasq ajoute la boucle locale à toute liste « --interface » :
        # l'en retirer le cantonne au seul pont.
        "--except-interface=lo",
        "--bind-interfaces",
        f"--port={PORT_DNS}",
        f"--address=/#/{ADRESSE_FICTIVE_V4}",
        f"--address=/#/{ADRESSE_FICTIVE_V6}",
        "--local-ttl=0",
        "--pid-file=",
        "--log-facility=-",
    ]
    return " ".join(shlex.quote(x) for x in parties)


# Le témoin que la levée touche pour annuler la mémoire des amonts muets du
# service. Son nom est tenu en accord avec « SentinelleAmonts » du code Go par
# un test : toucher un fichier que rien ne lit ne réveillerait personne.
SENTINELLE_AMONTS = ".amonts-oublies"
# Le magasin, quand les réglages posés ne se lisent pas. Le service et la
# levée doivent désigner le MÊME fichier, et la levée tourne souvent sans
# l'environnement de l'unité.
CACHE_DIR_DEFAUT = "/var/cache/erplibre_go_qemu_cache"


def sentinelle_amonts(cache_dir: str = "") -> str:
    """Le chemin du témoin, sous le magasin.

    Le réglage posé prime : un magasin déplacé emporte son témoin, sans quoi
    la levée toucherait un fichier hors du répertoire que le service lit.
    """
    import os

    racine = cache_dir or reglage("EL_CACHE_DIR") or CACHE_DIR_DEFAUT
    return os.path.join(racine, SENTINELLE_AMONTS)


def restore_cmd(table: str = TABLE) -> str:
    """La commande qui la retire, muette si elle n'était pas là.

    Toujours vraie : le rebranchement se fait dans un « finally », et une
    coupure déjà retirée ne doit pas y lever d'erreur qui masquerait celle
    d'origine.
    """
    return f"sudo sh -c {shlex.quote(_retrait(table))}"


def _retrait(table: str = TABLE) -> str:
    """Le retrait nu, sans sudo : `restore_cmd` le lance sous « sudo sh -c »,
    le guet le lance déjà en root.

    Il retire la table, arrête le résolveur fictif, ET touche le témoin des
    amonts muets. Arrêter le résolveur seul laisserait le port 53 des VM
    détourné vers un port muet ; retirer la table seule laisserait tourner un
    processus que plus rien n'interroge ; et sans le témoin, les amonts notés
    muets pendant la coupure le resteraient jusqu'à la fin de leur fenêtre,
    la première requête d'après la levée tombant dans le repli alors que le
    réseau est revenu. Aucun canal n'existe vers le service en marche.
    """
    return (
        f"nft delete table inet {table} 2>/dev/null || true; "
        f"systemctl stop {UNITE_DNS} 2>/dev/null || true; "
        f"touch {shlex.quote(sentinelle_amonts())} 2>/dev/null || true"
    )


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
# « stored-status » et « stale-status » n'en sont pas davantage : elles
# portent un objet de STATUT seul — une redirection ou un refus gardés, sans
# corps — et l'index d'une suite gardé en 404 ne la rend pas lisible.
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


# Ce qu'un bureau installe vraiment. Les quatre composants, sur la suite de
# base ET sur ses deux compagnes : « xrdp » vit dans « universe », ses
# dépendances dans « restricted », et les correctifs dans « -security ». Un
# cache rempli pour « main » seul laisse apt sans rien de tout cela.
COMPOSANTS_APT = ("main", "universe", "restricted", "multiverse")
SUFFIXES_APT = ("", "-updates", "-security")

# « /dists/<suite>/<composant>/binary-<arche>/ » : ce que porte l'URL d'un
# index de paquets, et la seule forme qui dise à la fois la suite, le
# composant et l'architecture.
_INDEX_APT = re.compile(r"/dists/([^/]+)/([^/]+)/binary-([^/]+)/")


def composants_absents(vms, chemin: str = "") -> list:
    """[(système, version, ["suite/composant", …])] — ce dont le cache n'a rien.

    Le verdict par SUITE ne suffit pas : une seule URL en réserve sous
    « /dists/<code>/ » le rend muet, alors que « restricted » ou
    « -security » peuvent manquer en entier. apt ne le dit qu'à
    l'installation, par « Unable to locate package », un message qui accuse
    le dépôt et jamais le cache — vingt minutes après la coupure.

    Muet quand on ne sait pas juger — famille sans jeton, journal illisible.
    Muet aussi quand le cache n'a RIEN de ce système : `suites_absentes` le
    dit déjà, et deux avertissements pour une cause apprennent à les
    enchaîner.
    """
    import json
    import os

    chemin = chemin or journal()
    if not chemin or not os.path.exists(chemin):
        return []
    vus = set()
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                if "/dists/" not in ligne:
                    continue
                try:
                    d = json.loads(ligne)
                except ValueError:
                    continue
                if d.get("outcome") not in ISSUES_EN_RESERVE:
                    continue
                trouve = _INDEX_APT.search(d.get("url") or "")
                if trouve:
                    vus.add(trouve.groups())
    except OSError:
        return []

    deja, sortie = set(), []
    for vm in vms or ():
        distro = vm.get("distro") or ""
        version = vm.get("version") or ""
        arche = vm.get("arch") or "amd64"
        cle = (distro, version, arche)
        if not distro or cle in deja:
            continue
        deja.add(cle)
        jeton = jeton_de_suite(distro, version)
        if not jeton:
            continue
        code = jeton.strip("/").split("/")[-1]
        attendus = [
            (code + suffixe, composant)
            for suffixe in SUFFIXES_APT
            for composant in COMPOSANTS_APT
        ]
        manque = [
            f"{suite}/{composant}"
            for suite, composant in attendus
            if (suite, composant, arche) not in vus
        ]
        # Tout manque : le cache ignore ce système, et `suites_absentes` le
        # dira mieux.
        if manque and len(manque) < len(attendus):
            sortie.append((distro, version, manque))
    return sortie


# Les paquets que le déploiement pose HORS du fil observé : leur pose part en
# unité détachée pour que cloud-init rende la main en quelques secondes, si
# bien qu'un échec ne remonte nulle part — ni au suivi, ni au journal des
# manques, qui ne connaît que ce qu'une coupure a déjà fait rater. Le pré-vol
# est donc le seul endroit où leur absence peut encore se dire À TEMPS.
PAQUETS_HORS_SUIVI = ("qemu-guest-agent",)


def paquets_absents(vms, noms=(), chemin: str = "") -> list:
    """Les paquets nommés dont le magasin n'a rien, ou [].

    Le verdict par index ne descend jamais au FICHIER : un cache qui détient
    l'index d'une suite passe pour complet alors qu'aucun octet du paquet
    lui-même n'a jamais traversé. Hors ligne, l'installation échoue vingt
    minutes plus tard sur « Unable to locate package », un message qui accuse
    le dépôt et jamais le cache.

    Jugé sur le journal, comme les autres verdicts : une URL en réserve qui
    porte le nom du paquet suffit. Le nom d'un fichier de paquet porte sa
    version et son architecture, jamais son miroir, si bien que la recherche
    vaut quel que soit le miroir qui l'a servi.

    Muet sans VM et quand le journal ne se lit pas : accuser un cache qu'on
    ne peut pas interroger ferait taire l'avertissement le jour où il compte.
    """
    import json
    import os

    noms = tuple(noms) or PAQUETS_HORS_SUIVI
    chemin = chemin or journal()
    if not (vms or ()) or not chemin or not os.path.exists(chemin):
        return []
    trouves = set()
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                restants = [n for n in noms if n not in trouves]
                if not restants:
                    break
                # Le test de chaîne AVANT le décodage : un journal de
                # déploiement porte des dizaines de milliers de lignes, et
                # les décoder toutes coûterait plus que le verdict ne vaut.
                for nom in restants:
                    if nom not in ligne:
                        continue
                    try:
                        d = json.loads(ligne)
                    except ValueError:
                        continue
                    if d.get("outcome") in ISSUES_EN_RESERVE and nom in (
                        d.get("url") or ""
                    ):
                        trouves.add(nom)
    except OSError:
        return []
    return [nom for nom in noms if nom not in trouves]


def miroirs_absents(depots, racine: str = "") -> list:
    """Les dépôts git déclarés qui n'ont pas encore de miroir, ou [].

    Une négociation git ne se garde pas : le cache tient un dépôt NU par
    amont et le sert localement. Un dépôt jamais mirroré n'a donc rien à
    servir une fois le réseau coupé, et le clone échoue — sans que rien ne
    l'ait annoncé, le verdict par index ne parlant que d'apt et le journal
    des manques ne connaissant que ce qu'une coupure a déjà fait rater.

    Le chemin d'un miroir est « <hôte>/<chemin>.git » sous la racine : la
    même règle que celle qui les pose, l'hôte en faisant partie parce que
    deux forges peuvent servir le même chemin.

    Muet quand la racine ne se lit pas : un magasin absent n'est pas un
    miroir manquant, et deux causes sous un seul message font cesser de lire.
    """
    import os
    from urllib.parse import urlsplit

    racine = racine or os.path.join(
        reglage("EL_CACHE_DIR") or CACHE_DIR_DEFAUT, "git"
    )
    if not os.path.isdir(racine):
        return []
    manque = []
    for depot in depots or ():
        morceaux = urlsplit(depot)
        chemin = morceaux.path.strip("/")
        if chemin.endswith(".git"):
            chemin = chemin[: -len(".git")]
        if not morceaux.netloc or not chemin:
            continue
        attendu = os.path.join(racine, morceaux.netloc, chemin + ".git")
        if not os.path.isdir(attendu):
            manque.append(f"{morceaux.netloc}/{chemin}")
    return manque


# ---------------------------------------------------------------------------
# Ce que les déploiements hors ligne précédents n'ont pas trouvé
# ---------------------------------------------------------------------------
#
# Une ligne « offline-miss » du journal d'accès PROUVE qu'un invité a demandé
# une adresse que le cache n'avait pas, pendant que l'amont était muet. Jointe
# à un déploiement — l'adresse de sa VM et sa fenêtre [début, dernière
# écriture de son log] — elle dit ce que ce déploiement a manqué, donc ce que
# le suivant manquera encore si rien n'a été rempli entre-temps.
#
# Une liste de manques est une BORNE BASSE : l'installation s'arrête au premier
# manque fatal, et ce qui la suivait n'a jamais été demandé.

# Le binaire du service. Le menu du cache porte le même chemin ; un test
# compare les deux.
BINAIRE = "/usr/local/bin/erplibre_go_qemu_cache"

# Un répertoire par déploiement, écrit par le suivi des installations : un
# « session.json » et un log par VM.
RUNS = "~/.erplibre/qemu-install"

# Les méthodes que le cache sait garder. Toute autre le traverse sans copie :
# un POST manqué hors ligne le sera toujours, et le compter dans « au moins
# N » promettrait un remplissage impossible.
METHODES_GARDABLES = ("GET", "HEAD")

# Les points de négociation git (gitSmartPaths, côté Go) ; un test compare.
# Le cache ne garde pas ces échanges : c'est le DÉPÔT qu'il tient, dans son
# miroir, et l'entrée 5 du menu du cache le remplit.
GIT_NEGOCIATION = ("/info/refs", "/git-upload-pack", "/git-receive-pack")

ISSUE_MANQUE = "offline-miss"

# Les issues d'un amont muet : servies du disque faute de réponse. Elles
# naissent d'une coupure, mais aussi EN LIGNE : un amont qui vient de refuser
# une connexion est tenu pour muet quelques secondes, et les requêtes qui ont
# de quoi se rabattre sont servies du disque sans l'appeler. Leur présence
# dans la fenêtre d'une VM ne prouve donc pas qu'elle a tourné coupée ; seul
# le « offline » du manifeste le dit.
ISSUES_AMONT_MUET = ("stale", "stale-status", "keep", ISSUE_MANQUE)

# Ce qui prouve qu'une RÉPONSE est gardée, plus large que ISSUES_EN_RESERVE :
# la VM hors ligne qui reçoit la redirection ou le 404 que l'amont avait rendu
# obtient ce qu'elle aurait eu en ligne.
ISSUES_REPONSE_GARDEE = ISSUES_EN_RESERVE + ("stored-status", "stale-status")

# Les verdicts de « --detient » qui valent détention : un corps, ou un objet
# de statut seul.
DETENTION = ("garde", "statut")

# Combien de déploiements renseignés d'un même nom sont réunis, et jusqu'à
# quel âge. Au-delà, branche, catalogue et cache ont changé, et l'avertissement
# parlerait d'un autre système.
RUNS_RETENUS = 3
AGE_MAX = 30 * 86400


def reglage(nom: str, conf: str = CONF) -> str:
    """Valeur d'un réglage du service (« EL_… »), ou "" s'il est illisible."""
    prefixe = f"{nom}="
    try:
        with open(conf, encoding="utf-8") as fh:
            for ligne in fh:
                if ligne.startswith(prefixe):
                    return ligne.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def instant(texte):
    """Secondes depuis l'époque d'une date RFC 3339, ou None.

    Le journal date en UTC ; une date sans fuseau est lue comme telle.
    """
    import datetime

    try:
        d = datetime.datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.timestamp()


def _horodatage(label: str):
    """L'instant local que porte le nom d'un répertoire de déploiement."""
    import time

    try:
        return time.mktime(time.strptime(label, "%Y%m%d-%H%M%S"))
    except (ValueError, OverflowError):
        return None


def lire_runs(racine: str = RUNS) -> list:
    """Les déploiements passés qui ont installé quelque chose.

    Rend [{"label", "debut", "hors_ligne", "vms": [{"nom", "ip", "fin",
    "code"}]}].

    « hors_ligne » est le « offline » du manifeste : True ou False quand il
    le porte, None sinon — un manifeste qui ne le porte pas ne dit pas si
    son déploiement a tourné coupé.

    « debut » est le « deploy_started » du manifeste quand il le porte :
    l'instant où le déploiement commence, AVANT la création des VM. Le
    premier démarrage d'une VM coupée — pose de l'agent invité, paquets de
    cloud-init — passe par le cache avant le lancement des installations, et
    ses manques tomberaient hors d'une fenêtre ouverte au lancement. À
    défaut, « debut » est le plus tôt de l'horodatage du répertoire et du
    « started », tous deux écrits au lancement des installations.

    « fin » est la dernière écriture du log de la VM, c'est-à-dire son
    marqueur de sortie ; « code » est ce marqueur, None quand il manque. Un
    déploiement sans branche ne fait que démarrer ses VM, n'installe rien,
    et n'est pas rendu.
    """
    import glob
    import json
    import os

    from script.todo.qemu_install_monitor import read_status

    out = []
    motif = os.path.join(os.path.expanduser(racine), "*", "session.json")
    for manifeste in glob.glob(motif):
        try:
            with open(manifeste, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get("branch"):
            continue
        label = os.path.basename(os.path.dirname(manifeste))
        debut = data.get("deploy_started")
        if not isinstance(debut, (int, float)) or isinstance(debut, bool):
            debuts = [
                d
                for d in (data.get("started"), _horodatage(label))
                if isinstance(d, (int, float))
            ]
            if not debuts:
                continue
            debut = min(debuts)
        vms = []
        for vm in data.get("vms") or ():
            if not isinstance(vm, dict):
                continue
            log = vm.get("log") or ""
            try:
                fin = os.path.getmtime(log)
            except (OSError, TypeError):
                continue
            vms.append(
                {
                    "nom": vm.get("name") or "",
                    "ip": vm.get("ip") or "",
                    "fin": fin,
                    "code": read_status(log)[1],
                }
            )
        hors_ligne = data.get("offline")
        out.append(
            {
                "label": label,
                "debut": debut,
                "hors_ligne": (
                    hors_ligne if isinstance(hors_ligne, bool) else None
                ),
                "vms": vms,
            }
        )
    return out


def _lignes(chemin: str, indices) -> list:
    """Les lignes du journal, décodées, dont le TEXTE contient un des indices.

    Le filtre sur le texte précède le décodage : le journal n'est pas tourné,
    il compte des dizaines de milliers de lignes, et seule une poignée
    concerne la question posée. Un journal illisible rend une liste vide.
    """
    import json

    if not chemin or not indices:
        return []
    out = []
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                if not any(i in ligne for i in indices):
                    continue
                try:
                    d = json.loads(ligne)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        return []
    return out


def releve_amont_muet(chemin: str, clients) -> list:
    """Les lignes servies amont muet à ces clients.

    Rend [{"client", "t", "issue", "methode", "url"}], « t » en secondes.
    """
    out = []
    for d in _lignes(chemin, [f'"{i}"' for i in ISSUES_AMONT_MUET]):
        if d.get("outcome") not in ISSUES_AMONT_MUET:
            continue
        if d.get("client") not in clients:
            continue
        quand = instant(d.get("time"))
        if quand is None:
            continue
        out.append(
            {
                "client": d["client"],
                "t": quand,
                "issue": d["outcome"],
                "methode": d.get("method") or "",
                "url": d.get("url") or "",
            }
        )
    return out


def bilan_du_nom(
    runs,
    nom: str,
    releve,
    maintenant: float,
    retenus: int = RUNS_RETENUS,
    age_max: float = AGE_MAX,
):
    """Ce que les derniers déploiements hors ligne de la VM « nom » ont manqué.

    Le NOM est la clé : il porte le système, sa version et la saveur du
    bureau, là où le manifeste peut laisser système et version vides. Une
    ligne du relevé appartient à un déploiement quand son client est l'adresse
    de sa VM et que son instant tombe dans la fenêtre de celle-ci : une
    adresse IP se réattribue, et seule la fenêtre dit à qui elle était.

    Les déploiements sont lus du plus récent au plus ancien :
      · un déploiement qui a RÉUSSI coupé (manifeste « offline » vrai, code
        0, des lignes d'amont muet) clôt la lecture des PLUS ANCIENS — ce
        qui leur manquait a été rempli depuis, ou n'est plus demandé. Ses
        PROPRES manques sont gardés : les blocs d'outils facultatifs
        préviennent et rendent 0, et une installation qui en a manqué
        plusieurs réussit quand même ;
      · une réussite qu'on ne sait pas coupée ne clôt rien, le manifeste
        l'ignorât-il seulement : les lignes d'amont muet naissent aussi en
        ligne, et clore à tort ferait taire des manques réels. Ne pas clore
        coûte peu — la lecture reste bornée par « retenus » et « age_max »,
        et ce que le magasin détient depuis est ôté plus loin ;
      · un déploiement sans manque ne renseigne pas : arrêté avant d'avoir
        rien demandé, sur un verrou apt par exemple, ou mené en ligne ;
      · les autres sont RÉUNIS, jusqu'à « retenus ». Prendre le seul dernier
        rendrait muet l'avertissement dès qu'un déploiement s'arrête tôt.

    Rend None quand aucun déploiement ne renseigne. Sinon {"nom", "age",
    "runs", "manques"} : « age » est celui du plus récent retenu, « manques »
    associe chaque (méthode, URL) au dernier instant où elle a manqué, le
    déploiement le plus récent d'abord.
    """
    candidats = sorted(
        (
            (run, vm)
            for run in runs
            for vm in run["vms"]
            if vm["nom"] == nom and vm["ip"]
        ),
        key=lambda rv: rv[1]["fin"],
        reverse=True,
    )
    pris = []
    for run, vm in candidats:
        if maintenant - vm["fin"] > age_max:
            break
        dedans = [
            ligne
            for ligne in releve
            if ligne["client"] == vm["ip"]
            and run["debut"] <= ligne["t"] <= vm["fin"]
        ]
        manques = [l for l in dedans if l["issue"] == ISSUE_MANQUE]
        if dedans and vm["code"] == 0 and run.get("hors_ligne") is True:
            if manques:
                pris.append((run, vm, manques))
            break
        if not manques:
            continue
        pris.append((run, vm, manques))
        if len(pris) >= retenus:
            break
    if not pris:
        return None
    manques = {}
    for _run, _vm, lignes in pris:
        for ligne in sorted(lignes, key=lambda l: l["t"]):
            cle = (ligne["methode"], ligne["url"])
            manques[cle] = max(manques.get(cle, 0.0), ligne["t"])
    return {
        "nom": nom,
        "age": maintenant - pris[0][1]["fin"],
        "runs": [run["label"] for run, _vm, _l in pris],
        "manques": manques,
    }


def tenus_selon_journal(chemin: str, manques) -> set:
    """Les (méthode, URL) dont le journal dit la réponse gardée APRÈS le manque.

    « manques » associe chaque (méthode, URL) à l'instant de son dernier
    manque. Le journal dit « a été gardé », pas « est encore là » : une purge
    efface l'objet et laisse ses lignes. Seule une ligne postérieure au manque
    compte — l'objet est entré, ou a été servi, après — ce qui écarte l'objet
    purgé avant le manque. Une purge postérieure reste invisible, d'où
    l'étiquette « selon le journal » partout où ce verdict est montré.
    """
    from urllib.parse import urlsplit

    hotes = set()
    for _methode, url in manques:
        try:
            hote = urlsplit(url).hostname
        except ValueError:
            hote = None
        if hote:
            hotes.add(f"//{hote}")
    tenus = set()
    for d in _lignes(chemin, sorted(hotes)):
        cle = (d.get("method") or "", d.get("url") or "")
        if cle not in manques or d.get("outcome") not in ISSUES_REPONSE_GARDEE:
            continue
        quand = instant(d.get("time"))
        if quand is not None and quand > manques[cle]:
            tenus.add(cle)
    return tenus


def detient_rendu(sortie: str) -> dict:
    """La sortie de « --detient », par (méthode, URL).

    Une ligne par question, six champs séparés par des tabulations :
    verdict, statut, date de garde (RFC 3339 ou « - »), classe, méthode, URL.
    Une ligne mal formée est sautée plutôt que devinée.
    """
    out = {}
    for ligne in (sortie or "").splitlines():
        champs = ligne.split("\t", 5)
        if len(champs) < 6:
            continue
        verdict, statut, garde_le, classe, methode, url = champs
        out[(methode, url)] = {
            "verdict": verdict,
            "statut": statut,
            "garde_le": garde_le,
            "classe": classe,
        }
    return out


def detient_interroger(paires, binaire: str = BINAIRE, cache_dir: str = ""):
    """Ce que le MAGASIN détient maintenant, par (méthode, URL).

    Le magasin et non le journal : un objet effacé après son entrée garde ses
    lignes « stored ». Rend None quand le binaire manque, ne connaît pas
    « --detient » — il se sonde dans son aide — ou échoue : l'appelant se
    rabat alors sur le journal, et le DIT. La question ne demande aucun
    privilège, les casiers étant lisibles par tous.
    """
    import os
    import subprocess

    paires = list(paires)
    if not paires:
        return {}
    if not os.path.isfile(binaire):
        return None
    try:
        aide = subprocess.run(
            [binaire, "--help"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if "-detient" not in (aide.stdout or "") + (aide.stderr or ""):
        return None
    argv = [binaire]
    cache_dir = cache_dir or reglage("EL_CACHE_DIR")
    if cache_dir:
        argv += ["--cache-dir", cache_dir]
    argv.append("--detient")
    try:
        p = subprocess.run(
            argv,
            input="".join(f"{m} {u}\n" for m, u in paires),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return detient_rendu(p.stdout)


def depot_git(url: str) -> str:
    """L'adresse du dépôt dont `url` est une négociation git, ou "".

    Le suffixe de négociation est retiré du chemin, et la requête avec lui :
    « …/d.git/info/refs?service=git-upload-pack » et « …/d.git/git-upload-pack »
    rendent le même dépôt, compté une fois. Une adresse illisible rend "".
    """
    from urllib.parse import urlsplit, urlunsplit

    try:
        morceaux = urlsplit(url or "")
    except ValueError:
        return ""
    for suffixe in GIT_NEGOCIATION:
        if morceaux.path.endswith(suffixe):
            chemin = morceaux.path[: -len(suffixe)] or "/"
            return urlunsplit(
                (morceaux.scheme, morceaux.netloc, chemin, "", "")
            )
    return ""


def manques_hors_ligne(
    vms, racine: str = RUNS, chemin: str = "", maintenant=None, detient=None
) -> list:
    """Par VM de la spec, ce que ses derniers déploiements hors ligne ont
    manqué et que le cache ne détient toujours pas.

    Rend [{"nom", "age", "runs", "manquants", "git", "jamais",
    "selon_journal"}], une entrée par nom qui manque encore quelque chose de
    comblable. « manquants » ne porte que des méthodes gardables que le cache
    ne détient pas. « git » : les dépôts, sans doublon, dont une négociation
    a manqué — le miroir les remplit, pas un rejeu, et le magasin n'est pas
    interrogé à leur sujet. « jamais » : ce que le cache ne gardera jamais.
    Les deux derniers sont nommés à part, pour ne pas promettre un
    remplissage impossible, et ne font pas parler l'avertissement à eux
    seuls : ni le magasin ni le journal ne disent si un miroir a été rempli
    depuis.

    « detient » est la question posée au magasin (detient_interroger par
    défaut) ; None en retour fait lire le journal à la place, et
    « selon_journal » le dit.

    Muet — [] — sans déploiement qui renseigne, et alors sans même lire le
    journal ni lancer le binaire : un avertissement qui parle sans savoir
    apprend à passer outre.
    """
    import time

    noms = []
    for vm in vms or ():
        nom = vm.get("name") or ""
        if nom and nom not in noms:
            noms.append(nom)
    if not noms:
        return []
    runs = lire_runs(racine)
    clients = {
        vm["ip"]
        for run in runs
        for vm in run["vms"]
        if vm["nom"] in noms and vm["ip"]
    }
    if not clients:
        return []
    chemin = chemin or journal()
    releve = releve_amont_muet(chemin, clients)
    maintenant = time.time() if maintenant is None else maintenant
    bilans = [
        b
        for b in (bilan_du_nom(runs, n, releve, maintenant) for n in noms)
        if b
    ]
    if not bilans:
        return []

    derniers = {}
    for b in bilans:
        for cle, quand in b["manques"].items():
            if _gardable(cle) and not depot_git(cle[1]):
                derniers[cle] = max(derniers.get(cle, 0.0), quand)
    verdicts = (detient or detient_interroger)(sorted(derniers))
    selon_journal = verdicts is None
    if selon_journal:
        tenus, jamais_gardes = tenus_selon_journal(chemin, derniers), set()
    else:
        tenus = {c for c, v in verdicts.items() if v["verdict"] in DETENTION}
        jamais_gardes = {
            c for c, v in verdicts.items() if v["verdict"] == "non-cachable"
        }
    out = []
    for b in bilans:
        git, jamais, manquants = _trier_manques(
            b["manques"], jamais_gardes, tenus
        )
        if manquants:
            out.append(
                {
                    "nom": b["nom"],
                    "age": b["age"],
                    "runs": b["runs"],
                    "manquants": manquants,
                    "git": git,
                    "jamais": jamais,
                    "selon_journal": selon_journal,
                }
            )
    return out


def _gardable(cle) -> bool:
    """La méthode d'un (méthode, URL) est-elle de celles que le cache
    garde ?"""
    return cle[0].upper() in METHODES_GARDABLES


def _trier_manques(manques, jamais_gardes, tenus):
    """Répartit des (méthode, URL) manqués en (git, jamais, manquants).

    « git » : les dépôts, triés et sans doublon, dont une négociation a
    manqué. « jamais » : les méthodes que le cache ne garde pas, et ce que
    le magasin dit non-cachable. « manquants » : le reste, moins `tenus`.
    La négociation git est reconnue AVANT la méthode : un POST sur
    « git-upload-pack » se remplit par le miroir, comme le GET qui le
    précède.
    """
    git, jamais, manquants = set(), [], []
    for cle in manques:
        depot = depot_git(cle[1])
        if depot:
            git.add(depot)
        elif not _gardable(cle) or cle in jamais_gardes:
            jamais.append(cle)
        elif cle not in tenus:
            manquants.append(cle)
    return sorted(git), jamais, manquants


def manques_recents(chemin: str, sous_reseau: str = "", depuis: float = 0.0):
    """Ce que les invités n'ont pas obtenu hors ligne depuis « depuis ».

    Rend [{"methode", "url", "dernier", "n", "clients"}], une entrée par
    (méthode, URL), le manque le plus récent d'abord. Ne comptent que les
    clients du sous-réseau des VM quand il est connu, et jamais la boucle
    locale : un rejeu depuis l'hôte écrit ses propres lignes, et les
    recompter ferait rejouer sans fin ce qui vient de l'être.
    """
    import ipaddress

    reseau = None
    if sous_reseau:
        try:
            reseau = ipaddress.ip_network(sous_reseau, strict=False)
        except ValueError:
            reseau = None
    par = {}
    for d in _lignes(chemin, [f'"{ISSUE_MANQUE}"']):
        if d.get("outcome") != ISSUE_MANQUE:
            continue
        client = d.get("client") or ""
        try:
            adresse = ipaddress.ip_address(client)
        except ValueError:
            continue
        if adresse.is_loopback or (
            reseau is not None and adresse not in reseau
        ):
            continue
        quand = instant(d.get("time"))
        if quand is None or quand < depuis:
            continue
        cle = (d.get("method") or "", d.get("url") or "")
        entree = par.setdefault(
            cle,
            {
                "methode": cle[0],
                "url": cle[1],
                "dernier": quand,
                "n": 0,
                "clients": set(),
            },
        )
        entree["n"] += 1
        entree["dernier"] = max(entree["dernier"], quand)
        entree["clients"].add(client)
    return sorted(par.values(), key=lambda e: -e["dernier"])
