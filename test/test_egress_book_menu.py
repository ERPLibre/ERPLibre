#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran du carnet : ce qu'il montre, et ce qu'il refuse de promettre.

Ni fichier de configuration, ni déploiement. Le mixin est instancié sans
passer par `TODO.__init__`, et le carnet est remplacé.

TROIS CHOSES QUE CES ÉPREUVES TIENNENT.

LE FICHIER SUIVI FERME L'ÉCRAN. Une adresse y part vers le dépôt public :
c'est la seule chose de cet écran qui soit une faute et non un réglage, et
elle se dit avant toute autre.

UNE SUPPRESSION NE PROMET QUE CE QU'ELLE PEUT. La fusion étend les listes :
retirer une adresse du carnet de la machine ne retire pas celle de
l'équipe. Le dire AVANT la confirmation, sinon la question porte sur une
suppression qu'on croit totale.

CE QUI MANQUE SE LIT AVANT LE FORMULAIRE. « VM paranoid » nomme sept rôles
et le déploiement refuse tant que l'un manque.
"""

import contextlib
import io as _io
import os
import sys
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.lib_valid import ValidationError  # noqa: E402
from script.todo import egress_book_menu as M  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.egress_book_menu import (  # noqa: E402
    EgressBookMenuMixin,
    role_hint,
    role_line,
)


class MenuDeBanc(EgressBookMenuMixin):
    def __init__(self):
        self.config_file = object()

    def fill_help_info(self, choix):
        return "> "

    def _is_yes(self, reponse):
        return (reponse or "").strip().lower() in ("o", "oui", "y", "yes")


def sortie(fonction, *args, **kwargs):
    tampon = _io.StringIO()
    with contextlib.redirect_stdout(tampon):
        fonction(*args, **kwargs)
    return tampon.getvalue()


class CasDeCarnet(unittest.TestCase):
    """La langue est ÉPINGLÉE : les clés SONT les chaînes anglaises."""

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"


class TestLaLigneDUnRole(CasDeCarnet):
    def test_a_shared_address_is_marked_and_not_separated(self):
        """Lue à part, elle se lirait comme un autre rôle — alors que la
        liste blanche les additionne dans la même règle."""
        ligne = role_line(
            "forge",
            ["203.0.113.7/32", "198.51.100.9/32"],
            ["198.51.100.9/32"],
        )
        self.assertIn("198.51.100.9/32 *", ligne)
        self.assertIn("203.0.113.7/32,", ligne)

    def test_an_address_of_this_machine_carries_no_mark(self):
        """Une marque permanente ne marque plus rien."""
        ligne = role_line("forge", ["203.0.113.7/32"], [])
        self.assertNotIn("*", ligne)

    def test_a_role_without_address_says_so(self):
        self.assertIn("no address", role_line("vault", [], []))

    def test_the_role_is_named_first(self):
        self.assertTrue(role_line("vault", [], []).startswith("vault"))


class TestCeQueLIndiceDit(CasDeCarnet):
    def test_it_gives_the_reason_the_symbol_carries(self):
        """Une copie de la raison divergerait de celle du dépôt."""
        from script.posture import allowlist

        indice = role_hint("dns-resolver")
        self.assertIn(allowlist.get("dns-resolver").reason, indice)

    def test_it_names_the_ports(self):
        self.assertIn("53", role_hint("dns-resolver"))

    def test_an_unknown_role_gives_nothing_and_does_not_crash(self):
        self.assertEqual("", role_hint("jamais-vu"))


class TestLeFichierSuiviFermeLEcran(CasDeCarnet):
    def test_it_refuses_before_offering_anything(self):
        """Ouvrir le menu puis signaler la fuite laisserait poser des
        adresses de plus pendant qu'une est déjà en route."""
        menu = MenuDeBanc()
        with patch.object(
            M.egress_book,
            "refuse_tracked",
            side_effect=ValidationError("forge est dans todo.json"),
        ), patch.object(M.click, "prompt", side_effect=AssertionError):
            texte = sortie(menu.prompt_execute_egress_book)
        self.assertIn("todo.json", texte)

    def test_a_clean_file_opens_the_menu(self):
        """Contrôle positif : refuser toujours fermerait l'écran."""
        menu = MenuDeBanc()
        with patch.object(
            M.egress_book, "refuse_tracked", return_value=None
        ), patch.object(M.click, "prompt", side_effect=["0"]):
            sortie(menu.prompt_execute_egress_book)


class TestUneSuppressionNePrometQueCeQuElleFait(CasDeCarnet):
    def oublier(self, partagees, reponse="o", retire=True):
        menu = MenuDeBanc()
        vus = []
        with patch.object(
            menu, "_book_pick_role", return_value="forge"
        ), patch.object(
            M.egress_book, "shared_networks", return_value=partagees
        ), patch.object(
            M.egress_book,
            "forget",
            side_effect=lambda r, config=None: vus.append(r) or retire,
        ), patch(
            "builtins.input", return_value=reponse
        ):
            return sortie(menu._book_forget), vus

    def test_it_names_what_will_stay_open_before_asking(self):
        """Après la confirmation, la question aurait porté sur une
        suppression qu'on croit totale."""
        texte, _vus = self.oublier(["198.51.100.9/32"])
        self.assertIn("will stay open", texte)
        self.assertIn("198.51.100.9/32", texte)

    def test_nothing_shared_means_no_warning(self):
        """Contrôle positif : avertir toujours ne dirait plus rien."""
        texte, _vus = self.oublier([])
        self.assertNotIn("will stay open", texte)

    def test_refusing_forgets_nothing(self):
        _texte, vus = self.oublier([], reponse="n")
        self.assertEqual([], vus)

    def test_accepting_forgets_from_this_machine(self):
        _texte, vus = self.oublier([], reponse="o")
        self.assertEqual(["forge"], vus)

    def test_a_role_absent_here_is_said_and_not_claimed(self):
        """Faux ne veut pas dire « pas d'adresse » : le rôle peut vivre
        dans le carnet de l'équipe."""
        texte, _vus = self.oublier([], reponse="o", retire=False)
        self.assertIn("nothing changed", texte)


class TestPoserUneAdresse(CasDeCarnet):
    def poser(self, saisie, ports="", role="forge"):
        menu = MenuDeBanc()
        vus = []

        def faux_save(r, reseaux, p=(), config=None):
            vus.append((r, list(reseaux), tuple(p)))

        with patch.object(
            menu, "_book_pick_role", return_value=role
        ), patch.object(M.egress_book, "save", side_effect=faux_save), patch(
            "builtins.input", side_effect=[saisie, ports]
        ):
            return sortie(menu._book_set), vus

    def test_a_comma_separated_list_becomes_several_networks(self):
        _texte, vus = self.poser("203.0.113.7, 198.51.100.9")
        self.assertEqual(["203.0.113.7", "198.51.100.9"], vus[0][1])

    def test_an_empty_entry_writes_nothing(self):
        menu = MenuDeBanc()
        vus = []
        with patch.object(
            menu, "_book_pick_role", return_value="forge"
        ), patch.object(
            M.egress_book, "save", side_effect=lambda *a, **k: vus.append(a)
        ), patch(
            "builtins.input", return_value=""
        ):
            texte = sortie(menu._book_set)
        self.assertEqual([], vus)
        self.assertIn("unchanged", texte)

    def test_no_port_means_the_repository_decides(self):
        """Les recopier ici en figerait une version."""
        _texte, vus = self.poser("203.0.113.7")
        self.assertEqual((), vus[0][2])

    def test_the_site_ports_travel_when_given(self):
        _texte, vus = self.poser("203.0.113.7", ports="2222, 8443")
        self.assertEqual((2222, 8443), vus[0][2])

    def test_a_refusal_is_shown_and_nothing_is_claimed(self):
        """Refusé À LA SAISIE : la faute de frappe se découvrait après un
        formulaire entier."""
        menu = MenuDeBanc()
        with patch.object(
            menu, "_book_pick_role", return_value="forge"
        ), patch.object(
            M.egress_book,
            "save",
            side_effect=ValidationError("« forge.example » est un nom"),
        ), patch(
            "builtins.input", side_effect=["forge.example", ""]
        ):
            texte = sortie(menu._book_set)
        self.assertIn("est un nom", texte)
        self.assertNotIn("Written for", texte)

    def test_it_warns_that_a_hostname_is_refused_before_asking(self):
        _texte, _vus = self.poser("203.0.113.7")
        # La phrase est imprimée avant la saisie ; on la retrouve dans la
        # sortie du même appel.
        texte, _v = self.poser("203.0.113.7")
        self.assertIn("HOSTNAME is refused", texte)


class TestCeQuiManqueAChaqueProfil(CasDeCarnet):
    def montrer(self, carnet, saisies=("n",), ecrits=None):
        """L'écran joué, avec les saisies bouchonnées.

        `input` EST BOUCHONNÉ même quand le chemin nominal ne le lit pas :
        l'écran propose désormais de poser ce qui manque, et une épreuve
        qui ne bouchonne pas attend sur l'entrée standard — elle rougit
        ici où stdin est fermé, et FIGE dans un terminal.
        """
        menu = MenuDeBanc()
        it = iter(saisies)
        ecrits = [] if ecrits is None else ecrits

        def saisie(*_a, **_k):
            return next(it)

        def ecrire(role, reseaux, ports, config=None):
            ecrits.append((role, list(reseaux), tuple(ports)))

        with patch.object(M.egress_book, "read", return_value=carnet):
            with patch.object(M.egress_book, "save", ecrire):
                with patch("builtins.input", saisie):
                    return sortie(menu._book_missing)

    def test_an_empty_book_says_which_profile_refuses(self):
        texte = self.montrer({})
        self.assertIn("VM paranoid", texte)
        self.assertIn("refuses to deploy", texte)
        self.assertIn("dns-resolver", texte)

    def test_the_profiles_that_need_nothing_are_marked_ready(self):
        """Contrôle positif : tout déclarer manquant ne dirait rien."""
        texte = self.montrer({})
        self.assertIn("✓ Sandbox", texte)

    def test_a_full_book_clears_the_confined_profile(self):
        complet = {
            r: ["203.0.113.7"]
            for r in (
                "dns-resolver",
                "ntp",
                "package-mirror",
                "python-index",
                "vault",
                "backup-target",
                "forge",
            )
        }
        texte = self.montrer(complet)
        self.assertIn("✓ VM paranoid", texte)
        self.assertNotIn("refuses to deploy", texte)


class TestPoserCeQuiManqueSansQuitterLEcran(CasDeCarnet):
    """La liste seule était un cul-de-sac.

    Il fallait retenir sept noms de rôle, revenir au menu, et les reposer
    un à un en retrouvant lequel servait à quoi. L'écran propose
    maintenant de les poser, et la question porte sur le SITE — « a-t-il
    un coffre ? » — et non sur l'envie de taper.
    """

    def jouer(self, saisies, carnet=None):
        menu = MenuDeBanc()
        it = iter(saisies)
        ecrits = []

        def ecrire(role, reseaux, ports, config=None):
            ecrits.append((role, list(reseaux), tuple(ports)))

        with patch.object(M.egress_book, "read", return_value=carnet or {}):
            with patch.object(M.egress_book, "save", ecrire):
                with patch("builtins.input", lambda *_a, **_k: next(it)):
                    return sortie(menu._book_missing), ecrits

    def test_declining_the_offer_writes_nothing(self):
        texte, ecrits = self.jouer(["n"])
        self.assertEqual([], ecrits)
        self.assertIn("refuses to deploy", texte)

    def test_accepting_writes_the_role_that_was_answered_yes(self):
        texte, ecrits = self.jouer(["o", "o", "198.51.100.5/32", "", "q"])
        self.assertEqual([("dns-resolver", ["198.51.100.5/32"], ())], ecrits)
        self.assertIn("After posting:", texte)

    def test_a_role_the_site_does_not_have_is_named_with_what_it_blocks(self):
        """« 3 rôles refusés » n'apprend pas lesquels, et c'est justement
        ce qu'il faut pour savoir quel profil reste hors de portée."""
        texte, ecrits = self.jouer(["o", "n", "q"])
        self.assertEqual([], ecrits)
        self.assertIn("Left aside:", texte)
        self.assertIn("dns-resolver", texte)
        self.assertIn("still blocks:", texte)
        self.assertIn("VM paranoid", texte)

    def test_q_stops_and_asks_nothing_more(self):
        """Sans arrêt, il faut répondre aux sept pour sortir de l'écran."""
        texte, _e = self.jouer(["o", "q"])
        self.assertNotIn("Left aside:", texte)

    def test_each_role_is_asked_once_not_once_per_profile(self):
        """Un rôle posé débloque d'un coup tous ceux qui l'attendaient ;
        le redemander ferait retaper la même adresse."""
        _t, _e = self.jouer(["o"] + ["n"] * 7)
        # Sept rôles manquent, sept questions et pas une de plus : si
        # l'écran bouclait par profil, l'itérateur serait vide avant la
        # fin et l'épreuve lèverait StopIteration.

    def test_nothing_missing_never_reaches_the_prompt(self):
        """Un écran qui pose une question quand tout va bien fait douter.

        L'itérateur est VIDE : toute lecture d'entrée lève ici.
        """
        complet = {
            r: ["203.0.113.7"]
            for r in (
                "dns-resolver",
                "ntp",
                "package-mirror",
                "python-index",
                "vault",
                "backup-target",
                "forge",
            )
        }
        texte, ecrits = self.jouer([], carnet=complet)
        self.assertEqual([], ecrits)
        self.assertIn("✓ VM paranoid", texte)

    def test_the_two_screens_share_one_way_to_ask_for_addresses(self):
        """« Poser » et « ce qui manque » demandent la même chose. Une
        seconde copie perdrait l'indice, le refus à la saisie ou les
        ports — et un chemin refuserait ce que l'autre accepte."""
        import inspect

        corps = inspect.getsource(M.EgressBookMenuMixin._book_set)
        self.assertIn("_book_write_role", corps)
        corps = inspect.getsource(M.EgressBookMenuMixin._book_missing)
        self.assertIn("_book_write_role", corps)


class TestLaFrontiereAvecLeModuleDuCarnet(CasDeCarnet):
    """Ici on demande et on affiche ; là-bas on lit, on contrôle, on écrit."""

    @staticmethod
    def source():
        chemin = os.path.join(RACINE, "script", "todo", "egress_book_menu.py")
        with open(chemin, encoding="utf-8") as fichier:
            return fichier.read()

    def test_the_screen_opens_no_file_and_parses_no_json(self):
        source = self.source()
        for interdit in ("json.", "CONFIG_FILE", "open("):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, source)

    def test_the_mixin_is_reachable_from_the_menu(self):
        """Le motif à éviter : un mixin écrit, éprouvé, jamais composé."""
        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.assertTrue(issubclass(TODO, EgressBookMenuMixin))
        self.assertTrue(hasattr(TODO, "prompt_execute_egress_book"))

    def test_the_deploy_menu_declares_where_the_entry_leads(self):
        with open(
            os.path.join(RACINE, "script", "todo", "todo.py"),
            encoding="utf-8",
        ) as fichier:
            self.assertIn(
                '"method": "prompt_execute_egress_book"', fichier.read()
            )


if __name__ == "__main__":
    unittest.main()
