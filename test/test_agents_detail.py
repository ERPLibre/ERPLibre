#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un appel d'outil a fait, retrouvé sans rien avoir collecté.

Le journal des hooks garde `tool_use_id` et RIEN d'autre de l'appel : ni la
commande, ni la réponse. Y écrire `tool_input` mettrait chaque commande shell
de la machine sur le disque pour quatorze jours, ce qui est garder et non
montrer. Ce module va donc les chercher dans la transcription, où Claude Code
les a déjà écrites, au moment où quelqu'un les demande.

Trois choses que ces tests défendent, et qu'aucune ne se devine :

**Un appel sur trois vit ailleurs.** Les outils lancés par un SOUS-AGENT
s'écrivent dans le fichier de celui-ci, sous le répertoire de la session,
alors que le hook les annonce sous l'identifiant de la session PARENTE.
Chercher dans la seule transcription principale laisse environ un tiers des
appels introuvables.

**Les deux moitiés sont dans des messages différents.** Le `tool_use` vit dans
un message d'assistant, le `tool_result` dans la réponse qui suit. Une moitié
peut manquer : un appel en cours n'a pas de résultat.

**Absent et vide ne se disent pas pareil.** Une sortie absente est un appel
encore en cours ; une sortie vide est une commande qui n'a rien répondu. Les
confondre fait chercher une panne là où il n'y a qu'un silence.
"""

import json
import unittest

from script.todo.assistant.agents import detail as dl

APPEL = "toolu_01aaaaaaaaaaaaaaaaaaaaaa"
AUTRE = "toolu_01bbbbbbbbbbbbbbbbbbbbbb"


def _assistant(identifiant=APPEL, nom="Bash", **entree):
    return {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": identifiant,
                    "name": nom,
                    "input": entree,
                }
            ]
        },
    }


def _resultat(
    identifiant=APPEL, contenu="deux lignes\nde sortie", erreur=False
):
    return {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": identifiant,
                    "content": contenu,
                    "is_error": erreur,
                }
            ]
        },
    }


def _fichier(objets):
    """Un faux fichier ligne à ligne, sans toucher au disque."""
    texte = "\n".join(json.dumps(o) for o in objets)

    class Faux:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return iter(texte.splitlines(keepends=True))

    return lambda chemin: Faux()


class TestOuChercher(unittest.TestCase):
    """Deux endroits, et l'oubli du second cache un appel sur trois."""

    def test_the_main_transcript_comes_first(self):
        chemins = dl.chemins_de_session(
            "une-session",
            lister=lambda motif, recursive=False: (
                ["/p/une-session.jsonl"]
                if motif.endswith("une-session.jsonl")
                else ["/p/une-session/subagents/a/agent-1.jsonl"]
            ),
        )
        self.assertEqual(chemins[0], "/p/une-session.jsonl")
        self.assertEqual(len(chemins), 2)

    def test_the_subagent_files_are_searched_too(self):
        """Un outil lancé par un sous-agent s'écrit chez lui, tandis que le
        hook l'annonce sous l'identifiant de la session parente."""
        chemins = dl.chemins_de_session(
            "une-session",
            lister=lambda motif, recursive=False: (
                [] if motif.endswith("une-session.jsonl") else ["/p/s/a.jsonl"]
            ),
        )
        self.assertEqual(chemins, ["/p/s/a.jsonl"])

    def test_a_file_named_twice_is_listed_once(self):
        chemins = dl.chemins_de_session(
            "une-session", lister=lambda motif, recursive=False: ["/p/x.jsonl"]
        )
        self.assertEqual(chemins, ["/p/x.jsonl"])

    def test_no_session_is_no_path(self):
        self.assertEqual(dl.chemins_de_session(""), [])
        self.assertEqual(dl.chemins_de_session(None), [])


class TestCeQuiEstRetrouve(unittest.TestCase):
    def _lire(self, objets, identifiant=APPEL):
        return dl.lire("/p/x.jsonl", identifiant, ouvrir=_fichier(objets))

    def test_the_command_and_its_answer_are_joined(self):
        """Les deux moitiés vivent dans des messages différents."""
        trouve = self._lire([_assistant(command="echo bonjour"), _resultat()])
        self.assertTrue(trouve.trouve)
        self.assertEqual(trouve.outil, "Bash")
        self.assertEqual(trouve.commande, "echo bonjour")
        self.assertEqual(trouve.sortie, "deux lignes\nde sortie")
        self.assertFalse(trouve.erreur)

    def test_another_call_in_the_same_file_is_ignored(self):
        trouve = self._lire(
            [
                _assistant(AUTRE, command="pas celle-ci"),
                _resultat(AUTRE, contenu="ni celle-ci"),
                _assistant(command="celle-ci"),
            ]
        )
        self.assertEqual(trouve.commande, "celle-ci")
        self.assertIsNone(trouve.sortie)

    def test_a_call_still_running_has_no_answer(self):
        """None et non "" : la commande n'a pas répondu RIEN, elle n'a pas
        encore répondu."""
        trouve = self._lire([_assistant(command="sleep 60")])
        self.assertTrue(trouve.trouve)
        self.assertIsNone(trouve.sortie)

    def test_a_command_that_answered_nothing_is_an_empty_string(self):
        trouve = self._lire(
            [_assistant(command="true"), _resultat(contenu="")]
        )
        self.assertEqual(trouve.sortie, "")
        self.assertIsNotNone(trouve.sortie)

    def test_an_error_is_reported(self):
        trouve = self._lire(
            [
                _assistant(command="faux"),
                _resultat(contenu="oups", erreur=True),
            ]
        )
        self.assertTrue(trouve.erreur)

    def test_an_answer_in_blocks_is_joined(self):
        """La réponse vient en chaîne, ou en liste de blocs."""
        trouve = self._lire(
            [
                _assistant(command="x"),
                _resultat(
                    contenu=[
                        {"type": "text", "text": "une"},
                        {"type": "image", "source": {}},
                        {"type": "text", "text": "deux"},
                    ]
                ),
            ]
        )
        self.assertEqual(trouve.sortie, "une\ndeux")

    def test_a_tool_without_a_command_shows_its_first_textual_field(self):
        """Seul Bash nomme son argument « command » ; montrer le premier
        champ textuel vaut mieux que de ne rien montrer."""
        trouve = self._lire(
            [_assistant(nom="Read", file_path="/un/fichier.py")]
        )
        self.assertEqual(trouve.outil, "Read")
        self.assertEqual(trouve.commande, "/un/fichier.py")

    def test_a_description_is_kept_beside_the_command(self):
        trouve = self._lire(
            [_assistant(command="x", description="Ce que ça fait")]
        )
        self.assertEqual(trouve.description, "Ce que ça fait")

    def test_nothing_found_is_an_empty_detail(self):
        trouve = self._lire([_assistant(AUTRE, command="x")])
        self.assertFalse(trouve.trouve)
        self.assertIsNone(trouve.sortie)

    def test_a_broken_line_is_skipped(self):
        """Une transcription en cours d'écriture finit sur une ligne coupée."""

        class Faux:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def __iter__(self):
                return iter(
                    [
                        "{ ceci porte " + APPEL + " et n'est pas du JSON\n",
                        json.dumps(_assistant(command="bonne")) + "\n",
                    ]
                )

        trouve = dl.lire("/p/x.jsonl", APPEL, ouvrir=lambda c: Faux())
        self.assertEqual(trouve.commande, "bonne")

    def test_an_unreadable_file_does_not_raise(self):
        def refuser(chemin):
            raise OSError("refusé")

        self.assertFalse(dl.lire("/p/x", APPEL, ouvrir=refuser).trouve)

    def test_nothing_asked_is_nothing_read(self):
        self.assertFalse(dl.lire("", APPEL).trouve)
        self.assertFalse(dl.lire("/p/x", "").trouve)


class TestLaRechercheSArrete(unittest.TestCase):
    """Un identifiant n'est écrit qu'une fois : balayer la suite ne change
    rien qu'en temps."""

    class Appel:
        session = "une-session"
        identifiant = APPEL

    def test_the_first_file_that_answers_wins(self):
        lus = []

        def ouvrir(chemin):
            lus.append(chemin)
            objets = (
                [_assistant(command="trouvée")] if chemin == "/p/1" else []
            )
            return _fichier(objets)(chemin)

        trouve = dl.pour(
            self.Appel(),
            lister=lambda motif, recursive=False: ["/p/1", "/p/2"],
            ouvrir=ouvrir,
        )
        self.assertEqual(trouve.commande, "trouvée")
        self.assertEqual(lus, ["/p/1"], "le second n'est pas ouvert")

    def test_the_next_file_is_tried_when_the_first_says_nothing(self):
        def ouvrir(chemin):
            objets = (
                [_assistant(command="au second")] if chemin == "/p/2" else []
            )
            return _fichier(objets)(chemin)

        trouve = dl.pour(
            self.Appel(),
            lister=lambda motif, recursive=False: ["/p/1", "/p/2"],
            ouvrir=ouvrir,
        )
        self.assertEqual(trouve.commande, "au second")

    def test_nowhere_is_an_empty_detail(self):
        trouve = dl.pour(
            self.Appel(), lister=lambda motif, recursive=False: []
        )
        self.assertFalse(trouve.trouve)


class TestCeQueLEcranAffiche(unittest.TestCase):
    def test_a_command_becomes_one_line(self):
        """Une commande multiligne casserait la rangée en trois."""
        self.assertEqual(
            dl.une_ligne("echo un\n  echo deux\n\techo trois"),
            "echo un echo deux echo trois",
        )

    def test_a_long_command_says_it_was_cut(self):
        coupe = dl.une_ligne("x" * 200, largeur=20)
        self.assertEqual(len(coupe), 20)
        self.assertTrue(coupe.endswith("…"))

    def test_nothing_is_nothing(self):
        self.assertEqual(dl.une_ligne(""), "")
        self.assertEqual(dl.une_ligne(None), "")

    def test_a_bounded_output_says_what_it_cut(self):
        """Couper en silence ferait chercher une erreur dans ce qui n'est
        plus affiché."""
        borne = dl.bornee("y" * 50, maximum=20)
        self.assertTrue(borne.startswith("y" * 20))
        self.assertIn("+30", borne)

    def test_a_short_output_is_untouched(self):
        self.assertEqual(dl.bornee("court", maximum=20), "court")

    def test_no_output_is_an_empty_string(self):
        self.assertEqual(dl.bornee(None), "")


class TestCeQueChaqueChampEst(unittest.TestCase):
    """Le genre décide d'où la valeur a le droit de paraître.

    Sans lui, un appel `Task` — qui n'a pas de `command` — retombait sur son
    `prompt` et étalait l'invite entière du sous-agent dans une colonne de
    tableau qui déclare ne montrer aucun contenu. Le volet de détail a le
    droit de la montrer, il prévient ; la colonne non.
    """

    TEMOIN = "invite-entiere-qui-ne-doit-pas-sortir"

    def _genre(self, **entree):
        return dl._entree({"input": entree})[2]

    def test_a_shell_command_is_a_command(self):
        self.assertEqual(self._genre(command="echo x"), "commande")

    def test_a_file_is_a_path(self):
        self.assertEqual(self._genre(file_path="/un/fichier.py"), "chemin")
        self.assertEqual(self._genre(path="/un/dossier"), "chemin")

    def test_a_prompt_a_query_and_a_pattern_are_free_text(self):
        for champ in ("prompt", "query", "pattern"):
            self.assertEqual(self._genre(**{champ: self.TEMOIN}), "texte")

    def test_only_a_few_genres_may_fill_a_column(self):
        self.assertNotIn("texte", dl.COLONNABLES)
        for sur in ("commande", "chemin", "url"):
            self.assertIn(sur, dl.COLONNABLES)

    def test_the_command_wins_over_a_prompt_on_the_same_call(self):
        """Un outil peut porter les deux ; c'est la commande qui situe."""
        valeur, _, genre = dl._entree(
            {"input": {"command": "echo x", "prompt": self.TEMOIN}}
        )
        self.assertEqual(genre, "commande")
        self.assertNotIn(self.TEMOIN, valeur)

    def test_a_task_call_is_never_colonnable(self):
        detail = dl.replier(
            dl.Detail(),
            _assistant(nom="Task", prompt=self.TEMOIN),
            APPEL,
        )
        self.assertEqual(detail.genre, "texte")
        self.assertFalse(detail.colonnable)
        self.assertEqual(detail.commande, self.TEMOIN)

    def test_a_bash_call_is_colonnable(self):
        detail = dl.replier(dl.Detail(), _assistant(command="echo x"), APPEL)
        self.assertTrue(detail.colonnable)


class TestLUrlNeSortPasAvecSonJeton(unittest.TestCase):
    """Une URL situe comme un chemin, et porte volontiers un jeton.

    La levée que le dépôt a consentie porte sur le CONTENU, pas sur les
    secrets : le module des serveurs MCP coupe déjà ce qui authentifie, et il
    n'y a pas de raison que celui-ci l'étale.
    """

    TEMOIN = "jeton-invente-qui-ne-doit-pas-sortir"

    def test_a_query_string_is_cut(self):
        valeur, _, genre = dl._entree(
            {
                "input": {
                    "url": f"https://api.exemple.test/v1?api_key={self.TEMOIN}"
                }
            }
        )
        self.assertEqual(genre, "url")
        self.assertNotIn(self.TEMOIN, valeur)
        self.assertIn("api.exemple.test", valeur)

    def test_the_credentials_before_the_host_are_cut(self):
        valeur, _, _ = dl._entree(
            {
                "input": {
                    "url": f"https://compte:{self.TEMOIN}@api.exemple.test/v1"
                }
            }
        )
        self.assertNotIn(self.TEMOIN, valeur)

    def test_a_plain_url_is_left_alone(self):
        url = "https://api.exemple.test/v1"
        valeur, _, _ = dl._entree({"input": {"url": url}})
        self.assertEqual(valeur, url)


if __name__ == "__main__":
    unittest.main()
