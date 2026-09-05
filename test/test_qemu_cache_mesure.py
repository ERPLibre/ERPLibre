#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le verdict du test long dit-il la vérité sur ce qu'il a mesuré ?

Le test long crée deux VM et dure des dizaines de minutes ; son CRITÈRE, lui,
est une fonction pure sur des lignes de journal. La tester ici coûte des
millisecondes et évite la seule chose qu'un test de quarante minutes ne
pardonne pas : un verdict faux au bout de la course.

Le piège que ces cas verrouillent : Arch est une publication continue. Entre
les deux déploiements, un miroir publie des versions neuves que la seconde VM
tirera légitimement — le cache ne sert jamais un index tant que l'amont
répond, donc elle les VERRA. Un critère fondé sur « zéro octet d'amont »
déclarerait le cache en panne alors qu'il fonctionne.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "long_test"))


def charger():
    """Le script long chargé comme module : il n'est pas un paquet."""
    chemin = RACINE / "long_test" / "qemu_cache.py"
    spec = importlib.util.spec_from_file_location("qemu_cache_long", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


QC = charger()


def ligne(url, upstream, octets=1000, issue="stored"):
    return {
        "url": url,
        "upstream": upstream,
        "bytes": octets,
        "outcome": issue,
        "class": "immutable",
    }


PAQUET_A = (
    "https://miroir.example/arch/core/os/x86_64/bash-5.2-1-x86_64.pkg.tar.zst"
)
PAQUET_B = (
    "https://miroir.example/arch/core/os/x86_64/git-2.51-1-x86_64.pkg.tar.zst"
)
PAQUET_NEUF = (
    "https://miroir.example/arch/core/os/x86_64/rust-1.91-1-x86_64.pkg.tar.zst"
)
INDEX = "https://miroir.example/arch/core/os/x86_64/core.db"


class TestFiltre(unittest.TestCase):
    def test_les_index_sont_ecartes(self):
        """Un index n'est JAMAIS servi du cache quand l'amont répond : le
        compter ferait échouer un test qui mesure autre chose."""
        lignes = [ligne(INDEX, True), ligne(PAQUET_A, True)]
        gardees = QC.paquets_seulement(lignes)
        self.assertEqual(len(gardees), 1)
        self.assertEqual(gardees[0]["url"], PAQUET_A)

    def test_les_deux_extensions_de_paquet(self):
        vieux = PAQUET_A.replace(".pkg.tar.zst", ".pkg.tar.xz")
        self.assertEqual(len(QC.paquets_seulement([ligne(vieux, True)])), 1)

    def test_une_url_absente_ne_casse_pas(self):
        self.assertEqual(QC.paquets_seulement([{"upstream": True}]), [])


class TestVerdict(unittest.TestCase):
    def test_le_cache_a_servi(self):
        premier = [ligne(PAQUET_A, True), ligne(PAQUET_B, True)]
        second = [
            ligne(PAQUET_A, False, issue="hit"),
            ligne(PAQUET_B, False, issue="hit"),
        ]
        self.assertTrue(QC.verdict(premier, second, None))

    def test_un_paquet_deja_vu_ressorti_est_un_echec(self):
        premier = [ligne(PAQUET_A, True)]
        second = [ligne(PAQUET_A, True)]
        self.assertFalse(
            QC.verdict(premier, second, None),
            "un fichier déjà tiré est ressorti sur le réseau sans que le "
            "verdict s'en plaigne",
        )

    def test_un_paquet_neuf_ne_fait_pas_echouer(self):
        """LE cas qui justifie le critère : le miroir a publié entre les deux
        déploiements. La seconde VM tire légitimement du neuf, et le cache a
        pourtant parfaitement servi ce qu'il avait."""
        premier = [ligne(PAQUET_A, True)]
        second = [
            ligne(PAQUET_A, False, issue="hit"),
            ligne(PAQUET_NEUF, True, octets=90_000_000),
        ]
        self.assertTrue(
            QC.verdict(premier, second, None),
            "un paquet publié entre les deux VM a été pris pour une panne",
        )

    def test_une_mesure_vide_est_un_echec(self):
        """Le cas qui a coûté vingt minutes : un détournement posé sur le
        mauvais sous-réseau laisse les VM sortir en direct. Le cache ne voit
        rien, le verdict n'a « aucune faute » à signaler — et rendre vrai
        déclarerait un succès qu'il n'a jamais mesuré."""
        self.assertFalse(
            QC.verdict([], [], None),
            "un cache que personne ne traverse est déclaré bon",
        )

    def test_une_seconde_vm_muette_est_un_echec(self):
        """La première a rempli, la seconde n'a rien demandé : il n'y a pas
        de mesure, donc pas de succès."""
        self.assertFalse(QC.verdict([ligne(PAQUET_A, True)], [], None))

    def test_le_melange(self):
        premier = [ligne(PAQUET_A, True), ligne(PAQUET_B, True)]
        second = [
            ligne(PAQUET_A, False, issue="hit"),
            ligne(PAQUET_B, True),
            ligne(PAQUET_NEUF, True),
        ]
        self.assertFalse(
            QC.verdict(premier, second, None),
            "un seul fichier déjà vu ressorti suffit à faire échouer",
        )


class TestLectureDuJournal(unittest.TestCase):
    def test_ne_lit_que_ce_qui_suit_le_decalage(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "acces.jsonl"
            p.write_text(
                json.dumps(ligne(PAQUET_A, True)) + "\n", encoding="utf-8"
            )
            decalage = p.stat().st_size
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ligne(PAQUET_B, False)) + "\n")
            lues, neuf = QC.lignes_depuis(str(p), decalage)
            self.assertEqual([x["url"] for x in lues], [PAQUET_B])
            self.assertEqual(neuf, p.stat().st_size)

    def test_journal_tourne_repart_du_debut(self):
        """Un journal plus court que le décalage a été remplacé : lire à
        l'ancienne position rendrait n'importe quoi, ou rien."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "acces.jsonl"
            p.write_text(
                json.dumps(ligne(PAQUET_A, True)) + "\n", encoding="utf-8"
            )
            lues, _ = QC.lignes_depuis(str(p), 10_000_000)
            self.assertEqual(len(lues), 1)

    def test_derniere_ligne_incomplete_sautee(self):
        """Le service écrit pendant qu'on lit : la dernière ligne peut être
        tronquée, et une exception ici perdrait toute la mesure."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "acces.jsonl"
            p.write_text(
                json.dumps(ligne(PAQUET_A, True)) + '\n{"url": "tron',
                encoding="utf-8",
            )
            lues, _ = QC.lignes_depuis(str(p), 0)
            self.assertEqual(len(lues), 1)

    def test_journal_absent(self):
        lues, decalage = QC.lignes_depuis("/inexistant/acces.jsonl", 42)
        self.assertEqual(lues, [])
        self.assertEqual(decalage, 42)


class TestConventionsDuTestLong(unittest.TestCase):
    """Ce que « long_test/ » exige de ses scripts."""

    def setUp(self):
        self.source = (RACINE / "long_test" / "qemu_cache.py").read_text(
            encoding="utf-8"
        )

    def test_defaire_et_a_blanc(self):
        for drapeau in ("--dry-run", "--detruire"):
            self.assertIn(drapeau, self.source, f"{drapeau} manque")

    def test_destruction_par_uuid(self):
        """Un nom se réutilise, et « --remove-all-storage » efface un disque
        pour de bon : le dépôt identifie ses machines par UUID."""
        self.assertIn("detruire_etage1", self.source)
        self.assertIn("attendu=", self.source)
        self.assertIn("uuid_libvirt", self.source)

    def test_la_coupure_vise_le_compte_du_service(self):
        """Couper tout le 443 de l'orchestrateur emporterait la session ssh
        depuis laquelle le test se lance."""
        self.assertIn("meta skuid", self.source)
        self.assertNotIn("policy drop", self.source)

    def test_la_coupure_est_toujours_retiree(self):
        self.assertIn("finally:", self.source)
        self.assertIn("rebrancher_lamont", self.source)

    def test_hors_du_lanceur_unitaire(self):
        """Le lanceur balaie « test/test_*.py » : ce script ne doit pas y
        être, ni porter un nom qu'il ramasserait."""
        self.assertFalse(
            (RACINE / "test" / "test_qemu_cache_long.py").exists(),
            "un test qui crée de vraies machines est entré dans test/",
        )


if __name__ == "__main__":
    unittest.main()
