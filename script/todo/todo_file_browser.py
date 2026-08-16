#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os

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
                        urwid.Button(f"{entry}/", on_press=self.open_directory)
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
            header=urwid.Text(("header", f"Navigate: {self.current_path}")),
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


def exit_program():
    """Exits the program."""
    raise urwid.ExitMainLoop()
