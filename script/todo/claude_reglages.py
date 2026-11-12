#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les réglages Claude Code du dépôt, dans .claude/settings.json.

Ce fichier est versionné : ce qui s'y écrit vaut pour chaque clone. Deux
réglages s'y gèrent d'ici, sans toucher aux autres clés du fichier :

- « ultracode » : vrai, chaque session part avec ultracode, l'orchestration
  par workflows de toute tâche substantielle ; absent, elle part sans. La
  clé est retirée plutôt que mise à faux, pour laisser décider le réglage
  du compte ;
- le hook SessionStart qui lance script/claude/session_start.py à
  l'ouverture (« startup ») et à la reprise (« resume ») d'une session.
  Une entrée d'un autre hook SessionStart reste en place.

Les fonctions rendent un nouveau dictionnaire et n'écrivent rien ; seule
`ecrire` touche au disque.
"""

import copy
import json
import os

FICHIER = os.path.join(".claude", "settings.json")
# $CLAUDE_PROJECT_DIR est la racine du projet que Claude Code donne au hook :
# la commande reste juste quel que soit le dossier où la session s'ouvre.
COMMANDE_HOOK = 'python3 "$CLAUDE_PROJECT_DIR/script/claude/session_start.py"'
SOURCES_HOOK = ("startup", "resume")


def lire(racine):
    """Les réglages du dépôt ; {} si le fichier manque. Lève ValueError
    s'il n'est pas un objet JSON : rien ne doit alors l'écraser."""
    try:
        with open(os.path.join(racine, FICHIER), encoding="utf-8") as fh:
            reglages = json.load(fh)
    except FileNotFoundError:
        return {}
    if not isinstance(reglages, dict):
        raise ValueError(f"{FICHIER} is not a JSON object")
    return reglages


def ecrire(racine, reglages):
    """Écrit `reglages` dans .claude/settings.json, indenté sur 2 espaces
    comme le reste du JSON du dépôt."""
    chemin = os.path.join(racine, FICHIER)
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(reglages, indent=2, ensure_ascii=False) + "\n")


def ultracode_actif(reglages):
    return reglages.get("ultracode") is True


def avec_ultracode(reglages, actif):
    neuf = copy.deepcopy(reglages)
    if actif:
        neuf["ultracode"] = True
    else:
        neuf.pop("ultracode", None)
    return neuf


def _est_le_notre(entree):
    return any(
        h.get("command") == COMMANDE_HOOK for h in entree.get("hooks") or []
    )


def hook_installe(reglages):
    """Vrai si chaque source de SOURCES_HOOK lance le message de session."""
    entrees = (reglages.get("hooks") or {}).get("SessionStart") or []
    couvertes = {e.get("matcher") for e in entrees if _est_le_notre(e)}
    return all(source in couvertes for source in SOURCES_HOOK)


def avec_hook(reglages, installe):
    """Pose ou retire le hook du message de session, une entrée par source.
    Les autres hooks restent ; une section vidée disparaît."""
    neuf = copy.deepcopy(reglages)
    hooks = neuf.setdefault("hooks", {})
    entrees = [
        e for e in hooks.get("SessionStart") or [] if not _est_le_notre(e)
    ]
    if installe:
        entrees += [
            {
                "matcher": source,
                "hooks": [{"type": "command", "command": COMMANDE_HOOK}],
            }
            for source in SOURCES_HOOK
        ]
    if entrees:
        hooks["SessionStart"] = entrees
    else:
        hooks.pop("SessionStart", None)
    if not hooks:
        neuf.pop("hooks")
    return neuf
