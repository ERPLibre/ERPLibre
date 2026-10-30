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

import ast
import hashlib
import inspect
import json
import os
import re
import shlex
import sys
import tempfile
import textwrap
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

    def test_harness_api_8(self):
        self.assertEqual(odoo.HARNESS_API, 8)


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
    installes="",
):
    """Un faux subprocess.run qui répond à adb devices, dumpsys window,
    dumpsys package (les sorties de paquets l'une après l'autre, la
    dernière ensuite) et pm list packages (installes)."""
    restants = list(paquets)

    def executer(commande, **_):
        sortie = ""
        if commande[:2] == ["adb", "devices"]:
            sortie = "List of devices attached\n" + devices
        elif commande[2:4] == ["pm", "list"]:
            sortie = installes
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

    def verifier(self, executer, which=None, batterie_reelle=False):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANDROID_SERIAL", None)
            return appareil.verifier_appareil(
                self.mobile,
                executer,
                which or self.adb_present,
                batterie_reelle=batterie_reelle,
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

    def test_batterie_reelle_exige_un_telephone_sans_l_app_perso(self):
        perso = faux_adb(
            installes=f"package:{appareil.APP_PERSO}\n"
            f"package:{appareil.PAQUET}\n"
        )
        self.assertEqual(self.verifier(perso), [])
        problemes = self.verifier(perso, batterie_reelle=True)
        self.assertTrue(any(appareil.APP_PERSO in p for p in problemes))
        vide = faux_adb(installes=f"package:{appareil.PAQUET}\n")
        self.assertEqual(self.verifier(vide, batterie_reelle=True), [])

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


UI = "com.android.systemui"
# Le nom d'une autre app au haut de sa notification, inventé
AUTRE = "Messagerie Exemple"


def noeud(paquet, haut, bas, enfants="", **attributs):
    """Un nœud de relevé uiautomator, inventé : paquet, bornes
    [0,haut][1000,bas] (x de attributs["x"] à 1000 sinon), enfants."""
    x1, x2 = attributs.pop("x", (0, 1000))
    valeurs = {
        "text": "",
        "class": "android.widget.FrameLayout",
        "content-desc": "",
        "resource-id": "",
        "clickable": "false",
        "focused": "false",
        "enabled": "true",
    }
    valeurs.update({k.replace("_", "-"): v for k, v in attributs.items()})
    texte = " ".join(f'{k}="{v}"' for k, v in valeurs.items())
    return (
        f'<node package="{paquet}" {texte}'
        f' bounds="[{x1},{haut}][{x2},{bas}]">{enfants}</node>'
    )


def en_tete(appli, haut):
    """L'en-tête d'une notification (android:id/notification_header) et
    le nom d'appli qu'il affiche (android:id/app_name_text)."""
    return noeud(
        UI,
        haut,
        haut + 10,
        noeud(
            UI,
            haut,
            haut + 10,
            text=appli,
            resource_id=appareil.NOM_APPLI,
            x=(100, 400),
        ),
        resource_id="android:id/notification_header",
        **{"class": "android.view.ViewGroup"},
    )


def rangee_xml(
    appli, haut, textes, reponse=None, bouton=True, focus=True, entete=True
):
    """La rangée d'une notification comme Android 11 la relève, chaque
    nœud à SystemUI : un FrameLayout sans id, enfant du conteneur du
    volet, son cadre expanded puis status_bar_latest_event_content ; dedans
    l'en-tête au nom appli (sans lui quand entete est faux : un enfant de
    groupe), les textes, « Répondre » quand bouton, puis, quand reponse
    n'est pas None, le champ de réponse (texte reponse, focalisé quand
    focus) et son envoi."""
    contenu = "".join(
        noeud(UI, haut + 10 * i, haut + 10 * i + 10, text=t)
        for i, t in enumerate(textes)
    )
    if entete:
        contenu += en_tete(appli, haut + 50)
    if bouton:
        contenu += noeud(
            UI,
            haut + 100,
            haut + 200,
            text="Répondre",
            clickable="true",
            x=(0, 400),
            **{"class": "android.widget.Button"},
        )
    champ = ""
    if reponse is not None:
        champ = noeud(
            UI,
            haut + 200,
            haut + 300,
            text=reponse,
            **{"class": "android.widget.EditText"},
            clickable="true",
            focused="true" if focus else "false",
            x=(0, 900),
        ) + noeud(
            UI,
            haut + 200,
            haut + 300,
            resource_id=appareil.ENVOI_REPONSE,
            clickable="true",
            x=(900, 1000),
        )
    cadre = noeud(
        UI,
        haut,
        haut + 300,
        noeud(
            UI,
            haut,
            haut + 200,
            contenu,
            resource_id="android:id/status_bar_latest_event_content",
        )
        + champ,
        resource_id="com.android.systemui:id/expanded",
    )
    return noeud(UI, haut, haut + 300, cadre, clickable="true")


def groupe_xml(appli, haut, *enfants):
    """Un groupe de notifications d'une app : sa rangée, enfant du
    conteneur du volet, porte le conteneur notification_children_container,
    qui porte l'en-tête au nom appli puis les rangées enfants (rangee_xml
    sans en-tête)."""
    return noeud(
        UI,
        haut,
        2900,
        noeud(
            UI,
            haut,
            2900,
            en_tete(appli, haut + 5) + "".join(enfants),
            resource_id=appareil.GROUPE_VOLET,
            **{"class": "android.view.ViewGroup"},
        ),
        clickable="true",
    )


def volet(*rangees):
    """Un relevé du volet : les rangées dans son conteneur
    (notification_stack_scroller), sous la racine de SystemUI."""
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        '<hierarchy rotation="0">'
        + noeud(
            UI,
            0,
            3000,
            noeud(
                UI,
                0,
                3000,
                "".join(rangees),
                resource_id=appareil.CONTENEUR_VOLET,
                **{"class": "android.widget.ScrollView"},
            ),
        )
        + "</hierarchy>"
    )


MESSAGE = "ms-test-message-attendu"


def notre(haut=1000, reponse=None, textes=("MS Chat", MESSAGE), **options):
    return rangee_xml(
        appareil.ENTETE_TEST, haut, list(textes), reponse, **options
    )


def faux_volet(releve):
    """Un faux subprocess.run : releve(textes) donne le XML du relevé
    selon les textes déjà tapés ; note les touchers (input tap x y) et les
    textes tapés (input text)."""
    touchers = []
    textes = []

    def executer(commande, **_):
        sortie = ""
        if commande[-2:] == ["cat", appareil.CONTENU_UI]:
            sortie = releve(textes)
        elif commande[2:4] == ["input", "tap"]:
            touchers.append((int(commande[4]), int(commande[5])))
        elif commande[2:4] == ["input", "text"]:
            textes.append(commande[4])
        return SimpleNamespace(stdout=sortie, stderr="", returncode=0)

    return executer, touchers, textes


def avec_champ(*avant, apres=()):
    """Le relevé avec notre rangée, son champ ouvert portant le dernier
    texte tapé, après les rangées avant et avant les rangées apres."""
    return lambda tapes: volet(
        *avant, notre(reponse=tapes[-1] if tapes else ""), *apres
    )


class TestVoletPortee(unittest.TestCase):
    """Les touchers du volet ne quittent jamais la rangée de la
    notification attendue de l'app de test (expandableNotificationRow) :
    le « Répondre », le champ et l'envoi d'une autre app, ou d'une autre
    notification de l'app, ne sont jamais touchés, et rien n'est tapé
    hors de notre champ."""

    def setUp(self):
        attente = mock.patch.object(appareil.time, "sleep")
        attente.start()
        self.addCleanup(attente.stop)

    def ctx(self, executer):
        return SimpleNamespace(appareil=SimpleNamespace(executer=executer))

    def test_le_bouton_est_celui_de_notre_notification(self):
        executer, touchers, _ = faux_volet(
            lambda _: volet(
                rangee_xml(AUTRE, 0, ["Alice Martin"], ""), notre()
            )
        )
        appareil.toucher_action(self.ctx(executer), "Répondre", MESSAGE)
        self.assertEqual(touchers, [(200, 1150)])

    def test_le_champ_et_l_envoi_sont_ceux_de_notre_notification(self):
        executer, touchers, textes = faux_volet(
            avec_champ(rangee_xml(AUTRE, 0, ["Alice Martin"], "", focus=False))
        )
        appareil.repondre_du_volet(self.ctx(executer), "motsinventes", MESSAGE)
        self.assertEqual(touchers, [(200, 1150), (950, 1250)])
        self.assertEqual(textes, ["motsinventes"])

    def test_un_champ_etranger_sans_contenu_visible_reste_hors_rangee(self):
        # Une rangée d'une autre app coupée par le bord : seuls son champ et
        # son envoi, à SystemUI, se voient au-dessus de la nôtre
        etrangere = noeud(
            UI,
            0,
            300,
            noeud(
                UI,
                200,
                300,
                text="",
                **{"class": "android.widget.EditText"},
                focused="false",
                x=(0, 900),
            )
            + noeud(
                UI,
                200,
                300,
                resource_id=appareil.ENVOI_REPONSE,
                clickable="true",
                x=(900, 1000),
            ),
        )
        executer, touchers, textes = faux_volet(avec_champ(etrangere))
        appareil.repondre_du_volet(self.ctx(executer), "motsinventes", MESSAGE)
        self.assertEqual(touchers, [(200, 1150), (950, 1250)])

    def test_un_volet_decale_avant_le_toucher_n_est_pas_touche(self):
        # Entre le premier relevé et le toucher, une notification d'une autre
        # app s'est posée à la place de la nôtre, descendue de 400
        releves = []

        def releve(_):
            releves.append(None)
            if len(releves) == 1:
                return volet(notre(haut=1000))
            return volet(
                rangee_xml(AUTRE, 1000, ["Alice Martin"], ""), notre(haut=1400)
            )

        executer, touchers, _ = faux_volet(releve)
        appareil.toucher_action(self.ctx(executer), "Répondre", MESSAGE)
        self.assertEqual(touchers, [(200, 1550)])

    def test_un_volet_qui_bouge_a_chaque_releve_n_est_jamais_touche(self):
        releves = []

        def releve(_):
            releves.append(None)
            return volet(notre(haut=1000 + 400 * (len(releves) % 2)))

        executer, touchers, _ = faux_volet(releve)
        with self.assertRaises(TimeoutError):
            appareil.toucher_dans(
                executer,
                "Répondre",
                MESSAGE,
                lambda n: n.get("text") == "Répondre",
                delai=0,
            )
        self.assertGreaterEqual(len(releves), 2)
        self.assertEqual(touchers, [])

    def test_deux_de_nos_notifications_chacune_sa_rangee(self):
        autre_conversation = notre(
            haut=400, textes=("MS Chat", "ms-test-autre")
        )
        executer, touchers, _ = faux_volet(
            lambda _: volet(autre_conversation, notre())
        )
        appareil.toucher_action(self.ctx(executer), "Répondre", MESSAGE)
        self.assertEqual(touchers, [(200, 1150)])

    def test_un_texte_mal_tape_n_est_jamais_envoye(self):
        executer, touchers, textes = faux_volet(
            lambda _: volet(notre(reponse="autrechose"))
        )
        with self.assertRaises(TimeoutError):
            appareil.repondre_du_volet(
                self.ctx(executer), "motsinventes", MESSAGE, delai=0
            )
        self.assertNotIn((950, 1250), touchers)

    def test_sans_notre_notification_rien_n_est_touche(self):
        executer, touchers, textes = faux_volet(
            lambda _: volet(rangee_xml(AUTRE, 0, ["Alice Martin"], ""))
        )
        with self.assertRaises(TimeoutError):
            appareil.repondre_du_volet(
                self.ctx(executer), "motsinventes", MESSAGE, delai=0
            )
        self.assertEqual(touchers, [])
        self.assertEqual(textes, [])

    def test_hors_d_une_rangee_de_notification_rien_n_est_touche(self):
        # Notre contenu relevé hors du conteneur du volet (une autre vue de
        # SystemUI) : il n'est dans aucune rangée
        hors_volet = (
            "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
            '<hierarchy rotation="0">'
            + noeud(
                UI,
                0,
                3000,
                noeud(
                    UI,
                    0,
                    3000,
                    notre(),
                    resource_id="com.android.systemui:id/qs_frame",
                ),
            )
            + "</hierarchy>"
        )
        executer, touchers, _ = faux_volet(lambda _: hors_volet)
        with self.assertRaises(TimeoutError):
            appareil.toucher_action(
                self.ctx(executer), "Répondre", MESSAGE, delai=0
            )
        self.assertEqual(touchers, [])

    def test_un_texte_d_une_autre_app_ne_designe_pas_notre_rangee(self):
        executer, touchers, _ = faux_volet(
            lambda _: volet(rangee_xml(AUTRE, 0, [MESSAGE], ""))
        )
        with self.assertRaises(TimeoutError):
            appareil.toucher_action(
                self.ctx(executer), "Répondre", MESSAGE, delai=0
            )
        self.assertEqual(touchers, [])

    def test_un_second_champ_focalise_hors_rangee_empeche_la_saisie(self):
        ailleurs = noeud(
            UI,
            2500,
            2600,
            **{"class": "android.widget.EditText"},
            focused="true",
        )
        executer, touchers, textes = faux_volet(avec_champ(apres=(ailleurs,)))
        with self.assertRaises(TimeoutError):
            appareil.repondre_du_volet(
                self.ctx(executer), "motsinventes", MESSAGE, delai=0
            )
        self.assertEqual(textes, [])
        self.assertNotIn((950, 1250), touchers)

    def test_des_mots_tapes_ailleurs_nomment_l_app_sans_y_toucher(self):
        def releve(tapes):
            # Notre champ reste vide, les mots arrivent dans le champ de la
            # notification d'une autre app
            ailleurs = rangee_xml(
                AUTRE,
                2000,
                ["Alice Martin"],
                tapes[-1] if tapes else "",
                bouton=False,
                focus=False,
            )
            return volet(notre(reponse=""), ailleurs)

        executer, touchers, _ = faux_volet(releve)
        with self.assertRaises(TimeoutError) as echec:
            appareil.repondre_du_volet(
                self.ctx(executer), "motsinventes", MESSAGE, delai=0
            )
        self.assertIn(AUTRE, str(echec.exception))
        self.assertEqual(touchers, [(200, 1150)])

    def test_deux_de_nos_rangees_portant_la_ligne_ne_designent_rien(self):
        racine = appareil.ET.fromstring(
            volet(notre(haut=400), notre(haut=1000)).split("?>", 1)[1]
        )
        self.assertIsNone(appareil.rangee(racine, MESSAGE))

    def test_titre_et_texte_portant_la_ligne_sont_une_seule_rangee(self):
        racine = appareil.ET.fromstring(
            volet(
                notre(haut=1000, textes=("Nouveau message", "Nouveau message"))
            ).split("?>", 1)[1]
        )
        choisie = appareil.rangee(racine, "Nouveau message")
        self.assertIsNotNone(choisie)
        self.assertEqual(choisie.get("bounds"), "[0,1000][1000,1300]")

    def test_un_enfant_de_notre_groupe_est_notre_rangee(self):
        # Groupée, notre notification n'a pas d'en-tête : celui du groupe
        # dit l'app
        executer, touchers, _ = faux_volet(
            lambda _: volet(
                groupe_xml(
                    appareil.ENTETE_TEST,
                    700,
                    rangee_xml(None, 1000, ["MS Chat", MESSAGE], entete=False),
                )
            )
        )
        appareil.toucher_action(self.ctx(executer), "Répondre", MESSAGE)
        self.assertEqual(touchers, [(200, 1150)])

    def test_un_enfant_du_groupe_d_une_autre_app_n_est_pas_touche(self):
        executer, touchers, _ = faux_volet(
            lambda _: volet(
                groupe_xml(
                    AUTRE,
                    700,
                    rangee_xml(None, 1000, ["MS Chat", MESSAGE], entete=False),
                )
            )
        )
        with self.assertRaises(TimeoutError):
            appareil.toucher_action(
                self.ctx(executer), "Répondre", MESSAGE, delai=0
            )
        self.assertEqual(touchers, [])

    def test_une_autre_app_affichant_le_jeton_laisse_notre_rangee(self):
        # Une autre app reprend le jeton de la course dans sa notification :
        # seule la rangée au nom de l'app de test porte les deux
        executer, touchers, _ = faux_volet(
            lambda _: volet(
                rangee_xml(AUTRE, 0, ["Alice Martin", MESSAGE]), notre()
            )
        )
        appareil.toucher_action(self.ctx(executer), "Répondre", MESSAGE)
        self.assertEqual(touchers, [(200, 1150)])

    def test_le_bouton_d_une_boite_de_dialogue_est_celui_de_l_app(self):
        def bouton(paquet, haut):
            return noeud(
                paquet,
                haut,
                haut + 100,
                text="Supprimer",
                resource_id=appareil.BOUTON_POSITIF,
                clickable="true",
            )

        executer, touchers, _ = faux_volet(
            lambda _: volet(
                bouton("org.exemple.messagerie", 100),
                bouton(appareil.PAQUET, 1500),
            )
        )
        appareil.toucher_dialogue(self.ctx(executer), "Supprimer")
        self.assertEqual(touchers, [(500, 1550)])

    def test_le_bouton_d_une_boite_qui_bouge_est_touche_a_sa_place_stable(
        self,
    ):
        releves = []

        def releve(_):
            releves.append(None)
            haut = 1500 if len(releves) == 1 else 1800
            return volet(
                noeud(
                    appareil.PAQUET,
                    haut,
                    haut + 100,
                    text="Supprimer",
                    resource_id=appareil.BOUTON_POSITIF,
                    clickable="true",
                )
            )

        executer, touchers, _ = faux_volet(releve)
        appareil.toucher_dialogue(self.ctx(executer), "Supprimer")
        self.assertEqual(touchers, [(500, 1850)])

    def test_le_toucher_d_une_notification_vise_la_notre(self):
        executer, touchers, _ = faux_volet(
            lambda _: volet(
                rangee_xml(AUTRE, 0, ["Ouvrez le colis"], bouton=False),
                notre(textes=("Ouvrez l'app pour terminer une action",)),
            )
        )
        appareil.toucher_notification(self.ctx(executer), "Ouvrez l")
        self.assertEqual(touchers, [(500, 1005)])


# Le tag d'une conversation : son configId (url|identifiant|base) porte
# des caractères que le shell du téléphone interprète
TAG = "chat:http://odoo.exemple.test:8069|admin|base_exemple:7"


def dumpsys_notification(
    tag=TAG, textes=(MESSAGE,), actions=("Répondre", "Marquer lu", "👍")
):
    """Une sortie inventée de dumpsys notification --noredact, de la forme
    d'Android 11 : la notification de l'app de test sous tag, ses textes
    dans ses extras et ses boutons dans actions={…}, après celle d'une
    autre app."""
    lignes = [
        "Current Notification Manager state:",
        "  Notification List:",
        "    NotificationRecord(0x0badcafe: pkg=org.exemple.messagerie"
        " user=UserHandle{0} id=3 tag=null importance=3"
        " key=0|org.exemple.messagerie|3|null|10111: Notification("
        "channel=general pri=0 contentView=null vibrate=null sound=null"
        " defaults=0x0 flags=0x10 color=0x00000000 vis=PRIVATE))",
        "      android.title=String (Alice Martin)",
        "      actions={",
        '        [0] "Répondre" -> PendingIntent{1: PendingIntentRecord{2'
        " org.exemple.messagerie broadcastIntent}}",
        "      }",
        f"    NotificationRecord(0x0decade0: pkg={appareil.PAQUET}"
        f" user=UserHandle{{0}} id=0 tag={tag} importance=4"
        f" key=0|{appareil.PAQUET}|0|{tag}|10234: Notification("
        "channel=chat.0123456789ab pri=1 contentView=null vibrate=null"
        " sound=null defaults=0x0 flags=0x18 color=0x00000000 vis=PRIVATE))",
    ]
    lignes += [f"      android.text=String ({t})" for t in textes]
    lignes.append("      actions={")
    lignes += [
        f'        [{i}] "{a}" -> PendingIntent{{{i}: PendingIntentRecord{{9'
        f" {appareil.PAQUET} broadcastIntent}}}}"
        for i, a in enumerate(actions)
    ]
    lignes.append("      }")
    return "\n".join(lignes) + "\n"


def faux_telephone(notification=None, porte='data="sent"'):
    """Un faux subprocess.run qui note chaque commande adb : dumpsys
    notification rend notification (dumpsys_notification() par défaut),
    am broadcast la réponse de la porte (porte), un relevé uiautomator le
    volet avec notre notification."""
    commandes = []
    notification = notification or dumpsys_notification()

    def executer(commande, **_):
        commandes.append(commande)
        sortie = ""
        if commande[2:4] == ["dumpsys", "notification"]:
            sortie = notification
        elif commande[2:4] == ["am", "broadcast"]:
            sortie = (
                "Broadcasting: Intent { act=x flg=0x400000 cmp=y"
                " (has extras) }\n"
                f"Broadcast completed: result=0, {porte}\n"
            )
        elif commande[-2:] == ["cat", appareil.CONTENU_UI]:
            sortie = volet(notre(reponse=""))
        return SimpleNamespace(stdout=sortie, stderr="", returncode=0)

    return executer, commandes


def touchers_volet(commandes):
    """Les commandes qui agissent par l'écran : input (tap, text, swipe,
    keyevent) et les relevés uiautomator."""
    return [
        c
        for c in commandes
        if c[1:2] == ["shell"] and c[2:3] in (["input"], ["uiautomator"])
    ]


def portes(commandes):
    return [c for c in commandes if c[2:4] == ["am", "broadcast"]]


class TestPorteDeTest(unittest.TestCase):
    """Par défaut, les scénarios des notifications ne touchent jamais au
    volet : les boutons se lisent dans dumpsys notification, les actions
    passent par la porte de test de l'app (am broadcast vers ChatTestDoor,
    construction -PsyncTest seulement). --toucher-volet garde les vrais
    touchers."""

    def setUp(self):
        attente = mock.patch.object(appareil.time, "sleep")
        attente.start()
        self.addCleanup(attente.stop)

    def ctx(self, executer, toucher_volet=False):
        return SimpleNamespace(
            appareil=SimpleNamespace(executer=executer),
            toucher_volet=toucher_volet,
        )

    def test_une_action_passe_par_la_porte_sans_toucher_l_ecran(self):
        executer, commandes = faux_telephone()
        appareil.agir(self.ctx(executer), "Marquer lu", MESSAGE, TAG)
        self.assertEqual(touchers_volet(commandes), [])
        (porte,) = portes(commandes)
        self.assertEqual(
            porte,
            [
                "adb",
                "shell",
                "am",
                "broadcast",
                "-n",
                "ca.erplibre.home.synctest/"
                "ca.erplibre.home.chatpush.ChatTestDoor",
                "-a",
                "ca.erplibre.home.chatpush.TEST_DOOR",
                "--es",
                "tag",
                shlex.quote(TAG),
                "--es",
                "kind",
                "read",
            ],
        )

    def test_chaque_bouton_a_sa_sorte(self):
        for titre, sorte in (
            ("Marquer lu", "read"),
            ("👍", "react"),
            ("Muet 1 h", "mute"),
        ):
            executer, commandes = faux_telephone(
                dumpsys_notification(actions=("Répondre", "Marquer lu", titre))
            )
            appareil.agir(self.ctx(executer), titre, MESSAGE, TAG)
            self.assertEqual(portes(commandes)[0][-1], sorte)
            self.assertEqual(touchers_volet(commandes), [])

    def test_la_reponse_porte_ses_mots_par_la_porte(self):
        executer, commandes = faux_telephone()
        envoi = appareil.repondre(
            self.ctx(executer), "motsinventes", MESSAGE, TAG
        )
        self.assertIsInstance(envoi, float)
        self.assertEqual(touchers_volet(commandes), [])
        (porte,) = portes(commandes)
        self.assertEqual(
            porte[-6:],
            ["--es", "kind", "reply", "--es", "text", "motsinventes"],
        )

    def test_l_ouverture_est_le_toucher_de_la_notification(self):
        executer, commandes = faux_telephone()
        appareil.ouvrir_notification(self.ctx(executer), MESSAGE, TAG)
        self.assertEqual(touchers_volet(commandes), [])
        (porte,) = portes(commandes)
        # Le toucher d'une notification permet à l'app d'ouvrir un écran
        # depuis l'arrière-plan : la porte reçoit le même droit
        self.assertIn("--allow-background-activity-starts", porte)
        self.assertEqual(porte[-3:], ["--es", "kind", "open"])

    def test_un_bouton_absent_de_dumpsys_n_ouvre_pas_la_porte(self):
        executer, commandes = faux_telephone(
            dumpsys_notification(actions=("Répondre", "Marquer lu", "👍"))
        )
        with self.assertRaises(TimeoutError) as echec:
            appareil.agir(
                self.ctx(executer), "Muet 1 h", MESSAGE, TAG, delai=0
            )
        self.assertIn("Muet 1 h", str(echec.exception))
        self.assertEqual(portes(commandes), [])
        self.assertEqual(touchers_volet(commandes), [])

    def test_une_notification_sans_la_ligne_n_ouvre_pas_la_porte(self):
        executer, commandes = faux_telephone(
            dumpsys_notification(textes=("ms-test-autre",))
        )
        with self.assertRaises(TimeoutError):
            appareil.repondre(
                self.ctx(executer), "motsinventes", MESSAGE, TAG, delai=0
            )
        self.assertEqual(portes(commandes), [])

    def test_une_porte_qui_n_envoie_rien_echoue_sans_les_mots(self):
        executer, _ = faux_telephone(porte='data="no-notification"')
        with self.assertRaises(RuntimeError) as echec:
            appareil.repondre(self.ctx(executer), "motsinventes", MESSAGE, TAG)
        self.assertIn("no-notification", str(echec.exception))
        self.assertNotIn("motsinventes", str(echec.exception))

    def test_un_echec_d_adb_ne_cite_pas_le_texte_de_la_reponse(self):
        def executer(argv, **_):
            return mock.Mock(returncode=1, stdout="", stderr="adb: failed")

        with self.assertRaises(RuntimeError) as echec:
            appareil.adb(
                "shell",
                "am",
                "broadcast",
                "--es",
                "text",
                "motsinventes",
                executer=executer,
            )
        self.assertIn("failed", str(echec.exception))
        self.assertIn("broadcast", str(echec.exception))
        self.assertNotIn("motsinventes", str(echec.exception))

    def test_l_alimentation_passe_par_la_porte_sans_tag(self):
        executer, commandes = faux_telephone()
        appareil.puissance_de_test(executer, pct=12, plugged=False)
        appareil.puissance_de_test(executer, saver=True, plugged=False, pct=80)
        appareil.puissance_de_test(executer, clear=True)
        self.assertEqual(
            [p[4:] for p in portes(commandes)],
            [
                [
                    "-n",
                    appareil.PORTE,
                    "-a",
                    appareil.PORTE_ACTION,
                    "--es",
                    "kind",
                    "power",
                    "--ei",
                    "pct",
                    "12",
                    "--ez",
                    "plugged",
                    "false",
                ],
                [
                    "-n",
                    appareil.PORTE,
                    "-a",
                    appareil.PORTE_ACTION,
                    "--es",
                    "kind",
                    "power",
                    "--ez",
                    "saver",
                    "true",
                    "--ez",
                    "plugged",
                    "false",
                    "--ei",
                    "pct",
                    "80",
                ],
                [
                    "-n",
                    appareil.PORTE,
                    "-a",
                    appareil.PORTE_ACTION,
                    "--es",
                    "kind",
                    "power",
                    "--ez",
                    "clear",
                    "true",
                ],
            ],
        )
        self.assertEqual(touchers_volet(commandes), [])

    def test_une_alimentation_refusee_par_la_porte_echoue(self):
        executer, _ = faux_telephone(porte='data="refused"')
        with self.assertRaises(RuntimeError) as echec:
            appareil.puissance_de_test(executer, pct=101)
        self.assertIn("refused", str(echec.exception))

    def test_toucher_volet_garde_les_vrais_touchers(self):
        executer, commandes = faux_telephone()
        appareil.agir(
            self.ctx(executer, toucher_volet=True), "Répondre", MESSAGE, TAG
        )
        self.assertEqual(portes(commandes), [])
        self.assertIn(
            ["adb", "shell", "input", "tap", "200", "1150"], commandes
        )

    def test_les_scenarios_n_atteignent_le_volet_que_par_le_mode(self):
        # Les scénarios des notifications passent par agir, repondre et
        # ouvrir_notification, qui choisissent la porte ou le doigt : ils ne
        # touchent ni ne tapent rien d'eux-mêmes
        for scenario in (
            appareil.scenario_notifications,
            appareil.scenario_actions_notifications,
            appareil.scenario_preferences_notifications,
            appareil.etape_batterie_reelle,
        ):
            source = inspect.getsource(scenario)
            for interdit in (
                "toucher_action(",
                "repondre_du_volet(",
                "toucher_notification(",
                "toucher_dans(",
                "arbre_ui(",
                "deplier(",
                "toucher_stable(",
                "statusbar expand",
                '"input"',
            ):
                self.assertNotIn(interdit, source, scenario.__name__)

    def test_le_mode_suit_l_option_jusqu_au_scenario(self):
        vus = []
        cibles = [
            {
                "version": 18,
                "url": "http://127.0.0.1:8018",
                "database": "base_18",
                "admin": {"login": "admin", "password": "admin"},
            }
        ]
        for option in (False, True):
            with mock.patch.object(
                appareil,
                "SCENARIOS",
                (("n", lambda ctx: vus.append(ctx.toucher_volet), (18,)),),
            ), mock.patch.object(
                appareil, "construire_apk", return_value=Path("x.apk")
            ), mock.patch.object(
                appareil, "Appareil"
            ), mock.patch.object(
                appareil, "Odoo"
            ):
                appareil.lancer(
                    cibles,
                    "/x",
                    executer=faux_adb(paquets=[dumpsys_paquet()]),
                    journal=lambda _: 0,
                    toucher_volet=option,
                )
        self.assertEqual(vus, [False, True])
        self.assertFalse(
            mobile_sync.parser().parse_args(["--appareil"]).toucher_volet
        )
        self.assertTrue(
            mobile_sync.parser()
            .parse_args(["--appareil", "--toucher-volet"])
            .toucher_volet
        )


def appels_vers(noeud, nom):
    """Les appels à la fonction nom sous le nœud ast, et la chaîne de
    leurs ancêtres (du plus proche au plus lointain)."""
    trouves = []

    def visiter(n, ancetres):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == nom
        ):
            trouves.append(ancetres)
        for enfant in ast.iter_child_nodes(n):
            visiter(enfant, [n] + ancetres)

    visiter(noeud, [])
    return trouves


def sous_l_option(ancetres):
    """Vrai quand un des ancêtres est un « if ctx.batterie_reelle: »."""
    return any(
        isinstance(a, ast.If) and ast.unparse(a.test) == "ctx.batterie_reelle"
        for a in ancetres
    )


def faux_telephone_batterie(low_power="0", ecran="30000", paquets=""):
    """Un faux subprocess.run qui note chaque commande adb : settings get
    rend low_power (global low_power) ou ecran (system
    screen_off_timeout), pm list packages rend paquets."""
    commandes = []

    def executer(commande, **_):
        commandes.append(commande[1:])
        sortie = ""
        if commande[2:5] == ["settings", "get", "global"]:
            sortie = low_power + "\n"
        elif commande[2:5] == ["settings", "get", "system"]:
            sortie = ecran + "\n"
        elif commande[2:4] == ["pm", "list"]:
            sortie = paquets
        return SimpleNamespace(stdout=sortie, stderr="", returncode=0)

    return executer, commandes


def touche_batterie(commande):
    """Vrai quand la commande adb change ou lit l'état de la batterie ou
    de l'alimentation du téléphone entier."""
    texte = " ".join(commande)
    return any(
        mot in texte for mot in ("dumpsys battery", "cmd power", "low_power")
    )


class TestBatterieReelle(unittest.TestCase):
    """La batterie et l'alimentation du téléphone entier ne changent que
    sous --batterie-reelle, sur un téléphone de test vide : l'option refuse
    un téléphone qui porte l'app de l'utilisateur, et rendre() remet l'état
    noté, dans l'ordre (mode d'économie et low_power, batterie, délai de
    l'écran). Par défaut, la porte de test simule seule l'alimentation."""

    def test_le_scenario_ne_touche_la_batterie_que_sous_l_option(self):
        source = inspect.getsource(appareil.scenario_preferences_notifications)
        for interdit in (
            "dumpsys battery",
            '"battery"',
            "cmd power",
            '"set-mode"',
            "low_power",
        ):
            self.assertNotIn(interdit, source)
        arbre = ast.parse(textwrap.dedent(source))
        appels = appels_vers(arbre, "etape_batterie_reelle")
        self.assertTrue(appels)
        for ancetres in appels:
            self.assertTrue(sous_l_option(ancetres))

    def test_l_etape_reelle_note_avant_de_toucher_et_rend_a_la_fin(self):
        source = textwrap.dedent(
            inspect.getsource(appareil.etape_batterie_reelle)
        )
        self.assertLess(
            source.index("noter_batterie()"), source.index("battery")
        )
        arbre = ast.parse(source)
        (essai,) = [n for n in ast.walk(arbre) if isinstance(n, ast.Try)]
        self.assertIn(
            "rendre_batterie()",
            "".join(ast.unparse(n) for n in essai.finalbody),
        )

    def test_batterie_reelle_refuse_un_telephone_portant_l_app_perso(self):
        executer, commandes = faux_telephone_batterie(
            paquets=f"package:{appareil.APP_PERSO}\n"
            f"package:{appareil.PAQUET}\n"
        )
        with mock.patch.object(appareil, "construire_apk") as construire:
            with self.assertRaises(RuntimeError) as refus:
                appareil.lancer(
                    [], "/x", executer=executer, batterie_reelle=True
                )
        self.assertIn(appareil.APP_PERSO, str(refus.exception))
        construire.assert_not_called()
        self.assertEqual(
            commandes,
            [["shell", "pm", "list", "packages", appareil.APP_PERSO]],
        )

    def test_batterie_reelle_accepte_un_telephone_de_test_vide(self):
        executer, _ = faux_telephone_batterie(
            paquets=f"package:{appareil.PAQUET}\n"
        )
        with mock.patch.object(appareil, "SCENARIOS", ()), mock.patch.object(
            appareil, "construire_apk", return_value=Path("x.apk")
        ) as construire, mock.patch.object(appareil, "Appareil"):
            appareil.lancer(
                [],
                "/x",
                executer=executer,
                journal=lambda _: 0,
                batterie_reelle=True,
            )
        construire.assert_called_once()

    def test_sans_l_option_rien_ne_lit_les_paquets(self):
        executer, commandes = faux_telephone_batterie(
            paquets=f"package:{appareil.APP_PERSO}\n"
        )
        with mock.patch.object(appareil, "SCENARIOS", ()), mock.patch.object(
            appareil, "construire_apk", return_value=Path("x.apk")
        ), mock.patch.object(appareil, "Appareil"):
            appareil.lancer([], "/x", executer=executer, journal=lambda _: 0)
        self.assertNotIn(
            ["shell", "pm", "list", "packages", appareil.APP_PERSO],
            commandes,
        )

    def test_rendre_remet_batterie_et_alimentation_apres_batterie_reelle(
        self,
    ):
        executer, commandes = faux_telephone_batterie(
            low_power="1", ecran="45000"
        )
        telephone = appareil.Appareil([8018], executer)
        telephone.noter_batterie()
        self.assertEqual(
            commandes[-1],
            [
                "shell",
                "settings",
                "put",
                "system",
                "screen_off_timeout",
                str(appareil.ECRAN_BATTERIE_REELLE),
            ],
        )
        debut = len(commandes)
        telephone.rendre()
        remise = [c for c in commandes[debut:] if touche_batterie(c)] + [
            c for c in commandes[debut:] if "screen_off_timeout" in c
        ]
        self.assertEqual(
            remise,
            [
                ["shell", "cmd", "power", "set-mode", "1"],
                ["shell", "settings", "put", "global", "low_power", "1"],
                ["shell", "dumpsys", "battery", "reset"],
                [
                    "shell",
                    "settings",
                    "put",
                    "system",
                    "screen_off_timeout",
                    "45000",
                ],
            ],
        )
        ordre = [commandes.index(c) for c in remise]
        self.assertEqual(ordre, sorted(ordre))
        # Une seconde remise ne rejoue rien : l'état noté est rendu
        debut = len(commandes)
        telephone.rendre()
        self.assertFalse(any(touche_batterie(c) for c in commandes[debut:]))

    def test_une_valeur_absente_est_rendue_absente(self):
        executer, commandes = faux_telephone_batterie(
            low_power="null", ecran="null"
        )
        telephone = appareil.Appareil([8018], executer)
        telephone.noter_batterie()
        telephone.rendre()
        self.assertIn(["shell", "cmd", "power", "set-mode", "0"], commandes)
        self.assertIn(
            ["shell", "settings", "delete", "global", "low_power"], commandes
        )
        self.assertIn(
            ["shell", "settings", "delete", "system", "screen_off_timeout"],
            commandes,
        )

    def test_rendre_sans_batterie_reelle_ne_touche_pas_la_batterie(self):
        executer, commandes = faux_telephone_batterie()
        appareil.Appareil([8018], executer).rendre()
        self.assertFalse(any(touche_batterie(c) for c in commandes))
        self.assertFalse(any("screen_off_timeout" in c for c in commandes))

    def test_l_option_suit_jusqu_au_scenario(self):
        vus = []
        cibles = [
            {
                "version": 18,
                "url": "http://127.0.0.1:8018",
                "database": "base_18",
                "admin": {"login": "admin", "password": "admin"},
            }
        ]
        executer, _ = faux_telephone_batterie()
        for option in (False, True):
            with mock.patch.object(
                appareil,
                "SCENARIOS",
                (("n", lambda ctx: vus.append(ctx.batterie_reelle), (18,)),),
            ), mock.patch.object(
                appareil, "construire_apk", return_value=Path("x.apk")
            ), mock.patch.object(
                appareil, "Appareil"
            ), mock.patch.object(
                appareil, "Odoo"
            ):
                appareil.lancer(
                    cibles,
                    "/x",
                    executer=executer,
                    journal=lambda _: 0,
                    batterie_reelle=option,
                )
        self.assertEqual(vus, [False, True])
        self.assertFalse(
            mobile_sync.parser().parse_args(["--appareil"]).batterie_reelle
        )
        self.assertTrue(
            mobile_sync.parser()
            .parse_args(["--appareil", "--batterie-reelle"])
            .batterie_reelle
        )


class TestMortEspacee(unittest.TestCase):
    """Android tient pour répété un plantage à moins de 60 s du précédent
    et affiche alors « … plante continuellement », qui garde le processus
    en vie : deux morts par am crash sont espacées d'au moins
    PLANTAGE_ESPACE, les scénarios qui se suivent compris."""

    def executer(self, commandes):
        def executer(commande, **_):
            commandes.append(commande)
            # run-as refusé, comme SELinux le refuse sur Android 11
            code = 1 if "run-as" in commande else 0
            return SimpleNamespace(stdout="", stderr="refusé", returncode=code)

        return executer

    def test_un_second_plantage_attend_la_fin_de_l_intervalle(self):
        horloge = [1000.0]
        attentes = []

        def dormir(secondes):
            attentes.append(secondes)
            horloge[0] += secondes

        commandes = []
        with mock.patch.object(
            appareil.time, "monotonic", lambda: horloge[0]
        ), mock.patch.object(
            appareil.time, "sleep", dormir
        ), mock.patch.object(
            appareil, "DERNIER_PLANTAGE", [None]
        ):
            executer = self.executer(commandes)
            self.assertEqual(
                appareil.tuer_processus(executer, "111"), "am crash"
            )
            horloge[0] += 25
            appareil.tuer_processus(executer, "222")
        self.assertEqual(attentes, [appareil.PLANTAGE_ESPACE - 25])
        self.assertGreater(appareil.PLANTAGE_ESPACE, 60)
        self.assertEqual(
            [c[4] for c in commandes if c[2:3] == ["am"]], ["111", "222"]
        )

    def test_un_plantage_loin_du_precedent_n_attend_pas(self):
        horloge = [1000.0]
        attentes = []
        with mock.patch.object(
            appareil.time, "monotonic", lambda: horloge[0]
        ), mock.patch.object(
            appareil.time, "sleep", attentes.append
        ), mock.patch.object(
            appareil, "DERNIER_PLANTAGE", [None]
        ):
            executer = self.executer([])
            appareil.tuer_processus(executer, "111")
            horloge[0] += 200
            appareil.tuer_processus(executer, "222")
        self.assertEqual(attentes, [])


class TestRemiseEnEtat(unittest.TestCase):
    """La remise en état de fin de scénario (la conversation remise en
    son) ne masque jamais l'échec du scénario : il remonte, et l'échec de
    la remise suit dans le journal."""

    def test_apres_un_echec_la_remise_qui_echoue_le_suit(self):
        echec = AssertionError("étape 5 : notification absente")

        def remise():
            raise RuntimeError("Odoo injoignable")

        appareil.remettre_en_etat(echec, "la remise en son", remise)
        lignes = appareil.lignes_echec("Odoo 18 — actions", echec)
        self.assertEqual(
            lignes[0],
            "  ✗ Odoo 18 — actions : AssertionError étape 5 : notification"
            " absente",
        )
        self.assertIn("la remise en son", lignes[1])
        self.assertIn("RuntimeError Odoo injoignable", lignes[1])

    def test_sans_echec_la_remise_qui_echoue_remonte(self):
        def remise():
            raise RuntimeError("Odoo injoignable")

        with self.assertRaises(RuntimeError):
            appareil.remettre_en_etat(None, "la remise en son", remise)

    def test_une_remise_reussie_ne_note_rien(self):
        echec = AssertionError("étape 5")
        appareil.remettre_en_etat(echec, "la remise en son", lambda: None)
        self.assertEqual(
            appareil.lignes_echec("Odoo 18 — actions", echec),
            ["  ✗ Odoo 18 — actions : AssertionError étape 5"],
        )


class TestScenariosAppareil(unittest.TestCase):
    """Le clavardage ne se joue que sur la 18, seule version que le chat de
    l'app connaît ; les autres versions le sautent sans le compter."""

    def test_api_du_hook_9(self):
        self.assertEqual(appareil.DEVICE_HOOK_API, 9)

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
            (
                "préférences du clavardage, app fermée",
                appareil.scenario_preferences_notifications,
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
