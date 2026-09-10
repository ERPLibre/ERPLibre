#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les serveurs MCP : ce qui se lit sans réseau, et ce qui n'est pas construit.

Deux populations cohabitent et une seule est lisible sur le disque. Les
déclarations locales vivent dans la configuration ; les connecteurs du compte
n'y sont dans AUCUN fichier — sur la machine où ce module a été écrit, la
configuration n'en déclarait aucun et l'interrogation en annonçait huit. Le
module ne doit donc jamais faire croire qu'une liste vide veut dire « aucun
serveur ».

Ce que ces tests défendent surtout, c'est une ABSENCE de commandes. `add`,
`remove`, `login` et `logout` changent la configuration ou ouvrent une
authentification. Un menu qui les propose à côté d'une simple liste invite à
en lancer une par erreur, et ce module ne sait pas les construire.

Les fichiers de configuration sont INJECTÉS : aucun test ne lit celui du
compte réel.
"""

import unittest

from script.todo.assistant.agents import mcp


def _charger(fichiers):
    return lambda chemin: fichiers.get(chemin, {})


class TestLesDeclarationsLocales(unittest.TestCase):
    def test_a_global_server_is_read(self):
        serveurs = mcp.declares(
            compte="/c",
            charger=_charger(
                {
                    "/c": {
                        "mcpServers": {
                            "un-serveur": {
                                "type": "http",
                                "url": "https://exemple.invalid/mcp",
                            }
                        }
                    }
                }
            ),
        )
        (serveur,) = serveurs
        self.assertEqual(serveur.nom, "un-serveur")
        self.assertEqual(serveur.origine, "global")
        self.assertEqual(serveur.transport, "http")

    def test_a_project_server_names_its_project(self):
        """L'origine décide de ce qu'un geste toucherait."""
        serveurs = mcp.declares(
            compte="/c",
            charger=_charger(
                {
                    "/c": {
                        "projects": {
                            "/home/compte/git/projet": {
                                "mcpServers": {"local": {"command": "npx"}}
                            }
                        }
                    }
                }
            ),
        )
        (serveur,) = serveurs
        self.assertEqual(serveur.origine, "projet")
        self.assertEqual(serveur.transport, "stdio")

    def test_a_repository_server_is_read_from_the_repository(self):
        serveurs = mcp.declares(
            compte="/c",
            depot="/d",
            charger=_charger(
                {"/d/.mcp.json": {"mcpServers": {"du-depot": {}}}}
            ),
        )
        (serveur,) = serveurs
        self.assertEqual(serveur.origine, mcp.DEPOT)

    def test_the_transport_is_deduced_only_from_the_target(self):
        """Une URL est du http, une commande du stdio. Rien d'autre n'est
        supposé : un bloc muet rend une cible vide, et l'écran affiche un
        tiret plutôt qu'un chemin inventé."""
        serveurs = mcp.declares(
            compte="/c",
            charger=_charger({"/c": {"mcpServers": {"muet": {}}}}),
        )
        (serveur,) = serveurs
        self.assertEqual(serveur.cible, "")
        self.assertEqual(serveur.transport, "")

    def test_a_block_that_is_not_an_object(self):
        serveurs = mcp.declares(
            compte="/c",
            charger=_charger({"/c": {"mcpServers": {"casse": "texte"}}}),
        )
        self.assertEqual(serveurs[0].cible, "")

    def test_an_unreadable_configuration_declares_nothing(self):
        self.assertEqual(mcp.declares(compte="/introuvable"), [])

    def test_nothing_declared_is_not_nothing_configured(self):
        """Une liste vide ne veut pas dire « aucun serveur » : les connecteurs
        du compte ne sont dans aucun fichier, et seule l'interrogation les
        connaît. C'est l'écran qui doit le dire, et il le dit."""
        self.assertEqual(mcp.declares(compte="/c", charger=_charger({})), [])

    def test_the_order_is_stable(self):
        serveurs = mcp.declares(
            compte="/c",
            charger=_charger(
                {
                    "/c": {
                        "mcpServers": {"b": {}, "a": {}},
                    }
                }
            ),
        )
        self.assertEqual([s.nom for s in serveurs], ["a", "b"])


class TestLesCommandesConstruites(unittest.TestCase):
    def test_the_listing_is_read_only(self):
        self.assertEqual(mcp.argv_lister(), ["claude", "mcp", "list"])

    def test_the_detail_is_read_only(self):
        self.assertEqual(
            mcp.argv_detail("un-serveur"),
            ["claude", "mcp", "get", "un-serveur"],
        )

    def test_a_name_that_looks_like_a_flag_is_refused(self):
        """Un nom saisi ne doit pas devenir une option de la commande."""
        for mauvais in ("--help", "-x", ""):
            with self.assertRaises(ValueError, msg=mauvais):
                mcp.argv_detail(mauvais)

    def test_no_command_that_changes_anything_exists(self):
        """`add`, `remove`, `login`, `logout` restent au CLI, où l'on va
        exprès. Les proposer à côté d'une liste invite à en lancer une par
        erreur, et ce module ne sait pas les construire."""
        construits = {nom for nom in dir(mcp) if nom.startswith("argv_")}
        self.assertEqual(construits, {"argv_lister", "argv_detail"})
        with open(mcp.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for interdit in ('"add"', '"remove"', '"login"', '"logout"'):
            self.assertNotIn(interdit, source, interdit)


if __name__ == "__main__":
    unittest.main()
