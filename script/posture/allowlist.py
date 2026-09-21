#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'une posture bornée a le droit d'atteindre, nommé par son RÔLE.

Un symbole est un rôle — le résolveur, la forge, le coffre — avec le port
par défaut du service, son protocole, et la raison qui justifie de lui
ouvrir une sortie. Il ne porte AUCUNE adresse : une adresse est une donnée
de site, elle vit dans la configuration privée, et le dépôt reste public.

Le rapprochement se fait à l'appel : `resolve` reçoit les réseaux du site,
les contrôle, et rend de quoi écrire une règle. Le vocabulaire est CLOS —
un besoin qui n'a pas de symbole se déclare ici, où il se relit, plutôt que
de se glisser dans une liste au moment du rendu.

QUATRE REFUS, ET AUCUN N'EST HÉRITÉ. `cidr_list` normalise, elle ne juge
pas : elle rend « 0.0.0.0/0 » sans broncher. Une liste qui porte la route
par défaut ne borne rien tout en s'annonçant bornée, et c'est exactement le
mensonge qui a fait retirer la posture « restricted » du registre. S'y
ajoutent la liste vide, le préfixe trop large — « 0.0.0.0/1 » deux fois
couvre l'Internet sans jamais écrire la route par défaut — et le nom
d'hôte.

LE NOM D'HÔTE SE REFUSE, il ne se résout pas. Résoudre fige l'adresse du
jour dans une règle : l'enregistrement qui bouge n'est jamais re-suivi, la
liste cesse en silence de couvrir le service, et l'adresse abandonnée peut
être réattribuée à un tiers que la règle autorise toujours.
"""

from __future__ import annotations

import ipaddress
import re
from typing import NamedTuple

from script.lib_valid import ValidationError, cidr_list

TCP = "tcp"
UDP = "udp"
PROTOCOLS = (TCP, UDP)

# Le préfixe le plus large qu'un symbole accepte, par famille d'adresses.
# Un symbole nomme UN service : en deçà, il nomme une région de l'Internet,
# et « destinations bornées » redevient un mot. Le seuil est généreux — un
# /16 porte 65 536 adresses, plus qu'aucun service d'un site n'en occupe.
PREFIXE_MINIMAL = {4: 16, 6: 32}

# Les routes qui couvrent tout. Nommées pour être refusées : elles ne
# désignent aucune machine, et c'est bien le problème.
ROUTES_PAR_DEFAUT = ("0.0.0.0/0", "::/0")

# Ce qui ressemble à un nom plutôt qu'à une adresse : des lettres, et rien
# des deux-points de l'IPv6.
NOM_DHOTE_RE = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9][A-Za-z0-9.-]*$")


class Destination(NamedTuple):
    """Un rôle joignable : ses ports par défaut, et pourquoi on l'ouvre.

    `reason` part dans le fichier de règles rendu, en commentaire, au-dessus
    de ce qu'elle justifie. Une règle qui ne dit pas pourquoi elle existe
    est une règle que personne n'ose retirer.
    """

    symbol: str
    protocols: tuple
    ports: tuple
    reason: str


class Allowed(NamedTuple):
    """Un symbole rapproché des réseaux du site, tout contrôlé."""

    symbol: str
    protocols: tuple
    ports: tuple
    networks: tuple
    reason: str


SYMBOLS = {
    "dns-resolver": Destination(
        symbol="dns-resolver",
        protocols=(UDP, TCP),
        ports=(53,),
        reason=(
            "Sans résolveur joignable, une machine bornée ne résout plus"
            " rien et chaque échec se lit comme une panne de réseau."
        ),
    ),
    "ntp": Destination(
        symbol="ntp",
        protocols=(UDP,),
        ports=(123,),
        reason=(
            "Une horloge qui dérive fait échouer TLS et la vérification des"
            " signatures, sans que l'heure soit jamais nommée comme cause."
        ),
    ),
    "package-mirror": Destination(
        symbol="package-mirror",
        protocols=(TCP,),
        ports=(80, 443),
        reason=(
            "Le miroir de la distribution, ou le cache local qui en tient"
            " lieu. Le port 80 reste : les paquets sont signés, pas le"
            " transport, et les miroirs le servent encore."
        ),
    ),
    "python-index": Destination(
        symbol="python-index",
        protocols=(TCP,),
        ports=(443,),
        reason=(
            "L'index Python, ou son miroir : les dépendances se résolvent au"
            " déploiement, et non une fois pour toutes dans l'image."
        ),
    ),
    "forge": Destination(
        symbol="forge",
        protocols=(TCP,),
        ports=(22, 443, 3000),
        reason=(
            "D'où viennent les sources et où repart le travail. Trois ports"
            " parce qu'une forge se sert en ssh, derrière un terminateur"
            " TLS, ou nue sur son port applicatif."
        ),
    ),
    "vault": Destination(
        symbol="vault",
        protocols=(TCP,),
        ports=(8200,),
        reason=(
            "Le serveur de secrets. Fermé, la machine démarre sans"
            " identifiants ; les poser dans son image serait pire, puisque"
            " l'image se copie et ne se révoque pas."
        ),
    ),
    "backup-target": Destination(
        symbol="backup-target",
        protocols=(TCP,),
        ports=(22,),
        reason=(
            "La cible des sauvegardes. L'ouvrir en sortie est ce qui permet"
            " de sauvegarder sans monter le disque de la machine sur l'hôte."
        ),
    ),
    "ai-gateway": Destination(
        symbol="ai-gateway",
        protocols=(TCP,),
        ports=(443, 4000),
        reason=(
            "Le point de passage unique des appels de modèle. Le nommer est"
            " ce qui permet de TOUT refuser quand il manque, au lieu de"
            " laisser chaque outil chercher sa propre route."
        ),
    ),
}


def get(symbol):
    """La destination `symbol`, ou None.

    Ne lève pas : une configuration de site peut nommer un symbole retiré,
    et l'écran doit pouvoir le dire plutôt que de s'interrompre.
    """
    return SYMBOLS.get(symbol)


def symbol_names():
    """Les symboles dans l'ordre du tableau."""
    return list(SYMBOLS)


def _dire_si_cest_un_nom(reseaux):
    """Relève le message quand ce qui a été refusé est un NOM d'hôte.

    Ne tourne que dans le chemin d'échec, et seulement pour remplacer une
    phrase par une meilleure : le découpage y est volontairement large,
    puisque ne rien reconnaître laisse simplement passer le message
    d'origine. Contrôler ici ce que `cidr_list` contrôle déjà en ferait une
    copie, qui divergerait de son original au premier correctif.
    """
    for jeton in re.split(r"[\s,\[\]()'\"]+", str(reseaux)):
        if jeton and ":" not in jeton and NOM_DHOTE_RE.match(jeton):
            raise ValidationError(
                f"« {jeton} » est un nom, pas un réseau. Le résoudre"
                " figerait l'adresse du jour : un enregistrement qui bouge"
                " n'est jamais re-suivi, et la règle continuerait"
                " d'autoriser une adresse réattribuée depuis. Écrire le"
                " réseau."
            )


def _controle_reseaux(symbol, reseaux):
    """Les réseaux normalisés, ou une ValidationError qui dit laquelle."""
    if isinstance(reseaux, tuple):
        reseaux = list(reseaux)
    try:
        propres = cidr_list(reseaux)
    except ValidationError:
        _dire_si_cest_un_nom(reseaux)
        raise
    if not propres:
        raise ValidationError(
            f"« {symbol} » n'a aucun réseau. Un symbole nommé sans"
            " destination n'ouvre rien, et l'absence se découvrirait sur la"
            " machine plutôt qu'ici."
        )
    for texte in propres:
        reseau = ipaddress.ip_network(texte)
        if texte in ROUTES_PAR_DEFAUT:
            raise ValidationError(
                f"« {texte} » couvre tout. Une liste qui la porte ne borne"
                " aucune destination tout en s'annonçant bornée."
            )
        plancher = PREFIXE_MINIMAL[reseau.version]
        if reseau.prefixlen < plancher:
            raise ValidationError(
                f"« {texte} » est trop large : préfixe /{plancher} au plus"
                f" large pour de l'IPv{reseau.version}. Deux moitiés"
                " couvrent l'Internet sans jamais écrire la route par"
                " défaut."
            )
    return tuple(propres)


def _controle_ports(symbol, ports):
    """Des entiers 1-65535, dédoublonnés et triés — l'ordre fait le rendu.

    Une chaîne se DÉCOUPE au lieu de s'itérer : « 443 » parcouru caractère
    par caractère rend les ports 3 et 4, donc une règle qui ouvre deux
    ports au hasard et pas celui qu'on demandait.
    """
    if isinstance(ports, str):
        ports = [jeton for jeton in re.split(r"[\s,]+", ports) if jeton]
    propres = []
    for brut in ports:
        try:
            numero = int(str(brut).strip())
        except ValueError:
            raise ValidationError(
                f"« {symbol} » : port « {brut} » refusé, un entier est"
                " attendu."
            )
        if not 1 <= numero <= 65535:
            raise ValidationError(
                f"« {symbol} » : port {numero} hors de 1-65535."
            )
        if numero not in propres:
            propres.append(numero)
    if not propres:
        raise ValidationError(
            f"« {symbol} » : aucun port. Une règle sans port ouvrirait les"
            " 65 535 autres avec celui qu'on voulait."
        )
    return tuple(sorted(propres))


def checked_ports(label, ports) -> tuple:
    """Les ports d'une posture, contrôlés par la MÊME porte qu'un symbole.

    Une posture qui borne ses ports sans nommer de destination n'a pas de
    symbole à résoudre, et elle a pourtant des ports à écrire. Elle passe
    donc ici plutôt que de valider chez elle : deux contrôles finiraient
    par diverger, et le plus permissif des deux ferait foi.
    """
    return _controle_ports(label, ports)


def resolve(symbol, networks, ports=()) -> Allowed:
    """Rapproche un symbole des réseaux du site, tout contrôlé.

    `ports` vide reprend ceux du symbole ; le site qui sert la même chose
    ailleurs les remplace, sans que le tableau ait à connaître son port.

    Lève `ValidationError` sur tout ce qui n'est pas une destination bornée
    — la lever ICI est le seul moment où l'écran peut encore le dire.
    """
    destination = get(symbol)
    if destination is None:
        connus = ", ".join(symbol_names())
        raise ValidationError(
            f"« {symbol} » n'est pas un rôle connu. Attendu l'un de :"
            f" {connus}. Un besoin nouveau se déclare dans le tableau, où"
            " il se relit."
        )
    return Allowed(
        symbol=destination.symbol,
        protocols=destination.protocols,
        ports=_controle_ports(symbol, ports or destination.ports),
        networks=_controle_reseaux(symbol, networks),
        reason=destination.reason,
    )
