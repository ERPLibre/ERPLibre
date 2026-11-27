# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Aides pour les tests qui lancent de VRAIS processus et vérifient qu'ils
sont morts.

Sans préfixe `test_`, le lanceur unitaire ne le prend pas pour un fichier
de tests.
"""

import os
import time

# Secondes d'attente au-delà desquelles un processus attendu est un échec.
ATTENTE = 5


def vivant(pid):
    """Vrai si `pid` tourne encore ; un zombie compte pour mort."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            etat = fh.read().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError, IndexError):
        return False
    return etat != "Z"


def tous_morts(pids, delai=3):
    """Les `pids` encore vivants après au plus `delai` secondes."""
    fin = time.monotonic() + delai
    restants = list(pids)
    while restants and time.monotonic() < fin:
        restants = [p for p in restants if vivant(p)]
        time.sleep(0.02)
    return restants


def lire(chemin):
    """Le contenu de `chemin`, ou "" s'il n'existe pas encore."""
    try:
        with open(chemin, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def lire_pid(chemin, delai=ATTENTE):
    """Le pid écrit dans `chemin`, attendu au plus `delai` secondes.

    L'écrivain renomme un fichier temporaire : le pid lu est toujours
    complet. Lève TimeoutError si le fichier n'apparaît pas."""
    fin = time.monotonic() + delai
    while not os.path.exists(chemin):
        if time.monotonic() >= fin:
            raise TimeoutError(chemin)
        time.sleep(0.01)
    with open(chemin, encoding="utf-8") as fh:
        return int(fh.read())
