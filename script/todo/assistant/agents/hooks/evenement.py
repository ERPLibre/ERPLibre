#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le hook qui écrit un événement d'agent. Il ne doit JAMAIS échouer.

Claude Code lance ce script à chaque appel d'outil, lui donne l'événement en
JSON sur l'entrée standard, et lit son code de sortie. Un code non nul sur un
`PreToolUse` BLOQUE l'appel : une télémétrie qui lèverait empêcherait donc le
travail qu'elle prétend mesurer. Tout est par conséquent enveloppé, et la
sortie est zéro quoi qu'il arrive — entrée illisible, disque plein, journal
impossible à créer.

**Aucune dépendance, aucun import du dépôt.** Ce script tourne des centaines
de fois par session, dans un interpréteur neuf chaque fois. Importer `todo.py`
coûterait près d'une seconde par appel d'outil ; importer même le paquet de
l'assistant tirerait `click` et l'internationalisation. Il ne lit donc que la
bibliothèque standard, et recopie les quelques constantes du journal — le
prix de la duplication est un test qui vérifie que les deux s'accordent.

**Il ne recopie ni la commande ni la réponse.** L'événement porte `tool_input`
— la ligne bash, le contenu d'une édition — et `tool_response`. Ni l'un ni
l'autre n'est écrit : le journal compte des appels, il ne garde pas ce qu'ils
disent. C'est un choix de conception et non un oubli, et il tient même là où
l'utilisateur a levé la frontière pour l'AFFICHAGE : ce qui n'est pas écrit
n'a pas à être protégé plus tard.
"""
import json
import os
import sys
import time

# Recopiés du journal. Le test `test_agents_hooks.py` vérifie qu'ils
# s'accordent, faute de pouvoir importer sans coûter une seconde par appel.
RACINE = "~/.erplibre/agents"
CHAMPS = ("hook_event_name", "session_id", "tool_name", "tool_use_id", "cwd")
CHAMPS_NOMBRE = ("duration_ms",)
CHAMPS_BOOLEEN = ("is_interrupt",)


def ecrire(brut, *, horloge=None, racine=None) -> bool:
    """Écrire une ligne pour cet événement. Rend vrai si elle est partie.

    `brut` est le texte reçu sur l'entrée standard. La fonction est séparée du
    `main` pour être vérifiable sans lancer de processus.
    """
    horloge = horloge or time.time
    try:
        evenement = json.loads(brut)
        if not isinstance(evenement, dict):
            return False
        ligne = {"ts": int(horloge() * 1000)}
        for champ in CHAMPS:
            valeur = evenement.get(champ)
            if isinstance(valeur, str) and valeur:
                ligne[champ] = valeur
        # Un filtre à chaînes écarte SILENCIEUSEMENT tout nombre : la durée
        # que l'outil rapporte et le drapeau d'interruption sont l'un un
        # entier et l'autre un booléen, donc ils se perdent sans rien dire.
        # Le booléen se teste AVANT l'entier, `isinstance(True, int)` étant
        # vrai en Python.
        for champ in CHAMPS_BOOLEEN:
            valeur = evenement.get(champ)
            if isinstance(valeur, bool):
                ligne[champ] = valeur
        for champ in CHAMPS_NOMBRE:
            valeur = evenement.get(champ)
            if isinstance(valeur, int) and not isinstance(valeur, bool):
                ligne[champ] = valeur
        if "hook_event_name" not in ligne:
            return False
        jour = time.strftime("%Y-%m-%d", time.localtime(horloge()))
        dossier = os.path.expanduser(racine or RACINE)
        os.makedirs(dossier, exist_ok=True)
        # UTF-8 explicite, comme le lecteur l'impose. Sans lui, le fichier
        # s'ouvre dans l'encodage de la LOCALE, et un chemin de travail
        # accentué lève sous une locale latine — l'exception est avalée par
        # le filet du hook, et l'événement se perd sans que rien ne le dise.
        with open(
            os.path.join(dossier, f"{jour}.jsonl"), "a", encoding="utf-8"
        ) as fh:
            fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def main(argv=None) -> int:
    """Toujours zéro. Un code non nul bloquerait l'appel d'outil observé."""
    try:
        ecrire(sys.stdin.read())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
