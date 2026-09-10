#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les serveurs MCP : ceux qui sont déclarés ici, et ceux qu'il faut demander.

Deux populations, et une seule est lisible sans réseau.

**Les serveurs DÉCLARÉS localement** vivent dans la configuration : un bloc
`mcpServers` global, un bloc par projet, et le `.mcp.json` d'un dépôt. Les
lire est instantané et ne demande rien à personne.

**Les connecteurs du compte** n'y sont pas. Sur la machine où ce module a été
écrit, la configuration ne déclarait AUCUN serveur et `claude mcp list` en
annonçait huit — des connecteurs provisionnés côté compte, que seule cette
commande connaît. Il n'y a donc pas de fichier à lire pour eux.

**Et c'est ce qui commande la forme de l'écran.** `claude mcp list` interroge
la SANTÉ de chaque serveur en réseau : il commence par « Checking MCP server
health… » et attend. Un menu qui l'appellerait pour afficher son propre
compte ferait attendre le réseau à chaque passage. L'interrogation est donc
une ENTRÉE qu'on choisit, jamais un effet de l'affichage — la même règle que
la découverte d'un serveur de modèle, qui ne sonde rien avant qu'on le
demande.

**Seules les commandes de LECTURE sont construites ici.** `add`, `remove`,
`login` et `logout` changent la configuration ou ouvrent une authentification,
et un menu qui les propose à côté d'une simple liste invite à en lancer une
par erreur. Elles restent au CLI, où l'on va exprès.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

# Où la configuration déclare des serveurs. Le fichier de compte porte un bloc
# global et un bloc par projet ; le dépôt peut porter son propre `.mcp.json`.
COMPTE = "~/.claude.json"
DEPOT = ".mcp.json"


@dataclass(frozen=True)
class Serveur:
    """Un serveur MCP déclaré, et d'où sa déclaration vient.

    `origine` est ce qui compte pour agir : un serveur du dépôt s'ajoute pour
    tout clone, un serveur de projet ne vaut que là, un serveur global suit
    la machine.
    """

    nom: str
    origine: str
    transport: str = ""
    cible: str = ""


def _charger(chemin):
    try:
        with open(os.path.expanduser(chemin), encoding="utf-8") as fh:
            donnees = json.load(fh)
    except (OSError, ValueError):
        return {}
    return donnees if isinstance(donnees, dict) else {}


def _decrire(nom, bloc, origine) -> Serveur:
    """Ce qu'un bloc de déclaration dit, sans inventer ce qu'il ne dit pas.

    La cible est l'URL ou la commande, selon le transport. Ni l'une ni l'autre
    n'est devinée : un bloc qui ne porte aucune des deux rend une cible vide,
    et l'écran affiche un tiret plutôt qu'un chemin supposé.
    """
    if not isinstance(bloc, dict):
        return Serveur(nom=nom, origine=origine)
    transport = str(bloc.get("type") or bloc.get("transport") or "")
    cible = str(bloc.get("url") or bloc.get("command") or "")
    if not transport and cible:
        transport = "http" if cible.startswith("http") else "stdio"
    return Serveur(nom=nom, origine=origine, transport=transport, cible=cible)


def declares(*, compte=None, depot=None, charger=None) -> list[Serveur]:
    """Les serveurs déclarés localement, sans toucher au réseau.

    `depot` est la racine du dépôt courant, pour son `.mcp.json`. Rien n'est
    inventé : une configuration qui ne déclare rien rend une liste vide, et
    l'écran dit alors que les connecteurs du compte, eux, demandent une
    interrogation.
    """
    charger = charger or _charger
    trouves = []
    conf = charger(compte or COMPTE)
    for nom, bloc in (conf.get("mcpServers") or {}).items():
        trouves.append(_decrire(nom, bloc, "global"))
    for chemin, projet in (conf.get("projects") or {}).items():
        for nom, bloc in ((projet or {}).get("mcpServers") or {}).items():
            trouves.append(
                _decrire(nom, bloc, os.path.basename(chemin.rstrip("/")))
            )
    if depot:
        local = charger(os.path.join(depot, DEPOT))
        for nom, bloc in (local.get("mcpServers") or {}).items():
            trouves.append(_decrire(nom, bloc, DEPOT))
    return sorted(trouves, key=lambda s: (s.origine, s.nom))


def argv_lister() -> list[str]:
    """L'argv qui interroge les serveurs. Il ATTEND le réseau.

    C'est pour ça qu'il n'est lancé que sur une entrée choisie : la commande
    contrôle la santé de chaque serveur, et un menu qui l'appellerait pour
    s'afficher ferait attendre le réseau à chaque passage.
    """
    return ["claude", "mcp", "list"]


def argv_detail(nom: str) -> list[str]:
    """L'argv qui détaille UN serveur. Lecture seule, comme la liste."""
    if not nom or nom.startswith("-"):
        raise ValueError(f"nom de serveur refusé : {nom!r}")
    return ["claude", "mcp", "get", nom]
