#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Proxmox VE au catalogue de déploiement : ce qui existe, et ce qui n'existe pas.

Proxmox ne publie AUCUNE image cloud — son ISO est un installateur qui formate
le disque. La voie que l'amont documente pour tout le reste est « Proxmox VE
sur Debian » : on part de l'image cloud Debian trixie et les paquets pve en
font l'hyperviseur. Le catalogue le dit ainsi, et l'image téléchargée est
littéralement celle de Debian.

Par architecture, vérifié dans le dépôt amont et non déduit :

- amd64 : 1800 paquets, proxmox-ve présent.
- arm64 : 448 paquets, proxmox-ve présent — officiel depuis PVE 9, dont le
  Release de trixie annonce « amd64 arm64 ».
- s390x : l'index « binary-s390x » répond 404. Ce n'est pas une difficulté,
  c'est une absence, et le catalogue la dit avant le déploiement.

Ce que ces tests gardent :

- Le nom de cache est celui de Debian : sans lui, le repli de fin nommait
  l'image « fedora-cloud-9 » et un même téléchargement se faisait deux fois.
- Les planchers RAM/disque sont ceux d'un hyperviseur, pas ceux de Debian.
- Le retrait du noyau Debian n'emporte JAMAIS celui de Proxmox — sans quoi la
  VM ne redémarrerait plus.
"""

import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RACINE = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/proxmox/install_proxmox.sh"

DISQUE_BOUCHON_COURT = "vdz"
DISQUE_BOUCHON = f"/dev/{DISQUE_BOUCHON_COURT}"

# Les commandes que la cible garantit et que la station de test peut ne pas
# avoir. Le script s'installe SUR Debian, où « hostname » est de priorité
# requise ; ailleurs il manque, et comme fix_hosts le lit dans une
# substitution — exécutée même en dry-run, la valeur étant nécessaire — le
# script sort en 127 dès la première section et TOUT ce qui suit n'est
# jamais rendu. Un bouchon par test l'emporte sur celui-ci.
STUBS_DEFAUT = {
    "hostname": (
        'case "$1" in\n'
        "  -s) echo pve-test ;;\n"
        "  -f) echo pve-test.local ;;\n"
        "  *) echo pve-test ;;\n"
        "esac"
    ),
    # preseed_debconf s'ouvre sur « command -v debconf-set-selections ||
    # return 0 » : absente, la fonction se retire en silence et les deux
    # préréponses qui empêchent apt de rester pendu ne sont jamais rendues.
    "debconf-set-selections": "cat > /dev/null",
    # boot_disk() lit le disque d'amorçage RÉEL de la station. Le fixer
    # tient la préréponse grub-pc sur la logique du script plutôt que sur
    # le partitionnement de qui lance les tests : « / » sur LVM, sur btrfs
    # ou dans un conteneur rend un pkname vide, et la préréponse disparaît.
    # Le nom est inventé, et absent du reste du dépôt : s'il n'apparaît pas
    # dans la sortie, c'est que le bouchon n'a pas servi.
    "findmnt": f"echo {DISQUE_BOUCHON}3",
    "lsblk": f"echo {DISQUE_BOUCHON_COURT}",
}

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

TODO_DIR = pathlib.Path(RACINE) / "script" / "todo"
from script.todo.todo_i18n import t  # noqa: E402


def _deploy():
    spec = importlib.util.spec_from_file_location(
        "deploy_qemu", RACINE / "script/qemu/deploy_qemu.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy()

# Proxmox VE 9 est bâtie sur Debian 13 : c'est ce qui autorise sa ligne de
# catalogue à recopier le nom de code et l'identifiant libosinfo de
# celle-ci. Le lien est nommé ici pour que les épreuves l'épinglent à la
# TABLE plutôt qu'au littéral qu'elle contient aujourd'hui.
DEBIAN_SOUS_PVE9 = "13"

# Somme publiée par l'amont sur « Install Proxmox VE on Debian 13 Trixie », et
# recopiée ici EXPRÈS : deux copies indépendantes, c'est ce qui donne son sens
# à un condensat épinglé. Si l'une change sans l'autre, ce test le dit.
KEY_SHA256 = "136673be77aba35dcce385b28737689ad64fd785a797e57897589aed08db6e45"


class TestCatalogue(unittest.TestCase):
    def test_it_is_offered_as_a_distro(self):
        self.assertIn("proxmox", DQ.DISTROS)
        versions, defaut = DQ.DISTROS["proxmox"]
        self.assertEqual("9", defaut)
        self.assertIn("9", versions)

    def test_the_base_is_the_debian_trixie_cloud_image(self):
        """C'est bien l'image DEBIAN qu'on télécharge : Proxmox n'en publie
        aucune."""
        for arch in ("amd64", "arm64"):
            url = DQ.image_url("proxmox", "trixie", arch, "9")
            self.assertIn("trixie", url)
            self.assertIn(f"debian-13-genericcloud-{arch}.qcow2", url)

    def test_the_cache_name_is_debians_so_the_download_is_shared(self):
        """Un déploiement Debian 13 et un Proxmox visent le MÊME fichier : le
        repli de fin nommait l'image « fedora-cloud-9 », et 325 Mio se
        retéléchargeaient."""
        pve = DQ.default_image_name("proxmox", "trixie", "amd64", "9")
        deb = DQ.default_image_name("debian", "trixie", "amd64", "13")
        self.assertEqual(deb, pve)
        self.assertNotIn("fedora", pve)

    def test_s390x_does_not_exist_and_is_refused(self):
        """Le dépôt amont n'a pas d'index s390x (404). Le refus vaut mieux
        qu'un déploiement qui échouera au premier apt."""
        self.assertNotIn("proxmox", DQ.ARCH_DISTRO_SUPPORT["s390x"])

    def test_arm64_is_official_since_pve_9(self):
        self.assertIn("proxmox", DQ.ARCH_DISTRO_SUPPORT["arm64"])

    def test_the_floors_are_a_hypervisors_not_debians(self):
        """Proxmox demande 2 Gio pour lui seul et télécharge son noyau : les
        1 Gio/20 Go de Debian donneraient une VM incapable d'héberger une
        seule invitée."""
        _code, _osinfo, ram, disque = DQ.PROXMOX_VERSIONS["9"]
        self.assertGreaterEqual(ram, 4096)
        self.assertGreaterEqual(int(disque.rstrip("G")), 32)
        deb_ram = DQ.DEBIAN_VERSIONS["13"][2]
        self.assertGreater(ram, deb_ram)

    def test_it_reuses_debians_osinfo(self):
        """Le système EST une Debian : libosinfo n'a pas d'entrée Proxmox, et
        en inventer une ferait échouer virt-install.

        Épinglé à la TABLE DEBIAN et non à un littéral : ce qui est copié se
        vérifie contre son autorité, sans quoi l'épreuve reste verte le jour
        où l'autorité change et où la copie, elle, ne bouge pas.
        """
        self.assertEqual(
            DQ.DEBIAN_VERSIONS[DEBIAN_SOUS_PVE9][1],
            DQ.PROXMOX_VERSIONS["9"][1],
        )

    def test_it_reuses_debians_code_name(self):
        """Le nom de code choisit l'image téléchargée : divergent, il en
        vise une qui n'existe pas, et le déploiement s'arrête au premier
        téléchargement."""
        self.assertEqual(
            DQ.DEBIAN_VERSIONS[DEBIAN_SOUS_PVE9][0],
            DQ.PROXMOX_VERSIONS["9"][0],
        )

    def test_it_is_named_after_proxmox_not_after_the_key(self):
        self.assertEqual("Proxmox VE 9", DQ.distro_label("proxmox", "9"))

    def test_the_login_guide_knows_it_is_apt(self):
        self.assertEqual("apt", DQ.DISTRO_PKG["proxmox"])


class TestLesDeuxCatalogues(unittest.TestCase):
    """todo.py duplique le catalogue de deploy_qemu.py. Qu'ils s'accordent.

    S'ACCORDER PORTE SUR TOUT CE QUI EST RECOPIÉ, et la copie porte les
    versions et la version par défaut autant que les noms. Comparer les
    seuls noms laissait passer une version ajoutée d'un côté — l'écran ne
    la propose pas — et un défaut déplacé — l'écran en propose une autre
    que celle que le déploiement retiendra.
    """

    def test_the_menu_offers_every_distro_of_the_catalogue(self):
        menu = set(TODO._QEMU_DISTROS)
        catalogue = set(DQ.DISTROS)
        self.assertEqual(
            catalogue,
            menu,
            "les deux catalogues divergent : "
            f"menu seul {menu - catalogue}, deploy seul {catalogue - menu}",
        )

    def test_the_menu_offers_every_version_of_each_distro(self):
        """Une version ajoutée à la table et pas au menu n'est proposée
        nulle part : elle existe pour le déploiement et pour personne."""
        for distro in sorted(DQ.DISTROS):
            with self.subTest(distro=distro):
                self.assertEqual(
                    list(DQ.DISTROS[distro][0]),
                    list(TODO._QEMU_DISTROS[distro][0]),
                )

    def test_the_menu_preselects_the_version_the_deploy_would_take(self):
        """Le défaut du menu est ce qu'on obtient en tapant Entrée. Décalé
        de celui de la table, l'écran annonce une version et le
        déploiement en pose une autre, sans qu'un mot soit dit."""
        for distro in sorted(DQ.DISTROS):
            with self.subTest(distro=distro):
                self.assertEqual(
                    DQ.DISTROS[distro][1], TODO._QEMU_DISTROS[distro][1]
                )

    def test_the_package_families_match_the_authoritative_table(self):
        """Le filtre d'outils est une COPIE de plus, et elle avait dérivé.

        Une famille absente rend "" et le filtre écarte alors tout outil
        qui en exige une : une VM Proxmox — qui EST une Debian — perdait
        les deux outils réclamant « apt ». Ne déclarer aucune distribution
        les gardait, donc le filtre punissait la précision.
        """
        self.assertEqual(
            DQ.DISTRO_PKG,
            TODO._QEMU_DISTRO_FAMILY,
            "la table des familles diverge de l'autorité : "
            f"autorité seule "
            f"{set(DQ.DISTRO_PKG) - set(TODO._QEMU_DISTRO_FAMILY)}, "
            f"copie seule "
            f"{set(TODO._QEMU_DISTRO_FAMILY) - set(DQ.DISTRO_PKG)}",
        )

    def test_naming_a_distro_never_gives_fewer_tools_than_naming_none(self):
        """LE RENVERSEMENT EST LE SIGNE. Ne rien dire ne doit pas offrir
        plus que dire juste — c'est ainsi qu'une famille manquante se
        voit, quelle que soit la distribution qui la perd."""
        tous = tuple(TODO._QEMU_VM_TOOLS)
        muet = len(TODO._qemu_tools_for(tous, "amd64", "gnome", distro=""))
        for distro in sorted(DQ.DISTROS):
            with self.subTest(distro=distro):
                nomme = len(
                    TODO._qemu_tools_for(tous, "amd64", "gnome", distro=distro)
                )
                self.assertLessEqual(
                    nomme,
                    muet,
                    "nommer une distribution ne peut pas en ajouter",
                )

    def test_a_proxmox_vm_gets_the_apt_tools(self):
        """Contrôle positif : la borne par famille doit continuer d'écarter
        ce qu'une distribution ne sait pas installer."""
        tous = tuple(TODO._QEMU_VM_TOOLS)
        apt = {
            c
            for c, *_r in TODO._qemu_tools_for(
                tous, "amd64", "gnome", distro="debian"
            )
        }
        pve = {
            c
            for c, *_r in TODO._qemu_tools_for(
                tous, "amd64", "gnome", distro="proxmox"
            )
        }
        dnf = {
            c
            for c, *_r in TODO._qemu_tools_for(
                tous, "amd64", "gnome", distro="fedora"
            )
        }
        self.assertEqual(apt, pve)
        self.assertNotEqual(apt, dnf)

    def test_the_fallback_tuples_match_the_authoritative_table(self):
        """Le repli du menu est une COPIE, et une copie ne suit pas.

        Le commentaire du menu raconte déjà cette panne : les tuples étaient
        tenus par la seule promesse « cohérent avec deploy_qemu », et Debian
        a gagné s390x là-bas sans l'obtenir ici — l'écran ne le proposait
        donc pas. La voie normale lit désormais la table ; le repli, lui,
        est toujours une copie et sert justement quand plus rien ne peut la
        lire.
        """
        for arch, copie in (
            ("s390x", TODO._QEMU_S390X_DISTROS),
            ("arm64", TODO._QEMU_ARM64_DISTROS),
        ):
            with self.subTest(arch=arch):
                self.assertEqual(
                    set(DQ.ARCH_DISTRO_SUPPORT[arch]),
                    set(copie),
                    f"le repli {arch} diverge de la table : "
                    f"table seule "
                    f"{set(DQ.ARCH_DISTRO_SUPPORT[arch]) - set(copie)}, "
                    f"repli seul "
                    f"{set(copie) - set(DQ.ARCH_DISTRO_SUPPORT[arch])}",
                )

    def test_no_screen_label_claims_a_single_distro_per_arch(self):
        """L'écran du choix d'architecture annonçait « Ubuntu only » pour
        s390x, que la table sert en six distributions.

        Une restriction énoncée EN DUR à côté d'une table qui l'infirme
        envoie choisir une autre architecture pour une raison fausse. La
        liste qui suit est déjà filtrée par la table : l'écran n'a pas à
        la résumer, et ne peut pas le faire sans dériver.
        """
        lignes = (
            (TODO_DIR / "qemu_menu.py")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        multiples = [
            a for a, d in DQ.ARCH_DISTRO_SUPPORT.items() if len(d) > 1
        ]
        for seule in ("Ubuntu only", "Debian only", "Fedora only"):
            # La LIGNE fautive, et non la page : un assertNotIn sur le
            # source entier rend un message de cinquante kilo-octets, que
            # personne ne lit — donc une garde qui ne renseigne pas.
            fautives = [
                f"qemu_menu.py:{n}: {l.strip()}"
                for n, l in enumerate(lignes, 1)
                if seule in l
            ]
            with self.subTest(mention=seule, arches=multiples):
                self.assertEqual([], fautives)

    def test_the_versions_agree_for_proxmox(self):
        versions, defaut = TODO._QEMU_DISTROS["proxmox"]
        self.assertEqual(["9"], list(versions))
        self.assertEqual("9", defaut)


class TestLeProfil(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_a_dedicated_profile_calls_the_dedicated_script(self):
        profils = dict(self.todo._qemu_install_profiles())
        libelle = t("Proxmox VE hypervisor (no Odoo)")
        self.assertIn(libelle, profils)
        self.assertIn("install_proxmox.sh", profils[libelle])

    def test_on_a_proxmox_vm_it_comes_first(self):
        """Laisser « Odoo 18 » en défaut ferait poser un ERP sur un
        hyperviseur : c'est le contraire de ce qu'on a demandé."""
        vus = []
        with mock.patch("builtins.input", lambda *a: ""):
            import contextlib
            import io

            with contextlib.redirect_stdout(io.StringIO()):
                libelle, cmd = self.todo._qemu_pick_install_profile("proxmox")
        vus.append((libelle, cmd))
        self.assertIn("install_proxmox.sh", cmd)

    def test_on_any_other_vm_odoo_stays_the_default(self):
        import contextlib
        import io

        with mock.patch("builtins.input", lambda *a: ""):
            with contextlib.redirect_stdout(io.StringIO()):
                libelle, cmd = self.todo._qemu_pick_install_profile("debian")
        self.assertNotIn("install_proxmox.sh", cmd)
        self.assertIn("install_odoo_18", cmd)


# Le script s'installe SUR Debian et appelle les outils de Debian. Une
# machine qui ne les a pas ne peut pas le JOUER : le shell rend 127 au
# premier appel, et tout ce qui suit — une sortie tronquée, une chaîne
# introuvable — est l'effet de cette absence, jamais un défaut du script.
#
# Un tel test SAUTE, et dit pourquoi. Un échec appellerait une correction qui
# n'existe pas, et un rapport qui en porte neuf fait douter de tout le reste :
# celui qui le lit — humain ou machine — cesse d'y chercher ce qui compte.
_OUTILS_DEBIAN = ("dpkg", "apt-get", "hostname", "debconf-set-selections")


def _sauter_si_outil_debian_manquant(res):
    """Saute le test quand le script a buté sur un outil absent de l'hôte.

    Jugé sur ce qui S'EST PASSÉ — le code 127 et le nom de l'outil dans la
    sortie — et non sur un inventaire préalable : une machine peut porter
    « dpkg » sans « debconf-set-selections », et l'inventaire dirait alors le
    contraire de l'exécution. Les tests qui attendent un REFUS du script
    n'atteignent jamais ces outils : ils continuent de tourner partout.
    """
    if res.returncode != 127:
        return
    sortie = (res.stdout or "") + (res.stderr or "")
    for outil in _OUTILS_DEBIAN:
        if outil in sortie:
            raise unittest.SkipTest(
                f"« {outil} » absent de cet hôte : le script d'installation"
                " Proxmox ne se joue que sur une base Debian"
            )


class TestLeScript(unittest.TestCase):
    def test_it_is_executable_and_valid_shell(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK), "pas exécutable")
        res = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_help_names_the_knobs_and_exits_clean(self):
        res = subprocess.run(
            ["bash", str(SCRIPT), "--help"], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode)
        for knob in ("--dry-run", "PVE_SUITE", "PVE_REBOOT"):
            self.assertIn(knob, res.stdout)

    def test_the_pinned_key_hash_is_the_published_one(self):
        texte = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(KEY_SHA256, texte)
        self.assertIn("proxmox-archive-keyring-", texte)

    def _lance(self, args=(), stubs=None, env=None):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            bin_dir.mkdir()
            for nom, corps in dict(STUBS_DEFAUT, **(stubs or {})).items():
                (bin_dir / nom).write_text(f"#!/bin/bash\n{corps}\n")
                (bin_dir / nom).chmod(0o755)
            osrel = pathlib.Path(tmp) / "os-release"
            osrel.write_text("ID=debian\nVERSION_CODENAME=trixie\n")
            res = subprocess.run(
                ["bash", str(SCRIPT), *args],
                capture_output=True,
                text=True,
                env=dict(
                    os.environ,
                    PATH=f"{bin_dir}:/usr/bin:/bin",
                    PVE_OS_RELEASE=str(osrel),
                    **(env or {}),
                ),
                timeout=120,
            )
        # HORS du « with » : le répertoire des doublures est rendu avant que
        # le saut ne remonte, et aucun test ne laisse le sien derrière lui.
        _sauter_si_outil_debian_manquant(res)
        return res

    def test_an_unpublished_architecture_is_refused_by_name(self):
        res = self._lance(stubs={"uname": "echo s390x"})
        self.assertNotEqual(0, res.returncode)
        self.assertIn("s390x", res.stdout + res.stderr)

    def test_another_distribution_is_refused_by_name(self):
        """Le script s'installe SUR Debian : le dire vaut mieux qu'un apt qui
        échouera sur un dépôt introuvable."""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".os", delete=False
        ) as fh:
            fh.write("ID=ubuntu\nVERSION_CODENAME=noble\n")
            chemin = fh.name
        self.addCleanup(os.unlink, chemin)
        res = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            env=dict(os.environ, PVE_OS_RELEASE=chemin),
            timeout=60,
        )
        self.assertNotEqual(0, res.returncode)
        self.assertIn("ubuntu", res.stdout + res.stderr)

    def test_the_dry_run_follows_the_upstream_procedure(self):
        res = self._lance(["--dry-run"])
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        out = res.stdout
        for attendu in (
            "proxmox-archive-keyring-trixie.gpg",
            "Types: deb",
            "pve-no-subscription",
            "Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg",
            "proxmox-default-kernel",
            "proxmox-ve postfix open-iscsi chrony",
        ):
            self.assertIn(attendu, out, attendu)

    def test_the_dry_run_changes_nothing_and_says_so(self):
        """La leçon du montage sshfs : ne rien annoncer qui n'ait eu lieu."""
        res = self._lance(["--dry-run"])
        self.assertIn("dry-run", res.stdout)
        self.assertNotIn("Proxmox VE installé", res.stdout)

    def test_postfix_is_preseeded_or_the_install_hangs(self):
        """postfix pose deux questions debconf : sans préréponse, une
        installation lancée par SSH reste pendue sur une saisie invisible."""
        res = self._lance(["--dry-run"])
        self.assertIn("debconf-set-selections", res.stdout)
        self.assertIn("main_mailer_type", res.stdout)

    def test_it_never_removes_the_proxmox_kernel(self):
        """Le noyau qu'on vient de poser : l'emporter laisserait une VM qui
        n'amorce plus. dpkg-query rend ici les deux, seul celui de Debian doit
        partir."""
        res = self._lance(
            ["--dry-run"],
            stubs={
                "uname": "echo x86_64",
                "dpkg": "exit 0",
                # Format réel de la requête : nom + état. dpkg connaît
                # aussi les paquets DÉSINSTALLÉS (« config-files »), et les
                # passer à apt réclamait un redémarrage pour rien.
                "dpkg-query": (
                    "printf 'linux-image-6.12.0-amd64 installed\\n"
                    "linux-image-amd64 config-files\\n"
                    "linux-image-6.14.11-1-pve installed\\n'"
                ),
            },
        )
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        ligne = [
            x for x in res.stdout.splitlines() if "remove linux-image" in x
        ]
        self.assertTrue(ligne, res.stdout)
        self.assertIn("linux-image-6.12.0-amd64", ligne[0])
        self.assertNotIn("pve", ligne[0])
        # « config-files » = déjà désinstallé : ne pas le repasser à apt.
        self.assertNotIn("linux-image-amd64", ligne[0])

    def test_without_the_proxmox_kernel_nothing_is_removed(self):
        """Une étape apt a pu échouer plus haut : on ne touche pas au noyau
        Debian tant que celui de Proxmox n'est pas là."""
        res = self._lance(
            ["--dry-run"],
            stubs={"uname": "echo x86_64", "dpkg": "exit 1"},
        )
        self.assertNotIn("remove linux-image", res.stdout)
        self.assertIn("noyau Debian reste en place", res.stdout)

    def test_grub_pc_is_preseeded_or_dpkg_stops(self):
        """Le piège propre à l'image cloud : elle amorce en EFI, les paquets
        pve tirent grub-pc, et sa post-installation refuse de deviner le
        disque — « You must correct your GRUB install devices before
        proceeding » : dpkg s'arrête et emporte la transaction."""
        res = self._lance(["--dry-run"])
        self.assertIn("grub-pc/install_devices", res.stdout)
        self.assertIn(
            f"install_devices multiselect {DISQUE_BOUCHON}", res.stdout
        )

    def test_apt_waits_for_the_lock_instead_of_giving_up(self):
        """Sur une VM fraîche, cloud-init tient encore le verrou : apt
        rend « held by process … (apt-get) » et, sans attente, le script
        meurt dans la minute qui suit le démarrage."""
        texte = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("DPkg::Lock::Timeout", texte)
        res = self._lance(["--dry-run"])
        self.assertIn("DPkg::Lock::Timeout", res.stdout)

    def test_it_waits_for_cloud_init_but_not_for_its_verdict(self):
        """cloud-init rend « error » sur l'image Debian 13 pour deux modules
        sans rapport (console-setup absent, update-locale) alors qu'il a bien
        fini. On attend qu'il termine, pas qu'il soit content."""
        res = self._lance(["--dry-run"])
        self.assertIn("cloud-init status --wait", res.stdout)
        # L'échec de cloud-init ne doit PAS arrêter le script : « || true »
        # sur l'appel réel, pas sur l'écho du dry-run.
        texte = SCRIPT.read_text(encoding="utf-8")
        reel = [
            x
            for x in texte.splitlines()
            if "cloud-init status --wait" in x and "dry-run" not in x
        ]
        self.assertTrue(reel, texte)
        self.assertIn("|| true", reel[0])

    def _esp(self, avec_secours):
        """Fausse partition EFI : un stub Debian, et le chemin de secours."""
        racine = tempfile.mkdtemp()
        self.addCleanup(
            lambda: subprocess.run(["rm", "-rf", racine], check=False)
        )
        deb = pathlib.Path(racine, "EFI", "debian")
        boot = pathlib.Path(racine, "EFI", "BOOT")
        deb.mkdir(parents=True)
        boot.mkdir(parents=True)
        (deb / "grub.cfg").write_text(
            "search.fs_uuid 81e2a465 root\nset prefix=($root)'/boot/grub'\n"
        )
        (boot / "BOOTX64.EFI").write_text("binaire")
        if avec_secours:
            (boot / "grub.cfg").write_text("déjà là")
        return racine

    def test_the_efi_fallback_stub_is_restored(self):
        """Sans ce fichier, GRUB s'arrête sur « grub> » : ni menu ni noyau.
        Vécu après le premier redémarrage — la VM brûlait 100 % d'un cœur sans
        lire une seule fois le disque, capture d'écran à l'appui."""
        esp = self._esp(avec_secours=False)
        res = self._lance(["--dry-run"], env={"PVE_ESP": esp})
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("amorçage de secours", res.stdout)
        self.assertIn("EFI/BOOT/", res.stdout)

    def test_a_working_fallback_is_left_alone(self):
        """Ne pas réécrire ce qui marche : le stub en place peut avoir été
        ajusté à la main."""
        esp = self._esp(avec_secours=True)
        res = self._lance(["--dry-run"], env={"PVE_ESP": esp})
        self.assertNotIn("amorçage de secours", res.stdout)

    def test_an_esp_without_any_stub_is_said_not_guessed(self):
        racine = tempfile.mkdtemp()
        self.addCleanup(
            lambda: subprocess.run(["rm", "-rf", racine], check=False)
        )
        pathlib.Path(racine, "EFI", "BOOT").mkdir(parents=True)
        res = self._lance(["--dry-run"], env={"PVE_ESP": racine})
        self.assertIn("aucun grub.cfg à recopier", res.stdout)

    def test_it_does_not_reboot_unless_asked(self):
        """Lancé par SSH depuis le déploiement, un reboot couperait la session
        et ferait passer une installation réussie pour un échec."""
        texte = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('PVE_REBOOT:-0}" != "1"', texte)
        res = self._lance(["--dry-run"])
        self.assertNotIn("systemctl reboot", res.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
