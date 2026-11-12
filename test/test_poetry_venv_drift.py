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
import json
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
from script.todo.version_manager import (  # noqa: E402
    diagnostiquer_version,
    get_odoo_version,
)
from script.todo import version_manager as vm  # noqa: E402

VERSION = "odoo18.0_python3.12.16"
# Un checkout resté sur un patch de Python que le json ne connaît plus.
NON_SUPPORTEE = "odoo18.0_python3.12.10"
SUPPORTEES = {
    "odoo17.0_python3.10.18": {
        "odoo_version": "17.0",
        "python_version": "3.10.18",
        "poetry_version": "1.8.3",
    },
    VERSION: {
        "default": True,
        "odoo_version": "18.0",
        "python_version": "3.12.16",
        "poetry_version": "2.5.1",
    },
}

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
        Path(f".venv.{VERSION}/bin/python").write_text("")
        Path("requirement").mkdir()
        for nom in (f"poetry.{VERSION}.lock", f"pyproject.{VERSION}.toml"):
            Path("requirement", nom).write_text("")
        os.symlink(f"requirement/poetry.{VERSION}.lock", "poetry.lock")
        os.symlink(f"requirement/pyproject.{VERSION}.toml", "pyproject.toml")
        Path("conf").mkdir()
        Path("conf", "supported_version_erplibre.json").write_text(
            json.dumps(SUPPORTEES), encoding="utf-8"
        )
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
        # Le venv reste comparable : par son propre lock, hors de la racine.
        os.remove(".erplibre-version")
        texte, _ = self.lancer([self.simulation(ALIGNE)])
        self.assertIn(
            todo_i18n.t("No .erplibre-version: no active Odoo version."),
            texte,
        )
        self.assertIn(todo_i18n.t("The venv matches the lock."), texte)
        self.assertIsNotNone(self.simuler.call_args.kwargs.get("projet"))

    def test_aucun_venv(self):
        shutil.rmtree(f".venv.{VERSION}")
        texte, _ = self.lancer([])
        self.simuler.assert_not_called()
        self.assertIn("conf/supported_version_erplibre.json", texte)


class TestMiseAJourSansQuestion(BancMenu):
    """mettre_a_jour_venv, appelée par la résolution du Healthcheck : le
    choix est déjà fait, rien n'est redemandé."""

    def test_le_venv_actif_s_installe_sans_question(self):
        with (
            patch.object(
                drift,
                "simuler",
                side_effect=[
                    self.simulation(SORTIE),
                    self.simulation(ALIGNE),
                ],
            ),
            patch.object(drift, "relever", return_value={}),
            patch("builtins.input", side_effect=AssertionError) as question,
            patch("sys.stdout", io.StringIO()),
        ):
            self.todo.mettre_a_jour_venv(
                {
                    "venv": f".venv.{VERSION}",
                    "genre": "odoo",
                    "version": VERSION,
                    "active": True,
                }
            )
        question.assert_not_called()
        self.assertEqual(
            ["EL_PHASE=poetry ./script/install/install_locally.sh"],
            self.installe(),
        )


class TestPlusieursVenvs(BancMenu):
    """Le choix du venv : un venv d'Odoo non actif, comparé à son propre
    lock, et le venv de l'outillage, comparé à ses exigences."""

    AUTRE = "odoo17.0_python3.10.18"

    def setUp(self):
        super().setUp()
        Path(f".venv.{self.AUTRE}/bin").mkdir(parents=True)
        for nom in ("python", "poetry"):
            Path(f".venv.{self.AUTRE}/bin/{nom}").write_text("")
        for nom in (
            f"poetry.{self.AUTRE}.lock",
            f"pyproject.{self.AUTRE}.toml",
        ):
            Path("requirement", nom).write_text("")
        Path(".venv.erplibre/bin").mkdir(parents=True)
        Path(".venv.erplibre/bin/python").write_text("")
        Path("conf", "python-erplibre-venv").write_text(".venv.erplibre\n")

    def jouer(self, reponses, simulations=(), sorties_outillage=()):
        sortie = io.StringIO()
        projets = []

        def simuler(_racine, _version, projet=None, **_k):
            projets.append(projet)
            if projet:
                # Le dossier temporaire porte les liens du lock visé.
                self.assertTrue(
                    os.path.realpath(
                        os.path.join(projet, "poetry.lock")
                    ).endswith(f"poetry.{self.AUTRE}.lock")
                )
            return simulations[len(projets) - 1]

        analyses = iter(sorties_outillage)

        def run(commande, *a, **k):
            return subprocess.CompletedProcess(
                commande, 0, json.dumps(next(analyses)), ""
            )

        with (
            patch.object(drift, "simuler", side_effect=simuler),
            patch.object(drift, "relever", return_value={}),
            patch("builtins.input", side_effect=list(reponses)),
            patch("script.todo.python_menu.subprocess.run", side_effect=run),
            patch("sys.stdout", sortie),
        ):
            self.todo.execute_poetry_drift()
        return sortie.getvalue(), projets

    def test_la_liste_met_l_actif_d_abord_et_l_outillage_a_la_fin(self):
        texte, projets = self.jouer(["0"])
        actif = texte.index(f"[1] .venv.{VERSION}")
        self.assertLess(actif, texte.index(f"[2] .venv.{self.AUTRE}"))
        self.assertIn("[3] .venv.erplibre", texte)
        self.assertEqual(projets, [])

    def test_un_venv_non_actif_se_compare_et_s_installe_par_son_lock(self):
        texte, projets = self.jouer(
            ["2", "o"],
            simulations=[self.simulation(SORTIE), self.simulation(ALIGNE)],
        )
        self.assertIsNotNone(projets[0])
        self.assertIn(f"requirement/poetry.{self.AUTRE}.lock", texte)
        commande = self.installe()[0]
        self.assertIn("install --no-root", commande)
        self.assertIn(f".venv.{self.AUTRE}", commande)
        # La version active et ses liens n'ont pas bougé.
        self.assertEqual(
            os.readlink("poetry.lock"), f"requirement/poetry.{VERSION}.lock"
        )

    def test_l_outillage_dit_ce_qui_manque_et_ce_qui_est_de_trop(self):
        etat = {
            "exigences": 3,
            "manquantes": ["absent>=1"],
            "hors_bornes": [{"exigence": "black==2", "installee": "1"}],
            "illisibles": [],
            "de_trop": [["ajoute-a-la-main", "0.1"]],
        }
        aligne = dict(etat, manquantes=[], hors_bornes=[])
        texte, _ = self.jouer(["3", "o"], sorties_outillage=[etat, aligne])
        self.assertIn(f"{todo_i18n.t('Requirements not satisfied:')} 2", texte)
        self.assertIn("absent>=1", texte)
        self.assertIn("black==2", texte)
        self.assertIn("ajoute-a-la-main 0.1", texte)
        self.assertIn("$ .venv.erplibre/bin/python", texte)
        self.assertEqual(
            self.installe(),
            [
                ". ./script/install/lib_pip_provider.sh && el_pip_install"
                f" .venv.erplibre -r {drift.EXIGENCES_OUTILLAGE}"
            ],
        )
        self.assertIn(
            todo_i18n.t("The venv satisfies its requirements:"), texte
        )

    def test_un_numero_inconnu_est_redemande(self):
        texte, _ = self.jouer(["9", "0"])
        self.assertIn("'9'", texte)


class TestDossierTemporaire(unittest.TestCase):
    def test_les_liens_visent_la_version_puis_disparaissent(self):
        racine = tempfile.mkdtemp(prefix="el_drift_projet_")
        self.addCleanup(shutil.rmtree, racine, True)
        Path(racine, "requirement").mkdir()
        for nom in (f"poetry.{VERSION}.lock", f"pyproject.{VERSION}.toml"):
            Path(racine, "requirement", nom).write_text("")
        Path(racine, "poetry.toml").write_text("")
        with drift.projet_temporaire(racine, VERSION) as projet:
            self.assertEqual(
                sorted(os.listdir(projet)),
                ["poetry.lock", "poetry.toml", "pyproject.toml"],
            )
            self.assertTrue(
                os.path.realpath(os.path.join(projet, "poetry.lock")).endswith(
                    f"poetry.{VERSION}.lock"
                )
            )
        self.assertFalse(os.path.exists(projet))


class TestDiagnostiquerVersion(unittest.TestCase):
    def versions(self):
        tmp = tempfile.mkdtemp(prefix="el_drift_json_")
        self.addCleanup(shutil.rmtree, tmp, True)
        Path(tmp, "conf").mkdir()
        Path(tmp, "conf", "supported_version_erplibre.json").write_text(
            json.dumps(SUPPORTEES), encoding="utf-8"
        )
        ancien = os.getcwd()
        os.chdir(tmp)
        try:
            return get_odoo_version()[0]
        finally:
            os.chdir(ancien)

    def test_une_version_supportee(self):
        diag = diagnostiquer_version(VERSION, self.versions())
        self.assertTrue(diag["supportee"])
        self.assertIsNone(diag["remplacante"])

    def test_un_autre_patch_trouve_sa_remplacante(self):
        diag = diagnostiquer_version(NON_SUPPORTEE, self.versions())
        self.assertFalse(diag["supportee"])
        self.assertEqual(VERSION, diag["remplacante"]["erplibre_version"])

    def test_une_version_d_odoo_inconnue_n_a_pas_de_remplacante(self):
        diag = diagnostiquer_version("odoo99.0_python3.99.1", self.versions())
        self.assertFalse(diag["supportee"])
        self.assertIsNone(diag["remplacante"])


class TestLeDiagnosticDeVersion(BancMenu):
    """Le cas réel : .erplibre-version sur un Python que le json ne
    supporte plus. Son lock n'existe pas, et pip-audit, qui ne cherche que
    les venvs du json, ne trouve rien."""

    def passer_sur_non_supportee(self):
        Path(".erplibre-version").write_text(NON_SUPPORTEE + "\n")
        Path(f".venv.{NON_SUPPORTEE}/bin").mkdir(parents=True)
        Path(f".venv.{NON_SUPPORTEE}/bin/poetry").write_text("")
        shutil.rmtree(f".venv.{VERSION}")
        os.remove("poetry.lock")
        os.symlink(f"requirement/poetry.{NON_SUPPORTEE}.lock", "poetry.lock")

    def test_les_ecarts_disent_pourquoi_le_lock_manque(self):
        self.passer_sur_non_supportee()
        texte, _ = self.lancer([self.simulation(ALIGNE)])
        self.simuler.assert_not_called()
        self.assertIn(
            f"{todo_i18n.t('Active version:')} {NON_SUPPORTEE}", texte
        )
        self.assertIn(
            f"{todo_i18n.t('Supported for Odoo')} 18.0 : {VERSION}", texte
        )
        self.assertIn("make install_odoo_18", texte)
        self.assertIn(
            todo_i18n.t(
                "Supported versions (conf/supported_version_erplibre.json):"
            ),
            texte,
        )
        self.assertIn(f"{VERSION} — Odoo 18.0, Python 3.12.16", texte)

    def test_pip_audit_dit_pourquoi_aucun_environnement(self):
        self.passer_sur_non_supportee()
        sortie = io.StringIO()
        with patch("sys.stdout", sortie):
            self.todo.execute_pip_audit()
        texte = sortie.getvalue()
        self.assertIn(
            todo_i18n.t(
                "No installed environment found."
                " Install an Odoo version first."
            ),
            texte,
        )
        self.assertIn("make install_odoo_18", texte)

    def test_une_version_supportee_sans_venv_dit_comment_l_installer(self):
        shutil.rmtree(f".venv.{VERSION}")
        sortie = io.StringIO()
        with patch("sys.stdout", sortie):
            self.todo._afficher_versions_supportees()
        texte = sortie.getvalue()
        self.assertIn(
            f"{todo_i18n.t('To install it:')} make install_odoo_18", texte
        )
        self.assertNotIn(todo_i18n.t("Supported for Odoo"), texte)
        self.assertIn(" ◀", texte)


class TestPlanifierVenvs(unittest.TestCase):
    VERSIONS = [
        {
            "erplibre_version": VERSION,
            "odoo_version": "18.0",
            "python_version": "3.12.16",
            "poetry_version": "2.5.1",
        },
        {
            "erplibre_version": "odoo17.0_python3.10.18",
            "odoo_version": "17.0",
            "python_version": "3.10.18",
            "poetry_version": "1.8.3",
        },
    ]

    def plan(self, venvs, sources):
        return {
            e["cible"]: e
            for e in vm.planifier_venvs(self.VERSIONS, set(venvs), sources)
        }

    def test_un_venv_d_un_autre_patch_donne_une_mise_a_jour(self):
        plan = self.plan({NON_SUPPORTEE}, {"18.0"})
        self.assertEqual(vm.MISE_A_JOUR, plan[VERSION]["action"])
        self.assertEqual(NON_SUPPORTEE, plan[VERSION]["depuis"])

    def test_le_venv_supporte_present_est_a_jour(self):
        plan = self.plan({VERSION, NON_SUPPORTEE}, {"18.0"})
        self.assertEqual(vm.A_JOUR, plan[VERSION]["action"])
        self.assertIsNone(plan[VERSION]["depuis"])

    def test_des_sources_sans_venv_donnent_une_installation(self):
        plan = self.plan(set(), {"17.0"})
        self.assertEqual(
            vm.INSTALLATION, plan["odoo17.0_python3.10.18"]["action"]
        )
        self.assertEqual(vm.SOURCES_ABSENTES, plan[VERSION]["action"])

    def test_un_venv_incomplet_se_reprend(self):
        plan = {
            e["cible"]: e
            for e in vm.planifier_venvs(
                self.VERSIONS, {VERSION}, {"18.0"}, complets=set()
            )
        }
        self.assertEqual(vm.REPRISE, plan[VERSION]["action"])

    def test_un_venv_supporte_inactif_s_active(self):
        plan = {
            e["cible"]: e
            for e in vm.planifier_venvs(
                self.VERSIONS,
                {VERSION, NON_SUPPORTEE},
                {"18.0"},
                active=NON_SUPPORTEE,
            )
        }
        self.assertEqual(vm.MISE_A_JOUR, plan[VERSION]["action"])
        self.assertEqual(NON_SUPPORTEE, plan[VERSION]["depuis"])

    def test_sans_sources_pas_de_mise_a_jour(self):
        plan = self.plan({NON_SUPPORTEE}, set())
        self.assertEqual(vm.SOURCES_ABSENTES, plan[VERSION]["action"])

    def test_la_plus_recente_d_abord(self):
        cibles = [
            e["cible"] for e in vm.planifier_venvs(self.VERSIONS, set(), set())
        ]
        self.assertEqual([VERSION, "odoo17.0_python3.10.18"], cibles)


class TestVersionsPython(BancMenu):
    """Installer ou mettre à jour les venvs sans la phase git."""

    def preparer(self, venvs, sources=("18.0",), active=None, incomplets=()):
        """Des venvs complets — interpréteur et Poetry — sauf ceux de
        `incomplets`, qui n'ont qu'un dossier bin vide."""
        shutil.rmtree(f".venv.{VERSION}")
        for venv in list(venvs) + list(incomplets):
            Path(f".venv.{venv}/bin").mkdir(parents=True)
        for venv in venvs:
            for outil in ("python", "poetry"):
                Path(f".venv.{venv}/bin/{outil}").write_text("")
        for odoo in sources:
            Path(f"odoo{odoo}/odoo").mkdir(parents=True)
            Path(f"odoo{odoo}/odoo/odoo-bin").write_text("")
        Path(".erplibre-version").write_text((active or venvs[0]) + "\n")

    def jouer(self, reponses, statuts=None):
        sortie = io.StringIO()
        statuts = iter(statuts or [])
        self.todo.execute.exec_command_live.side_effect = lambda *a, **k: next(
            statuts, 0
        )
        with (
            patch("builtins.input", side_effect=list(reponses)) as question,
            patch("sys.stdout", sortie),
        ):
            self.todo.execute_python_versions()
        return sortie.getvalue(), question

    def test_mise_a_jour_d_un_patch_ancien_sans_les_depots(self):
        self.preparer([NON_SUPPORTEE])
        texte, _ = self.jouer(["1", "o"])
        self.assertIn(f"[1] {VERSION}", texte)
        self.assertEqual(
            [
                f'./script/install/install_venv.sh "Odoo" .venv.{VERSION}'
                " 3.12.16",
                f"./script/version/update_env_version.py --erplibre_version"
                f" {VERSION} --switch",
                "EL_PHASE=poetry ./script/install/install_locally.sh",
            ],
            self.installe(),
        )
        for commande in self.installe():
            self.assertNotIn("repo", commande)
            self.assertNotIn("install_dev", commande)

    def test_le_defaut_est_non(self):
        self.preparer([NON_SUPPORTEE])
        self.jouer(["1", ""])
        self.assertEqual([], self.installe())

    def test_un_venv_rate_n_active_rien(self):
        # install_venv.sh échoue : ni --switch ni poetry, la version active
        # ne bouge pas.
        self.preparer([NON_SUPPORTEE])
        texte, _ = self.jouer(["1", "o"], statuts=[1])
        self.assertEqual(1, len(self.installe()), self.installe())
        self.assertIn("❌", texte)

    def test_une_autre_odoo_rend_la_main_a_celle_de_depart(self):
        # Odoo 18 actif et à jour ; on installe le venv d'Odoo 17. La
        # dernière cible laisse 17 active : on revient sur 18.
        self.preparer([VERSION], sources=("18.0", "17.0"), active=VERSION)
        self.jouer(["1", "o"])
        commandes = self.installe()
        self.assertIn(
            "./script/version/update_env_version.py --erplibre_version"
            " odoo17.0_python3.10.18 --switch",
            commandes,
        )
        self.assertEqual(
            "./script/version/update_env_version.py --erplibre_version"
            f" {VERSION} --switch",
            commandes[-1],
        )

    def test_rien_a_faire_ne_pose_aucune_question(self):
        self.preparer([VERSION], active=VERSION)
        texte, question = self.jouer([])
        self.assertIn(
            todo_i18n.t("No Python version to install or update."), texte
        )
        question.assert_not_called()

    def test_l_ancien_venv_est_signale_et_garde(self):
        self.preparer([VERSION, NON_SUPPORTEE], active=VERSION)
        texte, _ = self.jouer([])
        self.assertIn(f".venv.{NON_SUPPORTEE}", texte)
        self.assertTrue(Path(f".venv.{NON_SUPPORTEE}").is_dir())

    def test_un_venv_incomplet_est_propose_a_la_reprise(self):
        # Une mise à jour coupée laisse le dossier du venv sans Poetry : il
        # n'est pas « à jour », il se reprend.
        self.preparer([NON_SUPPORTEE], incomplets=[VERSION])
        texte, _ = self.jouer(["1", "o"])
        self.assertIn(todo_i18n.t("incomplete venv: resume"), texte)
        self.assertEqual(3, len(self.installe()))

    def test_un_venv_supporte_inactif_est_propose_a_l_activation(self):
        # Le venv 3.12.16 existe, mais .erplibre-version est encore 3.12.10.
        self.preparer([VERSION, NON_SUPPORTEE], active=NON_SUPPORTEE)
        texte, _ = self.jouer(["1", "o"])
        self.assertIn(
            f"{todo_i18n.t('activate instead of')} {NON_SUPPORTEE}", texte
        )
        self.assertIn(
            "./script/version/update_env_version.py --erplibre_version"
            f" {VERSION} --switch",
            self.installe(),
        )

    def test_sans_sources_aucune_mise_a_jour_n_est_proposee(self):
        self.preparer([NON_SUPPORTEE], sources=())
        texte, question = self.jouer([])
        self.assertIn(todo_i18n.t("Odoo sources missing: full install"), texte)
        question.assert_not_called()

    def test_le_retour_prevu_est_montre_avant_la_confirmation(self):
        self.preparer([VERSION], sources=("18.0", "17.0"), active=VERSION)
        texte, _ = self.jouer(["1", ""])
        confirmation = texte[texte.index(todo_i18n.t("Will execute:")) :]
        self.assertIn(
            "./script/version/update_env_version.py --erplibre_version"
            f" {VERSION} --switch",
            confirmation,
        )

    def test_finir_sur_une_autre_odoo_avertit_pour_config_conf(self):
        # Départ sur un patch non supporté, sans venv supporté pour lui : le
        # retour est impossible, et la fin sur Odoo 17 doit être dite.
        self.preparer([NON_SUPPORTEE], sources=("17.0",), active=NON_SUPPORTEE)

        def executer(commande, **_kwargs):
            if "--switch" in commande:
                cible = commande.split("--erplibre_version ")[1].split()[0]
                Path(".erplibre-version").write_text(cible + "\n")
            return 0

        self.todo.execute.exec_command_live.side_effect = executer
        sortie = io.StringIO()
        with (
            patch("builtins.input", side_effect=["1", "o"]),
            patch("sys.stdout", sortie),
        ):
            self.todo.execute_python_versions()
        texte = sortie.getvalue()
        self.assertIn("./script/generate_config.sh", texte)
        self.assertIn("odoo17.0_python3.10.18", texte)

    def test_une_cible_reussie_est_inscrite_dans_l_etat(self):
        self.preparer([NON_SUPPORTEE])
        self.jouer(["1", "o"])
        etat = json.loads(Path(".erplibre-state.json").read_text())
        entree = etat["odoo_versions"]["18.0"]
        self.assertEqual("3.12.16", entree["python"])
        self.assertEqual("2.5.1", entree["poetry"])
        self.assertTrue(entree["installed"])

    def test_une_cible_ratee_n_est_pas_inscrite(self):
        self.preparer([NON_SUPPORTEE])
        self.jouer(["1", "o"], statuts=[0, 0, 1])
        etat_fichier = Path(".erplibre-state.json")
        if etat_fichier.exists():
            etat = json.loads(etat_fichier.read_text())
            self.assertNotEqual(
                "3.12.16",
                etat["odoo_versions"].get("18.0", {}).get("python"),
            )

    def test_un_numero_invalide_redemande(self):
        self.preparer([NON_SUPPORTEE])
        texte, _ = self.jouer(["9", "1", ""])
        self.assertIn(todo_i18n.t("Error, cannot understand value"), texte)
        self.assertEqual([], self.installe())


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
            f"[10] {todo_i18n.t('Git repository - Repositories and git tools')}",
            sortie[0],
        )
        self.assertIn(
            f"[11] {todo_i18n.t('Database - Database tools')}", sortie[0]
        )

    def test_le_fil_d_ariane_nomme_le_menu(self):
        self.assertEqual(
            "Python", TODO._MENU_LABELS.get("prompt_execute_python")
        )


if __name__ == "__main__":
    unittest.main()
