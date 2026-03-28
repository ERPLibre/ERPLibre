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

        first_file_idx = None
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
                    if first_file_idx is None:
                        first_file_idx = len(self.list_walker)
                    self.list_walker.append(
                        urwid.Button(entry, on_press=self.select_file)
                    )
        except OSError as e:
            # Handle directory access errors
            self.list_walker.append(urwid.Text(f"Access Error: {e}"))

        # Set focus: "." for dir selection, first file for file selection
        if self.open_dir and len(self.list_walker) > 1:
            self.list_walker.set_focus(1)  # Focus on "." (select current dir)
        elif first_file_idx is not None:
            self.list_walker.set_focus(first_file_idx)  # Focus on first file

    def _update_header(self):
        if hasattr(self, "_header_text"):
            self._header_text.set_text(
                ("header", f"Navigate: {self.current_path}")
            )

    def go_up_directory(self, button):
        """Moves up one level in the directory hierarchy."""
        parent_path = os.path.dirname(self.current_path)
        if parent_path != self.current_path:
            self.current_path = parent_path
            self.refresh_list()
            self._update_header()

    def open_directory(self, button):
        """Moves into a subdirectory."""
        dirname = button.label[:-1]
        new_path = os.path.join(self.current_path, dirname)
        if os.path.isdir(new_path):
            self.current_path = new_path
            self.refresh_list()
            self._update_header()

    def select_directory(self, button):
        """Selects a directory and calls the callback function."""
        self.callback(self.current_path)
        raise urwid.ExitMainLoop()

    def select_file(self, button):
        """Selects a file and calls the callback function."""
        filename = button.label
        selected_file_path = os.path.join(self.current_path, filename)
        self.callback(selected_file_path)
        raise urwid.ExitMainLoop()

    def run_main_frame(self):
        self._header_text = urwid.Text(
            ("header", f"Navigate: {self.current_path}")
        )
        main_frame = urwid.Frame(
            body=self,
            header=self._header_text,
            footer=urwid.Text(
                (
                    "footer",
                    "Arrow keys: navigate | Enter/Space: select | q/Esc: cancel",
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

        def unhandled_input(key):
            if key in ("q", "Q", "esc"):
                raise urwid.ExitMainLoop()

        loop = urwid.MainLoop(main_frame, palette, unhandled_input=unhandled_input)
        loop.run()


def exit_program():
    """Exits the program."""
    raise urwid.ExitMainLoop()
