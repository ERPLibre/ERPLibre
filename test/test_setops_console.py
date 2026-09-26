#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La console web : une porte sans serrure, et un PID qui se recycle.

Deux propriétés portent le reste. La console n'a AUCUNE authentification : ce
qui atteint son port lit tout l'inventaire et déclenche ses gestes, donc elle
ne se lie qu'à la boucle locale et s'atteint d'ailleurs par une redirection
SSH. Et un PID enregistré désigne parfois, au moment du signal, un autre
travail : rien n'est signalé sans avoir relu la ligne de commande.

Les noms d'hôte et les chemins sont inventés et n'existent nulle part ailleurs
dans le dépôt ; « .invalid » est réservé par le RFC 2606.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import console as C  # noqa: E402


class TestCeQuiEstSuivi(unittest.TestCase):
    def test_a_real_record_is_read(self):
        """Le contrôle positif : sans lui, un lecteur qui refuse tout
        passerait chacun des refus éprouvés plus bas."""
        lu = C.lit_suivi('{"pid": 4242, "port": 8765}')
        self.assertEqual(C.Suivi(pid=4242, port=8765), lu)

    def test_a_pid_that_would_signal_a_whole_group_is_refused(self):
        """LE REFUS QUI COMPTE. `kill(0)` porte sur TOUT le groupe de
        l'appelant — todo se tuerait lui-même — et `kill(-1)` sur tout ce que
        l'utilisateur possède."""
        for pid in (0, -1, -4242):
            with self.subTest(pid=pid):
                self.assertIsNone(
                    C.lit_suivi(json.dumps({"pid": pid, "port": 8765}))
                )

    def test_a_pid_that_is_not_an_integer_is_refused(self):
        for pid in ("4242", 42.0, True, None, [4242]):
            with self.subTest(pid=pid):
                self.assertIsNone(
                    C.lit_suivi(json.dumps({"pid": pid, "port": 8765}))
                )

    def test_a_port_outside_the_range_is_refused(self):
        for port in (0, -1, 65536, 99999):
            with self.subTest(port=port):
                self.assertIsNone(
                    C.lit_suivi(json.dumps({"pid": 42, "port": port}))
                )

    def test_anything_that_is_not_a_record_is_refused(self):
        for texte in ("", None, "[]", "pas du json", '{"pid": 42}'):
            with self.subTest(texte=texte):
                self.assertIsNone(C.lit_suivi(texte))

    def test_what_is_written_reads_back(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, C.SUIVI)
            self.assertTrue(C.ecrit_suivi(chemin, 4242, 8765))
            with open(chemin, encoding="utf-8") as tenu:
                self.assertEqual(C.Suivi(4242, 8765), C.lit_suivi(tenu.read()))

    def test_a_record_that_cannot_be_written_says_so_without_raising(self):
        """Un suivi perdu ne doit pas faire échouer le lancement."""
        self.assertFalse(
            C.ecrit_suivi("/aucun-dossier-fictif-ici/suivi.json", 42, 8765)
        )

    def test_forgetting_a_record_that_is_not_there_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as dossier:
            C.oublie(os.path.join(dossier, "jamais-ecrit.json"))


class TestOuLeSuiviSePose(unittest.TestCase):
    """Le dossier d'exécution n'appartient qu'à l'utilisateur ; le dossier
    temporaire est partagé."""

    def test_the_user_runtime_directory_wins_when_it_exists(self):
        with tempfile.TemporaryDirectory() as dossier:
            self.assertEqual(dossier, C.dossier({"XDG_RUNTIME_DIR": dossier}))

    def test_a_runtime_directory_that_is_not_there_is_not_used(self):
        vu = C.dossier({"XDG_RUNTIME_DIR": "/aucun-dossier-fictif-ici"})
        self.assertNotEqual("/aucun-dossier-fictif-ici", vu)
        self.assertTrue(os.path.isdir(vu))

    def test_no_runtime_directory_still_gives_a_place(self):
        self.assertTrue(os.path.isdir(C.dossier({})))


class TestUnPidSeRecycle(unittest.TestCase):
    """Au moment du signal, un numéro enregistré désigne parfois un autre
    travail, et le signal irait au GROUPE entier de ce travail."""

    def setUp(self):
        self.procfs = tempfile.mkdtemp(prefix="setops-console-banc-")
        self.addCleanup(self._menage)

    def _menage(self):
        for racine, _d, fichiers in os.walk(self.procfs, topdown=False):
            for nom in fichiers:
                os.unlink(os.path.join(racine, nom))
            if racine != self.procfs:
                os.rmdir(racine)
        os.rmdir(self.procfs)

    def poser(self, pid, ligne):
        dossier = os.path.join(self.procfs, str(pid))
        os.makedirs(dossier)
        with open(os.path.join(dossier, "cmdline"), "wb") as tenu:
            tenu.write(b"\0".join(ligne.encode() for ligne in ligne.split()))

    def test_the_command_line_of_a_live_pid_is_read(self):
        self.poser(4242, "make -C moteur inventaire-ui CONFIRMER=false")
        lue = C.ligne_de_commande(4242, self.procfs)
        self.assertIn(C.MARQUE, lue)
        self.assertTrue(C.tenue(lue))

    def test_a_pid_that_is_gone_is_a_fact_not_a_doubt(self):
        """LE CAS QUI BLOQUAIT TOUT. Un lancement raté laisse un PID mort dans
        le suivi ; rendu « on ne sait pas », l'écran reste indécidable et la
        console ne peut plus jamais être lancée d'ici. Le dossier du PID
        disparu d'un procfs monté, le système AFFIRME que le processus est
        parti."""
        self.assertIs(C.ABSENT, C.ligne_de_commande(4242, self.procfs))
        self.assertFalse(C.tenue(C.ABSENT))

    def test_a_dead_pid_lets_the_console_be_started_again(self):
        """La conséquence à l'écran, et c'est elle qui compte."""
        mot, _pid = C.situation(
            C.Suivi(4242, C.PORT), C.tenue(C.ABSENT), False
        )
        self.assertEqual(C.ARRETEE, mot)

    def test_no_procfs_at_all_is_a_doubt_and_nothing_is_affirmed(self):
        """Sur un système sans procfs, on ne sait rien — et sur un doute, rien
        n'est tué ni déclaré arrêté."""
        self.assertIsNone(
            C.ligne_de_commande(4242, "/aucun-procfs-fictif-ici")
        )
        self.assertIsNone(C.tenue(None))

    def test_a_pid_that_is_not_a_number_is_a_doubt(self):
        for pid in ("quarante-deux", None, [4242]):
            with self.subTest(pid=pid):
                self.assertIsNone(C.ligne_de_commande(pid, self.procfs))

    def test_a_recycled_pid_is_not_ours(self):
        self.poser(4242, "un-autre-travail --qui-passait-par-la")
        self.assertFalse(C.tenue(C.ligne_de_commande(4242, self.procfs)))

    def test_the_mark_is_a_word_of_the_line_and_not_a_substring(self):
        """Cherchée par contenance, la marque se trouve dans une cible voisine,
        dans le chemin d'un journal, et dans le `grep` d'un développeur — celui
        que ces écrans invitent justement à retaper. Le signal partirait au
        GROUPE de ce travail."""
        for ligne in (
            f"make {C.MARQUE}-legacy",
            f"grep -rn {C.MARQUE} script/",
            f"less /tmp/{C.MARQUE}.log",
            f"python3 -m http.server  # remplace {C.MARQUE}",
            f"vim docs/{C.MARQUE}.md",
        ):
            with self.subTest(ligne=ligne):
                self.assertFalse(C.tenue(ligne), ligne)

    def test_the_shape_todo_launches_is_recognised(self):
        """Le contrôle positif : sans lui, un garde qui refuse tout passerait
        les cinq refus ci-dessus."""
        self.assertTrue(
            C.tenue(f"make --no-print-directory -C moteur {C.MARQUE} X=1")
        )


class TestLEtatSeDecideSurDesFaits(unittest.TestCase):
    SUIVI = C.Suivi(pid=4242, port=8765)

    def test_our_own_console_is_alive(self):
        self.assertEqual(
            (C.VIVANTE, 4242), C.situation(self.SUIVI, True, True)
        )

    def test_our_process_alive_with_a_dead_port_is_not_running(self):
        """UN DÉTACHÉ ÉCHOUE EN SILENCE : le `make` peut vivre pendant que le
        serveur qu'il lance a planté ou n'a pas encore lié. Rendre VIVANTE
        annonçait une page morte, et n'offrait plus de relancer. Cette
        combinaison n'était éprouvée nulle part."""
        self.assertEqual(
            (C.MUETTE, 4242), C.situation(self.SUIVI, True, False)
        )

    def test_a_port_held_by_someone_else_is_not_ours(self):
        """Elle ne s'arrête pas d'ici : le PID suivi ne la tient pas."""
        self.assertEqual((C.TENU, 0), C.situation(self.SUIVI, False, True))
        self.assertEqual((C.TENU, 0), C.situation(None, False, True))

    def test_nothing_running_and_a_free_port_is_stopped(self):
        self.assertEqual((C.ARRETEE, 0), C.situation(None, False, False))
        self.assertEqual((C.ARRETEE, 0), C.situation(self.SUIVI, False, False))

    def test_a_missing_fact_is_never_guessed(self):
        """Sur un doute, l'écran n'offre ni de lancer — deux consoles se
        disputeraient le port — ni d'arrêter."""
        for portee, occupe in ((None, True), (True, None), (None, None)):
            with self.subTest(portee=portee, occupe=occupe):
                mot, _pid = C.situation(self.SUIVI, portee, occupe)
                self.assertEqual(C.INCONNU, mot)

    def test_every_state_is_in_the_closed_vocabulary(self):
        for suivi in (None, self.SUIVI):
            for portee in (True, False, None):
                for occupe in (True, False, None):
                    mot, _pid = C.situation(suivi, portee, occupe)
                    self.assertIn(mot, C.ETATS)


class TestRienNestTueSansPreuve(unittest.TestCase):
    SUIVI = C.Suivi(pid=4242, port=8765)

    def setUp(self):
        self.signales = []

    def signal(self, pid):
        self.signales.append(pid)

    def test_a_proven_console_is_signalled(self):
        """Le contrôle positif : sans lui, un arrêt qui refuse toujours
        passerait les deux refus qui suivent."""
        self.assertEqual(
            C.ARRET_FAIT, C.arreter(self.SUIVI, True, self.signal)
        )
        self.assertEqual([4242], self.signales)

    def test_a_recycled_pid_is_never_signalled(self):
        self.assertEqual(
            C.ARRET_REFUSE, C.arreter(self.SUIVI, False, self.signal)
        )
        self.assertEqual([], self.signales)

    def test_an_unreadable_command_line_is_never_signalled(self):
        self.assertEqual(
            C.ARRET_REFUSE, C.arreter(self.SUIVI, None, self.signal)
        )
        self.assertEqual([], self.signales)

    def test_nothing_tracked_is_never_signalled(self):
        self.assertEqual(C.ARRET_REFUSE, C.arreter(None, True, self.signal))
        self.assertEqual([], self.signales)

    def test_a_signal_that_fails_is_said_and_not_swallowed(self):
        def refuse(_pid):
            raise ProcessLookupError(3, "No such process")

        self.assertEqual(
            C.ARRET_IMPOSSIBLE, C.arreter(self.SUIVI, True, refuse)
        )


class TestLaPorteResteSurLaBoucle(unittest.TestCase):
    """Lier large publierait sur le réseau une console sans serrure qui peut
    déployer sur la flotte."""

    def test_the_address_the_screen_verifies_is_the_loopback(self):
        self.assertTrue(C.ADRESSE.startswith("127."))
        self.assertIn(C.ADRESSE, C.url())

    def test_the_forward_keeps_both_ends_on_the_loopback(self):
        """L'authentification revient à SSH, elle ne disparaît pas."""
        ligne = C.redirection("poste-fictif.invalid", "exploitant")
        self.assertIn(f"{C.PORT}:{C.ADRESSE}:{C.PORT}", ligne)
        self.assertIn("exploitant@poste-fictif.invalid", ligne)
        self.assertNotIn("0.0.0.0", ligne)

    def test_a_forward_without_a_user_still_names_the_host(self):
        self.assertTrue(
            C.redirection("poste-fictif.invalid").endswith(
                "poste-fictif.invalid"
            )
        )

    def test_no_host_gives_no_line_rather_than_a_broken_one(self):
        for hote in ("", "   ", None):
            with self.subTest(hote=hote):
                self.assertEqual("", C.redirection(hote))


class TestLAttente(unittest.TestCase):
    """Le port ne s'ouvre ni ne se libère à l'instant du geste : sans attente,
    l'écran conclurait sur l'état d'avant."""

    def test_it_stops_as_soon_as_the_answer_comes(self):
        vus = iter([False, False, True, False])
        pauses = []
        self.assertTrue(
            C.attendre(lambda: next(vus), True, 10, lambda: pauses.append(1))
        )
        self.assertEqual(2, len(pauses))

    def test_it_gives_back_what_it_last_saw(self):
        self.assertFalse(C.attendre(lambda: False, True, 3, lambda: None))

    def test_it_never_pauses_after_the_last_look(self):
        pauses = []
        C.attendre(lambda: False, True, 3, lambda: pauses.append(1))
        self.assertEqual(2, len(pauses))

    def test_it_looks_at_least_once(self):
        regards = []
        C.attendre(lambda: regards.append(1) or True, True, 0)
        self.assertEqual(1, len(regards))


if __name__ == "__main__":
    unittest.main()
