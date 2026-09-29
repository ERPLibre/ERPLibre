#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La commande « db » d'ERPLibre sert-elle aussi un Odoo amont ?

Toute la gestion des bases — restauration, clone, sauvegarde, suppression —
passe par « ./odoo_bin.sh db », une commande du fork ERPLibre d'Odoo. Un
Odoo amont n'en a pas (10, 11) ou en a une d'une autre interface (19, 20).
odoo_bin.sh réécrit alors l'appel vers erplibre_db, un addon de ce dépôt,
et cet addon parle aux deux API de gestion des bases d'Odoo :
odoo.service.db jusqu'à 19, odoo.modules.db en 20.

Ce qui est gardé ici :

- la réécriture n'a lieu que si l'Odoo actif n'a pas la commande du fork, et
  ne touche aucune autre commande ;
- l'adaptateur prend la bonne API, et retire l'argument qu'une version ne
  connaît pas au lieu d'y échouer — en le disant quand il était demandé.

L'installation réelle sur Odoo 10 et 20 se vérifie contre un PostgreSQL :
elle n'a pas sa place dans ce lanceur, qui doit rester rapide.
"""

import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
ODOO_BIN = RACINE / "odoo_bin.sh"
LIB_ODOO_RC = RACINE / "script" / "lib_odoo_rc.sh"
COMMANDE = (
    RACINE / "script/odoo/cli_addons/erplibre_db/cli/erplibre_db.py"
)

# Le faux interpréteur imprime les arguments qu'odoo_bin.sh lui passe.
FAUX_PYTHON = '#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n'


class TestReecritureParOdooBin(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name).resolve()
        (self.racine / ".erplibre-version").write_text("odoo10.0_python2.7.18")
        (self.racine / ".odoo-version").write_text("10.0")
        bin_dir = self.racine / ".venv.odoo10.0_python2.7.18" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python").write_text(FAUX_PYTHON)
        (bin_dir / "python").chmod(0o755)
        (bin_dir / "activate").write_text(f'export PATH="{bin_dir}:$PATH"\n')
        (self.racine / "script").mkdir()
        (self.racine / "script" / "lib_odoo_rc.sh").write_text(
            LIB_ODOO_RC.read_text(encoding="utf-8")
        )
        self.cli = self.racine / "odoo10.0" / "odoo" / "odoo" / "cli"
        self.cli.mkdir(parents=True)
        # Odoo 9 et suivants ont une commande shell ; seul 8 n'en a pas.
        (self.cli / "shell.py").write_text("")

    def tearDown(self):
        self._tmp.cleanup()

    def _args(self, *args):
        sortie = subprocess.run(
            ["bash", str(ODOO_BIN), *args],
            cwd=self.racine,
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "ODOO_RC"},
        )
        self.assertEqual(0, sortie.returncode, sortie.stderr)
        # Le premier argument est le chemin d'odoo-bin.
        return sortie.stdout.splitlines()[1:]

    def test_un_odoo_amont_sans_db_passe_a_erplibre_db(self):
        self.assertEqual(
            [
                f"--addons-path={self.racine}/script/odoo/cli_addons",
                "erplibre_db",
                "--list",
            ],
            self._args("db", "--list"),
        )

    def test_une_commande_db_d_une_autre_interface_aussi(self):
        """Odoo 19 et 20 ont une commande « db » à sous-commandes."""
        (self.cli / "db.py").write_text("subparsers.add_parser('load')\n")
        self.assertEqual("erplibre_db", self._args("db", "--list")[1])

    def test_le_fork_erplibre_garde_sa_commande(self):
        (self.cli / "db.py").write_text('parser.add_option("--restore_image")\n')
        self.assertEqual(["db", "--list"], self._args("db", "--list"))

    def test_les_autres_commandes_ne_sont_pas_touchees(self):
        self.assertEqual(
            ["shell", "-d", "base"], self._args("shell", "-d", "base")
        )

    def _config(self, contenu):
        tools = self.racine / "odoo10.0" / "odoo" / "odoo" / "tools"
        tools.mkdir(parents=True)
        (tools / "config.py").write_text(contenu)

    def test_no_http_devient_no_xmlrpc_pour_odoo_10(self):
        """Odoo 10 refuse « --no-http » : seule sa forme --no-xmlrpc existe."""
        self._config('group.add_option("--no-xmlrpc", dest="xmlrpc")\n')
        self.assertEqual(
            ["--no-xmlrpc", "--stop-after-init", "-d", "base"],
            self._args("--no-http", "--stop-after-init", "-d", "base"),
        )

    def test_les_options_http_deviennent_xmlrpc_pour_odoo_10(self):
        self._config('group.add_option("--no-xmlrpc", dest="xmlrpc")\n')
        self.assertEqual(
            [
                "--xmlrpc-port",
                "8169",
                "--xmlrpc-port=8170",
                "--xmlrpc-port",
                "8171",
                "--xmlrpc-interface=127.0.0.1",
                "--log-handler=werkzeug:INFO",
            ],
            self._args(
                "--http-port",
                "8169",
                "--http-port=8170",
                "-p",
                "8171",
                "--http-interface=127.0.0.1",
                "--log-handler=werkzeug:INFO",
            ),
        )

    def test_no_http_reste_tel_quel_des_odoo_11(self):
        self._config('group.add_option("--no-http", dest="http_enable")\n')
        self.assertEqual(
            ["--no-http", "-d", "base"], self._args("--no-http", "-d", "base")
        )

    def test_uninstall_d_un_odoo_amont_passe_a_erplibre_uninstall(self):
        self._config('group.add_option("--no-http", dest="http_enable")\n')
        self.assertEqual(
            [
                f"--addons-path={self.racine}/script/odoo/cli_addons",
                "erplibre_uninstall",
                "--no-http",
                "-d",
                "base",
                "--uninstall",
                "a,b",
            ],
            self._args("--no-http", "-d", "base", "--uninstall", "a,b"),
        )

    def test_le_fork_erplibre_garde_son_uninstall(self):
        self._config(
            'group.add_option("--no-http", dest="http_enable")\n'
            'group.add_option("--uninstall", dest="uninstall")\n'
        )
        self.assertEqual(
            ["-d", "base", "--uninstall=a"],
            self._args("-d", "base", "--uninstall=a"),
        )


class TestLaDispositionOpenerp(unittest.TestCase):
    """Odoo 8 et 9 : paquet openerp/, lanceur openerp-server, pas d'odoo-bin."""

    def monter(self, version, config, shell=True):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        racine = Path(self._tmp.name).resolve()
        cle = "odoo%s_python2.7.18" % version
        (racine / ".erplibre-version").write_text(cle)
        (racine / ".odoo-version").write_text(version)
        bin_dir = racine / (".venv." + cle) / "bin"
        bin_dir.mkdir(parents=True)
        # Il montre aussi ERPLIBRE_DEV_MODE, que seul odoo_bin.sh voit.
        (bin_dir / "python").write_text(
            FAUX_PYTHON + 'echo "DEV=${ERPLIBRE_DEV_MODE:-}"\n'
        )
        (bin_dir / "python").chmod(0o755)
        (bin_dir / "activate").write_text(f'export PATH="{bin_dir}:$PATH"\n')
        (racine / "script").mkdir()
        (racine / "script" / "lib_odoo_rc.sh").write_text(
            LIB_ODOO_RC.read_text(encoding="utf-8")
        )
        paquet = racine / ("odoo%s" % version) / "odoo" / "openerp"
        (paquet / "cli").mkdir(parents=True)
        (paquet / "tools").mkdir()
        (paquet / "tools" / "config.py").write_text(config)
        if shell:
            (paquet / "cli" / "shell.py").write_text("")
        self.racine = racine
        return racine

    def lancer(self, *args, env=None):
        environ = {k: v for k, v in os.environ.items() if k != "ODOO_RC"}
        environ.update(env or {})
        sortie = subprocess.run(
            ["bash", str(ODOO_BIN), *args],
            cwd=self.racine,
            capture_output=True,
            text=True,
            env=environ,
        )
        self.assertEqual(0, sortie.returncode, sortie.stderr)
        return sortie.stdout.splitlines()

    CONFIG_8 = 'group.add_option("--no-xmlrpc", dest="xmlrpc")\n'
    CONFIG_9 = (
        'group.add_option("--no-xmlrpc", dest="xmlrpc")\n'
        "group.add_option('--dev', dest='dev_mode', action='store_true')\n"
    )

    def test_le_lanceur_est_openerp_server(self):
        self.monter("8.0", self.CONFIG_8)
        lignes = self.lancer("-d", "base")
        self.assertTrue(lignes[0].endswith("/odoo8.0/odoo/openerp-server"), lignes)

    def test_odoo_8_sans_shell_passe_a_erplibre_shell(self):
        self.monter("8.0", self.CONFIG_8, shell=False)
        self.assertEqual(
            [
                f"--addons-path={self.racine}/script/odoo/cli_addons",
                "erplibre_shell",
                "-d",
                "base",
            ],
            self.lancer("shell", "-d", "base")[1:-1],
        )

    def test_odoo_9_garde_son_shell(self):
        self.monter("9.0", self.CONFIG_9)
        self.assertEqual(["shell", "-d", "base"], self.lancer("shell", "-d", "base")[1:-1])

    def test_odoo_9_n_a_qu_un_drapeau_dev(self):
        self.monter("9.0", self.CONFIG_9)
        self.assertEqual(
            ["--dev", "-d", "base"], self.lancer("--dev", "cg", "-d", "base")[1:-1]
        )

    def test_odoo_8_n_a_pas_de_dev_le_mode_passe_par_l_environnement(self):
        self.monter("8.0", self.CONFIG_8)
        lignes = self.lancer("--dev", "cg", "-d", "base", "-i", "user_test")
        self.assertEqual(["-d", "base", "-i", "user_test"], lignes[1:-1])
        self.assertEqual("DEV=cg", lignes[-1])

    def test_odoo_8_lit_la_configuration_par_openerp_server(self):
        self.monter("8.0", self.CONFIG_8)
        (self.racine / "config.conf").write_text("[options]\n")
        environ = {k: v for k, v in os.environ.items() if k not in ("ODOO_RC", "OPENERP_SERVER")}
        sortie = subprocess.run(
            ["bash", "-c", 'source script/lib_odoo_rc.sh; odoo_rc_resolve "$PWD"; echo "$OPENERP_SERVER"'],
            cwd=self.racine, capture_output=True, text=True, env=environ,
        )
        self.assertEqual(str(self.racine / "config.conf"), sortie.stdout.strip())


class TestDesinstallerSelonLApi(unittest.TestCase):
    """downstream_dependencies() rend des enregistrements depuis Odoo 10, des
    identifiants en 8 et 9 (ancienne API) : les unir tels quels levait
    « Mixing apples and oranges », et le module restait installé."""

    DESINSTALLE = []

    class Modules(object):
        NOMS = {1: "crm", 2: "sale_crm", 3: "base"}

        def __init__(self, ids, ancienne_api):
            self.ids = list(ids)
            self.ancienne_api = ancienne_api

        def search(self, domaine):
            noms = domaine[0][2]
            return self.browse([i for i, n in self.NOMS.items() if n in noms])

        def browse(self, ids):
            return type(self)(ids, self.ancienne_api)

        def __bool__(self):
            return bool(self.ids)

        def __or__(self, autre):
            if not isinstance(autre, type(self)):
                raise TypeError("Mixing apples and oranges")
            return self.browse(sorted(set(self.ids) | set(autre.ids)))

        def mapped(self, champ):
            return [self.NOMS[i] for i in self.ids]

        def downstream_dependencies(self):
            return [2] if self.ancienne_api else self.browse([2])

        def button_immediate_uninstall(self):
            TestDesinstallerSelonLApi.DESINSTALLE.append(self.mapped("name"))

    def desinstaller(self):
        import ast

        source = (COMMANDE.parent / "erplibre_uninstall.py").read_text(
            encoding="utf-8"
        )
        arbre = ast.parse(source)
        fonction = [
            n for n in arbre.body
            if isinstance(n, ast.FunctionDef) and n.name == "desinstaller"
        ][0]
        espace = {}
        exec(compile(ast.Module([fonction], []), "erplibre_uninstall", "exec"), espace)
        return espace["desinstaller"]

    def test_les_identifiants_d_odoo_8_et_9_deviennent_des_enregistrements(self):
        TestDesinstallerSelonLApi.DESINSTALLE = []
        env = {"ir.module.module": self.Modules([], ancienne_api=True)}
        self.assertEqual(["crm", "sale_crm"], self.desinstaller()(env, ["crm"]))
        self.assertEqual([["crm", "sale_crm"]], TestDesinstallerSelonLApi.DESINSTALLE)

    def test_les_enregistrements_d_odoo_10_et_suivants_passent_tels_quels(self):
        env = {"ir.module.module": self.Modules([], ancienne_api=False)}
        self.assertEqual(["crm", "sale_crm"], self.desinstaller()(env, ["crm"]))


def _charger_commande(api):
    """Charge erplibre_db.py contre un faux paquet odoo portant l'API
    demandée : « legacy » (odoo.service.db) ou « moderne » (odoo.modules.db).
    """
    appels = []

    odoo = types.ModuleType("odoo")
    odoo.release = types.SimpleNamespace(version="20.0")
    odoo.api = types.ModuleType("odoo.api")
    cli = types.ModuleType("odoo.cli")
    cli.Command = type("Command", (), {})
    tools = types.ModuleType("odoo.tools")
    tools.config = {}
    service = types.ModuleType("odoo.service")
    modules = types.ModuleType("odoo.modules")
    faux = {
        "odoo": odoo,
        "odoo.api": odoo.api,
        "odoo.cli": cli,
        "odoo.tools": tools,
        "odoo.service": service,
        "odoo.modules": modules,
    }
    if api == "legacy":
        db = types.ModuleType("odoo.service.db")

        # La signature d'Odoo 10 : ni neutralize_database, ni phone.
        def exp_duplicate_database(db_original_name, db_name):
            appels.append(("clone", db_original_name, db_name))

        def restore_db(db, dump_file, copy=False):
            appels.append(("restore", db, dump_file, copy))

        db.exp_duplicate_database = exp_duplicate_database
        db.restore_db = restore_db
        service.db = db
        faux["odoo.service.db"] = db
    else:
        db = types.ModuleType("odoo.modules.db")

        def duplicate(db_original_name, db_name, *, neutralize_database=False):
            appels.append(("clone", db_original_name, db_name, neutralize_database))

        db.duplicate = duplicate
        modules.db = db
        faux["odoo.modules.db"] = db

    anciens = {nom: sys.modules.get(nom) for nom in faux}
    sys.modules.update(faux)
    try:
        spec = importlib.util.spec_from_file_location(
            f"erplibre_db_{api}", COMMANDE
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for nom, ancien in anciens.items():
            if ancien is None:
                sys.modules.pop(nom, None)
            else:
                sys.modules[nom] = ancien
    return module, appels


class TestAdaptateur(unittest.TestCase):
    def test_odoo_10_clone_sans_neutralize_database(self):
        module, appels = _charger_commande("legacy")
        with redirect_stderr(io.StringIO()):
            module.cloner("source", "cible", False)
        self.assertEqual([("clone", "source", "cible")], appels)

    def test_une_option_demandee_et_absente_est_signalee(self):
        """Neutraliser sur Odoo 10 : l'option n'existe pas, on le dit."""
        module, appels = _charger_commande("legacy")
        erreur = io.StringIO()
        with redirect_stderr(erreur):
            module.restaurer("base", "copie.zip", True, True)
        self.assertEqual([("restore", "base", "copie.zip", True)], appels)
        self.assertIn("neutralize_database", erreur.getvalue())

    def test_une_option_absente_non_demandee_reste_muette(self):
        module, _appels = _charger_commande("legacy")
        erreur = io.StringIO()
        with redirect_stderr(erreur):
            module.restaurer("base", "copie.zip", True, False)
        self.assertEqual("", erreur.getvalue())

    def test_odoo_20_passe_par_odoo_modules_db(self):
        module, appels = _charger_commande("moderne")
        module.cloner("source", "cible", True)
        self.assertEqual([("clone", "source", "cible", True)], appels)

    def test_une_image_designe_le_zip_d_image_db(self):
        module, _appels = _charger_commande("legacy")
        opt = types.SimpleNamespace(restore_image="base", restore_db_file=None)
        self.assertEqual(
            os.path.join(".", "image_db", "base.zip"), module.chemin_image(opt)
        )


if __name__ == "__main__":
    unittest.main()
