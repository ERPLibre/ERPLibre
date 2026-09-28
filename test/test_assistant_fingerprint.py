#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'échelle de reconnaissance, sans un seul octet de réseau.

Ce fichier ne sonde rien : il appelle `identify` sur les corps de référence de
`llm_fake_server.FIXTURES`, ceux-là mêmes que le faux serveur sert au
transport. Les deux moitiés lisent donc les MÊMES octets ; sans ce partage,
l'analyse serait vérifiée contre une idée du protocole et le transport contre
une autre, et l'écart ne se verrait qu'en production.

Ce qu'il défend est l'ORDRE des étages, qui casse en silence. LocalAI sert
l'API native d'Ollama en entier, jusqu'à la chaîne « Ollama is running » sur
« / » : glisser l'étage LocalAI sous l'étage Ollama nomme « ollama » toutes
les machines LocalAI, sans lever, sans rien afficher d'anormal, et la
conversation part ensuite vers un serveur mal caractérisé. Le test le plus
important du fichier construit un corps qui satisfait les DEUX signatures et
exige « localai ».

Le reste défend la règle « l'identité se lit dans le corps » : ni le port ni
le code de statut ne nomment un logiciel, et un corps HTML, vide ou coupé rend
une empreinte sans logiciel plutôt qu'une exception.
"""

import unittest

from llm_fake_server import CATALOGUE_LONG, FIXTURES

from script.todo.assistant.fingerprint import (
    BODY_CAP,
    GPT4ALL_PORT,
    OPENAI_HOST,
    PORTS,
    Fingerprint,
    identify,
    probe_plan,
)

# Ce que chaque famille de référence doit se voir nommer. « gpt4all » et
# « routeur » n'y sont pas : le premier ne s'atteint que par son port et le
# second ne doit rien nommer du tout, donc chacun a son propre test.
EXPECTED = {
    "ollama": "ollama",
    "localai": "localai",
    "localai_starting": "localai",
    "llamacpp": "llamacpp",
    "vllm": "vllm",
    "lmstudio": "lmstudio",
    "koboldcpp": "koboldcpp",
    "jan": "jan",
    "open_webui": "open_webui",
    "textgen_webui": "textgen_webui",
    "tabbyapi": "tabbyapi",
    "exo": "exo",
}


class Echelle(unittest.TestCase):
    """L'ordre des étages, qui est la seule chose que le corps ne dit pas."""

    def test_localai_est_ecarte_avant_qu_on_interroge_ollama(self):
        double = {**FIXTURES["ollama"], **FIXTURES["localai"]}
        # Le corps satisfait les deux signatures à la fois : c'est ce que
        # rend une machine LocalAI, et rien dans l'API d'Ollama ne l'en
        # distingue.
        self.assertIn("/api/tags", double)
        self.assertIn("/", double)
        self.assertIn("/readyz", double)
        self.assertEqual(identify(double, port=11434).software, "localai")

    def test_readyz_est_ce_qui_separe_localai_d_ollama(self):
        double = {**FIXTURES["ollama"], **FIXTURES["localai"]}
        sans_readyz = {
            path: answer
            for path, answer in double.items()
            if path != "/readyz"
        }
        # Un mandataire qui masque `/readyz` retire le SEUL point qui écarte
        # LocalAI : l'échelle ne doit alors plus prétendre le reconnaître.
        self.assertNotEqual(identify(sans_readyz).software, "localai")

    def test_une_version_0_9_0_figee_est_localai_pas_ollama(self):
        fp = identify(FIXTURES["localai"])
        self.assertEqual(fp.software, "localai")
        # Le littéral que LocalAI sert sur `/api/version` ne décrit pas
        # LocalAI : il n'est jamais rendu comme sa version, et il ne peut pas
        # non plus servir à trancher, ce numéro-là ayant existé comme version
        # réelle d'Ollama.
        self.assertNotEqual(fp.version, "0.9.0")
        self.assertIn("version", fp.unknown)
        vrai = identify(FIXTURES["ollama"])
        self.assertEqual((vrai.software, vrai.version), ("ollama", "0.6.2"))

    def test_le_port_ne_decide_jamais_de_l_identite(self):
        self.assertTrue(PORTS, "la liste des ports à frapper est vide")
        for port in PORTS:
            with self.subTest(port=port):
                fp = identify(FIXTURES["llamacpp"], port=port)
                self.assertEqual(fp.software, "llamacpp")
        # Le port d'Ollama sans aucune réponse ne nomme pas Ollama.
        self.assertEqual(identify({}, port=11434).software, "")

    def test_gpt4all_ne_s_atteint_que_par_elimination(self):
        corps = FIXTURES["gpt4all"]
        self.assertEqual(
            identify(corps, port=GPT4ALL_PORT).software, "gpt4all"
        )
        # Le même corps ailleurs ne nomme rien : l'étage est une élimination,
        # pas une signature.
        self.assertEqual(identify(corps, port=8080).software, "")
        # Et l'élimination ne passe jamais devant un accord réel.
        self.assertEqual(
            identify(FIXTURES["koboldcpp"], port=GPT4ALL_PORT).software,
            "koboldcpp",
        )
        # Sur le bon port, une page qui n'est pas un serveur LLM ne devient
        # pas un GPT4All par défaut.
        self.assertEqual(
            identify(FIXTURES["routeur"], port=GPT4ALL_PORT).software, ""
        )

    def test_ollama_survit_a_une_confirmation_absente_pas_a_un_dementi(self):
        corps = FIXTURES["ollama"]
        sans_version = {
            path: answer
            for path, answer in corps.items()
            if path != "/api/version"
        }
        fp = identify(sans_version)
        # Une confirmation qui manque laisse l'accord debout : l'inconnu ne
        # retire rien, il se dit inconnu.
        self.assertEqual(fp.software, "ollama")
        self.assertIn("version", fp.unknown)
        # Un démenti, lui, retire l'accord : du JSON étranger monté sous
        # `/api/version` n'est pas un Ollama.
        dementi = {
            **corps,
            "/api/version": (200, b'{"version":"pas un numero"}'),
        }
        self.assertEqual(identify(dementi).software, "")

    def test_openai_se_nomme_par_son_hote_sans_aucun_scan(self):
        fp = identify({}, host=OPENAI_HOST)
        self.assertEqual(fp.software, "openai")
        self.assertEqual(identify({}, host="localhost").software, "")


class Signatures(unittest.TestCase):
    """Le champ précis qui accorde chaque étage, et pas un champ voisin."""

    def test_chaque_famille_de_reference_se_nomme(self):
        self.assertTrue(EXPECTED, "la table des familles attendues est vide")
        for famille, logiciel in EXPECTED.items():
            with self.subTest(famille=famille):
                self.assertIn(famille, FIXTURES)
                fp = identify(FIXTURES[famille], port=8080)
                self.assertEqual(fp.software, logiciel)

    def test_koboldcpp_se_nomme_par_son_champ_result(self):
        fp = identify(FIXTURES["koboldcpp"])
        self.assertEqual((fp.software, fp.version), ("koboldcpp", "0.0"))
        autre = {"/api/extra/version": (200, b'{"result":"autre chose"}')}
        self.assertEqual(identify(autre).software, "")

    def test_open_webui_se_nomme_par_deployment_id(self):
        self.assertEqual(
            identify(FIXTURES["open_webui"]).software, "open_webui"
        )
        # `name` et `version` se retrouvent chez d'autres interfaces ; seul
        # `deployment_id` accorde l'étage.
        sans = {"/api/config": (200, b'{"name":"autre","version":"0.0.0"}')}
        self.assertEqual(identify(sans).software, "")

    def test_llamacpp_se_nomme_par_build_info_avec_chat_template_caps(self):
        fp = identify(FIXTURES["llamacpp"])
        self.assertEqual(
            (fp.software, fp.version), ("llamacpp", "b9999-0000000")
        )
        # Les deux clés sont exigées ensemble : `build_info` seul se recopie.
        seul = {"/props": (200, b'{"build_info":"b1-0000000"}')}
        self.assertEqual(identify(seul).software, "")
        # Derrière un mandataire qui masque `/props`, `owned_by` reste.
        proxy = {"/v1/models": FIXTURES["llamacpp"]["/v1/models"]}
        self.assertEqual(identify(proxy).software, "llamacpp")

    def test_vllm_repond_sur_version_pas_api_version(self):
        self.assertEqual(identify(FIXTURES["vllm"]).software, "vllm")
        # `/api/version` appartient à Ollama et à LocalAI : le même corps sur
        # ce chemin ne nomme pas vLLM.
        ailleurs = {"/api/version": (200, b'{"version":"0.0.0"}')}
        self.assertEqual(identify(ailleurs).software, "")

    def test_exo_se_nomme_par_son_pair_ou_par_son_catalogue(self):
        """Deux lectures l'accordent, et chacune couvre ce que l'autre ne
        couvre pas.

        `/node_id` tient en quelques dizaines d'octets, donc il survit à un
        catalogue trop gros pour être analysé. `owned_by` survit au
        mandataire inverse qui ne publie que `/v1`. Une seule des deux
        laisserait un déploiement courant sans nom.
        """
        seul_pair = {"/node_id": FIXTURES["exo"]["/node_id"]}
        self.assertEqual(identify(seul_pair).software, "exo")
        seul_catalogue = {"/v1/models": FIXTURES["exo"]["/v1/models"]}
        self.assertEqual(identify(seul_catalogue).software, "exo")
        # Une chaîne JSON nue est ce qui accorde l'étage : un objet sur ce
        # chemin est autre chose, et ne doit rien nommer.
        objet = {"/node_id": (200, b'{"id":"autre chose"}')}
        self.assertEqual(identify(objet).software, "")

    def test_le_titre_par_defaut_du_cadre_web_n_est_pas_celui_de_jan(self):
        """L'étage Jan lit le même `/openapi.json` et passe AVANT. Accorder
        Jan sur un titre générique nommerait « jan » tout serveur bâti sur ce
        cadre."""
        self.assertEqual(identify(FIXTURES["exo"]).software, "exo")

    def test_un_catalogue_plus_long_que_le_plafond_rend_ses_modeles(self):
        """Le mode de défaillance que le plafond de catalogue empêche.

        Coupé au plafond d'empreinte, le JSON s'arrête au milieu d'une entrée
        et ne s'analyse plus : aucun modèle n'est lu, et un étage qui lit le
        catalogue ne reconnaît plus rien. Le serveur se conclut muet à
        l'instant où il énumérait son offre.
        """
        self.assertGreater(
            len(CATALOGUE_LONG), BODY_CAP, "catalogue trop court"
        )
        fp = identify(FIXTURES["exo"])
        self.assertEqual(100, len(fp.models))
        self.assertNotIn("models", fp.unknown)
        # Le même catalogue coupé au plafond d'empreinte : plus un modèle.
        coupe = {"/v1/models": (200, CATALOGUE_LONG[:BODY_CAP])}
        self.assertEqual((), identify(coupe).models)

    def test_un_gros_catalogue_se_lit_en_temps_lineaire(self):
        """Le dédoublonnage passe par un ENSEMBLE, pas par la liste en cours.

        Le mode de défaillance est un menu figé, pas un mauvais résultat :
        `identify` est PUR et tourne HORS du budget de `collect`, qui ne
        borne que le transport. Un « in » sur la liste rend la fonction
        quadratique, et le plafond d'un catalogue borne le nombre de noms
        bien plus haut que celui d'une réponse d'empreinte — un catalogue
        d'un mégaoctet demandait alors quinze secondes de calcul.
        """
        import json
        import time

        gros = json.dumps(
            {
                "object": "list",
                "data": [{"id": f"{n:06x}"} for n in range(60000)],
            }
        ).encode()
        debut = time.monotonic()
        fp = identify({"/v1/models": (200, gros)}, port=8080)
        ecoule = time.monotonic() - debut
        self.assertEqual(60000, len(fp.models))
        # Linéaire tient en une fraction de seconde ; quadratique met plus de
        # dix secondes. Le seuil est LARGE exprès : il sépare deux ordres de
        # grandeur, il ne mesure pas la machine.
        self.assertLess(
            ecoule, 3.0, f"{ecoule:.1f}s : dédoublonnage linéaire ?"
        )

    def test_le_plafond_d_un_catalogue_reste_dimensionne(self):
        """Le monter sans fin coûte des deux côtés : le corps vient d'un
        tiers, et les noms qu'on en tire sont retenus par le balayage pour
        chaque hôte reconnu."""
        from script.todo.assistant.fingerprint import CATALOG_CAP

        self.assertGreater(CATALOG_CAP, BODY_CAP)
        # Quatre fois la plus grande offre observée suffit ; au-delà, aucun
        # serveur de plus ne devient lisible.
        self.assertGreater(CATALOG_CAP, 4 * len(CATALOGUE_LONG))
        self.assertLessEqual(CATALOG_CAP, 1 << 20)

    def test_un_401_sur_le_chemin_model_singulier_est_un_accord(self):
        fp = identify(FIXTURES["tabbyapi"])
        self.assertEqual(fp.software, "tabbyapi")
        # Le défi porte sur `/v1/model` au singulier ; le pluriel est servi
        # par onze serveurs sur douze et ne nomme personne.
        pluriel = {"/v1/models": (401, b'{"detail":"Invalid API key"}')}
        self.assertEqual(identify(pluriel).software, "")


class CorpsHostiles(unittest.TestCase):
    """Ce qu'un serveur mal élevé rend, et qui doit rester un résultat."""

    def test_une_page_de_routeur_sur_8080_ne_nomme_rien(self):
        fp = identify(FIXTURES["routeur"], port=8080)
        self.assertEqual(fp.software, "")
        self.assertEqual(fp.models, ())
        self.assertIn("software", fp.unknown)

    def test_un_503_starting_est_vivant_pas_mort(self):
        fp = identify(FIXTURES["localai_starting"], port=8080)
        self.assertEqual(fp.software, "localai")
        # Le statut ne nomme pourtant rien par lui-même : `/health` rend 200
        # chez trois serveurs et 503 pendant un chargement, sans distinguer
        # personne.
        self.assertEqual(identify(FIXTURES["llamacpp_loading"]).software, "")

    def test_un_corps_tronque_ne_leve_pas(self):
        self.assertTrue(FIXTURES, "les corps de référence ont disparu")
        for famille, corps in FIXTURES.items():
            coupe = {
                path: (status, body[:12])
                for path, (status, body) in corps.items()
            }
            with self.subTest(famille=famille):
                self.assertIsInstance(identify(coupe, port=8080), Fingerprint)
        coupe = {"/props": (200, b'{"build_in')}
        self.assertEqual(identify(coupe).software, "")

    def test_un_serveur_inconnu_ne_nomme_rien(self):
        anonyme = {
            "/v1/models": (
                200,
                b'{"object":"list","data":[{"id":"un-modele"}]}',
            )
        }
        fp = identify(anonyme, port=8000)
        self.assertEqual(fp.software, "")
        self.assertIn("software", fp.unknown)
        # Le catalogue reste lisible : un point de terminaison anonyme mais
        # compatible OpenAI est utilisable, il n'est simplement pas nommé.
        self.assertEqual(fp.models, ("un-modele",))
        self.assertNotIn("models", fp.unknown)

    def test_une_table_vide_ne_leve_pas(self):
        fp = identify({})
        self.assertEqual(fp.software, "")
        self.assertEqual(
            fp.unknown, frozenset({"software", "version", "models"})
        )


class Plan(unittest.TestCase):
    """Ce que la découverte s'autorise à émettre, avant toute socket."""

    def test_le_plan_ne_contient_que_des_GET_sans_doublon(self):
        plan = probe_plan()
        self.assertTrue(plan, "le plan de sonde est vide")
        self.assertEqual({methode for methode, _ in plan}, {"GET"})
        chemins = [chemin for _, chemin in plan]
        self.assertEqual(len(chemins), len(set(chemins)))

    def test_readyz_precede_tout_ce_qui_ressemble_a_ollama(self):
        chemins = [chemin for _, chemin in probe_plan()]
        self.assertEqual(chemins[0], "/readyz")
        for tardif in ("/api/tags", "/", "/api/version"):
            self.assertLess(chemins.index("/readyz"), chemins.index(tardif))

    def test_aucun_chemin_du_plan_ne_declenche_une_generation(self):
        chemins = [chemin for _, chemin in probe_plan()]
        # `/api/show` est un POST : il appartient à l'interrogation des
        # capacités, après le choix d'un serveur. Un balayage qui l'émettrait
        # pourrait charger un modèle.
        self.assertNotIn("/api/show", chemins)
        for interdit in ("/completion", "/v1/chat/completions", "/api/chat"):
            self.assertNotIn(interdit, chemins)

    def test_les_ports_a_frapper_sont_uniques_et_portent_celui_de_gpt4all(
        self,
    ):
        self.assertEqual(len(PORTS), len(set(PORTS)))
        self.assertEqual(len(PORTS), 12)
        self.assertIn(GPT4ALL_PORT, PORTS)


if __name__ == "__main__":
    unittest.main()
