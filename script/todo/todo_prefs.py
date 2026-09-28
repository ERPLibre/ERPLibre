#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Préférences persistantes du CLI TODO.

Réglages qui survivent d'une session à l'autre et qui appartiennent à
l'UTILISATEUR, pas au dépôt : ils vivent donc dans ~/.erplibre (comme la
télémétrie de navigation) et non dans un fichier versionné.

- get(key, default) / set(key, value) : accès unitaire.
- reset() : efface tout et revient aux défauts.

Tout est best-effort : une préférence illisible ou un disque plein ne doivent
JAMAIS empêcher le CLI de démarrer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Clés connues et leur valeur par défaut. Une clé absente de ce dictionnaire
# reste lisible/écrivable, mais n'apparaît pas dans l'écran de configuration.
DEFAULTS = {
    # Interface du déploiement QEMU : "ask" pose la question à chaque fois,
    # "tui" ouvre le formulaire directement, "cli" garde les invites en ligne.
    "qemu_deploy_ui": "ask",
    # Affichage pendant le déploiement : "cli" (sortie texte, facile à copier
    # depuis le terminal) ou "tui" (blocs repliables + copie OSC 52).
    "qemu_deploy_progress": "cli",
    # Interface de la migration Odoo : "ask" / "tui" / "cli".
    "migration_ui": "ask",
    # Balayage de découverte des serveurs LLM : connexions en vol. Sert
    # seulement quand il est INFÉRIEUR au nombre de sondes, le balayage
    # plafonnant à celui-ci — un /24 sur onze ports en compte 2 794. Monter
    # raccourcit en groupant les vagues ; descendre allège la salve sur un
    # commutateur qui perd des paquets sous charge.
    "assistant_sweep_workers": 1024,
    # Délai d'une connexion du balayage, en secondes. Le SEUL réglage d'ici
    # qui fabrique des faux négatifs : sous charge, un hôte joignable en une
    # milliseconde se manque à 0,05 s. Le descendre annonce des réseaux vides
    # qui ne le sont pas.
    "assistant_sweep_timeout": 0.30,
    # Cache courriel : mode par DÉFAUT. Un compte peut le surcharger via
    # sa clé `cache_mode` dans accounts.json ; `null` là-bas veut dire
    # « hérite d'ici ». Valeurs : clear | encrypted | ephemeral.
    "mail_cache_mode": "clear",
    # Rafraîchissement automatique des boîtes, en secondes, ACTIF seulement
    # tant que le TUI courriel est à l'écran. 0 désactive.
    "mail_refresh_sec": 300,
    # Délai d'une lecture IMAP, en secondes. Il ne borne pas la passe mais
    # CHAQUE lecture : un LIST lent sur une grande boîte le dépasse parfois
    # — vu chez un grand fournisseur — et la socket est alors marquée morte
    # par Python pour de bon. Le client rouvre désormais le lien, mais
    # monter ce délai évite la coupure plutôt que de la réparer.
    "mail_timeout_sec": 30,
    # Disposition des volets du client courriel (touche `v`). Voir
    # `script.todo.mail.tui.MAIL_LAYOUTS` pour les valeurs valides ;
    # `resolve_layout` y retombe sur "columns" si la valeur stockée n'en fait
    # plus partie.
    "mail_layout": "columns",
    # Tailles personnalisées des volets (`+`/`-`/`0`, et la souris de la
    # tâche suivante), UNE entrée PAR disposition : {"<layout>": {"folders":
    # <cellules>, "list_pane": <cellules>}}. Une disposition ou un volet
    # absent de ce dictionnaire veut dire « pas encore personnalisé » — la
    # feuille de style de la disposition décide seule. Voir
    # `script.todo.mail.tui.resolve_pane_sizes`, qui retombe sur {} pour
    # toute valeur absente ou corrompue.
    "mail_pane_sizes": {},
}


def _path() -> Path:
    base = Path(os.path.expanduser("~/.erplibre"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "todo_prefs.json"


def load() -> dict:
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    try:
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        pass


def get(key: str, default=None):
    """Valeur d'une préférence : fichier, puis DEFAULTS, puis `default`."""
    if default is None:
        default = DEFAULTS.get(key)
    return load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 - API voulue : prefs.set(...)
    data = load()
    data[key] = value
    _save(data)


def reset() -> int:
    """Efface toutes les préférences. Renvoie le nombre de clés effacées."""
    count = len(load())
    _save({})
    return count
