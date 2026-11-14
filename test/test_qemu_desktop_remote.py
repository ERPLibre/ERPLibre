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

from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

DISTROS = ("", "ubuntu", "debian", "fedora", "almalinux", "arch", "opensuse")


def _cmd(flavour="gnome", app_store="deb", distro=""):
    return TODO.__new__(TODO)._qemu_desktop_remote_cmd(
        flavour, app_store, distro=distro
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
        "cat",
        "chmod",
        "cut",
        "date",
        "dirname",
        "grep",
        "id",
        "mkdir",
        "sed",
        "sleep",
        "tail",
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
        for nom in self.REELS:
            vrai = shutil.which(nom)
            if vrai:
                (self.bin / nom).symlink_to(vrai)
        # sudo laisse tomber « -u <compte> » et exporte les « VAR=valeur »
        # qui précèdent la commande, comme le vrai.
        self.stub(
            "sudo",
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
        self.stub("systemctl")
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

    def grdctl(self, systeme=True, ignore=""):
        """grdctl : son aide nomme « --system » ou non.

        Comme le vrai en mode système, il rend 0 à TOUTES les sous-commandes,
        qu'il ait pris le réglage ou non. Il garde un état, que relit
        « status --show-credentials » avec les lignes du vrai :
        identifiants, chemin de la clé, état activé. `ignore` nomme la
        sous-commande qu'il rend 0 SANS l'appliquer (« set-credentials »,
        « set-tls-key », « enable »)."""
        aide = "--system   Configure system daemon" if systeme else "rdp"
        etat = self.tmp / "grd-etat"

        def pose(sous, action):
            return "true" if sous == ignore else action

        self.stub(
            "grdctl",
            f'E={etat}; touch "$E"\n'
            'case "$*" in\n'
            f'  --help) echo "  {aide}";;\n'
            '  "--system rdp set-credentials "*) '
            + pose("set-credentials", 'echo "user=$4" >> "$E"')
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
            '    s=disabled; grep -qx enabled "$E" && s=enabled\n'
            '    printf "RDP:\\n\\tStatus: %s\\n\\tTLS key: %s\\n'
            '\\tUsername: %s\\n" "$s" "${k:-(null)}" "${u:-(null)}";;\n'
            "esac\n"
            "exit 0",
        )

    def run(self, cmd, os_id=""):
        if os_id:
            release = self.tmp / "os-release"
            release.write_text(f"ID={os_id}\n")
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

    def test_the_old_call_is_unchanged(self):
        self.assertEqual(
            TODO._QEMU_APT_NO_SNAP, TODO._qemu_apt_store_pkgs("deb")
        )


class TestDesktopsForDistro(unittest.TestCase):
    def test_nixos_gets_none(self):
        self.assertEqual([], TODO._qemu_desktops_for("nixos"))

    def test_the_four_families_get_both(self):
        for distro in ("ubuntu", "debian", "fedora", "arch", "opensuse"):
            self.assertEqual(
                ["gnome", "cinnamon"], TODO._qemu_desktops_for(distro), distro
            )

    def test_an_unknown_distro_gets_all(self):
        self.assertEqual(
            list(TODO._QEMU_DESKTOP), TODO._qemu_desktops_for("inconnue")
        )


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
        self.assertIn("erplibre", out)
        self.assertTrue(
            (self.vm.home / ".config/gnome-initial-setup-done").exists()
        )

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

    def test_the_credentials_go_as_arguments(self):
        """La forme en arguments, la seule qu'un pipe ne perd pas, puis la
        relecture de l'état par « status --show-credentials »."""
        self.vm.stub("dnf")
        self.vm.grdctl()
        rc, out, log = self.vm.run(_cmd("gnome"), "fedora")
        self.assertEqual(0, rc, out)
        self.assertIn(
            f"grdctl --system rdp set-credentials {self._user()} erplibre",
            log,
        )
        self.assertNotIn("grdctl --system rdp set-credentials", log)
        self.assertGreater(
            _indice(log, "grdctl --system status --show-credentials"),
            _indice(log, "grdctl --system rdp enable"),
        )
        self.assertIn("RDP 3389 (GNOME Remote Desktop)", out)

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


if __name__ == "__main__":
    unittest.main()
