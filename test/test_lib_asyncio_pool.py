#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le pool de coroutines, et les deux retraits d'asyncio qui le tuaient.

Le drapeau `--max_process` de `run_parallel_test.py` et de
`show_evolution_module.py` passe par cette classe, et elle ne pouvait plus
tourner du tout : `asyncio.get_event_loop()` LÈVE hors d'une loop en marche
depuis Python 3.14, ce qui rendait l'instanciation impossible, et le mot-clé
`loop=` a été RETIRÉ d'`asyncio.wait` en Python 3.10, ce qui lève un
TypeError. Deux échecs à des étages différents, tous deux sur le chemin d'un
drapeau que l'aide annonce encore.

Ces tests exercent le pool pour de vrai — de vraies coroutines, une vraie
loop, un vrai résultat — parce que c'est la seule façon de prouver qu'un
retrait d'API ne le traverse plus. Ils n'affirment rien sur l'ordre des
résultats : le pool rend ce qui finit, dans l'ordre où cela finit.
"""

import asyncio
import io
import unittest
from contextlib import redirect_stdout

from script.lib_asyncio import AsyncioPool


async def rendre(valeur, delai=0):
    if delai:
        await asyncio.sleep(delai)
    return valeur


class TestLePoolTourne(unittest.TestCase):
    """Le pool s'instancie, tourne et se ferme sans loop fournie."""

    def _lancer(self, pool):
        """Exécute en silence : le pool imprime son état à chaque ajout."""
        with redirect_stdout(io.StringIO()):
            return pool.run_until_complete()

    def tearDown(self):
        asyncio.set_event_loop(None)

    def test_it_can_be_built_without_a_loop(self):
        """Le cas qui levait : construire hors de toute loop en marche."""
        pool = AsyncioPool(2)
        self.assertIsNone(pool._loop)

    def test_it_runs_more_coros_than_its_concurrency(self):
        pool = AsyncioPool(2)
        with redirect_stdout(io.StringIO()):
            for valeur in range(5):
                pool.add_coro(rendre(valeur))
        resultats = self._lancer(pool)
        pool.close()
        self.assertEqual(sorted(resultats), [0, 1, 2, 3, 4])

    def test_a_single_coro(self):
        pool = AsyncioPool(4)
        with redirect_stdout(io.StringIO()):
            pool.add_coro(rendre("seule"))
        resultats = self._lancer(pool)
        pool.close()
        self.assertEqual(resultats, ["seule"])

    def test_staggered_coros_all_come_back(self):
        """Des durées inégales : c'est là que FIRST_COMPLETED est exercé."""
        pool = AsyncioPool(2)
        with redirect_stdout(io.StringIO()):
            for valeur, delai in ((1, 0.03), (2, 0.01), (3, 0.02), (4, 0)):
                pool.add_coro(rendre(valeur, delai))
        resultats = self._lancer(pool)
        pool.close()
        self.assertEqual(sorted(resultats), [1, 2, 3, 4])


class TestLaFermeture(unittest.TestCase):
    """`close` ne ferme que ce que la classe a ouvert."""

    def tearDown(self):
        asyncio.set_event_loop(None)

    def test_close_before_any_run_is_harmless(self):
        AsyncioPool(2).close()

    def test_close_closes_the_loop_it_created(self):
        pool = AsyncioPool(1)
        with redirect_stdout(io.StringIO()):
            pool.add_coro(rendre(1))
            pool.run_until_complete()
        boucle = pool._loop
        pool.close()
        self.assertTrue(boucle.is_closed())

    def test_a_borrowed_loop_is_left_open(self):
        """Une loop reçue appartient à l'appelant, qui compte encore dessus."""
        boucle = asyncio.new_event_loop()
        try:
            pool = AsyncioPool(1, loop=boucle)
            with redirect_stdout(io.StringIO()):
                pool.add_coro(rendre(1))
                pool.run_until_complete()
            pool.close()
            self.assertFalse(boucle.is_closed())
        finally:
            boucle.close()


if __name__ == "__main__":
    unittest.main()
