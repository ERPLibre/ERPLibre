#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'historique des SMS, par correspondant, et qui dure.

La memoire du modem ne convient pas : elle tient quelques messages, l'agent de
la passerelle efface ceux qu'il a remontes, et un message ENVOYE n'y porte
aucune date tant qu'aucun accuse de reception n'a ete demande. Une liste tiree
d'elle ne montre donc ni les echanges d'hier ni le fil d'une conversation.

Le journal vit sous `private/` : un SMS porte un numero de telephone et ce que
quelqu'un a ecrit.

Une ligne par message, ajoutee et jamais reecrite : un fichier tenu en un seul
bloc se perd en entier quand l'ecriture est interrompue, la ou une ligne
tronquee ne coute que le dernier message.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

#: Ou vit le journal, sous la racine du depot.
FICHIER_RELATIF = "private/sms/historique.jsonl"


def racine() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def chemin(fichier: str = "") -> str:
    return fichier or os.path.join(racine(), FICHIER_RELATIF)


def cle_numero(numero: str) -> str:
    """Les chiffres du numero, indicatif nord-americain compris.

    Le meme correspondant s'ecrit « +1 514 555-0142 » a l'arrivee et
    « 5145550142 » a la saisie : sans normalisation, une conversation se
    scinderait en deux fils.
    """
    chiffres = "".join(c for c in str(numero or "") if c.isdigit())
    if len(chiffres) == 10:
        chiffres = "1" + chiffres
    return chiffres


def _signature(entree: dict) -> tuple:
    """Ce qui distingue deux messages. L'horodatage en est ecarte : le meme
    message relu depuis le modem n'en porte pas toujours un."""
    return (entree.get("sens"), cle_numero(entree.get("numero")),
            (entree.get("texte") or "").strip())


def lister(fichier: str = "") -> list:
    """Tout le journal, du plus ancien au plus recent.

    Une ligne illisible est sautee, pas fatale : elle ne coute que son propre
    message, et le reste de l'historique se lit quand meme.
    """
    try:
        with open(chemin(fichier), encoding="utf-8") as flux:
            lignes = flux.readlines()
    except OSError:
        return []
    entrees = []
    for ligne in lignes:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            entrees.append(json.loads(ligne))
        except ValueError:
            continue
    return entrees


def ajouter(sens: str, numero: str, texte: str, horodatage: str = "",
            fichier: str = "") -> dict:
    """Ajoute un message et le rend. Un doublon exact n'est pas reecrit."""
    entree = {
        "sens": sens,
        "numero": numero,
        "texte": texte,
        "horodatage": horodatage or datetime.now().isoformat(timespec="seconds"),
    }
    connues = {_signature(e) for e in lister(fichier)}
    if _signature(entree) in connues:
        return entree
    cible = chemin(fichier)
    os.makedirs(os.path.dirname(cible), mode=0o700, exist_ok=True)
    with open(cible, "a", encoding="utf-8") as flux:
        flux.write(json.dumps(entree, ensure_ascii=False) + "\n")
    os.chmod(cible, 0o600)
    return entree


def fusionner_du_modem(messages, fichier: str = "") -> int:
    """Verse dans le journal ce que le modem porte encore.

    Rend le nombre de messages retenus. Ce que l'agent de la passerelle a
    deja efface du modem ne revient pas : le journal est la seule memoire
    longue, et c'est pourquoi l'envoi s'y ecrit sans attendre.
    """
    retenus = 0
    for message in messages:
        sens = "out" if (message.get("etat") or "") in ("sent", "sending") else "in"
        entree = {"sens": sens, "numero": message.get("numero") or "",
                  "texte": message.get("texte") or ""}
        if not entree["numero"]:
            continue
        avant = len(lister(fichier))
        ajouter(sens, entree["numero"], entree["texte"],
                message.get("horodatage") or message.get("remis_le") or "",
                fichier)
        retenus += len(lister(fichier)) - avant
    return retenus


def par_correspondant(fichier: str = "") -> list:
    """Les conversations, la plus recemment active en tete.

    Rend [(numero affichable, [messages du plus ancien au plus recent])].
    """
    fils = {}
    for entree in lister(fichier):
        fils.setdefault(cle_numero(entree.get("numero")), []).append(entree)
    conversations = []
    for _cle, messages in fils.items():
        messages.sort(key=lambda m: m.get("horodatage") or "")
        conversations.append((messages[-1].get("numero") or "?", messages))
    conversations.sort(key=lambda c: c[1][-1].get("horodatage") or "", reverse=True)
    return conversations
