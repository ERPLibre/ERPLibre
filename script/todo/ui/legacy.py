#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Capture héritée : chaque question que TODO pose par `input`,
`click.prompt`, `click.confirm`, `getpass` ou `auto_ask.ask` passe par le
port lié, sans qu'un seul site d'appel change.

`install(port)` se pose SEULEMENT dans le worker d'une session web et dans
le mode enregistrement, APRÈS `import urwid` (il lie sys.stdout en
argument par défaut à son import) et AVANT tout import de TODO : les
`ask=input` liés à l'import (transform_setup, textual_setup, vault) lient
alors le crochet. Le CLI ne la pose jamais.

Ce que devient chaque question, dans cet ordre :
- `getpass`, `click.prompt(hide_input=True)` : un secret ;
- le texte d'un menu de `fill_help_info` (`MenuText`, voir `wrap_menus`) :
  ce menu, entrée pour entrée ;
- « Type … to confirm », « Tapez … pour confirmer » : une confirmation
  tapée, jamais un bouton ;
- `click.confirm`, une dernière ligne qui porte [y/N], (o/N), (Y/n),
  (O/n) : une confirmation, avec le défaut qu'elle dit ;
- un écran à crochets (`[N] libellé`, sous un fil d'Ariane `📍 A › B` et
  des sections `── X ──`) : un menu ; un écran qui numérote aussi
  autrement (`1.`, `1)`, `1 -`) reste du texte ;
- tout le reste : une question texte, avec son défaut.
`auto_ask.ask` en mode auto devient un compte à rebours.

click garde sa boucle : les enveloppes de `click.prompt` et
`click.confirm` notent le défaut, `hide_input` et le menu, puis appellent
l'original, dont les crochets `visible_prompt_func` et
`hidden_prompt_func` posent la question ; une valeur que click refuse
redemande. Le port rend "" pour Entrée : `input` le rend tel quel, click
et auto_ask y mettent leur défaut. Annuler lève EOFError, que click change
en Abort, comme Ctrl+D.

`sys.stdout` passe par un `Tee`, qui garde au plus TEE_LIMIT caractères
imprimés depuis la fin de la question précédente : l'écran que lit la
suivante.
"""

import builtins
import contextvars
import getpass
import inspect
import re
import sys

from script.todo import ui
from script.todo.todo_i18n import t
from script.todo.ui import port

TEE_LIMIT = 64 * 1024
# Réponses de l'invite, oui d'abord : y/N, o/N, Y/n, O/n, Y/N, y/o/N, y/Y.
CONFIRM = re.compile(r"[\[(]((?:[yo]/)+[yno])[\])]", re.IGNORECASE)
TYPED = re.compile(
    r"\b(?:re)?(?:type|tape[sz]?)\b.*\b(?:to confirm|pour confirmer)\b",
    re.IGNORECASE,
)
# Écrans faits à la main : fil d'Ariane, section, entrée.
CRUMB = re.compile(r"^\s*📍\s*(.+?)\s*$")
SECTION = re.compile(r"^\s*──\s*(.+?)\s*──\s*$")
# `[N] libellé` ; le « : » d'une invite collée à la dernière entrée n'en
# fait pas partie.
ENTRY = re.compile(r"^\s*\[(\d{1,3}|[A-Za-z])\]\s+(\S.*?)\s*:?\s*$")
# Une numérotation qui n'est pas entre crochets : « 1. », « 1) », « 1 - ».
OTHER_NUMBERING = re.compile(r"^\s*\d{1,3}(?:[.)]|\s+[-–])\s+\S")

_NOTE = contextvars.ContextVar("todo_legacy_note", default=None)
_saved = {}
_tee = None


class Tee:
    """Écrit tout dans `inner`, le terminal, et garde au plus TEE_LIMIT
    caractères écrits depuis `clear`. Le reste (`fileno`, `isatty`,
    `encoding`, `flush`…) est celui de `inner`."""

    def __init__(self, inner):
        self.inner = inner
        self.parts = []
        self.size = 0

    def write(self, text):
        written = self.inner.write(text)
        self.parts.append(text)
        self.size += len(text)
        if self.size > 2 * TEE_LIMIT:
            self.parts = ["".join(self.parts)[-TEE_LIMIT:]]
            self.size = len(self.parts[0])
        return written

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def since(self) -> str:
        return "".join(self.parts)[-TEE_LIMIT:]

    def clear(self):
        self.parts, self.size = [], 0

    def __getattr__(self, name):
        return getattr(self.inner, name)


def confirm_default(line):
    """Ce que vaut Entrée à une invite qui porte ses réponses, « y » ou
    « n » ; None si les deux sont en majuscules. Sans « n » (y/Y, o/O),
    seul oui est oui : Entrée vaut « n ». Ce défaut ne fait que redire
    l'invite, pour la page : Entrée rend "", auquel l'appelant donne son
    propre défaut, qui peut contredire les lettres."""
    letters = CONFIRM.search(line)[1].split("/")
    yes, no = letters[0], letters[-1]
    if no.lower() != "n":
        return "n"
    if yes.isupper() and no.islower():
        return "y"
    if no.isupper() and yes.islower():
        return "n"
    return None


def _last_line(text) -> str:
    return next(
        (line for line in reversed(text.splitlines()) if line.strip()), ""
    )


class MenuText(str):
    """Le texte exact d'un menu de `fill_help_info`, qui porte ce menu :
    `menu`, un dict `items`, `crumbs`, `sections` (voir
    `port.menu_view`)."""

    menu = None


def read_screen(text):
    """Le menu d'un écran à crochets, depuis son dernier fil d'Ariane :
    un dict `items` (clé, libellé, section), `crumbs`, `sections` ; None
    sans entrée `[N]`, ou si une ligne numérote autrement."""
    lines = text.splitlines()
    starts = [n for n, line in enumerate(lines) if CRUMB.match(line)]
    crumbs, sections, items, section = [], [], [], None
    for line in lines[starts[-1] if starts else 0 :]:
        if OTHER_NUMBERING.match(line):
            return None
        if match := CRUMB.match(line):
            crumbs = [crumb.strip() for crumb in match[1].split("›")]
        elif match := SECTION.match(line):
            section = match[1]
            sections.append(section)
        elif match := ENTRY.match(line):
            items.append(
                {"key": match[1], "label": match[2], "section": section}
            )
    if not items:
        return None
    return {"items": items, "crumbs": crumbs, "sections": sections}


def wrap_menus(todo_class) -> None:
    """Fait rendre à `todo_class.fill_help_info` un MenuText : le même
    texte, octet pour octet, qui porte ses entrées exactes. Posée avant
    que TODO() soit construit, elle couvre aussi la copie liée que garde
    DatabaseManager."""
    original = todo_class.fill_help_info

    def fill_help_info(self, choices, *args, **kwargs):
        text = MenuText(original(self, choices, *args, **kwargs))
        text.menu = _menu_of(text, choices)
        return text

    todo_class.fill_help_info = fill_help_info


def _menu_of(text, choices) -> dict:
    """Entrées de `choices` comme `fill_help_info` les numérote (une
    section ne prend pas de numéro), puis `[0]`, la dernière ligne."""
    items, sections, section, number = [], [], None, 0
    for choice in choices:
        if choice.get("section"):
            section = choice["section"]
            sections.append(section)
            continue
        number += 1
        key = choice.get("prompt_description_key")
        label = t(key) if key else choice["prompt_description"]
        items.append({"key": str(number), "label": label, "section": section})
    back = ENTRY.match(_last_line(text))
    items.append(
        {"key": "0", "label": back[2] if back else "0", "section": None}
    )
    crumb = CRUMB.match(text.split("\n", 1)[0])
    crumbs = [c.strip() for c in crumb[1].split("›")] if crumb else []
    return {"items": items, "crumbs": crumbs, "sections": sections}


def _question(prompt, note=None) -> str:
    """Pose `prompt` au port lié, selon ce qu'il est (voir le module), et
    rend la ligne répondue. L'écran lu est ce que le Tee a gardé, suivi de
    `prompt` ; il est oublié une fois la question finie, réponse comprise."""
    note = note or {}
    target = ui.current()
    text = str(prompt)
    screen = (_tee.since() if _tee is not None else "") + text
    default = note.get("default")
    try:
        if note.get("hide"):
            return target.ask(text, kind="secret")
        menu = note.get("menu") or getattr(prompt, "menu", None)
        if menu is not None:
            view = port.menu_view(text, source="fill_help_info", **menu)
            return target.menu(view)
        line = _last_line(screen)
        if TYPED.search(line):
            return target.ask(text, default, "typed")
        if note.get("confirm") or CONFIRM.search(line):
            if default is None and not note.get("confirm"):
                default = confirm_default(line)
            return target.ask(text, default, "confirm")
        read = read_screen(screen)
        if read is not None:
            return target.menu(port.menu_view(text, **read))
        return target.ask(text, default, "text")
    finally:
        if _tee is not None:
            _tee.clear()


def _input(prompt=""):
    return _question(prompt)


def _getpass(prompt="Password: ", stream=None, *, echo_char=None):
    return _question(prompt, {"hide": True})


def _visible_prompt(prompt):
    return _question(prompt, _NOTE.get())


def _hidden_prompt(prompt):
    return _question(prompt, {**(_NOTE.get() or {}), "hide": True})


def _click_prompt(text, *args, **kwargs):
    """`click.prompt` d'origine, qui pose ses questions par les crochets
    de click ; le défaut, `hide_input` et le menu de `text` sont notés
    pour eux."""
    original = _saved["prompt"]
    bound = inspect.signature(original).bind(text, *args, **kwargs)
    default = bound.arguments.get("default")
    note = {
        "default": None if default is None else str(default),
        "hide": bool(bound.arguments.get("hide_input")),
        "menu": getattr(text, "menu", None),
    }
    token = _NOTE.set(note)
    try:
        return original(text, *args, **kwargs)
    finally:
        _NOTE.reset(token)


def _click_confirm(text, default=False, *args, **kwargs):
    """`click.confirm` d'origine ; sa question est une confirmation, dont
    Entrée vaut `default`."""
    answer = {True: "y", False: "n"}.get(default)
    token = _NOTE.set({"confirm": True, "default": answer})
    try:
        return _saved["confirm"](text, default, *args, **kwargs)
    finally:
        _NOTE.reset(token)


def _auto_ask(prompt, default="", seconds=None):
    """`auto_ask.ask` : en mode auto, un compte à rebours qui rend
    `default` à l'échéance ; sinon la question qu'est son texte. Une
    réponse vide vaut `default`, comme à l'origine."""
    from script.todo import auto_ask

    if not auto_ask.enabled():
        return _question(prompt, {"default": default or None}) or default
    timeout = auto_ask.delay() if seconds is None else seconds
    try:
        answer = ui.current().ask(str(prompt), default, "countdown", timeout)
    finally:
        if _tee is not None:
            _tee.clear()
    return answer or default


def install(target):
    """Pose la capture et lie `target` au contexte courant ; rend la
    fonction qui défait tout, liens et Tee compris."""
    global _tee
    import click
    import click.termui

    from script.todo import auto_ask

    if _saved:
        raise RuntimeError("the legacy capture is already installed")
    port.ORIGINAL.setdefault("auto_ask.ask", auto_ask.ask)
    hooks = [
        (builtins, "input", _input),
        (getpass, "getpass", _getpass),
        (click, "prompt", _click_prompt),
        (click, "confirm", _click_confirm),
        (click.termui, "visible_prompt_func", _visible_prompt),
        (click.termui, "hidden_prompt_func", _hidden_prompt),
        (auto_ask, "ask", _auto_ask),
    ]
    for owner, name, hook in hooks:
        _saved[name] = getattr(owner, name)
        setattr(owner, name, hook)
    _tee = Tee(sys.stdout)
    sys.stdout = _tee
    token = ui.attach(target)

    def uninstall():
        global _tee
        ui.detach(token)
        sys.stdout = _tee.inner
        _tee = None
        for owner, name, _ in hooks:
            setattr(owner, name, _saved.pop(name))

    return uninstall
