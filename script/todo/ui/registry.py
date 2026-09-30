#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Registre des menus de TODO : chaque menu déclaré comme une donnée.

Un fichier de menus, `script/todo/menus/<famille>.py`, n'écrit que des
appels de ces constructeurs, aux arguments littéraux :
`navigator.navigate` affiche un menu et répond à ses entrées,
`todo_telemetry.build_code_tree` le lit par AST, sans rien importer. Ce
module n'importe ni TODO ni une bibliothèque d'interface.

`key` (d'une `Entry` ou d'une `Section`) et `intro` (d'un `Menu`) sont
des clés de traduction anglaises, que `t()` traduit au rendu. `action`,
`state`, `suffix`, `when`, `opens`, `before`, `asks` et `method` sont
des NOMS de méthodes de l'objet qui ouvre le menu, TODO ou un objet de
TODO, jamais des fonctions. Le numéro d'une entrée est sa place parmi
les entrées numérotées montrées : une `Section` n'en prend pas, un
`FromConfig` ou un `FromMethod` en prend un par élément de sa liste qui
n'est pas une section, une `Entry` dont la garde `when` rend faux aucun,
ni une `Entry` qui répond à sa touche (`hotkey`).
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
    `action` avec `kwargs`, que `suffix` reçoit aussi. `when` nomme une
    méthode sans argument, relue à chaque dessin du menu : tant qu'elle
    rend faux, l'entrée n'est pas montrée et les suivantes gardent leur
    numéro sans elle. `danger`, `needs`, `interfaces` et `glance` se
    déclarent ; le navigateur ne les lit pas. De ces quatre, l'arbre de
    télémétrie ne lit que `danger` : le nœud d'une entrée `danger=True`
    porte "danger", et ni la TUI de télémétrie ni la page web ne le
    lancent ; le menu, lui, l'affiche et le lance comme une autre
    entrée. `hotkey`, une lettre, répond à l'entrée à la place d'un
    numéro, dans un menu `asks` seulement. `crumb` est le segment du fil
    d'Ariane de l'écran que l'action dessine elle-même, hors du registre
    (un sélecteur) : le navigateur l'ajoute au fil le temps de l'action,
    et l'arbre de télémétrie en fait un menu sans feuille, sous ce
    segment, que ni la TUI ni la page web ne lancent."""

    key: str
    action: str
    kwargs: dict | None = None
    suffix: str | None = None
    when: str | None = None
    danger: bool | None = None
    needs: list | None = None
    interfaces: list | None = None
    glance: bool = False
    hotkey: str | None = None
    crumb: str | None = None


@dataclass(frozen=True)
class FromConfig:
    """Une entrée par élément de la liste `config_key` de todo.json et de
    ses surcharges privées, relue à chaque rendu du menu : l'élément porte
    son libellé, et y répondre appelle la méthode `action` avec
    `{kwarg: élément}`. Un élément `{"section": …}` est un titre de
    section, qui ne prend pas de numéro."""

    config_key: str
    action: str
    kwarg: str


@dataclass(frozen=True)
class FromMethod:
    """Une entrée par élément de la liste que rend la méthode `method`,
    appelée sans argument à chaque rendu du menu : comme un `FromConfig`,
    l'élément porte son libellé, un élément `{"section": …}` est un titre
    de section, et y répondre appelle la méthode `action` avec
    `{kwarg: élément}`. L'arbre de télémétrie, qui n'appelle rien, n'en
    montre aucune feuille."""

    method: str
    action: str
    kwarg: str


@dataclass(frozen=True)
class Menu:
    """Un menu. `name` : la méthode qui l'ouvre ; `crumb` : son segment
    du fil d'Ariane et de l'arbre de télémétrie, que le navigateur ajoute
    au fil de l'entrée du menu à son retour, et donc le dernier segment de
    sa clé de télémétrie, qui est le fil entier ; ou None pour un menu
    qu'ouvre un autre objet que TODO, qui s'affiche sous le fil du menu
    qui l'ouvre. `entries` : des `Section`,
    `Entry`, `FromConfig` et `FromMethod`, dans l'ordre affiché. `state`
    nomme la méthode qui rend la ligne d'état sous le fil d'Ariane.
    `intro` est la clé de la ligne dite une fois, à l'entrée, derrière
    `mark`. [0] rend `back`. `render` : "each" redessine le menu à chaque
    tour, "once" le dessine une fois, avant de poser la question.
    `closes` : le menu se referme après l'action d'une entrée, et rend
    alors `back`, comme sur [0].
    `abort_closes` : Ctrl+C ou Ctrl+D à sa question referment le menu,
    qui rend `back` après une ligne vide, au lieu de laisser l'`Abort` de
    click remonter jusqu'à terminer TODO.
    `opens` nomme la méthode appelée une fois à l'entrée, après l'intro et
    avant le premier dessin : elle rend un dict pour ouvrir le menu, dont
    les clés s'ajoutent aux kwargs de l'action de chaque entrée, ou toute
    autre valeur, que le menu rend sans se dessiner. Ces clés ne répètent
    jamais un kwarg d'une entrée : le navigateur passe les deux en
    arguments nommés, et une clé répétée lève TypeError quand l'entrée
    est choisie.
    `before` nomme la méthode appelée avant chaque question, que le menu
    se redessine ou non.
    `closes_on_result` : une entrée dont l'action rend une valeur vraie
    referme le menu, qui rend cette valeur ; une valeur fausse laisse la
    question revenir.
    `asks` nomme la méthode qui pose la question du menu à la place de
    `fill_help_info` et de `click.prompt` : elle reçoit les entrées
    montrées, un dict {"key", "label"} chacune, sa touche ou son numéro et
    son libellé, et rend la réponse, « 0 » pour [0] ; le navigateur
    n'écrit alors ni fil d'Ariane ni ligne vide après elle, et un tel menu
    refuse `state` et `abort_closes`, que seule sa question lirait.
    `quits` : réservé au menu racine, qu'ouvre `run`. Son [0] se lit
    « 🚪 Quit » et rend `back` à `run`, dont TODO sort ; un autre menu
    qui le déclarerait rendrait la main à son parent sous ce mot. Ctrl+C
    ou Ctrl+D à sa question terminent TODO (SystemExit 0), sans ligne
    vide. Un tel menu refuse `abort_closes`, qui le refermerait à la
    place, et `asks`.
    """

    name: str
    crumb: str | None
    entries: list
    state: str | None = None
    intro: str | None = None
    mark: str = "🤖"
    back: object = False
    render: str = "each"
    closes: bool = False
    abort_closes: bool = False
    opens: str | None = None
    before: str | None = None
    closes_on_result: bool = False
    asks: str | None = None
    quits: bool = False

    def __post_init__(self):
        if self.render not in RENDERS:
            raise ValueError(f"render is one of {RENDERS}: {self.render!r}")
        # Une touche remplace un numéro : un chiffre en prendrait un autre,
        # et `fill_help_info`, qui numérote chaque entrée, ne la montre pas.
        # C'est une lettre ASCII minuscule, propre à son entrée : une
        # question `asks` rend la réponse en minuscules, et deux entrées
        # d'une même touche se confondraient.
        keys = [getattr(item, "hotkey", None) for item in self.entries]
        keys = [key for key in keys if key]
        if keys and not self.asks:
            raise ValueError(f"hotkey needs asks: {keys!r}")
        if len(set(keys)) != len(keys) or not all(
            len(key) == 1 and key.isascii() and key.islower() for key in keys
        ):
            raise ValueError(f"hotkey is one lowercase letter: {keys!r}")
        if self.asks and (self.state or self.abort_closes):
            raise ValueError("asks takes neither state nor abort_closes")
        if self.quits and (self.abort_closes or self.asks):
            raise ValueError("quits takes neither abort_closes nor asks")
