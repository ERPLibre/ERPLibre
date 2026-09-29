#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Synchronisation de plusieurs comptes de front.

Chaque compte a son propre socket et son cache verrouillé : les faire
avancer ensemble transforme des attentes réseau en série en une seule
attente. Ce qui doit rester vrai : un compte qui échoue n'emporte pas les
autres, et deux passes ne se chevauchent jamais sur un même compte.
"""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def rapport(nouveaux=0, erreurs=None, purges=None):
    return SimpleNamespace(
        new_messages=nouveaux, errors=erreurs or [], purged=purges or []
    )


class FausseSession:
    """Une session dont la passe DURE, pour que le parallélisme se voie."""

    def __init__(self, nom, duree=0.20, leve=None, en_ligne=True):
        self.account = SimpleNamespace(name=nom)
        self.online = en_ligne
        self.error = "hors ligne"
        self.duree = duree
        self.leve = leve
        self.debuts = []

    def sync(self, progress=None):
        self.debuts.append(time.time())
        time.sleep(self.duree)
        if self.leve:
            raise self.leve
        return rapport(nouveaux=1)

    def close(self):
        pass


class TestMenuSyncsInParallel(unittest.TestCase):
    def _lancer(self, sessions):
        import script.todo.mail.menu as menu

        sorties = []
        with patch.object(
            menu, "_load_accounts", return_value=[s.account for s in sessions]
        ), patch(
            "script.todo.mail.tui.open_sessions", return_value=sessions
        ), patch.object(
            menu, "secret_store_for", return_value=MagicMock()
        ), patch(
            "builtins.print", side_effect=lambda *a: sorties.append(str(a[0]))
        ):
            depart = time.time()
            menu._sync_now(MagicMock())
            return time.time() - depart, "\n".join(sorties)

    def test_four_accounts_take_far_less_than_four_passes(self):
        """La mesure qui décide : en série il faudrait la somme des durées."""
        sessions = [FausseSession(f"c{i}") for i in range(4)]
        duree, _ = self._lancer(sessions)
        self.assertLess(duree, 0.20 * 4 * 0.75)

    def test_a_single_account_is_not_sent_through_a_pool(self):
        sessions = [FausseSession("seul")]
        _, sortie = self._lancer(sessions)
        self.assertIn("seul", sortie)

    def test_one_failing_account_does_not_stop_the_others(self):
        """Sans ce rattrapage, une exception dans un fil remonterait à la
        récupération du résultat et emporterait les comptes suivants."""
        sessions = [
            FausseSession("bon1"),
            FausseSession("casse", leve=OSError("réseau coupé")),
            FausseSession("bon2"),
        ]
        _, sortie = self._lancer(sessions)
        self.assertIn("bon1", sortie)
        self.assertIn("bon2", sortie)
        self.assertIn("réseau coupé", sortie)

    def test_an_offline_account_is_reported_not_synced(self):
        sessions = [FausseSession("dodo", en_ligne=False)]
        _, sortie = self._lancer(sessions)
        self.assertIn("hors ligne", sortie)
        self.assertEqual(sessions[0].debuts, [])

    def test_each_account_output_stays_in_one_block(self):
        """Un entrelacement de lignes venues de plusieurs comptes serait
        illisible : chaque bloc est rendu d'un seul tenant."""
        sessions = [
            FausseSession("a"),
            FausseSession("b", leve=OSError("boum")),
        ]
        _, sortie = self._lancer(sessions)
        for bloc in sortie.split("\n"):
            self.assertLessEqual(sum(bloc.count(n) for n in ("a :", "b :")), 1)


class TestTheCapIsRespected(unittest.TestCase):
    def test_the_pool_never_exceeds_the_cap(self):
        """Plafonné : trente connexions simultanées se font refuser par les
        fournisseurs et n'accélèrent rien."""
        import script.todo.mail.menu as menu
        from script.todo.mail.tui import SYNC_PARALLELE

        vivants = []
        maximum = [0]
        verrou = threading.Lock()

        class Compteuse(FausseSession):
            def sync(self, progress=None):
                with verrou:
                    vivants.append(1)
                    maximum[0] = max(maximum[0], len(vivants))
                time.sleep(0.05)
                with verrou:
                    vivants.pop()
                return rapport()

        sessions = [Compteuse(f"c{i}") for i in range(SYNC_PARALLELE + 4)]
        with patch.object(
            menu, "_load_accounts", return_value=[s.account for s in sessions]
        ), patch(
            "script.todo.mail.tui.open_sessions", return_value=sessions
        ), patch.object(
            menu, "secret_store_for", return_value=MagicMock()
        ), patch(
            "builtins.print"
        ):
            menu._sync_now(MagicMock())
        self.assertLessEqual(maximum[0], SYNC_PARALLELE)
        self.assertGreater(maximum[0], 1)


if __name__ == "__main__":
    unittest.main()
