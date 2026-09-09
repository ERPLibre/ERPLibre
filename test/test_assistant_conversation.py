#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'historique tient-il, et une panne reste-t-elle lisible ?

Le transport est un VRAI serveur de boucle locale, questionné par le VRAI
client `openai`. Un double du client ne rendrait que ce qu'on aurait imaginé en
l'écrivant, or ce qui casse une conversation vient du transport : une
connexion refusée, un corps d'erreur, un flux coupé.

Ce que ces tests défendent, et ce qui casserait sans eux :

- Le second tour porte le premier échange. Un backend sans mémoire qui
  n'enverrait que la question courante ferait perdre le fil à chaque tour.
- L'inverse pour une session qui garde son histoire : lui rejouer la nôtre
  doublerait chaque échange et ferait payer deux fois les mêmes jetons.
- Une commande porte une barre oblique, et aucun nombre nu n'en est une. Une
  question collée sur plusieurs lignes dont l'une vaut « 0 » déclencherait
  sinon une action de menu.
- L'invite ne part JAMAIS sur l'argv de `claude` : un argv se lit par
  n'importe quel compte local dès que `/proc` est monté sans `hidepid`.
- La lecture seule tient par des drapeaux, pas par une phrase d'invite.

Rien ici n'ouvre de socket sortante, ne lance de vrai `claude`, ni ne lit la
configuration de la machine : le serveur est lié à la boucle locale sur un
port choisi par le système, et le lanceur de sous-processus est injecté.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

import openai  # noqa: E402
from llm_fake_server import FakeLLM, port_ferme  # noqa: E402

from script.todo.assistant.backends import (  # noqa: E402
    ClaudeCliBackend,
    HttpBackend,
    Interrupted,
    claude_argv,
)
from script.todo.assistant.chat import (  # noqa: E402
    COMMANDS,
    Conversation,
    parse_command,
)

MODELE = "petit-modele:7b"


def completion(texte):
    """Le corps d'une réponse `/v1/chat/completions`, valeurs inventées."""
    return json.dumps(
        {
            "id": "chatcmpl-0",
            "object": "chat.completion",
            "created": 0,
            "model": MODELE,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": texte},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
            },
        }
    ).encode()


def fragment(texte, fin=None):
    """Un événement de flux, à la forme des serveurs compatibles OpenAI."""
    return (
        b"data: "
        + json.dumps(
            {
                "id": "chatcmpl-0",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": MODELE,
                "choices": [
                    {
                        "index": 0,
                        "delta": {} if fin else {"content": texte},
                        "finish_reason": fin,
                    }
                ],
            }
        ).encode()
        + b"\n\n"
    )


# Le corps d'erreur cite un modèle absent : c'est la panne la plus courante
# d'un serveur local, et son message est la seule chose qui dise quoi faire.
CORPS_ERREUR = (
    b'{"error":{"message":"model \'absent\' not found, pull it first",'
    b'"type":"api_error"}}'
)

FLUX = fragment("bon") + fragment("jour") + fragment("", "stop")
FLUX += b"data: [DONE]\n\n"

# Un seul serveur pour tout le fichier, trois préfixes de chemin : le client
# `openai` ajoute « /chat/completions » à la racine qu'on lui donne, donc la
# racine choisie décide de la réponse servie. Un serveur de plus coûterait un
# demi-seconde d'arrêt.
ROUTES = {
    "/v1/chat/completions": (200, completion("bonjour")),
    "/panne/chat/completions": (500, CORPS_ERREUR),
    "/flux/chat/completions": (200, FLUX),
    "/routeur/chat/completions": (
        200,
        b"<html><body>Administration</body></html>",
    ),
    "/vide/chat/completions": (200, b'{"choices":[]}'),
    "/muet/chat/completions": (
        200,
        b'{"choices":[{"index":0,"finish_reason":"length",'
        b'"message":{"role":"assistant","content":""}}]}',
    ),
}


def longueur(entete):
    """La taille du corps annoncée, quelle que soit la casse de l'en-tête."""
    for cle, valeur in entete.items():
        if cle.lower() == "content-length":
            return int(valeur)
    return 0


class Enregistreur:
    """Un backend qui garde ce qu'on lui envoie, sans mémoire propre.

    Il implémente le protocole plutôt que de le simuler : ce qui est vérifié
    ici est la FORME des messages, et un serveur ne la rend pas visible.
    """

    keeps_history = False

    def __init__(self, reponse="bonjour"):
        self.recus = []
        self.reponse = reponse

    def send(self, messages, *, on_chunk=None):
        self.recus.append([dict(message) for message in messages])
        if on_chunk is not None:
            on_chunk(self.reponse)
        return self.reponse, {"model": "modele-de-test"}


class SessionQuiGarde(Enregistreur):
    """Un backend qui tient son histoire de son côté, comme `claude`."""

    keeps_history = True


class Coupure:
    """Un backend coupé en pleine réponse, qui rend ce qui était arrivé."""

    keeps_history = False

    def __init__(self, partiel):
        self.partiel = partiel

    def send(self, messages, *, on_chunk=None):
        if on_chunk is not None and self.partiel:
            on_chunk(self.partiel)
        raise Interrupted(self.partiel, {"model": MODELE})


class MainLevee:
    """Un backend interrompu avant le premier octet."""

    keeps_history = False

    def send(self, messages, *, on_chunk=None):
        raise KeyboardInterrupt


class AllerRetour(unittest.TestCase):
    """Le vrai client contre un vrai serveur : la réponse ET les pannes.

    Les deux sont des faits de transport, et le serveur est monté une fois
    pour le fichier — son arrêt coûte une demi-seconde.
    """

    @classmethod
    def setUpClass(cls):
        cls.faux = FakeLLM(routes=ROUTES)
        cls.faux.__enter__()
        cls.client = openai.OpenAI(
            base_url=f"{cls.faux.url}/v1", api_key="cle-de-test", timeout=5
        )
        cls.client_panne = openai.OpenAI(
            base_url=f"{cls.faux.url}/panne",
            api_key="cle-de-test",
            timeout=5,
            max_retries=0,
        )
        cls.client_flux = openai.OpenAI(
            base_url=f"{cls.faux.url}/flux", api_key="cle-de-test", timeout=5
        )
        cls.client_routeur = openai.OpenAI(
            base_url=f"{cls.faux.url}/routeur",
            api_key="cle-de-test",
            timeout=5,
        )
        cls.client_muet = openai.OpenAI(
            base_url=f"{cls.faux.url}/muet", api_key="cle-de-test", timeout=5
        )
        cls.client_vide = openai.OpenAI(
            base_url=f"{cls.faux.url}/vide", api_key="cle-de-test", timeout=5
        )

    @classmethod
    def tearDownClass(cls):
        cls.faux.__exit__(None, None, None)

    def setUp(self):
        self.depart = len(self.faux.seen)

    def vues(self):
        """Les requêtes reçues depuis le début de ce test."""
        return self.faux.seen[self.depart :]

    def test_une_reponse_traverse_le_vrai_client(self):
        conversation = Conversation(
            HttpBackend(None, MODELE, client=self.client)
        )
        tour = conversation.ask("salut")
        self.assertEqual(tour.role, "assistant")
        self.assertEqual(tour.text, "bonjour")
        self.assertEqual(conversation.last_meta["model"], MODELE)
        self.assertEqual([v[0] for v in self.vues()], ["POST"])

    def test_le_second_tour_porte_le_premier_echange(self):
        conversation = Conversation(
            HttpBackend(None, MODELE, client=self.client)
        )
        conversation.ask("salut")
        conversation.ask("encore")
        self.assertEqual(
            [(m["role"], m["content"]) for m in conversation.last_sent],
            [
                ("user", "salut"),
                ("assistant", "bonjour"),
                ("user", "encore"),
            ],
        )
        vues = self.vues()
        self.assertEqual(len(vues), 2, "deux envois attendus")
        self.assertGreater(
            longueur(vues[1][2]),
            longueur(vues[0][2]),
            "le second corps doit porter l'échange précédent",
        )

    def test_les_fragments_forment_le_texte_rendu(self):
        recus = []
        conversation = Conversation(
            HttpBackend(None, MODELE, client=self.client_flux)
        )
        tour = conversation.ask("salut", on_chunk=recus.append)
        self.assertTrue(recus, "aucun fragment reçu")
        self.assertEqual("".join(recus), tour.text)
        self.assertEqual(tour.text, "bonjour")
        self.assertEqual(conversation.last_meta["finish_reason"], "stop")

    def test_une_connexion_refusee_est_un_message_pas_une_trace(self):
        mort = openai.OpenAI(
            base_url=f"http://127.0.0.1:{port_ferme()}/v1",
            api_key="cle-de-test",
            timeout=2,
            max_retries=0,
        )
        conversation = Conversation(HttpBackend(None, MODELE, client=mort))
        tour = conversation.ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertIn("refused", tour.text.lower())
        self.assertNotIn("Traceback", tour.text)
        self.assertNotIn("\n", tour.text)
        self.assertEqual(conversation.turns, [])

    def test_un_corps_d_erreur_est_montre_pas_avale(self):
        conversation = Conversation(
            HttpBackend(None, MODELE, client=self.client_panne)
        )
        tour = conversation.ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertIn("500", tour.text)
        self.assertIn("pull it first", tour.text)
        self.assertEqual(conversation.turns, [])

    def test_une_page_html_est_un_message_pas_une_trace(self):
        conversation = Conversation(
            HttpBackend(None, MODELE, client=self.client_routeur)
        )
        tour = conversation.ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertIn("Administration", tour.text)
        self.assertEqual(conversation.turns, [])

    def test_une_reponse_sans_choix_est_un_message(self):
        conversation = Conversation(
            HttpBackend(None, MODELE, client=self.client_vide)
        )
        tour = conversation.ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertIn("no choice", tour.text)

    def test_une_reponse_vide_est_un_message_pas_un_blanc(self):
        """Un serveur dont le moteur de modèle s'arrête rend un 200 avec un
        contenu VIDE. L'afficher tel quel se confond avec un modèle qui n'a
        rien à dire, et une panne de ressources sur l'hôte se lit alors comme
        un défaut du menu. La cause vit dans `finish_reason`, donc elle est
        nommée."""
        conversation = Conversation(
            HttpBackend(None, MODELE, client=self.client_muet)
        )
        tour = conversation.ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertIn("empty answer", tour.text)
        self.assertIn("length", tour.text)
        self.assertEqual(conversation.turns, [])

    def test_un_parametre_inconnu_est_nomme_pas_une_trace(self):
        conversation = Conversation(
            HttpBackend(
                None, MODELE, client=self.client, params={"num_ctx": 4096}
            )
        )
        tour = conversation.ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertIn("num_ctx", tour.text)
        self.assertEqual(self.vues(), [], "rien ne doit partir sur le réseau")


class Historique(unittest.TestCase):
    """Qui garde les tours, qui les reçoit, et ce qu'il en reste."""

    def test_l_historique_ne_vit_qu_en_memoire(self):
        backend = Enregistreur()
        conversation = Conversation(backend)

        def refuse(*args, **kwargs):
            raise AssertionError(f"écriture interdite : {args!r}")

        with patch("builtins.open", side_effect=refuse):
            conversation.ask("salut")
            conversation.ask("encore")
            texte = conversation.transcript()
        self.assertIn("salut", texte)
        self.assertIn("encore", texte)
        self.assertEqual(len(conversation.turns), 4)
        self.assertEqual(
            Conversation(backend).turns,
            [],
            "une conversation neuve part vide : rien n'a été relu",
        )

    def test_un_backend_qui_garde_son_histoire_ne_recoit_pas_la_notre(self):
        backend = SessionQuiGarde()
        conversation = Conversation(backend, system="ne pas rejouer")
        conversation.ask("salut")
        conversation.ask("encore")
        self.assertEqual(len(backend.recus), 2, "deux envois attendus")
        for envoi in backend.recus:
            self.assertEqual(len(envoi), 1, envoi)
            self.assertEqual(envoi[0]["role"], "user")
        self.assertEqual(backend.recus[1][0]["content"], "encore")
        self.assertEqual(len(conversation.turns), 4)

    def test_l_invite_systeme_ouvre_l_envoi_d_un_backend_sans_memoire(self):
        backend = Enregistreur()
        Conversation(backend, system="tu es bref").ask("salut")
        self.assertEqual(len(backend.recus), 1, "un envoi attendu")
        self.assertEqual(
            backend.recus[0][0], {"role": "system", "content": "tu es bref"}
        )

    def test_l_invite_systeme_du_gpt_sert_de_defaut(self):
        class GptDeTest:
            name = "Outil de test"
            system = "tu réécris"

        backend = Enregistreur()
        conversation = Conversation(backend, gpt=GptDeTest())
        conversation.ask("salut")
        self.assertEqual(backend.recus[0][0]["content"], "tu réécris")
        self.assertIn("Outil de test", conversation.transcript())

    def test_vider_l_historique_rend_le_nombre_de_tours_jetes(self):
        conversation = Conversation(Enregistreur())
        conversation.ask("salut")
        conversation.ask("encore")
        self.assertEqual(conversation.reset(), 4)
        self.assertEqual(conversation.turns, [])
        self.assertEqual(conversation.reset(), 0)

    def test_une_reponse_coupee_garde_ce_qui_est_arrive(self):
        conversation = Conversation(Coupure("bonj"))
        tour = conversation.ask("salut")
        self.assertTrue(tour.interrupted)
        self.assertEqual(tour.text, "bonj")
        self.assertEqual(len(conversation.turns), 2)
        self.assertIn("(interrupted)", conversation.transcript())

    def test_une_coupure_sans_texte_ne_laisse_aucun_tour(self):
        conversation = Conversation(MainLevee())
        tour = conversation.ask("salut")
        self.assertTrue(tour.interrupted)
        self.assertEqual(tour.text, "")
        self.assertEqual(conversation.turns, [])

    def test_ce_qui_est_parti_reste_visible_apres_une_panne(self):
        class Panne:
            keeps_history = False

            def send(self, messages, *, on_chunk=None):
                from script.todo.assistant.backends import BackendError

                raise BackendError("500 - server said no")

        conversation = Conversation(Panne(), system="tu es bref")
        tour = conversation.ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertEqual(
            [m["role"] for m in conversation.last_sent], ["system", "user"]
        )


class Commandes(unittest.TestCase):
    """Ce qui est une commande, et ce qui reste une question."""

    def test_une_commande_exige_une_barre_oblique(self):
        self.assertEqual(parse_command("/new"), ("/new", ""))
        self.assertEqual(parse_command("new"), (None, "new"))
        self.assertEqual(parse_command("q"), (None, "q"))

    def test_une_ligne_collee_valant_zero_n_est_pas_une_commande(self):
        for ligne in ("0", "1", " 3 ", "0 "):
            self.assertEqual(parse_command(ligne), (None, ligne), ligne)

    def test_une_question_qui_commence_par_un_chemin_reste_une_question(self):
        ligne = "/v1/models rend quoi ?"
        self.assertEqual(parse_command(ligne), (None, ligne))

    def test_une_commande_porte_son_argument(self):
        self.assertEqual(
            parse_command("/gpt hygiene des commentaires"),
            ("/gpt", "hygiene des commentaires"),
        )

    def test_chaque_commande_documentee_se_reconnait(self):
        self.assertTrue(COMMANDS, "aucune commande déclarée")
        for commande in COMMANDS:
            self.assertEqual(parse_command(commande), (commande, ""))
            self.assertTrue(COMMANDS[commande], commande)

    def test_une_ligne_vide_est_du_texte_pas_une_commande(self):
        self.assertEqual(parse_command(""), (None, ""))
        self.assertEqual(parse_command("   "), (None, "   "))


class ArgvClaude(unittest.TestCase):
    """L'argv de `claude -p` : ce qu'il porte, et ce qu'il ne porte jamais."""

    QUESTION = "quelle est la cause de cet échec"

    def test_l_argv_claude_ne_porte_jamais_l_invite(self):
        argv = claude_argv(session_id="s-1", cwd="/depot", fork=True)
        self.assertNotIn(self.QUESTION, argv)
        self.assertNotIn(self.QUESTION, " ".join(argv))
        self.assertIn("-p", argv)
        self.assertEqual(
            argv[argv.index("--output-format") + 1],
            "json",
            "l'enveloppe JSON est la seule forme lisible par un programme",
        )

    def test_l_argv_lecture_seule_porte_tools_et_permission_mode(self):
        argv = claude_argv(session_id=None, cwd="/depot", fork=False)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--add-dir") + 1], "/depot")

    def test_sans_lecture_seule_aucun_drapeau_d_outil(self):
        argv = claude_argv(
            session_id=None, cwd="/depot", fork=False, read_only=False
        )
        for drapeau in ("--tools", "--permission-mode", "--add-dir"):
            self.assertNotIn(drapeau, argv)

    def test_l_argv_par_defaut_branche_une_copie(self):
        argv = claude_argv(session_id="s-1", cwd=None, fork=True)
        self.assertEqual(argv[argv.index("--resume") + 1], "s-1")
        self.assertIn("--fork-session", argv)

    def test_sans_fork_l_argv_ecrit_dans_la_session_nommee(self):
        argv = claude_argv(session_id="s-1", cwd=None, fork=False)
        self.assertIn("--resume", argv)
        self.assertNotIn("--fork-session", argv)

    def test_sans_session_il_n_y_a_rien_a_brancher(self):
        argv = claude_argv(session_id=None, cwd=None, fork=True)
        self.assertNotIn("--fork-session", argv)
        self.assertNotIn("--resume", argv)


def enveloppe(resultat, session="s-2", erreur=False):
    """Une enveloppe `claude -p --output-format json`, valeurs inventées."""
    return json.dumps(
        {
            "session_id": session,
            "result": resultat,
            "is_error": erreur,
            "num_turns": 1,
            "total_cost_usd": 0.01,
            "modelUsage": {
                "modele-de-test": {
                    "contextWindow": 200000,
                    "maxOutputTokens": 8192,
                }
            },
        }
    )


class SessionClaude(unittest.TestCase):
    """Le backend `claude` : par où part l'invite, et quelle session répond."""

    def lanceur(self, sorties):
        """Un lanceur injecté qui garde (argv, stdin) de chaque appel."""
        self.appels = []

        def run(argv, stdin_text):
            self.appels.append((list(argv), stdin_text))
            return sorties.pop(0)

        return run

    def test_l_invite_part_sur_l_entree_standard(self):
        backend = ClaudeCliBackend(
            session_id="s-1",
            cwd="/depot",
            run=self.lanceur([(0, enveloppe("la cause est le cache"), "")]),
        )
        texte, faits = backend.send(
            [{"role": "user", "content": "quelle cause"}]
        )
        self.assertEqual(texte, "la cause est le cache")
        argv, entree = self.appels[0]
        self.assertEqual(entree, "quelle cause")
        self.assertNotIn("quelle cause", argv)
        self.assertNotIn("quelle cause", " ".join(argv))
        self.assertEqual(
            faits["modelUsage"]["modele-de-test"]["contextWindow"], 200000
        )

    def test_un_second_envoi_reprend_la_copie_sans_la_refourcher(self):
        backend = ClaudeCliBackend(
            session_id="s-1",
            cwd=None,
            run=self.lanceur(
                [
                    (0, enveloppe("un"), ""),
                    (0, enveloppe("deux"), ""),
                ]
            ),
        )
        conversation = Conversation(backend)
        conversation.ask("premier")
        self.assertEqual(backend.session_id, "s-2")
        self.assertFalse(backend.fork)
        conversation.ask("second")
        second = self.appels[1][0]
        self.assertEqual(second[second.index("--resume") + 1], "s-2")
        self.assertNotIn(
            "--fork-session",
            second,
            "brancher à chaque tour perdrait le tour d'avant",
        )

    def test_le_fragment_unique_est_le_texte_rendu(self):
        backend = ClaudeCliBackend(
            run=self.lanceur([(0, enveloppe("une réponse"), "")])
        )
        recus = []
        texte, _ = backend.send(
            [{"role": "user", "content": "salut"}], on_chunk=recus.append
        )
        self.assertEqual(recus, ["une réponse"])
        self.assertEqual("".join(recus), texte)

    def test_une_enveloppe_en_erreur_est_un_message(self):
        backend = ClaudeCliBackend(
            run=self.lanceur(
                [(1, enveloppe("budget dépassé", erreur=True), "")]
            )
        )
        tour = Conversation(backend).ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertIn("budget dépassé", tour.text)

    def test_une_sortie_qui_n_est_pas_du_json_cite_la_sortie(self):
        backend = ClaudeCliBackend(
            run=self.lanceur([(1, "", "unknown option --tools\n")])
        )
        tour = Conversation(backend).ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertIn("unknown option", tour.text)
        self.assertNotIn("\n", tour.text)

    def test_un_claude_absent_est_un_message_pas_un_plantage(self):
        def introuvable(argv, stdin_text):
            raise FileNotFoundError(2, "No such file or directory", "claude")

        backend = ClaudeCliBackend(run=introuvable)
        tour = Conversation(backend).ask("salut")
        self.assertEqual(tour.role, "error")
        self.assertIn("PATH", tour.text)


if __name__ == "__main__":
    unittest.main()
