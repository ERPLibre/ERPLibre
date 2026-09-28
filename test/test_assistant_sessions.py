#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les conversations gardées : ce qui s'écrit, et ce qui se reprend.

Aucun test ici ne touche le dossier de l'utilisateur : chacun écrit dans un
dossier temporaire qu'il crée et détruit. C'est la précaution qui manquait la
première fois — la suite avait laissé huit fausses séances chez la personne
qui la lançait, indiscernables des vraies à la relecture.

Trois régressions sont visées par leur nom.

**Le nom qui écrase.** L'export nommait ses fichiers d'après le seul nombre de
tours : deux conversations de la même longueur portaient le même nom, et la
seconde effaçait la première sans un mot. Le nom d'une séance porte donc la
date ET un identifiant.

**Les droits trop larges.** `~/.erplibre` est lisible par tous les comptes de
la machine, et une conversation porte ce qu'on y a tapé. Le dossier est en
0700 et les fichiers en 0600 dès leur création : un `open` ordinaire les
créerait avec le masque du compte, souvent lisible par tout le monde.

**La ligne abîmée qui emporte la séance.** Un disque plein coupe une ligne en
deux. Les voisines doivent rester lisibles, sans quoi une coupure perd la
conversation entière au lieu d'un tour.

Les questions, les réponses et les modèles des jeux d'essai sont INVENTÉS.
"""

import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant import sessions  # noqa: E402
from script.todo.assistant.chat import Turn  # noqa: E402
from script.todo.assistant.servers import Server  # noqa: E402

DEBUT = "2026-03-04T05:06:07-05:00"
SEANCE = "a1b2c3d4e5f6"

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


class UneSeanceEcrite(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.base = self.dossier.name
        self.addCleanup(self.dossier.cleanup)

    def _ouvrir(self, seance=SEANCE, debut=DEBUT):
        return sessions.ouvrir(
            seance, SERVEUR, outil="outil-invente", debut=debut, base=self.base
        )

    def test_le_nom_porte_la_date_et_l_identifiant(self):
        """Deux conversations de la même longueur portaient le même nom, et
        la seconde effaçait la première sans un mot."""
        cible = self._ouvrir()
        self.assertTrue(str(cible).endswith(f"2026-03-04-{SEANCE}.jsonl"))
        autre = self._ouvrir(seance="0000aaaa1111")
        self.assertNotEqual(str(cible), str(autre))

    def test_deux_seances_du_meme_jour_ne_s_ecrasent_pas(self):
        premiere = self._ouvrir()
        sessions.noter(premiere, Turn("user", "première question inventée"))
        sessions.noter(premiere, Turn("assistant", "première réponse"))
        seconde = self._ouvrir(seance="0000aaaa1111")
        sessions.noter(seconde, Turn("user", "seconde question inventée"))
        sessions.noter(seconde, Turn("assistant", "seconde réponse"))
        titres = [vue.titre for vue in sessions.lister(base=self.base)]
        self.assertEqual(2, len(titres))
        self.assertIn("première question inventée", titres)
        self.assertIn("seconde question inventée", titres)

    def test_les_droits_ne_laissent_lire_que_le_proprietaire(self):
        """`~/.erplibre` est lisible par tous les comptes de la machine, et
        une conversation porte ce qu'on y a tapé."""
        cible = self._ouvrir()
        self.assertEqual(
            0o600, stat.S_IMODE(os.stat(cible).st_mode), "fichier trop ouvert"
        )
        self.assertEqual(
            0o700,
            stat.S_IMODE(os.stat(os.path.dirname(cible)).st_mode),
            "dossier trop ouvert",
        )

    def test_chaque_tour_s_ajoute_sans_relire_le_fichier(self):
        cible = self._ouvrir()
        for rang in range(3):
            sessions.noter(cible, Turn("user", f"question {rang}"))
            sessions.noter(cible, Turn("assistant", f"réponse {rang}"))
        lues = sessions._lignes(cible)
        self.assertEqual(sessions.ENTETE, lues[0].get("kind"))
        self.assertEqual(7, len(lues))

    def test_le_raisonnement_ne_se_confond_pas_avec_la_reponse(self):
        """Il est payé dans les jetons de la réponse ; le confondre avec elle
        ferait relire comme dit ce qui n'a été que pensé."""
        cible = self._ouvrir()
        sessions.noter(
            cible,
            Turn("assistant", "la réponse", reasoning="la réflexion"),
        )
        derniere = sessions._lignes(cible)[-1]
        self.assertEqual("la réponse", derniere["text"])
        self.assertEqual("la réflexion", derniere["reasoning"])

    def test_une_ecriture_impossible_ne_tue_pas_la_conversation(self):
        """Garder une conversation est un service rendu, pas une condition
        pour en tenir une."""
        barrage = os.path.join(self.base, "sessions-bloquees")
        with open(barrage, "w", encoding="utf-8") as fichier:
            fichier.write("")
        # Un FICHIER là où le dossier doit aller : la création échoue.
        self.assertIsNone(
            sessions.ouvrir(SEANCE, SERVEUR, debut=DEBUT, base=barrage)
        )
        self.assertFalse(sessions.noter(None, Turn("user", "x")))


class UneSeanceRelue(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.base = self.dossier.name
        self.addCleanup(self.dossier.cleanup)
        self.cible = sessions.ouvrir(
            SEANCE, SERVEUR, outil="outil-invente", debut=DEBUT, base=self.base
        )
        sessions.noter(self.cible, Turn("user", "  une   question inventée "))
        sessions.noter(self.cible, Turn("assistant", "une réponse inventée"))

    def test_le_resume_porte_de_quoi_reconnaitre_la_seance(self):
        """Une date et un modèle ne distinguent pas deux conversations du
        même après-midi ; la question qui l'a ouverte, si."""
        (vue,) = sessions.lister(base=self.base)
        self.assertEqual(SEANCE, vue.seance)
        self.assertEqual(SERVEUR.model, vue.modele)
        self.assertEqual("outil-invente", vue.outil)
        self.assertEqual(1, vue.tours)
        self.assertEqual("une question inventée", vue.titre)

    def test_un_titre_trop_long_est_coupe(self):
        cible = sessions.ouvrir(
            "1111bbbb2222", SERVEUR, debut=DEBUT, base=self.base
        )
        sessions.noter(cible, Turn("user", "mot " * 80))
        sessions.noter(cible, Turn("assistant", "une réponse"))
        vues = {vue.seance: vue for vue in sessions.lister(base=self.base)}
        self.assertLessEqual(
            len(vues["1111bbbb2222"].titre), sessions.TITRE_MAX
        )

    def test_la_reprise_rend_les_tours_tels_qu_ils_etaient(self):
        """Le modèle doit recevoir au tour suivant ce qu'il aurait reçu sans
        l'interruption."""
        tours = sessions.charger(self.cible)
        self.assertEqual(
            [
                ("user", "  une   question inventée "),
                ("assistant", "une réponse inventée"),
            ],
            [(tour.role, tour.text) for tour in tours],
        )

    def test_une_question_sans_reponse_ne_repart_pas_dans_l_historique(self):
        """Le fichier la garde — elle a été posée — mais la rejouer seule
        enverrait deux questions d'affilée au modèle, alors que la
        conversation en mémoire n'a jamais rien gardé d'un tour en panne."""
        sessions.noter(self.cible, Turn("user", "question qui échoue"))
        sessions.noter(self.cible, Turn("error", "404 pas d'instance"))
        roles = [entree.get("role") for entree in sessions._lignes(self.cible)]
        self.assertIn("error", roles, "la panne doit rester sur le disque")
        textes = [tour.text for tour in sessions.charger(self.cible)]
        self.assertNotIn("question qui échoue", textes)

    def test_une_reponse_coupee_avec_du_texte_repart(self):
        """Ce qui est arrivé a été payé : le jeter ferait redemander ce qu'on
        a déjà."""
        sessions.noter(self.cible, Turn("user", "question coupée"))
        sessions.noter(
            self.cible, Turn("assistant", "un début", interrupted=True)
        )
        tours = sessions.charger(self.cible)
        self.assertEqual("un début", tours[-1].text)
        self.assertTrue(tours[-1].interrupted)
        self.assertEqual("question coupée", tours[-2].text)

    def test_une_reponse_vide_ne_fait_pas_un_echange(self):
        """Une coupure avant le premier mot ne laisse rien à garder, et la
        conversation en mémoire n'en garde rien non plus."""
        sessions.noter(self.cible, Turn("user", "question sans un mot"))
        sessions.noter(self.cible, Turn("assistant", "", interrupted=True))
        textes = [tour.text for tour in sessions.charger(self.cible)]
        self.assertNotIn("question sans un mot", textes)

    def test_les_tours_repartent_toujours_par_paires(self):
        """Un historique qui commence par une réponse, ou qui finit par une
        question, n'est pas un historique que le modèle sait lire."""
        sessions.noter(self.cible, Turn("assistant", "réponse orpheline"))
        sessions.noter(self.cible, Turn("user", "question orpheline"))
        tours = sessions.charger(self.cible)
        self.assertEqual(0, len(tours) % 2)
        roles = [tour.role for tour in tours]
        self.assertEqual(["user", "assistant"] * (len(tours) // 2), roles)

    def test_une_seance_sans_reponse_n_est_pas_proposee(self):
        """Une séance ouverte puis quittée sans un mot ferait rouvrir un
        fichier vide."""
        muette = sessions.ouvrir(
            "2222cccc3333", SERVEUR, debut=DEBUT, base=self.base
        )
        sessions.noter(muette, Turn("user", "une question sans réponse"))
        seances = [vue.seance for vue in sessions.lister(base=self.base)]
        self.assertNotIn("2222cccc3333", seances)

    def test_une_ligne_abimee_n_emporte_pas_les_voisines(self):
        """Un disque plein coupe une ligne en deux ; une coupure ne doit
        perdre qu'un tour, pas la conversation."""
        with open(self.cible, "a", encoding="utf-8") as fichier:
            fichier.write('{"role": "user", "text": "cou\n')
        sessions.noter(self.cible, Turn("user", "après la coupure"))
        sessions.noter(self.cible, Turn("assistant", "toujours là"))
        textes = [tour.text for tour in sessions.charger(self.cible)]
        self.assertIn("après la coupure", textes)
        self.assertIn("toujours là", textes)

    def test_un_role_inconnu_est_saute(self):
        """Un tour que la conversation ne saurait pas rejouer vaut mieux
        absent que fabriqué."""
        with open(self.cible, "a", encoding="utf-8") as fichier:
            fichier.write(json.dumps({"role": "system", "text": "x"}) + "\n")
            fichier.write(json.dumps({"text": "sans rôle"}) + "\n")
        self.assertEqual(2, len(sessions.charger(self.cible)))

    def test_un_dossier_absent_se_lit_comme_aucune_seance(self):
        self.assertEqual([], sessions.lister(base="/chemin-invente-absent"))
        self.assertEqual([], sessions.charger("/chemin-invente/absent.jsonl"))
        self.assertIsNone(sessions.resume("/chemin-invente/absent.jsonl"))

    def test_la_liste_met_la_plus_recente_en_tete(self):
        for jour, seance in (
            ("2026-03-01T00:00:00-05:00", "aaaa11112222"),
            ("2026-03-09T00:00:00-05:00", "bbbb33334444"),
        ):
            cible = sessions.ouvrir(
                seance, SERVEUR, debut=jour, base=self.base
            )
            sessions.noter(cible, Turn("user", "q"))
            sessions.noter(cible, Turn("assistant", "r"))
        seances = [vue.seance for vue in sessions.lister(base=self.base)]
        self.assertEqual("bbbb33334444", seances[0])

    def test_la_liste_se_borne_quand_on_le_demande(self):
        for rang in range(4):
            cible = sessions.ouvrir(
                f"cccc{rang:08d}", SERVEUR, debut=DEBUT, base=self.base
            )
            sessions.noter(cible, Turn("user", "q"))
            sessions.noter(cible, Turn("assistant", "r"))
        self.assertEqual(2, len(sessions.lister(base=self.base, combien=2)))


if __name__ == "__main__":
    unittest.main()
