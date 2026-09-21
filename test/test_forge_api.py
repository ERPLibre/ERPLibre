#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le client de forge : où passe le jeton, et ce que quatre pannes veulent.

Ni forge, ni réseau, ni jeton. La session est un paramètre, donc tout ce qui
décide se vérifie depuis une station.

DEUX CHOSES QUE CES ÉPREUVES EXISTENT POUR TENIR.

LE JETON NE DOIT PARAÎTRE NULLE PART SAUF DANS UN EN-TÊTE. Une URL atterrit
dans le journal d'accès du serveur, dans celui de tout mandataire, et dans
l'historique du shell. Un jeton de forge donne le droit d'écrire dans tous
les dépôts du compte.

LA PAGINATION DOIT ALLER AU BOUT. Un client qui lit la première page et
s'arrête annonce trente dépôts là où il y en a deux cents, sans rien dire —
et « créer les dépôts manquants » en recréerait cent soixante-dix qui
existent déjà.
"""

import json
import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.forge import api  # noqa: E402
from script.forge.api import ForgeClient  # noqa: E402

PROFIL = {"url": "https://forge.example", "verify_tls": True}
JETON = "jeton-de-banc-0123456789"


class ReponseFausse:
    def __init__(self, status=200, corps="{}"):
        self.status_code = status
        self.text = corps

    def json(self):
        return json.loads(self.text)


class SessionFausse:
    """Une session de banc : un journal des appels, des réponses au tour."""

    def __init__(self, *reponses, panne=None):
        self.reponses = list(reponses)
        self.panne = panne
        self.appels = []

    def request(self, methode, url, **options):
        self.appels.append({"methode": methode, "url": url, **options})
        if self.panne is not None:
            raise self.panne
        if not self.reponses:
            return ReponseFausse(200, "{}")
        return self.reponses.pop(0)


def client(*reponses, profil=None, token=JETON, panne=None):
    session = SessionFausse(*reponses, panne=panne)
    return ForgeClient(profil or PROFIL, token, session=session), session


class TestLeJetonNeVoyageQueDansUnEntete(unittest.TestCase):
    def test_it_is_in_the_authorization_header(self):
        self.assertEqual(f"token {JETON}", api.headers(JETON)["Authorization"])

    def test_no_token_no_header(self):
        """Contrôle positif : l'en-tête n'est pas systématique."""
        self.assertNotIn("Authorization", api.headers(""))

    def test_it_never_reaches_the_url(self):
        appelant, session = client()
        appelant.whoami()
        self.assertTrue(session.appels, "aucun appel : rien n'est prouvé")
        for appel in session.appels:
            self.assertNotIn(JETON, appel["url"])
            self.assertNotIn(JETON, json.dumps(appel.get("params") or {}))

    def test_it_never_reaches_the_body_of_a_read(self):
        appelant, session = client()
        appelant.repos()
        for appel in session.appels:
            self.assertNotIn(JETON, json.dumps(appel.get("json") or {}))

    def test_it_never_reaches_a_verdict_detail(self):
        """Un détail s'affiche dans un menu et se copie-colle dans un
        rapport de panne."""
        appelant, _ = client(ReponseFausse(500, f"erreur avec {JETON}"))
        reponse = appelant.whoami()
        self.assertNotEqual(api.OK, reponse.kind)
        # Le corps EST recopié : c'est la forge qui a écrit le jeton dedans,
        # ce qui n'arrive pas. Ce que l'épreuve tient, c'est que le client
        # n'en AJOUTE pas.
        appelant, _ = client(ReponseFausse(500, "panne interne"))
        self.assertNotIn(JETON, appelant.whoami().detail)

    def test_a_transport_failure_does_not_carry_it_either(self):
        appelant, _ = client(panne=OSError("connexion refusée"))
        self.assertNotIn(JETON, appelant.whoami().detail)


class TestLAdresseDApi(unittest.TestCase):
    def test_the_base_and_the_path_join_once(self):
        self.assertEqual(
            "https://forge.example/api/v1/user",
            api.api_url("https://forge.example", "user"),
        )

    def test_extra_slashes_never_double(self):
        """Une barre en trop donne un chemin doublé qu'une forge accepte et
        l'autre non : une panne qui ne se voit que sur l'une des deux."""
        for base in ("https://forge.example", "https://forge.example/"):
            for chemin in ("user", "/user", "user/"):
                with self.subTest(base=base, chemin=chemin):
                    self.assertEqual(
                        "https://forge.example/api/v1/user",
                        api.api_url(base, chemin),
                    )

    def test_each_segment_is_escaped(self):
        """Un nom de dépôt porte ce que son propriétaire y a mis."""
        url = api.api_url("https://forge.example", "repos/o/un nom")
        self.assertIn("un%20nom", url)
        self.assertNotIn("un nom", url)

    def test_a_segment_that_climbs_is_refused_and_not_escaped(self):
        """`quote` laisse « .. » INTACT — le point est non réservé en RFC
        3986 — donc un segment « .. » remonte et appelle un autre point.
        L'échapper serait pire : il désignerait un dépôt nommé « .. »."""
        for chemin in (
            "repos/o/../../admin",
            "repos/../admin",
            "repos/o/./n",
            "..",
        ):
            with self.subTest(chemin=chemin):
                with self.assertRaises(ValueError):
                    api.api_url("https://forge.example", chemin)

    def test_a_name_that_merely_contains_dots_is_fine(self):
        """Contrôle positif : refuser tout point retirerait des noms
        parfaitement ordinaires. Seuls « . » et « .. » ENTIERS remontent."""
        for nom in ("site.web", "...js", ".cache", "a..b", "..."):
            with self.subTest(nom=nom):
                url = api.api_url("https://forge.example", f"repos/o/{nom}")
                self.assertTrue(url.endswith(f"/repos/o/{nom}"), url)

    def test_the_separator_stays_a_separator(self):
        """Échapper la barre entre segments donnerait un seul segment."""
        url = api.api_url("https://forge.example", "repos/o/n")
        self.assertIn("/repos/o/n", url)


class TestLesQuatrePannesQuiSeRessemblent(unittest.TestCase):
    """Elles disent toutes « ça ne marche pas » et se corrigent ailleurs."""

    def test_no_token_is_said_before_any_call(self):
        """Appeler sans jeton coûterait un aller-retour pour apprendre ce
        qu'on savait déjà."""
        appelant, session = client(token="")
        self.assertEqual(api.NO_TOKEN, appelant.whoami().kind)
        self.assertEqual([], session.appels)

    def test_a_refused_token_is_named(self):
        appelant, _ = client(ReponseFausse(401, '{"message":"token"}'))
        self.assertEqual(api.BAD_TOKEN, appelant.whoami().kind)

    def test_an_untrusted_certificate_is_not_a_bad_token(self):
        """Il se corrige en approuvant l'autorité, pas en régénérant."""
        appelant, _ = client(
            panne=OSError("certificate verify failed: self signed certificate")
        )
        self.assertEqual(api.TLS_UNTRUSTED, appelant.whoami().kind)

    def test_a_dead_forge_is_not_a_bad_token(self):
        appelant, _ = client(panne=OSError("Connection refused"))
        self.assertEqual(api.UNREACHABLE, appelant.whoami().kind)

    def test_a_private_range_refusal_is_not_a_bad_token(self):
        """LE PIÈGE : la forge répond un refus de PERMISSION. Sans lire le
        corps, on régénère un jeton parfaitement valide."""
        for dit in (
            "You are not allowed to import local repositories.",
            "the host resolve to a private ip address",
            "migrate from a local network is not allowed",
        ):
            with self.subTest(dit=dit[:40]):
                appelant, _ = client(ReponseFausse(403, dit))
                self.assertEqual(
                    api.LOCALNETWORK_REFUSED, appelant.whoami().kind
                )

    def test_the_wording_case_does_not_decide(self):
        appelant, _ = client(ReponseFausse(403, "PRIVATE IP ADDRESS"))
        self.assertEqual(api.LOCALNETWORK_REFUSED, appelant.whoami().kind)

    def test_every_verdict_is_in_the_closed_vocabulary(self):
        self.assertTrue(api.VERDICTS, "vocabulaire vidé : rien n'est prouvé")
        cas = (
            client(ReponseFausse(200, "{}")),
            client(ReponseFausse(401, "x")),
            client(ReponseFausse(404, "x")),
            client(ReponseFausse(409, "x")),
            client(ReponseFausse(500, "x")),
            client(token=""),
            client(panne=OSError("SSLError")),
            client(panne=OSError("timed out")),
        )
        for appelant, _ in cas:
            self.assertIn(appelant.whoami().kind, api.VERDICTS)

    def test_a_transport_failure_never_escapes_as_an_exception(self):
        """L'appelant est un menu : une pile d'appels y perd la
        conversation."""
        for panne in (OSError("x"), ValueError("y"), RuntimeError("z")):
            with self.subTest(panne=type(panne).__name__):
                appelant, _ = client(panne=panne)
                self.assertIn(appelant.whoami().kind, api.VERDICTS)


class TestLaPaginationVaAuBout(unittest.TestCase):
    @staticmethod
    def page(combien, depart=0):
        return ReponseFausse(
            200,
            json.dumps(
                [
                    {"name": f"depot{n}"}
                    for n in range(depart, depart + combien)
                ]
            ),
        )

    def test_a_short_first_page_is_the_only_one(self):
        appelant, session = client(self.page(3))
        reponse = appelant.repos()
        self.assertEqual(api.OK, reponse.kind)
        self.assertEqual(3, len(reponse.data))
        self.assertEqual(1, len(session.appels))

    def test_a_full_page_is_followed_by_the_next(self):
        """Le défaut que ces épreuves existent pour empêcher."""
        appelant, session = client(
            self.page(api.PAGE_SIZE),
            self.page(api.PAGE_SIZE, api.PAGE_SIZE),
            self.page(7, 2 * api.PAGE_SIZE),
        )
        reponse = appelant.repos()
        self.assertEqual(2 * api.PAGE_SIZE + 7, len(reponse.data))
        self.assertEqual(3, len(session.appels))

    def test_the_page_number_advances(self):
        """Redemander la page 1 tournerait sans fin en la recopiant."""
        appelant, session = client(
            self.page(api.PAGE_SIZE), self.page(1, api.PAGE_SIZE)
        )
        appelant.repos()
        self.assertEqual(
            [1, 2], [appel["params"]["page"] for appel in session.appels]
        )

    def test_the_page_size_is_asked_for_and_not_assumed(self):
        """Le défaut du serveur se change dans sa configuration ; un client
        qui s'y fie s'arrête au bout d'une page sans le dire."""
        appelant, session = client(self.page(1))
        appelant.repos()
        self.assertEqual(api.PAGE_SIZE, session.appels[0]["params"]["limit"])

    def test_an_empty_answer_is_an_empty_list_and_not_a_crash(self):
        appelant, _ = client(ReponseFausse(200, "[]"))
        reponse = appelant.repos()
        self.assertEqual(api.OK, reponse.kind)
        self.assertEqual([], reponse.data)

    def test_a_failure_mid_way_is_reported_and_not_swallowed(self):
        """Rendre la première page en disant « voilà tout » ferait croire
        la liste complète."""
        appelant, _ = client(self.page(api.PAGE_SIZE), ReponseFausse(500, "x"))
        reponse = appelant.repos()
        self.assertNotEqual(api.OK, reponse.kind)
        self.assertIsNone(reponse.data)


class TestCeQueLeClientRefuseAvantDAppeler(unittest.TestCase):
    def test_a_private_target_is_named_without_a_round_trip(self):
        """La forge la refuse, et son refus se lit comme un mauvais jeton :
        le dire ici épargne surtout la mauvaise piste."""
        appelant, session = client()
        reponse = appelant.migrate("http://192.168.10.5:3000/x.git", "x")
        self.assertEqual(api.LOCALNETWORK_REFUSED, reponse.kind)
        self.assertEqual([], session.appels)
        self.assertIn("ALLOW_LOCALNETWORKS", reponse.detail)

    def test_a_public_target_is_called_normally(self):
        """Contrôle positif : tout refuser retirerait l'usage."""
        appelant, session = client(ReponseFausse(201, "{}"))
        self.assertEqual(
            api.OK, appelant.migrate("https://forge.example/x.git", "x").kind
        )
        self.assertEqual(1, len(session.appels))

    def test_a_hostname_is_not_judged_here(self):
        """Il se résout côté forge, et personne ici ne sait où."""
        self.assertFalse(
            api.clone_est_en_plage_privee("https://interne.example/x.git")
        )

    def test_every_private_family_is_recognised(self):
        for url in (
            "http://10.0.0.1/x.git",
            "http://172.16.0.1/x.git",
            "http://192.168.0.1/x.git",
            "http://127.0.0.1/x.git",
            "http://169.254.1.1/x.git",
            "http://[fd00::1]/x.git",
        ):
            with self.subTest(url=url):
                self.assertTrue(api.clone_est_en_plage_privee(url))

    def test_a_documentation_address_is_not_taken_for_local(self):
        """LE PIÈGE INVERSE. `ipaddress.is_private` range les plages de
        DOCUMENTATION dans « privé » ; la forge, non. S'y fier rendrait ce
        prédicat plus strict que la forge : il refuserait sans appeler une
        opération qu'elle aurait acceptée, en nommant un réglage qui n'y
        est pour rien."""
        for url in (
            "https://192.0.2.10/x.git",
            "https://198.51.100.7/x.git",
            "https://203.0.113.5/x.git",
            "https://[2001:db8::1]/x.git",
        ):
            with self.subTest(url=url):
                self.assertFalse(api.clone_est_en_plage_privee(url))

    def test_a_routable_address_is_not_taken_for_local(self):
        self.assertFalse(api.clone_est_en_plage_privee("https://8.8.8.8/x"))
        self.assertFalse(
            api.clone_est_en_plage_privee("https://[2606:4700::1]/x")
        )

    def test_the_range_list_is_not_empty(self):
        """Une liste vidée rendrait tout non local, et les épreuves de
        refus tomberaient — mais celle-ci le dit plus vite."""
        self.assertTrue(api.PLAGES_LOCALES)


class TestCeQueLeClientEnvoie(unittest.TestCase):
    def test_a_created_repository_is_private(self):
        """Un dépôt de client créé public est visible le temps qu'on s'en
        aperçoive, et ce qui a été vu ne se reprend pas."""
        appelant, session = client(ReponseFausse(201, "{}"))
        appelant.create_repo("nouveau")
        self.assertIs(True, session.appels[0]["json"]["private"])

    def test_a_public_repository_has_to_be_asked_for(self):
        """Contrôle positif : forcer privé toujours retirerait l'usage."""
        appelant, session = client(ReponseFausse(201, "{}"))
        appelant.create_repo("nouveau", private=False)
        self.assertIs(False, session.appels[0]["json"]["private"])

    def test_a_migration_is_a_mirror_by_default(self):
        appelant, session = client(ReponseFausse(201, "{}"))
        appelant.migrate("https://forge.example/x.git", "x")
        self.assertIs(True, session.appels[0]["json"]["mirror"])

    def test_the_tls_posture_of_the_profile_travels(self):
        """Un profil qui exige la vérification ne doit pas la voir coupée
        par un défaut d'appel."""
        appelant, session = client(ReponseFausse(200, "{}"))
        appelant.whoami()
        self.assertIs(True, session.appels[0]["verify"])

        appelant, session = client(
            ReponseFausse(200, "{}"),
            profil={**PROFIL, "verify_tls": False},
        )
        appelant.whoami()
        self.assertIs(False, session.appels[0]["verify"])

    def test_every_call_is_bounded_in_time(self):
        """Sans borne, un menu se fige sur une forge éteinte et il ne reste
        que Ctrl-C."""
        appelant, session = client(ReponseFausse(200, "{}"))
        appelant.whoami()
        self.assertEqual(api.TIMEOUT, session.appels[0]["timeout"])


class TestLeModuleNAfficheRienEtNOuvrePasLeCoffre(unittest.TestCase):
    def test_it_neither_prints_nor_prompts(self):
        import ast

        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        chemin = os.path.join(racine, "script", "forge", "api.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        noms = [
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertTrue(noms, "aucun appel lu : rien n'est prouvé")
        for interdit in ("print", "input", "getpass"):
            self.assertNotIn(interdit, noms)

    def test_it_does_not_reach_for_the_vault_itself(self):
        """Un module qui va chercher un secret tout seul se retrouve à
        demander une phrase de passe au milieu d'un affichage de liste."""
        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        chemin = os.path.join(racine, "script", "forge", "api.py")
        with open(chemin, encoding="utf-8") as fichier:
            source = fichier.read()
        for interdit in ("SecretStore", "kdbx", "keyring", "pykeepass"):
            self.assertNotIn(interdit, source)


if __name__ == "__main__":
    unittest.main()
