#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu de la forge : ce qu'il montre, et ce qu'il ne montre jamais.

Ni forge, ni coffre, ni jeton. Le menu est instancié sans passer par
`TODO.__init__`, et ses collaborateurs sont remplacés : ce qui est éprouvé
est ce qui S'AFFICHE, sur des verdicts fabriqués.

DEUX CHOSES QUE CES ÉPREUVES TIENNENT.

LE JETON NE S'AFFICHE JAMAIS — ni en écho de saisie, ni dans une liste, ni
dans un résumé. Un menu se déroule souvent devant quelqu'un, et sa sortie se
colle dans un rapport de panne.

CHAQUE VERDICT A SA PHRASE, et la phrase dit QUOI FAIRE. Un verdict ajouté
au vocabulaire sans phrase doit se voir ici, et non se taire chez
l'utilisateur sous la forme d'une ligne vide qui se lit comme un succès.
"""

import contextlib
import io as _io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.forge import api  # noqa: E402
from script.forge.api import Reponse  # noqa: E402
from script.todo import forge_menu, todo_i18n  # noqa: E402
from script.todo.forge_menu import (  # noqa: E402
    SENTENCES,
    ForgeMenuMixin,
    profile_line,
    verdict_sentence,
)

JETON = "jeton-de-banc-0123456789"
PROFIL = {
    "name": "atelier",
    "url": "https://forge.example",
    "owner": "erplibre",
    "verify_tls": True,
    "allow_plaintext": False,
    "driver": "forgejo",
}


class MenuDeBanc(ForgeMenuMixin):
    """Le mixin seul, avec les collaborateurs que TODO lui donnerait."""

    def __init__(self, client=None, jeton=JETON):
        self.kdbx_manager = None
        self._client_de_banc = client
        self._jeton_de_banc = jeton

    def _forge_token(self, name, quiet=False):
        return self._jeton_de_banc

    def _forge_client(self, name):
        return PROFIL, self._client_de_banc

    def _is_yes(self, reponse):
        return (reponse or "").strip().lower() in ("o", "oui", "y", "yes")


class ClientDeBanc:
    def __init__(self, reponse):
        self.reponse = reponse

    def whoami(self):
        return self.reponse

    def repos(self):
        return self.reponse


def sortie(fonction, *args, **kwargs):
    """Ce que la fonction IMPRIME, sans qu'elle atteigne un terminal."""
    tampon = _io.StringIO()
    with contextlib.redirect_stdout(tampon):
        fonction(*args, **kwargs)
    return tampon.getvalue()


class CasDeMenu(unittest.TestCase):
    """La langue est ÉPINGLÉE, en anglais.

    Les clés de traduction SONT les chaînes anglaises : y assurer les
    assertions les rend lisibles et indépendantes de la langue que le
    processus a choisie — un test qui compare un mot français passe ou
    tombe selon ce qu'une autre épreuve a laissé dans `_current_lang`.
    """

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"


class TestChaqueVerdictADeQuoiAgir(CasDeMenu):
    def test_every_verdict_of_the_vocabulary_has_a_sentence(self):
        """Un verdict ajouté sans phrase se tairait chez l'utilisateur."""
        self.assertTrue(api.VERDICTS, "vocabulaire vidé : rien n'est prouvé")
        for verdict in api.VERDICTS:
            with self.subTest(verdict=verdict):
                self.assertTrue(verdict_sentence(verdict).strip())

    def test_the_table_has_no_stale_entry(self):
        """Une phrase pour un verdict retiré devient un cimetière."""
        self.assertEqual(set(), set(SENTENCES) - set(api.VERDICTS))

    def test_an_unknown_verdict_raises_rather_than_prints_nothing(self):
        """Une chaîne vide s'afficherait comme une ligne blanche, qui se
        lit comme un succès."""
        with self.assertRaises(KeyError):
            verdict_sentence("verdict-jamais-declare")

    def test_the_private_range_sentence_names_the_setting_not_the_token(self):
        """LE PIÈGE : dire « jeton refusé » enverrait régénérer un jeton
        parfaitement valide."""
        phrase = SENTENCES[api.LOCALNETWORK_REFUSED]
        self.assertIn("ALLOW_LOCALNETWORKS", phrase)
        self.assertIn("NOT the token", phrase)

    def test_the_tls_sentence_does_not_advise_turning_it_off(self):
        """Le conseil qui vient en premier à l'esprit est le mauvais : il
        envoie le jeton à qui répond à la place de la forge."""
        phrase = SENTENCES[api.TLS_UNTRUSTED]
        self.assertIn("Trust the authority", phrase)

    def test_every_sentence_says_something(self):
        for verdict, phrase in SENTENCES.items():
            with self.subTest(verdict=verdict):
                self.assertGreater(len(phrase.strip()), 10, verdict)


class TestLeJetonNeSaffichePas(CasDeMenu):
    def test_the_profile_line_says_present_and_not_the_value(self):
        ligne = profile_line(PROFIL, True)
        self.assertNotIn(JETON, ligne)
        self.assertIn("token stored", ligne)

    def test_the_profile_line_says_absent_too(self):
        """Contrôle positif : toujours dire « déposé » ne dirait rien."""
        self.assertIn("no token", profile_line(PROFIL, False))

    def test_checking_never_echoes_it(self):
        menu = MenuDeBanc(ClientDeBanc(Reponse(api.OK, data={"login": "x"})))
        with patch.object(menu, "_forge_select_profile", return_value="a"):
            texte = sortie(menu._forge_check)
        self.assertNotIn(JETON, texte)

    def test_listing_repositories_never_echoes_it(self):
        menu = MenuDeBanc(ClientDeBanc(Reponse(api.OK, data=[])))
        with patch.object(menu, "_forge_select_profile", return_value="a"):
            texte = sortie(menu._forge_list_repos)
        self.assertNotIn(JETON, texte)

    def test_the_token_prompt_does_not_echo(self):
        """`input` écrirait la saisie à l'écran, donc dans un partage
        d'écran et dans le tampon du terminal."""
        import ast

        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        chemin = os.path.join(racine, "script", "todo", "forge_menu.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        depot = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_forge_store_token"
        ]
        self.assertEqual(1, len(depot), "ancre absente ou dédoublée")
        appels = [
            noeud.func.id
            for noeud in ast.walk(depot[0])
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertNotIn("input", appels)
        attributs = [
            noeud.func.attr
            for noeud in ast.walk(depot[0])
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
        ]
        self.assertIn("getpass", attributs)


class TestCeQueLaLigneDeProfilMontre(CasDeMenu):
    def test_a_cautious_profile_shows_no_warning_mark(self):
        """Une marque permanente ne marque plus rien."""
        ligne = profile_line(PROFIL, True)
        self.assertNotIn("TLS UNVERIFIED", ligne)
        self.assertNotIn("PLAINTEXT", ligne)

    def test_an_unverified_profile_says_so(self):
        """C'est le seul champ dont l'oubli se paie en secret : une
        vérification coupée ne se voit nulle part ailleurs."""
        ligne = profile_line({**PROFIL, "verify_tls": False}, True)
        self.assertIn("TLS UNVERIFIED", ligne)

    def test_a_plaintext_profile_says_so(self):
        ligne = profile_line({**PROFIL, "allow_plaintext": True}, True)
        self.assertIn("PLAINTEXT", ligne)

    def test_the_address_and_the_owner_are_shown(self):
        ligne = profile_line(PROFIL, True)
        self.assertIn("https://forge.example", ligne)
        self.assertIn("erplibre", ligne)

    def test_a_field_missing_does_not_crash(self):
        self.assertTrue(profile_line({}, False))


class TestCeQueLeMenuEcritSurUnVerdict(CasDeMenu):
    def test_a_failure_is_written_as_its_sentence(self):
        menu = MenuDeBanc(
            ClientDeBanc(Reponse(api.LOCALNETWORK_REFUSED, detail="refus"))
        )
        with patch.object(menu, "_forge_select_profile", return_value="a"):
            texte = sortie(menu._forge_check)
        self.assertIn("ALLOW_LOCALNETWORKS", texte)

    def test_the_forge_own_words_are_shown_too(self):
        """La phrase oriente, le détail prouve. Sans le détail, un cas non
        prévu se lit comme le cas prévu."""
        menu = MenuDeBanc(
            ClientDeBanc(Reponse(api.REFUSED, detail="mot de la forge"))
        )
        with patch.object(menu, "_forge_select_profile", return_value="a"):
            texte = sortie(menu._forge_check)
        self.assertIn("mot de la forge", texte)

    def test_a_success_names_the_account(self):
        menu = MenuDeBanc(
            ClientDeBanc(Reponse(api.OK, data={"login": "compte-de-banc"}))
        )
        with patch.object(menu, "_forge_select_profile", return_value="a"):
            texte = sortie(menu._forge_check)
        self.assertIn("compte-de-banc", texte)

    def test_a_failed_listing_does_not_print_a_count(self):
        """« 0 dépôts » sur une panne se lit comme une forge vide."""
        menu = MenuDeBanc(ClientDeBanc(Reponse(api.BAD_TOKEN, detail="x")))
        with patch.object(menu, "_forge_select_profile", return_value="a"):
            texte = sortie(menu._forge_list_repos)
        self.assertNotIn("0 ", texte)
        self.assertIn(SENTENCES[api.BAD_TOKEN][:30], texte)

    def test_an_empty_forge_does_print_a_count(self):
        """Contrôle positif : une forge vraiment vide doit le dire."""
        menu = MenuDeBanc(ClientDeBanc(Reponse(api.OK, data=[])))
        with patch.object(menu, "_forge_select_profile", return_value="a"):
            texte = sortie(menu._forge_list_repos)
        self.assertIn("0", texte)

    def test_a_public_repository_is_marked(self):
        """Un dépôt de client public est visible le temps qu'on s'en
        aperçoive : la liste doit le faire remarquer."""
        menu = MenuDeBanc(
            ClientDeBanc(
                Reponse(
                    api.OK,
                    data=[
                        {"full_name": "o/prive", "private": True},
                        {"full_name": "o/ouvert", "private": False},
                    ],
                )
            )
        )
        with patch.object(menu, "_forge_select_profile", return_value="a"):
            texte = sortie(menu._forge_list_repos)
        self.assertIn("PUBLIC", texte)
        self.assertIn("o/ouvert", texte)


class TestLaFrontiereAvecLeModuleDeForge(CasDeMenu):
    """Ici on demande et on affiche ; là-bas on décide et on appelle."""

    def test_the_menu_builds_no_url_and_reads_no_status_code(self):
        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        chemin = os.path.join(racine, "script", "todo", "forge_menu.py")
        with open(chemin, encoding="utf-8") as fichier:
            source = fichier.read()
        for interdit in (
            "/api/v1",
            "status_code",
            "requests",
            "Authorization",
        ):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, source)

    def test_the_module_is_reachable_from_the_menu(self):
        """Le motif à éviter : un mixin écrit, éprouvé, et jamais composé."""
        import sys as _sys

        _sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.assertTrue(issubclass(TODO, forge_menu.ForgeMenuMixin))
        self.assertTrue(hasattr(TODO, "prompt_execute_forge"))

    def test_the_git_menu_declares_where_the_entry_leads(self):
        """Un numéro codé en dur mènerait ailleurs dès qu'une entrée de
        todo.json s'ajoute : l'entrée porte sa destination."""
        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        with open(
            os.path.join(racine, "script", "todo", "todo.py"),
            encoding="utf-8",
        ) as fichier:
            source = fichier.read()
        self.assertIn('"method": "prompt_execute_forge"', source)


if __name__ == "__main__":
    unittest.main()
