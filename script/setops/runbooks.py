#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les séquences du moteur, lues dans son registre, et ce que todo en conduit.

Le Makefile du moteur porte plus de cent trente cibles documentées et ne dit
NULLE PART dans quel ordre les jouer. Le registre des runbooks le dit : il
range les cibles en dix-sept séquences, chacune avec son but, et donne à
chaque étape son « pourquoi », qui n'a de sens qu'à sa place dans la suite.

**RIEN N'EST MASQUÉ.** Une séquence dont on retirerait les étapes que todo ne
lance pas mentirait par omission : huit des dix-sept en ont, et l'une
commencerait à son étape 2. Chaque étape est donc affichée, et ce qui ne se
lance pas d'ici porte la RAISON pour laquelle il ne se lance pas. C'est le
même parti que l'écran d'état, qui montre ses dix lignes avec trois marques
plutôt que la seule liste de ce qui est prêt.

**LA RÈGLE DE PÉRIMÈTRE EST ÉCRITE UNE FOIS**, dans `barriere()`. Deux
copies diraient tôt ou tard deux choses différentes du même geste.

Rien ici ne lance quoi que ce soit : le texte arrive de l'exécuteur.
"""

from __future__ import annotations

import json
from typing import NamedTuple

# La commande qui rend le registre assemblé. Le moteur l'expose depuis la
# contribution `--json` ; sans elle, il faudrait analyser un arbre fait pour
# l'œil, qui dérive au premier changement de mise en page.
ARGV_REGISTRE = (
    "python3",
    "-B",
    "scripts/runbooks.py",
    "lister",
    "--json",
)

# Les natures que le registre déclare, et ce qu'elles valent pour todo.
MESURE = "mesure"
ECRITURE = "ecriture"
DESTRUCTIF = "destructif"
NATURES = (MESURE, ECRITURE, DESTRUCTIF)

# Les portées du registre. `poste` et `toute` ne demandent rien ; `tenant`
# veut un écosystème monté, `site` veut l'underlay du site.
TENANT = "tenant"
SITE = "site"
POSTE = "poste"
TOUTE = "toute"
PORTEES = (TENANT, SITE, POSTE, TOUTE)

# Les raisons de ne pas conduire une étape depuis ici. Vocabulaire CLOS : une
# raison de plus s'ajoute ici, et l'écran la traduit — jamais l'inverse.
DESTRUCTIVE = "destructive"
CONFIRMATION_MOTEUR = "confirmation-moteur"
SANS_ECOSYSTEME = "sans-ecosysteme"
SANS_SITE = "sans-site"
FORME_INCONNUE = "forme-inconnue"
BARRIERES = (
    DESTRUCTIVE,
    CONFIRMATION_MOTEUR,
    SANS_ECOSYSTEME,
    SANS_SITE,
    FORME_INCONNUE,
)

# La variable que les applicateurs du moteur lisent pour écrire au lieu de
# simuler. Une étape qui l'exige est réservée aux phases d'écriture assumée.
CONFIRMER = "CONFIRMER"


class Ecart(NamedTuple):
    """Ce que todo sait d'une cible et que le registre ne dit pas ENCORE.

    `interactif` : la cible PARLE à l'opérateur — elle pose des questions, et
    l'une peut demander un secret. Capturée, elle lit une entrée fermée, rend
    « EOF » et n'a rien fait ; le terminal lui est donc rendu.

    `ecrit` : elle touche au système alors que sa nature déclarée dit le
    contraire. Todo pose sa propre confirmation dessus.

    `drapeau` : le nom d'une variable qui est un INTERRUPTEUR et non une
    valeur. La recette la lit par `$(if $(NOM),…)`, où GNU make tient toute
    chaîne non vide pour vraie : « 0 » force donc autant que « 1 ». Todo ne
    demande jamais sa valeur — il pose une question fermée et passe « 1 », ou
    ne passe rien du tout.
    """

    interactif: bool = False
    ecrit: bool = False
    drapeau: str = ""
    pourquoi: str = ""


# LES ÉCARTS SONT NOMMÉS, PAS DISPERSÉS. Chacun est un manque du registre en
# amont, et une épreuve rougit le jour où le registre le dit lui-même : l'entrée
# doit alors partir, sans quoi elle masquerait la correction. C'est la seule
# façon qu'une table de dérogations ne vieillisse pas en silence.
ECARTS = {
    "config": Ecart(
        interactif=True,
        ecrit=True,
        pourquoi=(
            "assistant qui écrit la configuration Proxmox et sème la voûte,"
            " en demandant un secret par une invite muette"
        ),
    ),
    "instancier-appliquer": Ecart(
        drapeau="FORCE",
        pourquoi=(
            "son libellé enseigne « FORCE=1 », mais la recette lit toute"
            " chaîne non vide : « 0 » passe outre le diff tout autant"
        ),
    ),
}


# LES ONZE PORTES des gestes d'écriture, et le nom de chacune à l'écran. Le
# libellé de la PORTE appartient à todo — court, stable, traduit, il doit tenir
# sur une ligne de menu ; TOUT ce qui décrit le geste vient du registre, relu à
# chaque visite : libellé complet, pourquoi, nature, portée, durée, variables et
# leurs invites. Une seule source, onze portes d'entrée.
#
# Une porte dont la cible n'est pas déclarée au registre ne mène nulle part, et
# une épreuve la refuse.
PORTE_INSTANCIER = "Set-OPS - Generate the inventory, diff first"
PORTE_INSTANCIER_APPLIQUER = "Set-OPS - Take the generated inventory"
PORTE_DEPLOYER = "Set-OPS - Deploy one host, layer by layer"
PORTE_DEPLOYER_GROUPE = "Set-OPS - Deploy one group across the fleet"
PORTE_APPLIQUER = "Set-OPS - Apply one group to the fleet"
PORTE_CREER_VM = "Set-OPS - Create one VM and wait for it"
PORTE_FLOTTE_CREER = "Set-OPS - Create the fleet's missing VMs"
PORTE_FLUX = "Set-OPS - Regenerate the flows and the firewall rules"
PORTE_SITE = "Set-OPS - Regenerate the site playbook"
PORTE_GENOME_INSCRIRE = "Set-OPS - Record the parentage in the instance"
PORTE_CONFIG = "Set-OPS - Proxmox assistant (asks you for a secret)"

PORTES = {
    "instancier": PORTE_INSTANCIER,
    "instancier-appliquer": PORTE_INSTANCIER_APPLIQUER,
    "deployer": PORTE_DEPLOYER,
    "deployer-groupe": PORTE_DEPLOYER_GROUPE,
    "appliquer": PORTE_APPLIQUER,
    "creer-vm": PORTE_CREER_VM,
    "flotte-creer": PORTE_FLOTTE_CREER,
    "flux": PORTE_FLUX,
    "site": PORTE_SITE,
    "genome-inscrire": PORTE_GENOME_INSCRIRE,
    "config": PORTE_CONFIG,
}


def methode(cible) -> str:
    """Le nom de la méthode qui ouvre la porte de `cible`.

    DÉRIVÉ de la cible, et non écrit à côté : une épreuve retrouve ainsi la
    méthode de chaque porte sans table à tenir à jour, et une porte sans
    méthode se voit.
    """
    return "_setops_geste_" + (cible or "").strip().replace("-", "_")


def trouve(runbooks, cible):
    """L'`Etape` que le registre déclare pour `cible`, ou None.

    Une cible peut figurer dans plusieurs séquences. Tant que ces déclarations
    sont IDENTIQUES, la porte en ouvre une sans ambiguïté. Si elles divergent,
    la porte ne peut pas choisir à la place de l'opérateur et rend None : une
    porte qui trancherait au hasard lancerait parfois l'autre geste.
    """
    cible = (cible or "").strip()
    vues = [
        etape
        for runbook in runbooks or ()
        for etape in runbook.etapes
        if etape.cible == cible
    ]
    if not vues or len(set(vues)) > 1:
        return None
    return vues[0]


def ecart(cible):
    """L'`Ecart` de `cible`, ou un écart vide. Jamais None : l'appelant lit
    toujours des champs, et un None ferait un test de plus à chaque usage."""
    return ECARTS.get((cible or "").strip(), Ecart())


class Variable(NamedTuple):
    """Une variable qu'une étape attend, telle que le registre la décrit.

    `invite` est le texte que le MOTEUR a écrit pour la demander : le
    reformuler ici ferait deux libellés pour la même question, et celui du
    moteur est celui que sa console affiche déjà.
    """

    nom: str
    invite: str
    facultative: bool


class Etape(NamedTuple):
    """Une étape d'un runbook, telle que le registre l'écrit."""

    cible: str
    libelle: str
    portee: str
    nature: str
    pourquoi: str
    duree: str
    variables: tuple
    exige_confirmation: bool
    facultative: bool


class Runbook(NamedTuple):
    """Une séquence du moteur, dans son ordre."""

    id: str
    titre: str
    portee: str
    but: str
    etapes: tuple


def _etape(brut):
    """Une `Etape` depuis une entrée du registre, ou None.

    Les champs sur lesquels todo DÉCIDE — la cible, la nature, la portée —
    sont exigés ; ceux qui ne servent qu'à l'affichage tolèrent le vide.
    """
    if not isinstance(brut, dict):
        return None
    cible = brut.get("cible")
    nature = brut.get("nature")
    if not isinstance(cible, str) or not cible.strip():
        return None
    if nature not in NATURES:
        return None
    portee = brut.get("portee")
    if portee is not None and portee not in PORTEES:
        return None
    variables = brut.get("variables")
    if variables is not None and not isinstance(variables, list):
        return None
    # LES VARIABLES SONT DES TABLES, PAS DES NOMS. Le registre écrit
    # {nom, invite, facultatif} : les traiter comme des chaînes ferait
    # demander une valeur pour « {'nom': 'HOTE', …} », et passerait cette
    # table à `make` comme nom de variable.
    attendues = []
    for variable in variables or ():
        if not isinstance(variable, dict):
            return None
        nom = variable.get("nom")
        if not isinstance(nom, str) or not nom.strip():
            return None
        attendues.append(
            Variable(
                nom=nom.strip(),
                invite=str(variable.get("invite") or ""),
                facultative=bool(variable.get("facultatif")),
            )
        )
    fixes = brut.get("fixes")
    if fixes is not None and not isinstance(fixes, dict):
        return None
    return Etape(
        cible=cible.strip(),
        libelle=str(brut.get("libelle") or ""),
        portee=portee or "",
        nature=nature,
        pourquoi=str(brut.get("pourquoi") or ""),
        duree=str(brut.get("duree") or ""),
        variables=tuple(attendues),
        exige_confirmation=CONFIRMER in (fixes or {}),
        facultative=bool(brut.get("facultative")),
    )


def lit_registre(sortie):
    """Les runbooks que le registre déclare, ou None si la forme change.

    La recette `make` n'est pas en cause ici — le script est appelé
    directement — mais la lecture commence tout de même à la première
    accolade : un avertissement de Python sur la sortie ne doit pas rendre
    le registre illisible.

    Fermé par défaut : une étape dont la nature ou la cible ne se lisent pas
    fait rendre None pour TOUT le registre. Une séquence partielle serait
    pire qu'une absence, puisque son ordre est ce qu'on vient y chercher.
    """
    texte = sortie or ""
    debut = texte.find("[")
    if debut < 0:
        return None
    try:
        lu, _fin = json.JSONDecoder().raw_decode(texte[debut:])
    except ValueError:
        return None
    if not isinstance(lu, list) or not lu:
        return None
    trouves = []
    for bloc in lu:
        if not isinstance(bloc, dict):
            return None
        rid = bloc.get("id")
        portee = bloc.get("portee")
        if not isinstance(rid, str) or not rid.strip():
            return None
        if portee not in PORTEES:
            return None
        brutes = bloc.get("etapes")
        if not isinstance(brutes, list) or not brutes:
            return None
        etapes = []
        for brute in brutes:
            lue = _etape(brute)
            if lue is None:
                return None
            etapes.append(lue)
        trouves.append(
            Runbook(
                id=rid.strip(),
                titre=str(bloc.get("titre") or ""),
                portee=portee,
                but=str(bloc.get("but") or ""),
                etapes=tuple(etapes),
            )
        )
    return tuple(trouves)


def barriere(etape, ecosysteme="", site=""):
    """Ce qui empêche todo de conduire `etape` d'ici, ou « » s'il peut.

    LA RÈGLE DE PÉRIMÈTRE EST ICI, ET NULLE PART AILLEURS. Deux copies
    diraient tôt ou tard deux choses différentes du même geste.

    L'ordre des refus va du plus général au plus circonstanciel : ce qui
    détruit ne se conduit pas d'ici quel que soit le poste, alors qu'une
    portée manquante se règle en montant un écosystème.
    """
    if etape is None or etape.nature not in NATURES:
        return FORME_INCONNUE
    if etape.nature == DESTRUCTIF:
        return DESTRUCTIVE
    if etape.exige_confirmation:
        return CONFIRMATION_MOTEUR
    if etape.portee == TENANT and not ecosysteme:
        return SANS_ECOSYSTEME
    if etape.portee == SITE and not site:
        return SANS_SITE
    return ""


def conduisible(etape, ecosysteme="", site=""):
    """`etape` se lance-t-elle d'ici ?"""
    return not barriere(etape, ecosysteme, site)


def ecrit(etape):
    """`etape` touche-t-elle au système ?

    Une écriture que le moteur ne garde pas lui-même est celle où todo pose
    sa PROPRE confirmation : la ligne affichée porte `CONFIRMER=false`, et
    pour ces cibles-là le drapeau ne veut rien dire — elles écrivent quand
    même. Sans cette question, la ligne enseignerait qu'un `false` protège.

    Une nature DÉCLARÉE `mesure` ne suffit pas à conclure : un assistant qui
    sème une voûte écrit, quoi que le registre en dise, et `ECARTS` le nomme.
    """
    if etape is None:
        return False
    return etape.nature == ECRITURE or ecart(etape.cible).ecrit


def interactif(etape):
    """`etape` a-t-elle besoin du terminal de l'opérateur ?

    Capturée, une cible qui pose des questions lit une entrée fermée, rend
    « EOF » et n'a rien fait. Le verdict est alors un refus que rien
    n'explique.
    """
    return etape is not None and ecart(etape.cible).interactif


def drapeau(etape):
    """Le nom du drapeau-INTERRUPTEUR de `etape`, ou « ».

    Sa valeur ne se demande jamais : la recette la lit par `$(if $(NOM),…)`,
    et GNU make tient toute chaîne non vide pour vraie. Demander « FORCE= »
    ferait forcer celui qui répond « 0 » pour dire non.
    """
    return ecart(etape.cible).drapeau if etape is not None else ""


def compte(runbook, ecosysteme="", site=""):
    """(conduisibles, total) des étapes de `runbook` depuis ici.

    Affiché en tête de chaque séquence : une liste dont on ne sait pas
    combien elle offre se parcourt en entier pour le découvrir.
    """
    etapes = runbook.etapes if runbook is not None else ()
    ouvertes = sum(1 for e in etapes if conduisible(e, ecosysteme, site))
    return ouvertes, len(etapes)
