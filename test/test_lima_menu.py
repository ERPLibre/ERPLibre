#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Lima : ce qu'il montre, ce qu'il refuse, ce qu'il ne joue pas.

Ni « limactl », ni VM, ni réseau. Le mixin est instancié sans passer par
`TODO.__init__`, et ce qui exécute est remplacé : ce qui est éprouvé est ce
qui S'AFFICHE et ce qui SERAIT joué.

TROIS CHOSES QUE CES ÉPREUVES TIENNENT.

AUCUN ARGUMENT DE L'OUTIL N'EST ÉCRIT ICI. Les commandes viennent de
`script.vm.lima` ; une copie dans le menu diverge de la confrontation de
`long_test/`, et c'est justement celle-ci qui prouve les formes.

LA SUPPRESSION DEMANDE LE NOM RETAPÉ. « -f » retire la dernière question de
l'outil ; sans la saisie, un choix mal tapé détruirait sans un mot.

CHAQUE ROUTE D'ACQUISITION A SA PHRASE, et une route inconnue LÈVE — une
chaîne vide s'afficherait comme un succès, ce qui est le contraire d'un
refus.
"""

import contextlib
import io as _io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo import lima_menu, todo_i18n  # noqa: E402
from script.todo.lima_menu import (  # noqa: E402
    TOOL_SENTENCES,
    LimaMenuMixin,
    config_path,
    instance_line,
    tool_sentence,
)
from script.vm import lima as L  # noqa: E402
from script.vm import lima_install as I  # noqa: E402


class ExecuteDeBanc:
    """Ce qui aurait été joué, et rien de joué."""

    def __init__(self):
        self.joues = []

    def exec_command_live(self, cmd, source_erplibre=True, new_env=None):
        self.joues.append(cmd)


class MenuDeBanc(LimaMenuMixin):
    def __init__(self, instances=None):
        self.execute = ExecuteDeBanc()
        self._instances = instances

    def _lima_instances(self):
        return self._instances

    def _lima_image(self, arch):
        return f"https://exemple.invalid/image-{arch}.img"

    def _is_yes(self, reponse):
        return (reponse or "").strip().lower() in ("o", "oui", "y", "yes")


def sortie(fonction, *args, **kwargs):
    tampon = _io.StringIO()
    with contextlib.redirect_stdout(tampon):
        fonction(*args, **kwargs)
    return tampon.getvalue()


class CasDeMenu(unittest.TestCase):
    """La langue est ÉPINGLÉE en anglais : les clés SONT les chaînes
    anglaises, et comparer un mot français ferait dépendre le verdict de ce
    qu'une autre épreuve a laissé dans `_current_lang`."""

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"


class TestChaqueRouteADeQuoiAgir(CasDeMenu):
    def test_every_verdict_of_the_vocabulary_has_a_sentence(self):
        self.assertTrue(I.REFUSALS, "vocabulaire vidé : rien n'est prouvé")
        for verdict in I.REFUSALS:
            with self.subTest(verdict=verdict):
                self.assertTrue(tool_sentence(verdict).strip())

    def test_the_table_has_no_stale_entry(self):
        self.assertEqual(set(), set(TOOL_SENTENCES) - set(I.REFUSALS))

    def test_an_unknown_route_raises_rather_than_prints_nothing(self):
        with self.assertRaises(KeyError):
            tool_sentence("route-jamais-declaree")

    def test_the_mismatch_sentence_says_to_run_nothing(self):
        """C'est le dernier moment où rien n'a encore été exécuté : un
        message tiède y ferait « réessayer »."""
        phrase = TOOL_SENTENCES[I.CHECKSUM_MISMATCH]
        self.assertIn("Run nothing", phrase)

    def test_the_manager_sentence_says_why_it_is_preferred(self):
        phrase = TOOL_SENTENCES[I.MANAGER]
        self.assertIn("signature", phrase)

    def test_no_sentence_advises_skipping_the_verification(self):
        """Le conseil qui vient en premier à l'esprit est le mauvais."""
        for verdict, phrase in TOOL_SENTENCES.items():
            with self.subTest(verdict=verdict):
                bas = phrase.lower()
                self.assertNotIn("skip the check", bas)
                self.assertNotIn("without verifying", bas)


class TestLeCheminDeConfiguration(CasDeMenu):
    def test_it_lives_under_the_user_directory_and_not_the_checkout(self):
        """Un fichier dans le checkout se ferait emporter par un ratissage
        d'indexation, et une instance appartient à qui la lance."""
        chemin = config_path("essai")
        self.assertTrue(chemin.endswith("essai.yaml"), chemin)
        self.assertNotIn("erplibre_devstack/script", chemin)
        self.assertTrue(os.path.isabs(chemin), chemin)

    def test_the_tilde_is_expanded(self):
        self.assertNotIn("~", config_path("essai"))

    def test_two_instances_do_not_share_a_file(self):
        self.assertNotEqual(config_path("a"), config_path("b"))


class TestLaLigneDInventaire(CasDeMenu):
    def test_a_running_instance_carries_a_different_marker(self):
        """LA MARQUE, et pas seulement la ligne : les libellés d'état
        diffèrent de toute façon, donc comparer les lignes entières
        passerait avec une marque unique."""
        vive = instance_line(L.Instance("a", "Running"))[0]
        morte = instance_line(L.Instance("a", "Stopped"))[0]
        self.assertNotEqual(vive, morte)

    def test_the_marker_is_at_a_fixed_place(self):
        """Une liste se balaie du regard : la marque doit être en tête, et
        au même endroit sur chaque ligne."""
        for etat in ("Running", "Stopped", ""):
            with self.subTest(etat=etat):
                ligne = instance_line(L.Instance("nom-long", etat))
                self.assertEqual(" ", ligne[1])
                self.assertTrue(ligne[2:].startswith("nom-long"))

    def test_the_state_is_written_and_not_only_coloured(self):
        """La sortie d'un menu se colle dans un rapport, où la couleur ne
        survit pas."""
        self.assertIn("Stopped", instance_line(L.Instance("a", "Stopped")))

    def test_the_ssh_port_shows_when_there_is_one(self):
        avec = instance_line(L.Instance("a", "Running", "arm64", "60022"))
        self.assertIn("60022", avec)

    def test_no_port_means_the_word_ssh_does_not_appear(self):
        """« ssh » suivi de rien laisse croire à un port qu'on n'a pas lu,
        et une ligne d'inventaire se relit vite."""
        sans = instance_line(L.Instance("a", "Running", "arm64"))
        self.assertNotIn("ssh", sans)

    def test_a_bare_instance_does_not_crash(self):
        self.assertTrue(instance_line(L.Instance("a", "")))


class TestCeQuiSeraitJoue(CasDeMenu):
    VIVE = L.Instance("vive", "Running", "arm64", "60022")
    MORTE = L.Instance("morte", "Stopped", "arm64")

    def test_starting_asks_the_module_for_its_command(self):
        menu = MenuDeBanc(instances=(self.MORTE,))
        with patch("builtins.input", return_value="1"):
            sortie(menu._lima_power, "start")
        self.assertEqual(
            [L.display(L.start_argv("morte"))], menu.execute.joues
        )

    def test_stopping_asks_the_module_for_its_command(self):
        menu = MenuDeBanc(instances=(self.VIVE,))
        with patch("builtins.input", return_value="1"):
            sortie(menu._lima_power, "stop")
        self.assertEqual([L.display(L.stop_argv("vive"))], menu.execute.joues)

    def test_an_action_outside_the_vocabulary_runs_nothing(self):
        """« suspend » n'est pas du vocabulaire de cet outil, et le laisser
        passer composerait une commande que l'outil rejette."""
        menu = MenuDeBanc(instances=(self.VIVE,))
        texte = sortie(menu._lima_power, "suspend")
        self.assertEqual([], menu.execute.joues)
        self.assertIn("not found", texte)

    def test_stopping_only_offers_what_is_running(self):
        """Proposer d'arrêter ce qui est éteint fait jouer une commande qui
        échoue, et le refus de l'outil ne dit pas que le choix était le
        mauvais."""
        menu = MenuDeBanc(instances=(self.VIVE, self.MORTE))
        with patch("builtins.input", return_value="1"):
            texte = sortie(menu._lima_power, "stop")
        self.assertIn("vive", texte)
        self.assertNotIn("morte", texte)

    def test_starting_only_offers_what_is_stopped(self):
        menu = MenuDeBanc(instances=(self.VIVE, self.MORTE))
        with patch("builtins.input", return_value="1"):
            texte = sortie(menu._lima_power, "start")
        self.assertIn("morte", texte)
        self.assertNotIn("vive", texte)

    def test_the_command_is_shown_before_it_is_played(self):
        menu = MenuDeBanc(instances=(self.MORTE,))
        with patch("builtins.input", return_value="1"):
            texte = sortie(menu._lima_power, "start")
        self.assertIn(L.display(L.start_argv("morte")), texte)

    def test_a_cancelled_choice_runs_nothing(self):
        menu = MenuDeBanc(instances=(self.MORTE,))
        with patch("builtins.input", return_value=""):
            sortie(menu._lima_power, "start")
        self.assertEqual([], menu.execute.joues)

    def test_an_out_of_range_choice_runs_nothing(self):
        menu = MenuDeBanc(instances=(self.MORTE,))
        with patch("builtins.input", return_value="9"):
            sortie(menu._lima_power, "start")
        self.assertEqual([], menu.execute.joues)

    def test_a_tool_that_did_not_answer_runs_nothing(self):
        """None et non un tuple vide : « aucune instance » et « l'outil est
        absent » se corrigent de deux côtés opposés."""
        menu = MenuDeBanc(instances=None)
        sortie(menu._lima_power, "start")
        self.assertEqual([], menu.execute.joues)

    def test_a_shell_only_opens_on_a_running_instance(self):
        menu = MenuDeBanc(instances=(self.VIVE, self.MORTE))
        with patch("builtins.input", return_value="1"):
            texte = sortie(menu._lima_shell)
        self.assertIn("vive", texte)
        self.assertEqual([L.display(L.shell_argv("vive"))], menu.execute.joues)


class TestLaSuppressionDemandeLeNom(CasDeMenu):
    MORTE = L.Instance("morte", "Stopped", "arm64")

    def repondre(self, *reponses):
        return patch("builtins.input", side_effect=list(reponses))

    def test_the_name_retyped_is_what_lets_it_through(self):
        menu = MenuDeBanc(instances=(self.MORTE,))
        with self.repondre("1", "morte"):
            sortie(menu._lima_delete)
        self.assertEqual(
            [L.display(L.delete_argv("morte"))], menu.execute.joues
        )

    def test_a_wrong_name_destroys_nothing(self):
        """« -f » retire la dernière question de l'outil : sans cette
        saisie, un choix mal tapé détruirait sans un mot."""
        menu = MenuDeBanc(instances=(self.MORTE,))
        with self.repondre("1", "mort"):
            texte = sortie(menu._lima_delete)
        self.assertEqual([], menu.execute.joues)
        self.assertIn("Cancelled", texte)

    def test_a_bare_yes_is_not_enough(self):
        """« o » se tape par réflexe ; recopier un nom oblige à regarder ce
        qu'on détruit."""
        menu = MenuDeBanc(instances=(self.MORTE,))
        with self.repondre("1", "o"):
            sortie(menu._lima_delete)
        self.assertEqual([], menu.execute.joues)

    def test_the_command_is_shown_before_the_question(self):
        menu = MenuDeBanc(instances=(self.MORTE,))
        with self.repondre("1", ""):
            texte = sortie(menu._lima_delete)
        self.assertIn(L.display(L.delete_argv("morte")), texte)

    def test_the_config_file_goes_with_the_instance(self):
        """Le laisser ferait redémarrer une instance qu'on croyait
        détruite, sous une configuration qu'on ne relirait pas."""
        with tempfile.TemporaryDirectory() as base:
            chemin = os.path.join(base, "morte.yaml")
            with open(chemin, "w", encoding="utf-8") as fichier:
                fichier.write("images: []\n")
            menu = MenuDeBanc(instances=(self.MORTE,))
            with patch.object(
                lima_menu, "config_path", return_value=chemin
            ), self.repondre("1", "morte"):
                sortie(menu._lima_delete)
            self.assertFalse(os.path.exists(chemin))

    def test_a_cancelled_deletion_keeps_the_config(self):
        with tempfile.TemporaryDirectory() as base:
            chemin = os.path.join(base, "morte.yaml")
            with open(chemin, "w", encoding="utf-8") as fichier:
                fichier.write("images: []\n")
            menu = MenuDeBanc(instances=(self.MORTE,))
            with patch.object(
                lima_menu, "config_path", return_value=chemin
            ), self.repondre("1", "non"):
                sortie(menu._lima_delete)
            self.assertTrue(os.path.exists(chemin))


class TestLaCreation(CasDeMenu):
    def creer(self, menu, nom, reponse, base):
        with patch.object(
            menu, "_lima_ask_name", return_value=nom
        ), patch.object(
            lima_menu,
            "config_path",
            return_value=os.path.join(base, f"{nom}.yaml"),
        ), patch(
            "builtins.input", return_value=reponse
        ):
            return sortie(menu._lima_create)

    def test_the_config_is_shown_whole_before_anything(self):
        """Elle décide de ce que l'invité monte de l'hôte et de ce qu'il
        expose : la relire coûte dix secondes, et c'est le seul moment."""
        with tempfile.TemporaryDirectory() as base:
            menu = MenuDeBanc()
            texte = self.creer(menu, "essai", "n", base)
        self.assertIn("mounts: []", texte)
        self.assertIn("images:", texte)
        self.assertEqual([], menu.execute.joues)

    def test_refusing_writes_no_file(self):
        with tempfile.TemporaryDirectory() as base:
            menu = MenuDeBanc()
            self.creer(menu, "essai", "n", base)
            self.assertEqual([], os.listdir(base))

    def test_accepting_writes_the_file_and_starts_it(self):
        """Contrôle positif : ne jamais écrire retirerait l'usage."""
        with tempfile.TemporaryDirectory() as base:
            menu = MenuDeBanc()
            self.creer(menu, "essai", "o", base)
            chemin = os.path.join(base, "essai.yaml")
            self.assertTrue(os.path.exists(chemin))
            with open(chemin, encoding="utf-8") as fichier:
                self.assertIn("mounts: []", fichier.read())
        self.assertEqual(
            [L.display(L.start_argv("essai", chemin))], menu.execute.joues
        )

    def test_what_the_config_cannot_hold_is_said(self):
        """Une configuration muette sur ce qu'elle n'applique pas fait
        croire à un confinement qui n'existe pas."""
        with tempfile.TemporaryDirectory() as base:
            menu = MenuDeBanc()
            with patch("script.todo.host_os.is_macos", return_value=False):
                texte = self.creer(menu, "essai", "n", base)
        self.assertIn("reachable-address", texte)

    def test_a_refused_name_creates_nothing(self):
        with tempfile.TemporaryDirectory() as base:
            menu = MenuDeBanc()
            texte = self.creer(menu, "", "o", base)
            self.assertEqual([], os.listdir(base))
        self.assertEqual([], menu.execute.joues)
        self.assertEqual("", texte)


class TestLeNomEstValide(CasDeMenu):
    def demander(self, saisie):
        menu = MenuDeBanc()
        with patch("builtins.input", return_value=saisie):
            tampon = _io.StringIO()
            with contextlib.redirect_stdout(tampon):
                return menu._lima_ask_name()

    def test_a_plain_name_passes(self):
        self.assertEqual("essai", self.demander("essai"))

    def test_a_path_traversal_is_refused(self):
        """Le nom devient un nom de FICHIER : un « ../ » écrirait la
        configuration ailleurs."""
        for mauvais in ("../ailleurs", "a/b", "..", "/etc/passwd"):
            with self.subTest(nom=mauvais):
                self.assertEqual("", self.demander(mauvais))

    def test_a_space_is_refused(self):
        """Il devient aussi un ARGUMENT : une espace couperait la commande
        en deux."""
        self.assertEqual("", self.demander("un nom"))

    def test_a_shell_metacharacter_is_refused(self):
        for mauvais in ("a;b", "a$(b)", "a&b", "a|b", "a`b`"):
            with self.subTest(nom=mauvais):
                self.assertEqual("", self.demander(mauvais))

    def test_nothing_typed_is_a_renouncement_and_not_an_error(self):
        self.assertEqual("", self.demander(""))


class TestLaFrontiereAvecLeModuleLima(CasDeMenu):
    """Ici on demande et on affiche ; là-bas on compose et on analyse."""

    @staticmethod
    def source():
        chemin = os.path.join(RACINE, "script", "todo", "lima_menu.py")
        with open(chemin, encoding="utf-8") as fichier:
            return fichier.read()

    @staticmethod
    def _litteraux_de_code(source):
        """Les chaînes du CODE qui nomment l'outil, docstrings exclues."""
        import ast

        arbre = ast.parse(source)
        docs = set()
        for noeud in ast.walk(arbre):
            if not isinstance(
                noeud,
                (
                    ast.Module,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            ):
                continue
            corps = getattr(noeud, "body", None) or []
            if (
                corps
                and isinstance(corps[0], ast.Expr)
                and isinstance(corps[0].value, ast.Constant)
                and isinstance(corps[0].value.value, str)
            ):
                docs.add(id(corps[0].value))
        return [
            noeud.value
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Constant)
            and isinstance(noeud.value, str)
            and id(noeud) not in docs
            and "limactl" in noeud.value
        ]

    def test_the_menu_writes_no_tool_argument_of_its_own(self):
        """Une copie ici diverge de la confrontation de `long_test/`, et
        c'est celle-ci qui prouve les formes."""
        litteraux = self._litteraux_de_code(self.source())
        self.assertEqual([], litteraux, litteraux)

    def test_it_calls_the_renderers(self):
        source = self.source()
        for rendu in (
            "list_argv",
            "start_argv",
            "stop_argv",
            "delete_argv",
            "shell_argv",
        ):
            with self.subTest(rendu=rendu):
                self.assertIn(f"lima.{rendu}(", source)

    def test_the_mixin_is_reachable_from_the_menu(self):
        """Le motif à éviter : un mixin écrit, éprouvé, et jamais composé."""
        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.assertTrue(issubclass(TODO, LimaMenuMixin))
        self.assertTrue(hasattr(TODO, "prompt_execute_lima"))

    def test_the_deploy_menu_declares_where_the_entry_leads(self):
        with open(
            os.path.join(RACINE, "script", "todo", "todo.py"),
            encoding="utf-8",
        ) as fichier:
            self.assertIn('"method": "prompt_execute_lima"', fichier.read())


if __name__ == "__main__":
    unittest.main()
