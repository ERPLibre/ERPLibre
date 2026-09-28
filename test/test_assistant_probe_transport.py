#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le transport de la découverte, contre un VRAI serveur qui se conduit mal.

`collect` ouvre de vraies sockets vers `llm_fake_server.FakeLLM`, lié à la
boucle locale sur un port choisi par le système. Rien ne quitte la machine, et
aucune de ces requêtes ne touche un serveur LLM réel.

Un double de `requests` ne rendrait que ce qu'on aurait imaginé en l'écrivant,
et tout ce qui casse une découverte vient du TRANSPORT : une page
d'administration qui rend du HTML là où l'échelle attend du JSON, un défi 401,
un 503 pendant le chargement d'un modèle, une connexion coupée en plein corps,
un corps qui ne finit pas, un écouteur qui accepte et ne répond jamais.

Ce que ce fichier défend, et qui coûte cher à qui le casse : le PLAFOND de
lecture, qui garde un corps de huit mégaoctets hors de la mémoire du menu ; le
DÉLAI, qui empêche un écouteur bloqué de figer le balayage ; et les deux
interdits du balayage — GET seulement, jamais d'en-tête `Authorization` — sans
lesquels une découverte pourrait charger un modèle ou dépenser un jeton.

Les corps servis sont ceux de `FIXTURES`, que lisent aussi les tests purs de
`test_assistant_fingerprint.py` : les deux moitiés du module se vérifient donc
contre les mêmes octets.
"""

import socketserver
from urllib.parse import urlsplit
import time
import unittest

from llm_fake_server import (
    CATALOGUE_LONG,
    FIXTURES,
    HOST,
    Cut,
    FakeLLM,
    Huge,
    Silent,
    port_ferme,
)

from script.todo.assistant.fingerprint import (
    BODY_CAP,
    CATALOG_CAP,
    CATALOG_PATHS,
    collect,
    identify,
    probe_plan,
)

# Les familles que le transport doit reconnaître de bout en bout. « gpt4all »
# demande son port et « openai » son nom d'hôte : ni l'un ni l'autre ne se
# joue dans le transport.
# `FakeLLM.__exit__` appelle `shutdown()`, qui attend que la boucle d'accueil
# remarque la demande. Sans argument, `serve_forever()` la sonde toutes les
# 0,5 s : chaque serveur jetable coûte alors une demi-seconde de sommeil, et ce
# fichier en démarre une vingtaine. Raccourcir la période de sondage ne change
# ni ce qui est servi ni ce qui est reçu — elle ne règle que la vitesse à
# laquelle un serveur accepte de mourir, donc si ce fichier reste une boucle
# rapide.
_SERVE_FOREVER = socketserver.BaseServer.serve_forever


def _serve_forever_reactif(self, poll_interval=0.01):
    return _SERVE_FOREVER(self, poll_interval)


def setUpModule():
    socketserver.BaseServer.serve_forever = _serve_forever_reactif


def tearDownModule():
    socketserver.BaseServer.serve_forever = _SERVE_FOREVER


FAMILIES = (
    "ollama",
    "localai",
    "localai_starting",
    "llamacpp",
    "koboldcpp",
    "jan",
    "lmstudio",
    "tabbyapi",
    "textgen_webui",
    "vllm",
    "exo",
)


class Transport(unittest.TestCase):
    """Ce que `collect` rend quand le serveur en face n'est pas poli."""

    def test_un_port_mort_est_absent_pas_une_exception(self):
        # Le port vient d'être rendu par le système : la connexion y est
        # refusée tout de suite, elle n'expire pas.
        bodies = collect(HOST, port_ferme(), budget=1.0)
        self.assertEqual(bodies, {})

    def test_du_html_sur_props_n_est_pas_un_llamacpp(self):
        with FakeLLM("routeur") as serveur:
            bodies = collect(serveur.host, serveur.port, budget=2.0)
        # La page a bien répondu, et elle a répondu à `/props` : c'est le cas
        # où une lecture non enveloppée lèverait.
        self.assertEqual(bodies["/props"][0], 200)
        self.assertTrue(bodies["/props"][1].startswith(b"<html"))
        self.assertEqual(identify(bodies, port=8080).software, "")

    def test_la_lecture_du_corps_est_plafonnee(self):
        with FakeLLM(routes={"/props": Huge()}) as serveur:
            bodies = collect(
                serveur.host, serveur.port, budget=5.0, max_bytes=4096
            )
        self.assertEqual(len(bodies["/props"][1]), 4096)
        # Le plafond par défaut est celui du module, pas un nombre du test.
        self.assertGreater(BODY_CAP, 0)

    def test_un_catalogue_traverse_le_transport_sans_etre_coupe(self):
        """Le plafond dépend du CHEMIN, et le prouver demande le transport.

        Un catalogue coupé au plafond d'empreinte s'arrête au milieu d'une
        entrée : son JSON ne s'analyse plus, aucun modèle n'est lu, et le
        serveur se conclut muet à l'instant où il énumérait son offre.
        """
        self.assertGreater(
            len(CATALOGUE_LONG), BODY_CAP, "catalogue trop court"
        )
        self.assertIn("/v1/models", CATALOG_PATHS)
        with FakeLLM("exo") as serveur:
            bodies = collect(serveur.host, serveur.port, budget=5.0)
        self.assertEqual(len(CATALOGUE_LONG), len(bodies["/v1/models"][1]))
        empreinte = identify(bodies, port=serveur.port)
        self.assertEqual("exo", empreinte.software)
        self.assertEqual(100, len(empreinte.models))

    def test_le_plafond_de_catalogue_se_baisse_pour_couper_partout(self):
        """Les deux plafonds sont réglables séparément, sans quoi un test qui
        veut voir une coupure ne pourrait plus en provoquer sur un
        catalogue."""
        with FakeLLM("exo") as serveur:
            bodies = collect(
                serveur.host,
                serveur.port,
                budget=5.0,
                max_bytes=512,
                catalog_bytes=512,
            )
        self.assertEqual(512, len(bodies["/v1/models"][1]))
        # Le plafond par défaut est celui du module, pas un nombre du test.
        self.assertGreater(CATALOG_CAP, BODY_CAP)

    def test_une_cible_ipv6_donne_une_url_lisible(self):
        """Sans crochets, les deux-points de l'adresse ne se distinguent pas
        de celui du port : l'analyse d'URL LÈVE, et la cible passe pour
        illisible au lieu de simplement ne pas répondre. Un tunnel lié en
        IPv6 sur cette machine y mène sans qu'on ait rien tapé.
        """
        import urllib.parse

        from script.todo.assistant.fingerprint import _authority

        self.assertEqual("127.0.0.1:8000", _authority("127.0.0.1", 8000))
        for adresse in ("::1", "2001:db8::1"):
            with self.subTest(adresse=adresse):
                url = f"http://{_authority(adresse, 8000)}/v1/models"
                parts = urllib.parse.urlsplit(url)
                self.assertEqual(adresse, parts.hostname)
                self.assertEqual(8000, parts.port)

    def test_un_serveur_muet_est_borne_par_le_delai(self):
        # L'écouteur accepte la connexion et ne répond jamais : « le port est
        # ouvert » ne suffit donc pas à conclure qu'un serveur est là.
        with FakeLLM(routes={"/readyz": Silent(2.0)}) as serveur:
            debut = time.monotonic()
            bodies = collect(serveur.host, serveur.port, budget=0.25)
            ecoule = time.monotonic() - debut
        self.assertEqual(bodies, {})
        # Le budget est celui de la collecte ENTIÈRE : un chemin bloqué le
        # consomme une fois, il ne le consomme pas quinze fois.
        self.assertLess(ecoule, 2.0)

    def test_un_corps_coupe_rend_ce_qui_est_arrive(self):
        with FakeLLM(routes={"/props": Cut()}) as serveur:
            bodies = collect(serveur.host, serveur.port, budget=2.0)
        self.assertEqual(bodies["/props"], (200, b'{"build_in'))
        self.assertEqual(identify(bodies).software, "")

    def test_un_401_est_collecte_comme_un_resultat(self):
        with FakeLLM("tabbyapi") as serveur:
            bodies = collect(serveur.host, serveur.port, budget=2.0)
        self.assertEqual(bodies["/v1/model"][0], 401)
        self.assertEqual(identify(bodies, port=5000).software, "tabbyapi")

    def test_un_503_est_collecte_comme_un_resultat(self):
        with FakeLLM("localai_starting") as serveur:
            bodies = collect(serveur.host, serveur.port, budget=2.0)
        self.assertEqual(bodies["/readyz"][0], 503)
        self.assertEqual(identify(bodies, port=8080).software, "localai")

    def test_chaque_famille_se_reconnait_a_travers_le_transport(self):
        self.assertTrue(FAMILIES, "la liste des familles servies est vide")
        for famille in FAMILIES:
            with self.subTest(famille=famille):
                self.assertIn(famille, FIXTURES)
                with FakeLLM(famille) as serveur:
                    bodies = collect(serveur.host, serveur.port, budget=3.0)
                attendu = (
                    "localai" if famille.startswith("localai") else famille
                )
                self.assertEqual(identify(bodies).software, attendu)


class Interdits(unittest.TestCase):
    """Ce qu'un balayage ne doit jamais émettre, prouvé par ce qui est reçu."""

    def test_aucun_en_tete_authorization_n_est_envoye(self):
        # Le serveur qui exige une clé est justement celui devant lequel la
        # tentation existerait : un 401 est un résultat, pas une invite.
        with FakeLLM("tabbyapi") as serveur:
            collect(serveur.host, serveur.port, budget=2.0)
            vues = list(serveur.seen)
        self.assertTrue(vues, "le serveur n'a reçu aucune requête")
        for methode, chemin, entetes in vues:
            with self.subTest(chemin=chemin):
                noms = {nom.lower() for nom in entetes}
                self.assertNotIn("authorization", noms)
                self.assertNotIn("x-api-key", noms)
                self.assertNotIn("api-key", noms)

    def test_la_decouverte_n_emet_que_des_GET(self):
        with FakeLLM("ollama") as serveur:
            collect(serveur.host, serveur.port, budget=2.0)
            vues = list(serveur.seen)
        self.assertTrue(vues, "le serveur n'a reçu aucune requête")
        self.assertEqual({methode for methode, _, _ in vues}, {"GET"})
        # `/api/show` est un POST qui charge le modèle nommé : il appartient à
        # l'interrogation des capacités, après le choix d'un serveur.
        chemins = {chemin for _, chemin, _ in vues}
        self.assertNotIn("/api/show", chemins)

    def test_le_transport_suit_le_plan_et_rien_d_autre(self):
        with FakeLLM("ollama") as serveur:
            collect(serveur.host, serveur.port, budget=3.0)
            vues = list(serveur.seen)
        self.assertTrue(vues, "le serveur n'a reçu aucune requête")
        attendus = [chemin for _, chemin in probe_plan()]
        self.assertEqual([chemin for _, chemin, _ in vues], attendus)

    def test_aucun_corps_n_est_monte_dans_une_requete(self):
        with FakeLLM("ollama") as serveur:
            collect(serveur.host, serveur.port, budget=2.0)
            vues = list(serveur.seen)
        self.assertTrue(vues, "le serveur n'a reçu aucune requête")
        for methode, chemin, entetes in vues:
            with self.subTest(chemin=chemin):
                longueurs = {
                    nom.lower(): valeur for nom, valeur in entetes.items()
                }
                self.assertNotIn("content-length", longueurs)


if __name__ == "__main__":
    unittest.main()
