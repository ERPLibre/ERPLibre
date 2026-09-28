#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Poser un modèle est la seule écriture du paquet, et elle reste hors du
balayage.

Ce que ces tests défendent tient en trois règles, et aucune ne se voit à
l'écran quand elle casse.

La reconnaissance doit rester INOFFENSIVE. `fingerprint` promet qu'un
balayage ne peut ni charger un modèle ni dépenser un jeton, et sa promesse
est tenue par un plan de requêtes en GET seul. Le jour où un chemin de pose
entre dans ce plan, un simple balayage de sous-réseau télécharge des
gigaoctets sur des machines que personne n'a désignées, et rien ne lève.

Une famille qui n'offre rien doit le DIRE. Treize familles se reconnaissent et
six ne savent pas poser de modèle ; leur proposer le geste rend 404, ce qui se
lit comme une panne de l'outil plutôt que comme une propriété du serveur.

Une panne doit rester TRADUISIBLE. Le module rend des clés, jamais des
phrases : une clé absente du dictionnaire s'affiche en anglais brut à un
lecteur francophone, et rien ne le signale — la vérification des clés du
menu ne lit que `assistant_menu.py`, donc pas celles-ci.

Aucune socket n'est ouverte : le transport est injecté partout.

Les hôtes sont INVENTÉS, comme `.claude/rules/04-code-conventions.md`
l'exige : le TLD « .invalid » est réservé et ne peut désigner aucune machine
du parc.
"""

import os
import subprocess
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant import capabilities  # noqa: E402
from script.todo.assistant import fingerprint  # noqa: E402
from script.todo.assistant import models  # noqa: E402
from script.todo.assistant import servers  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS  # noqa: E402

# Un hôte qui n'existe pas, et ne peut pas exister.
HOTE = "cinabre.invalid"


def un_serveur(software="ollama", **changes):
    """Un serveur retenu, tel que le registre le rend."""
    champs = {
        "handle": "server-1",
        "label": "Atelier",
        "host": HOTE,
        "port": 11434,
        "software": software,
        "model": "",
        "hosting": "lan",
        "secret_ref": "",
    }
    champs.update(changes)
    return servers.Server(**champs)


class UnTransport:
    """Un transport injecté : il note ce qu'on lui demande et rend ce qu'on
    lui a dit de rendre."""

    def __init__(self, reponse=(200, b"{}")):
        self.reponse = reponse
        self.appels = []

    def __call__(
        self, server, methode, chemin, corps, jeton, flux, long=False
    ):
        self.appels.append((methode, chemin, corps, jeton, flux, long))
        return self.reponse


class UnFlux:
    """Des lignes NDJSON qu'on peut fermer, et qui disent si on l'a fait."""

    def __init__(self, lignes):
        self._lignes = list(lignes)
        self.ferme = False

    def __iter__(self):
        for ligne in self._lignes:
            yield ligne

    def close(self):
        self.ferme = True


class LaTableDesFamilles(unittest.TestCase):
    def test_les_familles_de_l_echelle_sont_toutes_decrites(self):
        """Une famille reconnue mais absente de la table lèverait au lieu de
        refuser : toute famille que `fingerprint` sait nommer a sa ligne."""
        for probe in fingerprint.LADDER:
            with self.subTest(probe.software):
                self.assertIsNotNone(
                    models.famille(probe.software),
                    f"{probe.software} reconnu mais absent de FAMILLES",
                )

    def test_un_logiciel_inconnu_ne_leve_pas(self):
        """`fingerprint` rend la chaîne vide quand il n'a pas reconnu : la
        table doit y répondre par un refus, pas par une exception."""
        self.assertIsNone(models.famille(""))
        self.assertFalse(models.gere(""))
        self.assertFalse(models.gere("un-logiciel-qui-n-existe-pas"))

    def test_les_familles_qui_n_offrent_rien_le_disent(self):
        """Six familles servent un modèle choisi ailleurs : elles refusent
        avec une raison, et la raison n'est pas le refus générique."""
        for nom in (
            "jan",
            "gpt4all",
            "koboldcpp",
            "textgenwebui",
            "vllm",
            "openai",
        ):
            with self.subTest(nom):
                table = models.FAMILLES[nom]
                self.assertIsNone(table.pose)
                self.assertNotEqual(table.raison_pose, models.REFUS_FAMILLE)

    def test_localai_ne_reprend_pas_les_chemins_ecrivables_d_ollama(self):
        """LocalAI réémet l'API de lecture d'Ollama, PAS sa moitié
        écrivable : lui appliquer « /api/pull » rendrait 404."""
        localai = models.FAMILLES["localai"]
        self.assertNotIn("/api/pull", localai.pose.chemin)
        self.assertNotIn("/api/delete", localai.retrait.chemin)
        # Le retrait y est un POST, et non le DELETE d'Ollama.
        self.assertEqual(localai.retrait.methode, "POST")


class LaPose(unittest.TestCase):
    def test_un_flux_rend_ses_etapes_puis_conclut(self):
        """Les événements sortent dans l'ordre du flux, et la fin nomme le
        modèle posé."""
        flux = UnFlux(
            [
                b'{"status":"pulling manifest"}\n',
                b'{"status":"downloading","completed":5,"total":10}\n',
                b'{"status":"success"}\n',
            ]
        )
        vus = []
        issue = models.pose(
            un_serveur(),
            "petit-modele:7b",
            requete=UnTransport((200, flux)),
            sur_evenement=vus.append,
        )
        self.assertTrue(issue.ok)
        self.assertEqual(issue.detail, models.POSE_FAITE)
        self.assertEqual(vus[0], ("etat", "pulling manifest"))
        self.assertEqual(vus[1], ("octets", 5, 10))
        self.assertEqual(vus[-1], ("fini", "petit-modele:7b"))
        self.assertTrue(flux.ferme)

    def test_une_erreur_au_milieu_du_flux_echoue(self):
        """Ollama répond 200 puis annonce l'erreur DANS le corps : lire le
        seul statut déclarerait la pose réussie."""
        flux = UnFlux(
            [
                b'{"status":"pulling manifest"}\n',
                b'{"error":"file does not exist"}\n',
            ]
        )
        issue = models.pose(
            un_serveur(), "absent", requete=UnTransport((200, flux))
        )
        self.assertFalse(issue.ok)
        self.assertEqual(issue.detail, models.REFUS_SERVEUR)
        self.assertIn("file does not exist", issue.brut)

    def test_un_refus_du_serveur_porte_son_texte(self):
        """Le serveur explique en clair ce que le statut ne dit pas : le
        texte remonte tel quel, sans traduction, parce qu'il vient de
        là-bas."""
        issue = models.pose(
            un_serveur(),
            "petit-modele",
            requete=UnTransport((404, b'{"error":"model not found"}')),
        )
        self.assertFalse(issue.ok)
        self.assertEqual(issue.detail, models.REFUS_SERVEUR)
        self.assertEqual(issue.brut, "model not found")

    def test_un_serveur_muet_n_est_pas_un_succes(self):
        """Le transport rend None quand rien n'a abouti."""
        issue = models.pose(
            un_serveur(), "petit-modele", requete=UnTransport(None)
        )
        self.assertFalse(issue.ok)
        self.assertEqual(issue.detail, models.REFUS_MUET)

    def test_un_nom_vide_ne_touche_pas_au_reseau(self):
        """Le refus se prononce AVANT d'ouvrir une socket."""
        transport = UnTransport()
        issue = models.pose(un_serveur(), "   ", requete=transport)
        self.assertFalse(issue.ok)
        self.assertEqual(issue.detail, models.REFUS_VIDE)
        self.assertEqual(transport.appels, [])

    def test_une_famille_sans_pose_ne_touche_pas_au_reseau(self):
        transport = UnTransport()
        issue = models.pose(
            un_serveur(software="vllm"), "un-modele", requete=transport
        )
        self.assertFalse(issue.ok)
        self.assertEqual(issue.detail, models.SANS_POSE["vllm"])
        self.assertEqual(transport.appels, [])

    def test_une_famille_qui_exige_une_cle_refuse_sans_elle(self):
        """Présenter la requête pour recevoir 401 apprend ce que la table
        dit déjà, en dérangeant le serveur."""
        transport = UnTransport()
        issue = models.pose(
            un_serveur(software="open_webui"),
            "un-modele",
            requete=transport,
        )
        self.assertFalse(issue.ok)
        self.assertEqual(issue.detail, models.REFUS_JETON)
        self.assertEqual(transport.appels, [])

    def test_une_pose_asynchrone_dit_qu_elle_est_lancee(self):
        """LocalAI rend un identifiant de tâche et travaille ensuite seul :
        « accepté » n'est pas « posé »."""
        issue = models.pose(
            un_serveur(software="localai"),
            "un-modele",
            requete=UnTransport((200, b'{"uuid":"tache"}')),
        )
        self.assertTrue(issue.ok)
        self.assertEqual(issue.detail, models.POSE_LANCEE)

    def test_le_nom_du_modele_entre_dans_le_corps_et_le_chemin(self):
        """Un identifiant de dépôt porte une barre oblique, qui découperait
        le chemin si elle n'était pas encodée."""
        transport = UnTransport((200, b"{}"))
        models.retrait(
            un_serveur(software="localai"),
            "org/depot",
            requete=transport,
        )
        _, chemin, _, _, _, _ = transport.appels[0]
        self.assertIn("org%2Fdepot", chemin)
        self.assertNotIn("org/depot", chemin)


class UnFluxQuiTombe:
    """Des lignes dont la lecture lève en cours de route."""

    def __init__(self, lignes, souci):
        self._lignes = list(lignes)
        self._souci = souci
        self.ferme = False

    def __iter__(self):
        for ligne in self._lignes:
            yield ligne
        raise self._souci

    def close(self):
        self.ferme = True


class UnFluxCoupe(unittest.TestCase):
    """Un corps qui s'arrête en route n'est pas une pose réussie.

    Le statut HTTP a déjà laissé passer l'erreur une fois — c'est pourquoi le
    corps se lit. Conclure au succès parce que la boucle s'est terminée
    rouvrirait exactement ce trou, d'un cran plus bas.
    """

    def test_un_flux_sans_etat_final_echoue(self):
        flux = UnFlux(
            [
                b'{"status":"pulling manifest"}\n',
                b'{"status":"downloading","completed":5,"total":10}\n',
            ]
        )
        issue = models.pose(
            un_serveur(), "modele", requete=UnTransport((200, flux))
        )
        self.assertFalse(issue.ok)
        self.assertEqual(issue.detail, models.REFUS_COUPE)
        self.assertTrue(flux.ferme)

    def test_un_flux_vide_echoue(self):
        issue = models.pose(
            un_serveur(),
            "modele",
            requete=UnTransport((200, UnFlux([]))),
        )
        self.assertFalse(issue.ok)
        self.assertEqual(issue.detail, models.REFUS_COUPE)

    def test_une_socket_qui_tombe_ne_traverse_pas_pose(self):
        """La lecture lève en plein téléchargement ; sans garde, l'exception
        remonte jusqu'au menu, qui n'en attend aucune."""
        for souci in (
            ConnectionResetError("reset"),
            OSError("timed out"),
        ):
            with self.subTest(type(souci).__name__):
                flux = UnFluxQuiTombe([b'{"status":"downloading"}\n'], souci)
                issue = models.pose(
                    un_serveur(),
                    "modele",
                    requete=UnTransport((200, flux)),
                )
                self.assertFalse(issue.ok)
                self.assertEqual(issue.detail, models.REFUS_COUPE)
                self.assertTrue(flux.ferme)


class LeBudget(unittest.TestCase):
    def test_une_pose_qui_telecharge_avant_de_repondre_a_le_temps(self):
        """TabbyAPI tire ses poids PUIS répond : couper la requête au budget
        court y annule le téléchargement."""
        transport = UnTransport((200, b"{}"))
        models.pose(
            un_serveur(software="tabbyapi"),
            "org/depot",
            jeton="une-cle",
            requete=transport,
        )
        self.assertTrue(transport.appels[0][-1], "budget long attendu")

    def test_une_requete_courte_garde_le_budget_court(self):
        transport = UnTransport((200, b"{}"))
        models.retrait(un_serveur(), "m", requete=transport)
        self.assertFalse(transport.appels[0][-1])


class LaNote(unittest.TestCase):
    def test_exo_dit_que_les_poids_restent(self):
        """Le retrait d'EXO aboutit, mais n'ôte que la fiche : le succès le
        dit, là où `raison_retrait` ne se lirait qu'en l'absence de geste."""
        issue = models.retrait(
            un_serveur(software="exo"),
            "org/depot",
            requete=UnTransport((200, b"{}")),
        )
        self.assertTrue(issue.ok)
        self.assertEqual(issue.note, models.SANS_RETRAIT["exo"])

    def test_une_note_est_une_cle_traduite(self):
        for table in models.FAMILLES.values():
            for gabarit in (table.pose, table.retrait):
                if gabarit is None or not gabarit.note:
                    continue
                with self.subTest(gabarit.note):
                    self.assertIn(gabarit.note, TRANSLATIONS)


class LeRetrait(unittest.TestCase):
    def test_le_verbe_est_nomme(self):
        """`urllib` ne sait pas dire DELETE : le transport le nomme, et la
        table le prouve."""
        transport = UnTransport((200, b""))
        issue = models.retrait(
            un_serveur(), "petit-modele:7b", requete=transport
        )
        self.assertTrue(issue.ok)
        self.assertEqual(issue.detail, models.RETRAIT_FAIT)
        methode, chemin, corps, _, _, _ = transport.appels[0]
        self.assertEqual(methode, "DELETE")
        self.assertEqual(chemin, "/api/delete")
        self.assertEqual(corps, {"model": "petit-modele:7b"})

    def test_une_famille_sans_retrait_le_dit(self):
        """LM Studio pose sans savoir retirer : le refus nomme la raison au
        lieu de laisser croire à une panne."""
        transport = UnTransport()
        issue = models.retrait(
            un_serveur(software="lmstudio"), "un-modele", requete=transport
        )
        self.assertFalse(issue.ok)
        self.assertEqual(issue.detail, models.SANS_RETRAIT["lmstudio"])
        self.assertEqual(transport.appels, [])


class LaListe(unittest.TestCase):
    def test_les_deux_enveloppes_se_lisent(self):
        """« models » chez Ollama, « data » chez qui suit OpenAI."""
        ollama = models.listing(
            un_serveur(),
            requete=UnTransport(
                (200, b'{"models":[{"name":"a"},{"name":"b"}]}')
            ),
        )
        self.assertEqual(ollama, ["a", "b"])
        openai = models.listing(
            un_serveur(software="vllm"),
            requete=UnTransport((200, b'{"data":[{"id":"c"}]}')),
        )
        self.assertEqual(openai, ["c"])

    def test_une_lecture_qui_n_aboutit_pas_rend_une_liste_vide(self):
        """N'avoir rien lu n'est pas une panne du menu."""
        self.assertEqual(
            models.listing(un_serveur(), requete=UnTransport(None)), []
        )
        self.assertEqual(
            models.listing(un_serveur(), requete=UnTransport((401, b"nope"))),
            [],
        )


class LaReconnaissanceResteInoffensive(unittest.TestCase):
    def test_aucun_chemin_de_gestion_n_est_dans_le_plan_de_decouverte(self):
        """Un balayage ne doit pouvoir ni charger un modèle ni dépenser un
        jeton. Le jour où un de ces chemins entre dans le plan, balayer un
        /24 télécharge des gigaoctets sur des machines que personne n'a
        désignées."""
        plan = {chemin for _, chemin in fingerprint.probe_plan()}
        for nom, table in models.FAMILLES.items():
            for gabarit in (table.pose, table.retrait):
                if gabarit is None:
                    continue
                with self.subTest(f"{nom} {gabarit.chemin}"):
                    nu = gabarit.chemin.split("?")[0]
                    nu = nu.replace(models.MODELE, "")
                    self.assertNotIn(nu.rstrip("/"), plan)

    def test_le_plan_de_decouverte_reste_en_lecture_seule(self):
        """La garde d'en face : le plan ne porte que des GET."""
        for methode, _ in fingerprint.probe_plan():
            self.assertEqual(methode, "GET")


class LesClesDePanne(unittest.TestCase):
    def test_chaque_cle_rendue_est_traduite(self):
        """Le module rend des clés ; une clé absente s'affiche en anglais
        brut à un lecteur francophone, et la vérification des clés du menu
        ne lit que `assistant_menu.py`."""
        cles = [
            models.REFUS_FAMILLE,
            models.REFUS_VIDE,
            models.REFUS_SERVEUR,
            models.REFUS_MUET,
            models.REFUS_JETON,
            models.POSE_LANCEE,
            models.POSE_FAITE,
            models.RETRAIT_FAIT,
        ]
        cles += list(models.SANS_POSE.values())
        cles += list(models.SANS_RETRAIT.values())
        for cle in cles:
            with self.subTest(cle):
                self.assertIn(cle, TRANSLATIONS)

    def test_chaque_raison_declaree_dans_la_table_est_traduite(self):
        for nom, table in models.FAMILLES.items():
            for raison in (table.raison_pose, table.raison_retrait):
                with self.subTest(f"{nom} {raison}"):
                    self.assertIn(raison, TRANSLATIONS)


class LeTransport(unittest.TestCase):
    def test_capabilities_ne_sait_toujours_pas_dire_delete(self):
        """La raison d'être d'un second transport. Le jour où
        `capabilities._http` nommerait son verbe, ce module pourrait s'y
        replier — et ce test dirait de le relire."""
        self.assertNotIn("method=", capabilities._http.__code__.co_names)

    def test_un_hote_ipv6_perd_ses_crochets(self):
        """`HTTPConnection` pose les siens : les lui donner déjà posés
        produirait « [[::1]] »."""
        self.assertEqual(models._hote("[::1]"), "::1")
        self.assertEqual(models._hote("::1"), "::1")
        self.assertEqual(models._hote(f" {HOTE} "), HOTE)


class LaFrontiere(unittest.TestCase):
    def test_la_gestion_des_modeles_ne_tire_pas_todo(self):
        """Importer `script.todo.todo` coûte près d'une seconde et imprime
        sur la sortie : le paquet doit rester importable seul."""
        # Dans un interpréteur NEUF : la suite complète importe todo par
        # ailleurs, et le sys.modules de ce processus en garderait la trace
        # quel que soit le module éprouvé ici.
        sortie = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, script.todo.assistant.models;"
                " print('script.todo.todo' in sys.modules)",
            ],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertEqual(sortie.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
