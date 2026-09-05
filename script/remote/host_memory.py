#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'appliance qu'on a choisie, retenue d'une entrée de menu à la suivante.

Un menu d'appliance compte des dizaines d'entrées et elles parlent toutes à
la même machine : redemander l'adresse à chacune serait insupportable. Le
choix vit donc à deux étages — un cache de processus, et les préférences,
qui le font survivre à la fermeture du menu.

Ce module ne DEMANDE rien et n'affiche rien : choisir un hôte est une
conversation, et elle appartient au menu. Il tient ce qui a été choisi, et
sait l'écrire en une ligne.

Une FICHE D'HÔTE est le dictionnaire que `script/remote/appliance_ssh.py`
consomme — « target », plus « jump », « port » et « sudo » au besoin. Elle
peut porter « version », que la sonde du produit y dépose.
"""

from __future__ import annotations

from script.todo import todo_prefs
from script.todo.todo_i18n import t


class HostMemory:
    """L'hôte retenu pour UNE appliance, en cache puis en préférence.

    `pref_key` sépare les appliances : deux produits sur la même station
    gardent chacun le leur, et une seule clé les ferait s'écraser.

    `version_label` préfixe la version dans le libellé — le nom court du
    produit. Vide, la version ne s'affiche pas.
    """

    def __init__(self, pref_key: str, version_label: str = "") -> None:
        self._pref_key = pref_key
        self._version_label = version_label
        self._cache = None

    def get(self) -> dict | None:
        """L'hôte retenu, ou None si personne n'en a encore choisi.

        Ne demande RIEN : un None dit à l'appelant qu'il a une question à
        poser, et c'est lui qui sait comment.
        """
        if self._cache:
            return self._cache
        garde = todo_prefs.get(self._pref_key) or {}
        if garde.get("target"):
            self._cache = garde
            return garde
        return None

    def remember(self, host: dict) -> None:
        """Retient l'hôte, pour ce processus et pour les suivants."""
        self._cache = host
        todo_prefs.set(self._pref_key, host)

    def forget(self) -> None:
        """Oublie l'hôte des deux étages à la fois.

        Vider le cache sans vider la préférence le ferait revenir au
        prochain démarrage, et l'oubli n'aurait pas eu lieu.
        """
        self._cache = None
        todo_prefs.set(self._pref_key, {})

    def label(self, host: dict) -> str:
        """« compte@adresse (par rebond) — PVE 9.2 », pour une tête de menu."""
        if not host:
            return ""
        libelle = host.get("target", "?")
        if host.get("jump"):
            libelle += f" ({t('through')} {host['jump']})"
        if host.get("version") and self._version_label:
            libelle += f" — {self._version_label} {host['version']}"
        return libelle
