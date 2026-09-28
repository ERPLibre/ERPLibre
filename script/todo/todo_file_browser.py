#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un navigateur de fichiers urwid, et urwid chargé seulement à l'usage.

urwid coûte à lui seul la moitié de l'import de TODO, qui charge ce module
au démarrage pour ses menus — et le navigateur ne s'ouvre que si l'on
choisit de parcourir. `FileBrowser`, qui hérite d'une classe urwid, est
donc bâtie à sa première demande (`__getattr__` de module), et
`exit_program` importe urwid à l'appel.

L'import vérifie pourtant qu'urwid est INSTALLÉ, sans le charger : les
appelants proposent la saisie directe d'un chemin quand ce module ne
s'importe pas, et ce repli doit toujours se décider à l'import.
"""

import functools
import importlib.util
import os

if importlib.util.find_spec("urwid") is None:
    raise ModuleNotFoundError("urwid", name="urwid")


def __getattr__(nom):
    if nom == "FileBrowser":
        return _file_browser()
    raise AttributeError(f"module {__name__!r} has no attribute {nom!r}")


@functools.cache
def _file_browser():
    """La classe FileBrowser, bâtie une fois, urwid chargé à ce moment."""
    import urwid

    class FileBrowser(urwid.WidgetWrap):
        def __init__(self, initial_path, callback, open_dir=False):
            self.callback = callback
            self.current_path = os.path.abspath(initial_path)
            self.list_walker = urwid.SimpleFocusListWalker([])
            self.listbox = urwid.ListBox(self.list_walker)
            super().__init__(self.listbox)
            self.open_dir = open_dir
            self.refresh_list()

        def refresh_list(self):
            """Updates the list of files and directories."""
            self.list_walker.clear()
            self.list_walker.append(
                urwid.Button("..", on_press=self.go_up_directory)
            )
            if self.open_dir:
                self.list_walker.append(
                    urwid.Button(".", on_press=self.select_directory)
                )

            try:
                entries = os.listdir(self.current_path)
                entries.sort(key=lambda r: r.lower())
                for entry in entries:
                    full_path = os.path.join(self.current_path, entry)
                    if os.path.isdir(full_path):
                        self.list_walker.append(
                            urwid.Button(
                                f"{entry}/", on_press=self.open_directory
                            )
                        )
                    elif not self.open_dir:
                        self.list_walker.append(
                            urwid.Button(entry, on_press=self.select_file)
                        )
            except OSError as e:
                # Handle directory access errors
                self.list_walker.append(urwid.Text(f"Access Error: {e}"))

        def go_up_directory(self, button):
            """Moves up one level in the directory hierarchy."""
            parent_path = os.path.dirname(self.current_path)
            if parent_path != self.current_path:
                self.current_path = parent_path
                self.refresh_list()

        def open_directory(self, button):
            """Moves into a subdirectory."""
            dirname = button.label[:-1]
            new_path = os.path.join(self.current_path, dirname)
            if os.path.isdir(new_path):
                self.current_path = new_path
                self.refresh_list()

        def select_directory(self, button):
            """Selects a directory, and closes the browser."""
            self.callback(self.current_path)
            exit_program()

        def select_file(self, button):
            """Selects a file, and closes the browser.

            The callback records the choice; leaving the loop is what ENDS the
            browser. Without it the selection worked and nothing seemed to happen:
            the screen stayed up, no key closed it, and only Ctrl+C got out — so
            the browser looked frozen at the exact moment it had done its job.
            """
            filename = button.label
            selected_file_path = os.path.join(self.current_path, filename)
            self.callback(selected_file_path)
            exit_program()

        def unhandled_input(self, key):
            """Leaving without choosing has to be possible.

            Every other way out of this browser selects something. A caller that
            offers an alternative — typing a path — can only be reached by
            cancelling, so cancelling has to exist.
            """
            if key in ("q", "Q", "esc"):
                exit_program()

        def run_main_frame(self):
            main_frame = urwid.Frame(
                body=self,
                header=urwid.Text(
                    ("header", f"Navigate: {self.current_path}")
                ),
                footer=urwid.Text(
                    (
                        "footer",
                        "Arrow keys to navigate, Enter to select, q to cancel.",
                    )
                ),
            )

            palette = [
                ("header", "dark cyan", "black"),
                ("footer", "dark cyan", "black"),
                ("body", "white", "black"),
                ("button", "black", "dark cyan", "standout"),
                ("focus", "white", "dark green", "bold"),
                ("bold", "bold", "black"),
            ]

            loop = urwid.MainLoop(
                main_frame, palette, unhandled_input=self.unhandled_input
            )
            loop.run()

    return FileBrowser


def exit_program():
    """Exits the program."""
    import urwid

    raise urwid.ExitMainLoop()
