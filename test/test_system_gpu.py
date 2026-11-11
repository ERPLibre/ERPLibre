#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mémoire GPU par processus : nvidia-smi (XML, puis CSV en repli) et
/proc/<pid>/fdinfo pour les autres pilotes DRM.

Les sorties de nvidia-smi et l'arbre /proc sont fabriqués : un test ne
dépend ni de la carte ni des pilotes du poste où il tourne.
"""

import ast
import inspect
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_gpu as sg  # noqa: E402
from script.todo import system_menu as sm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

MIO = 1024**2

XML = """<?xml version="1.0" ?>
<!DOCTYPE nvidia_smi_log SYSTEM "nvsmi_device_v12.dtd">
<nvidia_smi_log>
  <driver_version>550.00</driver_version>
  <attached_gpus>2</attached_gpus>
  <gpu id="00000000:01:00.0">
    <product_name>Carte Exemple 12G</product_name>
    <uuid>GPU-aaaa</uuid>
    <fb_memory_usage>
      <total>12288 MiB</total>
      <reserved>256 MiB</reserved>
      <used>1100 MiB</used>
      <free>10932 MiB</free>
    </fb_memory_usage>
    <processes>
      <process_info>
        <gpu_instance_id>N/A</gpu_instance_id>
        <compute_instance_id>N/A</compute_instance_id>
        <pid>4242</pid>
        <type>G</type>
        <process_name>/usr/lib/xorg/Xorg</process_name>
        <used_memory>100 MiB</used_memory>
      </process_info>
      <process_info>
        <pid>4343</pid>
        <type>C</type>
        <process_name>python3</process_name>
        <used_memory>800 MiB</used_memory>
      </process_info>
    </processes>
  </gpu>
  <gpu id="00000000:02:00.0">
    <product_name>Carte Exemple 8G</product_name>
    <uuid>GPU-bbbb</uuid>
    <fb_memory_usage>
      <total>8192 MiB</total>
      <used>5 MiB</used>
    </fb_memory_usage>
    <processes>
    </processes>
  </gpu>
</nvidia_smi_log>
"""

AMDGPU = """pos:\t0
flags:\t02100002
drm-driver:\tamdgpu
drm-client-id:\t27
drm-pdev:\t0000:03:00.0
pasid:\t32789
drm-memory-vram:\t819200 KiB
drm-memory-gtt: \t4096 KiB
drm-memory-cpu: \t0 KiB
drm-engine-gfx:\t1234 ns
"""

I915 = """pos:\t0
drm-driver:\ti915
drm-client-id:\t5
drm-pdev:\t0000:00:02.0
drm-total-system0:\t64 MiB
drm-shared-system0:\t0
drm-resident-system0:\t48 MiB
"""

SANS_STATS = """pos:\t0
flags:\t02100002
mnt_id:\t39
"""


class ArbreProc:
    """Un faux /proc : chaque processus a comm, cmdline, et des fd qui
    pointent où on veut, avec leur fdinfo."""

    def __init__(self, racine):
        self.racine = racine

    def processus(self, pid, comm, cmdline, fds=(), lisible=True):
        dossier = os.path.join(self.racine, str(pid))
        os.makedirs(os.path.join(dossier, "fd"))
        os.makedirs(os.path.join(dossier, "fdinfo"))
        with open(os.path.join(dossier, "comm"), "w") as fh:
            fh.write(comm + "\n")
        with open(os.path.join(dossier, "cmdline"), "w") as fh:
            fh.write("".join(a + "\0" for a in cmdline))
        for numero, (cible, fdinfo) in enumerate(fds, start=3):
            os.symlink(cible, os.path.join(dossier, "fd", str(numero)))
            with open(os.path.join(dossier, "fdinfo", str(numero)), "w") as fh:
                fh.write(fdinfo)
        if not lisible:
            os.chmod(os.path.join(dossier, "fd"), 0)


class TestLesTailles(unittest.TestCase):
    def test_units_and_missing_values(self):
        self.assertEqual(sg.taille("812 MiB"), 812 * MIO)
        self.assertEqual(sg.taille("4096 KiB"), 4096 * 1024)
        self.assertEqual(sg.taille("0"), 0)
        self.assertEqual(sg.taille("800", "MiB"), 800 * MIO)
        for absent in ("N/A", "[N/A]", "[Not Supported]", "", None):
            self.assertIsNone(sg.taille(absent), absent)


class TestNvidia(unittest.TestCase):
    def test_xml_lists_graphics_and_compute_processes(self):
        gpus = sg.nvidia_xml(XML)
        self.assertEqual([g["index"] for g in gpus], [0, 1])
        premier = gpus[0]
        self.assertEqual(premier["nom"], "Carte Exemple 12G")
        self.assertEqual(premier["utilisee"], 1100 * MIO)
        self.assertEqual(premier["totale"], 12288 * MIO)
        self.assertEqual(
            [
                (p["pid"], p["type"], p["memoire"])
                for p in premier["processus"]
            ],
            [(4242, "G", 100 * MIO), (4343, "C", 800 * MIO)],
        )
        self.assertEqual(gpus[1]["processus"], [])

    def test_unreadable_xml_gives_none(self):
        self.assertIsNone(sg.nvidia_xml("pas du xml <"))

    def test_csv_keeps_a_comma_in_the_process_name(self):
        gpus = sg.nvidia_csv(
            "0, GPU-aaaa, Carte Exemple 12G, 1100, 12288\n",
            "4343, python3 train.py --a=1,2, 800, GPU-aaaa\n"
            "4444, worker, [N/A], GPU-aaaa\n"
            "9999, ailleurs, 10, GPU-inconnu\n",
        )
        processus = gpus[0]["processus"]
        self.assertEqual(
            [(p["pid"], p["nom"], p["memoire"]) for p in processus],
            [
                (4343, "python3 train.py --a=1,2", 800 * MIO),
                (4444, "worker", None),
            ],
        )
        self.assertTrue(all(p["type"] == "C" for p in processus))

    def test_csv_is_the_fallback_when_xml_fails(self):
        sorties = {
            "-q": None,
            "--query-gpu": "0, GPU-aaaa, Carte, 10, 100\n",
            "--query-compute-apps": "1, a, 5, GPU-aaaa\n",
        }

        def commande(args, timeout=5):
            return sorties[args[1].split("=")[0]]

        with mock.patch.object(sg, "commande", side_effect=commande):
            res = sg.nvidia()
        self.assertEqual(res["source"], "nvidia-smi --query-compute-apps")
        self.assertEqual(res["gpus"][0]["processus"][0]["pid"], 1)

    def test_no_nvidia_smi_gives_none(self):
        with mock.patch.object(sg, "commande", return_value=None):
            self.assertIsNone(sg.nvidia())


class TestFdinfo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proc = ArbreProc(self.tmp.name)

    def test_memory_per_process_and_region(self):
        self.proc.processus(
            100,
            "firefox",
            ["firefox"],
            fds=[
                ("/dev/dri/renderD128", AMDGPU),
                ("/home/x/fichier", "pos:\t0\n"),
            ],
        )
        self.proc.processus(
            200, "glxgears", ["glxgears"], fds=[("/dev/dri/card0", I915)]
        )
        res = sg.drm(self.tmp.name)
        par_pid = {p["pid"]: p for p in res["processus"]}
        self.assertEqual(
            par_pid[100]["regions"],
            {"vram": 819200 * 1024, "gtt": 4096 * 1024, "cpu": 0},
        )
        self.assertEqual(par_pid[100]["pilote"], "amdgpu")
        self.assertEqual(par_pid[100]["pci"], "0000:03:00.0")
        # resident l'emporte sur total, et shared n'est pas une valeur.
        self.assertEqual(par_pid[200]["regions"], {"system0": 48 * MIO})
        self.assertEqual(res["sans_stats"], [])

    def test_a_client_shared_after_a_fork_counts_once(self):
        for pid in (100, 101):
            self.proc.processus(
                pid, "app", ["app"], fds=[("/dev/dri/renderD128", AMDGPU)]
            )
        res = sg.drm(self.tmp.name)
        self.assertEqual([p["pid"] for p in res["processus"]], [100])
        self.assertEqual(res["sans_stats"], [])

    def test_a_driver_without_statistics_is_named(self):
        self.proc.processus(
            300, "Xorg", ["Xorg"], fds=[("/dev/dri/card0", SANS_STATS)]
        )
        res = sg.drm(self.tmp.name)
        self.assertEqual(res["processus"], [])
        self.assertEqual(res["sans_stats"], [{"pid": 300, "nom": "Xorg"}])

    @unittest.skipIf(os.geteuid() == 0, "root lit tous les descripteurs")
    def test_the_whole_command_line_is_kept(self):
        longue = ["qemu-system-x86_64", "-name"] + [
            f"opt{i}" for i in range(40)
        ]
        self.proc.processus(500, "qemu", longue)
        self.assertEqual(
            sg.ligne_commande(500, self.tmp.name), " ".join(longue)
        )

    def test_other_accounts_are_counted_kernel_threads_are_not(self):
        self.proc.processus(400, "autre", ["autre"], lisible=False)
        self.proc.processus(401, "kthreadd", [], lisible=False)
        res = sg.drm(self.tmp.name)
        self.assertEqual(res["illisibles"], 1)


class TestLaRelectureSudo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proc = ArbreProc(self.tmp.name)

    def test_the_root_program_stands_alone_and_reads_the_same(self):
        """Lancé par « python3 -I -c », hors du dépôt : il ne doit rien
        importer d'ERPLibre et rendre ce que drm() rend."""
        self.proc.processus(
            100, "firefox", ["firefox"], fds=[("/dev/dri/renderD128", AMDGPU)]
        )
        self.proc.processus(
            300, "Xorg", ["Xorg"], fds=[("/dev/dri/card0", SANS_STATS)]
        )
        res = subprocess.run(
            [sys.executable, "-I", "-c", sg.code_sudo(), self.tmp.name],
            cwd=tempfile.gettempdir(),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(res.stdout), sg.drm(self.tmp.name))
        self.assertNotIn("script.todo", sg.code_sudo())

    def lancer(
        self,
        retour=0,
        sortie='{"processus": [], "sans_stats": [], ' '"illisibles": 0}',
        exception=None,
    ):
        resultat = subprocess.CompletedProcess([], retour, sortie, None)
        with mock.patch.object(
            sg.subprocess,
            "run",
            side_effect=exception,
            return_value=resultat,
        ) as run:
            lu = sg.drm_sudo()
        return lu, run

    def test_sudo_keeps_the_terminal_for_the_password(self):
        lu, run = self.lancer()
        self.assertTrue(lu["sudo"])
        args, kwargs = run.call_args
        self.assertEqual(args[0][:5], ["sudo", "--", "python3", "-I", "-c"])
        self.assertEqual(kwargs, {"stdout": subprocess.PIPE, "text": True})

    def test_any_failure_gives_none(self):
        self.assertIsNone(self.lancer(retour=1)[0])
        self.assertIsNone(self.lancer(sortie="pas du json")[0])
        self.assertIsNone(self.lancer(sortie="[]")[0])
        self.assertIsNone(self.lancer(exception=KeyboardInterrupt)[0])
        self.assertIsNone(self.lancer(exception=OSError)[0])


class TestLaQuestionSudo(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def demander(self, reponse, illisibles=5, euid=1000, tty=True, lu=None):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        faits = {
            "drm": {
                "processus": [],
                "sans_stats": [],
                "illisibles": illisibles,
            }
        }
        avant = faits["drm"]
        with (
            mock.patch.object(sm.os, "geteuid", return_value=euid),
            mock.patch.object(sm.sys.stdin, "isatty", return_value=tty),
            mock.patch("builtins.input", return_value=reponse) as question,
            mock.patch("builtins.print"),
            mock.patch.object(sg, "drm_sudo", return_value=lu) as sudo,
            mock.patch.object(sg, "completer"),
        ):
            todo._system_gpu_sudo(faits)
        return faits["drm"] is avant, question.called, sudo.called, faits

    def test_no_question_when_nothing_is_hidden_root_or_no_terminal(self):
        for cas in ({"illisibles": 0}, {"euid": 0}, {"tty": False}):
            garde, question, sudo, _ = self.demander("o", **cas)
            self.assertTrue(garde, cas)
            self.assertFalse(question, cas)
            self.assertFalse(sudo, cas)

    def test_no_keeps_the_reading_without_root(self):
        garde, question, sudo, _ = self.demander("")
        self.assertTrue(question)
        self.assertFalse(sudo)
        self.assertTrue(garde)

    def test_yes_replaces_the_reading_with_the_root_one(self):
        lu = {"processus": [], "sans_stats": [], "illisibles": 0, "sudo": True}
        garde, _, sudo, faits = self.demander("o", lu=lu)
        self.assertTrue(sudo)
        self.assertIs(faits["drm"], lu)
        texte = "\n".join(
            sm.lignes_gpu(
                {
                    "cartes": [],
                    "nvidia": None,
                    "drm": lu,
                    "nvidia_sans_reponse": False,
                }
            )
        )
        self.assertIn("/proc/*/fdinfo, sudo", texte)

    def test_a_failed_sudo_keeps_the_reading_without_root(self):
        garde, _, sudo, _ = self.demander("o", lu=None)
        self.assertTrue(sudo)
        self.assertTrue(garde)


class TestLeChoixDeLaSource(unittest.TestCase):
    def collecter(self, pilotes, nvidia_smi, nvidia=None):
        cartes = [
            {"carte": f"card{i}", "pilote": p} for i, p in enumerate(pilotes)
        ]
        drm = {"processus": [], "sans_stats": [], "illisibles": 0}
        with (
            mock.patch.object(sg, "cartes", return_value=cartes),
            mock.patch.object(
                sg.shutil,
                "which",
                return_value="/usr/bin/nvidia-smi" if nvidia_smi else None,
            ),
            mock.patch.object(sg, "nvidia", return_value=nvidia) as nv,
            mock.patch.object(sg, "drm", return_value=drm) as lu,
        ):
            res = sg.collecter()
        return res, nv.called, lu.called

    def test_nvidia_card_uses_nvidia_smi_only(self):
        res, nv, lu = self.collecter(
            ["nvidia"], True, {"source": "x", "gpus": []}
        )
        self.assertTrue(nv)
        self.assertFalse(lu)
        self.assertFalse(res["nvidia_sans_reponse"])

    def test_nvidia_card_without_nvidia_smi_is_reported(self):
        res, nv, lu = self.collecter(["nvidia"], False, None)
        self.assertTrue(nv)
        self.assertTrue(res["nvidia_sans_reponse"])

    def test_other_drivers_read_fdinfo_without_nvidia_smi(self):
        res, nv, lu = self.collecter(["amdgpu", "i915"], False)
        self.assertFalse(nv)
        self.assertTrue(lu)

    def test_hybrid_laptop_reads_both(self):
        res, nv, lu = self.collecter(
            ["i915", "nvidia"], True, {"source": "x", "gpus": []}
        )
        self.assertTrue(nv)
        self.assertTrue(lu)


class TestLeRapportGpu(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def faits(self):
        gpus = sg.nvidia_xml(XML)
        for p in gpus[0]["processus"]:
            p.update(compte="erplibre", commande=None)
        return {
            "cartes": [
                {
                    "carte": "card0",
                    "pci": "0000:03:00.0",
                    "fabricant": "AMD",
                    "pilote": "amdgpu",
                    "modele": "Carte AMD",
                    "vram_totale": 8192 * MIO,
                    "vram_utilisee": 1024 * MIO,
                }
            ],
            "nvidia": {"source": "nvidia-smi -q -x", "gpus": gpus},
            "drm": {
                "processus": [
                    {
                        "pid": 100,
                        "pci": "0000:03:00.0",
                        "pilote": "amdgpu",
                        "regions": {"vram": 800 * MIO, "gtt": 0},
                        "compte": "erplibre",
                        "commande": "firefox",
                    }
                ],
                "sans_stats": [{"pid": 300, "nom": "Xorg"}],
                "illisibles": 12,
            },
            "nvidia_sans_reponse": False,
        }

    def test_biggest_first_unattributed_and_blind_spots(self):
        texte = "\n".join(sm.lignes_gpu(self.faits()))
        self.assertLess(texte.index("python3"), texte.index("Xorg"))
        # 1100 utilisés, 900 attribués aux processus.
        self.assertIn("Non attribuée", texte)
        self.assertIn("200.0 Mio", texte)
        self.assertIn("vram 800.0 Mio", texte)
        self.assertNotIn("gtt", texte)
        self.assertIn("Aucun processus n'utilise cette carte.", texte)
        self.assertIn("Xorg (300)", texte)
        self.assertIn("12 processus d'autres comptes", texte)
        self.assertIn("VRAM : 1.0 Gio utilisée sur 8.0 Gio", texte)

    def test_control_characters_never_reach_the_terminal(self):
        """Le nom et la ligne de commande viennent d'autres comptes : une
        séquence d'échappement ou un saut de ligne n'en sort pas."""
        faits = self.faits()
        faits["drm"]["processus"][0][
            "commande"
        ] = "\x1b]52;c;QUJD\x07\n  1 forge"
        faits["drm"]["sans_stats"] = [{"pid": 300, "nom": "X\x1b[2Jorg"}]
        texte = "\n".join(sm.lignes_gpu(faits))
        self.assertNotIn("\x1b", texte)
        self.assertNotIn("\x07", texte)
        self.assertNotIn("\n  1 forge", texte)
        self.assertIn("?]52;c;QUJD??  1 forge", texte)

    def test_compute_only_source_is_flagged(self):
        faits = self.faits()
        faits["nvidia"]["source"] = "nvidia-smi --query-compute-apps"
        texte = "\n".join(sm.lignes_gpu(faits))
        self.assertIn("Processus de calcul seulement", texte)

    def test_unknown_memory_does_not_invent_an_unattributed_share(self):
        faits = self.faits()
        faits["nvidia"]["gpus"][0]["processus"][0]["memoire"] = None
        texte = "\n".join(sm.lignes_gpu(faits))
        self.assertNotIn("Non attribuée", texte)
        self.assertIn("N/A", texte)

    def test_every_message_is_translated(self):
        source = inspect.getsource(sm.lignes_gpu)
        cles = [
            n.args[0].value
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "t"
            and isinstance(n.args[0], ast.Constant)
        ]
        self.assertTrue(cles)
        source = textwrap.dedent(
            inspect.getsource(sm.SystemMenuMixin._system_gpu_sudo)
        )
        cles += [
            n.args[0].value
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "t"
            and isinstance(n.args[0], ast.Constant)
        ]
        for cle in cles + ["GPU memory per process", "Reading GPU memory…"]:
            self.assertIn(cle, todo_i18n.TRANSLATIONS, cle)


class TestLeMenu(unittest.TestCase):
    def test_entry_8_reads_gpu_memory(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        with (
            mock.patch.object(TODO, "_system_gpu") as gpu,
            mock.patch("click.prompt", side_effect=["8", "0"]),
            mock.patch("builtins.print"),
        ):
            todo.prompt_execute_system()
        gpu.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
