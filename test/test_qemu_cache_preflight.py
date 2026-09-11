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
import re
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
from script.todo import qemu_cache_menu as menu  # noqa: E402
from script.todo.qemu_cache_menu import QemuCacheMenuMixin as M  # noqa: E402
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


class TestLesManquesRecents(SansSysteme):
    """Ce que le menu relit pour combler : les invités seuls, sans doublon."""

    def test_le_releve(self):
        maintenant = time.time()
        chemin = self.journal(
            [
                ligne(maintenant - 60, "offline-miss", URL_A),
                ligne(
                    maintenant - 30, "offline-miss", URL_A, client="192.0.2.11"
                ),
                ligne(
                    maintenant - 20, "offline-miss", URL_B, client="127.0.0.1"
                ),
                ligne(
                    maintenant - 10,
                    "offline-miss",
                    URL_C,
                    client="198.51.100.7",
                ),
                ligne(maintenant - 9 * 86400, "offline-miss", URL_POST),
                ligne(maintenant - 5, "stored", URL_A2),
            ]
        )
        releve = cache_offline.manques_recents(
            chemin, "192.0.2.0/24", maintenant - 7 * 86400
        )
        self.assertEqual(
            [(e["methode"], e["url"]) for e in releve], [("GET", URL_A)]
        )
        self.assertEqual(releve[0]["n"], 2)
        self.assertEqual(releve[0]["clients"], {IP, "192.0.2.11"})

    def test_sans_sous_reseau_la_boucle_locale_reste_ecartee(self):
        maintenant = time.time()
        chemin = self.journal(
            [ligne(maintenant - 20, "offline-miss", URL_B, client="127.0.0.1")]
        )
        self.assertEqual(cache_offline.manques_recents(chemin, "", 0.0), [])


# ---------------------------------------------------------------------------
# Le verdict de rejeu et la commande
# ---------------------------------------------------------------------------


def exclusions_du_go():
    """DefaultExclusions, relues dans la source Go comme le fait le test qui
    lit proxy.go."""
    src = (RACINE / "script" / "qemu_cache" / "mitm.go").read_text(
        encoding="utf-8"
    )
    bloc = re.search(r"var DefaultExclusions = \[\]string\{([^}]*)\}", src)
    return re.findall(r'"([^"]+)"', bloc.group(1))


class TestLeVerdictDeRejeu(unittest.TestCase):
    """Ce qui se rejoue, et ce qui ne doit JAMAIS l'être.

    Un hôte en tunnel rejoué depuis l'hôte revient dans le cache : sans
    détournement, la destination d'origine d'une connexion locale est
    l'écoute elle-même, et le tunnel s'y rappelle sans fin.
    """

    def test_get_et_head_sur_un_nom_se_rejouent(self):
        self.assertEqual(menu.verdict_de_rejeu("GET", URL_A), "rejouable")
        self.assertEqual(menu.verdict_de_rejeu("HEAD", URL_B), "rejouable")

    def test_un_post_ne_se_garde_jamais(self):
        for methode in ("POST", "PUT", "DELETE"):
            self.assertEqual(menu.verdict_de_rejeu(methode, URL_A), "jamais")

    def test_une_adresse_ip_en_https_est_un_tunnel(self):
        self.assertEqual(menu.verdict_de_rejeu("GET", URL_IP), "tunnel")

    def test_une_adresse_ip_en_http_ou_localhost_nest_pas_rejouee(self):
        for url in (
            "http://192.0.2.99/x",
            "http://localhost/x",
            "ftp://example.com/x",
        ):
            self.assertEqual(menu.verdict_de_rejeu("GET", url), "adresse", url)

    def test_les_exclusions_declarees_passent_en_tunnel(self):
        exclus = menu.exclusions_declarees(str(RACINE))
        self.assertEqual(sorted(exclus), sorted(exclusions_du_go()))
        self.assertGreater(len(exclus), 0)
        for hote in exclus:
            self.assertEqual(
                menu.verdict_de_rejeu("GET", f"https://{hote}/v1/x", exclus),
                "tunnel",
                hote,
            )

    def test_une_exclusion_en_suffixe_couvre_le_domaine(self):
        exclus = [".example.org"]
        self.assertEqual(
            menu.verdict_de_rejeu("GET", "https://a.example.org/x", exclus),
            "tunnel",
        )
        self.assertEqual(
            menu.verdict_de_rejeu(
                "GET", "https://example.org.invalid/x", exclus
            ),
            "rejouable",
        )

    def test_une_negociation_git_va_au_miroir(self):
        url = "https://example.com/o/d.git/info/refs?service=git-upload-pack"
        self.assertEqual(menu.verdict_de_rejeu("GET", url), "git")

    def test_les_chemins_git_suivent_le_go(self):
        src = (RACINE / "script" / "qemu_cache" / "classify.go").read_text(
            encoding="utf-8"
        )
        bloc = re.search(r"var gitSmartPaths = \[\]string\{([^}]*)\}", src)
        self.assertEqual(
            tuple(re.findall(r'"([^"]+)"', bloc.group(1))),
            menu.GIT_NEGOCIATION,
        )


class TestLaCommandeDeRejeu(unittest.TestCase):
    """La connexion va à l'écoute locale ; le nom d'hôte, lui, ne change pas.

    C'est ce qui donne au rejeu la clé qu'une VM produirait. L'autorité est
    APPROUVÉE, jamais contournée : « -k » ferait passer n'importe quoi pour le
    cache.
    """

    CA = "/var/lib/essai/ca.crt"

    def cmd(self, methode, url):
        return menu.rejeu_cmd(methode, url, "8898", "8899", self.CA)

    def test_http_passe_par_le_mandataire_du_cache(self):
        argv = self.cmd("GET", URL_B)
        self.assertEqual(argv[0], "curl")
        self.assertIn("-x", argv)
        self.assertEqual(argv[argv.index("-x") + 1], "http://127.0.0.1:8898")
        self.assertNotIn("--connect-to", argv)
        self.assertNotIn("-I", argv)
        self.assertEqual(argv[-1], URL_B)
        self.assertIn("--max-time", argv)

    def test_https_mene_la_connexion_a_lecoute_tls(self):
        argv = self.cmd("GET", URL_A)
        self.assertEqual(
            argv[argv.index("--connect-to") + 1], "::127.0.0.1:8899"
        )
        self.assertEqual(argv[argv.index("--cacert") + 1], self.CA)
        for interdit in ("-k", "--insecure", "-L", "-x"):
            self.assertNotIn(interdit, argv)
        self.assertEqual(argv[-1], URL_A)

    def test_head_se_rejoue_en_head(self):
        self.assertIn("-I", self.cmd("HEAD", URL_A))
        self.assertIn("-I", self.cmd("HEAD", URL_B))

    def test_le_curlrc_de_loperateur_est_ecarte(self):
        """curl n'honore « -q » qu'en tout premier argument. Ailleurs, un
        « proxy » du ~/.curlrc enverrait le rejeu https hors du cache, et
        un en-tête ou « compressed » changerait ce qui entre au magasin."""
        for methode, url in (("GET", URL_A), ("GET", URL_B), ("HEAD", URL_A)):
            argv = self.cmd(methode, url)
            self.assertEqual(argv[:2], ["curl", "-q"], argv)

    def test_la_redirection_se_lit_dans_le_dernier_bloc(self):
        entetes = (
            "HTTP/1.1 100 Continue\r\n\r\n"
            "HTTP/1.1 302 Found\r\nLocation: /depot/cible.tar.gz\r\n\r\n"
        )
        self.assertEqual(menu.statut_et_cible(entetes, URL_A), (302, URL_A2))
        self.assertEqual(
            menu.statut_et_cible("HTTP/2 200\r\n\r\n", URL_A), (200, "")
        )
        self.assertEqual(menu.statut_et_cible("", URL_A), (None, ""))


# ---------------------------------------------------------------------------
# L'entrée 9 : refuser sous la coupure, montrer, confirmer, rejouer, vérifier
# ---------------------------------------------------------------------------


class Faux(M):
    def __init__(self):
        self.execute = self
        self.executees = []

    def exec_command_live(self, cmd, **_kw):
        self.executees.append(cmd)


class TestLeComblement(SansSysteme):
    def setUp(self):
        super().setUp()
        self.binaire = self.dossier / "binaire"
        self.binaire.write_text("")
        conf = self.dossier / "env"
        conf.write_text(
            "EL_SUBNET=192.0.2.0/24\nEL_HTTP_PORT=8898\nEL_TLS_PORT=8899\n"
            f"EL_CACHE_DIR={self.dossier / 'casiers'}\nEL_EXCLUDE=\n"
        )
        maintenant = time.time()
        self.chemin = self.journal(
            [
                ligne(maintenant - 300, "offline-miss", URL_A),
                ligne(maintenant - 200, "offline-miss", URL_B),
                ligne(
                    maintenant - 150, "offline-miss", URL_POST, methode="POST"
                ),
                ligne(maintenant - 100, "offline-miss", URL_IP),
            ]
        )
        self.coupe = False
        self.guet = False
        self.actif = True
        self.rejoue = False
        for cible, valeur in (
            ("CACHE_BIN", str(self.binaire)),
            ("CACHE_CONF", str(conf)),
        ):
            p = mock.patch.object(menu, cible, valeur)
            p.start()
            self.addCleanup(p.stop)
        for nom, fonction in (
            ("_cache_journal", staticmethod(lambda: self.chemin)),
            ("_cache_actif", classmethod(lambda cls: self.actif)),
            ("_cache_amont_coupe", classmethod(lambda cls: self.coupe)),
            ("_cache_guet_actif", classmethod(lambda cls: self.guet)),
        ):
            p = mock.patch.object(M, nom, fonction)
            p.start()
            self.addCleanup(p.stop)

    def repondre(self, texte, kw):
        if texte.endswith("--help"):
            return 0, "  -detient\n"
        if texte.endswith("--detient"):
            lignes = []
            for question in (kw.get("input") or "").splitlines():
                methode, url = question.split(" ", 1)
                garde = self.rejoue and url in (URL_A2, URL_B)
                verdict = "garde" if garde else "absent"
                lignes.append(f"{verdict}\t200\t-\tvolatile\t{methode}\t{url}")
            return 0, "\n".join(lignes) + "\n"
        if texte.startswith("curl "):
            self.rejoue = True
            if texte.endswith(" " + URL_A):
                return 0, f"HTTP/1.1 302 Found\r\nLocation: {URL_A2}\r\n\r\n"
            return 0, "HTTP/1.1 200 OK\r\n\r\n"
        return 0, ""

    def combler(self, confirmer=True):
        sortie = io.StringIO()
        faux = Faux()
        with mock.patch(
            "click.confirm", return_value=confirmer
        ) as confirme, contextlib.redirect_stdout(sortie):
            faux._cache_combler()
        return sortie.getvalue(), confirme, faux

    def curls(self):
        return [(c, kw) for c, kw in self.lancees if c.startswith("curl ")]

    def test_sous_la_coupure_rien_ne_part(self):
        self.coupe = True
        texte, confirme, faux = self.combler()
        self.assertEqual(
            self.curls(), [], "un rejeu est parti sous la coupure"
        )
        confirme.assert_not_called()
        self.assertIn(cache_offline.restore_cmd(), texte)
        self.assertEqual(faux.executees, [])

    def test_sous_le_guet_rien_ne_part_et_le_geste_arrete_le_guet(self):
        """Le guet tient la coupure jusqu'à la fin de la dernière
        installation détachée. Le geste donné l'arrête ; retirer la table
        seule ferait finir ces installations en ligne et laisserait le guet
        tourner pour rien."""
        self.guet = True
        texte, confirme, faux = self.combler()
        self.assertEqual(self.curls(), [], "un rejeu est parti sous le guet")
        confirme.assert_not_called()
        self.assertIn(cache_offline.lever_maintenant_cmd(), texte)
        self.assertNotIn(cache_offline.restore_cmd(), texte)
        self.assertIn(
            t("Lifting it now makes those installations finish online."), texte
        )
        self.assertEqual(faux.executees, [])

    def test_une_coupure_illisible_fait_demander_non_par_defaut(self):
        """sudo exige un mot de passe : la coupure ne se lit pas, et la
        prendre pour absente ferait rejouer sous la coupure."""
        self.coupe = None
        texte, confirme, _f = self.combler(confirmer=False)
        self.assertEqual(self.curls(), [])
        confirme.assert_called_once()
        self.assertIs(confirme.call_args.kwargs.get("default"), False)
        self.assertIn(
            t(
                "Cannot tell whether the upstream is cut: reading nft needs a"
                " sudo password here."
            ),
            texte,
        )
        self.assertEqual(
            [c for c, _kw in self.lancees if c.endswith("--detient")],
            [],
            "le magasin a été interrogé avant la réponse",
        )

    def test_une_coupure_illisible_acceptee_rejoue(self):
        self.coupe = None
        _texte, confirme, _f = self.combler(confirmer=True)
        self.assertEqual(confirme.call_count, 2)
        self.assertNotEqual(self.curls(), [])

    def test_service_arrete_rien_ne_part(self):
        self.actif = False
        _texte, confirme, _f = self.combler()
        self.assertEqual(self.curls(), [])
        confirme.assert_not_called()

    def test_sans_binaire_rien_ne_part(self):
        self.binaire.unlink()
        _texte, confirme, _f = self.combler()
        self.assertEqual(self.lancees, [])
        confirme.assert_not_called()

    def test_refuser_la_confirmation_ne_lance_rien(self):
        texte, confirme, _f = self.combler(confirmer=False)
        confirme.assert_called_once()
        self.assertEqual(self.curls(), [])
        self.assertIn(URL_POST, texte, "le plan tait ce qui ne se rejoue pas")

    def test_le_rejeu_passe_par_le_cache_et_se_verifie(self):
        with mock.patch.dict(
            os.environ, {"https_proxy": "http://198.51.100.1:3128"}
        ):
            texte, _c, _f = self.combler()
        curls = self.curls()
        cibles = [c.rsplit(" ", 1)[-1] for c, _kw in curls]
        # Le manque le plus récent d'abord ; une redirection est suivie
        # aussitôt, avant l'adresse suivante.
        self.assertEqual(cibles, [URL_B, URL_A, URL_A2])
        for c, kw in curls:
            argv = c.split()
            self.assertTrue(
                ("--connect-to" in argv and "--cacert" in argv)
                or "http://127.0.0.1:8898" in argv,
                c,
            )
            for interdit in ("-k", "--insecure", "-L"):
                self.assertNotIn(interdit, argv)
            self.assertNotIn(
                "https_proxy", kw.get("env") or {}, "le mandataire hérité"
            )
        # Le rejeu et sa vérification tournent sans privilège. Le seul sudo
        # admis est la lecture non interactive du journal du service, qui
        # nomme les refus de tunnel appris.
        for c, _kw in self.lancees:
            self.assertNotIn("nft", c)
            if c.startswith("sudo"):
                self.assertTrue(c.startswith("sudo -n journalctl "), c)
        for c, _kw in curls:
            self.assertNotIn("sudo", c)
        self.assertNotIn(URL_POST, cibles)
        self.assertNotIn(URL_IP, cibles)
        self.assertIn(t("held"), texte)
        self.assertIn(t("not held"), texte)
        self.assertIn(
            t("User-Agent or Accept may keep another answer than the VM's."),
            texte,
        )


class TestLeMenuLitLaCoupureEtLeGuet(SansSysteme):
    """Ce que le menu du cache croit de la coupure et du guet.

    Trois lectures sans privilège ou sans mot de passe, chacune réduite à
    une marque que la commande écrit quand elle réussit : les messages de
    nft, de sudo et de systemctl se traduisent, et une inclusion de texte
    lit « inactive » comme « active ».
    """

    def setUp(self):
        super().setUp()
        self.sorties = {}

    def repondre(self, texte, kw):
        for motif, sortie in self.sorties.items():
            if motif in texte:
                return 0, sortie
        return 1, ""

    def test_la_coupure_a_trois_etats(self):
        posee = (
            "table inet x {\n  meta skuid 900 tcp dport { 80, 443 } drop\n}\n"
        )
        for sortie, attendu in (
            (f"{menu.NFT_LISIBLE}\n{posee}", True),
            (f"{menu.NFT_LISIBLE}\nError: la table n'existe pas\n", False),
            ("sudo: un mot de passe est nécessaire\n", None),
            ("", None),
        ):
            self.sorties = {"nft list": sortie}
            self.assertIs(M._cache_amont_coupe(), attendu, sortie)
        for c, _kw in self.lancees:
            self.assertNotRegex(c, r"sudo (?!-n )", "sudo peut demander")

    def test_le_guet_se_lit_sans_sudo(self):
        self.sorties = {cache_offline.guet_actif_cmd(): menu.GUET_ACTIF}
        self.assertTrue(M._cache_guet_actif())
        self.sorties = {}
        self.assertFalse(M._cache_guet_actif())
        for c, _kw in self.lancees:
            self.assertIn(cache_offline.guet_actif_cmd(), c)
            self.assertNotIn("sudo", c)

    def diagnostic(self, coupe, guet):
        binaire = self.dossier / "binaire"
        binaire.write_text("")
        sortie = io.StringIO()
        faux = Faux()
        with mock.patch.object(menu, "CACHE_BIN", str(binaire)), mock.patch(
            "script.todo.qemu_cache_menu.QemuCacheMenuMixin._cache_amont_coupe",
            classmethod(lambda cls: coupe),
        ), mock.patch(
            "script.todo.qemu_cache_menu.QemuCacheMenuMixin._cache_guet_actif",
            classmethod(lambda cls: guet),
        ), mock.patch(
            "script.todo.qemu_cache_menu.QemuCacheMenuMixin._cache_par_machine",
            return_value=[],
        ), mock.patch(
            "script.todo.qemu_cache_menu.QemuCacheMenuMixin._cache_compte_issues",
            return_value={},
        ), mock.patch(
            "script.todo.qemu_cache_menu.QemuCacheMenuMixin._cache_bypass_lire",
            return_value=[],
        ), contextlib.redirect_stdout(
            sortie
        ):
            faux._cache_diagnostic()
        return sortie.getvalue()

    def test_sous_le_guet_le_diagnostic_donne_larret_du_guet(self):
        """Donner le retrait de la table ferait finir en ligne les
        installations qui tournent, et le guet resterait sans rien à
        lever."""
        for coupe in (True, None):
            texte = self.diagnostic(coupe, guet=True)
            self.assertIn(cache_offline.lever_maintenant_cmd(), texte)
            self.assertNotIn(cache_offline.restore_cmd(), texte)
            self.assertIn(
                t("held until its last installation ends (12 h at most)."),
                texte,
            )

    def test_sans_guet_le_diagnostic_donne_le_retrait(self):
        texte = self.diagnostic(True, guet=False)
        self.assertIn(cache_offline.restore_cmd(), texte)
        self.assertNotIn(cache_offline.lever_maintenant_cmd(), texte)

    def test_un_guet_sans_coupure_est_nomme(self):
        texte = self.diagnostic(False, guet=True)
        self.assertIn(
            t("The lift watcher still runs, with no cut left to lift."), texte
        )
        self.assertIn(cache_offline.lever_maintenant_cmd(), texte)

    def test_une_coupure_illisible_est_dite_sans_alarme(self):
        texte = self.diagnostic(None, guet=False)
        self.assertNotIn(cache_offline.restore_cmd(), texte)
        self.assertNotIn(
            t("Upstream CUT: the cache can pull nothing from the internet"),
            texte,
        )
        self.assertIn(
            t(
                "Cannot tell whether the upstream is cut: reading nft needs a"
                " sudo password here."
            ),
            texte,
        )


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
