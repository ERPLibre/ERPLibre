#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Déployer avec l'amont du cache coupé.

Ce qui tombe n'est PAS le réseau de la VM : elle en a besoin pour joindre le
cache, qui vit sur l'orchestrateur. Seul le service perd son accès sortant,
si bien que tout ce qui arrive encore dans la VM vient du disque.

Les règles sont VÉRIFIÉES au caractère près et jamais appliquées : la machine
qui exécute les tests garde son pare-feu intact.
"""

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.qemu import cache_offline  # noqa: E402


class TestLesRegles(unittest.TestCase):
    def test_la_coupure_vise_le_compte_et_non_le_port(self):
        """Une règle générale sur le 443 de l'orchestrateur emporterait la
        session ssh depuis laquelle le déploiement est lancé."""
        regles = cache_offline.nft_rules()
        self.assertIn(f"meta skuid {cache_offline.SERVICE_USER}", regles)
        self.assertIn("hook output", regles)
        self.assertNotIn("hook input", regles)

    def test_les_deux_ports_tombent(self):
        """Ne couper que le 443 laisserait passer tout un miroir en clair."""
        self.assertIn("tcp dport { 80, 443 }", cache_offline.nft_rules())

    def test_la_politique_reste_permissive(self):
        """« policy accept » : seule la ligne ciblée jette. Une politique
        « drop » couperait tout ce que l'hôte émet."""
        self.assertIn("policy accept", cache_offline.nft_rules())

    def test_la_table_est_distincte_de_celle_du_detournement(self):
        """Les mêler ferait tomber la redirection de tout le pont en
        rebranchant l'amont."""
        self.assertNotEqual(cache_offline.TABLE, "erplibre_qemu_cache")

    def test_le_retrait_est_muet_sur_une_table_absente(self):
        """Il se fait dans un « finally » : une erreur y masquerait celle
        d'origine."""
        self.assertIn("|| true", cache_offline.restore_cmd())
        self.assertIn(cache_offline.TABLE, cache_offline.restore_cmd())


class TestLeCompteDuService(unittest.TestCase):
    """Le script d'installation est en shell et ne peut pas lire la valeur
    d'ici : les deux copies doivent dire la même chose, sans quoi la coupure
    viserait un compte qui n'émet rien et le test passerait pour hors ligne
    en étant en ligne."""

    def test_le_meme_compte_que_le_script_dinstallation(self):
        src = (
            RACINE / "script" / "install" / "install_qemu_cache.sh"
        ).read_text(encoding="utf-8")
        trouve = re.search(r'^SERVICE_USER="([^"]+)"', src, re.M)
        self.assertIsNotNone(trouve, "SERVICE_USER absent du script")
        self.assertEqual(trouve.group(1), cache_offline.SERVICE_USER)


class TestLeTestLongEtLeFormulaireCoupentPareil(unittest.TestCase):
    """Une seule source : ce que la case « Sans connexion internet » fait est
    exactement ce que la contre-épreuve du test long mesure."""

    def test_le_test_long_ne_recopie_pas_les_regles(self):
        src = (RACINE / "long_test" / "qemu_cache.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("cache_offline.cut_cmd()", src)
        self.assertNotIn("meta skuid", src)


class TestLeCablageDuDeploiement(unittest.TestCase):
    """La coupure couvre la spec ENTIÈRE, installation comprise, et se retire
    quoi qu'il arrive."""

    def _lance(self, offline, echec_coupure=False, plante=False):
        sys.argv = ["todo.py"]
        from script.todo.qemu_deploy import _SansInternetImpossible  # noqa
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vu = {"shell": [], "ordre": []}

        def shell(cmd, timeout=60):
            vu["shell"].append(cmd)
            if "nft -f -" in cmd:
                vu["ordre"].append("coupure")
                return 1 if echec_coupure else 0
            vu["ordre"].append("rebranchement")
            return 0

        todo._qemu_shell = shell

        def deploie(spec):
            vu["ordre"].append("déploiement")
            if plante:
                raise RuntimeError("le déploiement a échoué")
            return "fait"

        todo._qemu_deploie_spec = deploie
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            if plante:
                with self.assertRaises(RuntimeError):
                    todo._qemu_run_spec({"offline": offline})
            else:
                vu["rendu"] = todo._qemu_run_spec({"offline": offline})
        vu["ecrit"] = sortie.getvalue()
        return vu

    def test_sans_la_case_rien_nest_touche(self):
        vu = self._lance(offline=False)
        self.assertEqual(vu["ordre"], ["déploiement"])
        self.assertEqual(vu["shell"], [])

    def test_la_coupure_precede_le_deploiement(self):
        """Après lui, elle ne mesurerait plus rien : c'est l'installation qui
        télécharge."""
        vu = self._lance(offline=True)
        self.assertEqual(
            vu["ordre"], ["coupure", "déploiement", "rebranchement"]
        )

    def test_le_rebranchement_a_lieu_meme_si_le_deploiement_plante(self):
        """Une coupure laissée en place prive le cache de réseau bien après,
        et la panne se découvre ailleurs."""
        vu = self._lance(offline=True, plante=True)
        self.assertEqual(
            vu["ordre"], ["coupure", "déploiement", "rebranchement"]
        )

    def test_une_coupure_impossible_ne_deploie_rien(self):
        """Une VM bâtie avec l'amont debout se bâtit toujours : son succès se
        lirait comme une preuve hors ligne qu'elle n'est pas."""
        vu = self._lance(offline=True, echec_coupure=True)
        self.assertEqual(vu["ordre"], ["coupure"])
        self.assertIn("✗", vu["ecrit"])

    def test_la_spec_porte_bien_la_cle(self):
        from script.todo.deploy_form_lib import build_spec

        spec = build_spec(
            [],
            set(),
            {
                "res_label": "",
                "ssh_key": "",
                "install": None,
                "add_ssh_config": True,
                "parallelism": 1,
                "offline": True,
            },
        )
        self.assertIs(spec["offline"], True)


if __name__ == "__main__":
    unittest.main()
