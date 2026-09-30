#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Navigateur : une seule boucle pour les menus du registre.

`navigate(todo, menu)` dessine `menu` par `todo.fill_help_info`, qui
écrit le texte et l'en-tête des menus écrits à la main (et rend, dans une
session web, le `MenuText` que pose `legacy.wrap_menus`), puis pose la
question par `click.prompt` : même suffixe « : », même question reposée
sur une réponse vide, même `Abort` sur Ctrl+C ou Ctrl+D, que seuls un menu
`abort_closes` et un menu `quits` rattrapent. `click.prompt` se lit à
chaque question : la capture d'une session web, qui remplace cet
attribut, y répond. Un menu `asks` écrit et pose sa question par sa
propre méthode, sans `fill_help_info` ni `click.prompt`, donc sans fil
d'Ariane ni clé de télémétrie.

`todo` est l'objet qui ouvre le menu : TODO, ou un objet de TODO dont
le `fill_help_info` est celui de TODO (`DatabaseManager`). Le cadre de
`navigate` ne porte pas de `self` : le fil d'Ariane, que `_menu_header`
lit dans la pile, reste celui des méthodes de TODO qui l'appellent, et
la clé de télémétrie aussi.
"""

import sys

import click

from script.todo.todo_i18n import t
from script.todo.ui.registry import FromConfig, FromMethod, Section


def _draw(todo, menu) -> tuple:
    """(dessin, actions) de `menu` tel qu'il s'affiche maintenant :
    `actions` donne le (méthode, kwargs) de chaque entrée montrée par sa
    touche, son `hotkey` ou son numéro parmi les entrées numérotées ; le
    dessin est le texte de `todo.fill_help_info`, ou, pour un menu
    `asks`, la liste des entrées montrées, {"key", "label"} chacune, dans
    l'ordre. Les gardes et les suffixes, puis la ligne d'état, sont
    demandés à `todo` avant l'en-tête ; une entrée dont la garde rend faux
    n'est ni montrée ni comptée, et un élément de configuration, ou de la
    liste que rend la méthode d'un `FromMethod`, qui porte une section,
    montrée, n'est pas compté."""
    choices, shown, actions, number = [], [], {}, 0
    for item in menu.entries:
        rows = []
        if isinstance(item, Section):
            choices.append({"section": t(item.key)})
        elif isinstance(item, (FromConfig, FromMethod)):
            if isinstance(item, FromConfig):
                elements = todo.config_file.get_config(item.config_key)
            else:
                elements = getattr(todo, item.method)()
            for element in elements or []:
                kwargs = {item.kwarg: element}
                rows.append((element, item.action, kwargs, None))
        elif not item.when or getattr(todo, item.when)():
            kwargs = dict(item.kwargs or {})
            label = t(item.key)
            if item.suffix:
                label += f"  ({getattr(todo, item.suffix)(**kwargs)})"
            choice = {"prompt_description": label}
            rows.append((choice, item.action, kwargs, item.hotkey))
        for choice, action, kwargs, hotkey in rows:
            choices.append(choice)
            if choice.get("section"):
                continue
            if not hotkey:
                number += 1
            key = hotkey or str(number)
            label = choice.get("prompt_description_key")
            label = t(label) if label else choice["prompt_description"]
            shown.append({"key": key, "label": label})
            actions[key] = (action, kwargs)
    if menu.asks:
        return shown, actions
    state = getattr(todo, menu.state)() if menu.state else None
    if menu.quits:
        return todo.fill_help_info(choices, state=state, quits=True), actions
    return todo.fill_help_info(choices, state=state), actions


def navigate(todo, menu):
    """Affiche `menu` pour `todo` et répond à ses entrées ; rend
    `menu.back` sur « 0 ». « N » appelle la méthode de la N-ième entrée
    numérotée avec ses kwargs, la touche d'une entrée (`hotkey`) la
    sienne, puis le menu reprend, ou rend `menu.back` s'il se referme
    (`closes`), ou ce que l'action a rendu de vrai (`closes_on_result`) ;
    toute autre réponse dit « Command not found ! ». L'intro,
    `t(menu.intro)` derrière `menu.mark`, s'affiche une fois, à l'entrée ;
    la méthode `menu.opens` s'appelle ensuite, une fois : un dict ouvre le
    menu et s'ajoute aux kwargs de chaque action, toute autre valeur est
    rendue sans que le menu se dessine. La méthode `menu.before` s'appelle
    avant chaque question. La méthode `menu.asks`, quand elle est nommée,
    pose la question : elle reçoit les entrées montrées et rend la
    réponse, sans ligne vide après elle, et ce qu'elle lève remonte.
    Un menu `render="each"` se redessine après chaque réponse, sa
    configuration relue ; un menu "once" garde son premier dessin. Ctrl+C
    ou Ctrl+D à la question remontent, sauf dans un menu `abort_closes`,
    qui rend alors `back` après une ligne vide, et dans un menu `quits`,
    qui termine TODO (SystemExit 0) ; ce qu'une action lève remonte
    toujours."""
    if menu.intro:
        print(f"{menu.mark} {t(menu.intro)}")
    context = {}
    if menu.opens:
        context = getattr(todo, menu.opens)()
        if not isinstance(context, dict):
            return context
    drawn, actions = _draw(todo, menu)
    while True:
        if menu.before:
            getattr(todo, menu.before)()
        if menu.asks:
            status = getattr(todo, menu.asks)(drawn)
        else:
            try:
                status = click.prompt(drawn)
            except (KeyboardInterrupt, click.exceptions.Abort):
                if menu.quits:
                    sys.exit(0)
                if not menu.abort_closes:
                    raise
                print()
                return menu.back
            print()
        if status == "0":
            return menu.back
        if status in actions:
            method, kwargs = actions[status]
            result = getattr(todo, method)(**kwargs, **context)
            if menu.closes:
                return menu.back
            if menu.closes_on_result and result:
                return result
        else:
            print(t("Command not found !"))
        if menu.render == "each":
            drawn, actions = _draw(todo, menu)
