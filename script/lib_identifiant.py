#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce texte porte-t-il une donnée qui désigne quelqu'un ou quelque chose ?

La règle est dans `.claude/rules/04-code-conventions.md` : ce qui est versionné
ne nomme ni client, ni base réelle, ni machine, ni adresse. Deux garde-fous s'en
servent — `script/git/commit_msg_lib.py` sur le message, et
`script/analyse/check_comment_hygiene.py` sur les commentaires — et ils
partagent CE module. Deux prédicats séparés pour la même question dérivent.

Chaque trouvaille porte sa position dans le texte : l'appelant en déduit la
ligne exacte, plutôt que de rechercher l'extrait à l'aveugle.
"""

from __future__ import annotations

import io
import os
import re
import sys

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# La liste des clients et des machines ne peut pas vivre dans le dépôt public :
# c'est ce qu'elle protège. Absente, le contrôle qui s'en sert est muet — et
# c'est le pire des cas, puisque rien ne distingue « aucun nom trouvé » de
# « aucun nom cherché ». Le dire une fois par exécution lève l'ambiguïté.
NOMS_INTERDITS = os.path.join(RACINE, "private", "noms_interdits.txt")
NOMS_INTERDITS_VAR = "EL_NOMS_INTERDITS"

_liste_absente_dite = False


def chemin_noms_interdits():
    """Le fichier de noms interdits, « EL_NOMS_INTERDITS » d'abord.

    Résolu à CHAQUE appel : une valeur par défaut figée à l'import rendrait
    la couture inopérante pour qui pose la variable après le chargement.
    """
    return os.environ.get(NOMS_INTERDITS_VAR) or NOMS_INTERDITS


IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Les blocs de documentation de la RFC 5737, qui existent pour l'exemple.
IPV4_DOCUMENTAIRES = ("192.0.2.", "198.51.100.", "203.0.113.")

# Un réseau qu'un ÉDITEUR documente comme son défaut est un fait durable et
# non l'adresse de quelqu'un. Le réécrire en adresse d'exemple rendrait faux
# ce qu'il documente ; changer la constante de déploiement pour satisfaire un
# vérificateur serait pire, puisque cela changerait ce que le code configure.
# Les deux dernières familles viennent du dépôt lui-même ; un test épingle
# qu'elles couvrent bien INTERNAL_CANDIDATES, sans quoi les deux dérivent.
IPV4_DEFAUTS_EDITEUR = (
    "192.168.122.",  # réseau « default » de libvirt
    "10.10.10.",  # ces huit-là : proxmox_deploy.INTERNAL_CANDIDATES,
    "10.10.20.",  # le pont interne descend d'un cran par étage imbriqué
    "10.10.30.",
    "10.10.40.",
    "10.20.10.",
    "10.30.10.",
    "172.31.10.",
    "192.168.210.",
    "10.7.0.",  # plage du tunnel dans les gabarits VPN
)

# Le dernier label est ALPHABÉTIQUE. Sans cette borne, un « compte@adresse »
# vaut un courriel en plus de l'adresse qu'il porte, qui compte alors double,
# et une épingle pip « paquet.git@v8.0.19 » vaut un compte.
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")

# Ce qui ne désigne personne : le compte de service d'une forge en URL ssh,
# l'adresse du propriétaire du dépôt, et les noms que la RFC 2606 réserve à
# l'exemple — l'équivalent, pour les noms, de la RFC 5737 pour les adresses.
EMAIL_PERMIS = re.compile(
    r"^git@"
    r"|@(?:technolibre|erplibre)\."
    r"|\.(?:example|invalid|test|localhost)$"
    r"|@example\.(?:com|net|org)$",
    re.IGNORECASE,
)

# Un segment entre chevrons ou une variable est un gabarit, pas un compte.
HOME = re.compile(r"/(?:home|Users)/(?![<$\"'{])([\w.-]+)/")

# UNE BASE SE NOMME DANS UN « -d ». C'est la forme sous laquelle un nom de
# base réelle entre dans un commentaire : une recette collée depuis un
# terminal, avec la base sur laquelle on l'a jouée. Les adresses, les
# courriels et les chemins de compte étaient cherchés ; celui-là ne l'était
# pas, et il ne se voyait que si le nom figurait dans la liste privée.
BASE_NOMMEE = re.compile(r"(?:^|\s)-d\s+(?![<$\"'{])([A-Za-z_][\w.-]*)")

# Ce qui ne désigne aucune base réelle : les noms que le dépôt emploie pour
# ses propres exemples, ceux qu'un lecteur comprend comme un gabarit, et les
# bases que le dépôt crée pour lui-même.
BASE_PERMISE = re.compile(
    r"^(?:db|base|database|nom|name|dbname|test|demo|exemple|sample"
    r"|my|mon|ma|erplibre|odoo|postgres|template\d*|\$|\{)",
    re.IGNORECASE,
)

# UN NOM DE BASE PORTE UNE STRUCTURE. Ceux qu'on trouve dans un parc
# s'écrivent « client_env_date » ou « nom_version » : ils portent un tiret
# bas ou un chiffre. Sans cette borne, « -d » suivi d'un mot de la phrase
# qui l'entoure — « produit un -d vide dès que… » — compte pour une base, et
# un rouge qui crie faux apprend à ignorer le rouge.
BASE_STRUCTUREE = re.compile(r"[_\d]")
# Des RÔLES que le dépôt définit lui-même — le compte de service dans les
# conteneurs, celui des exemples — et non des personnes.
HOME_PERMIS = frozenset(
    {"runner", "user", "utilisateur", "USER", "odoo", "erplibre", "test"}
)


# Un fichier DÉCLARE qu'une valeur y est inventée : « hygiene-exemple: <valeur> »,
# en commentaire, n'importe où. C'est ce qui permet à un test de PORTER la donnée
# qu'il doit faire détecter — sans elle il ne prouverait rien — sans que le
# vérificateur la prenne pour une fuite. Une déclaration ne vaut que dans le
# fichier qui la porte, et jamais pour un nom propre : un nom de client ne
# s'invente pas, il se retire.
MARQUEUR_EXEMPLE = re.compile(r"hygiene-exemple\s*:\s*(\S+)")


def exemples_declares(source):
    """Les valeurs qu'un fichier déclare inventées, par « hygiene-exemple »."""
    return {
        trouve.group(1).strip("\"'.,;)")
        for trouve in MARQUEUR_EXEMPLE.finditer(source)
    }


def adresse_de_machine(valeur):
    """Cette suite de quatre nombres désigne-t-elle une machine du parc ?

    Non pour un octet hors bornes, une version de module Odoo (`18.0.1.3`), la
    boucle locale, un masque, un bloc documentaire, et une adresse de RÉSEAU —
    un dernier octet nul nomme une plage, pas un hôte.
    """
    try:
        nombres = [int(o) for o in valeur.split(".")]
    except ValueError:
        return False
    if len(nombres) != 4 or any(n > 255 for n in nombres):
        return False
    if 12 <= nombres[0] <= 18 and nombres[1] == 0:
        return False
    if nombres[0] in (0, 127, 255) or nombres[3] == 0:
        return False
    if valeur.startswith(IPV4_DOCUMENTAIRES + IPV4_DEFAUTS_EDITEUR):
        return False
    return True


def termes_interdits():
    """Les termes du fichier privé, en minuscules. Vide s'il n'existe pas.

    Une absence est DITE, une fois par exécution, sur stderr : un contrôle
    muet se lit comme un contrôle satisfait.

    AUCUN CHEMIN EN PARAMÈTRE, et c'est la garde : le garde-fou du message
    de commit en passait un — la constante du module — et ignorait donc
    « EL_NOMS_INTERDITS » que l'autre honorait. Qui range sa liste ailleurs
    voyait ses commentaires contrôlés et ses commits, non. Sans paramètre,
    il n'y a plus qu'une façon de résoudre ce chemin.
    """
    global _liste_absente_dite
    chemin = chemin_noms_interdits()
    try:
        with io.open(chemin, encoding="utf-8") as fh:
            contenu = fh.read()
    except OSError:
        if not _liste_absente_dite:
            _liste_absente_dite = True
            print(
                f"⚠ {chemin} absent : aucun nom propre n'est cherché."
                " Un nom par ligne, « # » en commentaire.",
                file=sys.stderr,
            )
        return []
    termes = []
    for ligne in contenu.split("\n"):
        terme = ligne.strip()
        if terme and not terme.startswith("#"):
            termes.append(terme.lower())
    return termes


def motif_de_termes(termes):
    """Un motif à frontières de mot pour toute la liste, None si elle est vide.

    Les frontières sont la différence entre chercher un nom et chercher une
    suite de lettres : un sigle de quatre lettres se retrouve autrement dans
    des mots communs, et la trouvaille se noie dans ce qu'elle a ramassé.

    LE SOULIGNÉ COMPTE POUR UNE FRONTIÈRE, et c'est le point : « \\b » ne
    voit pas la fin d'un nom collé à un suffixe par un souligné, alors que
    c'est la forme même d'un nom de base de données. Un nom listé passait
    donc à travers dès qu'il portait un suffixe — le mécanisme existait, la
    liste pouvait être juste, et la trouvaille n'arrivait pas.

    Les frontières portent sur les LETTRES seules. Un chiffre qui suit ne
    prolonge pas le nom, il le numérote : « copy_<nom>3 » est la copie d'une
    base réelle, et l'exclure des trouvailles laisserait passer la forme la
    plus courante. Ce qui précède ou suit dans un identifiant compose avec
    le nom, il n'en fait pas un autre mot.
    """
    if not termes:
        return None
    return re.compile(
        r"(?<![a-z])(?:%s)(?![a-z])" % "|".join(re.escape(t) for t in termes),
        re.IGNORECASE,
    )


def identifiants(texte, termes=(), exemples=()):
    """Les données identifiantes d'un texte : (motif, extrait, position).

    Chaque OCCURRENCE est rendue, et non chaque valeur : la même adresse citée
    à deux endroits est à corriger aux deux. `exemples` porte ce que le fichier
    déclare inventé ; la déclaration ne couvre PAS les noms propres.
    """
    trouves = []
    exemples = frozenset(exemples)

    for trouve in IPV4.finditer(texte):
        if trouve.group(0) in exemples:
            continue
        if adresse_de_machine(trouve.group(0)):
            trouves.append(("adresse", trouve.group(0), trouve.start()))

    for trouve in EMAIL.finditer(texte):
        if trouve.group(0) in exemples:
            continue
        if not EMAIL_PERMIS.search(trouve.group(0)):
            trouves.append(("courriel", trouve.group(0), trouve.start()))

    for trouve in HOME.finditer(texte):
        if trouve.group(1) not in HOME_PERMIS:
            trouves.append(
                ("compte", f"/home/{trouve.group(1)}/", trouve.start())
            )

    for trouve in BASE_NOMMEE.finditer(texte):
        nom = trouve.group(1)
        if nom in exemples or BASE_PERMISE.match(nom):
            continue
        if not BASE_STRUCTUREE.search(nom):
            continue
        trouves.append(("base", nom, trouve.start(1)))

    motif = motif_de_termes(tuple(termes))
    if motif:
        for trouve in motif.finditer(texte):
            trouves.append(
                ("nom privé", trouve.group(0).lower(), trouve.start())
            )

    return sorted(trouves, key=lambda t: t[2])
