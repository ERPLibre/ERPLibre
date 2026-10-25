#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La commande des tests de synchronisation mobile, sans Odoo ni base.

long_test/mobile_sync.py démarre de vrais Odoo et dure des minutes ; ce
qu'elle décide avant de les démarrer se vérifie ici, en quelques
millisecondes : les prérequis et leurs messages (le dépôt mobile d'abord),
les versions, les noms de bases, le balayage, la configuration des
serveurs, la clé des gabarits, et la lecture du rapport de Vitest, où zéro
test est un échec et pas une réussite silencieuse.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "long_test"))

import mobile_sync  # noqa: E402
import mobile_sync_device as appareil  # noqa: E402
import mobile_sync_odoo as odoo  # noqa: E402

KIT = "export const HARNESS_API = {api};\n"


def node(version):
    """Un faux subprocess.run qui répond `node --version`."""
    return lambda *a, **k: SimpleNamespace(
        stdout=f"v{version}.1.0\n", returncode=0
    )


def depot_mobile(
    racine, nom="erplibre-mobile", api=odoo.HARNESS_API, vitest=True, kit=True
):
    mobile = Path(racine) / "mobile"
    (mobile / "src" / "testing").mkdir(parents=True)
    (mobile / "package.json").write_text(json.dumps({"name": nom}))
    if kit:
        (mobile / "src" / "testing" / "syncTestKit.ts").write_text(
            KIT.format(api=api)
        )
    if vitest:
        (mobile / "node_modules" / ".bin").mkdir(parents=True)
        (mobile / "node_modules" / ".bin" / "vitest").write_text("")
    return mobile


class TestDepotMobile(unittest.TestCase):
    """Le dépôt mobile d'abord : absent, trop ancien ou sans dépendances, la
    commande s'arrête en disant quoi faire."""

    def test_pret(self):
        with tempfile.TemporaryDirectory() as racine:
            self.assertEqual(
                odoo.verifier_mobile(depot_mobile(racine), executer=node(22)),
                [],
            )

    def test_absent_renvoie_a_son_installation(self):
        with tempfile.TemporaryDirectory() as racine:
            problemes = odoo.verifier_mobile(
                Path(racine) / "absent", executer=node(22)
            )
        self.assertEqual(len(problemes), 1)
        self.assertIn("./mobile/install_mobile_dev.sh", problemes[0])

    def test_autre_paquet(self):
        with tempfile.TemporaryDirectory() as racine:
            problemes = odoo.verifier_mobile(
                depot_mobile(racine, nom="autre"), executer=node(22)
            )
        self.assertTrue(any("erplibre-mobile" in p for p in problemes))

    def test_node_trop_ancien(self):
        with tempfile.TemporaryDirectory() as racine:
            problemes = odoo.verifier_mobile(
                depot_mobile(racine), executer=node(20)
            )
        self.assertTrue(any("Node 22" in p for p in problemes))

    def test_dependances_absentes(self):
        with tempfile.TemporaryDirectory() as racine:
            problemes = odoo.verifier_mobile(
                depot_mobile(racine, vitest=False), executer=node(22)
            )
        self.assertTrue(any("npm ci" in p for p in problemes))

    def test_kit_absent_ou_autre_api(self):
        with tempfile.TemporaryDirectory() as racine:
            sans_kit = odoo.verifier_mobile(
                depot_mobile(racine, kit=False), executer=node(22)
            )
        with tempfile.TemporaryDirectory() as racine:
            autre_api = odoo.verifier_mobile(
                depot_mobile(racine, api=odoo.HARNESS_API + 1),
                executer=node(22),
            )
        self.assertTrue(any("syncTestKit" in p for p in sans_kit))
        self.assertTrue(
            any(f"API {odoo.HARNESS_API + 1}" in p for p in autre_api)
        )


class TestVersions(unittest.TestCase):
    def arbre(self, racine, version, venvs=1):
        odoo_bin = Path(racine) / f"odoo{version}.0" / "odoo" / "odoo-bin"
        odoo_bin.parent.mkdir(parents=True)
        odoo_bin.write_text("")
        for i in range(venvs):
            (
                Path(racine) / f".venv.odoo{version}.0_python3.1{i}" / "bin"
            ).mkdir(parents=True)

    def test_trouve_odoo_bin_et_son_venv(self):
        with tempfile.TemporaryDirectory() as racine:
            self.arbre(racine, 17)
            trouvees = odoo.versions_installees(Path(racine), demandees=[17])
        self.assertEqual(trouvees[17].odoo_bin.name, "odoo-bin")
        self.assertIn(".venv.odoo17.0_", str(trouvees[17].python))
        self.assertTrue(trouvees[17].addons_path.endswith("odoo/odoo/addons"))

    def test_version_absente_ou_venv_ambigu(self):
        with tempfile.TemporaryDirectory() as racine:
            with self.assertRaisesRegex(
                odoo.PrerequisManquant, "Odoo 16 absent"
            ):
                odoo.versions_installees(Path(racine), demandees=[16])
            self.arbre(racine, 18, venvs=2)
            with self.assertRaisesRegex(odoo.PrerequisManquant, "2 venv"):
                odoo.versions_installees(Path(racine), demandees=[18])

    def test_lire_versions(self):
        self.assertEqual(odoo.lire_versions("18, 16,18"), [18, 16])
        for mauvais in ("15", "dix-sept", ""):
            with self.assertRaises(ValueError):
                odoo.lire_versions(mauvais)


class TestBasesEtServeurs(unittest.TestCase):
    def test_nom_de_course_valide_et_son_pid(self):
        nom = odoo.nom_course(4242, "20261023120000", 17)
        self.assertLessEqual(len(nom), odoo.LONGUEUR_NOM_MAX)
        self.assertEqual(odoo.pid_de_course(nom), 4242)
        self.assertIsNone(odoo.pid_de_course("mobile_sync_tpl_17"))
        self.assertEqual(odoo.pid_de_course("mobile_sync_tpl_16_build_77"), 77)
        with self.assertRaises(ValueError):
            odoo.nom_course(4242, "x" * 60, 17)

    def test_balaie_seulement_les_courses_mortes(self):
        bases = {
            odoo.nom_course(1, "20260101000000", 16),
            odoo.nom_course(2, "20260101000000", 17),
            "mobile_sync_tpl_16",
            "mobile_sync_tpl_17_build_3",
        }
        restes = odoo.a_balayer(bases, vivant=lambda pid: pid == 2)
        self.assertEqual(
            restes,
            [
                odoo.nom_course(1, "20260101000000", 16),
                "mobile_sync_tpl_17_build_3",
            ],
        )

    def test_configuration_d_un_serveur(self):
        version = odoo.VersionOdoo(
            17, Path("/x/odoo17.0/odoo/odoo-bin"), Path("/x/py")
        )
        texte = odoo.config_odoo(
            version, "mobile_sync_run_1_2_17", 8123, 8124, Path("/tmp/run")
        )
        for attendu in (
            "workers = 0",
            "max_cron_threads = 0",
            "list_db = False",
            "http_interface = 127.0.0.1",
            "http_port = 8123",
            "gevent_port = 8124",
            "dbfilter = ^mobile_sync_run_1_2_17$",
            "addons_path = /x/odoo17.0/odoo/addons,/x/odoo17.0/odoo/odoo/addons",
        ):
            self.assertIn(attendu, texte)

    def test_la_cle_du_gabarit_suit_la_post_installation(self):
        version = odoo.VersionOdoo(
            18, Path("/x/odoo18.0/odoo/odoo-bin"), Path("/x/py")
        )
        revision = lambda *a, **k: SimpleNamespace(
            stdout="abc123\n", returncode=0
        )
        avant = odoo.cle_gabarit(version, executer=revision)
        self.assertTrue(avant.startswith("mobile_sync:18:"))
        with mock.patch.object(
            odoo, "POST_INSTALLATION", odoo.POST_INSTALLATION + "\n# autre"
        ):
            self.assertNotEqual(
                odoo.cle_gabarit(version, executer=revision), avant
            )
        autre_revision = lambda *a, **k: SimpleNamespace(
            stdout="def456\n", returncode=0
        )
        self.assertNotEqual(
            odoo.cle_gabarit(version, executer=autre_revision), avant
        )

    def test_le_chemin_des_addons_de_18_porte_ceux_d_erplibre(self):
        v18 = odoo.VersionOdoo(
            18, Path("/x/odoo18.0/odoo/odoo-bin"), Path("/x/py")
        )
        v17 = odoo.VersionOdoo(
            17, Path("/x/odoo17.0/odoo/odoo-bin"), Path("/x/py")
        )
        self.assertIn(
            "/x/odoo18.0/addons/ERPLibre_erplibre_addons",
            v18.addons_path.split(","),
        )
        self.assertNotIn("ERPLibre_erplibre_addons", v17.addons_path)
        self.assertIn("erplibre_mobile_chat", v18.modules)
        self.assertNotIn("erplibre_mobile_chat", v17.modules)

    def test_la_cle_de_18_suit_les_addons_erplibre(self):
        with tempfile.TemporaryDirectory() as racine:
            odoo_bin = Path(racine) / "odoo18.0" / "odoo" / "odoo-bin"
            module = (
                Path(racine)
                / "odoo18.0"
                / "addons"
                / "ERPLibre_erplibre_addons"
                / "erplibre_mobile_chat"
            )
            module.mkdir(parents=True)
            (module / "a.py").write_text("un")
            version = odoo.VersionOdoo(18, odoo_bin, Path("/x/py"))
            tete = {"addons": "aaa"}

            def executer(commande, **kw):
                depot = commande[2]
                sortie = tete["addons"] if "ERPLibre" in depot else "core"
                return SimpleNamespace(stdout=sortie + "\n", returncode=0)

            avant = odoo.cle_gabarit(version, executer=executer)
            tete["addons"] = "bbb"
            apres_tete = odoo.cle_gabarit(version, executer=executer)
            (module / "a.py").write_text("deux")
            apres_contenu = odoo.cle_gabarit(version, executer=executer)
        self.assertNotEqual(avant, apres_tete)
        self.assertNotEqual(apres_tete, apres_contenu)

    def test_la_cle_de_16_et_17_ignore_les_addons_erplibre(self):
        appels = []

        def executer(commande, **kw):
            appels.append(commande[2])
            return SimpleNamespace(stdout="abc\n", returncode=0)

        for numero in (16, 17):
            version = odoo.VersionOdoo(
                numero,
                Path(f"/x/odoo{numero}.0/odoo/odoo-bin"),
                Path("/x/py"),
            )
            odoo.cle_gabarit(version, executer=executer)
        self.assertEqual(appels, ["/x/odoo16.0/odoo", "/x/odoo17.0/odoo"])

    def test_la_post_installation_cree_l_utilisateur_et_le_canal_du_chat(self):
        self.assertIn("chat_user", odoo.POST_INSTALLATION_CHAT)
        self.assertIn("ms chat", odoo.POST_INSTALLATION_CHAT)
        self.assertNotIn("chat_user", odoo.POST_INSTALLATION)
        self.assertEqual(odoo.post_installation(17), odoo.POST_INSTALLATION)
        self.assertIn(odoo.POST_INSTALLATION_CHAT, odoo.post_installation(18))
        compile(odoo.post_installation(18), "post", "exec")

    def test_cles_de_16_et_17_figees_et_18_suit_le_chat(self):
        """Les clés de 16 et 17 ne voient jamais le bloc du chat : elles
        valent le hachage du texte commun seul."""
        executer = lambda *a, **k: SimpleNamespace(
            stdout="abc\n", returncode=0
        )
        for numero in (16, 17):
            version = odoo.VersionOdoo(
                numero,
                Path(f"/x/odoo{numero}.0/odoo/odoo-bin"),
                Path("/x/py"),
            )
            attendu = hashlib.sha256(
                "\n".join(
                    [
                        "abc",
                        ",".join(version.modules),
                        odoo.POST_INSTALLATION,
                        odoo.FUSEAU,
                    ]
                ).encode()
            ).hexdigest()[:16]
            self.assertEqual(
                odoo.cle_gabarit(version, executer=executer),
                f"mobile_sync:{numero}:{attendu}",
            )
            with mock.patch.object(
                odoo, "POST_INSTALLATION_CHAT", "# autre chat"
            ):
                self.assertEqual(
                    odoo.cle_gabarit(version, executer=executer),
                    f"mobile_sync:{numero}:{attendu}",
                )
        v18 = odoo.VersionOdoo(
            18, Path("/x/odoo18.0/odoo/odoo-bin"), Path("/x/py")
        )
        avant = odoo.cle_gabarit(v18, executer=executer)
        with mock.patch.object(odoo, "POST_INSTALLATION_CHAT", "# autre chat"):
            self.assertNotEqual(
                odoo.cle_gabarit(v18, executer=executer), avant
            )

    def test_harness_api_2(self):
        self.assertEqual(odoo.HARNESS_API, 2)


class TestRapport(unittest.TestCase):
    """Zéro test, ou zéro test pour une version, est un échec : un chemin
    mal résolu ne doit pas passer pour une course verte."""

    def rapport(self, noms, echecs=0):
        donnees = {
            "numTotalTests": len(noms),
            "numFailedTests": echecs,
            "numFailedTestSuites": 0,
            "testResults": [
                {"assertionResults": [{"fullName": n} for n in noms]}
            ],
        }
        fichier = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        )
        json.dump(donnees, fichier)
        fichier.close()
        self.addCleanup(os.unlink, fichier.name)
        return fichier.name

    def test_tout_passe(self):
        bilan = mobile_sync.lire_rapport(
            self.rapport(["Odoo 16 — a x", "Odoo 18 — a x"]), [16, 18]
        )
        self.assertEqual(bilan, (2, 0, {16: 1, 18: 1}))
        self.assertEqual(mobile_sync.verdict(*bilan)[0], mobile_sync.SORTIE_OK)

    def test_aucun_test_ou_une_version_vide_echoue(self):
        vide = mobile_sync.lire_rapport(self.rapport([]), [16])
        self.assertEqual(
            mobile_sync.verdict(*vide),
            (mobile_sync.SORTIE_TESTS, "aucun test n'a tourné"),
        )
        sans_17 = mobile_sync.lire_rapport(
            self.rapport(["Odoo 16 — a x"]), [16, 17]
        )
        self.assertEqual(
            mobile_sync.verdict(*sans_17)[1], "aucun test pour Odoo 17"
        )

    def test_des_echecs(self):
        bilan = mobile_sync.lire_rapport(
            self.rapport(["Odoo 16 — a x"], echecs=1), [16]
        )
        self.assertEqual(
            mobile_sync.verdict(*bilan)[0], mobile_sync.SORTIE_TESTS
        )


class TestCommande(unittest.TestCase):
    def test_dry_run_ne_cree_rien(self):
        versions = {
            v: odoo.VersionOdoo(
                v, Path(f"/x/odoo{v}.0/odoo/odoo-bin"), Path("/x/py")
            )
            for v in odoo.VERSIONS
        }
        with mock.patch.object(
            odoo, "verifier_mobile", return_value=[]
        ), mock.patch.object(
            odoo, "versions_installees", return_value=versions
        ), mock.patch.object(
            odoo, "psql", return_value="1"
        ), mock.patch.object(
            odoo, "construire_gabarit"
        ) as construire, mock.patch.object(
            odoo, "supprimer_base"
        ) as supprimer, mock.patch.object(
            odoo, "copier_gabarit"
        ) as copier, mock.patch(
            "sys.stdout"
        ):
            code = mobile_sync.main(["--dry-run"])
        self.assertEqual(code, mobile_sync.SORTIE_OK)
        construire.assert_not_called()
        supprimer.assert_not_called()
        copier.assert_not_called()

    def test_un_prerequis_manquant_sort_en_2(self):
        with mock.patch.object(
            odoo,
            "verifier_mobile",
            return_value=["mobile/erplibre_home_mobile absent"],
        ), mock.patch.object(
            odoo, "versions_installees", return_value={}
        ), mock.patch.object(
            odoo, "psql", return_value="1"
        ), mock.patch(
            "sys.stdout"
        ):
            self.assertEqual(
                mobile_sync.main([]), mobile_sync.SORTIE_PREREQUIS
            )


def faux_adb(devices="SERIE\tdevice\n", fenetre="isKeyguardShowing=false"):
    """Un faux subprocess.run qui répond à adb devices et dumpsys window."""

    def executer(commande, **_):
        sortie = ""
        if commande[:2] == ["adb", "devices"]:
            sortie = "List of devices attached\n" + devices
        elif "dumpsys" in commande:
            sortie = fenetre
        return SimpleNamespace(stdout=sortie, stderr="", returncode=0)

    return executer


class TestAppareil(unittest.TestCase):
    """Le téléphone d'abord : absent, verrouillé, non autorisé ou ambigu,
    la commande s'arrête en disant quoi faire, sans rien installer."""

    def setUp(self):
        self.mobile = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.mobile))
        (self.mobile / "android").mkdir()
        (self.mobile / "android" / "gradlew").write_text("")
        self.adb_present = lambda nom: "/usr/bin/adb"

    def verifier(self, executer, which=None):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANDROID_SERIAL", None)
            return appareil.verifier_appareil(
                self.mobile, executer, which or self.adb_present
            )

    def test_pret(self):
        self.assertEqual(self.verifier(faux_adb()), [])

    def test_adb_absent(self):
        problemes = self.verifier(faux_adb(), which=lambda nom: None)
        self.assertEqual(len(problemes), 1)
        self.assertIn("platform-tools", problemes[0])

    def test_verrouille(self):
        problemes = self.verifier(faux_adb(fenetre="isKeyguardShowing=true"))
        self.assertTrue(any("verrouillé" in p for p in problemes))

    def test_aucun_non_autorise_ou_plusieurs(self):
        self.assertTrue(
            any(
                "aucun téléphone" in p
                for p in self.verifier(faux_adb(devices=""))
            )
        )
        self.assertTrue(
            any(
                "débogage USB" in p
                for p in self.verifier(faux_adb(devices="S\tunauthorized\n"))
            )
        )
        self.assertTrue(
            any(
                "ANDROID_SERIAL" in p
                for p in self.verifier(
                    faux_adb(devices="A\tdevice\nB\tdevice\n")
                )
            )
        )

    def test_gradlew_absent(self):
        (self.mobile / "android" / "gradlew").unlink()
        self.assertTrue(any("gradlew" in p for p in self.verifier(faux_adb())))

    def test_la_cle_de_l_apk_suit_le_code_non_commite(self):
        def depot(diff):
            return lambda commande, **_: SimpleNamespace(
                stdout=diff if "diff" in commande else "abc\n", returncode=0
            )

        propre = appareil.cle_apk(self.mobile, depot(""))
        self.assertEqual(propre, appareil.cle_apk(self.mobile, depot("")))
        self.assertNotEqual(
            propre, appareil.cle_apk(self.mobile, depot("+ une ligne"))
        )


class TestCommandeAppareil(unittest.TestCase):
    def versions(self):
        return {
            v: odoo.VersionOdoo(
                v, Path(f"/x/odoo{v}.0/odoo/odoo-bin"), Path("/x/py")
            )
            for v in odoo.VERSIONS
        }

    def test_dry_run_annonce_le_telephone_sans_rien_installer(self):
        sortie = []
        with mock.patch.object(
            odoo, "verifier_mobile", return_value=[]
        ), mock.patch.object(
            odoo, "versions_installees", return_value=self.versions()
        ), mock.patch.object(
            odoo, "psql", return_value="1"
        ), mock.patch.object(
            appareil, "verifier_appareil", return_value=[]
        ), mock.patch.object(
            appareil, "lancer"
        ) as lancer, mock.patch(
            "builtins.print",
            lambda *a, **k: sortie.append(" ".join(map(str, a))),
        ), mock.patch(
            "sys.stdout"
        ):
            code = mobile_sync.main(["--dry-run", "--appareil"])
        self.assertEqual(code, mobile_sync.SORTIE_OK)
        self.assertTrue(any(appareil.PAQUET in ligne for ligne in sortie))
        lancer.assert_not_called()

    def test_un_telephone_manquant_sort_en_2(self):
        with mock.patch.object(
            odoo, "verifier_mobile", return_value=[]
        ), mock.patch.object(
            odoo, "versions_installees", return_value=self.versions()
        ), mock.patch.object(
            odoo, "psql", return_value="1"
        ), mock.patch.object(
            appareil,
            "verifier_appareil",
            return_value=["écran du téléphone verrouillé"],
        ), mock.patch(
            "sys.stdout"
        ):
            self.assertEqual(
                mobile_sync.main(["--appareil"]), mobile_sync.SORTIE_PREREQUIS
            )


class TestServeursGardes(unittest.TestCase):
    """Une course gardée laisse ses serveurs tourner : la course qui balaie
    leurs bases les arrête d'abord, et seulement eux."""

    def test_arrete_le_serveur_de_la_base_balayee_seulement(self):
        with tempfile.TemporaryDirectory() as runs:
            course = Path(runs) / "4242_20260101000000"
            course.mkdir()
            serveurs = [
                SimpleNamespace(
                    processus=SimpleNamespace(pid=pid),
                    base=base,
                    url="http://127.0.0.1:1",
                )
                for pid, base in (
                    (11, "mobile_sync_run_a_16"),
                    (12, "mobile_sync_run_a_17"),
                    (13, "mobile_sync_run_a_18"),
                )
            ]
            odoo.noter_gardes(course, serveurs)
            vivants = {
                11: f"odoo-bin -c {course}/odoo16.conf",
                12: f"odoo-bin -c {course}/odoo17.conf",
                13: "un autre programme qui a repris ce pid",
            }
            tues = []

            def tuer(pid, sig):
                tues.append((pid, sig))
                vivants.pop(pid, None)

            arretes = odoo.arreter_gardes(
                {"mobile_sync_run_a_16", "mobile_sync_run_a_18"},
                runs,
                lire=lambda pid: vivants.get(pid, ""),
                tuer=tuer,
            )
            self.assertEqual(arretes, [11])
            self.assertEqual(tues, [(11, odoo.signal.SIGTERM)])
            restants = json.loads((course / odoo.GARDES).read_text())
            self.assertEqual(
                [g["base"] for g in restants], ["mobile_sync_run_a_17"]
            )


class TestDetruire(unittest.TestCase):
    def test_a_blanc_liste_sans_rien_supprimer(self):
        with mock.patch.object(
            odoo, "bases_existantes", return_value={"mobile_sync_tpl_16"}
        ), mock.patch.object(
            odoo, "supprimer_base"
        ) as supprimer, mock.patch.object(
            odoo, "arreter_gardes"
        ) as arreter, mock.patch.object(
            mobile_sync.shutil, "rmtree"
        ) as effacer, mock.patch(
            "sys.stdout"
        ):
            code = mobile_sync.main(["--detruire", "--dry-run"])
        self.assertEqual(code, mobile_sync.SORTIE_OK)
        supprimer.assert_not_called()
        arreter.assert_not_called()
        effacer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
