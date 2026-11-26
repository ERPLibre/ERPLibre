#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long OpenTofu de bout en bout, gardé sans rien créer.

`long_test/opentofu_proxmox.py` monte un Proxmox jetable dans QEMU, y
applique un parc d'une VM, vérifie ssh, un second plan vide, la destruction
et l'absence de la VM. Ces tests-ci n'ouvrent aucune session ssh, ne lancent
ni sudo ni `tofu` et n'écrivent pas dans le vrai `private/` : le moteur,
l'hôte et TODO sont des doublures.
"""

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "long_test"))
sys.argv = ["todo.py"]

import descente  # noqa: E402
import opentofu_proxmox as otp  # noqa: E402

from script.opentofu import spec as spec_parc  # noqa: E402
from script.opentofu.moteur import Changement, Resultat  # noqa: E402

SCRIPT = RACINE / "long_test" / "opentofu_proxmox.py"


def _interdit(*args, **kwargs):
    raise AssertionError(f"sous-processus lancé : {args[:1]}")


class LaPlace(unittest.TestCase):
    def test_it_lives_out_of_the_unit_runner_and_is_executable(self):
        self.assertTrue(SCRIPT.exists())
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_names(self):
        self.assertEqual(otp.NOM_BASE, "test-tofu-pve")
        self.assertEqual(otp.OUTIL, "opentofu_proxmox")
        self.assertEqual(otp.PARC, "test-tofu")
        self.assertEqual(otp.VM, "test-tofu-vm-1")
        self.assertEqual(otp.Descente.NOM_BASE, "test-tofu-pve")
        self.assertEqual(otp.Descente.OUTIL, "opentofu_proxmox")

    def test_steps_in_order(self):
        self.assertEqual(
            otp.ETAPES,
            (
                "monter_pve",
                "preparer_hote",
                "plan_1",
                "apply",
                "ssh",
                "plan_2",
                "destroy",
                "absence",
            ),
        )

    def test_registries_hold_the_script(self):
        from script.todo.longtest_menu import SCRIPTS_DEFAISABLES

        self.assertIn("opentofu_proxmox.py", descente.SCRIPTS)
        self.assertIn("opentofu_proxmox.py", SCRIPTS_DEFAISABLES)

    def test_readme_base_has_a_section(self):
        texte = (RACINE / "long_test" / "README.base.md").read_text("utf-8")
        self.assertEqual(texte.count("## opentofu_proxmox.py"), 2)


class LeMenu(unittest.TestCase):
    def test_the_menu_dispatches_plan_and_run(self):
        """15 : le plan, 16 : la course. Les entrées existantes gardent
        leur numéro."""
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vus = []
        todo.fill_help_info = lambda choix: ""
        todo._longtest_run = lambda nom, args="", demander=None: vus.append(
            (nom, args)
        )
        todo._longtest_defaire = lambda: vus.append("défaire")
        with mock.patch(
            "script.todo.longtest_menu.click.prompt",
            side_effect=["15", "16", "12", "13", "0"],
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                todo.prompt_execute_longtest()
        self.assertEqual(
            vus,
            [
                ("opentofu_proxmox.py", "--dry-run"),
                ("opentofu_proxmox.py", ""),
                "défaire",
                ("usb_passthrough.py", "--dry-run"),
            ],
        )

    def test_every_label_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for cle in (
            "OpenTofu on a disposable Proxmox: plan only (dry-run)",
            "OpenTofu on a disposable Proxmox: run it",
        ):
            with self.subTest(cle=cle):
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))


class LEssaiABlanc(unittest.TestCase):
    """`--dry-run` : ni sudo, ni tofu, ni réseau, ni écriture de parc."""

    def setUp(self):
        self.maison = tempfile.TemporaryDirectory()
        self.addCleanup(self.maison.cleanup)

    def _lancer(self):
        sortie = io.StringIO()
        with contextlib.ExitStack() as pile:
            pile.enter_context(
                mock.patch.dict(os.environ, {"HOME": self.maison.name})
            )
            pile.enter_context(
                mock.patch.object(
                    descente, "capacite_hote", return_value=(16, 32000, 200)
                )
            )
            pile.enter_context(mock.patch("subprocess.run", _interdit))
            pile.enter_context(mock.patch("subprocess.Popen", _interdit))
            pile.enter_context(
                mock.patch.object(spec_parc, "sauver", _interdit)
            )
            pile.enter_context(mock.patch.object(otp, "prealables", _interdit))
            pile.enter_context(contextlib.redirect_stdout(sortie))
            code = otp.principal(["--dry-run"])
        return code, sortie.getvalue()

    def test_dry_run_creates_nothing_and_lists_the_steps(self):
        code, sortie = self._lancer()
        self.assertEqual(code, 0, sortie[-1500:])
        self.assertIn("test-tofu-pve-1", sortie)
        self.assertIn("dry-run", sortie)
        positions = [sortie.find(f"── {e}") for e in otp.ETAPES[1:]]
        self.assertNotIn(-1, positions, sortie[-1500:])
        self.assertEqual(positions, sorted(positions))
        # La commande de création est montrée, sans sudo devant.
        ligne = next(x for x in sortie.splitlines() if "deploy_qemu.py" in x)
        self.assertNotIn("sudo", ligne)
        self.assertIn("test-tofu-pve-1", ligne)

    def test_dry_run_report_is_named_apart_and_claims_nothing(self):
        self._lancer()
        dossier = Path(self.maison.name) / ".erplibre" / "longtest"
        rapports = sorted(dossier.glob("*.json"))
        self.assertEqual(len(rapports), 1, rapports)
        self.assertTrue(rapports[0].name.startswith("test-tofu-pve-"))
        self.assertTrue(rapports[0].name.endswith("-dryrun.json"))
        rapport = json.loads(rapports[0].read_text("utf-8"))
        self.assertTrue(rapport["dry_run"])
        self.assertEqual(rapport["outil"], "opentofu_proxmox")
        self.assertEqual(list(rapport["etapes"]), list(otp.ETAPES))
        self.assertTrue(
            all(e["statut"] == "plan" for e in rapport["etapes"].values())
        )
        self.assertFalse(rapport["verdict"])


class LesPrealables(unittest.TestCase):
    def _tout_va(self, pile):
        pile.enter_context(
            mock.patch.object(
                otp.outil, "trouver_tofu", return_value="/opt/tofu"
            )
        )
        pile.enter_context(
            mock.patch.object(otp.outil, "version_tofu", return_value="1.13.9")
        )
        pile.enter_context(
            mock.patch.object(otp, "cle_publique", return_value="/k.pub")
        )
        pile.enter_context(
            mock.patch.object(otp, "agent_ssh_charge", return_value=True)
        )
        pile.enter_context(
            mock.patch.object(otp, "kvm_present", return_value=True)
        )
        pile.enter_context(
            mock.patch.object(otp, "imbrication_active", return_value=True)
        )
        pile.enter_context(
            mock.patch.object(otp, "autre_descente", return_value=[])
        )
        dossier = tempfile.TemporaryDirectory()
        pile.callback(dossier.cleanup)
        pile.enter_context(
            mock.patch.object(spec_parc, "RACINE_PARCS", Path(dossier.name))
        )

    def test_nothing_missing(self):
        with contextlib.ExitStack() as pile:
            self._tout_va(pile)
            self.assertEqual(otp.prealables(), [])

    def test_missing_tofu_refuses_with_its_remedy_and_creates_nothing(self):
        sortie = io.StringIO()
        with contextlib.ExitStack() as pile:
            self._tout_va(pile)
            pile.enter_context(
                mock.patch.object(otp.outil, "trouver_tofu", return_value=None)
            )
            mener = pile.enter_context(mock.patch.object(otp, "mener"))
            pile.enter_context(contextlib.redirect_stdout(sortie))
            code = otp.principal([])
        self.assertEqual(code, 1)
        mener.assert_not_called()
        texte = sortie.getvalue()
        self.assertIn("tofu", texte)
        self.assertIn("Check or install tofu", texte)

    def test_old_tofu_is_refused(self):
        with contextlib.ExitStack() as pile:
            self._tout_va(pile)
            pile.enter_context(
                mock.patch.object(
                    otp.outil, "version_tofu", return_value="1.9.0"
                )
            )
            manques = otp.prealables()
        self.assertEqual(len(manques), 1)
        self.assertIn("1.9.0", manques[0])
        self.assertIn(">= 1.10", manques[0])

    def test_an_existing_fleet_is_refused(self):
        with contextlib.ExitStack() as pile:
            self._tout_va(pile)
            spec_parc.dossier_parc(otp.PARC, spec_parc.RACINE_PARCS).mkdir()
            manques = otp.prealables()
        self.assertEqual(len(manques), 1)
        self.assertIn("--detruire", manques[0])


SECRET_PLAN = "valeur-du-plan-a-ne-jamais-afficher"


class _Moteur:
    """Doublure du moteur : deux plans, un apply, un destroy, des sorties."""

    def __init__(self, racine, plans, sorties=None, apply_ok=True):
        self.racine = racine
        self.apply_ok = apply_ok
        self.plans = list(plans)
        self.appels = []
        self.captures = []
        self._sorties = (
            {otp.VM: {"vmid": 100, "ip": "10.10.10.150"}}
            if sorties is None
            else sorties
        )

    def planifier(self, spec, journal):
        self.appels.append("planifier")
        spec["vms"][0]["vmid"] = 100
        return Resultat(True, "plan"), self.plans.pop(0)

    def _capturer(self, spec, args, journal):
        self.captures.append(list(args))
        return Resultat(True), '{"secret": "%s"}' % SECRET_PLAN

    def appliquer(self, spec, journal):
        self.appels.append("appliquer")
        return Resultat(self.apply_ok, "apply")

    def detruire(self, spec, journal):
        self.appels.append("detruire")
        return Resultat(True, "destroy")

    def sorties(self, spec):
        return self._sorties


class _Todo:
    def __init__(self, casse=False):
        self.appels = []
        self.casse = casse

    def _tofu_apres_apply(self, spec, sorties, nouvelles):
        self.appels.append(("apres_apply", sorted(nouvelles)))
        if self.casse:
            raise OSError("ssh config illisible")

    def _tofu_apres_destroy(self, spec):
        self.appels.append("apres_destroy")

    @staticmethod
    def _tofu_alias(spec, vm):
        return f"{spec['cible']['hote']['target']}+{vm}"

    @staticmethod
    def _ssh_config_block(alias):
        return {"names": [alias], "proxyjump": "test-tofu-pve-1"}


PLAN_1 = [
    Changement("creer", otp.VM, "vm"),
    Changement("creer", otp.VM, "cloud-init"),
    Changement("creer", "debian-13-genericcloud-amd64.qcow2", "image"),
]


class LesEtapesTofu(unittest.TestCase):
    """Les étapes après le PVE, sur des doublures : verdict sur l'état."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parcs = Path(self.tmp.name) / "parcs"
        self.chemin = os.path.join(self.tmp.name, "test-tofu-pve-1.json")
        self.journal = os.path.join(self.tmp.name, "test-tofu-pve-1.log")
        self.captures = Path(self.chemin[: -len(".json")])
        self.lances = []
        self.sortie = ""

    def _descente(self):
        d = otp.Descente(
            {"niveaux": [], "demandee": 1, "atteignable": 1, "arret": ""},
            self.journal,
            False,
            self.chemin,
        )
        d.etages = [
            {
                "niveau": 1,
                "nom": "test-tofu-pve-1",
                "alias": "test-tofu-pve-1",
                "cree": True,
                "uuid": "u",
                "ok": True,
            }
        ]
        return d

    def _run(self, cmd, **kwargs):
        self.lances.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def _derouler(
        self,
        plans,
        qm_list="",
        preparer_ok=True,
        sorties=None,
        todo=None,
        apply_ok=True,
    ):
        d = self._descente()
        mot = _Moteur(self.parcs, plans, sorties, apply_ok)
        todo = todo or _Todo()
        ecran = io.StringIO()

        def preparer_hote(spec, brut, recreer=False, racine=None):
            return Resultat(preparer_ok, "prêt"), dict(spec)

        with contextlib.ExitStack() as pile:
            pile.enter_context(
                mock.patch.object(spec_parc, "RACINE_PARCS", self.parcs)
            )
            pile.enter_context(
                mock.patch.object(
                    otp.Descente, "preparer_parent", return_value=("l",)
                )
            )
            pile.enter_context(
                mock.patch.object(otp.Descente, "_todo", return_value=todo)
            )
            pile.enter_context(
                mock.patch.object(
                    otp.jeton_proxmox, "preparer_hote", preparer_hote
                )
            )
            pile.enter_context(
                mock.patch.object(otp.moteur, "moteur_pour", return_value=mot)
            )
            pile.enter_context(
                mock.patch.object(
                    otp.resolution,
                    "executer_ssh",
                    return_value=lambda cmd: (0, qm_list),
                )
            )
            pile.enter_context(
                mock.patch.object(otp, "cle_publique", return_value="/k.pub")
            )
            pile.enter_context(mock.patch("subprocess.run", self._run))
            pile.enter_context(mock.patch("time.sleep"))
            pile.enter_context(contextlib.redirect_stdout(ecran))
            d.etapes_tofu()
        self.sortie = ecran.getvalue()
        return d, mot, todo

    def test_everything_ok_gives_a_positive_verdict(self):
        d, mot, todo = self._derouler([PLAN_1, []])
        self.assertEqual(list(d.etapes), list(otp.ETAPES[1:]))
        for nom, etape in d.etapes.items():
            with self.subTest(etape=nom):
                self.assertEqual(etape["statut"], "ok", etape)
                self.assertIn("secondes", etape)
        self.assertEqual(
            mot.appels, ["planifier", "appliquer", "planifier", "detruire"]
        )
        self.assertIn(("apres_apply", [otp.VM]), todo.appels)
        self.assertIn("apres_destroy", todo.appels)
        ssh = [c for c in self.lances if c[0] == "ssh"]
        self.assertEqual(ssh[0][-2:], [f"test-tofu-pve-1+{otp.VM}", "true"])
        self.assertIn("BatchMode=yes", ssh[0])
        d.etapes["monter_pve"] = {"statut": "ok", "secondes": 1}
        self.assertTrue(d.verdict())

    def test_the_plan_json_is_kept_private(self):
        _d, mot, _todo = self._derouler([PLAN_1, []])
        capture = self.captures / "show_plan.json"
        self.assertIn(SECRET_PLAN, capture.read_text("utf-8"))
        self.assertEqual(stat.S_IMODE(capture.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.captures.stat().st_mode), 0o700)
        # Par le moteur, sur son plan sauvé ; un seul plan capturé quand le
        # second est vide.
        self.assertEqual(
            mot.captures, [["show", "-json", "-no-color", "plan.bin"]]
        )
        self.assertFalse((self.captures / "show_plan_2.json").exists())

    def test_the_plan_content_never_reaches_screen_or_journal(self):
        modif = [Changement("modifier", otp.VM, "vm", [("ram", 1, 2)])]
        self._derouler([PLAN_1, modif])
        self.assertTrue((self.captures / "show_plan_2.json").is_file())
        self.assertIn("show_plan.json", self.sortie)
        self.assertNotIn(SECRET_PLAN, self.sortie)
        journal = Path(self.journal).read_text("utf-8")
        self.assertIn("show_plan.json", journal)
        self.assertNotIn(SECRET_PLAN, journal)
        self.assertNotIn(SECRET_PLAN, Path(self.chemin).read_text("utf-8"))

    def test_a_second_plan_with_changes_fails_but_still_destroys(self):
        modif = [Changement("modifier", otp.VM, "vm", [("ram", 1, 2)])]
        d, mot, _todo = self._derouler([PLAN_1, modif])
        self.assertEqual(d.etapes["plan_2"]["statut"], "echec")
        self.assertIn("ram", d.etapes["plan_2"]["detail"])
        self.assertIn("show_plan_2.json", d.etapes["plan_2"]["detail"])
        self.assertEqual(d.etapes["destroy"]["statut"], "ok")
        self.assertEqual(d.etapes["absence"]["statut"], "ok")
        self.assertFalse(d.verdict())

    def test_missing_outputs_after_apply_still_destroy(self):
        """L'apply a tourné : la VM est dans l'état tofu. Une sortie
        manquante ne doit jamais laisser la VM derrière la course."""
        d, mot, _todo = self._derouler([PLAN_1, []], sorties={})
        self.assertEqual(d.etapes["apply"]["statut"], "ok")
        self.assertIn("⚠", d.etapes["apply"]["detail"])
        self.assertIn("detruire", mot.appels)
        self.assertEqual(d.etapes["destroy"]["statut"], "ok")
        self.assertEqual(d.etapes["absence"]["statut"], "ok")

    def test_a_broken_after_apply_still_destroys(self):
        d, mot, _todo = self._derouler([PLAN_1, []], todo=_Todo(casse=True))
        self.assertIn("ssh config illisible", d.etapes["apply"]["detail"])
        self.assertIn("detruire", mot.appels)
        self.assertEqual(d.etapes["absence"]["statut"], "ok")

    def test_a_failed_apply_stops_the_rest(self):
        d, mot, _todo = self._derouler([PLAN_1], apply_ok=False)
        self.assertEqual(d.etapes["apply"]["statut"], "echec")
        self.assertNotIn("detruire", mot.appels)
        for nom in ("ssh", "plan_2", "destroy", "absence"):
            self.assertEqual(d.etapes[nom]["statut"], "saute")

    def test_an_unexpected_first_plan_stops_before_apply(self):
        plan = PLAN_1 + [Changement("detruire", "autre", "vm")]
        d, mot, _todo = self._derouler([plan])
        self.assertEqual(d.etapes["plan_1"]["statut"], "echec")
        self.assertNotIn("appliquer", mot.appels)
        for nom in ("apply", "ssh", "plan_2", "destroy", "absence"):
            self.assertEqual(d.etapes[nom]["statut"], "saute")
        self.assertFalse(d.verdict())

    def test_a_vm_still_listed_after_destroy_fails_absence(self):
        qm = (
            "      VMID NAME                 STATUS     MEM(MB)    "
            "BOOTDISK(GB) PID\n"
            f"       100 {otp.VM}       running    1024       "
            "8.00 1234\n"
        )
        d, _mot, _todo = self._derouler([PLAN_1, []], qm_list=qm)
        self.assertEqual(d.etapes["absence"]["statut"], "echec")
        self.assertFalse(d.verdict())

    def test_a_failed_host_preparation_skips_the_rest(self):
        d, mot, _todo = self._derouler([PLAN_1, []], preparer_ok=False)
        self.assertEqual(d.etapes["preparer_hote"]["statut"], "echec")
        self.assertEqual(mot.appels, [])

    def test_steps_are_saved_with_the_level_for_undo(self):
        """Chaque étape réécrit le rapport partiel : l'étage 1 y reste, sans
        quoi --detruire ne trouverait plus le PVE."""
        self._derouler([PLAN_1, []])
        rapport = json.loads(Path(self.chemin).read_text("utf-8"))
        self.assertEqual(rapport["outil"], "opentofu_proxmox")
        self.assertEqual(rapport["etages"][0]["nom"], "test-tofu-pve-1")
        self.assertIn("absence", rapport["etapes"])
        self.assertIn("pid", rapport)


class LeDefaire(unittest.TestCase):
    """Le parc et les captures ne partent qu'après un PVE défait d'après un
    rapport."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parcs = Path(self.tmp.name) / "parcs"
        (self.parcs / otp.PARC).mkdir(parents=True)
        self.captures = Path(self.tmp.name) / "test-tofu-pve-1"
        self.captures.mkdir()
        self.rapport = {"fichier": str(self.captures) + ".json"}

    def _defaire(self, argv, code_detruire, rapport):
        sortie = io.StringIO()
        with contextlib.ExitStack() as pile:
            pile.enter_context(
                mock.patch.dict(os.environ, {"HOME": self.tmp.name})
            )
            pile.enter_context(
                mock.patch.object(spec_parc, "RACINE_PARCS", self.parcs)
            )
            pile.enter_context(
                mock.patch.object(otp, "dernier_rapport", return_value=rapport)
            )
            detruire = pile.enter_context(
                mock.patch.object(otp, "detruire", return_value=code_detruire)
            )
            pile.enter_context(contextlib.redirect_stdout(sortie))
            code = otp.principal(argv)
        return code, detruire, sortie.getvalue()

    def test_dry_run_lists_fleet_and_captures_and_keeps_them(self):
        code, detruire, sortie = self._defaire(
            ["--detruire", "--dry-run"], 0, self.rapport
        )
        self.assertEqual(code, 0)
        self.assertTrue(detruire.call_args.kwargs["dry_run"])
        self.assertTrue((self.parcs / otp.PARC).is_dir())
        self.assertTrue(self.captures.is_dir())
        self.assertIn(str(self.parcs / otp.PARC), sortie)
        self.assertIn(str(self.captures), sortie)

    def test_fleet_and_captures_go_after_the_pve(self):
        code, _d, _s = self._defaire(["--detruire"], 0, self.rapport)
        self.assertEqual(code, 0)
        self.assertFalse((self.parcs / otp.PARC).exists())
        self.assertFalse(self.captures.exists())

    def test_fleet_stays_when_the_pve_stays(self):
        code, _d, _s = self._defaire(["--detruire"], 1, self.rapport)
        self.assertEqual(code, 1)
        self.assertTrue((self.parcs / otp.PARC).is_dir())
        self.assertTrue(self.captures.is_dir())

    def test_fleet_stays_when_no_report_was_undone(self):
        """« aucun rapport : rien à défaire » rend 0 sans avoir rien
        détruit : la VM du parc peut encore vivre quelque part."""
        code, _d, sortie = self._defaire(["--detruire"], 0, {})
        self.assertEqual(code, 0)
        self.assertTrue((self.parcs / otp.PARC).is_dir())
        self.assertIn("aucun rapport", sortie)


if __name__ == "__main__":
    unittest.main()
