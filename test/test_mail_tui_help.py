#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La fenêtre d'aide, touche `h` : les raccourcis du client et quelques
repères, fermée par Échap.

Le piège que ce fichier existe pour interdire : une aide qui MENT. La liste
des touches est engendrée depuis `MailApp.BINDINGS` ; le test central
(`TestHelpIsGeneratedFromBindings`) vérifie donc l'ÉCRAN contre cette liste,
liaison par liaison, sans jamais répéter une touche en dur — ajouter une
liaison demain la fait apparaître sans toucher à ce fichier, tandis qu'une
liste recopiée à la main dans l'écran d'aide le ferait échouer.

Comme `test_mail_tui_splitter.py` : ce qui compte se mesure sur
l'application montée pour de vrai, et sur ce qui est RÉELLEMENT rendu
(`Compositor.render_strips`), jamais sur un attribut interne de l'écran.
"""
import os
import re
import tempfile
import unittest
from pathlib import Path

from script.todo import todo_i18n
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import Store
from script.todo.mail.tui import Session


def collapse(text: str) -> str:
    """Le texte, espaces (et retours à la ligne) réduits à un seul espace.

    Une description longue se replie sur plusieurs lignes DANS sa colonne :
    la chercher telle quelle dans le rendu échouerait alors sur un simple
    repli, pas sur une vraie absence. Rich replie aux limites de mots, donc
    cette normalisation la reconstitue.
    """
    return re.sub(r"\s+", " ", text)


class HelpCase(unittest.IsolatedAsyncioTestCase):
    """Monte `MailApp` pour de vrai, `$HOME` détourné vers un dossier
    jetable — même motif que `test_mail_tui_log.py` : `on_mount` lit
    `todo_prefs`, qui crée `~/.erplibre` s'il est absent.

    La langue est posée en écrivant `todo_i18n._current_lang`, JAMAIS par
    `todo_i18n.set_lang` : celle-ci réécrit `./env_var.sh`, un fichier réel
    du dépôt (`EL_LANG="fr"`) — un test ne doit pas changer la langue du
    poste de qui le lance. Elle est posée AVANT de monter l'application :
    `MailApp` est défini À L'INTÉRIEUR de `run_tui`, donc les `t()` de ses
    `BINDINGS` sont évalués à CET appel, pas à l'import du module.
    """

    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name
        self._old_lang = todo_i18n._current_lang

        self.cache_dir = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.account.cache_mode = "clear"
        self.store = Store(
            self.account, mode="clear", base=Path(self.cache_dir.name)
        )
        self.store.open()
        self.session = Session(self.account, self.store, None, password="x")

    def tearDown(self):
        self.store.close()
        todo_i18n._current_lang = self._old_lang
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()
        self.cache_dir.cleanup()

    async def _mounted_app(self, lang: str = "fr"):
        import textual.app

        from script.todo.mail.tui import run_tui

        todo_i18n._current_lang = lang
        captured = []
        orig_init = textual.app.App.__init__

        def capturing_init(app_self, *a, **kw):
            orig_init(app_self, *a, **kw)
            captured.append(app_self)

        textual.app.App.__init__ = capturing_init
        try:
            run_tui(run_app=False, sessions=[self.session])
        finally:
            textual.app.App.__init__ = orig_init
        return captured[-1]

    def screen_lines(self, app) -> list[str]:
        """Les lignes RÉELLEMENT à l'écran.

        `Compositor.render_strips` (`textual/_compositor.py:1185`, vérifié
        dans la source de Textual 8.2.8) compose tous les widgets visibles de
        l'écran courant et rend une bande par ligne — c'est exactement ce que
        le terminal recevrait. Un `Static.render()` dirait, lui, ce que le
        widget A ENVIE d'afficher, y compris quand il est hors du cadre ou
        caché derrière autre chose.
        """
        return [strip.text for strip in app.screen._compositor.render_strips()]

    def shortcut_rows(self, lines: list[str]) -> list[str]:
        """Les lignes du TABLEAU des raccourcis, découpées entre ses deux
        titres — jamais l'écran entier : la prose, elle, nomme aussi des
        touches, et un test qui ne saurait pas les distinguer passerait pour
        de mauvaises raisons.
        """
        from script.todo.todo_i18n import t

        start = next(
            index
            for index, line in enumerate(lines)
            if t("mail_help_keys_heading") in line
        )
        end = next(
            index
            for index, line in enumerate(lines)
            if t("mail_help_notes_heading") in line
        )
        return [
            line.strip() for line in lines[start + 1 : end] if line.strip()
        ]

    def shown_bindings(self, app) -> list:
        from textual.binding import Binding

        return [
            binding
            for binding in Binding.make_bindings(app.BINDINGS)
            if binding.show
        ]


class TestHelpOpensAndCloses(HelpCase):
    async def test_h_opens_the_help_window(self):
        from textual.screen import ModalScreen

        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            self.assertIn(
                t("mail_help_title"),
                collapse("\n".join(self.screen_lines(app))),
            )

    async def test_escape_closes_it_and_takes_its_text_off_the_screen(self):
        from textual.screen import ModalScreen

        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()
            self.assertIsInstance(app.screen, ModalScreen)

            await pilot.press("escape")
            await pilot.pause()

            self.assertNotIsInstance(app.screen, ModalScreen)
            # Fermée pour de vrai : plus rien de l'aide n'est rendu — un
            # `dismiss()` qui laisserait l'écran empilé passerait le premier
            # test (« ce n'est plus un ModalScreen ») sans passer celui-ci.
            self.assertNotIn(
                t("mail_help_title"),
                collapse("\n".join(self.screen_lines(app))),
            )

    async def test_h_pressed_twice_does_not_stack_a_second_help_window(self):
        """Un Échap doit suffire à sortir, même après avoir tapé `h` deux
        fois — ce que fait quelqu'un qui ne sait plus où il en est, donc
        exactement le public de cette fenêtre.

        C'est aussi le garde-fou de l'absence de `priority=True` sur `h`
        (voir `MailApp.BINDINGS`) : sans priorité, les liaisons de `MailApp`
        ne sont plus consultées dès qu'un écran modal est posé, donc le
        second `h` ne fait rien. AVEC une priorité, elles le sont encore
        (`App._check_bindings` lit alors la chaîne NON tronquée,
        `app.py:3978`), une deuxième aide s'empile, et cet Échap n'en
        referme qu'une : l'aide resterait à l'écran. Mesuré dans les deux
        sens — le raisonnement seul s'est déjà trompé une fois sur ce
        point.
        """
        from textual.screen import ModalScreen

        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            self.assertNotIn(
                t("mail_help_title"),
                collapse("\n".join(self.screen_lines(app))),
                "un second `h` a empilé une deuxième fenêtre d'aide",
            )
            self.assertNotIsInstance(app.screen, ModalScreen)


class TestHelpIsGeneratedFromBindings(HelpCase):
    """Le test qui vaut ce fichier : l'aide est vérifiée CONTRE
    `MailApp.BINDINGS`, jamais contre une liste écrite ici.
    """

    async def test_every_shown_binding_is_on_screen_with_its_description(self):
        app = await self._mounted_app()
        # Fenêtre haute : l'aide défile (voir `TestHelpFitsASmallWindow`),
        # or ce test-ci veut voir TOUTES les lignes à la fois.
        async with app.run_test(size=(100, 45)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()

            bindings = self.shown_bindings(app)
            # Garde-fou : une liste vide (ou amputée) ferait passer la boucle
            # ci-dessous sans rien vérifier du tout.
            self.assertGreaterEqual(len(bindings), 15)

            rows = self.shortcut_rows(self.screen_lines(app))
            joined = collapse(" ".join(rows))
            for binding in bindings:
                key_display = app.get_key_display(binding)
                self.assertTrue(
                    any(row.startswith(key_display) for row in rows),
                    f"touche {binding.key!r} absente de l'aide",
                )
                self.assertIn(
                    collapse(binding.description),
                    joined,
                    f"description de {binding.key!r} absente de l'aide",
                )

    async def test_the_table_has_exactly_one_row_per_shown_binding(self):
        """Une liaison MANQUANTE, mais aussi une touche EN TROP (celle que
        laisserait une liste recopiée après le retrait d'une liaison) : le
        compte des lignes du tableau attrape les deux. Vrai parce que la
        fenêtre de test est assez large pour qu'aucune description ne se
        replie sur une deuxième ligne.
        """
        app = await self._mounted_app()
        async with app.run_test(size=(100, 45)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()

            rows = self.shortcut_rows(self.screen_lines(app))
            self.assertEqual(len(rows), len(self.shown_bindings(app)))

    async def test_a_hidden_binding_is_not_listed_as_a_shortcut(self):
        """`escape` (« Retour », le plein écran) est `show=False` : le pied
        d'écran ne la montre pas, l'aide non plus. Son rôle DANS cette
        fenêtre — fermer — est dit en prose, pas emprunté à cette liaison.
        """
        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test(size=(100, 45)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()

            rows = self.shortcut_rows(self.screen_lines(app))
            self.assertNotIn(t("mail_back_binding"), " ".join(rows))
            # La prose, elle, dit bien comment sortir.
            screen = collapse("\n".join(self.screen_lines(app)))
            self.assertIn(collapse(t("mail_help_close_hint")), screen)

    async def test_symbol_keys_are_shown_as_symbols_not_as_words(self):
        """`Binding("plus", ...)` doit se lire `+`, pas « plus » — c'est ce
        que l'utilisateur presse.
        """
        app = await self._mounted_app()
        async with app.run_test(size=(100, 45)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()

            rows = self.shortcut_rows(self.screen_lines(app))
            bindings = {b.key: b for b in self.shown_bindings(app)}
            for key, symbol in (
                ("plus", "+"),
                ("minus", "-"),
                ("slash", "/"),
            ):
                description = bindings[key].description
                row = next(row for row in rows if description in row)
                self.assertTrue(
                    row.startswith(symbol),
                    f"{key!r} affichée « {row} » au lieu de « {symbol} »",
                )
                self.assertNotIn(key, row)

    async def test_upper_and_lower_case_keys_stay_distinguishable(self):
        """`r`/`R` et `a`/`A` sont quatre actions différentes : une aide qui
        les afficherait pareil enverrait l'utilisateur presser la mauvaise.
        """
        app = await self._mounted_app()
        async with app.run_test(size=(100, 45)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()

            rows = self.shortcut_rows(self.screen_lines(app))
            bindings = {b.key: b for b in self.shown_bindings(app)}
            for lower, upper in (("r", "R"), ("a", "A")):
                lower_row = next(row for row in rows if row.startswith(lower))
                upper_row = next(row for row in rows if row.startswith(upper))
                self.assertNotEqual(lower_row, upper_row)
                self.assertIn(bindings[lower].description, lower_row)
                self.assertIn(bindings[upper].description, upper_row)


class TestNoBindingFiresUnderAModalScreen(HelpCase):
    """La classe de bogues dont `h` et `z` ne sont que deux cas : SOUS un
    écran modal, AUCUNE liaison de `MailApp` ne doit se déclencher.

    Textual ne tronque la chaîne de liaisons au dernier écran modal que pour
    les liaisons SANS priorité (`Screen._modal_binding_chain`,
    `screen.py:449`, lue par `App._check_bindings`, `app.py:3978`). Une
    priorité posée sur n'importe quelle liaison de `MailApp` la ferait donc
    tourner pendant qu'un modal est à l'écran — mesuré : `z` y pose
    `fullscreen` sur `#panes` SANS que rien ne bouge (le modal couvre), et
    la classe est encore là après le renvoi du modal.

    Un test par touche ne garderait la classe que jusqu'où va notre patience
    à recopier. Ces deux-ci partent donc de `MailApp.BINDINGS` — la même
    source que le tableau de l'aide — et couvrent gratuitement la prochaine
    liaison ajoutée.
    """

    # `escape` est la seule touche exclue : sous un modal, elle regarde
    # LÉGITIMEMENT le modal (c'est sa liaison à lui qui la sert, et c'est
    # ainsi qu'on referme l'aide). Toutes les autres liaisons de `MailApp`
    # sont dans la boucle, sans exception — un jour où l'une d'elles
    # demanderait un traitement à part, c'est un signal à remonter, pas une
    # ligne à ajouter ici.
    KEYS_LEFT_TO_THE_MODAL = ("escape",)

    def _keys_under_test(self, app) -> list[tuple[str, str]]:
        """Les couples (touche, nom de l'action attendue), dans l'ordre de
        `MailApp.BINDINGS`."""
        from textual.binding import Binding

        pairs = []
        for binding in Binding.make_bindings(app.BINDINGS):
            # `Binding("home,ctrl+a", ...)` est légal chez Textual : une
            # liaison peut porter plusieurs touches.
            for key in binding.key.split(","):
                if key and key not in self.KEYS_LEFT_TO_THE_MODAL:
                    pairs.append((key, f"action_{binding.action}"))
        return pairs

    def _spy_on_every_action(self, app) -> list[str]:
        """Remplace chaque `action_*` visée par une liaison de `MailApp` par
        un mouchard qui n'appelle PAS l'action réelle.

        Deux raisons de ne pas rappeler l'original : `q` mettrait fin à
        l'application au milieu du test, et `c` empilerait un écran
        d'écriture qui avalerait les touches suivantes — la boucle
        s'arrêterait de mesurer après la première fuite au lieu de toutes
        les lister. Textual résout une action par
        `getattr(namespace, f"action_{nom}")`, donc poser l'attribut sur
        l'INSTANCE suffit à intercepter.
        """
        from textual.binding import Binding

        fired: list[str] = []
        for binding in Binding.make_bindings(app.BINDINGS):
            name = f"action_{binding.action}"

            def spy(_name=name):
                fired.append(_name)

            setattr(app, name, spy)
        return fired

    async def test_the_keys_do_fire_when_no_modal_is_open(self):
        """Le contrôle POSITIF, sans lequel le test suivant passerait aussi
        bien si `pilot.press` n'envoyait rien du tout.

        Les mêmes touches, la même boucle, mais sans écran modal : chacune
        doit déclencher SON action. Ce test garde aussi le mécanisme du
        mouchard lui-même (une action nommée autrement qu'en
        `action_<nom>` ne serait pas interceptée, et se verrait ici).
        """
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            pairs = self._keys_under_test(app)
            fired = self._spy_on_every_action(app)

            for key, _action in pairs:
                await pilot.press(key)
                await pilot.pause()

            # Liste ORDONNÉE, pas un compte : une touche muette compensée
            # par une autre qui tirerait deux fois passerait un simple
            # décompte, et le contrôle ne contrôlerait plus rien.
            self.assertEqual(fired, [action for _key, action in pairs])

    async def test_no_binding_fires_while_the_help_is_open(self):
        """La garantie : aucune de ces touches ne déclenche quoi que ce soit
        pendant que l'aide est posée.
        """
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()
            # Le mouchard est posé APRÈS l'ouverture : `action_show_help`
            # doit avoir tourné pour de vrai, c'est lui qui met le modal en
            # place.
            fired = self._spy_on_every_action(app)

            for key, _action in self._keys_under_test(app):
                await pilot.press(key)
                await pilot.pause()

            self.assertEqual(
                fired, [], f"des liaisons ont tourné sous le modal : {fired}"
            )

    async def test_the_client_underneath_is_untouched(self):
        """Le même parcours, mais avec les VRAIES actions en place : ce que
        les mouchards ne peuvent pas montrer, c'est l'état laissé derrière.

        Trois mesures, celles que la tâche 26 a prises à la main : l'aide est
        toujours l'écran actif, `#panes` n'a pas pris la classe `fullscreen`
        (l'effet SILENCIEUX qu'un `z` prioritaire produirait), et un SEUL
        Échap ramène le client entier — trois volets affichés.
        """
        from textual.screen import ModalScreen

        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()

            for key, _action in self._keys_under_test(app):
                await pilot.press(key)
                await pilot.pause()

            self.assertIn(
                t("mail_help_title"),
                collapse("\n".join(self.screen_lines(app))),
            )
            self.assertFalse(
                app.query_one("#panes").has_class("fullscreen"),
                "une touche a basculé le plein écran sous le modal",
            )

            await pilot.press("escape")
            await pilot.pause()

            self.assertNotIsInstance(app.screen, ModalScreen)
            for pane in ("#folders", "#list_pane", "#preview"):
                self.assertTrue(
                    app.query_one(pane).display,
                    f"{pane} a disparu après le passage sous le modal",
                )


class TestHelpDoesNotStealTyping(HelpCase):
    async def test_h_typed_in_the_search_box_types_an_h(self):
        """Taper « h » dans la recherche doit écrire un « h », jamais ouvrir
        l'aide.

        Ce test fixe le COMPORTEMENT, pas le mécanisme : il passe aussi avec
        `priority=True` sur `h` (mesuré), parce que `Screen._binding_chain`
        (`screen.py:428-435`, Textual 8.2.8) retire les liaisons de tout
        caractère imprimable dès que le widget focalisé déclare pouvoir le
        consommer (`Input.check_consume_key`) — avant la répartition, y
        compris prioritaire. Ce qui interdit vraiment la priorité est écrit
        là où elle serait posée (`MailApp.BINDINGS`), et gardé par
        `test_h_pressed_twice_does_not_stack_a_second_help_window`.
        """
        from textual.screen import ModalScreen
        from textual.widgets import Input

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("slash")
            await pilot.pause()
            self.assertIsInstance(app.focused, Input)

            await pilot.press("h")
            await pilot.pause()

            self.assertEqual(app.query_one("#search", Input).value, "h")
            self.assertNotIsInstance(app.screen, ModalScreen)


class TestHelpFitsASmallWindow(HelpCase):
    async def test_nothing_is_out_of_reach_in_a_small_terminal(self):
        """~19 raccourcis plus la prose ne tiennent pas dans 20 lignes : ce
        qui dépasse doit rester ATTEIGNABLE en défilant, jamais coupé pour
        toujours — c'est exactement la partie basse de la liste, donc les
        touches ajoutées en DERNIER, qu'une fenêtre sans ascenseur
        perdrait.
        """
        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test(size=(80, 20)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()

            body = app.screen.query_one("#help_body")
            # Sans ça, le test passerait aussi sur une fenêtre où tout tient
            # déjà — il ne prouverait plus rien du défilement.
            self.assertGreater(body.max_scroll_y, 0)
            first_screen = collapse(" ".join(self.screen_lines(app)))
            self.assertNotIn(collapse(t("mail_help_close_hint")), first_screen)

            seen = first_screen
            for _ in range(40):
                if body.scroll_offset.y >= body.max_scroll_y:
                    break
                body.scroll_relative(y=4, animate=False)
                await pilot.pause()
                seen += " " + collapse(" ".join(self.screen_lines(app)))

            for binding in self.shown_bindings(app):
                self.assertIn(
                    collapse(binding.description),
                    seen,
                    f"« {binding.description} » reste inatteignable",
                )
            self.assertIn(collapse(t("mail_help_close_hint")), seen)


class TestBindingDescriptionsAreTranslated(HelpCase):
    async def test_every_description_comes_from_the_translation_table(self):
        """Aucune description de `MailApp` ne doit rester écrite en dur.

        Formulation retenue : chaque description doit être la valeur `fr` ET
        `en` d'UNE MÊME clé `mail_*` de `TRANSLATIONS`. Deux formulations
        plus simples ont été écartées :

        - « la description diffère entre fr et en » serait FAUSSE pour une
          traduction légitimement identique dans les deux langues
          (« Sync »).
        - « la description est une valeur du dictionnaire » passerait pour
          une chaîne en dur comme « Quitter », qui est aussi la valeur `fr`
          de la clé générale `Quit`.

        Celle-ci n'a pas ces trous : une description en dur donnerait la même
        chaîne française dans les DEUX langues, et il faudrait pour la
        laisser passer une clé `mail_*` dont le `fr` et l'`en` valent tous
        deux ce français-là.
        """
        from textual.binding import Binding

        from script.todo.todo_i18n import TRANSLATIONS

        app_fr = await self._mounted_app(lang="fr")
        app_en = await self._mounted_app(lang="en")
        fr_bindings = list(Binding.make_bindings(app_fr.BINDINGS))
        en_bindings = list(Binding.make_bindings(app_en.BINDINGS))

        self.assertGreaterEqual(len(fr_bindings), 15)
        self.assertEqual(len(fr_bindings), len(en_bindings))
        for fr_binding, en_binding in zip(fr_bindings, en_bindings):
            self.assertEqual(fr_binding.key, en_binding.key)
            matches = [
                key
                for key, entry in TRANSLATIONS.items()
                if key.startswith("mail_")
                and entry.get("fr") == fr_binding.description
                and entry.get("en") == en_binding.description
            ]
            self.assertTrue(
                matches,
                f"description de {fr_binding.key!r} non traduite :"
                f" {fr_binding.description!r} (fr) /"
                f" {en_binding.description!r} (en)",
            )

    async def test_the_help_window_is_in_english_under_en(self):
        """La conséquence visible de la conversion : sous `en`, l'aide —
        dont TOUT le contenu vient de ces descriptions — est en anglais.
        """
        from script.todo.todo_i18n import t

        app = await self._mounted_app(lang="en")
        async with app.run_test(size=(100, 45)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("h")
            await pilot.pause()

            screen = collapse("\n".join(self.screen_lines(app)))
            self.assertIn(t("mail_help_title"), screen)
            self.assertIn(t("mail_add_account_binding"), screen)
            self.assertNotIn("Nouveau compte", screen)
            self.assertIn(collapse(t("mail_help_sync")), screen)


if __name__ == "__main__":
    unittest.main()
