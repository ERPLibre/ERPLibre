#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""scenario_odoo : le pilote d'un scénario, lancé pour de vrai contre une
racine factice.

La racine factice porte un dépôt de gabarits sous git, un config.conf et
des commandes qui se contentent de noter leurs arguments : db_restore,
les installations, le test du générateur, odoo_bin.sh. Seul le contrôle
git est le vrai script du dépôt. Aucune base, aucun Odoo : le verdict,
l'ordre des étapes, le détail JSON et le démontage sur SIGTERM se jugent
sur ce que les commandes ont noté.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, "test")

from processus_reels import lire, tous_morts  # noqa: E402

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PILOTE = os.path.join(RACINE, "script", "test", "scenario_odoo.py")
RUN_ID = "0a1b2c3d"
DEPOT = "./odoo18.0/addons/DepotModeles"

NOTER = '#!/bin/sh\necho "$(basename "$0") $*" >> "$APPELS"\n'

COMMANDES = {
    "script/database/db_restore.py": NOTER + 'exit "${FAUX_RESTORE_RC:-0}"\n',
    "script/addons/install_addons_dev.sh": NOTER,
    "script/addons/install_addons.sh": NOTER,
    "script/code_generator/search_class_model.py": NOTER,
    "odoo_bin.sh": NOTER,
    "script/code_generator/install_and_test_code_generator.sh": NOTER
    + 'grep -h "path_module_generate =" "$3"/cg_exemple/hooks.py\n'
    + '[ -n "$FAUX_CG_SUPPRIME" ] && rm -f "$FAUX_CG_SUPPRIME"\n'
    + 'if [ -n "$FAUX_CG_DORT" ]; then\n'
    + "    sleep 60 &\n"
    + '    echo "$$ $!" > "$FAUX_CG_DORT.tmp"\n'
    + '    mv "$FAUX_CG_DORT.tmp" "$FAUX_CG_DORT"\n'
    + "    wait\n"
    + "fi\n"
    + 'echo "${FAUX_CG_SORTIE:-fini}"\n'
    + 'exit "${FAUX_CG_RC:-0}"\n',
    "faux.sh": NOTER + 'echo "${FAUX_SORTIE:-rien}"\nexit "${FAUX_RC:-0}"\n',
}

HOOK = """import os

MODULE_NAME = "exemple_genere"


def post_init_hook(env):
    # path_module_generate = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))

    value = {
        # "path_sync_code": path_module_generate,
    }
"""

ENTREES = [
    {"run_command": True, "test_name": "cmd_fictive", "script": "./faux.sh"},
    {
        "run_test_exec": True,
        "test_name": "scn_exec",
        "path_module_check": DEPOT,
        "generated_module": "exemple_genere",
        "tested_module": "cg_exemple",
        "restore_db_image_name": "image_fictive",
    },
    {
        "run_test_exec": True,
        "test_name": "scn_deux",
        "path_module_check": DEPOT,
        "generated_module": "exemple_genere",
        "tested_module": "cg_exemple,cg_autre",
        "restore_db_image_name": "image_fictive",
    },
    {
        "run_test_exec": True,
        "test_name": "scn_sans_hooks",
        "path_module_check": DEPOT,
        "generated_module": "exemple_genere",
        "tested_module": "cg_sans_hooks",
        "restore_db_image_name": "image_fictive",
    },
    {
        "run_test_exec": True,
        "test_name": "scn_origine",
        "path_module_check": DEPOT,
        "generated_module": "exemple_genere",
        "tested_module": "cg_exemple",
        "file_to_restore": "exemple_genere/i18n/fr.po",
        "file_to_restore_origin": True,
        "restore_db_image_name": "image_fictive",
    },
]

ENTETE = re.compile(r'^(PASS|FAIL) \[(\S+)\] \[\d+\.\d{3}s\] Execute "(.*)"$')


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class RacineFactice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scn_pilote_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.racine = os.path.join(self.tmp, "racine")
        os.makedirs(self.racine)
        with open(os.path.join(self.racine, ".odoo-version"), "w") as fh:
            fh.write("18.0")
        with open(os.path.join(self.racine, "config.conf"), "w") as fh:
            fh.write(
                "[options]\naddons_path = /fictif/odoo18.0/addons/DepotA,"
                "/fictif/odoo18.0/addons/DepotModeles\n"
            )
        for chemin, contenu in COMMANDES.items():
            self.ecrire(chemin, contenu, executable=True)
        verif = "script/code_generator/check_git_change_code_generator.sh"
        os.makedirs(
            os.path.dirname(os.path.join(self.racine, verif)), exist_ok=True
        )
        shutil.copy(
            os.path.join(RACINE, verif), os.path.join(self.racine, verif)
        )
        for module in ("cg_exemple", "cg_autre"):
            self.ecrire(f"{DEPOT}/{module}/hooks.py", HOOK)
        self.ecrire(f"{DEPOT}/cg_sans_hooks/__init__.py", "")
        self.ecrire(f"{DEPOT}/exemple_genere/__init__.py", "")
        self.ecrire(f"{DEPOT}/exemple_genere/i18n/fr.po", 'msgid ""\n')
        self.json = os.path.join(self.tmp, "scenarios.json")
        with open(self.json, "w") as fh:
            json.dump({"lst_test": ENTREES}, fh)
        self.appels = os.path.join(self.tmp, "appels.log")
        self.tmpdir = os.path.join(self.tmp, "tmpdir")
        os.makedirs(self.tmpdir)
        self.env = dict(
            os.environ,
            APPELS=self.appels,
            TMPDIR=self.tmpdir,
            XDG_CACHE_HOME=os.path.join(self.tmp, "cache"),
            GIT_AUTHOR_NAME="Auteur Fictif",
            GIT_AUTHOR_EMAIL="auteur@fictif.invalid",
            GIT_COMMITTER_NAME="Auteur Fictif",
            GIT_COMMITTER_EMAIL="auteur@fictif.invalid",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
        )
        self.env.pop("PYTHONPATH", None)
        depot = os.path.join(self.racine, DEPOT)
        _git("init", "-q", ".", cwd=depot)
        _git("add", ".", cwd=depot)
        subprocess.run(
            ["git", "commit", "-qm", "init"],
            cwd=depot,
            env=self.env,
            check=True,
            capture_output=True,
        )
        self.detail = os.path.join(self.tmp, "detail.json")

    def ecrire(self, chemin, contenu, executable=False):
        complet = os.path.join(self.racine, chemin)
        os.makedirs(os.path.dirname(complet), exist_ok=True)
        with open(complet, "w") as fh:
            fh.write(contenu)
        if executable:
            os.chmod(complet, 0o755)

    def commande(self, nom):
        return [
            sys.executable,
            "-u",
            PILOTE,
            "--json",
            self.json,
            "--name",
            nom,
            "--run-id",
            RUN_ID,
            "--detail",
            self.detail,
            "--racine",
            self.racine,
        ]

    def lancer(self, nom, **env):
        res = subprocess.run(
            self.commande(nom),
            env=dict(self.env, **env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return res.returncode, res.stdout + res.stderr

    def appels_notes(self):
        return lire(self.appels).splitlines()

    def etapes(self):
        with open(self.detail, encoding="utf-8") as fh:
            return json.load(fh)


class TestVerdict(RacineFactice):
    def test_a_clean_command_is_green(self):
        rc, sortie = self.lancer("cmd_fictive", FAUX_SORTIE="tout va bien")
        self.assertEqual(rc, 0, sortie)
        entetes = [
            m.groups() for m in map(ENTETE.match, sortie.splitlines()) if m
        ]
        self.assertEqual(entetes, [("PASS", "cmd_fictive", "./faux.sh")])
        self.assertIn("OK [cmd_fictive]", sortie.splitlines()[-1])

    def test_an_error_line_with_code_zero_fails(self):
        rc, sortie = self.lancer(
            "cmd_fictive",
            FAUX_SORTIE="2031-01-01 4242 ERROR base_fictive odoo.registry: boum",
        )
        self.assertEqual(rc, 1)
        derniere = sortie.rstrip().splitlines()[-1]
        self.assertIn("ÉCHEC [cmd_fictive]", derniere)
        self.assertIn("« script »", derniere)
        self.assertIn("odoo.registry: boum", sortie.rsplit("── résumé", 1)[1])
        (etape,) = self.etapes()
        self.assertEqual(etape["etat"], "echec")

    def test_an_ignored_error_line_stays_green(self):
        rc, sortie = self.lancer(
            "cmd_fictive",
            FAUX_SORTIE="fetchmail_notify_error_to_sender absent",
        )
        self.assertEqual(rc, 0, sortie)

    def test_a_non_zero_code_fails_without_error_line(self):
        rc, sortie = self.lancer("cmd_fictive", FAUX_RC="3")
        self.assertEqual(rc, 1)
        self.assertIn("(code 3)", sortie.splitlines()[-1])
        self.assertIn("FAIL [cmd_fictive]", sortie)


class TestDeroule(RacineFactice):
    def test_the_full_chain_in_a_sandbox(self):
        rc, sortie = self.lancer("scn_exec")
        self.assertEqual(rc, 0, sortie)
        appels = self.appels_notes()
        self.assertEqual(
            [a.split()[0] for a in appels],
            [
                "db_restore.py",
                "install_and_test_code_generator.sh",
                "odoo_bin.sh",
            ],
        )
        base = appels[0].split()[2]
        self.assertTrue(base.startswith(f"test_scn_{RUN_ID}_"), base)
        self.assertLessEqual(len(base), 62)
        self.assertEqual(appels[2], f"odoo_bin.sh db drop {base}")
        bac = re.search(r"^bac : (.*)$", sortie, re.M).group(1)
        # Le générateur reçoit le dépôt COPIÉ et son hooks.py réécrit.
        copie = os.path.join(bac, "workspace", "odoo18.0/addons/DepotModeles")
        self.assertIn(
            f"install_and_test_code_generator.sh {base} cg_exemple {copie}"
            f" exemple_genere {bac}/workspace/config.conf",
            appels[1],
        )
        self.assertIn(f'path_module_generate = "{copie}"', sortie)
        # Le bac est supprimé, l'origine intacte.
        self.assertFalse(os.path.exists(bac))
        self.assertEqual(os.listdir(self.tmpdir), [])
        with open(
            os.path.join(self.racine, DEPOT, "cg_exemple/hooks.py")
        ) as fh:
            self.assertEqual(fh.read(), HOOK)
        lignes = [
            m.groups() for m in map(ENTETE.match, sortie.splitlines()) if m
        ]
        self.assertEqual(
            [(etat, cmd.split()[0]) for etat, _nom, cmd in lignes],
            [
                (
                    "PASS",
                    "./script/code_generator/check_git_change_code_generator.sh",
                ),
                ("PASS", "./script/database/db_restore.py"),
                (
                    "PASS",
                    "./script/code_generator/install_and_test_code_generator.sh",
                ),
                ("PASS", "./odoo_bin.sh"),
            ],
        )
        etats = {e["nom"]: e["etat"] for e in self.etapes()}
        self.assertEqual(etats["restore"], "ok")
        self.assertEqual(etats["cg_test"], "ok")
        for e in self.etapes():
            self.assertEqual(
                set(e), {"id", "classe", "nom", "duree", "etat", "message"}
            )
            self.assertEqual(e["classe"], "scn_exec")

    def test_one_git_check_per_tested_module(self):
        rc, sortie = self.lancer("scn_deux")
        self.assertEqual(rc, 0, sortie)
        verifs = [
            m.group(3)
            for m in map(ENTETE.match, sortie.splitlines())
            if m and "check_git_change" in m.group(3)
        ]
        self.assertEqual(len(verifs), 2)
        self.assertTrue(verifs[0].endswith(" cg_exemple"))
        self.assertTrue(verifs[1].endswith(" cg_autre"))

    def test_a_missing_hooks_file_stops_before_the_database(self):
        rc, sortie = self.lancer("scn_sans_hooks")
        self.assertEqual(rc, 1)
        self.assertIn("Hook file", sortie)
        self.assertEqual(self.appels_notes(), [])
        self.assertIn("« hooks cg_sans_hooks »", sortie.splitlines()[-1])

    def test_a_failed_restore_skips_the_rest_and_the_drop(self):
        rc, _sortie = self.lancer("scn_exec", FAUX_RESTORE_RC="1")
        self.assertEqual(rc, 1)
        self.assertEqual(
            [a.split()[0] for a in self.appels_notes()], ["db_restore.py"]
        )

    def test_declared_origin_files_restored_when_deleted(self):
        origine = os.path.join(self.racine, DEPOT, "exemple_genere/i18n/fr.po")
        rc, sortie = self.lancer("scn_origine", FAUX_CG_SUPPRIME=origine)
        self.assertEqual(rc, 0, sortie)
        self.assertTrue(os.path.exists(origine))

    def test_origin_files_not_deleted_fail_the_scenario(self):
        rc, sortie = self.lancer("scn_origine")
        self.assertEqual(rc, 1)
        self.assertIn("« file_to_restore »", sortie.splitlines()[-1])


class TestSigterm(RacineFactice):
    def test_sigterm_drops_the_base_restores_then_exits_143(self):
        origine = os.path.join(self.racine, DEPOT, "exemple_genere/i18n/fr.po")
        marqueur = os.path.join(self.tmp, "dort")
        p = subprocess.Popen(
            self.commande("scn_origine"),
            env=dict(
                self.env, FAUX_CG_SUPPRIME=origine, FAUX_CG_DORT=marqueur
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self.addCleanup(self._tuer_groupe, p)
        fin = time.monotonic() + 60
        while not os.path.exists(marqueur) and time.monotonic() < fin:
            if p.poll() is not None:
                self.fail(p.stdout.read())
            time.sleep(0.05)
        pids = [int(x) for x in lire(marqueur).split()]
        self.assertFalse(os.path.exists(origine))
        os.kill(p.pid, signal.SIGTERM)
        sortie, _ = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 143, sortie)
        self.assertEqual(tous_morts(pids), [])
        drops = [a for a in self.appels_notes() if a.startswith("odoo_bin.sh")]
        self.assertEqual(len(drops), 1, self.appels_notes())
        self.assertRegex(
            drops[0], rf"^odoo_bin.sh db drop --if-exists test_scn_{RUN_ID}_"
        )
        self.assertTrue(os.path.exists(origine))
        self.assertIn("ARRÊTÉ [scn_origine]", sortie)
        self.assertIn("« cg_test »", sortie)
        self.assertEqual(os.listdir(self.tmpdir), [])
        self.assertTrue(any(e["nom"] == "restore" for e in self.etapes()))

    @staticmethod
    def _tuer_groupe(p):
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
        if p.stdout:
            p.stdout.close()


if __name__ == "__main__":
    unittest.main()
