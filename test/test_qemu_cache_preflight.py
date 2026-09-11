#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Savoir avant de couper ce qui a manqué ; le combler tant qu'on est en ligne.

Un déploiement hors ligne qui a manqué une adresse la manquera encore au
suivant, si rien ne l'a remplie entre-temps. Le journal d'accès le sait —
chaque « offline-miss » porte son client et son instant — et le suivi des
installations sait quelle VM portait quelle adresse, et quand. Réunis, ils
disent quoi annoncer avant la coupure, et quoi rejouer par le cache tant que
l'amont répond.

Aucun test ne touche la machine qui les exécute : ni pare-feu, ni service, ni
réseau. Toute commande est interceptée pour la CLASSE entière, et la doublure
ne relaie jamais vers la vraie : un chemin qui lancerait une commande imprévue
échoue sur une réponse vide au lieu d'agir.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.qemu import cache_offline  # noqa: E402
from script.todo.qemu_install_monitor import EXIT_MARKER  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except ImportError:
    TEXTUAL = False

INSTALLATEUR = RACINE / "script" / "install" / "install_qemu_cache.sh"
QEMU_FORM = RACINE / "script" / "todo" / "qemu_deploy_form.py"

# Des valeurs inventées : un nom de VM qu'aucun parc ne porte, des adresses
# de documentation (RFC 5737) et des domaines réservés (RFC 2606).
MAINTENANT = 1_900_000_000.0
NOM = "vm-essai-hl"
AUTRE = "vm-essai-autre"
IP = "192.0.2.10"
URL_A = "https://example.com/depot/a.tar.gz?v=1&w=2"
URL_A2 = "https://example.com/depot/cible.tar.gz"
URL_B = "http://example.org/liste"
URL_C = "https://example.net/racine/16.json"
URL_POST = "https://example.net/api/stats"
URL_IP = "https://192.0.2.99/objet"


def iso(instant):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(instant))


def ligne(instant, issue, url, methode="GET", client=IP):
    """Une ligne du journal d'accès, telle que le service l'écrit."""
    return {
        "time": iso(instant),
        "method": methode,
        "url": url,
        "class": "volatile",
        "outcome": issue,
        "status": 504 if issue == "offline-miss" else 200,
        "bytes": 0,
        "upstream": False,
        "client": client,
    }


class SansSysteme(unittest.TestCase):
    """subprocess.run est remplacé pour toute la classe, sans relais.

    La doublure note chaque appel et répond par « repondre », qui rend par
    défaut un échec vide. Le jour où le code sous test lance une commande
    que le test n'attend pas, il reçoit ce vide — jamais la machine réelle.
    """

    def setUp(self):
        self.lancees = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dossier = Path(self.tmp.name)

        def doublure(cmd, *a, **kw):
            texte = cmd if isinstance(cmd, str) else " ".join(map(str, cmd))
            self.lancees.append((texte, kw))
            rc, sortie = self.repondre(texte, kw)
            return subprocess.CompletedProcess(cmd, rc, sortie, "")

        patch = mock.patch("subprocess.run", doublure)
        patch.start()
        self.addCleanup(patch.stop)

    def repondre(self, texte, kw):
        return 127, ""

    def journal(self, lignes):
        chemin = self.dossier / "acces.jsonl"
        with open(chemin, "w", encoding="utf-8") as fh:
            for d in lignes:
                # Compact, comme le json.Marshal de Go.
                fh.write(json.dumps(d, separators=(",", ":")) + "\n")
        return str(chemin)

    def deploiement(
        self,
        label,
        debut,
        vms,
        branche="develop",
        deploy_started=None,
        hors_ligne=None,
    ):
        """Un répertoire de déploiement : session.json et un log par VM.

        vms : [(nom, ip, fin, code)]. « fin » date le log ; un code None le
        laisse sans marqueur de sortie, comme une installation en cours.
        « deploy_started » et « hors_ligne », quand ils sont donnés, sont
        écrits au manifeste comme le fait le suivi des installations — le
        second sous « offline ».
        """
        d = self.dossier / "runs" / label
        d.mkdir(parents=True)
        entrees = []
        for nom, ip, fin, code in vms:
            log = d / f"{nom}.log"
            texte = "en-tête\n"
            if code is not None:
                texte += f"{EXIT_MARKER} {code}\n"
            log.write_text(texte)
            os.utime(log, (fin, fin))
            entrees.append({"name": nom, "ip": ip, "log": str(log)})
        manifeste = {"branch": branche, "started": debut, "vms": entrees}
        if deploy_started is not None:
            manifeste["deploy_started"] = deploy_started
        if hors_ligne is not None:
            manifeste["offline"] = hors_ligne
        (d / "session.json").write_text(json.dumps(manifeste))
        return str(self.dossier / "runs")


# ---------------------------------------------------------------------------
# Le choix des déploiements qui renseignent
# ---------------------------------------------------------------------------


class TestLeBilanDesDeploiements(SansSysteme):
    """Quels déploiements parlent, et pour quelle VM.

    Deux pannes muettes sont gardées ici. Prendre le seul dernier déploiement
    rend l'avertissement muet dès qu'il s'est arrêté avant d'avoir rien
    demandé. Et une adresse IP se réattribue : sans la fenêtre du déploiement,
    les manques d'une VM seraient comptés à une autre.
    """

    def bilan(self, racine, lignes, nom=NOM):
        runs = cache_offline.lire_runs(racine)
        releve = cache_offline.releve_amont_muet(
            self.journal(lignes), {IP, "192.0.2.11"}
        )
        return cache_offline.bilan_du_nom(runs, nom, releve, MAINTENANT)

    def test_les_deploiements_renseignes_sont_reunis(self):
        t1, t2 = MAINTENANT - 7200, MAINTENANT - 3600
        racine = self.deploiement("ancien", t1 - 600, [(NOM, IP, t1, 1)])
        self.deploiement("recent", t2 - 600, [(NOM, IP, t2, 1)])
        b = self.bilan(
            racine,
            [
                ligne(t1 - 300, "offline-miss", URL_A),
                ligne(t2 - 300, "offline-miss", URL_B),
                ligne(t2 - 200, "offline-miss", URL_A),
            ],
        )
        self.assertEqual(set(b["manques"]), {("GET", URL_A), ("GET", URL_B)})
        self.assertEqual(b["runs"], ["recent", "ancien"])
        self.assertAlmostEqual(b["age"], 3600, delta=1)

    def test_un_deploiement_arrete_tot_ne_renseigne_pas(self):
        """Coupé, arrêté sur un verrou apt avant d'avoir rien manqué : il ne
        dit rien, et ne doit pas faire taire le précédent."""
        t1, t2 = MAINTENANT - 7200, MAINTENANT - 3600
        racine = self.deploiement("ancien", t1 - 600, [(NOM, IP, t1, 1)])
        self.deploiement("verrou", t2 - 600, [(NOM, IP, t2, 100)])
        b = self.bilan(
            racine,
            [
                ligne(t1 - 300, "offline-miss", URL_A),
                ligne(t2 - 300, "stale", URL_B),
            ],
        )
        self.assertIsNotNone(b, "l'arrêt précoce a fait taire l'avertissement")
        self.assertEqual(b["runs"], ["ancien"])
        self.assertEqual(list(b["manques"]), [("GET", URL_A)])

    def test_une_reussite_hors_ligne_clot_la_lecture(self):
        """Réussi coupé : ce qui manquait avant a été rempli, ou n'est plus
        demandé. Le rappeler serait un avertissement sans motif."""
        t1, t2 = MAINTENANT - 7200, MAINTENANT - 3600
        racine = self.deploiement("ancien", t1 - 600, [(NOM, IP, t1, 1)])
        self.deploiement(
            "reussi", t2 - 600, [(NOM, IP, t2, 0)], hors_ligne=True
        )
        b = self.bilan(
            racine,
            [
                ligne(t1 - 300, "offline-miss", URL_A),
                ligne(t2 - 300, "stale", URL_B),
            ],
        )
        self.assertIsNone(b)

    def test_une_reussite_quon_ne_sait_pas_coupee_ne_clot_rien(self):
        """Un amont qui vient de refuser une connexion est tenu pour muet
        quelques secondes : des lignes « stale » naissent alors EN LIGNE. Une
        réussite n'est une preuve hors ligne que si le manifeste le dit."""
        t1, t2 = MAINTENANT - 7200, MAINTENANT - 3600
        for hors_ligne in (False, None):
            with self.subTest(hors_ligne=hors_ligne):
                racine = self.deploiement(
                    f"ancien-{hors_ligne}", t1 - 600, [(NOM, IP, t1, 1)]
                )
                self.deploiement(
                    f"recent-{hors_ligne}",
                    t2 - 600,
                    [(NOM, IP, t2, 0)],
                    hors_ligne=hors_ligne,
                )
                b = self.bilan(
                    racine,
                    [
                        ligne(t1 - 300, "offline-miss", URL_A),
                        ligne(t2 - 300, "stale", URL_B),
                    ],
                )
                self.assertIsNotNone(b, "une réussite en ligne a tout tu")
                self.assertEqual(list(b["manques"]), [("GET", URL_A)])
                shutil.rmtree(racine)

    def test_le_hors_ligne_du_manifeste_est_lu(self):
        """Un booléen seul fait foi : toute autre valeur ne dit rien."""
        for ecrit, lu in ((True, True), (False, False), ("oui", None)):
            with self.subTest(ecrit=ecrit):
                racine = self.deploiement(
                    "seul",
                    MAINTENANT - 600,
                    [(NOM, IP, MAINTENANT, 1)],
                    hors_ligne=ecrit,
                )
                runs = cache_offline.lire_runs(racine)
                self.assertIs(runs[0]["hors_ligne"], lu)
                shutil.rmtree(racine)
        racine = self.deploiement(
            "sans", MAINTENANT - 600, [(NOM, IP, MAINTENANT, 1)]
        )
        self.assertIsNone(cache_offline.lire_runs(racine)[0]["hors_ligne"])

    def test_une_reussite_hors_ligne_garde_ses_propres_manques(self):
        """Les blocs d'outils facultatifs préviennent et rendent 0 : une
        installation coupée qui en a manqué plusieurs réussit quand même.
        Ses manques parlent ; seuls les déploiements plus anciens se
        taisent."""
        t1, t2 = MAINTENANT - 7200, MAINTENANT - 3600
        racine = self.deploiement("ancien", t1 - 600, [(NOM, IP, t1, 1)])
        self.deploiement(
            "reussi", t2 - 600, [(NOM, IP, t2, 0)], hors_ligne=True
        )
        b = self.bilan(
            racine,
            [
                ligne(t1 - 300, "offline-miss", URL_A),
                ligne(t2 - 400, "stale", URL_C),
                ligne(t2 - 300, "offline-miss", URL_B),
            ],
        )
        self.assertIsNotNone(b, "les manques d'une réussite sont perdus")
        self.assertEqual(b["runs"], ["reussi"])
        self.assertEqual(list(b["manques"]), [("GET", URL_B)])

    def test_la_fenetre_souvre_au_debut_du_deploiement(self):
        """Le premier démarrage d'une VM coupée passe par le cache avant le
        lancement des installations : « deploy_started » ouvre la fenêtre
        là, et un manque de ce démarrage est attribué."""
        fin = MAINTENANT - 3600
        racine = self.deploiement(
            "seul", fin - 600, [(NOM, IP, fin, 1)], deploy_started=fin - 1500
        )
        b = self.bilan(racine, [ligne(fin - 1200, "offline-miss", URL_A)])
        self.assertIsNotNone(b, "le manque du premier démarrage est perdu")
        self.assertEqual(list(b["manques"]), [("GET", URL_A)])

    def test_sans_deploy_started_la_fenetre_souvre_au_lancement(self):
        """Un manifeste qui ne le porte pas garde la règle d'avant : le plus
        tôt du répertoire et de « started »."""
        fin = MAINTENANT - 3600
        racine = self.deploiement("seul", fin - 600, [(NOM, IP, fin, 1)])
        self.assertIsNone(
            self.bilan(racine, [ligne(fin - 1200, "offline-miss", URL_A)])
        )
        self.assertIsNotNone(
            self.bilan(racine, [ligne(fin - 300, "offline-miss", URL_A)])
        )

    def test_une_reussite_en_ligne_ne_clot_rien(self):
        """Réussi amont branché : il ne prouve rien du hors ligne."""
        t1, t2 = MAINTENANT - 7200, MAINTENANT - 3600
        racine = self.deploiement("ancien", t1 - 600, [(NOM, IP, t1, 1)])
        self.deploiement("en_ligne", t2 - 600, [(NOM, IP, t2, 0)])
        b = self.bilan(racine, [ligne(t1 - 300, "offline-miss", URL_A)])
        self.assertIsNotNone(b)
        self.assertEqual(b["runs"], ["ancien"])

    def test_la_cle_est_le_nom_et_la_fenetre(self):
        """La même adresse, portée par deux VM à deux moments."""
        t1, t2 = MAINTENANT - 7200, MAINTENANT - 3600
        racine = self.deploiement("autre", t1 - 600, [(AUTRE, IP, t1, 1)])
        self.deploiement("la_notre", t2 - 600, [(NOM, IP, t2, 1)])
        lignes = [
            ligne(t1 - 300, "offline-miss", URL_C),
            ligne(t2 - 300, "offline-miss", URL_A),
        ]
        self.assertEqual(
            list(self.bilan(racine, lignes)["manques"]), [("GET", URL_A)]
        )
        self.assertEqual(
            list(self.bilan(racine, lignes, nom=AUTRE)["manques"]),
            [("GET", URL_C)],
        )

    def test_la_fenetre_ecarte_avant_et_apres(self):
        """Une ligne écrite après la fin du log vient d'un autre geste sur la
        VM, pas du déploiement."""
        fin = MAINTENANT - 3600
        racine = self.deploiement("seul", fin - 600, [(NOM, IP, fin, 1)])
        b = self.bilan(
            racine,
            [
                ligne(fin - 900, "offline-miss", URL_B),
                ligne(fin - 300, "offline-miss", URL_A),
                ligne(fin + 60, "offline-miss", URL_C),
            ],
        )
        self.assertEqual(list(b["manques"]), [("GET", URL_A)])

    def test_le_debut_est_le_plus_tot_des_deux(self):
        """« started » est écrit après le lancement de toutes les VM ; le nom
        du répertoire date le début du lancement."""
        fin = MAINTENANT - 3600
        label = time.strftime("%Y%m%d-%H%M%S", time.localtime(fin - 900))
        racine = self.deploiement(label, fin - 600, [(NOM, IP, fin, 1)])
        b = self.bilan(racine, [ligne(fin - 800, "offline-miss", URL_A)])
        self.assertIsNotNone(b, "la première requête a été perdue")

    def test_trop_vieux_se_tait(self):
        fin = MAINTENANT - cache_offline.AGE_MAX - 60
        racine = self.deploiement("vieux", fin - 600, [(NOM, IP, fin, 1)])
        self.assertIsNone(
            self.bilan(racine, [ligne(fin - 300, "offline-miss", URL_A)])
        )

    def test_le_nombre_de_deploiements_est_borne(self):
        lignes = []
        racine = ""
        for i in range(4):
            fin = MAINTENANT - 3600 * (i + 1)
            racine = self.deploiement(f"r{i}", fin - 600, [(NOM, IP, fin, 1)])
            lignes.append(ligne(fin - 300, "offline-miss", f"{URL_B}/{i}"))
        b = self.bilan(racine, lignes)
        self.assertEqual(len(b["runs"]), cache_offline.RUNS_RETENUS)

    def test_sans_branche_rien_nest_installe(self):
        fin = MAINTENANT - 3600
        racine = self.deploiement(
            "demarrage", fin - 600, [(NOM, IP, fin, 1)], branche=""
        )
        self.assertIsNone(
            self.bilan(racine, [ligne(fin - 300, "offline-miss", URL_A)])
        )


# ---------------------------------------------------------------------------
# Ce que le magasin détient, ou le journal à défaut
# ---------------------------------------------------------------------------


class TestCeQueLeMagasinDetient(SansSysteme):
    """Le bilan moins ce que le cache détient MAINTENANT."""

    def preflight(self, detient, extra=()):
        fin = MAINTENANT - 3600
        racine = self.deploiement("seul", fin - 600, [(NOM, IP, fin, 1)])
        lignes = [
            ligne(fin - 400, "offline-miss", URL_A),
            ligne(fin - 350, "offline-miss", URL_B),
            ligne(fin - 300, "offline-miss", URL_POST, methode="POST"),
            ligne(fin - 250, "offline-miss", URL_C, methode="HEAD"),
        ] + list(extra)
        return cache_offline.manques_hors_ligne(
            [{"name": NOM}],
            racine=racine,
            chemin=self.journal(lignes),
            maintenant=MAINTENANT,
            detient=detient,
        )

    def test_le_magasin_soustrait_ce_quil_detient(self):
        demandes = []

        def detient(paires):
            demandes.extend(paires)
            return {
                ("GET", URL_A): {"verdict": "garde"},
                ("HEAD", URL_C): {"verdict": "statut"},
                ("GET", URL_B): {"verdict": "absent"},
            }

        (b,) = self.preflight(detient)
        self.assertEqual(b["manquants"], [("GET", URL_B)])
        self.assertFalse(b["selon_journal"])
        self.assertNotIn(
            ("POST", URL_POST), demandes, "un POST n'a rien à demander"
        )

    def test_un_post_nest_pas_compte_mais_nomme(self):
        (b,) = self.preflight(lambda paires: {})
        self.assertNotIn(("POST", URL_POST), b["manquants"])
        self.assertEqual(b["jamais"], [("POST", URL_POST)])

    def test_ce_que_le_cache_ne_garde_pas_va_avec_les_post(self):
        (b,) = self.preflight(
            lambda paires: {("GET", URL_B): {"verdict": "non-cachable"}}
        )
        self.assertIn(("GET", URL_B), b["jamais"])
        self.assertNotIn(("GET", URL_B), b["manquants"])

    def test_une_negociation_git_nomme_son_depot_a_part(self):
        """Un GET de négociation n'est ni un POST ni une adresse à
        rejouer : c'est un dépôt que le miroir remplit. Compté par dépôt, et
        jamais demandé au magasin."""
        depot = "https://example.com/o/d.git"
        demandes = []

        def detient(paires):
            demandes.extend(paires)
            return {}

        (b,) = self.preflight(
            detient,
            extra=[
                ligne(
                    MAINTENANT - 3900,
                    "offline-miss",
                    f"{depot}/info/refs?service=git-upload-pack",
                ),
                ligne(
                    MAINTENANT - 3850,
                    "offline-miss",
                    f"{depot}/git-upload-pack",
                    methode="POST",
                ),
            ],
        )
        self.assertEqual(b["git"], [depot])
        for cle in b["jamais"] + b["manquants"] + demandes:
            self.assertNotIn(depot, cle[1], cle)
        self.assertEqual(b["jamais"], [("POST", URL_POST)])

    def test_selon_le_journal_une_negociation_git_nest_pas_comblable(self):
        """Sans « --detient », le journal ne dit rien d'une négociation : la
        compter parmi les manquants promettrait un rejeu qui ne garde rien."""
        url = "https://example.com/o/d.git/info/refs?service=git-upload-pack"
        (b,) = self.preflight(
            lambda paires: None,
            extra=[ligne(MAINTENANT - 3900, "offline-miss", url)],
        )
        self.assertNotIn(("GET", url), b["manquants"])
        self.assertEqual(b["git"], ["https://example.com/o/d.git"])

    def test_le_depot_dune_negociation(self):
        for url, attendu in (
            (
                "https://example.com/o/d.git/info/refs?service=x",
                "https://example.com/o/d.git",
            ),
            ("http://example.org/d/git-receive-pack", "http://example.org/d"),
            ("https://example.com/info/refs", "https://example.com/"),
            ("https://example.com/o/d.git/HEAD", ""),
            ("", ""),
        ):
            self.assertEqual(cache_offline.depot_git(url), attendu, url)

    def test_selon_le_journal_une_garde_anterieure_ne_compte_pas(self):
        """Un objet gardé puis purgé laisse ses lignes « stored » : seule
        une garde POSTÉRIEURE au manque vaut détention."""
        fin = MAINTENANT - 3600
        (b,) = self.preflight(
            lambda paires: None,
            extra=[
                ligne(fin - 5000, "stored", URL_A),
                ligne(fin + 900, "stored", URL_B),
                ligne(fin + 950, "stored-status", URL_C, methode="HEAD"),
            ],
        )
        self.assertTrue(b["selon_journal"])
        self.assertEqual(b["manquants"], [("GET", URL_A)])

    def test_tout_detenu_se_tait(self):
        self.assertEqual(
            self.preflight(
                lambda paires: {p: {"verdict": "garde"} for p in paires}
            ),
            [],
        )

    def test_sans_deploiement_rien_nest_lu_ni_lance(self):
        fin = MAINTENANT - 3600
        racine = self.deploiement("autre", fin - 600, [(AUTRE, IP, fin, 1)])

        def interdit(paires):
            raise AssertionError("le magasin a été interrogé pour rien")

        self.assertEqual(
            cache_offline.manques_hors_ligne(
                [{"name": NOM}],
                racine=racine,
                chemin=str(self.dossier / "absent.jsonl"),
                maintenant=MAINTENANT,
                detient=interdit,
            ),
            [],
        )
        self.assertEqual(self.lancees, [])


class TestUnObjetDeStatutNestPasUnCorps(unittest.TestCase):
    """Une redirection ou un refus gardés ne rendent pas une suite lisible.

    Le contrôle de la suite compte les issues qui prouvent un CORPS ; y mêler
    les objets de statut ferait taire « le cache n'a rien pour ce système »
    devant un index gardé en 404. Pour le bilan hors ligne, en revanche, ils
    valent réponse : la VM reçoit ce que l'amont avait rendu.
    """

    def test_les_issues_de_statut_restent_hors_de_la_reserve(self):
        for issue in ("stored-status", "stale-status"):
            self.assertNotIn(issue, cache_offline.ISSUES_EN_RESERVE)
            self.assertIn(issue, cache_offline.ISSUES_REPONSE_GARDEE)


class TestLaQuestionAuMagasin(SansSysteme):
    """« --detient » : sondé dans l'aide, interrogé sur l'entrée standard."""

    def setUp(self):
        super().setUp()
        self.binaire = self.dossier / "binaire"
        self.binaire.write_text("")
        self.aide = "  -cache-dir string\n  -detient\n    lit l'entrée\n"
        self.rc = 0
        self.sortie = (
            f"garde\t200\t2030-01-01T00:00:00Z\tvolatile\tGET\t{URL_A}\n"
            f"absent\t0\t-\tvolatile\tGET\t{URL_B}\n"
        )
        self.entree = None

    def repondre(self, texte, kw):
        if texte.endswith("--help"):
            return 0, self.aide
        if texte.endswith("--detient"):
            self.entree = kw.get("input")
            return self.rc, self.sortie
        return 127, ""

    def interroger(self, paires=(("GET", URL_A), ("GET", URL_B))):
        return cache_offline.detient_interroger(
            list(paires), str(self.binaire), "/casiers/essai"
        )

    def test_le_rendu_lit_les_six_champs(self):
        rendu = cache_offline.detient_rendu(self.sortie + "ligne mal formée\n")
        self.assertEqual(rendu[("GET", URL_A)]["verdict"], "garde")
        self.assertEqual(rendu[("GET", URL_B)]["garde_le"], "-")
        self.assertEqual(len(rendu), 2)

    def test_la_question_part_sur_lentree_standard(self):
        rendu = self.interroger()
        self.assertEqual(rendu[("GET", URL_A)]["verdict"], "garde")
        self.assertEqual(self.entree, f"GET {URL_A}\nGET {URL_B}\n")
        (argv,) = [c for c, _kw in self.lancees if c.endswith("--detient")]
        self.assertIn("--cache-dir /casiers/essai", argv)
        self.assertNotIn("sudo", argv)

    def test_un_binaire_sans_detient_rend_none(self):
        self.aide = "  -cache-dir string\n  -status\n"
        self.assertIsNone(self.interroger())
        self.assertFalse(
            any(c.endswith("--detient") for c, _kw in self.lancees),
            "la question est partie vers un binaire qui ne la connaît pas",
        )

    def test_un_echec_rend_none(self):
        self.rc = 2
        self.assertIsNone(self.interroger())

    def test_un_binaire_absent_rend_none_sans_rien_lancer(self):
        self.binaire.unlink()
        self.assertIsNone(self.interroger())
        self.assertEqual(self.lancees, [])

    def test_rien_a_demander_ne_lance_rien(self):
        self.assertEqual(self.interroger(()), {})
        self.assertEqual(self.lancees, [])


# ---------------------------------------------------------------------------
# F5 : prévenir avant la coupure, une fois, pour les deux motifs
# ---------------------------------------------------------------------------


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLAvertissementAvantLaCoupure(SansSysteme):
    """Même idiome que la suite absente : un premier F5 prévient, un second
    passe outre. Les deux motifs partagent UN avertissement — deux
    confirmations d'affilée apprendraient à les enchaîner sans lire."""

    MANQUE = {
        "nom": "vm-essai-hl",
        "age": 7200,
        "runs": ["r"],
        "manquants": [("GET", URL_A), ("GET", URL_B)],
        "git": ["https://example.com/o/d.git"],
        "jamais": [("POST", URL_POST), ("GET", URL_C)],
        "selon_journal": False,
    }

    def deployer(self, absentes, manques):
        import asyncio

        from textual.widgets import Checkbox, SelectionList

        from script.todo.qemu_deploy_form import run_deploy_form
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        mod = todo._qemu_import_module()
        todo._qemu_list_domains = lambda: []
        todo._qemu_branch_list = lambda: ["develop", "master"]
        with contextlib.redirect_stdout(io.StringIO()):
            ctx = dict(todo._qemu_form_context(mod), cache_offert=True)
        vu = {"notes": []}

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 70)) as pilote:
                await pilote.pause()
                liste = app.query_one("#f_catalog", SelectionList)
                liste.select(liste.options[0].value)
                app._recompute()
                await pilote.pause()
                app.query_one("#f_offline", Checkbox).value = True
                await pilote.pause()
                app.notify = lambda message, **kw: vu["notes"].append(message)
                app.action_deploy()
                vu["premier"] = app._result.get("spec")
                app.action_deploy()
                vu["second"] = app._result.get("spec")

        with mock.patch.object(
            cache_offline, "suites_absentes", lambda vms: absentes
        ), mock.patch.object(
            cache_offline, "manques_hors_ligne", lambda vms: manques
        ):
            asyncio.run(scenario())
        return vu

    def test_les_manques_bloquent_le_premier_f5(self):
        vu = self.deployer([], [self.MANQUE])
        self.assertIsNone(
            vu["premier"], "le déploiement est parti sans prévenir"
        )
        self.assertIsNotNone(vu["second"], "un second F5 ne passe pas outre")
        (note,) = vu["notes"]
        self.assertIn("vm-essai-hl", note)
        self.assertIn(f"{t('lacked at least')} 2 ", note)
        self.assertIn("2 h", note)
        self.assertIn(URL_A, note)

    def test_git_et_jamais_gardees_sont_nommes_pour_ce_quils_sont(self):
        """Une négociation git se comble par le miroir, pas par un rejeu ;
        et un GET que le cache ne garde pas n'est pas un POST."""
        vu = self.deployer([], [self.MANQUE])
        (note,) = vu["notes"]
        self.assertIn(
            "+1 "
            + t(
                "git repositories not mirrored: fill them from entry 5 of"
                " the cache menu"
            ),
            note,
        )
        self.assertIn(
            "+2 " + t("requests the cache never keeps:") + " GET, POST", note
        )
        self.assertNotIn(t("POST requests are never kept"), note)

    def test_sans_git_ni_jamais_rien_nest_ajoute(self):
        vu = self.deployer([], [dict(self.MANQUE, git=[], jamais=[])])
        (note,) = vu["notes"]
        self.assertNotIn(t("requests the cache never keeps:"), note)
        self.assertNotIn(t("git repositories not mirrored"), note)
        self.assertNotIn(" (+", note)

    def test_un_seul_avertissement_pour_les_deux(self):
        vu = self.deployer([("ubuntu", "26.04")], [self.MANQUE])
        self.assertIsNone(vu["premier"])
        self.assertIsNotNone(vu["second"])
        (note,) = vu["notes"]
        self.assertIn("ubuntu 26.04", note)
        self.assertIn(URL_A, note)

    def test_le_journal_seul_est_dit(self):
        vu = self.deployer([], [dict(self.MANQUE, selon_journal=True)])
        (note,) = vu["notes"]
        self.assertIn(
            t("according to the log: a purge can make it wrong"), note
        )

    def test_rien_a_dire_rien_ne_bloque(self):
        vu = self.deployer([], [])
        self.assertIsNotNone(
            vu["premier"], "un avertissement sans motif apprend à passer outre"
        )
        self.assertEqual(vu["notes"], [])

    def test_le_formulaire_ne_sait_toujours_pas_couper(self):
        src = QEMU_FORM.read_text(encoding="utf-8")
        for interdit in ("cut_cmd", "restore_cmd", "nft", "curl"):
            self.assertNotIn(interdit, src, interdit)


if __name__ == "__main__":
    unittest.main()
