#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La posture traverse l'écran et atteint la spec, ou elle n'existe pas.

Le backend est une LIGNE parce que ce chemin ne sait pas le piloter ; la
posture est un CHOIX parce qu'il sait la poser. C'est la seule différence
entre les deux, et elle décide de la forme du widget.

Une clé que `build_spec` ne recopie pas n'atteint jamais la spec — c'est
déjà arrivé au choix de suivi, et c'est pourquoi la traversée s'éprouve de
bout en bout plutôt qu'au seul endroit où on l'a écrite.

Ce que l'écran propose se lit sur l'ÉCRAN MONTÉ et non dans la source :
un test qui lit le fichier passe au vert sur un panneau qu'il ne lit plus.
"""

import asyncio
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.append(str(RACINE))

sys.argv = ["todo.py"]

from script.posture import registry as R  # noqa: E402
from script.posture import spec as S  # noqa: E402
from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False

# Le dict minimal que `build_spec` exige en accès direct.
FORM = {
    "res_label": "x1",
    "ssh_key": "",
    "install": None,
    "add_ssh_config": False,
    "parallelism": 1,
}


def contexte():
    todo = TODO.__new__(TODO)
    mod = todo._qemu_import_module()
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    return todo._qemu_form_context(mod)


class TestLaSpecLaTransporte(unittest.TestCase):
    def test_a_mute_spec_means_the_freest_posture(self):
        """Une spec écrite avant que les postures existent n'en nomme
        aucune, et doit continuer de se déployer comme avant."""
        self.assertEqual(
            R.DEFAULT_POSTURE, build_spec([], [], FORM)["posture"]
        )

    def test_what_the_form_says_reaches_the_spec(self):
        spec = build_spec([], [], dict(FORM, posture="paranoid"))
        self.assertEqual("paranoid", spec["posture"])

    def test_the_spec_reads_back_through_the_key_that_names_it(self):
        """La clé est nommée à un seul endroit : l'écrire à la main ici
        laisserait les deux se séparer sans que rien ne le dise."""
        spec = build_spec([], [], dict(FORM, posture="paranoid"))
        self.assertEqual("paranoid", S.posture_name(spec))
        self.assertIsNotNone(S.posture_of(spec))

    def test_it_sits_at_deployment_level_and_not_inside_install(self):
        """Dans « install », elle disparaîtrait dès qu'on décoche la case,
        emportant le réseau de la machine avec ce qu'on installe dedans."""
        spec = build_spec([], [], dict(FORM, posture="local-only"))
        self.assertIn("posture", spec)
        self.assertIsNone(spec["install"])

    def test_an_empty_choice_falls_back_and_does_not_erase(self):
        spec = build_spec([], [], dict(FORM, posture=""))
        self.assertEqual(R.DEFAULT_POSTURE, spec["posture"])


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestCeQueLEcranPropose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = contexte()

    @property
    def offertes(self):
        """Les noms de posture offerts, dans l'ordre où l'écran les met.

        Lus sur la clé que l'écran LIT VRAIMENT. Une seconde clé qui
        n'aurait plus que des épreuves pour lecteurs pourrait tomber en
        panne sans que rien ne le dise."""
        return [nom for _libelle, nom in self.ctx["posture_choices"]]

    def test_the_context_offers_every_posture_of_the_registry(self):
        """Une liste écrite à la main perdrait la cinquième le jour où
        elle arrive, sans que rien ne le dise."""
        self.assertEqual(R.posture_names(), self.offertes)

    def test_the_order_goes_from_freest_to_most_bounded(self):
        """On descend vers la contrainte, on n'y tombe pas par défaut."""
        self.assertEqual(R.DEFAULT_POSTURE, self.offertes[0])
        self.assertEqual(R.DEFAULT_POSTURE, self.ctx["posture"])

    def _monte(self, choix=None, essais=()):
        """Monte l'écran, choisit éventuellement, et rend ses valeurs.

        `essais` fait tenter des valeurs une à une : un Select REFUSE ce qui
        n'est pas dans ses options, si bien qu'accepter est la preuve que
        l'option existe — sans lire l'intérieur du widget, qui n'est pas à
        nous et change avec sa version.
        """
        from textual.widgets import Select

        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {"acceptes": [], "refuses": []}

        async def scenario():
            app = run_deploy_form(self.ctx, run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                widget = app.query_one("#f_posture", Select)
                vu["defaut"] = widget.value
                for valeur in essais:
                    try:
                        widget.value = valeur
                    except Exception:
                        vu["refuses"].append(valeur)
                    else:
                        vu["acceptes"].append(valeur)
                    await pilote.pause()
                if choix is not None:
                    widget.value = choix
                    await pilote.pause()
                vu["valeurs"] = app._form_values()

        asyncio.run(scenario())
        return vu

    def test_the_screen_offers_exactly_what_the_registry_knows(self):
        vu = self._monte(essais=tuple(R.posture_names()) + ("restricted",))
        self.assertEqual(R.posture_names(), vu["acceptes"])
        self.assertEqual(["restricted"], vu["refuses"])

    def test_the_screen_opens_on_the_freest_one(self):
        self.assertEqual(R.DEFAULT_POSTURE, self._monte()["defaut"])

    def test_the_real_data_box_comes_out_in_the_values(self):
        """Le maillon qui manquait au choix de suivi : le widget existe, et
        sa valeur n'est recopiée nulle part."""
        from textual.widgets import Checkbox

        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}

        async def scenario():
            app = run_deploy_form(self.ctx, run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                vu["defaut"] = app._form_values()["real_data"]
                app.query_one("#f_real_data", Checkbox).value = True
                await pilote.pause()
                vu["coche"] = app._form_values()["real_data"]

        asyncio.run(scenario())
        self.assertFalse(vu["defaut"])
        self.assertTrue(vu["coche"])

    def test_what_is_chosen_comes_out_in_the_values(self):
        """Le maillon qui manquait au choix de suivi : le widget existait,
        et sa valeur n'était recopiée nulle part."""
        vu = self._monte(choix="paranoid")
        self.assertEqual("paranoid", vu["valeurs"]["posture"])

    def test_the_untouched_screen_yields_the_freest_one(self):
        self.assertEqual(
            R.DEFAULT_POSTURE, self._monte()["valeurs"]["posture"]
        )

    def test_the_whole_way_through_from_the_screen_to_the_spec(self):
        """Bout en bout : ce que l'écran rend, la spec le porte."""
        valeurs = self._monte(choix="local-only")["valeurs"]
        spec = build_spec([], [], dict(FORM, posture=valeurs["posture"]))
        self.assertEqual("local-only", S.posture_name(spec))


if __name__ == "__main__":
    unittest.main()
