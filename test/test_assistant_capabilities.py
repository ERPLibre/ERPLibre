#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un serveur annonce, ce qu'un gpt exige, et qui grise l'autre.

Ce qui casserait sans ces tests est une régression silencieuse, pas une
exception : le catalogue s'afficherait, et il serait faux.

D'un côté, GRISER SUR L'INCONNU. Le point de terminaison le plus courant
n'annonce aucune capacité ; qui traite « pas de réponse » comme « non »
grise tout le catalogue devant lui, et l'utilisateur n'a rien à répondre à un
refus qui ne repose sur rien. De l'autre, l'échelle d'hébergement, seule
exigence qui grise avant d'avoir parlé au serveur : y inverser deux barreaux
présente un tiers comme la machine locale, et c'est un envoi de données qui
part sans que personne n'ait été prévenu.

Aucun test n'ouvre de socket ni n'interroge un résolveur : le transport et la
résolution arrivent par argument nommé. Les noms d'hôte portent tous le
domaine réservé « .invalid », qu'aucun résolveur ne peut faire aboutir — si
l'injection cessait d'être branchée, le test échouerait au lieu d'interroger
le DNS de qui le lance.

Les corps de réponse viennent de `llm_fake_server.FIXTURES`, la table que
lisent aussi les tests de transport : deux tables se seraient contredites sans
que rien ne le montre. `/api/show` n'y est pas et se définit ici, parce que la
découverte n'émet que des GET et qu'elle n'a donc jamais eu à le connaître.
"""
import ipaddress
import os
import sys
import unittest
from dataclasses import replace

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from llm_fake_server import FIXTURES  # noqa: E402

from script.todo.assistant import capabilities  # noqa: E402
from script.todo.assistant.capabilities import (  # noqa: E402
    NOTHING_ANNOUNCED,
    Capabilities,
    classify_hosting,
    match,
)
from script.todo.assistant.fingerprint import Fingerprint  # noqa: E402

HOTE = "127.0.0.1"
PORT = 11434

# Des noms inventés, dans le domaine réservé aux noms qui n'existent pas.
NOM_LOCAL = "boite-a-modeles.invalid"
NOM_LAN = "modele-du-quartier.invalid"
NOM_MORT = "modele-lointain.invalid"
NOM_MIXTE = "modele-a-deux-faces.invalid"

# Une adresse privée inventée, et une adresse publique prise dans le préfixe
# de relais 6to4, retiré du service et rendu à l'IANA : elle est globale pour
# `ipaddress` et ne désigne aucune machine.
PRIVEE = "10.42.0.7"
PUBLIQUE = "192.88.99.1"

# Le modèle que la table partagée fait annoncer par Ollama.
MODELE = "petit-modele:7b"

# `POST /api/show` : l'énumération de capacités et le bloc `model_info`. Le
# compte de paramètres y est un ENTIER de paramètres, que la lecture ramène en
# milliards ; la longueur de contexte porte le nom de l'architecture en
# préfixe.
SHOW = (
    200,
    b'{"capabilities":["completion","tools"],'
    b'"model_info":{"general.architecture":"petit",'
    b'"petit.context_length":8192,'
    b'"general.parameter_count":7241732096}}',
)

# Le même serveur, qui ne publie pas son bloc `model_info`.
SHOW_SANS_INFO = (200, b'{"capabilities":["completion","vision"]}')


def desservir(table, journal=None):
    """Un transport injecté qui sert `table` par chemin, 404 pour le reste.

    La même fonction tient le GET et le POST : le POST reçoit une charge utile
    de plus, dont une table figée n'a pas besoin pour choisir sa réponse.
    `journal` reçoit chaque appel, ce qui permet d'affirmer qu'il n'y en a eu
    aucun.
    """

    def repondre(host, port, path, payload=None):
        if journal is not None:
            journal.append(path)
        return table.get(path, (404, b""))

    return repondre


def resoudre(table):
    """Un résolveur injecté : un nom absent de `table` ne résout pas."""

    def resolve(host):
        if host not in table:
            raise OSError("nom inconnu")
        return table[host]

    return resolve


def lire(software, table=None, *, poste=None, models=(), journal=None):
    """`read` avec ses DEUX transports injectés, jamais un seul.

    N'injecter que le GET laisserait le POST d'`/api/show` partir sur une
    vraie socket dès qu'un lecteur change d'avis sur ce qu'il interroge. Le
    test n'a pas à y penser : l'aide branche les deux.
    """
    return capabilities.read(
        Fingerprint(software, models=tuple(models)),
        HOTE,
        PORT,
        http_get=desservir(table or {}, journal),
        http_post=desservir(poste or {}, journal),
    )


class Hebergement(unittest.TestCase):
    """La classe d'hébergement : la seule exigence jamais inconnue."""

    def test_la_boucle_locale_est_testee_avant_le_prive(self):
        # `ipaddress` rapporte la boucle locale comme privée AUSSI : tester
        # `is_private` d'abord classerait la machine même comme du réseau
        # local, et un gpt qui exige `loopback` s'y grise.
        self.assertTrue(ipaddress.ip_address(HOTE).is_private)
        self.assertEqual(classify_hosting(HOTE), "loopback")
        self.assertEqual(classify_hosting("::1"), "loopback")
        self.assertEqual(classify_hosting("[::1]"), "loopback")

    def test_un_nom_qui_ne_resout_pas_se_lit_comme_global(self):
        # Deux façons d'échouer, une seule lecture : le résolveur lève, ou il
        # ne rend rien. Un nom qu'on ne sait pas placer n'est jamais local.
        self.assertEqual(
            classify_hosting(NOM_MORT, resolve=resoudre({})), "global"
        )
        self.assertEqual(
            classify_hosting(NOM_MORT, resolve=resoudre({NOM_MORT: []})),
            "global",
        )

    def test_un_nom_se_classe_par_l_adresse_qu_il_resout(self):
        resolve = resoudre({NOM_LOCAL: [HOTE], NOM_LAN: [PRIVEE]})
        self.assertEqual(
            classify_hosting(NOM_LOCAL, resolve=resolve), "loopback"
        )
        self.assertEqual(classify_hosting(NOM_LAN, resolve=resolve), "lan")

    def test_un_nom_a_plusieurs_adresses_prend_la_plus_pessimiste(self):
        # Une destination n'est locale que si TOUTES ses adresses le sont :
        # l'envoi partira vers celle que le système choisira, pas vers celle
        # qui arrangeait le classement.
        resolve = resoudre({NOM_MIXTE: [HOTE, PUBLIQUE]})
        self.assertEqual(
            classify_hosting(NOM_MIXTE, resolve=resolve), "global"
        )

    def test_ce_qui_n_est_ni_local_ni_prive_est_un_tiers(self):
        # La plage de transition d'opérateur n'est ni privée ni globale pour
        # `ipaddress` : le rang le plus haut est celui qui ne promet rien.
        for host in (PUBLIQUE, "100.64.0.1", "", "   "):
            with self.subTest(host=host):
                self.assertEqual(classify_hosting(host), "global")


class Appariement(unittest.TestCase):
    """Ce qui grise une entrée du catalogue, et ce qui ne la grise pas."""

    def test_inconnu_ne_grise_jamais(self):
        exigeant = {
            "hosting": "any",
            "context_window": 32000,
            "parameters": 12,
            "tool_calling": True,
            "vision": True,
            "json_output": True,
        }
        verdict, raison = match(exigeant, NOTHING_ANNOUNCED, "global")
        self.assertEqual(verdict, "unknown")
        self.assertNotEqual(raison, "")
        for cle, valeur in exigeant.items():
            if cle == "hosting":
                continue
            with self.subTest(cle=cle):
                seule = {"hosting": "any", cle: valeur}
                verdict, _ = match(seule, NOTHING_ANNOUNCED, "global")
                self.assertEqual(verdict, "unknown")

    def test_une_exigence_contredite_grise_avec_sa_raison(self):
        lu = Capabilities(tool_calling=False, vision=True)
        verdict, raison = match(
            {"hosting": "any", "tool_calling": True}, lu, "loopback"
        )
        self.assertEqual(verdict, "no")
        self.assertEqual(raison, capabilities.REASON_TOOLS)

    def test_loopback_satisfait_lan_satisfait_any(self):
        attendus = {
            ("loopback", "loopback"): "ok",
            ("loopback", "lan"): "ok",
            ("loopback", "any"): "ok",
            ("lan", "loopback"): "no",
            ("lan", "lan"): "ok",
            ("lan", "any"): "ok",
            ("global", "loopback"): "no",
            ("global", "lan"): "no",
            ("global", "any"): "ok",
        }
        self.assertTrue(attendus, "aucun couple à vérifier")
        for (hosting, exige), attendu in attendus.items():
            with self.subTest(hosting=hosting, exige=exige):
                verdict, raison = match(
                    {"hosting": exige}, NOTHING_ANNOUNCED, hosting
                )
                self.assertEqual(verdict, attendu)
                if attendu == "no":
                    self.assertEqual(raison, capabilities.REASON_HOSTING)

    def test_sans_exigence_d_hebergement_le_defaut_refuse_un_tiers(self):
        self.assertEqual(match({}, NOTHING_ANNOUNCED, "lan"), ("ok", ""))
        self.assertEqual(match({}, NOTHING_ANNOUNCED, "loopback"), ("ok", ""))
        verdict, raison = match({}, NOTHING_ANNOUNCED, "global")
        self.assertEqual(verdict, "no")
        self.assertEqual(raison, capabilities.REASON_HOSTING)

    def test_un_barreau_que_l_echelle_ignore_ne_grise_pas(self):
        # Une faute de frappe dans l'en-tête d'un gpt n'est pas une
        # contradiction : elle se signale, elle ne refuse pas.
        verdict, raison = match(
            {"hosting": "sur-la-lune"}, NOTHING_ANNOUNCED, "loopback"
        )
        self.assertEqual(verdict, "unknown")
        self.assertIn("hosting", raison)

    def test_un_contexte_plus_petit_que_demande_est_le_seul_nombre_dur(self):
        lu = Capabilities(
            context_window=8192,
            parameters=3.0,
            estimated=frozenset({"parameters"}),
        )
        exige = {"hosting": "any", "context_window": 32000, "parameters": 7}
        verdict, raison = match(exige, lu, "loopback")
        self.assertEqual(verdict, "no")
        self.assertEqual(raison, capabilities.REASON_CONTEXT)
        # Le contexte satisfait, il ne reste que l'écart sur une estimation :
        # elle ne grise pas, elle se répète par son nom à l'envoi.
        assez = replace(lu, context_window=32768)
        verdict, raison = match(exige, assez, "loopback")
        self.assertEqual(verdict, "unknown")
        self.assertIn("parameters", raison)

    def test_un_nombre_de_parametres_estime_ne_grise_pas(self):
        devine = Capabilities(
            parameters=3.0, estimated=frozenset({"parameters"})
        )
        exige = {"hosting": "any", "parameters": 7}
        self.assertEqual(match(exige, devine, "loopback")[0], "unknown")
        # Le même écart, mais LU sur le serveur, grise.
        self.assertEqual(
            match(exige, Capabilities(parameters=3.0), "loopback"),
            ("no", capabilities.REASON_PARAMETERS),
        )

    def test_la_raison_nomme_la_cle_qu_on_n_a_pas_pu_verifier(self):
        exigences = {
            "context_window": 8000,
            "parameters": 7,
            "tool_calling": True,
            "vision": True,
            "json_output": True,
        }
        self.assertTrue(exigences, "aucune exigence à vérifier")
        for cle, valeur in exigences.items():
            with self.subTest(cle=cle):
                verdict, raison = match(
                    {"hosting": "any", cle: valeur},
                    NOTHING_ANNOUNCED,
                    "loopback",
                )
                self.assertEqual(verdict, "unknown")
                self.assertIn(cle, raison)

    def test_une_cle_hors_de_l_ensemble_ferme_n_est_pas_avalee(self):
        verdict, raison = match(
            {"hosting": "any", "quantisation": "Q4"},
            NOTHING_ANNOUNCED,
            "loopback",
        )
        self.assertEqual(verdict, "unknown")
        self.assertEqual(raison, capabilities.REASON_UNCHECKED_OTHER)

    def test_une_exigence_a_faux_est_satisfaite_par_n_importe_quoi(self):
        # Un gpt qui déclare ne pas avoir besoin de la vision n'a pas à
        # attendre qu'un serveur muet la lui annonce.
        exige = {"hosting": "any", "vision": False, "tool_calling": False}
        self.assertEqual(match(exige, NOTHING_ANNOUNCED, "global"), ("ok", ""))

    def test_une_contradiction_l_emporte_sur_une_inconnue(self):
        lu = Capabilities(context_window=4096)
        exige = {"hosting": "any", "context_window": 8000, "vision": True}
        self.assertEqual(
            match(exige, lu, "loopback"),
            ("no", capabilities.REASON_CONTEXT),
        )


class Lecture(unittest.TestCase):
    """Les trois degrés d'honnêteté : ce qui se lit, ce qui se devine,
    et ce qui manque."""

    def test_ollama_traduit_ses_capacites_depuis_l_enumeration(self):
        journal = []
        caps = lire(
            "ollama",
            FIXTURES["ollama"],
            poste={"/api/show": SHOW},
            models=[MODELE],
            journal=journal,
        )
        # Un seul aller-retour : `/api/show` a tout dit, et `/api/tags` est le
        # repli, pas un passage obligé.
        self.assertEqual(journal, ["/api/show"])
        self.assertIs(caps.tool_calling, True)
        # L'énumération ne porte ni « vision » ni « image » : c'est une
        # négation LUE, et elle peut donc griser.
        self.assertIs(caps.vision, False)
        self.assertEqual(caps.context_window, 8192)
        self.assertEqual(caps.parameters, 7.24)
        self.assertEqual(caps.estimated, frozenset())
        # Aucun serveur de la table n'annonce la sortie JSON.
        self.assertIsNone(caps.json_output)

    def test_localai_est_lu_par_le_lecteur_d_ollama(self):
        caps = lire(
            "localai",
            FIXTURES["ollama"],
            poste={"/api/show": SHOW},
            models=[MODELE],
        )
        self.assertEqual(caps.context_window, 8192)
        self.assertIs(caps.tool_calling, True)

    def test_une_taille_lue_dans_les_tags_n_est_pas_estimee(self):
        # Sans `model_info`, le repli lit le `parameter_size` que le serveur
        # publie déjà : une lecture, donc rien dans `estimated`.
        journal = []
        caps = lire(
            "ollama",
            FIXTURES["ollama"],
            poste={"/api/show": SHOW_SANS_INFO},
            models=[MODELE],
            journal=journal,
        )
        self.assertEqual(journal, ["/api/show", "/api/tags"])
        self.assertEqual(caps.parameters, 7.2)
        self.assertEqual(caps.estimated, frozenset())
        self.assertIsNone(caps.context_window)
        self.assertIs(caps.vision, True)

    def test_un_nombre_de_parametres_absent_est_devine_dans_le_nom(self):
        caps = lire("ollama", {}, models=[MODELE])
        self.assertEqual(caps.parameters, 7.0)
        self.assertEqual(caps.estimated, frozenset({"parameters"}))
        # Et la devinette ne grise rien, si loin du compte soit-elle.
        verdict, _ = match(
            {"hosting": "any", "parameters": 70}, caps, "loopback"
        )
        self.assertEqual(verdict, "unknown")

    def test_llamacpp_donne_les_outils_et_la_vision_depuis_props(self):
        caps = lire(
            "llamacpp", FIXTURES["llamacpp"], models=["un-modele.gguf"]
        )
        self.assertIs(caps.tool_calling, True)
        self.assertIs(caps.vision, False)
        self.assertEqual(caps.context_window, 32768)
        self.assertEqual(caps.parameters, 7.0)
        self.assertEqual(caps.estimated, frozenset())

    def test_llamacpp_lit_les_deux_noms_du_drapeau_d_outils(self):
        table = dict(FIXTURES["llamacpp"])
        table["/props"] = (
            200,
            b'{"build_info":"b0-0","chat_template_caps":'
            b'{"supports_tool_calls":true}}',
        )
        caps = lire("llamacpp", table, models=["un-modele.gguf"])
        self.assertIs(caps.tool_calling, True)
        self.assertIsNone(caps.vision)

    def test_lmstudio_donne_le_contexte_et_la_vision_sans_les_outils(self):
        caps = lire("lmstudio", FIXTURES["lmstudio"], models=["un-modele"])
        self.assertEqual(caps.context_window, 8192)
        self.assertIs(caps.vision, False)
        # Aucun drapeau d'outils n'existe chez ce serveur : le champ reste
        # vide, parce qu'un `False` inventé griserait un serveur qui appelle
        # des outils en vrai.
        self.assertIsNone(caps.tool_calling)

    def test_lmstudio_nomme_la_vision_par_le_type_du_modele(self):
        table = {
            "/api/v0/models": (
                200,
                b'{"data":[{"id":"un-modele","type":"vlm",'
                b'"max_context_length":4096}]}',
            )
        }
        caps = lire("lmstudio", table, models=["un-modele"])
        self.assertIs(caps.vision, True)

    def test_koboldcpp_annonce_ses_booleens_sans_aucun_contexte(self):
        table = {
            "/api/extra/version": (
                200,
                b'{"result":"KoboldCpp","version":"0.0","vision":true}',
            )
        }
        caps = lire("koboldcpp", table)
        self.assertIs(caps.vision, True)
        self.assertIsNone(caps.context_window)
        self.assertIsNone(caps.tool_calling)
        # Le corps partagé ne porte pas le drapeau : la vision reste vide.
        self.assertIsNone(lire("koboldcpp", FIXTURES["koboldcpp"]).vision)

    def test_un_serveur_qui_n_annonce_rien_rend_tout_a_none(self):
        journal = []
        self.assertTrue(capabilities.SILENT, "la famille muette est vide")
        for software in sorted(capabilities.SILENT):
            with self.subTest(software=software):
                caps = lire(
                    software,
                    FIXTURES.get(software, {}),
                    models=["un-modele-7b"],
                    journal=journal,
                )
                self.assertEqual(caps, NOTHING_ANNOUNCED)
        # Le nom du modèle porte sa taille : la rendre vide prouve que le
        # lecteur n'a pas tourné du tout, et le journal qu'aucune requête n'est
        # partie vers un serveur qui n'a rien à en dire.
        self.assertEqual(journal, [])

    def test_un_logiciel_non_reconnu_ne_fait_aucune_requete(self):
        journal = []
        caps = lire("", FIXTURES["ollama"], models=[MODELE], journal=journal)
        self.assertEqual(caps, NOTHING_ANNOUNCED)
        self.assertEqual(journal, [])

    def test_un_corps_qui_n_est_pas_du_json_laisse_tout_a_none(self):
        # Une page d'administration de routeur répond volontiers, en HTML, à
        # n'importe quel chemin.
        caps = lire("llamacpp", FIXTURES["routeur"], models=["un-modele.gguf"])
        self.assertEqual(caps, NOTHING_ANNOUNCED)

    def test_un_statut_qui_n_est_pas_200_n_annonce_aucune_capacite(self):
        # Un démarrage et un défi d'authentification sont des serveurs
        # vivants, mais ils n'annoncent aucune capacité.
        for statut in (401, 503):
            with self.subTest(statut=statut):
                corps = FIXTURES["llamacpp"]["/props"][1]
                table = {"/props": (statut, corps)}
                caps = lire("llamacpp", table, models=["un-modele.gguf"])
                self.assertEqual(caps, NOTHING_ANNOUNCED)

    def test_un_drapeau_lu_comme_un_nombre_n_est_pas_une_longueur(self):
        # `isinstance(True, int)` est vrai : un booléen pris pour un contexte
        # de 1 serait une capacité inventée, et elle griserait.
        table = {
            "/v1/models": (
                200,
                b'{"data":[{"id":"un-modele.gguf",'
                b'"meta":{"n_ctx_train":true,"n_params":0}}]}',
            )
        }
        caps = lire("llamacpp", table, models=["un-modele.gguf"])
        self.assertIsNone(caps.context_window)
        self.assertIsNone(caps.parameters)


if __name__ == "__main__":
    unittest.main()
