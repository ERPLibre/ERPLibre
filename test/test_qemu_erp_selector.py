#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sélecteur ERP puis Version des déploiements QEMU et Proxmox.

Ce que ces tests gardent :

- les versions d'Odoo viennent de conf/supported_version_erplibre.json, la
  plus récente d'abord, les dépréciées marquées, « default » en défaut ;
  Dolibarr n'offre que sa version épinglée ;
- les commandes installées sont celles des profils d'avant le sélecteur,
  défaut compris ;
- « Aucun » offre les profils sans ERP à la place des versions ;
- la spec porte l'ERP et la version à côté de la commande, et une spec qui
  ne les porte pas se juge sur sa commande ;
- l'invite pose l'ERP puis la version ;
- dans les deux écrans : le choix commun, la surcharge d'une rangée, et
  l'historique qui revient sur un changement d'ERP.
"""

import asyncio
import contextlib
import io
import json
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

from script.todo import qemu_erp as erp  # noqa: E402
from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.qemu_erp import dolibarr as qd  # noqa: E402
from script.todo.qemu_erp import odoo  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
ODOO_18 = "make install_os && make install_odoo_18"
ODOO_17 = "make install_os && make install_odoo_17"
ODOO_16 = "make install_os && make install_odoo_16"
TOUTES = "make install_os && make install_odoo_all_version"
PVE = "./script/proxmox/install_proxmox.sh"


def json_conf(nom):
    return json.loads((RACINE / "conf" / nom).read_text(encoding="utf-8"))


class TestLesVersions(unittest.TestCase):
    def test_odoo_versions_come_from_the_json(self):
        data = json_conf("supported_version_erplibre.json").values()
        attendues = sorted(
            (e["odoo_version"] for e in data),
            key=lambda v: tuple(int(p) for p in v.split(".")),
            reverse=True,
        )
        cles = [v.key for v in odoo.APP.versions()]
        self.assertEqual(attendues + [odoo.ALL_VERSIONS], cles)
        defaut = next(e["odoo_version"] for e in data if e.get("default"))
        self.assertEqual(defaut, odoo.APP.default_version())

    def test_deprecated_versions_say_so(self):
        data = json_conf("supported_version_erplibre.json").values()
        obsoletes = {e["odoo_version"] for e in data if e.get("is_deprecated")}
        self.assertTrue(obsoletes)
        for v in odoo.APP.versions():
            with self.subTest(v.key):
                self.assertEqual(v.key in obsoletes, v.deprecated)
                if v.deprecated:
                    self.assertEqual(t("%s (deprecated)") % v.key, v.label)

    def test_dolibarr_offers_its_pinned_version_only(self):
        pin = json_conf("supported_version_dolibarr.json")["version"]
        versions = qd.APP.versions()
        self.assertEqual([pin], [v.key for v in versions])
        self.assertEqual(qd.INSTALL_CMD, qd.APP.install_cmd_for(pin))

    def test_a_version_gives_the_command_it_always_had(self):
        self.assertEqual(ODOO_17, odoo.APP.install_cmd_for("17.0"))
        self.assertEqual(ODOO_18, odoo.APP.install_cmd_for(""))
        self.assertEqual(TOUTES, odoo.APP.install_cmd_for("all"))
        self.assertEqual("", odoo.APP.install_cmd_for("11.0"))
        self.assertEqual("17.0", odoo.APP.version_for_cmd(f"  {ODOO_17}\n"))
        self.assertIsNone(odoo.APP.version_for_cmd(PVE))

    def test_the_profiles_install_what_they_installed_before(self):
        todo = TODO.__new__(TODO)
        profils = todo._qemu_install_profiles()
        cmds = [c for _l, c in profils]
        avant = {
            *(
                f"make install_os && make install_odoo_{v}"
                for v in ("18", "17", "16", "15", "14", "13", "12")
            ),
            TOUTES,
            "make install_os && ./script/install/install_erplibre.sh",
            qd.INSTALL_CMD,
            "make install_os && ./mobile/install_and_run.sh",
            todo._QEMU_ERPLIBRE_VENV_CMD
            + " && ./script/install/install_erplibre_home.sh",
            "make install_os && make install_dev && " + todo._QEMU_QEMU_PKGS,
            PVE,
        }
        self.assertEqual(avant, set(cmds))
        self.assertEqual(len(avant), len(cmds))
        self.assertEqual(("ERPLibre + Odoo 18", ODOO_18), profils[0])


class TestLeSelecteur(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.choix = erp.Choices(self.todo._qemu_install_profiles())

    def test_the_erp_list_is_the_registry_then_none(self):
        self.assertEqual(
            [erp.APP_ODOO, erp.APP_DOLIBARR, erp.APP_NONE],
            [k for _n, k in self.choix.apps],
        )
        self.assertEqual(t("No ERP"), self.choix.apps[-1][0])

    def test_none_offers_the_profiles_without_erp(self):
        self.assertEqual(
            self.todo._qemu_other_profiles(),
            self.choix.options(erp.APP_NONE),
        )

    def test_every_profile_comes_back_through_its_choice(self):
        for label, cmd in self.todo._qemu_install_profiles():
            with self.subTest(label):
                app, valeur = self.choix.of_cmd(cmd)
                self.assertEqual(cmd, self.choix.cmd(app, valeur))
                self.assertEqual(label, self.choix.label_of_cmd(cmd))

    def test_the_default_is_odoo_and_its_default_version(self):
        self.assertEqual((erp.APP_ODOO, "18.0"), self.choix.first())
        self.assertEqual(self.choix.first(), self.choix.of_cmd("inconnue"))

    def test_an_erp_without_profile_is_not_offered(self):
        choix = erp.Choices([("ERPLibre + Odoo 18", ODOO_18), ("PVE", PVE)])
        self.assertEqual(
            [erp.APP_ODOO, erp.APP_NONE], [k for _n, k in choix.apps]
        )
        self.assertEqual([("18.0", "18.0")], choix.options(erp.APP_ODOO))


class TestLaSpec(unittest.TestCase):
    def test_the_fields_follow_the_command(self):
        self.assertEqual(
            {"app": "odoo", "version": "17.0", "options": {}},
            erp.choice_fields(ODOO_17),
        )
        self.assertEqual(
            {"app": "none", "version": "", "options": {}},
            erp.choice_fields(PVE),
        )

    def test_build_spec_writes_them_per_vm_and_in_the_block(self):
        vms = [
            {"name": "a", "install_cmd": qd.INSTALL_CMD},
            {"name": "b", "install_cmd": ""},
        ]
        form = {
            "res_label": "x1",
            "ssh_key": "",
            "add_ssh_config": False,
            "parallelism": 1,
            "install": {"branch": "develop", "cmd": ODOO_16, "label": "16"},
        }
        spec = build_spec(vms, [], form)
        a, b = spec["vms"]
        pin = qd.APP.default_version()
        self.assertEqual(
            ("dolibarr", pin, {}),
            (a["app"], a["app_version"], a["app_options"]),
        )
        self.assertEqual(("", ""), (b["app"], b["app_version"]))
        # « version » reste celle du système de la VM.
        self.assertNotIn("version", b)
        self.assertEqual(
            ("odoo", "16.0", {}),
            tuple(spec["install"][k] for k in ("app", "version", "options")),
        )

    def test_an_old_spec_is_judged_on_its_command(self):
        ancienne = {
            "vms": [
                {
                    "name": "a",
                    "distro": "nixos",
                    "install_cmd": qd.INSTALL_CMD,
                },
                {"name": "b", "distro": "nixos", "install_cmd": ""},
            ],
            "install": {"branch": "develop", "cmd": ODOO_18},
        }
        neuve = json.loads(json.dumps(ancienne))
        build_spec(
            neuve["vms"],
            [],
            {
                "res_label": "",
                "ssh_key": "",
                "add_ssh_config": False,
                "parallelism": 1,
                "install": None,
            },
        )
        neuve["install"].update(erp.choice_fields(ODOO_18))
        self.assertIs(
            qd.APP, erp.vm_app(ancienne["vms"][0], ancienne["install"])
        )
        self.assertIs(
            odoo.APP, erp.vm_app(ancienne["vms"][1], ancienne["install"])
        )
        self.assertEqual(
            erp.install_refusals(ancienne), erp.install_refusals(neuve)
        )
        self.assertTrue(erp.install_refusals(ancienne))

    def test_the_app_key_is_read_first(self):
        vm = {"install_cmd": "commande-maison", "app": erp.APP_DOLIBARR}
        self.assertIs(qd.APP, erp.vm_app(vm, {}))
        self.assertIs(
            qd.APP, erp.vm_app({}, {"cmd": ODOO_18, "app": "dolibarr"})
        )


class TestLInvite(unittest.TestCase):
    def joue(self, reponses, distro="", systems=()):
        todo = TODO.__new__(TODO)
        suite = iter(reponses)
        with (
            contextlib.redirect_stdout(io.StringIO()) as sortie,
            mock.patch("builtins.input", lambda _p="": next(suite, "")),
        ):
            choix = todo._qemu_pick_install_profile(distro, systems=systems)
        return choix, sortie.getvalue()

    def test_blank_answers_give_odoo_18(self):
        (label, cmd), sortie = self.joue([])
        self.assertEqual(("ERPLibre + Odoo 18", ODOO_18), (label, cmd))
        self.assertIn(t("Which ERP?"), sortie)

    def test_the_version_is_asked_after_the_erp(self):
        (_l, cmd), sortie = self.joue(["1", "2"])
        self.assertEqual(ODOO_17, cmd)
        self.assertIn(t("Which version?"), sortie)
        self.assertIn(t("%s (deprecated)") % "12.0", sortie)

    def test_all_versions_is_the_last_odoo_choice(self):
        rang = str(len(odoo.APP.versions()))
        (_l, cmd), _s = self.joue(["1", rang])
        self.assertEqual(TOUTES, cmd)

    def test_none_offers_the_other_profiles(self):
        todo = TODO.__new__(TODO)
        autres = todo._qemu_other_profiles()
        rang = next(
            i for i, (_l, c) in enumerate(autres, 1) if c.endswith("home.sh")
        )
        (label, cmd), _s = self.joue(["3", str(rang)])
        self.assertEqual(autres[rang - 1], (label, cmd))

    def test_a_system_that_imposes_its_profile_is_the_default(self):
        (_l, cmd), sortie = self.joue([], distro="proxmox")
        self.assertEqual(PVE, cmd)
        self.assertIn(f"{t('No ERP')} *", sortie)

    def test_dolibarr_asks_no_version(self):
        (_l, cmd), sortie = self.joue(["2"], systems=("ubuntu",))
        self.assertEqual(qd.INSTALL_CMD, cmd)
        self.assertNotIn(t("Which version?"), sortie)


# ------------------------------------------------------------------ #
# Les deux écrans
# ------------------------------------------------------------------ #
FORMES = ("qemu", "proxmox")


def contextes():
    todo = todo_muet()
    with contextlib.redirect_stdout(io.StringIO()):
        qemu = todo._qemu_form_context(todo._qemu_import_module())
    pve = contexte_proxmox(todo)
    pve["install_profiles"] = todo._qemu_install_profiles()
    return {"qemu": qemu, "proxmox": pve}


CTX = contextes() if TEXTUAL else {}


def fabrique(nom):
    if nom == "qemu":
        from script.todo.qemu_deploy_form import run_deploy_form

        return run_deploy_form
    from script.todo.proxmox_deploy_form import run_proxmox_form

    return run_proxmox_form


async def calme(pilote, n=4):
    for _ in range(n):
        await pilote.pause()


def scenario(nom, gestes):
    """Monte l'écran `nom`, coche une Ubuntu, joue `gestes(app, pilote,
    vu)` et rend ce qu'ils ont relevé."""
    ctx = CTX[nom]
    rang = next(
        i
        for i, e in enumerate(ctx["catalog"]["amd64"])
        if e["distro"] == "ubuntu"
    )
    vu = {}

    async def corps():
        from textual.widgets import SelectionList

        app = fabrique(nom)(ctx, run_app=False)
        async with app.run_test(size=(220, 70)) as pilote:
            await calme(pilote)
            liste = app.query_one(SelectionList)
            liste.select(liste.get_option_at_index(rang).value)
            await calme(pilote)
            await gestes(app, pilote, vu)

    asyncio.run(corps())
    return vu


def versions_offertes(app, ident="#f_version"):
    from textual.widgets import Select

    return [
        v
        for _l, v in app.query_one(ident, Select)._options
        if v != Select.NULL
    ]


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLesEcrans(unittest.TestCase):
    def test_the_common_erp_changes_the_version_list(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Select

                    vu["depart"] = app._form_values()["install"]
                    app.query_one("#f_erp", Select).value = "dolibarr"
                    await calme(pilote)
                    vu["doli"] = versions_offertes(app)
                    vu["doli_rangee"] = versions_offertes(app, "#v0_ver")
                    vu["install"] = app._form_values()["install"]
                    app.query_one("#f_erp", Select).value = "odoo"
                    await calme(pilote)
                    vu["retour"] = (
                        app.query_one("#f_version", Select).value,
                        versions_offertes(app),
                    )

                vu = scenario(nom, gestes)
                pin = qd.APP.default_version()
                depart = vu["depart"]
                self.assertEqual(
                    (ODOO_18, "odoo", "18.0", {}),
                    tuple(
                        depart[k] for k in ("cmd", "app", "version", "options")
                    ),
                )
                self.assertEqual([pin], vu["doli"])
                self.assertEqual([pin], vu["doli_rangee"])
                self.assertEqual(
                    (qd.INSTALL_CMD, "dolibarr", pin),
                    tuple(vu["install"][k] for k in ("cmd", "app", "version")),
                )
                self.assertEqual("18.0", vu["retour"][0])
                self.assertEqual(
                    [v.key for v in odoo.APP.versions()], vu["retour"][1]
                )

    def test_the_common_version_reaches_the_rows(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Select

                    app.query_one("#f_version", Select).value = "17.0"
                    await calme(pilote)
                    vu["rangee"] = app.query_one("#v0_ver", Select).value
                    vu["install"] = app._form_values()["install"]
                    vu["vm"] = app.vms[0].get("install_cmd")

                vu = scenario(nom, gestes)
                self.assertEqual("17.0", vu["rangee"])
                self.assertEqual(ODOO_17, vu["install"]["cmd"])
                self.assertEqual("17.0", vu["install"]["version"])
                # La rangée suit le choix commun : aucune surcharge.
                self.assertEqual("", vu["vm"])

    def test_a_row_overrides_the_version_and_the_erp(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Select

                    app.query_one("#v0_ver", Select).value = "16.0"
                    await calme(pilote)
                    vm = app.vms[0]
                    vu["odoo16"] = (
                        vm["install_cmd"],
                        vm["app"],
                        vm["app_version"],
                    )
                    vu["commun"] = app._form_values()["install"]["cmd"]
                    app.query_one("#v0_erp", Select).value = "none"
                    await calme(pilote)
                    vm = app.vms[0]
                    vu["aucun"] = (vm["install_cmd"], vm["app"])
                    vu["versions"] = versions_offertes(app, "#v0_ver")

                vu = scenario(nom, gestes)
                self.assertEqual((ODOO_16, "odoo", "16.0"), vu["odoo16"])
                self.assertEqual(ODOO_18, vu["commun"])
                autres = TODO.__new__(TODO)._qemu_other_profiles()
                self.assertEqual((autres[0][1], "none"), vu["aucun"])
                self.assertEqual([c for _l, c in autres], vu["versions"])

    def test_undo_brings_back_the_erp_and_its_versions(self):
        # Les deux gestes se suivent de près : sans délai de fusion nul,
        # l'écho des saisies des rangées remontées les fondrait en une
        # entrée, et ctrl+z reviendrait à l'ouverture.
        for nom in FORMES:
            with (
                self.subTest(nom),
                mock.patch("script.todo.deploy_form_history.MERGE_DELAY", 0),
            ):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Select

                    app._hist_settle()
                    app.query_one("#f_version", Select).value = "16.0"
                    await calme(pilote)
                    app._hist_settle()
                    app.query_one("#f_erp", Select).value = "dolibarr"
                    await calme(pilote)
                    app._hist_settle()
                    await pilote.press("ctrl+z")
                    await calme(pilote, 6)
                    vu["defait"] = (
                        app.query_one("#f_erp", Select).value,
                        app.query_one("#f_version", Select).value,
                        versions_offertes(app),
                        app._form_values()["install"]["cmd"],
                    )
                    await pilote.press("ctrl+y")
                    await calme(pilote, 6)
                    vu["refait"] = (
                        app.query_one("#f_erp", Select).value,
                        app._form_values()["install"]["cmd"],
                    )

                vu = scenario(nom, gestes)
                erp_v, version, offertes, cmd = vu["defait"]
                self.assertEqual(
                    ("odoo", "16.0", ODOO_16), (erp_v, version, cmd)
                )
                self.assertEqual(
                    [v.key for v in odoo.APP.versions()], offertes
                )
                self.assertEqual(("dolibarr", qd.INSTALL_CMD), vu["refait"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
