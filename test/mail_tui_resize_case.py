#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""`ResizeCase` : `MailApp` montée pour de vrai, `$HOME` détourné.

Partagée par `test_mail_tui_resize.py` et
`test_mail_tui_resize_terminal.py`. Sans préfixe `test_`, le lanceur
unitaire ne la prend pas pour un fichier de tests.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import Store
from script.todo.mail.tui import Session

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from async_case import AsyncCase  # noqa: E402


class ResizeCase(AsyncCase):
    """Monte `MailApp` pour de vrai, `$HOME` détourné — même motif que
    `test_mail_tui_layout.py`.
    """

    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name

        self.cache_dir = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.account.cache_mode = "clear"
        self.store = Store(
            self.account, mode="clear", base=Path(self.cache_dir.name)
        )
        self.store.open()
        self.session = Session(self.account, self.store, None, password="x")

    def tearDown(self):
        self.store.close()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()
        self.cache_dir.cleanup()

    def _fresh_session(self):
        """Une DEUXIÈME session sur le MÊME cache disque — pas
        `self.session` réutilisée : `MailApp.on_unmount` ferme la session
        (donc le `Store`) quand `run_test()` démonte l'appli, si bien que
        réutiliser le même objet `Session` pour un second montage
        planterait sur un cache déjà fermé. Un vrai redémarrage rouvre le
        cache depuis le DISQUE ; ceci en est le double fidèle.
        """
        store = Store(
            self.account, mode="clear", base=Path(self.cache_dir.name)
        )
        store.open()
        return Session(self.account, store, None, password="x")

    async def _mounted_app(self, sessions=None):
        import textual.app

        from script.todo.mail.tui import run_tui

        sessions = sessions if sessions is not None else [self.session]
        captured = []
        orig_init = textual.app.App.__init__

        def capturing_init(app_self, *a, **kw):
            orig_init(app_self, *a, **kw)
            captured.append(app_self)

        textual.app.App.__init__ = capturing_init
        try:
            run_tui(run_app=False, sessions=sessions)
        finally:
            textual.app.App.__init__ = orig_init
        return captured[-1]
