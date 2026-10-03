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
                  "/dev/erplibre-modem-at", executer=self.executer, service_actif=False,
                  maintenant=datetime(2026, 9, 17, 8, 0, 0))
        commande, entree, _ = self.appels[0]
        self.assertNotIn("864209", " ".join(commande))
        self.assertEqual(entree, "864209\n")

    def test_l_enregistrement_va_sous_private(self):
        _, wav = rec.jouer("reperage_code_ecoute", "+15145550199", "864209", "/bin/x",
                           "/dev/p", executer=self.executer, service_actif=False,
                           maintenant=datetime(2026, 9, 17, 8, 0, 0))
        self.assertTrue(wav.startswith(os.path.join(self.tmp.name, "private/")))
        self.assertTrue(wav.endswith("reperage_code_ecoute-20260917-080000.wav"))

    def test_le_delai_couvre_toute_la_recette(self):
        """Abandonner le processus avant la fin laisserait l'appel ouvert."""
        rec.jouer("reperage_code_ecoute", "+15145550199", "1234", "/bin/x", "/dev/p",
                  executer=self.executer, service_actif=False)
        self.assertGreaterEqual(self.appels[0][2], 20 + 20 + 90)

    def test_sans_code_rien_ne_part(self):
        bilan, wav = rec.jouer("reperage_code_ecoute", "+15145550199", "", "/bin/x",
                               "/dev/p", executer=self.executer, service_actif=False)
        self.assertIn("code", bilan["erreur"])
        self.assertEqual(self.appels, [])
        self.assertEqual(wav, "")

    def test_une_sortie_illisible_devient_une_erreur_lisible(self):
        bilan, _ = rec.jouer("reperage_code_ecoute", "+15145550199", "1234", "/bin/x",
                             "/dev/p", executer=lambda *a: (2, "", "port tenu"),
                             service_actif=False)
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

    def test_l_annonce_collee_au_message_se_coupe_sur_sa_duree(self):
        """L'operateur n'y laisse parfois aucun blanc mesurable. La duree de
        l'annonce, stable d'un appel a l'autre, donne alors la coupure."""
        bilan = {
            "evenements": [{"ms": 23600, "quoi": "étape 4 : touches 1"}],
            # annonce + message colles (10,9 s), puis le menu (29,9 s).
            "courbe_crete_100ms": courbe(
                (False, 25.5), (True, 10.9), (False, 0.7), (True, 29.9),
                (False, 6.2), (True, 18.2)),
        }
        debut, fin, methode = rec.bornes_et_methode(bilan)
        self.assertEqual(methode, "duree de l'annonce")
        # Le message occupe la fin du bloc : apres les 7,3 s d'annonce.
        self.assertGreaterEqual(debut, 25500 + 7300 - 1000)
        self.assertLessEqual(fin, 36400 + 500)

    def test_le_message_colle_au_menu_se_coupe_sur_la_duree_du_menu(self):
        """L'autre fusion : le menu enchaine sans blanc apres le message."""
        bilan = {
            "evenements": [{"ms": 24000, "quoi": "étape 4 : touches 1"}],
            # annonce (7,3 s), puis message + menu colles (34,0 s).
            "courbe_crete_100ms": courbe(
                (False, 25.8), (True, 7.3), (False, 1.0), (True, 34.0),
                (False, 6.3), (True, 8.5)),
        }
        debut, fin, methode = rec.bornes_et_methode(bilan)
        self.assertEqual(methode, "duree du menu")
        # Le menu occupe les 29,9 dernieres secondes du bloc.
        self.assertLessEqual(fin, 68100 - 29900 + 500)
        self.assertGreaterEqual(debut, 33100 - 300)

    def test_la_methode_est_notee_a_cote_du_message(self):
        """Savoir si la coupure vient d'un silence ou d'une duree estimee
        change ce qu'on croit de l'extrait."""
        import wave

        bilan = {
            "evenements": [{"ms": 3300, "quoi": "étape 4 : touches 1"}],
            "courbe_crete_100ms": courbe(
                (False, 6.3), (True, 7.3), (False, 1.2), (True, 2.8),
                (False, 1.8), (True, 29.8), (False, 5.5)),
        }
        with tempfile.TemporaryDirectory() as dossier:
            source = os.path.join(dossier, "appel.wav")
            with wave.open(source, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"\x00\x00" * 8000 * 60)
            sortie = rec.extraire_message(source, bilan, os.path.join(dossier, "m"))
            with open(os.path.splitext(sortie)[0] + ".json", encoding="utf-8") as flux:
                self.assertEqual(json.load(flux)["decoupe"], "silence")

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


class TestTeleversement(unittest.TestCase):
    """Le message de l'operateur monte dans Odoo par la route du module
    erplibre_repondeur, avec le meme transport signe que l'agent SMS."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wav = os.path.join(self.tmp.name, "message-20260928-050000.wav")
        with open(self.wav, "wb") as flux:
            flux.write(b"RIFFdonnees")
        self.message = {"fichier": self.wav, "duree_secondes": 4.3,
                        "recupere_le": "2026-09-28T01:00:00-04:00"}

    class Poste:
        def __init__(self, reponse=None, erreur=None):
            self.reponse, self.erreur, self.charges = reponse or {}, erreur, []

        def poster(self, route, charge):
            self.charges.append((route, charge))
            if self.erreur:
                raise self.erreur
            return self.reponse

    def test_le_numero_part_vide(self):
        """L'operateur annonce l'appelant a la voix : y mettre le numero de la
        messagerie ferait croire que c'est lui qui a appele."""
        poste = self.Poste({"ok": True, "id": 7})
        ok, detail = rec.televerser(self.message, poste)
        self.assertTrue(ok)
        route, charge = poste.charges[0]
        self.assertEqual(route, rec.ROUTE_MESSAGE)
        self.assertEqual(charge["numero"], "")
        self.assertEqual(charge["source"], "operateur")
        self.assertEqual(detail, "7")

    def test_la_duree_est_arrondie(self):
        """Tronquee, une seconde et neuf dixiemes s'affichait « 1 s » et
        laissait croire a un enregistrement rate."""
        poste = self.Poste({"ok": True, "id": 1})
        rec.televerser(dict(self.message, duree_secondes=1.9), poste)
        self.assertEqual(poste.charges[0][1]["duree_secondes"], 2)

    def test_l_horodatage_part_en_utc(self):
        """Odoo stocke en UTC sans fuseau : un horodatage local s'y afficherait
        decale de plusieurs heures."""
        poste = self.Poste({"ok": True, "id": 1})
        rec.televerser(self.message, poste)
        self.assertEqual(poste.charges[0][1]["recu_le"], "2026-09-28 05:00:00")

    def test_la_reference_evite_le_doublon(self):
        """Une reponse perdue fait rejouer le televersement : la meme
        reference retrouve le message au lieu d'en creer un second."""
        poste = self.Poste({"ok": True, "id": 1})
        rec.televerser(self.message, poste)
        rec.televerser(self.message, poste)
        references = {c["reference"] for _r, c in poste.charges}
        self.assertEqual(len(references), 1)

    def test_un_refus_laisse_le_fichier_en_place(self):
        poste = self.Poste(erreur=RuntimeError("Odoo a repondu 503"))
        ok, detail = rec.televerser(self.message, poste)
        self.assertFalse(ok)
        self.assertIn("503", detail)
        self.assertTrue(os.path.exists(self.wav))

    def test_sans_odoo_configure_rien_ne_part(self):
        """Une installation sans Odoo garde ses messages en local."""
        with mock.patch.object(rec, "transport_odoo", return_value=None):
            ok, detail = rec.televerser(self.message)
        self.assertFalse(ok)
        self.assertIn("Odoo", detail)

    def test_la_marque_est_posee_apres_la_reponse(self):
        """Marquee avant, une reponse perdue perdrait le message pour Odoo."""
        compagnon = os.path.splitext(self.wav)[0] + ".json"
        with open(compagnon, "w", encoding="utf-8") as flux:
            json.dump(self.message, flux)
        rec.marquer_televerse(self.message, "7")
        with open(compagnon, encoding="utf-8") as flux:
            self.assertEqual(json.load(flux)["televerse_odoo"], "7")

    def test_le_transport_vient_de_l_agent_de_la_passerelle(self):
        """Le meme secret et la meme signature : un second protocole serait un
        second endroit ou se tromper."""
        from script.todo.modem import passerelle

        with mock.patch.dict(os.environ, {
                passerelle.VARIABLE_URL: "http://127.0.0.1:8069",
                passerelle.VARIABLE_SECRET: "secret",
                passerelle.VARIABLE_APPAREIL: "modem"}, clear=False):
            self.assertIsInstance(rec.transport_odoo(), passerelle.Transport)
        with mock.patch.dict(os.environ, {passerelle.VARIABLE_SECRET: ""}, clear=False):
            self.assertIsNone(rec.transport_odoo())


class TestRecetteDEffacement(unittest.TestCase):
    def test_l_avertissement_dit_le_silence_de_la_recette(self):
        """La valeur annoncee est celle qui s'appliquera, pas une recopie."""
        recette = rec.charger_recette("recuperer_un_message")
        self.assertEqual(rec.silence_avant_effacement_s(recette), 4.5)
        self.assertIsNone(rec.silence_avant_effacement_s(
            rec.charger_recette("reperage_code_ecoute")))

    def test_le_service_actif_arrete_tout_avant_le_coffre(self):
        """Deverrouiller un coffre pour s'entendre dire que la ligne est
        prise fait payer un geste pour rien."""
        import io
        from contextlib import redirect_stdout

        from script.todo.modem import menu

        coffre = mock.patch("script.todo.modem.code_messagerie.coffre")
        sortie = io.StringIO()
        with mock.patch.object(menu.device_mod, "port_reserve", return_value="/dev/p"), \
                mock.patch("script.todo.modem.recuperation.ligne_occupee",
                           return_value="le service tient le port"), \
                coffre as ouvrir, redirect_stdout(sortie):
            menu._repondeur_recuperer(todo=None)
        self.assertIn("le service tient le port", sortie.getvalue())
        ouvrir.assert_not_called()

    def test_l_effacement_est_annonce_avant_le_choix(self):
        """Une confirmation arrive quand la decision est prise. Ce que la
        commande detruit se dit AVANT, la ou on choisit encore."""
        import io
        from contextlib import redirect_stdout

        from script.todo.modem import menu

        sortie = io.StringIO()
        with mock.patch.object(menu.device_mod, "port_reserve", return_value="/dev/p"), \
                mock.patch("script.todo.modem.recuperation.ligne_occupee",
                           return_value=""), \
                mock.patch.object(menu.mv_mod, "numero_messagerie", return_value=("+15145550199", "")), \
                mock.patch("os.path.exists", return_value=True), \
                mock.patch("builtins.input", return_value="0"), \
                redirect_stdout(sortie):
            menu._repondeur_recuperer(todo=None)
        texte = sortie.getvalue()
        self.assertIn("EFFAC", texte.upper())
        self.assertLess(texte.upper().index("EFFAC"), texte.index("[1]"))

    def test_le_coffre_ne_s_ouvre_qu_une_fois_l_effacement_accepte(self):
        """Deverrouiller ses mots de passe pour decouvrir ensuite ce que la
        commande fait, et pouvoir encore y renoncer, fait payer un geste avant
        d'avoir decide."""
        import io
        from contextlib import redirect_stdout

        from script.todo.modem import menu

        sortie = io.StringIO()
        with mock.patch.object(menu.device_mod, "port_reserve", return_value="/dev/p"), \
                mock.patch("script.todo.modem.recuperation.ligne_occupee",
                           return_value=""), \
                mock.patch.object(menu.mv_mod, "numero_messagerie", return_value=("+15145550199", "")), \
                mock.patch("os.path.exists", return_value=True), \
                mock.patch("builtins.input", return_value="0"), \
                mock.patch("script.todo.modem.code_messagerie.coffre") as ouvrir, \
                redirect_stdout(sortie):
            menu._repondeur_recuperer(todo=None)
        ouvrir.assert_not_called()

    def test_l_avertissement_s_affiche_avant_le_choix(self):
        import io
        from contextlib import redirect_stdout

        from script.todo.modem import menu

        sortie = io.StringIO()
        with mock.patch.object(menu.device_mod, "port_reserve", return_value="/dev/p"), \
                mock.patch("script.todo.modem.recuperation.ligne_occupee",
                           return_value=""), \
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


class TestLaLigneOccupee(unittest.TestCase):
    """Une recette prend le port AT pour elle seule.

    Le service de voix le tient en permanence. Composer pendant qu'il tourne
    donne un appel facture, qui echoue sur un verrou et rapporte un nom de
    fichier au lieu de la cause.
    """

    def test_le_service_actif_empeche_de_composer(self):
        bilan, wav = rec.jouer("reperage_code_ecoute", "+15145550199", "1234",
                               "/bin/x", "/dev/p", service_actif=True)
        self.assertEqual(wav, "")
        self.assertIn("port AT", bilan["erreur"])
        self.assertIn("systemctl stop", bilan["erreur"])

    def test_le_service_eteint_laisse_composer(self):
        self.assertEqual(rec.ligne_occupee(service_actif=False), "")


if __name__ == "__main__":
    unittest.main()
