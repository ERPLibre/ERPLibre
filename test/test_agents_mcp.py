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

    def test_a_name_a_shell_would_read_is_refused(self):
        """Le nom saisi est recollé en une LIGNE de shell par l'appelant.

        Refuser le nom vide et celui qui ouvre sur un tiret ne suffit donc
        pas : tout ce qu'un shell interprète doit tomber ici, faute de quoi
        un point-virgule transforme une lecture en n'importe quelle commande.
        """
        for mauvais in (
            "serveur; echo pris",
            "serveur && echo pris",
            "serveur | cat",
            "$(echo pris)",
            "`echo pris`",
            "serveur > /tmp/pris",
            "serveur\nautre",
            "serveur pris",
            "'serveur'",
            "..",
        ):
            with self.assertRaises(ValueError, msg=mauvais):
                mcp.argv_detail(mauvais)

    def test_an_ordinary_name_still_passes(self):
        """Refuser trop refuserait la fonctionnalité : les noms réels
        passent."""
        for bon in ("github", "mon-serveur", "serveur_2", "api.exemple", "a"):
            self.assertEqual(mcp.argv_detail(bon)[-1], bon, bon)

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


class TestLUrlNeSortPasAvecSonJeton(unittest.TestCase):
    """Une passerelle MCP hébergée porte couramment son jeton DANS son URL.

    En paramètre de requête, ou en « compte:jeton@ » devant l'hôte. Recopier
    l'URL telle quelle à l'écran rend copiable un authentifiant que personne
    n'a demandé à voir. Le schéma, l'hôte et le chemin suffisent à reconnaître
    un serveur, et c'est tout ce qui est gardé.

    Le témoin est inventé, et sa présence dans l'entrée est ce qui prouve
    qu'il ne ressort pas.
    """

    TEMOIN = "jeton-invente-qui-ne-doit-pas-sortir"

    def test_a_query_string_is_cut(self):
        url = f"https://passerelle.exemple/sse?api_key={self.TEMOIN}"
        garde = mcp.sans_authentifiant(url)
        self.assertNotIn(self.TEMOIN, garde)
        self.assertTrue(garde.startswith("https://passerelle.exemple/sse"))

    def test_a_fragment_is_cut(self):
        url = f"https://passerelle.exemple/sse#{self.TEMOIN}"
        self.assertNotIn(self.TEMOIN, mcp.sans_authentifiant(url))

    def test_the_credentials_before_the_host_are_cut(self):
        url = f"https://compte:{self.TEMOIN}@passerelle.exemple/sse"
        garde = mcp.sans_authentifiant(url)
        self.assertNotIn(self.TEMOIN, garde)
        self.assertNotIn("compte", garde)
        self.assertIn("passerelle.exemple", garde)

    def test_what_remains_is_marked_as_cut(self):
        """Sans marque, on croirait lire l'URL entière."""
        url = f"https://passerelle.exemple/sse?api_key={self.TEMOIN}"
        self.assertTrue(mcp.sans_authentifiant(url).endswith("…"))

    def test_a_plain_url_is_left_alone(self):
        url = "https://passerelle.exemple/sse"
        self.assertEqual(mcp.sans_authentifiant(url), url)

    def test_the_declared_server_carries_the_cut_url(self):
        """C'est la STRUCTURE qui est dépouillée : l'écran ne peut pas
        montrer ce qu'elle ne porte plus."""
        (serveur,) = mcp.declares(
            compte="/c",
            charger=_charger(
                {
                    "/c": {
                        "mcpServers": {
                            "passerelle": {
                                "url": (
                                    "https://passerelle.exemple/sse"
                                    f"?api_key={self.TEMOIN}"
                                )
                            }
                        }
                    }
                }
            ),
        )
        self.assertNotIn(self.TEMOIN, serveur.cible)
        self.assertEqual(serveur.transport, "http")

    def test_a_local_command_is_not_touched(self):
        """Une commande n'est pas une URL : la découper la casserait."""
        (serveur,) = mcp.declares(
            compte="/c",
            charger=_charger(
                {"/c": {"mcpServers": {"local": {"command": "npx"}}}}
            ),
        )
        self.assertEqual(serveur.cible, "npx")
        self.assertEqual(serveur.transport, "stdio")


if __name__ == "__main__":
    unittest.main()
