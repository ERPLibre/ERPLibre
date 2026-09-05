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

import argparse
import importlib.util
import json
import re
import sys
import tempfile
import unittest
import unittest.mock
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


class TestCeQuIlFautDefaire(unittest.TestCase):
    """Un échec ne doit pas faire perdre le moyen de défaire ce qui existe.

    Le nom d'une machine est noté AVANT sa création, pour qu'une création
    interrompue à mi-chemin laisse une trace. Une exécution qui échoue tout de
    suite écrit donc un rapport qui NOMME une machine sans la connaître, et
    s'en tenir au dernier rapport ferait retomber la destruction sur le nom —
    ce que ce dépôt a appris à ne plus faire, « --remove-all-storage »
    effaçant un disque pour de bon.
    """

    def rapports(self, *contenus):
        """Écrit des rapports datés dans un faux dépôt de rapports.

        Le balayage des machines VIVANTES est neutralisé ici : sans cela ces
        contrôles liraient le libvirt de la machine qui les exécute, et
        passeraient ou tomberaient selon ce qui y tourne. Le balayage a ses
        propres contrôles, où il est la chose mesurée.
        """
        import contextlib
        import json as _json
        import tempfile
        from unittest import mock

        d = tempfile.mkdtemp()
        for i, c in enumerate(contenus):
            nom = f"qemu_cache-2026090{i + 1}-000000.json"
            (Path(d) / nom).write_text(_json.dumps(c), encoding="utf-8")

        @contextlib.contextmanager
        def isole():
            with mock.patch.object(
                QC.os.path,
                "expanduser",
                lambda p: d if "longtest" in p else p,
            ), mock.patch.object(QC, "machines_vivantes", return_value=[]):
                yield

        return d, isole()

    def test_un_uuid_connu_survit_a_un_rapport_muet(self):
        d, patch = self.rapports(
            {"vms": ["vm-1"], "uuids": {"vm-1": "UUID-1"}},
            {"vms": ["vm-1"]},  # l'échec qui suit, sans UUID
        )
        with patch:
            machines, lus = QC.machines_a_defaire()
        self.assertEqual(len(lus), 2)
        self.assertEqual(
            machines.get("vm-1"),
            "UUID-1",
            "l'échec le plus récent a fait perdre l'UUID qui permet de"
            " détruire sans risque",
        )

    def test_les_machines_de_plusieurs_essais_sont_reunies(self):
        d, patch = self.rapports(
            {"vms": ["vm-1", "vm-2"], "uuids": {"vm-1": "U1", "vm-2": "U2"}},
            {"vms": ["vm-3"], "uuids": {"vm-3": "U3"}},
        )
        with patch:
            machines, _ = QC.machines_a_defaire()
        self.assertEqual(
            sorted(machines),
            ["vm-1", "vm-2", "vm-3"],
            "s'en tenir au dernier rapport laisserait vivantes les machines"
            " d'un essai antérieur",
        )

    def test_un_rapport_sans_machine_est_saute(self):
        d, patch = self.rapports({"vms": []}, {"vms": ["vm-1"]})
        with patch:
            machines, lus = QC.machines_a_defaire()
        self.assertEqual(len(lus), 1)
        self.assertEqual(sorted(machines), ["vm-1"])

    def test_aucun_rapport_et_aucune_machine(self):
        """Rien à lire, rien qui vit : il n'y a rien à défaire."""
        d, patch = self.rapports()
        with patch:
            machines, lus = QC.machines_a_defaire()
        self.assertEqual((machines, lus), ({}, []))


class TestUnPlanNestPasUneMesure(unittest.TestCase):
    """Un essai à blanc écrit un rapport, et le comparatif le comptait.

    Le plan ne crée aucune VM et n'installe aucun paquet : ses durées valent
    zéro. Comptées comme des mesures, elles montrent dans le tableau des
    exécutions qui n'ont jamais eu lieu et tirent la moyenne vers le bas — un
    témoin à blanc faisait ainsi croire à une comparaison qui n'existait pas.
    """

    def test_un_rapport_marque_a_blanc_est_ecarte(self):
        self.assertFalse(
            QC.mesure_reelle({"dry_run": True, "durees": {"vm-1": 42.0}})
        )

    def test_un_rapport_ancien_se_trahit_par_ses_zeros(self):
        """Les rapports d'avant la marque : une installation de paquets qui
        prend zéro seconde n'a pas eu lieu."""
        self.assertFalse(
            QC.mesure_reelle({"durees": {"vm-1": 0.0, "vm-2": 0.0}})
        )

    def test_une_vraie_mesure_passe(self):
        self.assertTrue(
            QC.mesure_reelle({"durees": {"vm-1": 19.6, "vm-2": 20.6}})
        )

    def test_un_rapport_sans_duree_ne_mesure_rien(self):
        self.assertFalse(QC.mesure_reelle({}))

    def test_le_comparatif_applique_bien_le_filtre(self):
        """Le contrôle précédent vérifie la RÈGLE ; celui-ci vérifie qu'elle
        est branchée. Sans lui, retirer l'appel laisse les tests verts et
        remet les lignes fantômes dans le tableau."""
        with tempfile.TemporaryDirectory() as rep:
            rapports = {
                "qemu_cache-20260101-000001.json": {
                    "outil": "qemu_cache",
                    "debut": "2026-01-01T00:00:01",
                    "dry_run": True,
                    "durees": {"vm-1": 0.0},
                },
                "qemu_cache-20260101-000002.json": {
                    "outil": "qemu_cache",
                    "debut": "2026-01-01T00:00:02",
                    "durees": {"vm-1": 12.5},
                },
            }
            for nom, contenu in rapports.items():
                with open(Path(rep) / nom, "w", encoding="utf-8") as fh:
                    json.dump(contenu, fh)
            with unittest.mock.patch.object(
                QC.os.path, "expanduser", return_value=rep
            ):
                vus = QC.rapports_recents()
        self.assertEqual(
            [r["durees"] for r in vus],
            [{"vm-1": 12.5}],
            "un plan à blanc revient dans le rapport de performance",
        )


class TestUnPrefixeParMode(unittest.TestCase):
    """Les trois modes ne doivent plus se disputer les mêmes machines.

    Ils créent tous une « première » et une « seconde » VM. Sous un préfixe
    unique, lancer le témoin après la mesure butait sur « machine(s) d'un
    essai précédent encore là » alors qu'il s'agissait d'une AUTRE expérience,
    et il fallait tout défaire pour comparer — ce que la comparaison exige
    justement de ne pas faire.
    """

    def mode(self, **kw):
        base = {
            "sans_cache": False,
            "hors_ligne": False,
            "distro": "arch",
            "version": "latest",
            "charge": "minimum",
        }
        base.update(kw)
        return argparse.Namespace(**base)

    def test_les_trois_preflxes_different(self):
        noms = {
            QC.base_des_noms(self.mode()),
            QC.base_des_noms(self.mode(sans_cache=True)),
            QC.base_des_noms(self.mode(hors_ligne=True)),
        }
        self.assertEqual(
            len(noms), 3, f"des modes partagent un préfixe : {noms}"
        )

    def test_le_temoin_se_nomme_sans_cache(self):
        self.assertTrue(
            QC.base_des_noms(self.mode(sans_cache=True)).startswith(
                "el-no-cache-"
            )
        )

    def test_le_nom_porte_le_systeme_et_la_charge(self):
        """Lire « virsh list » doit suffire à savoir d'où vient une machine,
        et deux essais qui ne portent pas sur la même chose ne doivent plus se
        disputer les mêmes noms."""
        self.assertEqual(
            QC.base_des_noms(
                self.mode(distro="ubuntu", version="24.04", charge="erplibre")
            ),
            "el-cache-ubuntu_2404-erplibre_odoo_18",
        )

    def test_latest_ne_figure_pas_dans_le_nom(self):
        """Une distribution en publication continue n'a qu'une version : le
        segment ne distinguerait aucune machine d'une autre."""
        self.assertEqual(
            QC.base_des_noms(self.mode(distro="arch", version="latest")),
            "el-cache-arch-minimum",
        )

    def test_un_essai_ne_bloque_pas_un_essai_different(self):
        """Le grief exact : mesurer Ubuntu butait sur des machines Arch."""
        arch = QC.base_des_noms(self.mode())
        ubuntu = QC.base_des_noms(
            self.mode(distro="ubuntu", version="24.04", charge="erplibre")
        )
        self.assertFalse(ubuntu.startswith(arch))
        self.assertFalse(arch.startswith(ubuntu))

    def test_le_prealable_ne_regarde_que_son_propre_prefixe(self):
        """Une machine d'une autre expérience n'entre en conflit avec rien."""
        vivantes = "el-cache-test-1\nel-no-cache-test-1\nautre-vm\n"
        with unittest.mock.patch.object(
            QC, "executer", return_value=(0, vivantes)
        ):
            self.assertEqual(
                QC.machines_vivantes("el-no-cache-test"),
                ["el-no-cache-test-1"],
            )

    def test_la_destruction_balaie_les_trois(self):
        """Les rapports sont bornés : une machine plus ancienne que la fenêtre
        ne serait jamais défaite et bloquerait tous les essais suivants."""
        vivantes = "el-cache-test-9\nel-offline-test-9\nel-no-cache-test-9\n"
        with unittest.mock.patch.object(
            QC, "executer", return_value=(0, vivantes)
        ), unittest.mock.patch.object(
            QC.os.path, "expanduser", return_value="/inexistant"
        ):
            machines, _ = QC.machines_a_defaire()
        self.assertEqual(
            sorted(machines),
            ["el-cache-test-9", "el-no-cache-test-9", "el-offline-test-9"],
        )


class TestLeMenuNeRefabriquePasLesNoms(unittest.TestCase):
    """Le menu annonce les machines qui vont naître : il les DEMANDE.

    Deux fabriques de noms dériveraient en silence, et le menu annoncerait
    alors des VM qui ne sont pas celles qui apparaissent dans « virsh list » —
    pire que de ne rien annoncer. Ce contrôle interdit donc au menu d'écrire un
    préfixe en dur.
    """

    def menu_source(self):
        return (
            Path(__file__).resolve().parent.parent
            / "script"
            / "todo"
            / "qemu_cache_menu.py"
        ).read_text(encoding="utf-8")

    def test_aucun_prefixe_ecrit_en_dur(self):
        trouves = set(re.findall(r'"(el-[a-z-]+)"', self.menu_source()))
        self.assertEqual(
            trouves,
            set(),
            f"le menu écrit des noms de machine en dur : {trouves}",
        )

    def test_le_menu_appelle_la_fabrique_du_script(self):
        self.assertIn("module.nom_de_base(", self.menu_source())


if __name__ == "__main__":
    unittest.main()
