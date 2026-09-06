#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Quel backend de VM cette machine emploie, et ce que la préférence promet.

Elle est INDICATIVE : elle préselectionne et elle informe, elle ne route
rien. Une préférence qui aiguillerait le déploiement enverrait une
description de machine dans un chemin qui ne sait pas la lire — le chemin
local est libvirt de bout en bout.

La résolution est PURE et reçoit l'hôte en paramètre : c'est ce qui permet
de l'éprouver pour un système qu'on n'a pas sous la main.

AUCUNE épreuve n'écrit de préférence : `todo_prefs._path()` fait un `mkdir`
sur le vrai répertoire personnel, et une épreuve qui appellerait `set()`
écrirait dans les réglages de la personne qui la lance.
"""

import ast
import os
import re
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo import host_os as H  # noqa: E402
from script.todo import todo_prefs  # noqa: E402
from script.todo import vm_backend_choice as C  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS  # noqa: E402
from script.vm import backend as VM  # noqa: E402


class TestLaResolution(unittest.TestCase):
    def test_an_explicit_choice_is_honoured_everywhere(self):
        """Choisir, c'est décider — même là où le choix n'apporte rien."""
        for backend in (VM.LIBVIRT, VM.PVE, VM.LIMA):
            for hote in (H.DEBIAN, H.MACOS):
                with self.subTest(backend=backend, hote=hote):
                    self.assertEqual(
                        backend, C.effective(backend, hote, limactl=True)
                    )

    def test_auto_is_libvirt_on_a_linux_host(self):
        for hote in (H.DEBIAN, H.ARCH, H.PROXMOX, H.UNKNOWN):
            with self.subTest(hote=hote):
                self.assertEqual(VM.LIBVIRT, C.effective(C.AUTO, hote))

    def test_auto_is_the_instance_tool_where_libvirt_cannot_exist(self):
        self.assertEqual(VM.LIMA, C.effective(C.AUTO, H.MACOS, limactl=True))

    def test_auto_falls_back_on_the_remote_host_when_the_tool_is_absent(self):
        """C'est ce que le menu local dit déjà en se retirant."""
        self.assertEqual(VM.PVE, C.effective(C.AUTO, H.MACOS, limactl=False))

    def test_an_unknown_preference_resolves_as_auto(self):
        """Figer un nom que personne ne sait servir vaut moins que
        retomber sur la règle du système."""
        for valeur in ("", None, "vmware", "AUTO ", "   "):
            with self.subTest(valeur=valeur):
                self.assertEqual(VM.LIBVIRT, C.effective(valeur, H.DEBIAN))

    def test_the_case_of_an_explicit_choice_does_not_matter(self):
        self.assertEqual(VM.LIMA, C.effective("LIMA", H.DEBIAN))

    def test_every_resolution_names_a_real_backend(self):
        for pref in C.CHOIX + ("inventée",):
            for hote in (H.DEBIAN, H.MACOS):
                for outil in (True, False):
                    with self.subTest(pref=pref, hote=hote, outil=outil):
                        self.assertIn(
                            C.effective(pref, hote, outil), VM.BACKENDS
                        )


class TestLeConseil(unittest.TestCase):
    """Un conseil, et non un refus : le choix FONCTIONNE, il n'apporte
    simplement rien. Cacher l'entrée répondrait à la question par son
    absence."""

    def test_it_says_what_the_new_backend_is_worth_on_linux(self):
        self.assertTrue(C.conseil(VM.LIMA, H.DEBIAN))

    def test_it_says_nothing_where_the_choice_is_the_right_one(self):
        """Contrôle positif : conseiller partout serait du bruit."""
        self.assertEqual("", C.conseil(VM.LIMA, H.MACOS))
        self.assertEqual("", C.conseil(VM.LIBVIRT, H.DEBIAN))
        self.assertEqual("", C.conseil(VM.PVE, H.DEBIAN))

    def test_it_says_why_the_local_one_is_absent_from_macos(self):
        self.assertTrue(C.conseil(VM.LIBVIRT, H.MACOS))

    def test_every_advice_is_translated(self):
        """Une clé absente s'affiche en anglais au milieu d'une phrase
        française."""
        for backend in VM.BACKENDS:
            for hote in (H.DEBIAN, H.MACOS):
                cle = C.conseil(backend, hote)
                if cle:
                    with self.subTest(backend=backend, hote=hote):
                        self.assertIn(cle, TRANSLATIONS)


class TestLaPreference(unittest.TestCase):
    def test_the_key_exists_and_defaults_to_auto(self):
        self.assertEqual(C.AUTO, todo_prefs.DEFAULTS["vm_backend"])

    def test_the_offered_values_are_exactly_the_known_ones(self):
        """Une valeur proposée que la résolution ignore serait une main
        qu'on ne peut pas jouer."""
        from script.todo.todo import TODO

        offertes = [v for v, _label in TODO._PREF_CHOICES["vm_backend"][1]]
        self.assertEqual(list(C.CHOIX), offertes)

    def test_every_label_is_translated(self):
        from script.todo.todo import TODO

        titre, options = TODO._PREF_CHOICES["vm_backend"]
        self.assertIn(titre, TRANSLATIONS)
        for _valeur, label in options:
            with self.subTest(label=label):
                self.assertIn(label, TRANSLATIONS)

    def test_the_unproven_backend_says_so_in_words(self):
        """Dans cet écran l'étoile marque la valeur COURANTE : une seconde
        étoile s'y lirait « c'est celle-là qui est active »."""
        from script.todo.todo import TODO

        libelles = dict(
            (v, lab) for v, lab in TODO._PREF_CHOICES["vm_backend"][1]
        )
        self.assertFalse(VM.is_proven(VM.LIMA))
        self.assertNotIn("*", libelles[VM.LIMA])
        self.assertRegex(libelles[VM.LIMA], r"(?i)never|jamais")


class TestLesRangsDeLEcranDeConfiguration(unittest.TestCase):
    """Cet écran n'avait AUCUN garde.

    Le socle qui garde les autres menus n'accepte qu'un libellé littéral
    `t("…")` ; ceux-ci sont des f-strings qui affichent la valeur courante,
    et il n'en lit donc presque rien. Une entrée ajoutée y décalait la
    remise à zéro sans que quoi que ce soit ne proteste — et remettre à zéro
    n'est pas ce qu'on voulait quand on visait le rang d'avant.
    """

    def corps(self):
        source = open(
            os.path.join(RACINE, "script", "todo", "todo.py"),
            encoding="utf-8",
        ).read()
        debut = source.index("    def prompt_configuration(self):")
        # Le membre SUIVANT borne la lecture, quel qu'il soit : nommer un
        # membre lointain avalerait des écrans entiers, et le compte
        # porterait alors sur tout autre chose sans que rien ne le dise.
        fin = source.index("\n    def ", debut + 1)
        return source[debut:fin]

    def test_the_body_was_actually_read(self):
        """Sur un corps vide, tout ce qui suit passe."""
        self.assertIn("Reset all preferences", self.corps())

    def test_as_many_entries_as_dispatches(self):
        corps = self.corps()
        entrees = corps.count('"prompt_description"')
        rangs = re.findall(r'elif status == "(\d+)":', corps)
        self.assertEqual(entrees, len(rangs))

    def test_the_ranks_run_from_one_without_a_hole(self):
        rangs = re.findall(r'elif status == "(\d+)":', self.corps())
        self.assertEqual([str(n) for n in range(1, len(rangs) + 1)], rangs)

    def test_the_reset_is_the_last_rank(self):
        """C'est elle qui se décale quand on ajoute une entrée, et elle
        efface tout."""
        corps = self.corps()
        rangs = re.findall(r'elif status == "(\d+)":', corps)
        dernier = f'elif status == "{rangs[-1]}":'
        apres = corps[corps.index(dernier) :]
        self.assertIn("todo_prefs.reset()", apres.split("elif")[1])

    def test_no_section_is_counted_as_a_command(self):
        """Un titre de section ne consomme pas de numéro."""
        self.assertGreaterEqual(self.corps().count('"section"'), 2)


class TestElleNEcritAucunePreference(unittest.TestCase):
    def test_the_module_never_writes(self):
        chemin = os.path.join(RACINE, "script", "todo", "vm_backend_choice.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        appels = [
            noeud.func.attr
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
        ]
        for interdit in ("set", "reset", "write_text"):
            self.assertNotIn(interdit, appels)


if __name__ == "__main__":
    unittest.main()
