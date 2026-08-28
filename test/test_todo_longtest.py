#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les tests LONGS : qu'ils existent, qu'ils annoncent, et qu'ils ne
polluent pas la suite unitaire.

Un test qui crée dix VM n'a rien à faire dans `test/` : le lanceur unitaire
doit rester lançable en quelques secondes, partout, y compris sur une machine
sans virtualisation. Ce fichier-ci vérifie la frontière, et que l'essai à
blanc du test long dit quelque chose sans rien créer.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(RACINE, ".venv.erplibre/bin/python")

# Le moteur vit dans son propre module depuis qu'il est partagé entre
# deep_proxmox et deep_qemu. Bouchonner « deep_proxmox.dernier_rapport » ne
# ferait plus rien : c'est descente.detruire qui appelle descente.dernier_rapport.
sys.path.insert(0, os.path.join(RACINE, "long_test"))
import descente as moteur  # noqa: E402


class TestLaFrontiere(unittest.TestCase):
    """long_test est hors de portée du lanceur unitaire, et ce n'est pas un
    rangement de confort."""

    def test_the_unit_runner_does_not_sweep_long_test(self):
        with open(
            os.path.join(RACINE, "script/test/run_unit_test.sh"),
            encoding="utf-8",
        ) as fh:
            lanceur = fh.read()
        # Le lanceur ne liste que des fichiers de test/ : rien qui parte de
        # long_test, sinon la suite unitaire créerait des VM.
        self.assertNotIn("long_test", lanceur)

    def test_the_runner_only_looks_under_test(self):
        """Le lanceur balaie TOUT test/test_*.py depuis qu'une liste de
        préfixes a laissé 2400 tests hors de la suite.

        La frontière n'est donc plus un nom mais un RÉPERTOIRE : ce qui doit
        rester hors de la suite doit vivre ailleurs que dans test/. C'est
        exactement pourquoi long_test est à la racine."""
        with open(
            os.path.join(RACINE, "script/test/run_unit_test.sh"),
            encoding="utf-8",
        ) as fh:
            lanceur = fh.read()
        self.assertIn("test/test_*.py", lanceur)
        # Aucun chemin du lanceur ne sort de test/ : sinon long_test y
        # entrerait par la porte de service.
        self.assertNotIn("long_test", lanceur)

    def test_the_script_is_executable_and_documented(self):
        script = os.path.join(RACINE, "long_test/deep_proxmox.py")
        self.assertTrue(os.access(script, os.X_OK), "doit être exécutable")
        # La doc est un .base.md : un .md généré se perd au prochain
        # « make doc_markdown ».
        self.assertTrue(
            os.path.exists(os.path.join(RACINE, "long_test/README.base.md"))
        )


class TestLEssaiABlanc(unittest.TestCase):
    """L'essai à blanc annonce le plan et n'exécute RIEN.

    C'est ce qui rend un test de plusieurs heures relisable avant de le
    lancer : on voit les ressources de chaque étage et les commandes, sans
    créer une machine."""

    @classmethod
    def setUpClass(cls):
        import tempfile

        # HOME temporaire : la suite unitaire tourne souvent, et elle n'a pas
        # à semer un rapport dans ~/.erplibre à chaque passage.
        cls.maison = tempfile.mkdtemp()
        cls.res = subprocess.run(
            [
                PYTHON,
                os.path.join(RACINE, "long_test/deep_proxmox.py"),
                "--depth",
                "4",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=RACINE,
            env=dict(os.environ, PYTHONPATH=RACINE, HOME=cls.maison),
        )

    @classmethod
    def tearDownClass(cls):
        import shutil

        shutil.rmtree(cls.maison, ignore_errors=True)

    def test_it_exits_cleanly(self):
        self.assertEqual(self.res.returncode, 0, self.res.stderr[-800:])

    def test_it_announces_the_plan_before_anything(self):
        """Les LIGNES du plan, pas les chiffres.

        La version d'avant cherchait « 1 », « 2 », « 3 », « 4 » dans la
        sortie : l'en-tête « 28 cœurs, 29128 Mo, 138 Go » et l'horodatage du
        journal les fournissent tous. Elle passait même à --depth 1, avec une
        seule ligne de plan — elle ne prouvait rien."""
        import re

        plan = re.findall(
            r"^\s+(\d+)\s+(\d+)\s+(\d+) Mo\s+(\d+) Go\s*$",
            self.res.stdout,
            re.M,
        )
        self.assertEqual([int(p[0]) for p in plan], [1, 2, 3, 4])
        self.assertIn("dry-run", self.res.stdout)

    def test_it_shows_the_commands_it_would_send(self):
        # Une étape affichée est une étape rejouable à la main : c'est ainsi
        # que les pannes de ce module ont été diagnostiquées.
        self.assertIn("qm create", self.res.stdout)
        self.assertIn("install_proxmox.sh", self.res.stdout)

    def test_the_installer_is_run_by_bash_not_sh(self):
        """Le script porte « set -euo pipefail » et un shebang bash.

        Sur Debian /bin/sh est dash, qui répond « set: Illegal option -o
        pipefail » et sort à la PREMIÈRE ligne — vérifié. Lancé par sh, chaque
        étage aurait échoué sur l'installation, à tous les coups."""
        # Sur la LIGNE, pas dans le texte : « bash /tmp/… » contient
        # « sh /tmp/… », donc un assertNotIn naïf échouait sur lui-même.
        lignes = [
            ligne.strip()
            for ligne in self.res.stdout.splitlines()
            if "install_proxmox.sh" in ligne
            and not ligne.strip().startswith("scp")
        ]
        self.assertTrue(lignes)
        for ligne in lignes:
            self.assertTrue(
                ligne.startswith("bash "), f"lancé par autre chose : {ligne}"
            )

    def test_the_first_level_gets_an_ssh_entry(self):
        """La CLI QEMU/KVM n'écrit PAS d'entrée ~/.ssh/config.

        Sans elle, « ssh deep-pve-1 » rend « Name or service not known » et la
        descente attendait son plein délai avant de conclure « jamais
        joignable » — sur une VM qui répondait parfaitement à son adresse.
        Trouvé au premier lancement réel, pas par l'attaque."""
        import inspect
        import sys as _sys

        _sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        src = inspect.getsource(deep_proxmox.Descente.creer_etage1)
        self.assertIn("_write_ssh_config_entry", src)
        self.assertIn("_qemu_vm_ip_now", src)
        # Et une VM sans adresse n'est pas déclarée prête.
        self.assertIn("créée mais sans adresse", src)

    def test_the_dry_run_claims_nothing_reached(self):
        """Le rapport d'un essai à blanc était indiscernable d'une réussite —
        JSON compris — et « --detruire » s'en servait."""
        import glob
        import json

        fichiers = glob.glob(
            os.path.join(self.maison, ".erplibre/longtest/*.json")
        )
        self.assertEqual(len(fichiers), 1, fichiers)
        self.assertIn("dryrun", fichiers[0])
        with open(fichiers[0], encoding="utf-8") as fh:
            rapport = json.load(fh)
        self.assertTrue(rapport["dry_run"])
        self.assertEqual(rapport["atteinte"], 0)
        self.assertTrue(all(not e["ok"] for e in rapport["etages"]))

    def test_the_plan_shrinks_towards_the_bottom(self):
        """Chaque étage annoncé est plus étroit que son parent, sur les trois
        ressources.

        Deux vCPU à chaque étage imbriqué donnaient un parent aussi étroit que
        son enfant : cent pour cent de surengagement, et l'hyperviseur à servir
        par-dessus. Mesuré : l'installation de l'étage 4 dépassait 2 h 50
        contre 793 s pour l'étage 3."""
        # Par expression exacte : la ligne « machine : … Mo … Go » du haut
        # contient les mêmes unités et décalait l'index d'un cran.
        import re

        plan = re.findall(
            r"^\s+(\d+)\s+(\d+)\s+(\d+) Mo\s+(\d+) Go\s*$",
            self.res.stdout,
            re.M,
        )
        self.assertEqual(len(plan), 4, plan)
        etages = sorted(
            (int(n), int(v), int(r), int(d)) for n, v, r, d in plan
        )
        for parent, enfant in zip(etages, etages[1:]):
            # Mémoire et disque : STRICTEMENT décroissants, chaque parent
            # portant son enfant en plus de lui-même.
            for i, quoi in ((2, "RAM"), (3, "disque")):
                self.assertGreater(
                    parent[i], enfant[i], f"étage {parent[0]} : {quoi}"
                )
            # Le processeur : jamais plus étroit, mais pas toujours plus
            # large. Deux étages imbriqués peu profonds ont la même largeur —
            # au quatrième étage, un vCPU de plus multiplie l'amorçage par
            # 9,4, alors qu'aux étages 2 et 3 il ne coûte rien.
            self.assertGreaterEqual(
                parent[1], enfant[1], f"étage {parent[0]} : vCPU"
            )
        # Et le plus profond reçoit ce qu'un Proxmox de test demande, pas ce
        # qui reste.
        self.assertEqual(etages[-1][1], 2, "vCPU du plus profond")


class TestLaProfondeurParDefaut(unittest.TestCase):
    """Trois, et c'est une MESURE, pas une prudence.

    Sur la machine où ce test a été écrit, les trois premiers étages coûtent
    280, 495 et 1 064 secondes — une demi-heure en tout. Le quatrième a demandé
    7 h 18 d'installation et 4 h 20 d'amorçage, et les suivants se comptent en
    jours. Un défaut à dix promettait ce qu'aucune machine ne peut tenir : la
    profondeur reste un paramètre, mais le défaut doit marcher."""

    def test_the_script_defaults_to_three(self):
        import inspect
        import sys as _sys

        _sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        src = inspect.getsource(moteur.mener)
        self.assertIn('"--depth", type=int, default=3', src)
        # Et les deux piles passent bien par là.
        self.assertIn("mener(", inspect.getsource(deep_proxmox.principal))

    def test_the_menu_defaults_to_three(self):
        import inspect

        from script.todo.todo import TODO

        src = inspect.getsource(TODO._longtest_depth)
        self.assertIn("else 3", src)
        # Et l'invite le DIT : un défaut caché se subit, il ne se choisit pas.
        self.assertIn("Depth (default 3): ", src)

    def test_the_prompt_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        entree = TRANSLATIONS.get("Depth (default 3): ")
        self.assertIsNotNone(entree, "invite non traduite")
        self.assertIn("3", entree["fr"])

    def test_the_default_depth_fits_a_modest_machine(self):
        """Le défaut doit tenir là où le test sera lancé, pas seulement sur la
        machine de celui qui l'a écrit."""
        from script.proxmox import nesting

        plan = nesting.nesting_plan(
            3, cpu_hote=8, ram_dispo_mo=24000, disque_libre_go=120
        )
        self.assertEqual(plan["atteignable"], 3)
        self.assertEqual(plan["arret"], "")


class TestDefaireSansEffacerAutreChose(unittest.TestCase):
    """« --detruire » effaçait par SOUS-CHAÎNE de nom, dans le mauvais ordre,
    sans confirmation et sans honorer --dry-run.

    Quatre défauts trouvés en attaquant le code écrit, chacun capable
    d'emporter une machine qui n'appartient pas au test. « qm destroy --purge »
    emporte les disques ET les entrées de sauvegarde."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox

    def test_the_deepest_level_goes_first(self):
        """Le tri comptait les « + » de l'alias — or alias_etage remplace le
        « + » du parent par un « - », donc chaque alias en portait
        exactement UN. Le tri ne triait rien, et la destruction partait du
        plus HAUT : « qm destroy --purge » sur l'étage 2 emportait le disque
        contenant les étages 3 et suivants."""
        rapport = {
            "etages": [
                {"niveau": 2, "vmid": 100, "parent_alias": "a"},
                {"niveau": 4, "vmid": 100, "parent_alias": "c"},
                {"niveau": 3, "vmid": 100, "parent_alias": "b"},
            ]
        }
        niveaux = [
            n
            for n, _p, _v, _nom in self.dp.a_defaire(rapport, self.dp.NOM_BASE)
        ]
        self.assertEqual(niveaux, [4, 3, 2])

    def test_a_level_without_a_vmid_is_not_guessed(self):
        # Un étage abandonné avant « qm create » n'a rien créé : ne rien
        # inventer à sa place.
        rapport = {"etages": [{"niveau": 2}, {"niveau": 3, "vmid": 101}]}
        self.assertEqual(len(self.dp.a_defaire(rapport, self.dp.NOM_BASE)), 0)

    def test_the_alias_chain_really_flattens_the_plus(self):
        # La cause du tri mort, énoncée pour qu'on ne la réintroduise pas.
        alias, precedent = "deep-pve-1", "deep-pve-1"
        for niveau in (2, 3, 4):
            alias = self.dp.alias_etage(niveau, precedent)
            precedent = alias
        self.assertEqual(alias.count("+"), 1, alias)

    def test_an_exact_name_is_required(self):
        """Le filtre était « NOM_BASE in name » : une VM de labo appelée
        « deep-pve-lab » sur un hyperviseur de production tombait dedans."""
        import inspect

        src = inspect.getsource(self.dp.detruire_une)
        self.assertIn("!= nom", src)
        self.assertNotIn("in presentes[vmid]", src)

    def test_dry_run_reports_are_never_used_to_destroy(self):
        """Un rapport d'essai à blanc n'a rien créé : s'en servir ferait
        détruire d'après un plan."""
        import inspect

        src = inspect.getsource(self.dp.dernier_rapport)
        self.assertIn('rapport.get("dry_run")', src)

    def test_destruction_honours_dry_run_and_asks(self):
        import inspect

        src = inspect.getsource(self.dp.detruire)
        self.assertIn("dry_run", src)
        # Une confirmation explicite, pas un « o/N » : le menu lançait cette
        # option d'une seule touche.
        self.assertIn("OUI", src)
        # La ligne de commande vit dans le moteur depuis qu'elle est
        # identique d'une pile à l'autre.
        self.assertIn("dry_run=args.dry_run", inspect.getsource(moteur.mener))


class TestUnRapportQuiSurvitAuProcessus(unittest.TestCase):
    """Le rapport ne s'écrivait qu'à la FIN de la descente.

    Constaté : une descente de dix étages arrêtée pendant l'installation du
    quatrième laissait quatre machines réelles, et « --detruire » répondait
    « aucun rapport de descente : rien à défaire ». Le seul enregistrement du
    couple (alias du parent, VMID) mourait avec le processus — il fallait
    retrouver ces VM à la main, c'est-à-dire par leur nom, ce que tout le
    reste de ce fichier s'applique à ne pas faire.
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox
        self.dossier = tempfile.mkdtemp(prefix="longtest-rapport-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)

    def _descente_tuee(self, a_l_etage):
        """Une descente dont l'installation MEURT à l'étage donné.

        Rien de réel n'est touché : aucune des méthodes qui créent une machine
        ou écrivent dans ~/.ssh/config n'est appelée pour de vrai.
        """
        niveaux = [
            {"niveau": n, "vcpu": 2, "ram": 4096, "disque": 25}
            for n in (1, 2, 3)
        ]
        plan = {"demandee": 3, "atteignable": 3, "niveaux": niveaux}
        chemin = os.path.join(self.dossier, "rapport.json")
        d = self.dp.Descente(plan, None, False, chemin)

        appels = []
        d.creer_etage1 = lambda res: "deep-pve-1"
        d.preparer_parent = lambda parent: {"stockage": "local-lvm"}

        def creer_enfant(parent, niveau, res, prep, noter=None):
            # Le VRAI ordre : le VMID est annoncé AVANT que la VM existe.
            if noter:
                noter(100 + niveau)
            return 100 + niveau, f"10.10.10.{niveau}"

        d.creer_enfant = creer_enfant
        d.ecrire_alias = lambda *a, **k: None
        d.attendre_ssh = lambda cible, delai, parent=None: 1
        d.redemarrer_et_verifier = lambda cible: True
        d.remettre_debout = lambda cible: True
        d.preparer_systeme = lambda cible: True
        d.controler = lambda cible: True

        def installer(cible):
            appels.append(cible)
            if len(appels) >= a_l_etage:
                raise KeyboardInterrupt("descente tuée")
            return True

        d.installer = installer
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                d.parcourir()
        with open(chemin, encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_killed_descent_still_names_what_it_created(self):
        rapport = self._descente_tuee(a_l_etage=3)
        # Le couple (parent, VMID) des étages imbriqués créés : c'est de lui
        # seul que « --detruire » se sert.
        self.assertEqual(
            self.dp.a_defaire(rapport, self.dp.NOM_BASE),
            [
                (3, "deep-pve-1+deep-pve-2", "103", self.dp.nom_etage(3)),
                (2, "deep-pve-1", "102", self.dp.nom_etage(2)),
            ],
        )

    def test_the_report_exists_as_soon_as_the_first_vm_does(self):
        """Tuée pendant l'installation de l'étage 1, il n'y a aucun VMID à
        noter — mais le domaine libvirt existe, et sans rapport « --detruire »
        ne le regardait même pas."""
        rapport = self._descente_tuee(a_l_etage=1)
        self.assertTrue(rapport["etages"])
        self.assertEqual(self.dp.a_defaire(rapport, self.dp.NOM_BASE), [])

    def test_a_partial_report_never_reads_as_a_finished_descent(self):
        rapport = self._descente_tuee(a_l_etage=3)
        self.assertTrue(rapport["interrompu"])
        self.assertLess(rapport["atteinte"], rapport["demandee"])
        # Et il n'est pas écarté comme un essai à blanc : c'est bien de VRAIES
        # machines qu'il parle.
        self.assertFalse(rapport["dry_run"])

    def test_a_dry_run_writes_no_partial_report(self):
        """Un plan n'a rien créé : lui laisser écrire un rapport ferait
        détruire d'après un plan."""
        plan = {
            "demandee": 1,
            "atteignable": 1,
            "niveaux": [{"niveau": 1, "vcpu": 2, "ram": 4096, "disque": 25}],
        }
        chemin = os.path.join(self.dossier, "blanc.json")
        d = self.dp.Descente(plan, None, True, chemin)
        with contextlib.redirect_stdout(io.StringIO()):
            d._sauver({"niveau": 1, "vmid": 101, "parent_alias": "x"})
        self.assertFalse(os.path.exists(chemin))


class TestNeJamaisDetruireSousUneDescenteVivante(unittest.TestCase):
    """Le correctif du rapport partiel a CRÉÉ ce danger.

    Avant, la descente en cours n'avait aucun rapport sur le disque et
    « --detruire » retombait sur la précédente, terminée. Depuis qu'il s'écrit
    VM par VM, le rapport de la descente VIVANTE est le plus récent : détruire
    aurait emporté l'arbre sous le processus qui installait encore."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox
        self.maison = tempfile.mkdtemp(prefix="longtest-maison-")
        self.dossier = os.path.join(self.maison, ".erplibre/longtest")
        os.makedirs(self.dossier)
        self._vrai = os.environ.get("HOME")
        os.environ["HOME"] = self.maison
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        # Un bouchon posé par un test et non repris fausse les SUIVANTS : la
        # première version de ce fichier remplaçait dernier_rapport et le
        # laissait en place, et le test d'après lisait le bouchon.
        self._vrais = {
            nom: getattr(deep_proxmox, nom)
            for nom in ("autre_descente", "dernier_rapport")
        }

    def tearDown(self):
        if self._vrai is not None:
            os.environ["HOME"] = self._vrai
        for nom, vrai in self._vrais.items():
            setattr(self.dp, nom, vrai)

    def _ecrire(self, nom, rapport):
        with open(
            os.path.join(self.dossier, nom), "w", encoding="utf-8"
        ) as fh:
            json.dump(rapport, fh)

    def test_a_living_descent_is_recognised_by_its_pid(self):
        # Ce processus-ci exécute bien un test, pas deep_proxmox.py : c'est
        # justement ce que le contrôle doit savoir distinguer.
        self.assertFalse(self.dp.descente_vivante(os.getpid()))
        self.assertFalse(self.dp.descente_vivante(None))
        self.assertFalse(self.dp.descente_vivante(999999999))

    def test_a_shell_that_merely_names_the_script_is_not_a_descent(self):
        """Constaté sur la machine : un « pgrep -f deep_proxmox.py » posé dans
        une boucle de surveillance donnait un shell dont la ligne de commande
        contient le motif, et deux faux positifs sur trois."""
        import subprocess

        faux = subprocess.Popen(
            [
                "sh",
                "-c",
                "echo deep_proxmox.py --depth 10 >/dev/null; sleep 30",
            ]
        )
        self.addCleanup(faux.kill)
        self.assertFalse(self.dp._lance_une_descente(faux.pid))
        self.assertNotIn(faux.pid, self.dp.autre_descente())

    def _fausse_descente(self):
        """Un processus qui exécute VRAIMENT un « deep_proxmox.py ».

        Un PID inventé ne prouverait rien : le contrôle lit /proc, et la seule
        façon honnête de l'éprouver est de lui donner un processus à voir."""
        faux = os.path.join(self.maison, "deep_proxmox.py")
        with open(faux, "w", encoding="utf-8") as fh:
            fh.write("import time\ntime.sleep(60)\n")
        proc = subprocess.Popen([sys.executable, faux])
        self.addCleanup(proc.kill)
        for _ in range(60):
            if self.dp._lance_une_descente(proc.pid):
                return proc.pid
            time.sleep(0.05)
        self.skipTest("le processus témoin n'a pas démarré")

    def test_a_living_descent_is_seen_in_proc(self):
        pid = self._fausse_descente()
        self.assertTrue(self.dp.descente_vivante(pid))
        self.assertIn(pid, self.dp.autre_descente())

    def test_the_report_of_a_living_descent_is_skipped(self):
        """Sans ce filtre, « --detruire » choisissait le rapport de la
        descente EN COURS — le plus récent — et détruisait l'arbre sous le
        processus qui installait encore."""
        pid = self._fausse_descente()
        self._ecrire(
            "deep-pve-20260101-000000.json",
            {
                "dry_run": False,
                "etages": [{"niveau": 2, "vmid": 102, "parent_alias": "a"}],
            },
        )
        self._ecrire(
            "deep-pve-20260102-000000.json",
            {
                "dry_run": False,
                "pid": pid,
                "etages": [{"niveau": 5, "vmid": 105, "parent_alias": "vif"}],
            },
        )
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            rapport = self.dp.dernier_rapport()
        # Celui de la descente vivante est écarté, et on le DIT.
        self.assertIn("descente EN COURS", sortie.getvalue())
        self.assertEqual(rapport["etages"][0]["vmid"], 102)

    def test_an_empty_later_report_never_masks_one_that_names_vms(self):
        """Un second lancement qui meurt à l'étage 1 — « le disque existe
        déjà » — écrivait un rapport VIDE sous un horodatage plus tardif.
        « --detruire » annonçait « 0 VM imbriquée(s) » puis effaçait le disque
        de l'étage 1, où vivaient les étages 2 et suivants : jamais arrêtés,
        jamais nommés."""
        self._ecrire(
            "deep-pve-20260101-000000.json",
            {
                "dry_run": False,
                "etages": [
                    {"niveau": 3, "vmid": 103, "parent_alias": "a+b"},
                    {"niveau": 2, "vmid": 102, "parent_alias": "a"},
                ],
            },
        )
        self._ecrire(
            "deep-pve-20260102-000000.json", {"dry_run": False, "etages": []}
        )
        with contextlib.redirect_stdout(io.StringIO()):
            rapport = self.dp.dernier_rapport()
        self.assertEqual(len(self.dp.a_defaire(rapport, self.dp.NOM_BASE)), 2)
        self.assertTrue(rapport["fichier"].endswith("20260101-000000.json"))

    def test_a_dry_run_report_still_never_wins(self):
        self._ecrire(
            "deep-pve-20260101-000000.json",
            {
                "dry_run": False,
                "etages": [{"niveau": 2, "vmid": 102, "parent_alias": "a"}],
            },
        )
        self._ecrire(
            "deep-pve-20260103-000000.json",
            {
                "dry_run": True,
                "etages": [{"niveau": 9, "vmid": 900, "parent_alias": "z"}],
            },
        )
        with contextlib.redirect_stdout(io.StringIO()):
            rapport = self.dp.dernier_rapport()
        self.assertEqual(rapport["etages"][0]["vmid"], 102)

    def test_destroying_refuses_while_a_descent_runs(self):
        appels = []
        moteur.autre_descente = lambda: [4242]
        moteur.dernier_rapport = lambda outil="": appels.append("lu") or {}
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            code = self.dp.detruire(self.dp.FAMILLE, None, dry_run=False)
        self.assertEqual(code, 1)
        # Le rapport n'est même pas LU : on ne demande rien, on ne propose
        # rien, et surtout on n'attend pas un « OUI » sur un arbre vivant.
        self.assertEqual(appels, [])
        self.assertIn("descente tourne", sortie.getvalue())


class TestLEtage1SIdentifiePasParSonNom(unittest.TestCase):
    """« virsh undefine --remove-all-storage » efface un disque pour de bon.

    Il partait sur le NOM fixe deep-pve-1, quel que soit le domaine qui le
    porte : la VM d'une descente précédente qu'on voulait garder, ou une
    machine sans rapport. C'est la famille de défauts la plus tenace de ce
    travail — une ressource liée à une machine par son nom au lieu de ce qui
    l'identifie vraiment."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox
        self.vrai_run = deep_proxmox.subprocess.run
        # LE staticmethod, pas la fonction qu'il enveloppe : le rendre nu en
        # ferait une méthode d'instance, et « self.uuid_libvirt(nom) »
        # passerait deux arguments à une fonction qui en prend un. La fuite
        # tombait sur les tests SUIVANTS.
        # Le crochet vit sur la classe de BASE, dans descente.py : c'est
        # elle qu'il faut détourner, pas la sous-classe Proxmox.
        self.moteur = moteur
        self.vrai_uuid = moteur.Descente.__dict__["uuid_libvirt"]
        self.addCleanup(setattr, deep_proxmox.subprocess, "run", self.vrai_run)
        self.addCleanup(
            setattr, moteur.Descente, "uuid_libvirt", self.vrai_uuid
        )
        self.lances = []

    def _virsh(self, dominfo=0):
        import types

        def faux(argv, **kw):
            self.lances.append(" ".join(argv[2:]))
            code = dominfo if "dominfo" in argv else 0
            return types.SimpleNamespace(returncode=code, stdout="", stderr="")

        self.dp.subprocess.run = faux

    def test_a_homonym_with_another_uuid_is_left_alone(self):
        self._virsh()
        self.moteur.Descente.uuid_libvirt = staticmethod(
            lambda nom: "AUTRE-UUID"
        )
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            res = self.dp.detruire_etage1(
                None, "deep-pve-1", attendu="LE-NOTRE"
            )
        self.assertFalse(res)
        self.assertIn("PAS notre machine", sortie.getvalue())
        # Aucun undefine, aucun destroy : seule la lecture a eu lieu.
        self.assertTrue(all("dominfo" in c for c in self.lances), self.lances)

    def test_our_own_machine_is_destroyed(self):
        self._virsh()
        self.moteur.Descente.uuid_libvirt = staticmethod(
            lambda nom: "LE-NOTRE"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            res = self.dp.detruire_etage1(
                None, "deep-pve-1", attendu="LE-NOTRE"
            )
        self.assertTrue(res)
        self.assertTrue(
            any(
                "undefine" in c and "remove-all-storage" in c
                for c in self.lances
            ),
            self.lances,
        )

    def test_an_old_report_without_a_uuid_says_so(self):
        """On procède alors par le nom, faute de mieux — mais on le DIT,
        plutôt que de laisser croire qu'on a vérifié."""
        self._virsh()
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            res = self.dp.detruire_etage1(None, "deep-pve-1")
        self.assertTrue(res)
        self.assertIn("identifié par son NOM", sortie.getvalue())

    def test_an_absent_domain_is_not_an_error(self):
        self._virsh(dominfo=1)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(
                self.dp.detruire_etage1(None, "deep-pve-1", attendu="X")
            )

    def test_the_name_comes_from_the_report_not_from_the_level(self):
        """Le déduire du numéro d'étage supposait que nom_etage ne changera
        jamais : un rapport ancien nommerait alors d'autres machines."""
        rapport = {
            "etages": [
                {
                    "niveau": 2,
                    "vmid": 102,
                    "parent_alias": "a",
                    "nom": "nom-ecrit-a-la-creation",
                }
            ]
        }
        self.assertEqual(
            self.dp.a_defaire(rapport, self.dp.NOM_BASE),
            [(2, "a", "102", "nom-ecrit-a-la-creation")],
        )

    def test_a_report_without_a_name_falls_back_on_the_level(self):
        rapport = {"etages": [{"niveau": 3, "vmid": 103, "parent_alias": "b"}]}
        self.assertEqual(
            self.dp.a_defaire(rapport, self.dp.NOM_BASE),
            [(3, "b", "103", self.dp.nom_etage(3))],
        )


class TestLaCauseDUnMontageAbsent(unittest.TestCase):
    """« pve_unit_cmd » joint le journal de l'unité à un échec — « la seule
    façon de dire la cause à quelqu'un dont le seul accès à l'hôte est cet
    outil », dit son propre commentaire dans proxmox_deploy.py.

    reparer_pmxcfs le jetait. Quand le montage échouait ensuite, il ne restait
    qu'un « /etc/pve : ABSENT » sans cause, et il fallait retourner sur la
    machine pour la chercher — sur un hyperviseur imbriqué mesuré 36 fois plus
    lent que son hôte."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox
        self.d = deep_proxmox.Descente.__new__(deep_proxmox.Descente)
        self.d.dry_run = False
        self.d.journal = None
        self.d.niveau_courant = 3
        self.vrai_run = deep_proxmox.pve.run
        self.addCleanup(setattr, deep_proxmox.pve, "run", self.vrai_run)
        deep_proxmox.pve.run = lambda h, c, t=None: (
            0,
            "10.0.0.2 22 10.0.0.1 22",
        )

    def _monter(self, verdict, unite_ko=None):
        def executer(hote, cmd, delai, etiquette=""):
            if etiquette == "montage":
                return 0, f"MOUNT-{verdict}"
            if unite_ko and etiquette == unite_ko:
                return 1, "pmxcfs-KO\nquorum_initialize failed: 2"
            return 0, "OK"

        self.d.executer = executer
        vrai = self.dp.pve.parse_mount_wait
        self.dp.pve.parse_mount_wait = lambda out: {
            "verdict": "MONTE" if "MONTE" in out else "ABSENT"
        }
        self.addCleanup(setattr, self.dp.pve, "parse_mount_wait", vrai)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            res = self.d.remettre_debout({"target": "h", "sudo": "sudo "})
        return res, sortie.getvalue()

    def test_a_failing_unit_is_named_with_its_journal(self):
        unite = self.dp.pve.PVE_UNITS[0]
        res, texte = self._monter("ABSENT", unite_ko=unite)
        self.assertFalse(res)
        self.assertIn(unite, texte)
        self.assertIn("quorum_initialize failed", texte)

    def test_all_units_up_and_still_no_mount_is_said_so(self):
        # Le silence ici se lisait « on n'a pas regardé ».
        res, texte = self._monter("ABSENT")
        self.assertFalse(res)
        self.assertIn("toutes les unités PVE sont debout", texte)

    def test_a_successful_mount_stays_quiet(self):
        """Le contrôle NÉGATIF : ne pas déverser un journal quand tout va
        bien. Un diagnostic qui sort toujours ne se lit plus."""
        res, texte = self._monter("MONTE", unite_ko=self.dp.pve.PVE_UNITS[0])
        self.assertTrue(res)
        self.assertNotIn("↳", texte)


class TestUneLectureRateeNeConclutRien(unittest.TestCase):
    """De l'absence de pont, preparer_parent RECONFIGURE le réseau du parent.

    Les codes de retour des lectures étaient jetés. Un « ip link show » qui
    échoue — hoquet ssh, sudo pas encore prêt — se lisait « pas de pont », et
    on posait un pont et un NAT sur une machine qui en avait déjà un."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox
        self.d = deep_proxmox.Descente.__new__(deep_proxmox.Descente)
        self.d.dry_run = False
        self.d.journal = None
        self.d.niveau_courant = 2

    def _descente_qui_lit(self, reponses):
        """`reponses` : [(code, sortie)] rendus dans l'ordre des lectures."""
        faites = []

        def executer(hote, cmd, delai, etiquette=""):
            faites.append(etiquette or cmd[:20])
            return reponses[len(faites) - 1] if reponses else (0, "")

        self.d.executer = executer
        return faites

    def test_an_unreadable_bridge_list_touches_nothing(self):
        faites = self._descente_qui_lit(
            [
                (0, "local-lvm  lvmthin  active  1  1  1  1.00%"),
                (255, ""),  # « ip link show » : échec de transport
            ]
        )
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertIsNone(self.d.preparer_parent({"target": "p"}))
        # Rien après la lecture ratée : pas de USED_NETS_CMD, pas de « pont ».
        self.assertEqual(faites, ["pvesm", "ponts"])
        self.assertIn("on ne touche PAS au réseau", sortie.getvalue())

    def test_an_empty_but_successful_read_does_create_the_bridge(self):
        """Le contrôle NÉGATIF. Sans lui, ce garde-fou interdirait la seule
        chose que preparer_parent est là pour faire."""
        faites = self._descente_qui_lit(
            [
                (0, "local-lvm  lvmthin  active  1  1  1  1.00%"),
                (0, ""),  # lu, et il n'y a vraiment aucun pont
                (0, ""),  # USED_NETS_CMD
                (0, "default via 10.0.0.1 dev eth0"),
            ]
            + [(0, "")] * 12
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.d.preparer_parent({"target": "p"})
        self.assertIn("réseaux", faites)
        self.assertIn("pont", faites)

    def test_an_unreadable_storage_list_is_named_as_such(self):
        faites = self._descente_qui_lit([(255, "")])
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertIsNone(self.d.preparer_parent({"target": "p"}))
        self.assertEqual(faites, ["pvesm"])
        texte = sortie.getvalue()
        self.assertIn("a échoué", texte)
        # Et NON « aucun stockage » : ce serait imputer au parent un défaut
        # qu'on n'a pas constaté.
        self.assertNotIn("aucun stockage", texte)


class TestUneVmCreeeEstToujoursNommee(unittest.TestCase):
    """Le VMID ne remontait qu'au RETOUR de creer_enfant.

    Or celle-ci enchaîne six commandes sur le parent. Un échec à la quatrième
    — « qm resize » sur un stockage plein — laissait une VM allumée et un
    disque alloué que le rapport ne nommait nulle part : « --detruire » ne
    pouvait pas la défaire, et il fallait la retrouver par son NOM."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox
        self.dossier = tempfile.mkdtemp(prefix="longtest-vmid-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)

    def test_a_creation_that_dies_midway_still_names_the_vm(self):
        niveaux = [
            {"niveau": n, "vcpu": 2, "ram": 4096, "disque": 25} for n in (1, 2)
        ]
        chemin = os.path.join(self.dossier, "rapport.json")
        d = self.dp.Descente(
            {"demandee": 2, "atteignable": 2, "niveaux": niveaux},
            None,
            False,
            chemin,
        )
        d.creer_etage1 = lambda res: "deep-pve-1"
        d.preparer_parent = lambda parent: (
            "local-lvm",
            "vmbr1",
            {},
            "1.1.1.1",
        )
        d.ecrire_alias = lambda *a, **k: None
        d.attendre_ssh = lambda cible, delai, parent=None: 1
        d.installer = lambda cible: True
        d.redemarrer_et_verifier = lambda cible: True
        d.remettre_debout = lambda cible: True
        d.preparer_systeme = lambda cible: True
        d.controler = lambda cible: True

        # La création note son VMID, puis MEURT — comme « qm resize » sur un
        # stockage plein.
        def creer_enfant(parent, niveau, res, prep, noter=None):
            noter(142)
            return None, None

        d.creer_enfant = creer_enfant
        with contextlib.redirect_stdout(io.StringIO()):
            d.parcourir()
        with open(chemin, encoding="utf-8") as fh:
            rapport = json.load(fh)
        self.assertEqual(
            self.dp.a_defaire(rapport, self.dp.NOM_BASE),
            [(2, "deep-pve-1", "142", self.dp.nom_etage(2))],
        )

    def test_the_vmid_is_announced_before_the_creating_commands(self):
        """Par l'ORDRE, pas par le résultat : noter après la première commande
        laisserait déjà passer un « qm create » réussi suivi d'un échec."""
        import inspect

        src = inspect.getsource(self.dp.Descente.creer_enfant)
        i_noter = src.index("noter(vmid)")
        i_boucle = src.index("for cmd in [pve.image_fetch_cmd")
        self.assertLess(i_noter, i_boucle)


class TestNePasAttendreUneMaisonDisparue(unittest.TestCase):
    """L'étage 1 a redémarré pendant l'installation de l'étage 4, éteignant
    les étages 2, 3 et 4 d'un coup.

    La descente a attendu son délai entier — quarante minutes — un ssh qui ne
    pouvait plus aboutir, puis a conclu « jamais joignable en ssh ». Le
    diagnostic était faux : la machine n'était pas lente, sa MAISON n'existait
    plus."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox
        self.vrai_run = deep_proxmox.pve.run
        self.addCleanup(setattr, deep_proxmox.pve, "run", self.vrai_run)
        self.d = deep_proxmox.Descente.__new__(deep_proxmox.Descente)
        self.d.dry_run = False
        self.d.journal = None

    def _cibles(self):
        return (
            {"target": "enfant", "sudo": "sudo ", "jump": ""},
            {"target": "parent", "sudo": "sudo ", "jump": ""},
        )

    def test_it_gives_up_as_soon_as_the_parent_stops_answering(self):
        appels = []

        def faux(hote, cmd, timeout=None):
            appels.append(hote["target"])
            # Une borne DURE : si le garde-fou disparaissait, la boucle
            # sonderait l'enfant jusqu'à l'expiration du délai. On la fait
            # éclater au troisième tour plutôt que de laisser le test tourner
            # — et ce test-ci doit échouer vite quand le code régresse.
            if appels.count("enfant") > 2:
                raise AssertionError(f"sondé sans fin : {appels[:6]}")
            return 255, ""

        self.dp.pve.run = faux
        enfant, parent = self._cibles()
        vrai_sleep = time.sleep
        time.sleep = lambda _s: None
        self.addCleanup(setattr, time, "sleep", vrai_sleep)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            res = self.d.attendre_ssh(enfant, 45, parent)
        self.assertIsNone(res)
        # DEUX sondes, et c'est tout : l'enfant, puis sa maison. Sans le
        # garde-fou la liste comptait autant d'« enfant » que le délai le
        # permet, et la descente attendait pour rien.
        self.assertEqual(appels, ["enfant", "parent"])
        self.assertIn("ne répond plus", sortie.getvalue())

    def test_a_slow_child_with_a_living_parent_is_still_waited_for(self):
        """Le contrôle NÉGATIF : un étage lent n'est pas un étage mort. Sans
        lui, ce garde-fou abandonnerait toute descente profonde."""
        etat = {"tours": 0}

        def faux(hote, cmd, timeout=None):
            if hote["target"] == "parent":
                return 0, ""  # la maison tient
            etat["tours"] += 1
            return (0, "") if etat["tours"] >= 3 else (255, "")

        self.dp.pve.run = faux
        self.dp.time = time  # même horloge
        enfant, parent = self._cibles()
        vrai_sleep = time.sleep
        time.sleep = lambda _s: None
        self.addCleanup(setattr, time, "sleep", vrai_sleep)
        with contextlib.redirect_stdout(io.StringIO()):
            res = self.d.attendre_ssh(enfant, 3600, parent)
        self.assertIsNotNone(res)
        self.assertEqual(etat["tours"], 3)

    def test_without_a_parent_the_behaviour_is_unchanged(self):
        # L'étage 1 n'a pas de parent : il tourne sur du métal.
        self.dp.pve.run = lambda hote, cmd, timeout=None: (0, "")
        enfant, _ = self._cibles()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.d.attendre_ssh(enfant, 60), 0)


class TestLeMenuDesDeuxTests(unittest.TestCase):
    """La liste des choix et le dispatch sont couplés PAR POSITION, sans
    garde : ajouter une entrée sans son branchement donne un menu qui affiche
    une option et répond « commande inconnue »."""

    def setUp(self):
        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)

    def test_every_listed_choice_has_a_branch(self):
        """fill_help_info numérote à partir de 1 : le choix n° i doit être
        traité, sinon le menu affiche une option et répond « commande
        inconnue »."""
        import inspect

        src = inspect.getsource(self.todo.prompt_execute_longtest)
        entrees = src.count('"prompt_description"')
        self.assertGreaterEqual(entrees, 5, "le menu a perdu des entrées")
        for i in range(1, entrees + 1):
            self.assertIn(
                f'"{i}"', src, f"le choix {i} est affiché mais pas traité"
            )
        # Et rien au-delà : un branchement sans entrée est un choix caché.
        self.assertNotIn(f'"{entrees + 1}"', src)

    def test_both_stacks_are_offered(self):
        import inspect

        src = inspect.getsource(self.todo.prompt_execute_longtest)
        self.assertIn("deep_proxmox.py", src)
        self.assertIn("deep_qemu.py", src)

    def test_undoing_asks_each_stack_separately(self):
        """Chacun ne connaît que ses rapports : lancer les deux ne peut pas
        faire détruire à l'un ce que l'autre a créé."""
        import inspect

        src = inspect.getsource(self.todo._longtest_defaire)
        self.assertIn("deep_proxmox.py", src)
        self.assertIn("deep_qemu.py", src)
        # À BLANC d'abord, toujours : un choix d'une touche ne doit pas mener
        # droit à « qm destroy --purge ».
        self.assertLess(
            src.index("--detruire --dry-run"), src.index('"--detruire"')
        )

    def test_the_host_options_are_built_from_the_host_dict(self):
        self.assertEqual(
            self.todo._longtest_args_hote({"target": "pve9", "jump": ""}),
            " --hote pve9",
        )
        self.assertEqual(
            self.todo._longtest_args_hote({"target": "vm", "jump": "porte"}),
            " --hote vm --jump porte",
        )

    def test_a_fresh_vm_is_the_default_answer(self):
        """Toute réponse hors plage retombe sur l'option 1 : le menu ne doit
        jamais partir d'un hôte qu'on n'a pas désigné."""
        import builtins

        vrai = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai)
        self.todo._pve_host = lambda ask=True: None
        for reponse in ("", "1", "n'importe quoi", "9"):
            with self.subTest(reponse=reponse):
                builtins.input = lambda _p="", r=reponse: r
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        self.todo._longtest_depart("deep_proxmox.py"), ""
                    )

    def test_the_known_host_is_offered_without_being_searched(self):
        import builtins

        vrai = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai)
        demande = []
        self.todo._pve_host = lambda ask=True: demande.append(ask) or {
            "target": "root@10.0.0.5",
            "jump": "",
            "version": "9.2.11",
        }
        builtins.input = lambda _p="": "2"
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            args = self.todo._longtest_depart("deep_proxmox.py")
        self.assertEqual(args, " --hote root@10.0.0.5")
        # Sans rien demander : c'est tout l'intérêt de _pve_host(ask=False).
        self.assertEqual(demande, [False])
        self.assertIn("9.2.11", sortie.getvalue())

    def test_a_qemu_descent_does_not_ask_for_a_proxmox(self):
        """Le sélecteur Proxmox VÉRIFIE « pveversion » : le proposer pour une
        descente QEMU refuserait un hôte libvirt parfaitement bon."""
        import builtins

        vrai = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai)
        reponses = iter(["3", "erplibre@10.0.0.7", ""])
        builtins.input = lambda _p="": next(reponses)
        self.todo._pve_pick_host = lambda: self.fail(
            "sélecteur Proxmox appelé"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            args = self.todo._longtest_depart("deep_qemu.py")
        self.assertEqual(args, " --hote erplibre@10.0.0.7")


class TestAucuneEtapeNeRepondNone(unittest.TestCase):
    """Une étape qui rend None dit « non » à l'appelant, sans dire pourquoi.

    Vécu : l'extraction du moteur avait coupé `preparer_systeme` sur le
    « return False » de sa boucle, sans son « return True » final. La descente
    affichait « ✗ étage 1 systeme » et pas une ligne de cause — et l'essai à
    blanc ne pouvait pas le voir, puisqu'il sort avant. Les deux piles étaient
    cassées, aucun test ne l'a vu."""

    CROCHETS = (
        "preparer_parent",
        "creer_enfant",
        "installer",
        "noyau_convient",
        "remettre_debout",
        "controler",
        "preparer_systeme",
        "redemarrer_et_verifier",
    )

    def test_no_step_can_fall_through_to_none(self):
        """Par l'AST, sur les trois fichiers : le dernier énoncé du corps d'une
        étape doit être un return ou un raise, jamais une boucle ou un if dont
        on peut sortir."""
        import ast

        chutes = []
        for chemin in (
            "long_test/descente.py",
            "long_test/deep_proxmox.py",
            "long_test/deep_qemu.py",
        ):
            arbre = ast.parse(
                open(os.path.join(RACINE, chemin), encoding="utf-8").read()
            )
            for noeud in ast.walk(arbre):
                if (
                    isinstance(noeud, ast.FunctionDef)
                    and noeud.name in self.CROCHETS
                ):
                    dernier = noeud.body[-1]
                    if isinstance(
                        dernier, (ast.For, ast.While, ast.If, ast.Try)
                    ):
                        chutes.append(f"{chemin}:{noeud.lineno} {noeud.name}")
        self.assertEqual(chutes, [])

    def test_the_real_path_of_preparer_systeme_answers_true(self):
        """Éprouvé sur le vrai chemin, pas seulement à blanc : c'est l'essai à
        blanc qui masquait le défaut, en sortant avant."""
        d = moteur.Descente.__new__(moteur.Descente)
        d.dry_run = False
        d.journal = None
        d.niveau_courant = 1
        d.executer = lambda h, c, delai, etiquette="", **k: (0, "OK")
        vrai = moteur.pve.run
        moteur.pve.run = lambda h, r, t=120: (0, "10.0.0.2 22 10.0.0.1 22")
        self.addCleanup(setattr, moteur.pve, "run", vrai)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIs(d.preparer_systeme({"target": "h"}), True)

    def test_a_failing_repair_answers_false_and_says_which(self):
        d = moteur.Descente.__new__(moteur.Descente)
        d.dry_run = False
        d.journal = None
        d.niveau_courant = 1
        d.executer = lambda h, c, delai, etiquette="", **k: (0, "hosts-KO")
        vrai = moteur.pve.run
        moteur.pve.run = lambda h, r, t=120: (0, "10.0.0.2 22 10.0.0.1 22")
        self.addCleanup(setattr, moteur.pve, "run", vrai)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertIs(d.preparer_systeme({"target": "h"}), False)
        # Et il DIT laquelle : un « ✗ » sans cause envoie chercher partout.
        self.assertIn("gel cloud-init", sortie.getvalue())

    def test_an_unknown_access_address_is_named(self):
        d = moteur.Descente.__new__(moteur.Descente)
        d.dry_run = False
        d.journal = None
        d.niveau_courant = 1
        vrai = moteur.pve.run
        moteur.pve.run = lambda h, r, t=120: (0, "")
        self.addCleanup(setattr, moteur.pve, "run", vrai)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertFalse(d.preparer_systeme({"target": "h"}))
        self.assertIn("adresse d'accès inconnue", sortie.getvalue())


class TestPartirDunHoteExistant(unittest.TestCase):
    """Créer une VM de tête pour héberger un hyperviseur qu'on possède déjà
    coûte cinq minutes ET un étage d'imbrication — donc de la lenteur."""

    def test_the_remote_capacity_is_read_as_the_machine_writes_it(self):
        # Sortie RÉELLE, prise sur un hôte du parc.
        vrai = "COEURS=8\nMEM=MemAvailable:    7056288 kB\nDISQUE=   7G\n"
        self.assertEqual(moteur.parse_capacite(vrai), (8, 6890, 7))

    def test_a_missing_line_reads_as_zero_not_as_a_guess(self):
        """Un plan dimensionné sur une capacité SUPPOSÉE annoncerait des
        étages qui ne tiennent pas."""
        self.assertEqual(moteur.parse_capacite(""), (0, 0, 0))
        self.assertEqual(moteur.parse_capacite("COEURS=4\n"), (4, 0, 0))

    def test_the_capacity_probe_is_written_for_dash(self):
        for interdit in ("[[", "pipefail", "$("):
            self.assertNotIn(interdit, moteur.CAPACITE_CMD, interdit)

    def test_sudo_is_deduced_not_assumed(self):
        """Sur un hôte joint en root, préfixer de « sudo » échoue là où
        l'image n'en a pas ; en utilisateur, ne pas le mettre échoue
        partout."""
        reponses = {}
        moteur.pve.run = lambda h, r, t=120: reponses.get(r, (0, ""))
        self.addCleanup(setattr, moteur.pve, "run", moteur.pve.run)
        vrai = moteur.pve.run

        reponses["id -u"] = (0, "0\n")
        self.assertEqual(moteur.joindre_racine("h")["sudo"], "")
        reponses["id -u"] = (0, "1000\n")
        self.assertEqual(moteur.joindre_racine("h")["sudo"], "sudo ")
        moteur.pve.run = vrai

    def test_an_unreachable_root_is_refused_not_guessed(self):
        vrai = moteur.pve.run
        moteur.pve.run = lambda h, r, t=120: (255, "")
        self.addCleanup(setattr, moteur.pve, "run", vrai)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertIsNone(moteur.joindre_racine("nulle-part"))
        self.assertIn("injoignable", sortie.getvalue())

    def test_the_delays_count_the_absolute_depth(self):
        """Un enfant de niveau 1 posé dans une racine DÉJÀ au troisième étage
        est en réalité au quatrième. Sans cela il héritait des délais du
        premier : quatre fois trop courts."""
        d = moteur.Descente.__new__(moteur.Descente)
        d.niveau_courant = 1
        d.profondeur_racine = 0
        seul = d.delai("ssh")
        d.profondeur_racine = 3
        self.assertEqual(d.delai("ssh"), seul * 16)

    def test_a_borrowed_root_is_never_a_level_that_was_reached(self):
        """L'y compter décalerait de un le total ET le code de sortie."""
        d = moteur.Descente.__new__(moteur.Descente)
        d.plan = {"demandee": 2, "atteignable": 2}
        d.etages = [{"niveau": 1, "ok": True}]
        d.dry_run = False
        d.OUTIL = "deep_proxmox"
        d.racine = {"target": "mon-proxmox"}
        d.profondeur_racine = 2
        etat = d._etat(interrompu=False)
        self.assertEqual(etat["atteinte"], 1)
        self.assertEqual(len(etat["etages"]), 1)
        # Elle est dite, mais à part — et jamais « cree ».
        self.assertEqual(etat["racine"]["alias"], "mon-proxmox")
        self.assertEqual(etat["racine"]["profondeur"], 2)
        self.assertFalse(etat["racine"]["cree"])

    def test_without_a_root_the_report_says_so(self):
        d = moteur.Descente.__new__(moteur.Descente)
        d.plan = {"demandee": 1, "atteignable": 1}
        d.etages = []
        d.dry_run = False
        d.OUTIL = "deep_proxmox"
        self.assertIsNone(d._etat(interrompu=False)["racine"])

    def test_the_first_level_is_local_only_without_a_root(self):
        """Avec une racine, TOUS les étages sont des enfants — le premier
        compris. Sans elle, le premier est une VM créée en local."""
        import inspect

        src = inspect.getsource(moteur.Descente.parcourir)
        self.assertIn("if parent is None:", src)
        self.assertNotIn("if niveau == 1:", src)


class TestDeuxPilesNeSeMelangentPas(unittest.TestCase):
    """Le dossier des rapports et le motif « *.json » sont PARTAGÉS.

    Depuis qu'il y a deux tests longs, « deep_qemu --detruire » prendrait le
    rapport le plus récent — pouvant être celui d'une descente Proxmox — et
    lancerait « virsh undefine » d'après des VMID de Proxmox."""

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="longtest-piles-")
        self.dossier = os.path.join(self.maison, ".erplibre/longtest")
        os.makedirs(self.dossier)
        self._vrai = os.environ.get("HOME")
        os.environ["HOME"] = self.maison
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)

    def tearDown(self):
        if self._vrai is not None:
            os.environ["HOME"] = self._vrai

    def _ecrire(self, nom, rapport):
        with open(
            os.path.join(self.dossier, nom), "w", encoding="utf-8"
        ) as fh:
            json.dump(rapport, fh)

    def _etage(self):
        return [{"niveau": 2, "identite": "102", "parent_alias": "a"}]

    def test_each_tool_only_sees_its_own_reports(self):
        self._ecrire(
            "deep-pve-20260101-000000.json",
            {
                "dry_run": False,
                "outil": "deep_proxmox",
                "etages": self._etage(),
            },
        )
        self._ecrire(
            "deep-qemu-20260102-000000.json",
            {"dry_run": False, "outil": "deep_qemu", "etages": self._etage()},
        )
        with contextlib.redirect_stdout(io.StringIO()):
            pve = moteur.dernier_rapport("deep_proxmox", "deep-pve")
            qemu = moteur.dernier_rapport("deep_qemu", "deep-qemu")
        self.assertTrue(
            pve["fichier"].endswith("deep-pve-20260101-000000.json")
        )
        self.assertTrue(
            qemu["fichier"].endswith("deep-qemu-20260102-000000.json")
        )

    def test_an_older_report_without_a_tool_is_placed_by_its_filename(self):
        """Les rapports écrits avant que ce champ existe n'ont pas d'outil.
        Les refuser les rendrait indéfaisables ; les accepter sans regarder
        ramènerait le danger. Le nom de fichier tranche."""
        self._ecrire(
            "deep-pve-20260101-000000.json",
            {"dry_run": False, "etages": self._etage()},
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(moteur.dernier_rapport("deep_proxmox", "deep-pve"))
            self.assertFalse(moteur.dernier_rapport("deep_qemu", "deep-qemu"))

    def test_a_report_is_never_handed_to_the_wrong_tool(self):
        self._ecrire(
            "deep-pve-20260103-000000.json",
            {
                "dry_run": False,
                "outil": "deep_proxmox",
                "etages": self._etage(),
            },
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(moteur.dernier_rapport("deep_qemu", "deep-qemu"))

    def test_the_lock_looks_for_every_descent_script(self):
        """Deux descentes de piles différentes se disputent la RAM, le disque
        et ~/.ssh/config aussi sûrement que deux de la même."""
        import inspect

        src = inspect.getsource(moteur._lance_une_descente)
        self.assertIn("SCRIPTS", src)
        self.assertIn("deep_proxmox.py", moteur.SCRIPTS)
        self.assertIn("deep_qemu.py", moteur.SCRIPTS)


class TestNeDetruirePasCeQuOnNaPasCree(unittest.TestCase):
    """Une descente peut PARTIR d'une machine existante.

    Ce qui protégeait jusqu'ici un hôte non créé était un effet de bord :
    a_defaire exigeait deux clés que seule une descente écrit. Depuis qu'un
    hôte emprunté peut figurer au rapport, il faut le DIRE."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox

    def test_a_borrowed_level_is_never_in_the_destroy_list(self):
        rapport = {
            "etages": [
                {
                    "niveau": 1,
                    "identite": "9",
                    "parent_alias": "x",
                    "cree": False,
                },
                {
                    "niveau": 2,
                    "identite": "102",
                    "parent_alias": "a",
                    "cree": True,
                },
            ]
        }
        niveaux = [
            n for n, _p, _i, _nom in moteur.a_defaire(rapport, "deep-pve")
        ]
        self.assertEqual(niveaux, [2])

    def test_a_borrowed_root_is_not_undefined_by_name(self):
        """Une descente partie d'un hôte existant n'a JAMAIS d'UUID libvirt
        local. Le repli par le nom aurait effacé un homonyme, disques
        compris."""
        lances = []

        def faux(argv, **kw):
            import types

            lances.append(" ".join(argv))
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        vrai = moteur.subprocess.run
        moteur.subprocess.run = faux
        self.addCleanup(setattr, moteur.subprocess, "run", vrai)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            res = moteur.detruire_etage1(None, "machine-a-moi", cree=False)
        self.assertTrue(res)
        self.assertIn("pas créé par cette descente", sortie.getvalue())
        self.assertFalse(
            [c for c in lances if "undefine" in c or "destroy" in c], lances
        )

    def test_a_borrowed_alias_stays_in_the_users_ssh_config(self):
        vus = {}
        import script.todo.todo as module_todo

        vrai = module_todo.TODO._write_ssh_config_entry
        module_todo.TODO._write_ssh_config_entry = (
            lambda self, host, user, ip, **kw: vus.update(
                drop=kw.get("also_drop")
            )
        )
        self.addCleanup(
            setattr, module_todo.TODO, "_write_ssh_config_entry", vrai
        )
        with contextlib.redirect_stdout(io.StringIO()):
            moteur.retirer_alias(
                {
                    "etages": [
                        {"niveau": 1, "alias": "mon-proxmox", "cree": False},
                        {"niveau": 2, "alias": "mon-proxmox+deep-pve-2"},
                    ]
                },
                nom_base="deep-pve",
            )
        self.assertEqual(vus["drop"], ("mon-proxmox+deep-pve-2",))

    def test_destroying_the_level_one_requires_a_name(self):
        """« virsh undefine --remove-all-storage » ne devine pas sa cible. Le
        repli nom_etage(1) désignait la machine numéro 1 de la pile, quelle
        que soit celle dont parlait le rapport."""
        import inspect

        signature = inspect.signature(moteur.detruire_etage1)
        self.assertIs(
            signature.parameters["nom"].default, inspect.Parameter.empty
        )


class TestLeDecompteDeLaDestruction(unittest.TestCase):
    """« if not detruire_etage1(…) : faits -= 1 » — un succès de l'étage 1
    n'ajoutait RIEN, alors que le total est len(liste) + 1.

    Le décompte était décalé de un dans TOUS les cas : une destruction
    complète annonçait « il reste des machines » et sortait 1. Le seul
    avertissement censé prévenir qu'un disque de plusieurs dizaines de Go
    reste alloué s'affichait toujours — on apprend à ne plus le lire."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "long_test"))
        import deep_proxmox

        self.dp = deep_proxmox
        # Pris ET rendus sur le MOTEUR. La première version les prenait sur
        # deep_proxmox et les rendait là aussi, alors qu'elle les posait sur
        # descente : les bouchons fuyaient sur tous les tests suivants, qui
        # inspectaient une lambda au lieu de la vraie fonction.
        self._vrais = {
            nom: getattr(moteur, nom)
            for nom in (
                "autre_descente",
                "dernier_rapport",
                "detruire_etage1",
                "retirer_alias",
            )
        }
        self._vraie_detruire_une = self.dp.FAMILLE.detruire_une
        self.addCleanup(
            setattr, self.dp.FAMILLE, "detruire_une", self._vraie_detruire_une
        )
        moteur.autre_descente = lambda: []
        moteur.retirer_alias = lambda *a, **k: None
        moteur.dernier_rapport = lambda outil="", prefixe="": {
            "fichier": "/x.json",
            "etages": [
                {"niveau": 3, "vmid": 103, "parent_alias": "a+b"},
                {"niveau": 2, "vmid": 102, "parent_alias": "a"},
            ],
        }
        self._entree = (
            __builtins__["input"]
            if isinstance(__builtins__, dict)
            else __builtins__.input
        )

    def tearDown(self):
        for nom, vrai in self._vrais.items():
            setattr(moteur, nom, vrai)
        import builtins

        builtins.input = self._entree

    def _lancer(self, etage1_ok, une=True):
        import builtins

        builtins.input = lambda _prompt="": "OUI"
        self.dp.FAMILLE.detruire_une = lambda *a, **k: une
        moteur.detruire_etage1 = lambda *a, **k: etage1_ok
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            code = self.dp.detruire(self.dp.FAMILLE, None, dry_run=False)
        return code, sortie.getvalue()

    def test_a_complete_destruction_reports_success(self):
        code, texte = self._lancer(etage1_ok=True)
        self.assertEqual(code, 0)
        self.assertIn("3 / 3", texte)
        self.assertNotIn("⚠", texte)

    def test_unreachable_levels_go_with_the_root_disk(self):
        """Mesuré sur un arbre réel : les étages 3 et 4 étaient injoignables
        — leur parent était éteint — et le compte disait « 2 / 4, il reste des
        machines ». Or « virsh undefine --remove-all-storage » sur l'étage 1
        efface le disque où ils VIVENT. L'avertissement était faux dans
        l'autre sens, et un avertissement faux ne se lit plus."""
        self.dp.FAMILLE.detruire_une = lambda *a, **k: False
        code, texte = self._lancer(etage1_ok=True, une=False)
        self.assertEqual(code, 0)
        self.assertIn("3 / 3", texte)
        self.assertIn("emporté(s) avec le disque de l'étage 1", texte)

    def test_a_surviving_level_one_is_the_only_real_warning(self):
        # Là, et là seulement, quelque chose vit encore : le disque est
        # debout, et tout ce qu'il contient avec lui.
        code, texte = self._lancer(etage1_ok=False)
        self.assertEqual(code, 1)
        self.assertIn("l'étage 1 est DEBOUT", texte)

    def test_the_ssh_aliases_of_a_destroyed_descent_are_removed(self):
        """Elles survivaient aux machines : des entrées mortes dont le
        ProxyJump désigne un hôte qui n'existe plus."""
        retires = []
        moteur.retirer_alias = (
            lambda rapport, journal=None, nom_base="": retires.append(
                [e.get("alias") for e in rapport["etages"]]
            )
        )
        self._lancer(etage1_ok=True)
        self.assertEqual(len(retires), 1)

    def test_the_aliases_are_computed_when_the_report_lacks_them(self):
        """Un étage abandonné avant l'écriture de son alias en a tout de même
        un : il est déterminé par (niveau, alias du parent)."""
        vus = {}
        import script.todo.todo as module_todo

        vrai = module_todo.TODO._write_ssh_config_entry

        def espion(self, host, user, ip, **kw):
            vus["drop"] = kw.get("also_drop")

        module_todo.TODO._write_ssh_config_entry = espion
        self.addCleanup(
            setattr, module_todo.TODO, "_write_ssh_config_entry", vrai
        )
        with contextlib.redirect_stdout(io.StringIO()):
            # La VRAIE fonction : setUp en a posé un bouchon pour les autres
            # tests de cette classe.
            self._vrais["retirer_alias"](
                nom_base=self.dp.NOM_BASE,
                rapport={
                    "etages": [
                        {"niveau": 1, "alias": "deep-pve-1"},
                        {"niveau": 2, "parent_alias": "deep-pve-1"},
                    ]
                },
            )
        self.assertEqual(
            vus["drop"],
            ("deep-pve-1", self.dp.alias_etage(2, "deep-pve-1")),
        )


class TestLeMenu(unittest.TestCase):
    def test_the_mixin_is_wired_into_TODO(self):
        todo = TODO.__new__(TODO)
        self.assertTrue(hasattr(todo, "prompt_execute_longtest"))

    def test_the_script_is_found_from_the_repository_root(self):
        todo = TODO.__new__(TODO)
        ancien = os.getcwd()
        try:
            os.chdir(RACINE)
            self.assertTrue(todo._longtest_script("deep_proxmox.py"))
            self.assertFalse(todo._longtest_script("nexiste-pas.py"))
        finally:
            os.chdir(ancien)

    def test_the_test_menu_offers_it(self):
        import inspect

        src = inspect.getsource(TODO.prompt_execute_test)
        self.assertIn("prompt_execute_longtest", src)
        self.assertIn("Long tests", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
