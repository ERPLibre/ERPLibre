#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Navigateur : une seule boucle pour les menus du registre.

`navigate(todo, menu)` dessine `menu` par `todo.fill_help_info`, qui
écrit le texte et l'en-tête des menus écrits à la main (et rend, dans une
session web, le `MenuText` que pose `legacy.wrap_menus`), puis pose la
question par `click.prompt` : même suffixe « : », même question reposée
sur une réponse vide, même `Abort` sur Ctrl+C ou Ctrl+D. `click.prompt`
se lit à chaque question : la capture d'une session web, qui remplace cet
attribut, y répond.

Le cadre de `navigate` ne porte pas de `self` : le fil d'Ariane, que
`_menu_header` lit dans la pile, reste celui des méthodes de TODO qui
l'appellent, et la clé de télémétrie aussi.
"""

import click

from script.todo.todo_i18n import t
from script.todo.ui.registry import FromConfig, Section


def _draw(todo, menu) -> tuple:
    """(texte, actions) de `menu` tel qu'il s'affiche maintenant : le
    texte de `todo.fill_help_info`, et le (méthode, kwargs) de chaque
    entrée numérotée, dans l'ordre. Les gardes et les suffixes, puis la
    ligne d'état, sont demandés à `todo` avant l'en-tête ; une entrée
    dont la garde rend faux n'est ni montrée ni comptée."""
    choices, actions = [], []
    for item in menu.entries:
        if isinstance(item, Section):
            choices.append({"section": t(item.key)})
        elif isinstance(item, FromConfig):
            for element in todo.config_file.get_config(item.config_key) or []:
                choices.append(element)
                actions.append((item.action, {item.kwarg: element}))
        elif not item.when or getattr(todo, item.when)():
            kwargs = dict(item.kwargs or {})
            label = t(item.key)
            if item.suffix:
                label += f"  ({getattr(todo, item.suffix)(**kwargs)})"
            choices.append({"prompt_description": label})
            actions.append((item.action, kwargs))
    state = getattr(todo, menu.state)() if menu.state else None
    return todo.fill_help_info(choices, state=state), actions


def navigate(todo, menu):
    """Affiche `menu` pour `todo` et répond à ses entrées ; rend
    `menu.back` sur « 0 ». « N » appelle la méthode de la N-ième entrée
    numérotée avec ses kwargs, puis le menu reprend, ou rend `menu.back`
    s'il se referme (`closes`) ; toute autre réponse dit « Command not
    found ! ». L'intro s'affiche une fois, à l'entrée.
    Un menu `render="each"` se redessine après chaque réponse, sa
    configuration relue ; un menu "once" garde son premier dessin."""
    if menu.intro:
        getattr(todo, menu.intro)()
    text, actions = _draw(todo, menu)
    while True:
        status = click.prompt(text)
        print()
        if status == "0":
            return menu.back
        numbers = [str(n) for n in range(1, len(actions) + 1)]
        if status in numbers:
            method, kwargs = actions[int(status) - 1]
            getattr(todo, method)(**kwargs)
            if menu.closes:
                return menu.back
        else:
            print(t("Command not found !"))
        if menu.render == "each":
            text, actions = _draw(todo, menu)
