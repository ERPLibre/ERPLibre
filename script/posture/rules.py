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


def _lignes_chaine(nom, accroche, destinations):
    lignes = [
        f"    chain {nom} {{",
        f"        type filter hook {accroche} priority 0; policy drop;",
        "        ct state established,related accept",
    ]
    if nom == "output":
        lignes.append('        oif "lo" accept')
    for destination in destinations:
        lignes.extend(_lignes_destination(destination))
    lignes.append("    }")
    return lignes


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
# `not-at-boot` : rien ne recharge le fichier à chaque démarrage, avant que
#   le réseau monte — une machine redémarrée repart sans règles.
# `failure-not-fatal` : la relecture DIT qu'un chargement a échoué, et le
#   déploiement se poursuit quand même. Nommer un manque qu'on découvre vaut
#   mieux que retirer le jeton qui l'a fait apparaître.
# `containers-unproven` : la chaîne forward est rendue, jamais confrontée à
#   un conteneur vivant qui tente une sortie hors liste.
NO_RENDERING = "no-rendering"
NOT_AT_BOOT = "not-at-boot"
FAILURE_NOT_FATAL = "failure-not-fatal"
CONTAINERS_UNPROVEN = "containers-unproven"
UNENFORCED_TOKENS = (
    NO_RENDERING,
    NOT_AT_BOOT,
    FAILURE_NOT_FATAL,
    CONTAINERS_UNPROVEN,
)

# Ce que le rendu ne fournit PAS, mais que la posture tient déjà par la
# nature de son réseau : « nat » ne promet que la sortie, que la traduction
# d'adresses donne, et un réseau isolé n'a pas de route du tout. Ni l'une ni
# l'autre n'attend quoi que ce soit d'un jeu de règles.
TENUES_PAR_LE_RESEAU = ("nat", "none")


def unenforced(posture) -> tuple:
    """Ce que le rendu de règles ne tient PAS de cette posture.

    Un mécanisme muet sur ce qu'il n'applique pas est ce qui fait croire à
    un confinement qui n'existe pas. Rend la LISTE des manques, en jetons
    non traduits, et l'appelant décide.

    Un tuple VIDE veut dire que cette posture n'attend rien de ce mécanisme
    — soit parce que la nature de son réseau la tient déjà, soit parce que
    tout ce qui manquait a été construit. Une épreuve tient l'équivalence
    avec `egress_enforced` : tant qu'un jeton reste, elle REFUSE la bascule
    du drapeau ; le jour où il n'en reste aucun, elle l'EXIGE.

    Une posture absente ne promet rien, donc rien ne manque.
    """
    if posture is None:
        return ()
    if posture.egress in TENUES_PAR_LE_RESEAU:
        return ()
    if not posture.destinations_bounded:
        # Seul jeton : le reste porterait sur un rendu qui n'existe pas.
        return (NO_RENDERING,)
    return (NOT_AT_BOOT, FAILURE_NOT_FATAL, CONTAINERS_UNPROVEN)


def render_egress(posture, destinations=()) -> str:
    """Le contenu du fichier de règles, ou une ValidationError qui dit non.

    Refuser plutôt que rendre une chaîne vide : un fichier vide se déposerait
    sur la machine et s'y lirait comme une politique.
    """
    destinations = _destinations_controlees(destinations)
    _refuse_la_posture(posture, destinations)
    lignes = [
        "#!/usr/sbin/nft -f",
        f"# Généré par ERPLibre — posture « {posture.name} ».",
        "# Ne pas modifier ici : le fichier est réécrit à chaque",
        "# déploiement, et la liste des destinations vit dans la",
        "# configuration.",
        "",
        f"table inet {TABLE}",
        f"delete table inet {TABLE}",
        "",
        f"table inet {TABLE} {{",
    ]
    for index, (nom, accroche) in enumerate(CHAINES):
        if index:
            lignes.append("")
        lignes.extend(_lignes_chaine(nom, accroche, destinations))
    lignes.append("}")
    return "\n".join(lignes) + "\n"
