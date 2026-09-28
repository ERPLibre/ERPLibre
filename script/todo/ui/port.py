#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Port d'interaction de TODO : ce qu'une interface sait faire pour poser
les questions de TODO, et deux ports qui le font.

Un port répond à `menu(view)`, `ask(text, default, kind, timeout)`,
`secret(text)`, `confirm(text, default, typed)`, `choose(text, options,
multi)`, `pick_path(start, directory)`, `notice(text, level)`, `run(cmd,
**opts)` et `open_view(view)`. `menu` et `ask` sont les deux primitives :
elles montrent leur texte tel quel et rendent la ligne répondue, sans son
saut de ligne. Une ligne vide rend "" et laisse le défaut à l'appelant,
comme `input` ; seul le compte à rebours (`kind="countdown"`) rend
`default` à l'échéance. `menu` pose un message déjà fait : un `menu`, ou
l'`ask` que construisent `choose` et `pick_path`. `BasePort` en déduit
les autres questions.

Chaque question est aussi un message `todo.v1` (`question`, `menu_view`) :
`speak`, un libellé court pour la voix ; `requires`, les capacités qu'un
client doit annoncer pour y répondre sans le terminal ; `fallback`,
toujours `pty` : le terminal de la session répond à toute question.

`TerminalPort` appelle les fonctions d'origine, gardées dans ORIGINAL
avant toute capture ; `ScriptedPort` répond depuis une liste et garde ses
événements. Ce module n'importe aucune bibliothèque d'interface à son
chargement : auto_ask, Execute et le navigateur urwid le sont à l'appel.
"""

import builtins
import getpass
import os
import re
import shlex
from string.templatelib import Interpolation, Template

from script.todo.todo_i18n import t

# Capacités sans lesquelles un client ne répond pas à une question de ce
# genre ; `pty`, le terminal, répond à toutes.
REQUIRES = {
    "text": ["free_text"],
    "secret": ["secret"],
    "confirm": [],
    "typed": ["typed"],
    "countdown": [],
    "choose": [],
    "path": ["free_text"],
}
FALLBACK = "pty"
SPEAK_LIMIT = 80
YES = ("y", "yes", "o", "oui")
NO = ("n", "no", "non")
# Décor en tête de ligne (emoji, puces) et ponctuation d'invite en fin.
_SPEAK_HEAD = re.compile(r"^[^\w«\"'(\[]+")
_SPEAK_TAIL = re.compile(r"[\s:]+$")
_CONVERT = {None: lambda value: value, "r": repr, "s": str, "a": ascii}

# Fonctions d'origine, prises avant toute capture : TerminalPort les
# appelle, jamais les crochets qui les remplacent. `legacy.install` y
# ajoute `auto_ask.ask` et `FileBrowser.run_main_frame` avant de les
# remplacer.
ORIGINAL = {"input": builtins.input, "getpass": getpass.getpass}


def speak(text) -> str:
    """La dernière ligne de `text` qui porte un mot, sans décor en tête ni
    ponctuation d'invite en fin, SPEAK_LIMIT caractères au plus."""
    for line in reversed(str(text).splitlines()):
        line = _SPEAK_TAIL.sub("", _SPEAK_HEAD.sub("", line.strip()))
        if re.search(r"\w", line):
            return line[:SPEAK_LIMIT]
    return ""


def question(kind, text, default=None, timeout=None, **fields) -> dict:
    """Message `ask` d'une question de genre `kind` (une clé de REQUIRES) ;
    `timeout_s` pour un compte à rebours ; `fields` s'y ajoutent, ou
    remplacent `speak`. Une confirmation se répond par `y` ou `n`, que
    `_is_yes` et `_is_no` de TODO lisent déjà."""
    message = {
        "t": "ask",
        "kind": kind,
        "text": text,
        "default": default,
        "speak": speak(text),
        "requires": list(REQUIRES[kind]),
        "fallback": FALLBACK,
    }
    if timeout is not None:
        message["timeout_s"] = timeout
    message.update(fields)
    return message


def path_question(start, directory=False) -> dict:
    """Message `ask` de genre `path` : le chemin d'un fichier, ou avec
    `directory` d'un répertoire, à choisir à partir du répertoire `start`,
    absolu. Le message porte `start` et `directory` pour la page ; son
    texte, pour le terminal, nomme `start`, d'où part un chemin relatif
    tapé, et dit qu'une ligne vide renonce."""
    if directory:
        invite = t("Directory path (empty to cancel): ")
    else:
        invite = t("File path (empty to cancel): ")
    return question(
        "path", f"📂 {start}\n{invite}", start=start, directory=bool(directory)
    )


def menu_view(
    text,
    items,
    crumbs=(),
    sections=(),
    source="text",
    printed=False,
    notes=(),
) -> dict:
    """Message `menu` : `text` s'affiche tel quel, `items` sont des dict
    `key`, `label`, `section` (None hors section) ; chacun reçoit son
    `speak`. `source` dit qui l'a produit : `fill_help_info` ou `text`
    (un écran lu). `printed` : vrai quand le terminal montre, au-dessus du
    menu, ce que TODO a écrit depuis la dernière réponse ; `notes` : les
    lignes de `text` que les entrées ne disent pas (une ligne d'état)."""
    return {
        "t": "menu",
        "text": text,
        "crumbs": list(crumbs),
        "sections": list(sections),
        "items": [dict(item, speak=speak(item["label"])) for item in items],
        "source": source,
        "printed": bool(printed),
        "notes": list(notes),
        "speak": speak(crumbs[-1] if crumbs else text),
        "requires": [],
        "fallback": FALLBACK,
    }


def shell(cmd) -> str:
    """La commande shell de `cmd`. Une str passe telle quelle ; dans une
    t-string (`Template`), chaque valeur interpolée, convertie (`!r`, `!s`,
    `!a`) et formatée comme dans une f-string, passe par `shlex.quote` :
    elle reste un seul mot, espaces et `;` compris. TypeError sinon.
    Jamais de guillemets autour de `{…}` : la citation est faite ici, et
    `t"echo '{x}'"` la refermerait, rendant `x` à plusieurs mots."""
    if isinstance(cmd, str):
        return cmd
    if not isinstance(cmd, Template):
        raise TypeError(f"a command is a str or a t-string, not {cmd!r}")
    words = []
    for part in cmd:
        if isinstance(part, Interpolation):
            value = _CONVERT[part.conversion](part.value)
            words.append(shlex.quote(format(value, part.format_spec)))
        else:
            words.append(part)
    return "".join(words)


class BasePort:
    """Les questions que chaque port déduit de ses primitives `menu` et
    `ask`."""

    def secret(self, text) -> str:
        return self.ask(text, kind="secret")

    def confirm(self, text, default=False, typed=None) -> bool:
        """Vrai pour oui. Avec `typed`, vrai seulement si la réponse est ce
        texte exact : la question, un `ask` de genre `typed` posé par
        `menu`, le porte (`expected`) pour qu'une page n'active sa réponse
        qu'à l'égalité, et c'est ici qu'elle se vérifie. Une page n'y offre
        donc aucun « non » : son Annuler lève EOFError (Abort sous click),
        comme Ctrl+D, et l'appelant prend l'une et l'autre pour non. Sans
        `typed`, redemande jusqu'à oui, non ou Entrée (le défaut)."""
        if typed is not None:
            message = question("typed", text, expected=typed)
            return self.menu(message).strip() == typed
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            answer = self.ask(
                f"{text} {hint}: ", "y" if default else "n", "confirm"
            )
            answer = answer.strip().lower()
            if answer in YES:
                return True
            if answer in NO:
                return False
            if not answer:
                return default

    def choose(self, text, options, multi=False):
        """L'option choisie par son numéro, ou avec `multi` la liste de
        celles que nomme une réponse comme « 1 3 » ; redemande tant que la
        réponse nomme autre chose. La question est un `ask` de genre
        `choose`, posé par `menu` : `options` (`key`, `label`, `speak`) et
        `multi` pour la page, un texte qui numérote les options pour le
        terminal."""
        items = [
            {"key": str(n), "label": str(option), "speak": speak(option)}
            for n, option in enumerate(options, 1)
        ]
        lines = [text, *(f"[{i['key']}] {i['label']}" for i in items)]
        shown = "\n".join(lines) + "\n: "
        message = question(
            "choose", shown, options=items, multi=multi, speak=speak(text)
        )
        while True:
            keys = self.menu(message).replace(",", " ").split()
            picked = [
                options[int(key) - 1]
                for key in keys
                if key.isdigit() and 0 < int(key) <= len(options)
            ]
            if keys and len(picked) == len(keys):
                if multi:
                    return picked
                if len(picked) == 1:
                    return picked[0]

    def pick_path(self, start, directory=False):
        """Le chemin absolu d'un fichier, ou avec `directory` d'un
        répertoire, choisi à partir du répertoire `start` ; None quand
        l'utilisateur renonce : Annuler (EOFError, comme Ctrl+D) ou une
        réponse blanche. La question est un `ask` de genre `path`
        (`path_question`), posé par `menu`. Un chemin relatif part de
        `start`, `~` du répertoire de l'utilisateur ; un chemin qui
        n'existe pas, ou d'un autre genre, se dit par `notice` et la même
        question revient."""
        start = os.path.abspath(start)
        message = path_question(start, directory)
        while True:
            try:
                answer = self.menu(message)
            except EOFError:
                return None
            if not answer.strip():
                return None
            path = os.path.join(start, os.path.expanduser(answer))
            path = os.path.abspath(path)
            if os.path.isdir(path) if directory else os.path.isfile(path):
                return path
            if os.path.exists(path):
                wrong = ("Not a file: ", "Not a directory: ")
            else:
                wrong = ("No such file: ", "No such directory: ")
            self.notice(f"{t(wrong[bool(directory)])}{path}", "error")


class TerminalPort(BasePort):
    """Le terminal, comme au CLI : `input`, `getpass` et le compte à
    rebours d'auto_ask d'origine, `print`, `Execute.exec_command_live`."""

    def menu(self, view) -> str:
        return ORIGINAL["input"](view["text"])

    def ask(self, text, default=None, kind="text", timeout=None) -> str:
        if kind == "secret":
            return ORIGINAL["getpass"](text)
        if kind == "countdown":
            from script.todo import auto_ask

            countdown = ORIGINAL.get("auto_ask.ask", auto_ask.ask)
            return countdown(text, default or "", timeout)
        return ORIGINAL["input"](text)

    def pick_path(self, start, directory=False):
        """Le navigateur urwid de TODO, plein écran, par sa boucle
        d'origine : le chemin choisi, ou None pour `q`."""
        from script.todo import todo_file_browser

        browser = todo_file_browser.FileBrowser
        run = ORIGINAL.get(
            "FileBrowser.run_main_frame", browser.run_main_frame
        )
        chosen = []
        run(browser(start, chosen.append, open_dir=directory))
        return chosen[-1] if chosen else None

    def notice(self, text, level="info") -> None:
        print(text)

    def run(self, cmd, **opts) -> int:
        from script.execute import execute

        return execute.Execute().exec_command_live(cmd, **opts)

    def open_view(self, view) -> bool:
        """Aucune page n'est ouverte depuis un terminal : faux."""
        return False


class ScriptedPort(BasePort):
    """Répond depuis `answers`, dans l'ordre, et garde chaque message dans
    `events`. Une réponse qui est une exception est levée ; sans réponse,
    EOFError, comme `input` en fin de fichier. `run` rend les `codes` dans
    l'ordre, puis 0."""

    def __init__(self, answers=(), codes=()):
        self.answers = list(answers)
        self.codes = list(codes)
        self.events = []

    def _answer(self, message) -> str:
        self.events.append(message)
        if not self.answers:
            raise EOFError("no scripted answer left")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def menu(self, view) -> str:
        return self._answer(view)

    def ask(self, text, default=None, kind="text", timeout=None) -> str:
        return self._answer(question(kind, text, default, timeout))

    def notice(self, text, level="info") -> None:
        self.events.append({"t": "notice", "text": text, "level": level})

    def run(self, cmd, **opts) -> int:
        self.events.append({"t": "run", "cmd": cmd, "opts": opts})
        return self.codes.pop(0) if self.codes else 0

    def open_view(self, view) -> bool:
        self.events.append({"t": "open_view", "view": view})
        return True
