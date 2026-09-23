#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le paquet des postures ne connaît ni menu, ni écran, ni hyperviseur.

Le registre porte déjà sa garde, et elle ne vaut que pour lui. Le paquet
n'en avait aucune, ce qui laisse un trou : le module SUIVANT importe ce
qu'il veut tant que personne n'y pense — et le paquet est sur le point d'en
recevoir plusieurs.

Ce qu'elle protège n'est pas une élégance. Une posture qui importerait la
couche menu deviendrait inéprouvable sans terminal. Une qui nommerait un
hyperviseur ferait de la politique réseau une propriété du backend, alors
que plusieurs consommateurs la lisent et qu'elle n'appartient à aucun.

Une qui ouvrirait un fichier ferait deux choses de plus, toutes deux
mauvaises : elle lirait la donnée du site — les adresses vivent dans la
configuration privée, pas ici — et un rendu qui écrit lui-même perd
l'atomicité, le mode et la trace que l'écriture du dépôt tient déjà.
"""

import ast
import os
import re
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

PAQUET = os.path.join(RACINE, "script", "posture")

# Ce que le paquet a le droit d'importer, en plus de la bibliothèque
# standard et de lui-même. Le contrôle des valeurs est partagé avec tout le
# dépôt EXPRÈS : un contrôle recopié diverge de sa copie au premier
# correctif, et celui-ci est déjà en service ailleurs.
DEPENDANCES_PERMISES = ("script.lib_valid",)

# Les appels qu'aucun module ne fait. `print` et `input` décideraient de la
# langue et du flux à la place de l'écran ; `t` ferait descendre l'i18n dans
# une couche qui rend des jetons, pas des phrases ; `open` ferait entrer la
# donnée du site ou sortir un fichier sans atomicité ni trace.
APPELS_INTERDITS = ("print", "input", "t", "open")

# Un hyperviseur nommé ici, et la politique réseau devient une propriété du
# backend. Le registre porte la même liste pour lui seul, avec son propre
# message ; celle-ci vaut pour ce qui n'est pas encore écrit.
HYPERVISEURS = ("qemu", "proxmox", "lima", "virsh", "pveversion", "libvirt")

# Une adresse est une donnée de site : elle vit dans la configuration
# privée, que le dépôt public ne suit pas. « 0.0.0.0 » est la seule
# exception, quel que soit le préfixe qui la suit : elle ne désigne aucune
# machine, et le paquet la nomme justement pour la refuser.
ADRESSE_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
ADRESSES_PERMISES = ("0.0.0.0",)


def modules():
    return sorted(
        os.path.join(PAQUET, nom)
        for nom in os.listdir(PAQUET)
        if nom.endswith(".py")
    )


def arbre_de(chemin):
    with open(chemin, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def racines_importees(chemin):
    vues = set()
    for noeud in ast.walk(arbre_de(chemin)):
        if isinstance(noeud, ast.Import):
            vues.update(alias.name for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            vues.add(noeud.module)
    return vues


def appels_nommes(chemin):
    return [
        noeud.func.id
        for noeud in ast.walk(arbre_de(chemin))
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
    ]


class TestLePaquetNeDependDeRien(unittest.TestCase):
    def test_there_is_something_to_check(self):
        """Sur un paquet vide, toutes les épreuves d'à côté passent."""
        self.assertGreaterEqual(len(modules()), 3)

    def test_no_module_imports_outside_the_standard_library(self):
        for chemin in modules():
            with self.subTest(module=os.path.basename(chemin)):
                for nom in racines_importees(chemin):
                    if nom.startswith("script.posture"):
                        continue
                    if nom in DEPENDANCES_PERMISES:
                        continue
                    self.assertIn(
                        nom.split(".")[0],
                        sys.stdlib_module_names,
                        f"{os.path.basename(chemin)} importe « {nom} »",
                    )

    def test_no_module_reaches_into_the_menu_layer(self):
        """Le nommer À PART de la garde générale : c'est l'import qui
        arriverait en premier — une posture a besoin d'une phrase, l'i18n
        est à portée — et celui dont la conséquence est la pire, une
        politique réseau qu'on ne peut plus éprouver sans terminal."""
        for chemin in modules():
            with self.subTest(module=os.path.basename(chemin)):
                for nom in racines_importees(chemin):
                    self.assertFalse(
                        nom.startswith("script.todo"),
                        f"{os.path.basename(chemin)} importe « {nom} »",
                    )


class TestLePaquetNeParleNiNEcrit(unittest.TestCase):
    def test_no_module_makes_a_forbidden_call(self):
        self.assertTrue(APPELS_INTERDITS, "liste vidée : rien n'est prouvé")
        for chemin in modules():
            vus = appels_nommes(chemin)
            for interdit in APPELS_INTERDITS:
                with self.subTest(
                    module=os.path.basename(chemin), appel=interdit
                ):
                    self.assertNotIn(interdit, vus)

    def test_the_reading_of_the_calls_actually_sees_them(self):
        """Contrôle positif : un lecteur qui ne rend jamais rien ferait
        passer l'épreuve d'à côté sur n'importe quel module."""
        vus = set()
        for chemin in modules():
            vus.update(appels_nommes(chemin))
        self.assertTrue(vus, "aucun appel lu dans tout le paquet")


class TestLePaquetNeSaitRienDeLHyperviseur(unittest.TestCase):
    def test_no_module_names_one(self):
        self.assertTrue(HYPERVISEURS, "liste vidée : rien n'est prouvé")
        for chemin in modules():
            with open(chemin, encoding="utf-8") as handle:
                source = handle.read().lower()
            for mot in HYPERVISEURS:
                with self.subTest(module=os.path.basename(chemin), mot=mot):
                    # Message court : l'échec par défaut recracherait le
                    # fichier entier.
                    self.assertNotIn(mot, source, f"« {mot} » nommé")


class TestAucuneAdresseNeSyRange(unittest.TestCase):
    """Le tableau de symboles est l'endroit où une adresse veut atterrir."""

    def test_no_module_carries_an_address(self):
        for chemin in modules():
            with self.subTest(module=os.path.basename(chemin)):
                with open(chemin, encoding="utf-8") as handle:
                    source = handle.read()
                for trouve in ADRESSE_RE.finditer(source):
                    if trouve.group() in ADRESSES_PERMISES:
                        continue
                    self.fail(f"adresse « {trouve.group()} » dans le paquet")

    def test_the_pattern_recognises_one(self):
        """Contrôle positif : une expression qui ne trouve jamais rien
        ferait passer l'épreuve d'à côté sur n'importe quel fichier."""
        self.assertTrue(ADRESSE_RE.search("route 198.51.100.4 refusée"))
        self.assertFalse(ADRESSE_RE.search("Odoo 18.0 sous Python 3.12.10"))


if __name__ == "__main__":
    unittest.main()
