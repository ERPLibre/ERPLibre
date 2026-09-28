#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le gabarit se bâtit-il sans qu'une question reste à l'écran ?

Une installation sans surveillance ne tombe pas : elle ATTEND. Une réponse qui
manque devient une question posée à une console que personne ne regarde, et
rien ne distingue de l'extérieur une installation lente d'une installation
arrêtée. Ce qui est éprouvé ici tient donc en une phrase : tout ce que
l'installateur demande a une réponse écrite, et ce qui ne peut pas être
répondu fait refuser AVANT de démarrer quoi que ce soit.

Les adresses employées appartiennent au bloc que la RFC 5737 réserve à la
documentation : elles ne désignent aucune machine, ici ni ailleurs.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RACINE, "long_test"))

import setops_gabarit as G  # noqa: E402

# Bloc de documentation de la RFC 5737 : aucune de ces adresses n'est routée.
HOTE = "gabarit-essai"
ADRESSE = "192.0.2.10"
PASSERELLE = "192.0.2.1"
DNS = "192.0.2.53"

# Un hachage crypt(3) INVENTÉ : il a la forme, il n'ouvre rien,
# et il ne correspond à aucun secret.
HACHAGE = "$y$j9T$hachageInventePourLeTest$0123456789abcdefgh"

# Les types que debconf connaît. Une ligne dont le troisième champ n'en est pas
# un n'est pas une réponse : elle est ignorée, et la question revient.
TYPES = {
    "string",
    "boolean",
    "select",
    "multiselect",
    "note",
    "password",
    "text",
    "title",
    "error",
}


def lignes():
    return G.lignes_preseed(HOTE, ADRESSE, PASSERELLE, DNS, HACHAGE)


def reponse(lignes_vues, gabarit):
    """La valeur écrite pour `gabarit`, ou None si la question reste ouverte."""
    for ligne in lignes_vues:
        champs = ligne.split()
        if len(champs) >= 3 and champs[1] == gabarit:
            return " ".join(champs[3:])
    return None


class TestToutCeQuiEstDemandeAUneReponse(unittest.TestCase):
    def test_a_missing_parameter_answers_nothing_rather_than_partly(self):
        # Un preseed amputé n'échoue pas : il pose la question qui manque.
        for rang in range(4):
            vus = [HOTE, ADRESSE, PASSERELLE, DNS]
            vus[rang] = "   "
            with self.subTest(rang=rang):
                self.assertEqual(G.lignes_preseed(*vus, HACHAGE), ())
        self.assertEqual(
            G.lignes_preseed(
                HOTE, ADRESSE, PASSERELLE, DNS, HACHAGE, disque=""
            ),
            (),
        )
        # Contrôle positif : refuser toujours passerait les cinq précédents.
        self.assertTrue(lignes())

    def test_every_line_names_a_template_and_a_type(self):
        for ligne in lignes():
            champs = ligne.split()
            with self.subTest(ligne=ligne[:48]):
                self.assertGreaterEqual(len(champs), 3)
                self.assertIn("/", champs[1])
                self.assertIn(champs[2], TYPES)

    def test_no_account_is_created_since_cloud_init_owns_the_identity(self):
        vues = lignes()
        self.assertIsNone(reponse(vues, "passwd/username"))
        self.assertEqual(reponse(vues, "passwd/make-user"), "false")
        # Mais d-i refuse d'avancer sans AUCUNE voie d'accès : la connexion
        # root est déclarée, avec un hachage qui n'ouvre rien.
        self.assertEqual(reponse(vues, "passwd/root-login"), "true")
        self.assertEqual(
            reponse(vues, "passwd/root-password-crypted"), HACHAGE
        )

    def test_a_marker_that_is_not_a_crypt_hash_is_refused(self):
        # Un hachage que crypt(3) ne reconnaît pas N'ÉCHOUE PAS :
        # l'installateur le laisse tomber et DEMANDE le mot de passe. Les
        # marqueurs de verrouillage en sont — ils verrouillent un compte
        # déjà créé, ils ne se préconfigurent pas.
        for vu in ("!", "*", "", "   ", "motdepasse", "$", None):
            with self.subTest(vu=vu):
                self.assertEqual(
                    G.lignes_preseed(HOTE, ADRESSE, PASSERELLE, DNS, vu),
                    (),
                )
        # Contrôle positif : refuser toujours passerait les sept.
        self.assertTrue(lignes())

    def test_the_swap_question_is_answered_when_the_recipe_declares_none(self):
        # L'implication, et non la ligne : une recette QUI PORTERAIT un swap
        # n'aurait pas à répondre, et ce garde se tairait alors.
        if "method{ swap }" in G.RECETTE:
            self.skipTest("la recette déclare un swap")
        self.assertEqual(
            reponse(lignes(), "partman-basicfilesystems/no_swap"), "false"
        )

    def test_the_root_partition_runs_to_the_end_of_the_disk(self):
        # « -1 » est ce qui rend la racine agrandissable après clonage ; une
        # taille maximale finie laisserait un reliquat derrière elle.
        morceaux = [m.strip() for m in G.RECETTE.split(".") if m.strip()]
        racine = [m for m in morceaux if "mountpoint{ / }" in m]
        self.assertEqual(len(racine), 1)
        self.assertEqual(racine[0].split()[2], "-1")

    def test_the_installer_powers_off_instead_of_rebooting(self):
        # Le noyau de l'installateur reste épinglé le temps de la pose : un
        # redémarrage y retombe et réinstalle. L'extinction est aussi la
        # condition d'arrêt que le pilote sait lire.
        sorties = {
            ligne.split()[1].rsplit("/", 1)[-1]: ligne.split()[-1]
            for ligne in lignes()
            if "debian-installer/exit/" in ligne
        }
        self.assertEqual(
            {nom for nom, val in sorties.items() if val == "true"},
            {"poweroff"},
        )

    def test_the_build_address_lives_only_in_the_installer(self):
        # Elle ne sert qu'à joindre le miroir. Écrite AUSSI dans le système
        # posé, elle part avec chaque clone, qui se lève alors sur elle —
        # et Cloud-Init écrivant la sienne sous un AUTRE nom d'interface,
        # les deux coexistent sans que rien ne signale le conflit.
        porteuses = [ligne for ligne in lignes() if ADRESSE in ligne]
        self.assertEqual(len(porteuses), 1)
        self.assertTrue(porteuses[0].split()[1].startswith("netcfg/"))

    def test_the_late_command_ends_on_something_that_returns_zero(self):
        # d-i s'arrête sur « Failed to run preseeded command » dès qu'une
        # commande rend autre chose que 0.
        tard = reponse(lignes(), "preseed/late_command")
        self.assertIsNotNone(tard)
        self.assertEqual(tard.rsplit(";", 1)[-1].strip(), "true")


class TestOuLInstallateurSeTrouve(unittest.TestCase):
    def test_the_kernel_and_its_initrd_are_named_together(self):
        # Un noyau sans son initrd démarre puis s'arrête faute de racine.
        urls = G.urls_installateur("trixie")
        self.assertEqual(len(urls), 2)
        self.assertNotEqual(*urls)

    def test_the_architecture_reaches_the_path(self):
        # Le chemin porte l'architecture DEUX fois ; en oublier une donne un
        # 404 qui se lit comme une panne de réseau.
        for url in G.urls_installateur("trixie", "arm64"):
            self.assertNotIn("amd64", url)
            self.assertEqual(url.count("arm64"), 2)

    def test_a_missing_piece_names_nothing(self):
        for code, arch in (
            ("", "amd64"),
            (None, "amd64"),
            ("trixie", ""),
            ("trixie", None),
        ):
            with self.subTest(code=code, arch=arch):
                self.assertEqual(G.urls_installateur(code, arch), ())
        # Contrôle positif : refuser toujours passerait les quatre.
        self.assertTrue(G.urls_installateur("trixie"))


class TestLesArgumentsDAmorcage(unittest.TestCase):
    def test_a_missing_path_yields_nothing_rather_than_half_a_command(self):
        self.assertIsNone(G.args_amorce("", "/i.gz"))
        self.assertIsNone(G.args_amorce("/linux", "  "))
        self.assertIsNone(G.args_amorce("/linux", "/i.gz", console=""))
        # Contrôle positif.
        self.assertIsNotNone(G.args_amorce("/linux", "/i.gz"))

    def test_the_same_path_twice_is_refused(self):
        # Le noyau et l'initrd sont deux fichiers ; les confondre donne une
        # VM qui démarre et n'installe rien.
        self.assertIsNone(G.args_amorce("/di/linux", "/di/linux"))

    def test_the_boot_line_silences_the_remaining_questions(self):
        self.assertIn("priority=critical", G.args_amorce("/k", "/i.gz"))

    def test_the_serial_journal_is_the_only_trace_of_a_screenless_run(self):
        sans = G.args_amorce("/k", "/i.gz")
        avec = G.args_amorce("/k", "/i.gz", journal="/var/log/di.log")
        self.assertNotIn("-serial", sans)
        self.assertIn("file:/var/log/di.log", avec)


class TestLaCreationDeLaVM(unittest.TestCase):
    def argv(self, **ecarts):
        champs = dict(vmid=9000, nom="g", stockage="local", pont="vmbr0")
        champs.update(ecarts)
        return G.argv_creation(**champs)

    def test_the_hardware_the_bench_measures_is_set(self):
        argv = self.argv()
        self.assertIsNotNone(argv)
        for drapeau, valeur in (("--machine", G.MACHINE), ("--bios", G.BIOS)):
            self.assertEqual(argv[argv.index(drapeau) + 1], valeur)

    def test_an_efi_disk_backs_the_firmware(self):
        # Sans stockage de variables, l'entrée d'amorçage que l'installateur
        # écrit ne survit pas à l'extinction.
        argv = self.argv()
        self.assertIn("--efidisk0", argv)
        self.assertTrue(
            argv[argv.index("--efidisk0") + 1].startswith("local:")
        )

    def test_an_unreadable_value_refuses_rather_than_creating_a_half_vm(self):
        for ecart in (
            dict(vmid="neuf-mille"),
            dict(vmid=0),
            dict(nom=" "),
            dict(stockage=""),
            dict(pont=""),
            dict(gio="seize"),
            dict(memoire=0),
            dict(coeurs=-1),
        ):
            with self.subTest(**ecart):
                self.assertIsNone(self.argv(**ecart))
        # Contrôle positif : refuser toujours passerait les huit précédents.
        self.assertIsNotNone(self.argv())


class TestCeQuiSeCorrigeDansLeGabarit(unittest.TestCase):
    def test_the_stanza_the_installer_wrote_is_taken_back(self):
        # Sans cela, chaque clone lève son réseau sur l'adresse du gabarit.
        cmds = G.cmds_dans_le_gabarit(9000)
        self.assertTrue(
            any("/etc/network/interfaces" in " ".join(c) for c in cmds)
        )

    def test_it_carries_no_address_of_its_own(self):
        # Le fichier posé DÉLÈGUE ; y réécrire une adresse recréerait le
        # défaut sous un autre nom.
        plat = " ".join(" ".join(c) for c in G.cmds_dans_le_gabarit(9000))
        self.assertNotRegex(plat, r"\d+\.\d+\.\d+\.\d+")

    def test_an_unreadable_vmid_names_no_command(self):
        for vu in ("", None, "neuf", 0, -1):
            with self.subTest(vu=vu):
                self.assertEqual(G.cmds_dans_le_gabarit(vu), ())
        # Contrôle positif : refuser toujours passerait les cinq.
        self.assertTrue(G.cmds_dans_le_gabarit(9000))


class TestLApresInstallation(unittest.TestCase):
    def test_the_pinned_kernel_is_removed_so_the_vm_boots_its_disk(self):
        cmds = G.cmds_apres_installation(9000, "local")
        self.assertTrue(any("--delete args" in c for c in cmds))

    def test_a_cloud_init_drive_is_part_of_the_template(self):
        # C'est par lui que chaque clone reçoit son compte et sa clé ; un
        # modèle sans lui donne des clones injoignables, en silence.
        cmds = G.cmds_apres_installation(9000, "local")
        self.assertTrue(any(":cloudinit" in c for c in cmds))

    def test_an_unreadable_value_names_no_command(self):
        for vmid, lieu in (
            ("", "local"),
            (None, "local"),
            ("neuf", "local"),
            (0, "local"),
            (-1, "local"),
            (9000, ""),
            (9000, "  "),
            (9000, None),
        ):
            with self.subTest(vmid=vmid, lieu=lieu):
                self.assertEqual(G.cmds_apres_installation(vmid, lieu), ())
        # Contrôle positif : refuser toujours passerait les huit précédents.
        self.assertTrue(G.cmds_apres_installation(9000, "local"))


class TestLaConversion(unittest.TestCase):
    def test_the_vm_is_stopped_before_it_is_frozen(self):
        # Le nettoyage vide /etc/machine-id et retire les clés d'hôte ; un
        # démarrage de plus les régénère, et le modèle les fige pour tous
        # ses clones.
        cmds = G.cmds_conversion(9000)
        arret = [i for i, c in enumerate(cmds) if " stop " in c]
        modele = [i for i, c in enumerate(cmds) if " template " in c]
        self.assertTrue(arret and modele)
        self.assertLess(max(arret), min(modele))

    def test_an_unreadable_vmid_names_no_command(self):
        for vu in ("", None, "neuf", 0, -1):
            with self.subTest(vu=vu):
                self.assertEqual(G.cmds_conversion(vu), ())
        # Contrôle positif : refuser toujours passerait les cinq.
        self.assertTrue(G.cmds_conversion(9000))


if __name__ == "__main__":
    unittest.main()
