#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Poser un fichier de règles sans rien changer pour ceux qui n'en veulent pas.

Le déploiement sert tous les jours et ne rend rien de nouveau ici : sans le
drapeau, la configuration produite doit être celle d'avant, à l'octet. C'est
l'assertion qui compte le plus de ce fichier — une option qui déborde sur le
cas courant coûte plus qu'elle n'apporte.

DEUX VOIES D'AMORCE, UNE SEULE SOURCE. La liste des fichiers d'accueil est
lue par cloud-init, par le late_command de l'installateur et par le
rangement dans l'initrd : une entrée de plus les couvre toutes les trois,
et c'est pourquoi elle passe par là plutôt que par un mécanisme neuf.

LES CONSTANTES SONT RECOPIÉES, DONC ÉPINGLÉES. Le script de déploiement se
charge seul, sans le dépôt sur le chemin d'import, et n'importe que la
bibliothèque standard : il ne PEUT pas importer le module qui rend les
règles. L'épreuve tient les deux valeurs égales à leur source, ce qui
remplace l'import impossible.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(str(RACINE))

from script.posture import plan  # noqa: E402


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    chemin = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploy_qemu"] = module
    spec.loader.exec_module(module)
    return module


DQ = _deploy_qemu()

REGLES = "table inet erplibre {\n}\n"


def args_de_banc(regles=None, unite=None):
    args = DQ.build_parser().parse_args(["--name", "banc"])
    args.hostname = "banc"
    if regles is not None:
        args.egress_rules = regles
    if unite is not None:
        args.egress_unit_text = unite
    return args


class TestSansLeDrapeauRienNeBouge(unittest.TestCase):
    def test_the_cloud_config_says_nothing_about_rules(self):
        texte = DQ.build_cloud_config(args_de_banc(), None, [])
        for trace in ("egress", "nft -f", DQ.EGRESS_GUEST_PATH):
            with self.subTest(trace=trace):
                self.assertNotIn(trace, texte)

    def test_the_installer_path_says_nothing_either(self):
        texte = DQ.build_preseed(args_de_banc(), None, [])
        self.assertNotIn("egress", texte)

    def test_the_welcome_files_are_the_ones_that_were_there(self):
        chemins = [entree[0] for entree in DQ.guide_files(args_de_banc())]
        self.assertNotIn(DQ.EGRESS_GUEST_PATH, chemins)
        self.assertIn("/etc/motd", chemins)

    def test_an_empty_rendering_is_the_same_as_none(self):
        """Un déploiement sans posture bornée rend une chaîne vide : elle ne
        doit pas produire une entrée qui ne contiendrait rien."""
        texte = DQ.build_cloud_config(args_de_banc(""), None, [])
        self.assertNotIn("egress", texte)


class TestAvecLeDrapeau(unittest.TestCase):
    def config(self):
        return DQ.build_cloud_config(args_de_banc(REGLES), None, [])

    def test_the_file_is_written_with_a_quoted_mode(self):
        """« permissions: 600 » non quoté est lu en DÉCIMAL et appliqué tel
        quel, sans le moindre avertissement."""
        texte = self.config()
        self.assertIn(f"  - path: {DQ.EGRESS_GUEST_PATH}", texte)
        self.assertIn(f"    permissions: '{DQ.EGRESS_GUEST_MODE}'", texte)

    def test_the_write_is_not_deferred(self):
        """Un propriétaire imposerait « defer: true », donc une pose à
        l'étape finale — trop tard pour un fichier chargé au démarrage."""
        entree = [
            e
            for e in DQ.guide_files(args_de_banc(REGLES))
            if e[0] == DQ.EGRESS_GUEST_PATH
        ][0]
        self.assertEqual("", entree[3])

    def test_the_content_travels_whole(self):
        self.assertIn("table inet erplibre", self.config())

    def test_the_load_line_is_the_very_last(self):
        """Le code de sortie d'un script est celui de sa dernière commande :
        ailleurs dans la liste, la panne se perdrait dans les « || true »
        qui suivent."""
        lignes = self.config().rstrip("\n").splitlines()
        self.assertEqual(f"  - nft -f {DQ.EGRESS_GUEST_PATH}", lignes[-1])

    def test_the_load_line_tolerates_no_failure(self):
        """C'est la SEULE ligne de runcmd sans repli, et c'est le point :
        un confinement qui ne se charge pas doit se voir."""
        derniere = self.config().rstrip("\n").splitlines()[-1]
        self.assertNotIn("|| true", derniere)
        avec_repli = [
            l
            for l in self.config().splitlines()
            if l.startswith("  - ") and l.endswith("|| true")
        ]
        self.assertTrue(avec_repli, "aucune ligne à repli : rien n'est prouvé")

    def test_the_installer_path_copies_it_too(self):
        texte = DQ.build_preseed(args_de_banc(REGLES), None, [])
        plat = DQ.installer_guide_name(DQ.EGRESS_GUEST_PATH)
        self.assertIn(f"cp /{plat} /target{DQ.EGRESS_GUEST_PATH}", texte)
        self.assertIn(f"chmod {DQ.EGRESS_GUEST_MODE}", texte)

    def test_the_name_kept_in_the_initrd_is_flat(self):
        """Le cpio est déplié séquentiellement et ne crée pas les parents
        manquants : une barre oblique ferait échouer le dépliage ENTIER,
        donc l'installation."""
        plat = DQ.installer_guide_name(DQ.EGRESS_GUEST_PATH)
        self.assertNotIn("/", plat)


class TestLUnitePoseeEtArmee(unittest.TestCase):
    """Les règles disent CE QUI passe, l'unité dit QUAND elles sont
    chargées. Sans elle, la voie de l'installateur posait le fichier et
    rien ne le chargeait jamais."""

    def config(self):
        return DQ.build_cloud_config(
            args_de_banc(REGLES, plan.unit_text()), None, []
        )

    def test_the_unit_is_written_where_systemd_reads_it(self):
        texte = self.config()
        self.assertIn(f"  - path: {DQ.EGRESS_UNIT_PATH}", texte)
        self.assertIn(f"    permissions: '{DQ.EGRESS_UNIT_MODE}'", texte)

    def test_the_first_boot_arms_it_before_loading(self):
        derniere = self.config().rstrip("\n").splitlines()[-1]
        self.assertLess(
            derniere.index(DQ.EGRESS_UNIT_NAME),
            derniere.index("nft -f"),
        )
        self.assertNotIn("|| true", derniere)

    def test_the_installer_path_arms_it_because_it_has_no_runcmd(self):
        """C'est LA raison de l'unité sur ce chemin : rien d'autre n'y
        charge les règles, ni au premier démarrage ni aux suivants."""
        texte = DQ.build_preseed(
            args_de_banc(REGLES, plan.unit_text()), None, []
        )
        self.assertIn(
            f"in-target systemctl enable {DQ.EGRESS_UNIT_NAME}", texte
        )
        plat = DQ.installer_guide_name(DQ.EGRESS_UNIT_PATH)
        self.assertIn(f"cp /{plat} /target{DQ.EGRESS_UNIT_PATH}", texte)

    def test_the_unit_name_kept_in_the_initrd_is_flat(self):
        """Une barre oblique ferait échouer le dépliage de l'initrd
        ENTIER, donc l'installation."""
        self.assertNotIn("/", DQ.installer_guide_name(DQ.EGRESS_UNIT_PATH))

    def test_rules_without_a_unit_keep_the_line_they_had(self):
        """Les deux drapeaux restent indépendants : un déploiement qui
        n'envoie que les règles doit se comporter comme avant."""
        derniere = (
            DQ.build_cloud_config(args_de_banc(REGLES), None, [])
            .rstrip("\n")
            .splitlines()[-1]
        )
        self.assertEqual(f"  - nft -f {DQ.EGRESS_GUEST_PATH}", derniere)

    def test_no_rules_means_no_unit_either(self):
        """Poser une unité qui chargerait un fichier absent la ferait
        échouer à chaque démarrage, sur une machine qui n'a rien demandé."""
        texte = DQ.build_cloud_config(args_de_banc(), None, [])
        self.assertNotIn(DQ.EGRESS_UNIT_NAME, texte)


class TestLesConstantesRecopieesSontEpinglees(unittest.TestCase):
    """L'import est impossible ; l'égalité, elle, se vérifie."""

    def test_the_guest_path_is_the_one_the_renderer_names(self):
        self.assertEqual(plan.RULES_PATH, DQ.EGRESS_GUEST_PATH)

    def test_the_mode_is_the_one_the_renderer_names(self):
        self.assertEqual(plan.RULES_MODE, DQ.EGRESS_GUEST_MODE)

    def test_the_unit_path_is_the_one_the_renderer_names(self):
        self.assertEqual(plan.UNIT_PATH, DQ.EGRESS_UNIT_PATH)
        self.assertEqual(plan.UNIT_NAME, DQ.EGRESS_UNIT_NAME)
        self.assertEqual(plan.UNIT_MODE, DQ.EGRESS_UNIT_MODE)

    def test_the_first_boot_line_is_the_one_the_renderer_names(self):
        lignes = (
            DQ.build_cloud_config(
                args_de_banc(REGLES, plan.unit_text()), None, []
            )
            .rstrip("\n")
            .splitlines()
        )
        self.assertEqual(f"  - {plan.first_boot_command()}", lignes[-1])

    def test_the_load_line_is_the_one_the_renderer_names(self):
        lignes = (
            DQ.build_cloud_config(args_de_banc(REGLES), None, [])
            .rstrip("\n")
            .splitlines()
        )
        self.assertEqual(f"  - {plan.load_command()}", lignes[-1])

    def test_the_script_still_imports_nothing_from_the_repository(self):
        """Il se charge seul, sans le dépôt sur le chemin d'import : un
        « from script.… » le casserait quand il est lancé en direct, et
        seulement là — donc jamais sous le menu, qui est où on l'essaie."""
        import ast

        chemin = RACINE / "script/qemu/deploy_qemu.py"
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        noms = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                noms.update(alias.name for alias in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                noms.add(noeud.module)
        self.assertTrue(noms, "aucun import lu : rien n'est prouvé")
        du_depot = [nom for nom in noms if nom.split(".")[0] == "script"]
        self.assertEqual([], du_depot)


class TestLireLeFichierRendu(unittest.TestCase):
    def test_nothing_asked_reads_nothing(self):
        self.assertEqual("", DQ.load_posed_file("", "Règles"))

    def test_a_missing_file_stops_before_anything_is_created(self):
        with self.assertRaises(SystemExit):
            DQ.load_posed_file("/nexiste-pas.invalid/regles.nft", "Règles")

    def test_an_empty_file_is_refused_like_a_missing_one(self):
        """Chargé, il s'accepterait sans rien appliquer, et la machine se
        lirait comme confinée alors que rien ne la borne."""
        with tempfile.NamedTemporaryFile("w", suffix=".nft") as fichier:
            fichier.write("   \n")
            fichier.flush()
            with self.assertRaises(SystemExit):
                DQ.load_posed_file(fichier.name, "Règles")

    def test_a_real_file_comes_back_whole(self):
        with tempfile.NamedTemporaryFile("w", suffix=".nft") as fichier:
            fichier.write(REGLES)
            fichier.flush()
            self.assertEqual(
                REGLES, DQ.load_posed_file(fichier.name, "Règles")
            )


if __name__ == "__main__":
    unittest.main()
