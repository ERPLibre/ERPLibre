#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'exécuteur des gestes du moteur : ce qu'il laisse passer, ce qu'il coupe.

Rien ici ne touche au moteur : les gestes joués sont un `make` de banc et un
`python3` qui rapporte ce qu'il voit dans son environnement. Ce qui est
éprouvé, ce sont les PROPRIÉTÉS — une liste blanche qui coupe vraiment, un
PATH jugé par segments et non par sous-chaînes, une ligne affichée qui est la
ligne lancée, et un verdict qui distingue « rendu non nul » de « n'a pas pu
tourner ».

Les noms de variables et de dossiers inventés ici n'apparaissent nulle part
ailleurs dans le dépôt.
"""

import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import runner as R  # noqa: E402

# Un environnement de poste tel qu'il arrive vraiment : ce qui doit passer,
# et quatre choses qui décideraient à la place de l'opérateur.
SOURCE = {
    "HOME": "/foyer-fictif",
    "PATH": "/usr/bin:/bin",
    "LANG": "fr_CA.UTF-8",
    "TERM": "xterm",
    "USER": "compte-fictif",
    "SSH_AUTH_SOCK": "/agent-fictif/sock",
    R.CONFIRMER: R.CONFIRME,
    "MAKEFLAGS": "-j8",
    "MAKELEVEL": "1",
    "SETOPS_UNDERLAY": "grappe-fictive-serpentine",
    "ANSIBLE_FORCE_COLOR": "1",
}


class TestLEnvironnementEstNeuf(unittest.TestCase):
    """Hérité, l'environnement décide à la place de l'opérateur."""

    def test_only_the_whitelist_survives(self):
        garde = R.base(SOURCE)
        self.assertEqual(
            {
                "HOME",
                "PATH",
                "LANG",
                "TERM",
                "USER",
                "SSH_AUTH_SOCK",
            },
            set(garde),
        )

    def test_a_confirmation_left_behind_never_reaches_the_engine(self):
        """Les applicateurs du moteur écrivent sur « true » lu dans
        l'environnement : un reste de geste précédent vaut ordre d'écrire."""
        self.assertNotIn(R.CONFIRMER, R.base(SOURCE))

    def test_the_parent_make_overrides_are_dropped(self):
        """todo se lance lui-même par `make todo` : ses surcharges
        traverseraient jusqu'au Makefile du moteur."""
        self.assertNotIn("MAKEFLAGS", R.base(SOURCE))
        self.assertNotIn("MAKELEVEL", R.base(SOURCE))

    def test_the_variables_the_engine_lets_win_are_dropped(self):
        """Le moteur pose ses défauts en `?=` : une valeur héritée gagne, et
        l'une d'elles désigne la grappe qu'un geste destructeur viserait."""
        self.assertNotIn("SETOPS_UNDERLAY", R.base(SOURCE))
        self.assertNotIn("ANSIBLE_FORCE_COLOR", R.base(SOURCE))

    def test_an_empty_source_gives_an_empty_environment(self):
        self.assertEqual({}, R.base({}))


class TestLePathEstJugeParSegments(unittest.TestCase):
    """Le venv d'ERPLibre porte un autre Python et d'autres bibliothèques."""

    def chemin(self, path):
        return R.base({"PATH": path})["PATH"].split(os.pathsep)

    def test_the_erplibre_venv_is_removed(self):
        self.assertEqual(
            ["/usr/bin", "/bin"],
            self.chemin(f"/depot/{R.VENV_ERPLIBRE}/bin:/usr/bin:/bin"),
        )

    def test_a_folder_that_merely_starts_the_same_stays(self):
        """Juger par sous-chaîne couperait un dossier voisin, et un PATH
        amputé se diagnostique très mal."""
        voisin = f"/depot/{R.VENV_ERPLIBRE}-de-cote/bin"
        self.assertIn(voisin, self.chemin(f"{voisin}:/usr/bin"))

    def test_an_empty_entry_is_dropped(self):
        """Une entrée vide vaut « le dossier courant » pour un shell, ce
        qu'aucun geste n'a demandé."""
        self.assertEqual(["/usr/bin"], self.chemin(":/usr/bin:"))

    def test_nothing_to_remove_leaves_the_path_alone(self):
        self.assertEqual(["/usr/bin", "/bin"], self.chemin("/usr/bin:/bin"))


class TestLaLigneMontreeEstLaLigneLancee(unittest.TestCase):
    MOTEUR = "/depot-fictif/moteur"

    def test_a_target_always_carries_its_confirmation(self):
        """Une ligne sans `CONFIRMER` laisse ignorer si le geste simule
        ou écrit, ce qui est la seule chose qu'on relit avant de valider."""
        argv = R.cible(self.MOTEUR, "instances")
        self.assertEqual(f"{R.CONFIRMER}={R.SIMULE}", argv[-1])

    def test_confirming_writes_it_on_the_line_too(self):
        argv = R.cible(self.MOTEUR, "instance-creer", confirmer=True)
        self.assertEqual(f"{R.CONFIRMER}={R.CONFIRME}", argv[-1])

    def test_the_confirmation_comes_last_whatever_the_variables(self):
        """Posée avant les variables, elle se perdrait de vue dans une ligne
        longue — et c'est la seule qu'on relit avant de valider."""
        argv = R.cible(
            self.MOTEUR,
            "instance-creer",
            [("NOM", "ecosysteme-fictif-cassiterite"), ("MODELE", "socle")],
        )
        self.assertTrue(argv[-1].startswith(R.CONFIRMER + "="))

    def test_the_variables_reach_the_line_as_make_expects_them(self):
        argv = R.cible(self.MOTEUR, "x", [("NOM", "un-nom-fictif")])
        self.assertIn("NOM=un-nom-fictif", argv)

    def test_what_is_shown_parses_back_to_what_is_run(self):
        """L'affichage est DÉRIVÉ de l'argv : une ligne montrée qui n'est
        pas la ligne lancée est pire que pas de ligne du tout."""
        argv = R.cible(self.MOTEUR, "x", [("NOM", "un nom avec des espaces")])
        self.assertEqual(list(argv), shlex.split(R.cite(argv)))


class TestLeVerdict(unittest.TestCase):
    """« Rendu non nul » et « n'a pas pu tourner » sont deux nouvelles."""

    def test_a_success_is_zero_and_reads_as_such(self):
        vu = R.jouer((sys.executable, "-c", "pass"))
        self.assertEqual(0, vu.code)
        self.assertTrue(vu.reussi)

    def test_a_refusal_carries_its_code(self):
        vu = R.jouer((sys.executable, "-c", "raise SystemExit(2)"))
        self.assertEqual(2, vu.code)
        self.assertFalse(vu.reussi)

    def test_a_command_that_does_not_exist_is_not_a_zero(self):
        """Rendre 0 ferait annoncer une réussite à un geste qui n'a jamais
        commencé."""
        vu = R.jouer(("/nulle-part-fictif/rien",))
        self.assertIsNone(vu.code)
        self.assertFalse(vu.reussi)

    def test_a_gesture_past_its_delay_is_not_a_zero(self):
        vu = R.jouer(
            (sys.executable, "-c", "import time; time.sleep(5)"), delai=1
        )
        self.assertIsNone(vu.code)
        self.assertFalse(vu.reussi)

    def test_the_output_is_carried_back(self):
        vu = R.jouer((sys.executable, "-c", "print('un-mot-fictif')"))
        self.assertIn("un-mot-fictif", vu.sortie)

    def test_the_error_output_is_carried_back_too(self):
        """Un geste qui explique son refus le fait souvent sur l'erreur :
        la perdre laisserait un code nu, sans raison."""
        vu = R.jouer(
            (
                sys.executable,
                "-c",
                "import sys; print('sur-erreur-fictif', file=sys.stderr)",
            )
        )
        self.assertIn("sur-erreur-fictif", vu.sortie)


class TestDeBoutEnBout(unittest.TestCase):
    """La chaîne entière : `make`, sa variable de ligne, et ce que le script
    appelé voit dans SON environnement."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        sonde = (
            f"import os; print('vu=' + repr(os.environ.get({R.CONFIRMER!r})))"
        )
        with open(
            os.path.join(self.dossier, "Makefile"), "w", encoding="utf-8"
        ) as fichier:
            fichier.write(
                "sonde:\n"
                f"\t@{shlex.quote(sys.executable)} -c {shlex.quote(sonde)}\n"
            )

    def vu(self, env, confirmer=False):
        verdict = R.jouer(
            R.cible(self.dossier, "sonde", confirmer=confirmer), env=env
        )
        self.assertEqual(0, verdict.code, verdict.sortie)
        return verdict.sortie.strip()

    def test_the_line_decides_and_the_environment_does_not(self):
        """`make` met une variable de ligne dans l'environnement du script
        appelé, ET elle l'emporte sur celle qui serait héritée. C'est ce qui
        fait du `CONFIRMER` affiché la garde réelle, et non un ornement."""
        pollue = dict(R.base(SOURCE))
        pollue[R.CONFIRMER] = R.CONFIRME
        self.assertEqual(f"vu={R.SIMULE!r}", self.vu(pollue))

    def test_confirming_reaches_the_called_script(self):
        """Contrôle positif : sans lui, une sonde qui ne verrait JAMAIS
        « true » passerait l'épreuve précédente sans rien prouver."""
        self.assertEqual(
            f"vu={R.CONFIRME!r}", self.vu(R.base(SOURCE), confirmer=True)
        )


class TestLeJournalDuDetache(unittest.TestCase):
    """Le dossier de repli d'un journal est PARTAGÉ : un autre compte peut y
    poser ce nom en lien vers un fichier qu'on a le droit d'écrire."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="setops-runner-banc-")
        self.addCleanup(self._menage)
        self.journal = os.path.join(self.dossier, "banc.log")

    def _menage(self):
        for nom in os.listdir(self.dossier):
            os.unlink(os.path.join(self.dossier, nom))
        os.rmdir(self.dossier)

    def test_the_log_is_readable_by_nobody_else(self):
        """`open(…, "ab")` naît en 0666 moins l'umask, donc lisible par tout le
        monde sur un poste ordinaire."""
        # Le journal est ouvert AVANT le lancement, donc il existe dès le
        # retour : rien à attendre du fils, dont la sortie ne change pas le mode.
        self.assertIsNotNone(R.detacher(["true"], journal=self.journal))
        mode = stat.S_IMODE(os.stat(self.journal).st_mode)
        self.assertEqual(0, mode & (stat.S_IRWXG | stat.S_IRWXO))

    def test_a_symlink_in_the_way_is_never_followed(self):
        """Suivi, tout ce que le détaché écrit part chez celui qui a posé le
        lien."""
        cible = os.path.join(self.dossier, "chez-un-autre.log")
        with open(cible, "w", encoding="utf-8") as tenu:
            tenu.write("intact\n")
        os.symlink(cible, self.journal)
        # L'ouverture refusée, le fils reçoit /dev/null : il ne peut donc JAMAIS
        # atteindre la cible, et le constat ne court après rien.
        R.detacher(["sh", "-c", "echo une-fuite"], journal=self.journal)
        with open(cible, encoding="utf-8") as tenu:
            self.assertEqual("intact\n", tenu.read())


class TestLeDelaiGardeCeQuiAEteDit(unittest.TestCase):
    """Jeté, le verdict d'un geste qui a tourné une heure en imprimant son
    avancement devenait celui d'un binaire introuvable."""

    def test_what_was_printed_before_the_bound_survives_it(self):
        panne = subprocess.TimeoutExpired(
            cmd=["banc"], timeout=1, output="tâche 3 sur 7 terminée\n"
        )
        with mock.patch.object(subprocess, "run", side_effect=panne):
            vu = R.jouer(["banc"])
        self.assertIsNone(vu.code)
        self.assertIn("tâche 3 sur 7", vu.sortie)

    def test_a_gesture_that_printed_nothing_says_nothing(self):
        panne = subprocess.TimeoutExpired(cmd=["banc"], timeout=1)
        with mock.patch.object(subprocess, "run", side_effect=panne):
            vu = R.jouer(["banc"])
        self.assertEqual("", vu.sortie)


class TestLEntreeNePasseJamaisParLeDisque(unittest.TestCase):
    """C'est le seul chemin par lequel un secret atteint l'outil qui le chiffre :
    écrit en clair puis chiffré, il resterait dans les blocs libérés et dans
    toute sauvegarde prise entre les deux gestes."""

    def test_the_text_reaches_the_command(self):
        vu = R.jouer(("cat",), entree="le texte passé\n")
        self.assertEqual((0, "le texte passé\n"), (vu.code, vu.sortie))

    def test_an_empty_input_is_still_an_input(self):
        """La chaîne vide OUVRE le tube : « rien à passer » n'est pas « ne rien
        ouvrir », et un outil qui lit une entrée vide voit une fin de fichier
        plutôt qu'une erreur."""
        vu = R.jouer(("cat",), entree="")
        self.assertEqual((0, ""), (vu.code, vu.sortie))

    def test_without_it_the_input_is_closed(self):
        """LA PROPRIÉTÉ. Un geste qui réclamerait une phrase de passe doit
        ÉCHOUER tout de suite, et non attendre jusqu'à la borne — une épreuve
        lancée pour des heures sans surveillance y resterait pendue."""
        vu = R.jouer(("sh", "-c", "read x"), delai=10)
        self.assertNotEqual(0, vu.code)

    def test_the_same_command_succeeds_when_given_one(self):
        """Le contrôle positif du précédent."""
        vu = R.jouer(("sh", "-c", "read x"), delai=10, entree="une ligne\n")
        self.assertEqual(0, vu.code)

    def test_it_never_raises_when_both_would_be_passed(self):
        """`input` OU `stdin`, jamais les deux : ensemble ils lèvent une
        ValueError que ce module attrape, et le geste rendrait « n'a pas pu
        tourner » sur un argument — un diagnostic très loin de sa cause."""
        self.assertEqual(0, R.jouer(("true",), entree="x").code)


class TestLeVerrouDesGestesDunMoteur(unittest.TestCase):
    """Deux gestes menés en même temps sur le même clone se disputent son
    instance montée, ses fichiers générés et la grappe : le second réécrit ce que
    le premier vient d'appliquer, et le résultat ne ressemble à aucun des deux.
    Le moteur n'a pas de verrou hors de sa console."""

    def test_two_clones_of_the_same_name_do_not_share_it(self):
        """UN VERROU PAR CLONE : deux clones sont deux moteurs, avec chacun son
        instance montée, et les faire s'attendre ferait refuser un geste qui ne
        touche rien de commun. Le dossier seul se répète d'un checkout à
        l'autre."""
        self.assertNotEqual(
            R.chemin_verrou("/un/endroit/Moteur"),
            R.chemin_verrou("/un/autre/Moteur"),
        )

    def test_the_same_clone_always_gives_the_same_file(self):
        """Le contrôle positif du précédent : sans lui, un chemin qui change à
        chaque appel ne verrouillerait jamais rien."""
        self.assertEqual(
            R.chemin_verrou("/un/endroit/Moteur"),
            R.chemin_verrou("/un/endroit/Moteur/"),
        )

    def test_the_file_name_carries_the_folder_so_a_human_reads_it(self):
        self.assertIn("Moteur", os.path.basename(R.chemin_verrou("/a/Moteur")))

    def test_it_lives_outside_the_engine(self):
        """Un fichier posé dans le clone apparaîtrait comme non suivi dans son
        état git, et un exploitant qui regarde ce qu'il a modifié y verrait un
        reste dont il ne sait rien."""
        moteur = "/un/endroit/Moteur"
        self.assertFalse(R.chemin_verrou(moteur).startswith(moteur))

    def test_without_an_engine_there_is_no_lock(self):
        for moteur in ("", "   ", None):
            with self.subTest(moteur=moteur):
                self.assertEqual("", R.chemin_verrou(moteur))

    def test_no_engine_does_not_block_the_gesture(self):
        """Le verrou ferme une course entre deux terminaux ; en faire une
        condition d'exécution empêcherait tout geste là où il ne peut pas
        s'écrire."""
        with R.verrou_du_moteur("") as libre:
            self.assertTrue(libre)

    def test_a_second_holder_is_refused_at_once(self):
        """NON BLOQUANT : un second terminal est refusé sur-le-champ plutôt que
        mis en attente d'un déploiement qui dure des dizaines de minutes."""
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier, True)
        moteur = os.path.join(dossier, "Moteur")
        with R.verrou_du_moteur(moteur) as premier:
            self.assertTrue(premier)
            with R.verrou_du_moteur(moteur) as second:
                self.assertFalse(second)

    def test_it_is_released_when_the_block_ends(self):
        """Le contrôle positif du précédent : sans lui, un verrou jamais rendu
        passerait l'épreuve ci-dessus."""
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier, True)
        moteur = os.path.join(dossier, "Moteur")
        with R.verrou_du_moteur(moteur) as premier:
            self.assertTrue(premier)
        with R.verrou_du_moteur(moteur) as apres:
            self.assertTrue(apres)

    def test_it_falls_with_the_process_even_killed(self):
        """LA PROPRIÉTÉ QUI COMPTE : aucun reste à nettoyer, et rien à purger
        après un arrêt qui s'est mal passé. Un verrou par fichier-témoin
        laisserait un poste bloqué jusqu'à une intervention à la main."""
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier, True)
        moteur = os.path.join(dossier, "Moteur")
        enfant = (
            "import sys, time; sys.path.insert(0, %r)\n"
            "from script.setops import runner\n"
            "with runner.verrou_du_moteur(%r) as libre:\n"
            "    print(libre, flush=True)\n"
            "    time.sleep(30)\n"
            % (
                os.path.normpath(
                    os.path.join(os.path.dirname(__file__), "..")
                ),
                moteur,
            )
        )
        fils = subprocess.Popen(
            [sys.executable, "-B", "-c", enfant],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(fils.kill)
        try:
            self.assertEqual("True", (fils.stdout.readline() or "").strip())
            with R.verrou_du_moteur(moteur) as pendant:
                self.assertFalse(pendant, "tenu ailleurs, il devait refuser")
            fils.kill()
            fils.wait(timeout=10)
        finally:
            fils.stdout.close()
        with R.verrou_du_moteur(moteur) as apres:
            self.assertTrue(
                apres, "le verrou n'est pas tombé avec le processus"
            )


if __name__ == "__main__":
    unittest.main()
