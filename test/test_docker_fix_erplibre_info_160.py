#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/update/docker_fix_erplibre_info_docker_erplibre_160.sh devant un
faux « docker » qui note chaque appel, ses arguments et, pour un exec -i, le
script reçu sur l'entrée standard : aucun conteneur n'est touché.

Ce que ces tests gardent :

- aucun appel n'utilise --privileged ;
- chaque docker exec nomme son compte par -u : sous « user: root », un exec
  sans -u tournerait en root ;
- git et python ne tournent jamais sous root : le seul exec de root est le
  chmod des dossiers de /ERPLibre/.repo, sans git ni python ;
- les lectures de git et de python tournent sous le propriétaire de
  /ERPLibre, lu par proprietaire_code ;
- un propriétaire root, ou illisible, arrête le script avant tout script
  envoyé au conteneur, et le message nomme l'image prise en charge ;
- l'aide (-h) décrit l'image prise en charge, dont le code appartient à son
  propriétaire, et ne promet plus de préparer une image 1.6.0.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = (
    RACINE
    / "script"
    / "update"
    / "docker_fix_erplibre_info_docker_erplibre_160.sh"
)
PROPRIETAIRE = "4242"

# Le faux docker note une ligne JSON par appel : ses arguments et, pour un
# exec -i, son entrée standard. « inspect » dit le conteneur en marche, sans
# montage ; « exec » du stat de /ERPLibre écrit FAUX_PROPRIETAIRE, celui de
# .odoo-version écrit 18.0, tout autre sort en 0 sans rien écrire.
FAUX_DOCKER = r"""#!/usr/bin/env python3
import json
import os
import sys

argv = sys.argv[1:]
entree = ""
if argv[:1] == ["exec"] and "-i" in argv:
    entree = sys.stdin.read()
with open(os.environ["FAUX_DOCKER_JOURNAL"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "stdin": entree}) + "\n")
if argv[:1] == ["inspect"]:
    if "{{.State.Running}}" in argv:
        print("true")
elif argv[:1] == ["exec"]:
    if argv[-3:] == ["-c", "%u", "/ERPLibre"]:
        print(os.environ["FAUX_PROPRIETAIRE"])
    elif argv[-1:] == ["/ERPLibre/.odoo-version"]:
        print("18.0")
"""


def lancer(proprietaire=PROPRIETAIRE):
    """Lance le script contre le conteneur « fixtest_c » ; rend la sortie
    et la liste des appels reçus par le faux docker."""
    with tempfile.TemporaryDirectory() as dossier:
        faux = Path(dossier) / "bin"
        faux.mkdir()
        (faux / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
        (faux / "docker").chmod(0o755)
        journal = Path(dossier) / "journal"
        journal.touch()
        env = dict(
            os.environ,
            PATH=f"{faux}:{os.environ['PATH']}",
            FAUX_DOCKER_JOURNAL=str(journal),
            FAUX_PROPRIETAIRE=proprietaire,
        )
        sortie = subprocess.run(
            [str(SCRIPT), "-c", "fixtest_c"],
            cwd=dossier,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )
        appels = [
            json.loads(ligne)
            for ligne in journal.read_text(encoding="utf-8").splitlines()
        ]
        return sortie, appels


def execs(appels):
    return [a for a in appels if a["argv"][:1] == ["exec"]]


def compte(appel):
    """Le compte passé à -u d'un exec, None sans -u."""
    argv = appel["argv"]
    if "-u" not in argv:
        return None
    return argv[argv.index("-u") + 1]


def en_root(appel):
    return compte(appel) in ("root", "0", "0:0")


def lance_git_ou_python(appel):
    texte = " ".join(appel["argv"]) + "\n" + appel["stdin"]
    return any(
        mot in texte for mot in ("git ", "g() {", "python", "/bin/python")
    )


class TestDockerFixErplibreInfo160(unittest.TestCase):
    def test_le_script_va_au_bout(self):
        sortie, appels = lancer()
        self.assertEqual(sortie.returncode, 0, sortie.stdout + sortie.stderr)
        self.assertIn(["restart", "fixtest_c"], [a["argv"] for a in appels])

    def test_jamais_privileged(self):
        _, appels = lancer()
        for appel in appels:
            self.assertNotIn("--privileged", appel["argv"])

    def test_chaque_exec_nomme_son_compte(self):
        _, appels = lancer()
        self.assertTrue(execs(appels))
        for appel in execs(appels):
            self.assertIsNotNone(compte(appel), appel["argv"])

    def test_root_ne_lance_ni_git_ni_python(self):
        _, appels = lancer()
        racines = [a for a in execs(appels) if en_root(a)]
        self.assertEqual(1, len(racines), [a["argv"] for a in racines])
        self.assertIn("chmod go+rx", racines[0]["stdin"])
        self.assertFalse(lance_git_ou_python(racines[0]), racines[0])
        self.assertIn("/usr/bin/env", racines[0]["argv"])

    def test_git_et_python_sous_le_proprietaire_ou_odoo(self):
        _, appels = lancer()
        comptes = {compte(a) for a in execs(appels) if lance_git_ou_python(a)}
        self.assertEqual({PROPRIETAIRE, "odoo"}, comptes)
        # Les étapes 1 à 3, mémoire, branche et option extra, sous le
        # propriétaire de /ERPLibre.
        etapes_git = [
            a
            for a in execs(appels)
            if "describe" in a["stdin"] or "checkout" in a["stdin"]
        ]
        self.assertEqual(2, len(etapes_git))
        for appel in etapes_git:
            self.assertEqual(PROPRIETAIRE, compte(appel))

    def test_un_proprietaire_root_arrete_avant_tout_script(self):
        for proprietaire in ("0", "root", ""):
            with self.subTest(proprietaire=proprietaire):
                sortie, appels = lancer(proprietaire)
                self.assertEqual(1, sortie.returncode)
                self.assertEqual(
                    [], [a for a in execs(appels) if "-i" in a["argv"]]
                )
                self.assertNotIn(
                    ["restart", "fixtest_c"], [a["argv"] for a in appels]
                )

    def test_le_refus_de_root_nomme_l_image_prise_en_charge(self):
        sortie, _ = lancer("0")
        self.assertIn("ERPLIBRE_CODE_OWNER=odoo", sortie.stderr)
        self.assertIn("1.6.0", sortie.stderr)

    def test_l_etape_2_nomme_l_image_prise_en_charge(self):
        _, appels = lancer()
        (etape,) = [a for a in execs(appels) if "checkout" in a["stdin"]]
        self.assertIn("ERPLIBRE_CODE_OWNER=odoo", etape["stdin"])

    def test_en_root_ne_transmet_aucun_argument(self):
        _, appels = lancer()
        (racine,) = [a for a in execs(appels) if en_root(a)]
        self.assertEqual(["bash", "-s"], racine["argv"][-2:])

    def test_l_aide_decrit_l_image_prise_en_charge(self):
        sortie = subprocess.run(
            [str(SCRIPT), "-h"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, sortie.returncode, sortie.stderr)
        self.assertIn("ERPLIBRE_CODE_OWNER=odoo", sortie.stdout)
        self.assertIn("Image prise en charge", sortie.stdout)
        self.assertNotIn(
            "Prépare un conteneur Docker d'ERPLibre 1.6.0", sortie.stdout
        )
        self.assertIn("Usage :", sortie.stdout)


if __name__ == "__main__":
    unittest.main()
