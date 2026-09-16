#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que le test long télécharge, et sur quel système.

Trois axes désormais : l'essai (cache, contre-épreuve, témoin), la charge
(un lot de paquets ou l'installation réelle) et la distribution. Chacun a sa
façon de se tromper en silence.

La charge doit être IDENTIQUE d'une VM à l'autre, sans quoi la comparaison ne
compare rien. Elle doit aussi correspondre à la famille de la distribution :
un nom de paquet d'une autre famille fait échouer l'installation loin de sa
cause, après le déploiement d'une machine entière.

Et le catalogue des systèmes n'est PAS recopié : il vient du déploiement. Une
seconde table proposerait un système que le déploiement ne sait pas installer,
ce que l'on ne découvrirait qu'en le lançant.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))


def charger():
    chemin = RACINE / "long_test" / "qemu_cache.py"
    spec = importlib.util.spec_from_file_location("qemu_cache_long", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


QC = charger()


class TestLeCatalogueVientDuDeploiement(unittest.TestCase):
    def test_aucun_systeme_inconnu_du_deploiement(self):
        from script.qemu.deploy_qemu import DISTROS

        for d in QC.systemes_mesurables():
            self.assertIn(
                d, DISTROS, f"« {d} » n'est pas au catalogue du déploiement"
            )

    def test_chaque_systeme_a_une_famille_servie(self):
        """Proposer un système dont on ne sait pas installer les paquets, c'est
        déployer une VM entière pour échouer à la dernière étape."""
        for d in QC.systemes_mesurables():
            self.assertIn(
                QC.famille_de(d),
                QC.PAQUETS_MINIMUM,
                f"« {d} » n'a pas de lot de paquets",
            )

    def test_proxmox_est_ecarte(self):
        """Un hyperviseur : on n'y installe ni ERPLibre ni un lot de
        développement, et le déploiement lui impose déjà son profil."""
        self.assertNotIn("proxmox", QC.systemes_mesurables())

    def test_les_quatre_familles_sont_couvertes(self):
        self.assertEqual(
            set(QC.PAQUETS_MINIMUM), {"pacman", "apt", "dnf", "zypper"}
        )


class TestLaCharge(unittest.TestCase):
    def test_chaque_famille_rend_une_commande(self):
        for d in sorted(QC.systemes_mesurables()):
            self.assertTrue(
                QC.commande_de_charge(d, "minimum"),
                f"aucune charge minimale pour « {d} »",
            )

    def test_un_systeme_hors_catalogue_ne_rend_rien(self):
        """Rendre une commande vide plutôt qu'une commande fausse : le test
        s'arrête en le disant, au lieu de lancer un shell vide dans la VM."""
        self.assertEqual(QC.commande_de_charge("haiku", "minimum"), "")

    def test_la_charge_reelle_contient_la_minimale(self):
        """Elles partagent leur début, ce qui rend leurs mesures comparables
        sur cette portion — et « make » n'existe pas avant que git l'ait
        cloné."""
        for d in sorted(QC.systemes_mesurables()):
            minimum = QC.commande_de_charge(d, "minimum")
            reelle = QC.commande_de_charge(d, "erplibre")
            self.assertTrue(
                reelle.startswith(minimum),
                f"« {d} » : la charge réelle ne part pas de la minimale",
            )

    def test_la_charge_reelle_clone_puis_installe(self):
        cmd = QC.commande_de_charge("arch", "erplibre")
        self.assertIn("git clone", cmd)
        self.assertIn("install_odoo_18", cmd)
        self.assertLess(
            cmd.index("git clone"),
            cmd.index("install_odoo_18"),
            "la cible make est lancée avant que le dépôt existe",
        )

    def test_chaque_charge_a_son_delai(self):
        """Un délai unique ferait échouer la courte ou laisserait la longue
        pendre : ERPLibre se compte en heures, le lot en minutes."""
        self.assertEqual(set(QC.DELAI_CHARGE), {"minimum", "erplibre"})
        self.assertGreater(
            QC.DELAI_CHARGE["erplibre"], QC.DELAI_CHARGE["minimum"]
        )

    def test_la_charge_attend_cloud_init_avant_tout(self):
        """cloud-init réécrit la liste des dépôts à son premier démarrage.

        Une mise à jour lancée pendant ce remplacement récupère une partie des
        index et s'arrête là SANS échouer : l'installation qui suit ne trouve
        plus les paquets de « main », et le message accuse le paquet plutôt que
        le moment. sshd répond bien avant que cloud-init ait fini.
        """
        for d in sorted(QC.systemes_mesurables()):
            cmd = QC.commande_de_charge(d, "minimum")
            self.assertTrue(
                cmd.startswith(QC.ATTENDRE_CLOUD_INIT),
                f"« {d} » touche au gestionnaire de paquets sans attendre",
            )

    def test_lattente_tolere_un_cloud_init_en_erreur(self):
        """Il sort en erreur pour un module accessoire — un fuseau que
        l'invité ne connaît pas — et ce n'est pas une raison de renoncer."""
        self.assertIn("|| true", QC.ATTENDRE_CLOUD_INIT)

    def test_lattente_relit_les_variables_du_cache(self):
        """La session de la charge s'ouvre avant que cloud-init n'écrive les
        variables du cache : « sudo npm » les relit, pas un npm sans sudo."""
        from script.qemu.deploy_qemu import cache_env_reload

        i = QC.ATTENDRE_CLOUD_INIT.index("status --wait")
        self.assertIn(cache_env_reload(), QC.ATTENDRE_CLOUD_INIT[i:])

    def test_la_charge_est_du_shell_valide(self):
        """Une instruction collée sans séparateur casse la commande entière,
        et la VM ne dit alors pas pourquoi elle n'a rien installé."""
        import subprocess

        for d in sorted(QC.systemes_mesurables()):
            for charge in ("minimum", "erplibre"):
                cmd = QC.commande_de_charge(d, charge)
                res = subprocess.run(
                    ["bash", "-n", "-c", cmd], capture_output=True, text=True
                )
                self.assertEqual(
                    res.returncode, 0, f"« {d} », {charge} : {res.stderr}"
                )

    def test_apt_ne_cache_plus_ses_echecs(self):
        """« apt-get update » rend ZÉRO même quand un index n'a pas pu être
        récupéré : il n'émet qu'un avertissement, que « -qq » cachait."""
        rafraichir = QC.PAQUETS_MINIMUM["apt"][0]
        self.assertIn("APT::Update::Error-Mode=any", rafraichir)
        self.assertNotIn("-qq", rafraichir)

    def test_le_plan_a_blanc_montre_la_commande_exacte(self):
        """Un plan qui montre autre chose que ce qui sera lancé n'est pas un
        plan."""
        from unittest import mock

        with mock.patch.object(QC, "dire") as dit:
            QC.poser_les_paquets(
                "10.0.0.1",
                None,
                dry_run=True,
                distro="debian",
                charge="erplibre",
            )
        annonce = " ".join(str(a) for c in dit.call_args_list for a in c.args)
        self.assertIn(QC.commande_de_charge("debian", "erplibre"), annonce)


class TestLesOptions(unittest.TestCase):
    def test_la_version_vide_vient_du_catalogue(self):
        from script.qemu.deploy_qemu import DISTROS

        for d in sorted(QC.systemes_mesurables()):
            defaut = DISTROS[d][1]
            self.assertTrue(
                defaut, f"« {d} » n'a pas de version par défaut au catalogue"
            )


class TestLeRapportSeClotSurUnEchec(unittest.TestCase):
    """Une étape qui échoue arrête la boucle : le rapport doit le dire.

    Sans « fin » ni « verdict », un rapport laissé par une VM qui n'a pas
    installé se lit comme une exécution encore en cours.
    """

    def boucler(self, echoue):
        import argparse
        import json
        import tempfile
        from unittest import mock

        args = argparse.Namespace(
            dry_run=False,
            sans_cache=False,
            hors_ligne=False,
            distro="debian",
            version="12",
            charge="minimum",
        )
        with tempfile.TemporaryDirectory() as rep:
            fichier = str(Path(rep) / "rapport.json")
            rapport = {"_fichier": fichier, "vms": []}
            with mock.patch.object(QC, "dire"), mock.patch.object(
                QC, "noter_uuid"
            ), mock.patch.object(
                QC,
                "deployer",
                return_value="" if echoue == "deployer" else "10.0.0.1",
            ), mock.patch.object(
                QC, "attendre_ssh", return_value=echoue != "attendre_ssh"
            ), mock.patch.object(
                QC,
                "poser_les_paquets",
                return_value=echoue != "poser_les_paquets",
            ):
                code = QC._boucle(args, rapport, None, "", 0)
            with open(fichier, encoding="utf-8") as fh:
                return code, json.load(fh)

    def test_chaque_etape_en_echec_ecrit_fin_et_verdict(self):
        for etape, mot in (
            ("deployer", "déploiement"),
            ("attendre_ssh", "ssh"),
            ("poser_les_paquets", "paquets"),
        ):
            with self.subTest(etape=etape):
                code, ecrit = self.boucler(etape)
                self.assertEqual(code, 1)
                self.assertEqual(ecrit.get("verdict"), "échec")
                self.assertTrue(ecrit.get("fin"))
                self.assertIn(mot, ecrit.get("etape_en_echec", ""))

    def test_un_echec_n_est_pas_un_succes(self):
        """Le verdict « ok » reste réservé à la boucle menée à son terme."""
        code, ecrit = self.boucler("deployer")
        self.assertNotEqual(ecrit.get("verdict"), "ok")
        self.assertEqual(len(ecrit["vms"]), 1)


class TestLaTroisiemeVmNaitHorsLigne(unittest.TestCase):
    """Le déploiement coupe l'audit de npm d'une VM hors ligne : le test long
    doit le lui demander, comme le formulaire, sans quoi il mesure une VM que
    personne ne déploierait ainsi."""

    def commande(self, **kw):
        from unittest import mock

        with mock.patch.object(QC, "dire") as dit, mock.patch.object(
            QC, "cle_publique", return_value="/tmp/cle.pub"
        ):
            QC.deployer("vm", None, dry_run=True, **kw)
        return " ".join(str(a) for c in dit.call_args_list for a in c.args)

    def test_la_vm_hors_ligne_recoit_offline(self):
        self.assertIn("--offline", self.commande(hors_ligne=True))

    def test_les_vm_en_ligne_n_en_recoivent_pas(self):
        self.assertNotIn("--offline", self.commande())

    def test_le_temoin_sans_cache_n_en_recoit_pas(self):
        self.assertNotIn(
            "--offline", self.commande(avec_cache=False, hors_ligne=True)
        )

    def test_la_contre_epreuve_le_demande(self):
        import inspect

        source = inspect.getsource(QC.contre_epreuve)
        self.assertIn("hors_ligne=True", source)


class TestPlusieursSystemes(unittest.TestCase):
    """Une série de campagnes, un système après l'autre."""

    def test_tous_designe_chaque_systeme_mesurable(self):
        self.assertEqual(
            QC.systemes_demandes("tous"), sorted(QC.systemes_mesurables())
        )

    def test_une_liste_garde_son_ordre_sans_doublon(self):
        self.assertEqual(
            QC.systemes_demandes("fedora, debian,fedora"), ["fedora", "debian"]
        )

    def test_un_nom_inconnu_est_refuse_avant_toute_machine(self):
        with self.assertRaises(ValueError):
            QC.systemes_demandes("fedora,haiku")

    def lancer(self, argv, codes=None):
        from unittest import mock

        appels = []
        codes = list(codes or [])

        def campagne(a):
            appels.append((a.distro, a.version))
            return (codes.pop(0) if codes else 0), ""

        with mock.patch.object(
            QC, "une_campagne", side_effect=campagne
        ), mock.patch.object(
            QC,
            "detruire",
            side_effect=lambda *x, **k: appels.append("détruire"),
        ), mock.patch(
            "builtins.print"
        ):
            code = QC.main(argv)
        return code, appels

    def test_la_serie_defait_les_machines_entre_deux_systemes(self):
        from script.qemu.deploy_qemu import DISTROS

        code, appels = self.lancer(
            [
                "--distro",
                "fedora,debian",
                "--charge",
                "erplibre",
                "--hors-ligne",
            ]
        )
        self.assertEqual(
            appels,
            [
                ("fedora", DISTROS["fedora"][1]),
                "détruire",
                ("debian", DISTROS["debian"][1]),
                "détruire",
            ],
        )
        self.assertEqual(code, 0)

    def test_un_echec_n_arrete_pas_la_serie(self):
        code, appels = self.lancer(["--distro", "fedora,debian"], codes=[1, 0])
        self.assertEqual(len([a for a in appels if a != "détruire"]), 2)
        self.assertEqual(code, 1)

    def test_a_blanc_rien_n_est_defait(self):
        _, appels = self.lancer(["--distro", "fedora,debian", "--dry-run"])
        self.assertNotIn("détruire", appels)

    def test_la_version_est_refusee_pour_plusieurs_systemes(self):
        from unittest import mock

        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            QC.main(["--distro", "tous", "--version", "12"])

    def test_un_seul_systeme_suit_le_chemin_d_avant(self):
        from script.qemu.deploy_qemu import DISTROS

        _, appels = self.lancer(["--distro", "ubuntu"])
        self.assertEqual(appels, [("ubuntu", DISTROS["ubuntu"][1])])


if __name__ == "__main__":
    unittest.main()
