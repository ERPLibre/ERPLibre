#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Écarts entre le venv d'Odoo et son poetry.lock, puis le rapport de mise
à jour.

Ce que le lock devrait donner vient de Poetry (« sync --dry-run ») : les
tests remplacent Poetry et l'interpréteur du venv par des faux, dans un
dépôt jetable. Rien n'est installé, aucun réseau.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

sys.argv = ["todo.py"]
from script.poetry import poetry_venv_drift as drift  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

VERSION = "odoo18.0_python3.12.16"

# Une vraie sortie de Poetry 2.1, abrégée.
SORTIE = """Installing dependencies from lock file

Package operations: 1 install, 2 updates, 2 removals

  - Removing poetry (2.1.3)
  - Removing pip-audit (2.9.0)
  - Installing dnspython (2.7.0)
  - Updating requests (2.31.0 -> 2.32.3)
  - Downgrading six (1.17.0 -> 1.16.0)
"""

# Une simulation sur un venv à jour : Poetry imprime AUSSI les opérations
# sautées. Format de Poetry 2.1.3, « sync --dry-run --no-ansi ».
SAUTEES = """Installing dependencies from lock file

Package operations: 0 installs, 0 updates, 0 removals, 2 skipped

  - Installing pip (26.2.2): Skipped for the following reason: Already \
installed
  - Installing dnspython (2.7.0): Skipped for the following reason: Not \
required
"""

ALIGNE = """Installing dependencies from lock file

Package operations: 0 installs, 0 updates, 1 removal

  - Removing poetry (2.1.3)
"""

REFUS = (
    "Current Python version (3.12.10) is not allowed by the project"
    " (>=3.12.16,<3.13).\n"
    'Please change python executable via the "env use" command.\n'
)


def fini(code=0, sortie="", erreur=""):
    return SimpleNamespace(returncode=code, stdout=sortie, stderr=erreur)


class TestLireLesOperations(unittest.TestCase):
    def test_chaque_action_et_ses_versions(self):
        ops = drift.lire_operations(SORTIE)
        self.assertEqual(
            [
                ("Removing", "poetry", "2.1.3", None),
                ("Removing", "pip-audit", "2.9.0", None),
                ("Installing", "dnspython", None, "2.7.0"),
                ("Updating", "requests", "2.31.0", "2.32.3"),
                ("Downgrading", "six", "1.17.0", "1.16.0"),
            ],
            [(o["action"], o["nom"], o["avant"], o["apres"]) for o in ops],
        )

    def test_une_operation_sautee_n_est_pas_un_ecart(self):
        self.assertEqual([], drift.lire_operations(SAUTEES))
        melange = SORTIE + SAUTEES.split("\n\n", 2)[2]
        self.assertEqual(5, len(drift.lire_operations(melange)))

    def test_le_reste_de_la_sortie_est_ignore(self):
        self.assertEqual([], drift.lire_operations("Resolving...\n\nOK\n"))

    def test_les_paquets_hors_du_lock_ne_sont_pas_des_ecarts(self):
        self.assertFalse(drift.a_des_ecarts(drift.lire_operations(ALIGNE)))
        self.assertTrue(drift.a_des_ecarts(drift.lire_operations(SORTIE)))

    def test_classer_range_par_action(self):
        classes = drift.classer(drift.lire_operations(SORTIE))
        self.assertEqual(
            ["Installing", "Updating", "Downgrading", "Removing"],
            list(classes),
        )
        self.assertEqual(2, len(classes["Removing"]))


class TestSimuler(unittest.TestCase):
    def test_le_venv_est_active_pour_poetry(self):
        """Sans VIRTUAL_ENV, Poetry compare le lock à l'interpréteur de
        base, pas au venv (virtualenvs.create = false)."""
        appels = []

        def executer(commande, **kwargs):
            appels.append((commande, kwargs))
            return fini(0, SORTIE)

        res = drift.simuler("/depot", VERSION, executer=executer)
        commande, kwargs = appels[0]
        self.assertEqual(
            [f"/depot/.venv.{VERSION}/bin/poetry", "sync", "--dry-run"],
            commande[:3],
        )
        self.assertIn("--no-root", commande)
        env = kwargs["env"]
        self.assertEqual(f"/depot/.venv.{VERSION}", env["VIRTUAL_ENV"])
        self.assertTrue(env["PATH"].startswith(f"/depot/.venv.{VERSION}/bin"))
        self.assertEqual(
            "keyring.backends.null.Keyring", env["PYTHON_KEYRING_BACKEND"]
        )
        self.assertEqual("/depot", kwargs["cwd"])
        self.assertTrue(res["ok"])
        self.assertEqual(5, len(res["operations"]))

    def test_poetry_1_retombe_sur_install_sync(self):
        commandes = []

        def executer(commande, **_kwargs):
            commandes.append(commande)
            if "sync" == commande[1]:
                return fini(1, "", 'The command "sync" does not exist.\n')
            return fini(0, ALIGNE)

        res = drift.simuler("/depot", VERSION, executer=executer)
        self.assertEqual(["install", "--sync", "--dry-run"], commandes[1][1:4])
        self.assertTrue(res["ok"])

    def test_un_refus_de_poetry_garde_sa_raison(self):
        res = drift.simuler(
            "/depot", VERSION, executer=lambda *a, **k: fini(1, "", REFUS)
        )
        self.assertFalse(res["ok"])
        self.assertEqual([], res["operations"])
        self.assertIn("is not allowed by the project", res["sortie"])

    def test_avec_un_vrai_processus(self):
        """Un faux poetry, exécuté pour de vrai : il ne répond que si le
        venv est bien activé."""
        tmp = tempfile.mkdtemp(prefix="el_drift_")
        self.addCleanup(shutil.rmtree, tmp, True)
        bin_dir = Path(tmp, f".venv.{VERSION}", "bin")
        bin_dir.mkdir(parents=True)
        poetry = bin_dir / "poetry"
        poetry.write_text(
            "#!/bin/sh\n"
            f'[ "$VIRTUAL_ENV" = "{tmp}/.venv.{VERSION}" ] || exit 9\n'
            f"cat <<'FIN'\n{SORTIE}FIN\n",
            encoding="utf-8",
        )
        poetry.chmod(0o755)
        res = drift.simuler(tmp, VERSION)
        self.assertTrue(res["ok"], res["sortie"])
        self.assertEqual(5, len(res["operations"]))


class TestReleverEtComparer(unittest.TestCase):
    def test_relever_lit_le_json_de_l_interpreteur(self):
        executer = lambda *a, **k: fini(  # noqa: E731
            0, '{"Requests": "2.32.3", "six": "1.16.0"}'
        )
        self.assertEqual(
            {"requests": ("Requests", "2.32.3"), "six": ("six", "1.16.0")},
            drift.relever("/depot", VERSION, executer=executer),
        )

    def test_relever_execute_l_interpreteur_du_venv(self):
        """Le vrai extrait importlib.metadata, par un interpréteur placé là
        où relever le cherche : .venv.<version>/bin/python."""
        tmp = tempfile.mkdtemp(prefix="el_drift_releve_")
        self.addCleanup(shutil.rmtree, tmp, True)
        bin_dir = Path(tmp, f".venv.{VERSION}", "bin")
        bin_dir.mkdir(parents=True)
        os.symlink(sys.executable, bin_dir / "python")
        releve = drift.relever(tmp, VERSION)
        self.assertIn("pip", releve, sorted(releve)[:10])
        self.assertEqual("pip", releve["pip"][0])

    def test_un_interpreteur_muet_rend_un_releve_vide(self):
        executer = lambda *a, **k: fini(1, "", "boom")  # noqa: E731
        self.assertEqual({}, drift.relever("/depot", VERSION, executer))

    def test_comparer(self):
        avant = {"six": ("six", "1.17.0"), "vieux": ("vieux", "1.0")}
        apres = {"six": ("six", "1.16.0"), "neuf": ("neuf", "2.0")}
        self.assertEqual(
            {
                "changes": [("six", "1.17.0", "1.16.0")],
                "ajoutes": [("neuf", "2.0")],
                "retires": [("vieux", "1.0")],
            },
            drift.comparer(avant, apres),
        )

    def test_le_rapport_s_ecrit_dans_le_cache(self):
        tmp = tempfile.mkdtemp(prefix="el_drift_cache_")
        self.addCleanup(shutil.rmtree, tmp, True)
        import datetime

        with patch.dict(os.environ, {"XDG_CACHE_HOME": tmp}):
            chemin = drift.ecrire_rapport(
                "# rapport\n",
                VERSION,
                maintenant=datetime.datetime(2031, 1, 2, 3, 4, 5),
            )
        self.assertEqual(
            os.path.join(
                tmp, "erplibre_poetry", f"{VERSION}_20310102_030405.md"
            ),
            chemin,
        )
        self.assertEqual("# rapport\n", Path(chemin).read_text())


class BancMenu(unittest.TestCase):
    """Un dépôt jetable comme dossier courant : .erplibre-version, le venv
    avec son poetry, et les liens que Poetry lit à la racine."""

    def setUp(self):
        self.ancien = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix="el_drift_menu_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.ancien)
        Path(".erplibre-version").write_text(VERSION + "\n")
        Path(f".venv.{VERSION}/bin").mkdir(parents=True)
        Path(f".venv.{VERSION}/bin/poetry").write_text("")
        Path("requirement").mkdir()
        for nom in (f"poetry.{VERSION}.lock", f"pyproject.{VERSION}.toml"):
            Path("requirement", nom).write_text("")
        os.symlink(f"requirement/poetry.{VERSION}.lock", "poetry.lock")
        os.symlink(f"requirement/pyproject.{VERSION}.toml", "pyproject.toml")
        self.cache = tempfile.mkdtemp(prefix="el_drift_rapports_")
        self.addCleanup(shutil.rmtree, self.cache, True)
        environ = patch.dict(os.environ, {"XDG_CACHE_HOME": self.cache})
        environ.start()
        self.addCleanup(environ.stop)
        self.todo = TODO()
        self.todo.execute = MagicMock()
        self.todo.execute.exec_command_live.return_value = 0

    def lancer(self, simulations, reponse="", releves=None):
        """execute_poetry_drift avec des simulations et des relevés donnés
        dans l'ordre. Rend (sortie, faux input). self.ordre trace les
        relevés et l'installation dans l'ordre où ils ont lieu, et
        self.simuler est le mock que le code a réellement appelé."""
        sortie = io.StringIO()
        releves = iter(releves or [{}, {}])
        self.ordre = []
        statut = self.todo.execute.exec_command_live.return_value

        def relever(*_a, **_k):
            self.ordre.append("releve")
            return next(releves)

        def installer(*_a, **_k):
            self.ordre.append("installation")
            return statut

        self.todo.execute.exec_command_live.side_effect = installer
        with (
            patch.object(
                drift, "simuler", side_effect=simulations
            ) as self.simuler,
            patch.object(drift, "relever", side_effect=relever),
            patch("builtins.input", return_value=reponse) as question,
            patch("sys.stdout", sortie),
        ):
            self.todo.execute_poetry_drift()
        return sortie.getvalue(), question

    @staticmethod
    def simulation(texte, ok=True):
        return {
            "ok": ok,
            "operations": drift.lire_operations(texte) if ok else [],
            "sortie": texte,
            "commande": "poetry sync --dry-run",
        }

    def installe(self):
        return [
            appel[0][0]
            for appel in self.todo.execute.exec_command_live.call_args_list
        ]


class TestLeParcours(BancMenu):
    def test_un_venv_aligne_ne_demande_rien(self):
        texte, question = self.lancer([self.simulation(ALIGNE)])
        self.assertIn(todo_i18n.t("The venv matches the lock."), texte)
        # Le paquet hors du lock est montré, sans compter comme un écart.
        self.assertIn(
            f"{todo_i18n.t('Outside the lock, left untouched by the update:')}"
            " 1 (poetry)",
            texte,
        )
        question.assert_not_called()
        self.assertEqual([], self.installe())

    def test_les_ecarts_sont_listes_puis_la_mise_a_jour_proposee(self):
        texte, question = self.lancer([self.simulation(SORTIE)], "")
        self.assertIn(f"{todo_i18n.t('Differences with the lock:')} 3", texte)
        self.assertIn("requests 2.31.0 → 2.32.3", texte)
        self.assertIn("dnspython 2.7.0", texte)
        self.assertIn("six 1.17.0 → 1.16.0", texte)
        question.assert_called_once()
        self.assertIn(
            todo_i18n.t(
                "Update the venv to match the lock (y/N, default: N)? "
            ),
            question.call_args[0][0],
        )
        # Le défaut est non : rien n'est installé.
        self.assertEqual([], self.installe())

    def test_oui_installe_le_lock_et_ecrit_le_rapport(self):
        avant = {
            "requests": ("requests", "2.31.0"),
            "six": ("six", "1.17.0"),
        }
        apres = {
            "requests": ("requests", "2.32.3"),
            "six": ("six", "1.16.0"),
            "dnspython": ("dnspython", "2.7.0"),
        }
        texte, _ = self.lancer(
            [self.simulation(SORTIE), self.simulation(ALIGNE)],
            "o",
            releves=[avant, apres],
        )
        self.assertEqual(
            ["EL_PHASE=poetry ./script/install/install_locally.sh"],
            self.installe(),
        )
        # Le relevé « avant » précède l'installation : pris après, les deux
        # relevés seraient égaux et le rapport ne dirait jamais rien.
        self.assertEqual(["releve", "installation", "releve"], self.ordre)
        rapports = list(Path(self.cache, "erplibre_poetry").glob("*.md"))
        self.assertEqual(1, len(rapports), texte)
        rapport = rapports[0].read_text()
        self.assertIn("requests : 2.31.0 → 2.32.3", rapport)
        self.assertIn("six : 1.17.0 → 1.16.0", rapport)
        self.assertIn("dnspython 2.7.0", rapport)
        self.assertIn(todo_i18n.t("None: the venv matches the lock."), rapport)
        self.assertIn(str(rapports[0]), texte)

    def test_un_echec_d_installation_est_dit_dans_le_rapport(self):
        self.todo.execute.exec_command_live.return_value = 3
        texte, _ = self.lancer(
            [self.simulation(SORTIE), self.simulation(SORTIE)],
            "o",
            releves=[{"six": ("six", "1.17.0")}, {"six": ("six", "1.17.0")}],
        )
        rapport = next(Path(self.cache, "erplibre_poetry").glob("*.md"))
        contenu = rapport.read_text()
        self.assertIn(f"{todo_i18n.t('failure, code')} 3", contenu)
        self.assertIn(todo_i18n.t("No package changed."), contenu)
        self.assertIn("requests", contenu)

    def test_une_nouvelle_simulation_refusee_ne_promet_pas_l_alignement(
        self,
    ):
        self.lancer(
            [self.simulation(SORTIE), self.simulation(REFUS, ok=False)],
            "o",
            releves=[{"six": ("six", "1.17.0")}, {"six": ("six", "1.16.0")}],
        )
        contenu = next(
            Path(self.cache, "erplibre_poetry").glob("*.md")
        ).read_text()
        self.assertIn(todo_i18n.t("Poetry refuses to compare:"), contenu)
        self.assertIn("is not allowed by the project", contenu)
        self.assertNotIn(
            todo_i18n.t("None: the venv matches the lock."), contenu
        )

    def test_un_refus_de_poetry_est_montre_sans_question(self):
        texte, question = self.lancer([self.simulation(REFUS, ok=False)])
        self.assertIn(todo_i18n.t("Poetry refuses to compare:"), texte)
        self.assertIn("is not allowed by the project", texte)
        question.assert_not_called()


class TestLesPrerequis(BancMenu):
    def test_un_lien_de_lock_casse_nomme_sa_cible(self):
        os.remove(f"requirement/poetry.{VERSION}.lock")
        texte, _ = self.lancer([self.simulation(ALIGNE)])
        self.simuler.assert_not_called()
        self.assertIn(f"requirement/poetry.{VERSION}.lock", texte)

    def test_poetry_absent_du_venv(self):
        os.remove(f".venv.{VERSION}/bin/poetry")
        texte, _ = self.lancer([])
        self.assertIn(todo_i18n.t("Poetry is missing from the venv:"), texte)

    def test_aucune_version_active(self):
        os.remove(".erplibre-version")
        texte, _ = self.lancer([])
        self.assertIn(
            todo_i18n.t("No .erplibre-version: no active Odoo version."),
            texte,
        )


class TestLeMenu(unittest.TestCase):
    def test_la_section_python_est_la_neuvieme_entree(self):
        todo = TODO()
        sortie = []
        with patch(
            "script.todo.todo.click.prompt",
            side_effect=lambda texte: sortie.append(texte) or "0",
        ):
            todo.prompt_execute()
        self.assertIn(
            f"[9] {todo_i18n.t('Python - Poetry and Python tools')}",
            sortie[0],
        )
        self.assertIn(
            f"[10] {todo_i18n.t('Database - Database tools')}", sortie[0]
        )

    def test_le_fil_d_ariane_nomme_le_menu(self):
        self.assertEqual(
            "Python", TODO._MENU_LABELS.get("prompt_execute_python")
        )


if __name__ == "__main__":
    unittest.main()
