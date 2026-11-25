#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""el_build_limit_jobs (S390x/lib_lowmem.sh) partage le budget de
compilations entre les paquets que Poetry construit en même temps et les
tâches de chacun : leur produit ne dépasse jamais le budget.

La bibliothèque est sourcée telle quelle ; la mémoire et le nombre de cœurs
sont remplacés par des fonctions qui rendent des valeurs choisies, et ninja
est absent du PATH pour qu'aucune enveloppe ne soit écrite.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "script", "install", "S390x", "lib_lowmem.sh")


def limiter(mem_mb, swap_mb, cpus, workers=None):
    """Rend {variable: valeur} après el_build_limit_jobs."""
    # Le PATH système atteint le vrai sudo : une doublure qui refuse passe
    # devant, el_build_limit_jobs n'ayant aucune raison de l'appeler.
    doublures = {"sudo": 'echo "sudo refuse dans ce test" >&2; exit 1'}
    with tempfile.TemporaryDirectory() as tmp:
        for nom, corps in doublures.items():
            fichier = Path(tmp) / nom
            fichier.write_text(f"#!/bin/sh\n{corps}\n")
            fichier.chmod(0o755)
        env = {
            "PATH": f"{tmp}:/usr/bin:/bin",
            "HOME": os.environ.get("HOME", "/tmp"),
        }
        if workers is not None:
            env["EL_POETRY_BUILD_WORKERS"] = str(workers)
        return _lire(_executer(mem_mb, swap_mb, cpus, env))


def _executer(mem_mb, swap_mb, cpus, env):
    """Sortie de el_build_limit_jobs, sous l'environnement `env`."""
    script = f"""
. "{LIB}"
el_mem_mb() {{ echo {mem_mb}; }}
el_swap_mb() {{ echo {swap_mb}; }}
nproc() {{ echo {cpus}; }}
command() {{ [ "$2" = ninja ] || [ "$2" = ninja-build ] && return 1; builtin command "$@"; }}
el_build_limit_jobs > /dev/null
echo "W=${{POETRY_INSTALLER_MAX_WORKERS}}"
echo "J=${{MAKEFLAGS#-j}}"
echo "C=${{CMAKE_BUILD_PARALLEL_LEVEL}}"
echo "M=${{MAX_JOBS}}"
"""
    out = subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out


def _lire(out):
    """{variable: valeur} des lignes « NOM=valeur »."""
    return dict(line.split("=", 1) for line in out.split())


class LeBudgetEstPartage(unittest.TestCase):
    def test_workers_times_jobs_never_exceed_the_budget(self):
        # Budget = (RAM + swap) / 2048, plafonné au nombre de cœurs.
        for mem, swap, cpus in [
            (10032, 1326, 6),
            (8013, 8012, 4),
            (33000, 0, 12),
            (2000, 0, 8),
            (1024, 0, 1),
        ]:
            budget = max(1, min(cpus, (mem + swap) // 2048))
            v = limiter(mem, swap, cpus)
            with self.subTest(mem=mem, swap=swap, cpus=cpus):
                self.assertLessEqual(int(v["W"]) * int(v["J"]), budget)
                self.assertGreaterEqual(int(v["W"]), 1)
                self.assertGreaterEqual(int(v["J"]), 1)

    def test_poetry_builds_two_packages_by_default(self):
        v = limiter(10032, 1326, 6)
        self.assertEqual(v["W"], "2")
        self.assertEqual(v["J"], "2")

    def test_every_engine_gets_the_same_task_count(self):
        v = limiter(33000, 0, 12)
        self.assertEqual(v["J"], v["C"])
        self.assertEqual(v["J"], v["M"])

    def test_a_budget_of_one_builds_one_package(self):
        v = limiter(1024, 0, 1)
        self.assertEqual((v["W"], v["J"]), ("1", "1"))

    def test_the_worker_count_can_be_overridden(self):
        v = limiter(33000, 0, 12, workers=1)
        self.assertEqual((v["W"], v["J"]), ("1", "12"))

    def test_an_invalid_worker_count_falls_back_to_one(self):
        v = limiter(33000, 0, 12, workers="abc")
        self.assertEqual(v["W"], "1")


if __name__ == "__main__":
    unittest.main()
