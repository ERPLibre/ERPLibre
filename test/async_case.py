#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""`AsyncCase` : un `IsolatedAsyncioTestCase` sans le mode debug d'asyncio.

`IsolatedAsyncioTestCase` ouvre sa boucle en mode debug. Ce mode capture
une trace de pile à chaque tâche et à chaque rappel, et relit les lignes
sources de chacune : sur une application Textual montée, qui en crée des
milliers, il coûte de 20 à 30 % de la durée du fichier. Ce qu'il signale
en échange — un rappel lent, une coroutine jamais attendue — n'est pas ce
que ces tests vérifient, et une coroutine jamais attendue reste signalée
par l'avertissement ordinaire de Python.

Sans préfixe `test_`, le lanceur unitaire ne le prend pas pour un fichier
de tests.
"""

import asyncio
import unittest


class AsyncCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        asyncio.get_running_loop().set_debug(False)
