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

import base64
import gzip
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
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


class TestLeDisqueVaSurToutStockageAImages(unittest.TestCase):
    def test_no_disk_format_is_forced_on_the_storage(self):
        """Un LVM-thin ou un ZFS refuse un qcow2 : chaque stockage prend le
        format qui est le sien."""
        argv = G.argv_creation(9000, HOTE, "un-stockage", "vmbr9")
        disque = argv[argv.index("--scsi0") + 1]
        options = dict(
            p.split("=", 1) for p in disque.split(",")[1:] if "=" in p
        )
        self.assertNotIn("format", options)
        self.assertTrue(disque.startswith("un-stockage:"))


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
    def test_a_clean_shutdown_is_tried_before_the_power_is_cut(self):
        """Le nettoyage vient d'écrire : couper le courant d'emblée peut
        perdre ce qui n'est pas encore sur le disque."""
        premiere = G.cmds_conversion(9000)[0]
        alternatives = premiere.split("||")
        self.assertIn("shutdown", alternatives[0])
        self.assertIn("stop", alternatives[-1])

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


def joue(cmds, env=None, cwd=None):
    """Joue `cmds` dans un shell, comme le nœud le ferait, dans l'ordre. Un
    couple (commande, entrée) reçoit son entrée sur l'entrée standard."""
    for cmd in cmds:
        cmd, entree = cmd if isinstance(cmd, tuple) else (cmd, None)
        vu = subprocess.run(
            ["sh", "-c", cmd],
            capture_output=True,
            text=True,
            input=entree,
            env=env,
            cwd=cwd,
            timeout=60,
        )
        if vu.returncode:
            return vu
    return vu


def bouchons(dossier, **corps):
    """Un dossier de commandes factices, à mettre en tête du PATH."""
    os.makedirs(dossier, exist_ok=True)
    for nom, texte in corps.items():
        chemin = os.path.join(dossier, nom.replace("_", "-"))
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n" + texte + "\n")
        os.chmod(chemin, 0o755)
    return dict(os.environ, PATH=f"{dossier}:{os.environ['PATH']}")


class TestLeReseauDeFabrique(unittest.TestCase):
    def test_the_template_never_takes_the_gateway(self):
        for cidr in ("192.0.2.1/24", "192.0.2.254/24", "198.51.100.1/30"):
            with self.subTest(cidr=cidr):
                adresse, prefixe, passerelle, masque = G.reseau_de_fabrique(
                    cidr
                )
                import ipaddress

                reseau = ipaddress.ip_interface(cidr).network
                self.assertNotEqual(adresse, passerelle)
                self.assertIn(ipaddress.ip_address(adresse), reseau)
                self.assertNotEqual(
                    ipaddress.ip_address(adresse), reseau.broadcast_address
                )
                self.assertEqual(reseau.prefixlen, prefixe)
                self.assertEqual(str(reseau.netmask), masque)

    def test_a_network_without_room_answers_nothing(self):
        for cidr in (
            "192.0.2.1/31",
            "192.0.2.1/32",
            "2001:db8::1/64",
            "",
            None,
            "x",
        ):
            with self.subTest(cidr=cidr):
                self.assertEqual((), G.reseau_de_fabrique(cidr))

    def test_the_netmask_reaches_the_installer(self):
        lignes = G.lignes_preseed(
            HOTE, ADRESSE, PASSERELLE, DNS, HACHAGE, masque="255.255.255.128"
        )
        self.assertEqual(
            "255.255.255.128", reponse(lignes, "netcfg/get_netmask")
        )


@unittest.skipUnless(shutil.which("cpio"), "cpio absent")
class TestLePreseedVoyageDansLInitrd(unittest.TestCase):
    """Joué pour de vrai dans un dossier jetable, wget remplacé : le noyau
    lit un cpio concaténé à la suite du premier, donc ce que l'initrd porte
    doit SE RELIRE tel quel."""

    URLS = (
        "https://exemple.invalid/linux",
        "https://exemple.invalid/initrd.gz",
    )

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dossier = os.path.join(self.tmp, "fabrique")
        # Un initrd d'origine : un cpio gzippé portant un fichier à lui.
        source = os.path.join(self.tmp, "source")
        os.makedirs(source)
        with open(os.path.join(source, "init"), "w") as fh:
            fh.write("origine\n")
        archive = subprocess.run(
            "echo init | cpio -H newc -o 2>/dev/null | gzip",
            shell=True,
            cwd=source,
            capture_output=True,
            check=True,
        ).stdout
        self.initrd = os.path.join(self.tmp, "initrd-amont.gz")
        with open(self.initrd, "wb") as fh:
            fh.write(archive)
        # wget factice : copie l'initrd d'amont, ou écrit un noyau quelconque.
        self.env = bouchons(
            os.path.join(self.tmp, "bin"),
            wget=(
                'for a; do case "$a" in -O) o=1;; *) [ "$o" = 1 ] && { f="$a";'
                ' o=; }; u="$a";; esac; done;'
                f' case "$u" in *initrd*) cp {shlex.quote(self.initrd)} "$f";;'
                ' *) echo noyau > "$f";; esac'
            ),
        )

    def lu_par_le_noyau(self, chemin):
        """[(nom, contenu)] de TOUTES les archives cpio concaténées, lues à la
        suite comme le noyau le fait — `cpio -i` s'arrêterait à la première.
        Une LISTE, et non un dictionnaire : deux entrées du même nom doivent
        se compter deux fois."""
        with open(chemin, "rb") as fh:
            octets = gzip.decompress(fh.read())
        fichiers, i = [], 0
        while i + 110 <= len(octets):
            if octets[i : i + 6] != b"070701":
                i += 1
                continue
            taille = int(octets[i + 54 : i + 62], 16)
            longueur = int(octets[i + 94 : i + 102], 16)
            debut = i + 110
            nom = octets[debut : debut + longueur - 1].decode()
            donnees = (debut + longueur + 3) & ~3
            fin = donnees + taille
            if nom != "TRAILER!!!":
                fichiers.append((nom, octets[donnees:fin].decode()))
            i = (fin + 3) & ~3
        return fichiers

    def membres(self, chemin):
        return [nom for nom, _c in self.lu_par_le_noyau(chemin)]

    def test_the_preseed_is_read_back_from_the_initrd_unchanged(self):
        texte = G.preseed(HOTE, ADRESSE, PASSERELLE, DNS, HACHAGE)
        vu = joue(
            G.cmds_preparer_installateur(self.dossier, self.URLS, texte),
            env=self.env,
        )
        self.assertEqual(0, vu.returncode, vu.stderr)
        _n, initrd, porteur, _j = G.chemins_installateur(self.dossier)
        self.assertEqual(["init", "preseed.cfg"], self.membres(porteur))
        self.assertEqual(
            texte, dict(self.lu_par_le_noyau(porteur))["preseed.cfg"]
        )
        # L'initrd d'origine reste intact : rejouer repart de lui.
        self.assertEqual(["init"], self.membres(initrd))

    def test_preparing_twice_does_not_stack_two_preseeds(self):
        """Le second passage porte un AUTRE preseed : c'est le sien seul que
        l'initrd doit porter."""
        premier = G.preseed(HOTE, ADRESSE, PASSERELLE, DNS, HACHAGE)
        second = G.preseed("autre-hote", ADRESSE, PASSERELLE, DNS, HACHAGE)
        for texte in (premier, second):
            joue(
                G.cmds_preparer_installateur(self.dossier, self.URLS, texte),
                env=self.env,
            )
        porteur = G.chemins_installateur(self.dossier)[2]
        self.assertEqual(["init", "preseed.cfg"], self.membres(porteur))
        self.assertEqual(
            second, dict(self.lu_par_le_noyau(porteur))["preseed.cfg"]
        )

    def test_the_root_hash_never_travels_on_a_command_line(self):
        """sudo journalise la ligne de commande, et la table des processus
        la montre : le preseed passe par l'entrée standard."""
        texte = G.preseed(HOTE, ADRESSE, PASSERELLE, DNS, HACHAGE)
        cmds = G.cmds_preparer_installateur(self.dossier, self.URLS, texte)
        lignes = [c[0] if isinstance(c, tuple) else c for c in cmds]
        entrees = [c[1] for c in cmds if isinstance(c, tuple)]
        for ligne in lignes:
            for mot in shlex.split(ligne):
                try:
                    clair = base64.b64decode(mot, validate=True).decode()
                except (ValueError, UnicodeDecodeError):
                    clair = ""
                self.assertNotIn(HACHAGE, mot + clair)
        self.assertTrue(
            any(HACHAGE in base64.b64decode(e).decode() for e in entrees)
        )

    def test_no_clear_preseed_is_left_beside_it(self):
        """Le preseed porte le hachage root : il ne vit que dans l'initrd."""
        texte = G.preseed(HOTE, ADRESSE, PASSERELLE, DNS, HACHAGE)
        joue(
            G.cmds_preparer_installateur(self.dossier, self.URLS, texte),
            env=self.env,
        )
        laisses = []
        for racine, _d, fichiers in os.walk(self.dossier):
            laisses += [f for f in fichiers if f.endswith(".cfg")]
        self.assertEqual([], laisses)

    def test_the_cleanup_takes_everything_away(self):
        texte = G.preseed(HOTE, ADRESSE, PASSERELLE, DNS, HACHAGE)
        joue(
            G.cmds_preparer_installateur(self.dossier, self.URLS, texte),
            env=self.env,
        )
        self.assertTrue(os.path.isdir(self.dossier))
        joue(G.cmds_menage(self.dossier))
        self.assertFalse(os.path.exists(self.dossier))

    def test_the_download_outlives_a_network_still_coming_up(self):
        for cmd in G.cmds_preparer_installateur(
            self.dossier, self.URLS, "x\n"
        ):
            if isinstance(cmd, str) and cmd.startswith("wget"):
                self.assertIn("--retry-on-host-error", cmd)
                self.assertIn("--retry-connrefused", cmd)

    def test_a_missing_piece_names_no_command(self):
        for dossier, urls, texte in (
            ("", self.URLS, "x"),
            ("relatif", self.URLS, "x"),
            (self.dossier, self.URLS[:1], "x"),
            (self.dossier, self.URLS, ""),
        ):
            with self.subTest(dossier=dossier, urls=urls, texte=texte):
                self.assertEqual(
                    (), G.cmds_preparer_installateur(dossier, urls, texte)
                )
        self.assertTrue(
            G.cmds_preparer_installateur(self.dossier, self.URLS, "x")
        )


class TestLeStatut(unittest.TestCase):
    def test_the_field_is_read_not_searched(self):
        self.assertEqual("stopped", G.lit_statut("status: stopped\n"))
        self.assertEqual("running", G.lit_statut("status: running\n"))
        self.assertIsNone(G.lit_statut("VM 9000 not running: VM is stopped\n"))
        self.assertIsNone(G.lit_statut(""))
        self.assertIsNone(G.lit_statut(None))


CLE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIInventeePourLeTest0123456789 x@y"


class TestLIdentiteDuGabarit(unittest.TestCase):
    def identite(self, cle=CLE, **change):
        champs = dict(
            vmid=9000,
            utilisateur="ansible",
            cle=cle,
            dossier="/var/lib/fabrique",
            adresse=ADRESSE,
            prefixe=24,
            passerelle=PASSERELLE,
            dns=DNS,
        )
        champs.update(change)
        return G.cmds_identite(**champs)

    def test_the_key_written_on_the_node_is_the_key_given(self):
        depot = self.identite()[0]
        corps = shlex.split(depot)[1]
        self.assertEqual(CLE + "\n", base64.b64decode(corps).decode())

    def test_the_address_carries_its_prefix_and_gateway(self):
        ligne = self.identite()[1]
        self.assertIn(f"ip={ADRESSE}/24,gw={PASSERELLE}", ligne)
        self.assertIn("--ciuser ansible", ligne)

    def test_what_is_not_a_public_key_is_never_written(self):
        for cle in (
            "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA==\n-----END",
            CLE + "\n" + CLE,
            "pas une clé",
            "",
            None,
        ):
            with self.subTest(cle=cle):
                self.assertEqual((), self.identite(cle=cle))
        self.assertTrue(self.identite())

    def test_a_missing_value_names_no_command(self):
        for change in (
            {"vmid": 0},
            {"vmid": "neuf"},
            {"utilisateur": ""},
            {"adresse": ""},
            {"prefixe": 0},
            {"prefixe": 33},
            {"dossier": "relatif"},
        ):
            with self.subTest(**change):
                self.assertEqual((), self.identite(**change))


class TestCeQueDitLAgent(unittest.TestCase):
    def test_the_command_reaches_the_guest_whole(self):
        commande = 'echo "a b" | tr a c; exit 3'
        argv = shlex.split(G.cmd_dans_l_invite(9000, commande, 45))
        self.assertEqual(commande, argv[-1])
        self.assertEqual("45", argv[argv.index("--timeout") + 1])

    def test_the_guests_own_code_is_read(self):
        sortie = json.dumps({"exited": 1, "exitcode": 3, "out-data": "x"})
        self.assertEqual((3, "x"), G.lit_invite(sortie))
        sortie = json.dumps({"exited": 1, "exitcode": 0})
        self.assertEqual((0, ""), G.lit_invite(sortie))

    def test_a_command_still_running_is_a_doubt(self):
        for sortie in (
            json.dumps({"exited": 0, "pid": 1234}),
            # Un code sans la fin déclarée ne vaut rien : c'est « exited »
            # qui dit que le processus s'est terminé.
            json.dumps({"exited": 0, "exitcode": 0}),
            json.dumps({"exited": 1, "exitcode": True}),
            "",
            None,
            "agent not running",
        ):
            with self.subTest(sortie=sortie):
                self.assertIsNone(G.lit_invite(sortie))


class TestLePremierDemarrageSeTait(unittest.TestCase):
    """Joué dans un shell, les outils du système remplacés."""

    def joue(self, **corps):
        with tempfile.TemporaryDirectory() as tmp:
            self.trace = os.path.join(tmp, "trace")
            corps = {
                nom: f'echo "{nom} $*" >> {self.trace}; {texte}'
                for nom, texte in corps.items()
            }
            env = bouchons(os.path.join(tmp, "bin"), **corps)
            vu = subprocess.run(
                ["sh", "-c", G.ATTENTE_PREMIER_DEMARRAGE],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )
            with open(self.trace) as fh:
                self.appels = fh.read().splitlines()
            return vu

    def test_cloud_init_is_waited_for_before_apt_is_looked_at(self):
        self.joue(cloud_init="exit 0", systemctl="exit 3", pgrep="exit 1")
        self.assertTrue(self.appels[0].startswith("cloud_init"))
        self.assertIn("--wait", self.appels[0].split())

    def test_cloud_init_in_error_does_not_fail_the_wait(self):
        """On attend la fin, pas le verdict."""
        vu = self.joue(
            cloud_init="echo 'status: error'; exit 1",
            systemctl="exit 3",
            pgrep="exit 1",
        )
        self.assertEqual(0, vu.returncode, vu.stdout + vu.stderr)
        self.assertIn("status: error", vu.stdout)

    def test_apt_that_never_rests_fails_and_says_so(self):
        vu = self.joue(
            cloud_init="exit 0",
            systemctl="exit 3",
            pgrep="exit 0",
            sleep="exit 0",
        )
        self.assertNotEqual(0, vu.returncode)
        self.assertIn("apt", vu.stdout)


class TestLeSystemePoseSeDecrit(unittest.TestCase):
    CONFORME = "racine=ext4\nechange=0\nefi=oui\n"

    def test_what_the_command_prints_is_what_the_reader_reads(self):
        """Joué dans un shell, outils remplacés : le relevé se relit."""
        with tempfile.TemporaryDirectory() as tmp:
            env = bouchons(
                os.path.join(tmp, "bin"),
                findmnt="echo ext4",
                swapon="true",
                dpkg_query="printf 'install ok installed'",
            )
            vu = subprocess.run(
                ["sh", "-c", G.CONSTATS_SYSTEME],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )
        ecarts = G.ecarts_systeme(vu.stdout)
        self.assertIsNotNone(ecarts, vu.stdout)
        # L'EFI dépend de la machine qui joue l'épreuve ; le reste non.
        self.assertEqual((), tuple(e for e in ecarts if "EFI" not in e))

    def test_a_missing_package_is_reported_by_the_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = bouchons(
                os.path.join(tmp, "bin"),
                findmnt="echo ext4",
                swapon="true",
                dpkg_query=(
                    'for a; do p="$a"; done;'
                    ' [ "$p" = cloud-init ] && exit 1;'
                    " printf 'install ok installed'"
                ),
            )
            vu = subprocess.run(
                ["sh", "-c", G.CONSTATS_SYSTEME],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )
        ecarts = G.ecarts_systeme(vu.stdout)
        self.assertEqual(
            ["paquet absent : cloud-init"],
            [e for e in ecarts if "paquet" in e],
        )

    def test_a_conforming_system_has_no_gap(self):
        self.assertEqual((), G.ecarts_systeme(self.CONFORME))

    def test_each_gap_is_named(self):
        for texte, mot in (
            (self.CONFORME.replace("ext4", "btrfs"), "btrfs"),
            (self.CONFORME.replace("echange=0", "echange=1"), "échange"),
            (self.CONFORME.replace("efi=oui", "efi=non"), "EFI"),
            (self.CONFORME + "manque=cloud-init\n", "cloud-init"),
        ):
            with self.subTest(mot=mot):
                ecarts = G.ecarts_systeme(texte)
                self.assertTrue(ecarts)
                self.assertIn(mot, " ".join(ecarts))

    def test_a_truncated_report_is_a_doubt(self):
        for texte in ("racine=ext4\nechange=0\n", "", None):
            with self.subTest(texte=texte):
                self.assertIsNone(G.ecarts_systeme(texte))


class TestLeMaterielAvantConversion(unittest.TestCase):
    CONFORME = (
        "agent: enabled=1\nbios: ovmf\nboot: order=scsi0\n"
        "efidisk0: local:9000/vm-9000-disk-0.qcow2,size=528K\n"
        "ide2: local:9000/vm-9000-cloudinit.qcow2,media=cdrom\n"
        "machine: q35\nname: g\n"
    )

    def sans(self, cle):
        return "\n".join(
            ligne
            for ligne in self.CONFORME.splitlines()
            if not ligne.startswith(cle + ":")
        )

    def test_a_conforming_vm_has_no_gap(self):
        self.assertEqual((), G.ecarts_materiel(self.CONFORME))
        self.assertEqual(
            (),
            G.ecarts_materiel(
                self.CONFORME.replace("enabled=1", "1,fstrim_cloned_disks=1")
            ),
        )

    def test_each_missing_key_is_a_gap(self):
        for cle in ("machine", "bios", "efidisk0", "ide2", "agent"):
            with self.subTest(cle=cle):
                self.assertTrue(G.ecarts_materiel(self.sans(cle)))

    def test_an_agent_switched_off_is_a_gap(self):
        self.assertTrue(
            G.ecarts_materiel(self.CONFORME.replace("enabled=1", "0"))
        )

    def test_an_unreadable_config_is_a_doubt(self):
        self.assertIsNone(G.ecarts_materiel(""))


if __name__ == "__main__":
    unittest.main()
