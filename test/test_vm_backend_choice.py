#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Quel backend de VM cette machine emploie, et ce que la préférence promet.

ELLE ROUTE. La valeur résolue entre dans la description de machine, et le
chemin local — libvirt de bout en bout — refuse tout ce qui n'est pas
libvirt. Le refus est juste : y laisser passer une autre description
produirait un déploiement libvirt sous un faux nom. C'est l'écran qui
doit le dire, et il a longtemps promis l'inverse.

La résolution est PURE et reçoit l'hôte en paramètre : c'est ce qui permet
de l'éprouver pour un système qu'on n'a pas sous la main.

AUCUNE épreuve n'écrit de préférence : `todo_prefs._path()` fait un `mkdir`
sur le vrai répertoire personnel, et une épreuve qui appellerait `set()`
écrirait dans les réglages de la personne qui la lance.
"""

import ast
import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

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

    def test_no_label_carries_a_star_of_its_own(self):
        """Dans cet écran l'étoile marque la valeur COURANTE : une seconde
        étoile s'y lirait « c'est celle-là qui est active »."""
        from script.todo.todo import TODO

        libelles = dict(
            (v, lab) for v, lab in TODO._PREF_CHOICES["vm_backend"][1]
        )
        self.assertNotIn("*", libelles[VM.LIMA])
        # Le libellé ne dit plus « jamais confronté » : le backend l'a été,
        # et un écran qui l'affirmerait encore enverrait choisir libvirt
        # pour une raison qui n'existe plus.
        self.assertNotRegex(libelles[VM.LIMA], r"(?i)never|jamais")


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


class TestLEcranDesBackends(unittest.TestCase):
    """Deux marques, et elles ne disent pas la même chose : « ← » ce qui est
    CHOISI, l'étoile ce qui n'a jamais été confronté au vrai outil. Une
    seule marque pour les deux ferait lire « non éprouvé » sur le backend
    actif."""

    def lignes(self, pref, hote, limactl=False):
        return C.render(pref, hote, limactl)

    def test_every_offered_value_gets_a_line(self):
        lignes = self.lignes(C.AUTO, H.ARCH)
        for rang in range(1, len(C.CHOIX) + 1):
            with self.subTest(rang=rang):
                self.assertTrue(
                    any(l.startswith(f"  [{rang}] ") for l in lignes)
                )

    def test_the_chosen_one_is_marked_and_the_others_are_not(self):
        lignes = self.lignes(VM.LIMA, H.ARCH)
        marquees = [l for l in lignes if "←" in l]
        self.assertEqual(1, len(marquees))
        self.assertIn("Lima", marquees[0])

    def test_an_unproven_one_carries_the_star_and_the_others_do_not(self):
        """L'épreuve porte sur le MÉCANISME, pas sur l'état d'un backend.

        Les trois ont désormais tourné contre leur outil ; la marquer sur
        celui qui l'est encore ferait tomber cette épreuve le jour où il
        est confronté, et le prochain backend arriverait sans garde. Un
        backend non éprouvé est donc POSÉ ici.
        """
        with patch.dict(VM.PROVEN, {VM.LIMA: False}):
            lignes = self.lignes(C.AUTO, H.ARCH)
        etoilees = [
            l
            for l in lignes
            if l.startswith("  [") and l.rstrip().endswith("*")
        ]
        self.assertEqual(1, len(etoilees))
        self.assertIn("Lima", etoilees[0])

    def test_the_star_never_lands_on_a_proven_backend(self):
        """C'est la confusion que les deux marques existent pour éviter."""
        for pref in C.CHOIX:
            for hote in (H.ARCH, H.MACOS):
                with self.subTest(pref=pref, hote=hote):
                    for ligne in self.lignes(pref, hote, True):
                        if "libvirt/QEMU" in ligne or "Proxmox VE" in ligne:
                            self.assertNotIn("*", ligne)

    def test_the_legend_appears_only_when_a_star_does(self):
        """Une légende sans étoile est du bruit, et une étoile sans légende
        est une marque que personne ne sait lire. L'épreuve est
        STRUCTURELLE : chercher le texte reviendrait à épingler la langue
        dans laquelle il s'affiche."""
        with patch.dict(VM.PROVEN, {VM.LIMA: False}):
            lignes = self.lignes(C.AUTO, H.ARCH)
        self.assertTrue(any(l.rstrip().endswith("*") for l in lignes))
        self.assertTrue(any(l.startswith("  * ") for l in lignes))

    def test_with_everything_proven_there_is_no_legend(self):
        """Ce que le dessin annonçait : le jour où tout est éprouvé, la
        légende part d'elle-même, aucun écran à retoucher.

        C'est l'état RÉEL du dépôt, et non un cas posé : rien n'est
        bouchonné ici, ce qui vérifie du même coup que la table le dit.
        """
        self.assertEqual([], [n for n in VM.BACKENDS if not VM.is_proven(n)])
        lignes = self.lignes(C.AUTO, H.ARCH)
        self.assertFalse(any(l.rstrip().endswith("*") for l in lignes))
        self.assertFalse(any(l.startswith("  * ") for l in lignes))

    def test_the_automatic_line_shows_what_automatic_gives(self):
        """Et NON ce que la préférence courante donne : sur une machine où
        l'on a choisi autre chose, les deux diffèrent, et afficher le second
        ferait croire qu'automatique mène là aussi."""
        lignes = self.lignes(VM.LIMA, H.ARCH)
        auto = next(l for l in lignes if l.startswith("  [1] "))
        self.assertIn(VM.LIBVIRT, auto)
        self.assertNotIn(VM.LIMA, auto)

    def test_the_automatic_line_borrows_no_star_and_no_advice(self):
        """Ils appartiennent au backend ; les lui emprunter les afficherait
        deux fois."""
        auto = next(
            l
            for l in self.lignes(C.AUTO, H.MACOS, True)
            if l.startswith("  [1] ")
        )
        self.assertNotIn("*", auto)

    def test_the_advice_sits_on_its_own_line(self):
        """Accolé, il déborde du terminal dès que le libellé est long, et
        c'est la fin de la phrase qui disparaît."""
        lignes = self.lignes(C.AUTO, H.ARCH)
        conseils = [
            l for l in lignes if l.startswith("        ") and l.strip()
        ]
        self.assertTrue(conseils)
        for ligne in conseils:
            with self.subTest(ligne=ligne[:40]):
                self.assertNotIn("[", ligne)

    def test_the_screen_says_what_is_in_use(self):
        for pref, hote, outil, attendu in (
            (C.AUTO, H.ARCH, False, VM.LIBVIRT),
            (C.AUTO, H.MACOS, True, VM.LIMA),
            (C.AUTO, H.MACOS, False, VM.PVE),
        ):
            with self.subTest(hote=hote, outil=outil):
                rendu = "\n".join(self.lignes(pref, hote, outil))
                self.assertIn(attendu, rendu.split("In use")[-1] + rendu)

    def test_no_line_is_absurdly_long(self):
        """Un terminal de 100 colonnes reste lisible."""
        for pref in C.CHOIX:
            for hote in (H.ARCH, H.MACOS):
                for ligne in self.lignes(pref, hote, True):
                    with self.subTest(ligne=ligne[:40]):
                        self.assertLessEqual(len(ligne), 100, ligne)


class TestLEcranQuiDemande(unittest.TestCase):
    """Le tour complet : afficher, choisir, retenir.

    Les préférences sont INJECTÉES : `todo_prefs._path()` fait un `mkdir`
    sur le vrai répertoire personnel, et une épreuve qui appellerait `set()`
    écrirait dans les réglages de la personne qui la lance.
    """

    def setUp(self):
        from script.todo.todo import TODO

        self.prefs = {"vm_backend": C.AUTO}
        patcheur = patch.multiple(
            "script.todo.vm_backend_menu.todo_prefs",
            get=lambda cle, defaut=None: self.prefs.get(cle, defaut),
            set=lambda cle, valeur: self.prefs.__setitem__(cle, valeur),
        )
        patcheur.start()
        self.addCleanup(patcheur.stop)
        hote = patch(
            "script.todo.vm_backend_menu.host_os.host_os", return_value=H.ARCH
        )
        hote.start()
        self.addCleanup(hote.stop)
        outil = patch(
            "script.todo.vm_backend_menu.shutil.which", return_value=None
        )
        outil.start()
        self.addCleanup(outil.stop)
        self.ecran = TODO.__new__(TODO)

    def jouer(self, *reponses):
        sortie = io.StringIO()
        with patch("builtins.input", side_effect=list(reponses)):
            with redirect_stdout(sortie):
                self.ecran._deploy_vm_backends()
        return sortie.getvalue()

    def test_it_announces_the_refusal_the_choice_really_causes(self):
        """L'écran annonçait que le choix ne routait rien.

        Il route : la valeur résolue entre dans la description de machine,
        et le chemin local refuse tout ce qui n'est pas libvirt. Un
        utilisateur qui choisissait « Lima » sur la foi de cette phrase
        découvrait le refus au déploiement, et le lisait comme une panne.

        L'épreuve ne tient pas des mots : elle tient que le backend nommé
        par l'écran est bien celui que le chemin local accepte, et le
        vérifie en JOUANT le refus.
        """
        from script.todo.todo import TODO as CLASSE
        from script.vm import backend as vm_backend

        affiche = self.jouer("0")
        self.assertTrue(affiche.strip())
        self.assertIn(vm_backend.LIBVIRT, affiche)

        todo = CLASSE.__new__(CLASSE)
        for autre in (
            n for n in vm_backend.BACKENDS if n != vm_backend.LIBVIRT
        ):
            spec = {
                "posture": "open",
                "real_data": False,
                "backend": autre,
                "name": "x",
                "install": {},
            }
            with self.subTest(backend=autre):
                with self.assertRaises(vm_backend.VerbNotImplemented) as vu:
                    CLASSE._qemu_deploy_parts_for(
                        todo, {"name": "x"}, spec, True, ""
                    )
                # Le refus NOMME le backend trouvé : sans cela l'écran
                # d'erreur n'apprend pas quoi changer.
                self.assertIn(autre, str(vu.exception))

    def test_a_number_is_remembered(self):
        self.jouer("4", "0")
        self.assertEqual(VM.LIMA, self.prefs["vm_backend"])

    def test_it_says_what_is_in_use_after_the_choice(self):
        affiche = self.jouer("2", "0")
        self.assertEqual(VM.LIBVIRT, self.prefs["vm_backend"])
        self.assertIn("✓", affiche)

    def test_a_number_out_of_range_changes_nothing(self):
        for reponse in ("0" + "9", "42", "abc", "-1"):
            with self.subTest(reponse=reponse):
                self.prefs["vm_backend"] = C.AUTO
                self.jouer(reponse, "0")
                self.assertEqual(C.AUTO, self.prefs["vm_backend"])

    def test_an_empty_answer_redisplays_rather_than_leaving(self):
        """Une entrée vide par mégarde ne doit pas fermer l'écran."""
        affiche = self.jouer("", "0")
        self.assertEqual(2, affiche.count("Backends de VM"))


if __name__ == "__main__":
    unittest.main()
