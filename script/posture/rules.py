#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le TEXTE des règles de sortie d'une posture. Rien n'est appliqué ici.

Rendre une chaîne et n'exécuter rien est ce qui permet de MONTRER les
règles avant de les poser, et de les éprouver sans machine ni privilège.
Ce module n'ouvre aucun fichier : l'écriture atomique existe ailleurs, avec
son mode et sa trace, et un rendu qui écrit les perdrait tous les deux.

L'ORDRE EST UNE PROPRIÉTÉ, PAS UN STYLE. Trois choses en dépendent :

1. La politique tombe sur la LIGNE QUI DÉCLARE la chaîne. Une règle « drop »
   posée en dernier laisserait tout sortir jusqu'à ce que cette ligne soit
   lue, et la fenêtre s'ouvre à chaque rechargement.
2. La chaîne forward est émise MÊME VIDE. Absente, le trafic des conteneurs
   retombe sur le défaut du noyau, qui accepte : les règles afficheraient
   complet pendant qu'un conteneur sort par la fenêtre.
3. Les connexions établies et la boucle locale passent AVANT les
   destinations. Après, la réponse au premier paquet autorisé serait
   elle-même jugée sur la liste, et une session ouverte se refermerait.

LE CHARGEMENT EST ATOMIQUE : le fichier se donne d'un bloc à l'analyseur,
qui applique tout ou rien. Il n'existe donc aucun instant où la moitié des
règles est en place — et c'est pour cela que le rendu produit un fichier
entier plutôt qu'une suite de commandes.

TOUT PASSE PAR LE TABLEAU DE SYMBOLES, y compris ce qui arrive déjà résolu.
Une destination se fabrique à la main aussi bien qu'elle se demande, et le
seul endroit qui ÉCRIT est le seul où le refus tient : un nom d'hôte, une
route qui couvre tout ou un port hors bornes sont refusés ici même quand
l'appelant a court-circuité la porte d'entrée.
"""

from __future__ import annotations

import ipaddress
import textwrap

from script.lib_valid import ValidationError
from script.posture import allowlist

# Le nom de la table. Le rendu la supprime et la recrée plutôt que de vider
# le jeu de règles entier : purger tout emporterait les tables des autres,
# et un conteneur perdrait son réseau au premier rechargement.
TABLE = "erplibre"

# Les chaînes rendues, avec leur accroche. `output` juge ce que la machine
# émet, `forward` ce qu'elle relaie — donc les conteneurs.
CHAINES = (("output", "output"), ("forward", "forward"))

# La famille d'adresses dicte le mot-clé, et les deux se rendent séparément.
MOT_FAMILLE = {4: "ip", 6: "ip6"}


def _refuse(message):
    raise ValidationError(message)


def _destinations_controlees(destinations):
    """Chaque destination repasse par la porte d'entrée, quoi qu'il arrive.

    Rend la liste re-validée, dans l'ordre reçu : c'est l'appelant qui
    décide de l'ordre des règles, et deux appels identiques doivent écrire
    le même fichier.
    """
    vues = []
    controlees = []
    for destination in destinations:
        symbole = getattr(destination, "symbol", None)
        if symbole in vues:
            _refuse(
                f"« {symbole} » est nommé deux fois. L'un des deux serait"
                " rendu sans que rien ne le dise."
            )
        vues.append(symbole)
        controlees.append(
            allowlist.resolve(
                symbole,
                list(getattr(destination, "networks", ())),
                getattr(destination, "ports", ()),
            )
        )
    return controlees


def _par_famille(networks):
    """{4: [...], 6: [...]}, chaque famille dans l'ordre reçu."""
    groupes = {}
    for texte in networks:
        version = ipaddress.ip_network(texte).version
        groupes.setdefault(version, []).append(texte)
    return groupes


def _commentaire(symbole, raison):
    """La raison repliée, pour qu'un terminal la lise sans la couper."""
    prefixe = "        # "
    return textwrap.wrap(
        f"{symbole} : {raison}",
        width=79,
        initial_indent=prefixe,
        subsequent_indent=prefixe,
    )


def _lignes_destination(destination):
    """Les règles d'UNE destination : une par famille et par protocole."""
    lignes = _commentaire(destination.symbol, destination.reason)
    ports = ", ".join(str(port) for port in destination.ports)
    groupes = _par_famille(destination.networks)
    for version in sorted(groupes):
        cibles = ", ".join(groupes[version])
        for protocole in destination.protocols:
            lignes.append(
                f"        {MOT_FAMILLE[version]} daddr {{ {cibles} }}"
                f" {protocole} dport {{ {ports} }} accept"
            )
    return lignes


def _lignes_ports(posture):
    """Les règles d'une posture qui borne ses PORTS et rien d'autre.

    Aucun `daddr` : c'est la différence, et elle se lit. Aucun mot de
    famille non plus — la table est `inet`, donc une ligne sans adresse
    vaut pour IPv4 et IPv6, là où une destination doit se séparer par
    famille puisque ses réseaux le sont.

    Les numéros repassent par la porte de `allowlist` : un port hors bornes
    est refusé au même endroit qu'un port de symbole, quel que soit le
    chemin qui l'a écrit.
    """
    lignes = []
    for protocole, ports in posture.egress_ports:
        if protocole not in allowlist.PROTOCOLS:
            _refuse(f"« {posture.name} » : protocole « {protocole} » inconnu.")
        propres = allowlist.checked_ports(posture.name, ports)
        liste = ", ".join(str(port) for port in propres)
        lignes.append(f"        {protocole} dport {{ {liste} }} accept")
    return lignes


def _lignes_chaine(nom, accroche, posture, destinations):
    lignes = [
        f"    chain {nom} {{",
        f"        type filter hook {accroche} priority 0; policy drop;",
        "        ct state established,related accept",
    ]
    if nom == "output":
        lignes.append('        oif "lo" accept')
    for destination in destinations:
        lignes.extend(_lignes_destination(destination))
    # DANS LES DEUX CHAÎNES, comme les destinations : ce que la machine
    # atteint, ce qu'elle relaie l'atteint aussi. Les réserver à `output`
    # priverait les conteneurs de tout réseau sans que rien ne le dise.
    if not destinations and posture is not None and posture.ports_bounded:
        lignes.extend(_lignes_ports(posture))
    lignes.append("    }")
    return lignes


def wants_rules(posture) -> bool:
    """Cette posture demande-t-elle un jeu de règles ?

    TROIS RAISONS D'EN VOULOIR, ET UNE SEULE ÉTAIT CONSULTÉE. Une liste
    bornée en donne une : il y a des adresses à nommer. Une sortie COUPÉE
    en donne une autre, et le rendu la sert depuis toujours — « policy
    drop », la boucle locale, les connexions déjà établies. Ne demander que
    la première laissait « local-only » se déployer avec la sortie ENTIÈRE :
    la posture qui promet le plus était la seule à ne rien poser, et rien ne
    le disait.

    Des PORTS bornés en donnent la troisième. Ce qui la refusait était
    l'absence de FORME et non l'absence de politique : sans un rendu qui
    ouvre des ports SANS nommer d'adresse, un fichier n'aurait pu que mimer
    une liste blanche portant la sortie entière.

    Le prédicat vit ICI et non dans `destinations` parce que c'est ce
    fichier qui décide des refus : `wants_rules` est faux exactement là où
    `_refuse_la_posture` refuse quelle que soit la liste. Une épreuve tient
    cet accord, qui ne peut donc pas dériver.

    Ce n'est PAS « a-t-elle une liste bornée » : `destinations.has_bounded_
    list` répond à cette autre question — « y a-t-il des adresses à
    résoudre » — et les deux ne coïncident que sur trois postures sur
    quatre.
    """
    if posture is None:
        return False
    # « nat » est assumé : lui rendre un jeu donnerait l'apparence d'un
    # confinement que le nom de la posture dément.
    if posture.egress == "nat":
        return False
    # Des destinations non bornées se liraient comme une liste blanche
    # portant la sortie entière — à moins que ce soient les PORTS qui
    # soient bornés, auquel cas le rendu n'écrit aucune adresse.
    return bool(posture.destinations_bounded or posture.ports_bounded)


def _refuse_la_posture(posture, destinations):
    """Ce qu'on ne rend PAS, et pourquoi le dire vaut mieux que rendre."""
    if posture is None:
        _refuse("Aucune posture : il n'y a rien à rendre.")
    if posture.egress == "nat":
        _refuse(
            f"« {posture.name} » ne borne rien, et c'est assumé. Lui rendre"
            " un jeu de règles donnerait l'apparence d'un confinement que"
            " le nom de la posture dément."
        )
    if not posture.destinations_bounded:
        # LA FORME « PORTS SEULS » : rien à nommer, donc une liste reçue
        # est une contradiction et le refus tient. Vide, le rendu ouvre des
        # ports vers n'importe où, ce que le fichier écrit en toutes
        # lettres au lieu de le déguiser en liste blanche.
        if posture.ports_bounded and not destinations:
            if not posture.egress_ports:
                _refuse(
                    f"« {posture.name} » borne ses ports et n'en déclare"
                    " aucun. Le fichier ne porterait que « policy drop »,"
                    " sous un nom qui promet une sortie bornée."
                )
            return
        _refuse(
            f"« {posture.name} » borne ses ports, pas ses destinations. Un"
            " fichier de règles la ferait lire comme une liste blanche,"
            " alors que la liste porterait la sortie entière."
        )
    if posture.egress == "none":
        if destinations:
            _refuse(
                f"« {posture.name} » ne laisse rien sortir : les"
                " destinations nommées ne seraient jamais atteintes, et le"
                " fichier dirait le contraire."
            )
        return
    if not destinations:
        _refuse(
            f"« {posture.name} » attend une liste de destinations. Vide,"
            " elle ne joint plus rien — ce qui est une autre posture, pas"
            " celle-ci."
        )
    if posture.dns == "resolver" and not any(
        d.symbol == "dns-resolver" for d in destinations
    ):
        _refuse(
            f"« {posture.name} » résout par un résolveur nommé, absent de"
            " la liste. Sans lui, chaque échec se lit comme une panne de"
            " réseau plutôt que comme un nom qui ne se résout pas."
        )


# Ce qui manque encore pour qu'un rendu CONFINE quoi que ce soit. Le
# vocabulaire est clos : un manque de plus se déclare ici, où les appelants
# le verront, plutôt que dans une phrase libre.
#
# `no-rendering` : le rendu refuse cette posture, il n'y a rien à appliquer.
# `reload-failure-unseen` : le rechargement a lieu à chaque démarrage, mais
#   un rechargement qui ÉCHOUE ne l'empêche pas et personne ne l'apprend —
#   la relecture n'a lieu qu'au déploiement. Le rendre fatal est à portée
#   d'une directive, et refusé faute de preuve : une image dépourvue de
#   l'analyseur s'éteindrait à son premier démarrage, sans message, avant
#   que la relecture puisse en dire la cause.
# `containers-unproven` : la chaîne forward est rendue, jamais confrontée à
#   un conteneur vivant qui tente une sortie hors liste.
NO_RENDERING = "no-rendering"
RELOAD_FAILURE_UNSEEN = "reload-failure-unseen"
CONTAINERS_UNPROVEN = "containers-unproven"
# La machine SORT LIBREMENT entre son premier démarrage et la pose des
# règles. Ce n'est pas une propriété de la posture mais du CHEMIN qui la
# livre : là où l'amorce écrit les règles avant le premier boot, il n'y a
# pas de fenêtre ; là où elles arrivent après, par un canal qui exige que
# la machine réponde déjà, il y en a une de plusieurs minutes.
BOOT_WINDOW_OPEN = "boot-window-open"
UNENFORCED_TOKENS = (
    NO_RENDERING,
    RELOAD_FAILURE_UNSEEN,
    CONTAINERS_UNPROVEN,
    BOOT_WINDOW_OPEN,
)

# Ce que le rendu ne fournit PAS, mais que la posture tient déjà — soit par
# la nature de son réseau, soit parce que ce qu'elle demande est TOTAL.
#
# « nat » ne promet que la sortie, et la traduction d'adresses la donne : il
# n'y a rien à poser.
#
# « none » ne demande aucune liste : elle demande que RIEN ne sorte, et les
# deux chaînes rendues le font en bloc — « policy drop » sur la sortie ET sur
# le transfert, donc le trafic des conteneurs avec. Il n'y a pas de
# destination à énumérer, donc pas d'énumération qui puisse être incomplète :
# c'est ce qui la distingue d'une liste blanche bornée, dont les deux
# faiblesses restantes tiennent justement à ce qu'elle énumère.
#
# Le motif écrit ici auparavant — « un réseau isolé n'a pas de route du
# tout » — reposait sur `network_kind`, qui est DÉCLARÉ et qu'aucun code ne
# configure : la VM reçoit le réseau ordinaire. La conclusion tenait, la
# raison non ; et depuis que le jeu de règles est réellement posé, elle tient
# pour une raison qui, elle, a du code derrière.
TENUES_PAR_LE_RESEAU = ("nat", "none")


def unenforced(posture, after_boot: bool = False) -> tuple:
    """Ce que le rendu de règles ne tient PAS de cette posture.

    Un mécanisme muet sur ce qu'il n'applique pas est ce qui fait croire à
    un confinement qui n'existe pas. Rend la LISTE des manques, en jetons
    non traduits, et l'appelant décide.

    Un tuple VIDE veut dire que cette posture n'attend rien de ce mécanisme
    — soit parce que la nature de son réseau la tient déjà, soit parce que
    tout ce qui manquait a été construit. Une épreuve tient l'équivalence
    avec `egress_enforced` : tant qu'un jeton reste, elle REFUSE la bascule
    du drapeau ; le jour où il n'en reste aucun, elle l'EXIGE.

    `after_boot` décrit le CHEMIN de livraison et non la posture. Vrai, les
    règles n'arrivent qu'une fois la machine debout et joignable : elle sort
    librement pendant tout son démarrage. Le drapeau de la posture, lui, ne
    peut pas en tenir compte — il est per-posture, et deux chemins livrent
    la même. C'est pourquoi le défaut est FAUX : l'équivalence porte sur le
    chemin qui écrit avant le premier boot, et ce paramètre dit l'autre.

    Une posture absente ne promet rien, donc rien ne manque.
    """
    if posture is None:
        return ()
    fenetre = (BOOT_WINDOW_OPEN,) if after_boot else ()
    if posture.egress in TENUES_PAR_LE_RESEAU:
        # La sortie libre n'a pas de fenêtre : rien n'est à poser, donc
        # rien n'arrive en retard. La sortie coupée, elle, en a une — ses
        # règles arrivent par le même canal tardif que les autres.
        return () if posture.egress == "nat" else fenetre
    if not (posture.destinations_bounded or posture.ports_bounded):
        # Seul jeton : le reste porterait sur un rendu qui n'existe pas, et
        # une fenêtre ne s'ouvre pas sur des règles qu'on ne pose jamais.
        return (NO_RENDERING,)
    return (RELOAD_FAILURE_UNSEEN, CONTAINERS_UNPROVEN) + fenetre


def render_egress(posture, destinations=()) -> str:
    """Le contenu du fichier de règles, ou une ValidationError qui dit non.

    Refuser plutôt que rendre une chaîne vide : un fichier vide se déposerait
    sur la machine et s'y lirait comme une politique.
    """
    destinations = _destinations_controlees(destinations)
    _refuse_la_posture(posture, destinations)
    # L'EN-TÊTE DIT OÙ VIT LA SOURCE, et elle n'est pas la même selon la
    # forme : ce fichier se relit sur la machine des mois plus tard, et y
    # annoncer une liste de destinations enverrait chercher ce qu'une
    # posture à ports bornés n'a pas.
    source = (
        "# déploiement, et les ports viennent de la posture."
        if not destinations
        and posture.ports_bounded
        and not posture.destinations_bounded
        else "# déploiement, et la liste des destinations vit dans la"
        " configuration."
    )
    lignes = [
        "#!/usr/sbin/nft -f",
        f"# Généré par ERPLibre — posture « {posture.name} ».",
        "# Ne pas modifier ici : le fichier est réécrit à chaque",
        source,
        "",
        f"table inet {TABLE}",
        f"delete table inet {TABLE}",
        "",
        f"table inet {TABLE} {{",
    ]
    for index, (nom, accroche) in enumerate(CHAINES):
        if index:
            lignes.append("")
        lignes.extend(_lignes_chaine(nom, accroche, posture, destinations))
    lignes.append("}")
    return "\n".join(lignes) + "\n"
