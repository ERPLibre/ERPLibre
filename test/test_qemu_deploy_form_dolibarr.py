#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le profil Dolibarr dans les deux écrans de déploiement : la case
Production se grise et dit pourquoi, un système refusé est nommé sur sa
rangée, et F5 ne déploie rien qui serait refusé."""

import asyncio
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_todo_deploy_form_parity import (  # noqa: E402
    TEXTUAL,
    contexte_proxmox,
    todo_muet,
)

from script.dolibarr import lib_dolibarr  # noqa: E402
from script.todo import qemu_dolibarr as qd  # noqa: E402

NIXOS = {
    "distro": "nixos",
    "version": "25.11",
    "arch": "amd64",
    "name": "erplibre-nixos-2511",
    "ram": 2048,
    "disk": "40G",
}
FORMES = ("qemu", "proxmox")


def contextes():
    todo = todo_muet()
    profils = todo._qemu_install_profiles()
    with contextlib.redirect_stdout(io.StringIO()):
        qemu = todo._qemu_form_context(todo._qemu_import_module())
    pve = contexte_proxmox(todo)
    pve["install_profiles"] = profils
    pve["catalog"] = {"amd64": pve["catalog"]["amd64"] + [NIXOS]}
    doli = next(i for i, (_l, c) in enumerate(profils) if c == qd.INSTALL_CMD)
    return {"qemu": qemu, "proxmox": pve}, doli


CTX, DOLI = contextes() if TEXTUAL else ({}, 0)


def fabrique(nom):
    if nom == "qemu":
        from script.todo.qemu_deploy_form import run_deploy_form

        return run_deploy_form
    from script.todo.proxmox_deploy_form import run_proxmox_form

    return run_proxmox_form


def scenario(nom, distros, gestes):
    ctx = CTX[nom]
    rangs = {}
    for i, e in enumerate(ctx["catalog"]["amd64"]):
        rangs.setdefault(e["distro"], i)
    vu = {}

    async def corps():
        from textual.widgets import SelectionList

        app = fabrique(nom)(ctx, run_app=False)
        async with app.run_test(size=(220, 70)) as pilote:
            await pilote.pause()
            liste = app.query_one(SelectionList)
            for d in distros:
                liste.select(liste.get_option_at_index(rangs[d]).value)
            await pilote.pause()
            await pilote.pause()
            await gestes(app, pilote, vu)

    asyncio.run(corps())
    return vu


async def commun(app, pilote, rang):
    from textual.widgets import Select

    app.query_one("#f_profile_install", Select).value = rang
    await pilote.pause()
    await pilote.pause()


def spec_rendue(nom, app):
    return app._result["spec"] if nom == "qemu" else app.result


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLaProduction(unittest.TestCase):
    def test_choosing_dolibarr_greys_production_and_says_why(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Checkbox

                    case = app.query_one("#f_prod", Checkbox)
                    case.value = True
                    await commun(app, pilote, DOLI)
                    vu["grise"] = case.disabled
                    vu["note"] = app.query_one("#t_prod_note").display
                    vu["prod"] = app._form_values()["install"]["prod"]
                    await commun(app, pilote, 0)
                    vu["rendu"] = (
                        case.disabled,
                        app._form_values()["install"]["prod"],
                        app.query_one("#t_prod_note").display,
                    )

                vu = scenario(nom, ["ubuntu"], gestes)
                self.assertTrue(vu["grise"])
                self.assertTrue(vu["note"])
                self.assertFalse(vu["prod"])
                self.assertEqual((False, True, False), vu["rendu"])


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLesSystemesRefuses(unittest.TestCase):
    def test_a_nixos_row_says_why(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    await commun(app, pilote, DOLI)
                    vu["tetes"] = {
                        r["vm"]["distro"]: app._row_head(i, r)
                        for i, r in enumerate(app.rows)
                    }

                tetes = scenario(nom, ["ubuntu", "nixos"], gestes)["tetes"]
                self.assertIn(
                    f"✗ {qd.distro_refusal('nixos')}", tetes["nixos"]
                )
                self.assertNotIn("✗", tetes["ubuntu"])

    def test_f5_refuses_and_deploys_nothing(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    await commun(app, pilote, DOLI)
                    with mock.patch.object(type(app), "notify") as dit:
                        app.action_deploy()
                        await pilote.pause()
                    vu["dit"] = " ".join(
                        str(c.args[0]) for c in dit.call_args_list
                    )
                    vu["spec"] = spec_rendue(nom, app)

                vu = scenario(nom, ["ubuntu", "nixos"], gestes)
                self.assertIsNone(vu["spec"])
                self.assertIn(t_nixos(), vu["dit"])

    def test_a_per_vm_choice_is_judged_too(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Select

                    i = next(
                        k
                        for k, r in enumerate(app.rows)
                        if r["vm"]["distro"] == "nixos"
                    )
                    app.query_one(f"#v{i}_prof", Select).value = DOLI
                    await pilote.pause()
                    await pilote.pause()
                    vu["tete"] = app._row_head(i, app.rows[i])

                vu = scenario(nom, ["ubuntu", "nixos"], gestes)
                self.assertIn("✗", vu["tete"])

    def test_a_supported_plan_deploys_dolibarr_in_dev(self):
        async def gestes(app, pilote, vu):
            from textual.widgets import Checkbox

            app.query_one("#f_prod", Checkbox).value = True
            await commun(app, pilote, DOLI)
            app.action_deploy()
            await pilote.pause()
            vu["spec"] = app._result["spec"]

        install = scenario("qemu", ["ubuntu"], gestes)["spec"]["install"]
        self.assertEqual(qd.INSTALL_CMD, install["cmd"])
        self.assertFalse(install["prod"])


def t_nixos():
    from script.todo.todo_i18n import t

    return t(lib_dolibarr.NIXOS_DECLARE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
