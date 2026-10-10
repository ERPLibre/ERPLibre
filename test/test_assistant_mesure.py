#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un tour a coûté : les comptes, et ce qui descend sur le disque.

Ce fichier ne touche ni serveur ni horloge. L'horodatage est INJECTÉ et le
journal s'écrit dans un dossier temporaire ; aucun test n'ajoute une ligne au
journal réel du dépôt, qui décrit une machine et vit sous `private/`.

Trois régressions sont visées par leur nom.

**Le zéro qui se fait passer pour une mesure.** Un serveur ne rend pas
toujours ses comptes de jetons — un flux n'en porte que si l'option a été
demandée, et certains logiciels n'en portent jamais. Lire une absence comme un
zéro donne un débit de zéro jeton par seconde, qui s'affiche comme un serveur
à l'arrêt alors qu'il vient de répondre. L'absence vaut `None`, et l'écran
montre un tiret.

**La division par une durée que l'horloge n'a pas séparée.** Un tour qui
revient du cache se mesure à zéro seconde, et un débit infini se lit comme une
mesure exceptionnelle au lieu d'un calcul qui n'a pas de sens.

**Le texte de l'échange qui remonte dans le journal.** Une question est ce que
l'utilisateur a tapé ; le journal vit sous `private/`, qui devient public avec
un fork public. Seule une empreinte courte y figure, et un test lit la ligne
entière pour s'assurer qu'aucun champ ne porte le texte.

Les valeurs des jeux d'essai sont INVENTÉES : `.claude/rules/04-code-conventions.md`
l'exige pour ce qui illustre un interdit.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant import mesure  # noqa: E402
from script.todo.assistant.servers import Server  # noqa: E402

# Un instant figé, pour que le mois du fichier et la ligne soient vérifiables.
INSTANT = "2026-03-04T05:06:07-05:00"

# Un serveur d'essai. L'adresse est de la plage de documentation et le modèle
# est inventé : rien ici ne désigne une machine réelle.
SERVEUR = Server(
    handle="server-1",
    label="essai",
    host="192.0.2.21",
    port=8000,
    software="logiciel-invente",
    model="famille-inventee/modele-a",
    hosting="lan",
    secret_ref="",
)

USAGE = {"prompt_tokens": 120, "completion_tokens": 300}


def une_mesure(**ecarts):
    """Une mesure d'essai, ses défauts nommés une seule fois."""
    arguments = {
        "seance": "seance-inventee",
        "rang": 1,
        "serveur": SERVEUR,
        "question": "une question inventée",
        "duree": 12.0,
        "premier": 0.5,
        "faits": {"usage": dict(USAGE), "finish_reason": "stop"},
        "maintenant": lambda: INSTANT,
    }
    arguments.update(ecarts)
    return mesure.mesurer(**arguments)


class LesComptes(unittest.TestCase):
    def test_le_debit_suit_les_jetons_rendus_et_la_duree_mesuree(self):
        m = une_mesure()
        self.assertEqual(120, m.invite)
        self.assertEqual(300, m.reponse)
        self.assertEqual(25.0, m.debit)
        self.assertEqual(12.0, m.duree)
        self.assertEqual(0.5, m.premier)
        self.assertEqual("stop", m.fin)

    def test_un_compte_absent_est_inconnu_et_jamais_zero(self):
        """Le mode de défaillance : un serveur qui vient de répondre
        s'affiche à zéro jeton par seconde, donc à l'arrêt."""
        for faits in ({}, {"usage": None}, {"usage": {}}, {"usage": []}):
            with self.subTest(faits=faits):
                m = une_mesure(faits=faits)
                self.assertIsNone(m.invite)
                self.assertIsNone(m.reponse)
                self.assertIsNone(m.debit)

    def test_un_compte_qui_n_est_pas_un_entier_est_inconnu(self):
        """Le corps vient d'un tiers : rien de sa forme n'est garanti."""
        for valeur in ("300", 3.5, True, None, [], {}):
            with self.subTest(valeur=valeur):
                m = une_mesure(faits={"usage": {"completion_tokens": valeur}})
                self.assertIsNone(m.reponse)

    def test_une_duree_nulle_ne_rend_pas_un_debit_infini(self):
        """Un tour servi depuis un cache se mesure à zéro seconde, et un
        débit infini se lirait comme une mesure exceptionnelle."""
        self.assertIsNone(mesure.debit(300, 0))
        self.assertIsNone(mesure.debit(300, -1))
        self.assertIsNone(une_mesure(duree=0).debit)

    def test_le_modele_rapporte_prime_sur_celui_qu_on_a_demande(self):
        """Un serveur qui sert autre chose que ce qu'on nomme est
        précisément ce que le journal doit montrer."""
        m = une_mesure(faits={"model": "famille-inventee/modele-b"})
        self.assertEqual("famille-inventee/modele-b", m.modele)
        # Sans rapport, on retombe sur le modèle demandé.
        self.assertEqual(SERVEUR.model, une_mesure(faits={}).modele)

    def test_un_envoi_sans_fragment_n_a_pas_de_premier_jeton(self):
        """`premier` vaut None sur un envoi d'un seul bloc comme sur une
        panne survenue avant le premier fragment : les deux sont « rien
        n'est arrivé au fil », et aucun n'est un délai de zéro."""
        self.assertIsNone(une_mesure(premier=None).premier)


class LEmpreinteDeLaQuestion(unittest.TestCase):
    def test_la_meme_question_rend_la_meme_empreinte(self):
        self.assertEqual(
            mesure.empreinte("  une question inventée  "),
            mesure.empreinte("une question inventée"),
        )

    def test_deux_questions_differentes_se_separent(self):
        self.assertNotEqual(
            mesure.empreinte("première question inventée"),
            mesure.empreinte("seconde question inventée"),
        )

    def test_une_question_vide_ne_fait_pas_lever(self):
        for vide in ("", None, "   "):
            with self.subTest(vide=vide):
                self.assertEqual(
                    mesure.EMPREINTE_LEN, len(mesure.empreinte(vide))
                )


class LaLigneDeJournal(unittest.TestCase):
    def test_aucun_champ_ne_porte_le_texte_de_l_echange(self):
        """Le journal vit sous `private/`, qui devient public avec un fork
        public. La question est ce que l'utilisateur a tapé."""
        secret = "phrase-temoin-qui-ne-doit-pas-sortir"
        m = une_mesure(question=secret)
        brut = mesure.ligne(m)
        self.assertNotIn(secret, brut)
        entree = json.loads(brut)
        for cle, valeur in entree.items():
            with self.subTest(cle=cle):
                self.assertNotIn(secret, str(valeur))
        self.assertEqual(mesure.empreinte(secret), entree["empreinte"])

    def test_la_ligne_est_du_json_sur_une_seule_ligne(self):
        """Un journal en lignes indépendantes se répare en le tronquant ;
        une ligne qui en porte deux casse ce qui suit."""
        brut = mesure.ligne(une_mesure())
        self.assertNotIn("\\n", brut)
        self.assertIsInstance(json.loads(brut), dict)

    def test_un_compte_inconnu_s_ecrit_null_et_non_zero(self):
        entree = json.loads(mesure.ligne(une_mesure(faits={})))
        self.assertIsNone(entree["reponse"])
        self.assertIsNone(entree["debit"])


class LeFichierMensuel(unittest.TestCase):
    def test_le_mois_se_lit_dans_l_horodatage_pas_a_l_horloge(self):
        """Une mesure réécrite plus tard retombe dans le fichier de SON
        mois, et non dans celui du jour où on la rejoue."""
        chemin = mesure.chemin(INSTANT, racine="/racine-inventee")
        self.assertTrue(str(chemin).endswith("mesures-2026-03.jsonl"))
        self.assertIn("private", str(chemin))

    def test_un_horodatage_abime_ne_fait_pas_lever(self):
        for abime in ("", None, "pas une date"):
            with self.subTest(abime=abime):
                self.assertTrue(
                    str(mesure.chemin(abime, racine="/x")).endswith(".jsonl")
                )

    def test_les_lignes_s_ajoutent_sans_ecraser_les_precedentes(self):
        """L'ajout est ce qui rend deux écrivains inoffensifs l'un pour
        l'autre ; une relecture-réécriture perdrait la ligne de l'autre."""
        with tempfile.TemporaryDirectory() as dossier:
            for rang in (1, 2, 3):
                mesure.ecrire(une_mesure(rang=rang), racine=dossier)
            lues = mesure.lire(mesure.chemin(INSTANT, racine=dossier))
        self.assertEqual([1, 2, 3], [entree["rang"] for entree in lues])

    def test_un_dossier_absent_est_cree(self):
        with tempfile.TemporaryDirectory() as dossier:
            cible = mesure.ecrire(une_mesure(), racine=dossier)
            self.assertIsNotNone(cible)
            self.assertTrue(os.path.exists(cible))

    def test_une_ecriture_impossible_ne_tue_pas_la_conversation(self):
        """Un journal est une commodité d'analyse : perdre une ligne est un
        moindre mal, et compter ne doit pas pouvoir interrompre un échange."""
        with tempfile.TemporaryDirectory() as dossier:
            barrage = os.path.join(dossier, "private")
            # Un FICHIER là où le dossier doit aller : la création échoue.
            with open(barrage, "w", encoding="utf-8") as fichier:
                fichier.write("")
            self.assertIsNone(mesure.ecrire(une_mesure(), racine=dossier))

    def test_une_ligne_abimee_n_emporte_pas_les_voisines(self):
        """Un disque plein coupe une ligne en deux ; les suivantes restent
        lisibles, et c'est ce qui rend le journal réparable."""
        with tempfile.TemporaryDirectory() as dossier:
            mesure.ecrire(une_mesure(rang=1), racine=dossier)
            cible = mesure.chemin(INSTANT, racine=dossier)
            with open(cible, "a", encoding="utf-8") as fichier:
                fichier.write('{"rang": 2, "cou\n')
                fichier.write("\n")
            mesure.ecrire(une_mesure(rang=3), racine=dossier)
            lues = mesure.lire(cible)
        self.assertEqual([1, 3], [entree["rang"] for entree in lues])

    def test_un_fichier_absent_se_lit_comme_un_journal_vide(self):
        self.assertEqual([], mesure.lire("/chemin-invente/absent.jsonl"))


if __name__ == "__main__":
    unittest.main()
