#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'historique des SMS par correspondant, et sa duree.

La memoire du modem tient quelques messages, l'agent de la passerelle efface
ceux qu'il remonte, et un message envoye n'y porte aucune date : une liste
tiree d'elle ne montre ni les echanges d'hier ni un fil de conversation.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.modem import journal_sms as journal  # noqa: E402


class TestJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fichier = os.path.join(self.tmp.name, "sms", "historique.jsonl")

    def test_un_envoi_survit_a_la_memoire_du_modem(self):
        """Le modem efface, le journal garde : c'est la seule memoire longue."""
        journal.ajouter("out", "+15145550142", "coucou", "2026-09-18T10:00:00",
                        self.fichier)
        self.assertEqual(len(journal.lister(self.fichier)), 1)

    def test_le_meme_numero_ne_fait_qu_un_fil(self):
        """« +1 514-555-0142 » a l'arrivee et « 5145550142 » a la saisie sont
        le meme correspondant : sans normalisation, le fil se scinde."""
        journal.ajouter("out", "5145550142", "un", "2026-09-18T10:00:00", self.fichier)
        journal.ajouter("in", "+1 514-555-0142", "deux", "2026-09-18T10:01:00",
                        self.fichier)
        conversations = journal.par_correspondant(self.fichier)
        self.assertEqual(len(conversations), 1)
        self.assertEqual(len(conversations[0][1]), 2)

    def test_le_fil_va_du_plus_ancien_au_plus_recent(self):
        journal.ajouter("in", "5145550142", "hier", "2026-09-17T09:00:00", self.fichier)
        journal.ajouter("out", "5145550142", "aujourd'hui", "2026-09-18T10:00:00",
                        self.fichier)
        _numero, messages = journal.par_correspondant(self.fichier)[0]
        self.assertEqual([m["texte"] for m in messages], ["hier", "aujourd'hui"])

    def test_la_conversation_la_plus_recente_vient_en_tete(self):
        journal.ajouter("in", "5145550142", "vieux", "2026-09-17T09:00:00", self.fichier)
        journal.ajouter("in", "5145550199", "neuf", "2026-09-18T10:00:00", self.fichier)
        premiers = [journal.cle_numero(n) for n, _m in
                    journal.par_correspondant(self.fichier)]
        self.assertEqual(premiers[0], "15145550199")

    def test_relire_le_modem_ne_double_pas_les_messages(self):
        """Le meme message relu a chaque rafraichissement doublait la liste."""
        du_modem = [{"numero": "+15145550142", "texte": "coucou",
                     "etat": "received", "horodatage": "2026-09-18T10:00:00"}]
        journal.fusionner_du_modem(du_modem, self.fichier)
        journal.fusionner_du_modem(du_modem, self.fichier)
        self.assertEqual(len(journal.lister(self.fichier)), 1)

    def test_un_envoi_deja_journalise_ne_revient_pas_par_le_modem(self):
        """L'envoi s'ecrit tout de suite ; le modem le rend ensuite sans date,
        et il ne doit pas apparaitre deux fois."""
        journal.ajouter("out", "+15145550142", "coucou", "2026-09-18T10:00:00",
                        self.fichier)
        journal.fusionner_du_modem(
            [{"numero": "+15145550142", "texte": "coucou", "etat": "sent"}],
            self.fichier)
        self.assertEqual(len(journal.lister(self.fichier)), 1)

    def test_une_ligne_illisible_ne_coute_que_son_message(self):
        """Une ecriture interrompue ne doit pas emporter tout l'historique."""
        journal.ajouter("in", "5145550142", "bon", "2026-09-18T10:00:00", self.fichier)
        with open(self.fichier, "a", encoding="utf-8") as flux:
            flux.write('{"sens": "in", tronque\n')
        self.assertEqual(len(journal.lister(self.fichier)), 1)

    def test_un_journal_absent_rend_une_liste_vide(self):
        self.assertEqual(journal.lister(self.fichier), [])
        self.assertEqual(journal.par_correspondant(self.fichier), [])

    def test_le_journal_n_est_lisible_que_par_son_proprietaire(self):
        """Un SMS porte un numero et ce que quelqu'un a ecrit."""
        journal.ajouter("in", "5145550142", "prive", "2026-09-18T10:00:00",
                        self.fichier)
        self.assertEqual(oct(os.stat(self.fichier).st_mode)[-3:], "600")

    def test_le_journal_vit_sous_private(self):
        self.assertTrue(journal.chemin().endswith("private/sms/historique.jsonl"))

    def test_le_sens_vient_de_l_etat_du_modem(self):
        journal.fusionner_du_modem([
            {"numero": "+15145550142", "texte": "recu", "etat": "received"},
            {"numero": "+15145550142", "texte": "envoye", "etat": "sent"},
        ], self.fichier)
        sens = {e["texte"]: e["sens"] for e in journal.lister(self.fichier)}
        self.assertEqual(sens, {"recu": "in", "envoye": "out"})

    def test_un_message_sans_numero_est_ignore(self):
        """Sans numero, il n'appartient a aucun fil."""
        journal.fusionner_du_modem([{"numero": "", "texte": "orphelin"}], self.fichier)
        self.assertEqual(journal.lister(self.fichier), [])


if __name__ == "__main__":
    unittest.main()
