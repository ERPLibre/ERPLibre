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
import re
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
import mobile_sync_ntfy as harness_ntfy  # noqa: E402
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

    def test_le_smtp_d_un_serveur_ne_mene_nulle_part(self):
        """Un courriel d'Odoo échoue aussitôt au lieu de partir : le SMTP
        vise 127.0.0.1, sur le port donné ou sur un port libre."""
        version = odoo.VersionOdoo(
            18, Path("/x/odoo18.0/odoo/odoo-bin"), Path("/x/py")
        )
        texte = odoo.config_odoo(
            version, "base", 8123, 8124, Path("/tmp/run"), port_smtp=8125
        )
        self.assertIn("smtp_server = 127.0.0.1", texte)
        self.assertIn("smtp_port = 8125", texte)
        defaut = odoo.config_odoo(version, "base", 8123, 8124, Path("/r"))
        port = int(re.search(r"smtp_port = (\d+)", defaut).group(1))
        self.assertGreater(port, 0)
        self.assertNotIn(port, (8123, 8124))

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
        self.assertIn("inbox_user", odoo.POST_INSTALLATION_CHAT)
        self.assertIn(
            "mail.group_mail_notification_type_inbox",
            odoo.POST_INSTALLATION_CHAT,
        )
        self.assertIn("ms chat", odoo.POST_INSTALLATION_CHAT)
        self.assertNotIn("chat_user", odoo.POST_INSTALLATION)
        self.assertEqual(odoo.post_installation(17), odoo.POST_INSTALLATION)
        self.assertIn(odoo.POST_INSTALLATION_CHAT, odoo.post_installation(18))
        compile(odoo.post_installation(18), "post", "exec")

    def test_les_reglages_d_avance_dans_chaque_version(self):
        """Les réglages de chaque utilisateur interne se créent dans le
        commun, après mc_user et avant le commit : la 16 et la 17 les ont
        aussi. La partie du chat crée ceux de chat_user, venu après."""
        commun = odoo.POST_INSTALLATION
        reglages = commun.index(
            'env["res.users.settings"]._find_or_create_for_user(interne)'
        )
        self.assertGreater(reglages, commun.index('"login": "mc_user"'))
        self.assertLess(reglages, commun.rindex("env.cr.commit()"))
        chat = odoo.POST_INSTALLATION_CHAT
        self.assertNotIn("_find_or_create_for_user(interne)", chat)
        self.assertLess(
            chat.index("_find_or_create_for_user(utilisateur)"),
            chat.rindex("env.cr.commit()"),
        )
        for numero in odoo.VERSIONS:
            script = odoo.post_installation(numero)
            self.assertIn("_find_or_create_for_user(interne)", script)
            compile(script, "post", "exec")

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

    def test_harness_api_7(self):
        self.assertEqual(odoo.HARNESS_API, 7)


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


class TestDeuxPasses(unittest.TestCase):
    """Les fichiers *.serial.test.ts (un réglage de tout le serveur) ne
    tournent pas côte à côte avec les autres : une seconde passe les joue
    un à la fois, et le bilan fusionne les deux passes."""

    def setUp(self):
        self.repertoire = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.repertoire))

    def test_la_seconde_passe_joue_les_fichiers_serie_un_a_la_fois(self):
        (premiere, rapport_1), (seconde, rapport_2) = (
            mobile_sync.commandes_vitest(self.repertoire, "chat")
        )
        self.assertEqual(premiere[:3], ["npx", "vitest", "run"])
        self.assertIn("--exclude", premiere)
        self.assertEqual(
            premiere[premiere.index("--exclude") + 1], "**/*.serial.test.ts"
        )
        self.assertNotIn("--no-file-parallelism", premiere)
        self.assertEqual(
            seconde[:4], ["npx", "vitest", "run", ".serial.test."]
        )
        self.assertIn("--no-file-parallelism", seconde)
        self.assertNotIn("--exclude", seconde)
        for commande, rapport in ((premiere, rapport_1), (seconde, rapport_2)):
            self.assertEqual(
                commande[commande.index("--dir") + 1],
                str(mobile_sync.SCENARIOS),
            )
            self.assertEqual(commande[commande.index("-t") + 1], "chat")
            self.assertIn(f"--outputFile.json={rapport}", commande)
        self.assertNotEqual(rapport_1, rapport_2)
        sans_filtre = mobile_sync.commandes_vitest(self.repertoire)
        self.assertTrue(all("-t" not in c for c, _ in sans_filtre))

    def jouer(self, passes, versions=(16, 18)):
        """jouer_vitest dont chaque passe écrit le rapport donné (une liste
        de noms de tests, None : aucun rapport) ; rend aussi les commandes
        lancées."""
        lancees = []
        contenus = iter(passes)

        def executer(commande, **_):
            lancees.append(commande)
            noms = next(contenus)
            if noms is None:
                return
            sortie = next(
                c.split("=", 1)[1]
                for c in commande
                if c.startswith("--outputFile.json=")
            )
            Path(sortie).write_text(
                json.dumps(
                    {
                        "numTotalTests": len(noms),
                        "numFailedTests": 0,
                        "numFailedTestSuites": 0,
                        "testResults": [
                            {
                                "assertionResults": [
                                    {"fullName": n} for n in noms
                                ]
                            }
                        ],
                    }
                )
            )

        bilan = mobile_sync.jouer_vitest(
            self.repertoire,
            self.repertoire / "targets.json",
            "",
            list(versions),
            executer=executer,
        )
        return bilan, lancees

    def test_le_bilan_fusionne_les_deux_passes(self):
        bilan, lancees = self.jouer(
            [["Odoo 16 — a x"], ["Odoo 18 — limite x"]]
        )
        self.assertEqual(len(lancees), 2)
        self.assertEqual(
            bilan, (mobile_sync.SORTIE_OK, "2 tests, tous passés")
        )

    def test_zero_test_sur_les_deux_passes_echoue(self):
        bilan, _ = self.jouer([[], []])
        self.assertEqual(
            bilan, (mobile_sync.SORTIE_TESTS, "aucun test n'a tourné")
        )
        sans_18, _ = self.jouer([["Odoo 16 — a x"], []])
        self.assertEqual(
            sans_18, (mobile_sync.SORTIE_TESTS, "aucun test pour Odoo 18")
        )

    def test_une_passe_sans_rapport_echoue(self):
        bilan, _ = self.jouer([["Odoo 16 — a x", "Odoo 18 — a x"], None])
        self.assertEqual(bilan[0], mobile_sync.SORTIE_TESTS)
        self.assertIn("vitest.serial.json", bilan[1])


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


def faux_adb(
    devices="SERIE\tdevice\n",
    fenetre="isKeyguardShowing=false",
    paquets=("",),
):
    """Un faux subprocess.run qui répond à adb devices, dumpsys window et
    dumpsys package (les sorties de paquets l'une après l'autre, la
    dernière ensuite)."""
    restants = list(paquets)

    def executer(commande, **_):
        sortie = ""
        if commande[:2] == ["adb", "devices"]:
            sortie = "List of devices attached\n" + devices
        elif "dumpsys" in commande and "package" in commande:
            sortie = restants.pop(0) if len(restants) > 1 else restants[0]
        elif "dumpsys" in commande:
            sortie = fenetre
        return SimpleNamespace(stdout=sortie, stderr="", returncode=0)

    return executer


def dumpsys_paquet(maj="2026-01-02 03:04:05", autre=None):
    """Une sortie de dumpsys package : la section de l'app de l'utilisateur,
    sa lastUpdateTime (None : absente), puis une autre section qui porte
    la sienne."""
    lignes = [
        "Packages:",
        f"  Package [{appareil.APP_PERSO}] (abc123):",
        "    firstInstallTime=2026-01-01 00:00:00",
    ]
    if maj:
        lignes.append(f"    lastUpdateTime={maj}")
    if autre:
        lignes += [
            "  Package [org.exemple.autre] (def456):",
            f"    lastUpdateTime={autre}",
        ]
    return "\n".join(lignes) + "\n"


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


class TestAppPerso(unittest.TestCase):
    """L'app de l'utilisateur est relevée avant et après les scénarios : une
    date changée ou illisible fait échouer la course."""

    def test_lit_la_date_de_sa_seule_section(self):
        self.assertEqual(
            appareil.maj_app_perso(
                faux_adb(paquets=[dumpsys_paquet(autre="2030-09-09 09:09:09")])
            ),
            "2026-01-02 03:04:05",
        )

    def test_absente_rend_none(self):
        self.assertIsNone(
            appareil.maj_app_perso(faux_adb(paquets=["Queries:\n"]))
        )

    def test_presente_sans_date_leve(self):
        with self.assertRaises(RuntimeError):
            appareil.maj_app_perso(
                faux_adb(
                    paquets=[dumpsys_paquet(maj=None, autre="2030-09-09")]
                )
            )

    def lancer(self, paquets):
        journal = []
        with mock.patch.object(appareil, "SCENARIOS", ()), mock.patch.object(
            appareil, "construire_apk", return_value=Path("x.apk")
        ), mock.patch.object(appareil, "Appareil"):
            bilan = appareil.lancer(
                [{"version": 18, "url": "http://127.0.0.1:8018"}],
                "/x",
                executer=faux_adb(paquets=paquets),
                journal=journal.append,
            )
        return bilan, journal

    def test_inchangee_ne_compte_rien(self):
        self.assertEqual(self.lancer([dumpsys_paquet()])[0], (0, 0))

    def test_changee_compte_un_echec(self):
        bilan, journal = self.lancer(
            [dumpsys_paquet(), dumpsys_paquet(maj="2026-05-05 05:05:05")]
        )
        self.assertEqual(bilan, (0, 1))
        self.assertTrue(any(appareil.APP_PERSO in ligne for ligne in journal))

    def test_illisible_apres_compte_un_echec(self):
        bilan, _ = self.lancer([dumpsys_paquet(), dumpsys_paquet(maj=None)])
        self.assertEqual(bilan, (0, 1))

    def test_illisible_avant_arrete_tout(self):
        with mock.patch.object(appareil, "construire_apk") as construire:
            with self.assertRaises(RuntimeError):
                appareil.lancer(
                    [],
                    "/x",
                    executer=faux_adb(paquets=[dumpsys_paquet(maj=None)]),
                )
        construire.assert_not_called()


def volet_xml(nous=True):
    """Un relevé uiautomator du volet, inventé : la notification d'une
    autre app d'abord, dépliée, avec son « Répondre » et son champ de
    réponse ouvert ; puis, quand nous est vrai, celle de l'app de test,
    avec les siens. Le cadre d'une rangée est à SystemUI, son contenu à
    l'app qui l'a postée, le champ de réponse et son envoi à SystemUI."""
    ui = "com.android.systemui"
    autre = "org.exemple.messagerie"

    def rangee(paquet, haut, textes):
        lignes = "".join(
            f'<node text="{t}" package="{paquet}" class="android.widget.TextView"'
            f' clickable="false" focused="false" enabled="true"'
            f' content-desc="" resource-id=""'
            f' bounds="[0,{haut + 10 * i}][800,{haut + 10 * i + 10}]"/>'
            for i, t in enumerate(textes)
        )
        return (
            f'<node package="{ui}" class="android.widget.FrameLayout"'
            f' text="" content-desc="" resource-id="" clickable="true"'
            f' focused="false" enabled="true" bounds="[0,{haut}][1000,{haut + 300}]">'
            f'<node package="{paquet}" class="android.widget.LinearLayout"'
            f' text="" content-desc="" resource-id="" clickable="false"'
            f' focused="false" enabled="true" bounds="[0,{haut}][1000,{haut + 200}]">'
            f"{lignes}"
            f'<node text="Répondre" package="{paquet}" class="android.widget.Button"'
            f' content-desc="" resource-id="" clickable="true" focused="false"'
            f' enabled="true" bounds="[0,{haut + 100}][400,{haut + 200}]"/>'
            "</node>"
            f'<node text="" package="{ui}" class="android.widget.EditText"'
            f' content-desc="" resource-id="" clickable="true" focused="true"'
            f' enabled="true" bounds="[0,{haut + 200}][900,{haut + 300}]"/>'
            f'<node text="" package="{ui}" class="android.widget.ImageButton"'
            f' content-desc="Envoyer" resource-id="{appareil.ENVOI_REPONSE}"'
            f' clickable="true" focused="false" enabled="true"'
            f' bounds="[900,{haut + 200}][1000,{haut + 300}]"/>'
            "</node>"
        )

    contenu = rangee(autre, 0, ["Alice Martin", "On se voit demain ?"])
    if nous:
        contenu += rangee(
            appareil.PAQUET, 1000, ["MS Chat", "ms-test-message-attendu"]
        )
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        f'<hierarchy rotation="0"><node package="com.android.systemui"'
        ' class="android.widget.FrameLayout" text="" content-desc=""'
        ' resource-id="" clickable="false" focused="false" enabled="true"'
        f' bounds="[0,0][1000,2000]">{contenu}</node></hierarchy>'
    )


def faux_volet(xml):
    """Un faux subprocess.run qui rend xml au cat du relevé et note les
    touchers (input tap x y) et les textes tapés (input text)."""
    touchers = []
    textes = []

    def executer(commande, **_):
        sortie = ""
        if commande[-2:] == ["cat", appareil.CONTENU_UI]:
            sortie = xml
        elif commande[2:4] == ["input", "tap"]:
            touchers.append((int(commande[4]), int(commande[5])))
        elif commande[2:4] == ["input", "text"]:
            textes.append(commande[4])
        return SimpleNamespace(stdout=sortie, stderr="", returncode=0)

    return executer, touchers, textes


class TestVoletPortee(unittest.TestCase):
    """Les touchers du volet ne quittent jamais la notification de l'app
    de test : le « Répondre », le champ et l'envoi d'une autre app,
    même dépliée au-dessus, ne sont jamais touchés."""

    def setUp(self):
        attente = mock.patch.object(appareil.time, "sleep")
        attente.start()
        self.addCleanup(attente.stop)

    def ctx(self, executer):
        return SimpleNamespace(appareil=SimpleNamespace(executer=executer))

    def test_le_bouton_est_celui_de_notre_notification(self):
        executer, touchers, _ = faux_volet(volet_xml())
        appareil.toucher_action(
            self.ctx(executer), "Répondre", "ms-test-message-attendu"
        )
        self.assertEqual(touchers, [(200, 1150)])

    def test_le_champ_et_l_envoi_sont_ceux_de_notre_notification(self):
        executer, touchers, textes = faux_volet(volet_xml())
        appareil.repondre_du_volet(
            self.ctx(executer), "motsinventes", "ms-test-message-attendu"
        )
        self.assertEqual(touchers, [(200, 1150), (450, 1250), (950, 1250)])
        self.assertEqual(textes, ["motsinventes"])

    def test_sans_notre_notification_rien_n_est_touche(self):
        executer, touchers, textes = faux_volet(volet_xml(nous=False))
        with self.assertRaises(TimeoutError):
            appareil.repondre_du_volet(
                self.ctx(executer),
                "motsinventes",
                "ms-test-message-attendu",
                delai=0,
            )
        self.assertEqual(touchers, [])
        self.assertEqual(textes, [])

    def test_un_texte_d_une_autre_app_ne_designe_pas_notre_rangee(self):
        executer, touchers, _ = faux_volet(volet_xml(nous=False))
        with self.assertRaises(TimeoutError):
            appareil.toucher_action(
                self.ctx(executer), "Répondre", "On se voit demain ?", delai=0
            )
        self.assertEqual(touchers, [])


class TestScenariosAppareil(unittest.TestCase):
    """Le clavardage ne se joue que sur la 18, seule version que le chat de
    l'app connaît ; les autres versions le sautent sans le compter."""

    def test_api_du_hook_8(self):
        self.assertEqual(appareil.DEVICE_HOOK_API, 8)

    def test_clavardage_sur_la_18_seulement(self):
        for version in (16, 17):
            self.assertNotIn(
                "clavardage",
                [nom for nom, _ in appareil.scenarios_de(version)],
            )
        for scenario in (
            ("clavardage", appareil.scenario_clavardage),
            ("groupe créé du téléphone", appareil.scenario_groupe),
            ("pièces jointes du clavardage", appareil.scenario_pieces_jointes),
            ("actions du clavardage", appareil.scenario_actions_clavardage),
            (
                "recherche et boîte du clavardage",
                appareil.scenario_recherche_boite,
            ),
            (
                "notifications du clavardage, app fermée",
                appareil.scenario_notifications,
            ),
            (
                "actions du clavardage, app tuée",
                appareil.scenario_actions_notifications,
            ),
        ):
            self.assertIn(scenario, appareil.scenarios_de(18))
            for version in (16, 17):
                self.assertNotIn(scenario, appareil.scenarios_de(version))
        self.assertEqual(len(appareil.scenarios_de(16)), 4)

    def test_lancer_saute_sans_compter(self):
        joues = []
        scenarios = (
            (
                "note",
                lambda ctx: joues.append(("note", ctx.version)),
                (16, 18),
            ),
            ("chat", lambda ctx: joues.append(("chat", ctx.version)), (18,)),
        )
        cibles = [
            {
                "version": v,
                "url": f"http://127.0.0.1:{8000 + v}",
                "database": f"base_{v}",
                "admin": {"login": "admin", "password": "admin"},
            }
            for v in (16, 18)
        ]
        with mock.patch.object(
            appareil, "SCENARIOS", scenarios
        ), mock.patch.object(
            appareil, "construire_apk", return_value=Path("x.apk")
        ), mock.patch.object(
            appareil, "Appareil"
        ), mock.patch.object(
            appareil, "Odoo"
        ):
            total, echecs = appareil.lancer(
                cibles,
                "/x",
                executer=faux_adb(paquets=[dumpsys_paquet()]),
                journal=lambda _: 0,
            )
        self.assertEqual((total, echecs), (3, 0))
        self.assertEqual(joues, [("note", 16), ("note", 18), ("chat", 18)])


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


class TestNtfy(unittest.TestCase):
    """Le ntfy de la course est le sien : sur 127.0.0.1, un port libre, sa
    configuration et ses fichiers sous le répertoire de la course, et
    chaque appel de la CLI porte --config. Celui de l'utilisateur (port
    8080, /etc/ntfy, /var/lib/ntfy) n'est jamais nommé."""

    def setUp(self):
        self.repertoire = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.repertoire))

    def demarrer(self):
        """demarrer_ntfy sur de faux processus : rend le ntfy et les
        commandes lancées (Popen, puis subprocess.run)."""
        lancees = []

        def lancer(commande, **_):
            lancees.append(("serve", commande))
            return SimpleNamespace(pid=4321, poll=lambda: None)

        def executer(commande, **_):
            lancees.append(("script", commande))
            return SimpleNamespace(
                stdout="token tk_inventeinventeinvente created for user"
                " erm_course, never expires\n",
                returncode=0,
            )

        ntfy = harness_ntfy.demarrer_ntfy(
            self.repertoire,
            lancer=lancer,
            executer=executer,
            sain=lambda url: True,
        )
        return ntfy, lancees

    def test_ntfy_config_is_local_and_temporary(self):
        ntfy, _ = self.demarrer()
        texte = ntfy.config.read_text()
        self.assertEqual(ntfy.config.parent, self.repertoire / "ntfy")
        cles = harness_ntfy.ntfy_mobile.read_yml_keys(texte)
        self.assertEqual(cles["listen-http"], f"127.0.0.1:{ntfy.port}")
        self.assertNotEqual(ntfy.port, 8080)
        self.assertEqual(ntfy.url, f"http://127.0.0.1:{ntfy.port}")
        self.assertEqual(cles["base-url"], ntfy.url)
        self.assertEqual(cles["auth-default-access"], "deny-all")
        self.assertEqual(cles["cache-duration"], "12h")
        self.assertEqual(
            cles["visitor-request-limit-exempt-hosts"], "127.0.0.1"
        )
        for cle in ("cache-file", "auth-file"):
            self.assertTrue(
                Path(cles[cle]).is_relative_to(self.repertoire / "ntfy"), cle
            )
        for interdit in ("/etc/ntfy", "/var/lib/ntfy", ":8080"):
            self.assertNotIn(interdit, texte)
        self.assertEqual(harness_ntfy.ntfy_mobile.config_problems(cles), [])

    def test_every_ntfy_call_has_config(self):
        ntfy, lancees = self.demarrer()
        sortes = [sorte for sorte, _ in lancees]
        self.assertEqual(sortes, ["serve", "script", "script"])
        serve = lancees[0][1]
        self.assertEqual(serve[:2], ["ntfy", "serve"])
        self.assertEqual(serve[serve.index("--config") + 1], str(ntfy.config))
        for _, script in lancees[1:]:
            self.assertEqual(script[:2], ["sh", "-c"])
            appels = [
                ligne
                for ligne in script[2].splitlines()
                if re.search(r"\bntfy\b", ligne)
            ]
            self.assertTrue(appels)
            for ligne in appels:
                self.assertIn(f"--config {ntfy.config}", ligne)
        self.assertIn(f"{ntfy.prefix}*", lancees[1][1][2])
        self.assertIn(f"{ntfy.autre.prefix}*", lancees[2][1][2])
        self.assertIn(ntfy.autre.prefix, ntfy.autre.link)
        self.assertEqual(ntfy.token, "tk_inventeinventeinvente")
        self.assertRegex(ntfy.prefix, r"^up[a-z0-9]{8}$")
        self.assertIn(f"prefix={ntfy.prefix}", ntfy.link)
        self.assertIn("cache=43200", ntfy.link)
        self.assertIn("odoo=http%3A%2F%2F127.0.0.1%3A", ntfy.link)

    def test_un_jeton_absent_arrete_le_ntfy(self):
        arretes = []

        def lancer(commande, **_):
            return SimpleNamespace(pid=4321, poll=lambda: None)

        with mock.patch.object(
            harness_ntfy, "arreter_ntfy", lambda n: arretes.append(n)
        ), self.assertRaises(RuntimeError):
            harness_ntfy.demarrer_ntfy(
                self.repertoire,
                lancer=lancer,
                executer=lambda *a, **k: SimpleNamespace(
                    stdout="", returncode=1
                ),
                sain=lambda url: True,
            )
        self.assertEqual(len(arretes), 1)

    def test_ntfy_calls_drop_the_ntfy_variables(self):
        """NTFY_* passe avant --config dans la CLI : un shell qui exporte
        NTFY_AUTH_FILE ferait écrire l'accès de la course ailleurs."""
        envs = []

        def lancer(commande, **kw):
            envs.append(kw.get("env"))
            return SimpleNamespace(pid=4321, poll=lambda: None)

        def executer(commande, **kw):
            envs.append(kw.get("env"))
            return SimpleNamespace(
                stdout="token tk_inventeinventeinvente created\n",
                returncode=0,
            )

        exporte = {"NTFY_AUTH_FILE": "/tmp/autre.db", "NTFY_TOKEN": "tk_x"}
        with mock.patch.dict(os.environ, exporte):
            harness_ntfy.demarrer_ntfy(
                self.repertoire,
                lancer=lancer,
                executer=executer,
                sain=lambda url: True,
            )
        self.assertEqual(len(envs), 3)
        for env in envs:
            self.assertIsNotNone(env)
            self.assertFalse([k for k in env if k.startswith("NTFY_")])
            self.assertEqual(env.get("PATH"), os.environ.get("PATH"))

    def test_une_interruption_au_demarrage_arrete_le_ntfy(self):
        """Ctrl-C (ou SIGTERM, que la course change en KeyboardInterrupt)
        pendant l'attente ou la création des accès : le ntfy, dans sa propre
        session et pas encore noté, est arrêté."""

        def lancer(commande, **_):
            return SimpleNamespace(pid=4321, poll=lambda: None)

        def interrompu(*_a, **_k):
            raise KeyboardInterrupt

        for sain, executer in (
            (interrompu, None),
            (lambda url: True, interrompu),
        ):
            arretes = []
            options = {"executer": executer} if executer else {}
            with mock.patch.object(
                harness_ntfy, "arreter_ntfy", lambda n: arretes.append(n)
            ), self.assertRaises(KeyboardInterrupt):
                harness_ntfy.demarrer_ntfy(
                    self.repertoire, lancer=lancer, sain=sain, **options
                )
            self.assertEqual(len(arretes), 1)

    def test_ntfy_absent_skips_with_a_plan_line(self):
        self.assertFalse(harness_ntfy.ntfy_disponible(lambda nom: None))
        self.assertTrue(
            harness_ntfy.ntfy_disponible(lambda nom: "/usr/bin/ntfy")
        )
        args = mobile_sync.parser().parse_args([])
        self.assertIn(
            "  ntfy : absent, tests de notification sautés",
            mobile_sync.plan([18], args, ntfy=False).splitlines(),
        )
        self.assertNotIn("ntfy", mobile_sync.plan([16], args, ntfy=False))
        serveurs = [
            SimpleNamespace(
                version=v,
                url=f"http://127.0.0.1:{v}",
                base=b,
                journal=self.repertoire / f"odoo{v}.log",
            )
            for v, b in ((17, "b17"), (18, "b18"))
        ]
        sans = mobile_sync.cibles(serveurs, None)
        self.assertTrue(all("ntfy" not in c for c in sans))
        self.assertEqual(
            [c["log"] for c in sans],
            [str(self.repertoire / f"odoo{v}.log") for v in (17, 18)],
        )
        ntfy = SimpleNamespace(
            url="http://127.0.0.1:40001",
            token="tk_inventeinventeinvente",
            prefix="upab12cd34",
            link="erplibre-ntfy:setup?v=1",
            config=self.repertoire / "ntfy" / "server.yml",
            autre=SimpleNamespace(
                token="tk_autreautreautre",
                prefix="upab12cd35",
                link="erplibre-ntfy:setup?v=1&prefix=upab12cd35",
            ),
        )
        avec = mobile_sync.cibles(serveurs, ntfy)
        self.assertNotIn("ntfy", avec[0])
        self.assertEqual(
            avec[1]["ntfy"],
            {
                "url": ntfy.url,
                "token": ntfy.token,
                "prefix": ntfy.prefix,
                "link": ntfy.link,
                "config": str(ntfy.config),
                "other": {
                    "token": "tk_autreautreautre",
                    "prefix": "upab12cd35",
                    "link": "erplibre-ntfy:setup?v=1&prefix=upab12cd35",
                },
            },
        )

    def test_garde_avec_les_serveurs_et_arrete_par_le_balayage(self):
        course = self.repertoire / "4242_20260101000000"
        course.mkdir()
        serveurs = [
            SimpleNamespace(
                processus=SimpleNamespace(pid=13),
                base="mobile_sync_run_a_18",
                url="http://127.0.0.1:1",
            )
        ]
        ntfy = SimpleNamespace(
            processus=SimpleNamespace(pid=14), url="http://127.0.0.1:2"
        )
        odoo.noter_gardes(course, serveurs, ntfy)
        vivants = {
            13: f"odoo-bin -c {course}/odoo18.conf",
            14: f"ntfy serve --config {course}/ntfy/server.yml",
        }
        tues = []

        def tuer(pid, sig):
            tues.append(pid)
            vivants.pop(pid, None)

        arretes = odoo.arreter_gardes(
            {"mobile_sync_run_a_18"},
            self.repertoire,
            lire=lambda pid: vivants.get(pid, ""),
            tuer=tuer,
        )
        self.assertEqual(sorted(arretes), [13, 14])


class TestAppareilNotifications(unittest.TestCase):
    """Le scénario des notifications accorde la permission et l'exemption
    de batterie à l'app de test seule ; rendre() les défait, et renvoie
    le port du ntfy de la course comme ceux des serveurs."""

    sdk = "33"

    def test_rendre_defait_permission_et_exemption(self):
        commandes = []

        def executer(commande, **_):
            commandes.append(commande[1:])
            sortie = ""
            if "whitelist" in commande and len(commande) == 5:
                sortie = "system,com.android.shell,1000\n"
            elif "getprop" in commande:
                sortie = self.sdk + "\n"
            return SimpleNamespace(stdout=sortie, stderr="", returncode=0)

        telephone = appareil.Appareil([8018, 40001], executer)
        telephone.autoriser_notifications()
        telephone.exempter_batterie()
        telephone.rendre()
        attendues = [
            ["shell", "pm", "grant", appareil.PAQUET, appareil.NOTIFIER],
            [
                "shell",
                "dumpsys",
                "deviceidle",
                "whitelist",
                f"+{appareil.PAQUET}",
            ],
            ["shell", "pm", "revoke", appareil.PAQUET, appareil.NOTIFIER],
            [
                "shell",
                "dumpsys",
                "deviceidle",
                "whitelist",
                f"-{appareil.PAQUET}",
            ],
        ]
        for attendue in attendues:
            self.assertIn(attendue, commandes)
        self.assertLess(
            commandes.index(attendues[0]), commandes.index(attendues[2])
        )
        for commande in commandes:
            self.assertNotIn(appareil.APP_PERSO, commande)

    def test_avant_android_13_rien_n_est_accorde(self):
        commandes = []

        def executer(commande, **_):
            commandes.append(commande[1:])
            sortie = "30\n" if "getprop" in commande else ""
            return SimpleNamespace(stdout=sortie, stderr="", returncode=0)

        telephone = appareil.Appareil([8018], executer)
        telephone.autoriser_notifications()
        telephone.rendre()
        self.assertFalse(any("grant" in c or "revoke" in c for c in commandes))

    def test_une_exemption_deja_la_reste(self):
        commandes = []

        def executer(commande, **_):
            commandes.append(commande[1:])
            sortie = ""
            if "whitelist" in commande and len(commande) == 5:
                sortie = f"user,{appareil.PAQUET},10234\n"
            return SimpleNamespace(stdout=sortie, stderr="", returncode=0)

        telephone = appareil.Appareil([8018], executer)
        telephone.exempter_batterie()
        telephone.rendre()
        self.assertNotIn(
            [
                "shell",
                "dumpsys",
                "deviceidle",
                "whitelist",
                f"-{appareil.PAQUET}",
            ],
            commandes,
        )

    def test_l_ecran_reste_allume_des_avant_la_construction(self):
        ordre = []
        telephone = mock.MagicMock()
        telephone.garder_allume.side_effect = lambda: ordre.append("allume")
        telephone.rendre.side_effect = lambda: ordre.append("rendre")
        with mock.patch.object(appareil, "SCENARIOS", ()), mock.patch.object(
            appareil,
            "construire_apk",
            side_effect=lambda **_: ordre.append("apk") or Path("x.apk"),
        ), mock.patch.object(appareil, "Appareil", return_value=telephone):
            appareil.lancer(
                [{"version": 18, "url": "http://127.0.0.1:8018"}],
                "/x",
                executer=faux_adb(paquets=[dumpsys_paquet()]),
                journal=lambda _: 0,
            )
        self.assertEqual(ordre, ["allume", "apk", "rendre"])

    def test_le_port_du_ntfy_est_renvoye(self):
        cibles = [
            {"version": 18, "url": "http://127.0.0.1:8018"},
            {
                "version": 18,
                "url": "http://127.0.0.1:8019",
                "ntfy": {"url": "http://127.0.0.1:40001"},
            },
        ]
        self.assertEqual(appareil.ports_de(cibles), [8018, 8019, 40001])


if __name__ == "__main__":
    unittest.main()
