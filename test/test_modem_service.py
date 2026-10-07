#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les unites systemd du modem : ce qu'elles portent, et ce qu'elles refusent.

Ce qui se verifie ici sans privilege : le rendu des gabarits, la place des
secrets, et les commandes construites. Poser une unite demande sudo et
appartient a la machine, pas a un test.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.modem import service  # noqa: E402


class TestGabarits(unittest.TestCase):
    def test_les_deux_unites_ont_leur_gabarit(self):
        for unite in service.UNITES:
            self.assertTrue(os.path.isfile(service.gabarit(unite)), unite)

    def test_aucun_jeton_ne_survit_au_rendu(self):
        """Un jeton oublie donne une unite que systemd accepte et qui echoue
        au demarrage sur un chemin litteral, illisible dans un journal."""
        for unite in service.UNITES:
            texte = service.rendre(unite)
            for ligne in texte.splitlines():
                if ligne.startswith("#") or not ligne.strip():
                    continue
                self.assertNotRegex(ligne, r"@[A-Z_]+@", "%s : %s" % (unite, ligne))

    def test_un_jeton_inconnu_leve_au_lieu_de_passer(self):
        with mock.patch.object(service, "valeurs", return_value={}):
            with self.assertRaises(ValueError):
                service.rendre(service.AGENT)

    def test_le_service_tourne_sous_le_compte_qui_le_pose(self):
        """Le port AT est au groupe « dialout » et la carte son a « audio ».
        systemd donne a l'unite tous les groupes du compte ; root n'aurait pas
        besoin de ces groupes, mais ecrirait les enregistrements en root."""
        import getpass

        for unite in service.UNITES:
            self.assertIn("User=%s" % getpass.getuser(), service.rendre(unite))

    def test_la_voix_est_interrompue_et_non_tuee(self):
        """Tue net, le binaire laisse le modem en conversation, et l'appel
        continue de se facturer jusqu'a ce que l'autre raccroche."""
        texte = service.rendre(service.VOIX)
        self.assertIn("KillSignal=SIGINT", texte)
        self.assertIn("TimeoutStopSec=", texte)

    def test_la_voix_ecoute_la_boucle_locale(self):
        """Un navigateur n'ouvre le micro sans certificat que dans un contexte
        sur, et l'adresse du poste n'en est pas un."""
        self.assertTrue(service.ECOUTE_DEFAUT.startswith("127.0.0.1:"))
        self.assertIn("-navigateur " + service.ECOUTE_DEFAUT,
                      service.rendre(service.VOIX))

    def test_l_agent_tourne_avec_l_interpreteur_du_depot(self):
        """« python3 » du systeme n'a pas les dependances : l'agent echouerait
        au demarrage sans dire laquelle manque."""
        texte = service.rendre(service.AGENT)
        self.assertIn("-m script.todo.modem.passerelle", texte)
        self.assertIn(".venv.erplibre", texte)

    def test_aucun_secret_dans_les_unites(self):
        """Une unite est lisible par tout le monde en 0644 : le secret passe
        par un fichier d'environnement en 0600, jamais par ExecStart."""
        secret = service.valeurs_environnement()["ERPLIBRE_SMS_HMAC_SECRET"]
        compte = service.postes()
        for unite in service.UNITES:
            texte = service.rendre(unite)
            if secret:
                self.assertNotIn(secret, texte, unite)
            self.assertNotIn(compte.split(":", 1)[-1], texte, unite)
            self.assertIn("EnvironmentFile=", texte)


class TestCompteDuSoftphone(unittest.TestCase):
    """Le compte du poste, que les DEUX cotes doivent porter identique."""

    def setUp(self):
        self.tmp = mock.patch.object(service, "chemin_postes")
        self.faux = self.tmp.start()
        self.addCleanup(self.tmp.stop)
        import tempfile

        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.faux.return_value = os.path.join(dossier.name, "voip", "postes")

    def test_il_se_cree_une_fois_puis_ne_change_plus(self):
        """Le regenerer couperait l'inscription du navigateur, qui porte
        encore l'ancien."""
        premier = service.postes()
        self.assertEqual(premier, service.postes())
        self.assertIn(":", premier)

    def test_il_n_est_lisible_que_par_son_proprietaire(self):
        service.postes()
        mode = os.stat(service.chemin_postes()).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_le_mot_de_passe_n_est_pas_devinable(self):
        _poste, _, mot = service.postes().partition(":")
        self.assertGreaterEqual(len(mot), 24)


class TestEnvironnement(unittest.TestCase):
    def test_les_deux_noms_de_l_url_portent_la_meme_valeur(self):
        """Le service Go lit ERPLIBRE_ODOO_URL, l'agent Python
        ERPLIBRE_SMS_URL : deux noms pour un seul serveur, et deux valeurs
        differentes enverraient les appels et les SMS a deux endroits."""
        valeurs = service.valeurs_environnement()
        self.assertEqual(valeurs["ERPLIBRE_ODOO_URL"],
                         valeurs["ERPLIBRE_SMS_URL"])

    def test_une_valeur_absente_refuse_la_pose(self):
        """Poser un fichier incomplet donnerait un service qui demarre et ne
        sert pas, ce qui se diagnostique bien plus tard."""
        with mock.patch.object(service, "valeurs_environnement",
                               return_value={"ERPLIBRE_SMS_URL": ""}):
            ok, detail = service.poser_environnement()
        self.assertFalse(ok)
        self.assertIn("ERPLIBRE_SMS_URL", detail)

    def test_l_etat_se_lit_sans_sudo(self):
        """Le fichier pose appartient a root en 0600 : l'etat s'appuie donc
        sur les SOURCES des valeurs, que l'exploitant peut lire."""
        appels = []

        def faux_run(args, timeout=30):
            appels.append(args)
            return 1, ""

        with mock.patch.object(service, "_run", faux_run):
            for unite in service.UNITES:
                service.variables_manquantes(unite)
        self.assertEqual([a for a in appels if "sudo" in a], [])


class TestCommandes(unittest.TestCase):
    def test_une_action_inconnue_est_refusee(self):
        ok, detail = service.commander(service.AGENT, "reload")
        self.assertFalse(ok)
        self.assertIn("reload", detail)

    def test_le_demarrage_automatique_se_commande_aussi(self):
        """Un service arrete mais toujours active revient de lui-meme au
        redemarrage suivant, et l'on cherche alors pourquoi il interroge."""
        appels = []

        def faux_run(args, timeout=30):
            appels.append(args)
            return 0, ""

        with mock.patch.object(service, "posee", return_value=True), \
                mock.patch.object(service, "_run", faux_run), \
                mock.patch.object(service.subprocess, "run"):
            for action in ("enable", "disable"):
                ok, _detail = service.commander(service.AGENT, action)
                self.assertTrue(ok, action)
        poses = [a for a in appels if "systemctl" in a]
        self.assertIn("enable", poses[0])
        self.assertIn("disable", poses[1])

    def test_une_action_hors_liste_reste_refusee(self):
        for action in ("mask", "reload-or-restart", ""):
            ok, detail = service.commander(service.AGENT, action)
            self.assertFalse(ok, action)
            self.assertIn("action inconnue", detail)

    def test_on_ne_commande_pas_une_unite_absente(self):
        """Sinon systemctl repond une erreur qui parle de lui, pas de nous."""
        with mock.patch.object(service, "posee", return_value=False):
            ok, detail = service.commander(service.AGENT, "start")
        self.assertFalse(ok)
        self.assertIn(service.AGENT, detail)

    def test_le_journal_se_lit_sans_sudo(self):
        """Demander sudo pour regarder ce qui ne va pas ajouterait une invite
        au pire moment."""
        vus = []

        def faux_run(args, timeout=30):
            vus.append(args)
            return 0, "une ligne"

        with mock.patch.object(service, "_run", faux_run):
            service.journal(service.VOIX, 5)
        self.assertEqual(vus[0][0], "journalctl")
        self.assertNotIn("sudo", vus[0])



class TestSoftphoneOdoo(unittest.TestCase):
    """Ce qu'on ecrit dans Odoo pour que le navigateur s'inscrive."""

    def setUp(self):
        from script.todo.modem import softphone

        self.soft = softphone

    def test_le_serveur_se_retrouve_au_lieu_de_se_dedoubler(self):
        script = self.soft.render_setup_script("1001", "secret", "127.0.0.1:8189")
        self.assertIn("search(", script)
        self.assertIn("pbx.write(valeurs)", script)

    def test_le_mode_est_production(self):
        """Le defaut du module est « test », ou l'appel n'est pas place : le
        softphone s'inscrit alors et ne sonne jamais."""
        self.assertEqual(self.soft.MODE, "prod")
        self.assertIn("'prod'",
                      self.soft.render_setup_script("1001", "s", "127.0.0.1:8189"))

    def test_le_domaine_est_l_hote_seul(self):
        """C'est le « realm » que le service annonce dans son defi : un ecart y
        fait refuser un mot de passe juste."""
        script = self.soft.render_setup_script("1001", "s", "127.0.0.1:8189")
        self.assertIn('"domain": \'127.0.0.1\'', script)
        self.assertIn('"ws_server": \'ws://127.0.0.1:8189\'', script)

    def test_un_utilisateur_absent_se_dit_au_lieu_de_passer(self):
        script = self.soft.render_setup_script("1001", "s", "127.0.0.1:8189",
                                               login="absent")
        self.assertIn("RESULTAT_ERREUR", script)

    def test_le_compte_vient_du_meme_fichier_que_le_service(self):
        """Les deux cotes doivent porter le meme mot de passe ; une valeur
        saisie deux fois finit par differer."""
        vus = {}

        def faux_lancer(base, script):
            vus["base"], vus["script"] = base, script
            return 0, "RESULTAT_PBX=1\nRESULTAT_WS=ws://x\nRESULTAT_POSTE=1001\n"

        poste, _, mot = service.postes().partition(":")
        ok, detail = self.soft.configurer("une_base", lancer=faux_lancer)
        self.assertTrue(ok, detail)
        self.assertIn(mot, vus["script"])
        self.assertIn(poste, vus["script"])



class TestPoseConditionnee(unittest.TestCase):
    """Poser une unite la DEMARRE : ce qui ne peut pas servir ne part pas."""

    def test_sans_environnement_la_pose_est_refusee(self):
        """Un service sans son environnement echoue aussitot : on obtient une
        unite en panne, une boucle de relances, et une cause enfouie a trois
        niveaux dans un journal."""
        appels = []

        def faux_run(args, timeout=30):
            appels.append(args)
            return 0, ""

        with mock.patch.object(service, "environnement_pose", return_value=False), \
                mock.patch.object(service, "_run", faux_run):
            for unite in service.UNITES:
                ok, detail = service.poser(unite)
                self.assertFalse(ok, unite)
                self.assertIn(service.CHEMIN_ENV, detail)
        self.assertEqual(appels, [], "rien ne doit avoir ete lance")

    def test_les_valeurs_disponibles_ne_suffisent_pas(self):
        """C'est le FICHIER que systemd lira, pas l'etat du poste : les deux se
        confondaient, et l'ecran annoncait « rien ne manque » pendant que les
        services echouaient faute de fichier."""
        with mock.patch.object(service, "environnement_pose", return_value=False):
            ok, _detail = service.poser(service.AGENT)
        self.assertFalse(ok)
        self.assertEqual(service.variables_manquantes(service.AGENT), [])
if __name__ == "__main__":
    unittest.main()
