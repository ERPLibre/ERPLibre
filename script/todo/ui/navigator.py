#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Navigateur : une seule boucle pour les menus du registre.

`navigate(todo, menu)` dessine `menu` par `todo.fill_help_info`, qui
écrit le texte et l'en-tête des menus écrits à la main (et rend, dans une
session web, le `MenuText` que pose `legacy.wrap_menus`), puis pose la
question par `click.prompt` : même suffixe « : », même question reposée
sur une réponse vide, même `Abort` sur Ctrl+C ou Ctrl+D, que seul un menu
`abort_closes` rattrape. `click.prompt` se lit à chaque question : la
capture d'une session web, qui remplace cet attribut, y répond.

`todo` est l'objet qui ouvre le menu : TODO, ou un objet de TODO dont
le `fill_help_info` est celui de TODO (`DatabaseManager`). Le cadre de
`navigate` ne porte pas de `self` : le fil d'Ariane, que `_menu_header`
lit dans la pile, reste celui des méthodes de TODO qui l'appellent, et
la clé de télémétrie aussi.
"""

import click

from script.todo.todo_i18n import t
from script.todo.ui.registry import FromConfig, FromMethod, Section


def _draw(todo, menu) -> tuple:
    """(texte, actions) de `menu` tel qu'il s'affiche maintenant : le
    texte de `todo.fill_help_info`, et le (méthode, kwargs) de chaque
    entrée numérotée, dans l'ordre. Les gardes et les suffixes, puis la
    ligne d'état, sont demandés à `todo` avant l'en-tête ; une entrée
    dont la garde rend faux n'est ni montrée ni comptée, et un élément de
    configuration, ou de la liste que rend la méthode d'un `FromMethod`,
    qui porte une section, montrée, n'est pas compté."""
    choices, actions = [], []
    for item in menu.entries:
        if isinstance(item, Section):
            choices.append({"section": t(item.key)})
        elif isinstance(item, (FromConfig, FromMethod)):
            if isinstance(item, FromConfig):
                elements = todo.config_file.get_config(item.config_key)
            else:
                elements = getattr(todo, item.method)()
            for element in elements or []:
                choices.append(element)
                if not element.get("section"):
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
    s'il se referme (`closes`), ou ce que l'action a rendu de vrai
    (`closes_on_result`) ; toute autre réponse dit « Command not
    found ! ». L'intro, `t(menu.intro)` derrière `menu.mark`, s'affiche
    une fois, à l'entrée ; la méthode `menu.opens` s'appelle ensuite, une
    fois : un dict ouvre le menu et s'ajoute aux kwargs de chaque action,
    toute autre valeur est rendue sans que le menu se dessine. La méthode
    `menu.before` s'appelle avant chaque question.
    Un menu `render="each"` se redessine après chaque réponse, sa
    configuration relue ; un menu "once" garde son premier dessin. Ctrl+C
    ou Ctrl+D à la question remontent, sauf dans un menu `abort_closes`,
    qui rend alors `back` après une ligne vide ; ce qu'une action lève
    remonte toujours."""
    if menu.intro:
        print(f"{menu.mark} {t(menu.intro)}")
    context = {}
    if menu.opens:
        context = getattr(todo, menu.opens)()
        if not isinstance(context, dict):
            return context
    text, actions = _draw(todo, menu)
    while True:
        if menu.before:
            getattr(todo, menu.before)()
        try:
            status = click.prompt(text)
        except (KeyboardInterrupt, click.exceptions.Abort):
            if not menu.abort_closes:
                raise
            print()
            return menu.back
        print()
        if status == "0":
            return menu.back
        numbers = [str(n) for n in range(1, len(actions) + 1)]
        if status in numbers:
            method, kwargs = actions[int(status) - 1]
            result = getattr(todo, method)(**kwargs, **context)
            if menu.closes:
                return menu.back
            if menu.closes_on_result and result:
                return result
        else:
            print(t("Command not found !"))
        if menu.render == "each":
            text, actions = _draw(todo, menu)
