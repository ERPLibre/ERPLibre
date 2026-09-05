#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'entrée « cache QEMU » du menu Déploiement mène-t-elle où elle le dit ?

Le sous-menu est écrit deux fois — une liste de `prompt_description` qui
numérote l'affichage, et une chaîne d'`elif status == "N"` qui dispatche.
Insérer une entrée au milieu décale les deux, et une seule erreur envoie
l'opérateur dans un autre écran sans que rien ne proteste : l'entrée du cache
est arrivée en 8, ce qui a poussé le VPN en 9.

Le test vérifie aussi que chaque clé i18n de l'entrée résout DANS LES DEUX
LANGUES. Une clé absente rend sa propre chaîne anglaise, donc un menu
français qui affiche de l'anglais est le symptôme d'une clé oubliée, et rien
ne lève.
"""

import ast
import re
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
TODO_PY = RACINE / "script" / "todo" / "todo.py"
sys.path.insert(0, str(RACINE / "script" / "todo"))

import todo_i18n  # noqa: E402

# Les clés que l'entrée emploie. Les tenir ICI, et non les relire du code,
# fait échouer le test quand une clé disparaît du dictionnaire.
CLES = (
    "QEMU cache - Download mirror for local VMs",
    "QEMU download cache for local VMs",
    "Cache - Install or reinstall",
    "Cache - Diagnose: does it serve?",
    "Cache - Service state",
    "Cache - VMs kept out of the cache",
    "Cache - Guide: how it works",
    "Cache - Tests and performance report",
    "Install the download cache shared by the QEMU VMs of this host",
    "HTTP port of the cache (default: 8898): ",
    "TLS port of the cache (default: 8899): ",
    "Cache directory (default: /var/cache/erplibre_go_qemu_cache): ",
    "Will write network rules on the host bridge:",
    "Only what leaves the VM subnet is redirected",
    "The rules exist only while the service runs",
    "Go is absent; the installer lays it down",
    "Install the QEMU download cache?",
    "Installing the QEMU download cache (requires sudo)...",
    "QEMU download cache installed and started",
    "Certificate authority a VM must trust: ",
    "The cache install failed, nothing is started",
    "QEMU cache install script not found: ",
    "No eviction is written: this cache never shrinks by itself",
    # Le sous-menu du service : allumer, éteindre, lire.
    "State of the cache service",
    "Stopping it removes the rules: no VM is redirected.",
    "starts at boot",
    "not at boot",
    "Service - Start (start)",
    "Service - Start at boot (enable)",
    "Service - Do not start at boot (disable)",
    "Service - Stop (stop)",
    "Service - Detailed state (status)",
    "Service - Logs (log)",
    "Access log, last requests:",
    # Les exceptions par adresse MAC : une VM soustraite au détournement.
    "VMs kept out of the download cache",
    "Exceptions - Remove the stale ones",
    "Exceptions - Remove one by its MAC",
    "No exception: every VM goes through the cache.",
    "MAC to give back to the cache",
    "VM gone",
    "Keep this VM out of the download cache",
    "Keep this VM out of the download cache? (y/N): ",
)

CACHE_PY = RACINE / "script" / "todo" / "qemu_cache_menu.py"


def corps_de(nom, suivant):
    """Le corps d'une méthode de qemu_cache_menu.py, dispatch compris."""
    src = CACHE_PY.read_text(encoding="utf-8")
    debut = src.index(f"def {nom}(self):")
    return src[debut : src.index(f"def {suivant}(self", debut)]


def affichage_et_dispatch(corps):
    """Rend (nombre d'entrées affichées, numéros atteignables, triés).

    Un numéro s'atteint de deux façons : une branche « status == "N" », ou
    une entrée d'une table qui associe le numéro à un verbe. Ne compter que
    les branches ferait passer pour un trou ce qu'une table couvre.

    Le zéro sort : il ferme le menu et n'est jamais affiché.
    """
    affichees = len(re.findall(r'"prompt_description": t\(', corps))
    numeros = set(re.findall(r'if status == "(\d+)":', corps))
    table = re.search(r"verbes = \{([^}]*)\}", corps)
    if table:
        numeros |= set(re.findall(r'"(\d+)":', table.group(1)))
    numeros.discard("0")
    return affichees, sorted(int(n) for n in numeros)


def corps_du_sous_menu():
    """Le corps de prompt_execute_deploy(), affichage et dispatch compris."""
    src = TODO_PY.read_text(encoding="utf-8")
    debut = src.index("def prompt_execute_deploy(self):")
    fin = src.index("def prompt_execute_deploy_ssh(self):", debut)
    return src[debut:fin]


class TestEntreeDuCache(unittest.TestCase):
    def setUp(self):
        self.corps = corps_du_sous_menu()

    def test_entree_affichee(self):
        self.assertIn(
            "QEMU cache - Download mirror for local VMs",
            self.corps,
            "l'entrée du cache ne s'affiche pas dans le menu Déploiement",
        )

    def test_entree_dispatchee(self):
        self.assertRegex(
            self.corps,
            r'elif status == "8":\s*\n\s*self\.prompt_execute_qemu_cache\(\)',
            "l'entrée 8 ne mène pas au sous-menu du cache",
        )

    def test_vpn_decale_en_neuf(self):
        """L'entrée insérée pousse le VPN : sans quoi deux entrées se
        partagent le numéro 8 et la seconde est inatteignable."""
        self.assertRegex(
            self.corps,
            r'elif status == "9":\s*\n\s*self\.prompt_execute_vpn\(\)',
            "le VPN n'a pas été décalé en 9",
        )

    def test_numeros_sans_trou_ni_doublon(self):
        numeros = [
            int(n) for n in re.findall(r'elif status == "(\d+)":', self.corps)
        ]
        self.assertEqual(
            numeros,
            sorted(numeros),
            f"les numéros du dispatch ne sont pas croissants : {numeros}",
        )
        self.assertEqual(
            len(numeros),
            len(set(numeros)),
            f"un numéro est dispatché deux fois : {numeros}",
        )
        self.assertEqual(
            numeros,
            list(range(1, len(numeros) + 1)),
            f"les numéros ne sont pas consécutifs à partir de 1 : {numeros}",
        )

    def test_methode_existe(self):
        src = TODO_PY.read_text(encoding="utf-8")
        self.assertIn(
            "def _deploy_qemu_cache(self):",
            src,
            "la méthode que le dispatch appelle n'existe pas",
        )


class TestSousMenusDuCache(unittest.TestCase):
    """Affichage et dispatch sont écrits deux fois, et rien ne les relie.

    La liste de `prompt_description` numérote l'écran ; la chaîne d'`elif
    status` décide où l'on va. Une entrée insérée au milieu de l'une sans
    l'autre envoie l'opérateur ailleurs qu'où il a lu, ou rend la dernière
    entrée inatteignable — dans les deux cas sans un mot d'erreur.
    """

    def verifier(self, nom, suivant, attendues):
        affichees, numeros = affichage_et_dispatch(corps_de(nom, suivant))
        self.assertEqual(
            affichees, attendues, f"{nom} n'affiche pas {attendues} entrées"
        )
        self.assertEqual(
            numeros,
            list(range(1, attendues + 1)),
            f"{nom} : le dispatch {numeros} ne suit pas l'affichage",
        )

    def test_le_menu_du_cache(self):
        self.verifier("prompt_execute_qemu_cache", "_cache_systemctl", 6)

    def test_le_menu_du_service(self):
        self.verifier("_cache_service", "_cache_journal_service", 6)

    def test_le_menu_des_exceptions(self):
        self.verifier("_cache_exceptions", "_cache_guide", 2)

    def test_letat_du_service_est_la_troisieme(self):
        """Sous le diagnostic, comme demandé : le décalage du guide et des
        tests est la moitié du changement, et c'est celle qui casse."""
        corps = corps_de("prompt_execute_qemu_cache", "_cache_systemctl")
        for numero, methode in (
            ("3", "_cache_service"),
            ("4", "_cache_exceptions"),
            ("5", "_cache_guide"),
            ("6", "_cache_tests"),
        ):
            self.assertRegex(
                corps,
                rf'elif status == "{numero}":\s*\n\s*self\.{methode}\(\)',
                f"l'entrée {numero} ne mène pas à {methode}",
            )

    def test_les_quatre_verbes_systemd(self):
        """start, enable, disable et stop, et pas un cinquième par erreur."""
        corps = corps_de("_cache_service", "_cache_journal_service")
        verbes = re.search(r"verbes = \{([^}]*)\}", corps)
        self.assertIsNotNone(verbes, "la table des verbes a disparu")
        self.assertEqual(
            re.findall(r'"(\w+)"', verbes.group(1))[1::2],
            ["start", "enable", "disable", "stop"],
        )


class TestToutesLesClesDuFichier(unittest.TestCase):
    """La liste CLES est tenue à la main, donc elle oublie.

    Ce contrôle-ci ne tient aucune liste : il relève par l'ARBRE tout appel
    « t("…") » du module et vérifie que le dictionnaire répond. Une clé
    absente ne lève pas — t() rend sa propre chaîne anglaise — et le symptôme
    est un menu français qui affiche une ligne en anglais, ce qu'aucun test de
    numérotation ne voit.
    """

    def test_chaque_appel_a_sa_traduction(self):
        arbre = ast.parse(CACHE_PY.read_text(encoding="utf-8"))
        cles = {
            n.args[0].value
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "t"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)
        }
        self.assertGreater(len(cles), 50, "le relevé n'a presque rien trouvé")
        manquantes = sorted(c for c in cles if c not in todo_i18n.TRANSLATIONS)
        self.assertEqual(
            manquantes,
            [],
            "clés employées mais absentes du dictionnaire — le menu français"
            f" affichera l'anglais : {manquantes}",
        )


class TestClesI18n(unittest.TestCase):
    def test_cles_presentes(self):
        manquantes = [c for c in CLES if c not in todo_i18n.TRANSLATIONS]
        self.assertEqual(
            manquantes, [], f"clés absentes du dictionnaire : {manquantes}"
        )

    def test_les_deux_langues_repondent(self):
        for cle in CLES:
            entree = todo_i18n.TRANSLATIONS[cle]
            for langue in ("fr", "en"):
                self.assertIn(langue, entree, f"« {cle} » n'a pas de {langue}")
                self.assertTrue(
                    entree[langue].strip(),
                    f"« {cle} » a un {langue} vide",
                )

    def test_le_francais_est_traduit(self):
        """Une valeur française identique à l'anglaise trahit une clé posée
        sans traduction. Les libellés purement techniques y échappent."""
        sans_traduction = [
            c
            for c in CLES
            if todo_i18n.TRANSLATIONS[c]["fr"]
            == todo_i18n.TRANSLATIONS[c]["en"]
        ]
        self.assertEqual(
            sans_traduction, [], f"non traduites : {sans_traduction}"
        )

    def test_icones_des_entrees(self):
        """L'icône vit DANS la chaîne traduite, comme partout ailleurs dans le
        menu : les deux langues doivent donc la porter."""
        attendues = {
            "QEMU cache - Download mirror for local VMs": "📦",
            "Cache - Install or reinstall": "📥",
            "Cache - Diagnose: does it serve?": "🔍",
            "Cache - Service state": "⚙",
            "Cache - VMs kept out of the cache": "🎫",
            "Cache - Guide: how it works": "📖",
            "Exceptions - Remove the stale ones": "🧹",
            "Exceptions - Remove one by its MAC": "✂",
            "Service - Start (start)": "▶",
            "Service - Start at boot (enable)": "🔗",
            "Service - Do not start at boot (disable)": "🚫",
            "Service - Stop (stop)": "⏹",
            "Service - Detailed state (status)": "📋",
            "Service - Logs (log)": "📜",
            "Cache - Tests and performance report": "🧪",
        }
        for cle, icone in attendues.items():
            entree = todo_i18n.TRANSLATIONS[cle]
            for langue in ("fr", "en"):
                self.assertTrue(
                    entree[langue].startswith(icone),
                    f"« {cle} » en {langue} ne porte pas {icone} :"
                    f" {entree[langue]}",
                )

    def test_aucune_cle_en_double(self):
        """Une clé en double écrase silencieusement la précédente."""
        src = (RACINE / "script" / "todo" / "todo_i18n.py").read_text(
            encoding="utf-8"
        )
        for cle in CLES:
            litteral = '    "%s": {' % cle.replace('"', '\\"')
            self.assertEqual(
                src.count(litteral),
                1,
                f"« {cle} » apparaît {src.count(litteral)} fois",
            )


if __name__ == "__main__":
    unittest.main()
