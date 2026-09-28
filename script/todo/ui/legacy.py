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
`auto_ask.ask` en mode auto devient un compte à rebours, et le navigateur
de fichiers urwid (`FileBrowser.run_main_frame`) le choix d'un chemin
(`pick_path`), dont le rappel du navigateur reçoit la réponse.

click garde sa boucle : les enveloppes de `click.prompt` et
`click.confirm` notent le défaut, `hide_input` et le menu, puis appellent
l'original, dont les crochets `visible_prompt_func` et
`hidden_prompt_func` posent la question ; une valeur que click refuse
redemande. Le port rend "" pour Entrée : `input` le rend tel quel, click
et auto_ask y mettent leur défaut. Annuler lève EOFError, que click change
en Abort, comme Ctrl+D.

`sys.stdout` passe par un `Tee`, qui rend au plus les TEE_LIMIT derniers
caractères imprimés depuis la fin de la question précédente, dont la
transcription de sa réponse fait partie : l'écran que lit la suivante. Un
menu dit si ces caractères portent autre chose que des blancs avant son
propre texte (`printed`) : ce qu'une feuille imprime avant de rendre la
main à son menu, et que ses boutons ne montrent pas. Il porte aussi les
lignes de son texte que ses entrées ne disent pas (`notes`), une ligne
d'état par exemple.
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
# Entre les entrées d'un menu écrit à la main et son invite : au plus
# NOTE_LINES notes, au retrait exact des entrées, et BLANK_LINES ligne vide.
NOTE_LINES = 2
BLANK_LINES = 1

_NOTE = contextvars.ContextVar("todo_legacy_note", default=None)
_saved = {}
_tee = None


class Tee:
    """Écrit tout dans `inner`, le terminal, et garde les caractères écrits
    depuis `clear` : `since` en rend TEE_LIMIT au plus, les derniers, et la
    mémoire gardée reste sous 2 × TEE_LIMIT environ. Le reste (`fileno`,
    `isatty`, `encoding`, `flush`…) est celui de `inner`."""

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
    """Ce que vaut Entrée à une invite qui porte ses réponses : « y » ou
    « n », la réponse dont la lettre est en majuscule ; None quand les
    deux ont la même casse, (Y/N) comme (y/n). Sans « n » (y/Y, o/O),
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
    sans entrée `[N]`, ou si une ligne numérote autrement. Sans fil
    d'Ariane, les entrées ne viennent que du bloc qui finit à l'invite,
    notes d'un menu écrit à la main comprises (`_prompt_block`) : une
    ligne à crochets d'une sortie antérieure, « [1] 48213 », n'en devient
    pas une."""
    return _read_screen(text.splitlines())[1]


def _read_screen(lines) -> tuple:
    """(début, menu) : le menu de `lines` que rend `read_screen`, ou None,
    et l'indice de sa première ligne, son dernier fil d'Ariane ou la
    première du bloc qui finit à l'invite."""
    starts = [n for n, line in enumerate(lines) if CRUMB.match(line)]
    start, stop = (starts[-1] if starts else 0), len(lines)
    if any(OTHER_NUMBERING.match(line) for line in lines[start:]):
        return start, None
    if not starts:
        start, stop = _prompt_block(lines)
    crumbs, sections, items, section = [], [], [], None
    for line in lines[start:stop]:
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
        return start, None
    return start, {"items": items, "crumbs": crumbs, "sections": sections}


def _prompt_block(lines) -> tuple:
    """Les bornes (début, fin) des lignes d'entrée ou de section qui
    finissent à l'invite, la dernière ligne : celle-ci si elle porte une
    entrée (« [0] Retour : »), et celles qui la précèdent, jusqu'à la
    première ligne vide ou d'un autre genre. Entre les entrées et l'invite
    peuvent venir les notes d'un menu écrit à la main (« ⚠ … », une ligne
    vide : `_notes`) ; des lignes qui en tiennent la place sans en être
    rendent un bloc vide : une sortie en retrait, trace d'appel ou journal,
    ne fait pas un menu des crochets qui la précèdent."""
    end = len(lines)
    if lines and not ENTRY.match(lines[-1]):
        end -= 1  # l'invite seule sur sa ligne
    gap = end
    while gap and _note(lines[gap - 1]):
        gap -= 1
    entry = lines[gap - 1] if gap else ""
    if gap < end and not _notes(entry, lines[gap:end]):
        return gap, gap
    start = gap
    while start and (
        ENTRY.match(lines[start - 1]) or SECTION.match(lines[start - 1])
    ):
        start -= 1
    return start, gap


def _note(line) -> bool:
    """Vrai pour une ligne vide, ou en retrait, qui n'est ni une entrée ni
    une section."""
    if ENTRY.match(line) or SECTION.match(line):
        return False
    return not line.strip() or line[:1].isspace()


def _notes(entry, gap) -> bool:
    """Vrai quand `gap`, les lignes entre la dernière entrée `entry` et
    l'invite, sont les notes d'un menu écrit à la main : `entry` est en
    retrait, et `gap` compte au plus NOTE_LINES notes, chacune au retrait
    exact de `entry`, et BLANK_LINES ligne vide."""
    indent = _indent(entry)
    notes = [line for line in gap if line.strip()]
    return (
        bool(indent and ENTRY.match(entry))
        and len(notes) <= NOTE_LINES
        and len(gap) - len(notes) <= BLANK_LINES
        and all(_indent(line) == indent for line in notes)
    )


def _indent(line) -> str:
    """Les blancs qui ouvrent `line`."""
    return line[: len(line) - len(line.lstrip())]


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


def _screen_notes(text, items=()) -> list:
    """Les lignes de `text`, le texte d'un menu, que ses entrées ne disent
    pas, sans leurs blancs : une ligne d'état, une note. Ni fil d'Ariane,
    ni section, ni entrée, ni la suite d'un libellé de `items` écrit sur
    plusieurs lignes, que le bouton de l'entrée montre déjà, ni la ligne
    « Command: » de l'en-tête de TODO, dans la langue de la session, ni une
    ligne sans mot, comme l'invite « : »."""
    header = t("Command:")
    rest = {
        line.strip()
        for item in items
        for line in str(item["label"]).splitlines()[1:]
    }
    return [
        line.strip()
        for line in text.splitlines()
        if re.search(r"\w", line)
        and line.strip() not in (header, *rest)
        and not (CRUMB.match(line) or SECTION.match(line) or ENTRY.match(line))
    ]


def _printed(before, screen, start) -> bool:
    """Vrai quand `before`, le début de `screen`, porte autre chose que des
    blancs avant la ligne `start` de `screen`, la première du menu."""
    offset = sum(len(line) for line in screen.splitlines(True)[:start])
    return bool(before[:offset].strip())


def _question(prompt, note=None) -> str:
    """Pose `prompt` au port lié, selon ce qu'il est (voir le module), et
    rend la ligne répondue. L'écran lu est ce que le Tee a gardé, suivi de
    `prompt` ; il est oublié une fois la question finie, réponse comprise."""
    note = note or {}
    target = ui.current()
    text = str(prompt)
    before = _tee.since() if _tee is not None else ""
    screen = before + text
    default = note.get("default")
    try:
        if note.get("hide"):
            return target.ask(text, kind="secret")
        menu = note.get("menu") or getattr(prompt, "menu", None)
        if menu is not None:
            view = port.menu_view(
                text,
                source="fill_help_info",
                printed=bool(before.strip()),
                notes=_screen_notes(text, menu["items"]),
                **menu,
            )
            return target.menu(view)
        line = _last_line(screen)
        if TYPED.search(line):
            return target.ask(text, default, "typed")
        if note.get("confirm") or CONFIRM.search(line):
            if default is None and not note.get("confirm"):
                default = confirm_default(line)
            return target.ask(text, default, "confirm")
        start, read = _read_screen(screen.splitlines())
        if read is not None:
            printed = _printed(before, screen, start)
            notes = _screen_notes(text, read["items"])
            view = port.menu_view(text, printed=printed, notes=notes, **read)
            return target.menu(view)
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


def _run_main_frame(browser):
    """`FileBrowser.run_main_frame` sous la capture : le port lié fait
    choisir un chemin (`pick_path`) à partir du répertoire que montre
    `browser`, un répertoire s'il en cherche un (`open_dir`). Le chemin
    choisi va au rappel de `browser`, comme le bouton d'urwid le lui
    donne ; renoncer ne l'appelle pas, comme `q`. Un rappel qui ferme
    l'écran d'urwid (`exit_program`) n'a plus de boucle à fermer : son
    ExitMainLoop s'arrête ici. L'écran que lit la question suivante
    repart vide."""
    import urwid

    try:
        path = ui.pick_path(browser.current_path, browser.open_dir)
    finally:
        if _tee is not None:
            _tee.clear()
    if path is not None:
        try:
            browser.callback(path)
        except urwid.ExitMainLoop:
            pass


def install(target):
    """Pose la capture et lie `target` au contexte courant ; rend la
    fonction qui défait tout, liens et Tee compris, et qui ne fait plus
    rien une fois la capture défaite.

    Le navigateur de fichiers (`script.todo.todo_file_browser`) s'importe
    ici, avant le Tee, et avec lui urwid s'il ne l'est pas encore. Sans
    urwid, il n'y a pas de navigateur à capturer. todo.py l'importe aussi
    sous son nom court, en mode script : ce nom désigne alors le même
    module, dont le navigateur est capturé."""
    global _tee
    import click
    import click.termui

    from script.todo import auto_ask

    if _saved:
        raise RuntimeError("the legacy capture is already installed")
    try:
        from script.todo import todo_file_browser
    except ImportError:
        todo_file_browser = None
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
    alias = None
    if todo_file_browser is not None:
        browser = todo_file_browser.FileBrowser
        port.ORIGINAL.setdefault(
            "FileBrowser.run_main_frame", browser.run_main_frame
        )
        hooks.append((browser, "run_main_frame", _run_main_frame))
        if "todo_file_browser" not in sys.modules:
            alias = sys.modules["todo_file_browser"] = todo_file_browser
    for owner, name, hook in hooks:
        _saved[name] = getattr(owner, name)
        setattr(owner, name, hook)
    tee = _tee = Tee(sys.stdout)
    sys.stdout = _tee
    token = ui.attach(target)

    def uninstall():
        global _tee
        if _tee is not tee:
            return  # déjà défaite, peut-être sous une capture plus récente
        ui.detach(token)
        sys.stdout = _tee.inner
        _tee = None
        for owner, name, _ in hooks:
            setattr(owner, name, _saved.pop(name))
        if alias is not None and sys.modules.get("todo_file_browser") is alias:
            del sys.modules["todo_file_browser"]

    return uninstall
