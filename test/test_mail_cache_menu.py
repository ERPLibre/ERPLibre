#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Cache face au mode inscrit : conversion [4], mode d'un compte
[2], défaut général [1], purge [3], et les autres entrées qui ouvrent un
cache.

`HOME` est temporaire (les comptes y vivent), la base des caches aussi,
les préférences sont un dict, le coffre un double en mémoire. `input` et
`click.prompt` sont remplacés ; la sortie est capturée."""

import base64
import contextlib
import functools
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mail_cache_fixtures import (
    COMPTE,
    FauxCoffre,
    fichiers,
    instantane,
    remplir,
)

from script.todo import todo_prefs
from script.todo.mail import accounts as mail_accounts
from script.todo.mail import cache_convert, menu
from script.todo.mail import store as store_mod
from script.todo.mail.accounts import AccountError, account_from_preset
from script.todo.mail.crypto import AesGcmCrypto, new_key
from script.todo.mail.store import (
    CACHE_CTL_DIRNAME,
    Store,
    StoreError,
    cache_exclusive,
    inscribed_mode,
    shown_mode,
)
from script.todo.todo_i18n import t


def compte(nom="perso", mode=None):
    acc = account_from_preset(nom, COMPTE, "generic")
    acc.cache_mode = mode
    return acc


class MenuCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.base = self.tmp / "mail"
        self.racine = self.base / "perso"
        self.ctl = self.base / CACHE_CTL_DIRNAME / "perso"
        self.prefs = {}
        self.coffre = FauxCoffre()
        self.todo = mock.MagicMock()
        self.todo._menu_header.return_value = "--"
        for rustine in (
            mock.patch.dict(os.environ, {"HOME": str(self.home)}),
            mock.patch.object(todo_prefs, "load", lambda: dict(self.prefs)),
            mock.patch.object(
                todo_prefs,
                "_save",
                lambda data: (self.prefs.clear(), self.prefs.update(data)),
            ),
            mock.patch.object(
                menu, "secret_store_for", lambda _todo: self.coffre
            ),
        ):
            rustine.start()
            self.addCleanup(rustine.stop)
        self.questions = []

    # -- mise en place ---------------------------------------------------

    def comptes(self, *modes):
        liste = [
            compte(f"perso{i}" if i else "perso", m)
            for i, m in enumerate(modes)
        ]
        mail_accounts.save(liste)
        return liste

    def cache(self, mode, nom="perso"):
        store = Store(compte(nom, mode), secrets=self.coffre, base=self.base)
        store.open()
        reperes = remplir(store)
        store.close()
        return reperes

    def relu(self, nom="perso"):
        return mail_accounts.find(mail_accounts.load(), nom)

    def ouvre(self, nom="perso", coffre=None):
        store = Store(
            self.relu(nom),
            secrets=self.coffre if coffre is None else coffre,
            base=self.base,
        )
        store.open()
        self.addCleanup(store.close)
        return store

    def lancer(self, fonction, reponses, *args, prompts=None, **kw):
        """Appelle `fonction(self.todo, *args, base=…)` avec les réponses
        données à `input` (une exception y est levée telle quelle) ; rend
        la sortie."""
        reponses = list(reponses)

        def repond(question=""):
            self.questions.append(question)
            reponse = reponses.pop(0)
            if isinstance(reponse, BaseException):
                raise reponse
            return reponse

        sortie = io.StringIO()
        with contextlib.ExitStack() as pile:
            pile.enter_context(mock.patch("builtins.input", repond))
            if prompts is not None:
                pile.enter_context(
                    mock.patch.object(
                        menu.click, "prompt", side_effect=list(prompts)
                    )
                )
            pile.enter_context(contextlib.redirect_stdout(sortie))
            self.retour = fonction(self.todo, *args, base=self.base, **kw)
        return sortie.getvalue()

    def avec_faute(self, point, exc):
        """`convert_cache` qui lève `exc` au point donné."""
        vrai = cache_convert.convert_cache

        def faute(p):
            if p == point:
                raise exc

        return mock.patch.object(
            cache_convert,
            "convert_cache",
            functools.partial(vrai, fault=faute),
        )


class TestConvertEntry(MenuCase):
    def test_entry_4_converts_after_confirmation_and_prints_the_summary(self):
        self.comptes("clear")
        self.cache("clear")
        sortie = self.lancer(
            menu.prompt_mail_cache, ["1", "o", "o"], prompts=["4", "0"]
        )
        self.assertIn(
            t("mail_cache_converted").format(
                account="perso",
                target="encrypted",
                messages=3,
                bodies=2,
                journal=4,
            ),
            sortie,
        )
        self.assertIn(
            t("mail_cache_convert_legacy").format(journal=1, auto_sent=0),
            sortie,
        )
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")
        self.assertEqual(self.ouvre().mode, "encrypted")

    def test_declining_changes_nothing(self):
        self.comptes("clear")
        self.cache("clear")
        avant = fichiers(self.racine)
        self.lancer(menu._convert_entry, ["1", "n"])
        self.assertEqual(fichiers(self.racine), avant)
        self.assertEqual(self.relu().cache_mode, "clear")

    def test_an_explicit_account_mode_follows_the_conversion(self):
        self.comptes("encrypted")
        self.cache("encrypted")
        self.lancer(menu._convert_entry, ["1", "o", "o"])
        self.assertEqual(self.relu().cache_mode, "clear")
        self.assertEqual(self.ouvre().mode, "clear")

    def test_an_inheriting_account_is_pinned_only_when_the_default_disagrees(
        self,
    ):
        self.comptes(None)
        self.cache("clear")
        self.lancer(menu._convert_entry, ["1", "o", "o"])
        self.assertIsNone(self.relu().cache_mode)
        ouvert = self.ouvre()
        self.assertEqual(ouvert.mode, "encrypted")
        ouvert.close()
        self.prefs["mail_cache_mode"] = "encrypted"
        self.lancer(menu._convert_entry, ["1", "o", "o"])
        self.assertEqual(self.relu().cache_mode, "clear")
        self.assertEqual(self.ouvre().mode, "clear")

    def test_a_refusal_prints_its_message_and_no_trace(self):
        self.comptes("clear")
        self.cache("clear")
        ouvert = self.ouvre()
        sortie = self.lancer(menu._convert_entry, ["1", "o"])
        ouvert.close()
        self.assertIn(
            t("mail_cache_convert_busy_open").format(account="perso"), sortie
        )
        self.assertNotIn("Traceback", sortie)
        self.assertFalse(self.retour)
        self.assertEqual(self.relu().cache_mode, "clear")

    def test_no_disk_cache_or_ephemeral_account_is_explained(self):
        self.comptes("clear")
        sortie = self.lancer(menu._convert_entry, ["1"])
        self.assertIn(
            t("mail_cache_convert_no_cache").format(account="perso"), sortie
        )
        self.comptes("ephemeral")
        sortie = self.lancer(menu._convert_entry, ["1"])
        self.assertIn(
            t("mail_cache_convert_ephemeral").format(account="perso"), sortie
        )

    def test_an_inheriting_ephemeral_account_is_not_converted(self):
        self.comptes(None)
        self.cache("encrypted")
        self.prefs["mail_cache_mode"] = "ephemeral"
        sortie = self.lancer(menu._convert_entry, ["1"])
        self.assertIn(
            t("mail_cache_convert_ephemeral").format(account="perso"), sortie
        )
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")
        self.assertIsNone(self.relu().cache_mode)

    def test_an_invalid_inscription_is_explained(self):
        self.comptes("clear")
        self.cache("clear")
        conn = sqlite3.connect(self.racine / "cache.db")
        conn.execute(
            "UPDATE meta SET value = 'magique' WHERE key = 'cache_mode'"
        )
        conn.commit()
        conn.close()
        sortie = self.lancer(menu._convert_entry, ["1"])
        self.assertIn(
            t("mail_err_cache_mode_invalid").format(
                account="perso", inscribed="'magique'"
            ),
            sortie,
        )

    def _cache_mele(self):
        self.comptes("encrypted")
        self.cache("clear")
        cle = new_key()
        self.coffre.set(
            compte().cache_key_ref(), base64.b64encode(cle).decode()
        )
        conn = sqlite3.connect(self.racine / "cache.db")
        conn.execute(
            "UPDATE messages SET sealed_snippet = ? WHERE uid = 2",
            (AesGcmCrypto(cle).seal(b"scelle"),),
        )
        conn.execute(
            "UPDATE meta SET value = 'encrypted' WHERE key = 'cache_mode'"
        )
        conn.commit()
        conn.close()

    def test_a_mixed_cache_is_offered_a_reseal_first(self):
        self._cache_mele()
        avant = fichiers(self.racine)
        self.lancer(menu._convert_entry, ["1", "n", "n"])
        self.assertEqual(
            self.questions[1],
            t("mail_cache_reseal_confirm").format(account="perso"),
        )
        self.assertEqual(
            self.questions[2],
            t("mail_cache_convert_confirm_clear").format(
                account="perso", source="encrypted", target="clear"
            ),
        )
        self.assertEqual(fichiers(self.racine), avant)
        self.lancer(menu._convert_entry, ["1", "o", "o"])
        self.assertFalse(
            [p for p in fichiers(self.racine) if p.endswith(".eml")]
        )
        self.assertEqual(self.ouvre().mode, "encrypted")
        self.assertEqual(self.relu().cache_mode, "encrypted")

    def test_an_unsaved_account_mode_is_announced(self):
        self.comptes("clear")
        self.cache("clear")
        with mock.patch.object(
            mail_accounts, "save", side_effect=OSError(13, "refusé")
        ):
            sortie = self.lancer(menu._convert_entry, ["1", "o", "o"])
        self.assertIn(
            t("mail_cache_convert_mode_unsaved").format(target="encrypted"),
            sortie,
        )
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")

    def test_ctrl_c_after_the_swap_settles_the_account_and_says_so(self):
        comptes = self.comptes("clear")
        self.cache("clear")
        with self.avec_faute("moved_new", KeyboardInterrupt()):
            sortie = self.lancer(
                menu._run_conversion,
                ["o"],
                comptes[0],
                "encrypted",
                on_committed=lambda c: menu._settle_account_mode(
                    comptes[0], comptes, c
                ),
            )
        self.assertTrue(self.retour)
        self.assertIn(
            t("mail_cache_convert_incomplete").format(
                account="perso", target="encrypted"
            ),
            sortie.splitlines(),
        )
        self.assertEqual(self.relu().cache_mode, "encrypted")
        self.assertEqual(self.ouvre().mode, "encrypted")
        self.assertEqual(sorted(os.listdir(self.ctl)), ["lock"])

    def regler(self, comptes):
        return lambda c: menu._settle_account_mode(comptes[0], comptes, c)

    def test_a_reseal_interrupted_after_the_swap_says_it_is_done(self):
        """Source et cible valent `encrypted` : seul l'état sur le disque
        dit que l'échange a eu lieu."""
        self._cache_mele()
        comptes = mail_accounts.load()
        with self.avec_faute("moved_new", KeyboardInterrupt()):
            sortie = self.lancer(
                menu._run_conversion,
                ["o"],
                comptes[0],
                "encrypted",
                on_committed=self.regler(comptes),
            )
        self.assertTrue(self.retour)
        self.assertIn(
            t("mail_cache_convert_incomplete").format(
                account="perso", target="encrypted"
            ),
            sortie.splitlines(),
        )
        self.assertNotIn(
            t("mail_cache_convert_cancelled").format(
                account="perso", source="encrypted"
            ),
            sortie,
        )
        self.assertEqual(self.ouvre().mode, "encrypted")
        self.assertEqual(sorted(os.listdir(self.ctl)), ["lock"])

    def test_a_reseal_interrupted_before_the_swap_says_nothing_changed(self):
        self._cache_mele()
        comptes = mail_accounts.load()
        rappels = []
        with self.avec_faute("built", KeyboardInterrupt()):
            sortie = self.lancer(
                menu._run_conversion,
                ["o"],
                comptes[0],
                "encrypted",
                on_committed=rappels.append,
            )
        self.assertFalse(self.retour)
        self.assertEqual(rappels, [])
        self.assertIn(
            t("mail_cache_convert_cancelled").format(
                account="perso", source="encrypted"
            ),
            sortie,
        )
        self.assertNotIn(
            t("mail_cache_convert_incomplete").format(
                account="perso", target="encrypted"
            ),
            sortie,
        )

    def test_a_failed_reseal_is_not_announced_as_converted(self):
        self._cache_mele()
        comptes = mail_accounts.load()
        rappels = []
        with mock.patch.object(
            cache_convert._Copier,
            "verify",
            side_effect=cache_convert._VerifyFailed("corps"),
        ):
            sortie = self.lancer(
                menu._run_conversion,
                ["o"],
                comptes[0],
                "encrypted",
                on_committed=rappels.append,
            )
        self.assertFalse(self.retour)
        self.assertEqual(rappels, [])
        self.assertIn(t("mail_cache_convert_verify_failed"), sortie)
        self.assertNotIn(
            t("mail_cache_convert_incomplete").format(
                account="perso", target="encrypted"
            ),
            sortie,
        )

    def test_ctrl_c_before_on_committed_settles_the_account_from_the_menu(
        self,
    ):
        """Un Ctrl-C dans `on_committed`, l'état `swapping` écrit : le
        menu rappelle `on_committed` et le compte suit la cible."""
        comptes = self.comptes("clear")
        self.cache("clear")
        regle = self.regler(comptes)
        appels = []

        def rappel(cible):
            appels.append(cible)
            if len(appels) == 1:
                raise KeyboardInterrupt
            regle(cible)

        sortie = self.lancer(
            menu._run_conversion,
            ["o"],
            comptes[0],
            "encrypted",
            on_committed=rappel,
        )
        self.assertTrue(self.retour)
        self.assertEqual(appels, ["encrypted", "encrypted"])
        self.assertEqual(self.relu().cache_mode, "encrypted")
        self.assertIn(
            t("mail_cache_convert_incomplete").format(
                account="perso", target="encrypted"
            ),
            sortie,
        )
        self.assertEqual(self.ouvre().mode, "encrypted")

    def test_an_unreadable_cache_is_not_called_an_unknown_mode(self):
        self.comptes("clear")
        self.racine.mkdir(parents=True)
        (self.racine / "cache.db").write_bytes(os.urandom(4096))
        sortie = self.lancer(menu._convert_entry, ["1"])
        self.assertIn(
            t("mail_cache_unreadable").format(account="perso"), sortie
        )
        self.assertNotIn(store_mod.PROBE_UNKNOWN, sortie)

    def test_a_recovery_error_after_the_swap_is_caught(self):
        comptes = self.comptes("clear")
        self.cache("clear")
        vrai = cache_convert.recover
        appels = []

        def reprise(*a, **k):
            appels.append(1)
            if len(appels) > 1:
                raise StoreError("reprise impossible")
            return vrai(*a, **k)

        with (
            self.avec_faute("moved_new", OSError(5, "panne")),
            mock.patch.object(cache_convert, "recover", reprise),
        ):
            sortie = self.lancer(
                menu._run_conversion,
                ["o"],
                comptes[0],
                "encrypted",
                on_committed=lambda c: menu._settle_account_mode(
                    comptes[0], comptes, c
                ),
            )
        self.assertTrue(self.retour)
        self.assertIn(
            t("mail_cache_convert_incomplete").format(
                account="perso", target="encrypted"
            ),
            sortie,
        )

    def test_ctrl_c_before_the_swap_says_the_cache_is_unchanged(self):
        self.comptes("clear")
        self.cache("clear")
        with self.avec_faute("built", KeyboardInterrupt()):
            sortie = self.lancer(menu._convert_entry, ["1", "o", "o"])
        self.assertIn(
            t("mail_cache_convert_cancelled").format(
                account="perso", source="clear"
            ),
            sortie,
        )
        self.assertEqual(inscribed_mode(compte(), self.base), "clear")
        self.assertEqual(self.relu().cache_mode, "clear")
        self.assertFalse((self.ctl / "new").exists())

    def test_the_losses_are_asked_before_converting(self):
        self.comptes("clear")
        self.cache("clear")
        store = self.ouvre()
        store.purge_all()
        avant = instantane(store)
        store.close()
        sortie = self.lancer(menu._convert_entry, ["1", "o", "n"])
        self.assertEqual(
            self.questions[2],
            t("mail_cache_convert_losses_confirm").format(
                journal=1, auto_sent=0
            ),
        )
        self.assertIn(t("mail_cache_convert_declined"), sortie)
        store = self.ouvre()
        self.assertEqual(store.mode, "clear")
        self.assertEqual(instantane(store), avant)

    def test_the_confirmation_warns_before_a_clear_target(self):
        self.comptes("encrypted")
        self.cache("encrypted")
        self.lancer(menu._convert_entry, ["1", "n"])
        self.assertEqual(
            self.questions[1],
            t("mail_cache_convert_confirm_clear").format(
                account="perso", source="encrypted", target="clear"
            ),
        )
        self.comptes("clear")
        self.lancer(menu._convert_entry, ["1", "n"])


class TestAccountModeEntry(MenuCase):
    def test_another_mode_for_an_existing_cache_offers_the_conversion(self):
        self.comptes("clear")
        self.cache("clear")
        self.lancer(
            menu.prompt_mail_cache,
            ["1", "encrypted", "o", "o"],
            prompts=["2", "0"],
        )
        self.assertEqual(
            self.questions[2],
            t("mail_cache_convert_confirm_encrypted").format(
                account="perso", source="clear", target="encrypted"
            ),
        )
        self.assertEqual(self.relu().cache_mode, "encrypted")
        self.assertEqual(self.ouvre().mode, "encrypted")

    def test_declining_keeps_the_account_mode(self):
        self.comptes("clear")
        self.cache("clear")
        sortie = self.lancer(
            menu.prompt_mail_cache, ["1", "encrypted", "n"], prompts=["2", "0"]
        )
        self.assertIn(t("mail_cache_account_mode_unchanged"), sortie)
        self.assertEqual(self.relu().cache_mode, "clear")
        self.assertEqual(inscribed_mode(compte(), self.base), "clear")

    def test_ephemeral_keeps_the_disk_cache_and_says_so(self):
        self.comptes("clear")
        self.cache("clear")
        sortie = self.lancer(
            menu.prompt_mail_cache, ["1", "ephemeral"], prompts=["2", "0"]
        )
        self.assertIn(
            t("mail_cache_ephemeral_keeps_disk").format(
                account="perso", mode="clear"
            ),
            sortie,
        )
        self.assertEqual(self.relu().cache_mode, "ephemeral")
        self.assertTrue((self.racine / "cache.db").exists())

    def test_the_same_mode_as_the_cache_is_saved_without_question(self):
        self.comptes(None)
        self.cache("encrypted")
        self.lancer(
            menu.prompt_mail_cache, ["1", "encrypted"], prompts=["2", "0"]
        )
        self.assertEqual(self.relu().cache_mode, "encrypted")
        self.assertEqual(len(self.questions), 2)

    def journal_sale_en_clair(self):
        """Un cache chiffré dont le contrôle d'époque et le journal sont
        salés en clair, comme après un retour en `clear` par l'ancien
        menu ; le compte demande `clear` et se voit refusé."""
        self.comptes("clear")
        self.cache("clear")
        conn = sqlite3.connect(self.racine / "cache.db")
        conn.execute(
            "UPDATE messages SET sealed_snippet = ? WHERE uid = 2",
            (AesGcmCrypto(self.cle_au_coffre()).seal(b"scelle"),),
        )
        conn.execute(
            "UPDATE meta SET value = 'encrypted' WHERE key = 'cache_mode'"
        )
        conn.commit()
        conn.close()

    def cle_au_coffre(self):
        cle = new_key()
        self.coffre.set(
            compte().cache_key_ref(), base64.b64encode(cle).decode()
        )
        return cle

    def lignes_du_journal(self):
        conn = sqlite3.connect(self.racine / "cache.db")
        try:
            return conn.execute("SELECT count(*) FROM rule_log").fetchone()[0]
        finally:
            conn.close()

    def test_encrypted_on_a_clear_salted_journal_offers_the_reseal(self):
        self.journal_sale_en_clair()
        lignes = self.lignes_du_journal()
        avant = fichiers(self.racine)
        sortie = self.lancer(
            menu.prompt_mail_cache, ["1", "encrypted", "n"], prompts=["2", "0"]
        )
        self.assertEqual(
            self.questions[2],
            t("mail_cache_reseal_confirm").format(account="perso"),
        )
        self.assertIn(t("mail_cache_account_mode_unchanged"), sortie)
        self.assertEqual(self.relu().cache_mode, "clear")
        self.assertEqual(fichiers(self.racine), avant)
        self.lancer(
            menu.prompt_mail_cache,
            ["1", "encrypted", "o", "o"],
            prompts=["2", "0"],
        )
        self.assertEqual(self.relu().cache_mode, "encrypted")
        store = self.ouvre()
        self.assertEqual(store.mode, "encrypted")
        store.cache_epoch()
        self.assertEqual(
            store._db().execute("SELECT count(*) FROM rule_log").fetchone()[0],
            lignes,
        )

    def test_ephemeral_on_an_unreadable_cache_names_no_internal_token(self):
        self.comptes("clear")
        self.racine.mkdir(parents=True)
        (self.racine / "cache.db").write_bytes(os.urandom(4096))
        sortie = self.lancer(
            menu.prompt_mail_cache, ["1", "ephemeral"], prompts=["2", "0"]
        )
        self.assertIn(
            t("mail_cache_ephemeral_keeps_disk").format(
                account="perso", mode=t("mail_cache_mode_unreadable")
            ),
            sortie,
        )
        self.assertNotIn(store_mod.PROBE_UNKNOWN, sortie)


class TestDefaultModeEntry(MenuCase):
    def test_an_inheriting_cache_in_another_mode_is_offered_the_conversion(
        self,
    ):
        self.comptes(None)
        self.cache("clear")
        self.lancer(
            menu.prompt_mail_cache, ["encrypted", "o", "o"], prompts=["1", "0"]
        )
        self.assertEqual(self.prefs["mail_cache_mode"], "encrypted")
        self.assertIsNone(self.relu().cache_mode)
        self.assertEqual(self.ouvre().mode, "encrypted")

    def test_declining_pins_the_inheriting_account_to_its_cache(self):
        self.comptes(None)
        self.cache("clear")
        sortie = self.lancer(
            menu.prompt_mail_cache, ["encrypted", "n"], prompts=["1", "0"]
        )
        self.assertEqual(self.prefs["mail_cache_mode"], "encrypted")
        self.assertEqual(self.relu().cache_mode, "clear")
        self.assertIn(
            t("mail_cache_default_pinned").format(
                account="perso", mode="clear"
            ),
            sortie,
        )
        self.assertEqual(self.ouvre().mode, "clear")

    def test_ctrl_c_at_the_question_leaves_the_account_pinned_and_openable(
        self,
    ):
        self.comptes(None)
        self.cache("clear")
        with self.assertRaises(KeyboardInterrupt):
            self.lancer(
                menu._reconcile_default,
                [KeyboardInterrupt()],
                "encrypted",
            )
        self.assertEqual(self.prefs["mail_cache_mode"], "encrypted")
        self.assertEqual(self.relu().cache_mode, "clear")
        self.assertEqual(self.ouvre().mode, "clear")

    def test_an_unsaved_pin_writes_no_preference(self):
        self.comptes(None)
        self.cache("clear")
        with mock.patch.object(
            mail_accounts, "save", side_effect=AccountError("refusé")
        ):
            sortie = self.lancer(menu._reconcile_default, [], "encrypted")
        self.assertIn("refusé", sortie)
        self.assertNotIn("mail_cache_mode", self.prefs)
        self.assertIsNone(self.relu().cache_mode)
        self.assertEqual(self.ouvre().mode, "clear")

    def test_an_ephemeral_default_pins_nothing(self):
        self.comptes(None)
        self.cache("clear")
        sortie = self.lancer(menu._reconcile_default, [], "ephemeral")
        self.assertEqual(self.prefs["mail_cache_mode"], "ephemeral")
        self.assertIsNone(self.relu().cache_mode)
        self.assertIn(
            t("mail_cache_ephemeral_keeps_disk").format(
                account="perso", mode="clear"
            ),
            sortie,
        )


class TestPurge(MenuCase):
    def purger(self, *reponses):
        return self.lancer(menu._cache_size_and_purge, ["1", "o", *reponses])

    def test_purge_opens_the_inscribed_mode_and_keeps_the_journal(self):
        self.comptes("clear")
        self.cache("encrypted")
        sortie = self.purger()
        self.assertIn(t("mail_purged"), sortie)
        conn = sqlite3.connect(self.racine / "cache.db")
        try:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM rule_log").fetchone()[0], 4
            )
            self.assertEqual(
                conn.execute("SELECT count(*) FROM messages").fetchone()[0], 0
            )
        finally:
            conn.close()
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")

    def test_purge_during_a_conversion_deletes_nothing(self):
        self.comptes("clear")
        self.cache("clear")
        avant = fichiers(self.racine)
        with cache_exclusive("perso", self.base) as tenu:
            self.assertTrue(tenu)
            sortie = self.purger()
        self.assertIn(t("mail_err_cache_busy_converting"), sortie)
        self.assertEqual(fichiers(self.racine), avant)

    def test_purge_on_a_mode_mismatch_erases_nothing(self):
        self.comptes("clear")
        self.cache("encrypted")
        avant = fichiers(self.racine)
        with mock.patch.object(menu, "inscribed_mode", return_value="clear"):
            sortie = self.purger()
        self.assertIn(
            t("mail_err_cache_mode_mismatch").format(
                account="perso", inscribed="encrypted", requested="clear"
            ),
            sortie,
        )
        self.assertNotIn(t("mail_purged"), sortie)
        self.assertEqual(fichiers(self.racine), avant)

    def test_purge_of_an_invalid_inscription_asks_before_erasing(self):
        shm = self.tmp / "shm"
        for valeur in ("magique", "ephemeral"):
            with self.subTest(valeur=valeur):
                self.comptes("clear")
                self.cache("clear")
                conn = sqlite3.connect(self.racine / "cache.db")
                conn.execute(
                    "UPDATE meta SET value = ? WHERE key = 'cache_mode'",
                    (valeur,),
                )
                conn.commit()
                conn.close()
                avant = fichiers(self.racine)
                with mock.patch.object(
                    store_mod, "ephemeral_base", return_value=shm
                ):
                    self.purger("n")
                    self.assertEqual(fichiers(self.racine), avant)
                    sortie = self.purger("o")
                self.assertEqual(
                    self.questions[-1],
                    t("mail_cache_purge_invalid_confirm").format(
                        account="perso", inscribed=shown_mode(valeur)
                    ),
                )
                self.assertIn(t("mail_purged"), sortie)
                self.assertFalse(self.racine.exists())
                self.assertFalse(shm.exists())

    def test_purge_without_the_key_asks_before_erasing(self):
        self.comptes("encrypted")
        self.cache("encrypted")
        self.coffre = FauxCoffre()
        avant = fichiers(self.racine)
        sortie = self.purger("n")
        self.assertIn(
            t("mail_err_cache_key_missing").format(account="perso"), sortie
        )
        self.assertEqual(
            self.questions[-1],
            t("mail_cache_purge_no_key_confirm").format(account="perso"),
        )
        self.assertEqual(fichiers(self.racine), avant)
        self.assertEqual((self.coffre.values, self.coffre.writes), ({}, 0))
        self.purger("o")
        self.assertFalse(self.racine.exists())

    def test_an_unreadable_cache_is_erased_only_under_the_exclusive_lock(self):
        self.comptes("clear")
        self.racine.mkdir(parents=True)
        (self.racine / "cache.db").write_bytes(os.urandom(64))
        for copie in ("old", "new"):
            (self.ctl / copie / "perso").mkdir(parents=True)
            (self.ctl / copie / "perso" / "cache.db").write_bytes(b"clair")
        (self.ctl / "convert.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "phase": "swapping",
                    "source": "clear",
                    "target": "encrypted",
                    "started_at": 1,
                }
            )
        )
        with cache_exclusive("perso", self.base) as tenu:
            self.assertTrue(tenu)
            sortie = self.purger()
        self.assertIn(
            t("mail_cache_convert_busy_open").format(account="perso"), sortie
        )
        self.assertTrue((self.racine / "cache.db").exists())
        sortie = self.purger()
        self.assertIn(t("mail_purged"), sortie)
        self.assertFalse(self.racine.exists())
        self.assertEqual(sorted(os.listdir(self.ctl)), ["lock"])

    def test_an_unreadable_cache_still_written_is_not_erased(self):
        """La sonde ne lit pas une base qu'un autre processus tient en
        écriture sans le verrou d'usage : la purge refuse de l'effacer."""
        self.comptes("clear")
        self.cache("clear")
        etranger = sqlite3.connect(self.racine / "cache.db", timeout=0.05)
        self.addCleanup(etranger.close)
        etranger.execute("BEGIN EXCLUSIVE")
        with mock.patch.object(store_mod, "STORE_BUSY_TIMEOUT_S", 0.05):
            sortie = self.purger()
        etranger.rollback()
        self.assertIn(
            t("mail_cache_convert_busy_open").format(account="perso"), sortie
        )
        self.assertNotIn(t("mail_purged"), sortie)
        self.assertTrue((self.racine / "cache.db").exists())


class TestSummary(MenuCase):
    def test_an_unreadable_cache_is_not_flagged_refused(self):
        comptes = self.comptes("clear")
        self.racine.mkdir(parents=True)
        (self.racine / "cache.db").write_bytes(os.urandom(4096))
        (ligne,) = menu.cache_summary(comptes, base=self.base)
        self.assertEqual(ligne["inscribed"], store_mod.PROBE_UNKNOWN)
        self.assertFalse(ligne["refused"])

    def test_the_list_flags_a_refused_mismatch(self):
        self.comptes("clear", "clear")
        self.cache("encrypted")
        sortie = self.lancer(menu._cache_size_and_purge, [""])
        lignes = sortie.splitlines()
        refus = t("mail_cache_summary_refused").format(
            requested="clear", inscribed="encrypted"
        )
        self.assertTrue(lignes[0].startswith(f"  perso — {refus} — "))
        self.assertEqual(lignes[1], "  perso1 — clear — 0 ko")


class TestRefusalShownByOtherEntries(MenuCase):
    def test_stats_entry_prints_the_mismatch_message(self):
        self.comptes("clear")
        self.cache("encrypted")
        sortie = self.lancer(menu._show_stats, [])
        self.assertIn(
            t("mail_err_cache_mode_mismatch").format(
                account="perso", inscribed="encrypted", requested="clear"
            ),
            sortie,
        )


class TestMenuBase(MenuCase):
    def test_menu_entries_never_probe_the_default_base(self):
        from script.todo.mail.rules import storage

        comptes = self.comptes(None)
        self.cache("encrypted")

        def interdit():
            raise AssertionError("base par défaut sondée")

        with (
            mock.patch.object(store_mod, "default_base", interdit),
            mock.patch.object(menu, "default_base", interdit),
        ):
            self.lancer(menu.prompt_mail_rules, ["1"], prompts=["0"])
            regles = storage.base_of(
                Store(comptes[0], mode="encrypted", base=self.base)
            )
            self.lancer(menu._show_rules_log, [], comptes[0], regles)
            magasin = menu._open_store(self.todo, comptes[0], base=self.base)
            magasin.close()
            self.lancer(menu._show_stats, [])
            menu.cache_summary(comptes, base=self.base)
            self.lancer(
                menu.prompt_mail_cache, ["1", "encrypted"], prompts=["2", "0"]
            )
            self.lancer(menu.prompt_mail_cache, ["1", "o"], prompts=["3", "0"])
            self.lancer(menu.prompt_mail_cache, ["1", "n"], prompts=["4", "0"])

    def test_entries_open_after_their_own_recovery(self):
        comptes = self.comptes(None)
        self.cache("clear")
        (self.ctl / "new").mkdir(parents=True)
        neuve = Store(
            compte(),
            mode="encrypted",
            secrets=self.coffre,
            base=self.ctl / "new",
            lock_held=True,
        )
        neuve.open()
        neuve.close()
        (self.ctl / "convert.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "phase": "swapping",
                    "source": "clear",
                    "target": "encrypted",
                    "started_at": 1,
                }
            )
        )
        magasin = menu._open_store(self.todo, comptes[0], base=self.base)
        self.addCleanup(magasin.close)
        self.assertEqual(magasin.mode, "encrypted")
        self.assertEqual(sorted(os.listdir(self.ctl)), ["lock"])


class TestVaultForAnUnreadableProbe(MenuCase):
    def test_an_unreadable_probe_still_brings_the_vault(self):
        """La sonde ne lit rien, le compte ne demande rien : le coffre est
        passé quand même, et l'ouverture trouve le cache chiffré sous son
        verrou."""
        from script.todo.mail.store import PROBE_UNKNOWN

        comptes = self.comptes(None)
        self.cache("encrypted")
        with mock.patch.object(
            store_mod, "_probe_root", return_value=PROBE_UNKNOWN
        ):
            magasin = menu._open_store(self.todo, comptes[0], base=self.base)
        self.addCleanup(magasin.close)
        self.assertEqual(magasin.mode, "encrypted")


class TestDeleteAccount(MenuCase):
    def test_deleting_an_account_without_cache_creates_no_control_dir(self):
        self.comptes("clear")
        self.lancer(menu._delete_account, ["1"])
        self.assertFalse((self.base / CACHE_CTL_DIRNAME).exists())
        self.assertEqual(mail_accounts.load(), [])

    def test_deleting_an_account_finishes_a_pending_cleanup(self):
        self.comptes("encrypted")
        self.cache("encrypted")
        (self.ctl / "old" / "perso").mkdir(parents=True)
        (self.ctl / "old" / "perso" / "cache.db").write_bytes(b"ancienne")
        (self.ctl / "convert.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "phase": "cleaning",
                    "source": "clear",
                    "target": "encrypted",
                    "started_at": 1,
                }
            )
        )
        self.lancer(menu._delete_account, ["1"])
        self.assertFalse((self.ctl / "old").exists())
        self.assertFalse((self.ctl / "convert.json").exists())
        self.assertTrue((self.racine / "cache.db").exists())
        self.assertEqual(mail_accounts.load(), [])


if __name__ == "__main__":
    unittest.main()
