#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Redimensionnement du TERMINAL : aucun volet sous le minimum, aucun volet
poussé hors de l'écran, quelle que soit la taille ou la disposition.

Séparé de `test_mail_tui_resize.py` pour la durée : chaque cas monte
l'application à plusieurs tailles, et les deux moitiés tournent en
parallèle dans le lanceur unitaire.
"""

import os
import sys
import unittest

from script.todo.mail.tui import MAIL_LAYOUTS, PANE_SIZE_MIN

# Le module d'appui voisin, comme llm_fake_server : test/ n'est pas un
# paquet, son répertoire entre donc à la main dans le chemin.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mail_tui_resize_case import ResizeCase  # noqa: E402


class TestTerminalResizeRespectsMinimum(ResizeCase):
    """Fix round : un volet grandi, puis un TERMINAL rétréci sans qu'aucune
    touche ne soit pressée, ne repassait par aucune des actions qui
    bornent — la surcharge en ligne restait figée à l'ancienne valeur, et
    le voisin s'écrasait jusqu'à zéro, sans qu'aucune touche ne puisse le
    récupérer (le plafond du volet écrasé se calcule alors contre SA
    PROPRE région, déjà nulle). `on_resize` reborne maintenant contre
    l'espace RÉELLEMENT disponible à chaque redimensionnement du terminal
    — mesuré ici, jamais une classe ni une variable interne.
    """

    async def test_shrinking_the_terminal_keeps_every_pane_above_minimum(
        self,
    ):
        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            panes = app.query_one("#panes")
            folders = app.query_one("#folders")
            right = app.query_one("#right")
            list_pane = app.query_one("#list_pane")
            preview = app.query_one("#preview")

            for layout_id, _ in MAIL_LAYOUTS:
                while app.mail_layout != layout_id:
                    await pilot.press("v")
                    await pilot.pause()

                # Grandit le volet dossiers (focus par défaut) près du
                # maximum permis par le terminal 80x24 de départ.
                for _ in range(20):
                    await pilot.press("+")
                await pilot.pause()

                # 40x18 (aire de #panes ~15) : assez pour satisfaire les
                # planchers des TROIS volets même en « stacked », le pire
                # cas (folders>=4 ET #right>=8, puisque #right y héberge à
                # son tour list_pane/preview le long du MÊME axe -- voir
                # `_PANE_SIBLING_MIN`) ; en dessous de ~15, ce ne serait
                # plus une question de correctif mais de terminal
                # physiquement trop petit pour les trois planchers à la
                # fois, hors de portée de tout redimensionnement de volet.
                await pilot.resize_terminal(40, 18)
                await pilot.pause()
                await pilot.pause()  # laisse le correctif différé tourner

                folders_dim = app._pane_dimension(panes)
                list_dim = app._pane_dimension(right)

                for widget, dim, name in (
                    (folders, folders_dim, "folders"),
                    (right, folders_dim, "right"),
                    (list_pane, list_dim, "list_pane"),
                    (preview, list_dim, "preview"),
                ):
                    measured = getattr(widget.region, dim)
                    self.assertGreaterEqual(
                        measured,
                        PANE_SIZE_MIN,
                        f"disposition {layout_id!r} : {name}.{dim} ="
                        f" {measured}, attendu >= {PANE_SIZE_MIN}",
                    )

                # Repart d'un terminal et de tailles propres avant la
                # disposition suivante.
                await pilot.resize_terminal(80, 24)
                await pilot.pause()
                await pilot.pause()
                await pilot.press("0")
                await pilot.pause()

    async def test_growing_the_terminal_back_restores_the_stored_size(self):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            for _ in range(3):
                await pilot.press("+")
            await pilot.pause()

            list_pane = app.query_one("#list_pane")
            grown_width = list_pane.region.width

            await pilot.resize_terminal(40, 24)
            await pilot.pause()
            await pilot.pause()
            self.assertLess(list_pane.region.width, grown_width)

            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            await pilot.pause()
            # L'INTENTION (stockée, jamais écrasée par le rétrécissement
            # temporaire) revient dès que la place existe de nouveau.
            self.assertEqual(list_pane.region.width, grown_width)


class TestReSettlingDoesNotStarveTheUncustomizedSibling(ResizeCase):
    """Round 3 : `_apply_pane_size_for_slot` lisait `pane.region` juste
    après son PROPRE `self._clear_pane_size(slot)`, dans le MÊME appel --
    cette région est pré-rafraîchissement, exactement la même classe de
    bogue déjà corrigée pour la lecture de `#right`. Reproduit en poussant
    `#folders` à son plafond (11 pressions, `#right` = 8, `list_pane` déjà
    correctement à 4), puis en redéclenchant `_apply_pane_size_for_slot`
    une seconde fois SANS rien changer à `#folders` -- soit par une
    pression `+` de plus (déjà au plafond, donc sans effet sur `#folders`
    lui-même), soit par un redimensionnement du terminal. `list_pane`
    retombait alors à 3 et y restait, PAS transitoirement.

    N'affirme jamais un nombre précis (ce serait passer par parité, comme
    le test initial de ce correctif qui ne reproduisait pas ce cas) :
    seulement que chaque volet reste >= `PANE_SIZE_MIN`.
    """

    async def _grow_folders_to_ceiling(self, pilot):
        for _ in range(11):
            await pilot.press("+")
        await pilot.pause()

    def _assert_every_pane_at_or_above_minimum(self, app):
        folders = app.query_one("#folders")
        right = app.query_one("#right")
        list_pane = app.query_one("#list_pane")
        preview = app.query_one("#preview")
        for widget, name in (
            (folders, "folders"),
            (right, "right"),
            (list_pane, "list_pane"),
            (preview, "preview"),
        ):
            self.assertGreaterEqual(
                widget.region.width,
                PANE_SIZE_MIN,
                f"{name}.width = {widget.region.width}, attendu >="
                f" {PANE_SIZE_MIN}",
            )

    async def test_an_extra_no_op_grow_does_not_starve_list_pane(self):
        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await self._grow_folders_to_ceiling(pilot)
            # #folders est déjà à son plafond : cette pression ne le
            # change PAS, mais redéclenche quand même la correction de
            # list_pane.
            await pilot.press("+")
            await pilot.pause()

            self._assert_every_pane_at_or_above_minimum(app)

    async def test_a_clean_resize_after_reaching_the_ceiling_does_not_starve_list_pane(
        self,
    ):
        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await self._grow_folders_to_ceiling(pilot)

            await pilot.resize_terminal(81, 24)
            await pilot.pause()
            await pilot.pause()

            self._assert_every_pane_at_or_above_minimum(app)

    async def test_a_stored_list_pane_size_is_recapped_when_folders_grows(
        self,
    ):
        """Ce que `then=` sert encore à garantir, une fois le plancher
        confié à la feuille de style : la taille STOCKÉE de `list_pane` doit
        être re-bornée contre le `#right` qui RESTE après l'agrandissement
        de `#folders`, pas contre celui d'avant.

        Mesuré par le remplissage EXACT de `#right` par ses trois enfants :
        une taille bornée contre un `#right` périmé les fait déborder, ce
        qu'aucune assertion de plancher ne verrait — `min-width` maintient
        alors chaque volet au-dessus de son plancher pendant que la somme
        dépasse le conteneur.
        """
        from textual.widgets import DataTable, Tree

        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            # Une taille de `list_pane` VOULUE par l'utilisateur, donc
            # stockée -- sans elle, rien à re-borner ici.
            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            for _ in range(3):
                await pilot.press("+")
            await pilot.pause()

            app.query_one("#folders", Tree).focus()
            await pilot.pause()
            await self._grow_folders_to_ceiling(pilot)

            right = app.query_one("#right")
            list_pane = app.query_one("#list_pane")
            list_splitter = app.query_one("#list_splitter")
            preview = app.query_one("#preview")
            self.assertEqual(
                list_pane.region.width
                + list_splitter.region.width
                + preview.region.width,
                right.region.width,
                f"list_pane {list_pane.region.width} + barre"
                f" {list_splitter.region.width} + preview"
                f" {preview.region.width} != #right"
                f" {right.region.width}",
            )
            self._assert_every_pane_at_or_above_minimum(app)


class _PaneThatMisreportsItsRegion:
    """Un volet qui MENT sur sa propre région, et note qu'on la lui a
    demandée. Tout le reste (`styles` compris) passe au vrai widget, si bien
    qu'une taille posée à travers ce mandataire arrive réellement sur
    l'écran.

    Sert à prouver une propriété STRUCTURELLE plutôt qu'à rejouer un
    scénario : la taille d'un volet ne doit dépendre en RIEN de la région de
    ce volet, parce qu'à l'instant où elle serait lue elle est encore
    pré-rafraîchissement (voir `_apply_pane_size_for_slot`). Une propriété
    ne se teste pas en attendant qu'une course se produise — 3 % des
    exécutions, la raison pour laquelle ce bogue a survécu à trois
    corrections.
    """

    # TOUTES les façons d'obtenir la géométrie RENDUE d'un widget, pas la
    # seule qui a servi au bogue : n'intercepter que `region` interdirait
    # une ORTHOGRAPHE, pas la classe -- `pane.size` rentrerait par la
    # fenêtre et les 46 tests resteraient verts.
    _MEASURED = frozenset(
        {
            "region",
            "size",
            "content_region",
            "content_size",
            "outer_size",
            "container_size",
            "virtual_size",
            "window_region",
            "scrollable_content_region",
        }
    )

    def __init__(self, widget, lie, reads):
        self._widget = widget
        self._lie = lie
        self._reads = reads

    def __getattr__(self, name):
        # `_widget`/`_lie`/`_reads` sont des attributs d'instance : la
        # recherche normale les trouve, `__getattr__` n'est jamais appelé
        # pour eux.
        if name in self._MEASURED:
            self._reads.append(f"{self._widget.id}.{name}")
            return self._lie
        return getattr(self._widget, name)


class TestPaneSizingIgnoresThePanesOwnRegion(ResizeCase):
    """Tâche 27. `_settle` prenait la région du volet comme base de bornage
    quand rien n'était stocké — une région que son PROPRE
    `_clear_pane_size`, deux lignes plus haut, venait d'invalider. Un
    `call_after_refresh` rendait la lecture juste presque toujours ; quand
    elle ne l'était pas, la base valait l'ancienne surcharge, le bornage
    retombait dessus, la branche « rien à corriger » sautait l'écriture, et
    `list_pane` restait DÉFINITIVEMENT à la part que la feuille de style lui
    donne (`2fr` de `#right`, soit 3 cellules).

    Les deux tests ci-dessous rendent ce cas DÉTERMINISTE.
    """

    async def _grow_folders_to_ceiling(self, pilot):
        for _ in range(11):
            await pilot.press("+")
        await pilot.pause()

    def _assert_every_pane_at_or_above_minimum(self, app):
        for name in ("#folders", "#right", "#list_pane", "#preview"):
            measured = app.query_one(name).region.width
            self.assertGreaterEqual(
                measured,
                PANE_SIZE_MIN,
                f"{name}.width = {measured}, attendu >= {PANE_SIZE_MIN}",
            )

    def _lie_about_pane_regions(self, app, lie, reads, calls):
        """Détourne `_pane_widgets` pour rendre un volet menteur, et note
        CHAQUE appel — les appels servent de contrôle positif : sans eux, un
        test qui n'affirme qu'une absence de lecture passerait tout aussi
        bien si le réglage des tailles n'avait pas tourné du tout.
        """
        original = app._pane_widgets

        def _patched(slot: str):
            calls.append(slot)
            pane, parent = original(slot)
            return _PaneThatMisreportsItsRegion(pane, lie, reads), parent

        app._pane_widgets = _patched

    async def test_the_floor_holds_even_when_the_pane_misreports_its_size(
        self,
    ):
        """Le volet rapporte EXACTEMENT le plancher : sous l'ancien code,
        `clamped == current` faisait sauter l'écriture et la feuille de
        style reprenait la main avec 3 cellules. Le plancher ne se mesure
        plus (`_PANE_MIN_CSS`), donc mentir ne peut plus l'abaisser.
        """
        from textual.geometry import Region

        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await self._grow_folders_to_ceiling(pilot)

            reads, calls = [], []
            self._lie_about_pane_regions(
                app,
                Region(0, 0, PANE_SIZE_MIN, PANE_SIZE_MIN),
                reads,
                calls,
            )
            await pilot.resize_terminal(81, 24)
            await pilot.pause()
            await pilot.pause()

            self.assertTrue(
                calls, "le réglage des tailles n'a pas tourné du tout"
            )
            self._assert_every_pane_at_or_above_minimum(app)

    async def test_settling_never_reads_the_region_of_the_pane_it_sizes(self):
        """La propriété elle-même, pas une de ses conséquences : aucune
        lecture, donc rien à lire trop tôt. Pour qu'une lecture périmée
        revienne, il faudrait la réintroduire ici — ce test l'interdit.
        """
        from textual.geometry import Region

        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await self._grow_folders_to_ceiling(pilot)

            reads, calls = [], []
            # Un redimensionnement du terminal, pas une touche `+`/`-` :
            # `_resize_focused_pane` lit LÉGITIMEMENT la région du volet (la
            # taille vive que l'utilisateur veut incrémenter), et cette
            # lecture-là ne suit aucun effacement.
            self._lie_about_pane_regions(
                app, Region(0, 0, 999, 999), reads, calls
            )
            await pilot.resize_terminal(81, 24)
            await pilot.pause()
            await pilot.pause()

            self.assertTrue(
                calls, "le réglage des tailles n'a pas tourné du tout"
            )
            self.assertEqual(
                reads,
                [],
                "le réglage des tailles a lu la région des volets"
                f" {reads} — une valeur encore pré-rafraîchissement",
            )
            # Et le mensonge n'a rien déréglé : la preuve que le chemin
            # exercé est bien le chemin mesuré.
            self._assert_every_pane_at_or_above_minimum(app)


class TestSmallTerminalsKeepEveryPaneOnScreen(ResizeCase):
    """Un volet qui DÉBORDE de son conteneur n'est pas seulement mal
    dimensionné : il n'est jamais composité. Aucune barre de défilement
    n'apparaît, `Tab` ne l'atteint pas, et rien à l'écran ne dit qu'il
    existe. C'est arrivé en « stacked » dès 80x20, dans l'état PAR DÉFAUT,
    sans qu'aucun test le voie : tous ceux qui approchent ces tailles
    pressent `+` d'abord, et une taille de `#folders` stockée réserve
    justement à `#right` de quoi tenir.

    `resolve_fraction_unit` (`_resolve.py:190-214`) épingle à son minimum
    tout enfant `fr` qui descendrait sous lui et le RETIRE du réservoir ;
    quand tous les frères `fr` s'épinglent, `1fr` vaut TOUT l'espace
    restant et chacun reçoit la totalité. Deux volets de 7 dans un
    conteneur de 8.

    Ces tests mesurent donc le REMPLISSAGE EXACT et la COMPOSITION, pas des
    planchers : un plancher tenu par un volet hors écran est tenu pour
    rien. Ils cassent aussi si Textual changeait la soustraction
    `border-box` de `_resolve_extrema`, qui décide ce que valent ces
    tailles.
    """

    # 13 lignes est le plancher réel de « stacked » : `#folders` ne descend
    # pas sous `PANE_SIZE_MIN`, `#right` a besoin d'au moins `PANE_SIZE_MIN`
    # + la barre pour que `#preview` garde une ligne, et `#panes` perd
    # l'en-tête, l'état et le pied. En dessous, aucune disposition des
    # trois volets ne tient — ce n'est plus un défaut de bornage.
    SMALL_SIZES = ((80, 20), (80, 18), (80, 16), (80, 14), (40, 18))

    def _assert_panes_fit_and_paint(self, app, label):
        panes = app.query_one("#panes")
        right = app.query_one("#right")
        outer = app._pane_dimension(panes)
        inner = app._pane_dimension(right)

        def measure(selector, dimension):
            return getattr(app.query_one(selector).region, dimension)

        outer_sum = (
            measure("#folders", outer)
            + measure("#folders_splitter", outer)
            + measure("#right", outer)
        )
        self.assertEqual(
            outer_sum,
            measure("#panes", outer),
            f"{label} : #folders + barre + #right = {outer_sum} !="
            f" #panes {measure('#panes', outer)} ({outer})",
        )
        inner_sum = (
            measure("#list_pane", inner)
            + measure("#list_splitter", inner)
            + measure("#preview", inner)
        )
        self.assertEqual(
            inner_sum,
            measure("#right", inner),
            f"{label} : #list_pane + barre + #preview = {inner_sum} !="
            f" #right {measure('#right', inner)} ({inner})",
        )

        # Le remplissage exact ne suffit pas à prouver qu'on VOIT les
        # volets : c'est le compositeur qui décide ce qui est peint.
        visible = app.screen._compositor.visible_widgets
        for selector in ("#folders", "#list_pane", "#preview"):
            self.assertIn(
                app.query_one(selector),
                visible,
                f"{label} : {selector} n'est pas composité — hors écran,"
                " sans barre de défilement ni accès au clavier",
            )

    async def test_a_fresh_launch_at_80x20_paints_every_pane(self):
        """Le scénario exact du signalement : premier lancement, aucune
        touche, une disposition par démarrage — pas un redimensionnement
        depuis une taille plus grande, qui n'emprunte pas le même chemin de
        montage.
        """
        from script.todo import todo_prefs

        for layout_id, _ in MAIL_LAYOUTS:
            todo_prefs.set("mail_layout", layout_id)
            app = await self._mounted_app(sessions=[self._fresh_session()])
            async with app.run_test(size=(80, 20)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.pause()
                await pilot.pause()

                self.assertEqual(app.mail_layout, layout_id)
                self._assert_panes_fit_and_paint(
                    app, f"lancement 80x20 en {layout_id!r}"
                )

    async def test_no_pane_is_pushed_off_screen_at_small_sizes(self):
        """La même garantie sur une plage de tailles et les trois
        dispositions, toujours SANS personnalisation — c'est l'absence de
        taille stockée qui déclenchait le défaut.
        """
        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            for width, height in self.SMALL_SIZES:
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                await pilot.pause()
                for layout_id, _ in MAIL_LAYOUTS:
                    while app.mail_layout != layout_id:
                        await pilot.press("v")
                        await pilot.pause()
                    await pilot.pause()
                    self._assert_panes_fit_and_paint(
                        app, f"{width}x{height} en {layout_id!r}"
                    )


if __name__ == "__main__":
    unittest.main()
