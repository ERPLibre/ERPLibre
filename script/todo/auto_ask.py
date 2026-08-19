#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Lire une réponse, ou prendre le défaut au bout du délai.

Le mode auto de la migration ne vaut que si TOUTES les invites le
connaissent. Or six d'entre elles vivent dans des outils lancés en
sous-processus — le désinstalleur de thème, le détecteur de SCSS figé, le
test de fumée. Elles ne partagent ni l'objet du pilote ni sa mémoire ; sans
rien de commun, elles attendraient indéfiniment une frappe qui ne vient
pas, et l'automatisation s'arrêterait là sans rien dire.

Ce qui traverse un `fork`, c'est l'environnement. Le pilote y pose
`ERPLIBRE_AUTO_EXECUTE`, chaque outil le lit, et il n'existe qu'une seule
implémentation du compte à rebours.

`select` plutôt qu'un fil ou une alarme : la question est « quelque chose
est-il LISIBLE maintenant », et il faut pouvoir renoncer. Un fil laisserait
derrière lui un `input()` toujours bloqué, qui volerait la frappe suivante.
"""

import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


ENV_ENABLED = "ERPLIBRE_AUTO_EXECUTE"
ENV_DELAY = "ERPLIBRE_AUTO_DELAY"
DEFAULT_DELAY = 5


def enabled():
    """Le mode auto est-il actif pour CE processus ?"""
    return os.environ.get(ENV_ENABLED, "") == "1"


def delay():
    """Combien de secondes attendre. Une valeur illisible ne bloque rien."""
    try:
        value = float(os.environ.get(ENV_DELAY, DEFAULT_DELAY))
    except (TypeError, ValueError):
        return DEFAULT_DELAY
    # Un délai nul ou négatif rendrait la reprise en main impossible : on
    # ne peut pas interrompre ce qui ne laisse aucune fenêtre.
    return value if value > 0 else DEFAULT_DELAY


def export(on, seconds=None):
    """Poser le mode auto dans l'environnement, pour tout ce qu'on lancera.

    C'est le seul canal qu'un sous-processus partage avec nous. Le retirer
    quand on l'éteint, plutôt que d'y écrire « 0 », évite qu'un reste de
    session précédente décide à notre place.
    """
    if on:
        os.environ[ENV_ENABLED] = "1"
        os.environ[ENV_DELAY] = str(
            seconds if seconds is not None else DEFAULT_DELAY
        )
    else:
        os.environ.pop(ENV_ENABLED, None)
        os.environ.pop(ENV_DELAY, None)


def ask(prompt, default="", seconds=None):
    """Poser la question. Rendre `default` si rien n'arrive à temps.

    Hors mode auto, c'est un `input()` ordinaire — sauf qu'une réponse vide
    vaut le défaut, comme partout ailleurs en ligne de commande. C'est ce
    qui permet d'écrire l'attendu dans la question : « (Y/n) » doit dire la
    vérité pour la personne qui appuie sur Entrée, pas seulement pour le
    compte à rebours.
    """
    if not enabled():
        return input(prompt) or default
    import select

    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        ready, _, _ = select.select(
            [sys.stdin], [], [], delay() if seconds is None else seconds
        )
    except (OSError, ValueError):
        # stdin n'est pas sélectionnable : on ne devine pas, on demande.
        return input("") or default
    if ready:
        answer = sys.stdin.readline().rstrip("\n")
        # Une réponse VIDE vaut « prends le défaut » : c'est tout le propos
        # du mode auto. Un stdin fermé — exécution non interactive — est
        # lisible tout de suite et rend justement une ligne vide ; sans
        # ceci, le défaut ne servirait jamais là.
        return answer or default
    # « Entrée », parce que c'est ce que l'invite a proposé. Elle annonce
    # « Entrée = effacer, k = garder » et ne mentionne nulle part « d » :
    # afficher la valeur brute nommait donc une réponse qui n'était pas au
    # menu, et l'on se demandait ce que l'outil venait de décider. La
    # valeur reste, entre parenthèses, pour qui veut la précision.
    detail = f" ({default})" if default else ""
    print(f" ⏱ → {t('Enter')}{detail}")
    return default


def make_ask(default, seconds=None):
    """Un `ask` à un seul argument, pour les outils qui en injectent un.

    Ils appellent `ask(question)` sans savoir ce qu'est un défaut : celui-ci
    appartient à l'outil, pas à l'appelant, et se fige donc ici.
    """

    def ask_one(prompt=""):
        return ask(prompt, default=default, seconds=seconds)

    return ask_one
