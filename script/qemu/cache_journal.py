#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le journal d'accès du cache, rendu lisible ligne à ligne.

Lit les lignes JSON du journal sur l'entrée standard et en écrit une par
requête servie. La flèche est la colonne qui compte sous une coupure : « ↑ »
dit que la requête est SORTIE vers l'internet, « · » qu'elle a été servie du
disque de l'hôte. Un déploiement hors ligne n'en produit aucune en « ↑ », et
« --amont » ne garde que celles-là : la commande reste alors muette tant que
rien ne sort.

Chaque ligne est écrite dès qu'elle est lue. « tail -f » y passe un flux sans
fin, et une sortie mise en tampon ne montrerait rien avant plusieurs
kilo-octets, c'est-à-dire des minutes sur un journal qui avance doucement.

Une ligne illisible est passée : le journal s'écrit pendant qu'on le lit, et
la dernière ligne d'un fichier en cours d'écriture est parfois tronquée.
"""

import argparse
import json
import sys


def taille(octets):
    """Une taille lisible, « - » quand la réponse n'avait pas de corps."""
    n = float(octets or 0)
    if not n:
        return "-"
    for unite in ("o", "Kio", "Mio", "Gio"):
        if n < 1024 or unite == "Gio":
            return f"{n:.0f} {unite}" if unite == "o" else f"{n:.1f} {unite}"
        n /= 1024
    return f"{n:.1f} Tio"


def ligne_lisible(brut, amont_seul=False):
    """La ligne à écrire pour une ligne du journal, "" s'il n'y a rien.

    Rend "" sur une ligne illisible et, sous « amont_seul », sur toute
    requête qui n'est pas sortie vers l'internet.
    """
    try:
        d = json.loads(brut)
    except (TypeError, ValueError):
        return ""
    if not isinstance(d, dict):
        return ""
    if amont_seul and not d.get("upstream"):
        return ""
    # L'horodatage du journal est en UTC, au format ISO : les positions 11 à
    # 19 en sont l'heure.
    heure = str(d.get("time", ""))[11:19] or "--:--:--"
    client = str(d.get("client") or "—")
    fleche = "↑" if d.get("upstream") else "·"
    url = str(d.get("url", ""))
    return (
        f"{heure}  {client:<15} {fleche} {d.get('status') or 0:>3} "
        f"{str(d.get('outcome', '?')):<13}{taille(d.get('bytes')):>9}  "
        f"{url[-70:]}"
    )


def main(argv=None, entree=None, sortie=None):
    analyseur = argparse.ArgumentParser(
        description="Met en forme le journal d'accès du cache QEMU."
    )
    analyseur.add_argument(
        "--amont",
        action="store_true",
        help="ne montrer que les requêtes sorties vers l'internet",
    )
    args = analyseur.parse_args(argv)
    entree = entree if entree is not None else sys.stdin
    sortie = sortie if sortie is not None else sys.stdout
    for brut in entree:
        ligne = ligne_lisible(brut, args.amont)
        if not ligne:
            continue
        sortie.write(ligne + "\n")
        sortie.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        # Ctrl-C arrête le suivi, et « tail » fermé ferme le tube : ni l'un
        # ni l'autre n'est une erreur à afficher.
        sys.exit(0)
