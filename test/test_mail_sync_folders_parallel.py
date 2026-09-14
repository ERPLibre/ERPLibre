#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Synchroniser les dossiers d'un compte par plusieurs liens.

Un `imaplib` n'a qu'un dossier sélectionné à la fois : sur un seul lien,
une boîte de trente dossiers les parcourt un par un, et le temps d'attente
est la somme des trente. Un lien de plus fait avancer un dossier de plus.

Ce que ces tests couvrent d'abord : que le RÉSULTAT ne change pas — le
parallélisme est une affaire de durée, jamais de contenu —, que les liens
supplémentaires sont refermés, et qu'un fournisseur qui refuse un lien de
plus n'empêche aucun dossier d'être synchronisé.
"""
import tempfile
import threading
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_sync import Syncer
from script.todo.mail.store import Store
from test_mail_sync import FakeImapTransport


class Compteur:
    """Ce que les liens d'un même compte font ensemble."""

    def __init__(self):
        self.ouverts = 0
        self.fermes = 0
        self.simultanes = 0
        self.plafond = 0
        self._verrou = threading.Lock()

    def entre(self):
        with self._verrou:
            self.simultanes += 1
            self.plafond = max(self.plafond, self.simultanes)

    def sort(self):
        with self._verrou:
            self.simultanes -= 1


class TransportObserve(FakeImapTransport):
    """Un lien qui dit quand il travaille, pour mesurer le recouvrement."""

    def __init__(self, folders, compteur, barriere=None):
        super().__init__(folders)
        self.compteur = compteur
        self.barriere = barriere

    def select(self, folder):
        self.compteur.entre()
        try:
            if self.barriere is not None:
                # Attend que TOUS les liens attendus soient là. Sans ce
                # rendez-vous, un test de parallélisme passerait aussi
                # devant une exécution séquentielle assez rapide.
                self.barriere.wait(timeout=5)
            return super().select(folder)
        finally:
            self.compteur.sort()

    def logout(self):
        super().logout()
        self.compteur.fermes += 1


class ParallelCase(unittest.TestCase):
    DOSSIERS = ("INBOX", "Archives", "Projets", "Envoyés")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.contenu = {}
        for rang, nom in enumerate(self.DOSSIERS, start=1):
            gabarit = FakeImapTransport()
            gabarit.add(nom, rang, subject=f"Message de {nom}")
            self.contenu.update(gabarit.folders)
        self.compteur = Compteur()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _copie(self, barriere=None):
        """Un lien de plus vers le MÊME compte : même contenu, état propre."""
        self.compteur.ouverts += 1
        return TransportObserve(
            {
                nom: {
                    "uidvalidity": f["uidvalidity"],
                    "messages": dict(f["messages"]),
                    "bodies": dict(f["bodies"]),
                }
                for nom, f in self.contenu.items()
            },
            self.compteur,
            barriere,
        )

    def _syncer(self, parallele, fabrique=None, barriere=None):
        return Syncer(
            self.store,
            self._copie(barriere),
            open_transport=fabrique or (lambda: self._copie(barriere)),
            parallele=parallele,
        )

    def _sujets(self):
        trouves = []
        for nom in self.DOSSIERS:
            etat = self.store.folder_state(nom)
            if etat:
                trouves += [
                    m.subject for m in self.store.list_messages(etat["id"])
                ]
        return sorted(trouves)


class TestTheResultDoesNotChange(ParallelCase):
    def test_every_folder_is_synced(self):
        rapport = self._syncer(3).sync()
        self.assertEqual(rapport.folders, len(self.DOSSIERS))

    def test_every_message_lands_in_the_cache(self):
        self._syncer(3).sync()
        self.assertEqual(
            self._sujets(),
            sorted(f"Message de {nom}" for nom in self.DOSSIERS),
        )

    def test_the_count_of_new_messages_is_the_whole_account(self):
        """Les rapports des liens sont FUSIONNÉS : l'appelant n'a pas à
        savoir combien ont servi."""
        self.assertEqual(
            self._syncer(3).sync().new_messages, len(self.DOSSIERS)
        )

    def test_one_link_gives_the_same_thing(self):
        self._syncer(1).sync()
        self.assertEqual(
            self._sujets(),
            sorted(f"Message de {nom}" for nom in self.DOSSIERS),
        )

    def test_a_folder_that_refuses_does_not_stop_the_others(self):
        syncer = self._syncer(3)
        syncer.transport.select_errors.add("Projets")
        rapport = syncer.sync()
        self.assertTrue(rapport.errors)
        self.assertIn("Message de INBOX", self._sujets())


class TestTheLinksThemselves(ParallelCase):
    def test_folders_really_advance_together(self):
        """Le point entier. Le rendez-vous ne se franchit que si trois
        dossiers sont sélectionnés en même temps ; une exécution
        séquentielle l'atteindrait seule et expirerait."""
        barriere = threading.Barrier(3, timeout=5)
        self._syncer(3, barriere=barriere).sync()
        self.assertEqual(self.compteur.plafond, 3)

    def test_extra_links_are_closed(self):
        """Un compte qui laisse un lien derrière lui à chaque passe atteint
        la limite du fournisseur en quelques minutes."""
        self._syncer(3).sync()
        self.assertEqual(self.compteur.fermes, 2)

    def test_the_first_link_is_the_one_already_open(self):
        """Ouvrir un lien pour le premier lot quand il y en a déjà un
        ouvert le gaspillerait."""
        syncer = self._syncer(3)
        avant = self.compteur.ouverts
        syncer.sync()
        self.assertEqual(self.compteur.ouverts - avant, 2)

    def test_no_extra_link_without_a_factory(self):
        syncer = Syncer(self.store, self._copie(), parallele=4)
        syncer.sync()
        self.assertEqual(self.compteur.ouverts, 1)

    def test_one_link_asks_for_nothing_more(self):
        self._syncer(1).sync()
        self.assertEqual(self.compteur.ouverts, 1)

    def test_never_more_links_than_folders(self):
        """Quatre dossiers ne justifient pas dix liens : un lien sans lot
        serait une connexion prise au plafond du fournisseur pour rien."""
        self._syncer(10).sync()
        self.assertEqual(self.compteur.ouverts, len(self.DOSSIERS))


class TestWhenTheProviderRefuses(ParallelCase):
    def test_a_refused_link_costs_no_folder(self):
        """Le lot du lien refusé revient au lien déjà ouvert : le compte se
        synchronise plus lentement, jamais moins complètement."""

        def refuse():
            raise OSError("trop de connexions simultanées")

        syncer = self._syncer(3, fabrique=refuse)
        rapport = syncer.sync()
        self.assertEqual(rapport.folders, len(self.DOSSIERS))
        self.assertEqual(
            self._sujets(),
            sorted(f"Message de {nom}" for nom in self.DOSSIERS),
        )

    def test_a_refused_link_is_not_an_error_in_the_report(self):
        """Ce n'est pas un incident pour la personne : tout est arrivé."""

        def refuse():
            raise OSError("trop de connexions simultanées")

        self.assertEqual(self._syncer(3, fabrique=refuse).sync().errors, [])

    def test_the_second_link_still_serves_if_the_third_fails(self):
        essais = []

        def parfois():
            essais.append(1)
            if len(essais) > 1:
                raise OSError("trop de connexions simultanées")
            return self._copie()

        syncer = self._syncer(3, fabrique=parfois)
        syncer.sync()
        self.assertEqual(self.compteur.fermes, 1)
        self.assertEqual(
            self._sujets(),
            sorted(f"Message de {nom}" for nom in self.DOSSIERS),
        )


if __name__ == "__main__":
    unittest.main()
