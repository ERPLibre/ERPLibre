#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Tout démon git que le dépôt sait lancer écoute la boucle locale.

Le protocole git n'authentifie personne : pas de compte, pas de mot de passe,
pas de trace d'auteur. Sans « --listen », `git daemon` se lie à TOUTES les
interfaces, et « --export-all » offre alors chaque dépôt sous le chemin de
base, en lecture, à ce qui atteint le port.

Les appelants consomment tous « git://127.0.0.1:9418/ » : leur usage est déjà
local, seule leur écoute ne l'était pas. Poser le drapeau ne retire rien.

L'épreuve BALAIE le dépôt plutôt que d'énumérer des fichiers : un script écrit
demain se fait prendre, une liste écrite en dur non. La documentation entre
dans le balayage — un bloc de code se copie-colle, et enseigner la forme large
la répand.

Un balayage de texte ne voit pas une ligne assemblée morceau par morceau :
`git_local_server.py` construit la sienne dans `daemon_command`, qui est donc
éprouvée ici par ce qu'elle REND, à travers le même prédicat.
"""

import importlib.util
import os
import re
import subprocess
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

# « git daemon » et ses arguments jusqu'au bout de la ligne. Le préfixe
# refuse un « # » avant : un commentaire décrit, il ne lance pas.
LANCEMENT = re.compile(r"^[^#\n]*\bgit\s+daemon\b(?P<args>[^\n]*)", re.M)

# Ce qui distingue un LANCEMENT d'une phrase qui cite la commande. Une
# occurrence sans aucun de ces deux arguments ne sert aucun dépôt.
SERT_UN_DEPOT = ("--base-path", "--export-all")

# Ce qui vaut boucle locale. Un nom d'hôte n'en est pas : il se résout où le
# résolveur veut, et « localhost » pointant ailleurs est un cas connu.
BOUCLE = ("127.0.0.1", "::1")


def _git_local_server():
    chemin = os.path.join(RACINE, "script", "git", "git_local_server.py")
    spec = importlib.util.spec_from_file_location("gls_ecoute", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fichiers_suivis():
    """Les fichiers que git suit, sans le répertoire privé."""
    sortie = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=RACINE,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [
        chemin
        for chemin in sortie.split("\0")
        if chemin and not chemin.startswith("private/")
    ]


def lancements():
    """(chemin, arguments) pour chaque démon que le dépôt sait lancer.

    Saute `test/` : les épreuves citent la commande pour la décrire, et se
    prendraient elles-mêmes pour des lancements.
    """
    trouves = []
    for chemin in fichiers_suivis():
        if chemin.startswith("test/"):
            continue
        try:
            with open(os.path.join(RACINE, chemin), encoding="utf-8") as f:
                texte = f.read()
        except (UnicodeDecodeError, IsADirectoryError, OSError):
            continue
        for trouve in LANCEMENT.finditer(texte):
            args = trouve.group("args")
            if any(marque in args for marque in SERT_UN_DEPOT):
                trouves.append((chemin, args))
    return trouves


class ContratDuDemon:
    """Les trois exigences, appliquées aux mêmes arguments d'où qu'ils
    viennent — d'un fichier lu ou d'un constructeur appelé."""

    def verifier(self, ou, args):
        with self.subTest(source=ou, exigence="adresse nommée"):
            self.assertIn("--listen=", args, args.strip())
        with self.subTest(source=ou, exigence="adresse locale"):
            adresse = re.search(r"--listen=(\S+)", args)
            self.assertIsNotNone(adresse, args.strip())
            self.assertIn(adresse.group(1), BOUCLE, f"{ou} : {args.strip()}")
        with self.subTest(source=ou, exigence="pas d'écriture anonyme"):
            self.assertNotIn("receive-pack", args)


class TestCeQueLeDepotSaitLancer(unittest.TestCase, ContratDuDemon):
    def setUp(self):
        self.lancements = lancements()

    def test_the_sweep_finds_something(self):
        """Un motif cassé rendrait zéro lancement, et toutes les épreuves
        seraient vertes sans avoir rien lu."""
        self.assertTrue(self.lancements, "aucun « git daemon » lu")

    def test_the_sweep_reaches_the_shell_the_docker_and_the_docs(self):
        """Contrôle positif du périmètre : rétrécir le balayage à un seul
        répertoire le rendrait vert en cessant de regarder."""
        vus = {chemin for chemin, _ in self.lancements}
        for attendu in ("script/manifest/", "docker/", "doc/"):
            with self.subTest(endroit=attendu):
                self.assertTrue(
                    any(chemin.startswith(attendu) for chemin in vus),
                    sorted(vus),
                )

    def test_every_daemon_binds_the_loopback_and_refuses_writing(self):
        for chemin, args in self.lancements:
            self.verifier(chemin, args)


class TestCeQueLeConstructeurAssemble(unittest.TestCase, ContratDuDemon):
    """La ligne bâtie en Python n'est lisible qu'une fois rendue."""

    def test_what_it_renders_by_default_obeys_the_same_contract(self):
        module = _git_local_server()
        self.verifier(
            "daemon_command()", module.daemon_command("/depots-de-banc", 9418)
        )


if __name__ == "__main__":
    unittest.main()
