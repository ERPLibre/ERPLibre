#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce texte porte-t-il une donnée qui désigne quelqu'un ou quelque chose ?

La règle est dans `.claude/rules/04-code-conventions.md` : ce qui est versionné
ne nomme ni client, ni base réelle, ni machine, ni adresse. Deux garde-fous s'en
servent — `script/git/hooks/commit-msg` sur le message, et
`script/analyse/check_comment_hygiene.py` sur les commentaires — et ils
partagent CE module. Deux prédicats séparés pour la même question dérivent.

Chaque trouvaille porte sa position dans le texte : l'appelant en déduit la
ligne exacte, plutôt que de rechercher l'extrait à l'aveugle.
"""

from __future__ import annotations

import io
import os
import re

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# La liste des clients et des machines ne peut pas vivre dans le dépôt public :
# c'est ce qu'elle protège. Absente, le contrôle qui s'en sert est muet.
NOMS_INTERDITS = os.path.join(RACINE, "private", "noms_interdits.txt")

IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Les blocs de documentation de la RFC 5737, qui existent pour l'exemple.
IPV4_DOCUMENTAIRES = ("192.0.2.", "198.51.100.", "203.0.113.")

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]*[\w-]\b")

# L'adresse du propriétaire du dépôt n'est pas une donnée de client.
EMAIL_PERMIS = re.compile(r"@(?:technolibre|erplibre)\.", re.IGNORECASE)

# Un segment entre chevrons ou une variable est un gabarit, pas un compte.
HOME = re.compile(r"/(?:home|Users)/(?![<$\"'{])([\w.-]+)/")
HOME_PERMIS = frozenset({"runner", "user", "utilisateur", "USER"})


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
    if valeur.startswith(IPV4_DOCUMENTAIRES):
        return False
    return True


def termes_interdits(chemin=NOMS_INTERDITS):
    """Les termes du fichier privé, en minuscules. Vide s'il n'existe pas."""
    try:
        with io.open(chemin, encoding="utf-8") as fh:
            contenu = fh.read()
    except OSError:
        return []
    termes = []
    for ligne in contenu.split("\n"):
        terme = ligne.strip()
        if terme and not terme.startswith("#"):
            termes.append(terme.lower())
    return termes


def identifiants(texte, termes=()):
    """Les données identifiantes d'un texte : (motif, extrait, position).

    Chaque OCCURRENCE est rendue, et non chaque valeur : la même adresse citée
    à deux endroits est à corriger aux deux.
    """
    trouves = []

    for trouve in IPV4.finditer(texte):
        if adresse_de_machine(trouve.group(0)):
            trouves.append(("adresse", trouve.group(0), trouve.start()))

    for trouve in EMAIL.finditer(texte):
        if not EMAIL_PERMIS.search(trouve.group(0)):
            trouves.append(("courriel", trouve.group(0), trouve.start()))

    for trouve in HOME.finditer(texte):
        if trouve.group(1) not in HOME_PERMIS:
            trouves.append(
                ("compte", f"/home/{trouve.group(1)}/", trouve.start())
            )

    minuscules = texte.lower()
    for terme in termes:
        depart = minuscules.find(terme)
        while depart != -1:
            trouves.append(("nom privé", terme, depart))
            depart = minuscules.find(terme, depart + 1)

    return sorted(trouves, key=lambda t: t[2])
