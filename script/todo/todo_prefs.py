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
    # Le backend de VM employé : auto | libvirt | pve | lima. La préférence
    # est INDICATIVE — elle préselectionne et elle informe, elle ne route
    # rien : aucun chemin de déploiement ne sait piloter autre chose que
    # libvirt en local aujourd'hui. « auto » se résout par le système, voir
    # `script.todo.vm_backend_choice.effective`.
    "vm_backend": "auto",
    # Interface du déploiement QEMU : "ask" pose la question à chaque fois,
    # "tui" ouvre le formulaire directement, "cli" garde les invites en ligne.
    "qemu_deploy_ui": "ask",
    # Affichage pendant le déploiement : "cli" (sortie texte, facile à copier
    # depuis le terminal) ou "tui" (blocs repliables + copie OSC 52).
    "qemu_deploy_progress": "cli",
    # Interface de la migration Odoo : "ask" / "tui" / "cli".
    "migration_ui": "ask",
    # Cache courriel : mode par DÉFAUT. Un compte peut le surcharger via
    # sa clé `cache_mode` dans accounts.json ; `null` là-bas veut dire
    # « hérite d'ici ». Valeurs : clear | encrypted | ephemeral.
    "mail_cache_mode": "clear",
    # Rafraîchissement automatique des boîtes, en secondes, ACTIF seulement
    # tant que le TUI courriel est à l'écran. 0 désactive.
    "mail_refresh_sec": 300,
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


# Ce que `reset` a pu constater. Le vocabulaire est CLOS : un état qu'on ne
# sait pas nommer se refuse plutôt que de se lire comme un succès.
EFFACE = "efface"
EFFACE_SANS_COMPTE = "efface-sans-compte"
ECHEC_ECRITURE = "echec-ecriture"


def _lire() -> tuple:
    """(préférences, lisible).

    `lisible` est FAUX quand le fichier EXISTE et ne se relit pas — un JSON
    tronqué, une virgule en trop. Ce n'est pas la même chose qu'un fichier
    absent, et la différence décide de ce qu'on a le droit d'annoncer : les
    deux rendent {}, mais l'un veut dire « il n'y a rien » et l'autre « le
    contenu est inconnu ».
    """
    chemin = _path()
    if not chemin.exists():
        return {}, True
    try:
        data = json.loads(chemin.read_text())
    except (OSError, ValueError):
        return {}, False
    return (data, True) if isinstance(data, dict) else ({}, False)


def load() -> dict:
    return _lire()[0]


def _save(data: dict) -> bool:
    """Écrit, et dit si l'écriture a eu lieu.

    Avalé, l'échec faisait annoncer un compte de clés effacées sur un
    fichier intact.
    """
    try:
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        return False
    return True


def get(key: str, default=None):
    """Valeur d'une préférence : fichier, puis DEFAULTS, puis `default`."""
    if default is None:
        default = DEFAULTS.get(key)
    return load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 - API voulue : prefs.set(...)
    data = load()
    data[key] = value
    _save(data)


def reset() -> tuple:
    """(verdict, nombre). Efface toutes les préférences.

    LE COMPTE VIENT DE LA LECTURE, ET LA LECTURE PEUT AVOIR ÉCHOUÉ. Un
    fichier tronqué se relit en {} : le compte valait 0 pendant que
    l'écriture REMPLAÇAIT un fichier plein, et l'écran annonçait « (0) » —
    « il n'y avait rien » — sur une destruction. Le nombre est REFUSÉ quand
    il n'est pas connu, plutôt que remplacé par un nombre faux.
    """
    data, lisible = _lire()
    if not _save({}):
        return ECHEC_ECRITURE, 0
    return (EFFACE, len(data)) if lisible else (EFFACE_SANS_COMPTE, 0)
