#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Quels couples (hôte, port) méritent une reconnaissance, et la frappe.

Ce module n'identifie rien : il rend des cibles et dit lesquelles ont accepté
une connexion. Qui répond derrière un port ouvert est la question de
`fingerprint`, et le partage est ce qui rend le balayage vérifiable sans
serveur — un connecteur injecté suffit à parcourir un /24 entier sans émettre
un paquet.

Quatre sources répondent à « où chercher ». Deux sont locales à ce module —
les réseaux que la machine porte, et la table de voisinage. Deux sont
INJECTÉES : l'énumération des VM libvirt et la résolution d'un alias SSH
existent déjà comme méthodes de la classe TODO, et ce paquet n'a pas le droit
d'importer `todo.py`. Elles arrivent donc en arguments nommés, et leur
absence rend une LISTE VIDE plutôt qu'une erreur : une source qu'on n'a pas
branchée est une source qui n'a rien à dire, pas une panne du menu.

**Le noyau est interrogé, jamais deviné.** Le préfixe d'un réseau se lit dans
`ip`, qui le connaît, et non dans une adresse, d'où il ne se déduit pas. Un
/24 tiré d'une adresse nue est une HYPOTHÈSE, et s'annonce comme telle. Ce
module ne rétrécit donc jamais un préfixe plus large pour le rendre
balayable : il le rend tel que le noyau l'annonce, et `plan_sweep` refuse
tout ce qui dépasse un /24. Rétrécir en silence présenterait une hypothèse
comme une lecture.

Une machine porte volontiers DEUX /24 — un sur son interface physique, un
sur un pont de virtualisation où elle est elle-même la passerelle. « Le /24
local » n'a donc pas de sens : `local_networks` les rend TOUS, chacun marqué
`is_bridge`, et le choix appartient au menu.

Le dimensionnement de la piscine se fait par NOMBRE DE VAGUES et jamais par
nombre de cœurs : une sonde de connexion est de l'attente réseau, et un
compte de cœurs à deux chiffres multiplierait par quinze la durée d'un /24.
Le prédicteur qui colle est `plafond(hôtes × ports / ouvriers) × délai` :
254 hôtes × 4 ports au pire cas, tout en délai d'attente, tiennent en 1,5 s
à 256 ouvriers et 0,30 s de délai, contre 2,9 s à 128.

D'où l'ordre des passes : une passe de CONNEXION SEULE sur tout le réseau
d'abord, puis le budget coûteux des GET de reconnaissance dépensé sur la
poignée d'hôtes qui ont accepté. `sweep` fait la première, et rien d'autre.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as PoolTimeout
from dataclasses import dataclass

from script.todo.assistant import fingerprint

# Ce qu'un /24 porte d'hôtes utilisables, et donc le plafond d'un balayage.
# Plus large est refusé : le temps croît linéairement, et une plage que
# personne n'a désignée décrit des machines que personne n'a désignées.
MAX_HOSTS = 254

# Le nombre d'ouvriers en vol. Dimensionné par VAGUES, jamais par cœurs :
# ces fils attendent le réseau, ils ne calculent pas, et le nombre de cœurs
# n'a aucun rapport avec le nombre de connexions qu'une machine peut tenir en
# attente. `sweep` plafonne à `min(len(jobs), workers)`, donc une valeur plus
# grande que le nombre de sondes ne change RIEN : un /24 sur onze ports en
# compte 2 794, et 4 096, 8 192 ou 16 384 ouvriers y donnent tous une vague et
# la même durée.
#
# La durée suit `plafond(sondes / ouvriers) × délai`. Le compromis retenu à
# 1 024 laisse trois vagues sur un /24 plutôt qu'une : le gain de la vague
# unique se compte en centièmes de seconde, et trois salves d'un tiers de
# taille pèsent moins sur un commutateur qu'une seule salve entière — donc
# moins de paquets perdus, et un paquet perdu se lit comme un port fermé.
MAX_WORKERS = 1024

# Le délai d'une connexion. Il NE se déduit PAS de la latence observée au
# repos : un hôte joignable en une milliseconde à vide se manque à 0,05 s de
# délai dès que mille connexions partent ensemble, parce que la file, la
# passerelle et le noyau ajoutent tous leur part sous charge. La marge sert
# donc à ça, et non à la distance.
#
# Il couvre aussi la résolution ARP d'un voisin absent du cache, qui est ce
# qui coûte devant une adresse morte. Le raccourcir est le seul réglage de ce
# module qui fabrique des FAUX NÉGATIFS, et un réseau annoncé vide sur un
# délai trop court est plus coûteux que les secondes épargnées.
CONNECT_TIMEOUT = 0.30

# L'intervalle du battement de cœur. Paramétrable, et c'est le point : un
# intervalle figé rend la branche du battement intestable, donc non testée.
HEARTBEAT_SEC = 2.0

# Le délai d'un aller-retour SSH pour lire les réseaux d'un hôte. Il
# borne l'attente d'un hôte éteint : sans lui, un menu tiendrait le
# temps que la pile TCP renonce d'elle-même.
SSH_TIMEOUT = 15

# Le port qu'annonce `ssh -G` quand aucun n'est déclaré, et donc la seule
# valeur de repli qui ne soit pas une invention.
SSH_PORT = 22

# Le délai d'un appel à `ip`. La commande lit des tables du noyau et rend la
# main tout de suite ; le délai n'existe que pour ne jamais tenir le menu.
IP_TIMEOUT = 10

# Une ligne de « ip -o -4 addr show » : le rang, l'interface, puis le
# préfixe. C'est le préfixe qui compte, et c'est lui que la forme sans « -o »
# rend inattachable à son interface, l'une étant sur la ligne d'en-tête et
# l'autre sur la suivante.
ADDR_LINE = re.compile(r"^\s*\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+/\d+)")

# Le nom d'interface d'une ligne de « ip link show ». L'arobase d'une
# interface appairée sépare le nom de son pair : le nom s'arrête avant.
LINK_NAME = re.compile(r"^\s*\d+:\s+([^:@\s]+)")

# Le jeton que « ip -d link » pose sur un pont, et lui seul. La frontière de
# mot est ce qui distingue le type « bridge » des attributs « bridge_id » et
# « bridge_slave », qui paraissent sur la même ligne ou sur celle d'un port.
BRIDGE_KIND = re.compile(r"\bbridge\b")

# L'interface que la table de routage a élue pour sortir de la machine. Elle
# ne choisit pas le réseau à balayer — elle ouvre la liste, parce que la
# question « lequel est le mien » a déjà été tranchée par le noyau.
ROUTE_DEV = re.compile(r"\bdev\s+(\S+)")

# Un alias de configuration SSH qui ne désigne pas une machine : un joker est
# une règle, et un motif nié retire un nom au lieu d'en déclarer un.
SSH_PATTERN_CHARS = ("*", "?")
SSH_NEGATION = "!"


@dataclass(frozen=True)
class Interface:
    """Un réseau que la machine porte, tel que le noyau l'annonce.

    `cidr` est la forme réseau du préfixe LU sur l'interface, jamais un
    préfixe supposé autour d'une adresse. `is_bridge` dit que l'interface est
    un pont de virtualisation, donc que la machine y est probablement la
    passerelle et que ce qui s'y trouve est à elle : l'affichage le signale,
    et le choix reste à l'utilisateur.
    """

    name: str
    cidr: str
    is_bridge: bool


def _c_env():
    """L'environnement d'un sous-processus, forcé en anglais.

    `ip` et `virsh` traduisent leurs champs quand la locale le demande, et
    une comparaison de jeton échoue alors sans rien lever. La même fonction
    existe comme méthode statique de la classe TODO ; ce paquet n'importe pas
    `todo.py`, d'où cette copie de trois lignes.
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    return env


def run_ip(args, *, run=None) -> str:
    """La sortie de « ip <args> », ou la chaîne vide. Le transport, et rien
    d'autre.

    `run(argv)` rend le texte de la sortie standard et vaut `None` par
    défaut, résolu ici sur un sous-processus en locale C. Cette couture est
    ce qui permet à un test de décider ce que la machine annonce, et elle
    sert aussi à l'appelant qui veut la table de voisinage brute pour
    `neigh_hosts`.

    Ne lève pas : une commande absente, un délai dépassé ou un code de retour
    non nul rendent la chaîne vide, que chaque analyse lit comme « rien à
    dire ».
    """
    if run is None:
        run = _run_ip
    try:
        return run(["ip"] + list(args)) or ""
    except Exception:
        # Un `run` injecté lève ce qu'il veut, et celui du système lève sur
        # une commande absente : les deux disent qu'il n'y a rien à analyser.
        return ""


def _run_ip(argv):
    """La sortie standard de `argv`, en locale C, ou la chaîne vide."""
    answer = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=IP_TIMEOUT,
        env=_c_env(),
    )
    return answer.stdout if answer.returncode == 0 else ""


def local_networks(*, run=None) -> list[Interface]:
    """Les réseaux IPv4 que la machine porte, dans l'ordre à proposer.

    L'interface élue par la route par défaut ouvre la liste : le noyau a déjà
    tranché laquelle sort de la machine, et le demander vaut mieux que
    l'ordre des rangs. Le reste suit dans l'ordre où `ip` les annonce.

    La boucle locale est écartée — elle se sonde sans balayage, en quelques
    millisecondes — et chaque réseau ne paraît qu'une fois, là où une lecture
    des adresses ET des routes rend le même préfixe deux fois.

    Le préfixe est celui que porte l'interface, sans retouche. Un réseau plus
    large qu'un /24 est rendu TEL QUEL, et c'est `plan_sweep` qui le refuse :
    le rétrécir ici présenterait un /24 supposé comme un /24 lu. Ni
    `route_to` ni `interface_addresses` de `script/vpn/drivers/base.py` ne
    servent ici — le premier ne prend aucun exécuteur injecté, donc un test
    parlerait à la vraie machine, et le second jette la longueur du préfixe,
    qui est justement ce qu'on vient chercher. `host_networks` de
    `script/qemu/deploy_qemu.py` la garde, mais perd le NOM de l'interface,
    que l'affichage et le marquage des ponts exigent.
    """
    addresses = run_ip(["-o", "-4", "addr", "show"], run=run)
    bridges = _bridge_names(run_ip(["-d", "-o", "link", "show"], run=run))
    first = _default_dev(
        run_ip(["-o", "-4", "route", "show", "default"], run=run)
    )
    found: list[Interface] = []
    seen: set[tuple[str, str]] = set()
    for line in addresses.splitlines():
        parsed = ADDR_LINE.match(line)
        if not parsed:
            continue
        name, address = parsed.group(1), parsed.group(2)
        network = _network(address)
        if network is None or network.is_loopback:
            continue
        key = (name, str(network))
        if key in seen:
            continue
        seen.add(key)
        found.append(Interface(name, str(network), name in bridges))
    found.sort(key=lambda item: 0 if item.name == first else 1)
    return found


def ssh_runner(alias, *, timeout=SSH_TIMEOUT):
    """Un exécuteur qui lance `ip` SUR `alias`, pour `local_networks`.

    `local_networks` reçoit son exécuteur en argument, donc lui en passer un
    qui traverse SSH suffit à énumérer les réseaux d'une AUTRE machine : la
    lecture des adresses, la détection des ponts et l'ordre par route par
    défaut se réutilisent tels quels, sans une ligne d'analyse en double.

    `BatchMode=yes` refuse toute invite : un hôte qui demanderait un mot de
    passe rend une chaîne vide plutôt que de bloquer le menu sur une question
    que personne ne voit venir.

    Les arguments sont cités un par un : la commande distante est une chaîne
    interprétée par un interpréteur là-bas, et un argument non cité s'y
    ferait relire.
    """

    def executer(argv):
        distant = " ".join(shlex.quote(morceau) for morceau in argv)
        answer = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={int(timeout)}",
                alias,
                distant,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_c_env(),
        )
        return answer.stdout if answer.returncode == 0 else ""

    return executer


def remote_networks(alias, *, run=None) -> list[Interface]:
    """Les réseaux IPv4 que porte `alias`, lus chez lui.

    Sert le cas que `local_networks` ne peut pas voir : quand le CLI tourne
    dans une machine virtuelle, les réseaux qu'il porte sont ceux de
    l'hyperviseur, et le parc réel est hors-lien. La machine du dessus, elle,
    porte les bons préfixes et sait les dire.

    Les réseaux sont LUS là-bas et balayés D'ICI : c'est la table de routage
    locale qui décide si l'on y accède, et une route par défaut suffit
    d'ordinaire. Rien n'est balayé depuis l'hôte distant, qui n'a donc besoin
    que d'un accès en lecture.

    Rend une liste vide quand l'hôte est injoignable, refuse une clé ou n'a
    pas `ip` : aucun de ces cas n'est une panne du menu.
    """
    return local_networks(run=run or ssh_runner(alias))


def qemu_hosts(
    *, list_domains=None, vm_ip=None
) -> list[tuple[str, str | None]]:
    """Les VM libvirt de la machine : (nom, adresse ou None).

    `list_domains()` rend les noms de domaine et `vm_ip(nom)` l'adresse d'un
    seul. Les deux sont INJECTÉS parce qu'ils existent comme méthodes de la
    classe TODO, que ce paquet n'importe pas. Sans `list_domains`, il n'y a
    rien à énumérer et la source rend une liste VIDE, sans erreur : le menu
    branche les deux, un test n'en branche aucun, et aucun des deux cas n'est
    une panne. Sans `vm_ip`, les domaines sortent avec une adresse inconnue.

    Le résolveur attendu est `_qemu_vm_ip_now`, qui lit le bail UNE FOIS et
    ne patiente pas. Les deux résolveurs patients du même fichier attendent
    jusqu'à dix minutes PAR VM : afficher une liste de trois VM éteintes
    gèlerait le menu une demi-heure, et une découverte ne doit jamais
    attendre une machine qui n'est pas allumée.

    Une VM sans adresse est LISTÉE avec `None`, jamais écartée : elle est
    définie, l'utilisateur peut vouloir la démarrer, et la faire disparaître
    de la liste ne le lui dirait pas.
    """
    if list_domains is None:
        return []
    try:
        names = list_domains() or []
    except Exception:
        # L'énumérateur injecté lève ce qu'il veut ; celui de la classe TODO
        # rend déjà [] sur un `virsh` absent. Les deux valent « aucune VM ».
        return []
    found: list[tuple[str, str | None]] = []
    for name in names:
        if not isinstance(name, str) or not name.strip():
            continue
        found.append((name, _vm_address(name, vm_ip)))
    return found


def ssh_hosts(
    *, list_aliases=None, resolve=None
) -> list[tuple[str, str, int]]:
    """Les machines de la configuration SSH : (alias, hôte, port).

    `list_aliases()` rend les noms déclarés et `resolve(alias)` la
    configuration résolue par `ssh -G`, en clés minuscules. Les deux sont
    INJECTÉS — ce sont des méthodes de la classe TODO, que ce paquet
    n'importe pas — et leur absence rend une liste VIDE sans erreur. Les deux
    sont exigées : sans résolveur, l'hôte et le port ne se sauraient pas, et
    les inventer serait une devinette là où `ssh -G` a la réponse.

    Le résolveur est celui qui délègue à `ssh` au lieu de relire le fichier,
    parce que lui seul connaît les `Include`, les `Match`, l'héritage des
    jokers et ses propres défauts, pour quelques millisecondes l'appel — d'où
    une résolution séquentielle de toute la configuration, qui ne mérite
    aucune parallélisation.

    Une entrée SANS `HostName` n'est jamais écartée : `ssh -G` remplit alors
    l'hôte avec l'ALIAS lui-même, et l'alias est une cible sondable que le
    DNS ou le fichier des hôtes résout très bien.

    Deux filtres tiennent de ce côté-ci. Un joker et un motif NIÉ sont des
    règles et non des machines ; l'énumérateur du dépôt écarte le premier et
    laisse passer le second, donc les deux sont refusés ici. Et aucun lecteur
    de fichier du dépôt ne suit `Include` : un alias déclaré dans un fichier
    inclus reste invisible à l'énumération, alors même que `ssh -G` le
    résoudrait — la source est donc incomplète sans être fausse.
    """
    if list_aliases is None or resolve is None:
        return []
    try:
        aliases = list_aliases() or []
    except Exception:
        # Un fichier absent rend déjà [] chez l'énumérateur du dépôt ; un
        # énumérateur injecté lève ce qu'il veut, et c'est la même chose.
        return []
    found: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for alias in aliases:
        if not _is_machine(alias) or alias in seen:
            continue
        seen.add(alias)
        config = _ssh_config(alias, resolve)
        host = _text(config.get("hostname")) or alias
        found.append((alias, host, _ssh_port(config.get("port"))))
    return found


def neigh_hosts(text: str) -> list[str]:
    """Les adresses qui ont PARLÉ, lues dans « ip neigh ». Fonction PURE.

    Une entrée du voisinage ne porte une adresse matérielle que si la machine
    a répondu ; une entrée `FAILED` ou `INCOMPLETE` n'en porte pas, et dit
    précisément qu'on a demandé sans obtenir. Exiger l'adresse matérielle est
    donc ce qui sépare « a parlé » de « a été sollicitée ».

    C'est le préfiltre par défaut d'un réseau trop large pour s'énumérer : il
    ne coûte rien, ne demande aucun droit, et ne touche que des machines déjà
    entrées dans le cache du noyau. Il est incomplet par nature — une machine
    silencieuse en est absente — donc il précède un balayage, il ne le
    remplace pas.

    Rend les adresses dans l'ordre de lecture, sans doublon.
    """
    found: list[str] = []
    for line in (text or "").splitlines():
        words = line.split()
        if len(words) < 2 or "lladdr" not in words:
            continue
        address = _address(words[0])
        if address is None or address in found:
            continue
        found.append(address)
    return found


def plan_sweep(cidr: str, ports=None, *, skip=()) -> list[tuple[str, int]]:
    """Les couples (adresse, port) à frapper sur `cidr`. Fonction PURE.

    `ports` vaut les onze ports de `fingerprint` en son absence. `skip`
    retire des adresses, et sert d'abord aux adresses de la machine
    elle-même : sans ce retrait, un balayage se reconnaît lui-même et la
    passerelle d'un pont est offerte comme un serveur découvert.

    Rend une liste VIDE, sans lever, dans les trois cas où il n'y a rien à
    planifier : un CIDR illisible, un réseau plus large qu'un /24, et un
    ensemble de ports vide. Le refus du plus large qu'un /24 est vérifié
    AVANT toute énumération, parce qu'énumérer un /8 pour découvrir qu'il est
    trop grand coûterait seize millions d'adresses en mémoire.

    Un /24 tiré d'une adresse nue est une HYPOTHÈSE et se dit comme telle à
    l'utilisateur : le préfixe réel ne se déduit pas d'une adresse, et ce
    module ne le devine jamais à sa place.

    L'ordre est par hôte, tous ses ports ensemble : c'est celui que
    l'affichage compte (« k/254 hôtes ») et celui qui groupe les résultats
    d'une même machine.
    """
    network = _network(cidr)
    if network is None:
        return []
    if _usable_count(network) > MAX_HOSTS:
        return []
    wanted = tuple(fingerprint.PORTS if ports is None else ports)
    if not wanted:
        return []
    excluded = {_address(one) or str(one) for one in skip or ()}
    return [
        (str(host), port)
        for host in network.hosts()
        if str(host) not in excluded
        for port in wanted
    ]


def sweep(
    jobs,
    *,
    connect=None,
    workers=MAX_WORKERS,
    timeout=CONNECT_TIMEOUT,
    heartbeat_sec=HEARTBEAT_SEC,
    now=None,
    on_event=None,
) -> list[tuple[str, int]]:
    """Frappe les couples de `jobs` et rend ceux qui ont accepté.

    `connect(hôte, port, délai)` rend un booléen et vaut `None` par défaut,
    résolu sur une connexion TCP nue. La sonde est une connexion et RIEN
    d'autre : un `ping` en sous-processus coûterait un `fork+exec` par
    adresse, soit un millier pour un /24, là où une socket n'en coûte aucun.

    La piscine est dimensionnée par le nombre de vagues,
    `min(len(jobs), workers)`, et jamais par le nombre de cœurs : ces fils
    attendent le réseau, ils ne calculent pas.

    `on_event` reçoit de petits tuples, et c'est par lui que le menu imprime
    sans que ce module connaisse l'affichage : `("hit", hôte, port)` dès
    qu'un port accepte, `("heartbeat", faits, total, secondes)` quand un
    intervalle passe sans qu'une réponse arrive, `("done", trouvés, total,
    secondes)` à la fin. Les trouvailles sont AUSSI rendues, dans l'ordre où
    les événements les ont annoncées, pour qu'un appelant — un test le
    premier — puisse affirmer sur des données plutôt que sur du texte capté.

    `now()` rend un compteur de secondes et vaut `None` par défaut, résolu
    sur l'horloge monotone. Injecté, il rend les durées des événements
    prévisibles.

    Un hôte qui met le délai entier à répondre n'arrête pas les autres, et un
    connecteur qui lève sur une adresse compte pour un port fermé : l'échec
    d'une cible ne fait pas perdre le balayage.
    """
    jobs = list(jobs or ())
    clock = time.monotonic if now is None else now
    started = clock()
    if not jobs:
        _emit(on_event, ("done", 0, 0, clock() - started))
        return []
    if connect is None:
        connect = _connect
    size = min(len(jobs), workers) or 1
    hits: list[tuple[str, int]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=size) as pool:
        futures = {
            pool.submit(connect, host, port, timeout): (host, port)
            for host, port in jobs
        }
        pending = set(futures)
        while pending:
            try:
                for future in as_completed(
                    list(pending), timeout=heartbeat_sec
                ):
                    pending.discard(future)
                    done += 1
                    host, port = futures[future]
                    if _accepted(future):
                        hits.append((host, port))
                        _emit(on_event, ("hit", host, port))
            except PoolTimeout:
                # Le battement : l'intervalle est passé sans qu'une réponse
                # arrive. Il dit que le balayage avance, là où un silence
                # prolongé se lit comme un blocage.
                _emit(
                    on_event,
                    ("heartbeat", done, len(jobs), clock() - started),
                )
    _emit(on_event, ("done", len(hits), len(jobs), clock() - started))
    return hits


def _emit(on_event, event):
    """Passe un événement à l'appelant, s'il en veut."""
    if on_event is not None:
        on_event(event)


def _accepted(future):
    """Le port a-t-il accepté ? Une levée compte pour un port fermé."""
    try:
        return bool(future.result())
    except Exception:
        # Un connecteur peut lever sur une adresse mal formée ou une pile
        # réseau à bout de descripteurs : c'est un port qui n'a pas répondu,
        # et le balayage continue sur les autres.
        return False


def _connect(host: str, port: int, timeout: float) -> bool:
    """Vrai si `port` accepte une connexion sur `host`.

    Une connexion et rien d'autre : aucun octet n'est envoyé, aucun verbe
    n'est prononcé, donc la passe ne peut ni charger un modèle ni dépenser un
    jeton. Le port ouvert coûte une fraction de milliseconde ; le délai
    n'existe que pour borner un écouteur qui accepte sans répondre.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _bridge_names(text) -> set[str]:
    """Les interfaces qui sont des ponts, d'après « ip -d link show »."""
    names = set()
    for line in (text or "").splitlines():
        parsed = LINK_NAME.match(line)
        if parsed and BRIDGE_KIND.search(line):
            names.add(parsed.group(1))
    return names


def _default_dev(text) -> str:
    """L'interface de la route par défaut, ou la chaîne vide."""
    parsed = ROUTE_DEV.search(text or "")
    return parsed.group(1) if parsed else ""


def _network(cidr):
    """Le réseau d'un CIDR, ou None quand la valeur n'en est pas un.

    Accepte l'adresse d'un hôte avec son préfixe — c'est la forme que `ip`
    rend — et la ramène à son réseau, ce qui est l'ensemble à balayer.
    """
    if not isinstance(cidr, str) or not cidr.strip():
        return None
    try:
        return ipaddress.ip_network(cidr.strip(), strict=False)
    except ValueError:
        return None


def _usable_count(network) -> int:
    """Le nombre d'hôtes utilisables d'un réseau, sans l'énumérer.

    Compté et non énuméré : le plafond se vérifie devant un /8 comme devant
    un /24, et matérialiser le premier pour le mesurer coûterait seize
    millions d'adresses. Un réseau de deux adresses ou moins les compte
    toutes, comme le fait l'énumération elle-même — il n'y a alors ni adresse
    de réseau ni adresse de diffusion à retirer.
    """
    total = network.num_addresses
    return total - 2 if total > 2 else total


def _address(text):
    """L'adresse en forme canonique, ou None si le texte n'en est pas une."""
    if not isinstance(text, str):
        return None
    try:
        return str(ipaddress.ip_address(text.strip()))
    except ValueError:
        return None


def _vm_address(name, vm_ip):
    """L'adresse d'une VM, ou None quand elle n'en annonce aucune."""
    if vm_ip is None:
        return None
    try:
        return _text(vm_ip(name)) or None
    except Exception:
        # Une VM dont la résolution échoue reste listée : une seule source
        # abîmée ne fait pas disparaître les autres machines.
        return None


def _ssh_config(alias, resolve) -> dict:
    """La configuration résolue d'un alias, ou un dictionnaire vide."""
    try:
        config = resolve(alias)
    except Exception:
        # Le résolveur du dépôt rend déjà {} sur un `ssh` absent ou un code
        # de retour non nul ; un résolveur injecté lève ce qu'il veut.
        return {}
    return config if isinstance(config, dict) else {}


def _is_machine(alias) -> bool:
    """Cet alias désigne-t-il une machine, plutôt qu'une règle ?"""
    if not isinstance(alias, str) or not alias.strip():
        return False
    if alias.startswith(SSH_NEGATION):
        return False
    return not any(char in alias for char in SSH_PATTERN_CHARS)


def _ssh_port(value) -> int:
    """Le port d'une configuration résolue, sinon le défaut de `ssh`.

    `ssh -G` rend toujours un port, et le défaut n'est atteint que si la
    résolution a échoué entièrement : il vaut alors ce que `ssh` lui-même
    aurait annoncé, ce qui n'invente rien.
    """
    text = _text(value)
    if text.isdigit():
        port = int(text)
        if 1 <= port <= 65535:
            return port
    return SSH_PORT


def _text(value) -> str:
    """La valeur quand c'est une chaîne, sans ses espaces de bord ; sinon "".

    Une valeur d'un autre type est jetée plutôt que passée par `str()` : la
    représentation d'un dictionnaire entrerait dans un nom d'hôte et de là
    dans une cible de connexion.
    """
    return value.strip() if isinstance(value, str) else ""
