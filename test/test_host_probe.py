#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Quatre pannes, et non une : chacune se corrige d'un côté différent.

« La machine ne répond pas » envoie vérifier le réseau. « Elle répond mais le
produit n'y est pas » envoie l'installer. Les confondre en un seul message
envoie chercher au mauvais endroit — c'est le défaut que ce module existe
pour empêcher, et ces épreuves sont ce qui le tient.

Rien ici ne touche à une machine : la commande à distance est un paramètre,
donc la décision se vérifie entièrement depuis une station.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.remote import host_probe as P  # noqa: E402

HOTE = {"target": "appliance", "jump": ""}
SONDE = "produit --version"


def version_de(sortie):
    """Analyseur de banc : « produit 1.2 » -> « 1.2 »."""
    for ligne in (sortie or "").splitlines():
        if ligne.startswith("produit "):
            return ligne.split()[1]
    return ""


class RunFaux:
    """Un exécuteur de banc : une réponse par commande, et un journal."""

    def __init__(self, **reponses):
        self.reponses = reponses
        self.appels = []

    def __call__(self, host, remote, timeout=0):
        self.appels.append(remote)
        for motif, reponse in self.reponses.items():
            if motif.replace("_", " ") in remote or motif in remote:
                return reponse
        return 127, "command not found"


class TestLesQuatreVerdicts(unittest.TestCase):
    def test_a_healthy_root_host_is_ok_without_sudo(self):
        run = RunFaux(produit=(0, "produit 9.2\n"), id=(0, "0\n"))
        verdict = P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertEqual(P.OK, verdict.kind)
        self.assertEqual("9.2", verdict.version)
        self.assertEqual("", verdict.sudo)

    def test_a_non_root_host_with_passwordless_sudo_gets_the_prefix(self):
        run = RunFaux(
            produit=(0, "produit 9.2\n"), id=(0, "1000\n"), sudo=(0, "")
        )
        verdict = P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertEqual(P.OK, verdict.kind)
        self.assertEqual("sudo ", verdict.sudo)

    def test_a_sudo_that_asks_for_a_password_is_refused(self):
        """Il bloquerait chaque commande sur une invite que nul ne voit."""
        run = RunFaux(
            produit=(0, "produit 9.2\n"),
            id=(0, "1000\n"),
            sudo=(1, "sudo: a password is required"),
        )
        verdict = P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertEqual(P.NEEDS_ROOT, verdict.kind)
        self.assertEqual("9.2", verdict.version)

    def test_reachable_without_the_product_is_not_unreachable(self):
        """LE défaut que ce module empêche : deux pannes, deux côtés."""
        run = RunFaux(
            produit=(127, "bash: produit: command not found"),
            true=(0, ""),
        )
        verdict = P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertEqual(P.PRODUCT_ABSENT, verdict.kind)

    def test_an_unreachable_host_says_so(self):
        run = RunFaux(
            produit=(255, "ssh: connect to host appliance port 22: timeout"),
            true=(255, "ssh: connect to host appliance port 22: timeout"),
        )
        verdict = P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertEqual(P.UNREACHABLE, verdict.kind)

    def test_an_unknown_host_key_is_an_agreement_not_a_failure(self):
        run = RunFaux(produit=(255, "Host key verification failed."))
        verdict = P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertEqual(P.HOSTKEY, verdict.kind)
        # Et le test de vie n'a PAS été tenté : il dirait « injoignable »
        # d'une machine qui n'attend qu'un accord.
        self.assertNotIn("true", run.appels)

    def test_every_verdict_is_in_the_closed_vocabulary(self):
        self.assertTrue(P.VERDICTS, "vocabulaire vidé : rien n'est prouvé")
        cas = (
            RunFaux(produit=(0, "produit 9.2\n"), id=(0, "0\n")),
            RunFaux(produit=(127, "nope"), true=(0, "")),
            RunFaux(produit=(255, "timeout"), true=(255, "timeout")),
            RunFaux(produit=(255, "Host key verification failed.")),
        )
        for run in cas:
            self.assertIn(
                P.diagnose(HOTE, SONDE, version_de, run=run).kind, P.VERDICTS
            )


class TestCeQueLeVerdictPorte(unittest.TestCase):
    def test_the_detail_is_what_the_probe_said(self):
        """« command not found » est la preuve utile ; « ok » ne l'est pas."""
        run = RunFaux(
            produit=(127, "bash: produit: command not found"),
            true=(0, "ok"),
        )
        verdict = P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertIn("command not found", verdict.detail)
        self.assertNotIn("ok", verdict.detail)

    def test_the_raw_output_is_kept_whole(self):
        """Le redemander coûterait un aller-retour pour une réponse acquise."""
        sortie = "produit 9.2\nnoyau 7.0.14-12-pve\n"
        run = RunFaux(produit=(0, sortie), id=(0, "0\n"))
        self.assertEqual(
            sortie, P.diagnose(HOTE, SONDE, version_de, run=run).raw
        )

    def test_ssh_noise_never_reaches_the_detail(self):
        run = RunFaux(
            produit=(
                127,
                "Warning: Permanently added 'x' (ED25519) to known hosts.\n"
                "bash: produit: command not found",
            ),
            true=(0, ""),
        )
        verdict = P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertNotIn("Permanently added", verdict.detail)
        self.assertIn("command not found", verdict.detail)


class TestLeNombreDAllersRetours(unittest.TestCase):
    """Chaque aller-retour est une seconde d'attente devant un menu."""

    def test_a_healthy_root_host_costs_two(self):
        run = RunFaux(produit=(0, "produit 9.2\n"), id=(0, "0\n"))
        P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertEqual(2, len(run.appels), run.appels)

    def test_the_liveness_test_runs_only_when_the_product_is_missing(self):
        run = RunFaux(produit=(0, "produit 9.2\n"), id=(0, "0\n"))
        P.diagnose(HOTE, SONDE, version_de, run=run)
        self.assertNotIn("true", run.appels)


class TestElleNAfficheRien(unittest.TestCase):
    """La décision se vérifie sans terminal ; les phrases sont au menu."""

    def test_the_module_never_prints(self):
        import ast

        chemin = os.path.join(RACINE, "script", "remote", "host_probe.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        noms = [
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertTrue(noms, "aucun appel lu : rien n'est prouvé")
        self.assertNotIn("print", noms)

    def test_it_names_no_product(self):
        chemin = os.path.join(RACINE, "script", "remote", "host_probe.py")
        with open(chemin, encoding="utf-8") as handle:
            source = handle.read().lower()
        for produit in ("proxmox", "pveversion", "truenas"):
            self.assertNotIn(produit, source)


if __name__ == "__main__":
    unittest.main()
