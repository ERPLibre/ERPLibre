#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'aide « ? » du formulaire de déploiement.

Une case cochée engage parfois huit poses, et son libellé n'en nomme que
trois : « Outils d'assistance IA » installe aussi les hooks git du dépôt, les
commandes Claude et une entrée d'historique. Ce que le formulaire fait ne
peut pas se lire seulement dans le code de la commande distante — on décide
devant l'écran, une heure avant que le journal ne le montre.

Ce que ces tests gardent :

- chaque outil du catalogue a une aide, et un outil ajouté sans texte fait
  tomber le test plutôt que d'afficher un bloc vide ;
- l'aide TRAVERSE le contexte : c'est le seul chemin jusqu'aux deux écrans,
  et un réglage qui n'y entre pas n'existe pas ;
- les DEUX formulaires l'ouvrent — c'est en n'en servant qu'un que l'écran
  Proxmox avait perdu la moitié des réglages ;
- la fenêtre se ferme sur Esc sans rien changer, et sans fermer l'écran qui
  la porte.
"""

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo.deploy_form_extras import (  # noqa: E402
    INSTALL_HELP,
    ExtrasMixin,
    extras_tables,
)
from script.todo.todo import TODO  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


def contexte():
    todo = TODO.__new__(TODO)
    mod = todo._qemu_import_module()
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    return todo._qemu_form_context(mod)


def contexte_proxmox():
    """Le contexte synthétique de l'écran Proxmox, plus le système invité.

    Chargé PAR SON CHEMIN, comme le fait test_qemu_ai_tools de deploy_qemu :
    « test » est aussi un paquet de la bibliothèque standard, et un import par
    son nom y mènerait. Le contexte lui-même n'est pas recopié — une seconde
    copie dériverait de celle que garde test_proxmox_form.
    """
    chemin = Path(__file__).resolve().parent / "test_proxmox_form.py"
    spec = importlib.util.spec_from_file_location("tpf_ctx", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    invite = TODO.__new__(TODO)._qemu_guest_context()
    return {**invite, **mod.contexte()}


class Ecran(ExtrasMixin):
    """Le mixin seul, sans Textual : les blocs sont du texte, pas des widgets."""

    def __init__(self, ctx):
        self._extras = extras_tables(ctx)


class LeCatalogue(unittest.TestCase):
    def test_every_tool_says_what_it_installs(self):
        """Un outil sans aide afficherait un bloc vide, ce qui se lit comme
        « il ne pose rien »."""
        for key, spec in TODO._QEMU_VM_TOOLS.items():
            with self.subTest(outil=key):
                self.assertTrue(spec.get("help"), key)
                for ligne in spec["help"]:
                    self.assertTrue(ligne.strip())

    def test_the_ai_tool_names_all_its_halves(self):
        """La case engage des installations ET une pré-configuration : celle
        qui n'est pas nommée est celle qu'on croit absente."""
        aide = " ".join(TODO._QEMU_VM_TOOLS["aidev"]["help"])
        for morceau in (
            "tig",
            "rtk",
            "starship",
            "zdiff3",
            "hooks",
            "commit",
            ".venv.erplibre/bin/activate",
        ):
            self.assertIn(morceau, aide)

    def test_the_help_crosses_the_context(self):
        """Le contexte est le seul chemin jusqu'aux deux écrans."""
        ctx = contexte()
        aides = ctx["vm_tool_help"]
        self.assertEqual(sorted(TODO._QEMU_VM_TOOLS), sorted(aides))
        for key, lignes in aides.items():
            self.assertTrue(lignes, key)

    def test_the_common_options_point_at_real_tables(self):
        """Une condition sur une clé inexistante lèverait au premier appel de
        l'aide, sur l'écran, devant l'utilisateur."""
        tab = extras_tables(contexte())
        for cle, titre, lignes in INSTALL_HELP:
            with self.subTest(titre=titre):
                if cle:
                    self.assertIn(cle, tab)
                self.assertTrue(titre.strip())
                self.assertTrue(lignes)


class LesBlocs(unittest.TestCase):
    def test_it_covers_the_common_settings_and_every_offered_tool(self):
        blocs = Ecran(contexte()).extras_help_blocks()
        titres = [titre for titre, _lignes in blocs]
        self.assertEqual(len(blocs), len(titres))
        for _key, label, _hint in extras_tables(contexte())["vm_tools"]:
            self.assertIn(label, titres)
        # Les réglages communs viennent d'abord : on lit l'écran de haut en
        # bas, et l'aide suit le même ordre.
        self.assertLess(len(INSTALL_HELP), len(blocs))

    def test_each_tool_block_ends_with_its_disk_cost(self):
        """Le disque est ce qui décide de cocher ou non sur une machine
        étroite : il est dans le bloc, pas seulement dans le libellé."""
        blocs = dict(Ecran(contexte()).extras_help_blocks())
        for _key, label, _hint in extras_tables(contexte())["vm_tools"]:
            self.assertRegex(blocs[label][-1], r"^\+\d+ Go$")

    def test_a_screen_without_tools_says_nothing_about_them(self):
        """Chaque accès aux tables est gardé : un formulaire n'est pas tenu
        d'offrir tous les réglages."""
        blocs = Ecran({}).extras_help_blocks()
        self.assertTrue(blocs)
        self.assertEqual(len(INSTALL_HELP) - 4, len(blocs))


def ouvre_l_aide(forme="qemu", touche="f1", saisie=False):
    """Ce que l'écran montre : {ouvert, texte, ferme, depart, piles}.

    Chaque forme apporte SON contexte : celui de l'autre écran lui manquerait
    la moitié de ses clés, et l'écran ne se monterait pas.
    """
    from script.todo.proxmox_deploy_form import run_proxmox_form
    from script.todo.qemu_deploy_form import run_deploy_form

    vu = {}

    async def scenario():
        app = (
            run_deploy_form(contexte(), run_app=False)
            if forme == "qemu"
            else run_proxmox_form(contexte_proxmox(), run_app=False)
        )
        async with app.run_test(size=(200, 60)) as pilote:
            await pilote.pause()
            if saisie:
                # Un champ de saisie avale les touches imprimables : c'est la
                # situation où « ? » ne peut pas servir, et F1 doit.
                from textual.widgets import Input

                app.set_focus(app.query_one("#f_key", Input))
                await pilote.pause()
            depart = app.screen.__class__.__name__
            await pilote.press(touche)
            await pilote.pause()
            vu["ouvert"] = app.screen.__class__.__name__
            vu["texte"] = " ".join(
                str(w.render()) for w in app.screen.query("Static")
            )
            await pilote.press("escape")
            await pilote.pause()
            vu["ferme"] = app.screen.__class__.__name__
            vu["depart"] = depart
            vu["piles"] = len(app.screen_stack)

    asyncio.run(scenario())
    return vu


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LEcran(unittest.TestCase):
    def test_f1_opens_it_on_both_forms(self):
        """C'est en ne servant qu'un des deux écrans que la moitié des
        réglages avait dérivé."""
        for forme in ("qemu", "proxmox"):
            with self.subTest(forme=forme):
                vu = ouvre_l_aide(forme)
                self.assertEqual("HelpScreen", vu["ouvert"])

    def test_the_question_mark_opens_it_too(self):
        """C'est la touche qu'on essaie d'abord, et le panneau l'a au montage
        — aucun champ de saisie ne prend le focus en arrivant."""
        vu = ouvre_l_aide("qemu", "?")
        self.assertEqual("HelpScreen", vu["ouvert"])

    def test_f1_is_the_one_that_works_from_a_text_field(self):
        """Un champ de saisie avale les touches imprimables : « ? » s'y écrit
        au lieu d'ouvrir, et c'est pourquoi F1 existe à côté."""
        self.assertEqual(
            "HelpScreen", ouvre_l_aide("qemu", "f1", saisie=True)["ouvert"]
        )
        self.assertNotEqual(
            "HelpScreen", ouvre_l_aide("qemu", "?", saisie=True)["ouvert"]
        )

    def test_escape_closes_it_and_leaves_the_form_standing(self):
        """Une aide qui fermerait le formulaire ferait perdre la saisie."""
        vu = ouvre_l_aide("qemu")
        self.assertEqual(vu["depart"], vu["ferme"])
        self.assertEqual(1, vu["piles"])

    def test_what_it_shows_is_what_the_option_installs(self):
        vu = ouvre_l_aide("qemu")
        for morceau in ("tig", "zdiff3", "hooks"):
            self.assertIn(morceau, vu["texte"])


if __name__ == "__main__":
    unittest.main()
