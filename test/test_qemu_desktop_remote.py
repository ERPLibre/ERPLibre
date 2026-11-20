#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Bureau d'une VM, famille par famille : paquets, accès distant, pare-feu.

GNOME 49 et suivants n'ont plus de session X11. xrdp et TigerVNC, qui en
ouvrent une, n'ont alors rien à servir : GNOME passe par GNOME Remote Desktop
en mode système, choisi à l'exécution sur la capacité de grdctl, et xrdp ne
reste qu'en repli pour un GNOME plus ancien. Cinnamon, bureau X11, garde
xrdp, et TigerVNC sur Arch.

Ce que ces tests gardent, sans VM :

- chaque branche (apt, dnf, pacman, zypper) nomme les bons paquets, et la
  branche GNOME ne pose jamais xrdp à côté de GNOME Remote Desktop ;
- dnf distingue Fedora des RHEL-likes, écarte firewalld de GNOME sur Fedora
  (et de GNOME seulement : Cinnamon l'exige), et un bureau qui ne s'installe
  pas fait échouer la commande ;
- Arch met tout le système à niveau AVANT d'installer le bureau, et un échec
  de cette mise à niveau arrête tout au lieu d'être masqué ;
- la liste anti-snap d'Ubuntu n'atteint pas Debian.

Les blocs sont aussi EXÉCUTÉS, sur un PATH fermé où chaque commande système
est une doublure qui note son appel : c'est le seul moyen de voir quelle
branche tourne vraiment, et dans quel ordre.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo.deploy_form_lib import (  # noqa: E402
    VM_LOGIN_FILE,
    VM_LOGIN_READ_CMD,
    vm_name,
)
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

DISTROS = ("", "ubuntu", "debian", "fedora", "almalinux", "arch", "opensuse")

# Mot de passe inventé que l'invité simulé trouve dans son fichier : il doit
# atteindre grdctl sans jamais paraître dans la commande ni dans sa sortie.
SONDE = "Zq7sondeXv"


def _cmd(
    flavour="gnome", app_store="deb", distro="", keep_login=False, version=""
):
    return TODO.__new__(TODO)._qemu_desktop_remote_cmd(
        flavour,
        app_store,
        distro=distro,
        version=version,
        keep_login=keep_login,
    )


def _branche(cmd, famille):
    """La branche d'installation d'une famille, telle que générée.

    Bornée au premier « if/elif command -v … » de la famille et au début de
    la suivante : les blocs plus bas (repli xrdp) répètent ces tests, mais
    après la fin de la cascade d'installation."""
    bornes = {
        "apt": ("if command -v apt-get", "elif command -v dnf"),
        "dnf": ("elif command -v dnf", "elif command -v pacman"),
        "pacman": ("elif command -v pacman", "elif command -v zypper"),
        "zypper": ("elif command -v zypper", "else echo 'Gestionnaire"),
    }
    debut, fin = bornes[famille]
    i = cmd.index(debut)
    return cmd[i : cmd.index(fin, i)]


def _acces(cmd):
    """Tout ce qui suit le démarrage du bureau : l'accès distant."""
    return cmd[cmd.index("EL_REM=") :]


class _Invite:
    """Un invité simulé : un PATH fermé, des doublures qui notent leurs
    appels dans un journal, et quelques vrais outils dont le bloc a besoin
    pour ses calculs (grep, cut, awk…).

    Le PATH ne contient QUE ce dossier : « command -v apt-get » n'y trouve
    apt-get que si le test l'y a mis, quelle que soit la machine qui lance
    les tests."""

    REELS = (
        "awk",
        "base64",
        "cat",
        "chmod",
        "cp",
        "cut",
        "date",
        "dirname",
        "grep",
        "id",
        "ln",
        "mkdir",
        "rm",
        "sed",
        "sh",
        "sleep",
        "tail",
        "tee",
        "test",
        "touch",
    )

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.log = self.tmp / "log"
        self.log.write_text("")
        # Le fichier que l'hôte dépose avant la commande : VM_LOGIN_FILE
        # y est réécrit par run(). Présent par défaut, comme après un
        # premier lancement.
        self.pw_file = self.tmp / "vm-password"
        self.pw_file.write_text(SONDE + "\n")
        for nom in self.REELS:
            vrai = shutil.which(nom)
            if vrai:
                (self.bin / nom).symlink_to(vrai)
        # sudo laisse tomber « -u <compte> » et exporte les « VAR=valeur »
        # qui précèdent la commande, comme le vrai ; comme son env_reset, il
        # ne laisse passer aucune variable d'autorité exportée par l'appelant.
        self.stub(
            "sudo",
            "unset NIX_SSL_CERT_FILE SSL_CERT_FILE CURL_CA_BUNDLE\n"
            'while [ $# -gt 0 ]; do case "$1" in '
            '-u) shift 2;; *=*) export "$1"; shift;; *) break;; esac; done\n'
            'exec "$@"',
            log=False,
        )
        self.stub("hostname", "echo 192.0.2.10")
        # Autre chose que x86_64 : le bloc des miroirs Arch, qui réécrit
        # /etc/pacman.d, est alors sauté.
        self.stub("uname", "echo aarch64")
        self.stub("pgrep", "exit 0")
        self.stub("install")
        self.stub("openssl")
        self.stub("reflector")
        # Le binaire de chaque bureau, que la commande cherche une fois les
        # paquets posés : les faux gestionnaires ne l'apportent pas.
        for sonde in {d["probe"] for d in TODO._QEMU_DESKTOP.values()}:
            self.stub(sonde, log=False)
        self.stub("systemctl")
        # Les binaires que le bloc sonde après l'installation : les
        # doublures des gestionnaires de paquets ne posent rien, l'invité
        # simulé a donc son bureau d'avance.
        self.stub("gnome-shell", log=False)
        self.stub("cinnamon", log=False)
        self.stub(
            "getent",
            "echo 'gnome-remote-desktop:x:900:900::"
            f"{self.tmp}/grd:/usr/sbin/nologin'",
        )

    def stub(self, nom, corps="exit 0", log=True):
        trace = 'echo "${0##*/} $*" >> "$LOG"\n' if log else ""
        chemin = self.bin / nom
        chemin.write_text(f"#!/bin/bash\n{trace}{corps}\n")
        chemin.chmod(0o755)

    def grdctl(self, systeme=True, ignore="", deja="", stdin=True):
        """grdctl : son aide nomme « --system » ou non.

        Comme le vrai en mode système, il rend 0 à TOUTES les sous-commandes,
        qu'il ait pris le réglage ou non. Il garde un état, que relit
        « status --show-credentials » avec les lignes du vrai :
        identifiants, mot de passe, chemin de la clé, état activé. `ignore`
        nomme la sous-commande qu'il rend 0 SANS l'appliquer
        (« set-credentials », « set-tls-key », « enable »). `deja` : compte
        dont les identifiants sont déjà posés, par un passage précédent, avec
        SONDE pour mot de passe.

        `stdin` : grdctl 47 et suivants, dont l'aide écrit
        « [<username> [<password>]] » et qui lisent un mot de passe absent
        sur leur entrée standard. Faux : grdctl 46, qui ne prend que les deux
        arguments et ignore un appel qui n'en a qu'un."""
        aide = "--system   Configure system daemon" if systeme else "rdp"
        aide += (
            "\\n    set-credentials [<username> [<password>]]"
            if stdin
            else "\\n    set-credentials <username> <password>"
        )
        etat = self.tmp / "grd-etat"
        if deja:
            etat.write_text(f"user={deja}\npass={SONDE}\n")
        if stdin:
            pose_id = (
                "if [ $# -ge 5 ]; then p=$5; else IFS= read -r p; fi; "
                'echo "user=$4" >> "$E"; echo "pass=$p" >> "$E"'
            )
        else:
            pose_id = (
                '[ $# -ge 5 ] && { echo "user=$4" >> "$E"; '
                'echo "pass=$5" >> "$E"; }'
            )

        def pose(sous, action):
            return "true" if sous == ignore else action

        self.stub(
            "grdctl",
            f'E={etat}; touch "$E"\n'
            'case "$*" in\n'
            f'  --help) printf "  {aide}\\n";;\n'
            '  "--system rdp set-credentials "*) '
            + pose("set-credentials", pose_id)
            + ";;\n"
            '  "--system rdp set-tls-key "*) '
            + pose("set-tls-key", 'echo "key=$4" >> "$E"')
            + ";;\n"
            '  "--system rdp enable") '
            + pose("enable", 'echo "enabled" >> "$E"')
            + ";;\n"
            '  "--system status --show-credentials")\n'
            '    u=$(sed -n "s/^user=//p" "$E" | tail -1)\n'
            '    k=$(sed -n "s/^key=//p" "$E" | tail -1)\n'
            '    w=$(sed -n "s/^pass=//p" "$E" | tail -1)\n'
            '    s=disabled; grep -qx enabled "$E" && s=enabled\n'
            '    printf "RDP:\\n\\tStatus: %s\\n\\tTLS key: %s\\n'
            '\\tUsername: %s\\n\\tPassword: %s\\n" "$s" "${k:-(null)}"'
            ' "${u:-(null)}" "${w:-(null)}";;\n'
            "esac\n"
            "exit 0",
        )

    # Fichiers système que le bloc écrit : redirigés sous le dossier du
    # test, où chaque test peut les relire. Sans cela, un lancement en root
    # écrirait le /etc de la machine qui exécute les tests.
    ETC = (
        "/etc/X11/default-display-manager",
        "/etc/plasma-setup-done",
        "/etc/greetd/config.toml",
        "/etc/i3/config",
        "/etc/pam.d/system-login",
        "/etc/pam.d/wayvnc",
        "/etc/plasmalogin.conf.d",
        "/etc/sddm.conf.d",
        "/usr/lib/systemd/user",
        "/etc/nixos/configuration.nix",
        "/etc/nixos/erplibre-desktop.nix",
        "/var/lib/erplibre/ca-bundle.crt",
    )

    def etc(self, chemin):
        """Chemin, sous le dossier du test, qui remplace `chemin`."""
        return self.tmp / "sys" / chemin.lstrip("/")

    def run(self, cmd, os_id=""):
        cmd = cmd.replace(VM_LOGIN_FILE, str(self.pw_file))
        for chemin in self.ETC:
            self.etc(chemin).parent.mkdir(parents=True, exist_ok=True)
            cmd = cmd.replace(chemin, str(self.etc(chemin)))
        if os_id:
            release = self.tmp / "os-release"
            # ID_LIKE comme les vraies AlmaLinux et Rocky : la famille RHEL
            # s'y reconnaît (_qemu_epel_cmd).
            like = (
                'ID_LIKE="rhel centos fedora"\n'
                if os_id in ("almalinux", "rocky")
                else ""
            )
            release.write_text(f"ID={os_id}\n{like}")
            cmd = cmd.replace("/etc/os-release", str(release))
        res = subprocess.run(
            ["/bin/bash", "-c", "set -e; " + cmd],
            capture_output=True,
            text=True,
            env={
                "PATH": str(self.bin),
                "HOME": str(self.home),
                "LOG": str(self.log),
                "LANG": "C.UTF-8",
            },
            timeout=60,
        )
        return res.returncode, res.stdout + res.stderr, self.journal()

    def journal(self):
        return self.log.read_text().splitlines()


def _indice(lignes, fragment):
    """Indice de la première ligne du journal qui contient `fragment`."""
    for i, ligne in enumerate(lignes):
        if fragment in ligne:
            return i
    raise AssertionError(
        f"{fragment!r} absent du journal :\n" + "\n".join(lignes)
    )


class TestPackagesPerFamily(unittest.TestCase):
    """Les paquets que chaque branche installe, pour chaque saveur."""

    def test_gnome_gets_its_remote_desktop_everywhere(self):
        cmd = _cmd("gnome")
        for famille in ("apt", "pacman", "zypper"):
            self.assertIn(
                "gnome-remote-desktop openssl", _branche(cmd, famille), famille
            )
        self.assertIn(
            "sudo dnf install -y gnome-remote-desktop openssl",
            _branche(cmd, "dnf"),
        )

    def test_gnome_never_installs_xrdp_with_its_desktop(self):
        """Deux serveurs sur 3389, et xrdp sans session GNOME à ouvrir."""
        cmd = _cmd("gnome")
        for famille in ("apt", "dnf", "pacman", "zypper"):
            self.assertNotIn("xrdp", _branche(cmd, famille), famille)
        self.assertNotIn("tigervnc", cmd)

    def test_cinnamon_keeps_xrdp_and_tigervnc(self):
        cmd = _cmd("cinnamon")
        for famille in ("apt", "dnf", "zypper"):
            self.assertIn("xrdp", _branche(cmd, famille), famille)
        self.assertIn("lightdm-gtk-greeter tigervnc", _branche(cmd, "pacman"))
        self.assertNotIn("grdctl", cmd)

    def test_arch_gnome_line(self):
        self.assertIn(
            "pacman -S --needed --noconfirm gnome gdm "
            "gnome-remote-desktop openssl;",
            _branche(_cmd("gnome"), "pacman"),
        )

    def test_fedora_and_rhel_likes_are_told_apart(self):
        dnf = _branche(_cmd("gnome"), "dnf")
        self.assertIn("/etc/os-release", dnf)
        self.assertIn('EL_ENVS="workstation-product-environment"', dnf)
        self.assertIn('EL_X="-x firewalld"', dnf)
        self.assertIn("graphical-server-environment", dnf)

    def test_only_gnome_excludes_firewalld_on_fedora(self):
        """Le groupe cinnamon-desktop exige firewall-config, qui requiert
        firewalld : l'exclure y ferait échouer toute l'installation."""
        self.assertIn('EL_X="-x firewalld"', _branche(_cmd("gnome"), "dnf"))
        cinnamon = _branche(_cmd("cinnamon"), "dnf")
        self.assertIn('EL_ENVS="cinnamon-desktop"; EL_X=""; else', cinnamon)
        self.assertNotIn("-x firewalld", cinnamon)

    def test_a_desktop_that_does_not_install_fails_the_command(self):
        dnf = _branche(_cmd("gnome"), "dnf")
        self.assertIn("exit 1", dnf)
        # Le message passe par t(), jamais par un echo codé en dur ; sa
        # traduction française peut commencer par les mêmes mots.
        self.assertNotIn("graphique dnf trouve pour", dnf)
        self.assertIn(
            t("No dnf graphical environment could be installed for"), dnf
        )

    def test_the_first_login_wizard_is_marked_done_for_gnome(self):
        self.assertIn("gnome-initial-setup-done", _cmd("gnome"))
        self.assertNotIn("gnome-initial-setup-done", _cmd("cinnamon"))


class TestAntiSnapList(unittest.TestCase):
    """La liste anti-snap est celle d'Ubuntu : sur Debian, elle installerait
    epiphany-browser et evolution à côté de firefox-esr."""

    def test_ubuntu_keeps_it(self):
        self.assertIn(
            "epiphany-browser", _branche(_cmd("gnome", "deb", "ubuntu"), "apt")
        )

    def test_debian_does_not_get_it(self):
        apt = _branche(_cmd("gnome", "deb", "debian"), "apt")
        self.assertNotIn("epiphany-browser", apt)
        self.assertNotIn("evolution", apt)
        self.assertNotIn("firefox-", apt)

    def test_an_unknown_distro_keeps_the_old_behaviour(self):
        self.assertIn("epiphany-browser", _branche(_cmd("gnome"), "apt"))

    def test_flatpak_still_adds_its_packages_on_debian(self):
        pkgs = TODO._qemu_apt_store_pkgs("flatpak", "debian")
        self.assertEqual("flatpak gnome-software-plugin-flatpak", pkgs)

    def test_snap_adds_nothing(self):
        self.assertEqual("", TODO._qemu_apt_store_pkgs("snap", "ubuntu"))

    def test_evolution_only_where_thunderbird_is_recommended(self):
        for flavour in ("gnome", "cinnamon"):
            self.assertIn(
                "evolution",
                TODO._qemu_apt_store_pkgs("deb", "ubuntu", flavour).split(),
            )
        for flavour in ("plasma", "xfce", "hyprland", "i3"):
            pkgs = TODO._qemu_apt_store_pkgs("deb", "ubuntu", flavour).split()
            self.assertNotIn("evolution", pkgs, flavour)
            self.assertIn("firefox-", pkgs, flavour)
            self.assertIn("epiphany-browser", pkgs, flavour)

    def test_plasma_keeps_discover_away_from_snap(self):
        self.assertIn(
            "plasma-discover-backend-snap-",
            TODO._qemu_apt_store_pkgs("deb", "ubuntu", "plasma").split(),
        )

    def test_the_flatpak_plugin_is_the_flavour_store(self):
        par_saveur = {
            "gnome": "flatpak gnome-software-plugin-flatpak",
            "plasma": "flatpak plasma-discover plasma-discover-backend-flatpak",
            "i3": "flatpak",
        }
        for flavour, attendu in par_saveur.items():
            self.assertEqual(
                attendu,
                TODO._qemu_apt_store_pkgs("flatpak", "debian", flavour),
            )

    def test_the_old_call_is_unchanged(self):
        self.assertEqual(
            TODO._QEMU_APT_NO_SNAP, TODO._qemu_apt_store_pkgs("deb")
        )


class TestDesktopsForRelease(unittest.TestCase):
    """Les saveurs offertes, par couple (distribution, version)."""

    def test_what_is_not_listed_gets_nothing(self):
        for distro, version in (
            ("nixos", "25.11"),
            ("proxmox", "9"),
            ("inconnue", "1"),
            ("ubuntu", ""),
            ("", ""),
            ("ubuntu", "99.04"),
        ):
            self.assertEqual(
                [], TODO._qemu_desktops_for(distro, version), (distro, version)
            )

    def test_an_end_of_life_release_keeps_only_the_first_two(self):
        self.assertEqual(
            ["gnome", "cinnamon"], TODO._qemu_desktops_for("ubuntu", "25.10")
        )

    def test_el10_has_no_x_server_desktop(self):
        for distro in ("almalinux", "rocky"):
            self.assertEqual(
                ["gnome", "plasma"], TODO._qemu_desktops_for(distro, "10")
            )
            self.assertEqual(
                ["gnome", "cinnamon", "xfce", "i3"],
                TODO._qemu_desktops_for(distro, "9"),
            )

    def test_the_rolling_releases_get_every_flavour(self):
        tout = list(TODO._QEMU_DESKTOP)
        self.assertEqual(tout, TODO._qemu_desktops_for("arch", "latest"))
        self.assertEqual(
            tout, TODO._qemu_desktops_for("opensuse", "tumbleweed")
        )

    def test_the_order_is_the_table_order(self):
        self.assertEqual(
            ["gnome", "cinnamon", "plasma", "xfce", "hyprland", "i3"],
            TODO._qemu_desktops_for("ubuntu", "26.04"),
        )

    def test_every_listed_release_exists_in_the_catalogue(self):
        """Une version mal orthographiée dans la table masquerait la saveur
        sans erreur : chaque version doit être une clé de DISTROS."""
        from script.qemu import deploy_qemu

        self.assertEqual(
            set(TODO._QEMU_DESKTOP), set(TODO._QEMU_DESKTOP_RELEASES)
        )
        for flavour, par_distro in TODO._QEMU_DESKTOP_RELEASES.items():
            for distro, versions in par_distro.items():
                for v in versions:
                    self.assertIn(
                        v, deploy_qemu.DISTROS[distro][0], (flavour, distro)
                    )

    def test_the_form_table_says_the_same_as_the_cli(self):
        table = TODO._qemu_desktops_by_release()
        for distro, par_version in table.items():
            for version, saveurs in par_version.items():
                self.assertEqual(
                    TODO._qemu_desktops_for(distro, version), saveurs
                )
        self.assertNotIn("proxmox", table)

    def test_nixos_gets_every_flavour(self):
        """NixOS déclare chaque saveur par son module : toutes y sont."""
        self.assertEqual(
            list(TODO._QEMU_DESKTOP),
            TODO._qemu_desktops_for("nixos", "26.05"),
        )
        self.assertEqual(
            set(TODO._QEMU_DESKTOP), set(TODO._QEMU_NIXOS_DESKTOP)
        )

    def test_every_offered_pair_has_a_package_line(self):
        """Ce qui est offert sait s'installer : une ligne de paquets pour le
        gestionnaire de la distribution."""
        o = TODO.__new__(TODO)
        cle = {"apt": "apt", "pacman": "pacman", "zypper": "zypper"}
        for flavour, par_distro in TODO._QEMU_DESKTOP_RELEASES.items():
            de = TODO._QEMU_DESKTOP[flavour]
            for distro, versions in par_distro.items():
                fam = TODO._QEMU_DISTRO_FAMILY[distro]
                for v in versions:
                    with self.subTest(f=flavour, d=distro, v=v):
                        if fam == "nix":
                            self.assertTrue(TODO._QEMU_NIXOS_DESKTOP[flavour])
                        elif fam == "dnf":
                            self.assertTrue(
                                o._qemu_desktop_value(de, "dnf", distro, v)
                                or de.get("dnf_env")
                            )
                        else:
                            self.assertTrue(
                                o._qemu_desktop_value(de, cle[fam], distro, v)
                            )


class TestFlavourField(unittest.TestCase):
    def test_the_most_precise_key_wins(self):
        de = {"k": {"*": "a", "opensuse": "b", "opensuse:16.0": "c"}}
        val = TODO._qemu_desktop_value
        self.assertEqual("c", val(de, "k", "opensuse", "16.0"))
        self.assertEqual("b", val(de, "k", "opensuse", "tumbleweed"))
        self.assertEqual("a", val(de, "k", "arch", "latest"))
        self.assertEqual("a", val(de, "k"))

    def test_a_string_holds_everywhere_and_nothing_is_none(self):
        self.assertEqual("x", TODO._qemu_desktop_value({"k": "x"}, "k", "a"))
        self.assertIsNone(TODO._qemu_desktop_value({}, "k", "a"))
        self.assertIsNone(
            TODO._qemu_desktop_value({"k": {"fedora": "x"}}, "k", "arch")
        )


class TestNameSuffix(unittest.TestCase):
    def test_every_flavour_round_trips(self):
        for flavour, de in TODO._QEMU_DESKTOP.items():
            nom = vm_name(
                "erplibre-ubuntu-2604", flavour, TODO._qemu_desktop_suffixes()
            )
            self.assertEqual(
                ("erplibre-ubuntu-2604", flavour),
                TODO._qemu_split_desktop_suffix(nom),
            )

    def test_a_server_name_has_no_flavour(self):
        self.assertEqual(
            ("erplibre-debian-13", None),
            TODO._qemu_split_desktop_suffix("erplibre-debian-13"),
        )
        self.assertEqual(("", None), TODO._qemu_split_desktop_suffix(""))

    def test_the_suffixes_are_distinct(self):
        suffixes = list(TODO._qemu_desktop_suffixes().values())
        self.assertEqual(len(suffixes), len(set(suffixes)))


class TestUnknownFlavour(unittest.TestCase):
    def test_it_is_refused_not_replaced_by_gnome(self):
        for flavour in ("kde", "", None, True):
            with self.assertRaises(ValueError, msg=repr(flavour)):
                _cmd(flavour)


class TestRemoteAccessText(unittest.TestCase):
    """Ce que la commande dit et fait, lu dans le texte généré."""

    def test_the_probe_is_a_capability_not_a_version(self):
        acces = _acces(_cmd("gnome"))
        self.assertIn("grdctl --help", acces)
        self.assertIn("grep -q -- --system", acces)
        self.assertNotIn("--version", acces)

    def test_the_grd_sequence_is_in_order(self):
        acces = _acces(_cmd("gnome"))
        etapes = [
            "getent passwd gnome-remote-desktop",
            "openssl req",
            "grdctl --system rdp set-tls-key",
            "grdctl --system rdp set-tls-cert",
            "grdctl --system rdp set-credentials",
            "grdctl --system rdp enable",
            "systemctl enable --now gnome-remote-desktop.service",
            "systemctl restart gnome-remote-desktop.service",
        ]
        positions = [acces.index(e) for e in etapes]
        self.assertEqual(sorted(positions), positions)

    def test_the_xrdp_fallback_is_there_for_gnome(self):
        acces = _acces(_cmd("gnome"))
        repli = acces[acces.index("else ", acces.index("--system; then")) :]
        self.assertIn("install -y xrdp", repli)

    def test_no_vnc_hint_for_gnome(self):
        self.assertNotIn("vncserver", _cmd("gnome"))

    def test_the_vnc_hint_stays_for_cinnamon(self):
        self.assertIn("vncserver :1", _acces(_cmd("cinnamon")))

    def test_the_rdp_service_is_opened_in_firewalld(self):
        cmd = _cmd("gnome")
        self.assertIn("firewall-offline-cmd --add-service=rdp", cmd)
        self.assertIn("firewall-cmd --permanent --add-service=rdp", cmd)
        self.assertIn("firewall-cmd --reload", cmd)


class TestArchUpgrade(unittest.TestCase):
    """Arch ne supporte pas la mise à jour partielle."""

    def setUp(self):
        self.prep = TODO.__new__(TODO)._qemu_pacman_prepare_cmd()

    def test_no_masked_full_upgrade(self):
        self.assertNotIn("-Syu --noconfirm || true", self.prep)

    def test_no_isolated_refresh_and_install(self):
        self.assertNotIn(
            "pacman -Sy --needed --noconfirm reflector", self.prep
        )

    def test_keyring_then_full_upgrade_with_reflector(self):
        self.assertIn(
            "pacman -Sy --needed --noconfirm archlinux-keyring "
            "&& sudo pacman -Su --needed --noconfirm reflector",
            self.prep,
        )
        self.assertIn("pacman -Syy", self.prep)

    def test_the_upgrade_comes_before_the_desktop(self):
        pacman = _branche(_cmd("gnome"), "pacman")
        self.assertLess(
            pacman.index("pacman -Su "),
            pacman.index("pacman -S --needed --noconfirm gnome"),
        )
        self.assertLess(
            pacman.index("reflector --latest"),
            pacman.index("pacman -S --needed --noconfirm gnome"),
        )


class TestValidShell(unittest.TestCase):
    def test_every_offered_release_is_valid_shell(self):
        for flavour, par_distro in TODO._QEMU_DESKTOP_RELEASES.items():
            for distro, versions in par_distro.items():
                for version in versions:
                    with self.subTest(f=flavour, d=distro, v=version):
                        res = subprocess.run(
                            ["bash", "-n"],
                            input=_cmd(
                                flavour, "deb", distro, version=version
                            ),
                            capture_output=True,
                            text=True,
                        )
                        self.assertEqual(0, res.returncode, res.stderr)

    def test_every_flavour_and_distro_is_valid_shell(self):
        for flavour in TODO._QEMU_DESKTOP:
            for distro in DISTROS:
                for store in ("deb", "flatpak", "snap"):
                    with self.subTest(f=flavour, d=distro, s=store):
                        res = subprocess.run(
                            ["bash", "-n"],
                            input=_cmd(flavour, store, distro),
                            capture_output=True,
                            text=True,
                        )
                        self.assertEqual(0, res.returncode, res.stderr)

    def test_the_prepare_block_is_valid_shell(self):
        res = subprocess.run(
            ["bash", "-n"],
            input=TODO.__new__(TODO)._qemu_pacman_prepare_cmd(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, res.returncode, res.stderr)


class TestItRuns(unittest.TestCase):
    """Le bloc entier, exécuté sous « set -e » sur un invité simulé."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vm = _Invite(self._tmp.name)

    def _tmp_for(self, nom):
        """Un dossier neuf par sous-cas : chaque invité simulé a son PATH,
        son journal et l'état de son grdctl."""
        d = Path(self._tmp.name) / f"cas-{nom}"
        d.mkdir()
        return d

    def _apt(self):
        # apt-get pose une doublure « xrdp » quand on le lui demande : c'est
        # ce que « command -v xrdp » verra ensuite.
        self.vm.stub(
            "apt-get",
            f'case " $* " in *" xrdp "*) printf "#!/bin/bash\\nexit 0\\n" '
            f"> {self.vm.bin}/xrdp; chmod +x {self.vm.bin}/xrdp;; esac",
        )

    # --- GNOME Remote Desktop ---------------------------------------- #

    def test_fedora_gets_grd_and_no_firewalld(self):
        self.vm.stub("dnf")
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome", distro="fedora"), "fedora")
        self.assertEqual(0, rc, out)
        self.assertIn(
            "dnf -y -x firewalld group install workstation-product-environment",
            log,
        )
        self.assertFalse(any("xrdp" in ligne for ligne in log), log)
        self.assertIn("RDP 3389 (GNOME Remote Desktop)", out)
        self.assertIn(t("password chosen at deployment"), out)
        self.assertTrue(
            (self.vm.home / ".config/gnome-initial-setup-done").exists()
        )

    def test_the_public_default_is_named_a_chosen_one_never(self):
        """L'annonce nomme le défaut public d'après le mot de passe que
        grdctl a relu ; un mot de passe choisi reste « choisi »."""
        for nom, clair, attendu in (
            ("defaut", "erplibre", "/ erplibre"),
            ("choisi", SONDE, f"/ {t('password chosen at deployment')}"),
        ):
            with self.subTest(nom):
                self.vm = _Invite(self._tmp_for(nom))
                self.vm.pw_file.write_text(clair + "\n")
                self.vm.stub("dnf")
                self.vm.grdctl()
                rc, out, _log = self.vm.run(_cmd("gnome"), "fedora")
                self.assertEqual(0, rc, out)
                self.assertIn(attendu, out)
                self.assertNotIn(SONDE, out)

    def test_the_grd_steps_run_in_order(self):
        self.vm.stub("dnf")
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        ordre = [
            _indice(log, "openssl req"),
            _indice(log, "grdctl --system rdp set-tls-key"),
            _indice(log, "grdctl --system rdp set-tls-cert"),
            _indice(log, "grdctl --system rdp set-credentials"),
            _indice(log, "grdctl --system rdp enable"),
            _indice(log, "systemctl enable --now gnome-remote-desktop"),
            _indice(log, "systemctl restart gnome-remote-desktop"),
        ]
        self.assertEqual(sorted(ordre), ordre)

    def _user(self):
        return subprocess.run(
            ["id", "-un"], capture_output=True, text=True
        ).stdout.strip()

    def test_the_password_goes_through_grdctl_stdin(self):
        """grdctl 47 et suivants : le compte en argument, le mot de passe sur
        l'entrée standard, jamais sur la ligne de commande que pkexec
        journalise. Puis la relecture par « status --show-credentials »."""
        self.vm.stub("dnf")
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self.assertIn(
            f"grdctl --system rdp set-credentials {self._user()}", log
        )
        self.assertFalse(any(SONDE in ligne for ligne in log), log)
        self.assertIn(f"pass={SONDE}", (self.vm.tmp / "grd-etat").read_text())
        self.assertGreater(
            _indice(log, "grdctl --system status --show-credentials"),
            _indice(log, "grdctl --system rdp enable"),
        )
        self.assertIn("RDP 3389 (GNOME Remote Desktop)", out)

    def test_grdctl_46_takes_the_password_as_an_argument(self):
        """grdctl 46 ne lit rien sur son entrée : son aide le dit, et il
        reçoit les deux arguments."""
        self.vm.stub("dnf")
        self.vm.grdctl(stdin=False)
        rc, out, log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self.assertIn(
            f"grdctl --system rdp set-credentials {self._user()} {SONDE}",
            log,
        )
        self.assertIn("RDP 3389 (GNOME Remote Desktop)", out)

    def test_a_password_other_than_the_file_is_not_announced(self):
        """La relecture compare le mot de passe de grdctl au fichier : un
        mot de passe perdu ou ancien laisse l'accès non annoncé, et le
        fichier en place pour une relance."""
        self.vm.pw_file.write_text("Autre7essaiQ\n")
        self.vm.stub("dnf")
        self.vm.grdctl(ignore="set-credentials", deja=self._user())
        rc, out, _log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self._non_annonce(out)
        self.assertTrue(self.vm.pw_file.exists())

    def _non_annonce(self, out):
        self.assertNotIn("RDP 3389", out)
        self.assertIn(
            t(
                "GNOME Remote Desktop not configured;"
                " the VM console remains available"
            ),
            out,
        )

    def test_a_setting_grdctl_silently_drops_is_not_announced(self):
        """grdctl rend 0 même quand il n'applique rien : identifiants, clé
        ou activation perdus, la relecture le voit, l'accès distant n'est
        pas annoncé — et le bureau reste, la commande rendant 0."""
        for sous in ("set-credentials", "set-tls-key", "enable"):
            with self.subTest(sous=sous):
                vm = self.vm = _Invite(self._tmp_for(sous))
                vm.stub("dnf")
                vm.grdctl(ignore=sous)
                rc, out, log = vm.run(_cmd("gnome"), "fedora")
                self.assertEqual(0, rc, out)
                self._non_annonce(out)
                self.assertFalse(any("xrdp" in ligne for ligne in log), log)

    def test_an_inactive_daemon_is_not_announced(self):
        self.vm.stub("dnf")
        self.vm.grdctl()
        self.vm.stub(
            "systemctl",
            'case "$*" in "is-active --quiet gnome-remote-desktop.service")'
            " exit 3;; esac\nexit 0",
        )
        rc, out, _log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self._non_annonce(out)

    def test_an_existing_key_is_kept(self):
        """Rejouable : une clé et un certificat présents ne sont pas
        régénérés."""
        d = Path(self._tmp.name) / "grd/.local/share/gnome-remote-desktop"
        d.mkdir(parents=True)
        (d / "tls.key").write_text("k")
        (d / "tls.crt").write_text("c")
        self.vm.stub("dnf")
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self.assertFalse(any(ligne.startswith("openssl") for ligne in log))

    def test_an_earlier_xrdp_is_disabled_on_the_grd_path(self):
        self._apt()
        self.vm.stub("xrdp")
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome", distro="ubuntu"))
        self.assertEqual(0, rc, out)
        self.assertIn("systemctl disable --now xrdp", log)
        self.assertNotIn("systemctl enable --now xrdp", log)
        self.assertFalse(
            any(
                ligne.startswith("apt-get") and "xrdp" in ligne
                for ligne in log
            )
        )
        self.assertLess(
            _indice(log, "systemctl disable --now xrdp"),
            _indice(log, "systemctl restart gnome-remote-desktop"),
        )

    # --- mot de passe du compte ---------------------------------------- #

    def test_the_command_carries_no_password(self):
        """Ni le défaut public ni aucune valeur : la commande se garde dans
        session.json et passe sur la ligne de commande de sudo."""
        for keep in (False, True):
            cmd = _cmd("gnome", keep_login=keep)
            self.assertNotIn('set-credentials "$(id -un)" ', cmd)
            self.assertNotIn("/ erplibre", cmd)
            self.assertNotIn(SONDE, cmd)
            self.assertIn(f"$(cat {VM_LOGIN_FILE})", cmd)

    def test_the_file_is_removed_once_reread(self):
        self.vm.stub("dnf")
        self.vm.grdctl()
        rc, out, _log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self.assertIn("RDP 3389 (GNOME Remote Desktop)", out)
        self.assertFalse(self.vm.pw_file.exists())
        self.assertNotIn(SONDE, out)
        self.assertNotIn(str(self.vm.pw_file), out)

    def test_a_kept_file_stays_and_is_named(self):
        """« Garder dans la VM » : le fichier reste, et l'annonce donne la
        commande pour le lire — jamais sa valeur."""
        self.vm.stub("dnf")
        self.vm.grdctl()
        rc, out, _log = self.vm.run(_cmd("gnome", keep_login=True), "fedora")
        self.assertEqual(0, rc, out)
        self.assertTrue(self.vm.pw_file.exists())
        lire = VM_LOGIN_READ_CMD.replace(VM_LOGIN_FILE, str(self.vm.pw_file))
        self.assertIn(lire, out)
        self.assertNotIn(SONDE, out)

    def test_a_failed_reread_keeps_the_file_for_a_relaunch(self):
        self.vm.stub("dnf")
        self.vm.grdctl(ignore="enable")
        rc, out, _log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self._non_annonce(out)
        self.assertTrue(self.vm.pw_file.exists())

    def test_without_the_file_and_credentials_rdp_is_off(self):
        self.vm.pw_file.unlink()
        self.vm.stub("dnf")
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self.assertIn(
            t("VM password file absent: RDP credentials left unchanged"), out
        )
        self.assertFalse(any("set-credentials" in ligne for ligne in log))
        self._non_annonce(out)

    def test_without_the_file_existing_credentials_are_kept(self):
        """Suivi rouvert : le fichier a été lu et retiré au premier passage,
        les identifiants de grdctl tiennent toujours."""
        self.vm.pw_file.unlink()
        self.vm.stub("dnf")
        self.vm.grdctl(deja=self._user())
        rc, out, log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self.assertFalse(any("set-credentials" in ligne for ligne in log))
        self.assertIn("RDP 3389 (GNOME Remote Desktop)", out)

    def test_the_xrdp_fallback_removes_the_file(self):
        """xrdp passe par PAM : le clair ne lui sert à rien."""
        self._apt()
        self.vm.grdctl(systeme=False)
        rc, out, _log = self.vm.run(_cmd("gnome", distro="debian"))
        self.assertEqual(0, rc, out)
        self.assertFalse(self.vm.pw_file.exists())

    def test_the_xrdp_fallback_keeps_a_kept_file(self):
        self._apt()
        self.vm.grdctl(systeme=False)
        rc, out, _log = self.vm.run(
            _cmd("gnome", distro="debian", keep_login=True)
        )
        self.assertEqual(0, rc, out)
        self.assertTrue(self.vm.pw_file.exists())

    # --- repli xrdp ---------------------------------------------------- #

    def test_without_system_mode_xrdp_is_installed_and_enabled(self):
        """GNOME 43 (Debian 12) : grdctl n'a pas de mode système."""
        self._apt()
        self.vm.grdctl(systeme=False)
        rc, out, log = self.vm.run(_cmd("gnome", distro="debian"))
        self.assertEqual(0, rc, out)
        self.assertTrue(
            any(
                ligne.startswith("apt-get") and ligne.endswith(" xrdp")
                for ligne in log
            ),
            log,
        )
        self.assertIn("systemctl enable --now xrdp", log)
        self.assertFalse(any("grdctl --system" in ligne for ligne in log))
        self.assertIn("RDP 3389", out)

    def test_without_grdctl_at_all_xrdp_is_installed(self):
        self._apt()
        rc, out, log = self.vm.run(_cmd("gnome", distro="debian"))
        self.assertEqual(0, rc, out)
        self.assertIn("systemctl enable --now xrdp", log)

    def test_a_missing_xrdp_only_warns(self):
        self.vm.stub("apt-get", 'case " $* " in *" xrdp "*) exit 100;; esac')
        self.vm.grdctl(systeme=False)
        rc, out, log = self.vm.run(_cmd("gnome", distro="debian"))
        self.assertEqual(0, rc, out)
        self.assertIn("⚠", out)

    # --- dnf ----------------------------------------------------------- #

    def test_rhel_likes_keep_the_cascade(self):
        self.vm.stub("dnf")
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome"), "almalinux")
        self.assertEqual(0, rc, out)
        self.assertIn("dnf -y group install graphical-server-environment", log)
        self.assertFalse(any("-x firewalld" in ligne for ligne in log))

    def test_fedora_cinnamon_installs_without_excluding_firewalld(self):
        self.vm.stub("dnf")
        rc, out, log = self.vm.run(_cmd("cinnamon", distro="fedora"), "fedora")
        self.assertEqual(0, rc, out)
        self.assertIn("dnf -y group install cinnamon-desktop", log)
        self.assertFalse(any("-x firewalld" in ligne for ligne in log), log)

    def test_no_dnf_environment_fails_the_command(self):
        self.vm.stub("dnf", 'case "$*" in *"group install"*) exit 1;; esac')
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome"), "almalinux")
        self.assertEqual(1, rc, out)
        self.assertIn("❌", out)
        self.assertFalse(any("set-default" in ligne for ligne in log), log)

    def test_firewalld_opens_rdp_offline_and_live(self):
        self.vm.stub("dnf")
        self.vm.grdctl()
        self.vm.stub("firewall-cmd")
        self.vm.stub("firewall-offline-cmd")
        self.vm.stub(
            "systemctl",
            'case "$*" in "is-active --quiet firewalld") exit 0;; esac',
        )
        rc, out, log = self.vm.run(_cmd("gnome"), "almalinux")
        self.assertEqual(0, rc, out)
        self.assertIn("firewall-offline-cmd --add-service=rdp", log)
        self.assertIn("firewall-cmd --permanent --add-service=rdp", log)
        self.assertIn("firewall-cmd --reload", log)

    def test_firewalld_stopped_is_configured_offline_only(self):
        self.vm.stub("dnf")
        self.vm.grdctl()
        self.vm.stub("firewall-cmd")
        self.vm.stub("firewall-offline-cmd")
        self.vm.stub(
            "systemctl",
            'case "$*" in "is-active --quiet firewalld") exit 3;; esac',
        )
        rc, out, log = self.vm.run(_cmd("gnome"), "almalinux")
        self.assertEqual(0, rc, out)
        self.assertIn("firewall-offline-cmd --add-service=rdp", log)
        self.assertFalse(
            any(ligne.startswith("firewall-cmd") for ligne in log)
        )

    def test_a_refused_firewall_only_warns(self):
        self.vm.stub("dnf")
        self.vm.grdctl()
        self.vm.stub("firewall-cmd", "exit 1")
        self.vm.stub("firewall-offline-cmd", "exit 1")
        rc, out, log = self.vm.run(_cmd("gnome"), "almalinux")
        self.assertEqual(0, rc, out)
        self.assertIn("firewalld", out)
        self.assertIn("⚠", out)

    # --- pacman -------------------------------------------------------- #

    def test_arch_upgrades_before_installing_gnome(self):
        self.vm.stub("pacman")
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome", distro="arch"))
        self.assertEqual(0, rc, out)
        self.assertLess(
            _indice(log, "pacman -Sy --needed --noconfirm archlinux-keyring"),
            _indice(log, "pacman -Su --needed --noconfirm reflector"),
        )
        self.assertLess(
            _indice(log, "pacman -Su --needed --noconfirm reflector"),
            _indice(log, "pacman -S --needed --noconfirm gnome gdm"),
        )
        self.assertLess(
            _indice(log, "pacman -Syu --noconfirm"),
            _indice(log, "pacman -S --needed --noconfirm gnome gdm"),
        )
        self.assertIn("RDP 3389 (GNOME Remote Desktop)", out)

    def test_a_transient_failure_is_retried_once(self):
        marque = Path(self._tmp.name) / "deja"
        self.vm.stub(
            "pacman",
            f'if [ "$1" = -Su ] && [ ! -e {marque} ]; then '
            f"touch {marque}; exit 1; fi",
        )
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome", distro="arch"))
        self.assertEqual(0, rc, out)
        self.assertIn(
            "pacman -Syy --needed --noconfirm archlinux-keyring", log
        )
        self.assertIn(
            "pacman -S --needed --noconfirm gnome gdm "
            "gnome-remote-desktop openssl",
            log,
        )

    def test_a_failed_upgrade_stops_everything(self):
        self.vm.stub("pacman", '[ "$1" = -Su ] && exit 1; exit 0')
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome", distro="arch"))
        self.assertEqual(1, rc, out)
        self.assertIn("❌", out)
        self.assertFalse(any("noconfirm gnome" in ligne for ligne in log), log)

    def test_cinnamon_on_arch_announces_vnc(self):
        self.vm.stub(
            "pacman",
            f'case "$*" in *tigervnc*) printf "#!/bin/bash\\nexit 0\\n" '
            f"> {self.vm.bin}/vncserver; chmod +x {self.vm.bin}/vncserver;; "
            "esac",
        )
        rc, out, log = self.vm.run(_cmd("cinnamon", distro="arch"))
        self.assertEqual(0, rc, out)
        self.assertIn("VNC 5901", out)
        self.assertFalse(any("grdctl" in ligne for ligne in log))


class TestNewFlavoursRun(unittest.TestCase):
    """Les saveurs ajoutées à GNOME et Cinnamon, exécutées sur un invité
    simulé : ce que chaque gestionnaire installe, le gestionnaire
    d'affichage retenu et ce que la saveur configure avant son démarrage."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vm = _Invite(self._tmp.name)

    def _xrdp_apt(self):
        self.vm.stub(
            "apt-get",
            f'case " $* " in *" xrdp "*) printf "#!/bin/bash\\nexit 0\\n" '
            f"> {self.vm.bin}/xrdp; chmod +x {self.vm.bin}/xrdp;; esac",
        )

    # --- dnf ----------------------------------------------------------- #

    def test_fedora_plasma_line_dm_and_first_run_marker(self):
        self.vm.stub("dnf")
        cmd = _cmd("plasma", distro="fedora", version="44")
        rc, out, log = self.vm.run(cmd, "fedora")
        self.assertEqual(0, rc, out)
        self.assertIn(
            "dnf -y -x firewalld -x firewall-config install "
            "@kde-desktop-environment krdp openssl",
            log,
        )
        self.assertFalse(any("epel-release" in l for l in log), log)
        self.assertIn("systemctl enable --force plasmalogin", log)
        self.assertTrue(self.vm.etc("/etc/plasma-setup-done").exists())
        # touch est un vrai outil de l'invité simulé : l'ordre se lit dans
        # la commande.
        self.assertLess(
            cmd.index("sudo touch /etc/plasma-setup-done"),
            cmd.index("systemctl start display-manager"),
        )

    def test_el_enables_epel_and_crb_before_the_desktop(self):
        self.vm.stub("dnf")
        self.vm.stub("crb")
        cmd = _cmd("plasma", distro="almalinux", version="10").replace(
            "/usr/bin/crb", "crb"
        )
        rc, out, log = self.vm.run(cmd, "almalinux")
        self.assertEqual(0, rc, out)
        self.assertLess(
            _indice(log, "dnf install -y epel-release"),
            _indice(log, "crb enable"),
        )
        self.assertLess(
            _indice(log, "crb enable"),
            _indice(log, "install @kde-desktop-environment"),
        )

    def test_a_refused_exclusion_is_retried_without_it(self):
        self.vm.stub("dnf", 'case "$*" in *" -x "*) exit 1;; esac')
        rc, out, log = self.vm.run(
            _cmd("xfce", distro="fedora", version="45"), "fedora"
        )
        self.assertEqual(0, rc, out)
        self.assertIn("dnf -y install @xfce-desktop-environment", log)

    def test_a_desktop_dnf_cannot_install_fails_the_command(self):
        self.vm.stub("dnf", 'case "$*" in *@*) exit 1;; esac')
        rc, out, log = self.vm.run(
            _cmd("i3", distro="fedora", version="44"), "fedora"
        )
        self.assertEqual(1, rc, out)
        self.assertIn("❌", out)
        self.assertFalse(any("set-default" in l for l in log), log)

    def test_el9_cinnamon_is_a_package_list_and_xrdp_only_warns(self):
        self.vm.stub("dnf", 'case "$*" in *xrdp*) exit 1;; esac')
        self.vm.stub("crb")
        cmd = _cmd("cinnamon", distro="rocky", version="9").replace(
            "/usr/bin/crb", "crb"
        )
        rc, out, log = self.vm.run(cmd, "rocky")
        self.assertEqual(0, rc, out)
        self.assertIn(
            "dnf -y install @base-x cinnamon lightdm lightdm-gtk dbus-x11", log
        )
        self.assertFalse(any("group install" in l for l in log), log)
        self.assertIn("⚠", out)

    def test_every_el_pair_runs_its_own_line_after_epel(self):
        """Chaque saveur offerte sur AlmaLinux et Rocky, exécutée : EPEL et
        CRB d'abord, puis la ligne propre à EL — jamais l'environnement de
        Fedora ni la cascade de groupes, absents d'EPEL."""
        attendus = {
            ("cinnamon", "9"): "-y install @base-x cinnamon lightdm",
            ("xfce", "9"): "-y -x gdm install @base-x @xfce-desktop lightdm",
            ("i3", "9"): "-y -x firewalld -x firewall-config install "
            "@base-x i3 i3status",
            ("plasma", "10"): "-y -x firewalld -x firewall-config install "
            "@kde-desktop-environment",
        }
        for distro in ("almalinux", "rocky"):
            for version in ("9", "10"):
                offertes = TODO._qemu_desktops_for(distro, version)
                for flavour in offertes:
                    if flavour == "gnome":
                        continue
                    with self.subTest(f=flavour, d=distro, v=version):
                        self.vm = _Invite(
                            self._tmp_for(f"{flavour}-{distro}-{version}")
                        )
                        self.vm.stub("dnf")
                        self.vm.stub("crb")
                        cmd = _cmd(
                            flavour, distro=distro, version=version
                        ).replace("/usr/bin/crb", "crb")
                        rc, out, log = self.vm.run(cmd, distro)
                        self.assertEqual(0, rc, out)
                        ligne = attendus[(flavour, version)]
                        self.assertLess(
                            _indice(log, "install -y epel-release"),
                            _indice(log, ligne),
                        )
                        self.assertFalse(
                            any("group install" in l for l in log), log
                        )

    def test_each_flavour_enables_its_own_display_manager(self):
        """Le gestionnaire d'affichage activé, pour chaque couple offert :
        plasma-login-manager là où l'environnement de Plasma l'impose."""
        plasmalogin = ("fedora", "almalinux", "rocky", "arch")
        attendu = {
            "xfce": lambda d: "lightdm",
            "i3": lambda d: "lightdm",
            "cosmic": lambda d: "cosmic-greeter",
            "hyprland": lambda d: "greetd",
            "plasma": lambda d: "plasmalogin" if d in plasmalogin else "sddm",
        }
        for flavour, dm in attendu.items():
            for distro, versions in TODO._QEMU_DESKTOP_RELEASES[
                flavour
            ].items():
                if distro == "nixos":
                    # Déclaré par le module, jamais activé à l'exécution.
                    continue
                for version in versions:
                    with self.subTest(f=flavour, d=distro, v=version):
                        cmd = _cmd(flavour, distro=distro, version=version)
                        self.assertIn(
                            f"systemctl enable --force {dm(distro)} ", cmd
                        )

    def test_fedora_cinnamon_keeps_its_group(self):
        self.vm.stub("dnf")
        rc, out, log = self.vm.run(
            _cmd("cinnamon", distro="fedora", version="44"), "fedora"
        )
        self.assertEqual(0, rc, out)
        self.assertIn("dnf -y group install cinnamon-desktop", log)
        self.assertFalse(any("epel-release" in l for l in log), log)

    # --- apt ----------------------------------------------------------- #

    def test_apt_plasma_preselects_sddm(self):
        self.vm.stub("debconf-set-selections", 'cat >> "$LOG"')
        self._xrdp_apt()
        cmd = _cmd("plasma", distro="ubuntu", version="26.04")
        rc, out, log = self.vm.run(cmd)
        self.assertEqual(0, rc, out)
        self.assertLess(
            _indice(log, "shared/default-x-display-manager select sddm"),
            _indice(log, "install -y kde-plasma-desktop sddm"),
        )
        self.assertEqual(
            "/usr/bin/sddm\n",
            self.vm.etc("/etc/X11/default-display-manager").read_text(),
        )
        self.assertIn("systemctl enable --force sddm", log)

    def test_a_flavour_apt_cannot_install_fails_the_command(self):
        self.vm.stub("apt-get")
        rc, out, log = self.vm.run(_cmd("cosmic", distro="fedora"))
        self.assertEqual(1, rc, out)
        self.assertIn("❌", out)
        self.assertFalse(any("install -y" in l for l in log), log)

    def test_xfce_gets_xrdp_and_announces_rdp(self):
        self._xrdp_apt()
        rc, out, log = self.vm.run(_cmd("xfce", distro="debian", version="13"))
        self.assertEqual(0, rc, out)
        self.assertIn(
            "install -y xfce4 xfce4-goodies lightdm lightdm-gtk-greeter "
            "dbus-x11 xrdp",
            " ".join(log),
        )
        self.assertIn("systemctl enable --now xrdp", log)
        self.assertIn("RDP 3389", out)
        self.assertEqual(
            "/usr/sbin/lightdm\n",
            self.vm.etc("/etc/X11/default-display-manager").read_text(),
        )

    def test_hyprland_on_apt_leaves_the_display_manager_file_alone(self):
        self.vm.stub("apt-get")
        rc, out, _log = self.vm.run(
            _cmd("hyprland", distro="ubuntu", version="26.04")
        )
        self.assertEqual(0, rc, out)
        self.assertFalse(
            self.vm.etc("/etc/X11/default-display-manager").exists()
        )

    def test_gnome_keeps_a_plain_enable(self):
        self.vm.stub("apt-get")
        self.vm.grdctl()
        rc, out, log = self.vm.run(
            _cmd("gnome", distro="debian", version="13")
        )
        self.assertEqual(0, rc, out)
        self.assertIn("systemctl enable gdm", log)
        self.assertFalse(any("enable --force" in l for l in log), log)

    # --- pacman et zypper ---------------------------------------------- #

    def test_arch_cosmic_names_its_vulkan_driver(self):
        self.vm.stub("pacman")
        rc, out, log = self.vm.run(
            _cmd("cosmic", distro="arch", version="latest")
        )
        self.assertEqual(0, rc, out)
        self.assertIn(
            "pacman -S --needed --noconfirm cosmic-session vulkan-swrast", log
        )
        self.assertIn("systemctl enable --force cosmic-greeter", log)
        self.assertTrue(
            (self.vm.home / ".config/cosmic-initial-setup-done").exists()
        )

    def test_zypper_plasma_sets_the_display_manager_alternative(self):
        self.vm.stub("zypper")
        self.vm.stub("update-alternatives")
        rc, out, log = self.vm.run(
            _cmd("plasma", distro="opensuse", version="tumbleweed")
        )
        self.assertEqual(0, rc, out)
        self.assertLess(
            _indice(log, "patterns-kde-kde_plasma sddm-qt6"),
            _indice(
                log,
                "update-alternatives --set default-displaymanager "
                "/usr/lib/X11/displaymanagers/sddm",
            ),
        )

    def test_leap_i3_has_no_i3status(self):
        self.vm.stub("zypper")
        rc, out, log = self.vm.run(
            _cmd("i3", distro="opensuse", version="16.0")
        )
        self.assertEqual(0, rc, out)
        ligne = log[_indice(log, "zypper --non-interactive install")]
        self.assertNotIn("i3status", ligne)
        self.assertIn(" i3 ", ligne)

    # --- configuration propre à la saveur ------------------------------ #

    def _i3(self, distro, version, existant=None):
        etc = self.vm.etc("/etc/i3/config")
        etc.parent.mkdir(parents=True, exist_ok=True)
        etc.write_text("bar {\n    status_command i3status\n}\n")
        cfg = self.vm.home / ".config/i3/config"
        if existant is not None:
            cfg.parent.mkdir(parents=True)
            cfg.write_text(existant)
        self.vm.stub("zypper")
        self.vm.stub("pacman")
        rc, out, _log = self.vm.run(_cmd("i3", distro=distro, version=version))
        self.assertEqual(0, rc, out)
        return cfg.read_text()

    def test_i3_gets_a_user_config_so_the_wizard_stays_quiet(self):
        self.assertIn("status_command i3status", self._i3("arch", "latest"))

    def test_leap_i3_config_drops_the_status_line(self):
        self.assertNotIn("status_command", self._i3("opensuse", "16.0"))

    def test_an_existing_i3_config_is_kept(self):
        self.assertEqual("mien\n", self._i3("arch", "latest", "mien\n"))

    GESTIONNAIRE = {
        "ubuntu": "apt-get",
        "arch": "pacman",
        "opensuse": "zypper",
    }

    def _hyprland(self, distro, version, lanceur=True, greetd=None):
        """Hyprland sur un invité qui n'a QUE le gestionnaire de paquets de
        `distro` : c'est sa branche, et sa ligne de paquets, qui tournent."""
        gc = self.vm.etc("/etc/greetd/config.toml")
        gc.parent.mkdir(parents=True, exist_ok=True)
        gc.write_text(
            greetd
            or "[terminal]\nvt = 7\n\n[default_session]\n"
            'command = "agreety --cmd /bin/sh"\nuser = "_greetd"\n'
        )
        self.vm.stub(self.GESTIONNAIRE[distro])
        if lanceur:
            self.vm.stub("start-hyprland")
        rc, out, log = self.vm.run(
            _cmd("hyprland", distro=distro, version=version)
        )
        self.assertEqual(0, rc, out)
        return gc.read_text(), out, log

    def test_hyprland_installs_its_greeter_on_each_system(self):
        attendus = {
            ("ubuntu", "26.04"): ("apt-get", "greetd tuigreet"),
            ("arch", "latest"): ("pacman", "greetd greetd-tuigreet"),
            ("opensuse", "tumbleweed"): (
                "zypper",
                "greetd greetd-branding-upstream tuigreet",
            ),
        }
        for (distro, version), (pm, paquets) in attendus.items():
            with self.subTest(distro):
                self.vm = _Invite(self._tmp_for(distro))
                _conf, _out, log = self._hyprland(distro, version)
                ligne = " ".join(l for l in log if l.startswith(pm))
                self.assertIn(paquets, ligne)
                self.assertIn("hyprland xdg-desktop-portal-hyprland", ligne)

    def test_a_rerun_keeps_the_existing_configurations(self):
        mien = (
            '[terminal]\nvt = 1\n\n[initial_session]\nuser = "x"\n'
            '[default_session]\ncommand = "tuigreet --cmd sway"\n'
        )
        hypr = self.vm.home / ".config/hypr/hyprland.lua"
        hypr.parent.mkdir(parents=True)
        hypr.write_text("-- mien\n")
        conf, _out, _log = self._hyprland("arch", "latest", greetd=mien)
        self.assertEqual(mien, conf)
        self.assertEqual("-- mien\n", hypr.read_text())

    def test_hyprland_greetd_keeps_the_shipped_user_and_vt(self):
        conf, _out, log = self._hyprland("ubuntu", "26.04")
        self.assertIn('user = "_greetd"', conf)
        self.assertIn("vt = 7", conf)
        self.assertIn('command = "tuigreet --time --cmd start-hyprland"', conf)
        self.assertIn("systemctl enable --force greetd", log)

    def test_hyprland_without_its_launcher_starts_the_compositor(self):
        conf, _out, _log = self._hyprland("ubuntu", "26.04", lanceur=False)
        self.assertIn('--cmd Hyprland"', conf)

    def test_hyprland_config_format_follows_the_release(self):
        self._hyprland("ubuntu", "26.04")
        hypr = self.vm.home / ".config/hypr"
        conf = (hypr / "hyprland.conf").read_text()
        self.assertIn("no_hardware_cursors = true", conf)
        self.assertIn("bind = $mod, Return, exec, kitty", conf)
        self.assertFalse((hypr / "hyprland.lua").exists())

        self.vm = _Invite(self._tmp_for("arch"))
        self._hyprland("arch", "latest")
        hypr = self.vm.home / ".config/hypr"
        lua = (hypr / "hyprland.lua").read_text()
        self.assertIn("no_hardware_cursors = true", lua)
        self.assertIn('hl.dsp.exec_cmd("kitty")', lua)
        self.assertFalse((hypr / "hyprland.conf").exists())

    def _tmp_for(self, nom):
        d = Path(self._tmp.name) / f"cas-{nom}"
        d.mkdir()
        return d

    def test_flavours_without_a_server_announce_the_console_only(self):
        """Ni xrdp ni pare-feu pour une saveur dont l'accès distant n'est
        pas posé, même quand un xrdp traîne sur le système : COSMIC, et
        Plasma sur Leap 16.0."""
        for flavour, distro, version, pm in (
            ("cosmic", "arch", "latest", "pacman"),
            ("plasma", "opensuse", "16.0", "zypper"),
        ):
            with self.subTest(flavour):
                self.vm = _Invite(self._tmp_for(f"{flavour}-{distro}"))
                self.vm.stub(pm)
                self.vm.stub("xrdp")
                self.vm.stub("firewall-cmd")
                self.vm.stub("busctl")
                rc, out, log = self.vm.run(
                    _cmd(flavour, distro=distro, version=version)
                )
                self.assertEqual(0, rc, out)
                self.assertIn(t("none, the hypervisor console only"), out)
                self.assertFalse(any("xrdp" in l for l in log), log)
                self.assertFalse(any("firewall" in l for l in log), log)
                self.assertFalse(any("busctl" in l for l in log), log)
                self.assertFalse(
                    (self.vm.home / ".config/krdpserverrc").exists()
                )


class TestNixosDesktop(unittest.TestCase):
    """NixOS déclare la saveur dans /etc/nixos/erplibre-desktop.nix, que
    « nixos-rebuild switch » applique : /etc/systemd et /etc/pam.d y sont
    produits par la construction, en lecture seule."""

    def _module(self, flavour):
        return TODO.__new__(TODO)._qemu_nixos_desktop_module(flavour)

    def _nix(self, flavour):
        return _cmd(flavour, distro="nixos", version="26.05")

    def test_each_flavour_declares_its_desktop_and_display_manager(self):
        attendu = {
            "gnome": ("desktopManager.gnome.enable", "gdm.enable"),
            "cinnamon": ("cinnamon.enable", "lightdm.enable"),
            "plasma": ("plasma6.enable", "sddm.enable"),
            "xfce": ("xfce.enable", "lightdm.enable"),
            "cosmic": ("cosmic.enable", "cosmic-greeter.enable"),
            "hyprland": ("programs.hyprland.enable", "greetd.enable"),
            "i3": ("windowManager.i3.enable", "lightdm.enable"),
        }
        self.assertEqual(set(TODO._QEMU_DESKTOP), set(attendu))
        for flavour, cles in attendu.items():
            with self.subTest(flavour=flavour):
                module = self._module(flavour)
                for cle in cles:
                    self.assertIn(f"{cle} = true;", module)
                self.assertIn(
                    "system.autoUpgrade.allowReboot = lib.mkForce false;",
                    module,
                )
                self.assertTrue(module.rstrip().endswith("}"))
                self.assertEqual(module.count("{"), module.count("}"))

    def test_the_firewall_opens_the_server_port_only(self):
        self.assertIn("allowedTCPPorts = [ 3389 ];", self._module("gnome"))
        self.assertIn("allowedTCPPorts = [ 3389 ];", self._module("plasma"))
        self.assertIn("allowedTCPPorts = [ 5900 ];", self._module("hyprland"))
        self.assertNotIn("allowedTCPPorts", self._module("cosmic"))
        self.assertNotIn("xrdp", self._module("cosmic"))

    def test_x11_flavours_get_xrdp_on_their_own_session(self):
        for flavour in ("xfce", "i3", "cinnamon"):
            with self.subTest(flavour=flavour):
                module = self._module(flavour)
                session = TODO._QEMU_DESKTOP[flavour]["x_session"]
                self.assertIn("services.xrdp.openFirewall = true;", module)
                self.assertIn(
                    f'services.xrdp.defaultWindowManager = "{session}";',
                    module,
                )

    def test_the_vm_account_is_substituted_where_a_session_opens(self):
        """Plasma et Hyprland ouvrent la session du compte d'office ; le
        nom n'est connu que dans l'invité."""
        for flavour in ("plasma", "hyprland"):
            self.assertIn('"@EL_USER@"', self._module(flavour))
            self.assertIn('sed "s/@EL_USER@/$(id -un)/g"', self._nix(flavour))
        self.assertNotIn("@EL_USER@", self._module("xfce"))

    def test_gnome_remote_desktop_is_wanted_by_the_graphical_target(self):
        self.assertIn(
            'systemd.services.gnome-remote-desktop.wantedBy = [ "graphical.target" ];',
            self._module("gnome"),
        )

    def test_nothing_is_enabled_or_written_under_etc_at_runtime(self):
        for flavour in TODO._QEMU_DESKTOP:
            with self.subTest(flavour=flavour):
                cmd = self._nix(flavour)
                # Le repli xrdp de GNOME, sans mode système, garde son
                # aiguillage ; l'installation du bureau n'en a aucun.
                self.assertNotIn("apt-get", cmd[: cmd.index("EL_REM=")])
                self.assertNotIn("set-default", cmd)
                self.assertNotIn("systemctl enable --force", cmd)
                self.assertNotIn("/etc/pam.d/wayvnc", cmd)
                self.assertNotIn("/etc/greetd/config.toml", cmd)
                self.assertNotIn(".conf.d/erplibre-autologin.conf", cmd)
                self.assertNotIn("enable --now gnome-remote-desktop", cmd)
                self.assertIn("nixos-rebuild switch", cmd)

    def test_hyprland_keeps_the_account_files_but_not_the_unit(self):
        """L'unité wayvnc est celle du module : une unité du compte, au
        chemin /usr/bin, la masquerait."""
        cmd = self._nix("hyprland")
        self.assertIn(".config/wayvnc/config", cmd)
        self.assertIn("hyprland.lua", cmd)
        self.assertNotIn(".config/systemd/user/wayvnc.service", cmd)

    def test_openssl_is_declared_for_the_server_keys(self):
        """GNOME Remote Desktop, KRdp et wayvnc créent leurs clés par
        openssl, absent du système de base ; une seule liste de paquets,
        un attribut répété étant une erreur de Nix."""
        for flavour in TODO._QEMU_DESKTOP:
            module = self._module(flavour)
            self.assertEqual(1, module.count("environment.systemPackages"))
            self.assertIn("pkgs.openssl", module)
        self.assertIn("pkgs.kitty", self._module("hyprland"))
        self.assertIn("pkgs.xterm", self._module("i3"))

    def test_networkmanager_stays_off(self):
        """GNOME, Plasma et COSMIC l'activent ; il heurte la configuration
        réseau de l'image."""
        for flavour in TODO._QEMU_DESKTOP:
            self.assertIn(
                "networking.networkmanager.enable = lib.mkForce false;",
                self._module(flavour),
            )

    def test_xrdp_is_found_by_its_unit(self):
        """NixOS ne met pas xrdp dans le PATH : l'annonce lit l'unité."""
        self.assertIn("systemctl cat xrdp.service", self._nix("xfce"))
        self.assertNotIn(
            "systemctl cat xrdp.service",
            _cmd("xfce", distro="debian", version="13"),
        )

    def test_i3_reads_the_account_config_at_the_console(self):
        """configFile lancerait « i3 -c /etc/i3/config » et la console
        ignorerait la copie du compte ; /etc/i3/config est posé à part."""
        module = self._module("i3")
        self.assertIn('environment.etc."i3/config".source', module)
        self.assertNotIn("configFile", module)

    def test_the_i3_copy_is_writable(self):
        """L'original est un fichier du store, en 0444."""
        self.assertIn('chmod 644 "$HOME/.config/i3/config"', self._nix("i3"))

    def test_krdp_asks_for_tls_security_on_nixos(self):
        """KRdp 6.6 propose NLA sans pouvoir le mener par PAM."""
        self.assertIn("NLA", self._nix("plasma"))
        self.assertNotIn("NLA", _cmd("plasma", distro="fedora", version="44"))

    def test_krdp_finds_the_declared_unit(self):
        self.assertIn("/etc/systemd/user", self._nix("plasma"))

    def test_every_flavour_is_valid_shell(self):
        for flavour in TODO._QEMU_DESKTOP:
            res = subprocess.run(
                ["bash", "-n", "-c", self._nix(flavour)], capture_output=True
            )
            self.assertEqual(0, res.returncode, (flavour, res.stderr))


class TestNixosDesktopRun(unittest.TestCase):
    """Le bloc NixOS exécuté dans un invité simulé."""

    CONF = "{ ... }:\n{\n  imports = [\n    ./hardware-configuration.nix\n  ];\n}\n"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vm = _Invite(tmp.name)
        self.conf = self.vm.etc("/etc/nixos/configuration.nix")
        self.conf.parent.mkdir(parents=True, exist_ok=True)
        self.conf.write_text(self.CONF)
        self.vm.stub("nixos-rebuild")
        self.vm.stub("busctl")
        self.vm.stub("ssh-keygen")

    def test_the_module_is_written_imported_once_and_applied(self):
        cmd = _cmd("xfce", distro="nixos", version="26.05")
        for _ in range(2):
            rc, out, log = self.vm.run(cmd)
            self.assertEqual(0, rc, out)
        module = self.vm.etc("/etc/nixos/erplibre-desktop.nix").read_text()
        self.assertEqual(
            TODO.__new__(TODO)._qemu_nixos_desktop_module("xfce"), module
        )
        self.assertEqual(
            1, self.conf.read_text().count("./erplibre-desktop.nix")
        )
        self.assertIn(
            "imports = [\n    ./erplibre-desktop.nix\n"
            "    ./hardware-configuration.nix\n",
            self.conf.read_text(),
        )
        self.assertIn("nixos-rebuild switch", log)
        self.assertLess(
            _indice(log, "nixos-rebuild switch"),
            _indice(log, "systemctl start display-manager.service"),
        )

    def test_the_account_name_replaces_the_placeholder(self):
        rc, out, _log = self.vm.run(
            _cmd("plasma", distro="nixos", version="26.05")
        )
        self.assertEqual(0, rc, out)
        module = self.vm.etc("/etc/nixos/erplibre-desktop.nix").read_text()
        compte = subprocess.run(
            ["id", "-un"], capture_output=True, text=True
        ).stdout.strip()
        self.assertIn(f'autoLogin.user = "{compte}";', module)
        self.assertNotIn("@EL_USER@", module)

    def test_a_configuration_without_imports_stops_the_command(self):
        self.conf.write_text("{ ... }:\n{\n}\n")
        rc, out, log = self.vm.run(_cmd("i3", distro="nixos", version="26.05"))
        self.assertNotEqual(0, rc)
        self.assertIn("imports", out)
        self.assertNotIn("nixos-rebuild switch", log)

    def test_a_rebuild_without_display_manager_fails(self):
        self.vm.stub(
            "systemctl",
            'case "$*" in "cat display-manager.service") exit 1;; esac',
        )
        rc, out, _log = self.vm.run(
            _cmd("cosmic", distro="nixos", version="26.05")
        )
        self.assertNotEqual(0, rc)
        self.assertIn("❌", out)

    def test_the_cache_authority_reaches_the_root_build(self):
        """Le /etc/sudoers de NixOS n'inclut pas /etc/sudoers.d : la
        variable passe en argument de sudo, jusqu'à la construction de
        root qui télécharge."""
        faisceau = self.vm.etc("/var/lib/erplibre/ca-bundle.crt")
        faisceau.parent.mkdir(parents=True, exist_ok=True)
        faisceau.write_text("ca\n")
        self.vm.stub("nixos-rebuild", 'echo "ca=$NIX_SSL_CERT_FILE" >> "$LOG"')
        rc, out, log = self.vm.run(_cmd("i3", distro="nixos", version="26.05"))
        self.assertEqual(0, rc, out)
        self.assertIn(f"ca={faisceau}", log)

    def test_without_authority_the_build_gets_none(self):
        self.vm.stub(
            "nixos-rebuild", 'echo "ca=${NIX_SSL_CERT_FILE:-}" >> "$LOG"'
        )
        rc, out, log = self.vm.run(_cmd("i3", distro="nixos", version="26.05"))
        self.assertEqual(0, rc, out)
        self.assertIn("ca=", log)

    def test_a_failed_rebuild_stops_the_command(self):
        """Une VM qui avait déjà un bureau a déjà display-manager.service :
        seul le code de retour dit que la nouvelle saveur n'a pas pris."""
        self.vm.stub("nixos-rebuild", "exit 1")
        rc, out, log = self.vm.run(
            _cmd("xfce", distro="nixos", version="26.05")
        )
        self.assertNotEqual(0, rc)
        self.assertIn("❌", out)
        self.assertNotIn(
            "systemctl start display-manager.service", "\n".join(log)
        )

    def _readlink(self, demarre, courant):
        self.vm.stub(
            "readlink",
            'case "$2" in /run/booted-system/*) echo ' + demarre + ";; "
            "*) echo " + courant + ";; esac",
            log=False,
        )

    def test_logind_restarts_after_a_version_jump(self):
        """Système reconstruit plus récent que celui qui a démarré : logind
        ancien, pam_systemd neuf, l'écran de connexion de GDM ne s'ouvre
        pas."""
        self._readlink("/nix/store/a-systemd", "/nix/store/b-systemd")
        rc, out, log = self.vm.run(
            _cmd("gnome", distro="nixos", version="26.05")
        )
        self.assertEqual(0, rc, out)
        self.assertLess(
            _indice(log, "systemctl cat display-manager.service"),
            _indice(log, "systemctl restart systemd-logind"),
        )

    def test_logind_stays_when_the_versions_match(self):
        self._readlink("/nix/store/a-systemd", "/nix/store/a-systemd")
        rc, out, log = self.vm.run(
            _cmd("gnome", distro="nixos", version="26.05")
        )
        self.assertEqual(0, rc, out)
        self.assertNotIn("systemctl restart systemd-logind", log)

    def test_a_rebuild_that_returns_4_is_not_the_verdict(self):
        """switch-to-configuration rend 4 quand une unité n'a pas redémarré,
        système activé quand même : le verdict est display-manager."""
        self.vm.stub("nixos-rebuild", "exit 4")
        rc, out, _log = self.vm.run(
            _cmd("cosmic", distro="nixos", version="26.05")
        )
        self.assertEqual(0, rc, out)
        self.assertIn("⚠", out)


class TestRemoteAccessPerRelease(unittest.TestCase):
    """L'accès distant choisi par (saveur, distribution, version), exécuté
    sur un invité simulé : KRdp, wayvnc, ou xrdp et TigerVNC sur la
    session X de la saveur."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vm = _Invite(self._tmp.name)
        self.vm.stub("busctl")
        self.vm.stub("firewall-cmd")
        self.vm.stub("firewall-offline-cmd")
        # ssh-keygen et openssl créent les fichiers demandés, comme les
        # vrais : c'est ce qui permet de vérifier leurs droits.
        self.vm.stub(
            "ssh-keygen",
            'while [ $# -gt 0 ]; do [ "$1" = -f ] && { touch "$2"; '
            "break; }; shift; done",
        )
        self.vm.stub(
            "openssl",
            'while [ $# -gt 0 ]; do case "$1" in -keyout|-out) touch "$2"; '
            "shift;; esac; shift; done",
        )
        self.compte = subprocess.run(
            ["id", "-un"], capture_output=True, text=True
        ).stdout.strip()

    def _krdp_unit(self):
        unite = self.vm.etc("/usr/lib/systemd/user") / (
            "app-org.kde.krdpserver.service"
        )
        unite.parent.mkdir(parents=True, exist_ok=True)
        unite.write_text("[Service]\nExecStart=krdpserver\n")
        return unite

    def _plasma(self, distro, version, pm):
        self.vm.stub(pm)
        self._krdp_unit()
        rc, out, log = self.vm.run(
            _cmd("plasma", distro=distro, version=version), distro
        )
        self.assertEqual(0, rc, out)
        return out, log

    # --- KRdp ----------------------------------------------------------- #

    def test_krdp_authenticates_the_session_account_with_pam(self):
        out, log = self._plasma("fedora", "44", "dnf")
        rc = (self.vm.home / ".config/krdpserverrc").read_text()
        self.assertIn("SystemUserEnabled=true", rc)
        self.assertIn("ListenPort=3389", rc)
        self.assertNotIn("Users=", rc)
        cle = self.vm.home / ".local/share/krdpserver/krdp.key"
        self.assertIn(f"CertificateKey={cle}", rc)
        self.assertEqual(0o600, cle.stat().st_mode & 0o777)
        self.assertIn("RDP 3389 (KRdp", out)
        self.assertIn("firewall-cmd --permanent --add-service=rdp", log)

    def test_krdp_is_enabled_for_the_account_only_without_h264(self):
        self._plasma("arch", "latest", "pacman")
        uu = self.vm.home / ".config/systemd/user"
        lien = (
            uu / "plasma-workspace.target.wants/app-org.kde.krdpserver.service"
        )
        self.assertTrue(lien.is_symlink())
        self.assertIn(
            "Environment=KRDP_DISABLE_H264=1",
            (
                uu / "app-org.kde.krdpserver.service.d/erplibre.conf"
            ).read_text(),
        )

    def test_krdp_pre_authorises_its_portal(self):
        _out, log = self._plasma("fedora", "45", "dnf")
        self.assertIn(
            "busctl --user call org.freedesktop.impl.portal.PermissionStore "
            "/org/freedesktop/impl/portal/PermissionStore "
            "org.freedesktop.impl.portal.PermissionStore SetPermission sbssas "
            "kde-authorized true remote-desktop org.kde.krdpserver 1 yes",
            log,
        )

    def test_the_session_opens_by_itself_then_locks(self):
        """Autologin dans le gestionnaire d'affichage de la distribution,
        verrou au démarrage de la session."""
        for distro, version, pm, dm in (
            ("fedora", "44", "dnf", "plasmalogin"),
            ("opensuse", "tumbleweed", "zypper", "sddm"),
        ):
            with self.subTest(distro):
                self.setUp()
                self._plasma(distro, version, pm)
                conf = self.vm.etc(f"/etc/{dm}.conf.d") / (
                    "erplibre-autologin.conf"
                )
                self.assertEqual(
                    f"[Autologin]\nUser={self.compte}\n"
                    "Session=plasma.desktop\n",
                    conf.read_text(),
                )
                verrou = (
                    self.vm.home / ".config/autostart/erplibre-lock.desktop"
                )
                self.assertIn("Exec=loginctl lock-session", verrou.read_text())

    def test_krdp_writes_no_password_anywhere(self):
        self._plasma("fedora", "44", "dnf")
        for f in self.vm.home.rglob("*"):
            if f.is_file():
                self.assertNotIn(SONDE, f.read_text(errors="ignore"), f)
        self.assertNotIn(SONDE, " ".join(self.vm.journal()))

    def test_a_rerun_keeps_an_edited_krdp_config(self):
        rc = self.vm.home / ".config/krdpserverrc"
        rc.parent.mkdir(parents=True)
        rc.write_text("[General]\nListenPort=3390\n")
        self._plasma("arch", "latest", "pacman")
        self.assertEqual("[General]\nListenPort=3390\n", rc.read_text())

    def test_a_missing_krdp_unit_only_warns(self):
        self.vm.stub("dnf")
        rc, out, _log = self.vm.run(
            _cmd("plasma", distro="fedora", version="44"), "fedora"
        )
        self.assertEqual(0, rc, out)
        self.assertIn(
            t("krdpserver user unit not found; KRdp not enabled"), out
        )

    def test_ubuntu_plasma_goes_through_xrdp_on_x11(self):
        self.vm.stub(
            "apt-get",
            f'case " $* " in *" xrdp "*) printf "#!/bin/bash\\nexit 0\\n" '
            f"> {self.vm.bin}/xrdp; chmod +x {self.vm.bin}/xrdp;; esac",
        )
        rc, out, log = self.vm.run(
            _cmd("plasma", distro="ubuntu", version="26.04")
        )
        self.assertEqual(0, rc, out)
        ligne = log[_indice(log, "install -y kde-plasma-desktop")]
        self.assertIn("plasma-session-x11 kwin-x11", ligne)
        self.assertIn(" xrdp", ligne)
        self.assertIn(
            "exec startplasma-x11", (self.vm.home / ".xsession").read_text()
        )
        self.assertFalse((self.vm.home / ".config/krdpserverrc").exists())
        self.assertIn("systemctl enable --now xrdp", log)

    # --- wayvnc --------------------------------------------------------- #

    def _hyprland(self, distro, version, pm):
        self.vm.stub(pm)
        self.vm.stub("start-hyprland")
        gc = self.vm.etc("/etc/greetd/config.toml")
        gc.parent.mkdir(parents=True, exist_ok=True)
        gc.write_text(
            '[terminal]\nvt = 1\n[default_session]\nuser = "greeter"\n'
        )
        rc, out, log = self.vm.run(
            _cmd("hyprland", distro=distro, version=version)
        )
        self.assertEqual(0, rc, out)
        return out, log, gc.read_text()

    def test_wayvnc_authenticates_through_its_own_pam_service(self):
        out, log, _gc = self._hyprland("arch", "latest", "pacman")
        self.assertEqual(
            "auth    required pam_unix.so\naccount required pam_unix.so\n",
            self.vm.etc("/etc/pam.d/wayvnc").read_text(),
        )
        w = self.vm.home / ".config/wayvnc"
        conf = (w / "config").read_text()
        for cle in (
            "enable_auth=true",
            "enable_pam=true",
            "address=0.0.0.0",
            "port=5900",
            "rsa_private_key_file=rsa_key.pem",
        ):
            self.assertIn(cle, conf)
        for nom in ("config", "rsa_key.pem", "tls_key.pem"):
            self.assertEqual(0o600, (w / nom).stat().st_mode & 0o777, nom)
        self.assertEqual(0o700, w.stat().st_mode & 0o777)
        self.assertIn("VNC 5900 (wayvnc", out)
        self.assertIn("firewall-cmd --permanent --add-service=vnc-server", log)

    def test_hyprland_opens_by_itself_locks_and_starts_wayvnc(self):
        _out, _log, gc = self._hyprland("arch", "latest", "pacman")
        self.assertIn(
            f'[initial_session]\ncommand = "start-hyprland"\n'
            f'user = "{self.compte}"',
            gc,
        )
        self.assertIn('user = "greeter"', gc)
        lua = (self.vm.home / ".config/hypr/hyprland.lua").read_text()
        self.assertLess(lua.index('"hyprlock"'), lua.index("wayvnc.service"))
        self.assertNotIn("--immediate", lua)
        unite = self.vm.home / ".config/systemd/user/wayvnc.service"
        self.assertIn("ExecStart=/usr/bin/wayvnc", unite.read_text())
        self.assertTrue((self.vm.home / ".config/hypr/hyprlock.conf").exists())

    def test_hyprlang_config_also_locks_and_starts_wayvnc(self):
        self._hyprland("ubuntu", "26.04", "apt-get")
        conf = (self.vm.home / ".config/hypr/hyprland.conf").read_text()
        self.assertIn("exec-once = hyprlock\n", conf)
        self.assertIn("systemctl --user start wayvnc.service", conf)

    # --- sessions X ----------------------------------------------------- #

    def test_xrdp_opens_the_flavour_session(self):
        self.vm.stub("dnf")
        rc, out, _log = self.vm.run(
            _cmd("xfce", distro="fedora", version="44"), "fedora"
        )
        self.assertEqual(0, rc, out)
        for nom in (".xsession", ".Xclients"):
            f = self.vm.home / nom
            self.assertEqual("#!/bin/sh\nexec startxfce4\n", f.read_text())
            self.assertTrue(f.stat().st_mode & 0o100, nom)

    def test_tigervnc_on_arch_names_the_flavour_session(self):
        self.vm.stub("pacman")
        rc, out, _log = self.vm.run(
            _cmd("i3", distro="arch", version="latest")
        )
        self.assertEqual(0, rc, out)
        self.assertEqual(
            "session=i3\n",
            (self.vm.home / ".config/tigervnc/config").read_text(),
        )

    def test_an_existing_xsession_is_kept(self):
        (self.vm.home / ".xsession").write_text("exec mien\n")
        self.vm.stub("apt-get")
        rc, out, _log = self.vm.run(_cmd("i3", distro="debian", version="13"))
        self.assertEqual(0, rc, out)
        self.assertEqual(
            "exec mien\n", (self.vm.home / ".xsession").read_text()
        )


if __name__ == "__main__":
    unittest.main()
