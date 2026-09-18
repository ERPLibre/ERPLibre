#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Jouer une recette de messagerie depuis la TUI, sans modem."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.modem import recuperation as rec  # noqa: E402

BILAN = {"complete": True, "duree_ms": 5000, "courbe_crete_100ms": [0] * 10 + [9000] * 14,
         "evenements": [{"ms": 2500, "quoi": "étape 2 : touches <code>#"}]}


class TestJouer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.enterContext(mock.patch.object(rec, "racine", return_value=self.tmp.name))
        self.appels = []

    def executer(self, commande, entree, timeout):
        self.appels.append((commande, entree, timeout))
        return 0, json.dumps(BILAN), ""

    def test_le_code_passe_par_l_entree_standard_et_jamais_en_argument(self):
        """La ligne de commande se lit par tout programme de la machine."""
        rec.jouer("reperage_code_ecoute", "+15145550199", "864209", "/bin/erplibre-sip-go",
                  "/dev/erplibre-modem-at", executer=self.executer,
                  maintenant=datetime(2026, 9, 17, 8, 0, 0))
        commande, entree, _ = self.appels[0]
        self.assertNotIn("864209", " ".join(commande))
        self.assertEqual(entree, "864209\n")

    def test_l_enregistrement_va_sous_private(self):
        _, wav = rec.jouer("reperage_code_ecoute", "+15145550199", "864209", "/bin/x",
                           "/dev/p", executer=self.executer,
                           maintenant=datetime(2026, 9, 17, 8, 0, 0))
        self.assertTrue(wav.startswith(os.path.join(self.tmp.name, "private/")))
        self.assertTrue(wav.endswith("reperage_code_ecoute-20260917-080000.wav"))

    def test_le_delai_couvre_toute_la_recette(self):
        """Abandonner le processus avant la fin laisserait l'appel ouvert."""
        rec.jouer("reperage_code_ecoute", "+15145550199", "1234", "/bin/x", "/dev/p",
                  executer=self.executer)
        self.assertGreaterEqual(self.appels[0][2], 20 + 20 + 90)

    def test_sans_code_rien_ne_part(self):
        bilan, wav = rec.jouer("reperage_code_ecoute", "+15145550199", "", "/bin/x",
                               "/dev/p", executer=self.executer)
        self.assertIn("code", bilan["erreur"])
        self.assertEqual(self.appels, [])
        self.assertEqual(wav, "")

    def test_une_sortie_illisible_devient_une_erreur_lisible(self):
        bilan, _ = rec.jouer("reperage_code_ecoute", "+15145550199", "1234", "/bin/x",
                             "/dev/p", executer=lambda *a: (2, "", "port tenu"))
        self.assertIn("port tenu", bilan["erreur"])


class TestResume(unittest.TestCase):
    def test_le_resume_donne_touches_et_parole(self):
        lignes = "\n".join(rec.resume(BILAN))
        self.assertIn("touches <code>#", lignes)
        self.assertIn("1.0 ->", lignes)

    def test_la_recette_livree_compose_le_code(self):
        with open(rec.chemin_recette("reperage_code_ecoute"), encoding="utf-8") as flux:
            recette = json.load(flux)
        self.assertTrue(rec.demande_code(recette))
        # Le repérage ne doit JAMAIS effacer : 7 est irréversible.
        self.assertNotIn("7", "".join(e.get("touches", "") for e in recette["etapes"]))


def courbe(*morceaux):
    """(parole?, secondes) -> courbe de 100 ms."""
    points = []
    for parle, secondes in morceaux:
        points += [9000 if parle else 0] * int(secondes * 10)
    return points


class TestDecoupe(unittest.TestCase):
    """Le deroule mesure sur une messagerie reelle : annonce, 1,2 s, message,
    1,8 s, menu, puis 5,5 s de silence avant que le menu ne se repete."""

    def bilan(self):
        return {
            "evenements": [{"ms": 3300, "quoi": "étape 4 : touches 1"}],
            "courbe_crete_100ms": courbe(
                (False, 6.3), (True, 7.3), (False, 1.2), (True, 2.8),
                (False, 1.8), (True, 29.8), (False, 5.5), (True, 10)),
        }

    def test_le_message_est_entre_l_annonce_et_le_menu(self):
        debut, fin = rec.bornes_du_message(self.bilan())
        self.assertLessEqual(debut, 14800)
        self.assertGreaterEqual(fin, 17600)
        # Ajustés à l'oreille : début une seconde plus tard, fin une
        # demi-seconde plus tôt.
        self.assertEqual((debut, fin), (13600 - 300 + 1000, 19400 + 300 - 500))

    def test_un_message_avec_des_pauses_reste_entier(self):
        """Une personne qui hesite coupe son message en plusieurs plages."""
        b = self.bilan()
        b["courbe_crete_100ms"] = courbe(
            (False, 6.3), (True, 7.3), (False, 1.2), (True, 2), (False, 2.5),
            (True, 3), (False, 1.8), (True, 29.8), (False, 5.5))
        debut, fin = rec.bornes_du_message(b)
        self.assertLessEqual(debut, 14800)
        self.assertGreaterEqual(fin, 6.3e3 + 7.3e3 + 1.2e3 + 2e3 + 2.5e3 + 3e3)

    def test_la_phrase_en_cours_quand_la_touche_part_n_est_pas_l_annonce(self):
        """Releve sur un appel reel : le « 1 » part pendant que la messagerie
        parle encore, et la fin de cette phrase precede l'annonce."""
        bilan = {
            "evenements": [{"ms": 23460, "quoi": "étape 4 : touches 1"}],
            # 6,5 -> 24,3 la phrase en cours ; 25,3 -> 32,6 l'annonce ;
            # 33,4 -> 39,7 le message ; 40,6 -> 70,5 le menu ; puis 6,3 s.
            "courbe_crete_100ms": courbe(
                (False, 6.5), (True, 17.8), (False, 1.0), (True, 7.3),
                (False, 0.8), (True, 6.3), (False, 0.9), (True, 29.9),
                (False, 6.3), (True, 8.5)),
        }
        debut, fin = rec.bornes_du_message(bilan)
        # Le message va de 33,4 a 39,7 : la decoupe l'encadre sans mordre
        # sur l'annonce, qui finit a 32,6.
        self.assertGreaterEqual(debut, 32600)
        self.assertLessEqual(debut, 33400)
        self.assertGreaterEqual(fin, 39700)
        self.assertLessEqual(fin, 40600)

    def test_l_annonce_et_le_message_restent_distincts(self):
        """Huit dixiemes de seconde les separent sur une messagerie reelle :
        fondre au-dela collerait les deux."""
        self.assertLess(rec.PONT_DECOUPE_MS, 800)

    def test_une_structure_inconnue_ne_se_decoupe_pas(self):
        """Mieux vaut garder l'enregistrement complet que decouper au hasard."""
        b = self.bilan()
        b["courbe_crete_100ms"] = courbe((False, 5), (True, 3), (False, 10))
        self.assertIsNone(rec.bornes_du_message(b))
        self.assertIsNone(rec.bornes_du_message({"evenements": [], "courbe_crete_100ms": []}))

    def test_l_extrait_est_un_wav_avec_sa_description(self):
        import wave

        with tempfile.TemporaryDirectory() as dossier:
            source = os.path.join(dossier, "appel.wav")
            with wave.open(source, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"\x00\x00" * 8000 * 70)
            sortie = rec.extraire_message(source, self.bilan(), os.path.join(dossier, "m"),
                                          maintenant=datetime(2026, 9, 17, 9, 0, 0))
            with wave.open(sortie) as w:
                duree = w.getnframes() / w.getframerate()
            self.assertAlmostEqual(duree, 4.9, delta=0.2)
            with open(os.path.splitext(sortie)[0] + ".json", encoding="utf-8") as flux:
                self.assertEqual(json.load(flux)["enregistrement_complet"], source)


class TestMessagesRecuperes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dossier = os.path.join(self.tmp.name, "messages")
        os.makedirs(self.dossier)

    def _poser(self, nom, recupere_le):
        wav = os.path.join(self.dossier, nom + ".wav")
        open(wav, "wb").write(b"RIFF")
        with open(os.path.join(self.dossier, nom + ".json"), "w", encoding="utf-8") as f:
            json.dump({"fichier": wav, "recupere_le": recupere_le,
                       "duree_secondes": 7.1,
                       "enregistrement_complet": wav.replace("messages/", "")}, f)
        return wav

    def test_du_plus_recent_au_plus_ancien(self):
        self._poser("vieux", "2026-09-17T09:00:00")
        self._poser("neuf", "2026-09-18T01:48:00")
        messages = rec.lister_messages(self.dossier)
        self.assertEqual(len(messages), 2)
        self.assertTrue(messages[0]["fichier"].endswith("neuf.wav"))

    def test_un_son_sans_description_est_ignore(self):
        open(os.path.join(self.dossier, "orphelin.wav"), "wb").write(b"RIFF")
        self.assertEqual(rec.lister_messages(self.dossier), [])

    def test_un_dossier_absent_rend_une_liste_vide(self):
        self.assertEqual(rec.lister_messages(os.path.join(self.tmp.name, "jamais")), [])

    def test_effacer_laisse_l_enregistrement_complet(self):
        """Le message est deja efface chez l'operateur : l'enregistrement
        complet de l'appel reste la copie de secours, avec l'annonce du
        numero de l'appelant."""
        wav = self._poser("message", "2026-09-18T01:48:00")
        complet = os.path.join(self.tmp.name, "appel.wav")
        open(complet, "wb").write(b"RIFF")
        rec.effacer_message({"fichier": wav, "enregistrement_complet": complet})
        self.assertFalse(os.path.exists(wav))
        self.assertEqual(rec.lister_messages(self.dossier), [])
        self.assertTrue(os.path.exists(complet))


class TestRecetteDEffacement(unittest.TestCase):
    def test_l_avertissement_dit_le_silence_de_la_recette(self):
        """La valeur annoncee est celle qui s'appliquera, pas une recopie."""
        recette = rec.charger_recette("recuperer_un_message")
        self.assertEqual(rec.silence_avant_effacement_s(recette), 4.5)
        self.assertIsNone(rec.silence_avant_effacement_s(
            rec.charger_recette("reperage_code_ecoute")))

    def test_l_avertissement_s_affiche_avant_le_choix(self):
        import io
        from contextlib import redirect_stdout

        from script.todo.modem import menu

        sortie = io.StringIO()
        with mock.patch.object(menu.device_mod, "port_reserve", return_value="/dev/p"), \
                mock.patch.object(menu.mv_mod, "numero_messagerie", return_value=("+15145550199", "")), \
                mock.patch("script.todo.modem.code_messagerie.coffre"), \
                mock.patch("script.todo.modem.code_messagerie.lire", return_value="1234"), \
                mock.patch("os.path.exists", return_value=True), \
                mock.patch("builtins.input", return_value="0"), \
                redirect_stdout(sortie):
            menu._repondeur_recuperer(todo=None)
        texte = sortie.getvalue()
        self.assertIn("4,5 s", texte)
        self.assertLess(texte.index("4,5 s"), texte.index("[1]"))

    def test_le_7_n_est_jamais_joue_sans_garde_juste_avant(self):
        """7 efface pour de bon : une garde doit le preceder immediatement."""
        with open(rec.chemin_recette("recuperer_un_message"), encoding="utf-8") as flux:
            etapes = json.load(flux)["etapes"]
        for i, etape in enumerate(etapes):
            if "7" in etape.get("touches", ""):
                self.assertIn("verifier_parole", etapes[i - 1])


if __name__ == "__main__":
    unittest.main()
