#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Registre des menus de TODO : chaque menu déclaré comme une donnée.

Un fichier de menus, `script/todo/menus/<famille>.py`, n'écrit que des
appels de ces constructeurs, aux arguments littéraux :
`navigator.navigate` affiche un menu et répond à ses entrées,
`todo_telemetry.build_code_tree` le lit par AST, sans rien importer. Ce
module n'importe ni TODO ni une bibliothèque d'interface.

`key` (d'une `Entry` ou d'une `Section`) est une clé de traduction
anglaise, que `t()` traduit au rendu. `action`, `state`, `intro` et
`suffix` sont des NOMS de méthodes de TODO, jamais des fonctions. Le
numéro d'une entrée est sa place parmi les entrées numérotées : une
`Section` n'en prend pas, un `FromConfig` en prend un par élément de sa
liste.
"""

from dataclasses import dataclass

RENDERS = ("each", "once")


@dataclass(frozen=True)
class Section:
    """Titre de section `── t(key) ──`, qui ne prend pas de numéro."""

    key: str


@dataclass(frozen=True)
class Entry:
    """Entrée numérotée : `t(key)`, suivi de `  (…)`, ce que rend la
    méthode `suffix` quand elle est nommée. Y répondre appelle la méthode
    `action` avec `kwargs`, que `suffix` reçoit aussi. `danger`, `needs`,
    `interfaces` et `glance` se déclarent pour les interfaces à venir :
    le navigateur ne les lit pas."""

    key: str
    action: str
    kwargs: dict | None = None
    suffix: str | None = None
    danger: bool | None = None
    needs: list | None = None
    interfaces: list | None = None
    glance: bool = False


@dataclass(frozen=True)
class FromConfig:
    """Une entrée par élément de la liste `config_key` de todo.json et de
    ses surcharges privées, relue à chaque rendu du menu : l'élément porte
    son libellé, et y répondre appelle la méthode `action` avec
    `{kwarg: élément}`."""

    config_key: str
    action: str
    kwarg: str


@dataclass(frozen=True)
class Menu:
    """Un menu. `name` : la méthode de TODO qui l'ouvre ; `crumb` : son
    segment du fil d'Ariane, sa valeur dans `_MENU_LABELS` et la clé de
    télémétrie. `entries` : des `Section`, `Entry` et `FromConfig`, dans
    l'ordre affiché. `state` nomme la méthode qui rend la ligne d'état
    sous le fil d'Ariane ; `intro`, celle qui s'affiche une fois, à
    l'entrée. [0] rend `back`. `render` : "each" redessine le menu à
    chaque tour, "once" le dessine une fois, avant de poser la question.
    """

    name: str
    crumb: str
    entries: list
    state: str | None = None
    intro: str | None = None
    back: object = False
    render: str = "each"

    def __post_init__(self):
        if self.render not in RENDERS:
            raise ValueError(f"render is one of {RENDERS}: {self.render!r}")
