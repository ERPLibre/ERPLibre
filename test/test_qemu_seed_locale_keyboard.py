#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le seed ne demande à l'invité que ce que son image sait honorer.

Deux réglages régionaux échouaient sur toute VM Debian, et le seul signe en
était le mot « error » dans le compte-rendu de cloud-init que le déploiement
imprime — un mot qui, s'il s'affiche à chaque fois, n'avertit plus de rien.

- le LOCALE : « update-locale LANG=xx_YY.UTF-8 » refuse un locale qui n'est
  pas généré, et un locale ne se génère qu'à partir de /etc/locale.gen. La VM
  restait en C.UTF-8 ;
- le CLAVIER : le module de cloud-init finit par « systemctl restart
  console-setup », service absent de l'image genericcloud. Le réglage est
  écrit AVANT cet échec, dans /etc/default/keyboard — c'est le fichier que
  localed et X relisent —, donc le poser nous-mêmes ne perd rien d'autre que
  la disposition de la console texte, qui demande ce paquet.

Ces tests gardent aussi la contrainte qui domine toutes les autres ici : le
user-data reste un YAML valide. Une erreur de syntaxe fait rejeter la
configuration ENTIÈRE, sans message : la VM démarre sans compte ni clé.
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _deploy_qemu():
    chemin = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


def _cloud_config(distro, cache_ca=""):
    argv = ["--distro", distro, "--hostname", "x"]
    if cache_ca:
        argv += ["--cache-ca", cache_ca]
    args = DQ.build_parser().parse_args(argv)
    return DQ.build_cloud_config(args, None, ["ssh-ed25519 AAAA essai"])


class LeLocale(unittest.TestCase):
    def test_the_locale_is_generated_before_cloud_init_applies_it(self):
        """« bootcmd » et non « runcmd » : le premier tourne à l'étape init,
        avant les modules de configuration dont « locale » fait partie. Le
        second viendrait après, et n'aurait plus rien à rattraper."""
        lignes = DQ.locale_bootcmd_lines("fr_CA.UTF-8")
        self.assertEqual("bootcmd:", lignes[0])
        self.assertIn("locale-gen", lignes[1])

    def test_the_line_is_added_to_locale_gen_only_once(self):
        """bootcmd tourne à CHAQUE démarrage : sans le grep, /etc/locale.gen
        s'allonge d'une ligne identique par boot."""
        self.assertIn(
            "grep -qxF 'fr_CA.UTF-8 UTF-8'",
            " ".join(DQ.locale_bootcmd_lines("fr_CA.UTF-8")),
        )

    def test_a_host_without_locale_gen_is_left_alone(self):
        """Fedora, la famille RHEL et openSUSE embarquent leurs locales déjà
        générées, et n'ont pas ce fichier."""
        self.assertIn(
            "[ -f /etc/locale.gen ] || exit 0",
            " ".join(DQ.locale_bootcmd_lines("fr_CA.UTF-8")),
        )

    def test_a_builtin_locale_asks_for_nothing(self):
        """C.UTF-8 et POSIX sont dans la bibliothèque C, pas dans
        locale.gen : les demander ferait échouer locale-gen, donc bootcmd,
        donc cloud-init — l'erreur qu'on retire."""
        for locale in ("C.UTF-8", "POSIX", ""):
            with self.subTest(locale=locale):
                self.assertEqual([], DQ.locale_bootcmd_lines(locale))


class LeClavier(unittest.TestCase):
    def test_debian_gets_the_file_and_not_the_cloud_init_key(self):
        """Le module de cloud-init n'y aboutit pas : console-setup manque."""
        self.assertEqual([], DQ.keyboard_lines("debian", "ca", "multix"))
        fichiers = DQ.keyboard_files("debian", "ca", "multix")
        self.assertEqual("/etc/default/keyboard", fichiers[0][0])
        self.assertIn("XKBLAYOUT=ca", fichiers[0][2])
        self.assertIn("XKBVARIANT=multix", fichiers[0][2])

    def test_elsewhere_cloud_init_keeps_the_job(self):
        """Une VM Ubuntu applique le clavier sans erreur : lui retirer le
        bloc perdrait la disposition de sa console, elle qui l'obtient."""
        for distro in ("ubuntu", "fedora", "arch", "opensuse", "nixos"):
            with self.subTest(distro=distro):
                self.assertEqual(
                    ["keyboard:", "  layout: ca", "  variant: multix"],
                    DQ.keyboard_lines(distro, "ca", "multix"),
                )
                self.assertEqual([], DQ.keyboard_files(distro, "ca", "multix"))

    def test_the_file_carries_a_model(self):
        """localed lit les quatre champs ; un XKBMODEL vide laisse X deviner."""
        self.assertIn("XKBMODEL=", DQ.keyboard_files("debian", "ca", "")[0][2])


class LeSeedEntier(unittest.TestCase):
    """Ce que la configuration produite doit rester, distro par distro."""

    def setUp(self):
        if yaml is None:
            self.skipTest("PyYAML absent")

    def test_the_user_data_stays_valid_yaml(self):
        """Une erreur de syntaxe fait rejeter le user-data en ENTIER, sans
        message : la VM démarre nue, sans compte ni clé SSH."""
        for distro in ("debian", "ubuntu", "fedora", "arch", "nixos"):
            with self.subTest(distro=distro):
                doc = yaml.safe_load(_cloud_config(distro))
                self.assertIsInstance(doc, dict)
                self.assertIn("users", doc)

    def test_bootcmd_is_a_list_of_arguments_not_a_shell_string(self):
        """La forme [sh, -c, "…"] met le corps hors de portée de YAML :
        accolades, apostrophes et redirections y passent sans échappement."""
        doc = yaml.safe_load(_cloud_config("debian"))
        self.assertIsInstance(doc["bootcmd"][0], list)
        self.assertEqual(["sh", "-c"], doc["bootcmd"][0][:2])

    def test_debian_asks_cloud_init_for_no_keyboard(self):
        doc = yaml.safe_load(_cloud_config("debian"))
        self.assertIsNone(doc.get("keyboard"))
        chemins = [f["path"] for f in doc["write_files"]]
        self.assertIn("/etc/default/keyboard", chemins)

    def test_ubuntu_keeps_asking(self):
        doc = yaml.safe_load(_cloud_config("ubuntu"))
        self.assertEqual("ca", doc["keyboard"]["layout"])
        chemins = [f["path"] for f in doc["write_files"]]
        self.assertNotIn("/etc/default/keyboard", chemins)


class LAutoriteDuCacheDansLeSeedAssemble(unittest.TestCase):
    """Le clavier et l'autorité du cache arrivent par la MÊME clé.

    Trois écritures se disputent « write_files: » — le guide, l'autorité du
    cache, le clavier — et cloud-init n'en lit qu'UNE : un document qui porte
    la clé deux fois garde la dernière, sans erreur ni message. Ce qui est
    perdu ne se voit alors qu'à l'usage, chez l'invité, et seulement pour ce
    qui en dépendait.

    Les tests plus haut regardent les fonctions une à une ; ceux-ci regardent
    le document ASSEMBLÉ, seul endroit où cette collision existe.
    """

    def setUp(self):
        if yaml is None:
            self.skipTest("PyYAML absent")
        dossier = tempfile.mkdtemp(prefix="cache-ca-")
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        # Une autorité INVENTÉE : cache_files exige « BEGIN CERTIFICATE » et
        # ne lit rien d'autre du fichier. Reprendre celle d'un hôte réel
        # figerait dans le dépôt le certificat d'une machine.
        self.ca = os.path.join(dossier, "ca.crt")
        with open(self.ca, "w", encoding="utf-8") as fh:
            fh.write(
                "-----BEGIN CERTIFICATE-----\nZXNzYWk=\n"
                "-----END CERTIFICATE-----\n"
            )

    def _chemins(self, distro):
        doc = yaml.safe_load(_cloud_config(distro, self.ca))
        return [f["path"] for f in doc.get("write_files", [])]

    def test_the_key_appears_exactly_once(self):
        """Deux « write_files: » dans le même document : PyYAML garde le
        second et jette le premier, sans rien dire."""
        for distro in ("debian", "ubuntu", "fedora", "arch", "nixos"):
            with self.subTest(distro=distro):
                texte = _cloud_config(distro, self.ca)
                lignes = texte.splitlines()
                self.assertEqual(
                    1, lignes.count("write_files:"), "\n".join(lignes[:5])
                )

    def test_the_authority_reaches_the_assembled_document(self):
        """Ce qu'aucun test ne gardait : l'autorité peut disparaître du
        document tout en restant correcte dans cache_files."""
        for distro in ("debian", "ubuntu", "fedora", "arch", "opensuse"):
            with self.subTest(distro=distro):
                chemins = self._chemins(distro)
                self.assertTrue(
                    any(c.endswith(DQ.CACHE_CERT_NAME) for c in chemins),
                    chemins,
                )

    def test_debian_keeps_both_the_keyboard_and_the_authority(self):
        """La seule distribution qui demande les deux par write_files : si
        une écriture en écrase une autre, c'est ici que cela se voit."""
        chemins = self._chemins("debian")
        self.assertIn("/etc/default/keyboard", chemins)
        self.assertTrue(any(c.endswith(DQ.CACHE_CERT_NAME) for c in chemins))

    def test_the_trust_command_reaches_runcmd(self):
        """Le fichier posé sans la commande qui relit le magasin ne sert à
        rien : les deux moitiés voyagent séparément."""
        doc = yaml.safe_load(_cloud_config("debian", self.ca))
        self.assertTrue(
            any("update-ca-certificates" in str(c) for c in doc["runcmd"]),
            doc["runcmd"],
        )

    def test_a_declarative_system_gets_it_where_it_can_be_written(self):
        """Un système déclaratif n'a pas d'ancre PAR FICHIER, mais il reçoit
        l'autorité quand même : sous un chemin inscriptible, /etc étant
        généré depuis le store et monté en lecture seule.

        Il l'a longtemps reçue nulle part, et c'est ce qui lui fermait le
        hors ligne — le magasin est alors la seule source, et une VM
        soustraite n'a plus rien."""
        doc = yaml.safe_load(_cloud_config("nixos", self.ca))
        chemins = [f["path"] for f in doc.get("write_files", [])]
        autorite = [c for c in chemins if DQ.CACHE_CERT_NAME in c]
        self.assertEqual(1, len(autorite), chemins)
        self.assertFalse(autorite[0].startswith("/etc/"))
        # Et le reste du document lui parvient toujours.
        self.assertIn("users", doc)
        self.assertEqual("ca", doc["keyboard"]["layout"])


if __name__ == "__main__":
    unittest.main()
