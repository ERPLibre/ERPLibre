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
    "QEMU cache - Install the download mirror for local VMs",
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
)


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
            "QEMU cache - Install the download mirror for local VMs",
            self.corps,
            "l'entrée du cache ne s'affiche pas dans le menu Déploiement",
        )

    def test_entree_dispatchee(self):
        self.assertRegex(
            self.corps,
            r'elif status == "8":\s*\n\s*self\._deploy_qemu_cache\(\)',
            "l'entrée 8 ne mène pas à _deploy_qemu_cache",
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

    def test_icone_de_lentree(self):
        """L'icône vit DANS la chaîne traduite, comme partout ailleurs dans le
        menu : les deux langues doivent donc la porter."""
        entree = todo_i18n.TRANSLATIONS[
            "QEMU cache - Install the download mirror for local VMs"
        ]
        for langue in ("fr", "en"):
            self.assertTrue(
                entree[langue].startswith("📦"),
                f"le {langue} ne porte pas l'icône : {entree[langue]}",
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
