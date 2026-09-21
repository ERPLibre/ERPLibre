#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Quels rôles une posture nomme, et comment le site leur donne une adresse.

Deux moitiés qui ne se mélangent pas. Le dépôt sait de QUOI une machine a
besoin — l'heure, les paquets, la forge, le coffre — et le site sait OÙ ces
choses se trouvent chez lui. Ce module tient la première et reçoit la
seconde en paramètre : c'est ce qui garde le dépôt public exempt d'adresse
tout en rendant la liste vérifiable sans configuration.

CE QUI SE DÉDUIT NE SE DÉCLARE PAS. Trois rôles se lisent déjà dans les
champs de la posture — le résolveur quand elle en nomme un, la forge quand
elle en a besoin, la passerelle IA quand les fournisseurs distants lui sont
joignables. Les redéclarer ouvrirait la porte à une posture qui nomme une
forge en annonçant ne pas en vouloir, et c'est la contradiction que la
déduction existe pour empêcher.

UNE LISTE VIDE EST UNE RÉPONSE, et elle en dit une seule : cette posture
n'a pas de liste bornée à rendre. Soit rien ne sort, soit rien n'est borné
— le rendu des règles nomme lequel des deux, parce que les deux se
corrigent de deux côtés opposés.

Le carnet d'adresses est celui du SITE : il porte tous les rôles qu'il
connaît, et chaque posture n'en consulte qu'une partie. Une entrée qui ne
sert pas à cette posture-ci n'est donc pas une erreur — refuser le surplus
rendrait un carnet partagé inutilisable dès la deuxième posture.
"""

from __future__ import annotations

from script.lib_valid import ValidationError
from script.posture import allowlist

# Ce qu'une machine bornée atteint quelle que soit la posture : rien ne se
# déploie sans l'heure, les paquets, les secrets et la cible des
# sauvegardes. L'ordre est celui du rendu, et le résolveur passe en tête —
# son absence fait lire tous les autres échecs comme des pannes de réseau.
SOCLE = (
    "ntp",
    "package-mirror",
    "python-index",
    "vault",
    "backup-target",
)

# Le champ de la posture qui commande le rôle, quand il y en a un.
DEDUITS = (
    ("dns-resolver", lambda posture: posture.dns == "resolver"),
    ("forge", lambda posture: posture.needs_forge),
    ("ai-gateway", lambda posture: posture.cloud),
)


def has_bounded_list(posture) -> bool:
    """Cette posture a-t-elle une liste de destinations à rendre ?

    DÉDUIT des deux champs qui le décident : borner les destinations sans
    politique de liste blanche ne nomme rien, et une liste blanche dont les
    destinations ne sont pas bornées porte la sortie entière.
    """
    if posture is None:
        return False
    return posture.destinations_bounded and posture.egress == "allowlist"


def symbols_for(posture) -> tuple:
    """Les rôles que cette posture nomme, dans l'ordre du rendu.

    Vide quand elle n'a pas de liste bornée — ce qui n'est pas un échec :
    c'est la réponse, et le rendu des règles dit laquelle des deux raisons
    s'applique.
    """
    if not has_bounded_list(posture):
        return ()
    noms = ["dns-resolver"] if posture.dns == "resolver" else []
    noms.extend(SOCLE)
    for symbole, commande in DEDUITS:
        if symbole not in noms and commande(posture):
            noms.append(symbole)
    return tuple(noms)


def _carnet(symbole, entree):
    """(réseaux, ports) tirés d'une entrée de carnet, quelle que soit sa
    forme.

    Une liste ou une chaîne suffit au cas courant ; un dictionnaire sert au
    site qui sert le même rôle sur un autre port. Toute autre forme est
    refusée plutôt que devinée : devinée, elle deviendrait une liste vide,
    et la machine découvrirait le manque une fois déployée.
    """
    if isinstance(entree, dict):
        return entree.get("networks", ()), entree.get("ports", ())
    if isinstance(entree, (list, tuple, str)):
        return entree, ()
    raise ValidationError(
        f"« {symbole} » : entrée de carnet illisible. Attendu une liste de"
        " réseaux, ou un dictionnaire « networks » et « ports »."
    )


def destinations_for(posture, addresses) -> tuple:
    """Les destinations prêtes à rendre, chacune passée par le contrôle.

    `addresses` est le carnet du site — {rôle: réseaux} —, celui que la
    configuration privée porte et que le dépôt ne suit pas.

    Un rôle nommé sans adresse est REFUSÉ ici : rendu quand même, il
    produirait une machine qui ne joint pas sa forge, et le manque se
    découvrirait sur la machine plutôt que devant l'écran.
    """
    carnet = addresses or {}
    prets = []
    for symbole in symbols_for(posture):
        if symbole not in carnet:
            raise ValidationError(
                f"« {symbole} » n'a pas d'adresse dans la configuration du"
                f" site. La posture « {posture.name} » le nomme, et sans"
                " lui la machine se déploie sans l'atteindre."
            )
        reseaux, ports = _carnet(symbole, carnet[symbole])
        prets.append(allowlist.resolve(symbole, reseaux, ports))
    return tuple(prets)
