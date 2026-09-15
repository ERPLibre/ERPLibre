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
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from script.todo import lima_menu, todo_i18n  # noqa: E402
from script.todo.lima_menu import LimaMenuMixin  # noqa: E402
from script.todo.lima_menu import (
    TOOL_SENTENCES,
    config_path,
    instance_line,
    tool_sentence,
)
from script.todo.todo_i18n import t  # noqa: E402
from script.vm import backend as vm_backend  # noqa: E402
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

    # Le composeur de chemin de menu vit sur TODO, comme la table qu'il
    # lit. Le banc tire la VRAIE méthode plutôt que d'en inventer une :
    # un chemin bouchonné passerait sur un menu renommé, ce qui est
    # exactement ce que ce composeur existe pour attraper.
    @staticmethod
    def menu_path(*fonctions):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO.menu_path(*fonctions)

    # Les deux voisins que le vrai menu tient du mixin de déploiement : le
    # banc déclare ce qu'il fournit plutôt que de monter tout TODO.
    posture_demandee = "open"

    def _deploy_ask_posture(self, after_boot=False):
        from script.posture import spec as posture_spec

        return {
            posture_spec.POSTURE_KEY: self.posture_demandee,
            posture_spec.REAL_DATA_KEY: False,
        }

    def _qemu_egress_rules(self, spec):
        from script.posture import allowlist, registry, rules
        from script.posture import spec as posture_spec

        posture = registry.get_posture(posture_spec.posture_name(spec))
        if not rules.wants_rules(posture):
            return ""
        cibles = ()
        if posture.destinations_bounded:
            cibles = (allowlist.resolve("dns-resolver", ["198.51.100.53"]),)
        return rules.render_egress(posture, cibles)


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

    def test_it_is_said_on_macos_too_when_nobody_asked_for_it(self):
        """LE PIÈGE. Sur macOS l'adresse joignable est POSSIBLE, donc une
        réponse fondée sur ce que l'HÔTE peut offrir dirait « rien ne
        manque » — sur une instance qui n'est pas joignable, parce que
        personne ne l'a demandée."""
        with tempfile.TemporaryDirectory() as base:
            menu = MenuDeBanc()
            with patch("script.todo.host_os.is_macos", return_value=True):
                texte = self.creer(menu, "essai", "n", base)
        self.assertIn("reachable-address", texte)

    def test_a_refused_name_creates_nothing(self):
        with tempfile.TemporaryDirectory() as base:
            menu = MenuDeBanc()
            texte = self.creer(menu, "", "o", base)
            self.assertEqual([], os.listdir(base))
        self.assertEqual([], menu.execute.joues)
        self.assertEqual("", texte)


class TestLaPostureALaCreation(CasDeMenu):
    """Lima était le SEUL des trois backends hors du système de postures.

    Le prédicat qui dit ce qu'une instance ne tient pas existait depuis le
    début, avec ses épreuves et zéro appelant : aucune posture n'était
    jamais choisie, donc il n'avait rien à juger.
    """

    def creer(self, menu, reponse="o", posture="open", macos=False):
        import tempfile as tf

        menu.posture_demandee = posture
        with tf.TemporaryDirectory() as base:
            self.base = base
            with patch.object(
                menu, "_lima_ask_name", return_value="essai"
            ), patch.object(
                lima_menu,
                "config_path",
                return_value=os.path.join(base, "essai.yaml"),
            ), patch.object(
                lima_menu.host_os, "is_macos", return_value=macos
            ), patch(
                "builtins.input", return_value=reponse
            ):
                texte = sortie(menu._lima_create)
            self.ecrits = os.listdir(base)
        return texte

    def test_a_cut_egress_is_refused_and_nothing_is_written(self):
        """Le réseau en mode utilisateur de Lima DONNE toujours la sortie,
        et aucun réglage d'instance ne la retire. Offrir « rien ne sort »
        ici serait exactement le nom rassurant que le registre s'interdit."""
        menu = MenuDeBanc()
        texte = self.creer(menu, posture="local-only")
        self.assertEqual([], self.ecrits)
        self.assertEqual([], menu.execute.joues)
        self.assertIn("egress-none", texte)

    def test_a_bounded_allowlist_poses_its_rules_in_the_guest(self):
        menu = MenuDeBanc()
        texte = self.creer(menu, posture="paranoid")
        self.assertIn("provision:", texte)
        self.assertIn("nft -f", texte)

    def test_a_free_egress_poses_nothing(self):
        """Lui rendre un bloc donnerait l'apparence d'un confinement que le
        nom de la posture dément."""
        menu = MenuDeBanc()
        texte = self.creer(menu, posture="open")
        self.assertNotIn("provision:", texte)

    def test_what_the_host_cannot_offer_is_said_on_linux(self):
        """Sans socket_vmnet — qui n'existe que sur macOS — l'invité sort
        mais ne se laisse pas joindre. Ce n'est pas un refus : le
        confinement n'est pas en cause, et le taire le serait."""
        texte = self.creer(MenuDeBanc(), posture="open", macos=False)
        self.assertIn(
            f"{t('Not held for this posture:')} reachable-address", texte
        )

    def test_macos_has_that_posture_limit_no_more(self):
        """DEUX QUESTIONS VOISINES, deux phrases. Sur macOS l'adresse
        joignable est POSSIBLE : la posture ne bute sur rien, et si elle
        manque encore c'est que personne ne l'a demandée — ce que dit
        l'autre phrase, celle de la configuration."""
        texte = self.creer(MenuDeBanc(), posture="open", macos=True)
        self.assertNotIn(t("Not held for this posture:"), texte)
        self.assertIn(
            f"{t('Not held by this config:')} reachable-address", texte
        )


class TestLEcranNePrometPasPlusQueLaTable(CasDeMenu):
    """La table dit QUEL gestionnaire fait autorité, pas que Lima y soit.

    Son commentaire est explicite : « Ce qu'elle n'affirme pas : que Lima y
    soit publié. Le gestionnaire le dit lui-même. » La phrase de l'écran
    affirmait pourtant « le gestionnaire le fournit » — et sur un hôte où
    le paquet n'existe pas, la commande conseillée échoue sur « impossible
    de trouver la cible », sans que rien ne dise quoi faire ensuite.

    Les deux routes peuvent être fermées en même temps : le gestionnaire
    est là et ne publie rien, et la table épinglée est vide par principe.
    C'est le cas qu'il faut nommer.
    """

    def phrase(self):
        return lima_menu.TOOL_SENTENCES[I.MANAGER]

    def test_it_does_not_claim_the_manager_provides_it(self):
        self.assertNotIn("provides it", self.phrase())

    def test_it_says_the_manager_is_the_one_to_ask(self):
        """C'est ce que la table affirme, et rien de plus."""
        self.assertIn("ask", self.phrase().lower())

    def test_it_says_what_to_do_when_the_answer_is_no(self):
        """Sans cela, l'utilisateur reste devant l'erreur du gestionnaire,
        qui ne connaît ni la table épinglée ni ce qui la remplit."""
        self.assertIn("RELEASES", self.phrase())

    def test_every_refusal_still_has_a_sentence(self):
        """Un verdict sans phrase s'afficherait vide, ce qui se lit comme
        « rien à signaler »."""
        for refus in I.REFUSALS:
            with self.subTest(refus=refus):
                self.assertTrue(lima_menu.TOOL_SENTENCES.get(refus))


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
        """Les chaînes du CODE qui nomment l'outil, docstrings
        exclues. La mécanique vit dans `test/code_literals.py` : ce
        contrôle a été recopié trois fois, et la troisième copie
        levait un TypeError sur une expression conditionnelle.
        """
        from code_literals import literals_matching

        return literals_matching(source, "limactl")

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


class TestInstallerErplibreDansUneInstance(CasDeMenu):
    """LE MÊME LANCEUR QUE LES AUTRES BACKENDS, et la clé qui manquait.

    `handle_of` lit la clé « lima » depuis toujours pour bâtir une fiche
    d'instance, et rien sous `script/` ne l'écrivait : le backend était
    complet, éprouvé, et inatteignable. Cette entrée l'écrit.

    Rien n'est lancé : `launch_installs` est intercepté, et ce qui est
    éprouvé est ce qu'il AURAIT reçu.
    """

    VIVE = L.Instance("vive", "Running", "arm64", "60022")

    def lancer(self, menu, reponses, instances=None):
        appels = []
        with patch.object(
            menu, "_lima_select", return_value="vive"
        ), patch.object(
            lima_menu,
            "launch_installs",
            side_effect=lambda *a, **k: appels.append((a, k))
            or "/tmp/manifeste-de-banc.json",
        ), patch(
            "builtins.input", side_effect=list(reponses)
        ):
            texte = sortie(menu._lima_install_erplibre)
        return texte, appels

    def menu(self):
        menu = MenuDeBanc(instances=(self.VIVE,))
        menu._qemu_repo_branch = lambda: "ma-branche"
        menu._qemu_install_dir = staticmethod(
            lambda prod: "/opt/erplibre" if prod else "$HOME/git/erplibre"
        )
        menu._qemu_erplibre_remote_cmd = (
            lambda branche, prod=False, **k: f"set -e; clone {branche} {prod}"
        )
        return menu

    def test_it_writes_the_key_that_names_the_backend(self):
        """SANS ELLE, `handle_of` rebâtirait une fiche libvirt et
        l'installation partirait vers un domaine local homonyme."""
        _texte, appels = self.lancer(self.menu(), ["", "n", "o"])
        self.assertEqual(1, len(appels))
        vms = appels[0][0][0]
        self.assertEqual([{"name": "vive", "ip": "vive", "lima": True}], vms)

    def test_the_handle_built_from_it_is_an_instance(self):
        """Le contrôle qui compte : c'est `handle_of` qui relira ce
        dictionnaire, et lui seul décide du backend."""
        from script.vm.backend import LIMA, handle_of

        _texte, appels = self.lancer(self.menu(), ["", "n", "o"])
        fiche = handle_of(appels[0][0][0][0])
        self.assertEqual(LIMA, fiche.backend)
        self.assertEqual("vive", fiche.key)

    def test_the_branch_defaults_to_the_current_one(self):
        """On déploie le plus souvent ce qu'on a sous les yeux."""
        _texte, appels = self.lancer(self.menu(), ["", "n", "o"])
        self.assertEqual("ma-branche", appels[0][0][1])

    def test_a_typed_branch_wins(self):
        """Contrôle positif : un défaut qui gagne toujours retirerait le
        choix."""
        _texte, appels = self.lancer(self.menu(), ["autre", "n", "o"])
        self.assertEqual("autre", appels[0][0][1])

    def test_an_empty_branch_and_no_current_one_cancels(self):
        """Cloner une branche vide échouerait dans l'invité, loin d'ici."""
        menu = self.menu()
        menu._qemu_repo_branch = lambda: ""
        _texte, appels = self.lancer(menu, ["", "n", "o"])
        self.assertEqual([], appels)

    def test_refusing_launches_nothing(self):
        _texte, appels = self.lancer(self.menu(), ["", "n", "n"])
        self.assertEqual([], appels)

    def test_the_production_layout_travels(self):
        _texte, appels = self.lancer(self.menu(), ["", "o", "o"])
        self.assertIn("True", appels[0][0][2])
        _texte, appels = self.lancer(self.menu(), ["", "n", "o"])
        self.assertIn("False", appels[0][0][2])

    def test_it_says_how_one_enters_the_instance(self):
        """La ligne se recopie : « ssh compte@vive » échouerait chez qui la
        recopie, et le message de ssh ne dirait pas pourquoi."""
        texte, _appels = self.lancer(self.menu(), ["", "n", "n"])
        self.assertIn("limactl shell vive", texte)
        self.assertNotIn("ssh ", texte)

    def test_it_does_not_dump_the_whole_remote_script(self):
        """Elle fait plusieurs milliers de caractères : la déverser
        noierait les trois lignes qui décident."""
        texte, _appels = self.lancer(self.menu(), ["", "n", "n"])
        self.assertNotIn("set -e; clone", texte)
        self.assertIn("characters", texte)

    def test_it_names_where_the_install_lands(self):
        texte, _appels = self.lancer(self.menu(), ["", "n", "n"])
        self.assertIn("$HOME/git/erplibre", texte)

    def test_it_only_offers_a_running_instance(self):
        """Installer dans une instance éteinte ferait échouer le canal
        d'exec, et le refus de l'outil ne dirait pas que le choix était le
        mauvais."""
        menu = self.menu()
        vus = []
        with patch.object(
            menu, "_lima_select", side_effect=lambda **k: vus.append(k) or ""
        ):
            sortie(menu._lima_install_erplibre)
        self.assertEqual([{"running": True}], vus)

    def test_it_asks_for_neither_desktop_nor_graphical_tools(self):
        """La configuration d'instance n'expose AUCUN affichage — c'est
        écrit dans `render_config` — donc un bureau ne serait vu par
        personne."""
        vus = {}
        menu = self.menu()
        menu._qemu_erplibre_remote_cmd = (
            lambda branche, **k: vus.update(k) or "set -e; clone"
        )
        self.lancer(menu, ["", "n", "o"])
        self.assertNotIn("desktop", vus)
        self.assertNotIn("tools", vus)

    def test_the_manifest_path_is_shown(self):
        """C'est par lui que le tableau de bord rouvre le suivi."""
        texte, _appels = self.lancer(self.menu(), ["", "n", "o"])
        self.assertIn("/tmp/manifeste-de-banc.json", texte)


class TestLesDeuxEntreesQuiNeDifferentQueParUnMot(CasDeMenu):
    """« Démarrer » et « Arrêter » mènent à la MÊME méthode.

    La table de cohérence de `test_todo_menu.py` compare des noms de
    méthode : elle ne peut donc pas les distinguer. Or les confondre fait
    DÉMARRER ce qu'on voulait arrêter — et le filtre d'état propose alors
    la mauvaise liste, si bien que le menu ne montre même pas l'instance
    qu'on visait.

    L'épreuve porte sur le COMPORTEMENT et non sur le texte : le menu est
    piloté, et ce qui compte est l'argument reçu.
    """

    def piloter(self, *reponses):
        """Le menu, conduit par ces réponses, puis « 0 » pour sortir."""
        recus = []
        menu = MenuDeBanc()
        menu.fill_help_info = lambda choix: "> "
        menu._lima_power = lambda action: recus.append(action)
        with patch.object(
            lima_menu.click, "prompt", side_effect=list(reponses) + ["0"]
        ):
            sortie(menu.prompt_execute_lima)
        return recus

    def test_the_bench_actually_drives_the_menu(self):
        """Contrôle du banc : un pilotage muet rendrait une liste vide, et
        les deux épreuves suivantes passeraient sans rien mesurer."""
        self.assertEqual(["start"], self.piloter("4"))

    def test_entry_four_starts_and_entry_five_stops(self):
        self.assertEqual(["start"], self.piloter("4"))
        self.assertEqual(["stop"], self.piloter("5"))

    def test_they_are_not_the_same_action(self):
        """L'épreuve qui tombe si un jour les deux rangs se recopient."""
        self.assertNotEqual(self.piloter("4"), self.piloter("5"))

    def test_every_entry_reaches_its_own_method(self):
        """Un « elif » décalé ferait lancer le voisin sous le libellé
        attendu, et la suppression est à un rang de l'ouverture d'un
        shell."""
        attendus = {
            "1": "_lima_tool",
            "2": "_lima_list",
            "3": "_lima_create",
            "6": "_lima_delete",
            "7": "_lima_shell",
            "8": "_lima_install_erplibre",
        }
        for rang, methode in attendus.items():
            with self.subTest(rang=rang, methode=methode):
                vus = []
                menu = MenuDeBanc()
                menu.fill_help_info = lambda choix: "> "
                setattr(menu, methode, lambda: vus.append(methode))
                with patch.object(
                    lima_menu.click, "prompt", side_effect=[rang, "0"]
                ):
                    sortie(menu.prompt_execute_lima)
                self.assertEqual([methode], vus)

    def test_an_unknown_entry_runs_nothing(self):
        menu = MenuDeBanc()
        menu.fill_help_info = lambda choix: "> "
        with patch.object(lima_menu.click, "prompt", side_effect=["99", "0"]):
            texte = sortie(menu.prompt_execute_lima)
        self.assertIn("not found", texte)

    def test_an_unproven_backend_is_flagged_on_every_pass(self):
        """Une note vue au premier passage ne tient pas au dixième.

        Le backend est POSÉ non éprouvé : le sien l'a été depuis, et une
        épreuve qui attendrait la note dans le dépôt tel qu'il est ne
        garderait plus rien — juste au moment où un autre backend pourrait
        arriver sans confrontation.
        """
        menu = MenuDeBanc()
        menu.fill_help_info = lambda choix: "> "
        with patch.dict(vm_backend.PROVEN, {vm_backend.LIMA: False}):
            with patch.object(lima_menu.click, "prompt", side_effect=["0"]):
                texte = sortie(menu.prompt_execute_lima)
        self.assertIn("*", texte)

    def test_a_proven_backend_carries_no_note(self):
        """Contrôle positif, et c'est l'état RÉEL du dépôt : la note part
        d'elle-même, sans qu'un écran soit retouché. La garder affichée
        enverrait choisir un autre backend pour une raison éteinte."""
        self.assertTrue(vm_backend.is_proven(vm_backend.LIMA))
        menu = MenuDeBanc()
        menu.fill_help_info = lambda choix: "> "
        with patch.object(lima_menu.click, "prompt", side_effect=["0"]):
            texte = sortie(menu.prompt_execute_lima)
        self.assertNotIn("*", texte)


if __name__ == "__main__":
    unittest.main()
