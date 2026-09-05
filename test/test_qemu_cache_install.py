#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'installateur du cache QEMU pose-t-il ce qu'il faut, et rien de plus ?

Ce script écrit des règles de pare-feu sur le pont de l'hôte. Une règle trop
large y prive la machine de son propre réseau, et une règle laissée derrière
un service arrêté envoie les VM vers un cache éteint. Les propriétés qui
empêchent ces deux pannes se lisent dans le texte du script et de l'unité, ce
qui se vérifie en secondes et sans toucher au pare-feu de la machine qui
exécute les tests.

Le jeu de règles lui-même est vérifié en Go, où il vit : voir
script/qemu_cache/rules_test.go. Ce test contrôle qu'il n'en existe pas de
seconde copie ici.
"""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "script" / "install" / "install_qemu_cache.sh"
SOURCES = RACINE / "script" / "qemu_cache"


class TestScriptDInstallation(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), f"script absent : {SCRIPT}")
        self.texte = SCRIPT.read_text(encoding="utf-8")

    def test_syntaxe_bash(self):
        r = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_executable(self):
        self.assertTrue(
            SCRIPT.stat().st_mode & 0o111,
            "le script n'est pas exécutable : le menu l'appelle par bash, mais "
            "un opérateur le lance directement",
        )

    def test_refuse_de_tourner_sans_root(self):
        self.assertIn("check_root", self.texte)
        self.assertRegex(
            self.texte,
            r"EUID.*-ne 0",
            "rien ne vérifie que le script tourne en root",
        )

    def test_les_regles_ne_sont_pas_recopiees(self):
        """Les règles viennent du binaire, seule source que les tests Go
        vérifient. Une copie littérale ici dériverait en silence."""
        for motif in ("redirect to :", "REDIRECT --to-ports", "ip daddr !="):
            self.assertNotIn(
                motif,
                self.texte,
                f"le script porte une copie des règles ({motif!r}) : "
                "elles doivent sortir de --print-nft / --print-iptables",
            )
        self.assertIn("--print-nft", self.texte)
        self.assertIn("--print-iptables", self.texte)

    def test_go_verifie_avant_de_compiler(self):
        self.assertIn("GO_MIN_MAJOR", self.texte)
        self.assertIn("GO_MIN_MINOR", self.texte)
        self.assertIn(
            "go_assez_recent",
            self.texte,
            "la version de Go n'est pas contrôlée : un golang trop ancien "
            "échoue à la compilation avec un message qui ne le dit pas",
        )

    def test_compile_avant_de_toucher_au_systeme(self):
        """L'ordre compte : une compilation échouée ne doit laisser ni unité,
        ni règle, ni service à moitié posé. « set -e » y suffit, à condition
        que la compilation précède."""
        self.assertIn("set -e", self.texte)
        ordre = [
            self.texte.index("  compiler\n"),
            self.texte.index("  ecrire_unite\n"),
        ]
        self.assertLess(
            ordre[0], ordre[1], "l'unité est écrite avant la compilation"
        )

    def test_sources_verifiees(self):
        self.assertIn(
            "go.mod",
            self.texte,
            "le script ne vérifie pas que les sources sont là",
        )


class TestUniteSystemd(unittest.TestCase):
    """L'unité telle qu'elle est ÉCRITE, et non telle qu'elle est écrite.

    Le heredoc est un gabarit : les règles y arrivent par substitution de
    commande, et le compte de service par une variable. Lire le gabarit
    reviendrait à vérifier autre chose que ce que systemd lira. La fonction
    est donc appelée pour de vrai, vers un fichier temporaire, avec les
    commandes du système neutralisées.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        unit = Path(cls.tmp) / "erplibre-go-qemu-cache.service"
        # Le script se termine par « main "$@" » : la ligne est retirée pour
        # pouvoir appeler UNE fonction sans rien installer. systemctl est
        # neutralisé, la machine de test n'ayant pas à recharger systemd.
        prelude = (
            # EL_SRC_DIR évite que la déduction du chemin des sources échoue :
            # « source <(...) » fait pointer BASH_SOURCE sur /dev/fd.
            f'export EL_SRC_DIR="{SOURCES}"\n'
            f'source <(sed "/^main \\"\\$@\\"/d" {SCRIPT})\n'
            "systemctl() { :; }\n"
            f'UNIT="{unit}"\n'
            "ecrire_unite\n"
        )
        r = subprocess.run(
            ["bash", "-c", prelude], capture_output=True, text=True
        )
        if r.returncode != 0 or not unit.is_file():
            raise AssertionError(
                f"l'unité n'a pas pu être générée : {r.stdout}{r.stderr}"
            )
        cls.unite_texte = unit.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.unite = self.unite_texte

    def test_les_regles_partent_a_larret(self):
        """Sans cela, arrêter le cache laisse les VM détournées vers un port
        que plus personne n'écoute : elles perdent tout téléchargement."""
        self.assertIn("ExecStopPost=", self.unite)
        self.assertRegex(
            self.unite,
            r"ExecStopPost=\+",
            "le retrait des règles ne demande pas le privilège root",
        )
        self.assertIn("delete table ip erplibre_qemu_cache", self.unite)

    def test_les_regles_sont_posees_en_root_seulement(self):
        """« + » fait tourner CETTE commande en root, alors que le service
        sert les fichiers sous un compte sans privilège."""
        self.assertRegex(self.unite, r"ExecStartPre=\+")
        self.assertRegex(self.unite, re.compile(r"^User=\S+$", re.M))
        self.assertNotRegex(
            self.unite,
            re.compile(r"^User=root$", re.M),
            "le service sert des fichiers en root alors qu'il n'en a pas besoin",
        )

    def test_durcissement(self):
        for directive in (
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
        ):
            self.assertIn(directive, self.unite, f"{directive} manque")

    def test_les_repertoires_ecrivables_sont_declares(self):
        """ProtectSystem=strict rend tout le système en lecture seule : sans
        ReadWritePaths, le cache ne peut rien écrire et le service tourne en
        échouant sur chaque objet."""
        m = re.search(r"ReadWritePaths=(.+)", self.unite)
        self.assertIsNotNone(m, "ReadWritePaths manque")
        chemins = m.group(1)
        for attendu in (
            "/var/cache/erplibre_go_qemu_cache",
            "/var/lib/erplibre_go_qemu_cache",
            "/var/log/erplibre_go_qemu_cache.jsonl",
        ):
            self.assertIn(attendu, chemins, f"{attendu} n'est pas écrivable")

    def test_redemarre_apres_le_reseau(self):
        self.assertIn("After=network.target", self.unite)

    def test_aucun_chemin_de_compte_dans_lunite(self):
        """L'unité est un fichier système : y figer le checkout de celui qui a
        installé la casse dès que le dépôt bouge, et fait entrer un nom de
        compte dans /etc."""
        self.assertNotIn(
            "/home/",
            self.unite,
            "l'unité porte un chemin de compte",
        )
        self.assertNotIn("/root/", self.unite, "l'unité porte le compte root")


class TestSourcesGo(unittest.TestCase):
    def test_module_present(self):
        self.assertTrue(
            (SOURCES / "go.mod").is_file(), "le module Go du cache est absent"
        )

    def test_binaire_non_versionne(self):
        """Un « go build » dans les sources y laisse un binaire de plusieurs
        mégaoctets : il ne doit pas pouvoir entrer dans un commit."""
        ignore = SOURCES / ".gitignore"
        self.assertTrue(ignore.is_file(), ".gitignore absent des sources Go")
        self.assertIn(
            "erplibre_go_qemu_cache", ignore.read_text(encoding="utf-8")
        )

    @unittest.skipIf(
        shutil.which("go") is None,
        "Go absent : la suite unitaire doit rester lançable sans lui",
    )
    def test_go_test(self):
        r = subprocess.run(
            ["go", "test", "./..."],
            cwd=str(SOURCES),
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
